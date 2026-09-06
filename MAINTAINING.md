# Maintaining this repository

Notes for whoever runs the pipeline, including me later. Licensing terms for
*users* of the data are in `LICENSE-DATA.md`; this is about keeping that file
true.

## Provenance

Every gap so far came from the same thing: a dataset arrived, got used, and
the provenance record was updated later or not at all. Three habits, in the
order they failed us.

**Record a source when you download it, not when you remember.** 740 MB of
election data sat outside `SOURCES.json` and outside `MANIFEST.json` for days.
The maps carried the right credit only because it was hardcoded in the map
tool -- nothing derived it from the record, so nothing could have caught a
mistake. The credit line is now built from `SOURCES.json`, which means an
unrecorded source is a visibly wrong credit rather than a silent one.

**Cite a version, not just a DOI.** A DOI names a dataset; a dataset can be
revised. The MEDSL county returns are on V20, and our local copy was several
versions and eight years behind, titled for a range it did not cover. Nothing
noticed, because a DOI still resolved and still looked right.
`shared/tools/dataverse_cite.py` asks the repository's API for the current
version and UNF; `--check SOURCES.json` re-queries every Dataverse DOI we
record and reports which have moved on. Run it before publishing anything.

**Ask what a licence obliges, not just what it is.** "CC BY-SA" is not a
label, it is an instruction that propagates: any output built from
share-alike input is share-alike too. That is why `share_alike` is a field of
its own rather than something to be read out of a licence string, and why the
credit line computes a map's licence from the sources it actually used. The
basemaps are CC BY and the vote maps are CC BY-SA, and neither is a choice
anyone types.

Two things the API cannot do, recorded so they are not rediscovered:
`dataverse.org` and the Dataverse dataset pages sit behind a CDN that refuses
automated clients, so metadata must come from
`/api/datasets/export?exporter=dataverse_json`, which answers plainly. And
some files are gated behind a mandatory guestbook form -- no API parameter
bypasses it, `gbrecs=true` included -- so updating those needs a person.


## Long runs

The districting engine is single-threaded and the national maps take about
twenty minutes each. Everything caches on the output stem, so an interrupted
run resumes rather than restarting -- but a process killed *while writing* a
tree leaves a truncated JSON that the cache check accepts as done. Kill
between maps, or delete the file it was writing.

Run long jobs at `nice -n 19 ionice -c 3`. On two cores that leaves the
foreground responsive and costs the job almost nothing, because it only takes
CPU that would otherwise idle.

## Things that fail silently

Collected because each of these produced a wrong answer that looked right:

- **A renamed column.** MEDSL's 2024 revision renamed `FIPS` to `county_fips`
  and upper-cased the party values. A reader written against the old file
  matches nothing and reports zero votes rather than raising.
- **A double-counted total.** The same file breaks later years down by voting
  mode *and* carries a TOTAL row; 3,282 keys have both. Summing every row
  inflates those states silently.
- **An ignored projection parameter.** Alaska's tree carries `lon_shift: 180`
  because the state straddles the antimeridian. Ignoring it puts every
  Alaskan block on the far side of the world, and only Alaska is affected, so
  nothing else looks wrong.
- **A metric that measures the wrong thing.** Aligning two maps on their
  bounding boxes counted the Center for Range Voting's edge-to-edge cut lines
  as land, which made their frame the whole image and ours the state outline.
  Agreement came out at 86% when the real figure was 99.6%.

The pattern is that each was caught by testing against a value known
independently -- the official apportionment, a published seat count, a
national vote total. Where such a check exists, it is worth more than reading
the code again.
