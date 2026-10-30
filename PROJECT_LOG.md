# Clash Court: project log

Decisions, build findings and test results for Clash Court. Sections keep the numbers they had in the shared
log (sections 1 to 50 are the the earlier project project and the Qloo tests that led to this idea; they live in the
the earlier project log). Test 28's code runs from the the earlier project folder (backtest28.py imports its test helpers).

## 51. The pick and the build: Clash Court (Oct 28 to 29)

**How the idea was chosen.** IDEAS_1000.md (1,000 ideas in eight areas) and a long round of brainstorming, with two
outside critiques from DeepSeek, ended in IDEAS_FINAL.md: 64 ideas from the whole project scored on real-world need,
demo strength, how agentic, Qloo depth, open lane and buildability (real world and Qloo depth count double). The
team asked for a real business problem, not a personal convenience, and for agents that argue. Clash Court ranked
first (9.0). DeepSeek's critique that it would be "a data engineering project shown as a spreadsheet" and that
"without Qloo fails" because a model knows famous pairs was accepted in part: Qloo depth was lowered from 5 to 4,
the design gained a chat for the booker, fan agents with a voice, a fan route and live disruption, and the score
fell to 8.5, tied with Opening Night. The team chose Clash Court.

**What it is.** An AI war-room that builds a festival timetable so fans do not have to choose between two acts they
love. Qloo scores how much every pair of acts on a bill shares fans; code moves sets to keep those pairs apart within
the booker's rules; agents read the booker's words and explain each move; a fan side plans one person's day.
Code: clash/ (overlap, schedule, agents, fanroute, baseline, api), static/clash.*, tests/test_clash_schedule.py
(8 tests). It is now the site's front page; the earlier project moved to /whitespace.

**Findings while building (in the order they came up).**
1. *Qloo's raw affinity is bunched.* On a 40-act test bill, 780 pairs sat in a narrow high band, so unrelated acts
   and near-twins scored close together (raw values are Qloo data and are not published here). Summed raw, the optimiser could cut clashes by only 1% (46.9 to 46.5).
   Fix: rank each act's scores within the bill, average both directions, cube (near-twins dominate). The optimiser
   then cut clashes by 34%. This rescaling is a product choice, not something a test chose; Test 28 scores Qloo's
   raw mean, as registered.
2. *Search returns a list.* /search returns `results` as a plain list; qloo._status assumed a dict and crashed when a
   trace was set. Fixed in qloo.py.
3. *Signal artists drop out.* Qloo leaves the signal entities out of insights results, so a fan's own favourite
   playing the festival scored nothing. Fix: a named favourite on the bill counts as a sure pick (1.0).
4. *First-improvement search stalls.* One local search left a 0.72 clash. Twelve seeded searches, best kept, lowered
   the total; some clashes stay because the billing rule (no act moves more than 2 hours) leaves no better place.
5. *Real timetables are not hourly.* The engine was rebuilt on real set times: a cell is one published set (stage,
   start, end); clash = weight x hours of overlap; a move swaps the acts in two cells; set lengths are kept within
   15 minutes. On the hourly test bill the scores were unchanged (9.43 to 6.16), as they should be.
6. *A model alone is unstable.* GPT-6 Astra, with no Qloo, asked twice to score all 780 pairs of the test bill:
   144 pair scores moved by 10 points or more, and the timetables built from the two answers differ in 24 of 40 set
   times. Qloo returns the same scores every time. The model said it knew every act on that bill. Cost $0.47.
   CORRECTION (same day): with identical Qloo scores, changing only the optimiser's seed moves 20 of 40 set times on
   the test bill (5 of 43 on the real Sunday), so "24 of 40 set times differ" was mostly the optimiser choosing
   between near-equal plans, not model instability. That claim was removed from the page and llms.txt.
9. *On a real bill the model is stable and knows more acts.* Lollapalooza Sunday, GPT-6 Astra alone, asked twice:
   only 13 of 903 pair scores moved by 10 points or more (mean change 0.026). It said it does not know 8 of 43 acts;
   Qloo has no data for 16. The model claims to know 9 acts Qloo lacks; Qloo holds 1 act the model does not know.
   So the honest "without Qloo" case rests on Test 28 (does Qloo match real co-listening better?), not on stability
   or coverage. Cost $0.58. The panel now shows these facts both ways.
7. *Qloo misses a third of a real 2026 bill.* Lollapalooza Chicago 2026, all four days (Time Out's published set
   times; Kidzapalooza left out): exact-name matches Thu 28 of 43, Fri 24, Sat 25, Sun 27, after a hand-checked
   alias pass that recovered only three names ((G)I-DLE, DJ Mustard, Trixie Mattel). Most missing acts are small
   early-afternoon sets, but some are new breakout acts (Sombr, who played the main stage on Thursday, is not in
   Qloo at all). So llms.txt no longer says Qloo covers small acts better than a model: a model may know a new act
   Qloo lacks. Missing acts are shown as "no data" and count as no clash; every "fewer clashes" figure is about the
   acts Qloo knows.
8. *Without a stage-size rule the optimiser cheats.* On the real Sunday it moved Tate McRae (main-stage closer) to
   close the mid-size Allianz stage and put small bands on the main stage, which no booker would do. A stage-size
   rule was added (main: T-Mobile and Bud Light; mid: Allianz, Tito's, Airbnb; small: BMI; Perry's locked to its
   dance acts). The grouping is the team's judgement and is stated on the page.

**Results on the real days (every rule kept; clash among the acts Qloo knows).**

| Day | Qloo matched | Published clash | Clash Court | Fewer |
|---|---|---|---|---|
| Thu Jul 30 | 28 of 43 | 3.00 | 1.99 | 34% |
| Fri Jul 31 | 24 of 43 | 5.78 | 2.84 | 51% |
| Sat Aug 1 | 25 of 43 | 5.07 | 1.79 | 65% |
| Sun Aug 2 (opens first) | 27 of 43 | 5.33 | 3.28 | 38% |

These numbers measure the timetable against Qloo's own scores, which is circular as evidence that fans gain. Test 28
(below) is the check against real listening.

**Source notes.** Only Time Out's page listed full set times (Fox 32 and WGN link to the official schedule; SeatGeek
refused the request). Each day was read twice and the reads matched. The page lists Devault twice on Thursday
(Perry's 1:45pm and Tito's 7:30pm); the second listing is kept under a label. Closing main-stage sets had no end
time; 10:00pm is assumed. All of this is written on the page.

**Test 28 (registered Oct 29, running).** PREREGISTRATION_28.md (e4d9b32), Amendment 1 (3b38674: a bill whose model
prompt a provider's filter refuses is set aside and the next seeded bill drawn), Amendment 2 (380c16c: the small
model moves from Google's API to CometAPI after repeated timeouts). Truth: real co-listening in the 2011 Last.fm
data. Arms: Qloo, fame, GPT-6 Astra alone and with Qloo, gemini-3.8-flash alone and with Qloo; measured on pair
scores and on the timetable each arm's scores produce, judged on real shared listeners. No outcome has been computed
or looked at. Interruptions so far: scikit-learn blocked by Windows Application Control (a stand-in module for an
unused import), one CometAPI policy refusal on bill 1, Google timeouts, and two CometAPI accounts out of credit (the
team confirmed each new key is from a paid account).

**Keys.** Two CometAPI keys were pasted in chat on Oct 29. Both live only in .env. Rotate them after the hackathon.


## 52. Clash Court: full act coverage (Oct 29, 2026)

The team asked for every act to have data. No real day is fully in Qloo (newcomers lag its catalogue), so:
1. New default day: Lollapalooza Thursday Aug 1, 2024 (Time Out set times; "Bensen Boone" corrected, Camden Cox's
   second listing labelled; Spinall is "DJ Spinall" in Qloo). Qloo holds 38 of 44.
2. Fallback for acts Qloo lacks: Last.fm artist.getsimilar (free API key in .env as LASTFM_API_KEY, cached in
   cache/). Last.fm's match is used directly as the clash weight. Ranking it like Qloo's scores was tried first and
   dropped: on a bill with few neighbours a match of 0.02 became a full clash (Wolves of Glendale and Daði Freyr).
3. Coverage now: 2024 Thu 44 of 44; 2026 Sun 43, Thu 43 (Devault's second listing aliased), Fri 42 (Chicago Made, a
   local showcase, has no data anywhere), Sat 43 of 43. Name risk: Saturday's "Ink" looks like a different artist.
4. Clash scores, published to ours, all rules kept (now counting Last.fm pairs, so not comparable with section 51):
   2024 Thu 10.85 to 5.45; 2026 Thu 3.53 to 2.35, Fri 5.78 to 3.01, Sat 5.11 to 1.86, Sun 5.50 to 3.30.
   (Correction: the first version of this line swapped 2026 Thursday and Sunday. These figures use the minimum move
   gain of 0.01 set in the demo pass below; at 0.005 the referee showed moves such as "5.63 to 5.63".)
6. Demo pass (Oct 30): example booker orders now come from each festival file (the old buttons named Turnstile,
   Doechii, Mitski and Clairo on every day); phone layout no longer runs off the screen; the fan route scores
   Last.fm acts too (a favourite among the act's similar artists places it at that quantile of the fan's Qloo
   scores). The "Without Qloo" panel is not yet computed for 2024 Thursday (needs model credit).
5. Not done: the fan route still scores only Qloo acts. Test 28's registered analysis is unchanged (Qloo only).


## 53. Test 28 result (Oct 30, 2026, registered analysis, PREREGISTRATION_28.md with Amendments 1 and 2)

10 bills of 30 Last.fm artists (HetRec, about 2011), none set aside. Truth: shared listeners. Pair level is Spearman
against true overlap; gain is (random minus arm) over (random minus best) on a 3-stage, 10-slot timetable.

| Arm | Pair level | Timetable gain |
|---|---|---|
| Qloo | 0.723 (0.700 to 0.747) | 0.663 (0.607 to 0.718) |
| Fame | 0.394 (0.333 to 0.453) | 0.043 (-0.066 to 0.155) |
| GPT-6 Astra alone | 0.697 (0.671 to 0.721) | 0.669 (0.634 to 0.704) |
| Astra with Qloo | 0.728 (0.707 to 0.750) | 0.702 (0.652 to 0.746) |
| gemini-3.8-flash alone | 0.695 (0.670 to 0.718) | 0.686 (0.641 to 0.724) |
| flash with Qloo | 0.723 (0.697 to 0.750) | 0.669 (0.627 to 0.712) |

Readings as registered:
1. Qloo gain above 0: "a timetable built on Qloo's scores made fewer real fans choose than a random one".
2. Qloo minus fame (gain): above, 0.62 (0.523 to 0.72). Pair level also above, 0.329.
3. Qloo minus Astra alone: no different (gain -0.006, -0.046 to 0.029; pair 0.026, -0.006 to 0.055).
4. Astra with Qloo minus alone: pair level above (0.031, 0.005 to 0.056); gain no different (0.033, 0.000 to 0.063;
   the lower bound is exactly 0, and the rule needs it above 0).
5. flash with Qloo minus alone: pair level above (0.028, 0.003 to 0.056); gain no different (-0.017, -0.06 to 0.025).
6. flash with Qloo minus Astra alone: no different (pair 0.026, -0.001 to 0.053; gain 0.000, -0.029 to 0.027).
7. Stability (no reading): Astra's two runs correlate 0.991 (0.989 to 0.992).

Plain words: Qloo alone matches a top model on real fan overlap and is far beyond popularity. Adding Qloo to a model
makes its pair scores slightly closer to real fans (both models), but the timetables built from them are not shown
to be better. The pattern of Tests 22 to 27 holds: no taste win over a top model, a small consistent nudge with Qloo.
Consequence for the page: the "Without Qloo" panel leans on run-to-run instability, but on these bills the frontier
model's two runs agree at 0.991. The instability claim should not be the headline.

## 54. The city desk, the map, Ask the court, the tour (Oct 30, 2026)

Scope widened after the team found a timetable fixer alone too narrow: one fan-overlap map answers three questions
(avoid a clash, find a partner, book a night nobody serves). City desk on Ticketmaster listings for 12 US cities:
book a date, a promoter's portfolio (Live Nation, New York, November: 1 same-night pair, 52 within a week, 34 to
co-promote), friends' month; openers and tour order led by the model (it beat Qloo in Tests 15 to 17), labelled.
Map on the earlier project's design: the agent flies venue to venue, the calendar fills in after. Ask the court: the earlier project's
follow-up pattern (model picks tools, numbers checked); three test questions answered with no unchecked numbers.
Limits for a public page: per-visitor hourly counts and a daily model spend cap (guard.py); the booker's model
fallback stops at the cap, pattern orders keep working. Guided tour (/?watch=1) checked end to end in a real browser
session: court, map sweep, portfolio, agent answer, comparison. The comparison section shows Test 28 both ways (wins,
the tie with a frontier model, where the model leads). Found and fixed while checking: tooltips rendered listing
names as HTML (now escaped), a race that could submit the portfolio before its promoter list loaded, picks at the
same venue hiding each other, and a narration bar knocked off centre by its entrance animation.

