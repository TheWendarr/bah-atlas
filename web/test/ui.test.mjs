// C6, C9 (D27), C14, C25: state validation, scale choice, the render function and the
// standard notice, on the delivered files.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { scaleFor } from "../src/classify.js";
import { noticeText } from "../src/notice.js";
import { computeView } from "../src/render.js";
import { createStore, initialState, validate } from "../src/state.js";

const read = (name) => JSON.parse(readFileSync(new URL(`../../delivery/2026/${name}`, import.meta.url), "utf8"));
const files = { ui: read("ui_metadata_2026.json"), grid: read("grid_2026.json"), payload: read("payload_2026.json") };
const { ui } = files;

test("the initial state is the B21 default view", () => {
  assert.deepEqual(initialState(ui), {
    rank: "E5",
    dependents: "with",
    homeType: "standard",
    mode: "rent",
    metric: "adequacy_ratio",
    selected: null,
  });
});

test("values outside the B21 lists fall back to the defaults and are reported", () => {
  const { state, corrected } = validate(ui, { ...initialState(ui), rank: "E10", homeType: "castle", selected: "ZZ000" });
  assert.equal(state.rank, "E5");
  assert.equal(state.homeType, "standard");
  assert.equal(state.selected, null);
  assert.deepEqual(corrected.sort(), ["homeType", "rank", "selected"]);
});

test("a metric the grid cannot show falls back to the default metric", () => {
  const { state, corrected } = validate(ui, { ...initialState(ui), metric: "flat95_gap" });
  assert.equal(state.metric, ui.default_metric);
  assert.deepEqual(corrected, ["metric"]);
});

test("the store tells subscribers the new and previous state", () => {
  const store = createStore(ui);
  const seen = [];
  store.subscribe((state, previous) => seen.push([previous.rank, state.rank]));
  store.set({ rank: "O3" });
  assert.deepEqual(seen, [["E5", "O3"]]);
  assert.equal(store.get().rank, "O3");
});

test("an off-standard view uses the metric's wider scale and its own labels (D27)", () => {
  const metric = ui.metrics.adequacy_ratio;
  const standard = scaleFor(metric, true);
  const off = scaleFor(metric, false);
  assert.equal(standard.offStandard, false);
  assert.deepEqual(standard.breaks, metric.breaks);
  assert.equal(off.offStandard, true);
  assert.deepEqual(off.breaks, metric.off_standard.breaks);
  assert.deepEqual(off.classLabels, metric.off_standard.class_labels);
  assert.deepEqual(off.colors, metric.colors);
});

test("every one of the 322 selections gets a filled notice in the right wording (C25)", () => {
  let count = 0;
  for (const { id: rank } of ui.grid.ranks) {
    for (const { id: dependents } of ui.grid.dependents) {
      for (const { id: homeType } of ui.grid.home_types) {
        const state = { ...initialState(ui), rank, dependents, homeType };
        const view = computeView(files, state);
        const text = noticeText(ui, state, view.standardView);
        assert.doesNotMatch(text, /[{}]/, `${rank} ${dependents} ${homeType}`);
        assert.ok(text.includes(ui.grid.standards_text[rank][dependents]));
        const template = view.standardView ? ui.grid.notice.standard : ui.grid.notice.off_standard;
        assert.ok(text.startsWith(template.split("{")[0]));
        if (homeType === "standard") assert.equal(view.standardView, true);
        count += 1;
      }
    }
  }
  assert.equal(count, 322);
});

test("the anchor home type of a rank is a statutory view (E-5 with dependents, 2 BR townhouse)", () => {
  const view = computeView(files, { ...initialState(ui), homeType: "th2" });
  assert.equal(view.standardView, true);
  assert.equal(view.scale.offStandard, false);
});

test("the default view classes match the delivered values", () => {
  const { classes } = computeView(files, initialState(ui));
  assert.deepEqual(["CO046", "NC182", "ZZ580"].map((code) => classes.get(code)), [5, 2, -1]);
});

test("a selected area carries one view per mode, equal to the payload for E-5 with dependents", () => {
  const { selected } = computeView(files, { ...initialState(ui), selected: "CO046" });
  for (const mode of ["rent", "buy"]) {
    const expected = files.payload.areas.CO046.e5_dep[mode];
    for (const field of ["bah_monthly", "cost_monthly", "adequacy_ratio", "design_gap_usd", "coverage_ratio", "surplus_usd"]) {
      assert.equal(selected[mode][field], expected[field], `${mode} ${field}`);
    }
  }
});
