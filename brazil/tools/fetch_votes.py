#!/usr/bin/env python3
"""Per-deputy votes for the shortlisted divisions only.

The bulk per-deputy files run 7-79 MB a year, about 700 MB for 2003-2024, to
answer a question that concerns a few dozen roll calls. The API serves one
division at a time with the deputy's party and state attached, which is
exactly the cell the reweighting needs, so the shortlist costs a few hundred
kilobytes instead.

Note the API rejects `itens` above its own limit but returns every voter for a
single division in one page anyway, so no pagination is needed here.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "upstream" / "camara" / "votos"
API = "https://dadosabertos.camara.leg.br/api/v2/votacoes/{vid}/votos"
UA = {"User-Agent": "counterfactual-legislatures/0.1 (research; github.com/brunoparga)",
      "Accept": "application/json"}


def main():
    cands = json.loads((ROOT / "results" / "near_miss.json").read_text())["candidates"]
    OUT.mkdir(parents=True, exist_ok=True)
    got = skipped = failed = 0
    for i, v in enumerate(cands, 1):
        dest = OUT / f"{v['id']}.json"
        if dest.exists() and dest.stat().st_size > 0:
            skipped += 1
            continue
        try:
            raw = urllib.request.urlopen(
                urllib.request.Request(API.format(vid=v["id"]), headers=UA),
                timeout=120).read()
            rows = json.loads(raw).get("dados", [])
        except Exception as e:
            print(f"  [{i}/{len(cands)}] {v['id']}: {e}")
            failed += 1
            continue
        recorded = sum(1 for r in rows if r.get("tipoVoto") == "Sim")
        dest.write_text(json.dumps(
            {"id": v["id"], "date": v["date"], "tally_sim": v["sim"],
             "tally_nao": v["nao"], "api_sim": recorded,
             "votes": [{"party": (r.get("deputado_") or {}).get("siglaPartido"),
                        "uf": (r.get("deputado_") or {}).get("siglaUf"),
                        "vote": r.get("tipoVoto")} for r in rows]},
            ensure_ascii=False))
        got += 1
        if recorded != v["sim"]:
            print(f"  [{i}/{len(cands)}] {v['id']}: API Sim {recorded} "
                  f"vs published {v['sim']}  (delta {recorded - v['sim']:+})")
        time.sleep(0.4)
    print(f"fetched {got}, reused {skipped}, failed {failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
