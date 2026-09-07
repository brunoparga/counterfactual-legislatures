#!/usr/bin/env python3
"""Reapportion the Brazilian Chamber of Deputies without its floor and ceiling.

THE QUESTION

Article 45 of the 1988 Constitution makes Chamber seats proportional to state
population, then contradicts itself: no state may have fewer than 8 or more
than 70. Roraima had 650,000 people in 2022 and gets 8 seats; Sao Paulo had
44 million and is capped at 70. A vote in Roraima is worth roughly ten votes
in Sao Paulo, by design and by constitutional text.

This computes what the Chamber would have looked like with the same votes,
the same chamber size and the same within-state allocation rule, changing
exactly one thing: a floor of 1 and no ceiling. Everything else is held fixed,
so the difference is attributable to the floor and ceiling alone.

A further scenario treats Brazil as a single 513-seat national district, which
removes district magnitude from the picture as well and shows what undiluted
national proportionality would give.

WHAT IS AND IS NOT MODELLED

Votes are taken as cast. This is a counterfactual about the *translation* of
votes into seats, not about how people would have voted under other rules --
which is unknowable, and which is why holding votes fixed is the honest choice
rather than a limitation to apologise for.

The within-state rule is Brazil's own (Lei 9.504/97 arts. 106-109): an
electoral quotient QE = valid votes / seats; each contender takes
floor(votes/QE) seats; leftovers go by largest average votes/(seats+1). From
2015 a contender needs 80% of QE to join the leftover round; before that it
needed a full quotient. Both eras are implemented, because using one rule
throughout would put a rule change inside a comparison meant to isolate
apportionment.

COALITIONS

Until 2018 parties ran in coalitions, and seats were won by the *coalition*
then filled by its highest-polling candidates regardless of party. The entity
that wins seats is therefore the coalition. Splitting its seats among member
parties needs candidate-level data we have not downloaded, so seats are
allocated to coalitions exactly and attributed to parties in proportion to
each party's nominal vote inside the coalition. That last step is an
approximation. It does not affect the seats-per-state results at all, and it
does not arise in 2022, where proportional coalitions no longer exist.
"""

import argparse
import csv
import io
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# LC 78/1993, in force for every election from 1994 to 2022.
ACTUAL_SEATS = {
    "AC": 8, "AL": 9, "AP": 8, "AM": 8, "BA": 39, "CE": 22, "DF": 8, "ES": 10,
    "GO": 17, "MA": 18, "MT": 8, "MS": 8, "MG": 53, "PA": 17, "PB": 12,
    "PR": 30, "PE": 25, "PI": 10, "RJ": 46, "RN": 8, "RS": 31, "RO": 8,
    "RR": 8, "SC": 16, "SP": 70, "SE": 8, "TO": 8}

CENSUS_FOR = {1990: 1991, 1994: 1991, 1998: 1991, 2002: 2000, 2006: 2000,
              2010: 2010, 2014: 2010, 2018: 2010, 2022: 2022}
# The Chamber grew from 503 to 513 with LC 78/1993, so 1990 is the one
# election here with a different denominator.
CHAMBER = {y: (503 if y == 1990 else 513) for y in CENSUS_FOR}

# TSE renamed the vote columns between vintages; both spellings appear in
# files downloaded on the same day, so they are matched by name not position.
NOMINAL = ("QT_VOTOS_NOMINAIS_VALIDOS", "QT_VOTOS_NOMINAIS")
LEGENDA = ("QT_TOTAL_VOTOS_LEG_VALIDOS", "QT_VOTOS_LEGENDA")


def pick(head, names):
    for n in names:
        if n in head:
            return head.index(n)
    return None


def read_votes(path):
    """Returns (entity votes, party nominal votes) keyed by state."""
    ent = defaultdict(int)                 # (uf, entity) -> nominal + legenda
    pv = defaultdict(int)                  # (uf, entity, party) -> nominal
    with zipfile.ZipFile(path) as z:
        have = {n.rsplit("/", 1)[-1][:-4].rsplit("_", 1)[-1]
                for n in z.namelist() if n.lower().endswith(".csv")}
        missing = set(ACTUAL_SEATS) - have
        for name in z.namelist():
            # The archive carries per-state files AND aggregates named
            # _BRASIL.csv and _BR.csv that repeat every state's rows with the
            # real SG_UF on them. Reading the whole archive therefore counts
            # the country twice over, silently and proportionally -- so only
            # files whose suffix is one of the 27 state codes are read.
            stem = name.rsplit("/", 1)[-1]
            if not stem.lower().endswith(".csv"):
                continue
            uf_of_file = stem[:-4].rsplit("_", 1)[-1]
            # 1998 ships no DF file; its rows exist only inside the BRASIL
            # aggregate, so that one archive needs the aggregate read for the
            # states it omits -- and only for those.
            if uf_of_file not in ACTUAL_SEATS and not (
                    uf_of_file == "BRASIL" and missing):
                continue
            with z.open(name) as fh:
                rd = csv.reader(io.TextIOWrapper(fh, encoding="latin-1"),
                                delimiter=";")
                head = [h.strip('"') for h in next(rd)]
                iu, ic = head.index("SG_UF"), head.index("DS_CARGO")
                ip, iq = head.index("SG_PARTIDO"), head.index("SQ_COLIGACAO")
                inom, ileg = pick(head, NOMINAL), pick(head, LEGENDA)
                for r in rd:
                    if r[ic].strip('"').upper() != "DEPUTADO FEDERAL":
                        continue
                    uf = r[iu].strip('"')
                    if uf not in ACTUAL_SEATS:
                        continue           # ZZ = votes cast abroad, no seats
                    if uf_of_file == "BRASIL" and uf not in missing:
                        continue           # already read from its own file
                    p = r[ip].strip('"')
                    n = int(r[inom] or 0) if inom is not None else 0
                    lg = int(r[ileg] or 0) if ileg is not None else 0
                    sq = r[iq].strip('"')
                    # A coalition of one is just the party; keying such rows on
                    # the coalition id would fragment a party for no reason.
                    key = f"C{sq}" if sq and sq not in ("-1", "0", "") else p
                    ent[(uf, key)] += n + lg
                    pv[(uf, key, p)] += n
    return ent, pv


def read_passport(year):
    """Election Passport's party votes per state, in read_votes' shape.

    No coalitions: the file is party totals, so each party is its own entity.
    That is not the rule Brazil used before 2020, which is why the two sources
    are reported as separate series rather than spliced into one.
    """
    src = (ROOT / "upstream" / "electionpassport" / "br_party_votes.json")
    d = json.loads(src.read_text()).get(str(year))
    if not d:
        return None, None
    ent, pv = defaultdict(int), defaultdict(int)
    for uf, rec in d.items():
        if uf not in ACTUAL_SEATS:
            continue
        for party, v in rec["votes"].items():
            ent[(uf, party)] += v
            pv[(uf, party, party)] += v
    return ent, pv


def largest_remainder(pops, total, floor=None, cap=None):
    """Hare quota with largest remainders, then floor and cap enforced.

    Brazil's own allocation is of this family, so keeping the family fixed and
    changing only floor and cap is what makes the comparison clean.
    """
    units = sorted(pops)
    if not units or total <= 0:
        return {u: 0 for u in units}
    q = sum(pops.values()) / total
    exact = {u: pops[u] / q for u in units}
    seats = {u: int(exact[u]) for u in units}
    left = total - sum(seats.values())
    for u in sorted(units, key=lambda u: (-(exact[u] - int(exact[u])), u))[:left]:
        seats[u] += 1
    if floor is None and cap is None:
        return seats
    # Bind whatever violates a limit, then redistribute the rest among the
    # units still free to move, repeating until nothing new binds.
    for _ in range(len(units) + 2):
        bound = {}
        for u in units:
            if floor is not None and seats[u] < floor:
                bound[u] = floor
            elif cap is not None and seats[u] > cap:
                bound[u] = cap
        if not bound:
            return seats
        free = [u for u in units if u not in bound]
        rest = total - sum(bound.values())
        if not free or rest <= 0:
            return {**{u: 0 for u in units}, **bound}
        new = {**bound, **largest_remainder({u: pops[u] for u in free}, rest)}
        if new == seats:
            return new
        seats = new
    return seats


def allocate(votes, magnitude, year):
    """Brazil's within-district rule: electoral quotient, then largest averages."""
    votes = {k: v for k, v in votes.items() if v > 0}
    if magnitude <= 0 or not votes:
        return {}
    valid = sum(votes.values())
    qe = max(1, round(valid / magnitude))
    seats = {k: min(magnitude, v // qe) for k, v in votes.items()}
    if sum(seats.values()) > magnitude:            # can happen at tiny QE
        seats = {k: 0 for k in votes}
    # From 2015, 80% of a quotient buys a place in the leftover round; before
    # that a full quotient was required.
    bar = 0.8 * qe if year >= 2018 else qe
    pool = [k for k, v in votes.items() if v >= bar]
    if not pool:
        pool = sorted(votes, key=lambda k: -votes[k])
    for _ in range(magnitude - sum(seats.values())):
        k = max(pool, key=lambda k: (votes[k] / (seats[k] + 1), votes[k]))
        seats[k] += 1
    return {k: v for k, v in seats.items() if v}


def by_party(ent, pv, seats_by_uf, year):
    """Run every state, then attribute coalition seats to member parties."""
    out = defaultdict(int)
    for uf, m in seats_by_uf.items():
        won = allocate({k[1]: n for k, n in ent.items() if k[0] == uf}, m, year)
        for key, s in won.items():
            members = {k[2]: n for k, n in pv.items()
                       if k[0] == uf and k[1] == key and n > 0}
            if len(members) <= 1:
                out[next(iter(members)) if members else key] += s
            else:
                for p, ps in allocate(members, s, year).items():
                    out[p] += ps
    return dict(sorted(out.items(), key=lambda x: -x[1]))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", nargs="*", type=int, default=None)
    ap.add_argument("--source", choices=("tse", "passport"), default="tse",
                    help="tse: coalition-level, 1998-2022 (1994 unusable -- its "
                         "file records zero legenda votes). passport: "
                         "party-level, 1990-2014, the only source for 1990.")
    ap.add_argument("--tse", default=str(ROOT / "upstream" / "tse"))
    ap.add_argument("--out", default=str(ROOT / "results"))
    a = ap.parse_args()

    pop = json.loads((ROOT / "upstream" / "ibge" /
                      "population_by_uf.json").read_text())
    if a.source == "passport":
        avail = set(json.loads((ROOT / "upstream" / "electionpassport" /
                                "br_party_votes.json").read_text()))
        years = a.years or sorted(y for y in CENSUS_FOR if str(y) in avail)
    else:
        years = a.years or sorted(
            y for y in CENSUS_FOR if y != 1994 and
            (Path(a.tse) / f"votacao_partido_munzona_{y}.zip").exists())

    out = {}
    for year in years:
        if a.source == "passport":
            ent, pv = read_passport(year)
            if ent is None:
                print(f"{year}: not in Election Passport"); continue
        else:
            ent, pv = read_votes(Path(a.tse) /
                                 f"votacao_partido_munzona_{year}.zip")
        M = CHAMBER[year]
        pops = pop[str(CENSUS_FOR[year])]["population"]
        # The historical 503-seat table for 1990 is not published anywhere we
        # can reach, so that year has no "actual" column; its baseline is the
        # constitutional rule recomputed on 503 seats.
        plans = {} if year == 1990 else {
            "actual": ACTUAL_SEATS,
        }
        plans["no_limits"] = largest_remainder(pops, M, floor=1)
        plans["recomputed_with_limits"] = largest_remainder(pops, M, floor=8,
                                                            cap=70)
        res = {p: {"seats_by_uf": s, "seats_by_party": by_party(ent, pv, s, year)}
               for p, s in plans.items()}

        # Single national district. Coalitions are state-specific, so this runs
        # on parties directly and needs no coalition assumption at all.
        natl = defaultdict(int)
        for (uf, key, p), n in pv.items():
            natl[p] += n
        res["national_single_district"] = {
            "seats_by_uf": None,
            "seats_by_party": dict(sorted(allocate(dict(natl), M, year).items(),
                                          key=lambda x: -x[1]))}
        res["census_basis"] = CENSUS_FOR[year]
        res["total_votes"] = sum(ent.values())
        # National party vote, for the disproportionality index. Legenda votes
        # belong to a party even inside a coalition, so this is exact.
        pvotes = defaultdict(int)
        for (uf, key), n in ent.items():
            members = {k[2]: v for k, v in pv.items() if k[0] == uf and k[1] == key}
            tot = sum(members.values())
            # A coalition can carry legenda votes while its members show no
            # nominal votes at all, so tot may be zero; split evenly then.
            if len(members) <= 1 or tot <= 0:
                if members:
                    for q in members:
                        pvotes[q] += n / len(members)
                else:
                    pvotes[key] += n
            else:
                for q, v in members.items():
                    pvotes[q] += n * v / tot
        res["votes_by_party"] = dict(sorted(
            ((k, round(v)) for k, v in pvotes.items()), key=lambda x: -x[1]))
        out[str(year)] = res
        chk = {p: sum(v["seats_by_party"].values()) for p, v in res.items()
               if isinstance(v, dict) and "seats_by_party" in v}
        print(f"{year}: {chk}", flush=True)

    o = Path(a.out); o.mkdir(parents=True, exist_ok=True)
    (o / f"chamber_{a.source}.json").write_text(json.dumps(out, indent=1))
    print(f"wrote {o / f'chamber_{a.source}.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
