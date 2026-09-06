# data/raw

Vendor artifacts exactly as downloaded. Contents are gitignored — this folder is
tracked only for its structure and this note. Do not edit files here; the
pipeline reads them read-only and writes to `data/interim/`.

Expected drops:

- `BAH-ASCII-YYYY.zip` — DTMO, from travel.dod.mil (BAH rates + ZIP-to-MHA)
- `cb_2020_us_zcta520_500k.shp` (+ `.shx .dbf .prj`) — Census ZCTA cartographic
  boundary file
- Zillow ZORI / ZHVI bulk CSVs, HUD FMR tables — added as those translators land
