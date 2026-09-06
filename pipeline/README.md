# Pipeline

The offline Python pipeline. Two stages today; both follow the same contract:
read a raw artifact as-is, validate loudly, emit stable outputs plus lineage.

## `ingest/` — endpoint translators

One script per data source. Input: a vendor artifact exactly as published.
Output: tidy CSVs and a `manifest.json` recording source, year, schema, counts,
and warnings.

- `ingest_bah_ascii.py` — DTMO BAH ASCII release (`BAH-ASCII-YYYY.zip`).
  Emits `zip_mha.csv`, `zip_mha_geo.csv`, `mha_names.csv`, `bah_rates.csv`.

Planned: `ingest_zillow_zori.py`, `ingest_hud_fmr.py`, `ingest_census_zcta.py`.

## `geometry/` — spatial associators

Turns tabular keys into map geometry.

- `build_mha_geometry.py` — dissolves Census ZCTA polygons up to the MHA level
  using the ZIP-to-MHA crosswalk. Emits a GeoPackage + GeoJSON with a coverage
  report.

## Convention for new scripts

Copy the shape of `ingest_bah_ascii.py`: locate canonical inputs, parse to a
documented spec, fail loudly on schema drift, write tidy outputs, record a
manifest. The part that changes per source is the schema/validation guard.
