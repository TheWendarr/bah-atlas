// X7 (ICD 9, must not 2): no colours, breaks, labels, status or caveat texts from B21 are
// written into the site's own source. They must reach the page from ui_metadata only, so
// a new delivery changes them without a code change.

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import test from "node:test";

const WEB = new URL("../", import.meta.url);
const ui = JSON.parse(readFileSync(new URL("../delivery/2026/ui_metadata_2026.json", WEB), "utf8"));

const sources = [
  ...readdirSync(new URL("src/", WEB)).map((name) => `src/${name}`),
  "index.html",
  "about.html",
].map((path) => ({ path, text: readFileSync(new URL(path, WEB), "utf8") }));

// Every string in B21 a reader sees, gathered from the fields that hold them. Short strings
// ("Rent", "100%") are left out: they are ordinary words, and a match would mean nothing.
function texts() {
  const found = new Set();
  const add = (value) => {
    if (typeof value === "string" && value.length >= 12) found.add(value);
  };
  for (const metric of Object.values(ui.metrics)) {
    for (const scale of [metric, metric.off_standard].filter(Boolean)) {
      add(scale.label);
      add(scale.short_label);
      scale.class_labels?.forEach(add);
    }
  }
  for (const { label, text } of Object.values(ui.statuses)) [label, text].forEach(add);
  for (const { title, text } of Object.values(ui.caveats)) [title, text].forEach(add);
  ui.global_caveats?.forEach((item) => (typeof item === "string" ? add(item) : Object.values(item).forEach(add)));
  for (const source of ui.sources) Object.values(source).forEach(add);
  add(ui.no_data_label);
  add(ui.clusters.legend_title);
  add(ui.clusters.out_of_scope_label);
  add(ui.clusters.fdr_marker.label);
  for (const { label } of Object.values(ui.clusters.classes)) add(label);
  Object.values(ui.grid.notice).forEach(add);
  Object.values(ui.grid.off_standard_scale).forEach(add);
  for (const byDependents of Object.values(ui.grid.standards_text)) Object.values(byDependents).forEach(add);
  return [...found];
}

function colours() {
  const found = new Set([ui.no_data_color, ui.clusters.fdr_marker.outline_color]);
  for (const metric of Object.values(ui.metrics)) metric.colors?.forEach((c) => found.add(c));
  for (const { color } of Object.values(ui.clusters.classes)) found.add(color);
  return [...found].map((c) => c.toLowerCase());
}

// Two neighbouring breaks written as a list, as they would be in a hard-coded scale.
function breakPairs() {
  const pairs = [];
  for (const metric of Object.values(ui.metrics)) {
    for (const scale of [metric, metric.off_standard].filter(Boolean)) {
      const breaks = scale.breaks ?? [];
      for (let i = 1; i < breaks.length; i++) pairs.push(new RegExp(`(^|[^\\d.])${breaks[i - 1]}\\s*,\\s*${breaks[i]}([^\\d.]|$)`));
    }
  }
  return pairs;
}

test("no B21 text is written into web/src or the pages (X7)", () => {
  const list = texts();
  assert.ok(list.length > 50, `only ${list.length} texts gathered`);
  for (const { path, text } of sources) {
    for (const value of list) assert.ok(!text.includes(value), `${path} holds B21 text: ${value.slice(0, 60)}`);
  }
});

test("no B21 colour is written into web/src or the pages (X7)", () => {
  const list = colours();
  assert.ok(list.length >= 10);
  for (const { path, text } of sources) {
    const lower = text.toLowerCase();
    for (const colour of list) assert.ok(!new RegExp(`${colour}(?![0-9a-f])`).test(lower), `${path} holds B21 colour ${colour}`);
  }
});

test("no B21 class breaks are written into web/src or the pages (X7)", () => {
  const pairs = breakPairs();
  assert.ok(pairs.length > 20);
  for (const { path, text } of sources) {
    for (const pair of pairs) assert.ok(!pair.test(text), `${path} holds breaks ${pair}`);
  }
});
