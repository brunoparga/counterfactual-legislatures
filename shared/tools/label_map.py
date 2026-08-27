#!/usr/bin/env python3
"""Caption a rendered map with what it is.

Says the region, how many districts, and which census -- the things a viewer
needs to read the picture. Not the population model or the cut-length metric:
those change the map but mean nothing to anyone who has not read the code, and
a caption crowded with parameters is worse than no caption.

Placement is deliberately dumb: a corner, with a soft dark pad behind the text
so it stays readable over both the near-black empty areas and the bright city
speckle. Placing it in the largest empty space inside the state outline is the
better answer and is on the roadmap; it is not worth blocking a caption on.

Animated GIFs are captioned frame by frame and re-encoded.
"""

import argparse
import sys

from PIL import Image, ImageDraw, ImageFont, ImageSequence

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_LIGHT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def draw_caption(im, title, sub=None, corner="tl", scale=0.034, pad_frac=0.022):
    """Draw title (and optional subtitle) onto a copy of `im`."""
    im = im.convert("RGB")
    w, h = im.size
    size = max(13, int(h * scale))
    try:
        f1 = ImageFont.truetype(FONT, size)
        f2 = ImageFont.truetype(FONT_LIGHT, int(size * 0.72))
    except OSError:
        f1 = f2 = ImageFont.load_default()

    d = ImageDraw.Draw(im, "RGBA")
    pad = int(h * pad_frac)
    lines = [(title, f1)] + ([(sub, f2)] if sub else [])

    widths, heights = [], []
    for t, f in lines:
        box = d.textbbox((0, 0), t, font=f)
        widths.append(box[2] - box[0])
        heights.append(box[3] - box[1])
    tw = max(widths)
    th = sum(heights) + (int(size * 0.35) if sub else 0)

    x = pad if corner in ("tl", "bl") else w - tw - pad
    y = pad if corner in ("tl", "tr") else h - th - pad * 2

    # A soft pad rather than a hard box: enough to lift the text off bright
    # pixels without looking like a sticker.
    m = int(size * 0.45)
    d.rectangle([x - m, y - m, x + tw + m, y + th + m], fill=(0, 0, 0, 130))

    cy = y
    for (t, f), hh in zip(lines, heights):
        d.text((x, cy), t, font=f, fill=(255, 255, 255, 235))
        cy += hh + int(size * 0.35)
    return im


def label_file(src, dst, title, sub=None, corner="tl", scale=0.034):
    im = Image.open(src)
    if getattr(im, "is_animated", False):
        frames = [draw_caption(f, title, sub, corner, scale).convert(
                      "P", palette=Image.ADAPTIVE, colors=128)
                  for f in ImageSequence.Iterator(im)]
        frames[0].save(dst, save_all=True, append_images=frames[1:],
                       duration=im.info.get("duration", 300),
                       loop=0, optimize=True)
        return len(frames)
    draw_caption(im, title, sub, corner, scale).save(dst, optimize=True)
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--title", required=True)
    ap.add_argument("--sub")
    ap.add_argument("--corner", default="tl", choices=("tl", "tr", "bl", "br"))
    ap.add_argument("--scale", type=float, default=0.034)
    a = ap.parse_args()
    n = label_file(a.src, a.dst, a.title, a.sub, a.corner, a.scale)
    print(f"{a.dst}: {n} frame(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
