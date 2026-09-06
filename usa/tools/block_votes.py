#!/usr/bin/env python3
"""Score a districting with votes that are already on census blocks.

The county-level version of this had a fatal flaw: it split a county's votes
across districts in proportion to population, which erases the political
sorting inside the county. Sixty per cent of Americans live in a county that
spans more than one district, so on the enacted 2012 map that method put 239
districts in Democratic hands where the true answer is 209 -- a thirty-seat
error, larger than the effect being measured.

Here the votes arrive already disaggregated to blocks, so there is no
allocation step left to be wrong. What remains is exact: which district
contains this block.

TWO CENSUS VINTAGES

The election data is keyed to 2020 blocks; the enacted-plan file is keyed to
2010 blocks. Block identifiers are reissued each census and do not refer to
the same ground, so the two cannot be joined by ID.

For a splitline map this does not arise -- the map is a set of half-planes, so
it partitions any point regardless of which census produced it.

For the enacted map it does, and the fix here is geometric rather than
administrative: build a spatial index of 2010 block centroids carrying their
district, and give each 2020 block the district of its nearest neighbour.
Blocks are small, so this can only err within roughly one block width of a
district boundary, and --report-distance measures how much population sits
that close rather than assuming it is few.
"""

import argparse
import csv
import json
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared" / "tools"))
from apportion import build, house_size, huntington_hill  # noqa: E402
from apportionment import FIPS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
M_PER_DEG = 111320.0


def dra_votes(st, contest, root):
    """{block geoid: (dem, rep)} from the DRA block file."""
    d = root / st
    hits = list(d.glob("election_data_block_*.csv"))
    if not hits:
        return {}
    out = {}
    with open(hits[0], newline="") as f:
        rd = csv.reader(f)
        head = next(rd)
        try:
            gi = head.index("GEOID")
            di = head.index(f"{contest}_Dem")
            ri = head.index(f"{contest}_Rep")
        except ValueError:
            return {}
        for row in rd:
            try:
                dv, rv = float(row[di] or 0), float(row[ri] or 0)
            except ValueError:
                continue
            if dv or rv:
                out[row[gi]] = (dv, rv)
    return out


def statewide(path, year):
    """{state: (dem, rep)} from county returns -- the fallback for a state
    with one district and no block data.

    Two traps in the current MEDSL file, both silent if unhandled:

    The 2024 revision renamed FIPS to county_fips and county to county_name,
    and upper-cased the party values. A reader written against the older file
    matches nothing and reports zero votes rather than failing.

    More seriously, later years break returns down by voting mode -- early,
    absentee, provisional -- *and* also carry a TOTAL row. 3,282 keys have
    both, so adding every row up counts those ballots twice. Where a TOTAL
    exists it is the whole figure and the mode rows are its parts; only where
    there is no TOTAL do the modes need summing.
    """
    per = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    has_total = defaultdict(set)
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["year"] == str(year)]

    def key(r):
        return (r.get("county_fips") or r.get("FIPS"),
                r.get("candidate", ""), r["party"])

    for r in rows:
        if (r.get("mode") or "TOTAL").upper() == "TOTAL":
            has_total[r["state_po"]].add(key(r))

    for r in rows:
        i = {"DEMOCRAT": 0, "REPUBLICAN": 1}.get(r["party"].upper())
        if i is None:
            continue
        mode = (r.get("mode") or "TOTAL").upper()
        if mode != "TOTAL" and key(r) in has_total[r["state_po"]]:
            continue           # already counted in this key's TOTAL row
        try:
            per[r["state_po"]][key(r)][i] += int(r["candidatevotes"] or 0)
        except ValueError:
            pass

    out = {}
    for st, keys in per.items():
        d = sum(v[0] for v in keys.values())
        rp = sum(v[1] for v in keys.values())
        out[st] = (d, rp)
    return out


def blocks_2020(st):
    """{geoid: (lat, lon)} for every 2020 block of a state."""
    low = st.lower()
    p = ROOT / "upstream" / "2020" / low / f"{low}geo{2020}.pl"
    out = {}
    with open(p, encoding="latin-1") as f:
        for line in f:
            q = line.rstrip("\n").split("|")
            if len(q) < 94 or q[2] != "750":
                continue
            out[q[9]] = (float(q[92]), float(q[93]))
    return out


def blocks_2010_cd(st, bef):
    """2010 block centroids and their enacted district."""
    low = st.lower()
    hits = list(Path(bef).glob(f"{FIPS[st]}_{st}_CD*.txt"))
    if not hits:
        return None
    cd = {}
    with open(hits[0]) as f:
        next(f)
        for line in f:
            b, c = line.rstrip("\n").split(",")
            cd[b] = c
    lat, lon, dist = [], [], []
    p = ROOT / "upstream" / "2010" / low / f"{low}geo2010.pl"
    with open(p, encoding="latin-1") as f:
        for line in f:
            if line[8:11] != "750" or line[11:13] != "00":
                continue
            b = line[27:29] + line[29:32] + line[54:60] + line[61:65]
            c = cd.get(b)
            # "ZZ" marks a block in no district at all -- water, mostly.
            # Such blocks must not seed the spatial index, or a coastal block
            # could inherit "no district" from open sea next to it.
            if c is None or not c.isdigit():
                continue
            lat.append(float(line[336:347]))
            lon.append(float(line[347:359]))
            dist.append(int(c))
    return np.array(lat), np.array(lon), np.array(dist, np.int32)


def gnomonic(lon, lat, lon0, lat0, shift=0.0):
    lo, la = np.radians(lon + shift), np.radians(lat)
    l0, a0 = np.radians(lon0), np.radians(lat0)
    cosc = np.sin(a0)*np.sin(la) + np.cos(a0)*np.cos(la)*np.cos(lo-l0)
    return (np.degrees(np.cos(la)*np.sin(lo-l0)/cosc),
            np.degrees((np.cos(a0)*np.sin(la) - np.sin(a0)*np.cos(la)*np.cos(lo-l0))/cosc))


def walk(nodes, X, Y):
    out = np.full(len(X), -1, np.int32)
    stack = [(0, np.arange(len(X)))]
    while stack:
        i, sel = stack.pop()
        if not len(sel):
            continue
        n = nodes[i]
        if "district" in n:
            out[sel] = n["district"]; continue
        s = (X[sel]*n["nx"] + Y[sel]*n["ny"]) < n["c"]
        stack.append((n["left"], sel[s])); stack.append((n["right"], sel[~s]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contest", default="E_12_PRES")
    ap.add_argument("--census", type=int, default=2010)
    ap.add_argument("--rule", default="fixed")
    ap.add_argument("--metric", default="span")
    ap.add_argument("--model", default="uniform", choices=("uniform", "point"))
    ap.add_argument("--map", default="splitline", choices=("splitline", "actual"))
    ap.add_argument("--dra", default=str(ROOT/"upstream"/"elections"/"dra_block"/"x"))
    ap.add_argument("--bef", default=str(ROOT/"upstream"/"elections"/"cd113"))
    ap.add_argument("--year", type=int, default=2012,
                    help="election year, for the statewide fallback")
    ap.add_argument("--fallback",
                    default=str(ROOT/"upstream"/"elections"/"countypres_2000-2024.csv"))
    ap.add_argument("--out", default=str(ROOT/"work"/"block_votes.json"))
    a = ap.parse_args()

    plans = ROOT / "plans"
    pops = build(a.census, 0, 0)
    seats = huntington_hill(pops, house_size(a.rule, pops))
    rows, nomatch, far = [], 0, []

    for st in sorted(seats, key=lambda s: FIPS[s]):
        n = seats[st]
        if n <= 0:
            continue
        votes = dra_votes(st, a.contest, Path(a.dra))
        if not votes:
            # DRA has no 2012 blocks for the at-large states. They hold one
            # district, so the state total settles it exactly -- no allocation
            # and no model, just arithmetic.
            if n == 1 and a.fallback:
                sv = statewide(a.fallback, a.year)
                if st in sv:
                    d_, r_ = sv[st]
                    rows.append({"state": st, "district": 1,
                                 "dem": round(d_), "rep": round(r_),
                                 "winner": "D" if d_ > r_ else "R",
                                 "source": "statewide"})
                    print(f"  {st}  1  statewide  "
                          f"{'D' if d_ > r_ else 'R'}", flush=True)
                    continue
            print(f"  {st}: no {a.contest} data"); continue
        coords = blocks_2020(st)
        gids = [g for g in votes if g in coords]
        nomatch += len(votes) - len(gids)
        if not gids:
            print(f"  {st}: no geoid overlap"); continue
        lat = np.array([coords[g][0] for g in gids])
        lon = np.array([coords[g][1] for g in gids])
        dv = np.array([votes[g][0] for g in gids])
        rv = np.array([votes[g][1] for g in gids])

        if a.map == "actual":
            ref = blocks_2010_cd(st, a.bef)
            if ref is None:
                print(f"  {st}: no equivalency file"); continue
            rlat, rlon, rdist = ref
            from scipy.spatial import cKDTree
            # plane approximation is fine: we only need the nearest neighbour
            k = np.cos(np.radians(rlat.mean()))
            tree = cKDTree(np.c_[rlon*k, rlat])
            d, idx = tree.query(np.c_[lon*k, lat], k=1)
            dist = rdist[idx]
            far.append((st, d*M_PER_DEG, dv+rv))
        else:
            t = plans / f"{a.census}_{st.lower()}_{n}_{a.model}_{a.metric}.json"
            if not t.exists():
                print(f"  {st}: no tree"); continue
            tj = json.load(open(t)); pr = tj["projection"]
            nodes = {x["i"]: x for x in tj["nodes"]}
            X, Y = gnomonic(lon, lat, pr["lon0"], pr["lat0"], pr.get("lon_shift", 0.0))
            dist = walk(nodes, X, Y)

        per = defaultdict(lambda: [0.0, 0.0])
        for dd, x, y in zip(dist.tolist(), dv.tolist(), rv.tolist()):
            per[dd][0] += x; per[dd][1] += y
        for dd in sorted(per):
            x, y = per[dd]
            rows.append({"state": st, "district": int(dd), "dem": round(x),
                         "rep": round(y), "winner": "D" if x > y else "R"})
        print(f"  {st} {n:2}  D {sum(1 for r in rows if r['state']==st and r['winner']=='D'):2}"
              f" / R {sum(1 for r in rows if r['state']==st and r['winner']=='R'):2}", flush=True)

    D = sum(1 for r in rows if r["winner"] == "D"); R = len(rows) - D
    x = sum(r["dem"] for r in rows); y = sum(r["rep"] for r in rows)
    print(f"\n{'='*50}\n{a.map} map | {a.contest} | block-level votes")
    print(f"votes  D {x:,.0f} ({100*x/(x+y):.1f}%)   R {y:,.0f} ({100*y/(x+y):.1f}%)")
    print(f"seats  D {D}   R {R}   of {len(rows)}")
    if nomatch:
        print(f"blocks with votes but no 2020 centroid: {nomatch:,}")
    if far:
        alld = np.concatenate([f[1] for f in far]); allv = np.concatenate([f[2] for f in far])
        for thr in (100, 250, 500, 1000):
            sh = 100*allv[alld > thr].sum()/allv.sum()
            print(f"  votes whose nearest 2010 block is >{thr:4} m away: {sh:.2f}%")
    Path(a.out).write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
