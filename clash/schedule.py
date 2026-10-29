"""Clash score, rules and the optimiser.

python -m clash.schedule testbill
A timetable is {act: [stage index, slot index]}. Two acts clash when they share a slot; a timetable's clash score is
the sum of Qloo overlap over clashing pairs. Every move is a swap of two cells (an empty cell counts), so the grid
stays whole."""
import itertools
import random
import sys
import time

from clash import overlap as ov


def published(fest):
    return {a: [s, k] for s, st in enumerate(fest["stages"]) for k, a in enumerate(fest["published"][st]) if a}


def clash_score(pos, olap):
    by_slot = {}
    for a, (_, k) in pos.items():
        by_slot.setdefault(k, []).append(a)
    return round(sum(olap.get(a, {}).get(b, 0.0) for acts in by_slot.values() for a, b in itertools.combinations(acts, 2)), 4)


def worst(pos, olap, n=5):
    """The n clashing pairs with the highest overlap: (score, act, act, slot)."""
    out = [(olap.get(a, {}).get(b, 0.0), a, b, pos[a][1]) for a, b in itertools.combinations(pos, 2) if pos[a][1] == pos[b][1]]
    return sorted(out, reverse=True)[:n]


def violations(pos, fest, extra=()):
    """Every rule the timetable breaks, in plain words. extra: the booker's rules, as dicts (see agents.py)."""
    r, home, last = fest["rules"], published(fest), len(fest["slots"]) - 1
    out = []
    for a, (s, k) in pos.items():
        if r.get("headliners_close") and home[a][1] == last and k != last:
            out.append(f"{a} is a headliner and must close a stage")
        if abs(k - home[a][1]) > r.get("billing_window", 99):
            out.append(f"{a} moved more than {r['billing_window']} slots from its billed time")
    for st, acts in r.get("stage_locked", {}).items():
        out += [f"{a} must stay on {st}" for a in acts if a in pos and fest["stages"][pos[a][0]] != st]
    for x in extra:
        a, t = x.get("act"), x["type"]
        if a not in pos:
            continue
        s, k = pos[a]
        if t == "not_after" and k > x["slot"]:
            out.append(f"{a} cannot play after {fest['slots'][x['slot']]}")
        elif t == "not_before" and k < x["slot"]:
            out.append(f"{a} cannot play before {fest['slots'][x['slot']]}")
        elif t == "on_stage" and s != x["stage"]:
            out.append(f"{a} must play {fest['stages'][x['stage']]}")
        elif t == "at_slot" and k != x["slot"]:
            out.append(f"{a} must play at {fest['slots'][x['slot']]}")
        elif t == "apart" and x.get("other") in pos and pos[x["other"]][1] == k:
            out.append(f"{a} and {x['other']} must not play at the same time")
    return out


def optimise(pos, fest, olap, extra=(), seconds=2.0, seed=0):
    """Local search from `pos`: swap two cells when that lowers the clash score and breaks no rule.
    Returns (new timetable, move log). Stops when no swap helps or after `seconds`."""
    pos = {a: list(v) for a, v in pos.items()}
    cells = [(s, k) for s in range(len(fest["stages"])) for k in range(len(fest["slots"]))]
    rng = random.Random(seed)
    log, start = [], time.time()
    cur = clash_score(pos, olap)
    improved = True
    while improved and time.time() - start < seconds:
        improved = False
        at = {tuple(v): a for a, v in pos.items()}
        order = list(itertools.combinations(cells, 2))
        rng.shuffle(order)
        for c1, c2 in order:
            if c1[1] == c2[1] or (c1 not in at and c2 not in at):
                continue  # same slot changes nothing
            a, b = at.get(c1), at.get(c2)
            trial = {x: list(v) for x, v in pos.items()}
            if a:
                trial[a] = list(c2)
            if b:
                trial[b] = list(c1)
            new = clash_score(trial, olap)
            if new < cur - 0.005 and not violations(trial, fest, extra):  # skip churn a booker would not want
                log.append({"acts": [x for x in (a, b) if x], "to": {**({a: list(c2)} if a else {}), **({b: list(c1)} if b else {})},
                            "before": cur, "after": new})
                pos, cur, improved = trial, new, True
                break
            if time.time() - start > seconds:
                break
    return pos, log


def main(slug):
    sys.stdout.reconfigure(encoding="utf-8")
    fest = ov.load(f"clash/festivals/{slug}.json")
    olap = ov.weights(ov.table(fest))
    pub = published(fest)
    assert not violations(pub, fest), violations(pub, fest)
    t0 = time.time()
    new, log = optimise(pub, fest, olap)
    took = time.time() - t0
    print("Clash score: sum of clash weights (0 to 1, see overlap.weights) over pairs playing at the same time")
    print(f"Published timetable: clash score {clash_score(pub, olap)}")
    for s, a, b, k in worst(pub, olap, 3):
        print(f"  {fest['slots'][k]}  {a} vs {b}  ({s:.3f})")
    print(f"Optimised: clash score {clash_score(new, olap)} after {len(log)} moves in {took:.1f} s")
    for s, a, b, k in worst(new, olap, 3):
        print(f"  {fest['slots'][k]}  {a} vs {b}  ({s:.3f})")
    v = violations(new, fest)
    print("Rules broken:", v if v else "none")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "testbill")
