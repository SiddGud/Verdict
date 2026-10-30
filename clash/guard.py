"""Limits for a public page: per-visitor hourly counts by kind of request, and a daily cap on model spend.

The page is open to anyone (judges get no login), so every call that can reach a paid model or many Qloo lookups
passes admit() first. When the day's model spend reaches DAILY_USD, model calls stop until the next day; tools that
need no model keep working.
"""
import datetime
import os
import threading
import time

import llm

DAILY_USD = float(os.environ.get("DAILY_USD") or llm.ENV.get("DAILY_USD") or 5)
PER_HOUR = {"ask": int(os.environ.get("ASKS_PER_HOUR") or 20), "model": int(os.environ.get("MODEL_PER_HOUR") or 10),
            "command": int(os.environ.get("COMMANDS_PER_HOUR") or 40), "lookup": int(os.environ.get("LOOKUPS_PER_HOUR") or 60)}
_lock = threading.Lock()
_hits = {}
_day = {"date": datetime.date.today(), "start": llm.SPEND["usd"]}


def spent_today():
    """Model spend since midnight (server time), in US dollars, from token usage."""
    with _lock:
        if datetime.date.today() != _day["date"]:
            _day.update(date=datetime.date.today(), start=llm.SPEND["usd"])
        return llm.SPEND["usd"] - _day["start"]


def over_budget():
    return spent_today() >= DAILY_USD


def visitor(request):
    """The visitor's address; behind a proxy (Render), the first address in X-Forwarded-For."""
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def admit(ip, kind, model=False):
    """None if the request may go ahead, else a plain reason to show the visitor."""
    if model and over_budget():
        return "Today's model budget for the public demo is used up; it resets at midnight. Every tool without a model still works."
    now = time.time()
    with _lock:
        hits = [t for t in _hits.get((ip, kind), []) if now - t < 3600]
        if len(hits) >= PER_HOUR[kind]:
            _hits[(ip, kind)] = hits
            return f"That is {PER_HOUR[kind]} of these in the last hour from your address; please try again later."
        hits.append(now)
        _hits[(ip, kind)] = hits
        if len(_hits) > 20000:  # keep memory bounded on a public server
            for k in list(_hits)[:10000]:
                _hits.pop(k, None)
    return None
