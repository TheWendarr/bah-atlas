// C14: the one path from state to what the map shows. Pure: it computes, and main.js
// writes the result to the map and the page.

import { classIndex, scaleFor } from "./classify.js";
import { gridView, zipMetricValues, zipView } from "./grid.js";
import { noticeText } from "./notice.js";
import { clusterEntry, clusterIndex, researchProfile } from "./research.js";
import { isZip } from "./state.js";

const viewOf = (grid, code, state, mode) => gridView(grid, code, state.rank, state.dependents, state.homeType, mode);

// C27: a place is an area code or, in the ZIP view, a ZIP code. A ZIP code's view needs
// B36, so until it has loaded the place has no view.
export function placeView(files, id, state, mode) {
  if (!isZip(id)) return viewOf(files.grid, id, state, mode);
  if (!files.zipgrid?.zips[id]) return null;
  return zipView(files.grid, files.zipgrid, id, state.rank, state.dependents, state.homeType, mode);
}

export function computeView(files, state) {
  const { grid, ui } = files;
  const codes = Object.keys(grid.areas);

  // Whether a view is the statutory test depends only on rank, dependents and home type.
  const standardView = viewOf(grid, codes[0], state, state.mode).standard_view;
  const scales = Object.fromEntries(ui.grid.metrics.map((id) => [id, scaleFor(ui.metrics[id], standardView)]));
  const scale = scales[state.metric];

  const classes = new Map();
  for (const code of codes) {
    classes.set(code, classIndex(viewOf(grid, code, state, state.mode)[state.metric], scale.breaks));
  }

  // C27: the ZIP codes' classes, on the same scale, once B36 has loaded.
  let zipClasses = null;
  if (state.geography === "zip" && files.zipgrid) {
    zipClasses = new Map();
    const { zips, values } = zipMetricValues(grid, files.zipgrid, state.rank, state.dependents, state.homeType, state.mode, state.metric);
    for (let n = 0; n < zips.length; n++) zipClasses.set(zips[n], classIndex(values[n], scale.breaks));
  }

  const selectedViews =
    state.selected === null ? null : ui.modes.map((mode) => [mode.id, placeView(files, state.selected, state, mode.id)]);
  const selected = selectedViews?.every(([, view]) => view !== null) ? Object.fromEntries(selectedViews) : null;
  // A ZIP code's MHA beside it in the panel (C28), in both modes.
  const selectedArea =
    selected && isZip(state.selected)
      ? Object.fromEntries(ui.modes.map((mode) => [mode.id, viewOf(grid, files.zipgrid.zips[state.selected].area, state, mode.id)]))
      : null;

  // C12: each pinned place in the current mode, so the comparison follows the controls.
  const compared = state.compare
    .map((code) => ({ code, view: placeView(files, code, state, state.mode) }))
    .filter(({ view }) => view !== null);

  // C16: the cluster overlay shows only when the reader asked for it and the selection is
  // a research profile's statutory view (ICD 9, must 9). B27 holds adequacy_gap clusters
  // for both modes, by MHA, so the ZIP view never shows them (D36).
  const research = state.geography === "zip" ? null : researchProfile(ui, state, standardView);
  const overlay = state.overlay && research !== null;
  let clusters = null;
  let selectedCluster = null;
  if (overlay) {
    clusters = new Map();
    for (const code of codes) {
      const entry = clusterEntry(files.hotspots, code, research, state.mode);
      clusters.set(code, { index: clusterIndex(ui, entry), fdr: entry?.lisa_fdr_significant === true });
    }
    if (state.selected !== null) selectedCluster = { entry: clusterEntry(files.hotspots, state.selected, research, state.mode) };
  }

  return {
    standardView,
    scale,
    scales,
    classes,
    zipClasses,
    selected,
    selectedArea,
    compared,
    notice: noticeText(ui, state, standardView),
    research,
    overlay,
    clusters,
    selectedCluster,
  };
}
