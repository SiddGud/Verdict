"""The "without Qloo" side: a language model alone scores every pair on the bill, twice, and builds its own
timetable from each run. Computed once ahead of time (it costs model calls) and cached privately.

python -m clash.baseline testbill
The page shows how far the model's two runs disagree and which acts it said it does not know. It never scores the
model's timetable with Qloo's numbers: that would only measure agreement with Qloo."""
import itertools
import json
import os
import sys

import llm
import qloo
from clash import overlap as ov
from clash import schedule as sc

ASK = ("Here are the acts on a festival bill, numbered. For each listed pair, estimate from 0 to 100 how much the two "
       "acts' fans are the same people. Use the whole range. Also list the numbers of any acts you do not know. "
       'Reply as {"pairs": {"1-2": n, ...}, "unknown": [numbers]} with every listed pair.')
BLOCKS = 4


def _path(fest, run):
    return os.path.join(qloo.CACHE, f"clash_model_{fest['slug']}_{run}.json")


def score(fest, run):
    """{act: {act: 0 to 1}} from the model alone, plus the acts it said it did not know. Cached per run."""
    path = _path(fest, run)
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    acts = fest["acts"]
    listing = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(acts))
    pairs = list(itertools.combinations(range(len(acts)), 2))
    size = -(-len(pairs) // BLOCKS)
    out, unknown = {a: {} for a in acts}, set()
    for b in range(BLOCKS):
        block = pairs[b * size:(b + 1) * size]
        want = [f"{i + 1}-{j + 1}" for i, j in block]

        def check(o):
            if not isinstance(o.get("pairs"), dict) or any(k not in o["pairs"] for k in want):
                raise ValueError("give a score for every listed pair")
        o = llm.complete_json(ASK, f"Acts:\n{listing}\n\nPairs to score: {', '.join(want)}", check=check, retries=2,
                              timeout=300)[0]
        for (i, j), k in zip(block, want):
            out[acts[i]][acts[j]] = out[acts[j]][acts[i]] = float(o["pairs"][k]) / 100
        unknown |= {acts[n - 1] for n in o.get("unknown") or [] if isinstance(n, int) and 0 < n <= len(acts)}
    r = {"overlap": out, "unknown": sorted(unknown)}
    json.dump(r, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return r


def summary(fest):
    """What the page shows, or None if the model runs were not computed for this festival."""
    if not all(os.path.exists(_path(fest, r)) for r in (1, 2)):
        return None
    runs = [score(fest, r) for r in (1, 2)]
    pub = sc.published(fest)
    tables = []
    for r in runs:
        w = ov.weights({"overlap": r["overlap"]})
        tables.append(sc.optimise(pub, fest, w)[0])
    moved = sum(tables[0][a] != tables[1][a] for a in pub)
    a, b = runs[0]["overlap"], runs[1]["overlap"]
    diffs = [abs(a[x][y] - b[x][y]) for x in a for y in a[x] if x < y]
    return {"set_times_that_differ": moved, "acts": len(pub), "mean_pair_change": round(sum(diffs) / len(diffs), 3),
            "pairs_changed_by_10_or_more": sum(d >= 0.1 for d in diffs), "pairs": len(diffs),
            "unknown": sorted(set(runs[0]["unknown"]) | set(runs[1]["unknown"]))}


def main(slug):
    sys.stdout.reconfigure(encoding="utf-8")
    fest = ov.load(f"clash/festivals/{slug}.json")
    for r in (1, 2):
        score(fest, r)
        print(f"model run {r} done")
    print(json.dumps(summary(fest), indent=1))
    print(f"CometAPI spend this process: ${llm.SPEND['usd']:.2f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "testbill")
