# M6 plan — Layer 2 to Layer 3 handoff

**Milestone:** M6 2.7 Front-End Payload + 2.8 Writeup · **due Fri 30 Oct 2026** (dates below move with any schedule change) · **written:** 18 Oct 2026 · tracker: [WBS](../WBS.md) · progress for the period: [24 Oct note](../progress/2026-10-24.md)

M6 is the handoff from the offline pipeline to the map. When it closes, Layer 3 can be built against a fixed set of files:

- **B20** attribute payload
- **B21** UI metadata
- **B22** build manifest
- **B27** hotspot overlay
- **B7** and **B28** polygon tiles

This page records the decisions taken on 18 Oct and how each node will be built and checked.

**In progress (18 Oct):** A8, B20, B21, B22, B23, B28, W1 (required); A9, B24, B19, B27 (optional).
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

**Config text (COA 2, decided 18 Oct):** A12 and A13 now hold values only, and their explanations live in [`docs/configuration.md`](../configuration.md). The D2 cluster fields and the D3 sensitivity layers are in A13. The whole pipeline is rerun once so every recorded hash matches (`make verify`). `config/ownership.json` follows the same split when A8 rewrites it.

## 2. Draft data contract (B20)

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

### B28 · CCG and territory polygons — target Wed 21 Oct

- **Why:** DoD publishes no polygons for County Cost Groups. The DTMO crosswalk does assign ZIPs to them: in 2026, 20,465 ZIPs map to the 39 ZZ codes and 214 ZIPs to the single XX code.
- **Method:** the same ZIP → ZCTA → dissolve that builds B6 (A2 + B1), applied to the `ccg` and `unknown` classes.
  - Extend `build_mha_geometry.py` with `--classes ccg,unknown` and write `non_mha_YYYY.gpkg` / `.geojson`.
  - B6 itself is untouched, so B16–B18 do not change.
- **Annotation:** every feature carries `class` and `geometry_source: "ZCTA dissolve of DTMO ZIP assignments (non-authoritative)"`. The same statement appears in SOURCES.md, the data dictionary, B21 (shown in the UI) and W1.
- **Checks:**
  - every ZZ and XX code with ZIPs gets a feature
  - no ZCTA is assigned to both an MHA and a CCG
  - unmatched ZIPs are reported, as B6 does
  - confirm which territory the XX bucket covers (expected: Puerto Rico)
- **Tiles:** a second layer `non_mha` beside B7's `mha` layer, or a second PMTiles file. Settled when C1 is planned; the GeoJSON is the M6 deliverable.

### A8 · property tax and insurance by locality — target Sat 24 Oct (required, tracked under M6)

- **Property tax:** ACS 5-year detailed tables at ZCTA level through the Census API, with the year pinned.
  - Variables: B25090_001E (aggregate real estate taxes paid) and B25079_001E (aggregate value of owner-occupied units).
  - MHA effective rate = Σ taxes ÷ Σ value over the MHA's ZCTAs. Summing aggregates weights each ZCTA by its housing stock and avoids a ratio of medians.
  - An MHA whose ZCTAs have no data falls back to its state rate, and is flagged.
- **Insurance (N2):** Treasury FIO average homeowners premium by ZIP, 2018–2022, as published.
  - The file covers only ZIPs with at least ten insurers and fifty policies.
  - Value per MHA = the median of its ZIPs, as B8–B10 do. MHAs with no published ZIP use the NAIC state average.
  - The year used and the understatement of 2026 premiums are recorded in the manifest and in SOURCES.
- **Pipeline:**
  - Change A8 in `fetch_sources.py` from `manual` to `api` (ACS) plus `direct` (FIO workbook).
  - Add `benchmarks/tax_insurance_to_mha.py`, which writes `mha_tax_insurance.csv` with a source flag per MHA (`locality` or `state_fallback`).
  - Point `config/ownership.json` at it. The ACS client is shared with A9.
- **Rerun chain:** B11 → B14/B15 → B17/B18 buy-mode tests. Rent results do not change. The M5 buy-mode Moran's I values (E-5 0.397, O-3 0.482) are replaced, and the progress note reports old against new.
- **Done when:** B11 has no placeholder warnings, every MHA has a sourced rate with its source flag, and the change in buy-mode results is recorded.

### B20 · attribute payload — target Wed 28 Oct

- **Content:** the contract in section 2.
- **Areas:** the 299 MHAs, the 39 CCGs (BAH rate only, N1) and the XX bucket (status `no_rate`). Alaska and Hawaii are included with `cluster_scope: false`.
- **Values:** taken only from the B12–B15 output and B4; B20 computes nothing new.
- **Checks:**
  - every code in B6 ∪ B28 has an entry, and vice versa
  - every non-null value matches its source row
  - every status and caveat id resolves in B21
  - the file size is reported (expected under 300 KB)
- **Docs:** a new data-dictionary section, and the contract published as `docs/data-contract.md`.

### B21 · UI metadata — target Wed 28 Oct

- **Profiles and metrics:** profile labels (A12), and metric definitions with A13 classes, colours and labels for all seven map layers. The three D3 sensitivity layers reuse existing class schemes, so no new breaks need to be designed:
  - `flat95_gap` uses the `coverage_ratio` breaks shifted by −0.95, which draws the same map as `coverage_ratio`, labelled as the fixed-95% reading
  - `safmr_adequacy_ratio` uses the `adequacy_ratio` breaks
  - `safmr_design_gap_usd` uses the `design_gap_usd` breaks
- **Names and caveats:** area names and classes (B3, B1, B28), and the caveat texts by id:
  - `utilities_grossed_up`
  - `tax_insurance_locality`
  - `insurance_2022_dollars`
  - `ccg_geometry`
  - `ccg_no_benchmark`
  - `piti_only_no_zori`
  - `outside_cluster_scope`
  - `lisa_exploratory`
- **Also:** benchmark windows and the source attributions that C20 will display.

### B27 · hotspot overlay payload — target Wed 28 Oct (optional)

- **Content:** keyed like B20, one entry per in-scope MHA, profile and mode:
  - `lisa_class` (HH, LL, HL, LH or NS at p < 0.05)
  - `lisa_p`
  - `fdr_significant`
  - `gi_class`
- **Labelling (D2):** the file and its legend label the p < 0.05 classes as exploratory and mark the FDR survivors.
- **Before building:** rerun B18 once with `make spatial PERMUTATIONS=99999`.
  - With 9,999 permutations, the smallest local p-value possible is 0.0002. The FDR cutoff for the top-ranked MHA is 0.05 ÷ 283 ≈ 0.00018, below that floor.
  - So the current count of two FDR survivors may be limited by permutation resolution rather than the data. The rerun settles which MHAs are marked; the result is recorded either way.

### H2 chain (D8, reduced) — A9 and B24 by Sat 24 Oct with A8; B19 after M6, before 16 Nov (optional)

H2 asks what the adequacy gaps are associated with. The research question itself is answered by B12–B18. H2 supplies the explanation the instructor's original redirect asked for.

- **A9 (ACS):** population and land area per ZCTA through the same Census API client as A8, with the year pinned.
- **B24:** population density per MHA (Σ population ÷ Σ land area over its ZCTAs) as the urbanicity measure.
- **B19 (spatial regression):** adequacy gap (E-5, rent) on three predictors:
  - log rent level (B8)
  - rent growth (annualised ZORI change over a pinned window from the A3 history)
  - log population density (B24)

  Method: ordinary least squares first, then the Lagrange-multiplier diagnostics to choose a spatial lag or spatial error model (PySAL `spreg`), on the same CONUS scope and KNN weights as B17.
- **Why reduced:** BEA Regional Price Parities (A10, B25) exist only for states and metro areas, which is coarser than MHAs. Their rent component is built from ACS rents, so it would largely repeat the rent-level variable. Both are scrapped. The research proposal records this.

### B22 · build manifest — target Thu 29 Oct

- Gathers every stage manifest into one file: input checksums, windows, row counts, warnings, software versions, git commit.
- Its own SHA-256 is the `build_id` in B20, B21 and B27.
- **Check:** the build stops if any stage manifest is missing, or was built from inputs (configs included) other than the ones beside it.

### B23 · QA / validation report — target Thu 29 Oct

A generated `docs/qa/qa-2026.md` covering:

1. Join coverage at each step: ZIPs → ZCTAs → MHAs; ZIPs with no ZORI, ZHVI or SAFMR.
2. Every warning carried in the stage manifests.
3. A hand-checked trace of three MHAs from raw source to B20: one in surplus, one short, one with a fallback.
4. ZORI against SAFMR agreement.
5. A8 locality and state-fallback counts, and the insurance year (N2).
6. Statistical caveats: the FDR result and the permutation check, k sensitivity, CONUS scope.

C21 (the about / data-caveats page) is built from this report.

### W1 · Layer 2 writeup — target Fri 30 Oct (author-written)

Wendell writes this; the outline points to the evidence each part draws on.

1. **Purpose** — how Layer 1 becomes Layer 3, and why the pipeline is offline and reproducible.
2. **From sources to areas** — the crosswalk, the synthesized geometry (B6, B28), and the median rule. Evidence: B1–B11 manifests.
3. **The adequacy test** — the statute, the cost share, and why `adequacy_gap` replaced the flat 95% target (D1). Evidence: coverage manifest.
4. **Spatial statistics** — the weights choice, the global result for H1 (confirmatory), and the local clusters (exploratory, D2). Evidence: spatial manifest, LISA map.
5. **The handoff** — the B20/B21/B22/B27 files and what the map may and may not do with them.
6. **Limitations** — every caveat from B23, including N1 and N2.

## 4. Sequence

| Target | Work |
|---|---|
| Wed 21 Oct | B28 polygons |
| Sat 24 Oct | A8 and A9 pulls; B24; `ownership.json` split as A12/A13 were; rerun B11 → B18 with 99,999 permutations |
| Wed 28 Oct | B20, B21, B27 |
| Thu 29 Oct | B22, B23 |
| Fri 30 Oct | W1; close M6 |
| By 16 Nov | B19 (H2) |

---

*AI-assistance disclosure: Claude (Anthropic) drafted this plan from the repository record and the author's 18 Oct decisions. The decisions are the author's.*
