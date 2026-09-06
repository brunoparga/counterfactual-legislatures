#!/usr/bin/env python3
"""Fetch Dave's Redistricting block-level election data, one file per state.

This is votes already disaggregated to census blocks, which is the whole point:
allocating county totals by population destroys the sorting inside a county,
and 60% of Americans live in a county that spans more than one district. At
block level there is no allocation left to get wrong -- only the exact question
of which district contains a block.

The disaggregation is not ours and is not free of assumptions; DRA pushed
precinct returns down to blocks. But it is done at precinct resolution by
people who validate it, rather than at county resolution by us.

LICENCE: CC BY-SA 4.0 plus a no-sale clause. Share-alike, so anything derived
from it is BY-SA -- unlike our cut trees, which are census-derived and CC-BY.
See LICENSE-DATA.md.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "upstream" / "elections" / "dra_block"
URL = "https://data.dra2020.net/file/dra-block-data/Election_Data_Block_{st}.v{v:02d}.zip"
DELAY = 2.5


def main():
    ver = json.loads((ROOT / "work" / "dra_versions.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    got = skipped = failed = 0
    total = 0
    for i, (st, v) in enumerate(sorted(ver.items()), 1):
        dest = OUT / f"{st}.zip"
        if dest.exists() and dest.stat().st_size > 0:
            skipped += 1
            total += dest.stat().st_size
            continue
        url = URL.format(st=st, v=v)
        try:
            req = urllib.request.Request(url, headers={"User-Agent":
                "counterfactual-legislatures/0.1 (research; contact via github.com/brunoparga)"})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            dest.write_bytes(data)
            total += len(data)
            got += 1
            print(f"  [{i}/{len(ver)}] {st} v{v:02d}  {len(data)/1e6:.1f} MB", flush=True)
        except Exception as e:
            print(f"  [{i}/{len(ver)}] {st}: FAILED {e}", flush=True)
            failed += 1
        time.sleep(DELAY)
    print(f"\nfetched {got}, reused {skipped}, failed {failed}, {total/1e6:.0f} MB total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
