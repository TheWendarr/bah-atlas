# data/raw

Vendor artifacts exactly as downloaded. Contents are gitignored — this folder is
tracked only for its structure and this note. Do not edit files here; the
pipeline reads them read-only and writes to `data/interim/`.

Expected drops (`make fetch` pulls every auto-pullable one and records URL,
sha256, size, and time in `fetch_manifest.json`):

- `BAH-ASCII-YYYY.zip` — A1, DTMO BAH rates + ZIP-to-MHA (manual download)
- `cb_2020_us_zcta520_500k.zip` — A2, Census ZCTA cartographic boundaries
- `Zip_zori_uc_sfrcondomfr_sm_month.csv` — A3, Zillow Observed Rent Index, ZIP level
- `Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv` — A4, Zillow Home Value Index, ZIP level
- `fy2026_safmrs_revised.xlsx` — A5, HUD Small Area FMRs FY2026 (revised)
- `dod_bah_rate_components_2026.pdf` — A6, DTMO BAH rate component breakdown
  (browser download: travel.dod.mil blocks scripts; `make fetch` then verifies it)
- `PMMS_history.csv` — A7, Freddie Mac PMMS weekly mortgage rates (direct from Freddie Mac)

- `2026-BAH_OOP_Amounts.pdf` — A12, DTMO member cost share by pay grade (browser download)
- `Supporting_Underlying_Metrics_and_Disclaimer_for_Analyses_of_US_Homeowners_Insurance_Markets_2018-2022.xlsx` — A8, Treasury FIO homeowners premiums by ZIP
- `acs5_2024_zcta.json` — A9, Census ACS 5-year query (tax, home value, population by ZCTA; needs `CENSUS_API_KEY`)

Run `python pipeline/fetch/fetch_sources.py --list` for the full registry.

**Archived copies.** The U.S. Government files above are also kept in the repository
in [`sources/`](../../sources/README.md) (`make sources-zip`). To restore them, unzip the
volumes and copy each `<node>/<file>` here; `make fetch` then validates them without
downloading. Zillow (A3, A4) and Freddie Mac (A7) files are listed there by URL and
SHA-256 only and must be downloaded from the provider.
