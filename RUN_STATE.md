# Unattended run state — started 2026-09-08

**What to do is in `RUN_PLAN.md`. This file is only the status.**

Live scratchpad for a long run that may outlast a session. **A future session
should read this first and resume at the first phase not marked done.** Each
phase commits on its own, so partial completion is still useful and nothing is
lost by stopping between phases.

Nothing is pushed. Six commits were already waiting before this run began.

## Decisions taken (user approved the plan "as-is", so the stated defaults hold)

- **Spain floor:** 1 seat per province, not 0. Unlike Brazil this genuinely
  binds — Soria has ~90k people against a national quota near 135k, so a strict
  proportional split gives it zero.
- **Spain elections:** 2008 onward, where the party system fragmented and
  D'Hondt in 3-5 seat provinces began to bite.
- **Voteview:** the splitline and enacted seat counts are presidential-vote
  based (231 vs 209), while the real 2012 House was 201 D. Apply the
  *difference* (+22) to the actual delegation rather than treating 231 as a
  seat count.

## Phases

| # | Phase | Est. | Status | Gate |
|---|---|---|---|---|
| 1 | US parameter sensitivity | 2.5h | **DONE** | PASSED for the 3 model/metric sets; FAILED for the 2 house-size rules, cause diagnosed |
| 2 | Compactness metrics | 1.5h | **DONE** | PASSED -- blocks sum to the published state total in all 50 states |
| 3 | Voteview near-miss screen | 2.5h | **DONE** | PASSED -- composition matches for all five congresses; tallies match on all 5,679 roll calls |
| 4 | Spain apportionment | 1.5h | **DONE** | PASSED -- all seven decrees reproduced 52/52 provinces |
| 5 | Write-ups and commits | 1.0h | **DONE** | PASSED -- working tree clean, nothing pushed |

## The rule that makes this safe to run unwatched

**Every phase has a validation gate with a known right answer. If the gate
fails, that phase stops and records the failure here — it does not proceed to
produce numbers on an implementation that cannot reproduce reality.** A phase
that stops costs only itself; the others still run.

## Not to be done unattended

- `git push`, or any outward-facing action
- deleting or overwriting existing results
- parsing Infoelectoral's fixed-width vote files (no independent total to check
  a column offset against; that is a supervised task)
- classification judgements that cannot be checked against a known answer

## Log

- 2026-09-08 — run state created, no phase started yet.
- 2026-09-08 09:14 — **Phase 1 done.** Five scorings run under
  `usa/results/sens/`. The three model x metric sets at `fixed` house size all
  pass the 209 D / 226 R gate and put the headline bias reduction at **63-65%**,
  so it does not depend on the model or the metric. The `cuberoot` and
  `wyoming` house-size rules **fail the gate** and were stopped: the seven
  states with no DRA block file are exactly the one-district states, and a
  larger house needs two districts in them, so they drop out of every plan in
  the run including the enacted baseline. The house-size axis is not
  measurable with the election data we hold. Written up in
  `usa/results/sens/SENSITIVITY.md`; the remaining four house-size runs were
  not attempted, since they fail identically.
- 2026-09-08 09:20 — **Phase 2 done.** `usa/tools/compactness.py`, gate passed
  in all 50 states. Splitline 39.13 km against the enacted 43.50 km, 10%
  tighter, more compact in 37 of 43 multi-district states. Written up as
  section 5 of `usa/results/FINDINGS.md`.
- 2026-09-08 09:30 — **Phase 3 done.** `near_miss_us.py` and `reweight_us.py`.
  Both gates passed, plus a third: the resampling is exact at zero delta.
  2,183 candidate roll calls, 507 reverse, 371 of them in the 113th Congress.
  Section 6 of `FINDINGS.md`. Note the model has no behavioural uncertainty,
  which is stated there rather than left to the reader.
- 2026-09-08 09:35 — **Phase 4 done.** `spain/`, gate passed: the LOREG art.
  162 implementation reproduces all seven convoking decrees province by
  province, and the padron revision each decree used is identified empirically
  rather than assumed, since no decree states one. Infoelectoral was not
  touched, as agreed.
- 2026-09-08 09:50 — **Phase 5 done.** `SOURCES.json` gains three sources and
  five outputs; `REPRODUCING.md` gains steps 8-11; `README.md`'s "varying
  magnitude" placeholder is filled in now that both countries under it exist.

---

## What this run did, and what every gate returned

Six commits, none pushed. Every phase had a validation gate with a known right
answer, and one of them failed and stopped that phase, which is the outcome
the rule exists to produce.

| phase | gate | result |
|---|---|---|
| 1 | enacted 2012 returns 209 D / 226 R | **PASSED** for the 3 model x metric sets; **FAILED** for both house-size rules |
| 2 | block populations sum to the published state total | **PASSED**, all 50 states |
| 3a | recomputed yea/nay equal Voteview's published counts | **PASSED**, 5,679 of 5,679 roll calls |
| 3b | seats by party equal the published House composition | **PASSED**, all five congresses |
| 3c | resampling is exact at zero delta | **PASSED**, zero variance on every roll call |
| 4 | LOREG art. 162 reproduces each convoking decree's annex | **PASSED**, 52 of 52 provinces in all 7 elections |

### What was found

- **The headline holds.** Splitline removes 63-65% of the measured
  pro-Republican bias across all three available model x metric combinations,
  against the 65% figure that had been computed at one point in that space.
- **The house-size axis cannot be measured** with the election data we hold,
  and the gate caught it rather than letting plausible numbers through. The
  seven states DRA publishes no block file for are exactly the one-district
  states; raise the house and they need two districts, the statewide shortcut
  stops applying, and they fall out of every plan in the run including the
  enacted baseline. Recorded as a failure in `usa/results/sens/SENSITIVITY.md`,
  and the remaining four combinations were not attempted.
- **Splitline is 10% more compact** than the enacted map on distance to
  centroid, and more compact in 37 of 43 multi-district states — concentrated
  in North Carolina, Pennsylvania, Texas, Maryland and Virginia at 16-29%.
  Washington runs 30% the other way, where a commission drew the map.
- **507 of 2,183 close, party-divided House roll calls reverse**, 371 of them
  in the 113th Congress, where +22 seats is exactly what turns 201-234 into
  223-212.
- **Spain's provincial floor**, not its allocation method, is where its
  malapportionment lives. Cutting the floor from two seats to one halves the
  disproportionality index; Sainte-Lague in place of quota-and-remainders moves
  one seat in two elections of seven and none in the other five.

### What stopped, and why

- **The two house-size runs**, on their gate, as above.
- **Infoelectoral's vote files** were not touched, as agreed at the outset:
  fixed-width records with no independent total to check a column offset
  against, which makes a wrong offset produce plausible numbers rather than an
  error. That is a supervised task and it is still open.
- **`point_land` plans** were not generated, as agreed: hours of engine time
  for a fourth corner of a space whose axes are already varied independently.

### Left open

- The within-province D'Hondt to Sainte-Lague swap for Spain, which needs the
  Infoelectoral files and is the larger of the two effects.
- Enacted comparators for the 2000 and 2020 censuses, which need the block
  equivalency files for the 108th-112th and 118th Congresses.
- The roll-call model has no behavioural uncertainty: it resamples which
  members sit, not how a different member would have voted. Stated in
  `FINDINGS.md` rather than left for a reader to infer.
