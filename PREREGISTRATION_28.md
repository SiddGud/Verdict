# Test 28: does a festival timetable built on Qloo's fan-overlap scores make fewer real fans choose? Pre-registered protocol

Registered 2026-10-29, before any code for this test was written and before any artist in it was looked up in Qloo or
shown to a model. The git commit adding this file is the timestamp.

## Why

The candidate product "Clash Court" builds a festival timetable that keeps acts with the same fans apart. It rests on
two claims: that Qloo's artist-to-artist scores track how many real fans two acts share, and that a timetable
optimised on those scores puts fewer real shared fans in conflict. It also matters whether a model alone, or a model
given Qloo's scores, does as well. The team wants this checked before building.

## What had been seen before this file

The HetRec 2011 Last.fm files and their headers (user_artists, artists, tags, user_taggedartists), and the dataset
counts reported in PREREGISTRATION_27.md. Test 27's per-user results on small artists. No pair of artists in this test
has been looked up, scored or computed.

## Data and outside truth

GroupLens HetRec 2011 Last.fm (`user_artists.dat`: each user's 50 most played artists; `user_taggedartists.dat`: user
tags).

- **Eligible artist:** 40 or more listeners among the dataset's users.
- **Genres:** the 8 tags applied (by any user) to the most eligible artists, counting each artist once per tag.
- **Bills:** 10 bills. Each bill draws 3 of the 8 genres (seeded), then 10 eligible artists tagged with each genre, in
  a seeded order, skipping artists already on the bill and artists Qloo's artist search does not return under the
  same name, until each genre has 10. 30 acts per bill. Seed 28.
- **Truth for a pair (A, B):** listeners of both divided by the listeners of the smaller act (the share of the smaller
  act's fans who would have to choose).

## Arms: a score for every pair on a bill

- **Qloo:** each act as `signal.interests.entities`, the other 29 in `filter.results.entities`; the pair's score is the
  mean of the two directions (one direction if only one is returned; 0 if neither).
- **Fame:** the product of the two acts' Qloo popularity.
- **Frontier model alone** (GPT-6 Astra through CometAPI), one call per bill: "Here are the acts on a festival bill. For
  every pair, estimate from 0 to 100 how much the two acts' fans are the same people. Use the whole range." Returns
  every pair.
- **Frontier model alone, second run:** the same call again, uncached, for stability only.
- **Frontier model with Qloo:** the same call, with each pair's Qloo score shown ("taste-database overlap 0 to 1, or
  none"), "use it as you see fit".
- **Small model alone and small model with Qloo:** the same two calls on gemini-3.8-flash through Google's API.

## Measures

1. **Pair level:** for each bill and arm, the Spearman correlation between the arm's scores and the truth over the
   bill's 435 pairs.
2. **Timetable level:** each bill is placed on 3 stages by 10 slots. For each arm, a fixed optimiser (local search
   from 20 seeded random starts, swapping two acts' slots, keeping the best) minimises the arm's predicted clash: the
   sum of its scores over pairs in the same slot. The schedule is then scored on the truth (true clash). Also built:
   the mean true clash of 200 seeded random schedules ("random") and the schedule optimised on the truth itself
   ("best possible"). An arm's **gain** is (random minus arm) divided by (random minus best possible): 0 is no better
   than random, 1 is as good as possible.
3. **Stability:** the Spearman correlation between the frontier model's two runs, per bill.

Means over bills with 95% intervals from 2,000 bootstrap resamples of bills (seed 0), for each arm and for these
differences, on both pair level and gain.

## Readings (fixed)

For each difference: lower bound above 0 "above", upper bound below 0 "below", otherwise "no different".

1. **Qloo gain above 0** (lower bound): "a timetable built on Qloo's scores made fewer real fans choose than a random
   one". Otherwise "not shown".
2. **Qloo minus fame** (gain): beyond fame or not.
3. **Qloo minus frontier model alone** (gain and pair level).
4. **Frontier model with Qloo minus frontier model alone** (gain and pair level).
5. **Small model with Qloo minus small model alone** (gain and pair level).
6. **Small model with Qloo minus frontier model alone** (gain and pair level).
7. Stability is reported, with no reading attached.

## Limitations, stated before the result

The listening data is from about 2011 and holds only each user's top 50 artists, so shared fans are undercounted.
Artists with 40 or more listeners in the data are well known, so the models have read about most of them; this test
is not about small acts. Qloo may have been built partly from Last.fm data, which would favour Qloo. The bills are
drawn by genre tags, not taken from real festivals. One model of each size. 10 bills is a small sample.
