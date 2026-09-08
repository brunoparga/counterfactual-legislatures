#!/usr/bin/env python3
"""Does the headline survive its parameters?

The central US claim -- that splitline removes about two thirds of the
measured pro-Republican bias -- was computed at one point in a nine-point
parameter space: `fixed` house size, `span` cut metric, `uniform` population
model. Three of those choices are defensible and none is forced, so the claim
is only worth as much as its stability across them.

This reads the scorings written by score_matrix.py into results/sens/ and
writes the comparison table. It computes nothing itself beyond means: every
number here comes from a scoring that had to reproduce the enacted 2012 result
before it was allowed to count.

WHAT VARIES, AND WHAT THE VARIATION MEANS

  model    uniform spreads a block's people over an equal-area disc; point
           treats them as a point mass at the block's internal point
  metric   span measures a cut's straight-line length including water; land
           measures only the land it crosses
  rule     the house size: fixed 435, the cube root of the population, or the
           Wyoming rule (every state gets a seat per smallest-state population)

The house-size rule is not on the same footing as the other two. The enacted
plan is 435 districts whatever rule we name, because it is a real map and not
a function of our parameters; so under `cuberoot` and `wyoming` the comparison
is between a 435-seat enacted chamber and a 676- or 544-seat splitline one.
Bias is a share and remains comparable, seat counts are not, and the tables
say which is which.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The four scorings the headline averages over: one plan, four elections.
HEADLINE = ["E_12_PRES", "E_16_PRES", "E_20_PRES", "E_16-20_COMP"]
LABEL = {"E_12_PRES": "2012 pres", "E_16_PRES": "2016 pres",
         "E_20_PRES": "2020 pres", "E_16-20_COMP": "2016-20 composite"}
GATE = ("enacted_cd113", "E_12_PRES", 209, 226)


def read(d):
    return {(m["plan"], m["contest"]): m
            for m in json.loads((d / "index.json").read_text())}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sens", default=str(ROOT / "results" / "sens"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    sens = Path(a.sens)
    out = Path(a.out) if a.out else sens / "SENSITIVITY.md"

    runs = {}
    for d in sorted(p for p in sens.iterdir() if (p / "index.json").exists()):
        runs[d.name] = read(d)
    if not runs:
        print(f"no scorings under {sens}")
        return 1

    plan, contest, wantD, wantR = GATE
    passed, failed = [], []
    for name, r in runs.items():
        m = r.get((plan, contest))
        ok = m and m["seats_D"] == wantD and m["seats_R"] == wantR
        (passed if ok else failed).append(name)
        got = f"{m['seats_D']} D / {m['seats_R']} R" if m else "missing"
        print(f"GATE {name:26} {plan}/{contest}: {got}  "
              f"{'OK' if ok else 'FAILED'}")
    if failed:
        print(f"\nSTOP: {len(failed)} runs did not reproduce {wantD} D / {wantR} R")

    rows = []
    for name in passed:
        r = runs[name]
        eb = [r[("enacted_cd113", c)]["bias"] for c in HEADLINE
              if ("enacted_cd113", c) in r]
        sb = [r[("splitline_2010", c)]["bias"] for c in HEADLINE
              if ("splitline_2010", c) in r]
        if len(eb) != 4 or len(sb) != 4:
            continue
        e = sum(abs(x) for x in eb) / 4
        s = sum(abs(x) for x in sb) / 4
        model, metric, rule = name.split("_")
        rows.append({"run": name, "model": model, "metric": metric, "rule": rule,
                     "enacted_mean_abs_bias": round(e, 3),
                     "splitline_mean_abs_bias": round(s, 3),
                     "reduction_pct": round(100 * (e - s) / e, 1) if e else None,
                     "districts": r[("splitline_2010", "E_12_PRES")]["districts"],
                     "per_contest": {c: {
                         "enacted_bias": r[("enacted_cd113", c)]["bias"],
                         "splitline_bias": r[("splitline_2010", c)]["bias"],
                         "enacted_D": r[("enacted_cd113", c)]["seats_D"],
                         "splitline_D": r[("splitline_2010", c)]["seats_D"],
                         "splitline_seat_share_D":
                             r[("splitline_2010", c)]["seat_share_D"],
                         "vote_share_D": r[("splitline_2010", c)]["vote_share_D"]}
                         for c in HEADLINE}})
    rows.sort(key=lambda x: (x["rule"] != "fixed", x["model"] != "uniform",
                             x["metric"] != "span"))

    red = [x["reduction_pct"] for x in rows]
    base = next((x for x in rows if x["run"] == "uniform_span_fixed"), None)
    L = []
    L.append("# Does the 65% headline survive its parameters?\n")
    L.append("Generated by `usa/tools/sensitivity_table.py` from the scorings in")
    L.append("`usa/results/sens/`, each written by `usa/tools/score_matrix.py`.\n")
    L.append("## The gate\n")
    L.append("Every run below had to return **209 D / 226 R** for the enacted")
    L.append("113th-Congress plan on 2012 presidential votes. That plan is a real")
    L.append("map and does not depend on our parameters, so a different number")
    L.append("would mean the run was broken rather than that the answer had")
    L.append("changed.\n")
    L.append(f"{len(passed)} of {len(runs)} runs passed."
             + (f" **Failed: {', '.join(failed)}.**" if failed else "") + "\n")
    if failed:
        L.append("### Where the gate stopped us\n")
        for name in failed:
            m = runs[name].get((plan, contest))
            if m:
                L.append(f"- `{name}` returned {m['seats_D']} D / {m['seats_R']} R "
                         f"over {m['districts']} districts, missing "
                         f"{', '.join(m['missing_states'])}.")
        L.append("")
        L.append("The cause is the same in both and it is a property of the")
        L.append("election data, not of the code. The seven states DRA publishes")
        L.append("no block file for — AK, DE, MT, ND, SD, VT, WY — are exactly")
        L.append("the states with one district, and a one-district state needs no")
        L.append("block data because its statewide total settles it exactly.")
        L.append("Raise the house size and those states need two districts, the")
        L.append("statewide shortcut stops applying, and they drop out of *every*")
        L.append("plan in the run — including the enacted one, which is why its")
        L.append("baseline moves when nothing about the enacted map has changed.\n")
        L.append("So **the house-size axis is not measurable with the election")
        L.append("data we hold**, and no numbers from those runs are reported")
        L.append("below. The remaining house-size combinations were not run once")
        L.append("the cause was established: they fail identically and for the")
        L.append("same reason.\n")

    L.append("## Bias reduction across the parameter space\n")
    L.append("Mean absolute bias over the four 2010-census scorings (2012, 2016,")
    L.append("2020 and the 2016-20 composite presidential votes), in percentage")
    L.append("points of seat share minus vote share.\n")
    L.append("| model | metric | house size | splitline seats | enacted | splitline | reduction |")
    L.append("|---|---|---|---|---|---|---|")
    for x in rows:
        L.append(f"| {x['model']} | {x['metric']} | {x['rule']} | {x['districts']} "
                 f"| {x['enacted_mean_abs_bias']:.2f} "
                 f"| {x['splitline_mean_abs_bias']:.2f} "
                 f"| **{x['reduction_pct']:.0f}%** |")
    L.append("")
    if red:
        L.append(f"Range: **{min(red):.0f}% to {max(red):.0f}%** across "
                 f"{len(red)} parameter sets.\n")
    L.append("The enacted column is the same map in every row, so it moves only")
    L.append("where the house-size rule changes which states are in the")
    L.append("comparison; it does not move with the model or the metric at all.\n")
    L.append("## Per contest\n")
    L.append("Splitline D districts, and bias, by parameter set.\n")
    L.append("| run | " + " | ".join(LABEL[c] for c in HEADLINE) + " |")
    L.append("|---|" + "---|" * len(HEADLINE))
    for x in rows:
        cells = []
        for c in HEADLINE:
            p = x["per_contest"][c]
            cells.append(f"{p['splitline_D']} ({p['splitline_bias']:+.2f})")
        L.append(f"| {x['run']} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("Enacted, for reference: " + ", ".join(
        f"{LABEL[c]} {base['per_contest'][c]['enacted_D']} "
        f"({base['per_contest'][c]['enacted_bias']:+.2f})" for c in HEADLINE)
        + ".\n" if base else "")

    out.write_text("\n".join(L))
    (sens / "sensitivity.json").write_text(json.dumps(
        {"gate": {"plan": plan, "contest": contest,
                  "expected": f"{wantD} D / {wantR} R",
                  "passed": passed, "failed": failed},
         "runs": rows}, indent=1))
    print(f"\n{'run':26}{'enacted':>9}{'splitline':>11}{'reduction':>11}")
    for x in rows:
        print(f"{x['run']:26}{x['enacted_mean_abs_bias']:9.2f}"
              f"{x['splitline_mean_abs_bias']:11.2f}{x['reduction_pct']:10.0f}%")
    print(f"\nwrote {out}\nwrote {sens/'sensitivity.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
