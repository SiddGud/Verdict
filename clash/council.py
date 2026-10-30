"""The court as working agents. For each of the worst clashes on the timetable:

1. Two fan agents (one per act, run in parallel) use tools on Qloo's fan overlap and the timetable, and each proposes
   one concrete move. Fan agents speak for fans, not for the festival, so their moves may break a house rule.
2. The booker agent checks every proposal with a rules tool, objects to the ones that break a rule, and may
   counter-propose a legal move found with its own tool.
3. The judge agent compares the proposals with a scoring tool and picks one, or none.
4. Code verifies every step: a move that breaks a rule is never applied, whatever an agent says. The chosen move is
   applied at once, so the next case is argued on the new timetable.

After the cases, the optimiser tidies the rest of the day with the agents' moves pinned. Both scores are reported:
the agents' court plus tidying, and the optimiser alone.

python -m clash.council lolla2024thu        records a run to cache/ (replayed on the page without model calls)
"""
import json
import os
import sys
import threading
import time

import llm
import qloo
from clash import agents as ag
from clash import overlap as ov
from clash import schedule as sc

CASES = 5
RED = 0.45      # shared-fan weight at which an overlap is a clash (the page's red line)
EVERY = 30      # with every=True the court argues every red clash, up to this many cases
MAX_TOOL_CALLS = 3


def _record_path(slug):
    return os.path.join(qloo.CACHE, f"council_{slug}.json")


# ---------- what the agents' tools compute (all code, no model) ----------

class Day:
    """A working timetable the agents argue over. Moves are applied only through apply(), after checks."""

    def __init__(self, fest, w, pos, extra):
        self.fest, self.w, self.pos, self.extra = fest, w, dict(pos), list(extra)
        self.h = sc._hours(fest)

    def score(self, pos=None):
        return sc.clash_score(pos or self.pos, self.w, self.fest)

    def minutes(self, a, b, pos=None):
        p = pos or self.pos
        return round(self.h[p[a]][p[b]] * 60) if a in p and b in p else 0

    def trial(self, act, cell):
        """The day if act moved to cell (swapping with whoever is there)."""
        pos = dict(self.pos)
        at = {i: x for x, i in pos.items()}
        occ, old = at.get(cell), pos[act]
        pos[act] = cell
        if occ:
            pos[occ] = old
        return pos, occ

    def check(self, act, cell):
        """Every rule a move would break, the clash score after it, and who it swaps with."""
        if act not in self.pos or not 0 <= cell < len(self.fest["cells"]) or cell == self.pos[act]:
            return {"error": "not a valid move"}
        pos, occ = self.trial(act, cell)
        return {"act": act, "to": sc.where(self.fest, cell), "cell": cell, "swaps_with": occ,
                "breaks": sc.violations(pos, self.fest, self.extra),
                "clash_score_before": round(self.score(), 3), "clash_score_after": round(self.score(pos), 3)}

    def moves(self, act, other, legal_only, k=6):
        """The k moves of act (to any slot) that most lower the whole day's clash score, each with the overlap left
        between act and other. legal_only drops moves that break a rule (the booker's view); fans see every move."""
        out = []
        for cell in range(len(self.fest["cells"])):
            if cell == self.pos[act]:
                continue
            pos, occ = self.trial(act, cell)
            breaks = sc.violations(pos, self.fest, self.extra)
            if legal_only and breaks:
                continue
            out.append({"act": act, "cell": cell, "to": sc.where(self.fest, cell), "swaps_with": occ,
                        "clash_score_after": round(self.score(pos), 3), "overlap_left_minutes": self.minutes(act, other, pos),
                        "breaks": breaks[:2]})
        out.sort(key=lambda m: (m["clash_score_after"], m["cell"]))
        return out[:k]

    def fans_of(self, act):
        """The acts on the bill whose fans most overlap with act's, and how long each overlaps act now."""
        row = sorted(((x, b) for b, x in self.w.get(act, {}).items() if b in self.pos), reverse=True)[:6]
        return [{"act": b, "rank_on_bill": i + 1, "shared_fans_weight": round(x, 2), "overlap_minutes_now": self.minutes(act, b)}
                for i, (x, b) in enumerate(row)]

    def apply(self, act, cell):
        pos, occ = self.trial(act, cell)
        self.pos = pos
        return occ


# ---------- one agent: a short tool loop that ends in a JSON reply ----------

def _fn(name, desc, props, req):
    return {"type": "function", "name": name, "description": desc, "strict": True,
            "parameters": {"type": "object", "properties": props, "required": req, "additionalProperties": False}}


S, I, B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}


def _agent(role, instructions, prompt, tools, run, emit, check):
    """Run one agent: up to MAX_TOOL_CALLS tool calls, then a JSON reply validated by check (raises on bad)."""
    inp = [{"role": "user", "content": prompt}]
    calls = 0
    for turn in range(MAX_TOOL_CALLS + 3):
        body = {"model": llm.MODEL, "instructions": instructions + " Reply with JSON only, no prose, no code fences.",
                "input": inp, "tools": tools, "tool_choice": "auto" if calls < MAX_TOOL_CALLS else "none",
                "stream": False, "reasoning": {"effort": "low"}, "max_output_tokens": 900}
        d = _call(body)
        fcs = [o for o in d.get("output", []) if o.get("type") == "function_call"]
        if not fcs:
            text = llm._text(d).strip()
            try:
                out = json.loads(text[text.find("{"): text.rfind("}") + 1])
                check(out)
                return out
            except (ValueError, KeyError, TypeError) as e:
                inp += [{"role": "assistant", "content": text[:2000]},
                        {"role": "user", "content": f"That reply was not usable ({str(e)[:120]}). Reply again with the JSON asked for."}]
                continue
        for fc in fcs:
            calls += 1
            try:
                args = json.loads(fc.get("arguments") or "{}")
                out = run(fc["name"], args)
            except Exception as e:  # noqa: BLE001 - the agent sees the error and can try again
                args, out = {}, {"error": str(e)[:160]}
            emit({"type": "tool", "agent": role, "name": fc["name"], "args": args, "summary": _brief(fc["name"], out)})
            inp += [{"type": "function_call", "call_id": fc["call_id"], "name": fc["name"], "arguments": fc.get("arguments") or "{}"},
                    {"type": "function_call_output", "call_id": fc["call_id"], "output": json.dumps(out)[:8000]}]
    raise llm.LLMError(f"{role} gave no usable reply")


def _call(body):
    """One model turn; when the provider says it is busy (HTTP 429), wait and try again, up to three times."""
    for wait in (5, 15, 30, None):
        try:
            return llm.hedged_response(body)
        except llm.LLMError as e:
            if "429" not in str(e) or wait is None:
                raise
            time.sleep(wait)


def _brief(name, out):
    if isinstance(out, dict) and "error" in out:
        return out["error"]
    if name == "fans_of":
        return "closest: " + ", ".join(f"{x['act']} (#{x['rank_on_bill']})" for x in out[:3])
    if name in ("moves_for", "legal_moves"):
        return f"{len(out)} moves; best: {out[0]['act']} to {out[0]['to']}, clash score {out[0]['clash_score_after']}" if out else "no move"
    if name in ("check_move", "score_move"):
        return f"{out['act']} to {out['to']}: " + ("breaks " + out["breaks"][0] if out["breaks"] else "keeps every rule") + \
               f", clash score {out['clash_score_before']} to {out['clash_score_after']}"
    return ""


FAN = ("You are the fan agent for {me}. Your fans share many fans with {other}, and the two sets overlap {mins} minutes "
       "from {when}. Use the tools to make your case with real numbers and to find a move that ends or shortens the "
       "overlap. You speak for fans, so you may propose any move, even one the festival's rules forbid; the booker will "
       "check. Then reply as JSON: {{\"statement\": \"two short sentences for the court, citing the numbers you found and naming the stage and time you want (never a slot number)\", "
       "\"proposal\": {{\"act\": \"{me} or {other}\", \"cell\": slot number from a tool}}}}.")
BOOKER = ("You are the booker agent for the festival. The house rules: headliners close their stages, no act moves more "
          "than two hours from its billed time, set lengths stay the same, acts stay on stages of their size, plus the "
          "booker's own rules. Check each proposal with check_move. Object, naming the rule, to any that breaks one. If "
          "none is legal, or a better legal move exists, find one with legal_moves and counter-propose it. Reply as JSON: "
          "{\"statement\": \"two short sentences for the court naming each move by act, stage and time, never by number\", \"objections\": [proposal numbers you object to], "
          "\"counter\": {\"act\": name, \"cell\": slot} or null}.")
JUDGE = ("You are the judge of Clash Court. Choose the proposal that frees the most fans while keeping every rule; the "
         "clerk has already checked each one (see breaks and clash_score_after). You may confirm a number with "
         "score_move. Choosing none is allowed if every proposal breaks a rule or makes the day worse. Reply as JSON: "
         "{\"choice\": proposal number or null, \"ruling\": \"two short sentences: the decision and why, citing the numbers; name the act, stage and time of each proposal you mention, never its number\"}.")


def run_cases(fest, w, base, extra, emit, n=CASES, stop=None, every=False, skip=(), offset=0):
    """Argue the n worst clashes of base with the agents, applying each decided move; with every=True, argue every red
    clash (weight at least RED) until none is left unargued. Returns (Day, decided moves, proposals refused)."""
    day = Day(fest, w, base, extra)
    decided, argued, refused = [], [set(p) for p in skip], 0
    for i in range(EVERY if every else n):
        if stop and stop():
            break
        # each clash is argued once: a case the court could not settle is not argued again
        worst = [x for x in sc.worst(day.pos, w, fest, 60) if x[0] > 0 and {x[2], x[3]} not in argued
                 and (not every or x[1] >= RED)]
        if not worst:
            break
        x, wt, a, b, mins = worst[0]
        argued.append({a, b})
        when = ov.clock(max(fest["cells"][day.pos[a]]["start"], fest["cells"][day.pos[b]]["start"]))
        emit({"type": "case", "n": offset + i + 1, "of": None if every else offset + n, "acts": [a, b], "when": when, "minutes": mins,
              "weight": round(wt, 2)})

        def fan_tools(me, other):
            def run(name, args):
                if name == "fans_of":
                    return day.fans_of(ag._act(args["act"], fest) or me)
                if name == "moves_for":
                    act = ag._act(args["act"], fest) or me
                    return day.moves(act, other if act == me else me, legal_only=False)
                raise ValueError("unknown tool")
            tools = [_fn("fans_of", "The acts on this bill whose fans most overlap with an act's (Qloo), and their overlap now.",
                         {"act": S}, ["act"]),
                     _fn("moves_for", "The moves of an act (to any slot) that most lower the day's clash score, with the "
                         "overlap left between the two acts and any rule each breaks.", {"act": S}, ["act"])]
            return tools, run

        props = {}

        def fan(me, other, slot):
            tools, run = fan_tools(me, other)

            def check(o):
                p = o["proposal"]
                act = ag._act(str(p["act"]), fest)
                if act not in (me, other) or not isinstance(p["cell"], int):
                    raise ValueError("propose moving one of the two acts, with a slot number from a tool")
                o["proposal"]["act"] = act
            try:
                facts = {"fans_of_" + me: day.fans_of(me)[:4],
                         "moves_for_" + me: day.moves(me, other, legal_only=False, k=4),
                         "moves_for_" + other: day.moves(other, me, legal_only=False, k=4)}
                emit({"type": "tool", "agent": f"fan:{me}", "name": "fans_of", "args": {"act": me},
                      "summary": _brief("fans_of", facts["fans_of_" + me])})
                emit({"type": "tool", "agent": f"fan:{me}", "name": "moves_for", "args": {"act": me},
                      "summary": _brief("moves_for", facts["moves_for_" + me])})
                o = _agent(f"fan:{me}", FAN.format(me=me, other=other, mins=mins, when=when),
                           f"The clash: {me} and {other}, {mins} minutes from {when}. What your tools already returned: "
                           f"{json.dumps(facts)}. Call a tool only if you need more.", tools, run, emit, check)
                props[slot] = o
            except Exception as e:  # noqa: BLE001 - a silent fan agent still lets the case go on
                props[slot] = {"statement": f"(The fan agent for {me} could not answer: {str(e)[:80]}.)", "proposal": None}

        ts = [threading.Thread(target=fan, args=(a, b, 0)), threading.Thread(target=fan, args=(b, a, 1))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        proposals = []
        for slot, me in ((0, a), (1, b)):
            o = props[slot]
            p = o.get("proposal")
            checked = day.check(p["act"], p["cell"]) if p else None
            if checked and "error" not in checked:
                proposals.append({"from": f"fans of {me}", **checked})
            emit({"type": "say", "agent": "fan", "act": me, "text": o["statement"],
                  "proposal": {k: checked[k] for k in ("act", "to", "swaps_with", "breaks", "clash_score_after")} if checked and "error" not in checked else None})

        def booker_run(name, args):
            if name == "check_move":
                return day.check(ag._act(args["act"], fest), int(args["cell"]))
            if name == "legal_moves":
                act = ag._act(args["act"], fest)
                return day.moves(act, b if act == a else a, legal_only=True)
            raise ValueError("unknown tool")
        btools = [_fn("check_move", "Every house or booker rule a move would break, and the clash score after it.",
                      {"act": S, "cell": I}, ["act", "cell"]),
                  _fn("legal_moves", "The best moves of an act that keep every rule, with the clash score after each.",
                      {"act": S}, ["act"])]
        listing = json.dumps([{"number": i + 1, "from": p["from"], "act": p["act"], "to": p["to"], "cell": p["cell"]} for i, p in enumerate(proposals)])

        def bcheck(o):
            assert isinstance(o["statement"], str) and isinstance(o.get("objections", []), list)
            c = o.get("counter")
            if c:
                act = ag._act(str(c["act"]), fest)
                if act not in (a, b) or not isinstance(c["cell"], int):
                    raise ValueError("counter-propose moving one of the two acts, with a slot number from legal_moves")
                c["act"] = act
        try:
            checked = [{"number": i + 1, "from": p["from"], "act": p["act"], "to": p["to"], "cell": p["cell"],
                        "breaks": p["breaks"], "clash_score_after": p["clash_score_after"]} for i, p in enumerate(proposals)]
            legal = {"legal_moves_" + a: day.moves(a, b, legal_only=True, k=4), "legal_moves_" + b: day.moves(b, a, legal_only=True, k=4)}
            for p in checked:
                emit({"type": "tool", "agent": "booker", "name": "check_move", "args": {"act": p["act"], "cell": p["cell"]},
                      "summary": f"{p['act']} to {p['to']}: " + ("breaks " + p["breaks"][0] if p["breaks"] else "keeps every rule")})
            emit({"type": "tool", "agent": "booker", "name": "legal_moves", "args": {"act": a},
                  "summary": _brief("legal_moves", legal["legal_moves_" + a])})
            bo = _agent("booker", BOOKER, f"The clash: {a} and {b}, {mins} minutes from {when}. Proposals, already checked "
                        f"with check_move: {json.dumps(checked)}. legal_moves already returned: {json.dumps(legal)}. "
                        f"Booker's own rules: {[ag.describe(r, fest) for r in extra] or 'none'}. Call a tool only if you need more.",
                        btools, booker_run, emit, bcheck)
        except Exception as e:  # noqa: BLE001
            bo = {"statement": f"(The booker agent could not answer: {str(e)[:80]}.)", "objections": [], "counter": None}
        counter = day.check(bo["counter"]["act"], bo["counter"]["cell"]) if bo.get("counter") else None
        if counter and "error" not in counter:
            proposals.append({"from": "the booker", **counter})
        emit({"type": "say", "agent": "booker", "text": bo["statement"],
              "objections": [proposals[k - 1]["act"] + " to " + proposals[k - 1]["to"] for k in bo.get("objections", []) if isinstance(k, int) and 0 < k <= len(proposals)],
              "counter": {k: counter[k] for k in ("act", "to", "swaps_with", "breaks", "clash_score_after")} if counter and "error" not in counter else None})

        board = [{"number": i + 1, "from": p["from"], "act": p["act"], "to": p["to"], "cell": p["cell"], "swaps_with": p["swaps_with"],
                  "breaks": p["breaks"], "clash_score_before": p["clash_score_before"], "clash_score_after": p["clash_score_after"]}
                 for i, p in enumerate(proposals)]

        def judge_run(name, args):
            if name == "score_move":
                return day.check(ag._act(args["act"], fest), int(args["cell"]))
            raise ValueError("unknown tool")

        def jcheck(o):
            c = o.get("choice")
            if c is not None and (not isinstance(c, int) or not 0 < c <= len(board)):
                raise ValueError("choice must be a proposal number or null")
            assert isinstance(o["ruling"], str)
        try:
            jo = _agent("judge", JUDGE, f"The clash: {a} and {b}, {mins} minutes from {when}. Proposals, checked by the clerk: "
                        f"{json.dumps(board)}", [_fn("score_move", "Check a move: rules it breaks and the clash score after.",
                                                     {"act": S, "cell": I}, ["act", "cell"])], judge_run, emit, jcheck)
        except Exception as e:  # noqa: BLE001
            jo = {"choice": None, "ruling": f"(The judge could not answer: {str(e)[:80]}.)"}

        down = [x for x in (props[0]["statement"], props[1]["statement"], bo["statement"], jo["ruling"]) if "could not answer" in x]
        if len(down) == 4:  # every agent failed (the model provider refused): stop rather than pretend the court sat
            raise llm.LLMError("the agents are unavailable right now " + down[0][down[0].find("("):][:120])
        refused += sum(1 for p in board if p["breaks"])
        chosen = board[jo["choice"] - 1] if jo.get("choice") else None
        note = None
        if chosen and (chosen["breaks"] or chosen["clash_score_after"] >= chosen["clash_score_before"]):
            note = ("The clerk refuses the judge's choice: it breaks " + chosen["breaks"][0]) if chosen["breaks"] else \
                   "The clerk refuses the judge's choice: it does not lower the clash score."
            chosen = None
        move = None
        if chosen:
            swapped = day.apply(chosen["act"], chosen["cell"])
            move = {"act": chosen["act"], "cell": chosen["cell"], "to": chosen["to"], "swaps_with": swapped, "by": chosen["from"]}
            decided.append({"pair": [a, b], **move})
        left = day.minutes(a, b)
        outcome = "resolved" if not left else "eased" if left < mins else "stands"
        emit({"type": "ruling", "text": jo["ruling"], "clerk": note, "outcome": outcome, "move": move,
              "minutes_after": left, "clash_score": round(day.score(), 3), "pos": day.pos})
    return day, decided, refused


def sit(fest, w, base, extra, emit, stop=None, every=False, ruled=None):
    """The whole sitting: the cases, then the optimiser tidies the rest with the agents' moves pinned. Returns the
    final timetable and a summary with both scores. ruled: the booker's own ruling on the first case, made before the
    agents argue the rest ({"pair": [a, b], "move": {"act", "cell"} or None})."""
    t0, usd0 = time.time(), llm.SPEND["usd"]
    start = sc.clash_score(base, w, fest)
    pre = []
    if ruled:
        d0 = Day(fest, w, base, extra)
        if ruled.get("move"):
            m = ruled["move"]
            swapped = d0.apply(m["act"], m["cell"])
            pre.append({"pair": ruled["pair"], "act": m["act"], "cell": m["cell"], "to": sc.where(fest, m["cell"]),
                        "swaps_with": swapped, "by": "you"})
        base = d0.pos
    day, decided, refused = run_cases(fest, w, base, extra, emit, stop=stop, every=every,
                                      n=CASES - (1 if ruled else 0), skip=[ruled["pair"]] if ruled else (),
                                      offset=1 if ruled else 0)
    decided = pre + decided
    pins = []
    for d in decided:
        for act in (d["act"], d["swaps_with"]):
            if act:
                c = fest["cells"][day.pos[act]]
                pins += [{"type": "on_stage", "act": act, "stage": c["stage"]}, {"type": "at_time", "act": act, "time": c["start"]}]
    after_cases = day.score()
    final, _ = sc.optimise(day.pos, fest, w, extra + pins)
    alone, _ = sc.optimise(base, fest, w, extra)
    summary = {"start": round(start, 3), "after_cases": round(after_cases, 3), "final": round(sc.clash_score(final, w, fest), 3),
               "optimiser_alone": round(sc.clash_score(alone, w, fest), 3), "decided": len(decided),
               "seconds": round(time.time() - t0), "model_usd": round(llm.SPEND["usd"] - usd0, 3),
               "broken": sc.violations(final, fest, extra), "every": every,
               # proof the agents choose: who proposed each applied move, how many proposals the code refused,
               # and how many applied moves the optimiser on its own would not have made
               "by_fans": sum(1 for d in decided if d["by"].startswith("fans")),
               "by_booker": sum(1 for d in decided if d["by"] == "the booker"),
               "by_you": sum(1 for d in decided if d["by"] == "you"),
               "refused": refused,
               "not_the_optimisers": sum(1 for d in decided if alone.get(d["act"]) != final.get(d["act"]))}
    emit({"type": "tidy", "summary": summary})
    return final, summary


def record(slug, every=False):
    """Run a sitting on the published timetable and save every event, for replay without model calls."""
    sys.stdout.reconfigure(encoding="utf-8")
    fest = ov.load(os.path.join(os.path.dirname(__file__), "festivals", f"{slug}.json"))
    w = ov.weights(ov.table(fest))
    events = []

    def emit(e):
        events.append(e)
        if e["type"] == "say":
            print(f"  [{e['agent']}{':' + e['act'] if e.get('act') else ''}] {e['text']}")
        elif e["type"] == "case":
            print(f"CASE {e['n']}: {e['acts'][0]} v {e['acts'][1]} ({e['minutes']} min)")
        elif e["type"] == "ruling":
            print(f"  [judge] {e['text']} -> {e['outcome']} {e['clerk'] or ''}")
        elif e["type"] == "tool":
            print(f"    tool {e['agent']} {e['name']}: {e['summary'][:90]}")
    final, summary = sit(fest, w, sc.published(fest), [], emit, every=every)
    summary["cases"] = sum(1 for e in events if e["type"] == "case")
    failed = [e for e in events if e["type"] in ("say", "ruling") and "could not answer" in (e.get("text") or "")]
    if failed:  # a sitting where an agent failed is not a sitting: never replay it as one
        print(f"NOT SAVED: {len(failed)} agent replies failed, for example: {failed[0]['text'][:160]}")
        sys.exit(1)
    json.dump({"slug": slug, "recorded": time.strftime("%Y-%m-%d %H:%M"), "events": events, "final": final, "summary": summary},
              open(_record_path(slug), "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps(summary, indent=1))


def recorded(slug):
    p = _record_path(slug)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


if __name__ == "__main__":
    record(sys.argv[1] if len(sys.argv) > 1 else "lolla2024thu", every="--every" in sys.argv)
