"""Two booking tools where a language model leads, because our tests found it better than Qloo at the core judgement
(Tests 15 and 16: picking openers; Test 17: tour cities). Qloo and real listings then check what the model proposed.

python -m clash.booking support "Clairo"
python -m clash.booking tour "Clairo" new-york boston chicago 2026-11-10 2026-11-30
Every answer says which part came from the model and which from Qloo or Ticketmaster."""
import datetime
import sys

import llm
import qloo
from clash import city as ct
from clash import overlap as ov

ASK_OPENERS = ("You book opening acts for touring artists. Suggest 10 real, currently active artists who could open "
               "for the headliner: their fans would come for the headliner, and they draw clearly smaller crowds. "
               'Reply as {"openers": [{"name": "...", "why": "one short sentence"}]}.')
ASK_ROUTE = ("You plan tour routes. Order these cities into one sensible driving or flying route for a short tour, "
             "starting anywhere, so that travel between consecutive dates is short. Use every city once. "
             'Reply as {"order": ["city key", ...], "why": "one short sentence"}.')


def support(headliner):
    """The model's opener ideas, each checked: does Qloo hold the artist, how much do the headliner's fans share it
    (ranked among the ideas), is it a smaller draw by Qloo popularity, and is it playing anywhere we list soon."""
    head = ov.resolve(headliner)
    if not head:
        return {"error": f"Qloo has no artist named exactly '{headliner}'."}

    def check(o):
        if not isinstance(o.get("openers"), list) or len(o["openers"]) < 5:
            raise ValueError("give at least 5 openers as a list")
    o = llm.complete_json(ASK_OPENERS, f"Headliner: {head['name']}", check=check, retries=1, timeout=90)[0]
    ideas = [x for x in o["openers"] if isinstance(x, dict) and x.get("name")][:10]
    held = {x["name"]: ov.resolve(x["name"]) for x in ideas}
    ids = {e["id"]: n for n, e in held.items() if e}
    aff = {}
    if ids:
        d = ov._get("/v2/insights", **{"filter.type": "urn:entity:artist", "signal.interests.entities": head["id"],
                                        "filter.results.entities": ",".join(ids), "take": 50})
        for x in qloo.results(d, "entities"):
            if x["entity_id"] in ids:
                aff[ids[x["entity_id"]]] = x.get("query", {}).get("affinity", 0.0)
    playing = {}
    for slug in ct.CITIES:
        try:
            rows = ct.shows(slug, "2026-11-01", "2026-12-31")
        except Exception:
            continue
        for r in rows:
            for x in ideas:
                if ov._norm(x["name"]) in {ov._norm(r["act"]), *(ov._norm(s) for s in r["support"])}:
                    playing.setdefault(x["name"], []).append(f"{ct.CITIES[slug][0]} {r['date']}")
    order = sorted(aff.values(), reverse=True)
    out = []
    for x in ideas:
        e = held[x["name"]]
        out.append({"name": x["name"], "why": str(x.get("why", ""))[:200], "in_qloo": bool(e),
                    "overlap_rank": (1 + order.index(aff[x["name"]])) if x["name"] in aff else None,
                    "smaller_draw": (e["popularity"] < head["popularity"]) if e else None,
                    "playing": playing.get(x["name"], [])[:3]})
    out.sort(key=lambda r: (r["overlap_rank"] is None, r["overlap_rank"] or 0))
    return {"headliner": head["name"], "openers": out,
            "note": "Ideas from the language model; fan overlap and draw from Qloo; dates from Ticketmaster."}


def tour(artist, cities, start, end):
    """The model orders the cities; then, city by city in that order, the engine picks the night with the least
    competition for the artist's fans, at least one day after the previous date and within four days of it."""
    cities = [c for c in cities if c in ct.CITIES]
    if len(cities) < 2:
        return {"error": "Pick at least two cities."}
    names = {c: ct.CITIES[c][0] for c in cities}

    def check(o):
        if sorted(o.get("order", [])) != sorted(cities):
            raise ValueError("use every city key exactly once: " + ", ".join(cities))
    o = llm.complete_json(ASK_ROUTE, "Cities: " + ", ".join(f"{k} ({v})" for k, v in names.items()),
                          check=check, retries=2, timeout=90)[0]
    day = datetime.date.fromisoformat(start)
    last = datetime.date.fromisoformat(end)
    legs = []
    for c in o["order"]:
        lo, hi = day, min(last, day + datetime.timedelta(days=4))
        if lo > last:
            legs.append({"city": names[c], "slug": c, "error": "no dates left in the window"})
            continue
        p = ct.plan(c, artist, lo.isoformat(), hi.isoformat())
        if "error" in p:
            return p
        ok = [n for n in p["nights"] if not n["few_announced"]] or p["nights"]
        best = min(ok, key=lambda n: (n["pull"], n["date"]))
        legs.append({"city": names[c], "slug": c, "date": best["date"], "weekday": best["weekday"], "pull": best["pull"],
                     "rivals": best["rivals"][:2], "few_announced": best["few_announced"]})
        day = datetime.date.fromisoformat(best["date"]) + datetime.timedelta(days=1)
    return {"artist": artist, "route_why": str(o.get("why", ""))[:200], "legs": legs,
            "note": "City order from the language model; each date from Ticketmaster listings and Qloo fan overlap."}


def main(args):
    sys.stdout.reconfigure(encoding="utf-8")
    if args[0] == "support":
        r = support(args[1])
        for x in r.get("openers", []):
            print(f"#{x['overlap_rank']}  {x['name']}  smaller={x['smaller_draw']}  {x['playing']}  | {x['why']}")
        print(r.get("error") or r["note"])
    else:
        r = tour(args[1], args[2:-2], args[-2], args[-1])
        print(r.get("error") or r["route_why"])
        for x in r.get("legs", []):
            print(x)
    print(f"model spend: ${llm.SPEND['usd']:.3f}")


if __name__ == "__main__":
    main(sys.argv[1:])
