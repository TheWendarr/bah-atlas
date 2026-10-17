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

### `manifest.json`
Provenance and lineage: source, source year, pay-grade schema, row/class counts,
and validation warnings. Feeds both reproducibility and the site's attribution
section.

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
| rent_share               | float | B5 rent share of total BAH |
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
| tax_monthly          | float | property tax (national placeholder rate until A8) |
| insurance_monthly    | float | homeowners insurance (national placeholder until A8) |
| mi_monthly           | float | mortgage insurance (0 for a VA loan) |
| own_housing_monthly  | float | PITI: the sum of the four above |
| utilities_usd        | float | from B8; blank where the MHA has no ZORI |
| own_total_monthly    | float | `own_housing_monthly + utilities_usd`; the buy-mode benchmark |

### ZIP-level companions
`zip_zori.csv`, `zip_zhvi.csv` (`zip, mha, value, months_used`) and `zip_safmr.csv`
(`zip, mha, br0..br4, hud_rows`) keep the pre-aggregation values for the B23 QA report.

### `*_manifest.json`
Input file and SHA-256, window months actually used, coverage counts, MHAs
without data, parameters (B11), and warnings.

## Computed metrics (`pipeline/metrics/coverage_metrics.py`, written to `data/interim/metrics_YYYY/`)

Long tables: one row per A12 profile x real MHA (2 x 299 in 2026), including MHAs
with no benchmark, whose metric columns are blank. Target = A12 `coverage_target` (0.95).

| column          | type  | notes |
|-----------------|-------|-------|
| profile         | str   | A12 profile id (`e5_dep`, `o3_dep`) |
| mha             | str   | MHA code |
| pay_grade, has_dependents | str | the B4 cell the profile selects |
| bah_monthly     | float | B4 monthly rate, USD |
| cost_monthly    | float | local monthly cost of the anchor dwelling (see each table) |
| coverage_ratio  | float | `bah_monthly / cost_monthly` (R) |
| gap_vs_target   | float | `R - 0.95`; the test variable for 2.6 spatial statistics |
| surplus_usd     | float | `bah_monthly - cost_monthly`; A13 `surplus_usd` classes |
| target_gap_usd  | float | `bah_monthly - 0.95 x cost_monthly`; dollars over/under the design point |
| status          | str   | why a value is blank (see each table) |

### `mha_rent_metrics.csv` (B12 coverage ratio, B13 surplus/gap)
`cost_monthly` = B8 `zori_utilities_adjusted`. Extra columns:

| column                | type  | notes |
|-----------------------|-------|-------|
| zori_zip_coverage     | float | B8 share of the MHA's ZIPs with ZORI data |
| safmr_bedrooms        | int   | profile `anchor_bedrooms` |
| safmr_monthly         | float | B10 `safmr_median` at that bedroom count (gross rent) |
| safmr_coverage_ratio, safmr_gap_vs_target, safmr_surplus_usd | float | the same metrics against SAFMR: bedroom-matched cross-check |
| status                | str   | `ok` or `no_zori` |

### `mha_buy_metrics.csv` (B14 coverage ratio, B15 surplus/gap)
`cost_monthly` = B11 `own_total_monthly` (PITI + utilities). Extra column
`own_housing_monthly` (PITI only, from B11). `status` is `ok`, `no_home_value`
(no ZHVI) or `no_utilities` (home value but no ZORI, so no utilities estimate).

### `coverage_metrics_manifest.json`
Input files and SHA-256, the definitions above, benchmark months per input (B8,
B9, B11 rate window), and per profile and mode: MHAs with a value, coverage-ratio
min/median/max, MHAs below target and at or above full cost, A13 class counts,
status counts, and the median ZORI-minus-SAFMR ratio difference.
