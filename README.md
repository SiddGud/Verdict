# Clash Court

Every show fights for the same fans. Clash Court maps who shares fans across live music, using Qloo's taste graph
and real listings, so shows stop fighting over the same people and start finding them. Entry for the Qloo Agentic
Hackathon 2026 by Athmeeya M Kashyap and Siddhant Gudwani.

## What it does

- **Festival court.** A real Lollapalooza day (published set times). Qloo scores how much every pair of acts shares
  fans. The worst clashes go on trial: fan agents argue with their numbers, the booker agent objects when the
  quickest fix breaks a rule, the court rules, and the whole timetable moves (about half the clash on Lollapalooza
  Thursday 2024, every rule kept). The booker can type emergencies ("Tyla just cancelled").
- **City desk.** A city's month of music shows on sale (Ticketmaster, 12 US cities):
  - Book a date: the nights where an artist's fans are pulled least, rivals to avoid, partners to market alongside.
  - Promoter portfolio: which of one promoter's shows compete on the same night, which to sequence, which to co-promote.
  - Friends' month: the shows that suit a whole group, and whose taste is closest.
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

## Try it in 90 seconds

Press "Watch the 90-second tour" on the page (or open `/?watch=1`): the court sits, the city desk reads New York for
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
