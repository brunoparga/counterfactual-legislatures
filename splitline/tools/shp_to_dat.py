#!/usr/bin/env python3
"""Cartographic boundary shapefile -> ARC/INFO ungenerate.

The 2000 census shipped state outlines as ungenerate ASCII (st<FIPS>_d00), the
format the splitline engine reads. That format was discontinued, so 2010 and
2020 boundaries come as shapefiles and have to be converted.

Pure stdlib: the .shp geometry and .dbf attribute formats are simple enough
that pulling in GDAL to read a polygon layer is not worth it.

Output shape, one block per ring:

    <id>   <centroid x>   <centroid y>
    <x> <y>
    ...
    END
    END

The leading coordinate pair is the ring centroid, which the engine discards --
it exists because the original census files had it there. Holes and separate
landmasses are just further rings; the even-odd fill handles both, so islands
and enclaves need no special casing.
"""

import argparse
import struct
import sys
from pathlib import Path

SHP_POLYGON = 5


def read_dbf(path):
    """Return a list of dicts, one per record."""
    with open(path, "rb") as f:
        data = f.read()
    nrec, hdr_len, rec_len = struct.unpack_from("<IHH", data, 4)

    fields = []
    off = 32
    while data[off] != 0x0D:
        name = data[off:off + 11].split(b"\0")[0].decode("latin-1")
        flen = data[off + 16]
        fields.append((name, flen))
        off += 32

    out = []
    base = hdr_len
    for i in range(nrec):
        rec = data[base + i * rec_len: base + (i + 1) * rec_len]
        if not rec or rec[:1] == b"*":  # deleted
            continue
        vals, p = {}, 1
        for name, flen in fields:
            vals[name] = rec[p:p + flen].decode("latin-1").strip()
            p += flen
        out.append(vals)
    return out


def read_shp(path):
    """Yield (record_index, [ring, ...]) for each polygon; ring is [(x,y),...]."""
    with open(path, "rb") as f:
        data = f.read()
    if struct.unpack_from(">i", data, 0)[0] != 9994:
        raise SystemExit(f"{path} is not a shapefile")

    off, idx = 100, 0
    n = len(data)
    while off < n:
        _, clen = struct.unpack_from(">ii", data, off)
        body = off + 8
        shape_type = struct.unpack_from("<i", data, body)[0]
        if shape_type == SHP_POLYGON:
            nparts, npoints = struct.unpack_from("<ii", data, body + 36)
            parts = list(struct.unpack_from(f"<{nparts}i", data, body + 44))
            pbase = body + 44 + nparts * 4
            coords = struct.unpack_from(f"<{npoints * 2}d", data, pbase)
            rings = []
            for k in range(nparts):
                s = parts[k]
                e = parts[k + 1] if k + 1 < nparts else npoints
                rings.append([(coords[2 * j], coords[2 * j + 1]) for j in range(s, e)])
            yield idx, rings
        off = body + clen * 2
        idx += 1


def centroid(ring):
    n = len(ring)
    return (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n)


def write_dat(rings, out_path):
    written = 0
    with open(out_path, "w") as f:
        for i, ring in enumerate(rings, 1):
            if len(ring) < 3:
                continue
            cx, cy = centroid(ring)
            f.write(f"{i:10d}{cx:20.9f}{cy:20.9f}\n")
            for x, y in ring:
                f.write(f"{x:20.9f}{y:20.9f}\n")
            # Close the ring explicitly; shapefile rings usually repeat the
            # first point, but do not rely on it.
            if ring[0] != ring[-1]:
                f.write(f"{ring[0][0]:20.9f}{ring[0][1]:20.9f}\n")
            f.write("END\n")
            written += 1
        f.write("END\n")
    return written


def state_field(rec):
    """GENZ2010 calls it STATE, cb_20xx calls it STATEFP."""
    for k in ("STATEFP", "STATE", "STATE_FIPS"):
        if k in rec:
            return rec[k]
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shp", required=True, help="path to the .shp (its .dbf must sit alongside)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fips", nargs="*", default=None,
                    help="2-digit state FIPS codes to keep; default keeps everything")
    ap.add_argument("--min-ring", type=int, default=0,
                    help="drop rings with fewer than this many vertices "
                         "(trims specks without touching real islands)")
    args = ap.parse_args()

    shp = Path(args.shp)
    dbf = shp.with_suffix(".dbf")
    if not dbf.exists():
        raise SystemExit(f"missing {dbf}")

    recs = read_dbf(dbf)
    keep = set(args.fips) if args.fips else None

    rings, kept_states = [], set()
    for idx, polys in read_shp(shp):
        rec = recs[idx] if idx < len(recs) else {}
        fips = state_field(rec)
        if keep is not None and fips not in keep:
            continue
        kept_states.add(fips)
        for r in polys:
            if len(r) >= max(3, args.min_ring):
                rings.append(r)

    if not rings:
        raise SystemExit("no rings selected -- check --fips against the .dbf")

    n = write_dat(rings, Path(args.out))
    verts = sum(len(r) for r in rings)
    print(f"{args.out}: {n} rings, {verts} vertices, "
          f"{len(kept_states)} state(s): {' '.join(sorted(x for x in kept_states if x))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
