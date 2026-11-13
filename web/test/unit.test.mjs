// X2, X3: the class rule and the contract gate.

import assert from "node:assert/strict";
import test from "node:test";
import { NO_CLASS, classIndex } from "../src/classify.js";
import { checkContract, checkManifest, sha256Hex } from "../src/contract.js";
import { formatMetric, percent, usd } from "../src/format.js";

const BREAKS = [-500, -250, -50, 50, 250, 500];

test("a value equal to a break falls in the class above", () => {
  BREAKS.forEach((limit, index) => assert.equal(classIndex(limit, BREAKS), index + 1));
});

test("values below the first break and above the last take the end classes", () => {
  assert.equal(classIndex(-501, BREAKS), 0);
  assert.equal(classIndex(501, BREAKS), BREAKS.length);
});

test("null has no class", () => {
  assert.equal(classIndex(null, BREAKS), NO_CLASS);
});

test("B23's two rounding cases classify on the rounded value", () => {
  // FL057 E-5 and NJ200 O-3 rent surplus_usd: 49.92 and 49.89, both rounded to 50.
  assert.equal(classIndex(50, BREAKS), 4);
});

test("a percent rounds a tie half away from zero, as the contract rounds", () => {
  // Each of these is a tie at one decimal of a percent. toFixed on value * 100 sent the
  // first three down, to 226.5%, 622.9% and 110.1%.
  assert.equal(percent(2.2655), "226.6%");
  assert.equal(percent(6.2295), "623.0%");
  assert.equal(percent(1.1015), "110.2%");
  assert.equal(percent(0.9695), "97.0%");
  assert.equal(percent(1.0465), "104.7%");
});

test("a percent away from a tie, a whole ratio and a missing value read as before", () => {
  assert.equal(percent(0.9694), "96.9%");
  assert.equal(percent(1.1486), "114.9%");
  assert.equal(percent(1), "100.0%");
  assert.equal(percent(0), "0.0%");
  assert.equal(percent(null), "—");
  assert.equal(formatMetric(0.9213, "percent"), "92.1%");
});

test("a negative percent takes the same minus sign as a dollar value, and never reads -0.0%", () => {
  assert.equal(percent(-0.0155), "−1.6%");
  assert.equal(percent(-0.00004), "0.0%");
  assert.equal(usd(-50), "−$50");
});

const files = (overrides = {}) => ({
  payload: { schema_version: "1.1.0", build_id: "aaaa" },
  ui: { schema_version: "1.1.0", build_id: "aaaa" },
  hotspots: { schema_version: "1.1.0", build_id: "aaaa" },
  grid: { schema_version: "1.1.0", build_id: "aaaa", ...overrides },
});

test("matching files pass", () => {
  assert.deepEqual(checkContract(files()), []);
});

test("a minor version step passes", () => {
  assert.deepEqual(checkContract(files({ schema_version: "1.2.0" })), []);
});

test("a different build id is refused", () => {
  assert.match(checkContract(files({ build_id: "bbbb" })).join(), /one build id/);
});

test("another major version is refused", () => {
  assert.match(checkContract(files({ schema_version: "2.0.0" })).join(), /schema_version 2\.0\.0/);
});

// C20: B22's own hash is the build id (ICD section 8).
const manifest = (overrides = {}) => ({ name: "build_manifest_2026.json", sha256: "aaaa", content: { schema_version: "1.2.1" }, ...overrides });

test("the build manifest whose hash is the build id passes", () => {
  assert.deepEqual(checkManifest(manifest(), "aaaa"), []);
});

test("a build manifest from another build is refused", () => {
  assert.match(checkManifest(manifest({ sha256: "bbbb" }), "aaaa").join(), /SHA-256 begins bbbb/);
});

test("a build manifest of another major version is refused", () => {
  assert.match(checkManifest(manifest({ content: { schema_version: "2.0.0" } }), "aaaa").join(), /schema_version 2\.0\.0/);
});

test("the delivered build manifest hashes to the delivered build id", async () => {
  const { readFileSync } = await import("node:fs");
  const read = (name) => readFileSync(new URL(`../../delivery/2026/${name}`, import.meta.url));
  const ui = JSON.parse(read("ui_metadata_2026.json"));
  assert.equal(await sha256Hex(read("build_manifest_2026.json")), ui.build_id);
});
