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

Run `python pipeline/fetch/fetch_sources.py --list` for the full registry.
