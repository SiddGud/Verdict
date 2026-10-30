"""A city's live music calendar, read the way the festival court reads a timetable: every night is a day and every
venue a stage. Shows on sale come from Ticketmaster; how much two acts share fans comes from Qloo (Last.fm for acts
Qloo does not hold).

python -m clash.city new-york plan "Clairo" 2026-11-01 2026-11-30
python -m clash.city chicago fan "Phoebe Bridgers" "Clairo"
Ticketmaster and Qloo replies are cached privately in cache/ (git-ignored)."""
import datetime
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import qloo
from clash import overlap as ov

CITIES = {"new-york": ("New York", "NY"), "chicago": ("Chicago", "IL"), "los-angeles": ("Los Angeles", "CA"),
          "boston": ("Boston", "MA"), "philadelphia": ("Philadelphia", "PA"), "washington": ("Washington", "DC"),
          "atlanta": ("Atlanta", "GA"), "nashville": ("Nashville", "TN"), "austin": ("Austin", "TX"),
          "denver": ("Denver", "CO"), "seattle": ("Seattle", "WA"), "san-francisco": ("San Francisco", "CA")}
TM = "https://app.ticketmaster.com/discovery/v2/events.json"
SKIP = ("tribute", "karaoke", "open mic", "brunch", "tour package", "parking", "vip", "upgrade")


def _key():
    for line in open(".env", encoding="utf-8") if os.path.exists(".env") else []:
        if line.startswith("TICKETMASTER_API_KEY="):
            return line.split("=", 1)[1].strip()
    return os.environ.get("TICKETMASTER_API_KEY")


def _tm(params):
    path = os.path.join(qloo.CACHE, "city_tm_" + hashlib.md5(json.dumps(params, sort_keys=True).encode()).hexdigest() + ".json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:  # listings change; keep a day
        return json.load(open(path, encoding="utf-8"))
    url = TM + "?" + urllib.parse.urlencode({**params, "apikey": _key()})
    for wait in (2, 5, 10, 0):
        try:
            d = json.load(urllib.request.urlopen(url, timeout=40))
            break
        except OSError:
            if not wait:
                raise
            time.sleep(wait)
    os.makedirs(qloo.CACHE, exist_ok=True)
    json.dump(d, open(path, "w", encoding="utf-8"))
    return d


def shows(city, start, end):
    """Music shows on sale in the city between two dates: [{date, time, venue, act, support, url}]. One row per show,
    headed by its first billed act; festivals and add-ons (parking, upgrades) are left out."""
    name, state = CITIES[city]
    out, seen = [], set()
    for page in range(5):  # Ticketmaster serves at most 1,000 results per search
        d = _tm({"city": name, "stateCode": state, "classificationName": "music", "size": 200, "page": page,
                 "sort": "date,asc", "startDateTime": f"{start}T00:00:00Z", "endDateTime": f"{end}T23:59:59Z"})
        for e in d.get("_embedded", {}).get("events", []):
            acts = [a["name"] for a in e.get("_embedded", {}).get("attractions", []) if a.get("name")]
            date = e["dates"]["start"].get("localDate")
            v = (e.get("_embedded", {}).get("venues") or [{}])[0]
            venue, loc = v.get("name", ""), v.get("location") or {}
            if (not acts or not date or not start <= date <= end  # the search window is in UTC; keep local dates
                    or any(w in e["name"].lower() for w in SKIP) or len(acts) > 6):
                continue
            k = (date, venue, acts[0])
            if k in seen:
                continue
            seen.add(k)
            out.append({"date": date, "time": (e["dates"]["start"].get("localTime") or "")[:5], "venue": venue,
                        "act": acts[0], "support": acts[1:3], "url": e.get("url", ""),
                        "promoter": (e.get("promoter") or {}).get("name") or "",
                        "lat": float(loc["latitude"]) if loc.get("latitude") else None,
                        "lon": float(loc["longitude"]) if loc.get("longitude") else None})
        if page + 1 >= d.get("page", {}).get("totalPages", 0):
            break
    return out


def _resolve_all(names):
    """{name: Qloo entity} for the names Qloo holds by exact name. Cached per name through qloo.get."""
    return {n: e for n in dict.fromkeys(names) if (e := ov.resolve(n))}


def fit(signal, acts):
    """{act: (weight 0 to 1, source)} for someone who loves the signal artists, over the acts given. Qloo scores the acts
    it holds; each act's score is ranked against the rest and cubed, as the festival court does, so that close matches
    dominate. An act Qloo lacks is placed by Last.fm when a signal artist is among its similar artists (match m puts it
    at that quantile). A signal artist on the list scores 1. Returns (scores, signals Qloo found, signals not found)."""
    found, missing = [], []
    for name in signal[:5]:
        e = ov.resolve(name)
        (found if e else missing).append(e or name)
    held = _resolve_all(acts)
    ids = {e["id"]: a for a, e in held.items()}
    raw = {}
    keys = list(ids)
    for i in range(0, len(keys) if found else 0, 40):
        d = ov._get("/v2/insights", **{"filter.type": "urn:entity:artist",
                                        "signal.interests.entities": ",".join(e["id"] for e in found),
                                        "filter.results.entities": ",".join(keys[i:i + 40]), "take": 50})
        for x in qloo.results(d, "entities"):
            if x["entity_id"] in ids:
                raw[ids[x["entity_id"]]] = x.get("query", {}).get("affinity", 0.0)
    vals = sorted(raw.values())
    out = {a: ((sum(v <= s for v in vals) / len(vals)) ** 3, "qloo") for a, s in raw.items()}
    named = {ov._norm(x) for x in signal[:5]}
    for a in acts:
        if ov._norm(a) in named:
            out[a] = (1.0, "named")
        elif a not in out and a not in held:
            sim = ov.lastfm_similar(a) or {}
            m = max((v for k, v in sim.items() if k in named), default=0.0)
            if m:
                out[a] = (min(1.0, m) ** 3, "lastfm")  # match m sits at that quantile, cubed like the rest
    return out, found, missing


def plan(city, artist, start, end, weekends=False):
    """Every night in the window, scored by how much the city's other shows that night pull on the artist's fans.
    Lower is better: fewer of their likely fans have something they would rather see."""
    rows = [r for r in shows(city, start, end) if ov._norm(r["act"]) != ov._norm(artist)]
    scores, found, missing = fit([artist], [r["act"] for r in rows])
    if not found:
        return {"error": f"Qloo has no artist named exactly '{artist}'. Try the name as billed."}
    nights = {}
    d0, d1 = datetime.date.fromisoformat(start), datetime.date.fromisoformat(end)
    for i in range((d1 - d0).days + 1):
        day = d0 + datetime.timedelta(days=i)
        if weekends and day.weekday() not in (4, 5):
            continue
        nights[day.isoformat()] = {"date": day.isoformat(), "weekday": day.strftime("%A"), "pull": 0.0, "shows": 0,
                                   "rivals": []}
    for r in rows:
        n = nights.get(r["date"])
        if not n:
            continue
        n["shows"] += 1
        w, src = scores.get(r["act"], (0.0, None))
        n["pull"] += w
        if w >= 0.2:
            n["rivals"].append({"act": r["act"], "venue": r["venue"], "time": r["time"], "weight": round(w, 3),
                                "source": src, "rank": None, "lat": r["lat"], "lon": r["lon"]})
    ranked = sorted((w for w, _ in scores.values()), reverse=True)
    usual = {}  # how many shows a night of this weekday usually lists in the window
    for n in nights.values():
        usual.setdefault(n["weekday"], []).append(n["shows"])
    usual = {k: sorted(v)[len(v) // 2] for k, v in usual.items()}
    for n in nights.values():
        n["usual"] = usual[n["weekday"]]
        n["few_announced"] = n["shows"] < 0.5 * usual[n["weekday"]]
        n["pull"] = round(n["pull"], 3)
        n["rivals"].sort(key=lambda x: -x["weight"])
        for x in n["rivals"]:
            x["rank"] = 1 + sum(v > x["weight"] for v in ranked)
        n["rivals"] = n["rivals"][:4]
    # nights with too few shows announced yet are not called best: they may only look quiet
    order = sorted((n for n in nights.values() if not n["few_announced"]), key=lambda n: (n["pull"], n["date"]))
    partners = sorted(({"act": r["act"], "venue": r["venue"], "date": r["date"], "lat": r["lat"], "lon": r["lon"],
                        "weight": round(scores[r["act"]][0], 3),
                        "source": scores[r["act"]][1], "rank": 1 + sum(v > scores[r["act"]][0] for v in ranked)}
                       for r in rows if r["act"] in scores and scores[r["act"]][0] >= 0.3), key=lambda x: -x["weight"])
    return {"artist": found[0]["name"], "city": CITIES[city][0], "start": start, "end": end, "shows": len(rows),
            "scored": len(scores), "nights": sorted(nights.values(), key=lambda n: n["date"]),
            "best": [n["date"] for n in order[:3]], "worst": [n["date"] for n in order[::-1][:3]],
            "partners": partners[:8],
            "map": [{"act": r["act"], "venue": r["venue"], "date": r["date"], "lat": r["lat"], "lon": r["lon"],
                     "weight": round(scores.get(r["act"], (0.0, None))[0], 3), "source": scores.get(r["act"], (0, None))[1]}
                    for r in rows if r["lat"] is not None and r["date"] in nights]}


def portfolio(city, promoter, start, end):
    """One promoter's shows in the city: which pairs share fans, and what to do about each. Same night: they compete
    for the same people. Within a week: the second show is the first one's best audience, so market it there.
    Further apart: co-promote (shared mailing list, bundle, retargeting)."""
    rows = [r for r in shows(city, start, end) if r["promoter"].lower() == promoter.lower()]
    acts = sorted({r["act"] for r in rows})
    if len(acts) < 2:
        return {"error": f"Fewer than two shows by {promoter} in this window."}
    fest = {"slug": f"portfolio_{city}_{hashlib.md5((promoter + start + end).encode()).hexdigest()[:8]}",
            "acts": acts, "qloo_names": {}}
    t = ov.table(fest)
    w = ov.weights(t)
    first = {}
    for r in sorted(rows, key=lambda r: r["date"]):
        first.setdefault(r["act"], r)
    pairs = []
    for i, a in enumerate(acts):
        for b in acts[i + 1:]:
            x = w.get(a, {}).get(b, 0.0)
            if x < 0.8:  # only the strongest overlaps: about the top tenth of each act's matches, cubed
                continue
            ra, rb = first[a], first[b]
            gap = abs((datetime.date.fromisoformat(ra["date"]) - datetime.date.fromisoformat(rb["date"])).days)
            kind = "compete" if gap == 0 else "sequence" if gap <= 7 else "copromote"
            pairs.append({"acts": [a, b], "weight": round(x, 3), "days_apart": gap, "kind": kind,
                          "shows": [ra, rb], "source": "lastfm" if a in t.get("lastfm", {}) or b in t.get("lastfm", {}) else "qloo"})
    pairs.sort(key=lambda p: (-p["weight"]))
    return {"promoter": promoter, "city": CITIES[city][0], "shows": len(rows), "acts": len(acts),
            "matched": len(t["matched"]) + len(t.get("lastfm", {})), "pairs": pairs,
            "counts": {k: sum(p["kind"] == k for p in pairs) for k in ("compete", "sequence", "copromote")}}


def promoters(city, start, end):
    """Promoters named on the city's listings, most shows first."""
    c = {}
    for r in shows(city, start, end):
        if r["promoter"] and r["promoter"].upper() != "PROMOTED BY VENUE":
            c[r["promoter"]] = c.get(r["promoter"], 0) + 1
    return sorted(c.items(), key=lambda x: -x[1])


def friends(city, people, start, end):
    """A group's month. people: {name: [favourite artists]}. Each show gets every person's fit; the group's picks are
    the shows that suit everyone (the lowest fit in the group is highest), and each pair of people is compared by how
    alike their fits run across the month's shows."""
    rows = shows(city, start, end)
    acts = [r["act"] for r in rows]
    fits = {}
    for name, favs in people.items():
        sc, found, missing = fit(favs, acts)
        fits[name] = {a: v for a, (v, _) in sc.items()}
    names = list(fits)
    picks = []
    for r in rows:
        each = {n: round(fits[n].get(r["act"], 0.0), 3) for n in names}
        low = min(each.values())
        if low >= 0.15:
            picks.append({**r, "fits": each, "group": low})
    picks.sort(key=lambda x: -x["group"])
    seen, top = set(), []
    for p in picks:
        if p["act"] not in seen:
            seen.add(p["act"])
            top.append(p)
    pairs = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            both = [(fits[a].get(x, 0.0), fits[b].get(x, 0.0)) for x in set(acts)]
            hi = [x for x in both if max(x) >= 0.3]
            share = sum(1 for x, y in hi if min(x, y) >= 0.3) / len(hi) if hi else 0.0
            pairs.append({"people": [a, b], "shared": round(share, 3), "count": len(hi)})
    pairs.sort(key=lambda p: -p["shared"])
    return {"people": names, "shows": len(rows), "picks": top[:8], "pairs": pairs}


def month(city, favourites, start, end):
    """A fan's month: on each night, the show they would most like to see, and the nights where two shows they would
    love are on at once."""
    rows = shows(city, start, end)
    scores, found, missing = fit(favourites, [r["act"] for r in rows])
    if not found and not any(s == "named" for _, s in scores.values()):
        return {"error": "None of those artists were found. Try exact names, for example 'Phoebe Bridgers'.",
                "not_found": missing}
    by = {}
    for r in rows:
        w, src = scores.get(r["act"], (0.0, None))
        if w >= 0.3:
            by.setdefault(r["date"], []).append({**r, "weight": round(w, 3), "source": src})
    nights = []
    for date in sorted(by):
        picks = sorted(by[date], key=lambda x: -x["weight"])
        day = datetime.date.fromisoformat(date)
        nights.append({"date": date, "weekday": day.strftime("%A"), "pick": picks[0],
                       "clash": picks[1] if len(picks) > 1 and picks[1]["weight"] >= 0.5 else None})
    return {"favourites": [e["name"] for e in found], "not_found": missing, "shows": len(rows), "nights": nights,
            "clashes": sum(1 for n in nights if n["clash"])}


def main(args):
    sys.stdout.reconfigure(encoding="utf-8")
    city, mode = args[0], args[1]
    if mode == "plan":
        r = plan(city, args[2], args[3], args[4])
        if "error" in r:
            print(r["error"]); return
        print(f"{r['artist']} in {r['city']}: {r['shows']} shows on sale, {r['scored']} scored")
        for n in r["nights"]:
            top = "; ".join(f"{x['act']} at {x['venue']} (#{x['rank']}, {x['source']})" for x in n["rivals"][:2])
            mark = " BEST" if n["date"] in r["best"] else " WORST" if n["date"] in r["worst"] else ""
            print(f"{n['date']} {n['weekday'][:3]} pull {n['pull']:.2f} of {n['shows']} shows{mark}  {top}")
    else:
        today = datetime.date.today()
        r = month(city, args[2:], today.isoformat(), (today + datetime.timedelta(days=30)).isoformat())
        if "error" in r:
            print(r["error"]); return
        for n in r["nights"]:
            c = f"   CLASH: {n['clash']['act']} at {n['clash']['venue']}" if n["clash"] else ""
            print(f"{n['date']} {n['weekday'][:3]}  {n['pick']['act']} at {n['pick']['venue']} ({n['pick']['weight']:.2f}){c}")
        print(f"{len(r['nights'])} nights with a show for you; {r['clashes']} where two clash")


if __name__ == "__main__":
    main(sys.argv[1:])
