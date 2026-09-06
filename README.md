# BAH Atlas

*Working title — see naming note in project docs.*

An open, reproducible atlas of how far the U.S. military **Basic Allowance for
Housing (BAH)** stretches against real local housing costs — showing where the
allowance meets its statutory coverage target and where it falls short, mapped
across every Military Housing Area (MHA).

BAH is designed to cover roughly 95% of local housing costs (a deliberate ~5%
member cost-share). This project measures realized coverage against an
independent housing-cost benchmark and characterizes where the gaps cluster in
space.

## Research question

> To what degree do BAH rates achieve their statutory coverage target relative
> to an independent housing-cost benchmark, and are the resulting adequacy gaps
> spatially clustered across U.S. Military Housing Areas rather than randomly
> distributed?

See `docs/research-proposal.md` for the full framing, method, and scope.

## How it works

A Python offline pipeline turns public data endpoints into static, web-ready
files; a MapLibre GL JS frontend renders them from a CDN. No live API calls at
request time.

```
data endpoint --> ingest (tidy CSVs) --> geometry (MHA polygons) --> tiles/JSON --> map
```

## Data sources

Each layer is attributed to its source:

- **BAH rates & ZIP-to-MHA crosswalk** — DoD Defense Travel Management Office (DTMO)
- **MHA geometry** — synthesized from U.S. Census ZIP Code Tabulation Areas (ZCTAs)
- **Rent benchmark** — Zillow Observed Rent Index (ZORI)
- **Home-value benchmark** — Zillow Home Value Index (ZHVI)
- **Affordability reference** — HUD Fair Market Rents (FMR / SAFMR)
- **Income / price context** — U.S. Census ACS, BEA Regional Price Parities (RPP)

## Repository layout

```
bah-atlas/
├── data/
│   ├── raw/         vendor artifacts as downloaded (gitignored)
│   ├── interim/     tidy parsed outputs (gitignored)
│   └── processed/   final web-ready geometry/tiles (gitignored)
├── pipeline/
│   ├── ingest/      endpoint translators: raw release -> tidy CSVs + manifest
│   └── geometry/    spatial builders: crosswalk + ZCTA -> MHA polygons
├── web/             MapLibre GL JS frontend (later)
├── docs/            research framing, data dictionary, attribution
└── tests/
```

## Quickstart

```bash
pip install -r requirements.txt

# Stage 1 — ingest the DTMO BAH ASCII release into tidy CSVs + manifest
python pipeline/ingest/ingest_bah_ascii.py \
    --zip data/raw/BAH-ASCII-2026.zip \
    --out data/interim/bah_2026

# Stage 2 — build MHA polygons (needs a Census ZCTA cartographic boundary file)
python pipeline/geometry/build_mha_geometry.py \
    --crosswalk data/interim/bah_2026/zip_mha_geo.csv \
    --zcta data/raw/cb_2020_us_zcta520_500k.shp \
    --out data/processed/mha_2026.gpkg
```

Or run both stages with `make` (see `Makefile`).

## Status

Early. The BAH ingestion translator is working and validated against the 2026
release (299 MHAs, tidy rate table, provenance manifest). Geometry builder is in
place pending the Census ZCTA input. Frontend not started.

## License

MIT — see `LICENSE`.
