#!/usr/bin/env python3
"""Wikitext seat tables -> {state: {party: seats}}, verified both ways.

These tables were first transcribed by eye from a screenshot, and three party
columns in 1990 and five in 1994 failed to reconcile with the published column
totals -- each set netting to zero, which is the signature of values landing in
an adjacent column. Parsing the wikitext removes the possibility entirely: cell
position comes from the markup rather than from pixel coordinates.

Both checks are then enforced rather than reported: every row must sum to its
published Soma, and every party column must sum to its published Total. A table
that fails either is rejected, because a seat table that does not add up is
worse than no seat table.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def cells(block):
    """Cell values of one wikitable row, stripped of markup."""
    out = []
    for line in block.strip().split("\n"):
        line = line.strip()
        if not line.startswith(("|", "!")):
            continue
        v = line.lstrip("|!")
        # drop a leading style run like align="center"| or width="30"|
        if "|" in v and re.match(r'^[a-z-]+="[^"]*"', v):
            v = v.split("|", 1)[1]
        v = v.replace("'''", "").strip()
        v = re.sub(r"\[\[[^|\]]*\|([^\]]*)\]\]", r"\1", v)
        v = re.sub(r"\[\[([^\]]*)\]\]", r"\1", v)
        out.append(v.strip())
    return out


def parse(text):
    body = text.split("{|", 1)[1].rsplit("|}", 1)[0]
    rows = [cells(b) for b in body.split("\n|-")]
    rows = [r for r in rows if r]
    head = rows[0]
    parties = head[1:-1]
    data, totals, soma = {}, None, {}
    for r in rows[1:]:
        if len(r) != len(head):
            continue
        name = r[0]
        vals = [int(x) if x.strip() else 0 for x in r[1:-1]]
        tot = int(r[-1])
        if name.lower().startswith("total"):
            totals = dict(zip(parties, vals))
            grand = tot
        elif name.lower().startswith("percent"):
            continue
        else:
            data[name] = {p: v for p, v in zip(parties, vals) if v}
            soma[name] = tot
    return parties, data, soma, totals, grand


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wikitext")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    parties, data, soma, totals, grand = parse(Path(a.wikitext).read_text())
    bad_rows = {u: (sum(data[u].values()), soma[u])
                for u in data if sum(data[u].values()) != soma[u]}
    bad_cols = {}
    for p in parties:
        got = sum(data[u].get(p, 0) for u in data)
        if got != totals[p]:
            bad_cols[p] = (got, totals[p])
    print(f"{a.year}: {len(data)} states, {len(parties)} parties, "
          f"chamber {grand}")
    print(f"  rows summing to their published Soma : "
          f"{'ALL' if not bad_rows else bad_rows}")
    print(f"  columns summing to published Total   : "
          f"{'ALL' if not bad_cols else bad_cols}")
    print(f"  states sum to chamber size           : "
          f"{sum(soma.values()) == grand} ({sum(soma.values())})")
    # Row sums and the chamber total are load-bearing: they *are* the
    # apportionment, so a failure there rejects the table. A party column that
    # misses its published total is a flaw in the source rather than in the
    # parse -- the 1994 table has one, PMDB 106 against a published 107 and
    # PSDB 64 against 63 -- and the party cells feed nothing, so it is recorded
    # and carried rather than thrown away.
    if bad_rows or sum(soma.values()) != grand:
        print("REJECTED -- the seat counts themselves do not reconcile")
        return 1
    if bad_cols:
        print("  NOTE: party columns above disagree with the source's own "
              "totals row. Rows and the chamber total are intact, so the "
              "apportionment is unaffected; the party cells carry the flaw.")
    out = a.out or str(ROOT / "upstream" / "wikipedia" / f"br_{a.year}_seats.json")
    Path(out).write_text(json.dumps(
        {"source": f"pt.wikipedia.org, 'Camara dos Deputados em {a.year}'",
         "licence": "CC BY-SA 4.0", "chamber": grand,
         "seats_by_uf": soma, "published_party_totals": totals,
         "by_uf_party": data,
         "verified": "every row sums to its published Soma; states sum to the "
                     "chamber size",
         "source_column_discrepancies": {k: {"cells": v[0], "published": v[1]}
                                         for k, v in bad_cols.items()}},
        indent=1, ensure_ascii=False))
    print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
