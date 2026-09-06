#!/usr/bin/env python3
"""Lay the generated plans out as browsable directories.

A plan depends only on (year, state, seats, model, metric) -- not on which
apportionment produced that seat count -- so a handful of files serve every
combination. `plans/` holds one copy of each; this builds the human-facing
view over them, where the same file appears under every apportionment that
uses it, named for that apportionment.

CANONICAL AND ADDITIONAL

Nearly all of the output answers a question nobody asked. The question this
project exists for is whether the House would have flipped, and answering it
needs one map per districting cycle: the ordinary 435-seat apportionment, the
metric the Center for Range Voting used, and a choice about who is represented.
That is the canonical set -- three censuses, two kinds of map, two inclusion
choices, twelve in all.

Everything else is real output and is kept, but it varies things the central
question does not turn on: House sizes that never existed, a cut metric we
concluded was not theirs, intermediate inclusion variants nobody asks about.
It goes under additional/, indexed, so the front door stays legible.

Names carry the full identity -- year, rule, variant, model, metric, state,
seats -- so a file copied out of its directory is still identifiable. The
directories are for browsing and nothing depends on them.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT.parent / "shared" / "tools"))
from apportion import build, house_size, huntington_hill  # noqa: E402
from apportionment import FIPS  # noqa: E402

RULE_DIR = {"fixed": "fixed-seats", "cuberoot": "cube-root",
            "wyoming": "smallest-state"}
VARIANTS = {(0, 0): "states-only", (1, 0): "plus-dc",
            (0, 1): "plus-pr", (1, 1): "plus-dc-pr"}

# The canonical dozen: ordinary House size, the metric CRV used, the model our
# own comparison runs on, and the two inclusion choices that are actually
# asked about -- the status quo, and everyone represented.
CANON_RULE = "fixed"
CANON_METRIC = "span"
CANON_MODEL = "uniform"
CANON_VARIANTS = {(0, 0), (1, 1)}


def plans_for(year, rule, dc, pr):
    pops = build(year, dc, pr)
    size = house_size(rule, pops)
    seats = huntington_hill(pops, size)
    nat = size - sum(seats.get(k, 0) for k in ("AK", "HI", "PR"))
    return seats, size, nat


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "maps"))
    ap.add_argument("--link", action="store_true", default=True)
    ap.add_argument("--clean", action="store_true",
                    help="remove the view tree first")
    a = ap.parse_args()

    out = Path(a.out)
    if a.clean and out.exists():
        shutil.rmtree(out)
    plans, renders = ROOT / "plans", ROOT / "renders"

    made = {"canonical": 0, "additional": 0}
    index = []
    for year in (2000, 2010, 2020):
        for rule in ("fixed", "cuberoot", "wyoming"):
            for dc, pr in ((0, 0), (1, 0), (0, 1), (1, 1)):
                seats, size, nat = plans_for(year, rule, dc, pr)
                for model in ("uniform", "point"):
                    for metric in ("span", "land"):
                        canon = (rule == CANON_RULE and metric == CANON_METRIC
                                 and model == CANON_MODEL
                                 and (dc, pr) in CANON_VARIANTS)
                        tier = "canonical" if canon else "additional"
                        d = out / tier / str(year)
                        d.mkdir(parents=True, exist_ok=True)
                        stem = (f"{year}_{RULE_DIR[rule]}_{VARIANTS[(dc,pr)]}"
                                f"_{model}_{metric}")
                        n_here = 0
                        for st, n in sorted(seats.items()):
                            if n <= 0:
                                continue
                            src_stem = f"{year}_{st.lower()}_{n}_{model}_{metric}"
                            for sub, ext in ((plans, "json"), (renders, "png"),
                                             (renders, "gif")):
                                src = sub / f"{src_stem}.{ext}"
                                if not src.exists():
                                    continue
                                dst = d / f"{stem}_{st.upper()}_{n}.{ext}"
                                if not dst.exists():
                                    os.symlink(os.path.relpath(src, d), dst)
                                    n_here += 1
                        tag = "dc" if dc else "nodc"
                        for sub, ext in ((plans, "json"), (renders, "png")):
                            src = sub / f"{year}_us48_{nat}_{tag}_{model}_{metric}.{ext}"
                            if not src.exists():
                                continue
                            dst = d / f"{stem}_US48_{nat}.{ext}"
                            if not dst.exists():
                                os.symlink(os.path.relpath(src, d), dst)
                                n_here += 1
                        made[tier] += n_here
                        if n_here:
                            index.append({
                                "tier": tier, "year": year, "rule": rule,
                                "house": size, "includes_dc": bool(dc),
                                "includes_pr": bool(pr), "model": model,
                                "metric": metric, "files": n_here,
                                "dir": str(d.relative_to(out)),
                                "prefix": stem})
    (out / "index.json").write_text(json.dumps(index, indent=1) + "\n")
    print(f"canonical {made['canonical']:,} links, "
          f"additional {made['additional']:,} links")
    print(f"{len(index)} map sets indexed -> {out/'index.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
