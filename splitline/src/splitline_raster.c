//
// splitline - shortest splitline districting
//
// Derived from autodistrict (bmp_version) by Ivan Ryan, 2007:
//   https://sourceforge.net/projects/autodistrict/
// Original code Copyright 2007 Ivan Ryan, Apache License 2.0.
// Modifications 2026: portable POSIX build, headless rendering, per-district
// bounding boxes, runtime district cap, national-scale memory limits.
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
// See the License for the specific language governing permissions
// and limitations under the License.
//
// The districting algorithm (splitdist/splitquad/findlargedist) is a faithful
// port of the original: same quadrant sweep, same slope search, same choice of
// "shortest" cut. What changed is everything around it -- see PORTING.md.
//

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <errno.h>

#define MINV(x, y) (((x) < (y)) ? (x) : (y))
#define MAXV(x, y) (((x) > (y)) ? (x) : (y))
#define ABSV(x) (((x) < 0) ? (-(x)) : (x))

// ---------------------------------------------------------------- geometry --

// Boundary outline, in the ARC/INFO "ungenerate" format the Census
// cartographic boundary files used to ship in. pa[] tags each vertex:
//   > 0       first vertex of a new polygon (the value is the polygon id)
//   -99999    first vertex of a hole ring inside the current polygon
//   0         an ordinary vertex
//   -1        end of data
static int *pa;
static double *px;
static double *py;
static int pnum;  // number of vertices actually loaded

// Edge list for the polygon currently being scan-converted.
static int *pxst, *pyst, *pxen, *pyen;
static int pcnt;
static int pmax;  // capacity of the edge arrays

static int winx = 950;
static int winy = 725;

static double la0 = 0, ph1 = 0;  // gnomonic projection centre

// ------------------------------------------------------------------ raster --

static unsigned char *frame;  // RGB, 3 bytes/pixel, bottom-up
static int *pop;              // population per pixel, -1 means "not land"
static int *district;         // district index per pixel
static unsigned char *border;

// Districts. Index `outside` (== max_dist) is the sentinel for non-land pixels.
static int numdist = 1;
static int max_dist;
static int outside;
static long *dist_tots;
static int *dist_seats;
static int *dlx, *dly, *dhx, *dhy;  // per-district bounding box
static int *tabler, *tableg, *tableb;

static int max_pop;

// -------------------------------------------------------------------- opts --

static const char *opt_boundary = NULL;
static const char *opt_pop = NULL;
static const char *opt_out = "out";
static const char *opt_assign = NULL;
static int opt_seats = 32;
static double opt_gain = 100.0;
static int opt_frames = 0;
static int opt_quiet = 0;

static double xoff = 0;  // dateline shift applied to all longitudes
static double minx, miny;
static double gn;

static void gnom_conv(double la, double ph, double *cx, double *cy);
static void build_mask(void);
static void render(void);
static void write_bmp(const char *filename);
static int findlargedist(void);
static void splitdist(int dist);
static void findborders(void);
static void optcolours(void);

static void die(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

#include <stdarg.h>
static void die(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "splitline: ");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
    exit(1);
}

static void *xmalloc(size_t n) {
    void *p = malloc(n);
    if (!p) die("out of memory allocating %zu bytes", n);
    return p;
}

static void *xcalloc(size_t n, size_t sz) {
    void *p = calloc(n, sz);
    if (!p) die("out of memory allocating %zu x %zu bytes", n, sz);
    return p;
}

static void note(const char *fmt, ...) {
    if (opt_quiet) return;
    va_list ap;
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    fflush(stdout);
}

// Read one line, stripping the newline. Returns 0 at EOF with nothing read.
static int read_line(char *buf, int cap, FILE *fp) {
    if (!fgets(buf, cap, fp)) return 0;
    size_t n = strlen(buf);
    while (n > 0 && (buf[n - 1] == '\n' || buf[n - 1] == '\r')) buf[--n] = 0;
    return 1;
}

// ------------------------------------------------------------ boundary I/O --

static void load_boundary(const char *fname) {
    FILE *fp = fopen(fname, "r");
    if (!fp) die("cannot open boundary file %s: %s", fname, strerror(errno));

    int cap = 1 << 16;
    pa = xmalloc(sizeof(int) * cap);
    px = xmalloc(sizeof(double) * cap);
    py = xmalloc(sizeof(double) * cap);

    int cnt = 0;
    int a;
    double b, c;

    pa[0] = -1;

    // Outer loop reads a polygon (or hole) id; inner loop reads its vertices
    // until the "END" terminator makes the %lf scan fail.
    while (fscanf(fp, "%d", &a) > 0) {
        pa[cnt] = a;
        while (fscanf(fp, "%lf %lf", &b, &c) > 0) {
            px[cnt] = b;
            py[cnt] = c;
            cnt++;
            if (cnt + 2 >= cap) {
                cap *= 2;
                pa = realloc(pa, sizeof(int) * cap);
                px = realloc(px, sizeof(double) * cap);
                py = realloc(py, sizeof(double) * cap);
                if (!pa || !px || !py) die("out of memory growing boundary arrays");
            }
            pa[cnt] = 0;
        }
        pa[cnt] = -1;
        if (fscanf(fp, "END") == EOF) break;
    }
    fclose(fp);

    pnum = cnt;
    if (pnum == 0) die("boundary file %s contained no vertices", fname);
    note("boundary: %d vertices\n", pnum);
}

// The edge arrays only ever need to hold the longest single ring, not the
// whole raster (the original sized them winx*winy, which is ~260 MB at
// national scale for data that never exceeds a few thousand entries).
static void size_edge_arrays(void) {
    int longest = 0, cur = 0;
    for (int i = 0; i < pnum; i++) {
        if (i > 0 && (pa[i] > 0 || pa[i] == -99999)) {
            if (cur > longest) longest = cur;
            cur = 0;
        }
        cur++;
    }
    if (cur > longest) longest = cur;

    pmax = longest + 8;
    pxst = xmalloc(sizeof(int) * pmax);
    pyst = xmalloc(sizeof(int) * pmax);
    pxen = xmalloc(sizeof(int) * pmax);
    pyen = xmalloc(sizeof(int) * pmax);
    note("longest ring: %d vertices\n", longest);
}

// Build the edge list for polygon `num` (1-based among polygons with pa>0).
static void genpoly(int num) {
    int cnt = 0, cnt2 = 0;
    while (cnt < num) {
        if (pa[cnt2] > 0) cnt++;
        cnt2++;
    }

    pcnt = 0;

    int xst = (int)px[cnt2];
    int yst = (int)py[cnt2];
    cnt2++;

    while (pa[cnt2] <= 0 && pa[cnt2] != -1) {
        if (pcnt + 2 >= pmax) break;  // guarded by size_edge_arrays
        if (pa[cnt2] == -99999) {
            // Close the current ring, then start a hole ring.
            pxst[pcnt] = (int)px[cnt2 - 1];
            pxen[pcnt] = xst;
            pyst[pcnt] = (int)py[cnt2 - 1];
            pyen[pcnt] = yst;
            pcnt++;
            cnt2++;
            xst = (int)px[cnt2];
            yst = (int)py[cnt2];
            cnt2++;
        } else {
            pxst[pcnt] = (int)px[cnt2 - 1];
            pxen[pcnt] = (int)px[cnt2];
            pyst[pcnt] = (int)py[cnt2 - 1];
            pyen[pcnt] = (int)py[cnt2];
            pcnt++;
            cnt2++;
        }
    }

    pxst[pcnt] = (int)px[cnt2 - 1];
    pxen[pcnt] = xst;
    pyst[pcnt] = (int)py[cnt2 - 1];
    pyen[pcnt] = yst;
    pcnt++;
}

static void putpixel(int x, int y, int r, int g, int b) {
    if (x < 0 || x >= winx || y < 0 || y >= winy) return;
    unsigned char *pix = frame + ((size_t)winx * y + x) * 3;
    if (r >= 0) pix[0] = (unsigned char)r;
    if (g >= 0) pix[1] = (unsigned char)g;
    if (b >= 0) pix[2] = (unsigned char)b;
}

static void getpixel(int x, int y, int *r, int *g, int *b) {
    *r = *g = *b = -1;
    if (x < 0 || x >= winx || y < 0 || y >= winy) return;
    unsigned char *pix = frame + ((size_t)winx * y + x) * 3;
    *r = pix[0];
    *g = pix[1];
    *b = pix[2];
}

// Even-odd scanline fill of the current edge list.
static void fill(int r, int g, int b) {
    static int *hits = NULL;
    if (hits == NULL) hits = xmalloc(sizeof(int) * (winx + 10));

    for (int y = 0; y < winy - 1; y++) {
        for (int x = 0; x < winx; x++) hits[x] = 0;

        for (int cnt = 0; cnt < pcnt; cnt++) {
            if ((pyst[cnt] > y && pyen[cnt] <= y) ||
                (pyst[cnt] <= y && pyen[cnt] > y) ||
                (pyst[cnt] == y && pyen[cnt] == y)) {
                if (pyst[cnt] == pyen[cnt]) {
                    if (pxst[cnt] == pxen[cnt]) {
                        putpixel(pxst[cnt], pyst[cnt], r, g, b);
                    } else {
                        if (pxst[cnt] >= 0 && pxst[cnt] < winx) hits[pxst[cnt]]++;
                        if (pxen[cnt] >= 0 && pxen[cnt] < winx) hits[pxen[cnt]]++;
                    }
                } else {
                    int xx = (pxen[cnt] * (pyst[cnt] - pyen[cnt]) +
                              (pxst[cnt] - pxen[cnt]) * (y - pyen[cnt])) /
                             (pyst[cnt] - pyen[cnt]);
                    if (xx >= 0 && xx < winx) hits[xx]++;
                }
            }
        }

        int f = 0;
        for (int cnt = 0; cnt < winx; cnt++) {
            f += hits[cnt];
            if (f & 1) putpixel(cnt, y, r, g, b);
        }
    }
}

static int count_polys(void) {
    int ccnt = 0;
    for (int cnt = 0; pa[cnt] != -1; cnt++)
        if (pa[cnt] > 0) ccnt++;
    return ccnt;
}

static void draw_land(int r, int g, int b) {
    int ccnt = count_polys();
    for (int i = 1; i <= ccnt; i++) {
        genpoly(i);
        fill(r, g, b);
    }
}

// Establish the land mask. Anything that is neither inside a boundary polygon
// nor carrying population is flagged out of play (pop = -1, district = outside).
// In the original this was fused into update(); splitting it out lets the
// district search run without touching the renderer.
static void build_mask(void) {
    memset(frame, 0, (size_t)winx * winy * 3);
    draw_land(192, 192, 192);

    long land = 0;
    for (int x = 0; x < winx; x++) {
        for (int y = 0; y < winy; y++) {
            int r, g, b;
            getpixel(x, y, &r, &g, &b);
            size_t i = (size_t)y * winx + x;
            if (r == 0 && g == 0 && b == 0 && pop[i] == 0) {
                pop[i] = -1;
                district[i] = outside;
            } else {
                land++;
            }
        }
    }
    note("land pixels: %ld of %d\n", land, winx * winy);
}

static void render(void) {
    memset(frame, 0, (size_t)winx * winy * 3);
    draw_land(192, 192, 192);

    int scale = MINV(10000, max_pop);
    if (scale < 1) scale = 1;

    for (int x = 0; x < winx; x++) {
        for (int y = 0; y < winy; y++) {
            size_t i = (size_t)y * winx + x;
            if (pop[i] <= -1) continue;

            double popu = (double)pop[i] * 60.0 / (double)scale;
            if (popu > 60) popu = 60;

            int d = district[i];
            double r = (popu + 192.0) * (double)tabler[d] / 255.0;
            double g = (popu + 192.0) * (double)tableg[d] / 255.0;
            double b = (popu + 192.0) * (double)tableb[d] / 255.0;

            if (border[i]) {
                r = (r + 255) / 2;
                g = (g + 255) / 2;
                b = (b + 255) / 2;
            }
            putpixel(x, y, (int)r, (int)g, (int)b);
        }
    }
}

// 24-bit BMP, bottom-up. Rows are padded to a 4-byte boundary.
static void write_bmp(const char *filename) {
    int pad = (4 - ((winx * 3) & 3)) & 3;
    long img_size = ((long)winx * 3 + pad) * (long)winy;
    long file_size = img_size + 54;

    FILE *fp = fopen(filename, "wb");
    if (!fp) die("cannot write %s: %s", filename, strerror(errno));

    unsigned char hdr[54];
    memset(hdr, 0, sizeof hdr);
    hdr[0] = 'B';
    hdr[1] = 'M';
    for (int i = 0; i < 4; i++) hdr[2 + i] = (file_size >> (8 * i)) & 0xFF;
    hdr[10] = 54;
    hdr[14] = 40;
    for (int i = 0; i < 4; i++) hdr[18 + i] = ((long)winx >> (8 * i)) & 0xFF;
    for (int i = 0; i < 4; i++) hdr[22 + i] = ((long)winy >> (8 * i)) & 0xFF;
    hdr[26] = 1;   // planes
    hdr[28] = 24;  // bpp
    for (int i = 0; i < 4; i++) hdr[34 + i] = (img_size >> (8 * i)) & 0xFF;
    fwrite(hdr, 1, sizeof hdr, fp);

    unsigned char *row = xmalloc((size_t)winx * 3 + 4);
    memset(row + (size_t)winx * 3, 0, 4);
    for (int y = 0; y < winy; y++) {
        unsigned char *src = frame + (size_t)winx * y * 3;
        for (int x = 0; x < winx; x++) {
            row[x * 3 + 0] = src[x * 3 + 2];  // BMP is BGR
            row[x * 3 + 1] = src[x * 3 + 1];
            row[x * 3 + 2] = src[x * 3 + 0];
        }
        fwrite(row, 1, (size_t)winx * 3 + pad, fp);
    }
    free(row);
    fclose(fp);
    note("wrote %s (%dx%d)\n", filename, winx, winy);
}

// ------------------------------------------------------------- districting --

// Recompute a district's population and bounding box by scanning `region`
// only. Every caller knows a box that contains the district, because
// districts are only ever carved out of their parent.
static void rescan(int d, int lx, int ly, int hx, int hy) {
    long tot = 0;
    int nlx = winx, nly = winy, nhx = -1, nhy = -1;
    for (int y = ly; y <= hy; y++) {
        for (int x = lx; x <= hx; x++) {
            size_t i = (size_t)y * winx + x;
            if (district[i] != d) continue;
            if (pop[i] > 0) tot += pop[i];
            if (x < nlx) nlx = x;
            if (x > nhx) nhx = x;
            if (y < nly) nly = y;
            if (y > nhy) nhy = y;
        }
    }
    dist_tots[d] = tot;
    if (nhx < 0) {  // empty district
        dlx[d] = dly[d] = 0;
        dhx[d] = dhy[d] = 0;
    } else {
        dlx[d] = nlx;
        dly[d] = nly;
        dhx[d] = nhx;
        dhy[d] = nhy;
    }
}

static int findlargedist(void) {
    int l_num = 0;
    long l_val = -1;
    for (int cnt = 0; cnt < numdist; cnt++) {
        // Only districts with seats left to allocate are splittable.
        if (dist_seats[cnt] > 1 && dist_tots[cnt] > l_val) {
            l_val = dist_tots[cnt];
            l_num = cnt;
        }
    }
    return l_num;
}

static void report(void) {
    if (opt_quiet) return;
    long seat_s_val = -1, seat_l_val = -1;
    for (int cnt = 0; cnt < numdist; cnt++) {
        if (dist_seats[cnt] <= 0) continue;
        long per = dist_tots[cnt] / dist_seats[cnt];
        if (seat_s_val < 0 || per < seat_s_val) seat_s_val = per;
        if (seat_l_val < 0 || per > seat_l_val) seat_l_val = per;
    }
    printf("districts %d/%d  per-seat min %ld max %ld  spread %.3f%%\n",
           numdist, opt_seats, seat_s_val, seat_l_val,
           seat_s_val > 0 ? ((double)(seat_l_val - seat_s_val) / (double)seat_s_val) * 100 : 0.0);
}

// Undo a trial split: fold district numdist-1 back into `dist`.
// Restricted to the parent's bounding box, which is where every pixel of the
// child necessarily lives.
static void mergewithlast(int dist, int lx, int ly, int hx, int hy) {
    if (numdist < 2) die("attempted merge with only 1 district");

    int last = numdist - 1;
    dist_seats[dist] += dist_seats[last];

    for (int y = ly; y <= hy; y++) {
        for (int x = lx; x <= hx; x++) {
            size_t i = (size_t)y * winx + x;
            if (district[i] == last && pop[i] >= 0) {
                dist_tots[dist] += pop[i];
                district[i] = dist;
            }
        }
    }

    dist_tots[last] = 0;
    dist_seats[last] = 0;
    numdist--;
}

// Sweep a half-plane across the district in one of four orientations,
// searching slopes for the cut that splits the population in the target ratio
// with the shortest cut line. Returns the squared cut length.
static double splitquad(int dist, int q, long pop_tgt, int *dbst, int dd,
                        int lx, int ly, int hx, int hy) {
    static int *newv = NULL;
    static int *oldv = NULL;
    if (newv == NULL) {
        newv = xmalloc(sizeof(int) * (MAXV(winx, winy) + 2));
        oldv = xmalloc(sizeof(int) * (MAXV(winx, winy) + 2));
    }

    long orig;
    int st_ld, st_sd, wld, wsd;

    switch (q) {
        case 0:  // (x, y)
            orig = (long)ly * winx + lx;
            st_ld = 1;
            st_sd = winx;
            wld = hx - lx + 1;
            wsd = hy - ly + 1;
            break;
        case 1:  // (-y, -x)
            orig = (long)hy * winx + hx;
            st_ld = -winx;
            st_sd = -1;
            wld = hy - ly + 1;
            wsd = hx - lx + 1;
            break;
        case 2:  // (-y, x)
            orig = (long)ly * winx + hx;
            st_ld = winx;
            st_sd = -1;
            wld = hy - ly + 1;
            wsd = hx - lx + 1;
            break;
        default:  // (-x, y)
            orig = (long)hy * winx + lx;
            st_ld = 1;
            st_sd = -winx;
            wld = hx - lx + 1;
            wsd = hy - ly + 1;
            break;
    }

    int mx = MAXV(winx, winy);
    double bres = (double)mx * mx;
    int bd = 0;

    int clow = 0;
    int chigh = wsd;
    int pos = 0;

    int mostlx, mostly = 0, mostrx, mostry = 0;

    int maxd = (dd == -1) ? wld : dd;
    int mind = (dd == -1) ? 1 : dd;
    if (maxd < 1) maxd = 1;
    if (mind < 1) mind = 1;

    dist_tots[numdist] = 0;

    for (int d = maxd; d >= mind; d--) {
        // Re-slope the cut for this d, restoring pixels the previous, steeper
        // slope had claimed.
        for (int cnt = 0; cnt < wsd; cnt++) {
            if (d == maxd) oldv[cnt] = ((-cnt * wld) / d);
            newv[cnt] = (-cnt * wld) / d;

            int x = MAXV(0, pos + newv[cnt]);
            int y = cnt;
            long pixadr = orig + (long)st_ld * x + (long)st_sd * y;

            int num_reps = pos + oldv[cnt] - x;

            if (pos + oldv[cnt] >= 0) {
                for (int cnt2 = 0; cnt2 <= num_reps; cnt2++) {
                    if (x > 0 && x < wld && district[pixadr] == numdist) {
                        district[pixadr] = dist;
                        dist_tots[numdist] -= pop[pixadr];
                        dist_tots[dist] += pop[pixadr];
                    }
                    x++;
                    pixadr += st_ld;
                }
            }
            oldv[cnt] = newv[cnt];
        }

        // Advance the cut until the new district reaches its population target.
        // At the steepest slope (d == 1) the offset legitimately runs to
        // wld*wsd, so the guard is only a backstop against a target that can
        // never be met; it must not bound the normal sweep.
        int brk = 1;
        long guard = (long)wld * wsd + wld + wsd + 8;
        while (brk && guard-- > 0) {
            for (int cnt = clow; (cnt < chigh) && brk; cnt++) {
                int x = pos + newv[cnt];
                int y = cnt;
                long pixadr = orig + (long)st_ld * x + (long)st_sd * y;
                if (x > 0 && x < wld && district[pixadr] == dist) {
                    district[pixadr] = numdist;
                    dist_tots[numdist] += pop[pixadr];
                    dist_tots[dist] -= pop[pixadr];
                    if (dist_tots[numdist] > pop_tgt) brk = 0;
                }
                if (x < 0) break;
                if (x > wld) clow = MINV(0, cnt - 1);
            }
            pos++;
        }
        pos--;

        // Measure the cut: the span between the extreme pixels along it.
        mostlx = wld;
        mostrx = -1;
        for (int cnt = 0; cnt < wsd; cnt++) {
            int en_pt = (cnt == wsd - 1) ? -1 : (pos + newv[cnt + 1]);
            int st_pt = pos + newv[cnt];
            en_pt = MINV(en_pt, wld - 1);
            en_pt = MAXV(en_pt, 0);
            st_pt = MINV(st_pt, wld - 1);
            st_pt = MAXV(st_pt, 0);
            for (int cnt2 = st_pt; cnt2 > en_pt; cnt2--) {
                long pixadr = orig + (long)st_ld * cnt2 + (long)st_sd * cnt;
                if (district[pixadr] == numdist || district[pixadr] == dist) {
                    if (cnt2 < mostlx && pop[pixadr] >= 0) {
                        mostlx = cnt2;
                        mostly = cnt;
                    }
                    if (cnt2 > mostrx && pop[pixadr] >= 0) {
                        mostrx = cnt2;
                        mostry = cnt;
                    }
                }
            }
        }

        double res = (double)(mostrx - mostlx) * (mostrx - mostlx) +
                     (double)(mostry - mostly) * (mostry - mostly);
        if (d == maxd || res < bres) {
            bres = res;
            bd = d;
        }
    }

    *dbst = bd;
    numdist++;
    return bres;
}

static void splitdist(int dist) {
    if (dist_seats[dist] == 1) {
        note("district %d has only 1 seat, not splitting\n", dist);
        return;
    }

    int d1 = dist_seats[dist] / 2;
    int d2 = dist_seats[dist] - d1;

    long tgt_pop = (dist_tots[dist] * d1) / dist_seats[dist];

    int lx = dlx[dist], ly = dly[dist], hx = dhx[dist], hy = dhy[dist];
    if (hx < winx - 1) hx++;
    if (hy < winy - 1) hy++;
    if (lx > 0) lx--;
    if (ly > 0) ly--;

    int d = 0, bq = 0, bd = 0;
    double bres = 0;

    for (int qdr = 0; qdr < 4; qdr++) {
        double res = splitquad(dist, qdr, tgt_pop, &d, -1, lx, ly, hx, hy);
        if (qdr == 0 || res < bres) {
            bres = res;
            bq = qdr;
            bd = d;
        }
        mergewithlast(dist, lx, ly, hx, hy);
    }

    splitquad(dist, bq, tgt_pop, &d, bd, lx, ly, hx, hy);

    dist_seats[dist] = d2;
    dist_seats[numdist - 1] = d1;

    // Both halves live inside the parent box, so this is the only region we
    // need to look at to refresh totals and boxes.
    rescan(dist, lx, ly, hx, hy);
    rescan(numdist - 1, lx, ly, hx, hy);
}

static void findborders(void) {
    for (int cntx = 0; cntx < winx; cntx++) {
        for (int cnty = 0; cnty < winy; cnty++) {
            size_t i = (size_t)cnty * winx + cntx;
            int curdist = district[i];
            unsigned char v = 0;
            if ((cntx + 1) < winx && district[i + 1] != curdist &&
                district[i + 1] != outside)
                v = 1;
            else if ((cnty + 1) < winy && (cntx + 1) < winx &&
                     district[i + winx + 1] != curdist &&
                     district[i + winx + 1] != outside)
                v = 1;
            else if (cntx > 0 && district[i - 1] != curdist &&
                     district[i - 1] != outside)
                v = 2;
            else if (cnty > 0 && (cntx + 1) < winx &&
                     district[i - winx + 1] != curdist &&
                     district[i - winx + 1] != outside)
                v = 2;
            border[i] = v;
        }
    }
}

// Greedy graph colouring over the district adjacency graph. The original
// rebuilt the whole adjacency matrix once per district (O(numdist * pixels),
// which is hopeless at 435 districts); this builds it in a single raster pass.
static void optcolours(void) {
    static const int rb[] = {0, 255, 128, 64, 192};
    const int nrb = (int)(sizeof(rb) / sizeof(rb[0]));
    const int nsets = nrb * nrb;

    unsigned char *adj = xcalloc((size_t)numdist * numdist, 1);

    for (int cnty = 0; cnty < winy; cnty++) {
        for (int cntx = 0; cntx < winx; cntx++) {
            size_t i = (size_t)cnty * winx + cntx;
            int a = district[i];
            if (a >= numdist) continue;
            if (cntx + 1 < winx) {
                int b = district[i + 1];
                if (b < numdist && b != a) {
                    adj[(size_t)a * numdist + b] = 1;
                    adj[(size_t)b * numdist + a] = 1;
                }
            }
            if (cnty + 1 < winy) {
                int b = district[i + winx];
                if (b < numdist && b != a) {
                    adj[(size_t)a * numdist + b] = 1;
                    adj[(size_t)b * numdist + a] = 1;
                }
            }
        }
    }

    for (int d = 0; d <= max_dist; d++) {
        tabler[d] = 200;
        tableg[d] = 200;
        tableb[d] = 200;
    }

    for (int dcnt = 0; dcnt < numdist; dcnt++) {
        int colset = 0;
        for (; colset < nsets; colset++) {
            int r = rb[colset / nrb];
            int b = rb[colset % nrb];
            int g = (int)(255 - (0.3 / 0.59) * r - (0.11 / 0.59) * b);
            if (g < 0) g = 0;
            if (g > 255) g = 255;

            int clash = 0;
            for (int bcnt = 0; bcnt < dcnt; bcnt++) {
                if (adj[(size_t)bcnt * numdist + dcnt] && tabler[bcnt] == r &&
                    tableb[bcnt] == b) {
                    clash = 1;
                    break;
                }
            }
            if (!clash) {
                tabler[dcnt] = r;
                tableg[dcnt] = g;
                tableb[dcnt] = b;
                break;
            }
        }
        if (colset == nsets) {
            // Ran out of distinct colours; reuse rather than abort.
            int r = rb[dcnt % nrb];
            int b = rb[(dcnt / nrb) % nrb];
            tabler[dcnt] = r;
            tableb[dcnt] = b;
            tableg[dcnt] = (int)(255 - (0.3 / 0.59) * r - (0.11 / 0.59) * b);
        }
    }

    free(adj);
}

// ------------------------------------------------------------- projection --

static void gnom_conv(double la, double ph, double *cx, double *cy) {
    static const double PI = 3.14159265358979323846;

    la = la / 180 * PI;
    ph = ph / 180 * PI;
    double la0r = la0 / 180 * PI;
    double ph1r = ph1 / 180 * PI;

    double denom = sin(ph1r) * sin(ph) + cos(ph1r) * cos(ph) * cos(la - la0r);

    *cx = cos(ph) * sin(la - la0r) / denom;
    *cy = (cos(ph1r) * sin(ph) - sin(ph1r) * cos(ph) * cos(la - la0r)) / denom;

    *cx *= 180 / PI;
    *cy *= 180 / PI;
}

static void project_to_pixel(double x, double y, int *xx, int *yy) {
    x += xoff;
    if (x >= 180) x -= 360;
    gnom_conv(x, y, &x, &y);
    *xx = (int)(20 + gn * (x - minx));
    *yy = (int)(20 + gn * (y - miny));
}

// ------------------------------------------------------------------- input --

static void load_population(const char *fname) {
    FILE *fp = fopen(fname, "r");
    if (!fp) die("cannot open population file %s: %s", fname, strerror(errno));

    char buf[16384];
    long total = 0, dropped = 0, nrec = 0;
    max_pop = 0;

    while (read_line(buf, sizeof buf, fp)) {
        if (buf[0] == 0 || buf[0] == '#') continue;
        int tractnum, blocknum, popul, curven;
        double x, y;
        if (sscanf(buf, "%d,%d,%d,%d,%lf,%lf", &tractnum, &blocknum, &popul,
                   &curven, &x, &y) < 6)
            continue;

        nrec++;
        int xx, yy;
        project_to_pixel(x, y, &xx, &yy);

        if (xx < 0 || xx >= winx || yy < 0 || yy >= winy) {
            dropped += popul;
            continue;
        }

        size_t i = (size_t)winx * yy + xx;
        pop[i] += popul;
        total += popul;
        if (pop[i] > max_pop) max_pop = pop[i];
    }
    fclose(fp);

    note("population: %ld records, %ld people", nrec, total);
    if (dropped) note(", %ld dropped outside frame", dropped);
    note("\n");
    if (total == 0) die("no population loaded from %s", fname);
}

// Map every input record back to the district its pixel ended up in.
static void dump_assignment(const char *popfile, const char *outfile) {
    FILE *fp = fopen(popfile, "r");
    if (!fp) die("cannot reopen %s: %s", popfile, strerror(errno));
    FILE *op = fopen(outfile, "w");
    if (!op) die("cannot write %s: %s", outfile, strerror(errno));

    fprintf(op, "tract,block,pop,district\n");

    char buf[16384];
    while (read_line(buf, sizeof buf, fp)) {
        if (buf[0] == 0 || buf[0] == '#') continue;
        int tractnum, blocknum, popul, curven;
        double x, y;
        if (sscanf(buf, "%d,%d,%d,%d,%lf,%lf", &tractnum, &blocknum, &popul,
                   &curven, &x, &y) < 6)
            continue;

        int xx, yy;
        project_to_pixel(x, y, &xx, &yy);
        int d = -1;
        if (xx >= 0 && xx < winx && yy >= 0 && yy < winy) {
            d = district[(size_t)winx * yy + xx];
            if (d >= numdist) d = -1;
        }
        fprintf(op, "%06d,%d,%d,%d\n", tractnum, blocknum, popul, d);
    }
    fclose(fp);
    fclose(op);
    note("wrote %s\n", outfile);
}

// -------------------------------------------------------------------- main --

static void usage(void) {
    fprintf(stderr,
            "usage: splitline --boundary FILE --pop FILE --seats N [options]\n"
            "\n"
            "  --boundary FILE   outline in ARC/INFO ungenerate format\n"
            "  --pop FILE        population points: tract,block,pop,curve,lon,lat\n"
            "  --seats N         number of districts to produce\n"
            "  --out PREFIX      output path prefix (default: out)\n"
            "  --gain N          pixels per degree (default: 100)\n"
            "  --assign FILE     also write a per-record district assignment CSV\n"
            "  --frames          write a BMP after every split, not just the last\n"
            "  --quiet           suppress progress output\n");
    exit(2);
}

int main(int argc, char **argv) {
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--boundary") && i + 1 < argc) opt_boundary = argv[++i];
        else if (!strcmp(argv[i], "--pop") && i + 1 < argc) opt_pop = argv[++i];
        else if (!strcmp(argv[i], "--out") && i + 1 < argc) opt_out = argv[++i];
        else if (!strcmp(argv[i], "--assign") && i + 1 < argc) opt_assign = argv[++i];
        else if (!strcmp(argv[i], "--seats") && i + 1 < argc) opt_seats = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--gain") && i + 1 < argc) opt_gain = atof(argv[++i]);
        else if (!strcmp(argv[i], "--frames")) opt_frames = 1;
        else if (!strcmp(argv[i], "--quiet")) opt_quiet = 1;
        else usage();
    }

    if (!opt_boundary || !opt_pop) usage();
    if (opt_seats < 1) opt_seats = 1;
    if (opt_gain <= 0) die("--gain must be positive");

    load_boundary(opt_boundary);
    size_edge_arrays();

    // Longitude range wider than 180 degrees means the outline straddles the
    // antimeridian (Alaska); shift it into a contiguous range first.
    double maxx = -500, minxx = 500, maxy = -500, minyy = 500;
    for (int cnt = 0; cnt < pnum; cnt++) {
        if (px[cnt] > maxx) maxx = px[cnt];
        if (px[cnt] < minxx) minxx = px[cnt];
        if (py[cnt] > maxy) maxy = py[cnt];
        if (py[cnt] < minyy) minyy = py[cnt];
    }
    if (maxx - minxx > 180) xoff = 180;

    maxx = -10000;
    minxx = 10000;
    for (int cnt = 0; cnt < pnum; cnt++) {
        px[cnt] += xoff;
        if (px[cnt] >= 180) px[cnt] -= 360;
        if (px[cnt] < minxx) minxx = px[cnt];
        if (px[cnt] > maxx) maxx = px[cnt];
    }

    la0 = (maxx + minxx) / 2;
    ph1 = (maxy + minyy) / 2;
    note("projection centre: %.4f, %.4f\n", la0, ph1);

    maxx = -10000;
    minxx = 10000;
    maxy = -10000;
    minyy = 10000;
    for (int cnt = 0; cnt < pnum; cnt++) {
        gnom_conv(px[cnt], py[cnt], &px[cnt], &py[cnt]);
        if (px[cnt] < minxx) minxx = px[cnt];
        if (px[cnt] > maxx) maxx = px[cnt];
        if (py[cnt] < minyy) minyy = py[cnt];
        if (py[cnt] > maxy) maxy = py[cnt];
    }

    minx = minxx;
    miny = minyy;
    gn = opt_gain;

    winx = (int)((maxx - minxx) * gn) + 41;
    winy = (int)((maxy - minyy) * gn) + 41;
    winx = (winx & 1) ? winx : winx + 1;
    winy = (winy & 1) ? winy : winy + 1;

    size_t npix = (size_t)winx * winy;
    note("raster: %d x %d (%.1f Mpx)\n", winx, winy, npix / 1e6);

    for (int cnt = 0; cnt < pnum; cnt++) {
        px[cnt] = 20 + gn * (px[cnt] - minx);
        py[cnt] = 20 + gn * (py[cnt] - miny);
    }

    max_dist = opt_seats;
    outside = max_dist;

    dist_tots = xcalloc(max_dist + 2, sizeof(long));
    dist_seats = xcalloc(max_dist + 2, sizeof(int));
    dlx = xcalloc(max_dist + 2, sizeof(int));
    dly = xcalloc(max_dist + 2, sizeof(int));
    dhx = xcalloc(max_dist + 2, sizeof(int));
    dhy = xcalloc(max_dist + 2, sizeof(int));
    tabler = xcalloc(max_dist + 2, sizeof(int));
    tableg = xcalloc(max_dist + 2, sizeof(int));
    tableb = xcalloc(max_dist + 2, sizeof(int));

    frame = xcalloc(npix, 3);
    pop = xcalloc(npix, sizeof(int));
    district = xcalloc(npix, sizeof(int));
    border = xcalloc(npix, 1);

    load_population(opt_pop);
    build_mask();

    dist_seats[0] = opt_seats;
    rescan(0, 0, 0, winx - 1, winy - 1);
    note("total population: %ld\n", dist_tots[0]);

    char fname[4096];
    clock_t t0 = clock();

    while (numdist < opt_seats) {
        int dcnt = findlargedist();
        if (dist_seats[dcnt] <= 1) {
            die("no splittable district left at %d of %d", numdist, opt_seats);
        }
        splitdist(dcnt);

        if (opt_frames) {
            findborders();
            optcolours();
            render();
            snprintf(fname, sizeof fname, "%s_%04d.bmp", opt_out, numdist);
            write_bmp(fname);
        } else if (!opt_quiet && (numdist % 25 == 0 || numdist == opt_seats)) {
            report();
        }
    }

    note("split complete in %.1fs\n", (double)(clock() - t0) / CLOCKS_PER_SEC);
    report();

    findborders();
    optcolours();
    render();
    snprintf(fname, sizeof fname, "%s_final.bmp", opt_out);
    write_bmp(fname);

    if (opt_assign) dump_assignment(opt_pop, opt_assign);

    return 0;
}
