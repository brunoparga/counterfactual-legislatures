#!/usr/bin/env python3
"""Fetch TSE Chamber of Deputies results, one file per election.

TSE's CDN sits behind Akamai bot detection. It rejects HEAD from anything, and
rejects GET unless the request carries a browser's full navigation header set
-- User-Agent alone is not enough, and neither is adding Accept and Referer.
The header that actually matters is the `Sec-Fetch-*` trio: with those the CDN
serves normally, including range requests.

So the direct route works and is preferred, because it gets the current file
rather than whenever the Archive last looked. The Wayback replay is kept as a
fallback for when TSE is down or tightens the check further; it uses the CDX
index and the `id_` suffix, which suppresses the Archive's own rewriting.

Coverage is 1994 onwards. **1990 is a genuine 404** under every `odsele`
dataset name -- TSE's machine-readable repository begins in 1994, and the 1990
election needs an academic compilation instead; see brazil/README.md. 1998 is
present on the live CDN (7.5 MB) even though it is absent from the Archive,
which is why the direct route is tried first.

What the file contains: votes by party, by municipality and electoral zone,
for every office. We want DEPUTADO FEDERAL only, aggregated to the state,
which is the district. Both nominal votes (cast for a named candidate) and
legenda votes (cast for the party alone) count toward a party's total under
Brazilian law, so both are summed.
"""

import hashlib
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
YEARS = [1994, 1998, 2002, 2006, 2010, 2014, 2018, 2022]
# Akamai serves the CDN only to something that looks like a navigating
# browser. The Sec-Fetch-* headers are the ones it actually checks.
BROWSER = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": "https://dadosabertos.tse.jus.br/",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-site"}
UA = {"User-Agent": "counterfactual-legislatures/0.1 (research; github.com/brunoparga)"}


def get(url, timeout=300, headers=None):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=headers or UA), timeout=timeout).read()


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
        data = ts = None
        try:
            data = get(url, headers=BROWSER)
        except Exception as e:
            print(f"  {y}: direct fetch failed ({e}), trying the Archive")
        if data is None:
            rows = json.loads(get(CDX.format(u=url), 120).decode())
            if len(rows) < 2:
                print(f"  {y}: NOT ARCHIVED EITHER -- no source")
                continue
            ts = rows[-1][1]          # newest snapshot; TSE revises these files
            data = get(REPLAY.format(ts=ts, u=url))
        dest.write_bytes(data)
        snaps[str(y)] = {"url": url, "via": "wayback" if ts else "tse-direct",
                         "wayback_snapshot": ts, "bytes": len(data),
                         "sha256": hashlib.sha256(data).hexdigest()}
        print(f"  {y}: {len(data)/1e6:.1f} MB  "
              f"via {'wayback ' + ts if ts else 'TSE direct'}", flush=True)
        time.sleep(2)
    sf.write_text(json.dumps(snaps, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
