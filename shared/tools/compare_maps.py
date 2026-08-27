#!/usr/bin/env python3
"""Compare two splitline maps of the same area pixel by pixel.

Colours and pixel scales differ between renderers, so alignment is done on
each image's land bounding box -- the extent of non-background pixels, which
corresponds to the same geography in both -- and district identity is
recovered by matching colour regions rather than assuming a shared palette.

Reports the share of land area where the two maps agree, after choosing the
best correspondence between their district labels.
"""

import argparse
import sys
from collections import Counter, defaultdict

from PIL import Image


def land_bbox(img, bg_tol=30):
    """Bounding box of non-background pixels. Background is near-black."""
    px = img.load()
    w, h = img.size
    lox, loy, hix, hiy = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y][:3]
            if r + g + b > bg_tol:
                if x < lox: lox = x
                if x > hix: hix = x
                if y < loy: loy = y
                if y > hiy: hiy = y
    if hix < 0:
        raise SystemExit("no land pixels found")
    return lox, loy, hix, hiy


def hue_family(c):
    """Which channels are lit. Both renderers use four hue families with the
    value carrying population density, so this is stable under shading while
    plain RGB quantisation is not."""
    r, g, b = c[:3]
    t = 24  # ignore near-black
    return (r > t, g > t, b > t)


def label_regions(img, bg_tol=30):
    """Label connected same-hue regions. With a proper four-colouring no two
    adjacent districts share a colour, so a connected component is exactly one
    district -- which is what makes colour reuse harmless here."""
    px = img.load()
    w, h = img.size
    lab = [[-1] * w for _ in range(h)]
    nxt = 0
    for y0 in range(h):
        for x0 in range(w):
            if lab[y0][x0] != -1:
                continue
            c = px[x0, y0]
            if sum(c[:3]) <= bg_tol:
                continue
            fam = hue_family(c)
            stack = [(x0, y0)]
            lab[y0][x0] = nxt
            while stack:
                x, y = stack.pop()
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < w and 0 <= ny < h):
                        continue
                    if lab[ny][nx] != -1:
                        continue
                    c2 = px[nx, ny]
                    if sum(c2[:3]) <= bg_tol or hue_family(c2) != fam:
                        continue
                    lab[ny][nx] = nxt
                    stack.append((nx, ny))
            nxt += 1
    return lab, nxt


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("reference")
    ap.add_argument("candidate")
    ap.add_argument("--samples", type=int, default=400,
                    help="grid resolution along each axis")
    args = ap.parse_args()

    ref = Image.open(args.reference).convert("RGB")
    cand = Image.open(args.candidate).convert("RGB")

    rbox = land_bbox(ref)
    cbox = land_bbox(cand)
    print(f"reference land bbox {rbox}  ({ref.size[0]}x{ref.size[1]})")
    print(f"candidate land bbox {cbox}  ({cand.size[0]}x{cand.size[1]})")

    rlab, rn = label_regions(ref)
    clab, cn = label_regions(cand)
    print(f"connected regions: reference {rn}, candidate {cn}")

    rpx, cpx = ref.load(), cand.load()
    rw, rh = rbox[2] - rbox[0], rbox[3] - rbox[1]
    cw, ch = cbox[2] - cbox[0], cbox[3] - cbox[1]

    pairs = Counter()
    n = args.samples
    for iy in range(n):
        for ix in range(n):
            u, v = (ix + 0.5) / n, (iy + 0.5) / n
            rx, ry = int(rbox[0] + u * rw), int(rbox[1] + v * rh)
            cx, cy = int(cbox[0] + u * cw), int(cbox[1] + v * ch)
            rc, cc = rpx[rx, ry], cpx[cx, cy]
            if sum(rc) <= 30 or sum(cc) <= 30:
                continue  # off-land in one of them
            a, b = rlab[ry][rx], clab[cy][cx]
            if a < 0 or b < 0:
                continue
            pairs[(a, b)] += 1

    if not pairs:
        raise SystemExit("no overlapping land samples")

    # Greedy label correspondence: bind each reference district to the
    # candidate district it overlaps most, largest overlaps first.
    by_ref = defaultdict(Counter)
    for (r, c), n_ in pairs.items():
        by_ref[r][c] += n_

    total = sum(pairs.values())
    used, agree = set(), 0
    order = sorted(by_ref, key=lambda r: -sum(by_ref[r].values()))
    print(f"\nreference regions: {len(by_ref)}   samples on land: {total}")
    for r in order:
        for c, n_ in by_ref[r].most_common():
            if c in used:
                continue
            used.add(c)
            agree += n_
            share = 100.0 * sum(by_ref[r].values()) / total
            print(f"  ref region {str(r):18s} -> cand {str(c):18s} "
                  f"{100.0*n_/sum(by_ref[r].values()):5.1f}% of a region "
                  f"holding {share:4.1f}% of the state")
            break

    print(f"\nagreement on land area: {100.0*agree/total:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
