// X2, X3: the class rule and the contract gate.

import assert from "node:assert/strict";
import test from "node:test";
import { NO_CLASS, classIndex } from "../src/classify.js";
import { checkContract } from "../src/contract.js";

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
