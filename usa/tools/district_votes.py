#!/usr/bin/env python3
"""How would a splitline map have voted?

Takes an election, spreads its votes down to census blocks, walks each block
through a splitline tree, and reports which party carries each district.

WHY PRESIDENTIAL VOTES AND NOT HOUSE VOTES

The obvious input for "how would this House map have voted" is House returns,
and it is the wrong one. House results are reported by district -- already
aggregated to the very districts being replaced -- so they cannot be pushed
into a different map. County-level House returns are not published, because
districts split counties.

Presidential returns are reported by county, are contested everywhere, and
carry no incumbency advantage tied to a district that is about to stop
existing. In a year like 2012 the presidential and House votes track each
other closely at national level, so this measures partisan lean rather than
predicting a specific race.

THE ALLOCATION IS DELIBERATELY CRUDE

A county's votes are split among the districts covering it in proportion to
the population living in each piece. That assumes turnout and partisanship are
uniform within a county, which they are not -- a county holding a city and its
exurbs is not politically uniform, and the splitline cut may run right between
them. It is the coarsest defensible model and the finest one that needs no
data beyond a 4.5 MB file. Precinct-level returns are the refinement; see the
roadmap.
"""

import argparse
import csv
import json
import pathlib
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared" / "tools"))
from apportion import build, house_size, huntington_hill  # noqa: E402
from apportionment import FIPS, NAMES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIPS_TO_ST = {v: k for k, v in FIPS.items()}


def county_votes(path, year):
    """{county fips int: {party: votes}} for one election year.

    A handful of rows carry no county: statewide write-ins, Maine's overseas
    (UOCAVA) ballots, "Federal Precinct" and the like. They cannot be placed
    on a map, so they are dropped -- but counted and reported, because a
    silently discarded vote is indistinguishable from a bug.
    """
    out = defaultdict(lambda: defaultdict(int))
    placeless = 0
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["year"] != str(year):
                continue
            p = r["party"]
            if p not in ("democrat", "republican"):
                continue
            try:
                v = int(r["candidatevotes"] or 0)
            except ValueError:
                continue
            try:
                fips = int(float(r["FIPS"]))
            except (ValueError, TypeError):
                placeless += v
                continue
            out[fips][p] += v
    return out, placeless


def state_votes(path, year):
    """{state_po: {party: votes}} -- the fallback when county codes do not join.

    Alaska reports by state House district rather than by borough, so its
    "FIPS" are 2701..2740 and match no census county. The returns are still
    good statewide, and Alaska has one congressional district, so nothing is
    lost by spreading them over the state by population.
    """
    out = defaultdict(lambda: defaultdict(int))
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["year"] != str(year):
                continue
            if r["party"] not in ("democrat", "republican"):
                continue
            try:
                out[r["state_po"]][r["party"]] += int(r["candidatevotes"] or 0)
            except ValueError:
                pass
    return out


def actual_cd(st, d):
    """{15-digit block id: district number} from a Census block equivalency file.

    The equivalency file is the enacted plan expressed on 2010 blocks, so no
    geometry and no point-in-polygon is needed -- which is the whole reason to
    validate against it rather than against a shapefile.
    """
    low = st.lower()
    hits = list(pathlib.Path(d).glob(f"{FIPS[st]}_{st}_CD*.txt"))
    if not hits:
        return None
    out = {}
    with open(hits[0]) as f:
        next(f)
        for line in f:
            b, cd = line.rstrip("\n").split(",")
            out[b] = cd
    return out


def blocks_2010(st, want_id=False):
    """county fips, population, lat, lon for every populated block of a state."""
    low = st.lower()
    p = ROOT / "upstream" / "2010" / low / f"{low}geo2010.pl"
    cty, pop, lat, lon, ids = [], [], [], [], []
    with open(p, encoding="latin-1") as f:
        for line in f:
            if line[8:11] != "750" or line[11:13] != "00":
                continue
            n = int(line[318:327] or 0)
            if n <= 0:
                continue
            cty.append(int(line[27:29]) * 1000 + int(line[29:32]))
            pop.append(n)
            lat.append(float(line[336:347]))
            lon.append(float(line[347:359]))
            if want_id:
                ids.append(line[27:29] + line[29:32] + line[54:60] + line[61:65])
    return (np.array(cty), np.array(pop, dtype=np.int64),
            np.array(lat), np.array(lon), ids)


def gnomonic(lon, lat, lon0, lat0, lon_shift=0.0):
    """Projected degrees. lon_shift moves the antimeridian out of the way --
    Alaska straddles it, and without the shift its blocks land on the far side
    of the world from its own cut tree."""
    lon = lon + lon_shift
    lo, la = np.radians(lon), np.radians(lat)
    l0, a0 = np.radians(lon0), np.radians(lat0)
    cosc = np.sin(a0) * np.sin(la) + np.cos(a0) * np.cos(la) * np.cos(lo - l0)
    x = np.cos(la) * np.sin(lo - l0) / cosc
    y = (np.cos(a0) * np.sin(la) - np.sin(a0) * np.cos(la) * np.cos(lo - l0)) / cosc
    return np.degrees(x), np.degrees(y)


def assign(nodes, X, Y):
    """District number for each point, by walking the cut tree."""
    out = np.full(len(X), -1, np.int32)
    stack = [(0, np.arange(len(X)))]
    while stack:
        i, sel = stack.pop()
        if len(sel) == 0:
            continue
        n = nodes[i]
        if "district" in n:
            out[sel] = n["district"]
            continue
        side = (X[sel] * n["nx"] + Y[sel] * n["ny"]) < n["c"]
        stack.append((n["left"], sel[side]))
        stack.append((n["right"], sel[~side]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--election", type=int, default=2012)
    ap.add_argument("--census", type=int, default=2010)
    ap.add_argument("--rule", default="fixed")
    ap.add_argument("--metric", default="span")
    ap.add_argument("--model", default="uniform", choices=("uniform", "point"))
    ap.add_argument("--returns",
                    default=str(ROOT / "upstream" / "elections" /
                                "countypres_2000-2016.csv"))
    ap.add_argument("--map", default="splitline",
                    choices=("splitline", "actual"),
                    help="which districting to score: our cut trees, or the "
                         "enacted plan from a block equivalency file")
    ap.add_argument("--bef", default=str(ROOT / "upstream" / "elections" / "cd113"))
    ap.add_argument("--out", default=str(ROOT / "work" / "district_votes.json"))
    a = ap.parse_args()

    plans = ROOT / "plans"
    votes, placeless = county_votes(a.returns, a.election)
    svotes = state_votes(a.returns, a.election)
    total_in = sum(v["democrat"] + v["republican"] for v in votes.values())
    print(f"{a.election}: {len(votes):,} counties, {total_in:,} two-party votes; "
          f"{placeless:,} unplaceable ({100*placeless/(total_in+placeless):.3f}%)",
          flush=True)

    pops = build(a.census, 0, 0)
    seats = huntington_hill(pops, house_size(a.rule, pops))

    rows, missing, fallback = [], set(), set()
    for st in sorted(seats, key=lambda s: FIPS[s]):
        n = seats[st]
        if n <= 0:
            continue
        if a.map == "actual":
            cty, pop, lat, lon, ids = blocks_2010(st, want_id=True)
            cd = actual_cd(st, a.bef)
            if cd is None:
                print(f"  {st}: no equivalency file"); continue
            dist = np.array([int(cd.get(b, "-1") or -1) for b in ids], np.int32)
        else:
            tree = plans / f"{a.census}_{st.lower()}_{n}_{a.model}_{a.metric}.json"
            if not tree.exists():
                print(f"  {st}: no tree"); continue
            d = json.load(open(tree))
            nodes = {x["i"]: x for x in d["nodes"]}
            pr = d["projection"]
            cty, pop, lat, lon, _ = blocks_2010(st)
            X, Y = gnomonic(lon, lat, pr["lon0"], pr["lat0"],
                            pr.get("lon_shift", 0.0))
            dist = assign(nodes, X, Y)

        # population of each (district, county) piece
        piece = defaultdict(int)
        for dd, cc, pp in zip(dist.tolist(), cty.tolist(), pop.tolist()):
            piece[(dd, cc)] += pp
        ctot = defaultdict(int)
        for (dd, cc), pp in piece.items():
            ctot[cc] += pp

        per = defaultdict(lambda: [0.0, 0.0])
        if not any(cc in votes for (_, cc) in piece):
            # No county code joins. Spread the statewide total over districts
            # by population instead of dropping the state.
            sv = svotes.get(st, {"democrat": 0, "republican": 0})
            dpop = defaultdict(int)
            for (dd, cc), pp in piece.items():
                dpop[dd] += pp
            tp = sum(dpop.values()) or 1
            for dd, pp in dpop.items():
                per[dd][0] = sv["democrat"] * pp / tp
                per[dd][1] = sv["republican"] * pp / tp
            fallback.add(st)
        else:
            for (dd, cc), pp in piece.items():
                v = votes.get(cc)
                if v is None:
                    missing.add(cc); continue
                share = pp / ctot[cc]
                per[dd][0] += v["democrat"] * share
                per[dd][1] += v["republican"] * share
        for dd in sorted(per):
            dv, rv = per[dd]
            rows.append({"state": st, "district": int(dd),
                         "dem": round(dv), "rep": round(rv),
                         "winner": "D" if dv > rv else "R"})
        print(f"  {st} {n:2}  "
              f"D {sum(1 for r in rows if r['state']==st and r['winner']=='D'):2} / "
              f"R {sum(1 for r in rows if r['state']==st and r['winner']=='R'):2}",
              flush=True)

    D = sum(1 for r in rows if r["winner"] == "D")
    R = len(rows) - D
    dv = sum(r["dem"] for r in rows); rv = sum(r["rep"] for r in rows)
    print(f"\n{'='*46}\n{a.map} map | {a.census} census, {a.rule}, {a.metric}, {a.model}")
    print(f"votes  D {dv:,} ({100*dv/(dv+rv):.1f}%)   R {rv:,} ({100*rv/(dv+rv):.1f}%)")
    print(f"seats  D {D}   R {R}   of {len(rows)}")
    if missing:
        print(f"counties with no returns: {len(missing)}")
    if fallback:
        print(f"states from statewide totals: {' '.join(sorted(fallback))}")
    Path(a.out).write_text(json.dumps(rows, indent=1))
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
