#!/usr/bin/env python3
"""Fetch the official padron population by province from INE.

LOREG art. 162.3 distributes 248 of the 350 seats "en proporcion a su
poblacion", and the population it means is the *poblacion de derecho* of the
padron municipal as officially declared by Royal Decree -- not an estimate and
not the resident-population series INE has published since 2021 under the
Estadistica Continua de Poblacion, which is a different concept with different
numbers. Using the wrong series moves seats.

TWO TABLES, BECAUSE INE STOPPED UPDATING THE FIRST ONE

  2852   "Poblacion por provincias y sexo" -- province level, 1996 to 2021,
         and then frozen.
  2854.. one table of municipalities per province, still updated. The province
  ..2909 aggregate is in there too: INE distinguishes it by giving it the
         two-digit province code where a municipality has a five-digit one.

So years up to 2021 come from 2852 and later years are read off the municipal
tables. The overlap is checked rather than assumed -- see --check, which
requires the two sources to agree exactly on every province in every shared
year before anything is written.

The province code is the join key everywhere downstream. Names are not: INE
writes "Balears, Illes" where the convoking decree writes "Balears (Illes)",
and there are seven such provinces.
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "upstream" / "ine"
UA = {"User-Agent": "counterfactual-legislatures/0.1 (research; github.com/brunoparga)"}
API = "https://servicios.ine.es/wstempus/js/ES"
PROVINCE_TABLE = 2852
OPERATION = 22          # Cifras Oficiales de Poblacion: Revision del Padron
NATIONAL = "00"         # the national total, which is not a province


def get(url):
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=180).read())


def totals(series):
    """{province_code: {year: population}} from a tip=M response.

    Keeps only the Total-sex series whose geography carries a two-digit code,
    which is INE's marker for the province aggregate as opposed to one of its
    municipalities. Code "00" is the national total and is not a province; it
    sits in the same table and looks identical to this filter, so it is named
    and dropped rather than left to double every national sum.
    """
    out = {}
    for s in series:
        meta = s.get("MetaData") or []
        if len(meta) < 2:
            continue
        geo, sex = meta[0], meta[1]
        code = (geo.get("Codigo") or "").strip()
        if (sex.get("Nombre") != "Total" or len(code) != 2
                or not code.isdigit() or code == NATIONAL):
            continue
        out.setdefault(code, {"name": geo["Nombre"], "pop": {}})
        for d in s["Data"]:
            if d.get("Valor") is not None:
                out[code]["pop"][str(d["Anyo"])] = int(d["Valor"])
    return out


def municipal_tables():
    """{province name: table id} for the per-province municipal tables."""
    out = {}
    for t in get(f"{API}/TABLAS_OPERACION/{OPERATION}"):
        name = (t.get("Nombre") or "").strip()
        if ": Poblacion por municipios y sexo" in name.replace("ó", "o"):
            out[name.split(":")[0].strip()] = t["Id"]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nult", type=int, default=40,
                    help="how many periods to pull from the province table")
    ap.add_argument("--recent", type=int, default=8,
                    help="periods to pull from each municipal table")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    url = f"{API}/DATOS_TABLA/{PROVINCE_TABLE}?nult={a.nult}&tip=M"
    prov = totals(get(url))
    print(f"table {PROVINCE_TABLE}: {len(prov)} provinces, "
          f"{min(min(v['pop']) for v in prov.values())}-"
          f"{max(max(v['pop']) for v in prov.values())}", flush=True)

    tabs = municipal_tables()
    print(f"{len(tabs)} municipal tables", flush=True)
    disagree, added = [], 0
    for i, (name, tid) in enumerate(sorted(tabs.items()), 1):
        m = totals(get(f"{API}/DATOS_TABLA/{tid}?nult={a.recent}&tip=M"))
        for code, rec in m.items():
            tgt = prov.setdefault(code, {"name": rec["name"], "pop": {}})
            for y, v in rec["pop"].items():
                if y in tgt["pop"]:
                    if tgt["pop"][y] != v:
                        disagree.append((code, y, tgt["pop"][y], v))
                else:
                    tgt["pop"][y] = v
                    added += 1
        print(f"  [{i}/{len(tabs)}] {name}", flush=True)

    if disagree:
        print(f"\nGATE FAILED: {len(disagree)} province-years disagree between "
              f"the province table and the municipal tables")
        for d in disagree[:10]:
            print(f"  province {d[0]} {d[1]}: {d[2]:,} vs {d[3]:,}")
        return 1
    print(f"\noverlap agrees exactly; {added} province-years added from the "
          f"municipal tables")

    years = sorted({y for v in prov.values() for y in v["pop"]})
    doc = {"source": "INE Tempus3, operation 22 (Cifras Oficiales de Poblacion "
                     "de los Municipios Espanoles: Revision del Padron Municipal)",
           "province_table_url": url,
           "municipal_tables": {k: v for k, v in sorted(tabs.items())},
           "years": years,
           "provinces": {c: prov[c] for c in sorted(prov)}}
    p = OUT / "population_by_province.json"
    p.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    print(f"{len(prov)} provinces, years {years[0]}-{years[-1]}")
    for y in ("2007", "2010", "2014", "2015", "2018", "2022"):
        tot = sum(v["pop"][y] for v in prov.values() if y in v["pop"])
        print(f"  1 Jan {y}: {tot:,}")
    print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
