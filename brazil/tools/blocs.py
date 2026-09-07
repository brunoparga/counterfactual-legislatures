#!/usr/bin/env python3
"""Does removing the floor and ceiling change who can govern Brazil?

The Gallagher index says the constitutional limits barely touch
proportionality. That is not the same as saying they barely touch politics.
Brazilian government is coalition presidentialism: a president wins office
with an ideological bloc that is never a majority, then buys a working
majority from the *centrao* -- the pragmatic bloc that joins whoever holds the
presidency, in exchange for offices and budget.

Two thresholds matter, and the second is where Brazilian agendas actually die:

  257  simple majority of 513
  308  three fifths, required for a constitutional amendment, which is what
       pension, tax and administrative reform all need

So the question is not only whether the president's coalition crosses those
lines, but **how much of it has to be bought**. If the over-represented small
states elect centrao deputies at a higher rate than the country does -- which
is the standard claim in Brazilian political science, and is testable rather
than assumed -- then correcting the apportionment should shrink the centrao
and enlarge the ideological blocs, making presidents structurally less
dependent on it even where no threshold moves.

THE MODEL, AND ITS LIMITS

Each party is assigned to the president's bloc, the opposition, or the centrao
for that term, and the centrao is assumed to vote with the president. That is
a first approximation and deliberately crude: it ignores the price paid, the
fact that discipline is bought vote by vote, and every party that split. It is
defensible only for the comparative question asked here -- the same
classification is applied to both apportionments, so the *difference* is
attributable to seats rather than to the classification.

Anything unclassified falls to the centrao by construction, since that is what
a small pragmatic party in Brazil overwhelmingly is. The count of such seats is
reported so the assumption stays visible.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Party labels exactly as they appear in each year's results. Membership is a
# judgement about that presidential term, not about the party for all time --
# PMDB/MDB is centrao throughout, PSDB is government under Cardoso and
# opposition under Lula and Dilma.
BLOCS = {
    1990: {"pres": "Collor (PRN)",
           "gov": {"PRN", "PFL", "PDS"},
           "opp": {"PT", "PDT", "PSB", "PCdoB", "PSDB", "PCB"}},
    1994: {"pres": "Cardoso (PSDB)",
           "gov": {"PSDB", "PFL", "PTB"},
           "opp": {"PT", "PDT", "PSB", "PCdoB", "PPS", "PV"}},
    1998: {"pres": "Cardoso (PSDB), 2nd term",
           "gov": {"PSDB", "PFL", "PTB", "PPB", "PPrB"},
           "opp": {"PT", "PDT", "PSB", "PC do B", "PCdoB", "PPS", "PV"}},
    2002: {"pres": "Lula (PT)",
           "gov": {"PT", "PC do B", "PCdoB", "PL", "PSB", "PMN", "PV"},
           "opp": {"PSDB", "PFL"}},
    2006: {"pres": "Lula (PT), 2nd term",
           "gov": {"PT", "PC do B", "PCdoB", "PSB", "PRB", "PL", "PR"},
           "opp": {"PSDB", "PFL", "DEM", "PPS"}},
    2010: {"pres": "Dilma (PT)",
           "gov": {"PT", "PC do B", "PCdoB", "PSB", "PR", "PRB", "PDT"},
           "opp": {"PSDB", "DEM", "PPS", "PSOL", "PV"}},
    2014: {"pres": "Dilma (PT), 2nd term",
           "gov": {"PT", "PC do B", "PCdoB", "PR", "PRB", "PROS", "PDT"},
           "opp": {"PSDB", "DEM", "SD", "SOLIDARIEDADE", "PPS", "PSOL",
                   "PSB", "PV", "NOVO"}},
    2018: {"pres": "Bolsonaro (PSL)",
           "gov": {"PSL", "PSC", "PRP", "PATRIOTA", "DC", "NOVO"},
           "opp": {"PT", "PSOL", "PC do B", "PCdoB", "PDT", "PSB", "REDE",
                   "PSDB"}},
    2022: {"pres": "Lula (PT), 3rd term",
           "gov": {"PT", "PSB", "PC do B", "PCdoB", "PV", "PSOL", "REDE",
                   "PDT", "CIDADANIA"},
           "opp": {"PL", "NOVO"}},
}
SERIES = {1990: "passport", 1994: "passport", 1998: "tse", 2002: "tse",
          2006: "tse", 2010: "tse", 2014: "tse", 2018: "tse", 2022: "tse"}
MAJORITY, AMENDMENT = 257, 308


def split(seats, year):
    b = BLOCS[year]
    gov = sum(v for k, v in seats.items() if k in b["gov"])
    opp = sum(v for k, v in seats.items() if k in b["opp"])
    cen = sum(v for k, v in seats.items()
              if k not in b["gov"] and k not in b["opp"])
    return gov, cen, opp


def required_discipline(gov, cen, threshold):
    """Share of the centrao the president must actually command to reach a
    threshold. Unlike a yes/no majority test this does not saturate, so it
    still discriminates when every scenario clears the line on paper."""
    return (threshold - gov) / cen if cen else float("inf")


def by_state(year):
    """{uf: {party: seats}} under the real apportionment, for asking whether a
    state is politically distinctive rather than merely large."""
    from chamber import (ACTUAL_SEATS as A, SEATS_1990, by_party, read_passport,
                         read_votes)
    if SERIES[year] == "passport":
        ent, pv = read_passport(year)
    else:
        ent, pv = read_votes(ROOT / "upstream" / "tse" /
                             f"votacao_partido_munzona_{year}.zip")
    seats = SEATS_1990 if year == 1990 else A
    return {uf: by_party(ent, pv, {uf: m}, year) for uf, m in seats.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "results" / "blocs.json"))
    ap.add_argument("--states", action="store_true",
                    help="also compare Sao Paulo and the 8-seat floor states "
                         "against the national bloc split (slow: re-reads votes)")
    a = ap.parse_args()
    data = {s: json.loads((ROOT / "results" / f"chamber_{s}.json").read_text())
            for s in ("tse", "passport")}

    out = {}
    print(f"{'year':6}{'president':26}{'scenario':11}"
          f"{'gov':>5}{'centrao':>9}{'opp':>5}{'  gov+cen':>10}{'  257':>6}{'  308':>6}")
    for year in sorted(BLOCS):
        src = data[SERIES[year]].get(str(year))
        if not src:
            continue
        M = 503 if year == 1990 else 513
        maj, amd = round(M / 2 + 0.5), round(M * 3 / 5)
        row = {"president": BLOCS[year]["pres"], "chamber": M,
               "majority": maj, "amendment": amd, "series": SERIES[year]}
        for scen in ("actual", "no_limits"):
            g, c, o = split(src[scen]["seats_by_party"], year)
            row[scen] = {"gov": g, "centrao": c, "opp": o, "gov_plus_centrao": g + c,
                         "has_majority": g + c >= maj,
                         "has_amendment": g + c >= amd,
                         "gov_alone_majority": g >= maj,
                         "centrao_seats_needed": max(0, maj - g)}
            print(f"{year if scen=='actual' else '':<6}"
                  f"{BLOCS[year]['pres'] if scen=='actual' else '':26}{scen:11}"
                  f"{g:5}{c:9}{o:5}{g+c:10}"
                  f"{'  yes' if g+c>=maj else '   NO':>6}"
                  f"{'  yes' if g+c>=amd else '   NO':>6}")
        for scen in ("actual", "no_limits"):
            g, c = row[scen]["gov"], row[scen]["centrao"]
            row[scen]["centrao_discipline_for_majority"] = round(
                required_discipline(g, c, maj), 4)
            row[scen]["centrao_discipline_for_amendment"] = round(
                required_discipline(g, c, amd), 4)
        d = row["no_limits"]["centrao_seats_needed"] - row["actual"]["centrao_seats_needed"]
        row["centrao_dependence_change"] = d
        row["centrao_size_change"] = row["no_limits"]["centrao"] - row["actual"]["centrao"]
        row["amendment_discipline_change"] = round(
            row["no_limits"]["centrao_discipline_for_amendment"]
            - row["actual"]["centrao_discipline_for_amendment"], 4)
        out[str(year)] = row
        print(f"{'':43}centrao seats the president must buy: "
              f"{row['actual']['centrao_seats_needed']} -> "
              f"{row['no_limits']['centrao_seats_needed']} ({d:+})\n")
    cs = [r["centrao_size_change"] for r in out.values()]
    ds = [r["amendment_discipline_change"] for r in out.values()]
    print(f"centrao size change, mean {sum(cs)/len(cs):+.1f} seats; "
          f"shrinks in {sum(1 for x in cs if x < 0)} of {len(cs)} elections")
    print(f"required centrao discipline for an amendment, mean change "
          f"{100*sum(ds)/len(ds):+.2f} pp")

    if a.states:
        print(f"\n{'year':6}{'unit':8}{'seats':>6}{'gov%':>8}{'centrao%':>10}{'opp%':>7}")
        for year in sorted(BLOCS):
            sp = by_state(year)
            nat = {}
            for d_ in sp.values():
                for k, v in d_.items():
                    nat[k] = nat.get(k, 0) + v
            floor = {}
            for uf, d_ in sp.items():
                if sum(d_.values()) == 8:
                    for k, v in d_.items():
                        floor[k] = floor.get(k, 0) + v
            for label, seats in (("SP", sp["SP"]), ("BRASIL", nat),
                                 ("8-seat", floor)):
                g, c, o = split(seats, year)
                t = g + c + o or 1
                print(f"{year if label=='SP' else '':<6}{label:8}{t:6}"
                      f"{100*g/t:7.1f}%{100*c/t:9.1f}%{100*o/t:6.1f}%")
                out[str(year)].setdefault("bloc_shares", {})[label] = {
                    "seats": t, "gov_pct": round(100*g/t, 1),
                    "centrao_pct": round(100*c/t, 1), "opp_pct": round(100*o/t, 1)}
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
