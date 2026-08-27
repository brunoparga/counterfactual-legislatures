#!/usr/bin/env python3
"""Render a cut tree to an animation with strictly controlled colours.

The engine's own renderer recolours from a palette computed over the finished
tree. That keeps a district's colour stable, but it cannot promise the two
properties that make an animation read correctly:

  1. No two touching regions ever share a colour, in any frame.
  2. A region's colour changes only when it is the new side of a cut.

Both fall out of assigning colours incrementally instead of all at once. When
a region splits, one side keeps the parent's colour and the other takes a new
one chosen against its neighbours at that moment. Cutting only subdivides, so
an existing pair never becomes adjacent later -- which means a greedy choice
made once is safe forever, and nothing ever has to be recoloured.

Adjacency is read off the rasterised frame rather than computed from geometry:
splitline regions are convex polygons clipped to an arbitrary outline, and
two of them can touch across a coastline in ways the half-planes alone do not
reveal.

Flat fills, no population shading -- for an animation the cuts are the
subject, and density speckle competes with them.
"""

import argparse
import json
import math
import sys

import numpy as np
from PIL import Image, ImageDraw

# Distinguishable at a glance, and legible on a dark page.
PALETTE = [
    (79, 143, 209), (226, 122, 63), (108, 181, 111), (198, 93, 126),
    (166, 132, 205), (222, 186, 78), (90, 190, 190), (205, 116, 96),
    (140, 155, 175), (172, 200, 96),
]
BG = (13, 15, 19)
EDGE = (232, 230, 225)


def read_rings(path):
    """ARC/INFO ungenerate -> list of rings, each a list of (lon, lat)."""
    rings, cur = [], None
    for line in open(path):
        t = line.split()
        if not t:
            continue
        if t[0].upper() == "END":
            if cur:
                rings.append(cur)
            cur = None
            continue
        if len(t) >= 3:          # ring header: id, centroid x, centroid y
            if cur:
                rings.append(cur)
            cur = []
            continue
        if len(t) == 2:
            if cur is None:
                cur = []
            cur.append((float(t[0]), float(t[1])))
    if cur:
        rings.append(cur)
    return [r for r in rings if len(r) >= 3]


def gnomonic(lon, lat, lon0, lat0):
    lo, la = math.radians(lon), math.radians(lat)
    l0, a0 = math.radians(lon0), math.radians(lat0)
    cosc = math.sin(a0) * math.sin(la) + math.cos(a0) * math.cos(la) * math.cos(lo - l0)
    if cosc <= 0:
        return None
    x = math.cos(la) * math.sin(lo - l0) / cosc
    y = (math.cos(a0) * math.sin(la) - math.sin(a0) * math.cos(la) * math.cos(lo - l0)) / cosc
    return math.degrees(x), math.degrees(y)


def dfs_cuts(nodes, root=0):
    """Internal nodes in the order the animation applies them: depth-first,
    left child first. The tree's own numbering already puts the southern or
    western side on the left, so this is west-then-north."""
    order, stack = [], [root]
    while stack:
        i = stack.pop()
        n = nodes[i]
        if "district" in n:
            continue
        order.append(i)
        # right pushed first so left is visited first
        stack.append(n["right"])
        stack.append(n["left"])
    return order


def regions(nodes, applied, X, Y):
    """Region id per pixel, given the set of cuts applied so far."""
    out = np.zeros(X.shape, dtype=np.int32)
    todo = [(0, np.ones(X.shape, dtype=bool))]
    while todo:
        i, mask = todo.pop()
        n = nodes[i]
        if i not in applied or "district" in n:
            out[mask] = i
            continue
        side = (X * n["nx"] + Y * n["ny"]) < n["c"]
        todo.append((n["left"], mask & side))
        todo.append((n["right"], mask & ~side))
    return out


def adjacency(reg, land):
    """Pairs of region ids that touch, read off the raster."""
    adj = set()
    a, b = reg[:, :-1], reg[:, 1:]
    m = land[:, :-1] & land[:, 1:] & (a != b)
    for u, v in set(zip(a[m].tolist(), b[m].tolist())):
        adj.add((min(u, v), max(u, v)))
    a, b = reg[:-1, :], reg[1:, :]
    m = land[:-1, :] & land[1:, :] & (a != b)
    for u, v in set(zip(a[m].tolist(), b[m].tolist())):
        adj.add((min(u, v), max(u, v)))
    return adj


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", required=True)
    ap.add_argument("--boundary", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=900)
    ap.add_argument("--margin", type=float, default=0.03)
    ap.add_argument("--title")
    ap.add_argument("--sub")
    ap.add_argument("--target-ms", type=int, default=9000)
    args = ap.parse_args()

    d = json.load(open(args.tree))
    nodes = {n["i"]: n for n in d["nodes"]}
    pr = d["projection"]

    rings = [[gnomonic(lo, la, pr["lon0"], pr["lat0"]) for lo, la in r]
             for r in read_rings(args.boundary)]
    rings = [[p for p in r if p] for r in rings]
    rings = [r for r in rings if len(r) >= 3]
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    mx, my = (x1 - x0) * args.margin, (y1 - y0) * args.margin
    x0, x1, y0, y1 = x0 - mx, x1 + mx, y0 - my, y1 + my
    W = args.width
    H = max(1, int(round(W * (y1 - y0) / (x1 - x0))))

    # Pixel centres in projected degrees. y flips: image rows run downward.
    px = x0 + (np.arange(W) + 0.5) * (x1 - x0) / W
    py = y1 - (np.arange(H) + 0.5) * (y1 - y0) / H
    X, Y = np.meshgrid(px, py)

    mask_img = Image.new("1", (W, H), 0)
    md = ImageDraw.Draw(mask_img)
    for r in rings:
        md.polygon([((x - x0) * W / (x1 - x0), (y1 - y) * H / (y1 - y0)) for x, y in r],
                   fill=1)
    land = np.array(mask_img, dtype=bool)

    order = dfs_cuts(nodes)
    colour = {0: 0}
    frames = []
    applied = set()

    for k in range(len(order) + 1):
        reg = regions(nodes, applied, X, Y)
        if k > 0:
            cut = order[k - 1]
            new = nodes[cut]["right"]            # left inherits, right is new
            colour[nodes[cut]["left"]] = colour.pop(cut)
            adj = adjacency(reg, land)
            taken = {colour[v] for (u, v) in adj if u == new and v in colour}
            taken |= {colour[u] for (u, v) in adj if v == new and u in colour}
            colour[new] = next(c for c in range(len(PALETTE)) if c not in taken)

        rgb = np.zeros((H, W, 3), dtype=np.uint8)
        rgb[:] = BG
        for rid, ci in colour.items():
            sel = land & (reg == rid)
            rgb[sel] = PALETTE[ci % len(PALETTE)]
        im = Image.fromarray(rgb)

        # Outline on top so the state reads as one shape throughout.
        dr = ImageDraw.Draw(im)
        for r in rings:
            dr.line([((x - x0) * W / (x1 - x0), (y1 - y) * H / (y1 - y0)) for x, y in r]
                    + [((r[0][0] - x0) * W / (x1 - x0), (y1 - r[0][1]) * H / (y1 - y0))],
                    fill=EDGE, width=2)
        frames.append(im)
        if k < len(order):
            applied.add(order[k])

    if args.title:
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
        from label_map import draw_caption
        frames = [draw_caption(f, args.title, args.sub, "tl", 0.038) for f in frames]

    per = max(90, args.target_ms // len(frames))
    dur = [int(per * 1.6)] + [per] * (len(frames) - 2) + [int(per * 2.6)]
    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=64) for f in frames]
    pal[0].save(args.out, save_all=True, append_images=pal[1:],
                duration=dur, loop=0, optimize=True)

    # Report whether the two promises actually held.
    reg = regions(nodes, applied, X, Y)
    bad = [(u, v) for (u, v) in adjacency(reg, land)
           if colour.get(u) is not None and colour.get(u) == colour.get(v)]
    print(f"{args.out}: {len(frames)} frames, {len(set(colour.values()))} colours, "
          f"{len(bad)} adjacent same-colour pairs in the final frame")
    return 0


if __name__ == "__main__":
    sys.exit(main())
