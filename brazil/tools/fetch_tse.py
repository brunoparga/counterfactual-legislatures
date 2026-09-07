#!/usr/bin/env python3
"""Fetch TSE Chamber of Deputies results, one file per election.

TSE blocks automated clients at the CDN (Akamai returns 403 to any
non-browser request, and to HEAD from anything), exactly as census.gov does.
The same remedy applies: locate a snapshot with the Wayback CDX index and
replay it with the `id_` suffix, which suppresses the Archive's own rewriting
so the bytes arrive unmodified.

Coverage is 1994 onwards. TSE's electronic repository does not go back to
1990, and 1998 is absent from the Archive as well as from the live CDN under
this path -- checked by prefix search across the whole `odsele` tree, not just
the expected filename. Those two elections need a different source; see
brazil/README.md.

What the file contains: votes by party, by municipality and electoral zone,
for every office. We want DEPUTADO FEDERAL only, aggregated to the state,
which is the district. Both nominal votes (cast for a named candidate) and
legenda votes (cast for the party alone) count toward a party's total under
Brazilian law, so both are summed.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "upstream" / "tse"
BASE = ("https://cdn.tse.jus.br/estatistica/sead/odsele/"
        "votacao_partido_munzona/votacao_partido_munzona_{y}.zip")
CDX = ("http://web.archive.org/cdx/search/cdx?url={u}&output=json"
       "&filter=statuscode:200&collapse=digest")
REPLAY = "https://web.archive.org/web/{ts}id_/{u}"
YEARS = [1994, 2002, 2006, 2010, 2014, 2018, 2022]
UA = {"User-Agent": "counterfactual-legislatures/0.1 (research; github.com/brunoparga)"}


def get(url, timeout=300):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                  timeout=timeout).read()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    snaps = {}
    sf = OUT / "snapshots.json"
    if sf.exists():
        snaps = json.loads(sf.read_text())
    for y in YEARS:
        dest = OUT / f"votacao_partido_munzona_{y}.zip"
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  {y}: have {dest.stat().st_size/1e6:.1f} MB")
            continue
        url = BASE.format(y=y)
        rows = json.loads(get(CDX.format(u=url), 120).decode())
        if len(rows) < 2:
            print(f"  {y}: NOT ARCHIVED")
            continue
        # newest snapshot last; take it, since TSE revises these files
        ts = rows[-1][1]
        data = get(REPLAY.format(ts=ts, u=url))
        dest.write_bytes(data)
        snaps[str(y)] = {"url": url, "wayback_snapshot": ts, "bytes": len(data)}
        print(f"  {y}: {len(data)/1e6:.1f} MB  snapshot {ts}", flush=True)
        time.sleep(2)
    sf.write_text(json.dumps(snaps, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
