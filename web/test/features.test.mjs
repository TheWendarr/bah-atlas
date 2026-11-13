// C15, C16, C17, C19: ZIP search, the cluster overlay, the permalink and the CSV export,
// on the delivered files. Pure functions only; the browser tests cover the page.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { areaBounds } from "../tools/area_bounds.mjs";
import { COLUMNS, textCell, toCsv, viewRows } from "../src/export.js";
import { gridView } from "../src/grid.js";
import { fitsOnMap } from "../src/locate.js";
import { fromHash, stateFromHash, toHash } from "../src/permalink.js";
import { computeView } from "../src/render.js";
import { NO_VALUE, OUT_OF_SCOPE, clusterIndex, researchProfile } from "../src/research.js";
import { checkZipFile, findZip, normalizeZip, zipIndex } from "../src/search.js";
import { initialState, validate } from "../src/state.js";

const DELIVERY = new URL("../../delivery/2026/", import.meta.url);
const read = (name) => JSON.parse(readFileSync(new URL(name, DELIVERY), "utf8"));
const files = {
  ui: read("ui_metadata_2026.json"),
  grid: read("grid_2026.json"),
  payload: read("payload_2026.json"),
  hotspots: read("hotspots_2026.json"),
};
const zips = read("zips_2026.json");
const { ui } = files;
const defaults = initialState(ui);

// C17 ------------------------------------------------------------------------------------

test("a link round-trips every field of the state (C17)", () => {
  const state = { ...defaults, rank: "O3", homeType: "sfh3", mode: "buy", metric: "surplus_usd", selected: "CO046", compare: ["NC182", "AK400"], overlay: true };
  assert.deepEqual(validate(ui, stateFromHash(defaults, toHash(state))).state, state);
});

test("the default view writes the selection only (C17)", () => {
  assert.equal(toHash(defaults), "#rank=E5&dep=with&home=standard&mode=rent&show=adequacy_ratio");
});

test("a link with bad or missing values falls back field by field (C17)", () => {
  const { state, corrected } = validate(ui, stateFromHash(defaults, "#rank=E10&home=th3&area=ZZ000&compare=CO046,QQ1,CO046&clusters=on&junk=1&=x&mode"));
  assert.equal(state.rank, defaults.rank);
  assert.equal(state.homeType, "th3");
  assert.equal(state.selected, null);
  assert.deepEqual(state.compare, ["CO046"]);
  assert.equal(state.overlay, true);
  assert.deepEqual(corrected.sort(), ["compare", "rank", "selected"]);
});

test("a hash that is not valid percent-encoding is ignored, not thrown (C17)", () => {
  assert.deepEqual(fromHash("#rank=%E0%A4%A&dep=without"), { dependents: "without" });
  assert.deepEqual(fromHash(""), {});
  assert.deepEqual(fromHash("#"), {});
});

// C16 ------------------------------------------------------------------------------------

test("the research view is exactly E-5 or O-3 with dependents at the statutory standard (C16, must 9)", () => {
  const found = [];
  for (const { id: rank } of ui.grid.ranks) {
    for (const { id: dependents } of ui.grid.dependents) {
      for (const { id: homeType } of ui.grid.home_types) {
        const state = { ...defaults, rank, dependents, homeType };
        const { research, standardView } = computeView(files, state);
        if (research) found.push(`${rank} ${dependents} ${homeType}`);
        assert.equal(research, researchProfile(ui, state, standardView));
      }
    }
  }
  // E-5's anchor is the 2 BR townhouse; O-3's standard is a blend, so it has no anchor type.
  assert.deepEqual(found, ["E5 with standard", "E5 with th2", "O3 with standard"]);
});

test("the overlay shows only when asked for and only on a research view (C16)", () => {
  assert.equal(computeView(files, defaults).overlay, false);
  assert.equal(computeView(files, { ...defaults, overlay: true }).overlay, true);
  assert.equal(computeView(files, { ...defaults, overlay: true, rank: "E1" }).overlay, false);
  assert.equal(computeView(files, { ...defaults, overlay: true, dependents: "without" }).overlay, false);
  assert.equal(computeView(files, { ...defaults, overlay: true, rank: "O3", homeType: "sfh4" }).overlay, false);
});

test("every area's overlay class equals B27, and no area outside cluster_scope has one (C16, must not 3)", () => {
  const order = Object.keys(ui.clusters.classes);
  for (const [rank, profile] of [["E5", "e5_dep"], ["O3", "o3_dep"]]) {
    for (const { id: mode } of ui.modes) {
      const { clusters } = computeView(files, { ...defaults, rank, mode, overlay: true });
      assert.equal(clusters.size, Object.keys(files.grid.areas).length);
      for (const [code, { index, fdr }] of clusters) {
        const label = `${profile} ${mode} ${code}`;
        if (!files.payload.areas[code].cluster_scope) {
          assert.equal(index, OUT_OF_SCOPE, label);
          assert.equal(fdr, false, label);
          continue;
        }
        const entry = files.hotspots.areas[code][profile][mode];
        assert.equal(index, entry.cluster === null ? NO_VALUE : order.indexOf(entry.cluster), label);
        assert.equal(fdr, entry.lisa_fdr_significant === true, label);
      }
    }
  }
});

test("the E-5 rent overlay counts equal the H1 finding in B21 (C16)", () => {
  const { clusters } = computeView(files, { ...defaults, overlay: true });
  const order = Object.keys(ui.clusters.classes);
  const counts = Object.fromEntries(order.map((id) => [id, 0]));
  let fdr = 0;
  for (const { index, fdr: marked } of clusters.values()) {
    if (index >= 0) counts[order[index]] += 1;
    if (marked) fdr += 1;
  }
  assert.deepEqual(counts, ui.findings.h1.clusters);
  assert.equal(fdr, ui.findings.h1.fdr_significant);
});

test("Alaska, Hawaii, County Cost Groups and the territory bucket are outside the overlay (C16)", () => {
  const { clusters } = computeView(files, { ...defaults, overlay: true });
  for (const code of ["AK400", "AK401", "ZZ510", "XX499"]) assert.equal(clusters.get(code).index, OUT_OF_SCOPE, code);
  const hawaii = Object.keys(ui.areas).filter((code) => code.startsWith("HI"));
  assert.ok(hawaii.length > 0);
  for (const code of hawaii) assert.equal(clusters.get(code).index, OUT_OF_SCOPE, code);
});

test("an untested area in the analysis has no cluster class (C16)", () => {
  assert.equal(clusterIndex(ui, null), OUT_OF_SCOPE);
  assert.equal(clusterIndex(ui, { cluster: null }), NO_VALUE);
  assert.equal(clusterIndex(ui, { cluster: "HH" }), 0);
});

// C15 ------------------------------------------------------------------------------------

test("ZIP input accepts five digits or ZIP+4, nothing else (C15)", () => {
  assert.equal(normalizeZip("80913"), "80913");
  assert.equal(normalizeZip(" 80913-1234 "), "80913");
  for (const text of ["8091", "809133", "abcde", "", "80913-12"]) assert.equal(normalizeZip(text), null, text);
});

test("every delivered ZIP finds its area: an MHA, a County Cost Group, the territory bucket (C15)", () => {
  const index = zipIndex(zips);
  let count = 0;
  for (const [code, list] of Object.entries(zips.areas)) {
    for (const zip of list) {
      assert.equal(index.get(zip), code);
      count += 1;
    }
  }
  assert.equal(index.size, count);
  assert.equal(count, 40_959);
  for (const [zip, code] of [["80913", "CO046"], ["23938", "ZZ510"], ["00601", "XX499"]]) {
    const found = findZip(index, ui, zip);
    assert.equal(found.code, code, zip);
    assert.ok(found.message.includes(ui.areas[code].display_name ?? ui.areas[code].name), zip);
  }
});

test("an unknown ZIP and a malformed one say so and select nothing (C15)", () => {
  const index = zipIndex(zips);
  const unknown = findZip(index, ui, "00000");
  assert.equal(unknown.code, null);
  assert.match(unknown.message, /00000 is not in the 2026 BAH ZIP list/);
  assert.equal(findZip(index, ui, "12").code, undefined);
});

test("the ZIP list must come from the map's build and a known major version (C15, must 6)", () => {
  assert.deepEqual(checkZipFile(zips, ui.build_id), []);
  assert.equal(checkZipFile({ ...zips, build_id: "0".repeat(64) }, ui.build_id).length, 1);
  assert.equal(checkZipFile({ ...zips, schema_version: "2.0.0" }, ui.build_id).length, 1);
});

test("every area has a bounding box from the tiles, and only the territory bucket is too wide to fit (C15, C17)", async () => {
  const boxes = await areaBounds(new URL("areas_2026.pmtiles", DELIVERY).pathname);
  assert.deepEqual(Object.keys(boxes).sort(), Object.keys(files.payload.areas).sort());
  for (const [code, [w, s, e, n]] of Object.entries(boxes)) {
    assert.ok(w < e && s < n && w >= -180 && e <= 180 && s >= -90 && n <= 90, code);
    assert.equal(fitsOnMap(boxes[code]), code !== "XX499", code);
  }
  // Colorado Springs lies around 104.8 W, 38.8 N.
  const [w, s, e, n] = boxes.CO046;
  assert.ok(w < -104.8 && e > -104.8 && s < 38.8 && n > 38.8);
});

// C19 ------------------------------------------------------------------------------------

test("the CSV has one row per area and every value equals gridView (C19)", () => {
  for (const state of [defaults, { ...defaults, rank: "E1", homeType: "sfh4", mode: "buy" }]) {
    const rows = viewRows(files, state);
    assert.equal(rows.length, 339);
    for (const row of rows) {
      const view = gridView(files.grid, row.code, state.rank, state.dependents, state.homeType, state.mode);
      for (const field of ["status", "bah_monthly", "cost_share_monthly", "cost_monthly", "own_housing_monthly", ...ui.grid.metrics]) {
        assert.equal(row[field], view[field], `${row.code} ${field}`);
      }
      assert.equal(row.standard_view, view.standard_view);
      assert.equal(row.caveats, view.caveats.join(";"));
    }
  }
});

test("the CSV parses back to the same rows (C19)", () => {
  const text = toCsv(files, defaults);
  assert.ok(text.endsWith("\r\n"));
  const lines = text.trimEnd().split("\r\n");
  assert.equal(lines[0], COLUMNS.join(","));
  assert.equal(lines.length, 340);
  // A minimal RFC 4180 reader: quoted fields may hold commas.
  const parse = (line) => [...line.matchAll(/("(?:[^"]|"")*"|[^,]*)(,|$)/g)].slice(0, COLUMNS.length).map(([, field]) =>
    field.startsWith('"') ? field.slice(1, -1).replaceAll('""', '"') : field);
  const rows = viewRows(files, defaults);
  lines.slice(1).forEach((line, i) => {
    const cells = parse(line);
    assert.equal(cells.length, COLUMNS.length, line);
    assert.equal(cells[0], rows[i].code);
    assert.equal(cells[1], rows[i].name);
    const gap = cells[COLUMNS.indexOf("design_gap_usd")];
    assert.equal(gap === "" ? null : Number(gap), rows[i].design_gap_usd);
  });
});

test("a text cell that a spreadsheet would run as a formula is written as text (C19)", () => {
  for (const text of ["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"]) assert.ok(textCell(text).replace(/^"/, "").startsWith("'"), JSON.stringify(text));
  assert.equal(textCell("KETCHIKAN, AK"), '"KETCHIKAN, AK"');
  assert.equal(textCell('say "hi"'), '"say ""hi"""');
  assert.equal(textCell("plain"), "plain");
  // Negative numbers stay numbers: the gap column is not a text cell.
  const row = toCsv(files, defaults).split("\r\n").find((line) => line.startsWith("NC182,"));
  assert.match(row, /,-\d+,/);
});
