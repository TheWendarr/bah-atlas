// C14: the one path from state to what the map shows. Pure: it computes, and main.js
// writes the result to the map and the page.

import { classIndex, scaleFor } from "./classify.js";
import { gridView } from "./grid.js";
import { noticeText } from "./notice.js";

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

  return { standardView, scale, scales, classes, selected, notice: noticeText(ui, state, standardView) };
}
