# Data dictionary

## Ingestion outputs (`pipeline/ingest/ingest_bah_ascii.py`)

### `zip_mha.csv`
| column     | type | notes |
|------------|------|-------|
| zip        | str  | 5-char ZIP, leading zeros preserved |
| mha        | str  | 5-char MHA/placeholder code |
| mha_class  | str  | `mha` (real), `ccg` (County Cost Group ZZ###), `unknown` (XX###) |

### `zip_mha_geo.csv`
Real MHAs only (`mha_class == mha`), columns `zip, mha`. Direct input to the
geometry builder.

### `mha_names.csv`
`mha, name, mha_class` — the DTMO MHA registry (code to name).

### `bah_rates.csv` (tidy/long)
| column          | type  | notes |
|-----------------|-------|-------|
| mha             | str   | MHA code |
| pay_grade       | str   | one of E1..E9, W1..W5, O1E..O3E, O1..O10 |
| has_dependents  | bool  | with- vs without-dependents table |
| monthly_rate    | float | USD/month |

### `manifest.json` (nodes B1-B4)
Provenance and lineage: source, source year, pay-grade schema, row/class counts,
and validation warnings. Feeds both reproducibility and the site's attribution
section. `input_file` / `input_sha256` record the A1 zip read, and
`output_sha256` the four CSVs written, so `make verify` can tie B1-B4 to the
fetched release and to every stage that reads them.

## Geometry outputs (`pipeline/geometry/build_mha_geometry.py`, written to `data/processed/`)

### `mha_YYYY.gpkg` / `mha_YYYY.geojson` (B6)
One row per real MHA: `mha`, geometry (EPSG:4326). Dissolved from Census ZCTAs
through `zip_mha_geo.csv`; no DoD MHA polygon layer exists.

### `non_mha_YYYY.gpkg` / `non_mha_YYYY.geojson` (B28)
One row per County Cost Group and territory-bucket code with at least one ZIP
matching a ZCTA (`make non-mha`). Same dissolve as B6, from the B1 crosswalk.

| column          | type | notes |
|-----------------|------|-------|
| mha             | str  | area code (`ZZ###` or `XX###`) |
| class           | str  | `ccg` or `unknown`, from B1 `mha_class` |
| geometry_source | str  | "ZCTA dissolve of DTMO ZIP assignments (non-authoritative)" |
| geometry        |      | EPSG:4326 |

### `non_mha_YYYY_geometry_manifest.json` (B28)
`inputs` / `input_sha256` (A2 ZCTA file, B1 crosswalk); `counts` (areas and
codes by class, multipolygon areas, ZIPs by class, ZIPs with no ZCTA match by
class, ZCTAs claimed by more than one area: always 0, since the build stops
otherwise); `codes_without_polygon`; `unknown_zip3_prefixes` (the territory
bucket's ZIP3 prefixes and counts, to confirm which territory it covers);
`outputs` / `output_sha256`; `warnings`.

### `areas_YYYY.pmtiles` (B7)
The B6 and B28 polygons in one vector layer, `areas`, tiled in a single
tippecanoe run (z2–z10) with shared-border detection. Each feature has only
`code` and `class`; the map promotes `code` as the feature id. Specified in
[data contract section 4](data-contract.md#4-b7--area-polygons-areas_2026pmtiles)
(decision D9). Replaces the MHA-only `mha_YYYY.pmtiles`, which `make tiles`
removes.

### `areas_YYYY_manifest.json` (B7)
`inputs` / `input_sha256` (B6 and B28 GeoJSON), features in total and by class,
layer and property names, the MapLibre source declaration, zoom range,
tippecanoe version, `output_file` / `output_sha256` / `output_bytes`.

### `mha_YYYY_geometry_manifest.json` (B6)
`inputs` / `input_sha256` (A2 ZCTA file, B2 crosswalk), `counts` (MHAs written,
multipolygon MHAs, ZIPs dropped as non-MHA, ZIPs with no ZCTA match),
`outputs` / `output_sha256` (gpkg and geojson). 2026: 299 MHAs, 115
multipolygon, 5,609 ZIPs without a ZCTA.

## Benchmark outputs (`pipeline/benchmarks/`, written to `data/interim/benchmarks_YYYY/`)

Common columns on every MHA-level table. One row per real MHA (299 in 2026),
including MHAs with no source data, whose value columns are blank.

| column            | type  | notes |
|-------------------|-------|-------|
| mha               | str   | MHA code |
| n_zips            | int   | ZIPs in the MHA per the DTMO crosswalk (B1) |
| n_zips_with_data  | int   | of those, ZIPs the source has a value for |
| zip_coverage      | float | n_zips_with_data / n_zips |

### `mha_zori.csv` (B8)
| column                   | type  | notes |
|--------------------------|-------|-------|
| zori_median / _mean / _min / _max | float | USD/month asking rent across the MHA's ZIPs; each ZIP is its mean over the window months |
| rent_share               | float | B5 rent share of total housing cost (rent + utilities) |
| zori_utilities_adjusted  | float | `zori_median / rent_share`; the primary rent benchmark (A12 `rent_primary`) |
| utilities_usd            | float | `zori_utilities_adjusted - zori_median`; also used by B11 |

### `mha_zhvi.csv` (B9)
`zhvi_median`, `_mean`, `_min`, `_max` — USD typical home value (mid tier), same method as ZORI.

### `mha_safmr.csv` (B10, long)
| column        | type  | notes |
|---------------|-------|-------|
| bedrooms      | int   | 0-4; a profile uses its `anchor_bedrooms` row |
| safmr_median / _mean / _min / _max | float | USD/month gross rent (utilities included) |

### `mha_ownership.csv` (B11)
| column               | type  | notes |
|----------------------|-------|-------|
| zhvi_median          | float | from B9 |
| loan_amount          | float | value x (1 - down payment) x (1 + financed funding fee) |
| rate_pct             | float | mean PMMS 30-year rate over the window (one national value) |
| pi_monthly           | float | principal and interest |
| tax_rate             | float | effective property-tax rate per year, from `mha_tax_insurance.csv` |
| tax_monthly          | float | `zhvi_median x tax_rate / 12` |
| tax_source           | str   | `locality` or `state_fallback` |
| insurance_annual_usd | float | FIO premiums per policy (data year in `ownership.json`), from `mha_tax_insurance.csv` |
| insurance_monthly    | float | `insurance_annual_usd / 12` |
| insurance_source     | str   | `locality` or `state_fallback` |
| mi_monthly           | float | mortgage insurance (0 for a VA loan) |
| own_housing_monthly  | float | PITI: the sum of the four above |
| utilities_usd        | float | from B8; blank where the MHA has no ZORI |
| own_total_monthly    | float | `own_housing_monthly + utilities_usd`; the buy-mode benchmark |

### `mha_tax_insurance.csv` (A8 rollup for B11; `make taxins`)
One row per real MHA, from `tax_insurance_to_mha.py`.

| column                   | type  | notes |
|--------------------------|-------|-------|
| mha                      | str   | MHA code |
| n_zips                   | int   | ZIPs in the MHA (B1) |
| tax_zips_with_data       | int   | of those, ZCTAs with usable ACS taxes and value |
| effective_tax_rate       | float | sum(B25090_001E) / sum(B25079_001E) over those ZCTAs, or the state rate |
| tax_source               | str   | `locality` or `state_fallback` |
| insurance_zips_with_data | int   | of the MHA's ZIPs, those FIO publishes for the data year |
| insurance_annual_usd     | float | median FIO premiums per policy over those ZIPs, or the state median |
| insurance_source         | str   | `locality` or `state_fallback` |

`mha_tax_insurance_manifest.json` records the A9, A8 and B1 files and SHA-256,
the config hash, the ACS vintage and period, ZCTAs usable or skipped (missing
estimate, zero value), the FIO sheet, years and ZIP counts, the MHAs on a state
fallback and the state values used, rate and premium summaries, and warnings.

### ZIP-level companions
`zip_zori.csv`, `zip_zhvi.csv` (`zip, mha, value, months_used`) and `zip_safmr.csv`
(`zip, mha, br0..br4, hud_rows`) keep the pre-aggregation values for the B23 QA report.

### `*_manifest.json`
Input file and SHA-256, window months actually used, coverage counts, MHAs
without data, parameters (B11), and warnings.

## Computed metrics (`pipeline/metrics/coverage_metrics.py`, written to `data/interim/metrics_YYYY/`)

Long tables: one row per A12 profile x real MHA (2 x 299 in 2026), including MHAs
with no benchmark, whose metric columns are blank.

**Statutory target.** 37 U.S.C. 403(b)(3) sets BAH = local cost of adequate
housing - 5% of the *national* average cost for the pay grade and dependency
status. The deduction (the member cost share, A12 `cost_share_monthly`, from
DTMO's out-of-pocket table) is the same dollars at every duty station, so BAH
covers exactly 95% of local cost only where local cost equals the national
mean. The test is therefore `adequacy_ratio` against 1.00, not `coverage_ratio`
against 0.95.

| column             | type  | notes |
|--------------------|-------|-------|
| profile            | str   | A12 profile id (`e5_dep`, `o3_dep`) |
| mha                | str   | MHA code |
| pay_grade, has_dependents | str | the B4 cell the profile selects |
| bah_monthly        | float | B4 monthly rate, USD |
| cost_share_monthly | float | A (A12): DTMO member cost share for the cell, USD/month |
| cost_monthly       | float | C: local monthly cost of the anchor dwelling (see each table) |
| coverage_ratio     | float | `BAH / C`: share of benchmark cost BAH pays (descriptive) |
| design_coverage    | float | `1 - A / C`: share BAH is designed to pay at this cost level |
| adequacy_ratio     | float | `(BAH + A) / C`: DoD's implied local cost vs the benchmark; target 1.00 |
| adequacy_gap       | float | `adequacy_ratio - 1` (= coverage_ratio - design_coverage); the test variable for 2.6 |
| surplus_usd        | float | `BAH - C`: full-cost dollars |
| design_gap_usd     | float | `BAH + A - C`: dollars over (+) or short of (-) the statutory design |
| flat95_gap         | float | `coverage_ratio - 0.95`: sensitivity column for the simple fixed-95% reading |
| status             | str   | why a value is blank (see each table) |

### `mha_rent_metrics.csv` (B12 coverage ratio, B13 surplus/gap)
`cost_monthly` = B8 `zori_utilities_adjusted`. Extra columns:

| column                | type  | notes |
|-----------------------|-------|-------|
| zori_zip_coverage     | float | B8 share of the MHA's ZIPs with ZORI data |
| safmr_bedrooms        | int   | profile `anchor_bedrooms` |
| safmr_monthly         | float | B10 `safmr_median` at that bedroom count (gross rent, HUD 40th percentile) |
| safmr_coverage_ratio, safmr_adequacy_ratio, safmr_design_gap_usd | float | the same metrics against SAFMR: bedroom-matched cross-check |
| status                | str   | `ok` or `no_zori` |

### `mha_buy_metrics.csv` (B14 coverage ratio, B15 surplus/gap)
`cost_monthly` = B11 `own_total_monthly` (PITI + utilities). Extra column
`own_housing_monthly` (PITI only, from B11). `status` is `ok`, `no_home_value`
(no ZHVI) or `piti_only_no_zori` (home value but no ZORI, so no utilities
estimate: the metrics are computed against PITI alone, decision 2.4; these rows
are mapped but left out of the manifest's buy summaries and the 2.6 tests).

### `coverage_metrics_manifest.json`
Input files and SHA-256, the statutory basis and cost-share parameters (source,
URL, PDF checksum, dollars per profile), the definitions above, benchmark months
per input (B8, B9, B11 rate window), and per profile and mode: MHAs with a value,
adequacy and coverage ratio min/median/max, MHAs below design, A13 class counts
for all four mapped metrics, status counts, `flat95_vs_design` (MHAs short under
the fixed-95% reading only, and under the statutory reading only), and for the
rent cross-check the median ZORI-minus-SAFMR adequacy difference.

## Spatial statistics (`pipeline/spatial/`, written to `data/interim/spatial_YYYY/`)

Scope is CONUS: MHAs coded AK, HI or a territory prefix are excluded from 2.6
and listed in both manifests. Distances are in EPSG:5070 (Conus Albers, equal
area) between one representative point per MHA, which always falls inside the
polygon.

### B16 spatial weights (`build_weights.py`)

**Why k-nearest neighbours.** B6 polygons are dissolves of the ZCTAs DTMO assigns
to each MHA. The County Cost Group counties between MHAs are not MHAs, so many MHAs
touch no other MHA. Under contiguity weights those MHAs have no neighbour and drop
out of every local statistic. KNN (k = 6) gives every MHA the same number of
neighbours. Queen contiguity is built as a diagnostic, and its island count in the
manifest is the evidence for the choice.

#### `mha_weights_knn6.gal`
Neighbour lists in GAL format (GeoDa / PySAL), stored unweighted. Moran's I and
LISA apply row standardization; Gi* uses binary weights.

#### `mha_neighbors.csv` (one row per KNN link)
| column      | type  | notes |
|-------------|-------|-------|
| mha         | str   | MHA code |
| neighbor    | str   | one of its k nearest MHAs; ties in distance break on MHA code |
| rank        | int   | 1 = nearest |
| distance_km | float | between representative points |
| queen       | bool  | whether the two polygons also touch (queen contiguity) |

#### `mha_weights_summary.csv` (one row per B6 MHA)
| column           | type  | notes |
|------------------|-------|-------|
| mha              | str   | MHA code |
| in_scope         | bool  | false for AK, HI and territory codes; other columns blank |
| x_m, y_m         | float | representative point, EPSG:5070 metres |
| queen_neighbors  | int   | 0 = island under contiguity weights |
| knn_nearest_km, knn_farthest_km | float | distance to the 1st and k-th neighbour |
| knn_component    | int   | connected piece of the KNN graph (0 = largest) |

#### `weights_manifest.json` (node B16)
B6 file and SHA-256, the scope rule and excluded MHAs, CRS, `primary` (k, tie
break, components, share of one-way links, nearest and k-th neighbour distances,
links over 500 km) and `diagnostic_queen` (islands and their codes, components,
neighbour-count distribution, KNN links that also touch).

### B17 global Moran's I and B18 LISA / Gi* (`spatial_stats.py`)

One test runs for every A12 profile × mode (rent from B12, buy from B14) ×
variable: `adequacy_gap` (primary; the statutory design test) and `flat95_gap`
(sensitivity). The primary test is the A12 default profile (`e5_dep`), rent,
`adequacy_gap`. The KNN weights are rebuilt for each test on the MHAs that have a
value. Taking a subset of the B16 matrix instead would leave some MHAs with fewer
than k neighbours. Defaults: 9,999 permutations, seed 2026, alpha 0.05.

#### `mha_spatial_stats.csv` (long: one row per test × MHA)
| column               | type  | notes |
|----------------------|-------|-------|
| profile, mode, variable | str | the test: A12 profile id; `rent` or `buy`; `adequacy_gap` or `flat95_gap` |
| mha                  | str   | MHA code |
| status               | str   | `tested`, `no_value` (blank in B12/B14, or a row whose B12/B14 status is not `ok`, such as a PITI-only buy row), `no_geometry` (not in B6), `out_of_scope` (AK, HI, territory) |
| value                | float | the variable tested, copied from B12/B14 |
| neighbors            | int   | k used for this test |
| lisa_i               | float | local Moran's I_i (row-standardized) |
| lisa_quadrant        | str   | HH, LH, LL, HL: the MHA's value and its neighbours' average, each above (H) or below (L) the mean |
| lisa_p_sim           | float | two-sided pseudo p-value from conditional permutation |
| lisa_fdr_significant | bool  | significant after the Benjamini-Hochberg step-up across this test's MHAs, at alpha |
| cluster              | str   | A13 cluster code: `lisa_quadrant` where `lisa_p_sim` < alpha, else `NS` |
| gi_z                 | float | standardized Getis-Ord Gi* (self included, binary weights); positive = high values nearby |
| gi_p_sim             | float | two-sided pseudo p-value for Gi* |
| gi_class             | str   | `hot` (gi_z > 0), `cold` (gi_z < 0) where `gi_p_sim` < alpha, else `ns` |

Stat columns are blank for rows that were not tested. Gi* is computed on the ratio
behind each gap (`adequacy_ratio` = `adequacy_gap` + 1; `coverage_ratio` =
`flat95_gap` + 0.95). The standardized z and its permutation p are unchanged by
adding a constant, so these are the Gi* values of the gap.

#### `spatial_stats_manifest.json` (nodes B17, B18)
Input files and SHA-256; method (weights, permutations, seed, alpha, smallest
attainable p-values, the two-sided local alternative, software versions); `headline`
(the primary test: n, Moran's I, p_sim, the H1 reading, cluster counts, FDR count,
Gi* hot and cold counts); `flat95_vs_adequacy_moran` (I for both variables per
profile and mode, and the difference); and one entry per test. Each test entry holds
`moran` (I, E[I], z and p by permutation and by normal approximation),
`moran_sensitivity` (adequacy_gap tests: I and p at k = 4, k = 8 and under queen
contiguity with islands dropped), `lisa` (cluster counts, FDR cut-off and counts),
`gi_star` (hot, cold, and agreement with HH / LL), and `not_tested` counts.

#### `mha_lisa_e5_dep_rent_map.png`
LISA cluster map of the primary test, in A13 cluster colours, with the global
result in the title. `make evidence` copies it to `docs/evidence/` and credits it to
B17 and B18.

## Front-end payload (2.7, in progress)

The files handed to Layer 3 (B7 area tiles, B20 attribute payload, B21 UI
metadata, B22 build manifest, B27 hotspot overlay) are specified field by field in
the [data contract (Layer 2 → Layer 3 ICD)](data-contract.md), which governs
them. B28 (County Cost Group and territory polygons) is merged into B7 under
decision D9. The decisions behind the contract are in the
[M6 plan](plans/m6-plan.md).

## Configuration

The authored configs (`config/profiles.json` A12, `config/classification.json`
A13, `config/ownership.json` B11) are documented field by field in
[`configuration.md`](configuration.md).
