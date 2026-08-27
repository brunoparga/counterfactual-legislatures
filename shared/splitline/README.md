# splitline

Shortest-splitline districting, derived from [autodistrict](https://sourceforge.net/projects/autodistrict/)
(Ivan Ryan, 2007, Apache-2.0). See `vendor/` for the pristine upstream and what
is in its history.

    make
    bin/splitline --boundary STATE.dat --pop STATE.pop --seats 9 \
                  --tree state.json --assign state.csv --png state.png

## Two engines

| binary | what it is |
|---|---|
| `bin/splitline` | point-based. The one to use. |
| `bin/splitline_raster` | faithful port of the 2007 raster approach, kept for cross-checking. |

The 2007 original rasterised the state, binned population into pixels, and
searched for cuts on the pixel grid. That was right for 2007 and wrong now: at
100 px/degree a pixel is 1.1 km and holds thousands of people in a city, none
of whom can be split. It shows up directly as population inequality — on a
uniform test square the raster engine lands at 0.020% spread where the
point-based engine is *exact*:

| test | raster | point-based |
|---|---|---|
| uniform square, 4 seats | 0.020% | **0.0000%** |
| clustered field, 32 seats | 6.550% | 5.067% |

The clustered case is still not exact, and that is the population model, not
the algorithm — see below.

## Outputs

**`--tree FILE` is the real output.** Every cut is a straight line, so each
district is the outline intersected with the half-planes on its path from the
root. That makes the whole map a binary tree of line equations:

- 32 districts = 63 nodes = 6 KB of JSON, against 141 KB for the equivalent BMP.
  432 districts is roughly 86 KB, against ~51 MB for a national BMP.
- District geometry is exact and resolution-free, not a pixel approximation.
- Lookup is a tree walk: `⌈log2(seats)⌉` comparisons, 9 for a national map.
  Verified against the C engine by replaying every point through an independent
  implementation — see the tree's own `note` field for the rule.

`--png` renders a picture *from* the tree, so resolution (`--gain`) is a free
parameter rather than a property of the run. `--assign` writes per-record
district assignment, which is what downstream questions (who changed districts
between cycles, joining election results) actually need.

## District numbering

Districts are numbered from 1 by a depth-first walk of the cut tree, left child
first.

For that to mean anything, the tree is canonicalised first. Every cut line has
two equivalent descriptions, `n`/`c` and `-n`/`-c`, and the angle search picks
whichever it happens to land on — so before canonicalisation "left child" was
effectively a coin flip and the numbering carried no information. Each cut is
now rewritten into a canonical form and its children swapped to match. Since
the lookup test `p·n < c` becomes `p·n > c` when both sides are negated,
swapping children preserves the geometry exactly.

**Left is the western side**, with north as the tie-break only for a cut
running exactly east-west, which has no western side. So normals point east
(`nx > 0`), and south (`ny < 0`) when the cut is horizontal. West dominates: a
cut tilted slightly anticlockwise from north-south keeps west-and-south as its
left child rather than flipping to north-and-east.

The comparison needs an epsilon. A due east-west cut emerges from the angle
sweep as `cos(pi/2)`, which is 6e-17 rather than 0, so testing `nx` against
exact zero would decide a horizontal cut on the sign of a rounding artifact.

District 1 is therefore the one reached by always heading west. Colorado 2000
comes out in clean west-to-east order, districts 1 through 7 running from
-107.2 to -103.4 mean longitude. That tidiness is not guaranteed, though: this
is a tree traversal, not a sort, so consecutive numbers are usually but not
always neighbours. If you need a strict geographic order, sort on the district
centroids instead.

**Numbers are not stable across censuses.** A shift in population moves the
cuts and renumbers everything downstream. For cycle-over-cycle comparison, use
geometry or block assignments, not district numbers.

## Population model, and the one caveat

Each input record is a **point mass**: all of a block's people sit on its
centroid. Two consequences:

1. Residual inequality is bounded by the largest single block's population
   relative to a district. Real blocks average ~40 people against a ~760k
   district, so this is small — but it is why the clustered synthetic test
   above still shows 5%, since one synthetic point there carries 5100 people.

2. When a cut passes through a block, everyone in it goes to whichever side the
   centroid fell. So "which district is this address in?" (geometry) and "how
   many people are in this district?" (accounting) can disagree for residents
   of blocks a line crosses. Pick one rule per question and say which.

Both dissolve if blocks are treated as **uniform density over their polygon**
rather than points: population splits by area, the two questions agree by
construction, and the cut can hit its target exactly because cumulative
population becomes continuous instead of a step function. That needs TIGER
TABBLOCK polygons rather than centroids. Everything depending on the model is
behind `find_offset()` and the `Pt` array, so it is a swap, not a rewrite.

## Input formats

`--boundary` is ARC/INFO ungenerate: a polygon id and centroid, then vertex
pairs, then `END`; `-99999` starts a hole ring; a final `END` closes the file.
The leading centroid is skipped when building edges.

`--pop` is `tract,block,pop,curve,lon,lat`, one record per line. Records with
zero population are dropped — they cannot move a cut.

`tools/make_synthetic.py` generates both for testing.
