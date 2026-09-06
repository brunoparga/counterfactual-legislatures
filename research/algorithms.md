# Other districting algorithms worth reproducing

Shortest splitline is one point in a space, and not an especially defensible
one — its own author presents it as a *bright-line* rule rather than a good
map. Its virtues are that it is deterministic, has no free parameters, and can
be described in two sentences. Its vices follow from exactly the same facts.

This surveys what else exists, ordered by how much it would add to this
project relative to what it costs to implement.

A distinction that organises the whole field:

- **Single-answer methods** produce one map from the data. Splitline,
  BDistricting, and integer-programming optima are of this kind. They answer
  "what would a neutral rule produce?"
- **Ensemble methods** produce thousands of maps and use the *distribution* as
  the null hypothesis. They answer "is the enacted map an outlier among
  legally acceptable maps?" — which is the question courts actually ask, and
  the one this project currently cannot answer at all.

The second family is where the academic and legal centre of gravity has been
since about 2018. Adding one ensemble method would do more for the project's
credibility than adding three more single-answer ones.

---

## 1. BDistricting / `redistricter` — Brian Olson

- Repo: `github.com/brianolson/redistricter` — C++/Java/Python/Go
- Site: `bdistricting.com`
- **Licence: none declared.** GitHub reports no licence file. Without one,
  default copyright applies and we may not redistribute or build on the code.
  This must be resolved before any use beyond reading it.

The closest sibling to splitline, and the natural first comparison. Instead of
recursive bisection it runs a single-objective optimisation: minimise the
average distance from a resident to their district's centre. That is a
defensible definition of compactness (it is essentially a k-means/centroidal
Voronoi objective under a population measure) and it produces visibly more
"natural" maps than splitline without introducing any political input.

**Why it matters here specifically:** it isolates *which* neutrality we care
about. Splitline and BDistricting are both blind to party and race; they
disagree substantially about what the map should be. Running both on the same
census data would show how much of "the neutral map" is the neutrality and how
much is the particular rule — which is the central methodological objection to
single-answer methods, and we currently have no answer to it.

Effort: moderate. The objective is simple enough to reimplement in our own
engine (we already have block populations and a projection), which also
sidesteps the licence problem entirely. Reimplementing a published *method* is
not a derivative work of someone's *code*.

## 2. ReCom / GerryChain — MGGG Redistricting Lab

- Repo: `github.com/mggg/GerryChain` — Python, licence reported as
  non-standard (`NOASSERTION`); needs reading before use
- Method paper: DeFord, Duchin, Solomon, "Recombination: A family of Markov
  chains for redistricting", arXiv:1911.05725

The dominant ensemble method. A state is a graph of precincts; a step merges
two adjacent districts, draws a random spanning tree over the merged region,
and cuts one edge to re-split it into two population-balanced halves. Because
each step destroys and rebuilds an entire boundary, the chain mixes far faster
than the older single-precinct "flip" chains, which is what made ensembles
practical.

**Why it matters here:** it converts "the splitline map elects 231 D" from an
isolated number into a percentile. If splitline sits at the 4th percentile of
50,000 neutral maps, that says something quite different from sitting at the
50th — and it is the same statistic expert witnesses put in front of courts.

Effort: high if we adopt GerryChain (it wants precinct adjacency graphs, which
we do not have and which are fiddly to build correctly), lower if we
implement ReCom over our own block data. Adjacency is the real cost.

## 3. `redist` / ALARM Project — Imai, Kenny, McCartan, Simko

- Repo: `github.com/alarm-redist/redist` — C++/R, **GPL-2.0**
- Talk in `usa/upstream/RDH22.pdf`

The statistically most careful of the ensemble tools. Rather than MCMC it uses
sequential Monte Carlo with importance weights, which gives samples from a
*specified* target distribution instead of from whatever a chain happens to
converge to — a real advantage when the question is "is this map an outlier",
because the answer depends entirely on what distribution it is an outlier
from.

The ALARM project also publishes **50-state precinct-level datasets and
pre-computed ensembles**, which is arguably more valuable to us than the
algorithm: it is a ready-made baseline we could compare our maps against
without running anything.

**Licence caution:** GPL-2.0 is copyleft. Linking our code to `redist` would
impose GPL on the result, which conflicts with the Apache-2.0 the engine
carries. *Using its published data*, or comparing against its published
ensembles, carries no such problem. Prefer the data.

## 4. SFSR / SFSR-G — Haas, Hachadoorian, Kimbrough, Miller, Murphy

- Method paper: "Seed-Fill-Shift-Repair: A redistricting heuristic for civic
  deliberation", *PLoS One* 2020, PMC7485828
- Application: Haas, Miller, Kimbrough, "An algorithmic approach to
  legislative apportionment bases and redistricting", *Electoral Studies* 79
  (2022) 102520 — PDF in `usa/upstream/`
- Repo: `github.com/Computational-Redistricting/Redistricting_SFSRG` —
  licence `NOASSERTION`, needs reading

Three phases: seed districts at random precincts and grow them until
everything is assigned (contiguity holds by construction); shift boundary
precincts until populations balance within ±1%; repair any contiguity breaks.
Simple, and deliberately so — the authors' argument is that a *plurality* of
plausible maps is the right input to public deliberation, not one optimum.

**Directly relevant to us for a second reason.** The *Electoral Studies*
paper uses SFSR-G to ask what happens if the apportionment basis changes from
total population to citizen voting-age population, and measures the answer in
**minority-majority and minority-opportunity districts** — the same metric
`usa/tools/demographics.py` now computes. Their finding is that the switch
reduces both. That gives our demographic numbers an external methodological
precedent and a comparison point, and their Pennsylvania corpus (11,206 plans)
is a published benchmark.

## 5. Fair-division redistricting — Tucker-Foltz

- `usa/upstream/JamieTuckerFoltzDissertation.pdf`, Harvard 2025,
  "Algorithms for Fair Redistricting"

A genuinely different framing: instead of asking a neutral rule to produce a
map, give the two parties a *protocol* whose equilibrium is fair — the
cake-cutting move of "I cut, you choose", generalised to maps. The guarantee
is game-theoretic rather than geometric: neither side can complain, because
each had the chance to act.

The dissertation covers three things we care about, in this order of
usefulness to us:

1. **Randomised apportionment** with fairness guarantees and without the
   cross-state correlations that deterministic rounding introduces — directly
   applicable to our existing Huntington-Hill work, and to the Brazilian and
   Spanish floor/ceiling questions.
2. **Provably fair map-drawing** via cake-cutting protocols.
3. **Sampling theory** for ensembles — the theoretical underpinning for §2–3.

Effort: high, and the payoff is conceptual rather than another map. Worth
reading before we make claims about what "fair" means.

## 6. Compactness-optimal integer programming

- Validi & Buchanan and successors; also Barnes & Solomon on Voronoi/power
  diagrams

Solve for the genuinely optimal map under a stated compactness objective, by
branch-and-cut, with contiguity as explicit constraints. Now tractable at
county level for most states, still not at block level for large ones.

**Value to us:** it bounds the others. If splitline's compactness is 0.31 and
the proven optimum is 0.34, splitline is nearly optimal and its critics must
argue about the objective, not the search. If the optimum is 0.55, splitline
is simply a poor optimiser and says so. That is a cheap, decisive result — one
number per state — and it needs no ensemble machinery.

## 7. The institutional baselines

Not algorithms, but the correct controls:

- **Iowa**: nonpartisan Legislative Services Agency draws maps on **whole
  counties**, with no political or incumbency data, and the legislature votes
  them up or down. The most successful real-world neutral procedure, and the
  county constraint makes it easy to reproduce.
- **Independent commissions** (AZ, CA, MI, WA).
- **Proportional benchmark**: seats simply in proportion to statewide vote.
  Not a districting at all, but it is the implicit standard everyone measures
  bias against, and we should report it explicitly rather than leave it
  implied.

---

## Recommendation

In order:

1. **The proportional and Iowa-style baselines**, because they cost almost
   nothing and make every existing number interpretable.
2. **BDistricting's objective, reimplemented** — the direct test of whether
   "neutral" is one thing or many, with no licence entanglement.
3. **ALARM's published ensembles as a comparison set** — buys the percentile
   framing without our building or running an ensemble.
4. **Our own ReCom over block data**, only if 3 proves insufficient. This is
   the expensive one, and the adjacency graph is most of the cost.

Licence position, in short: reimplement methods from papers, use published
data, and do not link GPL code into an Apache-2.0 engine. Two of the four
repos here have no usable licence declared at all, which settles the question
in the same direction.
