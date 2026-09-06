#!/usr/bin/env python3
"""Cut trees as SVG: districts as polygons, not pixels.

A splitline district is not a shape that happens to get drawn -- it is exactly
the region outline intersected with the half-planes on its path from the root.
So the districts *are* polygons, and rasterising them throws that away and
then spends effort getting it back with edge detection and zoomed insets.

Clipping a polygon by a half-plane is the easy case of Sutherland-Hodgman: the
clip region is convex, so one pass per ring suffices. Rings are clipped
independently and the result is filled even-odd, so holes stay holes and
islands stay islands.

The animation falls out of the same computation. Every node of the tree has a
region, not just the leaves, so frame N is simply the set of nodes on the
frontier after N cuts. Emitting all of them and toggling visibility gives an
animation that is one file, scrubbable, and still sharp at any zoom -- and the
cut itself can be drawn rather than merely appearing, by animating a dash
offset along the chord it cuts through its parent.
"""

import json
import math
from pathlib import Path

EPS = 1e-12


def clip_ring(ring, nx, ny, c, less):
    """Sutherland-Hodgman against the half-plane x*nx + y*ny < c (or >=)."""
    if not ring:
        return []

    def inside(p):
        v = p[0] * nx + p[1] * ny - c
        return (v < 0) if less else (v >= 0)

    out = []
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        ia, ib = inside(a), inside(b)
        if ia:
            out.append(a)
        if ia != ib:
            va = a[0] * nx + a[1] * ny - c
            vb = b[0] * nx + b[1] * ny - c
            d = va - vb
            if abs(d) > EPS:
                t = va / d
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out if len(out) >= 3 else []


def clip(polys, nx, ny, c, less):
    return [r for r in (clip_ring(p, nx, ny, c, less) for p in polys) if r]


def node_regions(nodes, rings, root=0):
    """{node id: list of rings} for every node, leaves and internal alike."""
    out = {}
    stack = [(root, rings)]
    while stack:
        i, polys = stack.pop()
        out[i] = polys
        n = nodes[i]
        if "district" in n or not polys:
            continue
        stack.append((n["left"], clip(polys, n["nx"], n["ny"], n["c"], True)))
        stack.append((n["right"], clip(polys, n["nx"], n["ny"], n["c"], False)))
    return out


def cut_chord(polys, nx, ny, c):
    """The segment where a cut crosses its own region -- the knife, not the
    infinite line. Returned as the two extreme crossing points."""
    pts = []
    for ring in polys:
        n = len(ring)
        for i in range(n):
            a, b = ring[i], ring[(i + 1) % n]
            va = a[0] * nx + a[1] * ny - c
            vb = b[0] * nx + b[1] * ny - c
            if (va < 0) != (vb < 0):
                d = va - vb
                if abs(d) > EPS:
                    t = va / d
                    pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    if len(pts) < 2:
        return None
    # order along the cut direction and take the extremes
    dx, dy = -ny, nx
    pts.sort(key=lambda p: p[0] * dx + p[1] * dy)
    return pts[0], pts[-1]


def dfs_cuts(nodes, root=0):
    """Cuts depth-first: finish one half completely before starting the other.

    This is the order the algorithm actually recurses in, so it shows how a
    single district is arrived at -- but it spends the whole second half of the
    animation in whichever corner it happened to descend into first.
    """
    order, stack = [], [root]
    while stack:
        i = stack.pop()
        n = nodes[i]
        if "district" in n:
            continue
        order.append(i)
        stack.append(n["right"])
        stack.append(n["left"])
    return order


def bfs_cuts(nodes, root=0):
    """Cuts breadth-first: halve the whole region, then halve both halves.

    Every cut at a given depth happens before any cut at the next, so the map
    subdivides evenly instead of boring into one corner. Cut lengths shrink
    together rather than by three orders of magnitude across the sequence,
    which is what makes the depth-first version look like it stalls and then
    flickers. The tree's own canonicalisation puts the southern or western
    side on the left, so left-before-right within a level is west-then-south.
    """
    from collections import deque
    order, q = [], deque([root])
    while q:
        i = q.popleft()
        n = nodes[i]
        if "district" in n:
            continue
        order.append(i)
        q.append(n["left"])
        q.append(n["right"])
    return order


CUT_ORDERS = {"dfs": dfs_cuts, "bfs": bfs_cuts}


def frontier(nodes, applied, root=0):
    """Regions visible after a given set of cuts has been made."""
    out, stack = [], [root]
    while stack:
        i = stack.pop()
        n = nodes[i]
        if i in applied and "district" not in n:
            stack.append(n["left"])
            stack.append(n["right"])
        else:
            out.append(i)
    return out


def path_d(polys, prec=4):
    parts = []
    for ring in polys:
        if len(ring) < 3:
            continue
        parts.append("M" + " ".join(
            f"{x:.{prec}f},{-y:.{prec}f}" for x, y in ring) + "Z")
    return "".join(parts)


def bbox(polys):
    xs = [p[0] for r in polys for p in r]
    ys = [p[1] for r in polys for p in r]
    return min(xs), max(xs), min(ys), max(ys)


PALETTE = ["#4f8fd1", "#e27a3f", "#6cb56f", "#c65d7e", "#a684cd",
           "#deba4e", "#5abebe", "#cd7460"]


def _overlap(a, b):
    ax0, ax1, ay0, ay1 = a
    bx0, bx1, by0, by1 = b
    return not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0)


def incremental_colours(nodes, regions, order):
    """Colour index per node, assigned as the tree is cut.

    One side of every cut keeps the parent's colour and the other takes a new
    one, so a region never changes colour once drawn. The new colour avoids
    those of regions it could touch -- approximated by bounding-box overlap,
    which is conservative: it may refuse a colour that would have been fine,
    never accept one that clashes.
    """
    colour = {0: 0}
    live = {0}
    for cut in order:
        n = nodes[cut]
        l, r = n["left"], n["right"]
        colour[l] = colour[cut]
        live.discard(cut)
        live.add(l)
        if not regions.get(r):
            colour[r] = colour[l]
            live.add(r)
            continue
        bb = bbox(regions[r])
        taken = {colour[o] for o in live
                 if regions.get(o) and _overlap(bb, bbox(regions[o]))}
        colour[r] = next(i for i in range(len(PALETTE)) if i not in taken)
        live.add(r)
    return colour


def svg_header(x0, x1, y0, y1, pad=0.02, width=900):
    w, h = x1 - x0, y1 - y0
    mx, my = w * pad, h * pad
    vb = f"{x0-mx:.4f} {-(y1+my):.4f} {w+2*mx:.4f} {h+2*my:.4f}"
    ht = int(round(width * (h + 2 * my) / (w + 2 * mx)))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" '
            f'width="{width}" height="{ht}" style="background:#0d0f13">'), ht


def render_static(nodes, rings, fill_fn, out, width=900, stroke="#f2f0eb",
                  stroke_w=None, title=None):
    """One path per district, filled by fill_fn(district) -> colour."""
    reg = node_regions(nodes, rings)
    leaves = [i for i in reg if "district" in nodes[i]]
    x0, x1, y0, y1 = bbox(rings)
    sw = stroke_w if stroke_w is not None else (x1 - x0) / 900
    head, _ = svg_header(x0, x1, y0, y1, width=width)
    parts = [head]
    if title:
        parts.append(f"<title>{title}</title>")
    parts.append(f'<g stroke="{stroke}" stroke-width="{sw:.5f}" '
                 f'stroke-linejoin="round" fill-rule="evenodd">')
    for i in sorted(leaves, key=lambda i: nodes[i]["district"]):
        d = nodes[i]["district"]
        parts.append(f'<path id="d{d}" fill="{fill_fn(d)}" d="{path_d(reg[i])}">'
                     f'<title>District {d}</title></path>')
    parts.append("</g></svg>")
    Path(out).write_text("".join(parts))
    return len(leaves)


def render_animated(nodes, rings, out, width=900, title=None, ms=1600,
                    hold_first=1.5, hold_last=4.0, stroke="#f2f0eb",
                    order="bfs"):
    """The GIF, as one scalable file: flat colours, hard cuts between frames.

    CSS animation in step-end, not linear. Interpolating opacity would fade a
    region in over its whole frame, which reads as a dissolve; the algorithm
    does not dissolve, it cuts. step-end holds each value until the next
    keyframe, so a region is simply there or not.

    No scripting: scripts in an SVG run only when the file is opened as a
    document, so an image viewer or an <img> tag would show a blank frame.
    A renderer supporting no animation at all shows the finished map, because
    that is the base state the animation overrides.
    """
    reg = node_regions(nodes, rings)
    order = CUT_ORDERS[order](nodes) if isinstance(order, str) else order
    colour = incremental_colours(nodes, reg, order)
    nsteps = len(order) + 1

    span = {}
    for k in range(nsteps):
        for i in frontier(nodes, set(order[:k])):
            lo, hi = span.get(i, (k, k))
            span[i] = (min(lo, k), max(hi, k))

    # The undivided region and the finished map are the two frames worth
    # looking at, so both are held; the pause at the end also separates one
    # loop from the next.
    length = [1.0] * nsteps
    length[0] += hold_first
    length[-1] += hold_last
    start, t = [0.0], 0.0
    for L in length:
        t += L
        start.append(t)
    total = start[-1]
    dur = total * ms / 1000.0

    x0, x1, y0, y1 = bbox(rings)
    sw = (x1 - x0) / 900
    head, _ = svg_header(x0, x1, y0, y1, width=width)

    css = [f"#regions path{{animation-duration:{dur:.2f}s;"
           f"animation-iteration-count:infinite;"
           f"animation-timing-function:step-end}}"]
    body = []
    for i, polys in reg.items():
        if not polys or i not in span:
            continue
        lo, hi = span[i]
        a = 100.0 * start[lo] / total
        b = 100.0 if hi == nsteps - 1 else 100.0 * start[hi + 1] / total
        base = 1 if "district" in nodes[i] else 0
        frames = [f"0%{{opacity:0}}"] if lo > 0 else []
        frames.append(f"{a:.4f}%{{opacity:1}}")
        if b < 100.0:
            frames.append(f"{b:.4f}%{{opacity:0}}")
        css.append(f"#n{i}{{opacity:{base};animation-name:k{i}}}"
                   f"@keyframes k{i}{{" + "".join(frames) + "}")
        body.append(f'<path id="n{i}" fill="{PALETTE[colour.get(i,0)%len(PALETTE)]}" '
                    f'd="{path_d(polys)}"/>')

    parts = [head]
    if title:
        parts.append(f"<title>{title}</title>")
    parts.append("<style>" + "".join(css) + "</style>")
    parts.append(f'<g id="regions" stroke="{stroke}" stroke-width="{sw:.5f}" '
                 f'stroke-linejoin="round" fill-rule="evenodd">'
                 + "".join(body) + "</g></svg>")
    Path(out).write_text("".join(parts))
    return nsteps
