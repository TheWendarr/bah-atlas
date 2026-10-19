# M6 plan — Layer 2 to Layer 3 handoff

**Milestone:** M6 2.7 Front-End Payload + 2.8 Writeup · **due Fri 30 Oct 2026** (dates below move with any schedule change) · **written:** 18 Oct 2026 · tracker: [WBS](../WBS.md) · progress for the period: [24 Oct note](../progress/2026-10-24.md)

M6 is the handoff from the offline pipeline to the map. When it closes, Layer 3 can be built against a fixed set of files:

- **B20** attribute payload
- **B21** UI metadata
- **B22** build manifest
- **B27** hotspot overlay
- **B7** polygon tiles, rebuilt with the B28 polygons merged in (D9)

The exact shape of every one of these files is fixed in the **[data contract (Layer 2 → Layer 3 ICD)](../data-contract.md)**, tracked as W2. This page records the decisions behind it and how each node will be built and checked.

**In progress (18 Oct):** A8, B20, B21, B22, B23, B28, W1, W2 (required); A9, B24, B19, B27 (optional). B19 is tracked under M6 from 18 Oct (D15).
**Code complete (18 Oct):** every Layer 2 node. What remains is the end-to-end run (`make layer2`), the author's review of the B23 report, W1, and the D10 delivery (`make deliver`).
**Scrapped:** B26, A10, B25.
**Layer 3 (C1–C24):** not started until this handoff exists.

## 1. Decisions (18 Oct 2026)

| Ref | Decision | Effect on the work |
|---|---|---|
| D1 | The project's primary test variable is `adequacy_gap` = (BAH + member cost share) ÷ local cost − 1. `flat95_gap` (BAH ÷ cost − 0.95) is kept as the sensitivity check. | Research question and method reworded. No pipeline change: B12–B18 already use it. |
| D2 | **Local clusters, option C.** LISA classes at pseudo p < 0.05 are shown and labelled *exploratory*. MHAs that stay significant after the Benjamini–Hochberg false-discovery-rate correction are marked as well. | B27 carries both fields. A13 gets an "exploratory" legend wording and an FDR marker style. W1 reports the global test as the confirmatory result and the local classes as exploratory. |
| D3 | **Payload option D.** Each value carries its inputs, and the sensitivity values (`flat95_gap`, SAFMR adequacy ratio, SAFMR design gap) are selectable map layers as well as popup numbers. | B20 carries them; A13 gains three metric entries (section 3, B21). |
| D5 | **Cluster results live in a separate file (B27)**, keyed like B20. B20 holds measured values only. | B27 started. C16 (hotspot toggle, optional) reads it. |
| D6 | **Contract conventions, all option (a):** (1) `schema_version` (semantic) plus `bah_year`; (2) ratios to 4 decimals, dollars whole; (3) one file nested by area code; (4) `null` plus a `status` code for missing values; (5) caveat ids in the data, caveat text in B21; (6) `build_id` points to B22, which holds windows and checksums. | Applies to B20, B21, B22, B27. |
| D8 | **H2 reduced.** H2 is tested with spatial regression (B19) on three explanatory variables: rent level (B8), rent growth (ZORI history, A3) and urbanicity (population density from ACS, A9 → B24). BEA Regional Price Parities (A10, B25) are scrapped. | A9, B24, B19 started; A10, B25 scrapped. Reasons are under "H2 chain" in section 3. |
| N1 | **County Cost Groups: polygon and BAH rate only.** CCGs have no DoD rent/utilities split, and many rural ZIPs have no ZORI. They are mapped with their BAH rates; their adequacy metrics are `null` with status `ccg_no_benchmark` and a visible caveat. | B20, B21 caveat, research proposal scope, SOURCES. |
| N2 | **Insurance as published.** The Treasury FIO ZIP-level premiums (2018–2022) and the NAIC state fallback (data year 2022) are used without scaling to 2026. The resulting understatement of 2026 premiums is documented as a limitation. | A8, SOURCES, B23, W1. |
| 2.1 | CCGs and the territory bucket (XX code) get map polygons, even though no authoritative polygon exists. The method is stated wherever the polygons appear. | B28. |
| 2.2 | Alaska and Hawaii MHAs carry their values on the map but stay out of the spatial statistics. | B20 `cluster_scope: false`. |
| 2.4 | Where buy mode has a home value but no ZORI utilities estimate (10 MHAs), the payload uses PITI (`own_housing_monthly`) with a note that it excludes utilities because the MHA has no ZORI data. | B20 status `piti_only_no_zori`. |
| 2.7 | Property tax and insurance come from authoritative locality sources. A8 is now **required** and tracked under M6, because B11–B18 are rebuilt on it before the payload is built. | A8. |
| 2.9 | H3 is removed from the project. | B26 scrapped. |
| 2.10 | Front-end build choices (bundler, hosting, basemap) wait until this handoff exists. | No Layer 3 work in M6. |
| D9 | **One tile layer for every area.** B7 becomes a single vector layer `areas` holding the 299 MHAs, 39 CCGs and the territory bucket, keyed on `code` with a `class` property, tiled in one tippecanoe run. (Option B, a second `non_mha` layer beside B7's `mha` layer, was rejected: separate runs simplify each side of an MHA-to-CCG border independently and leave slivers, the id field `mha` would hold CCG codes, and every front-end join would have to be routed between two layers.) | B7 is rebuilt in M6 with B28 as an input; B6 and B16–B18 are unchanged. The ICD (W2) specifies the layer. C1 reads B7 only. |
| D10 | **Processed outputs stay off the repository until Layers 1 and 2 are complete.** They are then added in one commit with the author's write-up of every action and decision, and Layer 3 starts after that commit. | ICD section 12. No release or `web/data/` copy during M6. |
| D11 | **Insurance state fallback from FIO itself (decided 18 Oct).** The FIO workbook has no state column. The fallback premium is the median over the published ZIPs of every real MHA in the same state, instead of the NAIC state average named in the 18 Oct plan. | One source and one data year for every premium; no second (NAIC) source to fetch and cite. The NAIC figure covers HO-3 policies statewide, not ZIPs near installations. No 2026 MHA needed it. |
| D12 | **Map wording in `config/ui_text.json`** (part of A13), read only by B21: status and caveat texts, global caveats, boundary statements, source attributions. | A wording change reruns only B21; B12–B18 keep their recorded hashes. Documented in `docs/configuration.md`. |
| D13 | **99,999 permutations is the Makefile default**, matching the recorded run. | A full rebuild reproduces the recorded B17/B18 evidence. |
| D14 | **Handoff files are written to `data/processed/handoff/`**, apart from the intermediate outputs. | The D10 delivery commit copies one folder. ICD 1.0.2, section 12. |
| D15 | **B19 is done now, inside M6 (decided 18 Oct).** H2 is tested before Layers 1 and 2 are declared complete, rather than after M6 by 16 Nov. Rent growth is annualised over **5 years** before the B8 window, in the same calendar months. | `milestones.csv` M6 tracks A8 and B19. `make regression` (B24 then B19); `GROWTH_YEARS ?= 5`. B23 and W1 report the H2 result. |
| D16 | **Delivery location: option B, a frozen copy in `delivery/2026/` (decided 18 Oct).** Option A (tracking `data/processed/handoff/` in place) was rejected: every rerun would rewrite the 17.6 MB tile archive in git history and move the Layer 3 input without a decision. | ICD 1.0.3, section 12. `make deliver` is the only writer and copies only when its six gates pass; `.gitignore` admits `delivery/*/*.pmtiles` only. |
| D17 | **Processed data enters the repository only after Layers 1–2 are complete and validated (restates D10 as gates, 18 Oct).** | `make deliver` refuses unless every Layer 1–2 node is complete or scrapped (W1 aside), the contract checks and `make verify` pass, the B23 verdict is PASS for this exact build, the build came from committed code, and W1 is written. The B23 report is written to the git-ignored `data/processed/qa/` and travels with the delivery. |

**Config text (COA 2, decided 18 Oct):** A12 and A13 now hold values only, and their explanations live in [`docs/configuration.md`](../configuration.md). The D2 cluster fields and the D3 sensitivity layers are in A13. The whole pipeline is rerun once so every recorded hash matches (`make verify`). `config/ownership.json` follows the same split when A8 rewrites it.

## 2. Draft data contract (B20)

**Superseded on 18 Oct by the [data contract (ICD)](../data-contract.md#5-b20--attribute-payload-payload_2026json).** The ICD uses the pipeline's own column names (`bah_monthly`, `cost_share_monthly`, `cost_monthly`) in place of the short names below, adds `design_coverage`, `safmr_monthly` and `own_housing_monthly` as inputs, and adds area-level caveats. The draft is kept as the record of the 18 Oct discussion.

Illustrative numbers; conventions per D6. Comments mark the decision each part follows.

```jsonc
{
  "schema_version": "1.0.0",
  "bah_year": 2026,
  "build_id": "sha256 of the B22 manifest",
  "profiles": ["e5_dep", "o3_dep"],
  "modes": ["rent", "buy"],
  "areas": {
    "CO018": {
      "class": "mha",                         // mha | ccg | unknown
      "cluster_scope": true,                  // false for AK, HI, CCG, XX (decision 2.2)
      "e5_dep": {
        "rent": {
          "status": "ok",                     // ok | no_zori | ccg_no_benchmark | ...
          "adequacy_ratio": 1.0463, "design_gap_usd": 99,
          "coverage_ratio": 0.9874, "surplus_usd": -27,
          "bah": 2112, "cost_share": 126, "cost": 2139,          // D3: inputs
          "flat95_gap": 0.0374,                                  // D3: sensitivity layer
          "safmr_adequacy_ratio": 1.0210, "safmr_design_gap_usd": 46,
          "caveats": ["utilities_grossed_up"]                    // D6(5): text in B21
        },
        "buy": {
          "status": "ok",                     // or piti_only_no_zori (decision 2.4)
          "...": "same metric fields; no SAFMR fields",
          "caveats": ["tax_insurance_locality"]
        }
      },
      "o3_dep": { "...": "..." }
    },
    "ZZ001": {
      "class": "ccg", "cluster_scope": false,
      "e5_dep": { "rent": { "status": "ccg_no_benchmark", "bah": 1650,
                            "adequacy_ratio": null, "caveats": ["ccg_geometry", "ccg_no_benchmark"] } }
    }
  }
}
```

## 3. Node plans

Every script follows the existing pattern: read inputs as-is, validate loudly, write tidy outputs plus a manifest, and test on synthetic fixtures. `make evidence` copies each new manifest into `docs/evidence/`.

### B28 · CCG and territory polygons, and the B7 rebuild — target Wed 21 Oct

- **Why:** DoD publishes no polygons for County Cost Groups. The DTMO crosswalk does assign ZIPs to them: in 2026, 20,465 ZIPs map to the 39 ZZ codes and 214 ZIPs to the single XX code.
- **Method:** the same ZIP → ZCTA → dissolve that builds B6 (A2 + B1), applied to the `ccg` and `unknown` classes.
  - Extend `build_mha_geometry.py` with `--classes ccg,unknown` and write `non_mha_YYYY.gpkg` / `.geojson`.
  - B6 itself is untouched, so B16–B18 do not change.
- **Annotation:** every feature carries `class` and `geometry_source: "ZCTA dissolve of DTMO ZIP assignments (non-authoritative)"`. The same statement appears in SOURCES.md, the data dictionary, B21 (shown in the UI) and W1.
- **Checks:**
  - every ZZ and XX code with ZIPs gets a feature
  - no ZCTA is assigned to both an MHA and a CCG
  - unmatched ZIPs are reported, as B6 does
  - confirm which territory the XX bucket covers (expected: Puerto Rico). **Result (18 Oct):** wider than expected: Puerto Rico (ZIP3 006, 007, 009), the U.S. Virgin Islands (008), the Pacific 969 range (Guam, the Northern Mariana Islands and the freely associated states) and one 967 ZIP, which in this bucket is expected to be 96799 (American Samoa). Recorded in ICD section 4 (1.0.1).
- **Built (code, 18 Oct):** `make non-mha` runs `build_mha_geometry.py --classes ccg,unknown` on B1 and writes `non_mha_2026.gpkg` / `.geojson` and the B28 manifest. B6 and B28 stay separate runs (mixing `mha` with the other classes is refused), so B6 is untouched. Six synthetic tests cover the classes, the manifest counts, the shared-ZCTA stop and the unchanged B6 path. The workstation run settles the counts and the XX territory (manifest `unknown_zip3_prefixes`).
- **Tiles (D9):** B28 is not tiled on its own. `build_mha_pmtiles.py` takes the B6 and B28 GeoJSONs, writes each feature with `code` and `class`, and tiles all of them in one run to `areas_2026.pmtiles`, layer `areas`, `promoteId: "code"` (ICD section 4). The B7 manifest records both inputs and their hashes; its docstring and `make tiles` change to match. B7 stays complete in M2: the rebuild is M6 work, as A8 is. **Built (code, 18 Oct):** `make tiles` now writes `areas_2026.pmtiles` and removes the retired `mha_2026.pmtiles` and its manifest first, so `make evidence` copies only the new B7 manifest. Five tests cover the merge and a full tippecanoe run (skipped where tippecanoe is absent).

### A8 · property tax and insurance by locality — target Sat 24 Oct (required, tracked under M6)

- **Property tax:** ACS 5-year detailed tables at ZCTA level through the Census API, with the year pinned.
  - Variables: B25090_001E (aggregate real estate taxes paid) and B25079_001E (aggregate value of owner-occupied units).
  - MHA effective rate = Σ taxes ÷ Σ value over the MHA's ZCTAs. Summing aggregates weights each ZCTA by its housing stock and avoids a ratio of medians.
  - An MHA whose ZCTAs have no data falls back to its state rate, and is flagged.
- **Insurance (N2):** Treasury FIO average homeowners premium by ZIP, 2018–2022, as published.
  - The file covers only ZIPs with at least ten insurers and fifty policies.
  - Value per MHA = the median of its ZIPs, as B8–B10 do. ~~MHAs with no published ZIP use the NAIC state average.~~ Proposed instead (D11, below): the median over the published ZIPs of every real MHA in the same state.
  - The year used and the understatement of 2026 premiums are recorded in the manifest and in SOURCES.
- **Pipeline:**
  - Change A8 in `fetch_sources.py` from `manual` to `api` (ACS) plus `direct` (FIO workbook).
  - Add `benchmarks/tax_insurance_to_mha.py`, which writes `mha_tax_insurance.csv` with a source flag per MHA (`locality` or `state_fallback`).
  - Point `config/ownership.json` at it. The ACS client is shared with A9.
- **Rerun chain:** B11 → B14/B15 → B17/B18 buy-mode tests. Rent results do not change. The M5 buy-mode Moran's I values (E-5 0.397, O-3 0.482) are replaced, and the progress note reports old against new.
- **PITI-only rows (decision 2.4) are computed in B14/B15, not B20.** `coverage_metrics.py` gives the 10 home-value-but-no-ZORI MHAs their metrics against PITI (`own_housing_monthly`) with status `piti_only_no_zori`, replacing `no_utilities`. `spatial_stats.py` then tests only buy rows with status `ok`, so these MHAs stay out of the buy-mode statistics exactly as they are today (6 of them are in CONUS).
- **Built (code, 18 Oct):**
  - `fetch_sources.py`: A9 is a pinned Census API query (`acs5_2024_zcta.json`: B25090_001E, B25079_001E, B01003_001E for every ZCTA), with the key read from `CENSUS_API_KEY` and kept out of the manifest; A8 is the FIO workbook, `direct`. One ACS query serves A8 tax and A9 population, and A2's ALAND20 gives land area, so B24 needs no second pull.
  - `benchmarks/tax_insurance_to_mha.py` + `fio_insurance.py` (`make taxins`) write `mha_tax_insurance.csv` and its manifest; the workbook layout was checked against the published file (sheet `Supporting Underlying Metrics`, one row per ZIP and year, 25,593 ZIPs a year).
  - `config/ownership.json` version 2 holds values only (`locality_effective_rate`, `locality_average_premium`, ACS vintage 2024, FIO year 2022); its explanations moved to `docs/configuration.md`, and `make check-config` now covers it.
  - `ownership_cost.py` reads the per-MHA rate and premium and carries the source flags into `mha_ownership.csv`; `coverage_metrics.py` and `spatial_stats.py` implement the PITI-only rule above.
  - 12 new tests (73 in all) pass.
- **Done when:** B11 has no placeholder warnings, every MHA has a sourced rate with its source flag, and the change in buy-mode results is recorded.
- **Result (18 Oct, commit `bf65c6b`):** all 299 MHAs have local tax and insurance values (no state fallback). Tax rates 0.23–2.40% (median 0.79%); premiums $833–$15,638 (median $1,625). Buy mode: E-5 median adequacy 0.779 → 0.768 (267 of 289 below design, unchanged); O-3 0.985 → 0.972 (159 → 166 below). Moran's I buy: E-5 0.397 → 0.359, O-3 0.482 → 0.434. Rent unchanged. Details and the MA119 (Nantucket) extreme are in the [24 Oct note](../progress/2026-10-24.md), part 4.

### B20 · attribute payload — target Wed 28 Oct

- **Built (code, 18 Oct):** `pipeline/handoff/` holds the four builders (B22, B20, B21, B27), `contract.py` (the contract's names, codes and rounding rules, shared by all of them) and `validate_handoff.py` (ICD checks 3–8). `make handoff` writes the five files and `SHA256SUMS` to `data/processed/handoff/` and validates them; 8 synthetic tests cover a build that conforms and four kinds of break. Writing it moved B27's p-values to 5 decimals (ICD 1.0.2).

- **Content:** the payload in [ICD section 5](../data-contract.md#5-b20--attribute-payload-payload_2026json); written after B22, whose hash it carries as `build_id`.
- **Areas:** the 299 MHAs, the 39 CCGs (BAH rate only, N1) and the XX bucket (status `no_rate`). Alaska and Hawaii are included with `cluster_scope: false`.
- **Values:** taken only from the B12–B15 output and B4; B20 computes nothing new.
- **Checks:** the conformance checks in [ICD section 11](../data-contract.md#11-conformance-checks), run by a standard-library validator in `tests/` against B20, B21 and B27. The file size is reported (expected under 300 KB after gzip).
- **Docs:** the ICD is the reference; the data dictionary points to it.

### B21 · UI metadata — target Wed 28 Oct

- **Profiles and metrics:** profile labels (A12), and metric definitions with A13 classes, colours and labels for all seven map layers. The three D3 sensitivity layers reuse existing class schemes, so no new breaks need to be designed:
  - `flat95_gap` uses the `coverage_ratio` breaks shifted by −0.95, which draws the same map as `coverage_ratio`, labelled as the fixed-95% reading
  - `safmr_adequacy_ratio` uses the `adequacy_ratio` breaks
  - `safmr_design_gap_usd` uses the `design_gap_usd` breaks
- **Names and caveats:** area names and classes (B3, B1, B28), status texts, and the caveat texts for the ten ids in [ICD section 5.5](../data-contract.md#55-caveat-ids). Writing the ICD added `tax_state_fallback` and `insurance_state_fallback`, one per A8 source flag.
- **Also:** benchmark windows and the source attributions that C20 will display.

### B27 · hotspot overlay payload — target Wed 28 Oct (optional)

- **Content:** [ICD section 7](../data-contract.md#7-b27--hotspot-overlay-hotspots_2026json-optional): `adequacy_gap` only, keyed like B20, one entry per in-scope MHA, profile and mode, using the B18 column names (`cluster`, `lisa_p_sim`, `lisa_fdr_significant`, `gi_class`), plus the global result per test.
- **Labelling (D2):** the file and its legend label the p < 0.05 classes as exploratory and mark the FDR survivors.
- **Before building:** rerun B18 once with `make spatial PERMUTATIONS=99999`.
  - With 9,999 permutations, the smallest local p-value possible is 0.0002. The FDR cutoff for the top-ranked MHA is 0.05 ÷ 283 ≈ 0.00018, below that floor.
  - So the current count of two FDR survivors may be limited by permutation resolution rather than the data. The rerun settles which MHAs are marked; the result is recorded either way.
  - **Result (18 Oct):** at 99,999 permutations the primary test still has 2 FDR survivors (1 HL, 1 LH; cut-off p = 0.00011), so the count reflects the data. Buy mode after A8: E-5 29, O-3 23.

### H2 chain (D8, reduced) — A9 done 18 Oct; B24 and B19 code written 18 Oct, inside M6 (D15)

H2 asks what the adequacy gaps are associated with. The research question itself is answered by B12–B18. H2 supplies the explanation the instructor's original redirect asked for.

- **A9 (ACS):** population and land area per ZCTA through the same Census API client as A8, with the year pinned.
- **B24:** population density per MHA (Σ population ÷ Σ land area over its ZCTAs) as the urbanicity measure.
- **B19 (spatial regression):** adequacy gap (E-5, rent) on three predictors:
  - log rent level (B8)
  - rent growth (annualised ZORI change over a pinned window from the A3 history)
  - log population density (B24)

  Method: ordinary least squares first, then the Lagrange-multiplier diagnostics to choose a spatial lag or spatial error model (PySAL `spreg`), on the same CONUS scope and KNN weights as B17.
- **Built (code, 18 Oct):**
  - `benchmarks/density_to_mha.py` (B24, `make density`): Σ population ÷ Σ ALAND20 over each MHA's ZCTAs (the plan's measure, B19 primary), and the population-weighted density (B19 sensitivity). ALAND20 is read from the A2 attribute table, so the generalized polygons play no part. 3 tests.
  - `spatial/regression.py` (B19, `make regression`): growth from the A3 history over the 5 years before the B8 window, matched calendar months, median of ZIP growth per MHA; OLS with residual Moran's I, the five LM tests, VIF and condition number; the Anselin (2005) rule chooses OLS, ML_Lag or ML_Error; residual Moran's I retested on the chosen model; sensitivity runs for population-weighted density and the O-3 profile. Stops if B8 came from another A3 file. 7 tests, including recovery of planted coefficients and of ρ = 0.6 on a lattice.
  - **Caveat recorded in the manifest:** the dependent variable divides by the utilities-inclusive ZORI and `ln_rent` is the log of ZORI, so part of a negative rent-level coefficient is mechanical. W1 should say so.
- **First run on the 2026 data (18 Oct) and the changes it led to:**
  - **Sample.** n = 201 of the 283 CONUS MHAs with a rent value. The 82 left out have no ZIP with ZORI in both the 2021 and 2026 windows. They differ from the modelled MHAs: median adequacy gap 0.054 against 0.156, median ln density 3.83 against 5.20. The 5-year result therefore describes the denser, better-covered MHAs. B19 now reports this comparison with Mann-Whitney U tests (`sample_selection`), warns when the groups differ, and reruns the primary profile with 3-year growth (2023 → 2026, `SENS_GROWTH_YEARS ?= 3`), which keeps more MHAs. The 5-year window stays primary (D15).
  - **Model form.** Both LM tests were significant (p ≈ 0) and neither robust test was, so the rule could not choose between lag and error; the three runs split (error, lag, lag). B19 now marks such a choice `ambiguous`, fits both models, reports AIC for both, and states for each predictor whether the two agree. B23 shows both as NOTE rows.
- **Why reduced:** BEA Regional Price Parities (A10, B25) exist only for states and metro areas, which is coarser than MHAs. Their rent component is built from ACS rents, so it would largely repeat the rent-level variable. Both are scrapped. The research proposal records this.

### B22 · build manifest — target Thu 29 Oct

- Gathers every stage manifest into one file: input checksums, windows, row counts, warnings, software versions, git commit. It builds on `tools/verify_hashes.py` (`make verify`), which already proves the recorded hashes agree.
- Its own SHA-256 is the `build_id` in B20, B21 and B27.
- **Build order (found while writing the ICD):** B22 cannot list the hashes of files that embed its own hash. So B22 is written first, from the stage manifests and B7; B20, B21 and B27 follow; a `SHA256SUMS` file over all five is written last ([ICD section 8](../data-contract.md#8-b22--build-manifest-build_manifest_2026json)). `nodes.csv` now shows B22 feeding B20, B21 and B27 instead of the reverse.
- **Check:** the build stops if any stage manifest is missing, or was built from inputs (configs included) other than the ones beside it.
- **`make handoff`:** builds B22, B20, B21, B27 and `SHA256SUMS` from the existing stage outputs and validates them. **`make layer2`** (18 Oct) is the end-to-end run ICD check 1 names: `all`, `regression`, `handoff`, `evidence`, `verify`, `qa`, `evidence`, `verify`.

### B23 · QA / validation report — target Thu 29 Oct

**Built (code, 18 Oct):** `pipeline/qa/qa_report.py` (`make qa`). The report is written to `data/processed/qa/qa_2026.md`, git-ignored, not `docs/qa/`: it is processed output, so it enters the repository with the D10 delivery (D17). It adds a verdict table, ICD checks 2, 4 and 9 (sizes, counts by status, classes changed by rounding), and a provenance check (the build came from committed code). The three traces are chosen automatically (one surplus and one short of design, each nearest the median of its side, inside cluster scope; one fallback) unless `make qa TRACE="..."` names them; each ratio is recomputed from its inputs. The hand-check against the raw files is recorded in the progress note, because the report itself is never edited. 4 tests.

Planned content (all covered):

1. Join coverage at each step: ZIPs → ZCTAs → MHAs (5,609 of 20,280 MHA ZIPs have no ZCTA polygon, from the B6 manifest); ZIPs with no ZORI, ZHVI or SAFMR.
2. Every warning carried in the stage manifests.
3. A hand-checked trace of three MHAs from raw source to B20: one in surplus, one short, one with a fallback.
4. ZORI against SAFMR agreement.
5. A8 locality and state-fallback counts, and the insurance year (N2).
6. Statistical caveats: the FDR result and the permutation check, k sensitivity, CONUS scope.

C21 (the about / data-caveats page) is built from this report.

### W2 · data contract (ICD) — written Sun 18 Oct

- **What:** [`docs/data-contract.md`](../data-contract.md), the Layer 2 → Layer 3 Interface Control Document. It widens the September "data contract" from the attribute payload to every delivered file: B7, B20, B21, B22, B27 and `SHA256SUMS`.
- **Contents:** parties; delivered files; common conventions (D6); one section per file with every field, type, status code and caveat id; consumer obligations; versioning; conformance checks; delivery (D10); change log.
- **Done when:** the author has reviewed it. Its conformance checks (section 11) are then the exit criteria M6 closes on; B20–B23 implement them.

### W1 · Layer 2 writeup — target Fri 30 Oct (author-written)

Wendell writes this; the outline points to the evidence each part draws on. **Scaffold (18 Oct):** [`docs/layer2-writeup.md`](../layer2-writeup.md) holds the headings, evidence links and a prompt per section, and adds section 7, the record of actions and decisions D10 asks for. Section 4 now covers H2 (B19, D15). `make deliver` refuses while any section still carries its prompt marker.

1. **Purpose** — how Layer 1 becomes Layer 3, and why the pipeline is offline and reproducible.
2. **From sources to areas** — the crosswalk, the synthesized geometry (B6, B28), and the median rule. Evidence: B1–B11 manifests.
3. **The adequacy test** — the statute, the cost share, and why `adequacy_gap` replaced the flat 95% target (D1). Evidence: coverage manifest.
4. **Spatial statistics** — the weights choice, the global result for H1 (confirmatory), and the local clusters (exploratory, D2). Evidence: spatial manifest, LISA map.
5. **The handoff** — the B7/B20/B21/B22/B27 files and what the map may and may not do with them. Evidence: the [ICD](../data-contract.md), sections 2 and 9.
6. **Limitations** — every caveat from B23, including N1 and N2.

## 4. Sequence

| Target | Work |
|---|---|
| Sun 18 Oct | W2 data contract (ICD) written |
| ~~Wed 21 Oct~~ Sun 18 Oct | B28 polygons; B7 rebuilt as one `areas` layer (D9) — done 3 days early |
| ~~Sat 24 Oct~~ Sun 18 Oct | A8 and A9 pulls; `ownership.json` split as A12/A13 were; rerun B11 → B18 with 99,999 permutations — done 6 days early |
| Sun 18 Oct | B20, B21, B22, B27 code; first `make handoff` on the 2026 data, validated against ICD 1.0.2 |
| Sun 18 Oct | B24, B19 (D15), B23 code; `make layer2`, `make deliver` and its gates (D16, D17); ICD 1.0.3 (wording) |
| Sun 18 Oct | First `make layer2` on the 2026 data: handoff validated, B23 PASS. B19 sample and model-form findings; patch for both. Stale B23 output fixed in `make handoff` |
| Workstation, next | `make layer2` again with the B19 changes; review the B23 report and hand-check its three traces; `make done N="B19 B20-B22 B23 B24 B27"` |
| Fri 30 Oct | W1; `make deliver`; `make done N=W1`; one commit with `delivery/2026/`, W1 and the tracker; close M6 |

---

*AI-assistance disclosure: Claude (Anthropic) drafted this plan from the repository record and the author's 18 Oct decisions. The decisions are the author's.*
