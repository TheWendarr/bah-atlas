// C6: one state object. Every change goes through set(), which checks it against the
// lists in B21 and tells subscribers. Pure apart from the subscribers it calls.
//
// C26 (D36): `geography` chooses the MHA or the ZIP view. In the ZIP view the open place
// and the pinned places may be ZIP codes as well as area codes. Whether a ZIP code is in
// the ZIP view is known only once B36 has loaded, so the store is given that lookup then
// (setZipLookup) and checks every ZIP code again.

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
    geography: ui.grid.default_geography ?? "mha",
  };
}

export const isZip = (id) => typeof id === "string" && /^\d{5}$/.test(id);

// C12: up to two pinned areas.
export const MAX_COMPARE = 2;

const ids = (list) => list.map((item) => item.id);

// What a place id stands for now: the id itself, its MHA (a ZIP code outside the ZIP view,
// once B36 is known), or null. Before B36 loads a ZIP code is kept in the ZIP view.
function place(ui, id, geography, zipArea) {
  if (typeof id !== "string") return null;
  if (id in ui.areas) return id;
  if (!isZip(id)) return null;
  if (geography === "zip") return zipArea ? (zipArea(id) ? id : null) : id;
  return zipArea?.(id) ?? null;
}

// Returns the accepted state and, where a value had to change, the field that changed.
export function validate(ui, state, zipArea = null) {
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
  keep("geography", ids(ui.grid.geographies ?? [{ id: "mha" }]), ui.grid.default_geography ?? "mha");
  if (next.selected !== null) {
    const id = place(ui, next.selected, next.geography, zipArea);
    if (id !== next.selected) {
      next.selected = id;
      corrected.push("selected");
    }
  }
  // Pinned places: known ids, each once, at most two, in the order they were pinned. A ZIP
  // code pinned in the ZIP view becomes its MHA when the reader returns to MHAs.
  const pinned = Array.isArray(next.compare) ? next.compare : [];
  const kept = pinned.map((id) => place(ui, id, next.geography, zipArea)).filter((id) => id !== null);
  const compare = [...new Set(kept)].slice(0, MAX_COMPARE);
  if (!Array.isArray(next.compare) || compare.join() !== pinned.join()) corrected.push("compare");
  next.compare = compare;
  if (typeof next.overlay !== "boolean") {
    next.overlay = false;
    corrected.push("overlay");
  }
  return { state: next, corrected };
}

export function createStore(ui, start = initialState(ui)) {
  let zipArea = null;
  let state = validate(ui, start).state;
  const listeners = new Set();
  return {
    get: () => state,
    // C27: B36 has loaded; `lookup(zip)` gives a ZIP code's MHA, or undefined outside the view.
    setZipLookup(lookup) {
      zipArea = lookup;
      return this.set({});
    },
    set(patch) {
      const result = validate(ui, { ...state, ...patch }, zipArea);
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
