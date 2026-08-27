#!/usr/bin/env python3
"""Census 2000 Summary File 1 -> splitline population points.

Replaces the 2007 geoproc.c, which did the same job in C with ~160 MB of
arrays declared as function locals (hence the -Wl,--stack,300388608 in
upstream's compile script).

SF1 splits what we need across two files:

  <st>geo.uf1     fixed-width, 401 chars + newline. Carries summary level,
                  the geographic identifiers, and each record's internal
                  point -- a lat/lon guaranteed to fall inside the area.
  <st>00001.uf1   comma-delimited. Field 5 is the logical record number that
                  joins back to the header; field 6 is P001001, total
                  population.

Verified offsets (0-based) against Colorado's real files:

    SUMLEV    8   3     '101' at block level
    GEOCOMP  11   2     '00'  = the whole area, not a subset
    CHARITER 13   3     '000'
    LOGRECNO 18   7
    STATE    29   2
    COUNTY   31   3
    TRACT    55   6
    BLKGRP   61   1
    BLOCK    62   4
    AREALAND 172 14     land area, square metres
    INTPTLAT 310  9     signed, scaled by 1e6
    INTPTLON 319 10     signed, scaled by 1e6
"""

import argparse
import sys
from pathlib import Path

SUMLEV_BLOCK = "101"
SUMLEV_STATE = "040"
WHOLE_AREA = "10100000"  # SUMLEV + GEOCOMP + CHARITER for a plain block record


def read_pop(path):
    """logical record number -> total population."""
    pop = {}
    with open(path, "r", encoding="latin-1") as f:
        for line in f:
            parts = line.split(",", 6)
            if len(parts) < 6:
                continue
            try:
                pop[int(parts[4])] = int(parts[5])
            except ValueError:
                continue
    return pop


def convert(geo_path, pop_path, out_path, zero_population=False):
    pop = read_pop(pop_path)
    if not pop:
        raise SystemExit(f"no population records in {pop_path}")

    state_total = None
    written = 0
    block_total = 0
    no_pop_record = 0

    with open(geo_path, "r", encoding="latin-1") as f, open(out_path, "w") as out:
        for line in f:
            tag = line[8:16]
            if line[8:11] == SUMLEV_STATE and state_total is None:
                lrn = int(line[18:25])
                state_total = pop.get(lrn)
            if tag != WHOLE_AREA:
                continue

            lrn = int(line[18:25])
            p = pop.get(lrn)
            if p is None:
                no_pop_record += 1
                continue

            tract = int(line[55:61])
            block = int(line[62:66])
            area = int(line[172:186] or 0)
            lat = int(line[310:319]) / 1e6
            lon = int(line[319:329]) / 1e6

            block_total += p
            if zero_population:
                p = 0
            # 7th field is land area in square metres, so the engine can
            # spread a block's people over an equal-area disc.
            out.write(f"{tract:06d},{block},{p},1,{lon:.6f},{lat:.6f},{area}\n")
            written += 1

    return {
        "blocks": written,
        "block_total": block_total,
        "state_total": state_total,
        "orphan_records": no_pop_record,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geo", required=True, help="<st>geo.uf1")
    ap.add_argument("--pop", required=True, help="<st>00001.uf1")
    ap.add_argument("--out", required=True, help="output points file")
    ap.add_argument("--zero-population", action="store_true",
                    help="emit blocks with population 0 (for DC on the nationwide map)")
    args = ap.parse_args()

    st = convert(Path(args.geo), Path(args.pop), Path(args.out), args.zero_population)

    print(f"blocks written : {st['blocks']}")
    print(f"block total    : {st['block_total']}")
    print(f"state total    : {st['state_total']}")
    if st["orphan_records"]:
        print(f"header records with no population row: {st['orphan_records']}")

    # The blocks partition the state exactly, so these must agree. If they do
    # not, an offset is wrong and every downstream map is quietly wrong too.
    if st["state_total"] is None:
        print("WARNING: no state-level (SUMLEV 040) record found; cannot verify",
              file=sys.stderr)
        return 1
    if st["block_total"] != st["state_total"]:
        print(f"ERROR: blocks sum to {st['block_total']} but the state total is "
              f"{st['state_total']} (off by {st['block_total'] - st['state_total']})",
              file=sys.stderr)
        return 1
    print("OK: block populations sum exactly to the state total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
