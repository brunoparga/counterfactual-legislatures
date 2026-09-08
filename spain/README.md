# Spain

The Congress of Deputies, and what its two-seat provincial floor costs.

Spain belongs with Brazil rather than with the United States in this
repository: the constituency is the province, the provinces are not going to
move, and no districting algorithm is involved. Everything interesting is in
the allocation arithmetic — which means the counterfactual has no modelling
error in the part that matters.

    tools/fetch_ine.py       padron population by province, via INE's Tempus3 API
    tools/fetch_boe.py       LOREG art. 162 and the seven convoking decrees
    tools/apportion_es.py    the rule, the gate, and the counterfactuals
    results/apportionment.json   what came out

## The rule

LOREG art. 162 — the text is in `upstream/boe/loreg_art162.txt`, fetched from
BOE's consolidated-legislation API rather than transcribed:

1. the Congress has **350** Diputados
2. every province gets an initial minimum of **two**; Ceuta and Melilla one each
3. the remaining **248** go to the provinces in proportion to population, by
   quota and largest remainders

Two details make this not a generic Hare allocation, and both are easy to get
wrong. The quota divides the total population by **248, not by 350**, so it is
not the average population per seat. And Ceuta and Melilla are outside the
quota pool entirely — they are autonomous cities, not provinces — so folding
their 170,000 people in moves a remainder seat.

## The gate, and the thing the law does not say

Art. 162.3 says the basis is the *poblacion de derecho*. It does not say which
padron revision, and neither does any convoking decree: the decree publishes a
bare table of 52 numbers with no population figure, no date and no source. So
every decree is ambiguous on its face.

Rather than assume, `apportion_es.py` runs the rule against **every** padron
revision INE publishes and reports which ones reproduce the decree's annex
exactly. That is the validation gate. All seven elections from 2008 pass, and
the revision that works is in every case the most recent one officially
declared before the decree:

| election | padron | provinces matching the decree |
|---|---|---|
| 2008-03-09 | 1 Jan 2007 | 52 / 52 |
| 2011-11-20 | 1 Jan 2010 | 52 / 52 |
| 2015-12-20 | 1 Jan 2014 | 52 / 52 |
| 2016-06-26 | 1 Jan 2015 | 52 / 52 |
| 2019-04-28 | 1 Jan 2018 | 52 / 52 |
| 2019-11-10 | 1 Jan 2018 | 52 / 52 |
| 2023-07-23 | 1 Jan 2022 | 52 / 52 |

The match is not always unique — the 2011 annex is reproduced by the 2008,
2009 and 2010 revisions alike, because no seat happens to change hands over
those three years. Where several work the latest is recorded, which is the
legally correct one. `reference_padron_candidates` in the results keeps all of
them, so the ambiguity is visible rather than hidden by the choice.

## What the floor costs

Population per seat, 2023 election on the 1 January 2022 padron:

| | population per seat |
|---|---|
| Soria (best represented) | 44,189 |
| Madrid (worst represented) | 182,442 |
| **ratio** | **4.13** |

Madrid is **12.8 seats short** of what its population would give it under
exact proportionality; no province is more than 2.0 seats over. The
malapportionment is not symmetric — it is a large deficit concentrated in a
few big provinces against a small surplus spread across many small ones.

The ratio has widened at every election in the series, from 3.71 in 2008 to
4.13 in 2023, without a single change to the rule. Depopulation of the
interior does the work: the floor is fixed at two seats and the provinces
sitting on it keep losing people.

### The counterfactuals

| scenario | weight ratio | Loosemore-Hanby | seats moved |
|---|---|---|---|
| official (LOREG art. 162) | 4.13 | 10.52 | — |
| floor cut from 2 seats to 1 | 3.50 | 5.46 | 18 |
| no floor (minimum 1, all 350 by quota) | 2.35 | 1.97 | 36 |
| one 350-seat national district | 1.00 | 0.00 | — |

Cutting the floor from two seats to one **halves** the disproportionality
index and moves 18 seats; Madrid goes from 37 to 44 and Barcelona from 32 to
37, paid for by one seat each from eighteen interior provinces. Removing the
floor altogether moves 36 and takes Madrid to 50.

Note what the second row does *not* do: the weight ratio only falls from 4.13
to 3.50, because Ceuta and Melilla still hold a seat each on 84,000 and 86,000
people and they set the ratio's numerator once Soria stops doing so. The
ratio and the index disagree about how much the floor matters, and they are
measuring different things — the ratio is an extreme, the index is a total.

### Sainte-Lague changes almost nothing, and makes the ratio worse

Replacing quota-and-remainders with the Sainte-Lague divisors, keeping the
floors, moves **one seat in two of the seven elections and none in the other
five**. In 2008 it hands Soria a third seat at Toledo's expense — which
*raises* the weight ratio from 3.71 to 5.57 while leaving Loosemore-Hanby
untouched. The apportionment method is not where Spain's disproportionality
comes from. The floor is.

## What is not here

**D'Hondt.** In Spain D'Hondt is not the apportionment rule — the
apportionment is quota-and-remainder, above. It is the rule for turning votes
into seats *within* a province, and in a five-seat province it is a far larger
source of disproportionality than the floor is. Swapping it for Sainte-Lague
needs province-level party votes, which live in Infoelectoral's fixed-width
files. Those are not parsed here: there is no independent total to check a
column offset against, so a silently wrong offset would produce plausible
numbers instead of an error. The `sainte_lague` scenario above varies the
*apportionment* method only and says nothing about the within-province
allocation.

**Election results of any kind.** Nothing here scores a vote. The whole
module is about how 350 seats are distributed over 52 constituencies before
anyone votes.
