"""A fan's route through the day: up to 5 favourite artists in, the best path of sets that do not overlap out, with
the clashes the fan cannot avoid flagged.

python -m clash.fanroute testbill "Phoebe Bridgers" "Clairo" "Frank Ocean"
Favourites need not play the festival. One Qloo call scores the whole bill against all of them at once."""
import bisect
import sys

import qloo
from clash import overlap as ov

WALK = 10  # minutes a fan may leave a set early to reach the next one


def fit(fest, favourites):
    """{act: fit for someone who loves these artists}, the favourites Qloo matched and those it did not, and the acts
    scored from Last.fm. Qloo scores the acts it holds. An act Qloo lacks is scored when a favourite is among its
    Last.fm similar artists (match m): it is placed at the m-th quantile of the fan's Qloo scores, so the two sources
    share one scale. A favourite who plays the bill is a sure pick (1.0) either way."""
    found, missing = [], []
    for name in favourites[:5]:
        e = ov.resolve(name)
        (found if e else missing).append(e or name)
    t = ov.table(fest)
    ids = {e["id"]: a for a, e in t["matched"].items()}
    scores = {}
    keys = list(ids)
    for i in range(0, len(keys) if found else 0, 40):
        d = ov._get("/v2/insights", **{"filter.type": "urn:entity:artist",
                                        "signal.interests.entities": ",".join(e["id"] for e in found),
                                        "filter.results.entities": ",".join(keys[i:i + 40]), "take": 50})
        for x in qloo.results(d, "entities"):
            if x["entity_id"] in ids:
                scores[ids[x["entity_id"]]] = x.get("query", {}).get("affinity", 0.0)
    for e in found:  # Qloo leaves the signal artists out of its results: an act the fan named is a sure pick
        if e["id"] in ids:
            scores[ids[e["id"]]] = 1.0
    alias = fest.get("qloo_names", {})
    named = {ov._norm(x) for x in favourites[:5]}
    ranked = sorted(v for v in scores.values() if v < 1.0)
    from_lastfm = []
    for a in t.get("lastfm", {}):
        if ov._norm(alias.get(a, a)) in named or ov._norm(a) in named:
            scores[a] = 1.0
        else:
            m = max((v for k, v in (ov.lastfm_similar(alias.get(a, a)) or {}).items() if k in named), default=0.0)
            if not m or not ranked:
                continue
            scores[a] = ranked[min(len(ranked) - 1, int(m * len(ranked)))]
        from_lastfm.append(a)
    missing = [x for x in missing if not any(ov._norm(x) == ov._norm(alias.get(a, a)) or ov._norm(x) == ov._norm(a)
                                             for a in from_lastfm)]
    return scores, found, missing, from_lastfm


def best_path(sets):
    """Weighted interval scheduling: the sets whose total value is highest, where each next set starts no more than
    WALK minutes before the last one ends. sets: [(start, end, value, act)]."""
    sets = sorted(sets, key=lambda x: x[1])
    ends = [s[1] for s in sets]
    best = [(0.0, [])]
    for i, (st, en, v, a) in enumerate(sets):
        j = bisect.bisect_right(ends, st + WALK, 0, i)  # sets that end by then: leave up to WALK minutes early
        take = (best[j][0] + v, best[j][1] + [i])
        best.append(max(best[i], take, key=lambda x: x[0]))
    return [sets[i] for i in best[-1][1]]


def route(fest, pos, favourites):
    """The fan's best path through the current timetable. A set's value is the fan's fit above their median for this
    bill, so only acts they like more than usual are worth a walk. A chosen set is flagged when an overlapping set is
    nearly as good (within 0.03) and in the fan's top quarter of the bill: a clash they cannot avoid."""
    scores, found, missing, from_lastfm = fit(fest, favourites)
    if not scores:
        return {"error": "None of those artists were found. Try exact names, for example 'Phoebe Bridgers'.",
                "missing": missing}
    ranked = sorted(scores.values(), reverse=True)
    median, top_q = ranked[len(ranked) // 2], ranked[max(0, len(ranked) // 4 - 1)]
    cells = fest["cells"]
    sets = [(cells[i]["start"], cells[i]["end"], scores[a] - median, a) for a, i in pos.items()
            if a in scores and scores[a] > median]
    out = []
    for st, en, v, a in sorted(best_path(sets)):
        rivals = sorted(((scores[b], b) for b, j in pos.items() if b != a and b in scores and
                         min(en, cells[j]["end"]) > max(st, cells[j]["start"])), reverse=True)
        r = rivals[0] if rivals and rivals[0][0] >= top_q and scores[a] - rivals[0][0] <= 0.03 else None
        out.append({"start": ov.clock(st), "end": ov.clock(en), "act": a, "stage": fest["stages"][cells[pos[a]]["stage"]],
                    "fit": round(scores[a], 3), "top": scores[a] >= top_q,
                    "source": "lastfm" if a in from_lastfm else "qloo",
                    "clash_with": {"act": r[1], "fit": round(r[0], 3)} if r else None})
    must = [h for h in out if h["top"]]
    return {"favourites": [e["name"] for e in found], "not_found": missing, "sets": out, "from_lastfm": from_lastfm,
            "summary": f"{len(out)} sets on your route, {len(must)} of them in your top quarter of the bill; "
                       f"{sum(1 for h in out if h['clash_with'])} where you must choose."}


def main(args):
    sys.stdout.reconfigure(encoding="utf-8")
    from clash import schedule as sc
    fest = ov.load(f"clash/festivals/{args[0]}.json")
    r = route(fest, sc.published(fest), args[1:])
    if "error" in r:
        print(r["error"]); return
    print("Favourites found:", ", ".join(r["favourites"]), "| not found:", ", ".join(r["not_found"]) or "none")
    for h in r["sets"]:
        mark = ("*" if h["top"] else " ") + ("L" if h["source"] == "lastfm" else " ")
        c = f"   MUST CHOOSE: {h['clash_with']['act']} ({h['clash_with']['fit']:.2f})" if h["clash_with"] else ""
        print(f"{mark} {h['start']}-{h['end']}  {h['act']} on {h['stage']} ({h['fit']:.2f}){c}")
    print(r["summary"])


if __name__ == "__main__":
    main(sys.argv[1:])
