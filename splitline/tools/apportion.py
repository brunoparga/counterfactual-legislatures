#!/usr/bin/env python3
"""Apportion a House of any size, by Huntington-Hill, from census data on disk.

435 is an arbitrary freeze from 1929, so the size is a parameter here. Three
rules are offered:

  fixed       435 seats, the status quo
  cuberoot    the cube root of the apportionment population
  wyoming     every district holds about as many people as the smallest state

and four choices of who is apportioned at all: the 50 states alone, plus DC,
plus PR, or plus both.

TWO POPULATION BASES, DELIBERATELY

Apportionment and districting legitimately count different people, and this
file keeps them apart:

  apportionment population = resident population
                           + federal employees serving overseas, allocated
                             back to their home state from administrative
                             records

  resident population      = what the block files contain, and what the
                             splitline engine draws lines from

The overseas count exists only at state level. The Census never produces a
block, tract or county attribution for it, so it cannot be pushed down into
the districting data -- and it should not be. Those people are North
Carolinians for the purpose of "how many seats does North Carolina get", and
are standing nowhere in North Carolina for the purpose of "where do the lines
go". Spreading them uniformly across a state would replace a known absence
with a confident error, since home of record clusters around military
communities.

This is also what really happens: states redistrict from PL 94-171 block
data, which carries no overseas count. A state apportioned on one base and
districted on another is standard practice, not an artifact here.

It matters. Apportioning the 2000 census on resident population alone gives
Utah the 435th seat instead of North Carolina -- a 0.031% margin, and the seat
Utah twice litigated over. Every other seat in 2000, and all 50 in 2010 and
2020, is identical either way.

Puerto Rico is read from its own census files like any state. No overseas
allocation is published for it, so its apportionment base is resident
population; PR_POP_PUBLISHED keeps the published figures as a cross-check,
and they agree exactly for all three censuses.
"""

import argparse
import math
import sys
from heapq import heappop, heappush
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apportionment import FIPS, NAMES, SEATS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class MissingData(Exception):
    """A census year is not fully downloaded yet."""

    def __init__(self, year, states):
        self.year, self.states = year, states
        super().__init__(f"{year}: {len(states)} state(s) not downloaded: "
                         + " ".join(states))

# Published apportionment-brief figures for Puerto Rico, kept as a check on
# the values now read from its census files. Verified equal for all three
# censuses.
PR_POP_PUBLISHED = {2000: 3_808_610, 2010: 3_725_789, 2020: 3_285_874}


def state_population(year, st):
    """Total population of one state, from its census files."""
    low = st.lower()
    d = ROOT / "data" / str(year) / low

    if year == 2000:
        geo = d / f"{low}geo.uf1"
        lrn = None
        with open(geo, encoding="latin-1") as f:
            for line in f:
                if line[8:11] == "040" and line[11:13] == "00":
                    lrn = int(line[18:25])
                    break
        if lrn is None:
            raise ValueError(f"no state record in {geo}")
        with open(d / f"{low}00001.uf1", encoding="latin-1") as f:
            for line in f:
                p = line.split(",", 6)
                if len(p) >= 6 and int(p[4]) == lrn:
                    return int(p[5])
        raise ValueError(f"logrecno {lrn} not found for {st}")

    geo = d / f"{low}geo{year}.pl"
    with open(geo, encoding="latin-1") as f:
        for line in f:
            if year == 2010:
                if line[8:11] == "040" and line[11:13] == "00":
                    return int(line[318:327])
            else:
                q = line.rstrip("\n").split("|")
                if len(q) > 90 and q[2] == "040" and q[4] == "00":
                    return int(q[90])
    raise ValueError(f"no state record in {geo}")


def huntington_hill(pops, size):
    """Allocate `size` seats over {unit: population}.

    Every unit gets one seat first, then the rest go one at a time to whichever
    unit currently has the largest priority P / sqrt(n(n+1)).
    """
    units = list(pops)
    if size < len(units):
        raise ValueError(f"{size} seats cannot cover {len(units)} units")
    seats = {u: 1 for u in units}

    heap = []
    for u in units:
        heappush(heap, (-pops[u] / math.sqrt(1 * 2), u))
    for _ in range(size - len(units)):
        _, u = heappop(heap)
        seats[u] += 1
        n = seats[u]
        heappush(heap, (-pops[u] / math.sqrt(n * (n + 1)), u))
    return seats


def house_size(rule, pops):
    total = sum(pops.values())
    if rule == "fixed":
        return 435
    if rule == "cuberoot":
        return round(total ** (1 / 3))
    if rule == "wyoming":
        return round(total / min(pops.values()))
    raise ValueError(rule)


def resident_base(year, cache={}):
    """{unit: resident population}, read from the census block files.

    This is the districting base -- what the splitline engine draws from.
    """
    if year not in cache:
        pops, missing = {}, []
        for st in FIPS:
            try:
                pops[st] = state_population(year, st)
            except FileNotFoundError:
                missing.append(st)
        if missing:
            raise MissingData(year, missing)
        cache[year] = pops
    return dict(cache[year])


def build(year, include_dc, include_pr, resident_only=False, cache={}):
    """{unit: population} for one year and one inclusion choice.

    Returns the *apportionment* population by default -- resident plus the
    published overseas allocation -- because that is what apportionment legally
    uses, and using it makes the 435-seat 50-state result reproduce the
    official one exactly in all three censuses. Pass resident_only=True to get
    the districting base instead.
    """
    res = resident_base(year)
    if resident_only:
        base = res
    else:
        if year not in cache:
            from read_apportionment import apportionment_population
            ap = apportionment_population(year, res)
            over = {s: ap[s] - res[s] for s in ap}
            cache[year] = (ap, over)
        ap, over = cache[year]
        base = {s: ap.get(s, res[s]) for s in res}
        # DC is not in the apportionment tables (it is not apportioned), so
        # its counterfactual base is resident plus its own overseas count.
        if "DC" in res and "DC" not in ap:
            base["DC"] = res["DC"] + over.get("DC", 0)

    # DC and PR are never apportioned unless the variant says so. Both are in
    # the population tables -- DC because the nationwide map must draw it, PR
    # because the +PR variants need its map -- so both have to be taken out
    # here and put back only on request.
    dc = base.pop("DC")
    pr = base.pop("PR", None)
    if include_dc:
        base["DC"] = dc
    if include_pr:
        if pr is None:
            raise MissingData(year, ["PR"])
        # No overseas allocation is published for PR; resident only.
        base["PR"] = pr
    return base


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, choices=(2000, 2010, 2020))
    ap.add_argument("--rule", choices=("fixed", "cuberoot", "wyoming"))
    ap.add_argument("--dc", action="store_true")
    ap.add_argument("--pr", action="store_true")
    ap.add_argument("--table", action="store_true",
                    help="print the full 3 x 3 x 4 summary")
    ap.add_argument("--detail", action="store_true",
                    help="print per-state seats for the selected combination")
    args = ap.parse_args()

    if args.table or not (args.year and args.rule):
        print(f"{'year':>5} {'rule':>9} {'includes':>12} {'units':>6} {'house':>6} "
              f"{'per seat':>10} {'DC':>4} {'PR':>4}  notes")
        for year in (2000, 2010, 2020):
            for rule in ("fixed", "cuberoot", "wyoming"):
                base = None
                for dc, pr in ((0, 0), (1, 0), (0, 1), (1, 1)):
                    try:
                        pops = build(year, dc, pr)
                    except MissingData as e:
                        print(f"{year:>5} {rule:>9}  -- skipped: {e}")
                        break
                    size = house_size(rule, pops)
                    seats = huntington_hill(pops, size)
                    total = sum(pops.values())
                    inc = {(0, 0): "50 states", (1, 0): "+DC",
                           (0, 1): "+PR", (1, 1): "+DC +PR"}[(dc, pr)]

                    note = ""
                    if not dc and not pr:
                        base = dict(seats)
                        # Only the 435-seat 50-state case has an official
                        # answer to check against; comparing a 692-seat House
                        # to the official table would just restate that it is
                        # bigger.
                        if rule == "fixed":
                            diff = [s for s in seats if seats[s] != SEATS[year][s]]
                            note = "matches official" if not diff else \
                                "DIFFERS: " + " ".join(
                                    f"{s}{seats[s]-SEATS[year][s]:+d}" for s in diff)
                        else:
                            note = f"baseline for this rule (+{size-435} vs 435)"
                    elif base is not None:
                        # Who pays for the new seats. With a fixed House the
                        # newcomers' seats have to come from somewhere, and
                        # naming the states that give them up is the point of
                        # the counterfactual.
                        lost = [(s, base[s] - seats[s]) for s in base
                                if s in seats and seats[s] < base[s]]
                        lost.sort(key=lambda kv: (-kv[1], kv[0]))
                        if lost:
                            note = "loses: " + " ".join(
                                f"{s}{-n:+d}" for s, n in lost)
                        else:
                            note = "no state loses a seat (House grew)"

                    print(f"{year:>5} {rule:>9} {inc:>12} {len(pops):>6} {size:>6} "
                          f"{total/size:>10,.0f} {seats.get('DC',0):>4} "
                          f"{seats.get('PR',0):>4}  {note}")
            print()
        return 0

    pops = build(args.year, args.dc, args.pr)
    size = house_size(args.rule, pops)
    seats = huntington_hill(pops, size)
    print(f"{args.year} {args.rule}: {size} seats over {len(pops)} units, "
          f"{sum(pops.values())/size:,.0f} per seat")
    if args.detail:
        for st in sorted(seats, key=lambda s: (-seats[s], s)):
            print(f"  {st}  {seats[st]:3d}  {pops[st]:>11,}  {NAMES.get(st, st)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
