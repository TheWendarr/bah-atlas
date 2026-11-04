// X1: the browser formula equals the pipeline's reference for every view, every field.
// `make web-golden` writes the reference file.

import assert from "node:assert/strict";
import { createReadStream, existsSync, readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import test from "node:test";
import { gridView } from "../src/grid.js";

const url = (path) => new URL(path, import.meta.url);
const GOLDEN = url("./.golden/grid.jsonl");
const VIEWS = 339 * 23 * 2 * 7 * 2;

test("every view matches contract.grid_view", async () => {
  assert.ok(existsSync(GOLDEN), "reference file missing: run `make web-golden`");
  const grid = JSON.parse(readFileSync(url("../../delivery/2026/grid_2026.json")));
  let views = 0;
  const lines = createInterface({ input: createReadStream(GOLDEN) });
  for await (const line of lines) {
    const [code, rank, dependents, homeType, mode, expected] = JSON.parse(line);
    const actual = gridView(grid, code, rank, dependents, homeType, mode);
    const label = `${code} ${rank} ${dependents} ${homeType} ${mode}`;
    for (const [field, value] of Object.entries(expected)) {
      if (field === "caveats") assert.deepEqual([...actual.caveats].sort(), [...value].sort(), `${label}: caveats`);
      else assert.equal(actual[field], value, `${label}: ${field}`);
    }
    views += 1;
  }
  assert.equal(views, VIEWS);
});

const tinyGrid = (lower, upper, share) => ({
  ranks: ["E1"],
  home_types: ["a", "b"],
  cost_share_monthly: { with: [0] },
  standards: { with: [{ lower: "a", upper: "b", share }] },
  areas: {
    X: {
      bah: { with: [1000] },
      rent: { cost: [lower, upper], status: ["ok", "ok"], caveats: [["c1"], ["c2"]] },
    },
  },
});

test("a blended cost on an exact tie rounds half away from zero", () => {
  const view = gridView(tinyGrid(600, 626.25, 0.5), "X", "E1", "with", "standard", "rent");
  assert.equal(view.cost_monthly, 613);
  assert.equal(view.design_gap_usd, 387); // 1000 - 613.13 = 386.87
});

test("a small negative gap rounds to 0, not -0", () => {
  const view = gridView(tinyGrid(1000.4, 1000.4, 0), "X", "E1", "with", "a", "rent");
  assert.ok(Object.is(view.design_gap_usd, 0));
});

test("a view with no cost has null metrics and keeps its status", () => {
  const grid = tinyGrid(null, null, 0);
  grid.areas.X.rent.status = ["no_zori", "no_zori"];
  const view = gridView(grid, "X", "E1", "with", "standard", "rent");
  assert.equal(view.status, "no_zori");
  assert.equal(view.adequacy_ratio, null);
  assert.equal(view.bah_monthly, 1000);
});

test("the caveats of a blended view are the union of its home types", () => {
  const view = gridView(tinyGrid(600, 700, 0.5), "X", "E1", "with", "standard", "rent");
  assert.deepEqual(view.caveats, ["c1", "c2"]);
});
