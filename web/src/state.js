// C6: one state object. Every change goes through set(), which checks it against the
// lists in B21 and tells subscribers. Pure apart from the subscribers it calls.

export function initialState(ui) {
  return {
    rank: ui.grid.default_rank,
    dependents: ui.grid.default_dependents,
    homeType: ui.grid.default_home_type,
    mode: ui.modes[0].id,
    metric: ui.default_metric,
    selected: null,
    compare: [],
    // C16: the reader's choice to show the cluster overlay. It shows only on a research
    // view (research.js), so the choice is kept while another view is open.
    overlay: false,
  };
}

// C12: up to two pinned areas.
export const MAX_COMPARE = 2;

const ids = (list) => list.map((item) => item.id);

// Returns the accepted state and, where a value had to change, the field that changed.
export function validate(ui, state) {
  const next = { ...state };
  const corrected = [];
  const keep = (field, allowed, fallback) => {
    if (!allowed.includes(next[field])) {
      next[field] = fallback;
      corrected.push(field);
    }
  };
  keep("rank", ids(ui.grid.ranks), ui.grid.default_rank);
  keep("dependents", ids(ui.grid.dependents), ui.grid.default_dependents);
  keep("homeType", ids(ui.grid.home_types), ui.grid.default_home_type);
  keep("mode", ids(ui.modes), ui.modes[0].id);
  // A metric the grid cannot show, or cannot show in this mode, falls back to the default.
  const shown = ui.grid.metrics.filter((id) => ui.metrics[id].modes.includes(next.mode));
  keep("metric", shown, ui.default_metric);
  if (next.selected !== null && !(next.selected in ui.areas)) {
    next.selected = null;
    corrected.push("selected");
  }
  // Pinned areas: known codes, each once, at most two, in the order they were pinned.
  const pinned = Array.isArray(next.compare) ? next.compare : [];
  const compare = [...new Set(pinned.filter((code) => code in ui.areas))].slice(0, MAX_COMPARE);
  if (!Array.isArray(next.compare) || compare.length !== next.compare.length) corrected.push("compare");
  next.compare = compare;
  if (typeof next.overlay !== "boolean") {
    next.overlay = false;
    corrected.push("overlay");
  }
  return { state: next, corrected };
}

export function createStore(ui, start = initialState(ui)) {
  let state = validate(ui, start).state;
  const listeners = new Set();
  return {
    get: () => state,
    set(patch) {
      const result = validate(ui, { ...state, ...patch });
      const previous = state;
      state = result.state;
      for (const listener of listeners) listener(state, previous, result.corrected);
      return result;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
