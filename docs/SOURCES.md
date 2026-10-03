# Sources & Attribution

A living record of every external dataset, artifact, and concept incorporated into
BAH Atlas — what it is, who provides it, where it comes from, and how it is licensed.

**Maintenance:** Add an entry the moment a source is pulled or a concept is adopted,
not later. Each data source that lands in `data/raw/` should also carry its retrieval
URL, retrieval date, and SHA-256 in the raw provenance manifest; this file is the
human-readable companion to that manifest. Status is one of `[incorporated]`,
`[planned]`, or `[reference]`.

Fields per entry: **Provider · Link · Role · License · Notes**

---

## Data sources

### DoD BAH rates & ZIP→MHA crosswalk (BAH ASCII 2026)  `[incorporated]`
- **Provider:** Defense Travel Management Office (DTMO), U.S. Department of Defense
- **Link:** https://www.travel.dod.mil/Allowances/Basic-Allowance-for-Housing/ · data collection method: https://www.travel.dod.mil/Allowances/Basic-Allowance-for-Housing/BAH-Data-Collection/
- **Artifact:** `BAH-ASCII-2026.zip` (paste the exact download URL you used into the raw manifest)
- **Role:** Primary source. The BAH rate numerator and the authoritative ZIP-to-MHA crosswalk. Ingested by `pipeline/ingest/ingest_bah_ascii.py`.
- **License:** U.S. Government work; not subject to domestic copyright.
- **Notes:** 2026 rates effective 1 Jan 2026. Underlying rental cost data is collected for DTMO by contractor Robert D. Niehaus, Inc. (RDN). Non-military areas roll up into 39 County Cost Groups (CCGs).

### DoD BAH Rate Component Breakdown (rent vs. utilities split)  `[planned]`
- **Provider:** Defense Travel Management Office (DTMO), U.S. Department of Defense
- **Link:** https://www.travel.dod.mil/Portals/119/Documents/BAH/PDF_BAH-Rate-Component-Breakdown/2026-BAH-Rate-Component-Breakdown.pdf
- **Role:** DoD's own published rent/utilities percentage split per MHA. Directly addresses the construct-validity gap where BAH's 95% target includes utilities but Zillow ZORI excludes them — this lets the utilities component be isolated rather than assumed.
- **License:** U.S. Government work; not subject to domestic copyright.
- **Notes:** Published annually since the 2012 rates. PDF format; will need extraction to tidy form.

### U.S. Census 2020 ZCTA cartographic boundaries (1:500k)  `[planned]`
- **Provider:** U.S. Census Bureau
- **Link:** https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip · landing: https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html
- **Artifact:** `cb_2020_us_zcta520_500k.shp` (inside the zip)
- **Role:** Base geometry. Dissolved to MHA polygons via the DTMO crosswalk by `pipeline/geometry/build_mha_geometry.py`.
- **License:** U.S. Government work; not subject to domestic copyright.
- **Notes:** Single 2020 vintage (no annual reissue), stable across the 2026 cycle. 500k is pre-simplified for thematic web mapping. ZCTA-to-ZIP is approximate — not every DTMO ZIP has a matching ZCTA; quantify and disclose the join dropouts.

### Zillow Observed Rent Index (ZORI) — ZIP level  `[planned]`
- **Provider:** Zillow (Zillow Group, Inc.)
- **Link:** https://www.zillow.com/research/data/ (Rentals → ZORI → Geography: ZIP, smoothed)
- **Role:** Independent rent benchmark; denominator for the rent-mode coverage ratio.
- **License:** Free for public use; **attribution to Zillow required** (per Zillow terms of use).
- **Notes:** Asking rent, **excludes utilities** (known downward bias vs. BAH's utilities-inclusive target). ZIP coverage is incomplete, thin in rural areas — treat sparsity as data relevant to the clustering question, not just a footnote. Zillow occasionally changes CSV download paths, so do not hardcode the CDN filename; pin a dated snapshot in `data/raw/`.

### Zillow Home Value Index (ZHVI) — ZIP level  `[planned]`
- **Provider:** Zillow (Zillow Group, Inc.)
- **Link:** https://www.zillow.com/research/data/ (Home Values → ZHVI, mid-tier 35th–65th pct, SFR+condo, smoothed & seasonally adjusted → Geography: ZIP)
- **Role:** Independent home-value benchmark for buy mode.
- **License:** Free for public use; **attribution to Zillow required** (per Zillow terms of use).
- **Notes:** Same download-path and coverage caveats as ZORI. Buy-vs-rent construct-validity limits already documented in the research framing.

### HUD Small Area Fair Market Rents (SAFMR) / FMR  `[planned]`
- **Provider:** U.S. Department of Housing and Urban Development — Office of Policy Development & Research (HUD USER / PD&R)
- **Link:** SAFMR (ZIP-level): https://www.huduser.gov/portal/datasets/fmr/smallarea/index.html · FMR: https://www.huduser.gov/portal/datasets/fmr.html · API: https://www.huduser.gov/hudapi/public/fmr
- **Role:** Affordability reference and utilities-inclusive cross-check against ZORI.
- **License:** U.S. Government work; not subject to domestic copyright.
- **Notes:** FMR is **gross rent (includes utilities)** — conceptually closer to BAH's 95% target than ZORI. SAFMR is ZIP-keyed (xlsx), so no FMR-area crosswalk step. From FY2025 onward SAFMR covers metro **and** non-metro ZIPs. Prefer the bulk xlsx over the token-gated REST API for a clean offline pipeline.

### BEA Regional Price Parities (RPP)  `[planned]`
- **Provider:** U.S. Bureau of Economic Analysis (BEA)
- **Link:** https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area *(verify exact table endpoint before ingest)*
- **Role:** Price/cost-of-living context layer (secondary).
- **License:** U.S. Government work; not subject to domestic copyright.
- **Notes:** Not blocking anything now. Deep-link table URL less stable than the sources above — confirm at ingest time.

### U.S. Census American Community Survey (ACS)  `[planned]`
- **Provider:** U.S. Census Bureau
- **Link:** https://www.census.gov/programs-surveys/acs/data.html *(verify exact table/variable endpoint before ingest)*
- **Role:** Income and demographic context layer (secondary).
- **License:** U.S. Government work; not subject to domestic copyright.
- **Notes:** Not blocking anything now. Confirm exact variables/vintage at ingest time.

---

## Prior work & references

### "2019 BAH Rate by Location" — Tableau Public visualization  `[reference]`
- **Provider / Author:** *chairforceone* (Tableau Public author)
- **Link:** https://public.tableau.com/app/profile/chairforceone/viz/2019BAHMap/2019BAHRatebyLocation?publish=yes
- **Role:** Prior public visualization, cited for positioning by contrast. It is a **rate-display** map — it shows what the BAH rate *is* by location. It does not evaluate rates against an independent cost benchmark, compute a coverage ratio, or test for spatial clustering — which is precisely where BAH Atlas's contribution begins.
- **Notes:** Distinct from the datasets above: this is a reference to existing work, not a data input. Differentiators — proprietary (Tableau), 2019 (stale), rate-display only. Not verified against the live interactive contents (Tableau loads as a JS app); confirm specifics if citing formally.

---

## Concepts & methods

*Placeholder for methodological and statutory references adopted as the analysis develops
(e.g., the ~95% statutory coverage target and its cite, spatial-statistics method
references for Moran's I / LISA / Getis-Ord Gi*, and any benchmark-adjustment
approaches). Add each with its source as it is incorporated.*
