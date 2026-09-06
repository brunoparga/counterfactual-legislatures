# Licensing of data

The code in this repository is under Apache-2.0 (see `LICENSE` and `NOTICE`).
Data is a separate question, and deliberately not answered once for everything.

## Why not a single licence

A generated dataset inherits obligations from whatever it was generated from,
and those obligations differ by country in ways that do not survive a blanket
declaration:

- **United States.** Census files and cartographic boundaries are works of the
  federal government and carry no copyright. Anything derived from them alone
  can be released on any terms.
- **European Union.** A *sui generis* database right exists that has no US
  equivalent, so a dataset derived from an EU database may carry obligations
  its US analogue would not.
- **OpenStreetMap.** ODbL, which is share-alike. Any *derived database* must
  also be ODbL. This is **incompatible with CC-BY**, and OSM is the obvious
  fallback for boundaries in countries without good official geodata. Anything
  touched by OSM is ODbL, full stop.
- **National statistical agencies.** Generally open, but each demands specific
  attribution wording — UK under OGL, Germany under dl-de/by-2-0, France under
  Licence Ouverte. A repository-level "CC-BY" does not discharge those.

So the licence is declared **per dataset**, not per repository.

## The rule

Every generated dataset carries provenance naming each input, its source, the
date retrieved, its licence, and any attribution string that licence requires.
The output's own licence is whatever is compatible with all of its inputs.

**Default: CC-BY-4.0**, used wherever every input permits it. All US-derived
output currently qualifies, since the inputs are uncopyrighted federal works.

CC-BY rather than CC0 so that reuse remains citable. The inputs impose no
attribution requirement, so this is a choice, not an inheritance.

## Findings from published research

Later phases pair legislative outcomes with published effect sizes — "policy A
changes variable X by this much". An effect size is a fact, and facts are not
copyrightable. Cite the paper; never redistribute it. Any table of such
findings in this repository is a set of citations plus numbers, not an archive
of literature.

## Attribution we owe

The shortest splitline method and the maps this project reproduces come from
the Center for Range Voting, whose page grants reuse on one condition:

> We give permission to all to re-use these images provided they cite the
> Center for Range Voting, this web page, and us; the Shortest Splitline
> algorithm was invented by Warren D. Smith and the program that produced the
> images was written by Ivan Ryan; the underlying data is from the US Census
> Bureau.

`NOTICE` carries that credit in the form we use. It applies to the maps
generated here, not only to theirs: the method is theirs whoever runs it. Any
reuse of images from this repository should carry it too.

## The site

`docs/` is published at polisci.brunoparga.net and mixes three kinds of thing,
so it takes three answers rather than inheriting one:

- **Markup and stylesheet** — code, and Apache-2.0 with the rest of it.
- **Prose** — CC-BY-4.0. Apache-2.0 would technically cover it, but a licence
  written about source and object form, derivative works of software and
  patent grants is the wrong instrument for an essay.
- **Maps** — CC-BY-4.0, as derivatives of the cut trees, which is the same
  answer the trees already have.
- **The Center for Range Voting's map** — theirs, used under the permission
  quoted above and credited in the page footer.

Nothing else is pulled in. The page loads no webfonts, no CDN, no third-party
scripts or stylesheets; the only external references are ordinary hyperlinks,
which carry no licence obligation. Font stacks name system fonts rather than
distributing any.

DejaVu Sans is used by `shared/tools/label_map.py` to draw captions into the
map images. Its licence permits this explicitly, and glyphs rendered into a
raster are not a redistribution of the font, so nothing is owed -- recorded
here only so an audit does not have to work it out again.

## Third-party material not committed here

- **rangevoting.org's published maps** (`usa/upstream/reference/`), the comparison
  baseline for reproducing the 2000 results. Their reuse terms above are met
  by the credit in `NOTICE`, so keeping them out is a scope and size choice
  rather than a licensing one.
- **Census source files** (`usa/upstream/`), excluded for size — they are public
  domain and freely redownloadable. `MANIFEST.json` and `MANIFEST.sha256` are
  tracked instead, recording a checksum and the exact Wayback snapshot for
  every downloaded file, so each one is both verifiable and re-fetchable. The
  apportionment tables are the exception: 104 KB whose origin URL was never
  recorded, so the bytes themselves are committed.
