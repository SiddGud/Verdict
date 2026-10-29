"""A fan's route through the day: up to 5 favourite artists in, the best act at each hour out, with the clashes the
fan cannot avoid flagged.

python -m clash.fanroute testbill "Phoebe Bridgers" "Clairo" "Frank Ocean"
Favourites need not play the festival. One Qloo call scores the whole bill against all of them at once."""
import sys

import qloo
from clash import overlap as ov


def fit(fest, favourites):
    """{act: Qloo affinity for someone who loves these artists}, plus the favourites Qloo matched and those it did not."""
    found, missing = [], []
    for name in favourites[:5]:
        e = ov.resolve(name)
        (found if e else missing).append(e or name)
    if not found:
        return {}, found, missing
    t = ov.table(fest)
    ids = {e["id"]: a for a, e in t["matched"].items()}
    scores = {}
    keys = list(ids)
    for i in range(0, len(keys), 40):
        d = qloo.get("/v2/insights", **{"filter.type": "urn:entity:artist",
                                        "signal.interests.entities": ",".join(e["id"] for e in found),
                                        "filter.results.entities": ",".join(keys[i:i + 40]), "take": 50})
        for x in qloo.results(d, "entities"):
            if x["entity_id"] in ids:
                scores[ids[x["entity_id"]]] = x.get("query", {}).get("affinity", 0.0)
    for e in found:  # Qloo leaves the signal artists out of its results: an act the fan named is a sure pick
        if e["id"] in ids:
            scores[ids[e["id"]]] = 1.0
    return scores, found, missing


def route(fest, pos, favourites):
    """For each hour: the fan's best act on the current timetable, and a clash flag when the second best act at the
    same hour is nearly as good (within 0.03 of the best and in the fan's top quarter of the bill)."""
    scores, found, missing = fit(fest, favourites)
    if not scores:
        return {"error": "None of those artists were found. Try exact names, for example 'Phoebe Bridgers'.",
                "missing": missing}
    ranked = sorted(scores.values(), reverse=True)
    top_q = ranked[max(0, len(ranked) // 4 - 1)]
    hours = []
    for k, slot in enumerate(fest["slots"]):
        here = sorted(((scores.get(a, 0.0), a, fest["stages"][st]) for a, (st, kk) in pos.items() if kk == k and a in scores),
                      reverse=True)
        if not here:
            continue
        best = here[0]
        rival = here[1] if len(here) > 1 and here[1][0] >= top_q and best[0] - here[1][0] <= 0.03 else None
        hours.append({"slot": slot, "act": best[1], "stage": best[2], "fit": round(best[0], 3), "top": best[0] >= top_q,
                      "clash_with": {"act": rival[1], "stage": rival[2], "fit": round(rival[0], 3)} if rival else None})
    must = [h for h in hours if h["top"]]
    return {"favourites": [e["name"] for e in found], "not_found": missing, "hours": hours,
            "summary": f"{len(must)} sets in your top quarter of the bill; "
                       f"{sum(1 for h in must if h['clash_with'])} hours where you must choose."}


def main(args):
    sys.stdout.reconfigure(encoding="utf-8")
    from clash import schedule as sc
    fest = ov.load(f"clash/festivals/{args[0]}.json")
    r = route(fest, sc.published(fest), args[1:])
    if "error" in r:
        print(r["error"]); return
    print("Favourites found:", ", ".join(r["favourites"]), "| not found:", ", ".join(r["not_found"]) or "none")
    for h in r["hours"]:
        mark = "*" if h["top"] else " "
        c = f"   MUST CHOOSE: {h['clash_with']['act']} ({h['clash_with']['fit']:.2f})" if h["clash_with"] else ""
        print(f"{mark} {h['slot']}  {h['act']} on {h['stage']} ({h['fit']:.2f}){c}")
    print(r["summary"])


if __name__ == "__main__":
    main(sys.argv[1:])
