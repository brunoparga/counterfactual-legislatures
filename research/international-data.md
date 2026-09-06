# Electoral data outside the US: a survey

Scope: what exists, at what geographic resolution, under what licence, and
roughly how large. **Nothing here has been downloaded.** Sizes marked *(est.)*
are inferred from the resolution and row counts rather than measured, and are
flagged as such so nobody later mistakes a guess for a fact.

Three questions per country, because they are the three things a
counterfactual needs:

1. **Boundaries** — where are the districts, and are they even needed? (For a
   party-list system the "district" is an existing administrative unit, so
   this question is free.)
2. **Geography of the vote** — the finest unit at which returns are published.
   This is the binding constraint everywhere, and it varies by two orders of
   magnitude between these six countries.
3. **Apportionment** — can we reproduce the seat allocation from published
   population figures? This is what lets us re-run the allocation under a
   different rule, which is a separate lever from redrawing boundaries and in
   several of these countries a much more consequential one.

A note on what "finest unit" buys us. The US work needs block-level votes
because the counterfactual districts cut across counties; allocating county
totals by population produced a 30-seat error. The same hazard applies
wherever the counterfactual unit is smaller than the reporting unit. Where the
counterfactual keeps existing administrative units intact — which is the case
for Spain, Brazil, and the list tier in Germany — reporting-unit data is
exact and no disaggregation is needed at all.

---

## Canada

| | |
|---|---|
| Chamber | House of Commons, 343 seats (2023 Representation Order; 338 before) |
| System | single-member plurality — directly comparable to the US |
| Boundaries | Federal Electoral Districts, Elections Canada / StatCan |
| Finest vote unit | **polling division** — a few hundred electors |
| Licence | Open Government Licence – Canada (attribution, very permissive) |

The best case of the six. Elections Canada publishes poll-by-poll results as a
single national ZIP per general election, and polling divisions are small
enough to serve the role census blocks serve in the US.

- Poll-by-poll, 43rd GE (2019):
  `https://www.elections.ca/res/rep/off/ovr2019app/51/data_donnees/pollbypoll_bureauparbureauCanada.zip`
- By polling station, same election:
  `https://www.elections.ca/res/rep/off/ovr2019app/51/data_donnees/pollresults_resultatsbureauCanada.zip`
- Catalogued on open.canada.ca with equivalents back to the 38th GE (2004).

Size *(est.)*: ~70k polling divisions × ~6 candidates ≈ 400k rows per
election, tens of MB zipped. Small.

**Caveat that matters:** polling divisions are published as *tables*, not
polygons. Elections Canada distributes polling-division boundary files
separately and their coverage before 2015 is patchy. Without polygons a poll
has no coordinates, so it cannot be assigned to a counterfactual district.
This needs checking before Canada is called easy. Fallback is to geocode via
the polling-place address, which is published.

**Apportionment — fully reproducible, and interesting.** *Constitution Act
1867* s.51: divide each province's population by the electoral quotient
(121,891 for 2023, itself 111,166 × average provincial growth), round up, then
apply the **senatorial clause** (no province gets fewer MPs than it has
senators) and the **grandfather clause** (no province gets fewer than it had
in the 43rd Parliament, per the 2022 *Preserving Provincial Representation
Act*). Territories get one each regardless.

Those two clauses are pure floor-raising, so Canada is a clean natural
experiment in what apportionment floors cost: re-running the division without
them is a two-line change and directly measures the distortion.

---

## United Kingdom

| | |
|---|---|
| Chamber | House of Commons, 650 seats |
| System | single-member plurality |
| Boundaries | four Boundary Commissions; 2023 Review in force from 2024 |
| Finest vote unit | **the constituency itself** |
| Licence | Open Parliament Licence / OGL |

The worst case of the six, and the reason is structural rather than
bureaucratic: UK ballot boxes from different polling districts are **mixed
before counting**, deliberately, to protect the secrecy of small polling
districts. Sub-constituency results therefore *do not exist* — they are not
withheld, they were never produced.

Consequences:

- Any UK counterfactual that redraws boundaries needs *modelled* vote
  geography, not measured. The standard instrument is the Rallings & Thrasher
  "notional results" — estimates of what each *new* constituency would have
  returned on the *previous* election's votes, built from local-election ward
  data. These are the accepted currency in UK psephology and were used by the
  BBC/Sky/ITV for the 2024 election, but they are estimates, and they are not
  open data.
- Ward-level *local* election results exist and are much finer, but they are a
  different electorate, a different turnout, and often a different party
  system. Using them as a proxy is a real modelling assumption.

What *is* freely available and clean:

- House of Commons Library, "General election 2024 results" (CBP-10009):
  results by constituency and by candidate, Excel and CSV. Small — 650 rows,
  ~4,500 candidacies.
- `electionresults.parliament.uk` covers every GE and by-election since 2010.
- ONS Open Geography Portal has constituency boundaries as open data.

Size: trivial, under 10 MB for everything.

**Apportionment — reproducible.** The 2023 Review allocated 650 seats to the
four nations and the English regions by **Sainte-Laguë on the electorate**
(not population — a meaningful difference), with a hard ±5% tolerance around
the UK electoral quota and four protected constituencies (Na h-Eileanan an
Iar, Orkney & Shetland, and two on the Isle of Wight). Electorate figures are
published, so this is directly re-runnable.

**Recommendation:** the UK is the right country to study *apportionment* and
*electoral system* counterfactuals, and the wrong one to study *boundary*
counterfactuals. Redrawing UK lines honestly requires buying or rebuilding
notional results.

---

## France

| | |
|---|---|
| Chamber | Assemblée nationale, 577 seats |
| System | two-round single-member |
| Boundaries | circonscriptions législatives; last redrawn 2010 |
| Finest vote unit | **bureau de vote** (polling station) |
| Licence | Licence Ouverte / Etalab 2.0 |

Excellent, and the user's instinct to prefer the first round is right: the
first round is a near-pure preference measurement across the full party
system, while the second round is a strategic-coordination measurement on a
reduced field. First round gives the vote geography; second round is where
the *seats* are decided, so both are needed to model outcomes, but only the
first round carries the underlying partisan signal.

- 2024 legislative, round 1, by bureau de vote:
  `https://www.data.gouv.fr/datasets/elections-legislatives-2024-resultats-du-1er-tour-par-bureau-de-vote`
- Round 2 equivalent published alongside.
- The Interior Ministry publishes each election at every level — national,
  region, département, circonscription, canton, commune, bureau de vote — in
  CSV and XLSX.
- Presidential elections are published to the same resolution, and are the
  better partisan measure for the same reason presidential vote is used in the
  US: one contest, identical everywhere, no incumbency or local-deal noise.

**The geography link:** results carry an `ID_BVOTE` that joins to a published
**contours des bureaux de vote** geographic dataset. That is the crucial
piece — it means French polling stations have polygons, which Canadian
polling divisions may not.

Size *(est.)*: ~69,000 bureaux de vote × candidates. Round-1 2024 with ~4,000
candidates nationally but ~10–15 per bureau ⇒ roughly 1M rows, ~100–200 MB
uncompressed per election. Contours are a few hundred MB. Manageable.

**Apportionment — reproducible with effort.** The 2009–10 *redécoupage*
allocated seats to départements by a divisor ("méthode de la tranche")
method with a floor of two per département, plus 11 seats for French citizens
abroad. The floor is the interesting part again. France has not redistricted
since 2010 despite substantial population change, so the *malapportionment*
counterfactual (same boundaries, current population) is available without any
boundary work at all.

---

## Spain

| | |
|---|---|
| Chamber | Congreso de los Diputados, 350 seats |
| System | closed-list PR, **province** as the district, D'Hondt, 3% provincial threshold |
| Boundaries | **none needed** — provinces are fixed and predate the system |
| Finest vote unit | **mesa electoral** (individual voting table, ~1,000 electors) |
| Licence | open, Ministerio del Interior / datos.gob.es |

Methodologically the cleanest of the six, because there is no boundary
question to get wrong. The districts are the 50 provinces plus Ceuta and
Melilla, and they are not going to change. Everything interesting in Spain is
in the **allocation rule**, and that is pure arithmetic on published numbers.

- Infoelectoral download area:
  `https://infoelectoral.interior.gob.es/es/elecciones-celebradas/area-de-descargas/`
  — every national election back to 1977, at mesa level, in a documented
  fixed-width format.
- Mirrored on datos.gob.es.

Size *(est.)*: ~60,000 mesas × ~10 parties ≈ 600k rows per election; the
historical archive back to 1977 is likely a few GB in total, far less if we
take only Congress elections.

**Apportionment — fully reproducible, and it is the whole story.** *LOREG*
art. 162: 2 seats per province (100) + 1 each for Ceuta and Melilla (2) = 102
fixed; the remaining 248 distributed among the 50 provinces by population
using largest remainders. Then within each province, D'Hondt.

Spain therefore offers three independent, separable levers, each a small
arithmetic change on data we can get exactly:

1. the 2-seat provincial floor (heavily over-weights rural Soria, Teruel,
   Cuenca),
2. D'Hondt versus Sainte-Laguë (D'Hondt over-rewards large parties, and with
   many small districts the effect compounds),
3. district magnitude itself (a single national district, or regional ones).

Because the vote data is exact at mesa level and no disaggregation is needed,
**Spain is the country where we can compute counterfactual seat counts with
zero modelling error.** That makes it the natural validation case for the
whole non-US pipeline.

---

## Germany

| | |
|---|---|
| Chamber | Bundestag, **630 seats** from 2025 (2023 reform) |
| System | mixed-member proportional; 299 single-member Wahlkreise + list tier |
| Boundaries | Wahlkreise, Bundeswahlleiterin |
| Finest vote unit | **Wahlbezirk** (precinct), also aggregated to Gemeinde |
| Licence | dl-de/by-2-0 (attribution required, specific wording) |

Germany is valuable precisely because the constituency tier is *not* where
seats come from. Every voter casts a Zweitstimme (party vote) that determines
the party's total, so redrawing the 299 Wahlkreise moves *who* sits but,
under the post-2023 rules, essentially not *how many* per party. That makes
Germany a clean control: it isolates the effect of districting on
representation from its effect on proportionality.

- Open-data hub, 2025 federal election:
  `https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse/opendata.html`
- Wahlbezirk-level results published April 2025.
- Wahlkreis shapefiles published by the Bundeswahlleiterin; Länder returning
  officers publish finer geography.

Size *(est.)*: ~90,000 Wahlbezirke; the national precinct file is on the
order of a few hundred MB. Municipality-level (~11,000 Gemeinden) is a few MB
and is often enough.

**Apportionment — reproducible, and recently rewritten.** The 2023 reform
fixed the chamber at 630 and introduced *Zweitstimmendeckung*: a constituency
winner takes the seat **only if** their party's list entitlement in that Land
covers it. Overhang and levelling seats are abolished. The 5% threshold
survives, and the *Grundmandatsklausel* (3 direct wins) was struck down and
then partly restored by the Constitutional Court in 2024.

The pre-2023 and post-2023 rules applied to the *same* votes is a ready-made
natural experiment, and the threshold is a second lever with large, easily
computed effects.

**Licence caution:** dl-de/by-2-0 requires a specific attribution string. It
is compatible with CC-BY but the wording must be carried verbatim; a generic
credit does not discharge it.

---

## Brazil

| | |
|---|---|
| Chamber | Câmara dos Deputados, 513 seats (**531 from 2027**) |
| System | open-list PR, **state** as the district, D'Hondt-ish with a quota |
| Boundaries | **none needed** — the 26 states + DF |
| Finest vote unit | **seção eleitoral** (polling section) and *boletim de urna* (per voting machine) |
| Licence | open, TSE Portal de Dados Abertos |

The most extreme malapportionment of the six, by design and by constitution,
which makes it the best case for showing what apportionment rules do.

- `https://dadosabertos.tse.jus.br/dataset/resultados-2022` — results by
  município, zona and seção.
- `https://dadosabertos.tse.jus.br/dataset/resultados-2022-boletim-de-urna` —
  per-machine results; over 472,000 boletins were published for 2022.

Size *(est.)*: the boletim-de-urna archive is the largest single item in this
survey — hundreds of thousands of machines × candidates, plausibly tens of GB
per election across all offices. The by-município/zona/seção aggregate is far
smaller and almost certainly sufficient, since the district is the state and
no sub-state assignment is required. **Take the aggregate, not the boletins,
unless we specifically need sub-municipal geography.**

**Apportionment — reproducible, and the single most interesting case here.**
*Constituição* art. 45 §1: seats proportional to population, but with a
**floor of 8 and a ceiling of 70** per state. The floor and ceiling are not
incidental; they are the mechanism. Roraima (~650k people) gets 8 seats; São
Paulo (~44M) is capped at 70. A São Paulo vote is worth roughly a tenth of a
Roraima vote.

Live and unresolved, which makes it topical: the STF ruled in 2023 that seats
must be redistributed on the 2022 Census and gave Congress until 30 June 2025
to act, failing which the TSE would. Congress responded in 2025 by **enlarging
the chamber from 513 to 531 from 2027** — expanding rather than
redistributing, so that the seven states due to lose seats (RJ −4; PB, BA, PI,
RS −2 each; PE, AL −1) lose none. That is a legislature choosing its own
apportionment to protect incumbents, in the open, this year.

Brazil needs no boundary work and no disaggregation. It needs population
figures from IBGE and the state-level vote, both of which are small and free.

---

## Summary and recommended order

| Country | Boundary work | Vote geography | Apportionment lever | Verdict |
|---|---|---|---|---|
| **Spain** | none | exact (mesa) | floor, D'Hondt, magnitude | **start here** — zero modelling error |
| **Brazil** | none | exact (state suffices) | floor 8 / ceiling 70 | **start here** — largest effect, live controversy |
| **France** | yes | excellent, with polygons | département floor, stale 2010 map | strong |
| **Canada** | yes | excellent *if* polygons exist | senatorial + grandfather clauses | strong, one open question |
| **Germany** | yes | good | 630 cap, 5% threshold, 2023 reform | good control case |
| **UK** | yes | **absent by design** | Sainte-Laguë on electorate | apportionment only |

Two of the six — Spain and Brazil — need no districting algorithm at all and
no disaggregation, so they can produce defensible counterfactual seat counts
from small downloads. They should come first: they establish the pipeline and
the reporting format with no methodological risk, and they are the two cases
where the answer is arithmetic rather than estimate.

The shortest-splitline engine is only meaningful for Canada, France, Germany
and the UK, and only the first three have the vote geography to support it.
