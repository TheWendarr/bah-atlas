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
| `profiles[].anchor_dwelling`, `anchor_bedrooms` | The DoD housing standard for the grade, and the SAFMR bedroom count it maps to. |
| `profiles[].cost_share_monthly` | DTMO member out-of-pocket dollars for the cell. |
| `benchmarks.rent_primary` | `zori_utilities_adjusted`: B8 ZORI, grossed up to include utilities with the B5 split. |
| `benchmarks.rent_crosscheck`, `safmr_bedroom_field` | HUD SAFMR (B10) at the profile's `anchor_bedrooms`. |
| `cost_share.*` | Where the cost-share dollars come from: method, year, source, URL, local artifact, SHA-256, the values read, and the date verified. `make verify` checks the SHA-256 against the fetch record. |

**The test target is not 95%.** 37 U.S.C. 403(b)(3) sets BAH at the local cost of adequate housing minus 5% of the *national* average cost for the grade. That deduction is the same dollars at every duty station. So BAH covers exactly 95% of local cost only where local cost equals the national mean: more in expensive MHAs, less in cheap ones.

B12–B15 therefore test `adequacy_ratio` = (BAH + `cost_share_monthly`) ÷ benchmark against 1.00. `coverage_target` survives only for the flat-95% sensitivity column (`flat95_gap` = BAH ÷ cost − 0.95).

**Why these profiles.**

- **E-5 with dependents** is the primary research profile. DoD's housing standard for E-5 is a 2-bedroom townhouse, so the anchor maps to a single bedroom count without interpolation.
- **O-3 with dependents** is the contrast profile. DoD's O-3 standard sits 98% of the way from a 3-bedroom townhouse to a 3-bedroom single-family home. It therefore differs from the primary in grade band, bedroom count and dwelling type at once.
- **Source:** DoD BAH housing standards by pay grade (BAH Primer; summarized at military.com, *Paycheck Chronicles*, 4 Dec 2014). This is listed in [SOURCES.md](SOURCES.md) under *Concepts & methods*.

**Why one ZORI series serves both profiles.** ZORI has no bedroom breakdown, so one ZIP-level series applies to every profile, made utilities-inclusive with B5. The bedroom-specific comparison comes from the SAFMR cross-check.

**Cost share.** These are the member out-of-pocket (absorption) dollars per cell, read from DTMO's annual out-of-pocket table: the same amount at every duty station. The 2026 values are E-5 with dependents $126 and O-3 with dependents $151. See the A12 out-of-pocket entry in [SOURCES.md](SOURCES.md).

## A14 housing standards (`config/housing_standards.json`)

Decision D18 (18 Oct 2026) lets the map show any rank with or without dependents in any of DoD's six housing profiles. This file holds what DoD itself prescribes for each of those 46 cells: the housing standard BAH is built on, and the member cost share deducted from it. B29 and B30 read the home types, the coverage metrics (B12–B15) read the research profiles' standards, B23 checks the table, and B31 ships it to the map.

| Field | Meaning |
|---|---|
| `_doc` | Pointer to this page. |
| `version`, `bah_year` | Schema version of this file; the BAH year the cost shares belong to. |
| `home_types[]` | DoD's six housing profiles, cheapest first: `id`, `building` (`apartment`, `townhouse`, `single_family`) and `bedrooms`. The order is the order standards interpolate in. |
| `reference_type` | `th2`, the 2-bedroom townhouse. B8 (all-homes ZORI) and B9 (all-homes ZHVI) are taken to stand for this dwelling, so every other type is a ratio to it (D19). |
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
| `version` | Schema version. Version 2 (18 Oct 2026) moved the explanations here and added the D2 and D3 entries. |
| `coverage_target` | Must equal A12's value (0.95). Used only by the flat-95% reading. |
| `no_data_color` | Fill for areas with no value: CCGs (decision N1), MHAs without a benchmark, and the territory bucket. |
| `palette_source` | Attribution for the palette. ColorBrewer requires credit, so this text is shown on the map. |
| `default_metric` | Layer shown first: `adequacy_ratio`. |
| `metrics.<name>.label`, `short_label` | Legend and control text. |
| `metrics.<name>.role` | `primary` (the statutory test), `descriptive` (plain BAH-versus-cost views) or `sensitivity` (alternative readings, decision D3). |
| `metrics.<name>.modes` | Which modes have this metric. The SAFMR layers are rent only, because HUD publishes rents, not ownership costs. |
| `metrics.<name>.format` | `percent` or `usd`, for legend and popup formatting. |
| `metrics.<name>.method`, `neutral`, `breaks`, `colors`, `class_labels` | Fixed half-open classes `[lower, upper)`. There is one more colour and label than breaks, and `neutral` must sit in the middle class. |
| `clusters.variable`, `alpha` | The cluster test: `adequacy_gap` at pseudo p < 0.05. |
| `clusters.legend_title` | Labels every local class as exploratory (decision D2). |
| `clusters.classes` | LISA quadrant codes with their label and colour. |
| `clusters.fdr_marker` | Outline that marks MHAs still significant after the Benjamini–Hochberg false-discovery-rate correction (decision D2). |

**Why fixed breaks rather than quantiles.** The research question asks whether BAH meets its statutory design, a fixed point. Fixed breaks keep that point visible as the near-white middle class and make maps comparable across profiles and modes. Quantile breaks would always paint the same share of MHAs red, whether or not any MHA misses the design.

The palette is ColorBrewer RdBu, 7 classes, which is colour-blind safe: red for shortfall, blue for surplus.

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

How a ZHVI home value (B9) becomes a monthly ownership cost comparable to BAH. `ownership_cost.py` reads and validates every field; `tax_insurance_to_mha.py` reads the property-tax and insurance years. Version 2 (18 Oct 2026, A8) replaced the national tax and insurance placeholders with per-MHA values and moved the explanations here, so B11 and everything after it are rerun once.

| Field | Meaning |
|---|---|
| `_doc` | Pointer to this page. |
| `version` | Schema version of this file. Version 2: locality tax and insurance, values only. |
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

**Why a VA loan.** Buy mode models the financing a service member most often uses: a VA-guaranteed loan, no down payment, no mortgage insurance, with the funding fee financed. Members with a service-connected disability rating are exempt from the fee, and subsequent-use VA loans pay 3.3% with less than 5% down; both are one-parameter sensitivity checks. Sources: VA funding fee table (rates effective 7 Apr 2023) and the Freddie Mac PMMS (A7), in [SOURCES.md](SOURCES.md).

**Why locality tax and insurance.** State effective property-tax rates run from about 0.31% (Hawaii) to 1.79% (Illinois), and premiums vary with state and hazard, so national figures misstate cost in both directions (decision 2.7).

- **Property tax:** the ACS aggregate real estate taxes paid (B25090_001E) divided by the aggregate value (B25079_001E), both for owner-occupied units, summed over the MHA's ZCTAs. Summing the aggregates weights each ZCTA by its housing stock and avoids a ratio of medians. ACS taxes are self-reported and assessments lag market value, so the rate is a typical effective rate, not a statutory one.
- **Insurance:** FIO "Premiums Per Policy" (written premium ÷ policies in force at year end), the median over the MHA's published ZIPs. Flat dollars rather than a share of value, because premiums track replacement cost and hazard more than market value.
- **State fallback:** the same ratio (tax) or median (insurance) over every real-MHA ZIP in the MHA's state, the state being the MHA code's two letters. Each MHA's row carries `tax_source` and `insurance_source` (`locality` or `state_fallback`), which become the payload caveats `tax_state_fallback` and `insurance_state_fallback`.

**Insurance state fallback (D11, decided 18 Oct 2026).** The FIO workbook has no state column, so the fallback is the median over the published ZIPs of every real MHA in the same state, rather than the NAIC state average: one source and one data year for every premium. No 2026 MHA needed it.

**Why not scaled to 2026 (decision N2).** Premiums have risen since 2022, so buy-mode costs understate 2026 insurance. Scaling would need an inflator the project would have to choose and defend; using the published year keeps the number traceable. B11 records the limitation in its manifest, and B23 and the write-up state it.

---

## `config/ui_text.json` (A13 display text)

The wording the map shows, read only by B21 (`build_ui_metadata.py`), which copies it into `ui_metadata_2026.json`. It sits beside A13 as part of the display configuration, in its own file so that a wording change touches only B21: B12–B18 record the hash of `classification.json`, not this file, and are not rerun (decided 18 Oct 2026).

| Field | Meaning |
|---|---|
| `_doc`, `version` | Pointer to this page; schema version of this file. |
| `modes` | Display label for `rent` and `buy`. |
| `statuses` | A `label` and a `text` for each status code in data contract section 5.4. B21 stops if a code is missing or an extra one appears. |
| `caveats` | A `title` and a `text` for each caveat id in section 5.5; B21 adds each id's level from the contract. Same check. |
| `global_caveats` | Limitations that apply to the whole map: `id`, `title`, `text`. |
| `geometry` | `method` and `authority` statements for the area outlines. |
| `sources` | One entry per incorporated source shown in the map's attribution (C20): `id` (node), `title`, `provider`, `url`, `license`, `used_for`. Follows [SOURCES.md](SOURCES.md). |

**Wording rules.** Each text says what the reader is looking at and why a value is missing or qualified, in plain language, without the project's node ids. A text that states a number (a year, a count) is avoided where B21 already carries it, so the file does not go stale when a window changes; `insurance_2022_dollars` names its year because the caveat id does.

---

*AI-assistance disclosure: Claude (Anthropic) moved these explanations out of the config files and edited them for accuracy with the author. The decisions are the author's.*
