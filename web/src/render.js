// C14: the one path from state to what the map shows. Pure: it computes, and main.js
// writes the result to the map and the page.

import { classIndex, scaleFor } from "./classify.js";
import { gridView } from "./grid.js";
import { noticeText } from "./notice.js";
import { clusterEntry, clusterIndex, researchProfile } from "./research.js";

const viewOf = (grid, code, state, mode) => gridView(grid, code, state.rank, state.dependents, state.homeType, mode);

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

  const selected =
    state.selected === null
      ? null
      : Object.fromEntries(ui.modes.map((mode) => [mode.id, viewOf(grid, state.selected, state, mode.id)]));

  // C12: each pinned area in the current mode, so the comparison follows the controls.
  const compared = state.compare.map((code) => ({ code, view: viewOf(grid, code, state, state.mode) }));

  // C16: the cluster overlay shows only when the reader asked for it and the selection is
  // a research profile's statutory view (ICD 9, must 9). B27 holds adequacy_gap clusters
  // for both modes.
  const research = researchProfile(ui, state, standardView);
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
    selected,
    compared,
    notice: noticeText(ui, state, standardView),
    research,
    overlay,
    clusters,
    selectedCluster,
  };
}
