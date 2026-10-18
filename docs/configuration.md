# Configuration reference

The project's authored configuration lives in `config/`. This page explains every field and the reasoning behind every value. The JSON files themselves hold values only.

## Why the explanations live here

Pipeline stages record the SHA-256 of each config they read:

- B12–B15 and B16–B18 record A12 and A13
- B11 records `ownership.json`

`make verify` then checks that those hashes match the configs in the repository. If explanations sat inside the JSON, correcting a sentence would change the file's hash. The M4–M5 evidence would then go stale even though no number had changed.

Keeping prose here means a wording fix touches only this page. `make check-config` enforces the split: it fails on `_about`, `rationale`, `note` or `*_note` fields, and on a missing `_doc` pointer.

## Changing a value

1. Edit the value in `config/`, then update the matching section below.
2. Run `make check-config`.
3. Rerun every stage that records the file:
   - A12 or A13: `make metrics spatial`
   - `ownership.json`: `make benchmarks metrics spatial`
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

MHAs that survive the Benjamini–Hochberg false-discovery-rate correction get the `fdr_marker` outline. On 18 Oct, 2 survived (1 HL, 1 LH) at 9,999 permutations. A rerun at 99,999 permutations checks whether that count is limited by permutation resolution.

---

## `config/ownership.json` (B11)

This file still carries its explanations inline: `_about`, `rationale`, `notes` and `sources`. A8 replaces its property-tax and insurance sections with locality data in M6. The explanations move here in that same change, so B11 and everything after it are rerun once rather than twice.

---

*AI-assistance disclosure: Claude (Anthropic) moved these explanations out of the config files and edited them for accuracy with the author. The decisions are the author's.*
