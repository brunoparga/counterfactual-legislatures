#!/usr/bin/env python3
"""Is splitline actually compact? Measured against the enacted map.

WHY THIS METRIC AND NOT A SHAPE ONE

The usual compactness scores -- Polsby-Popper, Reock, convex-hull -- all need
district *geometry*: a perimeter, a bounding circle, a hull. A splitline plan
has exact geometry, being an intersection of half-planes, but the enacted
113th-Congress plan reaches us as a list of block assignments with no polygons
at all, so a shape score cannot be computed for the thing we need to compare
against without first reconstructing boundaries we do not have.

This one needs no geometry from either side:

    population-weighted mean distance from a resident to the
    population-weighted centroid of their district

It is Brian Olson's BDistricting objective, which is convenient twice over: it
is defined on assignments rather than shapes, so both plans can be scored the
same way, and it puts a number on this repository's relationship to Olson's
method without touching his GPL code.

It also measures the thing compactness is *for*. A district's residents being
close to its centre is what makes a district a place; perimeter ratios are a
proxy for that, and a poor one for a coastline.

DISTANCES ARE SPHERICAL, CENTROIDS ARE TOO

A district can be 800 km across and Alaska is worse, so the centroid is the
normalised population-weighted mean of the blocks' 3-D unit vectors and the
distance to it is a great circle. A flat-earth mean of latitudes and
longitudes would put the centroid of an Alaskan district in the wrong ocean.

VINTAGE

Both plans are scored on 2010 census blocks. The enacted plan is published on
2010 blocks, so there is no crosswalk and no nearest-centroid join anywhere in
this file -- unlike the vote scoring, where the election data is on 2020
blocks and the join has to be measured. A splitline plan is a set of
half-planes and partitions any vintage exactly.

THE GATE

Block populations must sum to the state's own published total, the check
pl_to_pop.py makes for every state it converts. Both numbers are in the same
geographic header: summary level 750 is a block, summary level 040 is the
state. If they disagree, a field offset is wrong and every distance computed
from those coordinates is wrong too.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apportion import build, house_size, huntington_hill  # noqa: E402
from apportionment import FIPS  # noqa: E402
from block_votes import gnomonic, walk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
R_EARTH_KM = 6371.0088


def read_blocks_2010(st):
    """(geoid, pop, lat, lon) arrays and the published state total.

    Fixed-width PL 94-171: SUMLEV @8(3), GEOCOMP @11(2), STATE @27(2),
    COUNTY @29(3), TRACT @54(6), BLOCK @61(4), POP100 @318(9),
    INTPTLAT @336(11), INTPTLON @347(12). Offsets as in pl_to_pop.py.
    """
    low = st.lower()
    p = ROOT / "upstream" / "2010" / low / f"{low}geo2010.pl"
    gid, pop, lat, lon = [], [], [], []
    state_total = None
    with open(p, encoding="latin-1") as f:
        for line in f:
            if line[11:13] != "00":
                continue
            lev = line[8:11]
            if lev == "040":
                if state_total is None:
                    state_total = int(line[318:327] or 0)
                continue
            if lev != "750":
                continue
            gid.append(line[27:29] + line[29:32] + line[54:60] + line[61:65])
            pop.append(int(line[318:327] or 0))
            lat.append(float(line[336:347]))
            lon.append(float(line[347:359]))
    return (gid, np.array(pop, np.int64), np.array(lat), np.array(lon),
            state_total)


def enacted_districts(st, bef, gid):
    """District number per block, -1 where the block is in none of them."""
    hits = list(Path(bef).glob(f"{FIPS[st]}_{st}_CD*.txt"))
    if not hits:
        return None
    cd = {}
    with open(hits[0]) as f:
        next(f)
        for line in f:
            b, c = line.rstrip("\n").split(",")
            # "ZZ" marks a block in no district at all -- open water.
            if c.isdigit():
                cd[b] = int(c)
    return np.array([cd.get(g, -1) for g in gid], np.int32)


def mean_distance(pop, lat, lon, dist):
    """Population-weighted mean km from a resident to their district centroid.

    Returns (national-style mean, per-district table). Blocks with no
    population contribute nothing by construction, and blocks assigned to no
    district are excluded by the caller rather than silently given one.
    """
    la, lo = np.radians(lat), np.radians(lon)
    xyz = np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo),
                    np.sin(la)], axis=1)
    w = pop.astype(np.float64)
    n = int(dist.max()) + 1
    tot = np.bincount(dist, weights=w, minlength=n)
    cent = np.stack([np.bincount(dist, weights=w * xyz[:, k], minlength=n)
                     for k in range(3)], axis=1)
    norm = np.linalg.norm(cent, axis=1)
    good = norm > 0
    cent[good] /= norm[good, None]
    # great-circle angle between each block and its district's centroid
    cosang = np.clip((xyz * cent[dist]).sum(1), -1.0, 1.0)
    km = R_EARTH_KM * np.arccos(cosang)
    per = np.bincount(dist, weights=w * km, minlength=n)
    rows = [{"district": int(d), "population": int(tot[d]),
             "mean_km": round(float(per[d] / tot[d]), 3)}
            for d in range(n) if tot[d] > 0]
    return float(per.sum()), float(w.sum()), rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="uniform")
    ap.add_argument("--metric", default="span")
    ap.add_argument("--rule", default="fixed")
    ap.add_argument("--states", nargs="*", default=None)
    ap.add_argument("--bef", default=str(ROOT/"upstream"/"elections"/"cd113"))
    ap.add_argument("--out", default=str(ROOT/"results"/"compactness.json"))
    a = ap.parse_args()

    pops = build(2010, 0, 0)
    seats = huntington_hill(pops, house_size(a.rule, pops))
    states = sorted((s for s, n in seats.items() if n > 0), key=lambda s: FIPS[s])
    if a.states:
        states = [s for s in states if s in set(a.states)]

    per_state, gate_fail = [], []
    tot = {"splitline": [0.0, 0.0], "enacted": [0.0, 0.0]}
    t0 = time.time()
    for i, st in enumerate(states, 1):
        gid, pop, lat, lon, state_total = read_blocks_2010(st)
        block_total = int(pop.sum())
        ok = state_total is not None and block_total == state_total
        if not ok:
            gate_fail.append((st, block_total, state_total))
            print(f"  [{i}/{len(states)}] {st}  GATE FAILED  blocks {block_total:,}"
                  f" vs state {state_total}", flush=True)
            continue

        n = seats[st]
        plan = ROOT / "plans" / f"2010_{st.lower()}_{n}_{a.model}_{a.metric}.json"
        row = {"state": st, "seats": n, "population": block_total,
               "blocks": len(gid)}
        if plan.exists():
            j = json.loads(plan.read_text())
            pr = j["projection"]
            nodes = {x["i"]: x for x in j["nodes"]}
            X, Y = gnomonic(lon, lat, pr["lon0"], pr["lat0"],
                            pr.get("lon_shift", 0.0))
            d = walk(nodes, X, Y)
            s, w, rows = mean_distance(pop, lat, lon, d)
            row["splitline"] = {"mean_km": round(s / w, 3), "districts": len(rows)}
            tot["splitline"][0] += s
            tot["splitline"][1] += w

        ed = enacted_districts(st, a.bef, gid)
        if ed is not None:
            sel = ed >= 0
            lost = int(pop[~sel].sum())
            s, w, rows = mean_distance(pop[sel], lat[sel], lon[sel], ed[sel])
            row["enacted"] = {"mean_km": round(s / w, 3), "districts": len(rows),
                              "population_in_no_district": lost}
            tot["enacted"][0] += s
            tot["enacted"][1] += w
        if "splitline" in row and "enacted" in row:
            row["change_pct"] = round(
                100 * (row["splitline"]["mean_km"] - row["enacted"]["mean_km"])
                / row["enacted"]["mean_km"], 2)
        per_state.append(row)
        sl = row.get("splitline", {}).get("mean_km")
        en = row.get("enacted", {}).get("mean_km")
        print(f"  [{i}/{len(states)}] {st:2} {n:2} seats  "
              f"splitline {sl if sl is None else f'{sl:8.2f}'} km  "
              f"enacted {en if en is None else f'{en:8.2f}'} km  "
              f"{time.time()-t0:.0f}s", flush=True)

    both = [r for r in per_state if "splitline" in r and "enacted" in r]
    doc = {"metric": "population-weighted mean km from a resident to the "
                     "population-weighted centroid of their district",
           "census": 2010, "model": a.model, "cut_metric": a.metric,
           "house_size_rule": a.rule,
           "gate": "block populations sum to the published state total",
           "gate_failures": [{"state": s, "blocks": b, "state_total": t}
                             for s, b, t in gate_fail],
           "national": {
               "splitline_mean_km": round(tot["splitline"][0] / tot["splitline"][1], 3)
               if tot["splitline"][1] else None,
               "enacted_mean_km": round(tot["enacted"][0] / tot["enacted"][1], 3)
               if tot["enacted"][1] else None},
           "states": per_state}
    nat = doc["national"]
    if nat["splitline_mean_km"] and nat["enacted_mean_km"]:
        nat["change_pct"] = round(100 * (nat["splitline_mean_km"] -
                                         nat["enacted_mean_km"])
                                  / nat["enacted_mean_km"], 2)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=1))

    print(f"\nGATE  {len(gate_fail)} states where blocks do not sum to the "
          f"published state total")
    if gate_fail:
        print("      STOP -- an offset is wrong")
    print(f"\nnational, population-weighted over {len(both)} states:")
    print(f"  splitline {nat['splitline_mean_km']:.2f} km")
    print(f"  enacted   {nat['enacted_mean_km']:.2f} km")
    print(f"  change    {nat.get('change_pct'):+.1f}%")
    worse = sorted((r for r in both if r["seats"] > 1),
                   key=lambda r: -r["change_pct"])
    print(f"\nsplitline least compact vs enacted:")
    for r in worse[:8]:
        print(f"  {r['state']:2} {r['seats']:2} seats  "
              f"{r['enacted']['mean_km']:7.2f} -> {r['splitline']['mean_km']:7.2f} km"
              f"  {r['change_pct']:+7.1f}%")
    print(f"\nsplitline most compact vs enacted:")
    for r in worse[-8:][::-1]:
        print(f"  {r['state']:2} {r['seats']:2} seats  "
              f"{r['enacted']['mean_km']:7.2f} -> {r['splitline']['mean_km']:7.2f} km"
              f"  {r['change_pct']:+7.1f}%")
    print(f"\nwrote {a.out}")
    return 1 if gate_fail else 0


if __name__ == "__main__":
    sys.exit(main())
