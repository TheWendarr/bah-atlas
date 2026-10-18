# Research framing

Condensed from the course research proposal and instructor feedback. The
instructor's key redirect: the original submission described data and delivery
(collect public data, use APIs, build a webapp) rather than a research method,
and the "maximize take-home pay" goal is weak because service members cannot
freely choose duty stations by housing cost. The stronger contribution is
identifying and explaining geographic disparities between BAH and actual
housing costs.

## Research question

To what degree do 2026 BAH rates meet their statutory design (the local cost of
adequate housing less a member cost share fixed at 5% of the national average
cost) when measured against an independent housing-cost benchmark, and are the
resulting adequacy gaps spatially clustered across U.S. Military Housing Areas
rather than randomly distributed?

*Reworded 18 Oct 2026 to match the adopted test variable. The earlier wording,
"statutory coverage target (~95% of local housing cost)", described the nominal
95% figure, which holds only where local cost equals the national average.*

## Method (summary)

- **Coverage ratio** R = BAH / local cost of the anchor dwelling (descriptive).
- **Test variable (adopted 18 Oct 2026):** adequacy gap = (BAH + member cost
  share) / local cost - 1, target 0. 37 U.S.C. 403(b)(3) deducts the same dollar
  cost share (5% of the *national* average cost) everywhere, so BAH meets its
  design where BAH + cost share equals local cost; it equals exactly 95% of local
  cost only where local cost equals the national mean. The original fixed reading,
  Gap = R - 0.95, is kept as a sensitivity check (`flat95_gap`).
- **Benchmark**: Zillow ZORI (rent), cross-checked against HUD FMR. Rent, not
  buy, for the primary test — BAH is statutorily benchmarked to rental cost.
- **Unit of analysis**: the MHA. Requires the MHA<->ZCTA crosswalk.
- **Hypotheses**: (H1) gaps are spatially autocorrelated (Moran's I), not
  random; (H2) gap sign/size associates with rent level, rent growth, urbanicity.
  H1 was tested in M5 (supported). **H2 scope (decided 18 Oct 2026, reduced):**
  spatial regression (B19) of the adequacy gap on rent level (B8), rent growth
  (the ZORI history, A3) and urbanicity (population density from ACS, A9 -> B24).
  BEA Regional Price Parities (A10, B25) were dropped: they exist only for states
  and metro areas, coarser than MHAs, and their rent component repeats the
  rent-level variable. See the [M6 plan](plans/m6-plan.md).
- **Procedure**: coverage surface -> ESDA -> global Moran's I -> LISA/Getis-Ord
  hotspots -> spatial regression.

## Scope

Primary: one anchor profile (E-5 with dependents) plus one contrast profile
(O-3 with dependents); CONUS-first. The spatial statistics use the CONUS MHAs
only. Alaska and Hawaii MHAs are mapped with their values but left out of the
clustering tests. County Cost Groups and the territory bucket are mapped on
polygons synthesized from their ZIP assignments (DoD publishes none), labelled as
non-authoritative, and are also left out of the clustering tests. County Cost
Groups show their BAH rates only: they have no DoD rent/utilities split and many
of their rural ZIPs have no rent benchmark, so no adequacy value is computed for
them (decided 18 Oct 2026).

## Guardrails

- Utilities (resolved, M3): BAH covers utilities and ZORI does not. B8 grosses
  ZORI up to utilities-inclusive with DoD's own rent/utilities split per MHA (B5),
  and the HUD SAFMR cross-check is already gross rent.
- Bibliography (in progress): 37 U.S.C. Sec. 403 and the DTMO out-of-pocket table
  are cited in `SOURCES.md`; cite the DoD BAH Primer and DTMO methodology directly
  in the formal write-up.
