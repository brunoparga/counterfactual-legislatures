#!/usr/bin/env python3
"""Turn a cut tree into an animation of the districting being drawn.

The tree already contains the animation. Frame N is the same map with only the
first N cuts applied, so the whole sequence is a rendering question, not a
districting one -- nothing is recomputed.

All frames come from a single engine process. That matters for more than
speed: the colour palette is computed once over the finished tree, so a
district keeps its colour from the frame it appears in to the last. Rendering
each frame separately recolours from scratch every time and the map flickers.

Nothing here is country-specific. It takes a boundary, a population file, a
tree and an output path.
"""

import subprocess
import time
from pathlib import Path

from PIL import Image

# A whole animation should run for about this long however many frames it has,
# so a 4-seat region does not flash past and an 80-seat one does not crawl.
TARGET_MS = 9000
MIN_FRAME_MS = 90


def render_frames(engine, boundary, pop, tree, tmpdir, width=900, prefix="f"):
    """Render every frame of one tree in a single engine pass.

    Returns the frame paths in cut order. Raises on engine failure so a caller
    can distinguish "no frames" from "engine broke".
    """
    tmpdir = Path(tmpdir)
    tmpdir.mkdir(parents=True, exist_ok=True)
    for old in tmpdir.glob(f"{prefix}_cut*.png"):
        old.unlink()

    r = subprocess.run(
        [str(engine), "--boundary", str(boundary), "--pop", str(pop),
         "--render-only", str(tree), "--anim", str(tmpdir / prefix),
         "--width", str(width), "--quiet"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-500:] or "engine failed")

    return sorted(tmpdir.glob(f"{prefix}_cut*.png"),
                  key=lambda p: int(p.stem.split("cut")[1]))


def build_gif(frames, out, hold_first=1.6, hold_last=2.6, colors=128):
    """Assemble frames into a looping GIF, paced so the whole clip runs about
    TARGET_MS regardless of frame count.

    The first and last frames are held longer: the undivided region and the
    finished map are the two a viewer actually wants to look at.
    """
    frames = list(frames)
    if not frames:
        raise ValueError("no frames")
    per = max(MIN_FRAME_MS, TARGET_MS // len(frames))
    if len(frames) == 1:
        dur = [per]
    else:
        dur = ([int(per * hold_first)] + [per] * (len(frames) - 2)
               + [int(per * hold_last)])

    # Convert to a palette as each frame is opened rather than holding every
    # frame as RGB: an 80-frame animation is ~45 MB this way and ~250 MB the
    # other, which matters on a machine already running a districting pass.
    imgs = [Image.open(f).convert("P", palette=Image.ADAPTIVE, colors=colors)
            for f in frames]
    imgs[0].save(out, save_all=True, append_images=imgs[1:],
                 duration=dur, loop=0, optimize=True)
    return len(imgs)


def animate(engine, boundary, pop, tree, out, tmpdir, width=900):
    """render_frames + build_gif. Returns (frame count, seconds)."""
    t0 = time.time()
    frames = render_frames(engine, boundary, pop, tree, tmpdir, width)
    if not frames:
        raise RuntimeError(f"{tree}: engine produced no frames")
    n = build_gif(frames, out)
    return n, time.time() - t0
