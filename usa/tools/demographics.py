#!/usr/bin/env python3
"""Who gains and who loses when districts are drawn by algorithm.

The partisan question -- how many seats each party wins -- is not the only
distributional question a districting answers, and arguably not the one with
the strongest evidence behind it. Since 1982 the Voting Rights Act has been
read to require districts in which a minority group can elect a candidate of
its choice, and those districts are frequently not compact: they follow a
river, a rail corridor, a chain of neighbourhoods. An algorithm that cuts on
the shortest available straight line cannot see them and will not preserve
them.

So this counts, for every district under a given plan, the voting-age
population by race and Hispanic origin, and reports how many districts clear
the thresholds that matter in practice:

  majority     >50%   the VRA benchmark for a district that can elect
  opportunity  40-50% frequently sufficient in practice with coalition or
                      crossover voting, and the level courts increasingly argue about
  influence    30-40% not enough to elect, enough to be courted

Voting-age population, not total population, because that is the VRA
denominator and because children do not vote. Table P4 of PL 94-171 -- "not
Hispanic or Latino, by race, for the population 18 years and over" -- is the
standard source and makes Hispanic origin and race mutually exclusive, so the
categories sum to the total and shares are comparable across groups.

Comparing this between the enacted plan and the splitline plan measures
something real and testable: whether a rule that is blind to race by
construction is also neutral in effect. There is no reason to expect that it
is, and the point of measuring rather than asserting is that the direction and
size of the effect are the finding.
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared" / "tools"))
from apportion import build, house_size, huntington_hill  # noqa: E402
from apportionment import FIPS  # noqa: E402
from block_votes import blocks_2010_cd, gnomonic, walk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# P4 offsets within the table (P0040001 is index 0). Hispanic origin first,
# then the non-Hispanic single races, so every person falls in exactly one.
GROUPS = [("hispanic", 1), ("nh_white", 4), ("nh_black", 5), ("nh_aian", 6),
          ("nh_asian", 7), ("nh_nhpi", 8), ("nh_other", 9), ("nh_multi", 10)]
# Groups large enough nationally for district counts to mean anything.
HEADLINE = ["hispanic", "nh_white", "nh_black", "nh_asian"]


def vap_2010(st):
    """{logrecno: [P0040001..P0040011]} plus block geo, for the 2010 vintage."""
    low = st.lower()
    seg = ROOT / "upstream" / "2010" / low / f"{low}000022010.pl"
    vap = {}
    with open(seg, newline="", encoding="latin-1") as f:
        for row in csv.reader(f):
            if len(row) < 152:
                continue
            # 5 header fields, then P3 (71 fields), then P4.
            vap[row[4]] = [int(x or 0) for x in row[76:87]]
    lat, lon, rec = [], [], []
    with open(ROOT / "upstream" / "2010" / low / f"{low}geo2010.pl",
              encoding="latin-1") as f:
        for line in f:
            if line[8:11] != "750" or line[11:13] != "00":
                continue
            lat.append(float(line[336:347])); lon.append(float(line[347:359]))
            rec.append(line[18:25])
    return np.array(lat), np.array(lon), rec, vap


def vap_2020(st):
    low = st.lower()
    seg = ROOT / "upstream" / "2020" / low / f"{low}000022020.pl"
    vap = {}
    with open(seg, encoding="latin-1") as f:
        for line in f:
            q = line.rstrip("\n").split("|")
            if len(q) < 152:
                continue
            vap[q[4]] = [int(x or 0) for x in q[76:87]]
    lat, lon, rec = [], [], []
    with open(ROOT / "upstream" / "2020" / low / f"{low}geo2020.pl",
              encoding="latin-1") as f:
        for line in f:
            q = line.rstrip("\n").split("|")
            if len(q) < 94 or q[2] != "750" or q[4] != "00":
                continue
            lat.append(float(q[92])); lon.append(float(q[93])); rec.append(q[7])
    return np.array(lat), np.array(lon), rec, vap


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--census", type=int, default=2010, choices=(2010, 2020))
    ap.add_argument("--rule", default="fixed")
    ap.add_argument("--metric", default="span")
    ap.add_argument("--model", default="uniform")
    ap.add_argument("--enacted", action="store_true")
    ap.add_argument("--states", nargs="*", default=None)
    ap.add_argument("--bef", default=str(ROOT/"upstream"/"elections"/"cd113"))
    ap.add_argument("--out", default=str(ROOT/"results"/"demographics"))
    a = ap.parse_args()

    pops = build(a.census, 0, 0)
    seats = huntington_hill(pops, house_size(a.rule, pops))
    states = [s for s in sorted(seats, key=lambda s: FIPS[s]) if seats[s] > 0]
    if a.states:
        states = [s for s in states if s in set(a.states)]

    plans = {f"splitline_{a.census}": []}
    if a.enacted and a.census == 2010:
        plans["enacted_cd113"] = []

    for i, st in enumerate(states, 1):
        n = seats[st]
        lat, lon, rec, vap = (vap_2010 if a.census == 2010 else vap_2020)(st)
        # P4 for every block, in block order; a block with no record is zero.
        tab = np.array([vap.get(r, [0] * 11) for r in rec], dtype=np.int64)

        assign = {}
        p = ROOT / "plans" / f"{a.census}_{st.lower()}_{n}_{a.model}_{a.metric}.json"
        if p.exists():
            j = json.load(open(p)); pr = j["projection"]
            X, Y = gnomonic(lon, lat, pr["lon0"], pr["lat0"],
                            pr.get("lon_shift", 0.0))
            assign[f"splitline_{a.census}"] = walk({x["i"]: x for x in j["nodes"]}, X, Y)
        if "enacted_cd113" in plans:
            ref = blocks_2010_cd(st, a.bef)
            if ref is not None:
                from scipy.spatial import cKDTree
                rlat, rlon, rdist = ref
                k = np.cos(np.radians(rlat.mean()))
                _, ix = cKDTree(np.c_[rlon * k, rlat]).query(np.c_[lon * k, lat], k=1)
                assign["enacted_cd113"] = rdist[ix]

        for pk, dist in assign.items():
            m = int(dist.max()) + 1
            for d in range(m):
                sel = dist == d
                if not sel.any():
                    continue
                tot = int(tab[sel, 0].sum())
                if tot <= 0:
                    continue
                row = {"state": st, "district": d, "vap": tot}
                for name, off in GROUPS:
                    v = int(tab[sel, off].sum())
                    row[name] = v
                    row[name + "_pct"] = round(100 * v / tot, 2)
                plans[pk].append(row)
        print(f"  [{i}/{len(states)}] {st}", flush=True)

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for pk, rows in plans.items():
        if not rows:
            continue
        (out / f"{pk}.json").write_text(json.dumps(rows, indent=1))
        s = {"districts": len(rows)}
        for g in HEADLINE:
            s[g] = {
                "majority": sum(1 for r in rows if r[g + "_pct"] > 50),
                "opportunity_40_50": sum(1 for r in rows if 40 < r[g + "_pct"] <= 50),
                "influence_30_40": sum(1 for r in rows if 30 < r[g + "_pct"] <= 40),
                "national_vap_pct": round(
                    100 * sum(r[g] for r in rows) / sum(r["vap"] for r in rows), 2),
            }
        summary[pk] = s
    (out / f"summary_{a.census}.json").write_text(json.dumps(summary, indent=1))

    print(f"\n{'='*72}\nvoting-age population, {a.census} census")
    for pk, s in summary.items():
        print(f"\n{pk}  ({s['districts']} districts)")
        print(f"  {'group':10} {'natl VAP%':>10} {'majority':>9} {'40-50%':>8} {'30-40%':>8}")
        for g in HEADLINE:
            x = s[g]
            print(f"  {g:10} {x['national_vap_pct']:10.2f} {x['majority']:9} "
                  f"{x['opportunity_40_50']:8} {x['influence_30_40']:8}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
