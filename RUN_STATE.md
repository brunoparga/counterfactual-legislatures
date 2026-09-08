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
| 5 | Write-ups and commits | 1.0h | NOT STARTED | working tree clean, nothing pushed |

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
