"""Festival files, Qloo artist matching and the pair overlap table.

python -m clash.overlap clash/festivals/testbill.json
The table is cached privately (cache/, git-ignored): Qloo response data never goes in the public repo."""
import json
import os
import re
import sys

import qloo


def _norm(name):
    n = re.sub(r"[^a-z0-9& ]", " ", name.lower().replace("’", "'").replace("'", "").replace("é", "e"))
    n = re.sub(r"\s+", " ", n.replace("&", " and ")).strip()
    return n[4:] if n.startswith("the ") else n


def load(path):
    """A festival file: stages, slots, the published timetable (stage -> act per slot, null for an empty slot), rules."""
    f = json.load(open(path, encoding="utf-8"))
    f["slug"] = os.path.splitext(os.path.basename(path))[0]
    f["acts"] = [a for st in f["stages"] for a in f["published"][st] if a]
    assert len(set(f["acts"])) == len(f["acts"]), "an act is listed twice"
    return f


def resolve(name):
    """The Qloo artist with this exact name among the top search results, or None. Never a near miss."""
    d = qloo.get("/search", query=name, types="urn:entity:artist", take=5)
    for h in d.get("results") or []:  # /search returns a plain list
        if isinstance(h, dict) and _norm(h.get("name", "")) == _norm(name):
            return {"name": h["name"], "id": h["entity_id"], "popularity": h.get("popularity") or 0.0}
    return None


def _scores(signal, ids):
    out = {}
    for i in range(0, len(ids), 40):
        d = qloo.get("/v2/insights", **{"filter.type": "urn:entity:artist", "signal.interests.entities": signal,
                                        "filter.results.entities": ",".join(ids[i:i + 40]), "take": 50})
        for x in qloo.results(d, "entities"):
            out[x["entity_id"]] = x.get("query", {}).get("affinity", 0.0)
    return out


def table(fest):
    """{"acts": [...], "matched": {act: entity}, "overlap": {act: {act: score}}} for every pair of matched acts.
    A pair's score is the mean of Qloo's two directions; acts Qloo does not hold have no row (shown as no data)."""
    path = os.path.join(qloo.CACHE, f"clash_{fest['slug']}.json")
    if os.path.exists(path):
        t = json.load(open(path, encoding="utf-8"))
        if t["acts"] == fest["acts"]:
            return t
    matched = {a: e for a in fest["acts"] if (e := resolve(a))}
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
    t = {"acts": fest["acts"], "matched": matched, "overlap": overlap}
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
    return {a: {b: round(((rank[a][b] + rank[b][a]) / 2) ** 3, 4) for b in row} for a, row in t["overlap"].items()}


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
    pairs = sorted(((s, a, b) for a in t["overlap"] for b, s in t["overlap"][a].items() if a < b), reverse=True)
    print(f"{len(pairs)} pairs scored")
    print("Highest overlap:")
    for s, a, b in pairs[:5]:
        print(f"  {s:.3f}  {a} + {b}")
    print(f"Qloo calls: {calls['live']} live, {calls['cached']} from cache"
          + (" (table itself from cache)" if not calls["live"] and not calls["cached"] else ""))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "clash/festivals/testbill.json")
