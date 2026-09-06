#!/usr/bin/env python3
"""Score every districting plan against every election we have, in one pass.

The per-contest scorer (block_votes.py) re-reads a state's census geoheader
for each run. That file is the expensive part -- 3.9 GB across the country --
so scoring eight contests against three censuses that way means twenty-four
passes over it to answer a question that only needs one.

Here the loop is inverted. A state is opened once; its block coordinates and
every contest on those blocks are read once; then each plan is walked and each
contest aggregated against the resulting district assignment. Reading is O(1)
in the number of (plan, contest) pairs, which is what makes the full matrix
cheap enough to rerun whenever a plan changes.

WHAT A SCORE MEANS

The vote is presidential, not congressional. Block-level House returns barely
exist -- 26 states in 2024, 21 in 2022, 3 in 2016 -- so there is no national
House map to be had at this resolution. Presidential vote as a measure of a
district's partisan lean is the standard substitute in redistricting work, and
it has a real advantage for this question: it is the same contest everywhere,
so it does not confound the districting with incumbency, candidate quality or
uncontested seats. It is not a forecast of who would have won the seat. It is
the partisan balance of the ground the seat is drawn on.

VINTAGES

Votes arrive on 2020 census blocks whatever year they were cast. A splitline
plan is a set of half-planes, so it partitions any point regardless of vintage
and no crosswalk is needed. An enacted plan is a list of 2010 block IDs, which
name different ground than 2020 IDs do, so those are joined by nearest
centroid instead -- see block_votes.py, where that method is validated against
the known 209/226 result for 2012.
"""

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared" / "tools"))
from apportion import build, house_size, huntington_hill  # noqa: E402
from apportionment import FIPS  # noqa: E402
from block_votes import blocks_2010_cd, blocks_2020, gnomonic, statewide, walk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
M_PER_DEG = 111320.0

# Which election a contest code refers to, for the statewide fallback. A
# composite has no single year, so it falls back to the mean of its parts.
CONTEST_YEAR = {"E_08_PRES": (2008,), "E_12_PRES": (2012,), "E_16_PRES": (2016,),
                "E_20_PRES": (2020,), "E_24_PRES": (2024,),
                "E_16-20_COMP": (2016, 2020)}

# The census whose districts were in force at each election. This is the
# pairing that makes a counterfactual honest: a plan is scored against the
# elections actually held under districts drawn from that census.
NATURAL = {2000: ["E_08_PRES"],
           2010: ["E_12_PRES", "E_16_PRES", "E_20_PRES", "E_16-20_COMP"],
           2020: ["E_20_PRES", "E_16-20_COMP", "E_24_PRES"]}


def read_state_votes(st, root, contests):
    """{contest: {geoid: (dem, rep, total)}} -- one pass over the state file."""
    hits = list((Path(root) / st).glob("election_data_block_*.csv"))
    if not hits:
        return {}
    with open(hits[0], newline="") as f:
        rd = csv.reader(f)
        head = next(rd)
        gi = head.index("GEOID")
        cols = {}
        for c in contests:
            try:
                cols[c] = (head.index(f"{c}_Dem"), head.index(f"{c}_Rep"),
                           head.index(f"{c}_Total"))
            except ValueError:
                continue
        if not cols:
            return {}
        out = {c: {} for c in cols}
        for row in rd:
            g = row[gi]
            for c, (di, ri, ti) in cols.items():
                try:
                    d, r = float(row[di] or 0), float(row[ri] or 0)
                    t = float(row[ti] or 0)
                except ValueError:
                    continue
                if d or r:
                    out[c][g] = (d, r, t)
    return out


def load_plan(census, st, n, model, metric):
    p = ROOT / "plans" / f"{census}_{st.lower()}_{n}_{model}_{metric}.json"
    if not p.exists():
        return None
    j = json.load(open(p))
    return j["projection"], {x["i"]: x for x in j["nodes"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--censuses", nargs="*", type=int, default=[2000, 2010, 2020])
    ap.add_argument("--contests", nargs="*", default=None,
                    help="default: the contests naturally paired with each census")
    ap.add_argument("--all-pairs", action="store_true",
                    help="score every contest against every census, not just "
                         "the ones held under that census's districts")
    ap.add_argument("--states", nargs="*", default=None, help="subset, for testing")
    ap.add_argument("--rule", default="fixed")
    ap.add_argument("--metric", default="span")
    ap.add_argument("--model", default="uniform", choices=("uniform", "point"))
    ap.add_argument("--enacted", action="store_true",
                    help="also score the enacted 113th-Congress plan (2010 only)")
    ap.add_argument("--dra", default=str(ROOT/"upstream"/"elections"/"dra_block"/"x"))
    ap.add_argument("--bef", default=str(ROOT/"upstream"/"elections"/"cd113"))
    ap.add_argument("--fallback",
                    default=str(ROOT/"upstream"/"elections"/"countypres_2000-2024.csv"))
    ap.add_argument("--out", default=str(ROOT/"results"))
    a = ap.parse_args()

    if a.contests:
        pairs = {c: list(a.censuses) for c in a.contests}
    elif a.all_pairs:
        pairs = {c: list(a.censuses) for c in CONTEST_YEAR}
    else:
        pairs = defaultdict(list)
        for cs in a.censuses:
            for c in NATURAL.get(cs, []):
                pairs[c].append(cs)
    contests = sorted(pairs)
    print(f"contests {contests}")

    seats = {cs: huntington_hill(build(cs, 0, 0),
                                 house_size(a.rule, build(cs, 0, 0)))
             for cs in a.censuses}

    # (plan_key, contest) -> list of district rows
    res = defaultdict(list)
    # (plan_key, contest) -> states that should be there and are not
    gaps = defaultdict(list)
    plan_keys = [f"splitline_{cs}" for cs in a.censuses]
    if a.enacted and 2010 in a.censuses:
        plan_keys.append("enacted_cd113")

    sv_cache = {}

    def state_totals(st, contest):
        """Two-party statewide totals from county returns, for at-large states."""
        yrs = CONTEST_YEAR.get(contest)
        if not yrs:
            return None
        acc = [0.0, 0.0]
        for y in yrs:
            if y not in sv_cache:
                sv_cache[y] = statewide(a.fallback, y)
            v = sv_cache[y].get(st)
            if v is None:
                return None
            acc[0] += v[0] / len(yrs)
            acc[1] += v[1] / len(yrs)
        return acc

    states = sorted({s for cs in a.censuses for s, n in seats[cs].items() if n > 0},
                    key=lambda s: FIPS[s])
    if a.states:
        states = [s for s in states if s in set(a.states)]
    t0 = time.time()
    for i, st in enumerate(states, 1):
        votes = read_state_votes(st, a.dra, contests)
        coords = blocks_2020(st) if votes else {}
        gids = sorted({g for c in votes for g in votes[c]} & set(coords)) if votes else []
        if gids:
            lat = np.array([coords[g][0] for g in gids])
            lon = np.array([coords[g][1] for g in gids])
            idx = {g: k for k, g in enumerate(gids)}
            vecs = {}
            for c in votes:
                d = np.zeros(len(gids)); r = np.zeros(len(gids)); t = np.zeros(len(gids))
                for g, (dv, rv, tv) in votes[c].items():
                    k = idx.get(g)
                    if k is not None:
                        d[k], r[k], t[k] = dv, rv, tv
                vecs[c] = (d, r, t)
        else:
            vecs = {}

        assign = {}
        for cs in a.censuses:
            n = seats[cs].get(st, 0)
            if n <= 0 or not gids:
                continue
            pl = load_plan(cs, st, n, a.model, a.metric)
            if pl is None:
                continue
            pr, nodes = pl
            X, Y = gnomonic(lon, lat, pr["lon0"], pr["lat0"],
                            pr.get("lon_shift", 0.0))
            assign[f"splitline_{cs}"] = walk(nodes, X, Y)
        if a.enacted and 2010 in a.censuses and gids:
            ref = blocks_2010_cd(st, a.bef)
            if ref is not None:
                from scipy.spatial import cKDTree
                rlat, rlon, rdist = ref
                k = np.cos(np.radians(rlat.mean()))
                tree = cKDTree(np.c_[rlon * k, rlat])
                _, ix = tree.query(np.c_[lon * k, lat], k=1)
                assign["enacted_cd113"] = rdist[ix]

        for c in contests:
            for cs in pairs[c]:
                n = seats[cs].get(st, 0)
                if n <= 0:
                    continue
                for pk in plan_keys:
                    if pk.startswith("splitline") and pk != f"splitline_{cs}":
                        continue
                    if pk == "enacted_cd113" and cs != 2010:
                        continue
                    dist = assign.get(pk)
                    if dist is None or c not in vecs:
                        tot = state_totals(st, c) if n == 1 else None
                        if tot:
                            res[(pk, c)].append(
                                {"state": st, "district": 1,
                                 "dem": round(tot[0]), "rep": round(tot[1]),
                                 "total": round(tot[0] + tot[1]),
                                 "source": "statewide"})
                        else:
                            gaps[(pk, c)].append(st)
                        continue
                    d, r, t = vecs[c]
                    m = int(dist.max()) + 1
                    dd = np.bincount(dist, weights=d, minlength=m)
                    rr = np.bincount(dist, weights=r, minlength=m)
                    tt = np.bincount(dist, weights=t, minlength=m)
                    for k in range(m):
                        if dd[k] or rr[k]:
                            res[(pk, c)].append(
                                {"state": st, "district": k,
                                 "dem": round(float(dd[k])),
                                 "rep": round(float(rr[k])),
                                 "total": round(float(tt[k]))})
        print(f"  [{i}/{len(states)}] {st}  {len(gids):,} blocks  "
              f"{time.time()-t0:.0f}s", flush=True)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for (pk, c), rows in sorted(res.items()):
        for row in rows:
            tp = row["dem"] + row["rep"]
            row["winner"] = "D" if row["dem"] > row["rep"] else "R"
            # positive is Democratic. Two-party, so a third-party surge moves
            # neither side's share and the margin stays comparable across years.
            row["margin"] = round(100 * (row["dem"] - row["rep"]) / tp, 2) if tp else 0.0
        D = sum(1 for r in rows if r["winner"] == "D")
        dv = sum(r["dem"] for r in rows); rv = sum(r["rep"] for r in rows)
        meta = {"plan": pk, "contest": c, "rule": a.rule, "metric": a.metric,
                "model": a.model, "districts": len(rows),
                "seats_D": D, "seats_R": len(rows) - D,
                "votes_D": dv, "votes_R": rv,
                "vote_share_D": round(100 * dv / (dv + rv), 3) if dv + rv else 0,
                "seat_share_D": round(100 * D / len(rows), 3) if rows else 0,
                "missing_states": sorted(set(gaps.get((pk, c), [])))}
        meta["bias"] = round(meta["seat_share_D"] - meta["vote_share_D"], 3)
        p = out / f"{pk}__{c}.json"
        p.write_text(json.dumps({"meta": meta, "districts": rows}, indent=1))
        index.append(meta | {"file": p.name})
        print(f"{pk:18} {c:14} D {D:3} R {len(rows)-D:3}  "
              f"votes D {meta['vote_share_D']:5.2f}%  seats D "
              f"{meta['seat_share_D']:5.2f}%  bias {meta['bias']:+.2f}"
              + (f"  MISSING {meta['missing_states']}" if meta["missing_states"] else ""))
    (out / "index.json").write_text(json.dumps(index, indent=1))
    print(f"\nwrote {len(index)} scorings to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
