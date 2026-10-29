"""Engine checks on small made-up festivals, so they need no Qloo calls."""
from clash import fanroute as fr
from clash import schedule as sc


def fest(sets, rules=None):
    from clash import overlap as ov
    rows = sorted(sets, key=lambda r: (r[0], ov.minutes(r[2])))
    stages = list(dict.fromkeys(r[0] for r in rows))
    f = {"name": "t", "slug": "t", "stages": stages, "rules": rules or {"headliners_close": True, "billing_window": 2}}
    f["cells"] = [{"stage": stages.index(r[0]), "start": ov.minutes(r[2]), "end": ov.minutes(r[3])} for r in rows]
    f["home"] = {r[1]: i for i, r in enumerate(rows)}
    f["acts"] = [r[1] for r in rows]
    f["day"] = [min(c["start"] for c in f["cells"]), max(c["end"] for c in f["cells"])]
    last = {}
    for i, c in enumerate(f["cells"]):
        if c["stage"] not in last or c["start"] > f["cells"][last[c["stage"]]]["start"]:
            last[c["stage"]] = i
    f["closing"] = set(last.values())
    return f


# a1 and b1 share most fans; a2 and b2 too. Published, both pairs play at the same time.
F = fest([("A", "a1", "12:00", "13:00"), ("A", "a2", "13:00", "14:00"), ("A", "a3", "14:00", "15:00"),
          ("B", "b1", "12:00", "13:00"), ("B", "b2", "13:00", "14:00"), ("B", "b3", "14:00", "15:00")])
W = {"a1": {"b1": 0.9, "b2": 0.0, "a2": 0.1}, "b1": {"a1": 0.9, "a2": 0.0, "b2": 0.1},
     "a2": {"b2": 0.8, "b1": 0.0, "a1": 0.1}, "b2": {"a2": 0.8, "a1": 0.0, "b1": 0.1}}


def test_published_clash():
    assert sc.clash_score(sc.published(F), W, F) == 1.7


def test_partial_overlap_counts_minutes():
    g = fest([("A", "x", "12:00", "13:00"), ("B", "y", "12:30", "13:30")])
    assert sc.clash_score(sc.published(g), {"x": {"y": 1.0}, "y": {"x": 1.0}}, g) == 0.5


def test_optimiser_lowers_clash_and_keeps_rules():
    new, log = sc.optimise(sc.published(F), F, W)
    assert sc.clash_score(new, W, F) < 1.7
    assert not sc.violations(new, F)
    assert new["a3"] in F["closing"] and new["b3"] in F["closing"]  # headliners still close
    assert log and all(m["after"] < m["before"] for m in log)


def test_same_result_every_run():
    assert sc.optimise(sc.published(F), F, W)[0] == sc.optimise(sc.published(F), F, W)[0]


def test_booker_rule_is_kept():
    rule = [{"type": "at_time", "act": "a1", "time": 720}]
    new, _ = sc.optimise(sc.published(F), F, W, extra=rule)
    assert F["cells"][new["a1"]]["start"] == 720 and not sc.violations(new, F, rule)


def test_set_length_is_kept():
    g = fest([("A", "long", "12:00", "14:00"), ("A", "short", "14:00", "14:30"), ("B", "z", "12:00", "14:00")])
    pos = {"long": 1, "short": 0, "z": 2}
    assert any("different length" in v for v in sc.violations(pos, g))


def test_fan_path_skips_overlaps():
    path = fr.best_path([(720, 780, 1.0, "a"), (750, 810, 0.5, "b"), (775, 840, 0.8, "c")])
    assert [p[3] for p in path] == ["a", "c"]  # c starts 5 minutes before a ends: leave a little early
