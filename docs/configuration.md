# Configuration reference

The project's authored configuration lives in `config/`. This page explains every field and the reasoning behind every value. The JSON files themselves hold values only.

## Why the explanations live here

Pipeline stages record the SHA-256 of each config they read:

- B12–B15 and B16–B18 record A12 and A13
- B11 and the A8 tax/insurance rollup record `ownership.json`

`make verify` then checks that those hashes match the configs in the repository. If explanations sat inside the JSON, correcting a sentence would change the file's hash. The M4–M5 evidence would then go stale even though no number had changed.

Keeping prose here means a wording fix touches only this page. `make check-config` enforces the split: it fails on `_about`, `rationale`, `note` or `*_note` fields, and on a missing `_doc` pointer.

## Changing a value

1. Edit the value in `config/`, then update the matching section below.
2. Run `make check-config`.
3. Rerun every stage that records the file:
   - A12 or A13: `make metrics spatial`
   - `ownership.json`: `make benchmarks metrics spatial` (the A8 rollup `make taxins` runs within `benchmarks`)
4. Run `make evidence` and then `make verify`, which should report that all recorded hashes agree.
5. Commit the config, this page and `docs/evidence/` together.

---

## A12 profiles (`config/profiles.json`)

Each profile selects one BAH cell (pay grade × dependency status from B4) and the bedroom count used to pick benchmark series. It also carries the member cost share DoD deducts for that cell. B12–B18 read it, and B21 ships it to the map.

| Field | Meaning |
|---|---|
| `_doc` | Pointer to this page. |
| `version` | Schema version of this file. Version 2 (18 Oct 2026) moved the explanations to this page. |
| `bah_year` | BAH rate year the profiles apply to. |
| `coverage_target` | 0.95. **A reference value for the sensitivity check only**; it is not the test target (see below). Must equal A13's `coverage_target`. |
| `default_profile` | Profile shown first on the map and used for the primary spatial test. |
| `profiles[].id`, `label` | Stable key and display name. |
| `profiles[].role` | `primary` (the research profile) or `contrast`. Exactly one profile is primary. |
| `profiles[].pay_grade`, `has_dependents` | The B4 cell this profile reads. |
| `profiles[].anchor_dwelling`, `anchor_bedrooms` | The DoD housing standard for the grade in words (the values are in A14), and the SAFMR bedroom count used for the cross-check. |
| `profiles[].cost_share_monthly` | DTMO member out-of-pocket dollars for the cell. Must equal the A14 cell (`make check-config`). |
| `benchmarks.standard_source` | `A14`: each profile is measured against the cost of its DoD housing standard (D19). |
| `benchmarks.rent_primary`, `buy_primary` | `b29_at_standard`, `b30_at_standard`: the standard blended from the B29 rent and B30 ownership benchmarks by home type. For E-5 that is the 2 BR townhouse, which equals B8 in rent mode; in buy mode it is priced between condo and single-family (D22), so it no longer equals B11. |
| `benchmarks.rent_crosscheck`, `safmr_bedroom_field` | HUD SAFMR (B10) at the profile's `anchor_bedrooms`. |
| `cost_share.*` | Where the cost-share dollars come from: method, year, source, URL, local artifact, SHA-256, the values read, and the date verified. `make verify` checks the SHA-256 against the fetch record. |

**The test target is not 95%.** 37 U.S.C. 403(b)(3) sets BAH at the local cost of adequate housing minus 5% of the *national* average cost for the grade. That deduction is the same dollars at every duty station. So BAH covers exactly 95% of local cost only where local cost equals the national mean: more in expensive MHAs, less in cheap ones.

B12–B15 therefore test `adequacy_ratio` = (BAH + `cost_share_monthly`) ÷ benchmark against 1.00. `coverage_target` survives only for the flat-95% sensitivity column (`flat95_gap` = BAH ÷ cost − 0.95).

**Why these profiles.**

- **E-5 with dependents** is the primary research profile. DoD's housing standard for E-5 is a 2-bedroom townhouse, so the anchor maps to a single bedroom count without interpolation.
- **O-3 with dependents** is the contrast profile. DoD's O-3 standard sits 98% of the way from a 3-bedroom townhouse to a 3-bedroom single-family home. It therefore differs from the primary in grade band, bedroom count and dwelling type at once.
- **Source:** DoD BAH housing standards by pay grade (BAH Primer; summarized at military.com, *Paycheck Chronicles*, 4 Dec 2014). This is listed in [SOURCES.md](SOURCES.md) under *Concepts & methods*.

**Why each profile has its own benchmark (D19, 18 Oct 2026).** Until 18 Oct one all-homes ZORI series served both profiles, so the E-5 vs O-3 contrast came only from the BAH numerator. Since D19 each profile is measured against its DoD standard: B29 and B30 give every MHA a benchmark for each of the six housing profiles (building type from Zillow's type series, bedrooms from the SAFMR or ZHVI bedroom ratio), and the profile's standard is blended from them with the A14 formula. In rent mode the all-homes series is taken to stand for a 2 BR townhouse, E-5's standard, so E-5 rent is unchanged; O-3 is recomputed. Buy mode changed again with D22 (below, under `config/ownership.json`). The SAFMR cross-check at `anchor_bedrooms` stays as it was.

**Cost share.** These are the member out-of-pocket (absorption) dollars per cell, read from DTMO's annual out-of-pocket table: the same amount at every duty station. The 2026 values are E-5 with dependents $126 and O-3 with dependents $151. See the A12 out-of-pocket entry in [SOURCES.md](SOURCES.md).

## A14 housing standards (`config/housing_standards.json`)

Decision D18 (18 Oct 2026) lets the map show any rank with or without dependents in any of DoD's six housing profiles. This file holds what DoD itself prescribes for each of those 46 cells: the housing standard BAH is built on, and the member cost share deducted from it. B29 and B30 read the home types, the coverage metrics (B12–B15) read the research profiles' standards, B23 checks the table, and B31 ships it to the map.

| Field | Meaning |
|---|---|
| `_doc` | Pointer to this page. |
| `version`, `bah_year` | Schema version of this file; the BAH year the cost shares belong to. |
| `home_types[]` | DoD's six housing profiles, cheapest first: `id`, `building` (`apartment`, `townhouse`, `single_family`) and `bedrooms`. The order is the order standards interpolate in. |
| `reference_type` | `th2`, the 2-bedroom townhouse. B8 (all-homes ZORI) is taken to stand for this dwelling in rent mode, so every other rent is a ratio to it (D19). In buy mode B9 stands for a 3 BR home (`config/ownership.json`, D34), and the townhouse has its own factor (D22). |
| `rent_type_series.multifamily_bedrooms` | 2: the bedroom count Zillow's multifamily rent series (A15.mfr) is taken to stand for. B29 compares it with the 2 BR townhouse at equal bedrooms (D34). Unchanged in effect from D19, which already treated it as 2 BR. |
| `rent_type_series.single_family_bedrooms` | 3: the bedroom count Zillow's single-family rent series (A15.sfr) is taken to stand for, the typical size of a single-family rental. B29 takes this size difference out of the single-family ratio before adding bedrooms with the SAFMR ratio (D34). |
| `rent_type_series.single_family_not_below_townhouse` | `true`: B29 never prices a single-family home below the townhouse with the same bedrooms. Where the size-matched single-family factor is below 1, B29 uses 1 and marks the row `floored` (D34). |
| `grades` | The rank dropdown: E-1–E-9, W-1–W-5, O-1–O-9 (D18; O-1E–O-3E and O-10 left out). |
| `standards.<grade>.with`, `.without` | `lower`, `upper`, `share`. Anchor: `upper` null and `share` 0, the cost of `lower`. Interpolated: `lower` + `share` × (`upper` − `lower`). Above the highest profile: `upper` null and `share` > 0, the cost of `lower` × (1 + `share`). |
| `cost_share_monthly.<grade>.with`, `.without` | DTMO 2026 out-of-pocket dollars for the cell (5% of the national mean BAH for the grade). |
| `cost_share_derived` | Grades whose values are copied from another grade: O-8 and O-9 from O-7 (below). |
| `sources.*` | The standards source and the out-of-pocket table, with URL, the local artifact and SHA-256 where there is one, and the date verified. |

**The standards (2026).**

| Grade | With dependents | Cost share | Without dependents | Cost share |
|---|---|---|---|---|
| E-1 | 50% from 2 BR apartment to 2 BR townhouse | $115 | 1 BR apartment (anchor) | $93 |
| E-2 | 50% from 2 BR apartment to 2 BR townhouse | $115 | 1 BR apartment (anchor) | $93 |
| E-3 | 50% from 2 BR apartment to 2 BR townhouse | $115 | 1 BR apartment (anchor) | $93 |
| E-4 | 50% from 2 BR apartment to 2 BR townhouse | $115 | 1 BR apartment (anchor) | $93 |
| E-5 | 2 BR townhouse (anchor) | $126 | 67% from 1 BR apartment to 2 BR apartment | $110 |
| E-6 | 3 BR townhouse (anchor) | $141 | 7% from 2 BR apartment to 2 BR townhouse | $114 |
| E-7 | 36% from 3 BR townhouse to 3 BR single-family | $144 | 53% from 2 BR apartment to 2 BR townhouse | $120 |
| E-8 | 75% from 3 BR townhouse to 3 BR single-family | $151 | 20% from 2 BR townhouse to 3 BR townhouse | $134 |
| E-9 | 16% from 3 BR single-family to 4 BR single-family | $160 | 51% from 2 BR townhouse to 3 BR townhouse | $139 |
| W-1 | 1% from 3 BR townhouse to 3 BR single-family | $123 | 31% from 2 BR apartment to 2 BR townhouse | $92 |
| W-2 | 52% from 3 BR townhouse to 3 BR single-family | $146 | 19% from 2 BR townhouse to 3 BR townhouse | $123 |
| W-3 | 3 BR single-family (anchor) | $154 | 54% from 2 BR townhouse to 3 BR townhouse | $136 |
| W-4 | 22% from 3 BR single-family to 4 BR single-family | $161 | 9% from 3 BR townhouse to 3 BR single-family | $147 |
| W-5 | 48% from 3 BR single-family to 4 BR single-family | $166 | 45% from 3 BR townhouse to 3 BR single-family | $148 |
| O-1 | 11% from 2 BR townhouse to 3 BR townhouse | $118 | 2 BR apartment (anchor) | $104 |
| O-2 | 98% from 2 BR townhouse to 3 BR townhouse | $134 | 83% from 2 BR apartment to 2 BR townhouse | $118 |
| O-3 | 98% from 3 BR townhouse to 3 BR single-family | $151 | 64% from 2 BR townhouse to 3 BR townhouse | $138 |
| O-4 | 58% from 3 BR single-family to 4 BR single-family | $176 | 40% from 3 BR townhouse to 3 BR single-family | $157 |
| O-5 | 4 BR single-family (anchor) | $193 | 63% from 3 BR townhouse to 3 BR single-family | $164 |
| O-6 | 4 BR single-family + 1% | $201 | 3 BR single-family (anchor) | $175 |
| O-7 | 4 BR single-family + 2% | $212 | 3 BR single-family + 2% | $187 |
| O-8 | 4 BR single-family + 2% | $212 | 3 BR single-family + 2% | $187 |
| O-9 | 4 BR single-family + 2% | $212 | 3 BR single-family + 2% | $187 |

**Source of the standards.** DTMO's *A Primer on the Basic Allowance for Housing* (January 2022) lists, for every grade, the housing profile it is anchored to or the percentage of the way between two profiles. The 2018 edition gives the same table, and CNA's April 2026 evaluation of BAH adequacy standards (Table 1) confirms the same anchor points: 1 BR apartment E-4 and 2 BR apartment O-1 without dependents; 2 BR townhouse E-5, 3 BR townhouse E-6, 3 BR single-family W-3 and 4 BR single-family O-5 with dependents. With-dependents E-1 to E-4 sit at the midpoint of a 2 BR apartment and a 2 BR townhouse; E-1 to E-3 take the E-4 standard, the minimum.

**Checked against the 2026 rates (`make standards`).** DoD sets each grade's BAH as the local cost of its standard minus its cost share. The six anchor cells therefore give each profile's local cost in every MHA, and every other cell then predicts its own 2026 rate. `pipeline/benchmarks/standards_check.py` runs that prediction for all 46 cells in all 299 MHAs and records the share the rates imply beside the share in this file. On 24 Oct 2026 every cell passed: the median residual is $1–4 a month (the published rates are rounded), and the implied shares agree with the primer within 0.01 for 45 of the 46 cells. It also settled two readings the primer leaves open:

- **Above the highest profile.** O-6 and O-7 with dependents (1%, 2%) and O-7 without (2%) are markups on the top anchor's cost: the rates imply 0.97%, 1.94% and 1.95%. They are not steps toward another profile.
- **E-8 without dependents** is the one cell that drifts: the primer says 20% from a 2 BR to a 3 BR townhouse, the 2026 rates imply about 23%. The file keeps the published 20%; the gap is about $12 a month in a typical MHA and is recorded in the check's manifest.

Without-dependents rates also have a floor at 75% of the with-dependents rate (since 2008). Where the floor sets the rate (766 MHA cells in 2026), the standard does not, so the check leaves those cells out. The floor changes BAH, not the housing standard, so the benchmark is unaffected.

**O-8 and O-9.** BAH stops rising at O-7: the 2026 O-8 and O-9 rates equal O-7's in every MHA, and DTMO's out-of-pocket table stops at O-7. Both grades therefore take O-7's standard and cost share, listed in `cost_share_derived`.

**What a standard means on the map.** With the home-type dropdown at *DoD standard for this grade* (the default), the map measures BAH against its statutory target. Any other home type measures how far BAH goes toward that home, which DoD does not promise; the map labels such views so (D18, C25).

---

## A13 classification (`config/classification.json`)

A13 sets the class breaks, colours and labels for every mapped metric, and the cluster classes for the hotspot overlay. B12–B15 read the breaks for the class counts in their manifest. B18 reads the cluster classes for its map. B21 ships the whole file to the map.

| Field | Meaning |
|---|---|
| `_doc` | Pointer to this page. |
| `version` | Schema version. Version 2 (18 Oct 2026) moved the explanations here and added the D2 and D3 entries. Version 3 (3 Nov 2026) added `ramp_labels`, `off_standard` and `clusters.out_of_scope_label`. |
| `coverage_target` | Must equal A12's value (0.95). Used only by the flat-95% reading. |
| `no_data_color` | Fill for areas with no value: CCGs (decision N1), MHAs without a benchmark, and the territory bucket. |
| `palette_source` | Attribution for the palette. ColorBrewer requires credit, so this text is shown on the map. |
| `default_metric` | Layer shown first: `adequacy_ratio`. |
| `metrics.<name>.label`, `short_label` | Legend and control text. |
| `metrics.<name>.role` | `primary` (the statutory test), `descriptive` (plain BAH-versus-cost views) or `sensitivity` (alternative readings, decision D3). |
| `metrics.<name>.modes` | Which modes have this metric. The SAFMR layers are rent only, because HUD publishes rents, not ownership costs. |
| `metrics.<name>.format` | `percent` or `usd`, for legend and popup formatting. |
| `metrics.<name>.method`, `neutral`, `breaks`, `colors`, `class_labels` | Fixed half-open classes `[lower, upper)`. There is one more colour and label than breaks, and `neutral` must sit in the middle class. |
| `metrics.<name>.ramp_labels` | Three short strings for a compact legend: low end, middle, high end. |
| `metrics.<name>.off_standard` | The second scale for the four grid metrics (D27): `label`, `short_label`, `neutral`, `breaks`, `class_labels`, `ramp_labels`. It shares the metric's colours. |
| `clusters.variable`, `alpha` | The cluster test: `adequacy_gap` at pseudo p < 0.05. |
| `clusters.legend_title` | Labels every local class as exploratory (decision D2). |
| `clusters.classes` | LISA quadrant codes with their label and colour. |
| `clusters.out_of_scope_label` | Legend text for areas outside the cluster analysis. |
| `clusters.fdr_marker` | Outline that marks MHAs still significant after the Benjamini–Hochberg false-discovery-rate correction (decision D2). |

**Why fixed breaks rather than quantiles.** The research question asks whether BAH meets its statutory design, a fixed point. Fixed breaks keep that point visible as the near-white middle class and make maps comparable across profiles and modes. Quantile breaks would always paint the same share of MHAs red, whether or not any MHA misses the design.

The palette is ColorBrewer RdBu, 7 classes, which is colour-blind safe: red for shortfall, blue for surplus.

### The second scale (decision D27, 3 Nov 2026)

The main breaks sit around the statutory design point. A view of a home DoD does not prescribe for a rank can land far from that point, and on the main breaks 124 of 266 such rent views and 121 of 266 buy views put at least 90% of areas in one class. `off_standard` spreads the classes across the range those views reach, so the geography stays visible, and its labels drop the word "statutory" because these views are not the statutory test. The breaks are still fixed, so every off-standard map is comparable with every other. The counts for each metric are in [data contract section 6.2](data-contract.md#62-the-second-colour-scale).

### The seven map layers

**`adequacy_ratio` (primary, the default).** 1.00 means DoD's implied local cost (BAH + cost share) equals the independent benchmark, so BAH meets 37 U.S.C. 403(b)(3) exactly. The ±3% neutral band (97–103%) absorbs DTMO's 1%-rounded rent/utilities split and benchmark noise. That band is a judgment, not a statutory tolerance.

**`design_gap_usd` (primary).** The same test in dollars per month: BAH + cost share − local cost. $0 means BAH equals the benchmark cost minus the member's statutory cost share, as the statute intends. The neutral band is ±$50.

**`coverage_ratio` (descriptive).** The share of the benchmark cost BAH pays. BAH's statutory design point for an MHA is 1 − cost share ÷ local cost, roughly 89–97% across MHAs. That is why the classes centred on 95% are only approximate. Use `adequacy_ratio` for the statutory test.

**`surplus_usd` (descriptive).** BAH − local cost: what a member pays or keeps against the full benchmark. An MHA exactly at its statutory design shows a gap equal to the member cost share ($126 for E-5, $151 for O-3 with dependents), not zero.

**`flat95_gap` (sensitivity).** BAH ÷ local cost − 0.95: the original fixed-95% reading, kept so readers can see what it would have concluded.
- Its breaks are the `coverage_ratio` breaks shifted by −0.95, so it draws the same map as `coverage_ratio`. Its labels state the difference in percentage points from 95%.
- On 17 Oct it called 52 MHAs short for E-5 renters, against 44 under the statutory test. The 8 extra are low-cost MHAs that meet their design.

**`safmr_adequacy_ratio` and `safmr_design_gap_usd` (sensitivity, rent only).** The same statutory test against HUD Small Area Fair Market Rent at the profile's anchor bedroom count, instead of utilities-adjusted ZORI.
- They use the `adequacy_ratio` and `design_gap_usd` classes, so the two benchmarks can be compared on one scale.
- SAFMR is gross rent (utilities included) at HUD's 40th percentile of recent-mover rents, so it is a lower anchor than ZORI.

### Clusters (decision D2, 18 Oct 2026)

LISA and Getis-Ord results come from B18, on `adequacy_gap`, for the hotspot overlay (B27 → C16).

The global Moran's I is the confirmatory test of H1: one test, I = 0.152, pseudo p = 0.0001 for the primary profile. The local classes are 283 separate tests at p < 0.05, so about 14 would be flagged by chance alone. They are therefore shown with an *exploratory* legend title.

MHAs that survive the Benjamini–Hochberg false-discovery-rate correction get the `fdr_marker` outline. On 18 Oct, 2 survived (1 HL, 1 LH) at 9,999 permutations, and the rerun at 99,999 permutations gave the same 2, so the count reflects the data rather than the permutation resolution.

---

## `config/ownership.json` (B11)

How a ZHVI home value (B9) becomes a monthly ownership cost comparable to BAH. `ownership_cost.py` reads and validates every field; `tax_insurance_to_mha.py` reads the property-tax and insurance years. Version 2 (18 Oct 2026, A8) replaced the national tax and insurance placeholders with per-MHA values and moved the explanations here, so B11 and everything after it are rerun once. Version 3 (1 Nov 2026, D22) adds `home_types.townhouse_position`, read by B30.

| Field | Meaning |
|---|---|
| `_doc` | Pointer to this page. |
| `version` | Schema version of this file. Version 2: locality tax and insurance, values only. Version 3: the townhouse position (D22). Version 4: the typical size of each Zillow home-value series (D34). |
| `loan.program` | The financing modelled: a VA purchase loan, first use. |
| `loan.term_years` | 30. |
| `loan.down_payment_share` | 0: no down payment, the common VA case. |
| `loan.funding_fee_share` | 0.0215: the VA funding fee for a first-use purchase with less than 5% down. |
| `loan.funding_fee_financed` | `true`: the fee is added to the loan, as is common. |
| `loan.mortgage_insurance_annual_share` | 0: VA loans carry no mortgage insurance. |
| `loan.rate_series` | `pmms30`: the Freddie Mac 30-year fixed rate (A7), averaged over the same months as the B9 home values. |
| `property_tax.method` | `locality_effective_rate`: each MHA's own rate, from `mha_tax_insurance.csv`. |
| `property_tax.source_node`, `acs_vintage` | A9, the ACS 5-year release (2024 = 2020–2024) the rate comes from. `tax_insurance_to_mha.py` stops if the fetched file is a different vintage. |
| `property_tax.fallback` | `state`: an MHA with no usable ZCTA takes its state's rate. |
| `insurance.method` | `locality_average_premium`: each MHA's own premium, from `mha_tax_insurance.csv`. |
| `insurance.source_node`, `data_year` | A8, the Treasury FIO year used (2022, the latest published). |
| `insurance.fallback` | `state`: an MHA with no published ZIP takes its state's median. |
| `insurance.scaled_to_bah_year` | `false`: used as published (decision N2). |
| `utilities.method` | `from_B8`: the owner cost adds the same utilities dollars B8 derives for renters in the MHA. |
| `home_types.townhouse_position` | 0.5: where B30 prices a townhouse on the line from the MHA's condo/co-op factor (0) to its single-family factor (1), the midpoint (D22 option B), both at equal bedrooms (D34). Read by B30 only; B11 validates it. |
| `home_types.all_homes_bedrooms` | 3: the bedroom count the all-homes ZHVI (B9) stands for. Per ZIP the all-homes value is 1.003 × the 3 BR value (median of 20,431 ZIPs, 2026 run), so B30 scales bedrooms from 3 BR (D34). |
| `home_types.condo_bedrooms` | 2: the bedroom count the condo/co-op ZHVI (A16.condo) stands for, the nearest whole count to where it measures. The 2026 manifest ratios put it a little below 2 BR (condo ÷ all-homes 0.655 against 2 BR ÷ all-homes 0.737); B30 measures it directly on every run. |
| `home_types.single_family_bedrooms` | 3: the bedroom count the single-family ZHVI (A16.sfr) stands for (national ratio to all homes 0.987, so it sits on the 3 BR value too). B30 measures all three sizes on every run and stops if a configured count is no longer the nearest one. |
| `home_types.keep_dod_order` | `true`: at equal bedrooms a townhouse is never priced below an apartment, nor a single-family home below a townhouse. Where the condo factor is above the single-family factor, B30 raises the single-family factor to it, so the three share the condo level and the rows are marked `floored` (D34, the buy-mode counterpart of `rent_type_series.single_family_not_below_townhouse`). |

**Why a VA loan.** Buy mode models the financing a service member most often uses: a VA-guaranteed loan, no down payment, no mortgage insurance, with the funding fee financed. Members with a service-connected disability rating are exempt from the fee, and subsequent-use VA loans pay 3.3% with less than 5% down; both are one-parameter sensitivity checks. Sources: VA funding fee table (rates effective 7 Apr 2023) and the Freddie Mac PMMS (A7), in [SOURCES.md](SOURCES.md).

**Why locality tax and insurance.** State effective property-tax rates run from about 0.31% (Hawaii) to 1.79% (Illinois), and premiums vary with state and hazard, so national figures misstate cost in both directions (decision 2.7).

- **Property tax:** the ACS aggregate real estate taxes paid (B25090_001E) divided by the aggregate value (B25079_001E), both for owner-occupied units, summed over the MHA's ZCTAs. Summing the aggregates weights each ZCTA by its housing stock and avoids a ratio of medians. ACS taxes are self-reported and assessments lag market value, so the rate is a typical effective rate, not a statutory one.
- **Insurance:** FIO "Premiums Per Policy" (written premium ÷ policies in force at year end), the median over the MHA's published ZIPs. Flat dollars rather than a share of value, because premiums track replacement cost and hazard more than market value.
- **State fallback:** the same ratio (tax) or median (insurance) over every real-MHA ZIP in the MHA's state, the state being the MHA code's two letters. Each MHA's row carries `tax_source` and `insurance_source` (`locality` or `state_fallback`), which become the payload caveats `tax_state_fallback` and `insurance_state_fallback`.

**Insurance state fallback (D11, decided 18 Oct 2026).** The FIO workbook has no state column, so the fallback is the median over the published ZIPs of every real MHA in the same state, rather than the NAIC state average: one source and one data year for every premium. No 2026 MHA needed it.

**Why not scaled to 2026 (decision N2).** Premiums have risen since 2022, so buy-mode costs understate 2026 insurance. Scaling would need an inflator the project would have to choose and defend; using the published year keeps the number traceable. B11 records the limitation in its manifest, and B23 and the write-up state it.

**Townhouse in buy mode (D22, decided 1 Nov 2026, option B).** Zillow publishes no townhouse home value. D19 let the all-homes ZHVI (B9) stand for the 2 BR townhouse, but the second grid run (24 Oct) showed that per ZIP the all-homes value is 1.356 × the 2 BR value, 1.003 × the 3 BR value and 0.823 × the 4 BR value, and that the single-family series sits almost on it (national ratio 0.987). The 3 BR townhouse therefore came out above the 3 BR single-family home in buy mode. B30 now prices the townhouse at a fixed position between the MHA's condo/co-op and single-family factors: g_townhouse = g_condo + 0.5 × (g_single-family − g_condo). The 2 BR townhouse, E-5's buy benchmark, no longer equals B11, so B11, B14–B18 and the handoff are rerun. B11 is kept as the all-homes ownership cost, and B30 checks that the all-homes value (both factors 1) reproduces it to the cent, so the two still run one model. The 0.5 is an assumption, not a measurement; a townhouse factor is `zip` only when both of its sides are, so an MHA without condo data carries `type_factor_national` on its townhouse values. Options A (keep D19 and state that buy mode cannot separate townhouses from single-family homes) and C (anchor buy mode to the 2 BR ZHVI series) were not taken. B30's `reference_check` still records which bedroom count the all-homes value resembles.

**Home types at equal bedrooms (D34, decided 7 Nov 2026).** A sense check against local rents in Colorado Springs (CO046) found the 3 BR single-family rent at $3,982 a month, against about $2,000–$2,800 asked locally (rent only) and a HUD 3 BR Fair Market Rent of $2,420 (with utilities). The cause was in both B29 and B30. Zillow's type series compare *typical* homes: its typical single-family rental is about a 3 BR home, while its typical home of any kind is smaller. The single-family ÷ all-homes ratio (1.324 in Colorado Springs) therefore carries both "a house, not a townhouse" and "a larger home". B29 then multiplied by the SAFMR 3 BR ÷ 2 BR ratio (1.391) as well, so the extra bedrooms were counted twice: $2,163 × 1.391 × 1.324 = $3,982. Buy mode had the same fault, and a second one that D22 had measured but not removed: B30 scaled bedrooms from 2 BR although the all-homes value is a 3 BR value, so every home above two bedrooms was priced roughly a third too high.

- **The rule.** Each Zillow series is placed at its own typical bedroom count before bedrooms are added, so a type ratio carries only the building difference. Rent: factor at equal bedrooms = type ratio × SAFMR 2 BR ÷ SAFMR *k* BR (*k* = 2 for multifamily, 3 for single-family). Buy: factor = type ratio × ZHVI ladder at 3 BR ÷ ladder at *k* BR (*k* = 2 for condo/co-op, 3 for single-family), and bedrooms scale from 3 BR.
- **The floor (rent).** Once size-matched, the single-family factor came out below 1 in 192 of 289 MHAs (median 0.95): at equal bedrooms Zillow's single-family rents sit at or slightly below the all-homes rent scaled by HUD's ratios. A house renting for less than a townhouse with the same bedrooms would make DoD's ladder fall with rank in those MHAs, and more likely reflects the D19 assumption that the all-homes rent is exactly a 2 BR home than a real discount. B29 therefore holds the single-family home at the townhouse of the same bedrooms there (`rent_type_series.single_family_not_below_townhouse`), and keeps the measured value in `size_matched_factor`.
- **The floor (buy).** Compared at equal bedrooms, condos cost more than single-family homes in 94 of 299 MHAs in the 7 Nov run (10 before D34, when the 2 BR base hid it), mostly coastal and urban markets. Left alone, a 2 BR apartment would be priced above a 2 BR townhouse there, and buy costs would fall with rank. B30 applies the same rule as rent (`home_types.keep_dod_order`): the single-family factor is raised to the condo factor, and the townhouse midpoint lands on the same level.
- **What changes.** Rent: single-family homes only, down a median 18.3% across the 289 MHAs with rent data (range −28.2% to +0.7%, computed from the 1.2.0 grid). Colorado Springs is one of the 192 floored MHAs: its size-matched factor is 0.952, so its 3 BR single-family rent becomes $3,008, the 3 BR townhouse, down from $3,982 (the measured value, $2,863, is kept in `size_matched_factor`). In floored MHAs every standard between the 3 BR townhouse and the 3 BR single-family home costs the same, so E-6, E-7, E-8, W-2 and O-3 with dependents share one benchmark there. Apartments and townhouses are unchanged, so E-5's rent benchmark and the H1/H2 findings, which use it, are unchanged. Buy: townhouses and single-family homes fall (national medians: about 17% and 26%); apartments are unchanged. These buy figures are estimates from the 2026 manifest medians; the rerun's B30 manifest and B23 report give the measured ones. Every grid view that uses a single-family home changes, as do O-3 in both modes (rent: median −18.0%) and E-5 in buy mode.
- **Options not taken.** Keeping the method and documenting the bias (O-3 and the larger off-standard views stay overstated); pricing every bedroom count from HUD's SAFMR and using Zillow only for the level (a larger change to D19, deferred). Re-basing the rent all-homes series on a fractional bedroom count would remove the need for the floor, but it would change E-5's benchmark and the research findings, so it is left as a question for after M7.

---

## `config/ui_text.json` (A13 display text)

The wording the map shows, read only by B21 (`build_ui_metadata.py`), which copies it into `ui_metadata_2026.json`. It sits beside A13 as part of the display configuration, in its own file so that a wording change touches only B21: B12–B18 record the hash of `classification.json`, not this file, and are not rerun (decided 18 Oct 2026).

| Field | Meaning |
|---|---|
| `_doc`, `version` | Pointer to this page; schema version of this file. |
| `no_data_label` | Legend text for `no_data_color`. |
| `display_names` | By area code, the name the map shows where the DTMO name reads badly: `XX499` is "UNKNOWN, NA", and `GA073` is "FORT GORDON, AL" in DTMO's file. B3 and `name` keep the DTMO text. |
| `modes` | Display label for `rent` and `buy`. |
| `statuses` | A `label` and a `text` for each status code in data contract section 5.4. B21 stops if a code is missing or an extra one appears. |
| `caveats` | A `title` and a `text` for each caveat id in section 5.5; B21 adds each id's level from the contract. Same check. |
| `global_caveats` | Limitations that apply to the whole map: `id`, `title`, `text`. |
| `geometry` | `method` and `authority` statements for the area outlines. |
| `grid.titles` | Control titles beyond `rank` and `home_type`: `dependents`, `metric`, `mode`. |
| `grid.off_standard_scale` | `title` and `subtitle` for the legend when the second scale is active. |
| `sources` | One entry per incorporated source shown in the map's attribution (C20): `id` (node), `title`, `provider`, `url`, `license`, `used_for`. Follows [SOURCES.md](SOURCES.md). |

**Wording rules.** Each text says what the reader is looking at and why a value is missing or qualified, in plain language, without the project's node ids. A text that states a number (a year, a count) is avoided where B21 already carries it, so the file does not go stale when a window changes; `insurance_2022_dollars` names its year because the caveat id does.

---

*AI-assistance disclosure: Claude (Anthropic) moved these explanations out of the config files and edited them for accuracy with the author. The decisions are the author's.*
