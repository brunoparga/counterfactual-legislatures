#!/usr/bin/env python3
"""Colour a stitched map by which party carried each district.

An instance of shared/tools/stitch.py, nothing more: the stitcher supplies
geometry, this supplies meaning. Swapping the colour function for a
four-colouring or a population-deviation ramp would reuse everything else.

Shade carries the margin, so a 50.1% district is nearly white and a safe seat
is saturated. A flat two-colour map would imply every district is equally
decided, which is the opposite of what a neutral map is supposed to show.

Alaska and Hawaii are drawn as their own panels because they do not belong on
a projection centred on the contiguous states -- not a special case in the
stitcher, just a second and third call to it.
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT.parent / "shared" / "tools"))
from apportion import build, house_size, huntington_hill  # noqa: E402
from apportionment import FIPS, NON_CONTIGUOUS  # noqa: E402
from metro_insets import windows as metro_windows  # noqa: E402
from stitch import (fwd, free_space, load_region, panel_projection,  # noqa: E402
                    panel_shift, place_boxes, stitch)

DEEP_D, PALE_D = (28, 78, 160), (176, 198, 232)
DEEP_R, PALE_R = (168, 32, 38), (238, 190, 190)


def ramp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


# The credit line is built from SOURCES.json rather than typed here, so a map
# cannot claim terms the provenance record disagrees with. Which sources a map
# used decides both the attributions it must carry and its own licence: any
# share-alike input makes the output share-alike too.
SOURCES = ROOT.parent / "SOURCES.json"


def credit_line(uses_votes):
    try:
        rec = json.loads(SOURCES.read_text())
    except OSError:
        return ""
    used = ["autodistrict-2007", "crv-splitline-maps", "us-census-2010-pl94171"]
    if uses_votes:
        # MEDSL supplies the seven at-large states, whose single district is
        # the whole state. CC0, so nothing is owed -- but they ask to be cited
        # and a map that uses their numbers should say so.
        used += ["dra-block-elections", "medsl-county-president"]
    by_id = {s["id"]: s for s in rec["sources"]}
    bits, share = [], False
    bits.append("Shortest splitline algorithm: Warren D. Smith")
    bits.append("original implementation: Ivan Ryan, 2007 (Apache-2.0)")
    bits.append("method and published maps: Center for Range Voting, "
                "rangevoting.org/SplitLR.html")
    bits.append("population: US Census Bureau (public domain)")
    for i in used:
        s_ = by_id.get(i, {})
        if s_.get("share_alike"):
            share = True
            if i == "dra-block-elections":
                bits.append("election data: Dave's Redistricting (CC BY-SA 4.0), "
                            "from the Voting and Election Science Team and "
                            "Ryne Rohla / Decision Desk HQ")
    if uses_votes:
        bits.append("at-large states: MIT Election Data and Science Lab, "
                    "doi:10.7910/DVN/VOQCHQ (CC0)")
    lic = "CC BY-SA 4.0" if share else "CC BY 4.0"
    bits.append(f"this map: {lic}")
    bits.append("github.com/brunoparga/counterfactual-legislatures")
    return " \u00b7 ".join(bits)


def boundary_file(census, st):
    """Where a state's outline lives for a given census.

    2000 shipped per-state ARC/INFO files named st<FIPS>_d00.dat; 2010 and
    2020 came as shapefiles that shp_to_dat.py converts to one boundary.dat
    per state. Same format either way, different name.
    """
    d = ROOT / "upstream" / str(census) / st.lower()
    b = d / "boundary.dat"
    if b.exists():
        return b
    hits = sorted(d.glob(f"st{FIPS[st]}_d00.dat"))
    return hits[0] if hits else None


def build_colours(path, cap=0.30):
    """(state, district) -> RGB, shaded by two-party margin."""
    out = {}
    for r in json.load(open(path)):
        tot = r["dem"] + r["rep"]
        if tot <= 0:
            continue
        m = abs(r["dem"] - r["rep"]) / tot
        t = min(m / cap, 1.0)
        out[(r["state"], r["district"])] = (
            ramp(PALE_D, DEEP_D, t) if r["dem"] > r["rep"]
            else ramp(PALE_R, DEEP_R, t))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--votes", default=str(ROOT / "work" / "block_votes_splitline.json"))
    ap.add_argument("--census", type=int, default=2010)
    ap.add_argument("--rule", default="fixed")
    ap.add_argument("--metric", default="span")
    ap.add_argument("--model", default="uniform")
    ap.add_argument("--width", type=int, default=2400)
    ap.add_argument("--title", default="")
    ap.add_argument("--insets", action="store_true",
                    help="blank the metro knots and draw them as panels")
    ap.add_argument("--basemap", action="store_true",
                    help="every district the same grey: the unpainted basis")
    ap.add_argument("--pan-x", type=float, default=0.0,
                    help="shift the frame right, moving the land left")
    ap.add_argument("--state-width", type=int, default=2,
                    help="state borders in px; internal cuts are always 1")
    ap.add_argument("--margin", type=float, default=0.02,
                    help="ocean around the land, as a fraction of extent")
    ap.add_argument("--inset-size", type=float, default=0.115,
                    help="panel width as a fraction of the map width")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    plans = ROOT / "plans"
    seats = huntington_hill(build(a.census, 0, 0), house_size(a.rule, build(a.census, 0, 0)))
    colours = build_colours(a.votes)
    missing = set()

    def load(sts):
        out = []
        for st in sts:
            n = seats.get(st, 0)
            if n <= 0:
                continue
            t = plans / f"{a.census}_{st.lower()}_{n}_{a.model}_{a.metric}.json"
            b = boundary_file(a.census, st)
            if not (t.exists() and b and b.exists()):
                continue
            out.append(load_region(st, t, b))
        return out

    if a.basemap:
        # The unpainted basis: every district the same grey, told apart only by
        # its edges. This is the map an election result gets applied to, and
        # drawing it once on its own is the honest way to see what the
        # algorithm produced without a partisan reading on top of it.
        def cf(name, d):
            return (146, 148, 156)
    else:
        def cf(name, d):
            c = colours.get((name, d))
            if c is None:
                missing.add((name, d))
                return (90, 90, 96)      # scored but unknown: visibly neutral
            return c

    conus = [s for s in seats if s not in NON_CONTIGUOUS and seats[s] > 0]
    regions = load(sorted(conus, key=lambda s: FIPS[s]))
    shift = panel_shift(regions)
    lon0, lat0 = panel_projection(regions, shift)

    metros = metro_windows(lon0, lat0, shift, fwd) if a.insets else []
    main_img, ids, win = stitch(
        regions, cf, width=a.width, outline=(236, 234, 229),
        outline_width=a.state_width,
        district_edges=(245, 243, 238), return_ids=True,
        lon0=lon0, lat0=lat0, shift=shift, margin=a.margin,
        pan=(a.pan_x, 0.0),
        blank_windows=[w for _, w in metros],
        blank_fill=(74, 76, 84) if a.basemap else (104, 106, 114))
    W, H = main_img.size
    x0, x1, y0, y1 = win

    def to_px(bx, by):
        return ((bx - x0) * W / (x1 - x0), (y1 - by) * H / (y1 - y0))

    canvas = main_img.copy()
    dr = ImageDraw.Draw(canvas)
    for _, (bx0, bx1, by0, by1) in metros:
        p0, p1 = to_px(bx0, by1), to_px(bx1, by0)
        dr.rectangle([p0, p1], outline=(250, 248, 243), width=2)

    pad = int(W * 0.008)
    x = pad
    for st, frac, bframe in (("AK", 0.155, 1.0), ("HI", 0.075, 0.995)):
        r = load([st])
        if not r:
            continue
        pan = stitch(r, cf, width=int(W * frac), outline=(236, 234, 229),
                     outline_width=a.state_width,
                     district_edges=(245, 243, 238), bounds_area_frac=bframe)
        canvas.paste(pan, (x, H - pan.size[1] - pad))
        x += pan.size[0] + pad

    if metros:
        side = int(W * a.inset_size)
        panels, sizes, targets = [], [], []
        for name, w in metros:
            pan = stitch(regions, cf, width=side, outline=(236, 234, 229),
                         outline_width=a.state_width,
                         district_edges=(245, 243, 238), lon0=lon0, lat0=lat0,
                         shift=shift, window=w)
            panels.append((name, pan, w))
            sizes.append(pan.size)   # label height is added below
            bx0, bx1, by0, by1 = w
            cx, cy = to_px((bx0 + bx1) / 2, (by0 + by1) / 2)
            targets.append((cx, cy))
        try:
            fnt = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                int(side * 0.13))
        except OSError:
            fnt = ImageFont.load_default()
        probe = ImageDraw.Draw(canvas)
        lab_h = max(probe.textbbox((0, 0), n, font=fnt)[3] for n, _, _ in panels)
        gap = max(2, int(side * 0.03))
        # the caption sits above the box, so reserve its height as part of the
        # footprint -- otherwise a box fits and its name lands on the coast
        sizes = [(w, h + lab_h + gap) for w, h in sizes]
        free = free_space(canvas)
        room = []
        for (bw, bh), (tx, ty) in zip(sizes, targets):
            r = int(max(bw, bh) * 2.5)
            sl = free[max(0, int(ty) - r):int(ty) + r,
                      max(0, int(tx) - r):int(tx) + r]
            room.append(sl.sum())
        idx = sorted(range(len(panels)), key=lambda i: room[i])
        spots = [None] * len(panels)
        got = place_boxes(free, [sizes[i] for i in idx],
                          [targets[i] for i in idx], step=8, pad=8)
        for i, g in zip(idx, got):
            spots[i] = g
        placed = 0
        for (name, pan, w), spot in zip(panels, spots):
            if spot is None:
                print(f"  no room for {name}")
                continue
            bx, by = spot
            py = by + lab_h + gap
            canvas.paste(pan, (bx, py))
            d2 = ImageDraw.Draw(canvas)
            d2.rectangle([(bx, py), (bx + pan.size[0], py + pan.size[1])],
                         outline=(250, 248, 243), width=2)
            bx0, bx1, by0, by1 = w
            sx, sy = to_px((bx0 + bx1) / 2, (by0 + by1) / 2)
            d2.line([(sx, sy), (bx + pan.size[0] / 2, py + pan.size[1] / 2)],
                    fill=(150, 152, 160), width=1)
            d2.text((bx, by), name, font=fnt, fill=(245, 243, 238))
            placed += 1
        print(f"insets placed: {placed} of {len(panels)}")

    if a.title:
        # A band above the map rather than text over it. Overlaying the title
        # cost us Seattle, which sits in the top-left corner of a map of the
        # contiguous states.
        try:
            f = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(W * 0.017))
        except OSError:
            f = ImageFont.load_default()
        probe = ImageDraw.Draw(canvas)
        bb = probe.textbbox((0, 0), a.title, font=f)
        band = (bb[3] - bb[1]) + int(W * 0.022)
        titled = Image.new("RGB", (W, canvas.size[1] + band), (13, 15, 19))
        titled.paste(canvas, (0, band))
        ImageDraw.Draw(titled).text(
            (pad, (band - (bb[3] - bb[1])) // 2 - bb[1]),
            a.title, font=f, fill=(240, 238, 233))
        canvas = titled

    # Credit band along the bottom: off-white, small, and outside the map so it
    # covers nothing.
    text = credit_line(uses_votes=not a.basemap)
    try:
        cf_ = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(W * 0.0088))
    except OSError:
        cf_ = ImageFont.load_default()
    probe = ImageDraw.Draw(canvas)
    # The full attribution runs to twice the canvas width, so it wraps on the
    # separators rather than being silently clipped -- a truncated licence
    # notice is worse than none, since it looks complete.
    avail = W - 2 * pad
    lines, cur = [], ""
    for chunk in text.split(" \u00b7 "):
        trial = chunk if not cur else cur + " \u00b7 " + chunk
        if probe.textlength(trial, font=cf_) <= avail:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = chunk
    if cur:
        lines.append(cur)
    lh = probe.textbbox((0, 0), "Ag", font=cf_)[3]
    gap = int(lh * 0.35)
    band = len(lines) * (lh + gap) + int(W * 0.010)
    final = Image.new("RGB", (W, canvas.size[1] + band), (13, 15, 19))
    final.paste(canvas, (0, 0))
    dd = ImageDraw.Draw(final)
    yy = canvas.size[1] + int(W * 0.005)
    for ln in lines:
        dd.text((pad, yy), ln, font=cf_, fill=(196, 194, 188))
        yy += lh + gap
    canvas = final
    canvas.save(a.out, optimize=True)
    print(f"wrote {a.out}  {canvas.size[0]}x{canvas.size[1]}")
    if missing:
        print(f"districts with no vote data: {len(missing)} "
              f"({' '.join(sorted({s for s, _ in missing}))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
