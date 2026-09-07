# Brazil

The Chamber of Deputies, and what its constitutional floor and ceiling cost.

Brazil is one of the two countries in `research/international-data.md`
identified as needing **no districting algorithm and no disaggregation**: the
district is the state, the states are not going to move, and TSE publishes
votes by party per state. Everything interesting is in the allocation
arithmetic, which means the counterfactual has no modelling error in the part
that matters.

    tools/fetch_tse.py    votes, 1994-2022, via the Wayback Machine
    tools/fetch_ibge.py   census population by state, via the SIDRA API
    tools/chamber.py      the three scenarios
    results/FINDINGS.md   what came out

Read `results/FINDINGS.md` first. The short version: the floor and ceiling are
a **huge** violation of one-person-one-vote (an 8x weight ratio between a
Roraima and a Sao Paulo voter, falling to 1.3x when removed) and only a
**minor** source of party disproportionality (11%). District magnitude does
far more damage than apportionment does.

Missing: **1990 and 1998**. See the last section of `FINDINGS.md`.
