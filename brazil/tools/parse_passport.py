#!/usr/bin/env python3
"""Election Passport's Brazil file -> party votes per state, 1982-2014.

TSE's machine-readable repository begins in 1994, so the 1990 election -- the
first Chamber election held under the 1988 Constitution, and therefore the
first under the floor of 8 and ceiling of 70 -- is not available from the
primary source at all. Election Passport (David Lublin, American University)
compiles constituency-level results for 110 countries; its BR file carries
total votes per party per state for every Chamber election from 1982 to 2014.

Two things this costs us relative to the TSE files, both worth stating plainly:

  * It is party totals, not coalition totals. Until 2018 seats were won by
    coalitions, so a party-level allocation is not the rule Brazil actually
    used. Every year is therefore also computed at party level, so that 1990
    is compared against like and not against the coalition-level series.
  * It stops at 2014.

Its compensating virtue is that it is an independent compilation, so for
1994-2014 it cross-checks the TSE parsing rather than merely extending it.

Requires the xlsx converted to CSV first (libreoffice --headless --convert-to
csv), because the workbook is one wide sheet with a column per party and no
merged cells, which survives that conversion intact.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Columns before the party columns begin.
META = ["YEAR", "STATE", "ABBREV", "CODE", "ELECTORS", "BALLOTS", "ABSTAIN",
        "BLANK", "INVALID", "VALID"]


def parse(path):
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        rd = csv.reader(f)
        head = [h.strip() for h in next(rd)]
        n = len(META)
        parties = [h.strip() for h in head[n:]]
        for row in rd:
            if not row or not row[0].strip():
                continue
            year, uf = row[0].strip(), row[2].strip()
            votes = {}
            for p, v in zip(parties, row[n:]):
                if not p or not v.strip():
                    continue
                try:
                    x = int(float(v))
                except ValueError:
                    continue
                if x > 0:
                    votes[p] = votes.get(p, 0) + x
            # The file carries a BRASIL row of national totals alongside the
            # states. It is not a constituency, so it is held aside -- and used
            # as a checksum, since the 27 states must sum to it.
            out.setdefault(year, {})[uf] = {
                "valid": int(float(row[9])) if row[9].strip() else sum(votes.values()),
                "votes": votes}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=None, help="BR.xlsx converted to CSV")
    ap.add_argument("--out", default=str(ROOT / "upstream" / "electionpassport" /
                                         "br_party_votes.json"))
    a = ap.parse_args()
    src = a.csv or str(ROOT / "upstream" / "electionpassport" / "BR.csv")
    d = parse(src)
    clean = {}
    for y, states in d.items():
        national = states.pop("BRASIL", None)
        clean[y] = states
        tot = sum(s["valid"] for s in states.values())
        chk = ("no BRASIL row" if national is None else
               "sums to BRASIL" if national["valid"] == tot else
               f"MISMATCH: states {tot:,} vs BRASIL {national['valid']:,}")
        print(f"  {y}: {len(states)} states, {tot:,} valid votes, "
              f"{len({p for s in states.values() for p in s['votes']})} parties"
              f"  [{chk}]")
    Path(a.out).write_text(json.dumps(clean, indent=1))
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
