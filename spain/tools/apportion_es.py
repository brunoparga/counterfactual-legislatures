#!/usr/bin/env python3
"""Spain's apportionment of 350 Diputados, and what its floor costs.

THE RULE (LOREG art. 162, verbatim in upstream/boe/loreg_art162.txt)

  1. the Congress has 350 Diputados
  2. every province gets an initial minimum of two; Ceuta and Melilla one each
  3. the remaining 248 go to the provinces in proportion to population:
     a quota is formed by dividing the total population *of the provinces* by
     248, each province takes the whole part of its population over that
     quota, and what is left over goes one seat at a time to the largest
     decimal fractions

Two details in that make it not a generic Hare allocation and are easy to get
wrong. The quota divides by 248, not by 350, so it is not the average
population per seat. And Ceuta and Melilla are outside the quota pool
entirely -- they are not provinces -- so including their 170,000 people moves
a remainder seat.

THE REFERENCE POPULATION IS NOT STATED ANYWHERE

Art. 162.3 says "poblacion de derecho" and the convoking decree names no
figure, no date and no source. Every decree is therefore ambiguous on its
face. Rather than assume the padron revision, this tool runs the rule against
every revision INE publishes and reports which one reproduces the decree's
annex exactly. That is the validation gate: an implementation that cannot
return the official 52-number vector is not allowed to produce a
counterfactual, because there would be no way to tell its errors from its
findings.

THE COUNTERFACTUALS

  official      the rule as written -- the gate
  floor_1       LOREG's architecture with the provincial minimum cut from two
                seats to one. Ceuta and Melilla stay at one, so the only thing
                that changes is the floor whose cost is being measured.
  no_floor      no minimum at all: all 350 by quota over all 52
                constituencies, raised to one where that would give zero. A
                true floor of zero would unseat Soria, Ceuta and Melilla
                outright, which is a different question from malapportionment.
  sainte_lague  LOREG's floors kept, the 248 remaining seats allocated by the
                Sainte-Lague divisors instead of by quota and remainders.
  national      one 350-seat national district: malapportionment is zero by
                construction, and it is here as the reference point the other
                rows are measured against.

WHAT IS NOT HERE

D'Hondt. In Spain D'Hondt is not the apportionment rule -- the apportionment
is quota-and-remainder, above -- it is the rule for turning votes into seats
*within* a province, and swapping it for Sainte-Lague needs province-level
party votes. Those live in Infoelectoral's fixed-width files, which are not
parsed here. So `sainte_lague` below varies the apportionment method and says
nothing about the within-province allocation, which is the larger effect and
remains open.
"""

import argparse
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared" / "tools"))
from allocation import sainte_lague as sl_divisors  # noqa: E402

HOUSE = 350
PROVINCE_MIN = 2          # art. 162.2
AUTONOMOUS_CITIES = {"51": "Ceuta", "52": "Melilla"}   # one Diputado each
POOL = HOUSE - 50 * PROVINCE_MIN - len(AUTONOMOUS_CITIES)   # 248, art. 162.3

# The Basque provinces were renamed between decrees: the 2008 decree says
# Alava, Guipuzcoa and Vizcaya where later ones say Araba/Alava, Gipuzkoa and
# Bizkaia. Nothing else in 60 distinct decree spellings fails to match INE
# once accents and punctuation are normalised away.
ALIASES = {"alava": "01", "guipuzcoa": "20", "guipuzkoa": "20", "vizcaya": "48"}


def fold(s):
    """Accent-free lowercase token set, so 'Balears (Illes)' == 'Balears, Illes'."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return frozenset("".join(c if c.isalnum() else " " for c in s).split())


def hare(pops, total):
    """Whole parts by quota, then the leftovers to the largest fractions."""
    q = sum(pops.values()) / total
    exact = {u: pops[u] / q for u in pops}
    seats = {u: int(exact[u]) for u in pops}
    left = total - sum(seats.values())
    for u in sorted(pops, key=lambda u: (-(exact[u] - int(exact[u])), u))[:left]:
        seats[u] += 1
    return seats


def official(pop):
    """LOREG art. 162 on {code: population}. Returns {code: seats}."""
    prov = {c: p for c, p in pop.items() if c not in AUTONOMOUS_CITIES}
    seats = {c: PROVINCE_MIN + n for c, n in hare(prov, POOL).items()}
    seats.update({c: 1 for c in AUTONOMOUS_CITIES})
    return seats


def floor_1(pop):
    """The same architecture with the provincial minimum cut from two to one."""
    prov = {c: p for c, p in pop.items() if c not in AUTONOMOUS_CITIES}
    pool = HOUSE - len(prov) - len(AUTONOMOUS_CITIES)
    seats = {c: 1 + n for c, n in hare(prov, pool).items()}
    seats.update({c: 1 for c in AUTONOMOUS_CITIES})
    return seats


def no_floor(pop):
    """All 350 by quota over all 52, with anything rounding to zero raised to one.

    Raising to one and re-running on the rest is not cosmetic: at a 350-seat
    quota Soria, Ceuta and Melilla are each below a full seat, and letting
    them round to zero would answer a question about abolishing
    constituencies rather than about the size of the floor.
    """
    seats = hare(pop, HOUSE)
    for _ in range(len(pop)):
        zero = [c for c in pop if seats[c] < 1]
        if not zero:
            break
        free = {c: pop[c] for c in pop if c not in zero}
        seats = {**{c: 1 for c in zero},
                 **hare(free, HOUSE - len(zero))}
    return seats


def sainte_lague(pop):
    """LOREG's floors, but the 248 remaining seats by the odd-number divisors."""
    prov = {c: p for c, p in pop.items() if c not in AUTONOMOUS_CITIES}
    seats = {c: PROVINCE_MIN + n for c, n in sl_divisors(prov, POOL).items()}
    seats.update({c: 1 for c in AUTONOMOUS_CITIES})
    return seats


SCENARIOS = {"official": official, "floor_1": floor_1, "no_floor": no_floor,
             "sainte_lague": sainte_lague}


def metrics(pop, seats):
    """How far the seat vector is from one person one vote."""
    tot_p, tot_s = sum(pop.values()), sum(seats.values())
    per = {c: pop[c] / seats[c] for c in pop if seats[c]}
    lo = min(per, key=lambda c: per[c])
    hi = max(per, key=lambda c: per[c])
    lh = 0.5 * sum(abs(seats[c] / tot_s - pop[c] / tot_p) for c in pop) * 100
    gq = (0.5 * sum((seats[c] / tot_s - pop[c] / tot_p) ** 2
                    for c in pop)) ** 0.5 * 100
    exact = {c: pop[c] / tot_p * tot_s for c in pop}
    return {"house": tot_s,
            "pop_per_seat_mean": round(tot_p / tot_s, 1),
            "best_represented": lo, "best_pop_per_seat": round(per[lo], 1),
            "worst_represented": hi, "worst_pop_per_seat": round(per[hi], 1),
            "vote_weight_ratio": round(per[hi] / per[lo], 3),
            "loosemore_hanby": round(lh, 3),
            "gallagher": round(gq, 3),
            "seats_above_proportional": sum(1 for c in pop
                                            if seats[c] - exact[c] >= 1),
            "seats_below_proportional": sum(1 for c in pop
                                            if exact[c] - seats[c] >= 1),
            "max_seat_surplus": round(max(seats[c] - exact[c] for c in pop), 2),
            "max_seat_deficit": round(max(exact[c] - seats[c] for c in pop), 2)}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ine", default=str(ROOT/"upstream"/"ine"/"population_by_province.json"))
    ap.add_argument("--boe", default=str(ROOT/"upstream"/"boe"/"convoking_decrees.json"))
    ap.add_argument("--out", default=str(ROOT/"results"/"apportionment.json"))
    a = ap.parse_args()

    ine = json.loads(Path(a.ine).read_text())["provinces"]
    boe = json.loads(Path(a.boe).read_text())["decrees"]
    by_fold = {fold(v["name"]): c for c, v in ine.items()}

    def code(name):
        f = fold(name)
        if f in by_fold:
            return by_fold[f]
        for tok in f:
            if tok in ALIASES:
                return ALIASES[tok]
        return None

    out, failures = [], []
    for dec in sorted(boe, key=lambda d: d["election_date"]):
        want, unknown = {}, []
        for name, n in dec["seats"].items():
            c = code(name)
            (unknown.append(name) if c is None else want.__setitem__(c, n))
        if unknown or len(want) != 52:
            failures.append((dec["election_date"],
                             f"decree names unmatched: {unknown or len(want)}"))
            continue

        years = sorted(y for y in {y for v in ine.values() for y in v["pop"]}
                       if int(y) < int(dec["election_date"][:4]) + 1)
        matches = []
        for y in years:
            pop = {c: v["pop"][y] for c, v in ine.items() if y in v["pop"]}
            if len(pop) != 52:
                continue
            if official(pop) == want:
                matches.append(y)
        if not matches:
            best = None
            for y in years:
                pop = {c: v["pop"][y] for c, v in ine.items() if y in v["pop"]}
                if len(pop) != 52:
                    continue
                got = official(pop)
                d = sum(abs(got[c] - want[c]) for c in want)
                if best is None or d < best[1]:
                    best = (y, d)
            failures.append((dec["election_date"],
                             f"no padron revision reproduces the annex; "
                             f"closest is {best[0]} off by {best[1]} seats"))
            print(f"{dec['election_date']}  GATE FAILED  {failures[-1][1]}")
            continue

        ref = matches[-1]          # the latest revision that reproduces it
        pop = {c: v["pop"][ref] for c, v in ine.items()}
        rec = {"election_date": dec["election_date"], "boe_id": dec["boe_id"],
               "decree_url": dec["url"],
               "reference_padron": f"{ref}-01-01",
               "reference_padron_candidates": matches,
               "population_total": sum(pop.values()),
               "official_reproduced": True,
               "province_names": {c: ine[c]["name"] for c in sorted(pop)},
               "population": {c: pop[c] for c in sorted(pop)},
               "scenarios": {}}
        for nm, fn in SCENARIOS.items():
            seats = fn(pop)
            rec["scenarios"][nm] = {"seats": {c: seats[c] for c in sorted(seats)},
                                    "metrics": metrics(pop, seats),
                                    "moved_vs_official": sum(
                                        abs(seats[c] - want[c]) for c in want) // 2}
        rec["scenarios"]["national"] = {
            "seats": None, "metrics": {"house": HOUSE, "vote_weight_ratio": 1.0,
                                       "loosemore_hanby": 0.0, "gallagher": 0.0},
            "moved_vs_official": None,
            "note": "one 350-seat national district; no apportionment to make"}
        out.append(rec)
        m = rec["scenarios"]["official"]["metrics"]
        print(f"{dec['election_date']}  padron {ref}-01-01  "
              f"52/52 provinces match the decree   "
              f"weight ratio {m['vote_weight_ratio']:.2f}  "
              f"(worst {ine[m['worst_represented']]['name']}, "
              f"best {ine[m['best_represented']]['name']})")

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(
        {"house": HOUSE, "rule": "LOREG art. 162",
         "gate": "the official scenario must reproduce the convoking decree's "
                 "annex province by province",
         "elections": out}, indent=1, ensure_ascii=False))
    print(f"\n{len(out)}/{len(boe)} elections reproduced; wrote {a.out}")

    if out:
        print(f"\n{'election':12}{'scenario':14}{'ratio':>7}{'L-H':>7}"
              f"{'seats moved':>13}")
        for r in out:
            for nm in list(SCENARIOS) + ["national"]:
                s = r["scenarios"][nm]
                mv = s["moved_vs_official"]
                print(f"{r['election_date']:12}{nm:14}"
                      f"{s['metrics']['vote_weight_ratio']:7.2f}"
                      f"{s['metrics']['loosemore_hanby']:7.2f}"
                      f"{('-' if mv is None else str(mv)):>13}")
    if failures:
        print(f"\nGATE FAILED for {len(failures)} elections:")
        for d, why in failures:
            print(f"  {d}: {why}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
