#!/usr/bin/env python3
"""PL 94-171 (2010 or 2020) -> splitline population points.

Unlike Census 2000 SF1, the PL geographic header carries POP100 itself, so no
join to a data segment is needed: the header alone has summary level,
identifiers, population and internal point.

The two vintages agree on nothing else, though:

  2010  fixed-width, 500-char records.
        SUMLEV @8(3) GEOCOMP @11(2) TRACT @54(6) BLOCK @61(4)
        POP100 @318(9) INTPTLAT @336(11) INTPTLON @347(12)

  2020  pipe-delimited, 97 fields, 1-based:
        3 SUMLEV, 5 GEOCOMP, 33 TRACT, 35 BLOCK, 91 POP100,
        93 INTPTLAT, 94 INTPTLON

Blocks are summary level 750 in both (not 101 as in 2000 SF1), and both write
the internal point as a signed decimal string rather than 2000's integer
scaled by a million. All offsets verified against Colorado, whose blocks sum
to the published state total in every year.
"""

import argparse
import sys
from pathlib import Path

SUMLEV_BLOCK = "750"
SUMLEV_STATE = "040"
WHOLE_AREA = "00"  # GEOCOMP: the area itself, not a subset


def parse_2010(line):
    if line[8:11] == SUMLEV_STATE and line[11:13] == WHOLE_AREA:
        return ("state", int(line[318:327] or 0))
    if line[8:11] != SUMLEV_BLOCK or line[11:13] != WHOLE_AREA:
        return None
    return ("block", int(line[54:60]), int(line[61:65]), int(line[318:327] or 0),
            float(line[336:347]), float(line[347:359]), int(line[198:212] or 0))


def parse_2020(line):
    f = line.rstrip("\n").split("|")
    if len(f) < 94:
        return None
    if f[2] == SUMLEV_STATE and f[4] == WHOLE_AREA:
        return ("state", int(f[90] or 0))
    if f[2] != SUMLEV_BLOCK or f[4] != WHOLE_AREA:
        return None
    return ("block", int(f[32] or 0), int(f[34] or 0), int(f[90] or 0),
            float(f[92]), float(f[93]), int(f[84] or 0))


def convert(geo_path, out_path, year, zero_population=False):
    parse = parse_2010 if year == 2010 else parse_2020
    state_total = None
    written = block_total = 0

    with open(geo_path, "r", encoding="latin-1") as f, open(out_path, "w") as out:
        for line in f:
            r = parse(line)
            if r is None:
                continue
            if r[0] == "state":
                if state_total is None:
                    state_total = r[1]
                continue
            _, tract, block, pop, lat, lon, area = r
            block_total += pop
            if zero_population:
                pop = 0
            # 7th field is land area in square metres; the engine uses it to
            # spread a block's population over an equal-area disc instead of
            # piling it on the centroid.
            out.write(f"{tract:06d},{block},{pop},1,{lon:.6f},{lat:.6f},{area}\n")
            written += 1

    return {"blocks": written, "block_total": block_total, "state_total": state_total}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geo", required=True, help="<st>geo2010.pl or <st>geo2020.pl")
    ap.add_argument("--year", type=int, required=True, choices=(2010, 2020))
    ap.add_argument("--out", required=True)
    ap.add_argument("--zero-population", action="store_true",
                    help="emit blocks with population 0 (DC on the nationwide map)")
    args = ap.parse_args()

    st = convert(Path(args.geo), Path(args.out), args.year, args.zero_population)

    print(f"blocks written : {st['blocks']}")
    print(f"block total    : {st['block_total']}")
    print(f"state total    : {st['state_total']}")

    # Blocks partition the state exactly. If these disagree an offset is wrong,
    # and every map built on it would be quietly wrong too.
    if st["state_total"] is None:
        print("WARNING: no SUMLEV 040 record; cannot verify", file=sys.stderr)
        return 1
    if st["block_total"] != st["state_total"]:
        print(f"ERROR: blocks sum to {st['block_total']} but state total is "
              f"{st['state_total']}", file=sys.stderr)
        return 1
    print("OK: block populations sum exactly to the state total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
