# Brazil

The Chamber of Deputies, and what its constitutional floor and ceiling cost.

Brazil is one of the two countries in `research/international-data.md`
identified as needing **no districting algorithm and no disaggregation**: the
district is the state, the states are not going to move, and TSE publishes
votes by party per state. Everything interesting is in the allocation
arithmetic, which means the counterfactual has no modelling error in the part
that matters.

    tools/fetch_tse.py       votes 1994-2022, direct from TSE (Sec-Fetch-* headers)
    tools/fetch_ibge.py      census population by state, via the SIDRA API
    tools/parse_passport.py  Election Passport's BR.xlsx -> party votes per state
    tools/chamber.py         the scenarios, --source tse | passport
    results/FINDINGS.md      what came out

Read `results/FINDINGS.md` first. The short version: the floor and ceiling are
a **huge** violation of one-person-one-vote (an 8x weight ratio in 2022, 16x on
the 1991 census, falling to about 1.4x when removed) and only a **minor** source
of party disproportionality. District magnitude does far more damage than
apportionment does.

Nine elections, 1990-2022, in two series -- TSE at coalition level for
1998-2022, Election Passport at party level for 1990-2014 -- because seats were
won by coalitions until 2018 and TSE's repository does not reach 1990. Where
they overlap they agree on total votes to within half a percent, which is what
caught two silent parsing bugs.
