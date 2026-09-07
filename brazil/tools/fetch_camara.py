#!/usr/bin/env python3
"""Fetch Chamber of Deputies roll-call summaries from the Camara's open data.

Two layers exist and they differ by two orders of magnitude in size:

  votacoes-YYYY.json       ~10 MB/yr  one record per vote, with the tallies
  votacoesVotos-YYYY.json  7-79 MB/yr one record per deputy per vote

Only the first is needed to *find* votes that could have flipped, so that is
what this fetches. Per-deputy votes are pulled later and only for the
shortlist, because reweighting a vote by (state, party) is worth doing for a
few dozen roll calls and not for the eighty thousand that were never close.

Coverage begins in 2003. Earlier years 404, so the 49th to 51st legislatures
-- the 1990, 1994 and 1998 elections -- have no roll-call data here and their
seat counterfactuals cannot be tested against actual votes.
"""

import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "upstream" / "camara"
URL = "https://dadosabertos.camara.leg.br/arquivos/votacoes/json/votacoes-{y}.json"
YEARS = range(2003, 2025)
UA = {"User-Agent": "counterfactual-legislatures/0.1 (research; github.com/brunoparga)"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    man = {}
    mf = OUT / "manifest.json"
    if mf.exists():
        man = json.loads(mf.read_text())
    total = 0
    for y in YEARS:
        dest = OUT / f"votacoes-{y}.json"
        if dest.exists() and dest.stat().st_size > 0:
            total += dest.stat().st_size
            continue
        url = URL.format(y=y)
        try:
            data = urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=300).read()
        except Exception as e:
            print(f"  {y}: {e}")
            continue
        dest.write_bytes(data)
        man[str(y)] = {"url": url, "bytes": len(data),
                       "sha256": hashlib.sha256(data).hexdigest()}
        total += len(data)
        print(f"  {y}: {len(data)/1e6:.1f} MB", flush=True)
        time.sleep(1)
    mf.write_text(json.dumps(man, indent=1))
    print(f"total {total/1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
