#!/usr/bin/env python3
"""Record what was downloaded, so 9 GB of census data need not be committed.

WHAT IS AND IS NOT LISTED

Only the files that actually came off the network: the archives, and the
handful of apportionment tables fetched loose. Everything else under the
upstream root is either unzipped from one of those or produced by our own
converters, and checksumming it would be recording our output as though it
were provenance.

WHY THE SNAPSHOT MATTERS MORE THAN THE CHECKSUM

census.gov refuses automated clients, so the bytes came through the Wayback
Machine. A checksum tells you your copy is intact; it does not tell you where
to get another one. The snapshot timestamp does, because

    https://web.archive.org/web/{snapshot}id_/{url}

is immutable in a way census.gov is not. The fetcher logged the snapshot it
used for each file, so those are recovered here by reading the logs rather
than by asking the Archive again -- a fresh CDX query could return a
different, equally valid snapshot, which would silently break the link
between this manifest and the bytes on disk.

Files fetched before that logging existed carry a null snapshot. They are
still verifiable, just not exactly re-fetchable.

    tools/make_manifest.py --root upstream --out upstream
    sha256sum -c upstream/MANIFEST.sha256
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Which SOURCES.json entry each download belongs to, by where it sits.
def source_id(rel):
    parts = rel.parts
    if parts[0] == "apportionment":
        return "us-apportionment-tables"
    if len(parts) > 1 and parts[1] == "boundary":
        return "us-census-boundaries"
    year = parts[0]
    if year == "2000":
        # The 2000 boundary files are per-state, alongside the SF1 archives.
        return ("us-census-boundaries" if rel.name.startswith("st")
                else "us-census-2000-sf1")
    return {"2010": "us-census-2010-pl94171",
            "2020": "us-census-2020-pl94171"}.get(year, "unknown")


def snapshots_from_logs(logdir):
    """{filename: wayback timestamp}, as recorded by fetch_census.py."""
    pat = re.compile(r"(\S+):\s+[\d.]+\s*[KMG]B\s+\(snapshot (\d{14})\)")
    found = {}
    for log in sorted(Path(logdir).glob("*.log")):
        for line in log.open(errors="replace"):
            m = pat.search(line)
            if m:
                found[m.group(1)] = m.group(2)
    return found


def sha256(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT / "upstream"),
                    help="upstream data directory")
    ap.add_argument("--logs", default=str(ROOT / "work"))
    ap.add_argument("--out", default=None, help="where to write (default: root)")
    args = ap.parse_args()

    root = Path(args.root)
    out = Path(args.out) if args.out else root
    if not root.is_dir():
        sys.exit(f"no such directory: {root}")

    snaps = snapshots_from_logs(args.logs)

    # Snapshots recovered by backfill_snapshots.py were found by hashing
    # candidate captures, not by reading a log, so regenerating from logs alone
    # would silently throw them away. Anything already known wins over nothing.
    old = out / "MANIFEST.json"
    if old.exists():
        prev = json.loads(old.read_text())
        kept = 0
        for e in prev.get("entries", []):
            name = Path(e["path"]).name
            if e.get("wayback_snapshot") and name not in snaps:
                snaps[name] = e["wayback_snapshot"]
                kept += 1
        if kept:
            print(f"carried {kept} snapshot(s) forward from the existing manifest")

    downloads = sorted(p for p in root.rglob("*.zip"))
    downloads += sorted(p for p in (root / "apportionment").glob("*")
                        if p.is_file() and p.suffix != ".zip")

    entries, total, uncovered = [], 0, 0
    t0 = time.time()
    for i, p in enumerate(downloads, 1):
        rel = p.relative_to(root)
        size = p.stat().st_size
        snap = snaps.get(p.name)
        if snap is None and rel.parts[0] != "apportionment":
            uncovered += 1
        # Two ways an input can be covered: a snapshot that re-fetches it, or
        # the bytes themselves. The apportionment tables take the second route
        # -- 104 KB, public domain, and the only inputs whose origin URL was
        # never recorded, so pointing at one is not an option.
        entries.append({
            "path": str(rel),
            "bytes": size,
            "sha256": sha256(p),
            "source_id": source_id(rel),
            "wayback_snapshot": snap,
            "tracked_here": rel.parts[0] == "apportionment",
        })
        total += size
        if i % 50 == 0:
            print(f"  {i}/{len(downloads)}  {total/1e9:.1f} GB  "
                  f"{time.time()-t0:.0f}s", flush=True)

    (out / "MANIFEST.json").write_text(json.dumps({
        "_comment": [
            "Files downloaded from elsewhere, not committed. See LICENSE-DATA.md",
            "and SOURCES.json. Extracted and converted files are absent by",
            "design: they reproduce from these.",
            "wayback_snapshot replays as https://web.archive.org/web/{snapshot}id_/{url}",
            "with url taken from the matching SOURCES.json entry. A null snapshot",
            "means the file predates the fetcher's logging; still verifiable,",
            "not exactly re-fetchable.",
        ],
        "generated": time.strftime("%Y-%m-%d"),
        "root": str(root.name),
        "files": len(entries),
        "bytes": total,
        "entries": entries,
    }, indent=1) + "\n")

    with (out / "MANIFEST.sha256").open("w") as f:
        for e in entries:
            f.write(f"{e['sha256']}  {e['path']}\n")

    tracked = sum(1 for e in entries if e["tracked_here"])
    print(f"\n{len(entries)} files, {total/1e9:.2f} GB")
    print(f"  {len(entries)-tracked-uncovered} re-fetchable by snapshot")
    print(f"  {tracked} tracked in this repository")
    print(f"  {uncovered} UNCOVERED" if uncovered else "  0 uncovered")
    print(f"wrote {out/'MANIFEST.json'} and {out/'MANIFEST.sha256'}")
    print(f"verify with:  cd {root} && sha256sum -c MANIFEST.sha256")
    return 0


if __name__ == "__main__":
    sys.exit(main())
