#!/usr/bin/env python3
"""Fetch a Dataverse dataset's citation metadata, and check ours is current.

A DOI names a dataset but not a version, and a dataset can be revised many
times -- the MEDSL county returns are on V20. So a citation that stops at the
DOI cannot say which data was used, and two people following it can get
different numbers.

The Dataverse citation standard has seven parts: author, title, year,
repository, version, persistent identifier, and UNF. The UNF is the one that
does the work. It is a cryptographic fingerprint of the data's *content*
rather than its file format, so it survives conversion between formats and
changes if any value changes. Recording it is what makes "the data I used" a
checkable claim.

This exists because we got it wrong: the local MEDSL file was three versions
and eight years out of date, titled for a range it did not cover, and nothing
in the provenance record noticed. Asking the API is cheap and mechanical, so
it should not depend on remembering to.

    dataverse_cite.py 10.7910/DVN/VOQCHQ
    dataverse_cite.py --check SOURCES.json
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

API = ("https://dataverse.harvard.edu/api/datasets/export"
       "?exporter=dataverse_json&persistentId=doi:{doi}")
CITE = ("https://dataverse.harvard.edu/api/datasets/:persistentId/versions/"
        ":latest/citation?persistentId=doi:{doi}")


def fetch(doi, timeout=45):
    """Citation components for one DOI, from the API.

    The API is used rather than the dataset page because the HTML is behind a
    CDN that refuses automated clients, while the API answers plainly.
    """
    req = urllib.request.Request(API.format(doi=doi), headers={
        "User-Agent": "counterfactual-legislatures/0.1 (research)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    ds = d.get("datasetVersion", d)
    out = {"doi": doi,
           "version": f"V{ds.get('versionNumber')}.{ds.get('versionMinorNumber')}",
           "unf": ds.get("UNF"),
           "released": (ds.get("releaseTime") or "")[:10]}
    lic = ds.get("license")
    out["licence"] = lic.get("name") if isinstance(lic, dict) else lic
    for f in ds.get("metadataBlocks", {}).get("citation", {}).get("fields", []):
        if f["typeName"] == "title":
            out["title"] = f["value"]
        elif f["typeName"] == "author":
            out["author"] = "; ".join(a["authorName"]["value"] for a in f["value"])
    out["files"] = [{"name": f.get("dataFile", {}).get("filename"),
                     "id": f.get("dataFile", {}).get("id"),
                     "unf": f.get("dataFile", {}).get("UNF"),
                     "bytes": f.get("dataFile", {}).get("filesize")}
                    for f in ds.get("files", [])]
    return out


def citation(doi, timeout=45):
    """The repository's own citation string, not one assembled from parts.

    Building it by hand got the year wrong: Dataverse cites a dataset by its
    original publication year, while the metadata also carries the release
    date of the current version, and those differ by eight years here. Asking
    for the citation avoids inventing a convention the repository already has.
    """
    import re
    req = urllib.request.Request(CITE.format(doi=doi), headers={
        "User-Agent": "counterfactual-legislatures/0.1 (research)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        msg = json.load(r).get("data", {}).get("message", "")
    return re.sub(r"<[^>]+>", "", msg).replace(" [fileUNF]", "").strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doi", nargs="*")
    ap.add_argument("--check", metavar="SOURCES.json",
                    help="re-query every Dataverse DOI in a sources file and "
                         "report where the recorded version has moved on")
    a = ap.parse_args()

    if a.check:
        rec = json.loads(open(a.check).read())
        bad = 0
        for s in rec["sources"]:
            url = s.get("url", "")
            if "doi.org/" not in url and "doi:" not in url:
                continue
            doi = url.split("doi.org/")[-1].split("doi:")[-1]
            try:
                m = fetch(doi)
            except (urllib.error.URLError, urllib.error.HTTPError) as e:
                print(f"  {s['id']}: could not reach the API ({e})")
                bad += 1
                continue
            cur = f"{m['version']} ({m['released']}), {m['unf']}"
            was = s.get("version_current")
            state = "current" if was == cur else f"STALE -- recorded {was!r}"
            print(f"  {s['id']}: {state}")
            if was != cur:
                print(f"      now {cur}")
                bad += 1
        print(f"\n{bad} entr{'y' if bad == 1 else 'ies'} to update")
        return 1 if bad else 0

    for doi in a.doi:
        m = fetch(doi)
        print(citation(doi))
        print(f"  licence: {m.get('licence')}")
        for f in m["files"]:
            print(f"  file: {f['name']}  {(f['bytes'] or 0)/1e6:.1f} MB  {f['unf']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
