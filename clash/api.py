"""HTTP routes for the Clash Court page. The server holds each visitor's timetable and is the only source of truth:
every reply carries the full state and a version number, and the page redraws from it."""
import glob
import os
import threading
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from clash import agents as ag
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
    grid = [[None] * len(fest["slots"]) for _ in fest["stages"]]
    for a, (st, k) in pos.items():
        others = sorted(((w.get(a, {}).get(b, 0.0), b) for b, (_, k2) in pos.items() if b != a and k2 == k), reverse=True)
        grid[st][k] = {"act": a, "matched": a in t["matched"], "clashes": [{"act": b, "weight": x} for x, b in others if x >= 0.2]}
    pub = sc.published(fest)
    return {"session": s["id"], "version": s["version"], "festival": {"slug": fest["slug"], "name": fest["name"],
            "note": fest.get("note", ""), "stages": fest["stages"], "slots": fest["slots"]},
            "grid": grid, "score": sc.clash_score(pos, w), "published_score": sc.clash_score(pub, w),
            "worst": [{"weight": x, "acts": [a, b], "slot": fest["slots"][k]} for x, a, b, k in sc.worst(pos, w, 5)],
            "rules": [{**r, "reads_as": ag.describe(r, fest)} for r in s["rules"]],
            "unmatched": [a for a in fest["acts"] if a not in t["matched"]],
            "feed": feed or [], "rule": rule}


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


@router.get("/api/clash/festivals")
def festivals():
    return [{"slug": os.path.splitext(os.path.basename(p))[0], "name": ov.load(p)["name"]}
            for p in sorted(glob.glob(os.path.join(FESTIVALS, "*.json")))]


@router.post("/api/clash/load")
def load(req: Load):
    fest, t, w = _festival(req.festival)
    s = {"id": uuid.uuid4().hex[:16], "version": 0, "fest": fest, "table": t, "w": w, "pos": sc.published(fest), "rules": []}
    with LOCK:
        if len(SESSIONS) >= MAX_SESSIONS:
            SESSIONS.pop(next(iter(SESSIONS)))
        SESSIONS[s["id"]] = s
    return _state(s)


def _apply(s):
    """Re-plan from the published timetable with every rule so far, as the war-room would."""
    base = sc.published(s["fest"])
    new, feed = ag.run(base, s["fest"], s["w"], s["rules"])
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
