# Layer 2 write-up — how Layer 1 becomes Layer 3

**W1** · M6 · author: Wendell McGowan III · written: ____ · covers the delivery in [`delivery/2026/`](../delivery/2026/) (data contract section 12)

<!--
Scaffold, 18 Oct 2026. The headings, the evidence lists and the prompts are scaffolding; the
prose is the author's. Each quoted line that opens with the pencil marker is a section still to
write: replace it with your text. `make deliver-check` refuses the delivery while any remains (gate 6).
Delete this comment when you finish.
-->

## 1. Purpose

> ✎ AUTHOR: What does Layer 2 take in and hand out, and why is it an offline, reproducible pipeline rather than live API calls from the map? Who reads this document (instructor, Layer 3 builder, a later BAH year)?

Evidence: [nodal architecture and tracker](WBS.md) · [data contract, sections 1–2](data-contract.md) · [research proposal](research-proposal.md)

## 2. From sources to areas

> ✎ AUTHOR: How a ZIP-level value becomes one value per MHA. Cover the DTMO crosswalk (299 MHAs, 39 County Cost Groups, the territory bucket), the synthesized polygons (no DoD polygon layer exists; B6 and B28, non-authoritative), the median rule, the utilities gross-up of ZORI (B5), and what is lost at each join (ZIP → ZCTA dropout, ZIPs with no ZORI).

Evidence: [B1–B4](evidence/manifest.json) · [B6](evidence/mha_2026_geometry_manifest.json) · [B28](evidence/non_mha_2026_geometry_manifest.json) · [B8](evidence/mha_zori_manifest.json) · [B9](evidence/mha_zhvi_manifest.json) · [B10](evidence/mha_safmr_manifest.json) · [A8](evidence/mha_tax_insurance_manifest.json) · [B11](evidence/mha_ownership_manifest.json) · B23 report, section 7

## 3. The adequacy test

> ✎ AUTHOR: The statute (37 U.S.C. 403(b)(3)), the member cost share, and why `adequacy_gap` is the test variable rather than a flat 95% target (D1). State the headline result for E-5 renters and the O-3 contrast, and what the SAFMR cross-check says.

Evidence: [coverage manifest](evidence/coverage_metrics_manifest.json) · [configuration reference](configuration.md) · B23 report, section 10

## 4. Spatial statistics

> ✎ AUTHOR: H1 — the weights choice (KNN, why not queen contiguity), the global Moran's I as the confirmatory result, and the local clusters as exploratory with the FDR survivors marked (D2). H2 — what the B19 regression found (model chosen and why, each predictor's sign and significance, collinearity), and the shared-denominator caveat on the rent-level coefficient.

Evidence: [weights](evidence/weights_manifest.json) · [B17/B18](evidence/spatial_stats_manifest.json) · [LISA map](evidence/mha_lisa_e5_dep_rent_map.png) · B24 manifest (`evidence/mha_density_manifest.json`) · B19 manifest (`evidence/regression_manifest.json`) · B23 report, section 11

## 5. The handoff

> ✎ AUTHOR: The six delivered files and what each is for, the conventions (one file keyed by area code, null plus status, caveat ids), what the map must and must not do with them, and how a reader can verify the delivery (SHA256SUMS, build_id, `make deliver-check`).

Evidence: [data contract, sections 2–9 and 12](data-contract.md) · [`delivery/2026/`](../delivery/2026/) · B23 report, sections 1–6

## 6. Limitations

> ✎ AUTHOR: Every caveat the map shows, in plain words: County Cost Groups without benchmarks (N1), 2022 insurance (N2), ZORI's utilities gross-up, the ZIP → ZCTA dropout, Alaska and Hawaii outside the clustering, the PITI-only buy rows, the exploratory local clusters, and anything the B23 report raised.

Evidence: B23 report, sections 8 and 12 · [SOURCES.md](SOURCES.md)

## 7. Actions and decisions

> ✎ AUTHOR: The record D10 asks for: every decision behind the delivered files, with its date and reason, in your words. The decision tables to draw from are listed below; summarize them rather than copying them.

Evidence: [M6 plan, section 1 (D1–D17, N1, N2, 2.1–2.10)](plans/m6-plan.md#1-decisions-18-oct-2026) · progress notes ([index](progress/README.md)), part 4 of each · [data contract change log](data-contract.md#13-change-log)

---

*AI-assistance disclosure: Claude (Anthropic) drafted the headings, evidence lists and prompts of this outline from the M6 plan. The text of each section is the author's.*
