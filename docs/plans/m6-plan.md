# M6 plan — Layer 2 to Layer 3 handoff

**Milestone:** M6 2.7 Front-End Payload + 2.8 Writeup · **due Fri 30 Oct 2026** (dates below move with any schedule change) · **written:** 18 Oct 2026 · tracker: [WBS](../WBS.md)

M6 is the handoff from the offline pipeline to the map. When it closes, Layer 3 can be built against three files whose shape will not change underneath it: the attribute payload (B20), the UI metadata (B21) and the build manifest (B22), plus the polygon tiles (B7, B28). This page records the decisions taken on 18 Oct, the decisions still open, and how each node will be built and checked.

Nodes started 18 Oct: **A8, B20, B21, B22, B23, B28, W1**. Not started, waiting on a decision: **B27** (D2, D5), **A9, A10, B24, B25, B19** (D8). Scrapped: **B26**. Layer 3 (C1–C24) is not started until this handoff exists.

## 1. Decisions recorded 18 Oct 2026

| Ref | Decision | Effect on the work |
|---|---|---|
| D1 | `adequacy_gap` = (BAH + member cost share) ÷ local cost − 1 is the primary test variable; `flat95_gap` stays as the sensitivity check. | Research proposal method updated. No pipeline change: B12–B18 already use it. |
| 2.1 | County Cost Groups (ZZ codes) and the territory bucket (XX code) get map geometry, even though no authoritative polygon exists. The method is stated wherever the polygons appear. | New node **B28**. |
| 2.2 | Alaska and Hawaii MHAs carry their metric values on the map but stay out of the spatial statistics. | B20 includes them; B16–B18 unchanged. |
| 2.4 | Where buy mode has a home value but no ZORI utilities estimate (10 MHAs), the payload uses PITI (`own_housing_monthly`) with a note that it excludes utilities because the MHA has no ZORI data. | B20 rule; B23 checks it. |
| 2.7 | Property tax and insurance come from authoritative locality-level sources instead of national placeholders. | **A8** started; B11 and everything after it is rerun. |
| 2.9 | H3 is removed from the project. | **B26** scrapped. |
| 2.10 | Front-end build choices (bundler, hosting, basemap) wait until this handoff exists. | No Layer 3 work in M6. |

## 2. Decisions still open

| Ref | Question | Blocks |
|---|---|---|
| D2 | Local cluster classes at p < 0.05 with the FDR result as a caveat, FDR-significant only, or both (exploratory classes with FDR survivors marked)? | B27, W1 wording |
| D3 (2.3) | Which values go in the payload: map metrics only, plus the inputs that explain them, plus the sensitivity values, or sensitivity values as map layers too? | B20 |
| D5 (2.5) | Cluster results inside B20, or a separate B27 overlay file? | B20, B27 |
| D6 (2.6) | Contract conventions: versioning, precision, layout, null encoding, caveats, provenance. | B20, B21, B22 |
| D8 (2.8) | Hypothesis H2: full chain, a reduced chain, or dropped as a scope change. | A9, A10, B24, B25, B19 |
| N1 | CCG values: polygon and BAH rate only, or adequacy metrics too (CCGs have no DoD rent/utilities split, and many rural ZIPs have no ZORI)? | B20 |
| N2 | Insurance vintage: the newest locality data is 2018–2022. Use it as published with the understatement documented, or scale it to 2026? | A8 |

The draft contract in section 3 shows where each of these lands.

## 3. Node plans

Every script follows the existing pattern: read inputs as-is, validate loudly, write tidy outputs plus a manifest, and test on synthetic fixtures. `make evidence` copies each new manifest into `docs/evidence/`.

### B28 · CCG and territory polygons — target Wed 21 Oct

- **Why:** DoD publishes no polygons for County Cost Groups. The DTMO crosswalk does assign ZIPs to them: in 2026, 20,465 ZIPs map to the 39 ZZ codes and 214 ZIPs to the single XX code.
- **Method:** the same ZIP → ZCTA → dissolve that builds B6 (A2 + B1), applied to the `ccg` and `unknown` classes. Extend `build_mha_geometry.py` with `--classes ccg,unknown` so the code path stays identical, and write a separate `non_mha_YYYY.gpkg` / `.geojson`. B6 is left untouched, so B16–B18 do not change.
- **Annotation:** every feature carries `class` (`ccg` or `unknown`) and `geometry_source: "ZCTA dissolve of DTMO ZIP assignments (non-authoritative)"`. The same statement goes in SOURCES.md, the data dictionary, B21 (shown in the UI) and W1.
- **Tiles:** add a second layer `non_mha` to B7's PMTiles, or a second PMTiles file. Choose when C1 is planned; the GeoJSON is the M6 deliverable.
- **Checks:** every ZZ and XX code with ZIPs gets a feature; no ZCTA is assigned to both an MHA and a CCG; report unmatched ZIPs as B6 does. Confirm which territory the XX bucket covers (expected: Puerto Rico).
- **Done when:** the file exists, the build report is in its manifest, and the tests pass.

### A8 · property tax and insurance by locality — target Sat 24 Oct (optional node; feeds B11)

- **Property tax:** ACS 5-year detailed tables at ZCTA level through the Census API, with the year pinned:
  - B25090_001E, aggregate real estate taxes paid
  - B25079_001E, aggregate value of owner-occupied units

  The MHA effective rate = Σ taxes ÷ Σ value over the MHA's ZCTAs. Summing aggregates before dividing weights each ZCTA by its housing stock and avoids taking a ratio of medians. It still has caveats: ACS taxes are self-reported, top-coded, and lag assessments. Fall back to the state rate for an MHA whose ZCTAs have no data.
- **Insurance:** Treasury Federal Insurance Office ZIP-level average homeowners premium, 2018–2022. The published file covers only ZIPs with at least ten insurers and fifty policies. Aggregate it to the MHA median, as B8–B10 do. Fall back to the NAIC state average for MHAs with no published ZIPs. Decision N2 sets the dollar year.
- **Pipeline:** change A8 in `fetch_sources.py` from `manual` to `api` (ACS) plus `direct` (FIO workbook). Add `benchmarks/tax_insurance_to_mha.py`, which writes `mha_tax_insurance.csv` with a source flag per MHA (`locality` or `state_fallback`). Change `config/ownership.json` from national values to `from_A8`, and mark the placeholder status as superseded.
- **Rerun chain:** B11 → B14/B15 → B17/B18 (buy-mode tests). The rent results do not change. The M5 buy-mode Moran's I values (E-5 0.397, O-3 0.482) will be replaced. The next progress note reports old against new.
- **Done when:** B11 has no placeholder warnings, every MHA has a sourced rate, and the change in buy-mode results is recorded.

### B20 · attribute payload (data contract) — target Wed 28 Oct

One JSON file the map joins to polygons through feature-state, keyed by area code. Draft shape, with illustrative numbers; the bracketed tags mark open decisions:

```jsonc
{
  "schema_version": "1.0.0",                       // [D6]
  "bah_year": 2026,
  "build_id": "sha256 of the B22 manifest",         // [D6]
  "profiles": ["e5_dep", "o3_dep"],
  "modes": ["rent", "buy"],
  "areas": {
    "CO018": {
      "class": "mha",                               // mha | ccg | unknown
      "cluster_scope": true,                        // false for AK, HI, CCG, XX
      "e5_dep": {
        "rent": {
          "status": "ok",                           // ok | no_zori | ...
          "adequacy_ratio": 1.0463, "design_gap_usd": 99,
          "coverage_ratio": 0.9874, "surplus_usd": -27,
          "bah": 2112, "cost_share": 126, "cost": 2139,   // [D3]
          "flat95_gap": 0.0374, "safmr_adequacy_ratio": 1.02  // [D3]
        },
        "buy": { "status": "ok", "...": "..." }
      },
      "o3_dep": { "...": "..." }
    }
  }
}
```

- **Scope:** 299 MHAs and 39 CCGs (metrics per N1), plus the XX bucket with status `no_rate`. Alaska and Hawaii are included with `cluster_scope: false`.
- **Rules:** buy mode falls back to PITI with status `piti_only_no_zori` (decision 2.4). Blank values are `null` with a status explaining why. Values come only from B12–B15 output; B20 computes nothing new.
- **Checks:** every code in B6 ∪ B28 has an entry and vice versa; every non-null value matches its B12–B15 source row; the file size is reported (expected well under 300 KB).
- **Docs:** a new data-dictionary section, and the contract published as `docs/data-contract.md`.

### B21 · UI metadata — target Wed 28 Oct

Everything the map needs to label and colour what B20 contains:

- profile labels (A12) and the metric definitions with A13 classes, colours and labels
- area names and classes (B3, B1), plus the caveat texts referenced by id (utilities gross-up, A8 sources, CCG geometry, PITI fallback, AK/HI cluster exclusion)
- benchmark windows, and the source attributions that C20 will display

**Check:** every class, metric and caveat id that B20 uses resolves in B21.

### B22 · build manifest — target Thu 29 Oct

- Gathers every stage manifest (A-level fetch record through B28) into one file: input checksums, windows, row counts, warnings, software versions, git commit.
- Its own SHA-256 is the `build_id` written into B20 and B21, so the map can show which build it is drawing.
- **Check:** the build stops if any stage manifest is missing, or was built from inputs other than the ones beside it.

### B23 · QA / validation report — target Thu 29 Oct

A generated `docs/qa/qa-2026.md` that samples each stage and states what it found:

1. Join coverage at each step: ZIPs → ZCTAs → MHAs; ZIPs with no ZORI, ZHVI or SAFMR.
2. Every warning carried in the stage manifests (Hamptons ZORI, duplicate HUD rows, KNN links over 500 km, and others).
3. A hand-checked trace of three MHAs from raw source to B20 value: one in surplus, one short, one with a fallback.
4. The ZORI vs SAFMR agreement.
5. The A8 locality vs state-fallback counts.
6. Statistical caveats: FDR result, k sensitivity, CONUS scope.

C21 (the about / data-caveats page) is built from this report later.

### W1 · Layer 2 writeup — target Fri 30 Oct (author-written)

Wendell writes this; the outline points to the evidence each part draws on.

1. **Purpose** — how Layer 1 becomes Layer 3, and why the pipeline is offline and reproducible.
2. **From sources to MHAs** — the crosswalk, the synthesized geometry (B6, B28), and the median rule. Evidence: B1–B11 manifests.
3. **The adequacy test** — the statute, the cost share, and why `adequacy_gap` replaced the flat 95% target (D1). Evidence: coverage manifest.
4. **Spatial statistics** — the weights choice, the global result for H1, and how local clusters are reported (D2). Evidence: spatial manifest, LISA map.
5. **The handoff** — the B20/B21/B22 contract and what the map may and may not do with it.
6. **Limitations** — every caveat from B23.

### Waiting on decisions

- **B27 hotspot overlay payload:** built only if D5 chooses a separate file. Its content follows D2.
- **H2 chain (A9, A10, B24, B25, B19):** set by D8. If A9 goes ahead, its ACS API pull shares code and geography with A8's property-tax pull.
- **B26 H3 overlay:** scrapped 18 Oct; the id is kept in the tracker.
- **Layer 3:** C1 will serve the B28 layer as well as B7. That edge is added when Layer 3 planning starts.

## 4. Sequence

| Target | Work | Depends on |
|---|---|---|
| Wed 21 Oct | B28 polygons | — |
| Sat 24 Oct | A8 pull; rerun B11 → B18 | N2 |
| Sat 24 Oct | Settle D3, D5, D6, N1 | — |
| Wed 28 Oct | B20, B21 | D3, D5, D6, N1, A8 rerun |
| Thu 29 Oct | B22, B23 | B20, B21 |
| Fri 30 Oct | W1; close M6 | B23, D2 |

---

*AI-assistance disclosure: Claude (Anthropic) drafted this plan from the repository record and the author's 18 Oct decisions. The decisions are the author's.*
