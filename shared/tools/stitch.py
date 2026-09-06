#!/usr/bin/env python3
"""Composite many separately-districted regions into one picture.

Each region was districted on its own, in its own projection, and knows
nothing about its neighbours. Stitching them is not a re-run: the cut trees
already hold the answer, and every pixel needs only

    pixel -> longitude/latitude -> which region is this? -> walk that
    region's tree -> which district? -> what colour is that district?

The last step is a callback, which is what makes this general. Colour by
party, by a four-colouring of the adjacency graph, by population deviation,
by anything at all -- the geometry does not change and nothing is recomputed.

Nothing here is American, or specific to splitline. A region is a name, an
outline and a tree; the caller supplies the meaning.

Regions that do not belong on the same canvas -- Alaska and Hawaii on a map of
the contiguous states, an overseas territory anywhere -- are not a special
case to be handled here. Render them as their own panel and place it where you
want it; `stitch` draws one panel.
"""

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def read_rings(path):
    """ARC/INFO ungenerate -> list of rings of (lon, lat)."""
    rings, cur = [], None
    for line in open(path):
        t = line.split()
        if not t:
            continue
        if t[0].upper() == "END":
            if cur:
                rings.append(cur)
            cur = None
        elif len(t) >= 3:
            if cur:
                rings.append(cur)
            cur = []
        elif len(t) == 2:
            if cur is None:
                cur = []
            cur.append((float(t[0]), float(t[1])))
    if cur:
        rings.append(cur)
    return [r for r in rings if len(r) >= 3]


def fwd(lon, lat, lon0, lat0, shift=0.0):
    """Gnomonic, in degrees. Returns NaN behind the horizon."""
    lo = np.radians(np.asarray(lon, float) + shift)
    la = np.radians(np.asarray(lat, float))
    l0, a0 = math.radians(lon0), math.radians(lat0)
    cosc = np.sin(a0) * np.sin(la) + np.cos(a0) * np.cos(la) * np.cos(lo - l0)
    with np.errstate(divide="ignore", invalid="ignore"):
        x = np.cos(la) * np.sin(lo - l0) / cosc
        y = (np.cos(a0) * np.sin(la) - np.sin(a0) * np.cos(la) * np.cos(lo - l0)) / cosc
    bad = cosc <= 0
    return np.where(bad, np.nan, np.degrees(x)), np.where(bad, np.nan, np.degrees(y))


def inv(x, y, lon0, lat0, shift=0.0):
    """Gnomonic inverse: projected degrees -> lon/lat."""
    xr, yr = np.radians(np.asarray(x, float)), np.radians(np.asarray(y, float))
    rho = np.hypot(xr, yr)
    l0, a0 = math.radians(lon0), math.radians(lat0)
    c = np.arctan(rho)
    with np.errstate(divide="ignore", invalid="ignore"):
        lat = np.arcsin(np.where(rho == 0, math.sin(a0),
                                 np.cos(c) * math.sin(a0)
                                 + yr * np.sin(c) * math.cos(a0) / rho))
        lon = l0 + np.arctan2(xr * np.sin(c),
                              rho * math.cos(a0) * np.cos(c)
                              - yr * math.sin(a0) * np.sin(c))
    return np.degrees(lon) - shift, np.degrees(lat)


def load_region(name, tree, boundary):
    d = json.load(open(tree))
    return {"name": name,
            "nodes": {n["i"]: n for n in d["nodes"]},
            "proj": d["projection"],
            "rings": read_rings(boundary),
            "seats": d.get("seats")}


def walk(nodes, X, Y):
    """District number for each point."""
    out = np.full(len(X), -1, np.int32)
    stack = [(0, np.arange(len(X)))]
    while stack:
        i, sel = stack.pop()
        if not len(sel):
            continue
        n = nodes[i]
        if "district" in n:
            out[sel] = n["district"]
            continue
        s = (X[sel] * n["nx"] + Y[sel] * n["ny"]) < n["c"]
        stack.append((n["left"], sel[s]))
        stack.append((n["right"], sel[~s]))
    return out


def panel_shift(regions):
    """180 if this panel straddles the antimeridian, else 0.

    Alaska runs from about 172E to 130W. Taken literally that is a span of
    nearly the whole globe, so a centre computed from it lands in Africa and
    the projection tears the state in half. Shifting longitudes by 180 puts the
    seam in the Atlantic where nothing is being drawn.
    """
    los = [p[0] for r in regions for ring in r["rings"] for p in ring]
    return 180.0 if (max(los) - min(los)) > 180 else 0.0


def panel_projection(regions, shift=0.0):
    """One gnomonic projection centred on everything being drawn."""
    los = [((p[0] + shift + 180) % 360) - 180
           for r in regions for ring in r["rings"] for p in ring]
    las = [p[1] for r in regions for ring in r["rings"] for p in ring]
    return (min(los) + max(los)) / 2, (min(las) + max(las)) / 2


def stitch(regions, colour_fn, width=2000, margin=0.02,
           background=(13, 15, 19), outline=None, outline_width=1,
           lon0=None, lat0=None, window=None, district_edges=None,
           return_ids=False, shift=None, bounds_area_frac=1.0,
           blank_windows=None, blank_fill=(104, 106, 114),
           blank_stroke=(240, 238, 233), pan=(0.0, 0.0)):
    """Render regions into one image.

    colour_fn(region_name, district) -> (r, g, b), or None to leave background.
    outline, if given, is the colour of the region borders -- the thing that
    distinguishes a stitched map from an all-in-one-go one.

    district_edges draws a line wherever two districts meet. Without it a map
    is only readable where neighbours happen to differ in colour, which is
    exactly what a partisan colouring cannot promise: two safe seats side by
    side are the same red, and the boundary between them disappears.

    window=(x0, x1, y0, y1) in projected degrees renders a sub-rectangle at
    full width instead of the whole extent -- which is all an inset is.

    blank_windows are rectangles to flatten to a single colour instead of
    drawing districts in. A metro area on a national map is a knot of slivers
    that resolves into noise at this scale; showing it as one grey block says
    plainly "this is not readable here, look at the inset" rather than
    pretending an illegible smear is information.

    bounds_area_frac below 1 sizes the frame from the largest rings holding
    that share of the total area, ignoring the rest. Hawaii's outline runs out
    to Kure Atoll, 2000 km beyond anyone who lives there, and framing to it
    would leave a panel of empty ocean. The outlying rings are still drawn --
    they are simply not allowed to decide the zoom.

    return_ids also hands back the per-pixel district raster, so a caller can
    find where the small districts are without rendering twice.
    """
    if shift is None:
        shift = panel_shift(regions)
    if lon0 is None or lat0 is None:
        lon0, lat0 = panel_projection(regions, shift)

    proj = []
    for r in regions:
        rr = [np.array(fwd([p[0] for p in ring], [p[1] for p in ring],
                           lon0, lat0, shift)).T
              for ring in r["rings"]]
        proj.append([a[~np.isnan(a).any(1)] for a in rr])
    if window is not None:
        x0, x1, y0, y1 = window
    else:
        keep = [a for rr in proj for a in rr if len(a) >= 3]
        if bounds_area_frac < 1.0 and len(keep) > 1:
            def area(a):
                x, y = a[:, 0], a[:, 1]
                return abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))) / 2
            ranked = sorted(keep, key=area, reverse=True)
            tot = sum(area(a) for a in ranked) or 1.0
            run, keep = 0.0, []
            for a in ranked:
                keep.append(a)
                run += area(a)
                if run / tot >= bounds_area_frac:
                    break
        allpts = np.vstack(keep)
        x0, y0 = allpts.min(0)
        x1, y1 = allpts.max(0)
        mx, my = (x1 - x0) * margin, (y1 - y0) * margin
        x0, x1, y0, y1 = x0 - mx, x1 + mx, y0 - my, y1 + my
        # pan shifts the frame, not the content: a positive x moves the land
        # left in the image, freeing the right-hand ocean for insets
        dx, dy = pan[0] * (x1 - x0), pan[1] * (y1 - y0)
        x0, x1, y0, y1 = x0 + dx, x1 + dx, y0 + dy, y1 + dy
    W = width
    H = max(1, int(round(W * (y1 - y0) / (x1 - x0))))

    def to_px(a):
        return np.c_[(a[:, 0] - x0) * W / (x1 - x0), (y1 - a[:, 1]) * H / (y1 - y0)]

    px = x0 + (np.arange(W) + 0.5) * (x1 - x0) / W
    py = y1 - (np.arange(H) + 0.5) * (y1 - y0) / H
    PX, PY = np.meshgrid(px, py)
    LON, LAT = inv(PX, PY, lon0, lat0, shift)

    img = np.zeros((H, W, 3), np.uint8)
    img[:] = background
    # A single id per pixel spanning every region, so an edge between two
    # districts of different states is detected the same way as one inside a
    # state. -1 is "no district here".
    ids = np.full((H, W), -1, np.int64)

    for ri, (r, rings) in enumerate(zip(regions, proj)):
        mask_img = Image.new("1", (W, H), 0)
        md = ImageDraw.Draw(mask_img)
        for a in rings:
            if len(a) >= 3:
                md.polygon([tuple(p) for p in to_px(a)], fill=1)
        m = np.array(mask_img, dtype=bool)
        if not m.any():
            continue
        pr = r["proj"]
        X, Y = fwd(LON[m], LAT[m], pr["lon0"], pr["lat0"], pr.get("lon_shift", 0.0))
        ok = ~(np.isnan(X) | np.isnan(Y))
        dist = np.full(X.shape, -1, np.int32)
        if ok.any():
            dist[ok] = walk(r["nodes"], X[ok], Y[ok])
        flat = img[m]
        for dd in np.unique(dist):
            if dd < 0:
                continue
            c = colour_fn(r["name"], int(dd))
            if c is not None:
                flat[dist == dd] = c
        img[m] = flat
        idflat = ids[m]
        idflat[dist >= 0] = ri * 100000 + dist[dist >= 0]
        ids[m] = idflat

    if blank_windows:
        for bw in blank_windows:
            bx0, bx1, by0, by1 = bw
            cx0 = int(round((bx0 - x0) * W / (x1 - x0)))
            cx1 = int(round((bx1 - x0) * W / (x1 - x0)))
            cy0 = int(round((y1 - by1) * H / (y1 - y0)))
            cy1 = int(round((y1 - by0) * H / (y1 - y0)))
            cx0, cx1 = max(0, cx0), min(W, cx1)
            cy0, cy1 = max(0, cy0), min(H, cy1)
            if cx1 <= cx0 or cy1 <= cy0:
                continue
            sub = ids[cy0:cy1, cx0:cx1]
            reg_px = sub >= 0
            blk = img[cy0:cy1, cx0:cx1]
            blk[reg_px] = blank_fill
            img[cy0:cy1, cx0:cx1] = blk
            # blanked pixels must not also grow district edges
            sub[reg_px] = -2
            ids[cy0:cy1, cx0:cx1] = sub

    if district_edges is not None:
        e = np.zeros((H, W), bool)
        e[:, :-1] |= (ids[:, :-1] != ids[:, 1:]) & (ids[:, :-1] >= 0) & (ids[:, 1:] >= 0)
        e[:-1, :] |= (ids[:-1, :] != ids[1:, :]) & (ids[:-1, :] >= 0) & (ids[1:, :] >= 0)
        img[e] = district_edges

    out = Image.fromarray(img)
    if outline:
        dr = ImageDraw.Draw(out)
        for rings in proj:
            for a in rings:
                if len(a) >= 3:
                    p = [tuple(v) for v in to_px(a)]
                    dr.line(p + [p[0]], fill=outline, width=outline_width)
    if return_ids:
        return out, ids, (x0, x1, y0, y1)
    return out


def find_insets(ids, window, min_px=None, pad=0.25, min_districts=2,
                max_insets=6, quantile=0.06):
    """Where is this map illegible, and what rectangle would fix it?

    Population decides district size, so a metro area collapses into a knot of
    slivers while the countryside is a handful of vast districts. Which places
    need magnifying is a property of the drawing, not a list of city names, so
    it is read off the rendered map: find districts far smaller than typical,
    group the ones that touch, and box each group.

    ids is the per-pixel district raster from stitch(return_ids=True), window
    the projected bounds it was drawn in. Returns windows in the same units,
    largest cluster first, ready to hand back to stitch(window=...).
    """
    from scipy import ndimage

    x0, x1, y0, y1 = window
    H, W = ids.shape
    vals, counts = np.unique(ids[ids >= 0], return_counts=True)
    if len(vals) == 0:
        return []
    if min_px is None:
        # "Far smaller than typical" rather than an absolute size, so the same
        # rule works on a state and on a nation.
        min_px = max(4, int(np.quantile(counts, quantile)))
    small = set(vals[counts <= min_px].tolist())
    if not small:
        return []

    mask = np.isin(ids, list(small))
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    out = []
    for k in range(1, n + 1):
        sel = lab == k
        ndist = len(set(ids[sel].tolist()))
        if ndist < min_districts:
            continue
        ys, xs = np.where(sel)
        # pixel bbox -> projected bounds, padded so the cluster is not flush
        # against the frame
        px0 = x0 + xs.min() * (x1 - x0) / W
        px1 = x0 + (xs.max() + 1) * (x1 - x0) / W
        py1 = y1 - ys.min() * (y1 - y0) / H
        py0 = y1 - (ys.max() + 1) * (y1 - y0) / H
        w, h = px1 - px0, py1 - py0
        side = max(w, h) * (1 + 2 * pad)
        cx, cy = (px0 + px1) / 2, (py0 + py1) / 2
        out.append({"window": (cx - side / 2, cx + side / 2,
                               cy - side / 2, cy + side / 2),
                    "districts": ndist, "pixels": int(sel.sum())})
    out.sort(key=lambda d: -d["districts"])
    return out[:max_insets]


def free_space(img, background=(13, 15, 19), tol=6):
    """Boolean mask of pixels still showing the background."""
    a = np.asarray(img).astype(int)
    return (np.abs(a - np.array(background)).max(2) <= tol)


def place_boxes(free, sizes, targets, step=8, pad=6):
    """Fit rectangles into empty space, each as near its subject as possible.

    A national map is mostly ocean and Canada, so there is room for insets --
    but where the room is depends on the projection and on what else has
    already been placed. Rather than hard-coding corners, this asks the
    rendered image: take the pixels still showing background, and for each box
    find the free position closest to the thing it magnifies.

    Emptiness is tested in constant time per candidate with a summed-area
    table, so scanning the whole canvas for every box is cheap.
    """
    H, W = free.shape
    occ = ~free
    out = []
    for (bw, bh), (tx, ty) in zip(sizes, targets):
        S = np.cumsum(np.cumsum(occ.astype(np.int32), 0), 1)

        def blocked(x, y, w, h):
            x1, y1 = x + w - 1, y + h - 1
            if x < 0 or y < 0 or x1 >= W or y1 >= H:
                return True
            tot = S[y1, x1]
            if x:
                tot -= S[y1, x - 1]
            if y:
                tot -= S[y - 1, x1]
            if x and y:
                tot += S[y - 1, x - 1]
            return tot > 0

        best = None
        for y in range(0, H - bh, step):
            for x in range(0, W - bw, step):
                if blocked(x - pad, y - pad, bw + 2 * pad, bh + 2 * pad):
                    continue
                d = (x + bw / 2 - tx) ** 2 + (y + bh / 2 - ty) ** 2
                if best is None or d < best[0]:
                    best = (d, x, y)
        if best is None:
            out.append(None)
            continue
        _, x, y = best
        out.append((x, y))
        occ[max(0, y - pad):y + bh + pad, max(0, x - pad):x + bw + pad] = True
    return out
