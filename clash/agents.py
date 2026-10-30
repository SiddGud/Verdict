"""The war-room: the booker's commands become checked rules, fan agents argue from Qloo's numbers, the referee
moves sets and explains each move.

python -m clash.agents "Clairo can't play after 5pm"
python -m clash.agents --feed testbill

Numbers in every message come from code. The model is used only to read a command the patterns below do not
understand, and its answer is checked against the festival's real acts, stages and times before it is used."""
import difflib
import re
import sys

import llm
from clash import overlap as ov
from clash import schedule as sc


# ---------- the booker: words to rules ----------

def _act(text, fest):
    names = {ov._norm(a): a for a in fest["acts"]}
    n = ov._norm(text)
    if n in names:
        return names[n]
    hit = difflib.get_close_matches(n, list(names), n=1, cutoff=0.75)
    return names[hit[0]] if hit else None


def _time(text, fest):
    """'5pm', '17:00', '5:30 pm', '17' -> minutes, or None if it is not within this festival's day."""
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text.lower())
    if not m:
        return None
    h = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0) if m.group(3) else int(m.group(1))
    if not m.group(3) and 1 <= h < 10:
        h += 12  # "play after 5" at a festival means 5 pm
    t = ov.minutes(f"{h:02d}:{int(m.group(2) or 0):02d}")
    return t if fest["day"][0] <= t <= fest["day"][1] else None


def _span(fest):
    return f"{ov.clock(fest['day'][0])} to {ov.clock(fest['day'][1])}"


def _stage(text, fest):
    hit = difflib.get_close_matches(text.lower().strip(), [s.lower() for s in fest["stages"]], n=1, cutoff=0.5)
    return [s.lower() for s in fest["stages"]].index(hit[0]) if hit else None


PATTERNS = [
    (r"^(?:cancel|drop|remove)\s+(.+?)(?:\s+(?:has|have|is|just).*)?$", "cancel"),
    (r"^(.+?)\s+(?:has\s+|just\s+)?(?:cancell?ed|pulled out|dropped out)", "cancel"),
    (r"^(.+?)\s+(?:can't|cannot|can not|must not|mustn't)\s+play\s+after\s+(.+)$", "not_after"),
    (r"^(.+?)\s+(?:must|has to|needs to)\s+(?:play|finish|be done)\s+(?:by|before)\s+(.+)$", "not_after_strict"),
    (r"^(.+?)\s+(?:can't|cannot|can not|must not|mustn't)\s+play\s+before\s+(.+)$", "not_before"),
    (r"^(.+?)\s+(?:arrives|lands|lands at|arrives at|gets in)\s+(?:at\s+)?(.+)$", "not_before"),
    (r"^keep\s+(.+?)\s+and\s+(.+?)\s+apart$", "apart"),
    (r"^(?:put|move)\s+(.+?)\s+(?:on|to)\s+(?:the\s+)?(.+?)$", "on_stage"),
    (r"^(.+?)\s+(?:must|has to)\s+play\s+(?:at|on)\s+(.+)$", "at_or_on"),
]


def parse(text, fest):
    """A booker command -> {"type": ..., ...} checked against this festival, or {"error": "..."}.
    Types: cancel, not_after, not_before, end_by, apart, on_stage, at_time (the schedule.violations rule types).
    Times are minutes from midnight."""
    t = text.strip().rstrip(".!").replace("’", "'")
    for pat, kind in PATTERNS:
        m = re.match(pat, t, re.I)
        if not m:
            continue
        a = _act(m.group(1), fest)
        if not a:
            continue
        if kind == "cancel":
            return {"type": "cancel", "act": a}
        if kind == "apart":
            b = _act(m.group(2), fest)
            if b:
                return {"type": "apart", "act": a, "other": b}
            continue
        if kind == "on_stage":
            s = _stage(m.group(2), fest)
            if s is not None:
                return {"type": "on_stage", "act": a, "stage": s}
            continue
        if kind == "at_or_on":
            k = _time(m.group(2), fest)
            if k is not None:
                return {"type": "at_time", "act": a, "time": k}
            s = _stage(m.group(2), fest)
            if s is not None:
                return {"type": "on_stage", "act": a, "stage": s}
            continue
        k = _time(m.group(2), fest)
        if k is None:
            return {"error": f"{m.group(2)} is not within this festival's day ({_span(fest)})"}
        if kind == "not_after_strict":  # "must finish by 5pm"
            return {"type": "end_by", "act": a, "time": k}
        return {"type": kind, "act": a, "time": k}
    if not MODEL_OK():
        return {"error": "I could not read that with the patterns, and the model is paused for today. Try: "
                         "'Tyla just cancelled', 'Kesha arrives at 4pm' or 'keep Hozier and Lizzy McAlpine apart'."}
    return _parse_with_model(t, fest)


MODEL_OK = lambda: True  # the web app swaps in its daily spend check  # noqa: E731


def _parse_with_model(text, fest):
    instr = ("You turn a festival booker's command into one rule. Types: cancel {act}; not_after {act, time} (the set "
             "may not start after time); not_before {act, time}; end_by {act, time} (the set must be over by "
             "time); apart {act, other}; on_stage {act, stage}; at_time {act, time}. Use names exactly as listed. If the command is none of these, return "
             '{"type": "unknown"}. Reply as {"type": ..., "act": ..., "other": ..., "time": "HH:MM", "stage": ...}.')
    prompt = (f"Acts: {', '.join(fest['acts'])}\nStages: {', '.join(fest['stages'])}\nFestival day: {_span(fest)}"
              f"\n\nCommand: {text}")
    try:
        o = llm.complete_json(instr, prompt, retries=2, timeout=60)[0]
    except Exception as e:  # any failure falls back to the examples; the reason goes to the server log
        print("booker model read failed:", type(e).__name__, str(e)[:200], file=sys.stderr)
        return {"error": "I could not read that command. Try: 'Clairo can't play after 5pm', 'cancel Turnstile', "
                         "'keep Mitski and Clairo apart', 'put Wallows on the Main Stage'."}
    kind = {"before": "not_after", "by": "not_after", "after": "not_before"}.get(o.get("type"), o.get("type"))
    a = _act(o.get("act") or "", fest)
    if kind not in ("cancel", "not_after", "not_before", "end_by", "apart", "on_stage", "at_time") or not a:
        return {"error": "I could not read that command as a rule about an act on this bill."}
    rule = {"type": kind, "act": a}
    if kind == "apart":
        b = _act(o.get("other") or "", fest)
        if not b:
            return {"error": "I could not find the second act on this bill."}
        rule["other"] = b
    elif kind == "on_stage":
        s = _stage(o.get("stage") or "", fest)
        if s is None:
            return {"error": "I could not find that stage."}
        rule["stage"] = s
    elif kind != "cancel":
        k = _time(str(o.get("time") or ""), fest)
        if k is None:
            return {"error": f"That time is not within this festival's day ({_span(fest)})."}
        rule["time"] = k
    rule["read_by_model"] = True
    return rule


def describe(rule, fest):
    t, a = rule["type"], rule.get("act")
    return {"cancel": lambda: f"{a} is cancelled",
            "not_after": lambda: f"{a} cannot start after {ov.clock(rule['time'])}",
            "not_before": lambda: f"{a} cannot start before {ov.clock(rule['time'])}",
            "end_by": lambda: f"{a} must be off stage by {ov.clock(rule['time'])}",
            "apart": lambda: f"{a} and {rule.get('other')} must not overlap",
            "on_stage": lambda: f"{a} plays {fest['stages'][rule.get('stage', 0)]}",
            "at_time": lambda: f"{a} starts at {ov.clock(rule['time'])}"}[t]()


# ---------- fan agents and the referee ----------

def _rank(w, a, b):
    """Where b ranks among a's matches on this bill (1 = closest)."""
    return 1 + sum(s > w[a][b] for s in w[a].values())


def complaints(pos, fest, w, n=5):
    """Fan agents of the acts in the n worst clashes speak, with their numbers."""
    out = []
    for x, wt, a, b, mins in sc.worst(pos, w, fest, n):
        if x <= 0:
            break
        when = ov.clock(max(fest["cells"][pos[a]]["start"], fest["cells"][pos[b]]["start"]))
        out.append({"who": f"fan:{a}", "act": a, "other": b, "weight": wt,
                    "text": (f"My fans rank {b} number {_rank(w, a, b)} of {len(w[a])} on this bill, and our sets "
                             f"overlap for {mins} minutes from {when} (clash weight {wt:.2f}). Move one of us.")})
    return out


def run(pos, fest, w, rules=(), seconds=2.0):
    """One round: fan agents complain, the booker's rules are read out, the referee moves sets.
    Returns (new timetable, feed). Cancelled acts leave the grid first."""
    pos = dict(pos)
    feed = []
    for r in rules:
        if r["type"] == "cancel" and r["act"] in pos:
            del pos[r["act"]]
    for r in rules:
        feed.append({"who": "booker", "text": describe(r, fest) + "."})
    feed += complaints(pos, fest, w)
    before = sc.clash_score(pos, w, fest)
    extra = [r for r in rules if r["type"] != "cancel"]
    broken = sc.violations(pos, fest, extra)
    if broken:
        feed.append({"who": "referee", "text": "The current timetable breaks a rule: " + "; ".join(broken) +
                     ". Repairing that first."})
        pos = _repair(pos, fest, w, extra)
        if sc.violations(pos, fest, extra):
            feed.append({"who": "referee", "text": "I cannot meet every rule at once: " +
                         "; ".join(sc.violations(pos, fest, extra)) + ". Please relax one."})
            return pos, feed
    new, log = sc.optimise(pos, fest, w, extra, seconds=seconds)
    for m in log:
        moved = ", ".join(f"{a} to {sc.where(fest, i)}" for a, i in m["to"].items())
        feed.append({"who": "referee", "text": f"Moved {moved}: clash score {m['before']:.2f} to {m['after']:.2f}.",
                     "acts": m["acts"], "to": m["to"], "score": m["after"]})
    after = sc.clash_score(new, w, fest)
    cut = 100 * (before - after) / before if before else 0
    feed.append({"who": "referee", "text": f"Done. Clash score {before:.2f} to {after:.2f} ({cut:.0f}% lower), "
                 f"{len(log)} moves, every rule kept."})
    return new, feed


def court(old, new, fest, w, extra=(), n=5):
    """The worst clashes on the timetable before the referee moved anything, argued as cases: each side's fan agent
    states its numbers, the booker objects if the most direct fix breaks a rule (found by trying it), and the ruling
    says where the two acts ended up after the whole re-plan."""
    h, cells = sc._hours(fest), fest["cells"]
    at = {i: a for a, i in old.items()}
    start = sc.clash_score(old, w, fest)
    cases = []
    for x, wt, a, b, mins in sc.worst(old, w, fest, n):
        if x <= 0 or a not in new or b not in new:
            continue
        when = ov.clock(max(cells[old[a]]["start"], cells[old[b]]["start"]))
        legal = broken = None  # (gain, mover, cell, why)
        window = 60 * fest["rules"].get("billing_window", 99)
        for mover, other in ((a, b), (b, a)):
            for c in range(len(cells)):  # fixes a booker would try: a free hour near the act's billed time
                occ = at.get(c)
                if (c == old[mover] or occ == other or h[c][old[other]]
                        or abs(cells[c]["start"] - cells[old[mover]]["start"]) > window):
                    continue
                trial = dict(old)
                trial[mover] = c
                if occ:
                    trial[occ] = old[mover]
                gain = start - sc.clash_score(trial, w, fest)
                why = sc.violations(trial, fest, extra)
                if why and (broken is None or gain > broken[0]):
                    broken = (gain, mover, c, why[0])
                if not why and (legal is None or gain > legal[0]):
                    legal = (gain, mover, c, None)
        objection = None
        if broken and (legal is None or broken[0] > legal[0]):
            objection = (f"Objection. The quickest fix is moving {broken[1]} to {sc.where(fest, broken[2])}, but "
                         f"{broken[3]}.")
        left = round(h[new[a]][new[b]] * 60)
        moved = [f"{y} to {sc.where(fest, new[y])}" for y in (a, b) if new[y] != old[y]]
        if not left:
            ruling = f"Sustained. {' and '.join(moved) if moved else 'Other sets moved'}: {a} and {b} no longer overlap."
            outcome = "resolved"
        elif left < mins:
            ruling = f"Partly sustained. {' and '.join(moved) or 'Other sets moved'}: the overlap drops from {mins} to {left} minutes."
            outcome = "eased"
        elif fest["rules"].get("headliners_close") and {fest["home"][a], fest["home"][b]} <= fest["closing"]:
            ruling = f"Overruled. {a} and {b} both headline, and headliners close their stages, so they must overlap."
            outcome = "stands"
        else:
            ruling = "Overruled. Every way to separate them breaks a rule or makes a worse clash elsewhere."
            outcome = "stands"
        cases.append({"acts": [a, b], "weight": wt, "minutes": mins, "when": when, "minutes_after": left,
                      "plaintiff": f"{b} is number {_rank(w, a, b)} of {len(w[a])} on this bill for our fans, and we "
                                   f"overlap {mins} minutes from {when}. Move one of us.",
                      "defendant": f"{a} is number {_rank(w, b, a)} of {len(w[b])} for ours too. We were billed on "
                                   f"{sc.where(fest, old[b])}: move them, not us.",
                      "objection": objection, "ruling": ruling, "outcome": outcome,
                      "from": {a: old[a], b: old[b]}, "to": {a: new[a], b: new[b]}})
    return cases


def _repair(pos, fest, w, extra):
    """Swap cells until no rule is broken, choosing the swap that leaves the fewest broken rules, then the lowest
    clash score."""
    import itertools
    for _ in range(40):
        cur = len(sc.violations(pos, fest, extra))
        if not cur:
            break
        at = {i: a for a, i in pos.items()}
        best = None
        for c1, c2 in itertools.combinations(range(len(fest["cells"])), 2):
            a, b = at.get(c1), at.get(c2)
            if not a and not b:
                continue
            trial = dict(pos)
            if a:
                trial[a] = c2
            if b:
                trial[b] = c1
            key = (len(sc.violations(trial, fest, extra)), sc.clash_score(trial, w, fest))
            if key[0] < cur and (best is None or key < best[0]):
                best = (key, trial)
        if not best:
            break
        pos = best[1]
    return pos


def main(args):
    sys.stdout.reconfigure(encoding="utf-8")
    fest = ov.load("clash/festivals/testbill.json")
    if args and args[0] == "--feed":  # --feed <festival> [command ...]
        fest = ov.load(f"clash/festivals/{args[1]}.json")
        w = ov.weights(ov.table(fest))
        rules = [parse(t, fest) for t in args[2:]]
        new, feed = run(sc.published(fest), fest, w, [r for r in rules if "error" not in r])
        for f in feed:
            print(f"[{f['who']}] {f['text']}")
        return
    r = parse(" ".join(args), fest)
    print(r if "error" in r else {**r, "reads_as": describe(r, fest)})


if __name__ == "__main__":
    main(sys.argv[1:])
