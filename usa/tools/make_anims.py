#!/usr/bin/env python3
"""Build one animation per state map: the districting, one cut at a time.

A map with S seats has S-1 cuts and therefore S frames, starting from the
undivided state. Frames are rendered in a single engine pass so the palette is
computed once rather than once per frame, and so a district keeps its colour
throughout.

Like the maps, an animation depends only on (year, state, seats, metric), not
on which apportionment produced that seat count, so each is built once into a
cache and linked into every variant that uses it under the naming convention.

Nationwide maps are excluded: at up to 687 cuts they are a different job, and
want the palette cached across runs rather than recomputed.
"""

import argparse
import os

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared" / "tools"))
from animate import animate  # noqa: E402
from apportion import build, house_size, huntington_hill  # noqa: E402
from apportionment import FIPS  # noqa: E402
from run_all import (CACHE, OUT, RULE_DIR, VARIANTS, state_boundary,  # noqa: E402
                     state_pop)

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT.parent / "shared" / "splitline" / "bin" / "splitline"
ANIM = ROOT / "cache_anim"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--metric", choices=("span", "land"), default="span")
    ap.add_argument("--width", type=int, default=900)
    ap.add_argument("--engine", default=str(ENGINE))
    ap.add_argument("--years", nargs="*", type=int, default=[2000, 2010, 2020])
    args = ap.parse_args()

    M = args.metric
    ANIM.mkdir(exist_ok=True)
    tmp = ROOT / "work" / "anim_frames"
    tmp.mkdir(parents=True, exist_ok=True)

    plans, jobs = [], set()
    for year in args.years:
        for rule in ("fixed", "cuberoot", "wyoming"):
            for dc, pr in ((0, 0), (1, 0), (0, 1), (1, 1)):
                pops = build(year, dc, pr)
                seats = huntington_hill(pops, house_size(rule, pops))
                plans.append((year, rule, dc, pr, seats))
                for st, n in seats.items():
                    if n > 0:
                        jobs.add((year, st, n))
    # Smallest first. Frames, render time and the peak memory of the GIF
    # assembly all scale with the seat count, so this banks most of the
    # animations early and leaves California for when nothing else is running.
    jobs = sorted(jobs, key=lambda j: (j[2], j))
    total_frames = sum(n for _, _, n in jobs)
    print(f"{len(jobs)} animations, {total_frames:,} frames, metric {M}",
          flush=True)

    started = time.time()
    made = skipped = failed = 0
    for i, (year, st, n) in enumerate(jobs, 1):
        gif = ANIM / f"{year}_{st.lower()}_{n}_{M}.gif"
        if gif.exists() and gif.stat().st_size > 0:
            skipped += 1
            continue
        tree = CACHE / f"{year}_{st.lower()}_{n}_{M}.json"
        if not tree.exists():
            print(f"  [{i}/{len(jobs)}] {st} {year} {n}: no tree yet, skipping")
            failed += 1
            continue

        try:
            nframes, dt = animate(args.engine, state_boundary(year, st),
                                  state_pop(year, st), tree, gif, tmp,
                                  width=args.width)
        except Exception as e:
            print(f"  [{i}/{len(jobs)}] {st} {year} {n}: FAILED\n{e}")
            failed += 1
            continue
        made += 1
        if made % 25 == 0 or n > 40:
            el = time.time() - started
            print(f"  [{i}/{len(jobs)}] {st} {year} {n}seats "
                  f"{nframes} frames {dt:.1f}s "
                  f"(elapsed {el/60:.0f} min)", flush=True)

    # Link into every variant that uses this seat count.
    nlink = 0
    for year, rule, dc, pr, seats in plans:
        d = OUT / f"{M}-metric" / str(year) / RULE_DIR[rule] / VARIANTS[(dc, pr)]
        if not d.exists():
            continue
        stem = f"{year}_{RULE_DIR[rule]}_{VARIANTS[(dc, pr)]}"
        for st, n in seats.items():
            if n <= 0:
                continue
            src = ANIM / f"{year}_{st.lower()}_{n}_{M}.gif"
            dst = d / f"{stem}_{st.upper()}_{n}.gif"
            if src.exists() and not dst.exists():
                os.symlink(os.path.relpath(src, d), dst)
                nlink += 1

    el = time.time() - started
    print(f"\nmade {made}, reused {skipped}, failed {failed}, {nlink} links")
    print(f"total {el/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
