"""Festival files, Qloo artist matching and the pair overlap table.

python -m clash.overlap clash/festivals/testbill.json
The table is cached privately (cache/, git-ignored): Qloo response data never goes in the public repo."""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import qloo


def _norm(name):
    n = re.sub(r"[^a-z0-9& ]", " ", name.lower().replace("’", "'").replace("'", "").replace("é", "e"))
    n = re.sub(r"\s+", " ", n.replace("&", " and ")).strip()
    return n[4:] if n.startswith("the ") else n


def minutes(hhmm):
    """'17:30' -> 1050. Times before 06:00 count as after midnight (a set at 00:30 ends the same festival day)."""
    h, m = (int(x) for x in hhmm.split(":"))
    return (h + (24 if h < 6 else 0)) * 60 + m


def clock(mins):
    return f"{(mins // 60) % 24:02d}:{mins % 60:02d}"


def load(path):
    """A festival file in either form:
    - "sets": [{"stage", "act", "start": "HH:MM", "end": "HH:MM"}], a real timetable with any set times;
    - "slots" + "published": {stage: [act per slot, or null]}, hourly slots (each set runs to the next slot).
    Either way the result has "cells" (stage index, start and end in minutes), "home" (act -> its published cell),
    "acts", "stages" and "rules"."""
    f = json.load(open(path, encoding="utf-8"))
    f["slug"] = os.path.splitext(os.path.basename(path))[0]
    if "sets" in f:
        rows = f["sets"]
        f.setdefault("stages", list(dict.fromkeys(r["stage"] for r in rows)))
    else:
        rows = [{"stage": st, "act": a, "start": t, "end": clock(minutes(t) + 60)}
                for st in f["stages"] for t, a in zip(f["slots"], f["published"][st]) if a]
    rows = sorted(rows, key=lambda r: (f["stages"].index(r["stage"]), minutes(r["start"])))
    f["cells"] = [{"stage": f["stages"].index(r["stage"]), "start": minutes(r["start"]), "end": minutes(r["end"])} for r in rows]
    f["home"] = {r["act"]: i for i, r in enumerate(rows)}
    f["acts"] = [r["act"] for r in rows]
    assert len(set(f["acts"])) == len(f["acts"]), "an act is listed twice"
    assert all(c["end"] > c["start"] for c in f["cells"]), "a set ends before it starts"
    f["day"] = [min(c["start"] for c in f["cells"]), max(c["end"] for c in f["cells"])]
    last = {}
    for i, c in enumerate(f["cells"]):
        if c["stage"] not in last or c["start"] > f["cells"][last[c["stage"]]]["start"]:
            last[c["stage"]] = i
    f["closing"] = set(last.values())
    f.setdefault("rules", {})
    return f


def _get(path, **params):
    """qloo.get, but an error reply (rate limit, timeout) is retried and then raised, never read as "no data"."""
    for wait in (2, 5, 10, 20):
        d = qloo.get(path, **params)
        if "error" not in d:
            return d
        time.sleep(wait)
    raise RuntimeError(f"Qloo kept failing on {path}: {d.get('error')}")


def resolve(name):
    """The Qloo artist with this exact name among the top search results, or None. Never a near miss."""
    d = _get("/search", query=name, types="urn:entity:artist", take=5)
    for h in d.get("results") or []:  # /search returns a plain list
        if isinstance(h, dict) and _norm(h.get("name", "")) == _norm(name):
            return {"name": h["name"], "id": h["entity_id"], "popularity": h.get("popularity") or 0.0}
    return None


def _scores(signal, ids):
    out = {}
    for i in range(0, len(ids), 40):
        d = _get("/v2/insights", **{"filter.type": "urn:entity:artist", "signal.interests.entities": signal,
                                        "filter.results.entities": ",".join(ids[i:i + 40]), "take": 50})
        for x in qloo.results(d, "entities"):
            out[x["entity_id"]] = x.get("query", {}).get("affinity", 0.0)
    return out


def _lastfm_key():
    for line in open(".env", encoding="utf-8") if os.path.exists(".env") else []:
        if line.startswith("LASTFM_API_KEY="):
            return line.split("=", 1)[1].strip()
    return os.environ.get("LASTFM_API_KEY")


def lastfm_similar(name):
    """{normalised artist name: Last.fm match 0 to 1} for an artist's similar artists (real listening data), or None
    if Last.fm does not know the artist. Cached privately like Qloo's replies."""
    path = os.path.join(qloo.CACHE, f"lastfm_{_norm(name).replace(' ', '_')}.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    q = urllib.parse.urlencode({"method": "artist.getsimilar", "artist": name, "api_key": _lastfm_key(),
                                "format": "json", "limit": 500})
    for wait in (2, 5, 10, 0):
        try:
            d = json.load(urllib.request.urlopen("https://ws.audioscrobbler.com/2.0/?" + q, timeout=30))
            break
        except OSError:
            if not wait:
                raise
            time.sleep(wait)
    if d.get("error") == 6:  # artist not found
        out = None
    elif "error" in d:
        raise RuntimeError(f"Last.fm failed on {name}: {d.get('message')}")
    else:
        out = {_norm(x["name"]): float(x["match"]) for x in d["similarartists"]["artist"]}
    os.makedirs(qloo.CACHE, exist_ok=True)
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return out


def _fill(fest, t):
    """Rows for acts Qloo does not hold, from Last.fm's similar artists: {act: {other act: match}}, 0 where the
    other act is not among its similar artists. Two filled acts get the mean of both directions."""
    alias = fest.get("qloo_names", {})
    sim = {a: lastfm_similar(alias.get(a, a)) for a in fest["acts"] if a not in t["matched"]}
    sim = {a: v for a, v in sim.items() if v is not None}
    rows = {a: {b: v.get(_norm(alias.get(b, b)), 0.0) for b in fest["acts"] if b != a} for a, v in sim.items()}
    for a in rows:
        for b in rows:
            if a < b:
                rows[a][b] = rows[b][a] = round((rows[a][b] + rows[b][a]) / 2, 4)
    return rows


def table(fest):
    """{"acts": [...], "matched": {act: entity}, "overlap": {act: {act: score}}, "lastfm": {act: {act: match}}}.
    "overlap" covers every pair of acts Qloo holds (the mean of Qloo's two directions). Acts Qloo does not hold get a
    row in "lastfm" from Last.fm's real listening data, kept separate and labelled; acts neither holds are no data."""
    path = os.path.join(qloo.CACHE, f"clash_{fest['slug']}.json")
    if os.path.exists(path):
        t = json.load(open(path, encoding="utf-8"))
        if t["acts"] == fest["acts"] and t.get("alias", {}) == fest.get("qloo_names", {}):
            if "lastfm" not in t:
                t["lastfm"] = _fill(fest, t)
                json.dump(t, open(path, "w", encoding="utf-8"), ensure_ascii=False)
            return t
    alias = fest.get("qloo_names", {})  # checked by hand: the act's name as Qloo writes it
    matched = {a: e for a in fest["acts"] if (e := resolve(alias.get(a, a)))}
    ids = {a: e["id"] for a, e in matched.items()}
    raw = {a: _scores(ids[a], [ids[b] for b in matched if b != a]) for a in matched}
    overlap = {a: {} for a in matched}
    for a in matched:
        for b in matched:
            if a < b:
                two = [raw[a][ids[b]]] if ids[b] in raw[a] else []
                two += [raw[b][ids[a]]] if ids[a] in raw[b] else []
                s = sum(two) / len(two) if two else 0.0
                overlap[a][b] = overlap[b][a] = round(s, 4)
    t = {"acts": fest["acts"], "alias": alias, "matched": matched, "overlap": overlap}
    t["lastfm"] = _fill(fest, t)
    os.makedirs(qloo.CACHE, exist_ok=True)
    json.dump(t, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return t


def weights(t):
    """Clash weight for every pair, 0 to 1. Qloo's raw scores are bunched (unrelated pairs and twins score close
    together), so each act's scores are ranked against the rest of the bill, the two directions averaged, and the
    result cubed so that near-twins dominate. Same keys as t["overlap"]."""
    rank = {}
    for a, row in t["overlap"].items():
        vals = sorted(row.values())
        rank[a] = {b: sum(v <= s for v in vals) / len(vals) for b, s in row.items()}
    w = {a: {b: round(((rank[a][b] + rank[b][a]) / 2) ** 3, 4) for b in row} for a, row in t["overlap"].items()}
    # Last.fm's match is already spread from 0 (not among the 500 most similar) to 1 (near twin), so it is used as
    # the weight directly; ranking would turn a match of 0.02 into a full clash on a bill with few neighbours.
    for a, row in t.get("lastfm", {}).items():
        for b, s in row.items():
            w.setdefault(a, {})[b] = w.setdefault(b, {})[a] = s
    return w


def main(path):
    sys.stdout.reconfigure(encoding="utf-8")
    calls = {"live": 0, "cached": 0}
    qloo.set_trace(lambda p, params, status, cached: calls.__setitem__("cached" if cached else "live",
                                                                         calls["cached" if cached else "live"] + 1))
    fest = load(path)
    t = table(fest)
    n = len(t["matched"])
    print(f"{fest['name']}: matched {n} of {len(fest['acts'])} acts in Qloo")
    missing = [a for a in fest["acts"] if a not in t["matched"]]
    if missing:
        print("No Qloo data:", ", ".join(missing))
        print(f"Filled from Last.fm: {len(t['lastfm'])} of {len(missing)}; no data at all:",
              ", ".join(a for a in missing if a not in t["lastfm"]) or "none")
    pairs = sorted(((s, a, b) for a in t["overlap"] for b, s in t["overlap"][a].items() if a < b), reverse=True)
    print(f"{len(pairs)} pairs scored")
    print("Highest overlap:")
    for s, a, b in pairs[:5]:
        print(f"  {s:.3f}  {a} + {b}")
    print(f"Qloo calls: {calls['live']} live, {calls['cached']} from cache"
          + (" (table itself from cache)" if not calls["live"] and not calls["cached"] else ""))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "clash/festivals/testbill.json")
