# Sources & Attribution

A living record of every external dataset, artifact, and concept incorporated into
BAH Atlas — what it is, who provides it, where it comes from, and how it is licensed.

**Maintenance:** Add an entry the moment a source is pulled or a concept is adopted,
not later. Each data source that lands in `data/raw/` should also carry its retrieval
URL, retrieval date, and SHA-256 in the raw provenance manifest
(`data/raw/fetch_manifest.json`, written by `make fetch`); this file is the
human-readable companion to that manifest. Status is one of `[incorporated]`,
`[planned]`, or `[reference]`.

Fields per entry: **Provider · Link · Artifact · Acquisition · Role · License · Notes · Verified**

Headings carry the node ID from the [work breakdown structure](WBS.md) (A = Layer 1 source).
Acquisition is one of: **auto** (pulled by `make fetch`), **browser** (the host blocks
scripted downloads; save it once from a web browser into `data/raw/` and `make fetch`
validates and checksums it), **api**, or **build** (produced by a local build step).

---

## Data sources

### A1 · DoD BAH rates & ZIP→MHA crosswalk (BAH ASCII 2026)  `[incorporated]`
- **Provider:** Defense Travel Management Office (DTMO), U.S. Department of Defense
- **Link:** https://www.travel.dod.mil/Allowances/Basic-Allowance-for-Housing/ · rate-file download page (used by the fetcher registry): https://www.travel.dod.mil/Allowances/Basic-Allowance-for-Housing/BAH-Rate-Files-Alt/ · data collection method: https://www.travel.dod.mil/Allowances/Basic-Allowance-for-Housing/BAH-Data-Collection/
- **Artifact:** `data/raw/BAH-ASCII-2026.zip` (paste the exact download URL you used into the raw manifest)
- **Acquisition:** browser
- **Role:** Primary source. The BAH rate numerator and the authoritative ZIP-to-MHA crosswalk. Ingested by `pipeline/ingest/ingest_bah_ascii.py` into B1–B4.
- **License:** U.S. Government work; not subject to domestic copyright.
- **Notes:** 2026 rates effective 1 Jan 2026. Underlying rental cost data is collected for DTMO by contractor Robert D. Niehaus, Inc. (RDN). Non-military areas roll up into 39 County Cost Groups (CCGs). The current archive includes temporary TX270 rates (16 May–31 Dec 2026); re-pull and re-checksum if your copy predates that.

### A2 · U.S. Census 2020 ZCTA cartographic boundaries (1:500k)  `[incorporated]`
- **Provider:** U.S. Census Bureau
- **Link:** https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip · landing: https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html
- **Artifact:** `data/raw/cb_2020_us_zcta520_500k.zip` (`cb_2020_us_zcta520_500k.shp` inside; the geometry step reads the zip directly)
- **Acquisition:** auto
- **Role:** Base geometry. Dissolved to MHA polygons (B6) via the DTMO crosswalk by `pipeline/geometry/build_mha_geometry.py`.
- **License:** U.S. Government work; not subject to domestic copyright.
- **Notes:** Single 2020 vintage (no annual reissue), stable across the 2026 cycle. 500k is pre-simplified for thematic web mapping. ZCTA-to-ZIP is approximate — not every DTMO ZIP has a matching ZCTA; quantify and disclose the join dropouts.
- **Verified:** 2026-10-03 — URL live, serves a valid zip archive.

### A3 · Zillow Observed Rent Index (ZORI) — ZIP level  `[incorporated]`
- **Provider:** Zillow (Zillow Group, Inc.)
- **Link:** https://files.zillowstatic.com/research/public_csvs/zori/Zip_zori_uc_sfrcondomfr_sm_month.csv · landing: https://www.zillow.com/research/data/ (Rentals → ZORI, all homes plus multifamily, smoothed → Geography: ZIP)
- **Artifact:** `data/raw/Zip_zori_uc_sfrcondomfr_sm_month.csv` (vendor filename; current copy pulled 2026-09-07)
- **Acquisition:** auto
- **Role:** Independent rent benchmark; denominator for the rent-mode coverage ratio (via B8).
- **License:** Free for public use; **attribution to Zillow required** (per Zillow terms of use).
- **Notes:** Asking rent, **excludes utilities** (known downward bias vs. BAH's utilities-inclusive target; corrected with A6 → B5). No bedroom breakdown: one series applies to every profile. Wide layout — RegionID, SizeRank, RegionName (ZIP; may lose leading zeros), RegionType, StateName, State, City, Metro, CountyName, then one column per month. ZIP coverage is incomplete and thin in rural areas — treat sparsity as data relevant to the clustering question, not just a footnote. Zillow occasionally moves its CSV paths: the fetcher pins the current path, and if it moves the pull fails loudly (HTML and size checks) instead of saving a bad file. Each pull's SHA-256 and date in the fetch manifest is the dated snapshot.
- **Verified:** 2026-10-03 — URL live, serves CSV text.

### A4 · Zillow Home Value Index (ZHVI) — ZIP level  `[incorporated]`
- **Provider:** Zillow (Zillow Group, Inc.)
- **Link:** https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv · landing: https://www.zillow.com/research/data/ (Home Values → ZHVI, mid-tier 35th–65th pct, SFR+condo, smoothed & seasonally adjusted → Geography: ZIP)
- **Artifact:** `data/raw/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv` (vendor filename; current copy pulled 2026-09-07)
- **Acquisition:** auto
- **Role:** Independent home-value benchmark for buy mode (via B9 → B11).
- **License:** Free for public use; **attribution to Zillow required** (per Zillow terms of use).
- **Notes:** Same layout, download-path, and coverage caveats as ZORI. Bedroom-count variants follow `Zip_zhvi_bdrmcnt_<N>_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv` if buy mode needs a bedroom-matched anchor. Buy-vs-rent construct-validity limits already documented in the research framing.
- **Verified:** 2026-10-03 — URL live, serves CSV text.

### A5 · HUD Small Area Fair Market Rents (SAFMR) FY2026, revised  `[incorporated]`
- **Provider:** U.S. Department of Housing and Urban Development — Office of Policy Development & Research (HUD USER / PD&R)
- **Link:** https://www.huduser.gov/portal/datasets/fmr/fmr2026/fy2026_safmrs_revised.xlsx · landing: https://www.huduser.gov/portal/datasets/fmr/smallarea/index.html · FMR: https://www.huduser.gov/portal/datasets/fmr.html · API: https://www.huduser.gov/hudapi/public/fmr
- **Artifact:** `data/raw/fy2026_safmrs_revised.xlsx` (vendor filename)
- **Acquisition:** auto
- **Role:** Affordability reference and utilities-inclusive cross-check against ZORI (via B10), selected by each profile's anchor bedroom count.
- **License:** U.S. Government work; not subject to domestic copyright.
- **Notes:** FMR is **gross rent (includes utilities)**, set by HUD at the 40th percentile of standard-quality recent-mover rents, so it is a lower anchor than a typical market rent — conceptually closer to BAH's 95% target than ZORI. SAFMR is ZIP-keyed with 0–4 bedroom columns, so no FMR-area crosswalk step. From FY2025 onward SAFMR covers metro **and** non-metro ZIPs. **Vintage choice:** the *revised* FY2026 release (effective 21 May 2026) is used as the current authoritative version; the original (effective 1 Oct 2025) is `fy2026_safmrs.xlsx` in the same folder. Record this for temporal alignment against 2026 BAH (effective 1 Jan 2026). Prefer the bulk xlsx over the token-gated REST API for a clean offline pipeline.
- **Verified:** 2026-10-03 — full download returns HTTP 200, 4.4 MB Excel workbook. (HUD answers partial/range requests with an empty 202; the fetcher uses full downloads.)

### A6 · DoD BAH Rate Component Breakdown 2026 (rent vs. utilities split)  `[incorporated]`
- **Provider:** Defense Travel Management Office (DTMO), U.S. Department of Defense
- **Link:** https://www.travel.dod.mil/Portals/119/Documents/BAH/PDF_BAH-Rate-Component-Breakdown/2026-BAH-Rate-Component-Breakdown.pdf
- **Artifact:** `data/raw/dod_bah_rate_components_2026.pdf`
- **Acquisition:** browser — travel.dod.mil returns HTTP 403 to scripted clients, even with browser headers. Open the link in a browser, save it under the artifact name, then run `make fetch` to validate and checksum it.
- **Role:** DoD's own published rent/utilities percentage split per MHA. Directly addresses the construct-validity gap where BAH's 95% target includes utilities but Zillow ZORI excludes them — this lets the utilities component be isolated rather than assumed. Parsed into B5 by `pipeline/ingest/ingest_rate_components.py`.
- **License:** U.S. Government work; not subject to domestic copyright.
- **Notes:** Published annually since the 2012 rates. One row per MHA (299): code and name, rent and utilities as average % of total housing cost (DTMO: "the average percentage that rent and utilities make of the total housing cost"). Percentages are rounded to 1%, so the derived shares carry about ±0.5 percentage points of precision; DTMO notes that a member's actual split may differ from the average.
- **Verified:** 2026-10-03 — document confirmed at this URL (299 MHA rows); scripted download blocked (403).

### A12 parameter · DTMO 2026 BAH Out-of-Pocket Amounts (member cost share)  `[incorporated]`
- **Provider:** Defense Travel Management Office (DTMO), U.S. Department of Defense
- **Link:** https://www.travel.dod.mil/Portals/119/Documents/BAH/PDF_BAH_OOP_Amounts/2026-BAH_OOP_Amounts.pdf · statute: https://www.law.cornell.edu/uscode/text/37/403
- **Artifact:** `data/raw/2026-BAH_OOP_Amounts.pdf` (SHA-256 `375ff25e…20c3`, pinned in the fetcher)
- **Acquisition:** browser — travel.dod.mil blocks scripted clients, as for A1 and A6.
- **Role:** The statutory target. 37 U.S.C. 403(b)(3) sets BAH = local cost of adequate housing − a percentage (5% since 2019) of the *national* average cost for the pay grade and dependency status. This table gives that deduction in dollars per grade; E05 with dependents ($126/month) and O03 with dependents ($151/month) are recorded as `cost_share_monthly` in `config/profiles.json` (A12) and used by B12–B15: adequacy ratio = (BAH + cost share) / benchmark, target 1.00.
- **License:** U.S. Government work; not subject to domestic copyright.
- **Notes:** DTMO: "5% of the National Mean BAH Rate for each paygrade." The same dollars apply at every duty station, so BAH covers exactly 95% of local cost only where local cost equals the national mean. 2026 amounts range $93–$212/month across grades (DoD 2026 BAH release). Published annually; the 2024 edition gave E05 $118 and O03 $141 with dependents.
- **Verified:** 2026-10-17 — PDF saved from a browser; E05 and O03 rows read with `pdftotext`.

### A7 · Freddie Mac Primary Mortgage Market Survey (PMMS), weekly history  `[incorporated]`
- **Provider:** Freddie Mac
- **Link:** https://www.freddiemac.com/pmms/docs/PMMS_history.csv · landing: https://www.freddiemac.com/pmms
- **Artifact:** `data/raw/PMMS_history.csv` (vendor filename)
- **Acquisition:** auto
- **Role:** Interest rate for amortizing ZHVI into a monthly ownership cost (B11, buy mode).
- **License:** Freddie Mac data; **attribution required** — cite as Freddie Mac, Primary Mortgage Market Survey (PMMS).
- **Notes:** Weekly since 2 April 1971. Columns: `date` (M/D/YYYY), `pmms30` (30-year fixed rate, %), `pmms30p` (points), `pmms15`, `pmms15p`, and 5/1 ARM fields (`pmms51`, `pmms51p`, `pmms51m`, `pmms51spread`); blank cells may contain a single space. PMMS methodology changed on 17 Nov 2022; account for the break in any multi-year comparison. **Source change:** this replaces the FRED mirror (`fredgraph.csv?id=MORTGAGE30US`), which silently drops scripted requests — curl over HTTP/2, HTTP/1.1, and IPv4, and Python urllib, all timed out with 0 bytes on 2026-10-03. Freddie Mac is the original publisher, which also makes for a cleaner citation.
- **Verified:** 2026-10-03 — HTTP 200, 97 KB CSV, latest observation 1 Oct 2026 (30-year 7.28%).

### A11 · Protomaps basemap (OpenStreetMap-derived)  `[incorporated]`
- **Provider:** Protomaps (basemap build); map data © OpenStreetMap contributors
- **Link:** daily planet builds at `https://build.protomaps.com/YYYYMMDD.pmtiles` · docs: https://docs.protomaps.com/basemaps/downloads
- **Artifact:** `data/processed/basemap.pmtiles` + `basemap_provenance.json` (build date, bounding box, max zoom, SHA-256)
- **Acquisition:** build — `make basemap` (`pipeline/tiles/build_basemap.sh`) extracts a CONUS bounding box from the newest daily build with the pmtiles CLI; only the needed tiles are downloaded.
- **Role:** Self-hosted basemap under the MHA choropleth (served as C4), so no third-party tile API key is needed.
- **License:** Open Database License (ODbL) Produced Work. **Attribution required on the map:** "© OpenStreetMap contributors" and Protomaps.
- **Notes:** Daily builds are retained for about a week, so the provenance JSON records exactly which build was cut.
- **Verified:** 2026-10-03 — build `20261002` available.

### A10 · BEA Regional Price Parities (RPP)  `[planned]`
- **Provider:** U.S. Bureau of Economic Analysis (BEA)
- **Link:** https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area · API: https://apps.bea.gov/api/
- **Acquisition:** api — pull the Regional dataset (RPP table) through the BEA API with pinned year and table parameters (free API key).
- **Role:** Price/cost-of-living context layer (secondary; optional node).
- **License:** U.S. Government work; not subject to domestic copyright.
- **Notes:** Not blocking anything now. Interactive-table deep links are less stable than API pulls — do not save an iTable URL as the source.

### A9 · U.S. Census American Community Survey (ACS)  `[planned]`
- **Provider:** U.S. Census Bureau
- **Link:** https://www.census.gov/programs-surveys/acs/data.html · API: https://api.census.gov/data/
- **Acquisition:** api — query the Census Data API with a pinned year and variable list.
- **Role:** Income and demographic context layer (secondary; optional node).
- **License:** U.S. Government work; not subject to domestic copyright.
- **Notes:** Not blocking anything now. Confirm exact variables/vintage at ingest time; do not save a data.census.gov table URL as the source.

---

## Software & tools

Third-party software the pipeline and project tooling run. None of it is redistributed
with the project; each is installed separately (`requirements.txt` for the Python
packages). Licenses were read from each project's license file or package metadata on
2026-10-17.

### pandas  `[incorporated]`
- **Provider:** pandas development team — https://pandas.pydata.org
- **Role:** Tabular reads and joins in the ingest translators (B1–B4) and benchmark steps.
- **License:** BSD-3-Clause.

### GeoPandas (with Shapely, pyproj, GDAL)  `[incorporated]`
- **Provider:** GeoPandas developers — https://geopandas.org
- **Role:** Reads the ZCTA shapefile (A2) and dissolves ZCTA polygons to MHA polygons (B6) in `pipeline/geometry/build_mha_geometry.py`.
- **License:** GeoPandas BSD-3-Clause; Shapely BSD-3-Clause; pyproj MIT; GDAL MIT (installed with the wheels).

### pypdf  `[incorporated]`
- **Provider:** pypdf contributors — https://pypi.org/project/pypdf/
- **Role:** Extracts text from the DTMO rate component breakdown PDF (A6 → B5) in `pipeline/ingest/ingest_rate_components.py`.
- **License:** BSD-3-Clause.
- **Notes:** Poppler's `pdftotext -layout` is the fallback extractor when pypdf is not installed (GNU GPL; called as an external program). `pdftotext` was also used to read the E05 and O03 rows of the 2026 out-of-pocket table.

### openpyxl  `[incorporated]`
- **Provider:** openpyxl developers — https://pypi.org/project/openpyxl/
- **Role:** Reads the HUD SAFMR workbook (A5 → B10) in `pipeline/benchmarks/safmr_to_mha.py`.
- **License:** MIT.

### tippecanoe  `[incorporated]`
- **Provider:** Felt (maintained fork; originally Mapbox) — https://github.com/felt/tippecanoe
- **Role:** Tiles the MHA polygons into a PMTiles archive (B6 → B7) in `pipeline/tiles/build_mha_pmtiles.py`; version 2.17 or later writes `.pmtiles` directly.
- **License:** BSD-2-Clause (© Mapbox Inc., © Protomaps LLC).

### pmtiles CLI (go-pmtiles)  `[incorporated]`
- **Provider:** Protomaps LLC — https://github.com/protomaps/go-pmtiles
- **Role:** Cuts the CONUS basemap extract from a Protomaps daily build (A11) in `pipeline/tiles/build_basemap.sh`.
- **License:** BSD-3-Clause.

### GitHub CLI (`gh`)  `[incorporated]`
- **Provider:** GitHub, Inc. — https://cli.github.com
- **Role:** Project tooling only: `make wbs-sync` mirrors the WBS milestones and node issues to GitHub (`tools/wbs_sync_github.py`). Not part of the data pipeline.
- **License:** MIT.

### libpysal  `[incorporated]`
- **Provider:** PySAL developers — https://pysal.org/libpysal/
- **Role:** Spatial weights objects for 2.6: the k-nearest-neighbour weights (B16, built from MHA representative points in `pipeline/spatial/build_weights.py`) and the queen contiguity weights used as a diagnostic and as a sensitivity check (B16, B17).
- **License:** BSD-3-Clause (package metadata, read 2026-10-18).
- **Notes:** Requires 4.10 or later. Cite the PySAL ecosystem paper (see *Concepts & methods*).

### esda (Exploratory Spatial Data Analysis)  `[incorporated]`
- **Provider:** PySAL developers — https://pysal.org/esda/
- **Role:** Global Moran's I (B17), local Moran's I / LISA and Getis-Ord Gi\* (B18) in `pipeline/spatial/spatial_stats.py`, with permutation inference.
- **License:** BSD-3-Clause (package metadata, read 2026-10-18).
- **Notes:** Requires 2.10 or later: the local tests set `alternative="two-sided"` explicitly, because esda is changing the default alternative hypothesis for conditional randomization between releases and an unpinned default would change the p-values on upgrade.

### Matplotlib  `[incorporated]`
- **Provider:** Matplotlib Development Team — https://matplotlib.org
- **Role:** Draws the LISA cluster map of the primary 2.6 test (`mha_lisa_e5_dep_rent_map.png`) that `make evidence` copies into `docs/evidence/` for the progress notes. Optional: the pipeline skips the map without it.
- **License:** Matplotlib License (based on the PSF license; OSI-approved).

### MapLibre GL JS  `[planned]`
- **Provider:** MapLibre contributors — https://github.com/maplibre/maplibre-gl-js
- **Role:** Front-end map runtime for Layer 3 (C-nodes): renders the B7 MHA tiles and the A11 basemap, joining B20 attributes with feature-state.
- **License:** BSD-3-Clause (includes the BSD-3-Clause notice for Mapbox GL JS v1.13 and earlier, from which it was forked).

---

## Prior work & references

### "2019 BAH Rate by Location" — Tableau Public visualization  `[reference]`
- **Provider / Author:** *chairforceone* (Tableau Public author)
- **Link:** https://public.tableau.com/app/profile/chairforceone/viz/2019BAHMap/2019BAHRatebyLocation?publish=yes
- **Role:** Prior public visualization, cited for positioning by contrast. It is a **rate-display** map — it shows what the BAH rate *is* by location. It does not evaluate rates against an independent cost benchmark, compute a coverage ratio, or test for spatial clustering — which is precisely where BAH Atlas's contribution begins.
- **Notes:** Distinct from the datasets above: this is a reference to existing work, not a data input. Differentiators — proprietary (Tableau), 2019 (stale), rate-display only. Not verified against the live interactive contents (Tableau loads as a JS app); confirm specifics if citing formally.

---

## Concepts & methods

### Statutory basis of BAH: 37 U.S.C. § 403  `[incorporated]`
- **Provider:** U.S. Code, Title 37 (Pay and Allowances of the Uniformed Services), § 403 — https://www.law.cornell.edu/uscode/text/37/403
- **Role:** Defines what BAH is meant to cover, and therefore the target the project tests. Section 403(b)(3) sets BAH = local cost of adequate housing − a percentage (5% since 2019) of the national average cost for the pay grade and dependency status. Since 17 Oct 2026 this is the basis of the primary test variable: adequacy ratio = (BAH + cost share) / benchmark, target 1.00 (B12–B15; see the A12 out-of-pocket entry for the dollar amounts).
- **License:** U.S. law; public domain.
- **Notes:** Replaces the flat "R ≈ 0.95" target in the original research proposal, which is kept as a sensitivity column (`flat95_gap`). Pending instructor approval; see the [17 Oct progress note](progress/2026-10-17.md).

### DoD BAH housing standards by pay grade  `[incorporated]`
- **Provider:** U.S. Department of Defense (BAH Primer); summarized at https://www.military.com/paycheck-chronicles/2014/12/04/much-house-rate
- **Role:** Basis for the anchor dwelling and bedroom count of each housing profile in `config/profiles.json` (A12): E-5 → 2-bedroom townhouse; O-3 → 98% of the way from a 3-bedroom townhouse to a 3-bedroom single-family home.
- **Notes:** Cite the DoD BAH Primer directly in the formal write-up.

### ColorBrewer colour schemes  `[incorporated]`
- **Provider:** Cynthia A. Brewer, Pennsylvania State University — https://colorbrewer2.org
- **Role:** RdBu 7-class diverging palette used for the coverage-ratio and surplus classes in `config/classification.json` (A13); chosen because it is colour-blind safe.
- **License:** Apache License 2.0; credit ColorBrewer.

### VA home loan funding fee  `[incorporated]`
- **Provider:** U.S. Department of Veterans Affairs — https://www.va.gov/housing-assistance/home-loans/funding-fee-and-closing-costs/
- **Role:** Financing assumption for buy mode (B11, `config/ownership.json`): VA purchase loan, first use, 0% down, funding fee 2.15% financed into the loan, no mortgage insurance.
- **License:** U.S. Government work; not subject to domestic copyright.
- **Notes:** Rates effective 7 Apr 2023. Subsequent use with less than 5% down is 3.3%; members receiving VA disability compensation, and active-duty Purple Heart recipients, are exempt.
- **Verified:** 2026-10-08.

### National effective property tax rate (B11 placeholder)  `[incorporated]`
- **Provider:** National Association of Home Builders (NAHB) analysis of the 2024 American Community Survey — https://eyeonhousing.org/2025/11/property-taxes-by-state-2024/
- **Role:** Placeholder property tax in B11 until A8 lands: 0.89% of home value per year ($8.88 per $1,000).
- **Notes:** State rates run from about 0.31% (Hawaii) to 1.79% (Illinois); a single national rate is a stated limitation.
- **Verified:** 2026-10-08.

### National average homeowners insurance premium (B11 placeholder)  `[incorporated]`
- **Provider:** NAIC homeowners insurance report, as summarised by the Insurance Information Institute — https://www.iii.org/fact-statistic/facts-statistics-homeowners-and-renters-insurance
- **Role:** Placeholder insurance in B11 until A8 lands: $1,569 per year (HO-3 average, data year 2022).
- **Notes:** The newest NAIC data year available; premiums have risen since, so this understates 2026 cost.
- **Verified:** 2026-10-08.

### Global Moran's I  `[incorporated]`
- **Reference:** Moran, P. A. P. (1950). Notes on continuous stochastic phenomena. *Biometrika*, 37(1–2), 17–23. https://doi.org/10.1093/biomet/37.1-2.17
- **Role:** Global test for spatial autocorrelation in the adequacy gap (B17; hypothesis H1). Row-standardized KNN weights, permutation inference; also run on the flat-95% gap to measure how much autocorrelation the fixed-95% reading builds in.

### Local Indicators of Spatial Association (LISA)  `[incorporated]`
- **Reference:** Anselin, L. (1995). Local indicators of spatial association — LISA. *Geographical Analysis*, 27(2), 93–115. https://doi.org/10.1111/j.1538-4632.1995.tb00338.x
- **Role:** Local cluster and outlier classes for each MHA (B18: HH, LL, HL, LH, or NS at p < 0.05), using the cluster codes and colours in `config/classification.json` (A13); later the hotspot overlay (B27, C16).

### Getis-Ord G and Gi\* statistics  `[incorporated]`
- **References:** Getis, A., & Ord, J. K. (1992). The analysis of spatial association by use of distance statistics. *Geographical Analysis*, 24(3), 189–206. https://doi.org/10.1111/j.1538-4632.1992.tb00261.x · Ord, J. K., & Getis, A. (1995). Local spatial autocorrelation statistics: Distributional issues and an application. *Geographical Analysis*, 27(4), 286–306. https://doi.org/10.1111/j.1538-4632.1995.tb00912.x
- **Role:** Hot-spot and cold-spot detection for the adequacy gap (B18), alongside LISA.
- **Notes:** The 1992 paper introduces the G statistics; the 1995 paper gives the standardized Gi\* form usually reported in hotspot maps. B18 computes Gi\* on the adequacy ratio (= gap + 1): the standardized z-score is unchanged by adding a constant, and the unstandardized G divides by the sum of the variable, which is near zero for a gap (`tests/test_spatial.py` checks the equivalence).

### Spatial weights: k-nearest neighbours  `[incorporated]`
- **Reference:** Getis, A., & Aldstadt, J. (2004). Constructing the spatial weights matrix using a local statistic. *Geographical Analysis*, 36(2), 90–104. https://doi.org/10.1111/j.1538-4632.2004.tb01127.x
- **Role:** B16 uses k = 6 nearest neighbours between MHA representative points (EPSG:5070), CONUS only. MHAs are dissolves of DTMO's ZCTAs and the County Cost Group counties between them are not MHAs, so contiguity weights leave many MHAs with no neighbour; KNN gives every MHA the same number of neighbours. Queen contiguity is kept as a diagnostic (island count in `weights_manifest.json`) and, with k = 4 and k = 8, as a sensitivity check on B17.
- **Notes:** Getis & Aldstadt show that results depend on the weights specification, which is the reason for reporting the sensitivity check rather than one weights matrix.

### False discovery rate for local statistics  `[incorporated]`
- **References:** Benjamini, Y., & Hochberg, Y. (1995). Controlling the false discovery rate: A practical and powerful approach to multiple testing. *Journal of the Royal Statistical Society: Series B*, 57(1), 289–300. https://doi.org/10.1111/j.2517-6161.1995.tb02031.x · Caldas de Castro, M., & Singer, B. H. (2006). Controlling the false discovery rate: A new application to account for multiple and dependent tests in local statistics of spatial association. *Geographical Analysis*, 38(2), 180–208. https://doi.org/10.1111/j.0016-7363.2006.00682.x
- **Role:** B18 tests about 290 MHAs at once, so roughly 5% would read as significant by chance at p < 0.05. The Benjamini-Hochberg step-up procedure is applied to each test's LISA p-values and reported as `lisa_fdr_significant`, beside the conventional p < 0.05 cluster class; Caldas de Castro & Singer apply it to local spatial statistics.

### PySAL  `[incorporated]`
- **Reference:** Rey, S. J., Anselin, L., Amaral, P., Arribas-Bel, D., Cortes, R. X., Gaboardi, J. D., Kang, W., Knaap, E., Li, Z., Lumnitz, S., Oshan, T. M., Shao, H., & Wolf, L. J. (2022). The PySAL ecosystem: Philosophy and implementation. *Geographical Analysis*. https://doi.org/10.1111/gean.12276
- **Role:** Citation for the libpysal and esda software used in 2.6.
  

*Still to add as they are adopted: the DoD BAH Primer and DTMO's BAH methodology, cited
directly rather than through summaries.*
