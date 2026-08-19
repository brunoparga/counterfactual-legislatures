#!/usr/bin/env python3
"""Build one state's map for one census year, end to end.

Downloading is the expensive one-off; generating maps is cheap and will be
re-run whenever the engine changes. So this does the whole chain from raw
census files to outputs, caching only the derived inputs (boundary and
population points), and never touching the downloads.

    python3 tools/run_state.py --year 2010 --state MI

Seats come from the apportionment for that census unless overridden.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pl_to_pop  # noqa: E402
import sf1_to_pop  # noqa: E402
import shp_to_dat  # noqa: E402
from apportionment import FIPS, NAMES, SEATS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "bin" / "splitline"

BOUNDARY_SHP = {
    2010: "boundary/gz_2010_us_040_00_500k.shp",
    2020: "boundary/cb_2020_us_state_500k.shp",
}


def build_boundary(year, st, datadir):
    """Return a path to the state outline in ungenerate format."""
    fips, low = FIPS[st], st.lower()

    if year == 2000:
        # Already ungenerate: this is the format the engine was written for.
        p = datadir / low / f"st{fips}_d00.dat"
        if not p.exists():
            raise FileNotFoundError(p)
        return p

    out = datadir / low / "boundary.dat"
    if out.exists() and out.stat().st_size > 0:
        return out
    shp = datadir / BOUNDARY_SHP[year]
    if not shp.exists():
        raise FileNotFoundError(shp)

    recs = shp_to_dat.read_dbf(shp.with_suffix(".dbf"))
    rings = []
    for idx, polys in shp_to_dat.read_shp(shp):
        rec = recs[idx] if idx < len(recs) else {}
        if shp_to_dat.state_field(rec) != fips:
            continue
        rings.extend(r for r in polys if len(r) >= 3)
    if not rings:
        raise SystemExit(f"no rings for {st} (FIPS {fips}) in {shp.name}")
    out.parent.mkdir(parents=True, exist_ok=True)
    shp_to_dat.write_dat(rings, out)
    return out


def build_pop(year, st, datadir, zero_population=False):
    low = st.lower()
    d = datadir / low
    out = d / f"{low}.pop"
    if out.exists() and out.stat().st_size > 0 and not zero_population:
        return out, None

    if year == 2000:
        stats = sf1_to_pop.convert(d / f"{low}geo.uf1", d / f"{low}00001.uf1",
                                   out, zero_population)
    else:
        stats = pl_to_pop.convert(d / f"{low}geo{year}.pl", out, year,
                                  zero_population)

    if stats["state_total"] is not None and not zero_population:
        if stats["block_total"] != stats["state_total"]:
            raise SystemExit(
                f"{st} {year}: blocks sum to {stats['block_total']} but the "
                f"state total is {stats['state_total']}")
    return out, stats


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True, choices=(2000, 2010, 2020))
    ap.add_argument("--state", required=True)
    ap.add_argument("--seats", type=int, default=None, help="override apportionment")
    ap.add_argument("--gain", type=float, default=120)
    ap.add_argument("--angles", type=int, default=360)
    ap.add_argument("--data", default=None, help="data root (default data/<year>)")
    ap.add_argument("--out", default="maps", help="output directory")
    ap.add_argument("--assign", action="store_true", help="also write assignment CSV")
    args = ap.parse_args()

    st = args.state.upper()
    datadir = Path(args.data) if args.data else ROOT / "data" / str(args.year)
    outdir = Path(args.out) / str(args.year)
    outdir.mkdir(parents=True, exist_ok=True)

    seats = args.seats if args.seats is not None else SEATS[args.year][st]
    if seats < 1:
        print(f"{st} {args.year}: no seats, no map")
        return 0

    t0 = time.time()
    boundary = build_boundary(args.year, st, datadir)
    pop, stats = build_pop(args.year, st, datadir)

    low = st.lower()
    cmd = [str(ENGINE), "--boundary", str(boundary), "--pop", str(pop),
           "--seats", str(seats), "--gain", str(args.gain),
           "--angles", str(args.angles),
           "--tree", str(outdir / f"{low}.json"),
           "--png", str(outdir / f"{low}.png")]
    if args.assign:
        cmd += ["--assign", str(outdir / f"{low}_blocks.csv")]

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"{st} {args.year}: ENGINE FAILED\n{r.stdout}\n{r.stderr}",
              file=sys.stderr)
        return 1

    spread = points = ""
    for line in r.stdout.splitlines():
        if line.startswith("population per district"):
            spread = line.split("spread")[-1].strip()
        if line.startswith("points:"):
            points = line.split(",")[0].replace("points:", "").strip()

    print(f"{st:2s} {args.year}  {NAMES[st]:22s} {seats:3d} seats  "
          f"{points:>18s}  spread {spread:>9s}  {time.time()-t0:5.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
