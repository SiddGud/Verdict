"""Clash score, rules and the optimiser, on real set times.

python -m clash.schedule testbill
A timetable is {act: cell index}; a cell is one set on the published timetable (a stage, a start and an end). Two
acts clash when their sets overlap in time; a timetable's clash score is the sum, over overlapping pairs, of the
pair's clash weight times the hours they overlap. Every move swaps the acts in two cells (an empty cell counts), so
the stages, set times and set lengths of the published timetable stay as they are."""
import itertools
import random
import sys
import time

from clash import overlap as ov

LENGTH_SLACK = 15  # minutes: an act may move only to a set within this much of its published length


def published(fest):
    return dict(fest["home"])


def _hours(fest):
    """Hours of overlap between every two cells on different stages, cached on the festival."""
    if "_ov" not in fest:
        c = fest["cells"]
        fest["_ov"] = [[max(0, min(a["end"], b["end"]) - max(a["start"], b["start"])) / 60 if a["stage"] != b["stage"] else 0.0
                        for b in c] for a in c]
    return fest["_ov"]


def pairs(pos, w, fest):
    """(weight x hours, weight, act, act, minutes) for every pair of acts whose sets overlap."""
    h = _hours(fest)
    out = []
    for a, b in itertools.combinations(pos, 2):
        x = h[pos[a]][pos[b]]
        if x:
            wt = w.get(a, {}).get(b, 0.0)
            out.append((round(wt * x, 4), wt, a, b, round(x * 60)))
    return out


def clash_score(pos, w, fest):
    return round(sum(p[0] for p in pairs(pos, w, fest)), 4)


def worst(pos, w, fest, n=5):
    """The n overlapping pairs with the most clash: (clash, weight, act, act, minutes of overlap)."""
    return sorted(pairs(pos, w, fest), reverse=True)[:n]


def violations(pos, fest, extra=()):
    """Every rule the timetable breaks, in plain words. extra: the booker's rules, as dicts (see agents.py)."""
    r, home, cells = fest["rules"], fest["home"], fest["cells"]
    out = []
    for a, i in pos.items():
        c, h = cells[i], cells[home[a]]
        if r.get("headliners_close") and home[a] in fest["closing"] and i not in fest["closing"]:
            out.append(f"{a} is a headliner and must close a stage")
        if abs(c["start"] - h["start"]) > 60 * r.get("billing_window", 99):
            out.append(f"{a} moved more than {r['billing_window']} hours from its billed time")
        if abs((c["end"] - c["start"]) - (h["end"] - h["start"])) > LENGTH_SLACK:
            out.append(f"{a} would get a set of a different length")
    tiers = r.get("stage_tiers")  # stage -> size class; an act may move only between stages of its own class
    if tiers:
        out += [f"{a} must stay on a stage the size of {fest['stages'][cells[home[a]]['stage']]}" for a, i in pos.items()
                if tiers.get(fest["stages"][cells[i]["stage"]]) != tiers.get(fest["stages"][cells[home[a]]["stage"]])]
    for st, acts in r.get("stage_locked", {}).items():
        out += [f"{a} must stay on {st}" for a in acts if a in pos and fest["stages"][cells[pos[a]]["stage"]] != st]
    for x in extra:
        a, t = x.get("act"), x["type"]
        if a not in pos:
            continue
        c = cells[pos[a]]
        if t == "not_after" and c["start"] > x["time"]:
            out.append(f"{a} cannot start after {ov.clock(x['time'])}")
        elif t == "not_before" and c["start"] < x["time"]:
            out.append(f"{a} cannot start before {ov.clock(x['time'])}")
        elif t == "on_stage" and c["stage"] != x["stage"]:
            out.append(f"{a} must play {fest['stages'][x['stage']]}")
        elif t == "end_by" and c["end"] > x["time"]:
            out.append(f"{a} must be off stage by {ov.clock(x['time'])}")
        elif t == "at_time" and c["start"] != x["time"]:
            out.append(f"{a} must start at {ov.clock(x['time'])}")
        elif t == "apart" and x.get("other") in pos and _hours(fest)[pos[a]][pos[x["other"]]]:
            out.append(f"{a} and {x['other']} must not overlap")
    return out


def optimise(pos, fest, w, extra=(), seconds=2.0, seed=0, tries=12):
    """Several local searches from `pos`, each trying swaps in a different seeded order; keeps the one with the
    lowest clash score (ties: fewer moves). Every move in the kept log lowers the score and breaks no rule."""
    start, best = time.time(), None
    for t in range(tries):
        left = seconds - (time.time() - start)
        if left <= 0 and best:
            break
        new, log = _search(pos, fest, w, extra, max(left, 0.2), seed * 1000 + t)
        key = (clash_score(new, w, fest), len(log))
        if best is None or key < best[0]:
            best = (key, new, log)
    return best[1], best[2]


def _search(pos, fest, w, extra, seconds, seed):
    """Local search from `pos`: swap the acts in two cells when that lowers the clash score and breaks no rule."""
    pos = dict(pos)
    cells, h = fest["cells"], _hours(fest)
    rng = random.Random(seed)
    log, start = [], time.time()
    cur = clash_score(pos, w, fest)
    improved = True
    while improved and time.time() - start < seconds:
        improved = False
        at = {i: a for a, i in pos.items()}
        order = list(itertools.combinations(range(len(cells)), 2))
        rng.shuffle(order)
        for c1, c2 in order:
            a, b = at.get(c1), at.get(c2)
            if not a and not b:
                continue
            if cells[c1]["start"] == cells[c2]["start"] and cells[c1]["end"] == cells[c2]["end"]:
                continue  # same times on two stages: the clashes would not change
            d = (_gain(a, c2, pos, w, h, b) + _gain(b, c1, pos, w, h, a)
                 - _gain(a, c1, pos, w, h, b) - _gain(b, c2, pos, w, h, a))  # only pairs with a or b change
            if d > -0.01:  # skip churn a booker would not want (and moves too small to show at two decimals)
                continue
            trial = dict(pos)
            if a:
                trial[a] = c2
            if b:
                trial[b] = c1
            new = round(cur + d, 4)
            if not violations(trial, fest, extra):
                log.append({"acts": [x for x in (a, b) if x], "to": {**({a: c2} if a else {}), **({b: c1} if b else {})},
                            "before": cur, "after": new})
                pos, cur, improved = trial, new, True
                break
            if time.time() - start > seconds:
                break
    return pos, log


def _gain(act, cell, pos, w, h, skip):
    """Clash between `act` placed in `cell` and every other act except `skip`."""
    if not act:
        return 0.0
    row = w.get(act, {})
    return sum(row.get(o, 0.0) * h[cell][i] for o, i in pos.items() if o != act and o != skip)


def where(fest, i):
    c = fest["cells"][i]
    return f"{fest['stages'][c['stage']]} at {ov.clock(c['start'])}"


def main(slug):
    sys.stdout.reconfigure(encoding="utf-8")
    fest = ov.load(f"clash/festivals/{slug}.json")
    w = ov.weights(ov.table(fest))
    pub = published(fest)
    assert not violations(pub, fest), violations(pub, fest)
    t0 = time.time()
    new, log = optimise(pub, fest, w)
    took = time.time() - t0
    print("Clash score: clash weight (0 to 1, see overlap.weights) times hours of overlap, summed over overlapping sets")
    print(f"Published timetable: clash score {clash_score(pub, w, fest)}")
    for x, wt, a, b, m in worst(pub, w, fest, 3):
        print(f"  {a} vs {b}: weight {wt:.2f}, {m} minutes")
    print(f"Optimised: clash score {clash_score(new, w, fest)} after {len(log)} moves in {took:.1f} s")
    for x, wt, a, b, m in worst(new, w, fest, 3):
        print(f"  {a} vs {b}: weight {wt:.2f}, {m} minutes")
    v = violations(new, fest)
    print("Rules broken:", v if v else "none")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "testbill")
