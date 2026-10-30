"""Ask the court: questions in plain words, answered by a tool-using loop (the same pattern as the earlier project's
follow-ups). The model chooses which tools to call; code runs them on the session's timetable, Qloo's fan overlap
(Last.fm for acts Qloo lacks), Ticketmaster listings and the pre-registered Test 28. At most MAX_CALLS tool calls a
question. Every number in the answer is checked against the tool results; numbers found in none are flagged.

One tool changes the timetable (booker_order): the page then replays the court with the new rule.
"""
import json
import re
import time

import llm
from clash import agents as ag
from clash import city as ct
from clash import fanroute as fr
from clash import overlap as ov
from clash import schedule as sc

MAX_CALLS = 6
MONTHS = {"2026-11": ("2026-11-01", "2026-11-30"), "2026-12": ("2026-12-01", "2026-12-31")}

INSTRUCTIONS = (
    "You are the clerk of Clash Court, an agent that keeps acts who share fans from playing at the same time, and "
    "reads a city's month of shows for promoters and fans. Answer with the tools. Rules: take every number, act, venue "
    "and date from tool results, never from memory; fan overlap comes from Qloo (or Last.fm where Qloo has no data, "
    "say so when it matters); say plainly when the tools cannot answer. If the user asks to change the timetable (a "
    "cancellation, an arrival time, keeping two acts apart), call booker_order with their words. Keep answers under "
    "120 words, plain text, no markdown, no dashes used as punctuation. Cities: " + ", ".join(ct.CITIES) +
    ". Months: " + ", ".join(MONTHS) + "."
)


def _fn(name, desc, props, req):
    return {"type": "function", "name": name, "description": desc, "strict": True,
            "parameters": {"type": "object", "properties": props, "required": req, "additionalProperties": False}}


S, I = {"type": "string"}, {"type": "integer"}
CITY = {"type": "string", "enum": list(ct.CITIES)}
MONTH = {"type": "string", "enum": list(MONTHS)}
TOOLS = [
    _fn("timetable", "The festival day now: clash score now and as published, the worst clashes left, the booker's "
        "rules, and how many sets the court moved.", {}, []),
    _fn("where_is", "Where an act plays now and as published, and the court's cases that involved it.",
        {"act": S}, ["act"]),
    _fn("shares_fans_with", "The acts on this bill whose fans most overlap with an act's (Qloo, or Last.fm where "
        "Qloo has no data), with whether they overlap in time now.", {"act": S, "top": I}, ["act", "top"]),
    _fn("clash_between", "How much two acts on the bill share fans, and how long their sets overlap now and as "
        "published.", {"act": S, "other": S}, ["act", "other"]),
    _fn("booker_order", "Change the timetable with a booker's order in plain words (for example 'Tyla just "
        "cancelled', 'Kesha arrives at 4pm', 'keep Hozier and Lizzy McAlpine apart'); the court sits again.",
        {"order": S}, ["order"]),
    _fn("fan_route", "A fan's best path through this festival day from up to five favourite artists, with the "
        "clashes they cannot avoid.", {"favourites": {"type": "array", "items": S}}, ["favourites"]),
    _fn("city_plan", "For an artist, every night of a month in a city scored by how much the city's other shows "
        "pull on their fans (Ticketmaster listings, Qloo overlap): best and worst nights, rivals, partners.",
        {"city": CITY, "month": MONTH, "artist": S}, ["city", "month", "artist"]),
    _fn("promoter_portfolio", "One promoter's shows in a city and month: pairs that share fans on the same night, "
        "within a week, or further apart.", {"city": CITY, "month": MONTH, "promoter": S}, ["city", "month", "promoter"]),
    _fn("promoters", "Promoters named on a city's listings for a month, most shows first.",
        {"city": CITY, "month": MONTH}, ["city", "month"]),
    _fn("evidence", "Pre-registered Test 28: Qloo, popularity and language models judged on real listening data.",
        {}, []),
]


def _act(name, s):
    a = ag._act(name, s["fest"])
    if not a:
        raise ValueError(f"no act on this bill matches '{name}'")
    return a


def _minutes(s, a, b, pos):
    h = sc._hours(s["fest"])
    return round(h[pos[a]][pos[b]] * 60) if a in pos and b in pos else 0


def run_tool(name, args, s, apply_order):
    fest, w, pos, t = s["fest"], s["w"], s["pos"], s["table"]
    pub = sc.published(fest)
    source = lambda a: "qloo" if a in t["matched"] else "lastfm" if a in t.get("lastfm", {}) else "no data"  # noqa: E731
    if name == "timetable":
        return {"festival": fest["name"], "clash_score_now": round(sc.clash_score(pos, w, fest), 2),
                "clash_score_published": round(sc.clash_score(pub, w, fest), 2),
                "sets_moved_by_the_court": sum(1 for a in pos if pub.get(a) != pos[a]),
                "worst_clashes_now": [{"acts": [a, b], "weight": round(wt, 2), "minutes": m}
                                      for x, wt, a, b, m in sc.worst(pos, w, fest, 5)],
                "booker_rules": [ag.describe(r, fest) for r in s["rules"]]}
    if name == "where_is":
        a = _act(args["act"], s)
        return {"act": a, "fan_data": source(a), "published": sc.where(fest, pub[a]),
                "now": sc.where(fest, pos[a]) if a in pos else "cancelled",
                "court_cases": [{"acts": c["acts"], "ruling": c["ruling"]} for c in s.get("cases", []) if a in c["acts"]]}
    if name == "shares_fans_with":
        a = _act(args["act"], s)
        row = sorted(((x, b) for b, x in w.get(a, {}).items() if b in pos), reverse=True)[:max(1, min(args["top"], 10))]
        return {"act": a, "fan_data": source(a), "closest": [
            {"act": b, "rank_on_this_bill": i + 1, "weight": round(x, 2), "fan_data": source(b),
             "overlap_minutes_now": _minutes(s, a, b, pos)} for i, (x, b) in enumerate(row)]}
    if name == "clash_between":
        a, b = _act(args["act"], s), _act(args["other"], s)
        return {"acts": [a, b], "weight": round(w.get(a, {}).get(b, 0.0), 2),
                "rank_of_second_for_first": ag._rank(w, a, b) if b in w.get(a, {}) else None,
                "overlap_minutes_now": _minutes(s, a, b, pos), "overlap_minutes_published": _minutes(s, a, b, pub),
                "fan_data": [source(a), source(b)]}
    if name == "booker_order":
        return apply_order(args["order"])
    if name == "fan_route":
        r = fr.route(fest, pos, [x.strip()[:60] for x in args["favourites"][:5] if x.strip()])
        if "error" in r:
            return r
        return {"summary": r["summary"], "not_found": r["not_found"],
                "sets": [{"time": h["start"], "act": h["act"], "stage": h["stage"], "fit": h["fit"],
                          "must_choose_against": (h["clash_with"] or {}).get("act")} for h in r["sets"]]}
    if name == "city_plan":
        a, b = MONTHS[args["month"]]
        r = ct.plan(args["city"], args["artist"][:60], a, b)
        if "error" in r:
            return r
        by = {n["date"]: n for n in r["nights"]}
        night = lambda d: {"date": d, "weekday": by[d]["weekday"], "shows": by[d]["shows"],  # noqa: E731
                           "closest_rival": (by[d]["rivals"] or [{}])[0].get("act")}
        return {"artist": r["artist"], "city": r["city"], "shows_on_sale": r["shows"], "best_nights": [night(d) for d in r["best"]],
                "worst_nights": [night(d) for d in r["worst"]],
                "partners": [{"act": p["act"], "date": p["date"], "venue": p["venue"], "rank": p["rank"]} for p in r["partners"][:5]]}
    if name == "promoter_portfolio":
        a, b = MONTHS[args["month"]]
        r = ct.portfolio(args["city"], args["promoter"][:80], a, b)
        if "error" in r:
            return r
        return {"promoter": r["promoter"], "shows": r["shows"], "counts": r["counts"],
                "pairs": [{"kind": p["kind"], "shows": [f"{x['act']}, {x['date']}, {x['venue']}" for x in p["shows"]]}
                          for p in r["pairs"][:8]]}
    if name == "promoters":
        a, b = MONTHS[args["month"]]
        return {"promoters": [{"name": n, "shows": c} for n, c in ct.promoters(args["city"], a, b)[:8]]}
    if name == "evidence":
        return {"test": "Test 28, written down before any result: 10 bills of 30 real artists, judged on listeners "
                        "each pair truly shares (Last.fm)",
                "matches_real_fans": {"qloo": 0.72, "popularity": 0.39, "frontier_model": 0.70,
                                      "frontier_model_with_qloo": 0.73},
                "timetable_quality": {"qloo": 0.66, "popularity": 0.04, "frontier_model": 0.67,
                                      "frontier_model_with_qloo": 0.70},
                "readings": ["Qloo matches a frontier model and is far above popularity",
                             "adding Qloo moved both models' scores closer to real fans",
                             "timetables were not shown better than the model alone"]}
    raise ValueError(f"unknown tool {name}")


def _canon(x):
    return x.rstrip("0").rstrip(".") if "." in x else (x.lstrip("0") or "0")


def _numbers(text):
    return {_canon(x) for x in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))}


def _summary(name, out):
    if "error" in out:
        return out["error"]
    if name == "timetable":
        return f"clash score {out['clash_score_published']} published, {out['clash_score_now']} now"
    if name == "where_is":
        return f"{out['act']}: {out['published']} published, {out['now']} now"
    if name == "shares_fans_with":
        return f"closest to {out['act']}: " + ", ".join(x["act"] for x in out["closest"][:3])
    if name == "clash_between":
        return f"{out['acts'][0]} and {out['acts'][1]}: weight {out['weight']}, {out['overlap_minutes_now']} min overlap now"
    if name == "booker_order":
        return out.get("reads_as", "")
    if name == "fan_route":
        return out["summary"]
    if name == "city_plan":
        return f"{out['shows_on_sale']} shows in {out['city']}; best {', '.join(n['date'] for n in out['best_nights'])}"
    if name == "promoter_portfolio":
        return f"{out['promoter']}: {out['counts']}"
    if name == "promoters":
        return ", ".join(p["name"] for p in out["promoters"][:3])
    if name == "evidence":
        return "Test 28 results"
    return ""


def ask(question, history, s, apply_order, emit):
    """history: [{"q", "a"}] of earlier questions this session. emit(event) streams to the page."""
    inp = [{"role": "user", "content": "Festival day loaded: " + s["fest"]["name"]}]
    for h in history[-4:]:
        inp += [{"role": "user", "content": h["q"][:300]}, {"role": "assistant", "content": h["a"][:800]}]
    inp.append({"role": "user", "content": question})
    seen, calls = json.dumps(history[-4:]) + s["fest"]["name"], 0
    for turn in range(MAX_CALLS + 1):
        body = {"model": llm.MODEL, "instructions": INSTRUCTIONS, "input": inp, "tools": TOOLS,
                "tool_choice": "auto" if calls < MAX_CALLS else "none", "stream": False,
                "reasoning": {"effort": "low"}, "max_output_tokens": 1200}
        d = llm.hedged_response(body)
        fcs = [o for o in d.get("output", []) if o.get("type") == "function_call"]
        if not fcs:
            answer = llm._text(d).strip()
            if not answer:
                if turn == MAX_CALLS:
                    raise llm.LLMError("the model returned no answer")
                inp.append({"role": "user", "content": "Please answer the question now in plain text."})
                continue
            loose = sorted(_numbers(answer) - _numbers(seen) - _numbers(question), key=float)
            emit({"type": "answer", "text": answer, "unchecked_numbers": loose, "tool_calls": calls})
            return answer
        for fc in fcs:
            calls += 1
            try:
                args = json.loads(fc.get("arguments") or "{}")
            except ValueError:
                args = {}
            emit({"type": "tool", "status": "running", "name": fc["name"], "args": args, "n": calls})
            t0 = time.time()
            try:
                out = run_tool(fc["name"], args, s, apply_order)
            except Exception as e:  # noqa: BLE001 - a failed tool is reported to the model, not raised
                out = {"error": str(e)[:200]}
            seen += json.dumps(out)
            try:
                summary = _summary(fc["name"], out)
            except Exception:  # noqa: BLE001
                summary = ""
            emit({"type": "tool", "status": "error" if "error" in out else "done", "name": fc["name"], "args": args,
                  "n": calls, "seconds": round(time.time() - t0, 1), "summary": summary})
            inp += [{"type": "function_call", "call_id": fc["call_id"], "name": fc["name"], "arguments": fc.get("arguments") or "{}"},
                    {"type": "function_call_output", "call_id": fc["call_id"], "output": json.dumps(out)[:12000]}]
    raise llm.LLMError("the tool loop did not finish")
