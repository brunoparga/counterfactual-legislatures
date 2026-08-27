#!/usr/bin/env python3
"""Generate every map for every apportionment, timing each run.

For each of the 36 apportionments (3 censuses x 3 House-size rules x 4 choices
of whether DC and PR are apportioned) this produces:

  * one map per state that has seats
  * one nationwide all-in-one-go map over the contiguous states

Output goes to  maps_<model>/<metric>-metric/<year>/<rule>/<variant>/
where model is uniform or point -- the two population models, each with its
own cache and output tree so neither can overwrite the other -- metric is
span or land -- the two definitions of cut length, generated
in parallel rather than one replacing the other -- rule is one of
fixed, cube-root, smallest-state, and variant is one of states, plus-dc,
plus-pr, plus-dc-pr.

Each year therefore has exactly three rule directories. Seating DC or PR
shifts the cube-root and smallest-state House sizes by a seat or two, but that
is a property of the variant rather than a different rule, so it stays inside
the same directory; the variant's own House size is in its
apportionment.json.

WORK IS SHARED. A state's map depends only on (year, state, seats) -- not on
which apportionment produced that seat count -- so Wyoming's one-seat map is
the same file whether it came from the fixed rule or the Wyoming rule. Maps
are therefore computed once into a cache and linked into place, which cuts
1,800 nominal state runs to about 450 real ones.

DC is drawn on the nationwide map in every variant, because its territory sits
inside the hull and omitting it would leave a hole. Its population is counted
only in the variants where it is actually apportioned. AK, HI and PR are never
on that map, and their seats come off the nationwide total.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared" / "tools"))
import pl_to_pop
import sf1_to_pop
import shp_to_dat
from apportion import build, house_size, huntington_hill
from apportionment import FIPS, NON_CONTIGUOUS

ROOT = Path(__file__).resolve().parent.parent

# The .dbf column naming the state differs between census vintages:
# GENZ2010 calls it STATE, cb_20xx calls it STATEFP.
STATE_FIELDS = ("STATEFP", "STATE", "STATE_FIPS")
ENGINE = ROOT.parent / "shared" / "splitline" / "bin" / "splitline"
CACHE = ROOT / "cache"
OUT = ROOT / "maps_uniform"

# The two population models. Uniform spreads each block over an equal-area
# disc and is the better model of where people actually are; point mass keeps
# a block whole, which is what a state redistricting from PL 94-171 data
# actually does. They answer different questions, so both are kept.
#
# Each model gets its own cache and output directory. The cache stem carries
# year, state, seats and metric but not the model, so sharing one directory
# would have a point-mass run silently overwrite the uniform trees.
MODELS = {
    "uniform": (["--uniform", "--subdiv", "10000"], "cache", "maps_uniform"),
    "point": ([], "cache_point", "maps_point"),
}
MODEL = "uniform"
MODEL_ARGS = MODELS[MODEL][0]

# How cut length is measured. These give visibly different maps wherever there
# is water to hop, so both are generated side by side rather than one
# overwriting the other. See the note in src/splitline.c.
METRICS = ("span", "land")
BOUNDARY_SHP = {2010: "boundary/gz_2010_us_040_00_500k.shp",
                2020: "boundary/cb_2020_us_state_500k.shp"}
VARIANTS = {(0, 0): "states-only", (1, 0): "plus-dc",
            (0, 1): "plus-pr", (1, 1): "plus-dc-pr"}

# Directory names for the House-size rules. "smallest-state" rather than
# "wyoming" because that is what the rule actually says -- Wyoming merely
# happens to be the smallest state in all three of these censuses.
RULE_DIR = {"fixed": "fixed-seats", "cuberoot": "cube-root",
            "wyoming": "smallest-state"}


def log(msg):
    print(msg, flush=True)


# ------------------------------------------------------------- prerequisites --

def state_pop(year, st):
    """Population points for one state, with block land area included."""
    low = st.lower()
    d = ROOT / "upstream" / str(year) / low
    out = d / f"{low}.pop"
    # Regenerate if missing or still in the old 6-column form.
    if out.exists() and out.stat().st_size > 0:
        with open(out) as f:
            first = f.readline()
        if first.count(",") >= 6:
            return out
    if year == 2000:
        sf1_to_pop.convert(d / f"{low}geo.uf1", d / f"{low}00001.uf1", out)
    else:
        pl_to_pop.convert(d / f"{low}geo{year}.pl", out, year)
    return out


def state_boundary(year, st):
    low, fips = st.lower(), FIPS[st]
    d = ROOT / "upstream" / str(year) / low
    if year == 2000:
        return d / f"st{fips}_d00.dat"
    out = d / "boundary.dat"
    if out.exists() and out.stat().st_size > 0:
        return out
    shp = ROOT / "upstream" / str(year) / BOUNDARY_SHP[year]
    recs = shp_to_dat.read_dbf(shp.with_suffix(".dbf"))
    rings = []
    for idx, polys in shp_to_dat.read_shp(shp):
        rec = recs[idx] if idx < len(recs) else {}
        if shp_to_dat.pick_field(rec, STATE_FIELDS) == fips:
            rings.extend(p for p in polys if len(p) >= 3)
    if not rings:
        raise SystemExit(f"no rings for {st} {year}")
    shp_to_dat.write_dat(rings, out)
    return out


def national_inputs(year, with_dc):
    """Combined outline and population for the contiguous map."""
    tag = "dc" if with_dc else "nodc"
    bnd = CACHE / f"us48_{year}.dat"
    pop = CACHE / f"us48_{year}_{tag}.pop"
    states = [s for s in FIPS if s not in NON_CONTIGUOUS]

    if not bnd.exists():
        if year == 2000:
            with open(bnd, "w") as o:
                for st in states:
                    txt = Path(state_boundary(year, st)).read_text()
                    # Drop each file's trailing END so rings concatenate.
                    o.write(txt.rstrip().rsplit("END", 1)[0])
                o.write("END\n")
        else:
            shp = ROOT / "upstream" / str(year) / BOUNDARY_SHP[year]
            recs = shp_to_dat.read_dbf(shp.with_suffix(".dbf"))
            keep = {FIPS[s] for s in states}
            rings = []
            for idx, polys in shp_to_dat.read_shp(shp):
                rec = recs[idx] if idx < len(recs) else {}
                if shp_to_dat.pick_field(rec, STATE_FIELDS) in keep:
                    rings.extend(p for p in polys if len(p) >= 3)
            shp_to_dat.write_dat(rings, bnd)

    if not pop.exists():
        with open(pop, "w") as o:
            for st in states:
                src = state_pop(year, st)
                if st == "DC" and not with_dc:
                    # Drawn but unrepresented: territory in, population zeroed.
                    for line in open(src):
                        f = line.split(",")
                        if len(f) >= 6:
                            f[2] = "0"
                            o.write(",".join(f))
                else:
                    o.write(open(src).read())
    return bnd, pop


# --------------------------------------------------------------------- runs --

def run(bnd, pop, seats, stem, timings, label, metric="span", want_png=True):
    """One engine invocation, cached by output stem."""
    js, png = CACHE / f"{stem}.json", CACHE / f"{stem}.png"
    if js.exists() and (png.exists() or not want_png):
        log(f"    cached  {label}")
        return js, (png if png.exists() else None)
    cmd = [str(ENGINE), "--boundary", str(bnd), "--pop", str(pop),
           "--seats", str(seats), *MODEL_ARGS, "--cut-metric", metric,
           "--tree", str(js)]
    if want_png:
        cmd += ["--png", str(png)]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.time() - t0
    if r.returncode != 0:
        log(f"    FAILED  {label}\n{r.stderr[-500:]}")
        for p in (js, png):
            p.unlink(missing_ok=True)
        return None, None
    spread = ""
    for line in r.stdout.splitlines():
        if line.startswith("population per district"):
            spread = line.split("spread")[-1].strip()
    timings.append((label, dt))
    log(f"    {dt:7.1f}s  {label}  spread {spread}")
    return js, (png if want_png else None)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", nargs="*", type=int, default=[2000, 2010, 2020])
    ap.add_argument("--skip-national", action="store_true")
    ap.add_argument("--cut-metric", choices=METRICS, default="span",
                    help="how cut length is measured (default span)")
    ap.add_argument("--link-only", action="store_true",
                    help="rebuild the output tree from the cache without "
                         "invoking the engine at all")
    ap.add_argument("--population-model", choices=sorted(MODELS),
                    default="uniform",
                    help="uniform spreads a block over an equal-area disc; "
                         "point keeps it whole (default uniform). Each model "
                         "has its own cache and output directory.")
    ap.add_argument("--no-png", action="store_true",
                    help="write only the cut trees. The tree is the real "
                         "output and the picture derives from it, so this is "
                         "much faster when only the JSON is wanted.")
    args = ap.parse_args()

    global MODEL, MODEL_ARGS, CACHE, OUT
    MODEL = args.population_model
    MODEL_ARGS, cache_dir, out_dir = MODELS[MODEL]
    CACHE, OUT = ROOT / cache_dir, ROOT / out_dir

    M = args.cut_metric
    CACHE.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    timings = []
    started = time.time()

    plans = []
    for year in args.years:
        for rule in ("fixed", "cuberoot", "wyoming"):
            # The directory is named for the House size the rule gives on the
            # 50 states alone. Adding DC or PR nudges the cube-root and Wyoming
            # sizes by a seat or two, but that is a property of the variant,
            # not a different rule, so it must not fan out into sibling
            # directories -- each year gets exactly three.
            base_size = house_size(rule, build(year, 0, 0))
            for dc, pr in ((0, 0), (1, 0), (0, 1), (1, 1)):
                pops = build(year, dc, pr)
                size = house_size(rule, pops)
                seats = huntington_hill(pops, size)
                plans.append((year, rule, dc, pr, base_size, size, seats))
    log(f"{len(plans)} apportionments over years {args.years}")

    # Distinct work
    st_jobs = sorted({(y, s, n) for y, _, _, _, _, _, sea in plans
                      for s, n in sea.items() if n > 0})
    nat_jobs = sorted({(y, size - sum(sea.get(k, 0) for k in ("AK", "HI", "PR")), bool(dc))
                       for y, _, dc, _, _, size, sea in plans})
    log(f"distinct: {len(st_jobs)} state maps, {len(nat_jobs)} nationwide maps\n")

    log("== state maps ==")
    if args.link_only:
        log("link-only: relaying cached maps, generating nothing")
    for i, (year, st, n) in enumerate([] if args.link_only else st_jobs, 1):
        label = f"[{i}/{len(st_jobs)}] {st} {year} {n}seats"
        try:
            run(state_boundary(year, st), state_pop(year, st), n,
                f"{year}_{st.lower()}_{n}_{M}", timings, label, M,
                want_png=not args.no_png)
        except Exception as e:
            log(f"    ERROR {label}: {e}")

    if not args.skip_national and not args.link_only:
        log("\n== nationwide all-in-one-go ==")
        for i, (year, n, dc) in enumerate(nat_jobs, 1):
            label = f"[{i}/{len(nat_jobs)}] US48 {year} {n}seats {'+DC' if dc else ''}"
            try:
                bnd, pop = national_inputs(year, dc)
                run(bnd, pop, n, f"{year}_us48_{n}_{'dc' if dc else 'nodc'}_{M}",
                    timings, label, M, want_png=not args.no_png)
            except Exception as e:
                log(f"    ERROR {label}: {e}")

    # Lay the shared outputs out under year / house size / variant.
    log("\n== linking output tree ==")
    nlink = 0
    for year, rule, dc, pr, base_size, size, seats in plans:
        d = OUT / f"{M}-metric" / str(year) / RULE_DIR[rule] / VARIANTS[(dc, pr)]
        d.mkdir(parents=True, exist_ok=True)
        stem = f"{year}_{RULE_DIR[rule]}_{VARIANTS[(dc, pr)]}"
        (d / f"{year}_{RULE_DIR[rule]}_{VARIANTS[(dc, pr)]}_apportionment.json").write_text(json.dumps(
            {"year": year, "rule": rule,
             "house": size, "house_50_states": base_size,
             "includes_dc": bool(dc), "includes_pr": bool(pr),
             "population_model": ("uniform disc, subdiv=10000"
                                 if MODEL == "uniform" else
                                 "point mass, one point per block"),
             "cut_metric": M,
             "seats": seats}, indent=1, sort_keys=True))
        for st, n in seats.items():
            if n <= 0:
                continue
            for ext in ("json", "png"):
                src = CACHE / f"{year}_{st.lower()}_{n}_{M}.{ext}"
                dst = d / f"{stem}_{st.upper()}_{n}.{ext}"
                if src.exists() and not dst.exists():
                    os.symlink(os.path.relpath(src, d), dst)
                    nlink += 1
        nat = size - sum(seats.get(k, 0) for k in ("AK", "HI", "PR"))
        for ext in ("json", "png"):
            src = CACHE / f"{year}_us48_{nat}_{'dc' if dc else 'nodc'}_{M}.{ext}"
            dst = d / f"{stem}_US48_{nat}.{ext}"
            if src.exists() and not dst.exists():
                os.symlink(os.path.relpath(src, d), dst)
                nlink += 1
    log(f"{nlink} links")

    total = time.time() - started
    log(f"\n== timing ==")
    log(f"runs executed : {len(timings)}")
    log(f"total wall    : {total/60:.1f} min ({total/3600:.2f} h)")
    if timings:
        timings.sort(key=lambda kv: -kv[1])
        log(f"slowest:")
        for label, dt in timings[:10]:
            log(f"   {dt:8.1f}s  {label}")
        log(f"sum of runs   : {sum(d for _, d in timings)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
