// ICD 5b.6 and section 9, obligation 9: the cluster overlay, the regression and the
// sensitivity layers belong to the two research profiles' statutory views only. This is
// the one place that decides it. Pure.

// The research profile a selection is the statutory view of, or null. A profile is a
// pay grade with dependents (B21 profiles); its statutory view is the DoD standard or the
// rank's anchor home type, which gridView reports as standard_view.
export function researchProfile(ui, state, standardView) {
  if (!standardView) return null;
  const profile = ui.profiles.find(
    (p) => p.pay_grade === state.rank && p.has_dependents === (state.dependents === "with"),
  );
  return profile ? profile.id : null;
}

// C16: the B27 entry for one area under a research view, or null when the area is outside
// the cluster analysis (cluster_scope false: Alaska, Hawaii, CCGs and the territory
// bucket have no B27 entry, and must not 3 forbids drawing a cluster for them).
export function clusterEntry(hotspots, code, profile, mode) {
  return hotspots.areas[code]?.[profile]?.[mode] ?? null;
}

// The overlay's class index for each cluster id, in B21 order. -1 is "tested, no value";
// -2 is outside the analysis, which the overlay leaves unfilled.
export const NO_VALUE = -1;
export const OUT_OF_SCOPE = -2;

export function clusterIndex(ui, entry) {
  if (entry === null) return OUT_OF_SCOPE;
  if (entry.cluster === null) return NO_VALUE;
  return Object.keys(ui.clusters.classes).indexOf(entry.cluster);
}
