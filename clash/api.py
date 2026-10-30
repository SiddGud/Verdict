"""HTTP routes for the Clash Court page. The server holds each visitor's timetable and is the only source of truth:
every reply carries the full state and a version number, and the page redraws from it."""
import glob
import json
import os
import queue
import threading
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from clash import agents as ag
from clash import ask as ak
from clash import guard
from clash import baseline as bl
from clash import fanroute as fr
from clash import overlap as ov
from clash import schedule as sc

router = APIRouter()
ag.MODEL_OK = lambda: not guard.over_budget()  # the booker's model fallback stops at the daily cap
FESTIVALS = os.path.join(os.path.dirname(__file__), "festivals")
SESSIONS, LOCK = {}, threading.Lock()
MAX_SESSIONS = 500


def _festival(slug):
    path = os.path.join(FESTIVALS, f"{slug}.json")
    if not os.path.exists(path):
        raise HTTPException(404, "unknown festival")
    fest = ov.load(path)
    t = ov.table(fest)
    return fest, t, ov.weights(t)


def _state(s, feed=None, rule=None):
    fest, t, w, pos = s["fest"], s["table"], s["w"], s["pos"]
    h = sc._hours(fest)
    at = {i: a for a, i in pos.items()}
    sets = []
    for i, c in enumerate(fest["cells"]):
        a = at.get(i)
        others = sorted(((w.get(a, {}).get(b, 0.0), b, round(h[i][j] * 60)) for b, j in pos.items() if a and b != a and h[i][j]),
                        reverse=True)
        sets.append({"cell": i, "stage": c["stage"], "start": c["start"], "end": c["end"], "act": a,
                     "matched": bool(a) and (a in t["matched"] or a in t.get("lastfm", {})),
                     "source": "qloo" if a in t["matched"] else "lastfm" if a in t.get("lastfm", {}) else None,
                     "clashes": [{"act": b, "weight": x, "minutes": m} for x, b, m in others if x >= 0.2]})
    pub = sc.published(fest)
    return {"session": s["id"], "version": s["version"], "festival": {"slug": fest["slug"], "name": fest["name"],
            "note": fest.get("note", ""), "stages": fest["stages"], "day": fest["day"],
            "examples": fest.get("examples", [])},
            "sets": sets, "score": sc.clash_score(pos, w, fest), "published_score": sc.clash_score(pub, w, fest),
            "worst": [{"weight": wt, "acts": [a, b], "minutes": m,
                       "from": ov.clock(max(fest["cells"][pos[a]]["start"], fest["cells"][pos[b]]["start"]))}
                      for x, wt, a, b, m in sc.worst(pos, w, fest, 5)],
            "rules": [{**r, "reads_as": ag.describe(r, fest)} for r in s["rules"]],
            "unmatched": [a for a in fest["acts"] if a not in t["matched"] and a not in t.get("lastfm", {})],
            "from_lastfm": [a for a in fest["acts"] if a in t.get("lastfm", {})],
            "fan_demand": _demand(s),
            "feed": feed or [], "cases": s.get("cases", []) if feed else [], "rule": rule}


def _demand(s):
    """Pairs that fans' routes forced them to choose between on the current timetable, most fans first."""
    count = {}
    for picks in s.get("fans", []):
        for k, (a, b) in picks.items():
            if a in s["pos"] and b in s["pos"] and sc._hours(s["fest"])[s["pos"][a]][s["pos"][b]]:
                count[(a, b)] = count.get((a, b), 0) + 1
    return [{"acts": list(p), "fans": n} for p, n in sorted(count.items(), key=lambda x: -x[1])[:5]]


def _session(sid):
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "session expired; reload the page")
    return s


class Load(BaseModel):
    festival: str = Field("testbill", max_length=60, pattern=r"^[a-z0-9_-]+$")


class Command(BaseModel):
    session: str = Field(max_length=40)
    text: str = Field(min_length=1, max_length=300)


class Session(BaseModel):
    session: str = Field(max_length=40)


ORDER = ["lolla2024thu", "lolla2026sun", "lolla2026thu", "lolla2026fri", "lolla2026sat"]  # the first one opens by default


@router.get("/api/clash/festivals")
def festivals():
    slugs = [os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(FESTIVALS, "*.json"))]
    slugs.sort(key=lambda x: (ORDER.index(x) if x in ORDER else len(ORDER), x))
    return [{"slug": x, "name": ov.load(os.path.join(FESTIVALS, f"{x}.json"))["name"]} for x in slugs]


@router.post("/api/clash/load")
def load(req: Load):
    fest, t, w = _festival(req.festival)
    s = {"id": uuid.uuid4().hex[:16], "version": 0, "fest": fest, "table": t, "w": w, "pos": sc.published(fest), "rules": [],
         "fans": []}
    with LOCK:
        if len(SESSIONS) >= MAX_SESSIONS:
            SESSIONS.pop(next(iter(SESSIONS)))
        SESSIONS[s["id"]] = s
    return _state(s)


def _apply(s):
    """Re-plan from the published timetable with every rule so far, as the war-room would."""
    base = sc.published(s["fest"])
    w = {a: dict(row) for a, row in s["w"].items()}
    reported = {}
    for picks in s.get("fans", []):  # each fan who had to choose between two acts adds weight to that pair
        for a, b in picks.values():
            reported[(a, b)] = reported.get((a, b), 0) + 1
    for (a, b), n in reported.items():
        if a in w and b in w[a]:
            w[a][b] = w[b][a] = min(1.0, w[a][b] + 0.1 * n)
    new, feed = ag.run(base, s["fest"], w, s["rules"])
    gone = {r["act"] for r in s["rules"] if r["type"] == "cancel"}
    s["cases"] = ag.court({a: i for a, i in base.items() if a not in gone}, new, s["fest"], w,
                          [r for r in s["rules"] if r["type"] != "cancel"])
    if reported:
        feed.insert(0, {"who": "booker", "text": f"{sum(reported.values())} fan route clash reports are counted as "
                        "extra weight on those pairs."})
    s["pos"], s["version"] = new, s["version"] + 1
    return feed


@router.post("/api/clash/run")
def run(req: Session):
    s = _session(req.session)
    with LOCK:
        feed = _apply(s)
    return _state(s, feed)


@router.post("/api/clash/command")
def command(req: Command, request: Request):
    s = _session(req.session)
    why = guard.admit(guard.visitor(request), "command")
    if why:
        return {**_state(s), "error": why}
    rule = ag.parse(req.text, s["fest"])
    if "error" in rule:
        return {**_state(s), "error": rule["error"]}
    with LOCK:
        s["rules"].append(rule)
        feed = _apply(s)
    return _state(s, feed, {**rule, "reads_as": ag.describe(rule, s["fest"])})


@router.post("/api/clash/reset")
def reset(req: Session):
    s = _session(req.session)
    with LOCK:
        s["pos"], s["rules"], s["version"] = sc.published(s["fest"]), [], s["version"] + 1
    return _state(s)


class Route(BaseModel):
    session: str = Field(max_length=40)
    favourites: list[str] = Field(min_length=1, max_length=5)


@router.post("/api/clash/route")
def route(req: Route):
    s = _session(req.session)
    favs = [f.strip()[:60] for f in req.favourites if f.strip()]
    r = fr.route(s["fest"], s["pos"], favs)
    if "error" not in r:
        with LOCK:
            s["fans"].append({h["start"]: (h["act"], h["clash_with"]["act"]) for h in r["sets"] if h["clash_with"]})
            s["version"] += 1
    return {**r, "state": _state(s)}


BASELINE = {}


@router.get("/api/clash/baseline")
def baseline(festival: str = "testbill"):
    if not festival.replace("-", "").replace("_", "").isalnum() or not os.path.exists(os.path.join(FESTIVALS, f"{festival}.json")):
        raise HTTPException(404, "unknown festival")
    if BASELINE.get(festival) is None:
        BASELINE[festival] = bl.summary(ov.load(os.path.join(FESTIVALS, f"{festival}.json")))
    return {"summary": BASELINE[festival]}


class Ask(BaseModel):
    session: str = Field(max_length=40)
    question: str = Field(min_length=2, max_length=300)
    history: list[dict] = Field(default_factory=list, max_length=8)


@router.post("/api/clash/ask")
def ask(req: Ask, request: Request):
    """Ask the court: streams the agent's tool calls and answer as server-sent events. A booker order the agent
    issues changes this session's timetable, and the new state is streamed so the page can replay the court."""
    s = _session(req.session)
    why = guard.admit(guard.visitor(request), "ask", model=True)
    if why:
        return JSONResponse({"error": why}, status_code=429)
    events = queue.Queue()
    history = [{"q": str(h.get("q", ""))[:300], "a": str(h.get("a", ""))[:800]} for h in req.history if isinstance(h, dict)]

    def apply_order(text):
        rule = ag.parse(str(text)[:300], s["fest"])
        if "error" in rule:
            return {"error": rule["error"]}
        with LOCK:
            s["rules"].append(rule)
            feed = _apply(s)
        st = _state(s, feed, {**rule, "reads_as": ag.describe(rule, s["fest"])})
        events.put({"type": "state", "state": st})
        return {"reads_as": st["rule"]["reads_as"], "clash_score_published": round(st["published_score"], 2),
                "clash_score_now": round(st["score"], 2),
                "court_cases": [{"acts": c["acts"], "ruling": c["ruling"]} for c in st["cases"]]}

    def work():
        try:
            ak.ask(req.question, history, s, apply_order, events.put)
        except Exception as e:  # noqa: BLE001 - the page shows the reason; the server keeps running
            events.put({"type": "error", "message": f"The agent could not answer: {str(e)[:160]}"})
        events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while True:
            e = events.get()
            if e is None:
                break
            yield "data: " + json.dumps(e) + "\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
