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

Planned: `ingest_zillow_zori.py`, `ingest_zillow_zhvi.py`, `ingest_hud_safmr.py`.

## `geometry/` — spatial associators

Turns tabular keys into map geometry.

- `build_mha_geometry.py` — dissolves Census ZCTA polygons up to the MHA level
  using the ZIP-to-MHA crosswalk. Emits a GeoPackage + GeoJSON with a coverage
  report.

## `tiles/` — web tiles

- `build_mha_pmtiles.py` — tiles the MHA polygons into `mha_YYYY.pmtiles`
  (B7) with tippecanoe. One layer, `mha`, whose only property is the MHA code;
  the frontend joins metrics with `promoteId: "mha"` + feature-state.
- `build_basemap.sh` — extracts a bounding box from a Protomaps daily planet
  build into `basemap.pmtiles` (A11 -> C4) with the pmtiles CLI.

## `check_config.py`

Validates `config/profiles.json` (A12) and `config/classification.json` (A13):
pay grades exist in the BAH release, bedroom counts fit SAFMR, class breaks,
colours, and labels line up.

## Convention for new scripts

Copy the shape of `ingest_bah_ascii.py`: locate canonical inputs, parse to a
documented spec, fail loudly on schema drift, write tidy outputs, record a
manifest. The part that changes per source is the schema/validation guard.
