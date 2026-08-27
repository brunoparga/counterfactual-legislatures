#!/usr/bin/env python3
"""Recover the Wayback snapshot for manifest entries that lack one.

MATCH, DO NOT RE-DOWNLOAD

The obvious fix -- fetch the file again and record whatever snapshot answers
-- is wrong. The Archive holds several captures of most of these URLs, and a
fresh fetch may well return a different one. Recording that would claim a
provenance the bytes on disk do not have, and every .pop file and cut tree
downstream was built from the bytes we already have.

So this asks the opposite question: of the snapshots the Archive holds for
this URL, which one hashes to the sha256 already in the manifest? That one is
where our copy came from. Nothing on disk is touched.

A file with no matching snapshot keeps its null and gains a note. That is a
real finding -- the capture we used may have been deleted, or the bytes came
from somewhere else -- and is worth recording rather than papering over.

    tools/backfill_snapshots.py            # report only
    tools/backfill_snapshots.py --write    # update MANIFEST.json in place
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_census as fc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# The apportionment tables were fetched ad hoc rather than by fetch_census.py,
# so no code records where they came from. census.gov answers 403 to any
# automated client, which means a live 404/403 cannot distinguish a wrong path
# from a blocked one -- the CDX index is the only way to tell, and a hash match
# is what actually confirms it.
APPORTIONMENT_URLS = {
    "apportionment-2020-table01.xlsx":
        "https://www2.census.gov/programs-surveys/decennial/2020/data/"
        "apportionment/apportionment-2020-table01.xlsx",
    "2020CensusOverseasCounts.xlsx":
        "https://www2.census.gov/programs-surveys/decennial/2020/data/"
        "apportionment/2020CensusOverseasCounts.xlsx",
    "ApportionmentPopulation2010.xls":
        "https://www.census.gov/population/apportionment/files/"
        "ApportionmentPopulation2010.xls",
    "2010CensusOverseasCounts.xlsx":
        "https://www.census.gov/population/apportionment/files/"
        "2010CensusOverseasCounts.xlsx",
    "2000_tab01.txt":
        "https://www.census.gov/population/cen2000/tab01.txt",
    "2000_pvalues.txt":
        "https://www.census.gov/population/cen2000/pvalues.txt",
    "2000_apportionment_results.html":
        "https://www.census.gov/population/www/cen2000/maps/files/"
        "apportionment_results.html",
}


def origin_url(rel):
    """The census.gov URL a manifest path was fetched from, or None."""
    parts = rel.parts
    if parts[0] == "apportionment":
        return APPORTIONMENT_URLS.get(rel.name)
    year = int(parts[0])
    if len(parts) == 2:                       # national boundary shapefile
        return fc.BOUNDARY.get(year)
    st = parts[1].upper()
    for url, fname in fc.state_targets(year, st):
        if fname == rel.name:
            return url
    return None


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(ROOT / "upstream" / "MANIFEST.json"))
    ap.add_argument("--write", action="store_true",
                    help="update the manifest (default: report only)")
    ap.add_argument("--candidates", type=int, default=8,
                    help="snapshots to try per URL")
    args = ap.parse_args()

    man = json.loads(Path(args.manifest).read_text())
    todo = [e for e in man["entries"] if not e.get("wayback_snapshot")]
    print(f"{len(todo)} entries without a snapshot\n")

    found = missing = nourl = 0
    for e in todo:
        rel = Path(e["path"])
        url = origin_url(rel)
        if not url:
            print(f"  {e['path']}: no origin URL known")
            e["snapshot_note"] = "origin URL not recorded"
            nourl += 1
            continue

        # Only the archives have a URL the code actually used. The
        # apportionment paths are reconstructed, so a miss says the guess was
        # wrong, not that the file went unarchived -- a distinction the note
        # has to preserve or it will be read as a claim about the Archive.
        guessed = rel.parts[0] == "apportionment"

        try:
            cands = fc.snapshots(url, n=args.candidates)
        except Exception as exc:
            print(f"  {e['path']}: CDX failed ({exc})")
            continue
        if not cands:
            print(f"  {e['path']}: no capture at {'guessed ' if guessed else ''}URL")
            e["snapshot_note"] = (
                f"origin URL not recorded; candidate {url} is not in the "
                f"Wayback index, so the candidate is probably wrong"
                if guessed else
                f"no capture of {url} found in the Wayback index")
            missing += 1
            continue

        hit = None
        for ts in cands:
            try:
                data = fc._get(fc.REPLAY.format(ts=ts, url=url))
            except (urllib.error.HTTPError, urllib.error.URLError, Exception):
                continue
            if sha256_bytes(data) == e["sha256"]:
                hit = ts
                break

        if hit:
            e["wayback_snapshot"] = hit
            e.pop("snapshot_note", None)
            print(f"  {e['path']}: matched snapshot {hit}")
            found += 1
        else:
            e["snapshot_note"] = (
                f"{len(cands)} capture(s) of {url} checked, none matched the "
                f"recorded sha256"
                + ("; origin URL not recorded, so this candidate may be the "
                   "wrong file" if guessed else
                   "; the capture we used may since have been removed"))
            print(f"  {e['path']}: {len(cands)} captures, none matched")
            missing += 1

    print(f"\nmatched {found}, unmatched {missing}, no URL {nourl}")
    if args.write:
        man["generated"] = time.strftime("%Y-%m-%d")
        Path(args.manifest).write_text(json.dumps(man, indent=1) + "\n")
        print(f"updated {args.manifest}")
    else:
        print("report only; pass --write to update the manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
