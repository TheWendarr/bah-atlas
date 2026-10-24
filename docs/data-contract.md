# Data contract — Layer 2 → Layer 3 Interface Control Document

**ICD version:** 1.1.0 · **contract `schema_version`:** 1.1.0 · **BAH year:** 2026 · **written:** 18 Oct 2026 · **revised:** 24 Oct 2026 (1.1.0, the grid) · **tracked as:** W2 (M6) · plan: [M6 plan](plans/m6-plan.md) · tracker: [WBS](WBS.md)

This document fixes everything that crosses the boundary between the offline pipeline (Layer 2, B nodes) and the static map (Layer 3, C nodes): which files are handed over, the exact shape of each, the rules for missing values, and what the map may and may not do with them. Layer 3 is built against this document, not against the pipeline code.

It is the "data contract" named in the nodal architecture (September 2026), widened from the attribute payload alone to every delivered file. The [data dictionary](data-dictionary.md) describes the pipeline's internal tables; where the two differ about a delivered file, this document governs.

**Status:** the interface is fixed. The files themselves are produced in M6 (targets in the [M6 plan](plans/m6-plan.md#4-sequence)), and their values change when A8 lands. The interface does not.

---

## 1. Parties

| Side | Owner | Nodes | Responsibility |
|---|---|---|---|
| Producer | Layer 2 pipeline (`make`, Python) | B7, B20, B21, B22, B27, B31 (B28 feeds B7) | Emit files that pass every check in section 11 |
| Consumer | Layer 3 static map (MapLibre GL JS) | C1–C3 serve the files; C5–C25 read them | Use the files as specified in section 9; compute nothing but the grid formula of section 5b.4 |
| Authority | Author (Wendell McGowan III) | W2 | Approves every change to this document (section 10) |

## 2. Delivered files

| Node | File | Format | Read by | Holds |
|---|---|---|---|---|
| **B7** | `areas_2026.pmtiles` | PMTiles v3, one vector layer | C1 → C5, C8, C9 | Polygons for every area, with the join key. No values. |
| **B20** | `payload_2026.json` | JSON | C2 → C8, C11, C12 | Measured values per area × profile × mode (the attribute payload) |
| **B21** | `ui_metadata_2026.json` | JSON | C3 → C7, C9, C10, C20, C21 | Labels, class breaks, colours, area names, status and caveat texts, sources |
| **B27** | `hotspots_2026.json` | JSON | C16 (optional) | Local cluster results, exploratory |
| **B31** | `grid_2026.json` | JSON | C2 → C6, C8, C14, C25 | The rank × dependents × home type grid: BAH for every rank, benchmarks for every home type, cost shares and DoD standards (section 5b) |
| **B22** | `build_manifest_2026.json` | JSON | C20, C21 (provenance) | Inputs, checksums, windows, software and the commit the build came from |
| — | `SHA256SUMS` | text, `sha256sum` format | delivery check | SHA-256 of the six files above |

B28 (County Cost Group and territory polygons) is not delivered on its own. Under decision D9 it is merged into B7 at tile time, so the map reads one set of polygons.

The year in each file name is `bah_year`. A later BAH year produces a new set of files under the same contract.

## 3. Common conventions

These follow decision D6 (18 Oct 2026).

| Topic | Rule |
|---|---|
| Encoding | UTF-8 JSON, no comments, no trailing commas. |
| Version | Every JSON file carries `schema_version` (semantic versioning) and `bah_year`. |
| Build link | B20, B21, B27 and B31 carry `build_id`, the SHA-256 of the B22 file. All four must carry the same value (section 8). |
| Area code | `^[A-Z]{2}[0-9]{3}$`, exactly as DTMO publishes it (`CO018`, `ZZ001`; the territory bucket follows the same `XX###` form). It is the only join key across files. |
| Ordering | Area entries are sorted by code; profiles follow A12 order; modes are `rent`, `buy`. |
| Ratios | Plain decimals (1.0463 means 104.63%), rounded to 4 decimal places. Never pre-multiplied to percent. p-values (B27) are rounded to 5 decimal places, the resolution of 99,999 permutations. |
| Dollars | US dollars per month, rounded to whole dollars, half away from zero. **Exception:** the B31 benchmark costs (`cost`, `own_housing`) carry cents, because the browser computes ratios from them (section 5b.3). |
| Missing values | The field is present and `null`, and the row's `status` says why (section 5.3). A field is never omitted to mean "missing". |
| Caveats | Arrays of caveat ids. The text for each id lives in B21 (section 6.4). |
| Enumerations | Every status, class and caveat id is a closed list in this document. A value outside its list is a contract failure. |
| Unknown fields | Consumers ignore fields they do not know. This is what lets a minor version add fields safely. |

## 4. B7 — area polygons (`areas_2026.pmtiles`)

Decision D9 (18 Oct 2026): one vector layer for every area, keyed on `code`.

| Property | Value |
|---|---|
| Vector layer | `areas` |
| Features | One per area code with at least one ZCTA polygon: 299 MHAs, 39 County Cost Groups, and the territory bucket if any of its ZIPs match a ZCTA. 2026: 339 (299 MHA, 39 CCG, 1 territory). Every CCG and the territory bucket is a multipolygon. |
| Feature properties | `code` (string, the join key) and `class` (`mha`, `ccg` or `unknown`). Nothing else: no values are baked into the tiles. |
| Feature id | MapLibre promotes `code`: `promoteId: "code"`. |
| Zoom | 2–10; MapLibre overzooms beyond 10. |
| Geometry | Census 2020 ZCTA polygons dissolved through the DTMO ZIP-to-area crosswalk. All areas are tiled in **one** tippecanoe run with shared-border detection, so neighbouring areas of any class meet without gaps or overlaps. |
| Territory bucket | One `XX###` code whose ZIPs lie in Puerto Rico (ZIP3 006, 007, 009), the U.S. Virgin Islands (008), the Pacific 969 range (Guam, the Northern Mariana Islands and the freely associated states) and one 967 ZIP, which in this bucket is expected to be 96799 (American Samoa). Its polygon therefore has parts in the Caribbean and the western Pacific, so a map fitted to all features spans the Pacific; the default view should be fitted to the `mha` class. These areas are outside CONUS and have no BAH rate (status `no_rate`). |
| Authority | No DoD polygon layer exists for any class. MHA polygons are a reconstruction; CCG and territory polygons are additionally labelled non-authoritative (caveat `ccg_geometry`). |
| Attribution | Carried in the archive metadata and repeated in B21 `sources`. |

Source declaration the map uses (C5):

```js
map.addSource("areas", {
  type: "vector",
  url: "pmtiles://areas_2026.pmtiles",
  promoteId: "code"
});
// every value join: map.setFeatureState({ source: "areas", sourceLayer: "areas", id: code }, {...})
```

Every `code` in B7 has an entry in B20, and every B20 entry with a polygon appears in B7 (section 11).

## 5. B20 — attribute payload (`payload_2026.json`)

B20 packs values already computed by B4 and B12–B15. It computes nothing new.

### 5.1 Top level

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string | `"1.1.0"` |
| `bah_year` | integer | `2026` |
| `build_id` | string | SHA-256 (64 hex characters) of the B22 file |
| `profiles` | array of string | A12 profile ids in A12 order: `["e5_dep", "o3_dep"]` |
| `modes` | array of string | `["rent", "buy"]` |
| `areas` | object | One entry per area code (section 5.2) |

### 5.2 Area entry: `areas.<code>`

| Field | Type | Meaning |
|---|---|---|
| `class` | string | `mha` · `ccg` (County Cost Group, `ZZ###`) · `unknown` (territory bucket, `XX###`) |
| `cluster_scope` | boolean | `true` only for CONUS MHAs. `false` for Alaska, Hawaii, CCGs and the territory bucket (decision 2.2). Areas with `false` have no B27 entry. |
| `caveats` | array of string | Area-level caveat ids (section 5.5) |
| `<profile id>` | object | One per profile, each holding `rent` and `buy` blocks (section 5.3) |

### 5.3 Value block: `areas.<code>.<profile>.<mode>`

| Field | Type | Rent | Buy | Source | Meaning |
|---|---|---|---|---|---|
| `status` | string | ✓ | ✓ | B12/B14 | Why any value is null (section 5.4) |
| `bah_monthly` | integer \| null | ✓ | ✓ | B4 | BAH for the profile's pay grade and dependency status |
| `cost_share_monthly` | integer \| null | ✓ | ✓ | A12 | DTMO member cost share (the statutory deduction) |
| `cost_monthly` | integer \| null | ✓ | ✓ | B29 / B30 | Local cost of the profile's DoD housing standard (A14, D19): utilities-inclusive rent (rent); PITI plus utilities (buy), or PITI alone under `piti_only_no_zori`. For E-5 the standard is the 2 BR townhouse, which equals B8 / B11 |
| `adequacy_ratio` | number \| null | ✓ | ✓ | B12/B14 | (BAH + cost share) ÷ cost. Primary map layer; target 1.00 |
| `design_gap_usd` | integer \| null | ✓ | ✓ | B13/B15 | BAH + cost share − cost. Primary map layer |
| `coverage_ratio` | number \| null | ✓ | ✓ | B12/B14 | BAH ÷ cost. Descriptive map layer |
| `design_coverage` | number \| null | ✓ | ✓ | B12/B14 | 1 − cost share ÷ cost: the share BAH is designed to pay at this cost level |
| `surplus_usd` | integer \| null | ✓ | ✓ | B13/B15 | BAH − cost. Descriptive map layer |
| `flat95_gap` | number \| null | ✓ | ✓ | B12/B14 | coverage_ratio − 0.95. Sensitivity map layer (D3) |
| `safmr_monthly` | integer \| null | ✓ | — | B10 | HUD SAFMR at the profile's anchor bedrooms |
| `safmr_adequacy_ratio` | number \| null | ✓ | — | B12 | Adequacy against SAFMR. Sensitivity map layer (D3) |
| `safmr_design_gap_usd` | integer \| null | ✓ | — | B13 | Design gap against SAFMR. Sensitivity map layer (D3) |
| `own_housing_monthly` | integer \| null | — | ✓ | B11 | PITI alone (principal, interest, tax, insurance, mortgage insurance) |
| `caveats` | array of string | ✓ | ✓ | — | Row-level caveat ids (section 5.5) |

`adequacy_gap` (adequacy_ratio − 1) is not carried: it is the same quantity as `adequacy_ratio`, and the map shows the ratio. B27 carries the cluster results computed on it.

Field names are the pipeline's own column names, so any value can be traced to its source row without a lookup table.

### 5.4 Status codes

| Mode | `status` | When | Non-null fields |
|---|---|---|---|
| both | `ok` | Benchmark present | All fields for the mode |
| rent | `no_zori` | MHA has no ZORI ZIP data (2026: 10 MHAs, 4 of them in Alaska or Hawaii) | `bah_monthly`, `cost_share_monthly`, `safmr_*` |
| buy | `piti_only_no_zori` | Home value present but no ZORI, so no utilities estimate (decision 2.4; 2026: the same 10 MHAs) | All buy fields; `cost_monthly` = `own_housing_monthly` |
| buy | `no_home_value` | MHA has no ZHVI data (2026: none) | `bah_monthly`, `cost_share_monthly` |
| both | `ccg_no_benchmark` | Area is a County Cost Group (decision N1) | `bah_monthly`, `cost_share_monthly` |
| both | `no_rate` | Area has no BAH rate (the territory bucket) | none |

Every status code has a label and explanatory text in B21 `statuses`. B31 uses the same codes for each home type (section 5b.2).

### 5.5 Caveat ids

| Id | Level | Attached to |
|---|---|---|
| `ccg_geometry` | area | Every `ccg` and `unknown` area: polygon synthesized from ZCTAs, non-authoritative |
| `outside_cluster_scope` | area | Every area with `cluster_scope: false` |
| `ccg_no_benchmark` | row | Every `ccg` row: BAH rate only, no rent/utilities split or benchmark |
| `utilities_grossed_up` | row | Rent rows with a ZORI value: ZORI excludes utilities and is grossed up with the DoD rent/utilities split (B5) |
| `piti_only_no_zori` | row | Buy rows with that status: cost excludes utilities |
| `tax_insurance_locality` | row | Buy rows whose tax and insurance both come from locality sources (A8) |
| `tax_state_fallback` | row | Buy rows whose property-tax rate fell back to the state rate (A8) |
| `insurance_state_fallback` | row | Buy rows whose insurance fell back to the state median of the FIO premiums published for real-MHA ZIPs (A8, decision D11) |
| `insurance_2022_dollars` | row | Every buy row with a value: insurance is used as published, 2018–2022, not scaled to 2026 (decision N2) |
| `type_factor_national` | row | B31 home types (and so any grid view using them) whose building-type or bedroom adjustment fell back to the national ratio (B29, B30) |
| `lisa_exploratory` | overlay | The B27 file as a whole: local clusters at pseudo p < 0.05, not corrected for multiple testing (decision D2) |

Caveats that apply to the whole map, such as the ZIP-to-ZCTA join dropout, are in B21 `global_caveats` rather than on any area.

### 5.6 Example

Illustrative numbers.

```json
{
  "schema_version": "1.1.0",
  "bah_year": 2026,
  "build_id": "9c1e…(64 hex)",
  "profiles": ["e5_dep", "o3_dep"],
  "modes": ["rent", "buy"],
  "areas": {
    "CO018": {
      "class": "mha",
      "cluster_scope": true,
      "caveats": [],
      "e5_dep": {
        "rent": {
          "status": "ok",
          "bah_monthly": 2112, "cost_share_monthly": 126, "cost_monthly": 2139,
          "adequacy_ratio": 1.0463, "design_gap_usd": 99,
          "coverage_ratio": 0.9874, "design_coverage": 0.9411, "surplus_usd": -27,
          "flat95_gap": 0.0374,
          "safmr_monthly": 2190, "safmr_adequacy_ratio": 1.0219, "safmr_design_gap_usd": 48,
          "caveats": ["utilities_grossed_up"]
        },
        "buy": {
          "status": "ok",
          "bah_monthly": 2112, "cost_share_monthly": 126, "cost_monthly": 2905,
          "adequacy_ratio": 0.7704, "design_gap_usd": -667,
          "coverage_ratio": 0.7270, "design_coverage": 0.9566, "surplus_usd": -793,
          "flat95_gap": -0.2230, "own_housing_monthly": 2620,
          "caveats": ["tax_insurance_locality", "insurance_2022_dollars"]
        }
      },
      "o3_dep": { "rent": { "status": "ok", "…": "same fields" }, "buy": { "…": "…" } }
    },
    "ZZ001": {
      "class": "ccg",
      "cluster_scope": false,
      "caveats": ["ccg_geometry", "outside_cluster_scope"],
      "e5_dep": {
        "rent": {
          "status": "ccg_no_benchmark",
          "bah_monthly": 1650, "cost_share_monthly": 126, "cost_monthly": null,
          "adequacy_ratio": null, "design_gap_usd": null, "coverage_ratio": null,
          "design_coverage": null, "surplus_usd": null, "flat95_gap": null,
          "safmr_monthly": null, "safmr_adequacy_ratio": null, "safmr_design_gap_usd": null,
          "caveats": ["ccg_no_benchmark"]
        },
        "buy": { "status": "ccg_no_benchmark", "…": "same pattern" }
      },
      "o3_dep": { "…": "…" }
    }
  }
}
```

## 5b. B31 — rank × dependents × home type grid (`grid_2026.json`)

Decisions D18–D20 (18 Oct 2026). The map lets the user pick any rank (E-1–E-9, W-1–W-5, O-1–O-9), with or without dependents, in any of DoD's six home types or *DoD standard for this rank* (the default). That is 23 × 2 × 7 = 322 views per mode. Precomputing them would be about 60 MB, so B31 carries the factors and the browser computes each view with the formula in 5b.4. B31 computes nothing itself: every number comes from B4, A14, B29 or B30.

### 5b.1 Top level

| Field | Type | Meaning |
|---|---|---|
| `schema_version`, `bah_year`, `build_id` | | As in B20 |
| `ranks` | array of string | The 23 grades in dropdown order: `["E1", …, "E9", "W1", …, "W5", "O1", …, "O9"]`. Every per-rank array below follows this order. |
| `dependents` | array of string | `["with", "without"]` |
| `home_types` | array of string | `["apt1", "apt2", "th2", "th3", "sfh3", "sfh4"]`: 1 and 2 BR apartment, 2 and 3 BR townhouse, 3 and 4 BR single-family home. Every per-type array below follows this order. |
| `modes` | array of string | `["rent", "buy"]` |
| `cost_share_monthly` | object | By dependents, an array of 23 whole dollars: the DTMO 2026 member cost share for each rank (A14). O-8 and O-9 repeat O-7's. |
| `standards` | object | By dependents, an array of 23 `{ "lower", "upper", "share" }` objects: each rank's DoD housing standard (A14). `upper` is a home type or `null`; `share` is a plain decimal in [0, 1). |
| `areas` | object | One entry per area code, the same codes as B20 (5b.2) |

### 5b.2 Area entry: `areas.<code>`

| Field | Type | Meaning |
|---|---|---|
| `class` | string | As in B20 |
| `bah` | object | By dependents, an array of 23 whole dollars or `null` (B4). The territory bucket's are all `null`. |
| `rent` | object | `cost`, `status`, `caveats`: three arrays of 6, one entry per home type |
| `buy` | object | `cost`, `own_housing`, `status`, `caveats`: four arrays of 6 |

| Array | Entry | Meaning |
|---|---|---|
| `cost` | number (cents) \| null | Rent: utilities-inclusive rent for the home type (B29). Buy: PITI plus utilities (B30), or PITI alone under `piti_only_no_zori`. |
| `own_housing` | number (cents) \| null | Buy only: PITI alone (B30) |
| `status` | string | The section 5.4 codes for the mode: `ok`, `no_zori` (rent), `piti_only_no_zori`, `no_home_value` (buy), `ccg_no_benchmark`, `no_rate`. `cost` is non-null exactly under `ok` and `piti_only_no_zori`. |
| `caveats` | array of string | Row-level caveat ids for this home type (section 5.5), including `type_factor_national` |

County Cost Groups carry their BAH and `ccg_no_benchmark` for every home type; the territory bucket carries `no_rate`.

### 5b.3 Why the costs carry cents

The research profiles' B20 values are computed from B29 and B30 values held to the cent. Carrying the same cents lets the browser formula reproduce B20 exactly (B23 checks this), so an E-5 or O-3 view on the grid never differs from the research layer by a rounding step. The map still displays whole dollars.

### 5b.4 The browser formula

For a selection of area `a`, rank `r` (index `i` in `ranks`), dependents `d`, home type `h` and mode `m`:

1. `BAH = areas[a].bah[d][i]` and `A = cost_share_monthly[d][i]`. Under status `no_rate` (step 3) both are shown as `null`, as in B20.
2. The home types used: `[h]`, or for *DoD standard*, `std = standards[d][i]` gives `[std.lower]`, plus `std.upper` when it is not `null`.
3. `status` is the first status among those home types that is not `ok`, else `ok`. `caveats` is the union of their caveat ids.
4. The cost `C`:
   - a single home type: `C = cost[h]`
   - *DoD standard*, `upper` null: `C = cost[lower] × (1 + share)` (an anchor when `share` is 0; above the highest profile otherwise)
   - *DoD standard*, interpolated: `C = cost[lower] + share × (cost[upper] − cost[lower])`
   - `C` is `null` if any cost it needs is `null`
5. If `BAH` or `C` is `null`, every metric is `null` and the status text explains why. Otherwise:

   | Metric | Formula | Rounding |
   |---|---|---|
   | `adequacy_ratio` | (BAH + A) ÷ C | 4 decimals |
   | `design_gap_usd` | BAH + A − C | whole dollars |
   | `coverage_ratio` | BAH ÷ C | 4 decimals |
   | `surplus_usd` | BAH − C | whole dollars |

   Rounding is half away from zero, on the full-precision result, then classified with the B21 `metrics` breaks.
6. The view is the **statutory test** when `h` is *DoD standard*, or `h` is the rank's anchor type. Every other view measures how far BAH goes toward a home DoD does not prescribe for that rank, and the map says so (C25, B21 `grid.notice`).

`pipeline/handoff/contract.py` (`grid_view`) is the reference implementation; the map's code must give the same results.

### 5b.5 Worked examples

Illustrative numbers.

| | O-3 with dependents, *DoD standard*, rent | E-1 with dependents, 4 BR single-family, buy | O-7 with dependents, *DoD standard*, rent |
|---|---|---|---|
| Home types used | `th3`, `sfh3` (standard: 98% from `th3` to `sfh3`) | `sfh4` only (a single home type) | `sfh4` (standard: `upper` null, share 0.02) |
| Costs used | th3 2,605.40; sfh3 3,120.75 | sfh4 4,512.18 | sfh4 3,402.00 |
| C | 2,605.40 + 0.98 × 515.35 = 3,110.443 | 4,512.18 | 3,402.00 × 1.02 = 3,470.04 |
| BAH + A | 2,868 + 151 = 3,019 | 2,016 + 115 = 2,131 | 3,405 + 212 = 3,617 |
| `adequacy_ratio` | 0.9706 | 0.4723 | 1.0424 |
| `design_gap_usd` | −91 | −2,381 | 147 |
| Statutory test | yes | no: an affordability view | yes |

If either `th3` or `sfh3` had status `no_zori`, the O-3 view would be `null` with status `no_zori`.

### 5b.6 What stays on the research profiles

The B27 hotspot overlay, the B19 regression and the flat-95% and SAFMR sensitivity layers exist only for the two research profiles in B20 (D20). The map shows them only when the selection equals a research profile's statutory view (E-5 or O-3, with dependents, *DoD standard* or that rank's anchor type).

## 6. B21 — UI metadata (`ui_metadata_2026.json`)

Everything the map needs to label and colour B20, so no wording or class break is hard-coded in Layer 3.

| Field | Type | Content |
|---|---|---|
| `schema_version`, `bah_year`, `build_id` | | As in B20 |
| `profiles` | array | A12 profile objects: `id`, `label`, `role`, `pay_grade`, `has_dependents`, `anchor_dwelling`, `anchor_bedrooms`, `cost_share_monthly` |
| `default_profile` | string | From A12 (`e5_dep`) |
| `modes` | array | `{ "id": "rent", "label": … }`, `{ "id": "buy", "label": … }` |
| `metrics` | object | The seven A13 map layers by id, each with `label`, `short_label`, `role` (`primary`, `descriptive`, `sensitivity`), `modes`, `format` (`percent` or `usd`), `neutral`, `breaks`, `colors`, `class_labels` |
| `default_metric` | string | From A13 (`adequacy_ratio`) |
| `no_data_color` | string | From A13; used for every null value |
| `clusters` | object | A13 `clusters` block: legend title, classes HH/LL/HL/LH/NS with labels and colours, FDR marker style |
| `areas` | object | By code: `name` (DTMO registry, B3) and `class` |
| `statuses` | object | By status code: `label` and `text` |
| `caveats` | object | By caveat id: `title`, `text`, `level` (`area`, `row`, `overlay`) |
| `global_caveats` | array | `{ "id", "title", "text" }` for limitations that apply to the whole map |
| `windows` | object | Display strings for each period: `bah_rates`, `rent_zillow_zori`, `home_value_zillow_zhvi`, `mortgage_rate_pmms`, `rent_crosscheck_hud_safmr`, `property_tax_acs`, `insurance_fio` |
| `sources` | array | `{ "id", "title", "provider", "url", "license", "used_for" }` for every incorporated source in [SOURCES.md](SOURCES.md) |
| `geometry` | object | `method` and `authority` statements for the polygons, as shown in the UI |
| `grid` | object | The dropdowns and notices for B31 (section 6.1) |

### 6.1 `grid`

| Field | Content |
|---|---|
| `ranks` | `{ "id": "E5", "label": "E-5" }` for the 23 ranks, in B31 order |
| `dependents` | `{ "id", "label" }` for `with` and `without` |
| `home_types` | `{ "id": "standard", "label" }` first, then the six types with `label`, `building` and `bedrooms` |
| `default_rank`, `default_dependents`, `default_home_type` | The primary research profile's cell (`E5`, `with`) and `standard` |
| `metrics` | The metric ids the grid supports: `adequacy_ratio`, `design_gap_usd`, `coverage_ratio`, `surplus_usd` |
| `standards_text` | By rank, then dependents: the DoD standard in words (C25), e.g. *98% of the way from a 3-bedroom townhouse to a 3-bedroom single-family home* |
| `notice` | `standard` and `off_standard` texts with `{standard}` and `{home_type}` placeholders the map fills from `standards_text` and the home-type label |
| `titles` | Dropdown titles |

**Class rule.** A value belongs to class `i`, where `i` is the number of breaks less than or equal to it. A value equal to a break falls in the class above. This is the rule the pipeline uses for the class counts in the coverage manifest (`bisect_right`).

**Rounding at breaks.** The pipeline counts classes on unrounded values; the map classifies the rounded values in B20. An area sitting within 0.00005 of a break can therefore land one class apart. B23 reports any such area.

## 7. B27 — hotspot overlay (`hotspots_2026.json`, optional)

Decision D2 (option C) and D5. Local results for the primary variable `adequacy_gap` only; the `flat95_gap` cluster results stay in the pipeline evidence.

| Field | Type | Content |
|---|---|---|
| `schema_version`, `bah_year`, `build_id` | | As in B20 |
| `variable` | string | `"adequacy_gap"` |
| `caveats` | array | `["lisa_exploratory"]` |
| `tests` | object | By profile, then mode: `n`, `k`, `permutations`, `alpha`, `moran_i` (4 decimals), `moran_p_sim` and `fdr_cutoff` (5 decimals) |
| `areas` | object | By code, then profile, then mode: the fields below. Only areas with `cluster_scope: true` appear. |

| Area field | Type | Meaning |
|---|---|---|
| `status` | string | `tested` or `no_value` (the B18 status) |
| `cluster` | string \| null | `HH`, `LL`, `HL`, `LH` where pseudo p < 0.05, else `NS`; null when not tested |
| `lisa_p_sim` | number \| null | Two-sided pseudo p-value, 5 decimal places |
| `lisa_fdr_significant` | boolean \| null | Survives the Benjamini–Hochberg correction across the test |
| `gi_class` | string \| null | `hot`, `cold` or `ns` |

The overlay is labelled exploratory wherever it is shown, and FDR-significant areas carry the A13 `fdr_marker` outline. The global Moran's I in `tests` is the confirmatory result for H1.

## 8. B22 — build manifest (`build_manifest_2026.json`)

| Field | Content |
|---|---|
| `schema_version`, `bah_year` | As above |
| `generated_at` | UTC timestamp |
| `node`, `build_order` | `"B22"`, and the build order below as text |
| `git` | `commit` the pipeline ran from, and `dirty: true` if the tree had uncommitted changes |
| `software` | Python and package versions; tippecanoe version |
| `raw_inputs` | Every Layer 1 file used, with SHA-256 (from the fetch record and A8/A9 pulls) |
| `configs` | A12, A13, A14, `ownership.json`, `ui_text.json` with SHA-256 |
| `stages` | One entry per stage manifest (fetch, B1–B18, B28, the A8 rollup, the A14 standards check, B29, B30, B7): nodes, file, SHA-256, generated time, warnings. The build stops if the A14 check did not pass. |
| `windows` | The benchmark periods B21 also shows |
| `spatial` | Permutations, seed and alpha of the B17/B18 run |
| `outputs` | B7 file name, SHA-256 and features by class |

**Build order.** B22 is written before B20, B21, B27 and B31, because they embed its hash as `build_id`. B22 therefore records B7 and the stage manifests, but not the four JSON files that point to it. Their hashes go into `SHA256SUMS`, written last.

```
stage manifests, B28 → B7 → B22 → B20, B21, B27, B31 → SHA256SUMS
```

The build stops if a stage manifest is missing or records inputs other than the files beside it (`make verify`).

## 9. Consumer obligations

The map **must**:

1. Join values to polygons only by `code`, through `setFeatureState` on the `areas` source and layer.
2. Classify and colour with B21 `metrics` breaks and colours, and draw every null value in `no_data_color`.
3. Show the B21 status text for any null value the user inspects, and the caveat texts for every caveat id on the area or row in view.
4. Label CCG and territory polygons as non-authoritative (`ccg_geometry`).
5. Label the B27 overlay as exploratory and mark FDR-significant areas.
6. Check that B20, B21, B27 and B31 carry the same `build_id`, and that `schema_version` has major version 1; otherwise refuse to render and show an error.
7. Show the B21 `sources` attribution (C20) and `global_caveats` (C21).
8. Compute grid views only with the section 5b.4 formula, and show the B21 `grid.notice` for every view: the statutory wording for a standard view, the affordability wording for any other (C25).
9. Show the B27 overlay, regression results and sensitivity layers only for a research profile's statutory view (section 5b.6).

The map **must not**:

1. Compute any metric, ratio or gap from other fields, except a grid view by the section 5b.4 formula. Formatting a ratio as a percentage is display, not computation.
2. Hard-code class breaks, colours, labels, status texts or caveat texts.
3. Show cluster results for areas with `cluster_scope: false`.
4. Present the flat-95% or SAFMR layers as the test result; they are sensitivity layers.

## 10. Versioning

| Change | Version step | Example |
|---|---|---|
| Values change, interface unchanged | none (new `build_id`) | A8 rerun, a new BAH release under the same contract |
| Field, status code, caveat id or metric added | minor (1.0.0 → 1.1.0) | B19 regression results added to B21 |
| Field, code or id renamed, removed, or its meaning or units changed | major (1.x → 2.0.0) | Ratios changed to percent |
| Wording of this document only | patch (1.0.0 → 1.0.1) | Clarified a sentence |

The ICD version and `schema_version` move together. Every change is entered in section 13 and approved by the author.

## 11. Conformance checks

These are the exit criteria for the handoff. B20–B23 implement them, and M6 does not close until all pass.

1. `make layer2` runs from `data/raw` to `SHA256SUMS` and the B23 report without error. (`make handoff` alone rebuilds only the delivered files from the existing stage outputs.)
2. `make verify` reports no failed checks.
3. Each JSON file validates against this document: required fields present, types correct, every enumeration value from its closed list, ratios at no more than 4 decimal places (p-values 5), dollars whole (B31 costs: cents).
4. The B7 codes and the B20 codes match exactly, except areas with no ZCTA polygon, which are listed in B23. B31 holds exactly the B20 codes.
5. Every non-null B20 value equals its source row (B4, B12–B15) after rounding; every B31 value equals B4, A14, B29 or B30.
6. Every status code and caveat id in B20, B27 and B31 has an entry in B21.
7. B20, B21, B27 and B31 share one `build_id`, and it equals the SHA-256 of the B22 file.
8. `SHA256SUMS` matches all six files.
9. B23 records the file sizes, the counts by status, and any area whose class differs between rounded and unrounded values.
10. B23 runs the section 5b.4 formula on B31 for both research profiles in every area and mode and finds B20's values; and recomputes two off-standard cells (E-1 with dependents in a 4 BR single-family home, O-9 with dependents in a 1 BR apartment) from B4, A14, B29 and B30.

## 12. Delivery

1. Layers 1 and 2 are completed in full first: every Layer 1 and Layer 2 node complete or scrapped, `make layer2` run end to end from `data/raw`, and the B23 report passing every check.
2. **Location (decided 18 Oct 2026, option B):** a frozen copy in `delivery/2026/` in the repository, holding the six delivered files, `SHA256SUMS`, and the B23 report with its manifest (`qa_2026.md`, `qa_2026_manifest.json`). Layer 3 reads only this folder. A pipeline rerun on the workstation changes `data/processed/handoff/` and nothing here; the delivery changes only by a deliberate re-delivery, entered in section 13.
3. `make deliver` is the only way files reach `delivery/`. It copies them only when all six gates pass (`make deliver-check` runs the gates alone):
   1. every Layer 1–2 node is complete or scrapped, apart from W1, which completes in the delivery commit
   2. the contract checks 3–8 pass
   3. `make verify` passes
   4. the B23 verdict is PASS, for this exact build and these six files, and the report is unedited
   5. the build came from committed code: the B22 commit is an ancestor of `HEAD`, and the pipeline code, configs, tools, Makefile and requirements are unchanged since
   6. the W1 write-up is written

   Each copy is then re-hashed against `SHA256SUMS` and the B23 manifest.
4. The delivered folder, the author's write-up of every action and decision behind it (W1, `docs/layer2-writeup.md`) and the tracker update are committed together. Layer 3 work begins after that commit. Until then, the files exist only on the author's workstation in `data/processed/handoff/` and `data/processed/qa/`, which git ignores.

## 13. Change log

| Version | Date | Change |
|---|---|---|
| 1.1.0 | 24 Oct 2026 | Additive (D18–D20). New delivered file B31 `grid_2026.json` (section 5b): BAH for 23 ranks × 2 dependency statuses, benchmarks for the six DoD home types, cost shares and standards, with the browser formula, its rounding and worked examples. B21 gains `grid` (section 6.1). New caveat id `type_factor_national`. B20 `cost_monthly` now comes from B29/B30 at each research profile's DoD standard: E-5 is unchanged, O-3 is recomputed (values change, interface unchanged). Consumer obligations 8–9 and the must-not exception for the grid formula; conformance check 10; six delivered files. Made before any delivery, so no consumer is affected. |
| 1.0.3 | 18 Oct 2026 | Wording only. Section 5.5: `insurance_state_fallback` describes the D11 fallback (FIO state median), not the NAIC average it replaced. Section 11, check 1: `make layer2` is the end-to-end run. Section 12: delivery location `delivery/2026/` (option B, a frozen copy) and the six `make deliver` gates. Made before any delivery, so no consumer is affected. |
| 1.0.2 | 18 Oct 2026 | p-values in B27 rounded to 5 decimal places instead of 4: at 99,999 permutations the smallest p is 0.00002, which 4 places would show as 0. Section 8 lists the fields B22 carries; section 6 names the window keys; section 12 names the handoff folder. Made before any file was produced under 1.0.x, so no consumer is affected. |
| 1.0.1 | 18 Oct 2026 | Section 4: the 2026 feature count (339) and the territory bucket's extent, from the first B28/B7 run. No interface change. |
| 1.0.0 | 18 Oct 2026 | First issue. Interface fixed from the 18 Oct decisions (D1–D8, N1, N2, 2.1–2.10) and D9 (one tile layer keyed on `code`). |

---

*AI-assistance disclosure: Claude (Anthropic) drafted this document from the repository record and the author's decisions. The decisions are the author's.*
