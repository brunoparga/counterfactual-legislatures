# The 9-hour unattended run

Written for a fresh session with no prior context. Read `RUN_STATE.md` for
where things stand, this for what to do. Work the phases in order; each one
commits on its own, so stopping between phases loses nothing.

## Orientation

`REPRODUCING.md` describes the whole pipeline. In short: `shared/` is
country-neutral, `usa/` and `brazil/` know about local formats, `usa/plans/`
holds the cut trees (the actual artifact), `usa/results/` and
`brazil/results/` hold scorings and findings.

Useful facts you would otherwise rediscover:

- **1,428 plans.** Three of the four model x metric combinations are complete
  at 446 each: `uniform_span`, `point_span`, `uniform_land`. `point_land` does
  not exist. Do not generate it — that is hours of engine time and the other
  three already vary each axis independently.
- **The validated answer**: scoring the enacted 113th-Congress plan with 2012
  presidential votes returns exactly **209 D / 226 R**. That is districts Obama
  carried, not seats won — Democrats won 201 seats that year.
- `usa/results/index.json` lists every scoring already computed.

## Environment

- Shell is **zsh**. Unquoted `$VAR` does not word-split. `cp`/`mv` are aliased
  to `-i` and will hang non-interactively — use `/bin/cp` or `-f`.
- **No sudo, and pip is externally managed.** numpy, scipy and PIL are
  available; pandas and openpyxl are not. For xlsx, use
  `libreoffice --headless --convert-to csv`.
- **census.gov blocks automated clients.** Everything census comes through the
  Wayback CDX index with the `id_` replay suffix — see
  `usa/tools/fetch_census.py`.
- Scratch goes in `usa/work/` (gitignored), never `/tmp`.
- Long jobs: run with `nohup nice -n 19 ... &` and log to `usa/work/`.

## Standing rules

1. **Never `git push`.** Commit freely; pushing needs Bruno's explicit yes.
2. Do not delete or overwrite existing results.
3. Commit after each phase and update the phase table in `RUN_STATE.md`.
4. **Every phase has a validation gate with a known right answer. If the gate
   fails, stop that phase, record the failure in `RUN_STATE.md`, and move to
   the next one.** Do not publish numbers from an implementation that cannot
   reproduce a known result.

---

## Phase 1 — Does the headline survive its parameters? (~2.5h)

The central US claim is that splitline removes **65% of the measured
pro-Republican bias** (mean absolute bias 3.00 -> 1.04 across four contests).
That rests on one parameter set: `fixed` house size, `span` metric, `uniform`
population model. If the result swings under other choices, we need to say so.

Run `usa/tools/score_matrix.py` over the three available model x metric
combinations and the three house-size rules, keeping `--enacted` so each has
its baseline:

```
python3 tools/score_matrix.py --enacted --model uniform --metric span --out results/sens/uniform_span
python3 tools/score_matrix.py --enacted --model point   --metric span --out results/sens/point_span
python3 tools/score_matrix.py --enacted --model uniform --metric land --out results/sens/uniform_land
```

Then repeat with `--rule cuberoot` and `--rule wyoming` if time allows; the
model/metric axes matter more.

**Gate:** every run must still return 209 D / 226 R for
`enacted_cd113 / E_12_PRES`. The enacted plan does not depend on our
parameters, so a different number means the run is broken.

**Output:** `usa/results/sens/SENSITIVITY.md` — a table of bias reduction per
parameter set, and a plain statement of whether the 65% headline holds.

## Phase 2 — Is splitline actually compact? (~1.5h)

Splitline claims compactness. Measure it, using a metric that needs no district
geometry so it works for the enacted map too: **population-weighted mean
distance from a resident to their district's centroid.** This is Brian Olson's
BDistricting objective, so it also gives the comparison to his method without
touching his GPL code.

For each state: block centroids and populations come from the PL files (see
`usa/tools/demographics.py` for the readers); district assignment comes from
walking the cut tree for splitline (`walk()` in `usa/tools/block_votes.py`) and
from the cd113 equivalency file for enacted.

**Gate:** block populations per state must sum to the published state total,
as `usa/tools/pl_to_pop.py` already verifies for Colorado.

**Output:** `usa/results/compactness.json` and a short section in
`usa/results/FINDINGS.md` giving the figure for splitline and enacted 2012.

## Phase 3 — Which US votes could have flipped? (~2.5h)

The US analogue of `brazil/tools/near_miss.py` and `brazil/tools/reweight.py`,
which are working models to copy.

Data: Voteview (`voteview.com/data`) — `HSall_votes.csv`,
`HSall_rollcalls.csv`, `HSall_members.csv`. House only, congresses 113-117.

Screen for roll calls that are both **close** (|yea - nay| <= 25) and
**party-divided** (the two parties' yea shares differ by more than 50 points).
A vote where both parties split evenly does not respond to a change in party
composition however close it was.

Reweighting differs from Brazil in one way: US apportionment fixes each state's
delegation size, so splitline changes *which* districts within a state, not how
many. So for each state, resample the delegation by converting members between
parties by the splitline-minus-enacted difference, drawing their positions from
that state's observed members of the receiving party. Monte Carlo as in
`brazil/tools/reweight.py`, which is exact when nothing moves.

Our 231 vs 209 figures are presidential-vote based while the real 2012 House
was 201 D, so **apply the difference (+22) to the actual delegation** rather
than treating 231 as a seat count.

**Gate:** recomputed party totals under the actual apportionment must match the
published House composition for each congress.

**Output:** `usa/results/near_miss.json`, `usa/results/reweighted.json`, and a
section in `usa/results/FINDINGS.md`.

## Phase 4 — Spain's apportionment (~1.5h)

Create `spain/`, mirroring `brazil/`.

`spain/tools/fetch_ine.py` — population by province from INE's API (same shape
as `brazil/tools/fetch_ibge.py`, which uses IBGE's SIDRA).

`spain/tools/apportion_es.py` — LOREG art. 162: 2 seats per province (100) plus
1 each for Ceuta and Melilla (2) = 102 fixed, and the remaining **248 by Hare
quota with largest remainders** on the reference population. Then the
counterfactuals: floor removed (**use a floor of 1, not 0**), Sainte-Lague in
place of D'Hondt, and a single 350-seat national district.

Elections: **2008 onward.**

**Gate:** the implementation must reproduce the official province-by-province
distribution published in the royal decree convoking each election. If it does
not, stop — do not produce counterfactuals from a rule that cannot reproduce
reality.

**Output:** `spain/results/apportionment.json`, `spain/README.md`.

**Do not** attempt to parse Infoelectoral's fixed-width vote files unattended.
Download them and record what is there — file names, sizes, whether the record
layout spec is fetchable — and stop. There is no independent total to check a
column offset against, and that is a supervised task.

## Phase 5 — Write up and commit (~1h)

Update `usa/results/FINDINGS.md`, `RUN_STATE.md` and `SOURCES.json` for any new
source. Leave the working tree clean. Write a short summary of what ran, what
each gate returned, and what stopped, at the bottom of `RUN_STATE.md`.

## Out of scope

Pushing; deleting anything; generating `point_land` plans; parsing Infoelectoral
votes; the Rust rewrite; anything needing a judgement call that cannot be
checked against a known answer.
