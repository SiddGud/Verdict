"""Bring your own lineup: a pasted timetable (one set per line: stage, act, start, end) becomes a festival day like the
built-in ones. Stored privately under cache/lineups (git-ignored), named by a hash of its content."""
import hashlib
import json
import os
import re

import qloo
from clash import overlap as ov

DIR = os.path.join(qloo.CACHE, "lineups")
MAX_SETS = 80
TIME = re.compile(r"^(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?$", re.I)


def _time(text):
    """'13:00', '1:30pm', '9pm', '00:30' -> 'HH:MM' (times before 06:00 count as after midnight, as elsewhere)."""
    m = TIME.match(text.strip().lower())
    if not m:
        raise ValueError(f"'{text}' is not a time (try 13:00 or 1pm)")
    h, mins, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ampm == "pm" and h != 12:
        h += 12
    if ampm == "am" and h == 12:
        h = 0
    if h > 23 or mins > 59:
        raise ValueError(f"'{text}' is not a time")
    return f"{h:02d}:{mins:02d}"


def parse(name, text):
    """{festival dict} from pasted lines, or raise ValueError with a reason a person can act on."""
    rows, seen = [], {}
    for n, line in enumerate(text.strip().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in re.split(r"\t|,", line)]
        if n == 1 and parts and parts[0].lower() in ("stage", "stages"):
            continue  # a header row
        if len(parts) != 4 or not all(parts):
            raise ValueError(f"Line {n}: need four parts, stage, act, start, end (got: {line[:60]})")
        stage, act, start, end = parts[0][:40], parts[1][:80], _time(parts[2]), _time(parts[3])
        if ov.minutes(end) <= ov.minutes(start):
            raise ValueError(f"Line {n}: {act} ends before it starts")
        if act in seen:  # the same act twice: keep both, labelled, as the built-in days do
            seen[act] += 1
            act = f"{act} (listing {seen[act]})"
        else:
            seen[act] = 1
        rows.append({"stage": stage, "act": act, "start": start, "end": end})
    if len(rows) < 4:
        raise ValueError("Paste at least four sets.")
    if len(rows) > MAX_SETS:
        raise ValueError(f"At most {MAX_SETS} sets per day.")
    stages = list(dict.fromkeys(r["stage"] for r in rows))
    if not 2 <= len(stages) <= 12:
        raise ValueError("Use between 2 and 12 stages.")
    for st in stages:  # sets on one stage may not overlap
        ss = sorted((ov.minutes(r["start"]), ov.minutes(r["end"]), r["act"]) for r in rows if r["stage"] == st)
        for (a0, a1, a), (b0, b1, b) in zip(ss, ss[1:]):
            if b0 < a1:
                raise ValueError(f"On {st}, {a} and {b} overlap; one stage plays one set at a time.")
    clean = (name or "My festival day").strip()[:80]
    return {"name": clean, "note": "Your own lineup. House rules: headliners keep closing their stages and no act moves "
                                   "more than two hours from its billed time.",
            "source": "pasted by the user", "stages": stages, "sets": rows,
            "rules": {"headliners_close": True, "billing_window": 2}}


def save(fest):
    """Store the lineup and return its slug (the same content always gets the same slug)."""
    os.makedirs(DIR, exist_ok=True)
    body = json.dumps(fest, sort_keys=True, ensure_ascii=False)
    slug = "custom-" + hashlib.sha256(body.encode()).hexdigest()[:12]
    with open(os.path.join(DIR, slug + ".json"), "w", encoding="utf-8") as f:
        f.write(body)
    return slug


def path(slug):
    return os.path.join(DIR, slug + ".json")
