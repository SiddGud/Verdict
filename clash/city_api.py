"""Web endpoints for the city tools: book a date, a promoter's portfolio, friends' month, openers and tour dates.
Answers are kept in memory by their inputs, so a repeated question costs no Qloo, Ticketmaster or model call."""
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from clash import booking as bk
from clash import city as ct

router = APIRouter()
MONTHS = {"2026-11": ("2026-11-01", "2026-11-30", "November 2026"), "2026-12": ("2026-12-01", "2026-12-31", "December 2026")}
MEMO, LOCK = {}, threading.Lock()
NAME = Field(min_length=1, max_length=60)


def _memo(key, fn):
    with LOCK:
        if key in MEMO:
            return MEMO[key]
    try:
        out = fn()
    except Exception as e:  # a provider failing should read as a message, not a crash
        return {"error": f"Something went wrong upstream: {str(e)[:160]}"}
    with LOCK:
        if len(MEMO) > 2000:
            MEMO.pop(next(iter(MEMO)))
        MEMO[key] = out
    return out


def _window(city, month):
    if city not in ct.CITIES:
        raise HTTPException(404, "unknown city")
    if month not in MONTHS:
        raise HTTPException(404, "unknown month")
    return MONTHS[month][:2]


@router.get("/api/city/options")
def options():
    return {"cities": [{"slug": k, "name": v[0]} for k, v in ct.CITIES.items()],
            "months": [{"key": k, "name": v[2]} for k, v in MONTHS.items()]}


class Plan(BaseModel):
    city: str = Field(max_length=30)
    month: str = Field(max_length=7)
    artist: str = NAME
    weekends: bool = False


@router.post("/api/city/plan")
def plan(req: Plan):
    a, b = _window(req.city, req.month)
    return _memo(("plan", req.city, req.month, req.artist.lower(), req.weekends),
                 lambda: ct.plan(req.city, req.artist.strip(), a, b, req.weekends))


@router.get("/api/city/promoters")
def promoters(city: str, month: str):
    a, b = _window(city, month)
    return {"promoters": [{"name": n, "shows": c} for n, c in _memo(("promoters", city, month),
                                                                     lambda: ct.promoters(city, a, b))]}


class Portfolio(BaseModel):
    city: str = Field(max_length=30)
    month: str = Field(max_length=7)
    promoter: str = Field(min_length=1, max_length=80)


@router.post("/api/city/portfolio")
def portfolio(req: Portfolio):
    a, b = _window(req.city, req.month)
    return _memo(("portfolio", req.city, req.month, req.promoter.lower()),
                 lambda: ct.portfolio(req.city, req.promoter, a, b))


class Friends(BaseModel):
    city: str = Field(max_length=30)
    month: str = Field(max_length=7)
    people: dict[str, list[str]] = Field(min_length=1, max_length=6)


@router.post("/api/city/friends")
def friends(req: Friends):
    a, b = _window(req.city, req.month)
    people = {k.strip()[:30]: [x.strip()[:60] for x in v if x.strip()][:5] for k, v in req.people.items() if k.strip()}
    people = {k: v for k, v in people.items() if v}
    if not people:
        raise HTTPException(422, "name at least one person and one artist")
    key = ("friends", req.city, req.month, tuple(sorted((k, tuple(v)) for k, v in people.items())))
    return _memo(key, lambda: ct.friends(req.city, people, a, b))


class Support(BaseModel):
    headliner: str = NAME


@router.post("/api/city/support")
def support(req: Support):
    return _memo(("support", req.headliner.lower()), lambda: bk.support(req.headliner.strip()))


class Tour(BaseModel):
    artist: str = NAME
    cities: list[str] = Field(min_length=2, max_length=8)
    month: str = Field(max_length=7)


@router.post("/api/city/tour")
def tour(req: Tour):
    if req.month not in MONTHS:
        raise HTTPException(404, "unknown month")
    a, b = MONTHS[req.month][:2]
    return _memo(("tour", req.artist.lower(), tuple(req.cities), req.month),
                 lambda: bk.tour(req.artist.strip(), req.cities, a, b))
