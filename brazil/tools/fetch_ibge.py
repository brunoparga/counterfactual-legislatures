#!/usr/bin/env python3
"""Fetch resident population by state (UF) from IBGE, one vector per census.

Apportionment normally runs on the most recent census before an election, so
that is the basis used here: four census vectors cover every Chamber election
from 1994 on.

  1991 census -> 1994, 1998 elections
  2000 census -> 2002, 2006
  2010 census -> 2010, 2014, 2018
  2022 census -> 2022

IBGE serves this through SIDRA, which is open and needs no key. Variable 93 is
"População residente"; n3 is the state level. The 1991-2010 censuses live in
table 136 and the 2022 census in table 4709, because IBGE renumbers tables
between censuses rather than extending one.

Using censuses rather than IBGE's annual estimates is a deliberate choice: it
mirrors how apportionment is actually done, needs no interpolation, and means
the counterfactual differs from reality only in the allocation rule and not
also in the population basis.
"""

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "upstream" / "ibge"
UA = {"User-Agent": "counterfactual-legislatures/0.1 (research; github.com/brunoparga)"}
# (year, sidra table). Variable 93 = resident population, level n3 = UF.
CENSUSES = [(1991, 136), (2000, 136), (2010, 136), (2022, 4709)]
URL = "https://apisidra.ibge.gov.br/values/t/{t}/n3/all/v/93/p/{y}"
# UF numeric code -> postal abbreviation, so the join to TSE is by code and
# never by name (IBGE and TSE disagree on accents and on "Distrito Federal").
UF = {11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO",
      21: "MA", 22: "PI", 23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL",
      28: "SE", 29: "BA", 31: "MG", 32: "ES", 33: "RJ", 35: "SP", 41: "PR",
      42: "SC", 43: "RS", 50: "MS", 51: "MT", 52: "GO", 53: "DF"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    out = {}
    for year, table in CENSUSES:
        url = URL.format(t=table, y=year)
        raw = urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=120).read()
        rows = json.loads(raw)[1:]
        pops = {}
        for r in rows:
            code = int(r["D1C"])
            if code in UF and r["V"] not in (None, "-", "..."):
                pops[UF[code]] = int(r["V"])
        if len(pops) != 27:
            print(f"  {year}: WARNING only {len(pops)} states")
        out[str(year)] = {"source_url": url, "population": pops,
                          "total": sum(pops.values())}
        print(f"  {year} census: {len(pops)} states, "
              f"{sum(pops.values()):,} people", flush=True)
    (OUT / "population_by_uf.json").write_text(json.dumps(out, indent=1))
    print(f"wrote {OUT/'population_by_uf.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
