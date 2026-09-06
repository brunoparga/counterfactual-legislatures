# From a different legislature to a different world

The project can now say what a legislature would have looked like. Saying what
it would have *done* is a much harder claim, and the gap between the two is
where this kind of work usually goes wrong. This file is about closing that
gap honestly, and about which literatures supply which link in the chain.

## The chain, and where it breaks

    districts  ->  seats  ->  votes in the chamber  ->  policy  ->  outcomes
                     (1)            (2)                  (3)         (4)

1. **seats**: done, and measurable. This is the part we control.
2. **votes in the chamber**: tractable, because roll calls are published and
   party discipline is measurable rather than assumed. This is the next thing
   to build, and it is mostly data engineering.
3. **policy**: hard. A bill passing is not a policy taking effect; agenda
   control, the Senate, the filibuster, the presidency and the courts all sit
   in between. This is where over-claiming happens.
4. **outcomes**: this is where the causal-inference literature lives, and it
   is the *only* link with a mature body of credible effect sizes.

The temptation is to chain all four and announce that splitline districting
would have saved N lives. That number would be indefensible: the uncertainties
multiply, and step 3 in particular has no honest point estimate.

**The defensible version stops at step 2 and reports step 4 separately.** "This
bill failed 214–221 on a near-party-line vote; under splitline districting the
chamber was 231–204 the other way; the literature on this class of policy
reports an effect of X." Three linked facts, each independently sourced, with
the join left explicit for the reader. That is a real finding. "Splitline
districting would have added 0.4 years to US life expectancy" is not.

---

## Step 2: which votes could have flipped

This is the piece to build first, and it is cheap.

**Data.** Voteview (`voteview.com/data`) publishes every congressional roll
call since 1789: member votes indexed by ICPSR ID, with party, state,
district, and DW-NOMINATE coordinates. CSV and JSON, updated live. Cite as
Lewis, Poole, Rosenthal, Boche, Rudkin & Sonnet, *Voteview: Congressional
Roll-Call Votes Database*. Licence needs confirming from the site before we
redistribute anything derived from it.

**The screen.** A seat swing flips a vote only if the vote was both *close*
and *party-divided*. Both are computable directly:

- **Margin**: |yea − nay| ≤ the modelled seat swing. Our 2012 result is
  231–204 splitline against 234–201 actual, a swing of ~22 seats, so the
  screen is roughly "decided by fewer than 25 votes".
- **Party division**: the Rice cohesion index per party, or simply the share
  of each party voting yea. A vote where both parties split evenly does not
  respond to a change in party composition, however close it was.

Applying both filters to every roll call of a congress yields a short list —
usually a few dozen out of a thousand-plus — of votes where the districting
plausibly determined the outcome. **That list is itself the deliverable**, and
it is honest in a way a simulated chamber is not: it enumerates the specific
decisions at stake rather than asserting a counterfactual outcome.

**The assumption to be explicit about.** Converting "22 more Democratic seats"
into "22 more yea votes" assumes a replacement member votes like their party's
median. That is a strong assumption and it is *measurable*: members from
marginal districts defect more often than members from safe ones, and
DW-NOMINATE plus district partisanship lets us estimate the defection rate
instead of assuming zero. The honest output is a distribution over outcomes,
not a flipped bit.

**Equivalents in the other five countries** — all published, all open:

| Country | Roll-call source | Note |
|---|---|---|
| Germany | Bundestag *namentliche Abstimmungen* (Excel); abgeordnetenwatch API, **CC0** | only recorded votes, a minority of the total |
| France | `data.assemblee-nationale.fr` — *scrutins*, JSON per legislature | good coverage |
| UK | Commons Divisions via Parliament's API; TheyWorkForYou / PublicWhip | very complete, strong whipping |
| Brazil | Câmara `dadosabertos` — *votações* with per-deputy positions | good coverage |
| Spain | Congreso *votaciones* | published, format needs checking |

Party discipline differs enormously across these — the UK and Germany are near
100%, Brazil's is famously low and coalition-driven — which means the
"replacement member votes with their party" assumption is nearly free in some
countries and untenable in others. That variation is itself a finding worth
reporting.

---

## Step 4: policies with credible measured effects

The user's archetype — tobacco control reducing cancer — is a good one
precisely because it is unusually clean: a well-identified intervention, a
long follow-up, a specific outcome, and effects large enough to see through
the noise. Most policy does not look like that. The realistic yield here is
**a small number of policy families**, not a general catalogue.

### Normative frames (what counts as "good")

Use published, canonical indicator sets rather than inventing one:

- **UN Sustainable Development Goals** — 17 goals, 169 targets, ~230
  indicators, with a maintained global database. The MDGs (2000–2015) are the
  predecessor and have the advantage of being *closed*, so outcomes are known.
- **Human Development Index** (UNDP) and its inequality-adjusted variant.
- **WELLBY** (wellbeing-adjusted life years) — the frame used by the World
  Happiness Report and increasingly by UK government appraisal. Attractive
  because it puts health, income and subjective wellbeing in one unit.
- **OECD Better Life Index**, **Social Progress Index** — alternative
  weightings, useful as robustness checks rather than as the primary frame.
- **DALYs** from the Global Burden of Disease study (IHME) — the standard unit
  for health effects, with country-year estimates free to download.

Using two or three of these rather than one is the right call: if a policy
looks good under SDG indicators, DALYs *and* WELLBYs, the conclusion does not
depend on the weighting.

### Policy families with the strongest evidence

Ordered by how well-identified the effect is:

1. **Tobacco control.** Taxation, smoke-free laws, advertising bans, plain
   packaging. Cross-national evidence covering 48 countries finds significant
   reductions in male lung-cancer mortality in 46 of them; the WHO MPOWER
   framework gives a standardised policy index that can be matched to
   legislative events. Long lags (decades) are the main complication.
2. **Alcohol pricing and availability.** Minimum unit pricing in Scotland is a
   near-textbook natural experiment with a clean control (England).
3. **Cash transfers**, conditional and unconditional. The largest
   randomised-evidence base in development economics; Brazil's *Bolsa Família*
   is directly relevant to one of our six countries and is unusually
   well-studied.
4. **Health insurance expansion.** The Oregon Health Insurance Experiment is
   an actual randomised trial; Medicaid expansion under the ACA is a
   staggered-adoption design across states, and states' decisions were
   sharply party-determined — which makes it *both* a measured-effect case and
   a party-cleavage case.
5. **Lead abatement**, **clean-air regulation**, **water fluoridation**. Large
   effects, long literatures, and the exposure varies geographically in ways
   that support quasi-experimental designs.
6. **Early-childhood education.** Perry Preschool and Abecedarian are small
   and old but randomised; the effect sizes are large and much-cited.
7. **Minimum wage.** Included deliberately as the case where the literature is
   genuinely contested. Useful as a discipline: a project that only picks
   policies with settled answers is selecting on the outcome.

**The binding constraint is not the effect-size literature — it is the join.**
We need cases where (a) a specific bill was voted on, (b) the vote was close
and party-divided, and (c) the policy belongs to a family with credible
measured effects. Each condition alone is easy; all three together will yield
few cases, and the user's expectation of a wide net is correct. Casting that
net is exactly what the Voteview screen in step 2 automates.

---

## "Who gets their way": the representation literature

The finding the user cites is **Gilens & Page (2014)**, "Testing Theories of
American Politics", *Perspectives on Politics* 12(3), on 1,779 policy issues:
economic elites and business-oriented interest groups have substantial
independent impact on policy, while average citizens have "little or no
independent influence".

**It should be cited with its critiques, because they are substantive and
partly successful.**

- **Branham, Soroka & Wlezien (2017)**, "When Do the Rich Win?", *Political
  Science Quarterly* 132(1): rich and poor agree on the large majority of
  issues; where they disagree, the rich win only slightly more often. The
  inequality that does exist is mostly *negative* power — the affluent
  blocking what the poor want, rather than getting things the poor oppose.
- **Enns (2015)**, in *Research & Politics*: conditioning on preference *gaps*
  inflates apparent class conflict, since groups usually rank policies
  similarly even when absolute support differs.

The defensible synthesis is narrower than the headline but more useful to us:
**the poor's distinct preferences are disproportionately blocked, and blocking
happens in legislatures.** That is precisely the mechanism a districting
counterfactual can speak to, since it changes who holds the veto points. It
also suggests the right thing to look for is *failed* legislation rather than
passed legislation — which agrees with the user's instinct about near-misses.

Comparative equivalents: Elsässer, Hense & Schäfer on Germany; the *Unequal
Democracies* project (Geneva) covers several of our six countries with
comparable designs.

---

## Surveyed opinion: the cheapest data in this file

The user is right that subjective data is far easier to get than measured
effects, and there is one dataset that fits this project unusually well.

**Cooperative Election Study (CES/CCES)**, `cces.gov.harvard.edu` — 50,000+
respondents per cycle, stratified for **congressional-district-level**
analysis, and, crucially, it asks about *the specific policy issues on which
Congress has taken roll-call votes in the preceding two sessions*. That is the
exact join we need: district opinion on one side, the member's actual vote on
the other.

With MRP (multilevel regression and poststratification) the CES supports
estimating opinion for *arbitrary* geographies — including our counterfactual
districts, since MRP poststratifies on demographics we can compute from census
blocks for any district we draw. `ccesMRPprep` (Kuriwaki) provides the
plumbing. This is the single most promising unexplored direction in this file:
it would let us say what a splitline district's *constituents* wanted, not
just how they voted for president.

Other countries: **Eurobarometer** (all four European countries, harmonised,
free), **ISSP** and **World Values Survey** (all six), **Latinobarómetro**
(Brazil), **British Election Study** and **German GLES** (large national
studies with fine geography).

---

## What to build next, in order

1. **The Voteview near-miss screen.** Cheap, self-contained, needs one
   download, and produces a concrete list of decisions our seat counts bear
   on. Nothing else here is worth much until this exists.
2. **Defection modelling** using DW-NOMINATE against district partisanship, to
   replace the party-line assumption with an estimated distribution.
3. **CES/MRP opinion by counterfactual district** — the most novel thing
   available, and it reuses the block demographics we already compute.
4. **The effect-size table**, built only for the policy families that survive
   step 1. Citations and numbers, never redistributed papers: an effect size
   is a fact and facts are not copyrightable, which is already the position
   recorded in `LICENSE-DATA.md`.
