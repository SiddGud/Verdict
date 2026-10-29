"""Phase 2 checks on a small made-up bill, so they need no Qloo calls."""
from clash import schedule as sc

FEST = {"stages": ["A", "B"], "slots": ["1", "2", "3"],
        "published": {"A": ["a1", "a2", "a3"], "B": ["b1", "b2", "b3"]},
        "rules": {"headliners_close": True, "billing_window": 2, "stage_locked": {}}}
# a1 and b1 share most fans; a2 and b2 too. Published, both pairs clash.
OLAP = {"a1": {"b1": 0.9, "b2": 0.0, "a2": 0.1}, "b1": {"a1": 0.9, "a2": 0.0, "b2": 0.1},
        "a2": {"b2": 0.8, "b1": 0.0, "a1": 0.1}, "b2": {"a2": 0.8, "a1": 0.0, "b1": 0.1}}


def test_published_clash():
    assert sc.clash_score(sc.published(FEST), OLAP) == 1.7


def test_optimiser_lowers_clash_and_keeps_rules():
    new, log = sc.optimise(sc.published(FEST), FEST, OLAP)
    assert sc.clash_score(new, OLAP) < 1.7
    assert not sc.violations(new, FEST)
    assert new["a3"][1] == 2 and new["b3"][1] == 2  # headliners still close
    assert log and all(m["after"] < m["before"] for m in log)


def test_same_result_every_run():
    assert sc.optimise(sc.published(FEST), FEST, OLAP)[0] == sc.optimise(sc.published(FEST), FEST, OLAP)[0]


def test_booker_rule_is_kept():
    rule = [{"type": "at_slot", "act": "a1", "slot": 0}]
    new, _ = sc.optimise(sc.published(FEST), FEST, OLAP, extra=rule)
    assert new["a1"][1] == 0 and not sc.violations(new, FEST, rule)
