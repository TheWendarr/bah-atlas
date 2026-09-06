# Research framing

Condensed from the course research proposal and instructor feedback. The
instructor's key redirect: the original submission described data and delivery
(collect public data, use APIs, build a webapp) rather than a research method,
and the "maximize take-home pay" goal is weak because service members cannot
freely choose duty stations by housing cost. The stronger contribution is
identifying and explaining geographic disparities between BAH and actual
housing costs.

## Research question

To what degree do BAH rates achieve their statutory coverage target (~95% of
local housing cost) when measured against an independent housing-cost benchmark,
and are the resulting adequacy gaps spatially clustered across U.S. Military
Housing Areas rather than randomly distributed?

## Method (summary)

- **Coverage ratio** R = BAH / local cost of the anchor dwelling; design target
  R ~= 0.95. Test variable: Gap = R - 0.95.
- **Benchmark**: Zillow ZORI (rent), cross-checked against HUD FMR. Rent, not
  buy, for the primary test — BAH is statutorily benchmarked to rental cost.
- **Unit of analysis**: the MHA. Requires the MHA<->ZCTA crosswalk.
- **Hypotheses**: (H1) gaps are spatially autocorrelated (Moran's I), not
  random; (H2) gap sign/size associates with rent level, rent growth, urbanicity.
- **Procedure**: coverage surface -> ESDA -> global Moran's I -> LISA/Getis-Ord
  hotspots -> spatial regression.

## Scope

Primary: one anchor profile (E-5 with dependents) plus one contrast profile;
CONUS-first. CCG and territory areas are out of scope (separate geography).

## Open guardrails

- Utilities: BAH's 95% target includes utilities; the rent benchmark excludes
  them. Either add a utility estimate or state the exclusion as a known bias.
- Bibliography: statutory/regulatory basis (37 U.S.C. Sec. 403, DoD BAH Primer,
  DTMO methodology) as load-bearing citations for the coverage target.
