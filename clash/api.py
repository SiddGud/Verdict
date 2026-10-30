"""HTTP routes for the Clash Court page. The server holds each visitor's timetable and is the only source of truth:
every reply carries the full state and a version number, and the page redraws from it."""
import glob
import json
import os
import queue
import threading
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from clash import agents as ag
from clash import ask as ak
from clash import guard
from clash import lineup as lu
from clash import baseline as bl
from clash import fanroute as fr
from clash import overlap as ov
from clash import schedule as sc

router = APIRouter()
ag.MODEL_OK = lambda: not guard.over_budget()  # the booker's model fallback stops at the daily cap
FESTIVALS = os.path.join(os.path.dirname(__file__), "festivals")
SESSIONS, LOCK = {}, threading.Lock()
PHOTOS = {}  # festival -> {act: Qloo image URL}
MAX_SESSIONS = 500


def _festival(slug):
    path = lu.path(slug) if slug.startswith("custom-") else os.path.join(FESTIVALS, f"{slug}.json")
    if not os.path.exists(path):
        raise HTTPException(404, "unknown festival")
    fest = ov.load(path)
    t = ov.table(fest)
    if slug not in PHOTOS:
        PHOTOS[slug] = ov.photos(fest)
    fest["photos"] = PHOTOS[slug]
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
            "examples": fest.get("examples", []), "photos": fest.get("photos", {})},
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
    return {**_state(s), "weights": {a: {b: round(x, 3) for b, x in row.items() if x >= 0.2} for a, row in w.items()}}


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
        s["undo"] = []
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


ABOUT = {}  # festival -> {act: Qloo's short description}


@router.get("/api/clash/graph")
def graph(session: str = Query(max_length=40), top: int = 3):
    """The bill as a fan-overlap graph: each act linked to its closest acts on the bill (Qloo, or Last.fm where Qloo
    has no data), and whether each linked pair overlaps in time as published and on the session's timetable now."""
    s = _session(session)
    fest, w, pos, t = s["fest"], s["w"], s["pos"], s["table"]
    slug, h, pub = fest["slug"], sc._hours(fest), sc.published(fest)
    if slug not in ABOUT:
        alias = fest.get("qloo_names", {})
        ABOUT[slug] = {a: (ov.resolve(alias.get(a, a)) or {}).get("about") for a in t["matched"]}
    top = max(1, min(top, 5))
    links, seen = [], set()
    for a in fest["acts"]:
        for x, b in sorted(((x, b) for b, x in w.get(a, {}).items()), reverse=True)[:top]:
            key = tuple(sorted((a, b)))
            if x < 0.3 or key in seen:
                continue
            seen.add(key)
            links.append({"source": a, "target": b, "weight": round(x, 3),
                          "clash_published": round(h[pub[a]][pub[b]] * 60),
                          "clash_now": round(h[pos[a]][pos[b]] * 60) if a in pos and b in pos else 0})
    src = lambda a: "qloo" if a in t["matched"] else "lastfm" if a in t.get("lastfm", {}) else None  # noqa: E731
    nodes = [{"id": a, "stage": fest["cells"][pub[a]]["stage"], "photo": fest.get("photos", {}).get(a),
              "source": src(a), "about": ABOUT[slug].get(a), "cancelled": a not in pos} for a in fest["acts"]]
    return {"stages": fest["stages"], "nodes": nodes, "links": links,
            "court_has_sat": s["version"] > 0 and pos != pub}



class Move(BaseModel):
    session: str = Field(max_length=40)
    act: str = Field(min_length=1, max_length=120)
    cell: int = Field(ge=0, le=500)


def _placed(fest, act, cell):
    """The rules that keep an act where the booker put it: its stage and its start time."""
    c = fest["cells"][cell]
    return [{"type": "on_stage", "act": act, "stage": c["stage"], "placed": True},
            {"type": "at_time", "act": act, "time": c["start"], "placed": True}]


@router.post("/api/clash/move")
def move(req: Move, request: Request):
    """The booker drags a set to another slot: the two sets swap, the day is re-scored, and the act is pinned there so
    the court plans around it. A move that breaks a house rule is kept (the booker decides) and the reasons are listed."""
    s = _session(req.session)
    why = guard.admit(guard.visitor(request), "command")
    if why:
        return {**_state(s), "error": why}
    fest = s["fest"]
    if req.act not in s["pos"] or req.cell >= len(fest["cells"]):
        raise HTTPException(422, "unknown act or slot")
    with LOCK:
        pos = dict(s["pos"])
        at = {i: a for a, i in pos.items()}
        old, other = pos[req.act], at.get(req.cell)
        if old == req.cell:
            return {**_state(s), "moved": None}
        s.setdefault("undo", []).append((dict(s["pos"]), list(s["rules"])))
        s["undo"] = s["undo"][-30:]
        pos[req.act] = req.cell
        if other:
            pos[other] = old
        rules = [r for r in s["rules"] if not (r.get("placed") and r.get("act") in (req.act, other))]
        rules += _placed(fest, req.act, req.cell)
        if other:  # the act it swapped with is placed too: the booker moved it as much as the first
            rules += _placed(fest, other, old)
        s["pos"], s["rules"], s["version"] = pos, rules, s["version"] + 1
    extra = [r for r in s["rules"] if r["type"] != "cancel" and not r.get("placed")]
    broken = sc.violations(s["pos"], fest, extra)
    return {**_state(s), "moved": {"act": req.act, "to": sc.where(fest, req.cell), "swapped": other,
                                   "swapped_to": sc.where(fest, old) if other else None}, "broken": broken}


@router.post("/api/clash/undo")
def undo(req: Session):
    s = _session(req.session)
    with LOCK:
        if not s.get("undo"):
            return {**_state(s), "error": "Nothing to undo."}
        s["pos"], s["rules"] = s["undo"].pop()
        s["version"] += 1
    extra = [r for r in s["rules"] if r["type"] != "cancel" and not r.get("placed")]
    return {**_state(s), "broken": sc.violations(s["pos"], s["fest"], extra), "undone": True}


class Council(BaseModel):
    session: str = Field(max_length=40)
    live: bool = False


def _council_summary_text(m):
    return (f"The agents decided {m['decided']} moves: clash score {m['start']:.2f} to {m['after_cases']:.2f}. The optimiser "
            f"then tidied the rest of the day with those moves pinned: {m['final']:.2f}. The optimiser alone reaches "
            f"{m['optimiser_alone']:.2f}." + (" Every rule kept." if not m["broken"] else " Rules broken: " + "; ".join(m["broken"][:2])))


@router.post("/api/clash/council")
def council(req: Council, request: Request):
    """The court as working agents (clash/council.py). On the timetable as published, a recorded sitting replays with
    no model calls; otherwise, or when asked to run live, the agents sit now and every event streams to the page."""
    from clash import council as cn
    s = _session(req.session)
    fest = s["fest"]
    rec = cn.recorded(fest["slug"]) if not req.live and not s["rules"] else None
    if rec:
        with LOCK:
            s["pos"], s["cases"], s["version"] = dict(rec["final"]), [], s["version"] + 1
        st = _state(s, [{"who": "referee", "text": _council_summary_text(rec["summary"])}])
        return {"recorded": rec["recorded"], "events": rec["events"], "summary": rec["summary"], "state": st}
    why = guard.admit(guard.visitor(request), "model", model=True)
    if why:
        return JSONResponse({"error": why}, status_code=429)
    gone = {r["act"] for r in s["rules"] if r["type"] == "cancel"}
    base = {a: i for a, i in sc.published(fest).items() if a not in gone}
    extra = [r for r in s["rules"] if r["type"] != "cancel"]
    events = queue.Queue()

    def work():
        try:
            final, summary = cn.sit(fest, s["w"], base, extra, events.put)
            with LOCK:
                s["pos"], s["cases"], s["version"] = final, [], s["version"] + 1
            events.put({"type": "final", "summary": summary,
                        "state": _state(s, [{"who": "referee", "text": _council_summary_text(summary)}])})
        except Exception as e:  # noqa: BLE001 - the page shows the reason; the server keeps running
            events.put({"type": "error", "message": f"The agents could not finish: {str(e)[:160]}"})
        events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while True:
            e = events.get()
            if e is None:
                break
            yield "data: " + json.dumps(e) + "\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})



class Lineup(BaseModel):
    name: str = Field("", max_length=80)
    text: str = Field(min_length=10, max_length=20000)


@router.post("/api/clash/lineup")
def lineup(req: Lineup, request: Request):
    """Bring your own lineup: checks the pasted sets, matches every act in Qloo (Last.fm where Qloo has none), scores
    the fan overlap, and streams progress. Ends with the new festival's slug, which /api/clash/load then opens."""
    try:
        fest = lu.parse(req.name, req.text)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    why = guard.admit(guard.visitor(request), "lineup")
    if why:
        return JSONResponse({"error": why}, status_code=429)
    slug = lu.save(fest)
    events = queue.Queue()

    def work():
        try:
            f = ov.load(lu.path(slug))
            acts = f["acts"]
            for i, a in enumerate(acts, 1):  # match first, one by one, so the page can show progress
                ov.resolve(a)
                if i % 3 == 0 or i == len(acts):
                    events.put({"type": "progress", "step": "Matching acts in Qloo", "done": i, "of": len(acts)})
            events.put({"type": "progress", "step": "Scoring how much every pair of acts shares fans", "done": 0, "of": 1})
            t = ov.table(f)
            events.put({"type": "done", "slug": slug, "name": f["name"], "acts": len(acts),
                        "in_qloo": len(t["matched"]), "from_lastfm": len(t.get("lastfm", {}))})
        except Exception as e:  # noqa: BLE001 - the page shows the reason
            events.put({"type": "error", "message": f"Could not build that day: {str(e)[:160]}"})
        events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while True:
            e = events.get()
            if e is None:
                break
            yield "data: " + json.dumps(e) + "\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
