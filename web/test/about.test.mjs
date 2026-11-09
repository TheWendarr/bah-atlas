// C21: every number about.html quotes by hand from an evidence file must equal that file.
// A new delivery that changes one fails here until the page is updated.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const PAGE = readFileSync(new URL("../about.html", import.meta.url), "utf8");
const QA = readFileSync(new URL("../../delivery/2026/qa_2026.md", import.meta.url), "utf8");

// The body of one numbered section of the QA report.
function section(number) {
  const start = QA.search(new RegExp(`^## ${number}\\. `, "m"));
  assert.ok(start >= 0, `qa_2026.md has no section ${number}`);
  const rest = QA.slice(start + 1);
  const end = rest.search(/^## /m);
  return end < 0 ? rest : rest.slice(0, end);
}

// Section 10, one row per profile: | Profile | Bedrooms | MHAs | Median | IQR | rho | ZORI | SAFMR | Same |
function crossCheck() {
  const values = {};
  for (const line of section(10).split("\n")) {
    const cells = line.split("|").slice(1, -1).map((cell) => cell.trim());
    if (cells.length !== 9 || !/_dep$/.test(cells[0])) continue;
    const [profile, , mhas, medianRatio, , , belowZori, belowSafmr, sameVerdict] = cells;
    Object.assign(values, {
      [`${profile}/mhas`]: mhas,
      [`${profile}/median_ratio`]: medianRatio,
      [`${profile}/below_zori`]: belowZori,
      [`${profile}/below_safmr`]: belowSafmr,
      [`${profile}/same_verdict`]: sameVerdict,
    });
  }
  return values;
}

// Section 11, the sample-selection bullet.
function sampleSelection() {
  const match = section(11).match(
    /Sample selection:\*\* (\d+) of (\d+) eligible MHAs modelled; the (\d+) without rent growth have median gap ([\d.]+) \(modelled ([\d.]+)\)/,
  );
  assert.ok(match, "qa_2026.md section 11 has no sample-selection line in the expected form");
  const [, modelled, eligible, unmodelled, unmodelledGap, modelledGap] = match;
  return { modelled, eligible, unmodelled, "unmodelled-gap": unmodelledGap, "modelled-gap": modelledGap };
}

const EVIDENCE = { ...crossCheck(), ...sampleSelection() };

// Every data-evidence="qa_2026.md#key" element and the text it holds.
const quoted = [...PAGE.matchAll(/data-evidence="qa_2026\.md#([^"]+)">([^<]*)</g)].map(([, key, text]) => ({ key, text }));

test("about.html quotes numbers from the QA report", () => {
  assert.ok(quoted.length >= 15, `found ${quoted.length}`);
});

test("every number about.html quotes equals the QA report (C21)", () => {
  for (const { key, text } of quoted) {
    assert.ok(key in EVIDENCE, `about.html quotes ${key}, which this test does not read from qa_2026.md`);
    assert.equal(text.trim(), EVIDENCE[key], key);
  }
});

test("both profiles' cross-check rows are quoted in full", () => {
  const keys = new Set(quoted.map(({ key }) => key));
  for (const key of Object.keys(crossCheck())) assert.ok(keys.has(key), key);
});

test("the statements the page makes still stand in the QA report", () => {
  // The shared denominator (section 11) and the SAFMR percentile (section 10).
  assert.match(section(11), /Shared denominator:\*\* .*part of a negative ln_rent coefficient is mechanical/);
  assert.match(section(10), /40th percentile/);
  // The page links to both sections by their GitHub anchors.
  for (const anchor of ["10-zori-against-safmr-rent-cross-check", "11-statistical-caveats"]) {
    assert.ok(PAGE.includes(`qa_2026.md#${anchor}`), anchor);
  }
  assert.match(QA, /^## 10\. ZORI against SAFMR \(rent cross-check\)$/m);
  assert.match(QA, /^## 11\. Statistical caveats$/m);
});
