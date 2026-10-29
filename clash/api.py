"""HTTP routes for the Clash Court page. The server holds each visitor's timetable and is the only source of truth:
every reply carries the full state and a version number, and the page redraws from it."""
import glob
import os
import threading
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from clash import agents as ag
from clash import baseline as bl
from clash import fanroute as fr
from clash import overlap as ov
from clash import schedule as sc

router = APIRouter()
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
            "feed": feed or [], "rule": rule}


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
def command(req: Command):
    s = _session(req.session)
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
