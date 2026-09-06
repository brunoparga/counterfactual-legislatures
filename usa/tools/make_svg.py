#!/usr/bin/env python3
"""Write a state's cut tree as SVG -- static, animated, or partisan.

Districts are polygons, not pixels: a district is exactly the state outline
intersected with the half-planes on its path from the root of the tree. So the
output is resolution-independent, every district is an addressable element,
and the smallest urban districts stay legible at any zoom without needing an
inset drawn for them.

    tools/make_svg.py --state IL --mode anim --ms 1200
    tools/make_svg.py --state IL --mode partisan
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT.parent / "shared" / "tools"))
from apportion import build, house_size, huntington_hill  # noqa: E402
from partisan_map import build_colours  # noqa: E402
from stitch import fwd, read_rings  # noqa: E402
from svg_map import render_animated, render_static  # noqa: E402


def load(state, census, rule, metric, model):
    pops = build(census, 0, 0)
    n = huntington_hill(pops, house_size(rule, pops))[state]
    plans = ROOT / "plans"
    tree = plans / f"{census}_{state.lower()}_{n}_{model}_{metric}.json"
    d = json.load(open(tree))
    pr = d["projection"]
    rings = []
    for r in read_rings(ROOT / "upstream" / str(census) / state.lower() / "boundary.dat"):
        x, y = fwd([p[0] for p in r], [p[1] for p in r],
                   pr["lon0"], pr["lat0"], pr.get("lon_shift", 0.0))
        pts = [(a, b) for a, b in zip(x, y) if not (np.isnan(a) or np.isnan(b))]
        if len(pts) >= 3:
            rings.append(pts)
    return {n["i"]: n for n in d["nodes"]}, rings, n


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", required=True)
    ap.add_argument("--mode", default="anim", choices=("anim", "partisan", "plain"))
    ap.add_argument("--census", type=int, default=2010)
    ap.add_argument("--rule", default="fixed")
    ap.add_argument("--metric", default="span")
    ap.add_argument("--model", default="uniform")
    ap.add_argument("--width", type=int, default=1000)
    # THE SPEED KNOB: milliseconds each cut is left on screen.
    ap.add_argument("--ms", type=int, default=1200,
                    help="milliseconds per cut (animation only)")
    ap.add_argument("--hold-first", type=float, default=1.5,
                    help="extra cut-lengths to hold the undivided state")
    ap.add_argument("--hold-last", type=float, default=4.0,
                    help="extra cut-lengths to hold the finished map")
    ap.add_argument("--order", default="bfs", choices=("bfs", "dfs"),
                    help="bfs halves the whole region, then both halves, and "
                         "so on; dfs finishes one half before starting the other")
    ap.add_argument("--votes", default=str(ROOT / "work" / "block_votes_splitline.json"))
    ap.add_argument("--out")
    a = ap.parse_args()

    st = a.state.upper()
    nodes, rings, n = load(st, a.census, a.rule, a.metric, a.model)
    out = a.out or str(ROOT / "work" / "diagnostics" / f"{st.lower()}_{a.mode}.svg")

    if a.mode == "anim":
        k = render_animated(nodes, rings, out, width=a.width, ms=a.ms,
                            hold_first=a.hold_first, hold_last=a.hold_last,
                            order=a.order,
                            title=f"{st}: shortest splitline, one cut at a time")
        cycle = (n + a.hold_first + a.hold_last) * a.ms / 1000
        print(f"{out}  {k} frames  {a.ms} ms/cut  cycle {cycle:.0f}s")
    else:
        if a.mode == "partisan":
            cols = build_colours(a.votes)
            def fill(d):
                return "#%02x%02x%02x" % cols.get((st, d), (120, 120, 126))
        else:
            from svg_map import PALETTE
            def fill(d):
                return PALETTE[d % len(PALETTE)]
        k = render_static(nodes, rings, fill, out, width=a.width,
                          title=f"{st}, {n} districts")
        print(f"{out}  {k} districts")
    print(f"{Path(out).stat().st_size/1000:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
