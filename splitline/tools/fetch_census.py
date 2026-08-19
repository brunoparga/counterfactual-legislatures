#!/usr/bin/env python3
"""Fetch decennial census inputs via the Internet Archive.

census.gov sits behind Cloudflare and refuses automated clients, but the
Wayback Machine holds the original FTP tree. Snapshots are resolved through
the CDX index rather than hardcoded, and downloaded with the `id_` replay
suffix so we get the original bytes rather than a Wayback HTML wrapper.

  2000  Summary File 1 per state: <st>geo.uf1 carries summary level, the
        geographic identifiers and each block's internal point; <st>00001.uf1
        carries P001001. Boundaries come as st<FIPS>_d00_ascii, already in the
        ARC/INFO ungenerate format the splitline engine reads.

  2010  PL 94-171 per state, one zip. The geographic header is fixed-width,
        500-char records, and carries POP100 alongside the internal point, so
        no join to a separate segment is needed.

  2020  PL 94-171 per state, one zip. Same idea but pipe-delimited; POP100 is
        field 91, INTPTLAT/INTPTLON are 93/94.

  2010/2020 boundaries are cartographic boundary *shapefiles*, one national
  file per year, and still need converting to ungenerate.

BE GENTLE. The Wayback Machine rate-limits hard and also throws transient
503s. Every request is spaced by --delay, retries back off exponentially, and
nothing is parallelised. A full 50-state year takes a while; that is fine.
"""

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apportionment import FIPS, NAMES  # noqa: E402

CDX = "http://web.archive.org/cdx/search/cdx"
REPLAY = "https://web.archive.org/web/{ts}id_/{url}"
UA = "Mozilla/5.0 (X11; Linux x86_64) counterfactual-legislatures/splitline"

SF1_2000 = "http://www2.census.gov/census_2000/datasets/Summary_File_1"
COB_2000 = "http://www.census.gov/geo/cob/bdy/st/st00ascii"
PL_2010 = "http://www2.census.gov/census_2010/redistricting_file--pl_94-171"
PL_2020 = ("https://www2.census.gov/programs-surveys/decennial/2020/data/"
           "01-Redistricting_File--PL_94-171")

BOUNDARY = {
    2010: "http://www2.census.gov/geo/tiger/GENZ2010/gz_2010_us_040_00_500k.zip",
    2020: "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_state_500k.zip",
}

# Politeness is adaptive and lives at session scope, not per request.
#
# Per-request backoff alone is memoryless: every new file starts over at the
# base rate, so during a sustained outage the session keeps knocking just as
# often no matter how hard the server pushes back. Here the spacing between
# *all* requests doubles on every failure and decays back toward the floor on
# success, and a run of consecutive failures trips a circuit breaker that
# stands down entirely for a while. The server can therefore slow us down,
# which is the whole point of being polite rather than merely patient.
DELAY = 6.0        # floor, from --delay
DELAY_MAX = 900.0  # never space requests further apart than this
BREAKER_AFTER = 5  # consecutive failures before standing down outright
BREAKER_MAX = 3600.0

_state = {"delay": None, "last": 0.0, "fails": 0}


def _pace():
    if _state["delay"] is None:
        _state["delay"] = DELAY
    d = _state["delay"]
    wait = d + random.uniform(0, d * 0.25) - (time.time() - _state["last"])
    if wait > 0:
        time.sleep(wait)
    _state["last"] = time.time()


def _on_success():
    _state["fails"] = 0
    before = _state["delay"] or DELAY
    # Ease back toward the floor rather than snapping to it.
    _state["delay"] = max(DELAY, before * 0.7)
    if _state["delay"] < before - 0.5:
        print(f"      (easing spacing to {_state['delay']:.0f}s)", flush=True)


def _on_failure(why):
    _state["fails"] += 1
    before = _state["delay"] or DELAY
    _state["delay"] = min(DELAY_MAX, before * 2)
    print(f"      {why}; spacing now {_state['delay']:.0f}s "
          f"({_state['fails']} consecutive)", flush=True)

    if _state["fails"] >= BREAKER_AFTER:
        pause = min(BREAKER_MAX, 300.0 * (2 ** (_state["fails"] - BREAKER_AFTER)))
        print(f"      circuit breaker: {_state['fails']} failures in a row, "
              f"standing down for {pause/60:.0f} min", flush=True)
        time.sleep(pause)


def _get(url, retries=5, timeout=300):
    delay = 20.0
    for attempt in range(retries):
        _pace()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            _on_success()
            return data
        except urllib.error.HTTPError as e:
            # A 404 is a real answer, not the server asking us to back off.
            if e.code in (429, 503, 504):
                _on_failure(f"HTTP {e.code}")
                if attempt < retries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            _on_failure(type(e).__name__)
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError(f"gave up on {url}")


def snapshots(url, n=6):
    """Successful Wayback snapshots of `url`, newest first.

    Returns several rather than one: the CDX index and the replay servers do
    not always agree, so a timestamp listed as a 200 can still 404 on replay.
    """
    q = urllib.parse.urlencode({
        "url": url, "output": "json", "filter": "statuscode:200",
        "collapse": "urlkey", "limit": f"-{n}",
    })
    # An empty body is NOT proof the file was never archived. Under load the
    # CDX server answers 200 with nothing in it, and treating that as absence
    # turns a transient outage into a permanent "does not exist" -- which is
    # what silently lost most of the 2000 set. Retry before believing it.
    for attempt in range(3):
        raw = _get(f"{CDX}?{q}", timeout=120).decode("utf-8", "replace").strip()
        if raw:
            break
        if attempt < 2:
            print(f"      empty CDX response, retrying in 30s")
            time.sleep(30)
    else:
        raise RuntimeError("CDX kept returning an empty body; treating as "
                           "unknown rather than absent")
    rows = json.loads(raw)
    if len(rows) < 2:
        return []
    ti = rows[0].index("timestamp")
    return [r[ti] for r in reversed(rows[1:])]


def fetch(url, dest, force=False):
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"      cached {dest.name} ({dest.stat().st_size/1e6:.1f} MB)")
        return dest

    cands = snapshots(url)
    if not cands:
        raise RuntimeError(f"no Wayback snapshot for {url}")

    last = None
    for ts in cands:
        try:
            data = _get(REPLAY.format(ts=ts, url=url))
        except urllib.error.HTTPError as e:
            if e.code in (404, 403, 451):
                print(f"      snapshot {ts} replays {e.code}, trying an older one")
                last = e
                continue
            raise
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(data)
        tmp.rename(dest)  # only appears complete once it is
        print(f"      {dest.name}: {len(data)/1e6:.1f} MB (snapshot {ts})")
        return dest

    raise RuntimeError(f"all {len(cands)} snapshots failed for {url}: {last}")


def unzip(path, outdir):
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(outdir)
    except zipfile.BadZipFile:
        raise RuntimeError(f"{path.name} is not a valid zip (bad snapshot?)")


def state_targets(year, st):
    """(url, filename) pairs making up one state-year."""
    fips, low = FIPS[st], st.lower()
    name = NAMES[st].replace(" ", "_")
    if year == 2000:
        return [
            (f"{SF1_2000}/{name}/{low}geo_uf1.zip", f"{low}geo_uf1.zip"),
            (f"{SF1_2000}/{name}/{low}00001_uf1.zip", f"{low}00001_uf1.zip"),
            (f"{COB_2000}/st{fips}_d00_ascii.zip", f"st{fips}_d00_ascii.zip"),
        ]
    if year == 2010:
        return [(f"{PL_2010}/{name}/{low}2010.pl.zip", f"{low}2010.pl.zip")]
    return [(f"{PL_2020}/{name}/{low}2020.pl.zip", f"{low}2020.pl.zip")]


def fetch_state(year, st, outroot, force=False):
    """Fetch every file for one state. Returns the names that failed.

    Each file is attempted independently. Previously one failure aborted the
    whole state, which was actively harmful for 2000: the boundary was fetched
    first, so a single spurious "missing" threw away the Summary File data too,
    and a year came out at 1/51 instead of mostly complete. A file that fails
    here is simply absent, and re-running picks it up because everything that
    did land is cached.
    """
    st = st.upper()
    low = st.lower()
    d = outroot / low
    d.mkdir(parents=True, exist_ok=True)
    print(f"  {st} {NAMES[st]}", flush=True)

    failed = []
    for url, fname in state_targets(year, st):
        try:
            z = fetch(url, d / fname, force)
            unzip(z, d)
        except Exception as e:
            print(f"      {fname}: FAILED ({e})", file=sys.stderr, flush=True)
            failed.append(fname)
    return failed


def fetch_boundary(year, outroot, force=False):
    if year not in BOUNDARY:
        return
    url = BOUNDARY[year]
    dest = outroot / Path(urllib.parse.urlparse(url).path).name
    print(f"  national boundary shapefile", flush=True)
    z = fetch(url, dest, force)
    unzip(z, outroot / "boundary")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("states", nargs="+", help="state abbreviations, or ALL")
    ap.add_argument("--year", type=int, required=True, choices=(2000, 2010, 2020))
    ap.add_argument("--out", default=None, help="output root (default data/<year>)")
    ap.add_argument("--delay", type=float, default=6.0,
                    help="minimum seconds between requests (default 6)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    global DELAY
    DELAY = args.delay

    outroot = Path(args.out) if args.out else Path(f"data/{args.year}")
    if args.states == ["ALL"]:
        # Every state with seats, plus DC, which the nationwide map needs.
        states = sorted(FIPS, key=lambda s: FIPS[s])
    else:
        states = [s.upper() for s in args.states]

    started = time.time()
    print(f"{args.year}: {len(states)} state(s) -> {outroot}, "
          f"{args.delay}s between requests", flush=True)

    failed = []
    try:
        fetch_boundary(args.year, outroot, args.force)
    except Exception as e:
        print(f"    boundary FAILED: {e}", file=sys.stderr)
        failed.append("boundary")

    partial = {}
    for i, st in enumerate(states, 1):
        print(f"[{i}/{len(states)}]", end=" ", flush=True)
        try:
            missing = fetch_state(args.year, st, outroot, args.force)
        except Exception as e:  # unexpected: keep going to the next state
            print(f"      FAILED: {e}", file=sys.stderr, flush=True)
            missing = ["<state aborted>"]
        if missing:
            partial[st] = missing

    mins = (time.time() - started) / 60
    total = len(states)
    print(f"\ndone in {mins:.1f} min: {total - len(partial)}/{total} states complete")

    if partial:
        print(f"\n{len(partial)} state(s) missing files (re-run to retry; "
              f"everything already downloaded is cached):", file=sys.stderr)
        for st in sorted(partial, key=lambda s: FIPS[s]):
            print(f"  {st}: {' '.join(partial[st])}", file=sys.stderr)
    if failed:
        print(f"also failed: {' '.join(failed)}", file=sys.stderr)
    return 1 if (partial or failed) else 0


if __name__ == "__main__":
    sys.exit(main())
