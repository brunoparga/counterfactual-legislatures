# Reproducing everything in this repository

Every artifact here — every plan, map, animation and vote scoring — is a
deterministic function of published inputs and the code in this repository.
This file is the recipe. It is written so that someone with no access to this
machine can rebuild any artifact and get the same bytes, and so that a future
maintainer can tell what an existing file was made from.

Companion files, split by audience:

- `LICENSE-DATA.md` — what you may do with the outputs (for reusers)
- `MAINTAINING.md` — how to keep the provenance records correct (for us)
- `SOURCES.json` — machine-readable provenance for every third-party input
- `usa/upstream/MANIFEST.json` — checksum and Wayback snapshot per file
- `research/` — surveys that inform future work; not inputs to any artifact

---

## 0. Layout

    shared/     country-neutral: the districting engine, seat-allocation
                maths, stitching, animation, SVG
    usa/        everything that knows about FIPS codes, census formats or
                the number 435
      upstream/   third-party inputs, NOT committed (9 GB); manifest is
      plans/      the cut trees -- THE artifact, committed, 12 MB
      renders/    PNG/GIF/SVG derived from plans/, not committed
      build/      engine intermediates, not committed
      maps/       browsable symlink views over the above, rebuilt not stored
      results/    vote scorings and demographics, committed
      work/       scratch and logs, not committed
    research/   literature and data surveys
    docs/       the published site (polisci.brunoparga.net)

The rule behind what is committed: **plans/ is the content.** Every district
is an exact half-plane intersection, resolution-free, so every picture is a
pure function of a plan plus rendering parameters. Storing 907 MB of PNGs
would be storing a cache.

## 1. Build the engine

    cd shared/splitline && make          # -> shared/splitline/bin/splitline

A C port of `autodistrict` (Ivan Ryan, 2007, Apache-2.0). The vendored
original is at `shared/splitline/vendor/autodistrict-2007/`; see `NOTICE`.

## 2. Fetch the inputs

**census.gov blocks automated clients.** Everything census is fetched through
the Wayback Machine: snapshots are located with the CDX index at
`http://web.archive.org/cdx/search/cdx` and replayed with the `id_` suffix
(`https://web.archive.org/web/{timestamp}id_/{url}`), which suppresses the
Archive's own rewriting so the bytes are unmodified.

    python3 usa/tools/fetch_census.py          # 9 GB, PL 94-171 + SF1 + boundaries
    python3 usa/tools/fetch_dra.py             # 614 MB, block-level election data

Verify against the manifest before trusting anything:

    sha256sum -c usa/upstream/MANIFEST.sha256

Two inputs cannot be fetched by script and need a person:

- **MEDSL county presidential returns** (`countypres_2000-2024.csv`) —
  Harvard Dataverse doi:10.7910/DVN/VOQCHQ is guestbook-gated (guestbookID
  458) and no API parameter bypasses it. Download by hand; accept the Dataset
  Terms dialog, which states CC0 1.0.
- **rangevoting.org reference maps** — comparison baseline only, not an input
  to any artifact.

### Known reproducibility gaps in the fetch step

Recorded here rather than quietly fixed, because they are the kind of thing
that silently breaks a rebuild years later:

1. **`fetch_dra.py` reads `usa/work/dra_versions.json`, which is gitignored.**
   The per-state version numbers (v06/v07) are therefore not recoverable from
   the repository. The file must be moved into version control. Until then a
   rebuild would fetch whatever version is current and might not match the
   checksums in `MANIFEST.json`.
2. **`MANIFEST.json` records `direct_url: true` for DRA files but not the URL
   itself.** The URL template lives only in `fetch_dra.py`
   (`https://data.dra2020.net/file/dra-block-data/Election_Data_Block_{st}.v{NN}.zip`).
   It should be in the manifest.
3. **The apportionment tables have no recorded origin URL.** This is why their
   bytes are committed rather than excluded — 104 KB is cheaper than an
   unreproducible input.
4. **The DRA server rejects `HEAD`.** Probing for new versions must use a
   ranged `GET` with the tool's User-Agent, or every URL appears to 403.

## 3. Populations and apportionment

    python3 usa/tools/pl_to_pop.py     # PL 94-171 (2010, 2020) -> .pop
    python3 usa/tools/sf1_to_pop.py    # Census 2000 SF1       -> .pop

Two vintages, no shared format: 2010 PL is fixed-width 500-char records, 2020
PL is pipe-delimited with 97 fields, 2000 SF1 needs a join to a data segment
and writes internal points as integers scaled by a million. Offsets are
documented in the module docstrings and were verified against Colorado, whose
blocks sum to the published state total in every year.

Apportionment (`usa/tools/apportion.py`) is Huntington-Hill on the
apportionment population — resident population plus overseas federal
employees, which is *not* the districting base. Three house-size rules are
implemented (`fixed` 435, `cuberoot`, `wyoming`) and four inclusion variants
(DC and Puerto Rico, in or out). The canonical set is `fixed`, no DC, no PR.

## 4. Districting

    python3 usa/tools/run_all.py --model uniform --metric span

Writes `usa/plans/{year}_{state}_{seats}_{model}_{metric}.json`. The model is
in the filename so a plan is identifiable outside its directory.

Two axes, both real:

- **Population model.** `uniform` spreads each block's population over an
  equal-area disc (`--subdiv 10000`); `point` treats it as a point mass.
  Uniform is better and is canonical; point is kept because it is what the
  Center for Range Voting used, and reproducing their maps requires it.
- **Cut metric.** `span` measures the straight-line length of a cut including
  water; `land` measures only the land crossed. **The CRV uses `span`** — this
  was established by measurement, not assumption: the Michigan-to-Louisiana
  cut passes 8 km from Indianapolis under `span` and 56 km under `land`, and
  the published map shows it through Indianapolis.

A plan file records the gnomonic projection (`lon0`, `lat0`, and `lon_shift`
for Alaska, which straddles the antimeridian) and the cut tree as nodes
carrying `nx`, `ny`, `c` half-plane coefficients. Assigning any point to a
district is a walk down that tree — which is why plans need no crosswalk to
score data from a different census vintage.

## 5. Rendering

    python3 usa/tools/partisan_map.py --insets --margin 0.10 \
        --inset-size 0.10 --pan-x 0.03 --out <path> --title "<title>"

**Those three numeric flags are load-bearing.** At the defaults the map fills
the canvas, `place_boxes` finds no free rectangle for the metro insets, and
the tool prints "no room for New York" and carries on — a silent degradation
that looks like a code regression and is not. They are recorded here because
they were previously written down nowhere.

Other renderers: `shared/tools/svg_map.py` (exact polygons; verified against
Illinois, where 18 districts sum to the state area to 6 decimal places),
`shared/tools/animate.py` (GIF, one cut per frame, single engine pass so the
palette is stable), `usa/tools/make_anims.py`, `usa/tools/make_views.py`
(rebuilds the symlink views under `usa/maps/`).

## 6. Vote scoring

    python3 usa/tools/block_votes.py  --map actual --contest E_12_PRES ...
    python3 usa/tools/score_matrix.py --enacted --out results

`block_votes.py` scores one (plan, contest) pair and is the validated
reference implementation. `score_matrix.py` scores the whole matrix in one
pass over the data — it opens each state once and walks every plan and
aggregates every contest against it, because re-reading 3.9 GB of geoheaders
per contest is the dominant cost.

**Validation.** Scoring the enacted 113th-Congress plan with 2012
presidential votes must return **209 D / 226 R**. That is the published count
of districts carried by Obama in 2012 and it is exact, so any error in the
block-to-district join shows up as a wrong number rather than a crash. Note
this is *districts carried*, not seats won — Democrats won 201 seats that year.

Three things this step gets right that a naive version gets wrong:

- **Never allocate county totals by population.** Sixty per cent of Americans
  live in a county spanning more than one district; population-proportional
  allocation erases the sorting inside a county and returned 239 D on the
  enacted 2012 map, a 30-seat error, larger than the effect being measured.
- **Two census vintages.** Election data is on 2020 blocks; the enacted-plan
  equivalency file is on 2010 blocks, and the IDs name different ground.
  Joined by nearest centroid, with the error measured rather than assumed:
  0.23% of votes lie more than 1 km from the nearest 2010 block.
- **The MEDSL file has two silent traps.** The 2024 revision renamed `FIPS` to
  `county_fips` and upper-cased party values (a reader written for the old
  file reports zero votes, not an error); and 3,282 keys carry both a `TOTAL`
  row and per-mode rows, so summing everything double-counts.

At-large states need no block data at all: the state has one district, so the
statewide total settles it exactly. This is why `E_12_PRES` is complete
despite DRA lacking block files for AK, DE, MT, ND, SD, VT and WY — those are
precisely the one-district states.

## 7. Demographics

    python3 usa/tools/demographics.py --census 2010 --enacted

Voting-age population by race and Hispanic origin per district, from PL 94-171
table P4 ("not Hispanic or Latino, by race, for the population 18 years and
over"), which makes the categories mutually exclusive and exhaustive. Counts
districts at the >50% (majority), 40-50% (opportunity) and 30-40% (influence)
thresholds. The metric follows Haas, Miller & Kimbrough (*Electoral Studies*
79, 2022), so the numbers are comparable to published work.

---

## What each committed artifact was made from

| Artifact | Made by | From |
|---|---|---|
| `usa/plans/*.json` | `run_all.py` + engine | PL 94-171 / SF1, boundaries, apportionment tables |
| `usa/maps/index.json` | `make_views.py` | `plans/`, `renders/` |
| `usa/results/*.json` | `score_matrix.py` | `plans/`, DRA block data, cd113 BEF, MEDSL |
| `usa/results/demographics/*` | `demographics.py` | `plans/`, PL 94-171, cd113 BEF |
| `usa/upstream/MANIFEST.*` | `make_manifest.py` | the fetched tree |
| `docs/*` | hand-written | — |

Licences differ by artifact and are not a repository-level answer: plans are
CC-BY-4.0 (census-derived, all public domain inputs); anything touching DRA
election data is CC-BY-SA-4.0, because DRA's data is share-alike. Each map
image carries its own credit line, generated from the `share_alike` fields in
`SOURCES.json` rather than hard-coded, so it cannot drift from the record.

## Determinism

The engine is deterministic: same inputs, same flags, same plan. There is no
random seed anywhere in the districting path. Two things are *not* bit-stable
and should not be checksummed:

- **GIF assembly** quantises to an adaptive palette, which depends on the
  Pillow version.
- **Inset placement** depends on the rendered canvas, so a font or Pillow
  change can move a box by a few pixels.

Plans and scorings are bit-stable and can be checksummed.
