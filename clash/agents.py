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


def _slot(text, fest):
    """'5pm', '17:00', '5 pm', '17' -> slot index, or None if the time is not a slot of this festival."""
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text.lower())
    if not m:
        return None
    h = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0) if m.group(3) else int(m.group(1))
    if not m.group(3) and h < 10:
        h += 12  # "play after 5" at a festival means 5 pm
    label = f"{h:02d}:{m.group(2) or '00'}"
    return fest["slots"].index(label) if label in fest["slots"] else None


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
    Types: cancel, not_after, not_before, apart, on_stage, at_slot (the schedule.violations rule types)."""
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
            k = _slot(m.group(2), fest)
            if k is not None:
                return {"type": "at_slot", "act": a, "slot": k}
            s = _stage(m.group(2), fest)
            if s is not None:
                return {"type": "on_stage", "act": a, "stage": s}
            continue
        k = _slot(m.group(2), fest)
        if k is None:
            return {"error": f"{m.group(2)} is not a set time at this festival ({fest['slots'][0]} to {fest['slots'][-1]})"}
        if kind == "not_after_strict":  # "must finish by 5pm": the set must start before 5
            return {"type": "not_after", "act": a, "slot": k - 1}
        return {"type": kind, "act": a, "slot": k}
    return _parse_with_model(t, fest)


def _parse_with_model(text, fest):
    instr = ("You turn a festival booker's command into one rule. Types: cancel {act}; not_after {act, time} (the set "
             "may not start after time); not_before {act, time}; apart {act, other}; on_stage {act, stage}; at_slot "
             "{act, time}. Use names exactly as listed. If the command is none of these, return "
             '{"type": "unknown"}. Reply as {"type": ..., "act": ..., "other": ..., "time": "HH:MM", "stage": ...}.')
    prompt = (f"Acts: {', '.join(fest['acts'])}\nStages: {', '.join(fest['stages'])}\nSet times: {', '.join(fest['slots'])}"
              f"\n\nCommand: {text}")
    try:
        o = llm.complete_json(instr, prompt, retries=2, timeout=60)[0]
    except Exception as e:  # any failure falls back to the examples; the reason goes to the server log
        print("booker model read failed:", type(e).__name__, str(e)[:200], file=sys.stderr)
        return {"error": "I could not read that command. Try: 'Clairo can't play after 5pm', 'cancel Turnstile', "
                         "'keep Mitski and Clairo apart', 'put Wallows on the Main Stage'."}
    kind = {"before": "not_after", "by": "not_after", "after": "not_before"}.get(o.get("type"), o.get("type"))
    a = _act(o.get("act") or "", fest)
    if kind not in ("cancel", "not_after", "not_before", "apart", "on_stage", "at_slot") or not a:
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
        k = fest["slots"].index(o["time"]) if o.get("time") in fest["slots"] else None
        if k is None:
            return {"error": "That is not a set time at this festival."}
        rule["slot"] = k
    rule["read_by_model"] = True
    return rule


def describe(rule, fest):
    t, a = rule["type"], rule.get("act")
    return {"cancel": lambda: f"{a} is cancelled",
            "not_after": lambda: f"{a} cannot start after {fest['slots'][rule['slot']]}",
            "not_before": lambda: f"{a} cannot start before {fest['slots'][rule['slot']]}",
            "apart": lambda: f"{a} and {rule.get('other')} must not play at the same time",
            "on_stage": lambda: f"{a} plays {fest['stages'][rule.get('stage', 0)]}",
            "at_slot": lambda: f"{a} plays at {fest['slots'][rule.get('slot', 0)]}"}[t]()


# ---------- fan agents and the referee ----------

def _rank(w, a, b):
    """Where b ranks among a's matches on this bill (1 = closest)."""
    return 1 + sum(s > w[a][b] for s in w[a].values())


def complaints(pos, fest, w, n=5):
    """Fan agents of the acts in the n worst clashes speak, with their numbers."""
    out = []
    for s, a, b, k in sc.worst(pos, w, n):
        if s <= 0:
            break
        out.append({"who": f"fan:{a}", "act": a, "other": b, "slot": k, "weight": s,
                    "text": (f"My fans rank {b} number {_rank(w, a, b)} of {len(w[a])} on this bill, and you have us "
                             f"head to head at {fest['slots'][k]} (clash weight {s:.2f}). Move one of us.")})
    return out


def run(pos, fest, w, rules=(), seconds=2.0):
    """One round: fan agents complain, the booker's rules are read out, the referee moves sets.
    Returns (new timetable, feed). Cancelled acts leave the grid first."""
    pos = {a: list(v) for a, v in pos.items()}
    feed = []
    for r in rules:
        if r["type"] == "cancel" and r["act"] in pos:
            del pos[r["act"]]
    for r in rules:
        feed.append({"who": "booker", "text": describe(r, fest) + "."})
    feed += complaints(pos, fest, w)
    before = sc.clash_score(pos, w)
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
        moved = ", ".join(f"{a} to {fest['stages'][new_cell[0]]} at {fest['slots'][new_cell[1]]}"
                          for a, new_cell in m["to"].items())
        feed.append({"who": "referee", "text": f"Moved {moved}: clash score {m['before']:.2f} to {m['after']:.2f}.",
                     "acts": m["acts"]})
    after = sc.clash_score(new, w)
    cut = 100 * (before - after) / before if before else 0
    feed.append({"who": "referee", "text": f"Done. Clash score {before:.2f} to {after:.2f} ({cut:.0f}% lower), "
                 f"{len(log)} moves, every rule kept."})
    return new, feed


def _repair(pos, fest, w, extra):
    """Swap cells until no rule is broken, choosing the swap that leaves the fewest broken rules, then the lowest
    clash score."""
    import itertools
    cells = [(s, k) for s in range(len(fest["stages"])) for k in range(len(fest["slots"]))]
    for _ in range(40):
        cur = len(sc.violations(pos, fest, extra))
        if not cur:
            break
        at = {tuple(v): a for a, v in pos.items()}
        best = None
        for c1, c2 in itertools.combinations(cells, 2):
            a, b = at.get(c1), at.get(c2)
            if not a and not b:
                continue
            trial = {x: list(v) for x, v in pos.items()}
            if a:
                trial[a] = list(c2)
            if b:
                trial[b] = list(c1)
            key = (len(sc.violations(trial, fest, extra)), sc.clash_score(trial, w))
            if key[0] < cur and (best is None or key < best[0]):
                best = (key, trial)
        if not best:
            break
        pos = best[1]
    return pos


def main(args):
    sys.stdout.reconfigure(encoding="utf-8")
    fest = ov.load("clash/festivals/testbill.json")
    if args and args[0] == "--feed":
        w = ov.weights(ov.table(fest))
        rules = [parse(t, fest) for t in args[1:]]
        new, feed = run(sc.published(fest), fest, w, [r for r in rules if "error" not in r])
        for f in feed:
            print(f"[{f['who']}] {f['text']}")
        return
    r = parse(" ".join(args), fest)
    print(r if "error" in r else {**r, "reads_as": describe(r, fest)})


if __name__ == "__main__":
    main(sys.argv[1:])
