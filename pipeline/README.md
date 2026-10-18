# Pipeline

The offline Python pipeline. Every stage follows the same contract: read a raw
artifact as-is, validate loudly, emit stable outputs plus lineage.

## `fetch/` — Layer 1 acquisition

- `fetch_sources.py` — registry of every Layer 1 source with its acquisition class
  (direct / manual / api / build). Auto-pulls the direct ones into `data/raw/`
  atomically, rejects HTML error pages and truncated files, and records provenance
  in `data/raw/fetch_manifest.json`. Stdlib only.

## `ingest/` — endpoint translators

One script per data source. Input: a vendor artifact exactly as published.
Output: tidy CSVs and a `manifest.json` recording source, year, schema, counts,
and warnings.

- `ingest_bah_ascii.py` — DTMO BAH ASCII release (`BAH-ASCII-YYYY.zip`).
  Emits `zip_mha.csv`, `zip_mha_geo.csv`, `mha_names.csv`, `bah_rates.csv`.

- `ingest_rate_components.py` — DTMO BAH Rate Component Breakdown PDF (A6 -> B5).
  Emits `rate_components.csv` (rent and utilities share per MHA) + manifest;
  cross-checks MHA codes against `mha_names.csv`.

The Zillow and HUD translators live in `benchmarks/`, because for those sources
translating and rolling up to the MHA are one step.

## `geometry/` — spatial associators

Turns tabular keys into map geometry.

- `build_mha_geometry.py` — dissolves Census ZCTA polygons up to the MHA level
  using the ZIP-to-MHA crosswalk (B6). Emits a GeoPackage + GeoJSON, a coverage
  report, and `mha_YYYY_geometry_manifest.json` with input and output SHA-256.
  With `--classes ccg,unknown` (`make non-mha`) the same dissolve builds the
  County Cost Group and territory-bucket polygons (B28) from the B1 crosswalk
  into `non_mha_YYYY.gpkg` / `.geojson`, each feature marked non-authoritative.
  It stops if any ZCTA would belong to two areas, and its manifest lists area
  codes left without a polygon and the territory bucket's ZIP3 prefixes. B6 and
  B28 are separate runs, so B6 and the spatial statistics never change with B28.

## `benchmarks/` — 2.3 MHA benchmarks and 2.4 ownership metrics

ZIP-level cost benchmarks rolled up to the MHA through the B1 crosswalk. Run all
four with `make benchmarks` (after `make ingest` and `make components`); outputs
go to `data/interim/benchmarks_YYYY/`.

- `mha_agg.py` — shared rule: real MHAs only, MHA value = median of its ZIP
  values (unweighted), every MHA gets a row with its ZIP coverage, including
  MHAs with no data. Stdlib only.
- `zillow_to_mha.py` — Zillow ZORI (A3 -> B8) and ZHVI (A4 -> B9). Averages each
  ZIP over a pinned window (default: the BAH calendar year), then aggregates.
  For ZORI, grosses rent up to utilities-inclusive with the B5 rent share:
  `zori_utilities_adjusted = zori_median / rent_share`.
- `safmr_to_mha.py` — HUD SAFMR workbook (A5 -> B10), 0-4 bedrooms, long format.
  Matches HUD's line-wrapped headers and stops with the headers it saw if the
  layout changes.
- `tax_insurance_to_mha.py` (with `fio_insurance.py`) — A8: per-MHA effective
  property-tax rate from the A9 ACS pull (aggregate taxes / aggregate value over
  the MHA's ZCTAs) and homeowners premium from the Treasury FIO workbook (median
  of the MHA's published ZIPs), each flagged `locality` or `state_fallback`
  (`make taxins`). Stops if the ACS vintage differs from `config/ownership.json`.
- `ownership_cost.py` — monthly cost of owning the B9 home value (B11): VA
  loan amortised at the window-average PMMS 30-year rate (A7), plus the MHA's
  property tax and insurance from `mha_tax_insurance.csv`, and B8 utilities.
  Parameters are in `config/ownership.json`, explained in
  `docs/configuration.md`.

Tests for all five run on synthetic fixtures with `make test`.

## `metrics/` — 2.5 computed metrics

- `coverage_metrics.py` — B12-B15 in one run (`make metrics`, after
  `make benchmarks`). For each A12 profile and real MHA, tests BAH against its
  statutory design (37 U.S.C. 403(b)(3): local cost minus 5% of the *national*
  average for the grade): adequacy ratio = (BAH + member cost share) / cost,
  target 1.00, plus the dollar gap vs design, the plain coverage ratio, and a
  fixed-95% sensitivity column. Rent mode uses B8 utilities-adjusted ZORI with a
  bedroom-matched B10 SAFMR cross-check; buy mode uses B11 ownership cost. Stops if B8 and B9 cover different months or if B11
  was built from different B8/B9 files than the ones beside it. Outputs go to
  `data/interim/metrics_YYYY/`. Stdlib only.

## `spatial/` — 2.6 spatial statistics

Tests hypothesis H1 (adequacy gaps cluster in space) on the CONUS MHAs; AK, HI and
territory codes are excluded. Run both with `make spatial` (after `make geometry`
and `make metrics`); outputs go to `data/interim/spatial_YYYY/`. Needs libpysal and
esda (PySAL); matplotlib for the map.

- `build_weights.py` — B16 (`make weights`). k-nearest-neighbour weights (k = 6)
  between MHA representative points in EPSG:5070, ties broken on MHA code. Queen
  contiguity is built as a diagnostic: MHAs separated by County Cost Group counties
  touch no other MHA, and the manifest counts those islands.
- `spatial_stats.py` — B17 and B18 for every A12 profile × rent/buy ×
  `adequacy_gap` (primary) / `flat95_gap` (sensitivity): global Moran's I with a
  k = 4 / k = 8 / queen sensitivity check, LISA clusters (A13 codes) with a
  Benjamini-Hochberg FDR column, and Getis-Ord Gi* hot and cold spots. Fixed seed
  and permutation count, so a rerun gives the same result. Stops if B16 was built
  from a different B6 file. Draws the LISA cluster map of the primary test.

## `tiles/` — web tiles

- `build_mha_pmtiles.py` — tiles the B6 and B28 polygons together into
  `areas_YYYY.pmtiles` (B7) with tippecanoe, in one run so shared borders match.
  One layer, `areas`, with two properties: `code` (the join key) and `class`
  (`mha`, `ccg`, `unknown`); the frontend joins metrics with
  `promoteId: "code"` + feature-state (decision D9, data contract section 4).
- `build_basemap.sh` — extracts a bounding box from a Protomaps daily planet
  build into `basemap.pmtiles` (A11 -> C4) with the pmtiles CLI.

## Verifying a build

`make verify` (`tools/verify_hashes.py`) checks every SHA-256 the manifests
record: committed evidence copies, config hashes, the chain from fetched raw
files through each stage, and, where `data/` holds pipeline output, the live
files. Run it after `make evidence`; it should end with "all recorded hashes
agree".

## `check_config.py`

Validates `config/profiles.json` (A12) and `config/classification.json` (A13):
pay grades exist in the BAH release, bedroom counts fit SAFMR, class breaks,
colours, labels, metric roles and modes, and the cluster legend and FDR marker
line up. It also keeps the two files to values only: explanations live in
[`docs/configuration.md`](../docs/configuration.md), because stages record each
config's SHA-256 and a wording edit would otherwise make the evidence stale.

## Convention for new scripts

Copy the shape of `ingest_bah_ascii.py`: locate canonical inputs, parse to a
documented spec, fail loudly on schema drift, write tidy outputs, record a
manifest. The part that changes per source is the schema/validation guard.
