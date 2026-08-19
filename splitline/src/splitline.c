//
// splitline - shortest splitline districting, point-based
//
// Derived from autodistrict (bmp_version) by Ivan Ryan, 2007:
//   https://sourceforge.net/projects/autodistrict/
// Original code Copyright 2007 Ivan Ryan, Apache License 2.0.
// Rewritten 2026 to work on population points rather than a raster.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
// either express or implied.
//
// -------------------------------------------------------------------------
//
// The 2007 original rasterised the state, binned population into pixels, and
// searched for cuts on the pixel grid. That was the right call on 2007
// hardware and is the wrong call now: at 100 px/degree a pixel is 1.1 km and
// holds thousands of people in a city, none of whom can be split, which shows
// up directly as population inequality between districts.
//
// This version keeps the algorithm and drops the raster. Cuts are found on the
// population points themselves, so the only quantisation left is the census
// block. The authoritative output is the tree of cut lines: every district is
// the state outline intersected with the half-planes on its path from the
// root, which makes district geometry exact, tiny to store, and O(depth) to
// query. Pictures are rendered from that tree at whatever resolution is asked
// for, rather than being the primary artifact.
//
// POPULATION MODEL: each input record is a point mass -- all of a block's
// people sit on its centroid. Everything that depends on that assumption is
// behind region_population() and split_at(); moving to area-weighted blocks
// (uniform density within each block polygon) means changing those, not the
// search.
//

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <zlib.h>

#define MAXDEPTH 64
#define NBINS 4096

static int opt_quiet = 0;

static void die(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "splitline: ");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
    exit(1);
}

static void note(const char *fmt, ...) {
    if (opt_quiet) return;
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stdout, fmt, ap);
    va_end(ap);
    fflush(stdout);
}

static void *xmalloc(size_t n) {
    void *p = malloc(n ? n : 1);
    if (!p) die("out of memory (%zu bytes)", n);
    return p;
}

static void *xcalloc(size_t n, size_t s) {
    void *p = calloc(n ? n : 1, s);
    if (!p) die("out of memory (%zu x %zu)", n, s);
    return p;
}

// ------------------------------------------------------------- projection --

static double la0 = 0, ph1 = 0;  // gnomonic centre
static double xoff = 0;          // antimeridian shift

static void gnomonic(double lon, double lat, double *x, double *y) {
    static const double D = M_PI / 180.0;
    lon += xoff;
    if (lon >= 180) lon -= 360;
    double la = lon * D, ph = lat * D, l0 = la0 * D, p1 = ph1 * D;
    double den = sin(p1) * sin(ph) + cos(p1) * cos(ph) * cos(la - l0);
    *x = (cos(ph) * sin(la - l0) / den) / D;
    *y = ((cos(p1) * sin(ph) - sin(p1) * cos(ph) * cos(la - l0)) / den) / D;
}

// ---------------------------------------------------------------- outline --

// Boundary edges in projected coordinates. Rings are closed on load, so an
// edge list is all the algorithm needs; ring structure only matters for the
// even-odd rules, which work edge-by-edge anyway.
typedef struct {
    double ax, ay, bx, by;
    double lox, loy, hix, hiy;
} Edge;

static Edge *edges;
static int nedges;

// Raw vertices, kept for rendering the land mask.
static double *vx, *vy;
static int *vtag;  // >0 new polygon, -99999 new hole ring, 0 continuation
static int nvert;

static double out_lox, out_loy, out_hix, out_hiy;

static void load_outline(const char *fname) {
    FILE *fp = fopen(fname, "r");
    if (!fp) die("cannot open boundary %s: %s", fname, strerror(errno));

    int cap = 1 << 16;
    vx = xmalloc(sizeof(double) * cap);
    vy = xmalloc(sizeof(double) * cap);
    vtag = xmalloc(sizeof(int) * cap);

    int n = 0, id;
    double a, b;
    while (fscanf(fp, "%d", &id) > 0) {
        int first = 1;
        while (fscanf(fp, "%lf %lf", &a, &b) > 0) {
            if (n + 2 >= cap) {
                cap *= 2;
                vx = realloc(vx, sizeof(double) * cap);
                vy = realloc(vy, sizeof(double) * cap);
                vtag = realloc(vtag, sizeof(int) * cap);
                if (!vx || !vy || !vtag) die("out of memory growing outline");
            }
            vx[n] = a;
            vy[n] = b;
            vtag[n] = first ? id : 0;
            first = 0;
            n++;
        }
        if (fscanf(fp, "END") == EOF) break;
    }
    fclose(fp);
    nvert = n;
    if (!nvert) die("boundary %s has no vertices", fname);
}

// The ungenerate format leads each polygon with its centroid, so the first
// coordinate pair of a ring is not on the ring. It is harmless for an even-odd
// fill (the spur out to the first real vertex and back cancels) but it is not
// harmless for measuring a cut, so drop it here.
static void project_outline(void) {
    // Choose the projection centre from the unprojected extent first.
    double lox = 1e18, hix = -1e18, loy = 1e18, hiy = -1e18;
    for (int i = 0; i < nvert; i++) {
        if (vx[i] < lox) lox = vx[i];
        if (vx[i] > hix) hix = vx[i];
        if (vy[i] < loy) loy = vy[i];
        if (vy[i] > hiy) hiy = vy[i];
    }
    if (hix - lox > 180) xoff = 180;

    lox = 1e18; hix = -1e18;
    for (int i = 0; i < nvert; i++) {
        double t = vx[i] + xoff;
        if (t >= 180) t -= 360;
        if (t < lox) lox = t;
        if (t > hix) hix = t;
    }
    la0 = (lox + hix) / 2;
    ph1 = (loy + hiy) / 2;
    note("projection centre %.4f, %.4f\n", la0, ph1);

    for (int i = 0; i < nvert; i++) gnomonic(vx[i], vy[i], &vx[i], &vy[i]);

    // Build edges, ring by ring, skipping each ring's leading centroid.
    int cap = nvert + 16;
    edges = xmalloc(sizeof(Edge) * cap);
    nedges = 0;

    int i = 0;
    while (i < nvert) {
        int start = i;         // centroid slot
        int rs = start + 1;    // first real vertex
        i = rs;
        while (i < nvert && vtag[i] == 0) i++;
        int re = i;            // one past last real vertex
        if (re - rs >= 2) {
            for (int k = rs; k < re; k++) {
                int k2 = (k + 1 < re) ? k + 1 : rs;
                Edge *e = &edges[nedges++];
                e->ax = vx[k]; e->ay = vy[k];
                e->bx = vx[k2]; e->by = vy[k2];
                e->lox = fmin(e->ax, e->bx);
                e->hix = fmax(e->ax, e->bx);
                e->loy = fmin(e->ay, e->by);
                e->hiy = fmax(e->ay, e->by);
            }
        }
    }

    out_lox = out_loy = 1e18;
    out_hix = out_hiy = -1e18;
    for (int k = 0; k < nedges; k++) {
        out_lox = fmin(out_lox, edges[k].lox);
        out_hix = fmax(out_hix, edges[k].hix);
        out_loy = fmin(out_loy, edges[k].loy);
        out_hiy = fmax(out_hiy, edges[k].hiy);
    }
    note("outline: %d edges\n", nedges);
}

// ----------------------------------------------------------------- points --

typedef struct {
    double x, y;
    long pop;
    long rec;  // input record index, for the assignment dump
} Pt;

static Pt *pts;
static long npts;
static long total_pop;

// Population model. Point mass puts all of a block's people on its centroid,
// which is what the 2007 original did and what bounds achievable equality at
// (largest block)/(district). Uniform spreads them over a disc of the same
// land area, subdividing a block into sub-points only when it is big enough
// relative to the quota to matter.
//
// Doing it at load time rather than splitting blocks at each cut is a
// deliberate trade: splitting during the recursion would need per-node point
// arrays instead of contiguous ranges, and fragment bookkeeping inside the
// hot loop, for the same effect on granularity. Here the cost is a slightly
// larger array, and only for the handful of blocks that are actually large.
static int opt_uniform = 0;
static double opt_subdiv = 1000.0;  // target sub-point weight = quota/this

// Metres per degree of latitude; the projection is in degrees, so this is how
// a block's land area becomes a radius the engine can use. It ignores the
// gnomonic scale factor, which varies by a few percent across a state.
#define M_PER_DEG 111320.0

static void add_point(long *cap, double x, double y, long pop, long rec) {
    if (npts >= *cap) {
        *cap *= 2;
        pts = realloc(pts, sizeof(Pt) * (*cap));
        if (!pts) die("out of memory growing points");
    }
    Pt *p = &pts[npts++];
    p->x = x;
    p->y = y;
    p->pop = pop;
    p->rec = rec;
}

static void load_points(const char *fname, int seats) {
    FILE *fp = fopen(fname, "r");
    if (!fp) die("cannot open population %s: %s", fname, strerror(errno));

    long cap = 1 << 16;
    pts = xmalloc(sizeof(Pt) * cap);
    npts = 0;
    total_pop = 0;

    // Two passes when spreading: the first totals the population so the
    // sub-point weight can be set from the quota.
    double thresh = 0;
    if (opt_uniform) {
        char b[8192];
        long t = 0;
        while (fgets(b, sizeof b, fp)) {
            int tr, bl, pp, cv; double lo, la;
            if (sscanf(b, "%d,%d,%d,%d,%lf,%lf", &tr, &bl, &pp, &cv, &lo, &la) >= 6
                && pp > 0)
                t += pp;
        }
        rewind(fp);
        thresh = (double)t / seats / opt_subdiv;
        if (thresh < 1) thresh = 1;
        note("uniform blocks: sub-point weight ~%.0f people\n", thresh);
    }

    char buf[8192];
    long rec = 0, nsub = 0, nsplit = 0, with_area = 0;
    while (fgets(buf, sizeof buf, fp)) {
        if (buf[0] == '#' || buf[0] == '\n') continue;
        int tract, block, popul, curve;
        double lon, lat;
        long area = 0;
        int got = sscanf(buf, "%d,%d,%d,%d,%lf,%lf,%ld", &tract, &block, &popul,
                         &curve, &lon, &lat, &area);
        if (got < 6) continue;
        rec++;
        if (popul <= 0) continue;  // empty blocks cannot move a cut
        total_pop += popul;

        double x, y;
        gnomonic(lon, lat, &x, &y);

        if (got >= 7 && area > 0) with_area++;

        int k = 1;
        if (opt_uniform && got >= 7 && area > 0 && popul > thresh)
            k = (int)ceil(popul / thresh);
        if (k <= 1) {
            add_point(&cap, x, y, popul, rec - 1);
            continue;
        }

        // Sunflower arrangement: radius as sqrt(i/k) spreads the sub-points
        // evenly by area rather than bunching them at the centre, and the
        // golden angle keeps them from lining up into spokes a cut could
        // slip between.
        double r = sqrt((double)area / M_PI) / M_PER_DEG;
        long each = popul / k, extra = popul % k;
        static const double GA = 2.39996322972865332;
        for (int i = 0; i < k; i++) {
            double rr = r * sqrt((i + 0.5) / k), th = i * GA;
            long p = each + (i < extra ? 1 : 0);
            if (p <= 0) continue;
            add_point(&cap, x + rr * cos(th), y + rr * sin(th), p, rec - 1);
        }
        nsub += k;
        nsplit++;
    }
    fclose(fp);
    if (!npts) die("no populated records in %s", fname);

    // Asking to spread blocks over an input with no area column would
    // silently fall back to point masses and quietly produce a different
    // model than the one requested, which is worse than failing.
    if (opt_uniform && with_area == 0)
        die("--uniform needs a 7th column of block land area, and %s has none; "
            "regenerate it with the current converters", fname);

    note("points: %ld from %ld records, %ld people", npts, rec, total_pop);
    if (nsplit) note(" (%ld blocks spread into %ld sub-points)", nsplit, nsub);
    note("\n");
}

// ------------------------------------------------------------------- tree --

// A cut is the line { p : p.n == c }, with the low side (p.n < c) taken as the
// left child. Storing the tree, rather than a raster, is what makes district
// geometry exact and lookup O(depth).
typedef struct {
    double nx, ny, c;  // cut line, internal nodes only
    int left, right;   // child node indices, -1 at a leaf
    int seats;
    long pop;
    long lo, hi;       // half-open range into pts[]
    int district;      // leaf id, -1 internal
} Node;

static Node *nodes;
static int nnodes, ncap;

static int new_node(long lo, long hi, int seats) {
    if (nnodes >= ncap) {
        ncap = ncap ? ncap * 2 : 256;
        nodes = realloc(nodes, sizeof(Node) * ncap);
        if (!nodes) die("out of memory growing tree");
    }
    Node *n = &nodes[nnodes];
    memset(n, 0, sizeof *n);
    n->left = n->right = -1;
    n->district = -1;
    n->lo = lo;
    n->hi = hi;
    n->seats = seats;
    n->pop = 0;
    for (long i = lo; i < hi; i++) n->pop += pts[i].pop;
    return nnodes++;
}

// ------------------------------------------------------- geometry of a cut --

// Half-planes constraining the region currently being split: p.mx,my <= k.
typedef struct { double mx, my, k; } Half;

// How long a candidate cut is -- the "shortest" in shortest splitline. There
// are two defensible definitions and they give visibly different maps, so both
// are available:
//
//   span  the distance from the first point of the region the cut enters to
//         the last one it leaves. Water in between still counts. This is what
//         the 2007 original measured (the distance between the extreme in-play
//         pixels on the cut) and is the plain reading of "shortest line".
//
//   land  the sum of only those parts of the cut that fall on land. Crossing a
//         lake or a bay is free.
//
// They diverge sharply wherever there is water to hop. On the 2000 nationwide
// map the first cut under `land` runs due north-south straight through Lake
// Michigan: 1,818 km end to end but only 1,355 km of land, so a quarter of its
// length costs nothing. Under `span` that discount disappears and the cut
// rotates to cross Michigan's lower peninsula instead.
//
// `span` is the default because it reproduces the reference maps and does not
// reward lake-hopping; `land` is kept because "how much boundary is actually
// drawn across inhabited ground" is a reasonable thing to minimise too, and
// comparing the two is interesting in its own right.
static int opt_span_metric = 1;
static double chord_length(double nx, double ny, double c, const Half *halves,
                           int nhalf, const int *elist, int nel,
                           double *sbuf) {
    double tx = -ny, ty = nx;

    int m = 0;
    for (int i = 0; i < nel; i++) {
        const Edge *e = &edges[elist[i]];
        double da = e->ax * nx + e->ay * ny - c;
        double db = e->bx * nx + e->by * ny - c;
        if ((da > 0 && db > 0) || (da < 0 && db < 0)) continue;
        if (da == db) continue;  // edge lies along the line; ignore
        double u = da / (da - db);
        double px = e->ax + u * (e->bx - e->ax);
        double py = e->ay + u * (e->by - e->ay);
        sbuf[m++] = px * tx + py * ty;
    }
    if (m < 2) return 0.0;

    // Insertion sort: m is the number of times a line crosses a coastline,
    // which is small even for the national outline.
    for (int i = 1; i < m; i++) {
        double v = sbuf[i];
        int j = i - 1;
        while (j >= 0 && sbuf[j] > v) { sbuf[j + 1] = sbuf[j]; j--; }
        sbuf[j + 1] = v;
    }

    double slo = -1e18, shi = 1e18;
    for (int h = 0; h < nhalf; h++) {
        double dn = tx * halves[h].mx + ty * halves[h].my;
        double base = c * (nx * halves[h].mx + ny * halves[h].my);
        double rhs = halves[h].k - base;
        if (fabs(dn) < 1e-15) {
            if (rhs < 0) return 0.0;  // line wholly outside this half-plane
        } else if (dn > 0) {
            shi = fmin(shi, rhs / dn);
        } else {
            slo = fmax(slo, rhs / dn);
        }
    }
    if (shi <= slo) return 0.0;

    double len = 0, lo = 1e18, hi = -1e18;
    for (int i = 0; i + 1 < m; i += 2) {
        double a = fmax(sbuf[i], slo);
        double b = fmin(sbuf[i + 1], shi);
        if (b > a) {
            len += b - a;
            if (a < lo) lo = a;
            if (b > hi) hi = b;
        }
    }
    if (opt_span_metric) return (hi > lo) ? hi - lo : 0.0;
    return len;
}

// ------------------------------------------------------------ split search --

// Comparator state for sorting the straddling bin by projected position.
// qsort rather than an insertion sort: at national scale a bin holds thousands
// of points and O(n^2) here would dominate the whole run.
static const double *sort_base;

static int cmp_by_t(const void *a, const void *b) {
    double ta = sort_base[*(const long *)a];
    double tb = sort_base[*(const long *)b];
    return (ta > tb) - (ta < tb);
}

// Offset at which the cumulative population reaches `target`, sweeping along
// direction n. Histogram first to localise, then exact within the one bin that
// straddles the target.
static double find_offset(long lo, long hi, double nx, double ny, long target,
                          double *tbuf, long *bins, long *idxbuf) {
    double mn = 1e18, mx = -1e18;
    for (long i = lo; i < hi; i++) {
        double t = pts[i].x * nx + pts[i].y * ny;
        tbuf[i - lo] = t;
        if (t < mn) mn = t;
        if (t > mx) mx = t;
    }
    if (mx <= mn) return mn;

    double scale = NBINS / (mx - mn);
    memset(bins, 0, sizeof(long) * NBINS);
    for (long i = lo; i < hi; i++) {
        int b = (int)((tbuf[i - lo] - mn) * scale);
        if (b < 0) b = 0;
        if (b >= NBINS) b = NBINS - 1;
        bins[b] += pts[i].pop;
    }

    long acc = 0;
    int hit = NBINS - 1;
    for (int b = 0; b < NBINS; b++) {
        if (acc + bins[b] >= target) { hit = b; break; }
        acc += bins[b];
    }

    // Exact pass over the straddling bin.
    long nb = 0;
    for (long i = lo; i < hi; i++) {
        int b = (int)((tbuf[i - lo] - mn) * scale);
        if (b < 0) b = 0;
        if (b >= NBINS) b = NBINS - 1;
        if (b == hit) idxbuf[nb++] = i;
    }
    sort_base = tbuf - lo;
    qsort(idxbuf, nb, sizeof(long), cmp_by_t);

    // Everything in a later bin sits at or above this, so it is a safe
    // separator when the target lands on the last point of the bin. Using the
    // region maximum here instead would fling the cut across the whole region.
    double bin_hi = mn + (double)(hit + 1) / scale;

    for (long i = 0; i < nb; i++) {
        acc += pts[idxbuf[i]].pop;
        if (acc >= target) {
            double t = tbuf[idxbuf[i] - lo];
            double next = (i + 1 < nb) ? tbuf[idxbuf[i + 1] - lo] : bin_hi;
            return (next > t) ? (t + next) / 2 : nextafter(t, HUGE_VAL);
        }
    }
    return bin_hi;
}

static long partition_points(long lo, long hi, double nx, double ny, double c) {
    long i = lo, j = hi - 1;
    while (i <= j) {
        double t = pts[i].x * nx + pts[i].y * ny;
        if (t < c) {
            i++;
        } else {
            Pt tmp = pts[i];
            pts[i] = pts[j];
            pts[j] = tmp;
            if (j == lo) break;
            j--;
        }
    }
    return i;
}

static int opt_angles = 360;

// Scratch, sized once to the largest region.
static double *tbuf;
static long *binbuf, *idxbuf;
static double *sbuf;

static void split_node(int ni, Half *halves, int nhalf, const int *elist, int nel,
                       int *next_district) {
    Node *n = &nodes[ni];
    if (n->seats <= 1) {
        n->district = (*next_district)++;
        return;
    }

    int d1 = n->seats / 2;
    int d2 = n->seats - d1;
    long target = (long)((double)n->pop * d1 / n->seats);
    if (target < 1) target = 1;

    double best_len = 1e18, best_nx = 1, best_ny = 0, best_c = 0;
    int found = 0;

    for (int a = 0; a < opt_angles; a++) {
        double th = 2 * M_PI * a / opt_angles;
        double nx = cos(th), ny = sin(th);
        double c = find_offset(n->lo, n->hi, nx, ny, target, tbuf, binbuf, idxbuf);
        double len = chord_length(nx, ny, c, halves, nhalf, elist, nel, sbuf);
        if (len <= 0) continue;
        if (!found || len < best_len) {
            found = 1;
            best_len = len;
            best_nx = nx;
            best_ny = ny;
            best_c = c;
        }
    }
    if (!found) die("no valid cut for node %d (%d seats, %ld people)", ni, n->seats, n->pop);

    long mid = partition_points(n->lo, n->hi, best_nx, best_ny, best_c);
    if (mid == n->lo || mid == n->hi)
        die("degenerate cut at node %d: all points on one side", ni);

    n->nx = best_nx;
    n->ny = best_ny;
    n->c = best_c;

    // new_node can realloc nodes[], so `n` must not be touched across it.
    long nlo = n->lo, nhi = n->hi;
    int li = new_node(nlo, mid, d1);
    int ri = new_node(mid, nhi, d2);
    nodes[ni].left = li;
    nodes[ni].right = ri;

    // Children must keep the FULL outline. chord_length decides inside/outside
    // by counting boundary crossings, so every edge has to be present for the
    // parity to hold; passing a child only the edges near it silently corrupts
    // the chord measurement. Restricting to the region is the job of the
    // half-planes, not of the edge list.
    if (nhalf + 1 >= MAXDEPTH) die("tree deeper than MAXDEPTH");

    halves[nhalf].mx = best_nx;
    halves[nhalf].my = best_ny;
    halves[nhalf].k = best_c;
    split_node(li, halves, nhalf + 1, elist, nel, next_district);

    halves[nhalf].mx = -best_nx;
    halves[nhalf].my = -best_ny;
    halves[nhalf].k = -best_c;
    split_node(ri, halves, nhalf + 1, elist, nel, next_district);
}

// ------------------------------------------------------------- numbering --
//
// District numbers have to come from somewhere, and "order the recursion
// happened to run in" is not a good answer: the search picks a cut normal
// anywhere in 0..360 degrees, so which child counted as "first" was
// effectively random, and the numbering carried no meaning.
//
// Canonicalise instead. Every cut line has two equivalent descriptions, n/c
// and -n/-c; pick one and swap the children to match. The lookup test
//
//     p.n < c  ->  left
//
// becomes, after negating both sides, p.n > c -> left, so swapping the
// children preserves the geometry exactly while fixing what "left" means.
//
// We want left to be the western side, with north as the tie-break only when
// the cut runs exactly east-west and so has no western side at all. Since
// p.n < c selects the side the normal points away from, that means normals
// point east (nx > 0); for a horizontal cut, where nx is zero, they point
// south (ny < 0) so that left is the northern side.
//
// West therefore dominates: a cut tilted a little anticlockwise from
// north-south keeps the west-and-south side as left, rather than flipping to
// north-and-east.
//
// The epsilon matters. A due east-west cut comes out of the angle sweep as
// cos(pi/2), which is 6e-17 rather than 0, so testing nx against exact zero
// would decide a horizontal cut on the sign of a rounding artifact.
//
// Numbering is then a depth-first walk taking the left child first, so
// district 1 is the one you reach by always heading west, and consecutive
// numbers are usually neighbours because the tree is a recursive spatial
// subdivision.
static void canonicalise_cuts(void) {
    const double EPS = 1e-9;
    for (int i = 0; i < nnodes; i++) {
        Node *n = &nodes[i];
        if (n->district >= 0) continue;
        int flip = (fabs(n->nx) > EPS) ? (n->nx < 0) : (n->ny > 0);
        if (flip) {
            n->nx = -n->nx;
            n->ny = -n->ny;
            n->c = -n->c;
            int t = n->left;
            n->left = n->right;
            n->right = t;
        }
    }
}

static void number_leaves(int i, int *next) {
    if (nodes[i].district >= 0) {
        nodes[i].district = (*next)++;
        return;
    }
    number_leaves(nodes[i].left, next);
    number_leaves(nodes[i].right, next);
}

// ------------------------------------------------------- reading a tree back --
//
// Rendering is a pure function of the tree, so it does not need the search.
// Loading a previously computed tree lets colours, lighting and framing be
// changed in seconds instead of re-running the districting for hours, and it
// is what makes the animation possible: truncate the tree to N cuts and draw.
//
// The parser is deliberately dumb. write_tree() emits exactly one node per
// line, so scanning for the known keys line by line is enough; this is not a
// general JSON reader and is not meant to be.
static void load_tree(const char *fname) {
    FILE *fp = fopen(fname, "r");
    if (!fp) die("cannot open tree %s: %s", fname, strerror(errno));

    char line[4096];
    int cap = 256;
    nodes = xmalloc(sizeof(Node) * cap);
    nnodes = 0;
    double jlon0 = 0, jlat0 = 0, jshift = 0;
    int got_proj = 0;

    while (fgets(line, sizeof line, fp)) {
        if (!got_proj && strstr(line, "\"projection\"")) {
            const char *a = strstr(line, "\"lon0\"");
            const char *b = strstr(line, "\"lat0\"");
            const char *c = strstr(line, "\"lon_shift\"");
            if (a && b && c &&
                sscanf(a, "\"lon0\": %lf", &jlon0) == 1 &&
                sscanf(b, "\"lat0\": %lf", &jlat0) == 1 &&
                sscanf(c, "\"lon_shift\": %lf", &jshift) == 1)
                got_proj = 1;
            continue;
        }
        const char *ip = strstr(line, "\"i\":");
        if (!ip) continue;

        int i;
        if (sscanf(ip, "\"i\": %d", &i) != 1) continue;
        while (i >= cap) {
            cap *= 2;
            nodes = realloc(nodes, sizeof(Node) * cap);
            if (!nodes) die("out of memory growing tree");
        }
        Node *n = &nodes[i];
        memset(n, 0, sizeof *n);
        n->left = n->right = -1;
        n->district = -1;

        const char *q;
        if ((q = strstr(line, "\"pop\":"))) sscanf(q, "\"pop\": %ld", &n->pop);
        if ((q = strstr(line, "\"seats\":"))) sscanf(q, "\"seats\": %d", &n->seats);
        if ((q = strstr(line, "\"district\":"))) {
            sscanf(q, "\"district\": %d", &n->district);
        } else {
            if ((q = strstr(line, "\"nx\":"))) sscanf(q, "\"nx\": %lf", &n->nx);
            if ((q = strstr(line, "\"ny\":"))) sscanf(q, "\"ny\": %lf", &n->ny);
            if ((q = strstr(line, "\"c\":"))) sscanf(q, "\"c\": %lf", &n->c);
            if ((q = strstr(line, "\"left\":"))) sscanf(q, "\"left\": %d", &n->left);
            if ((q = strstr(line, "\"right\":"))) sscanf(q, "\"right\": %d", &n->right);
        }
        if (i + 1 > nnodes) nnodes = i + 1;
    }
    fclose(fp);
    if (!nnodes) die("tree %s had no nodes", fname);
    if (!got_proj) die("tree %s had no projection block", fname);

    // The outline decides the projection; the tree must agree or the cuts
    // would be drawn in a different coordinate system than the coastline.
    if (fabs(jlon0 - la0) > 1e-6 || fabs(jlat0 - ph1) > 1e-6 ||
        fabs(jshift - xoff) > 1e-6)
        die("tree projection (%.6f, %.6f, shift %.0f) does not match the "
            "boundary's (%.6f, %.6f, shift %.0f) -- wrong boundary file?",
            jlon0, jlat0, jshift, la0, ph1, xoff);
    note("tree: %d nodes loaded\n", nnodes);
}

// A region's stable name: the district number of its leftmost leaf. It does
// not change when the region is later split -- the left part keeps it and only
// the right part takes a new one -- so a district holds the same identity, and
// therefore the same colour, from the frame it appears in to the end.
//
// Numbering frontier regions from 1 instead is what broke the first attempt:
// the new numbers collided with the untouched leaves' own numbers, so two
// unrelated regions rendered as one and districts appeared to vanish.
static int leftmost_district(int i) {
    while (nodes[i].district < 0) i = nodes[i].left;
    return nodes[i].district;
}

// Truncate to the first `keep` cuts in depth-first, left-first order -- the
// same order the districts are numbered in, so the animation advances west to
// east. A region that is already a single district is finished and is never
// touched again.
static void truncate_tree(int keep) {
    int *stack = xmalloc(sizeof(int) * (nnodes + 4));
    int sp = 0, used = 0;
    stack[sp++] = 0;
    while (sp) {
        int i = stack[--sp];
        if (nodes[i].district >= 0) continue;   // already a finished district
        if (used >= keep) {
            nodes[i].district = leftmost_district(i);
            nodes[i].left = nodes[i].right = -1;
            continue;
        }
        used++;
        stack[sp++] = nodes[i].right;   // left pops first
        stack[sp++] = nodes[i].left;
    }
    free(stack);
    note("truncated to %d of the tree's cuts\n", used);
}

// ------------------------------------------------------------------ lookup --

static int district_at(double x, double y) {
    int i = 0;
    while (nodes[i].district < 0) {
        double t = x * nodes[i].nx + y * nodes[i].ny;
        i = (t < nodes[i].c) ? nodes[i].left : nodes[i].right;
    }
    return nodes[i].district;
}

// ------------------------------------------------------------------ output --

static void write_tree(const char *fname, int seats) {
    FILE *fp = fopen(fname, "w");
    if (!fp) die("cannot write %s: %s", fname, strerror(errno));
    fprintf(fp, "{\n");
    fprintf(fp, "  \"projection\": {\"type\": \"gnomonic\", \"lon0\": %.10f, "
                "\"lat0\": %.10f, \"lon_shift\": %.1f},\n", la0, ph1, xoff);
    fprintf(fp, "  \"seats\": %d,\n  \"population\": %ld,\n", seats, total_pop);
    fprintf(fp, "  \"note\": \"A point (x,y) in projected degrees is in district "
                "d by walking from node 0: go left when x*nx + y*ny < c, else "
                "right, until a node has a district.\",\n");
    fprintf(fp, "  \"numbering\": \"Districts are numbered from 1 by a "
                "depth-first walk of this tree, left child first. Every cut "
                "normal is canonicalised to point north (east for a due "
                "north-south cut), so the left child is always the southern or "
                "western side. District 1 is therefore the one reached by "
                "always heading south/west, and consecutive numbers are "
                "usually neighbours, because the tree is a recursive spatial "
                "subdivision. Numbers are not stable across censuses: a shift "
                "in population changes the cuts, and the numbering with "
                "them.\",\n");
    fprintf(fp, "  \"nodes\": [\n");
    for (int i = 0; i < nnodes; i++) {
        Node *n = &nodes[i];
        fprintf(fp, "    {\"i\": %d, \"pop\": %ld, \"seats\": %d", i, n->pop, n->seats);
        if (n->district >= 0) {
            fprintf(fp, ", \"district\": %d}", n->district);
        } else {
            fprintf(fp, ", \"nx\": %.12g, \"ny\": %.12g, \"c\": %.12g, "
                        "\"left\": %d, \"right\": %d}", n->nx, n->ny, n->c,
                    n->left, n->right);
        }
        fprintf(fp, "%s\n", i + 1 < nnodes ? "," : "");
    }
    fprintf(fp, "  ]\n}\n");
    fclose(fp);
    note("wrote %s (%d nodes)\n", fname, nnodes);
}

static void write_assignment(const char *popfile, const char *outfile) {
    FILE *fp = fopen(popfile, "r");
    if (!fp) die("cannot reopen %s: %s", popfile, strerror(errno));
    FILE *op = fopen(outfile, "w");
    if (!op) die("cannot write %s: %s", outfile, strerror(errno));

    fprintf(op, "tract,block,pop,district\n");
    char buf[8192];
    while (fgets(buf, sizeof buf, fp)) {
        if (buf[0] == '#' || buf[0] == '\n') continue;
        int tract, block, popul, curve;
        double lon, lat, x, y;
        if (sscanf(buf, "%d,%d,%d,%d,%lf,%lf", &tract, &block, &popul, &curve,
                   &lon, &lat) < 6)
            continue;
        gnomonic(lon, lat, &x, &y);
        fprintf(op, "%06d,%d,%d,%d\n", tract, block, popul, district_at(x, y));
    }
    fclose(fp);
    fclose(op);
    note("wrote %s\n", outfile);
}

// Minimal PNG writer (truecolour, zlib via compress2).
static void write_png(const char *fname, unsigned char *rgb, int w, int h) {
    unsigned char *raw = xmalloc((size_t)h * (w * 3 + 1));
    for (int y = 0; y < h; y++) {
        raw[(size_t)y * (w * 3 + 1)] = 0;  // filter: none
        // PNG is top-down; our y axis points up.
        memcpy(raw + (size_t)y * (w * 3 + 1) + 1,
               rgb + (size_t)(h - 1 - y) * w * 3, (size_t)w * 3);
    }
    uLongf zcap = compressBound((uLong)h * (w * 3 + 1));
    unsigned char *z = xmalloc(zcap);
    if (compress2(z, &zcap, raw, (uLong)h * (w * 3 + 1), 9) != Z_OK)
        die("zlib compression failed");

    FILE *fp = fopen(fname, "wb");
    if (!fp) die("cannot write %s: %s", fname, strerror(errno));

    static const unsigned char sig[8] = {137, 80, 78, 71, 13, 10, 26, 10};
    fwrite(sig, 1, 8, fp);

    void put_chunk(const char *tag, const unsigned char *data, size_t len) {
        unsigned char be[4] = {(len >> 24) & 255, (len >> 16) & 255,
                               (len >> 8) & 255, len & 255};
        fwrite(be, 1, 4, fp);
        uLong crc = crc32(0, (const Bytef *)tag, 4);
        if (len) crc = crc32(crc, data, len);
        fwrite(tag, 1, 4, fp);
        if (len) fwrite(data, 1, len, fp);
        unsigned char cb[4] = {(crc >> 24) & 255, (crc >> 16) & 255,
                               (crc >> 8) & 255, crc & 255};
        fwrite(cb, 1, 4, fp);
    }

    unsigned char ihdr[13] = {
        (w >> 24) & 255, (w >> 16) & 255, (w >> 8) & 255, w & 255,
        (h >> 24) & 255, (h >> 16) & 255, (h >> 8) & 255, h & 255,
        8, 2, 0, 0, 0};
    put_chunk("IHDR", ihdr, 13);
    put_chunk("IDAT", z, zcap);
    put_chunk("IEND", NULL, 0);
    fclose(fp);
    free(raw);
    free(z);
    note("wrote %s (%dx%d)\n", fname, w, h);
}

// ---------------------------------------------------------------- palette --
//
// The four hue families from the original rangevoting.org maps, as channel
// masks. Value carries population density: darkest where nobody lives, full
// brightness in the densest blocks, which is what gives those maps their dark
// ground and bright city speckle.
static const int PALETTE[4][3] = {
    {0, 1, 1},  // teal
    {0, 1, 0},  // green
    {1, 0, 1},  // purple
    {1, 1, 0},  // olive
};
#define PAL_MIN 64  // shade of uninhabited land

// Adjacency of districts, from the rendered district raster.
static unsigned char *build_adjacency(const int *dpix, int w, int h, int n) {
    unsigned char *adj = xcalloc((size_t)n * n, 1);
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            int a = dpix[(size_t)y * w + x];
            if (a < 0) continue;
            if (x + 1 < w) {
                int b = dpix[(size_t)y * w + x + 1];
                if (b >= 0 && b != a) {
                    adj[(size_t)a * n + b] = 1;
                    adj[(size_t)b * n + a] = 1;
                }
            }
            if (y + 1 < h) {
                int b = dpix[(size_t)(y + 1) * w + x];
                if (b >= 0 && b != a) {
                    adj[(size_t)a * n + b] = 1;
                    adj[(size_t)b * n + a] = 1;
                }
            }
        }
    }
    return adj;
}

// DSATUR order with backtracking. A map of contiguous regions is a planar
// graph so four colours always suffice, but greedy assignment will not find
// such a colouring on its own -- hence the search. Splitline districts can be
// disconnected (Hawaii spans islands), which breaks planarity, so this widens
// the palette rather than failing if four genuinely will not do.
static int colour_search(const unsigned char *adj, int n, int *colour,
                         int ncolours, int placed, long *budget) {
    if (placed == n) return 1;
    if ((*budget)-- <= 0) return 0;

    // Pick the uncoloured vertex with the fewest remaining options.
    int best = -1, best_avail = ncolours + 1;
    for (int v = 0; v < n; v++) {
        if (colour[v] >= 0) continue;
        int used[8] = {0};
        int avail = 0;
        for (int u = 0; u < n; u++)
            if (adj[(size_t)v * n + u] && colour[u] >= 0) used[colour[u]] = 1;
        for (int c = 0; c < ncolours; c++) if (!used[c]) avail++;
        if (avail < best_avail) { best_avail = avail; best = v; }
        if (avail == 0) return 0;
    }
    if (best < 0) return 1;

    for (int c = 0; c < ncolours; c++) {
        int ok = 1;
        for (int u = 0; u < n; u++)
            if (adj[(size_t)best * n + u] && colour[u] == c) { ok = 0; break; }
        if (!ok) continue;
        colour[best] = c;
        if (colour_search(adj, n, colour, ncolours, placed + 1, budget)) return 1;
        colour[best] = -1;
    }
    return 0;
}

// A colouring computed once from the complete tree and reused for every frame.
//
// Colouring each frame on its own is valid but unstable: as regions split the
// adjacency graph changes and the search reassigns colours, so a district that
// has not moved appears to change colour when a neighbour arrives. Since a
// region is named by its leftmost leaf, and that leaf has one colour in the
// full map, inheriting it keeps a district the same colour from the frame it
// appears in to the last.
static int *g_colour = NULL;
static int g_ncolour = 0;

static void colour_graph(unsigned char *adj, int n, int *colour) {
    for (int k = 4; k <= 12; k++) {
        for (int i = 0; i < n; i++) colour[i] = -1;
        long budget = 2000000;
        if (colour_search(adj, n, colour, k, 0, &budget)) {
            if (k > 4) note("four colours were not enough; used %d\n", k);
            return;
        }
    }
    note("colouring search exhausted; falling back to round-robin\n");
    for (int i = 0; i < n; i++) colour[i] = i & 3;
}

static void four_colour(const int *dpix, int w, int h, int n, int *colour) {
    if (n <= 0) return;
    unsigned char *adj = build_adjacency(dpix, w, h, n);
    colour_graph(adj, n, colour);
    free(adj);
}

// Where the first cut leaves the state, as the extreme crossings of the
// outline along that line. Used to mark it on the render.
static int cut_extremes(double nx, double ny, double c, double *smin, double *smax) {
    double tx = -ny, ty = nx;
    int found = 0;
    double lo = 0, hi = 0;
    for (int i = 0; i < nedges; i++) {
        const Edge *e = &edges[i];
        double da = e->ax * nx + e->ay * ny - c;
        double db = e->bx * nx + e->by * ny - c;
        if ((da > 0 && db > 0) || (da < 0 && db < 0)) continue;
        if (da == db) continue;
        double u = da / (da - db);
        double ix = e->ax + u * (e->bx - e->ax);
        double iy = e->ay + u * (e->by - e->ay);
        double s = ix * tx + iy * ty;
        if (!found) { lo = hi = s; found = 1; }
        else { if (s < lo) lo = s; if (s > hi) hi = s; }
    }
    *smin = lo;
    *smax = hi;
    return found;
}

static void plot(unsigned char *rgb, int w, int h, int x, int y, int r, int g, int b) {
    if (x < 0 || x >= w || y < 0 || y >= h) return;
    size_t i = ((size_t)y * w + x) * 3;
    rgb[i] = r; rgb[i + 1] = g; rgb[i + 2] = b;
}

static void thick_line(unsigned char *rgb, int w, int h, double x0, double y0,
                       double x1, double y1, int thick, int r, int g, int b) {
    double dx = x1 - x0, dy = y1 - y0;
    int steps = (int)(fmax(fabs(dx), fabs(dy)) + 1);
    for (int s = 0; s <= steps; s++) {
        double t = (double)s / steps;
        int px = (int)(x0 + dx * t), py = (int)(y0 + dy * t);
        for (int oy = -thick; oy <= thick; oy++)
            for (int ox = -thick; ox <= thick; ox++)
                plot(rgb, w, h, px + ox, py + oy, r, g, b);
    }
}

// A chevron sitting just outside the outline, pointing back along the cut into
// the state, so the first split is findable at a glance.
static void chevron(unsigned char *rgb, int w, int h, double tipx, double tipy,
                    double ox, double oy, double size, int thick) {
    double px = -oy, py = ox;  // perpendicular
    double ax = tipx + ox * size * 0.6;
    double ay = tipy + oy * size * 0.6;
    double b1x = ax + ox * size + px * size;
    double b1y = ay + oy * size + py * size;
    double b2x = ax + ox * size - px * size;
    double b2y = ay + oy * size - py * size;
    thick_line(rgb, w, h, ax, ay, b1x, b1y, thick, 255, 255, 255);
    thick_line(rgb, w, h, ax, ay, b2x, b2y, thick, 255, 255, 255);
}

// Render by asking the tree which district each land pixel belongs to. The
// picture is a view of the tree, so resolution is a free parameter.
// Rasterise the untruncated tree once and colour that, so every frame can
// inherit a district's colour instead of recomputing one.
static void precompute_colours(double gain) {
    const int margin = 20;
    int w = (int)((out_hix - out_lox) * gain) + 2 * margin + 1;
    int h = (int)((out_hiy - out_loy) * gain) + 2 * margin + 1;

    int *dpix = xmalloc(sizeof(int) * (size_t)w * h);
    int ndist = 0;
    for (int py = 0; py < h; py++) {
        for (int px = 0; px < w; px++) {
            double wx = (px + 0.5 - margin) / gain + out_lox;
            double wy = (py + 0.5 - margin) / gain + out_loy;
            int d = district_at(wx, wy);
            dpix[(size_t)py * w + px] = d;
            if (d + 1 > ndist) ndist = d + 1;
        }
    }
    unsigned char *adj = build_adjacency(dpix, w, h, ndist);
    free(dpix);

    // Colouring the final map is not enough for an animation. A region shows
    // its leftmost leaf's colour, so when a region splits, the two halves take
    // the colours of leftmost(left) and leftmost(right) -- and those two
    // districts need not be adjacent in the finished map, so nothing stops
    // them sharing a colour and the cut being invisible. Add an edge for every
    // cut to forbid exactly that.
    int extra = 0;
    for (int i = 0; i < nnodes; i++) {
        if (nodes[i].district >= 0) continue;
        int a = leftmost_district(nodes[i].left);
        int b = leftmost_district(nodes[i].right);
        if (a >= 0 && b >= 0 && a < ndist && b < ndist && a != b) {
            if (!adj[(size_t)a * ndist + b]) extra++;
            adj[(size_t)a * ndist + b] = 1;
            adj[(size_t)b * ndist + a] = 1;
        }
    }

    g_colour = xcalloc(ndist ? ndist : 1, sizeof(int));
    g_ncolour = ndist;
    colour_graph(adj, ndist, g_colour);
    free(adj);
    note("palette fixed from the full tree (%d districts, %d split "
         "constraints added)\n", ndist - 1, extra);
}

static void render(const char *fname, double gain, int mark_first_cut) {
    double span_x = (out_hix - out_lox) * gain;
    double span_y = (out_hiy - out_loy) * gain;

    // The chevrons sit outside the outline, so the margin has to be wide
    // enough to hold one or they get clipped by the canvas edge.
    double chev = fmax(10.0, span_x / 45.0);
    int margin = mark_first_cut ? (int)(chev * 1.9) + 10 : 20;

    int w = (int)span_x + 2 * margin + 1;
    int h = (int)span_y + 2 * margin + 1;
    if (w < 8 || h < 8) die("render size too small");
    note("render %dx%d at %.0f px/degree\n", w, h, gain);

    unsigned char *rgb = xcalloc((size_t)w * h, 3);
    unsigned char *land = xcalloc((size_t)w * h, 1);

    // Even-odd scanline fill of the outline into the land mask.
    double *xs = xmalloc(sizeof(double) * (nedges + 4));
    for (int py = 0; py < h; py++) {
        double wy = (py + 0.5 - margin) / gain + out_loy;
        int m = 0;
        for (int i = 0; i < nedges; i++) {
            Edge *e = &edges[i];
            if ((e->ay <= wy && e->by > wy) || (e->by <= wy && e->ay > wy)) {
                double u = (wy - e->ay) / (e->by - e->ay);
                xs[m++] = e->ax + u * (e->bx - e->ax);
            }
        }
        for (int i = 1; i < m; i++) {
            double v = xs[i];
            int j = i - 1;
            while (j >= 0 && xs[j] > v) { xs[j + 1] = xs[j]; j--; }
            xs[j + 1] = v;
        }
        for (int i = 0; i + 1 < m; i += 2) {
            int x0 = (int)((xs[i] - out_lox) * gain) + margin;
            int x1 = (int)((xs[i + 1] - out_lox) * gain) + margin;
            if (x1 < 0 || x0 >= w) continue;
            if (x0 < 0) x0 = 0;
            if (x1 >= w) x1 = w - 1;
            for (int x = x0; x <= x1; x++) land[(size_t)py * w + x] = 1;
        }
    }
    free(xs);

    // District index per pixel, resolved once; the colouring needs adjacency
    // before it can pick colours, so it cannot be done in a single pass.
    int *dpix = xmalloc(sizeof(int) * (size_t)w * h);
    for (int py = 0; py < h; py++) {
        for (int px = 0; px < w; px++) {
            size_t i = (size_t)py * w + px;
            if (!land[i]) { dpix[i] = -1; continue; }
            double wx = (px + 0.5 - margin) / gain + out_lox;
            double wy = (py + 0.5 - margin) / gain + out_loy;
            dpix[i] = district_at(wx, wy);
        }
    }

    int ndist = 0;
    for (size_t i = 0; i < (size_t)w * h; i++)
        if (dpix[i] + 1 > ndist) ndist = dpix[i] + 1;

    int *colour = xmalloc(sizeof(int) * (ndist ? ndist : 1));
    if (g_colour && g_ncolour >= ndist) {
        for (int i = 0; i < ndist; i++) colour[i] = g_colour[i];
    } else {
        four_colour(dpix, w, h, ndist, colour);
    }

    // Population brightness. The search works on points, not a raster, so the
    // density channel is built here purely for drawing.
    long *ppix = xcalloc((size_t)w * h, sizeof(long));
    long peak = 0;
    for (long k = 0; k < npts; k++) {
        int px = (int)((pts[k].x - out_lox) * gain) + margin;
        int py = (int)((pts[k].y - out_loy) * gain) + margin;
        if (px < 0 || px >= w || py < 0 || py >= h) continue;
        size_t i = (size_t)py * w + px;
        ppix[i] += pts[k].pop;
        if (ppix[i] > peak) peak = ppix[i];
    }
    if (peak < 1) peak = 1;

    for (size_t i = 0; i < (size_t)w * h; i++) {
        int d = dpix[i];
        if (d < 0) continue;
        // Empty land sits at the darkest shade; density drives it to full.
        double f = ppix[i] > 0 ? log1p((double)ppix[i]) / log1p((double)peak) : 0.0;
        int v = (int)(PAL_MIN + (255 - PAL_MIN) * f);
        if (v > 255) v = 255;
        const int *m = PALETTE[colour[d] & 3];
        rgb[i * 3 + 0] = (unsigned char)(v * m[0]);
        rgb[i * 3 + 1] = (unsigned char)(v * m[1]);
        rgb[i * 3 + 2] = (unsigned char)(v * m[2]);
    }
    free(ppix);
    free(colour);
    free(dpix);

    // Outline the districts by marking pixels whose right/up neighbour differs.
    for (int py = 0; py + 1 < h; py++) {
        for (int px = 0; px + 1 < w; px++) {
            size_t i = (size_t)py * w + px;
            if (!land[i]) continue;
            double wx = (px + 0.5 - margin) / gain + out_lox;
            double wy = (py + 0.5 - margin) / gain + out_loy;
            int d = district_at(wx, wy);
            int dr = district_at(wx + 1.0 / gain, wy);
            int du = district_at(wx, wy + 1.0 / gain);
            if (d != dr || d != du) {
                rgb[i * 3 + 0] = 40;
                rgb[i * 3 + 1] = 40;
                rgb[i * 3 + 2] = 40;
            }
        }
    }

    if (mark_first_cut && nnodes > 0 && nodes[0].district < 0) {
        double nx = nodes[0].nx, ny = nodes[0].ny, c = nodes[0].c;
        double tx = -ny, ty = nx;
        double smin, smax;
        if (cut_extremes(nx, ny, c, &smin, &smax)) {
            double size = chev;
            int thick = (int)fmax(1.0, w / 900.0);
            // Two tips: the cut leaves the outline at each extreme crossing.
            double hix = c * nx + smax * tx, hiy = c * ny + smax * ty;
            double lox = c * nx + smin * tx, loy = c * ny + smin * ty;
            chevron(rgb, w, h,
                    (hix - out_lox) * gain + margin, (hiy - out_loy) * gain + margin,
                    tx, ty, size, thick);
            chevron(rgb, w, h,
                    (lox - out_lox) * gain + margin, (loy - out_loy) * gain + margin,
                    -tx, -ty, size, thick);
            note("first cut marked at (%.4f, %.4f) and (%.4f, %.4f) projected\n",
                 lox, loy, hix, hiy);
        }
    }

    write_png(fname, rgb, w, h);
    free(rgb);
    free(land);
}

// -------------------------------------------------------------------- main --

static void usage(void) {
    fprintf(stderr,
            "usage: splitline --boundary FILE --pop FILE --seats N [options]\n"
            "\n"
            "  --boundary FILE  outline in ARC/INFO ungenerate format\n"
            "  --pop FILE       points: tract,block,pop,curve,lon,lat\n"
            "  --seats N        number of districts\n"
            "  --tree FILE      write the cut tree as JSON (the real output)\n"
            "  --assign FILE    write per-record district assignment CSV\n"
            "  --png FILE       render a picture from the tree\n"
            "  --gain N         render resolution, px/degree (default 100)\n"
            "  --width N        force image width in pixels, overriding --gain\n"
            "  --no-chevrons    do not mark where the first cut leaves the state\n"
            "  --render-only F  draw a previously computed tree instead of\n"
            "                   searching; needs --boundary, --pop and --png\n"
            "  --anim PREFIX    with --render-only, write every frame of the\n"
            "                   animation as PREFIX_cutN.png in one pass, so\n"
            "                   the palette is computed once instead of per frame\n"
            "  --cuts N         with --render-only, draw only the first N cuts\n"
            "                   in depth-first order (one animation frame)\n"
            "  --cut-metric M   how cut length is measured: span (default,\n"
            "                   end to end, water counted) or land (only the\n"
            "                   parts crossing land)\n"
            "  --uniform        spread each block over an equal-area disc\n"
            "                   instead of piling it on the centroid\n"
            "  --subdiv N       sub-point weight = quota/N (default 1000)\n"
            "  --angles N       candidate directions per cut (default 360)\n"
            "  --quiet\n");
    exit(2);
}

int main(int argc, char **argv) {
    const char *bnd = NULL, *popf = NULL, *treef = NULL, *assignf = NULL, *pngf = NULL;
    int seats = 0;
    double gain = 100;
    int opt_pxwidth = 0;
    int mark_first_cut = 1;
    const char *opt_render_only = NULL;
    const char *opt_anim = NULL;
    int opt_cuts = -1;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--boundary") && i + 1 < argc) bnd = argv[++i];
        else if (!strcmp(argv[i], "--pop") && i + 1 < argc) popf = argv[++i];
        else if (!strcmp(argv[i], "--tree") && i + 1 < argc) treef = argv[++i];
        else if (!strcmp(argv[i], "--assign") && i + 1 < argc) assignf = argv[++i];
        else if (!strcmp(argv[i], "--png") && i + 1 < argc) pngf = argv[++i];
        else if (!strcmp(argv[i], "--seats") && i + 1 < argc) seats = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--gain") && i + 1 < argc) gain = atof(argv[++i]);
        else if (!strcmp(argv[i], "--width") && i + 1 < argc) opt_pxwidth = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--no-chevrons")) mark_first_cut = 0;
        else if (!strcmp(argv[i], "--render-only") && i + 1 < argc) opt_render_only = argv[++i];
        else if (!strcmp(argv[i], "--cuts") && i + 1 < argc) opt_cuts = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--anim") && i + 1 < argc) opt_anim = argv[++i];
        else if (!strcmp(argv[i], "--uniform")) opt_uniform = 1;
        else if (!strcmp(argv[i], "--cut-metric") && i + 1 < argc) {
            const char *m = argv[++i];
            if (!strcmp(m, "span")) opt_span_metric = 1;
            else if (!strcmp(m, "land")) opt_span_metric = 0;
            else die("--cut-metric must be span or land, not %s", m);
        }
        else if (!strcmp(argv[i], "--subdiv") && i + 1 < argc) opt_subdiv = atof(argv[++i]);
        else if (!strcmp(argv[i], "--angles") && i + 1 < argc) opt_angles = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--quiet")) opt_quiet = 1;
        else usage();
    }
    if (!bnd || !popf) usage();
    if (!opt_render_only && seats < 1) usage();
    if (opt_angles < 4) die("--angles must be at least 4");

    load_outline(bnd);
    project_outline();

    if (opt_render_only) {
        // No search: the tree already exists, we are only drawing it.
        load_tree(opt_render_only);
        seats = nodes[0].seats;
        load_points(popf, seats > 0 ? seats : 1);
        if (!pngf && !opt_anim) die("--render-only needs --png or --anim");
        double span = out_hix - out_lox;
        if (opt_pxwidth > 0) {
            gain = (opt_pxwidth - 41) / span;
        } else {
            double want = fmax(1400.0, 120.0 * sqrt((double)seats));
            if (span * gain + 41 < want) gain = (want - 41) / span;
        }
        if (seats <= 2) mark_first_cut = 0;

        if (opt_anim) {
            // Every frame comes from the same tree, so the palette is fixed
            // once and the tree is restored between frames -- truncation is
            // destructive and cannot be undone in place.
            precompute_colours(gain);
            int ncuts = 0;
            for (int i = 0; i < nnodes; i++)
                if (nodes[i].district < 0) ncuts++;

            Node *pristine = xmalloc(sizeof(Node) * nnodes);
            memcpy(pristine, nodes, sizeof(Node) * nnodes);

            char fname[4096];
            for (int f = 0; f <= ncuts; f++) {
                memcpy(nodes, pristine, sizeof(Node) * nnodes);
                truncate_tree(f);
                snprintf(fname, sizeof fname, "%s_cut%d.png", opt_anim, f);
                render(fname, gain, mark_first_cut);
            }
            free(pristine);
            return 0;
        }

        // Colour from the whole tree first, then cut it back: a district must
        // keep its colour across every frame of an animation.
        if (opt_cuts >= 0) {
            precompute_colours(gain);
            truncate_tree(opt_cuts);
        }
        render(pngf, gain, mark_first_cut);
        return 0;
    }

    load_points(popf, seats);

    tbuf = xmalloc(sizeof(double) * npts);
    binbuf = xmalloc(sizeof(long) * NBINS);
    idxbuf = xmalloc(sizeof(long) * npts);
    sbuf = xmalloc(sizeof(double) * (nedges + 4));

    int *elist = xmalloc(sizeof(int) * nedges);
    for (int i = 0; i < nedges; i++) elist[i] = i;

    nodes = NULL;
    nnodes = ncap = 0;
    int root = new_node(0, npts, seats);
    (void)root;

    Half halves[MAXDEPTH];
    int next_district = 0;
    split_node(0, halves, 0, elist, nedges, &next_district);

    // Replace the recursion-order numbering with the documented one.
    canonicalise_cuts();
    int renum = 1;  // districts are 1-based, as real ones are
    number_leaves(0, &renum);
    free(elist);

    note("districts: %d\n", next_district);

    long lo = -1, hi = -1;
    for (int i = 0; i < nnodes; i++) {
        if (nodes[i].district < 0) continue;
        long p = nodes[i].pop;
        if (lo < 0 || p < lo) lo = p;
        if (hi < 0 || p > hi) hi = p;
    }
    note("population per district: min %ld max %ld spread %.4f%%\n", lo, hi,
         lo > 0 ? 100.0 * (hi - lo) / lo : 0.0);

    if (treef) write_tree(treef, seats);
    if (assignf) write_assignment(popf, assignf);

    if (pngf) {
        // Resolution should follow how much detail is in the map, not how far
        // the state sprawls. Otherwise Hawaii gets a huge canvas for spanning
        // an ocean while New Hampshire, 1.7 degrees wide with 400 districts,
        // comes out as a postage stamp.
        // With two districts there is exactly one cut, so pointing at it tells
        // the reader nothing they cannot already see.
        if (seats <= 2) mark_first_cut = 0;

        double span = out_hix - out_lox;
        if (opt_pxwidth > 0) {
            gain = (opt_pxwidth - 41) / span;
        } else {
            double want = fmax(1400.0, 120.0 * sqrt((double)seats));
            if (span * gain + 41 < want) gain = (want - 41) / span;
        }
        render(pngf, gain, mark_first_cut);
    }
    return 0;
}
