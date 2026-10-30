# Clash Court

Every show fights for the same fans. Clash Court maps who shares fans across live music, using Qloo's taste graph
and real listings, so shows stop fighting over the same people and start finding them. Entry for the Qloo Agentic
Hackathon 2026 by Athmeeya M Kashyap and Siddhant Gudwani.

## The site

- **Festival court** (`/`, the front page): the court, the timetable you can drag, emergencies, your own lineup, and
  the bill drawn as Qloo sees it.
- **For fans** (`/#/fans`): plan your day at the festival, and a month of nights out with friends.
- **For promoters** (`/#/promoters`): the city desk (book a date, promoter portfolio, openers and tour).
- **Why Qloo** (`/#/why`): what Qloo adds on each festival day, and Test 28.

Each page says what it is for, how to use it, and gives examples to try. "Ask the court" (the chat) is on every page.
The earlier one-page version is kept at `/classic`.

## What it does

- **The bill as Qloo sees it.** Every act on the day drawn as a photo, pulled toward the acts its fans share (a force
  layout over Qloo's pair overlap). Pink lines are pairs on at the same time; switch to "After the court" and watch
  them go (9 pairs to 1 on Lollapalooza Thursday 2024).
- **Festival court, argued by working agents.** A real Lollapalooza day (published set times). Qloo scores how much
  every pair of acts shares fans. For every red clash, two fan agents (one per act) call tools on Qloo's
  overlap and the timetable and each propose a concrete move; the booker agent checks every proposal with a rules
  tool, objects to the ones that break a rule and may counter-propose a legal one; the judge agent compares them with
  a scoring tool and rules. Code verifies every move (a rule-breaking choice is never applied), the chosen move is
  made at once, and the optimiser then tidies the rest of the day with the agents' moves pinned. The page reports
  both scores honestly (on Lollapalooza Thursday 2024 the agents argued all 10 red clashes and made 9 moves, 3 proposed by fan agents and
  6 by the booker, 6 of them moves the optimiser alone would not have made: 10.85 to 5.92, against 5.45 for the
  optimiser alone). Recorded
  sittings replay instantly; "Run the agents live" sits again (about 3 minutes), with clash arcs linking the sets that
  share fans until the court separates them (about half the clash on Lollapalooza
  Thursday 2024, every rule kept). The booker can type emergencies ("Tyla just cancelled").
- **Bring your own lineup.** Paste one set per line (stage, act, start, end); every act is matched in Qloo (Last.fm
  where Qloo has none), the overlap is scored, and the day opens like a built-in one.
- **What Qloo adds, on this day.** Coverage and identity (IDs, photos), how a model with no Qloo changes its scores
  when asked twice, what each side does not know, and cost; accuracy stated as Test 28 found it (a tie).
- **You decide.** Drag any set to another slot: before you drop, the slot shows in red or green whether that act's
  fans would clash there, and with whom. The move is re-scored, any house rule it breaks is listed, Undo puts it back,
  and the act stays pinned where you put it when the court plans the rest. Clashes show in red.
- **City desk.** A city's month of music shows on sale (Ticketmaster; any US city, with New York and Chicago in
  November 2026 loaded ahead on the demo so every answer is quick; `CITIES_READY` sets the list):
  - Book a date: the nights where an artist's fans are pulled least, rivals to avoid, partners to market alongside.
  - Promoter portfolio: which of one promoter's shows compete on the same night, which to sequence, which to co-promote.
  - Friends' month: the group's month as a plan on a calendar: dated nights out, who goes to each (shows they would
    love, about their top tenth of the month), nights for the whole group first, each person's own nights when nobody
    shares their taste, the other show that night, and tickets.
  - Openers and tour: a language model suggests openers and orders tour cities; Qloo and Ticketmaster check them.
- **Your day.** A fan names favourite artists and gets a route through the festival; clashes they cannot avoid are
  filed with the court.
- **Ask the court.** A conversational agent: ask anything about the festival day, a city's month or the evidence. The
  model chooses its tools (Qloo overlap, the timetable, Ticketmaster listings, Test 28); each call appears as it runs;
  every number in the answer is checked against the tool results. A booker order it issues replays the court.
- **The map.** On the city desk the agent flies venue to venue through the shows that pull hardest on an artist's
  fans, then the month's calendar fills in; promoter pairs are drawn as lines; a tour is drawn as a route.
- **With and without Qloo.** Test 28 shown both ways: Qloo far beyond popularity, level with a frontier model, best
  when the two work together; and where the model leads instead.

## Try it in 2 minutes

Press "Watch the 2-minute tour" on the page (or open `/?watch=1`): the court sits, the city desk reads New York for
Clairo, a promoter's portfolio is drawn, and the agent answers a question. Other demo links: `/?convene=1`,
`/?book=Clairo`, `/?portfolio=1`, `/?friends=1`, `/?ask=Who shares the most fans with Hozier?`.

## Where every number comes from

| Source | Used for |
|---|---|
| Qloo `/search`, `/v2/insights` | Matching acts; fan overlap between acts and between a fan's favourites and every act |
| Last.fm `artist.getsimilar` | Fan overlap for the few acts Qloo does not hold (labelled on the page) |
| Ticketmaster Discovery | Shows on sale in each city, with venue, date and promoter |
| Language model (CometAPI) | Reading plain-word booker orders the patterns miss; openers; tour city order |

The model leads only where our pre-registered tests found it better than Qloo (openers, tour cities), and is labelled.

## Evidence (pre-registered Test 28)

On 10 bills of 30 real artists, judged on how many listeners each pair truly shares (Last.fm):

| Who scores fan overlap | Matches real fans | Timetable quality |
|---|---|---|
| Qloo alone | 0.72 | 0.66 |
| Popularity only | 0.39 | 0.04 |
| Frontier model alone (GPT-6 Astra) | 0.70 | 0.67 |
| Frontier model with Qloo | 0.73 | 0.70 |

Qloo matches a frontier model and is far beyond popularity; adding Qloo made both models' scores closer to real fans;
timetables were not shown to be better than the model's alone. Protocol: PREREGISTRATION_28.md. Log: PROJECT_LOG.md.

## Run it

```
python -m venv .venv
.venv\Scripts\activate            (Windows; on macOS or Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env             then fill in QLOO_API_KEY, TICKETMASTER_API_KEY, LASTFM_API_KEY, COMET_API_KEY
uvicorn app:app --port 8000
```

Open http://localhost:8000. Engine tests: `PYTHONPATH=. python tests/test_clash_schedule.py`.
The page is open to anyone (no login), so model calls are limited per visitor per hour and capped per day
(`DAILY_USD`, default 5); tools that need no model keep working when the cap is reached.
Replies from Qloo, Ticketmaster and Last.fm are cached in `cache/` (git-ignored; Qloo data never goes in the repo).

## Code

- `app.py`: the server. `clash/`: `overlap.py` (matching, pair table, Last.fm fill), `schedule.py` (clash score,
  rules, optimiser), `agents.py` (booker, fan agents, court cases), `fanroute.py`, `city.py`, `booking.py`,
  `ask.py` (the conversational agent), `guard.py` (limits), `api.py`, `city_api.py`, `festivals/` (real set times).
  `static/`: the page (`court.js` the court, `city.js` the city desk and map, `ask.js` the agent panel, `tour.js`).

MIT licence.
