// C6, C9 (D27), C14, C25: state validation, scale choice, the render function and the
// standard notice, on the delivered files.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { scaleFor } from "../src/classify.js";
import { noticeText } from "../src/notice.js";
import { gridView } from "../src/grid.js";
import { WINDOW_SOURCE, areaAttribution } from "../src/sources.js";
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
    compare: [],
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

test("buy-mode PITI equals B20's own_housing_monthly for both research profiles in every area (C11)", () => {
  let compared = 0;
  for (const profile of ui.profiles) {
    for (const [code, area] of Object.entries(files.payload.areas)) {
      const expected = area[profile.id]?.buy;
      if (!expected) continue;
      const view = gridView(files.grid, code, profile.pay_grade, "with", "standard", "buy");
      assert.equal(view.own_housing_monthly, expected.own_housing_monthly, `${profile.id} ${code}`);
      compared += 1;
    }
  }
  // 339 areas for each of the two profiles; O-3's standard is a blend, so its PITI is too.
  assert.equal(compared, 2 * 339);
});

test("rent views carry no PITI", () => {
  assert.equal(gridView(files.grid, "CO046", "E5", "with", "standard", "rent").own_housing_monthly, null);
});

test("pinned areas keep known codes, once each, at most two (C12)", () => {
  const { state, corrected } = validate(ui, { ...initialState(ui), compare: ["CO046", "ZZ000", "CO046", "NC182", "CA038"] });
  assert.deepEqual(state.compare, ["CO046", "NC182"]);
  assert.ok(corrected.includes("compare"));
  assert.deepEqual(validate(ui, { ...initialState(ui), compare: "CO046" }).state.compare, []);
  assert.deepEqual(validate(ui, { ...initialState(ui), compare: ["NC182", "CO046"] }).corrected, []);
});

test("each pinned area is computed in the current mode and follows the controls (C12)", () => {
  const state = { ...initialState(ui), rank: "O3", mode: "buy", compare: ["CO046", "AK400"] };
  const { compared } = computeView(files, state);
  assert.deepEqual(compared.map(({ code }) => code), ["CO046", "AK400"]);
  for (const { code, view } of compared) {
    assert.deepEqual(view, gridView(files.grid, code, "O3", "with", "standard", "buy"));
  }
  // AK400 has a home value but no rent index: PITI alone, with its own status.
  assert.equal(compared[1].view.status, "piti_only_no_zori");
});

test("every B21 data window belongs to a B21 source (C20)", () => {
  const ids = new Set(ui.sources.map((source) => source.id));
  for (const key of Object.keys(ui.windows)) {
    assert.ok(key in WINDOW_SOURCE, `window ${key} has no source in sources.js`);
    assert.ok(ids.has(WINDOW_SOURCE[key]), `window ${key}: unknown source ${WINDOW_SOURCE[key]}`);
  }
});

test("the map credits each provider whose licence asks for attribution, once (C20)", () => {
  const html = areaAttribution(ui);
  assert.equal((html.match(/Zillow Group/g) ?? []).length, 1);
  assert.match(html, /Freddie Mac/);
  // The basemap source credits OpenStreetMap itself.
  assert.doesNotMatch(html, /OpenStreetMap/);
  assert.doesNotMatch(html, /Census|Defense Travel/);
});
