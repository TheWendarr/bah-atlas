// C21: the About page in a real browser. Run after `node build.mjs --dev`, or set SITE_URL
// to test the deployed site.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { serve } from "../serve.mjs";

const DIST = fileURLToPath(new URL("../../dist", import.meta.url));
const UI = JSON.parse(readFileSync(new URL("../../../delivery/2026/ui_metadata_2026.json", import.meta.url), "utf8"));
// D33: on the live site, Cloudflare's blocked inline script is the one error forgiven.
const LIVE = Boolean(process.env.SITE_URL);
const BLOCKED_INLINE_SCRIPT = /^Executing inline script violates/;
const WEBGL = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];

let browser;
let site;
let origin;

before(async () => {
  if (LIVE) origin = process.env.SITE_URL;
  else {
    site = await serve(DIST);
    origin = site.origin;
  }
  browser = await chromium.launch({ args: WEBGL });
});

after(async () => {
  await browser.close();
  site?.server.close();
});

async function about(context = {}, route = null) {
  const page = await browser.newPage(context);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    if (LIVE && BLOCKED_INLINE_SCRIPT.test(message.text())) return;
    if (route && /404|Failed to load resource/.test(message.text())) return;
    errors.push(message.text());
  });
  if (route) await page.route(route.pattern, route.handler);
  await page.goto(`${origin}/about.html`);
  await page.waitForFunction(() => document.documentElement.dataset.state, null, { timeout: 30_000 });
  return { page, errors };
}

const text = (page, selector) => page.textContent(selector);

test("the About page loads without errors and shows every B21 global caveat (C21, must 7)", async () => {
  const { page, errors } = await about();
  assert.equal(await page.evaluate(() => document.documentElement.dataset.state), "ready");
  assert.deepEqual(errors, []);
  assert.equal(await page.locator("[data-caveat]").count(), UI.global_caveats.length);
  for (const caveat of UI.global_caveats) {
    const item = page.locator(`[data-caveat="${caveat.id}"]`);
    assert.equal(await item.isVisible(), true, caveat.id);
    assert.equal(await item.locator("h3").textContent(), caveat.title);
    assert.equal(await item.locator("p").textContent(), caveat.text);
  }
  await page.close();
});

test("the H1 and H2 results equal B21's findings (C21)", async () => {
  const { page } = await about();
  const { h1, h2 } = UI.findings;
  const h1Text = await text(page, '[data-render="h1"]');
  for (const value of [h1.n, h1.moran_i, h1.fdr_significant]) assert.ok(h1Text.includes(String(value)), String(value));
  for (const [id, count] of Object.entries(h1.clusters)) {
    const row = page.locator(`[data-cluster="${id}"]`);
    assert.equal(await row.locator("th").textContent(), UI.clusters.classes[id].label);
    assert.equal(await row.locator("td").textContent(), String(count));
  }
  const model = await text(page, '[data-render="h2-model"]');
  for (const value of [h2.n, h2.eligible, h2.ols_r2]) assert.ok(model.includes(String(value)), String(value));
  for (const predictor of h2.predictors) {
    const row = page.locator(`[data-predictor="${predictor.id}"]`);
    assert.equal(await row.locator("th code").textContent(), predictor.id);
    assert.equal(await row.locator("td.coef").textContent(), String(predictor.b));
    assert.ok((await row.locator("td.reading").textContent()).startsWith(predictor.reading), predictor.id);
  }
  await page.close();
});

test("the three results the plan requires are stated plainly (C21)", async () => {
  const { page } = await about();
  // 1. The O-3 verdict depends on the benchmark: both profiles' rows, with their labels.
  for (const profile of UI.profiles) {
    assert.equal(await text(page, `tr[data-profile="${profile.id}"] th`), profile.label);
  }
  assert.equal(await page.isVisible('[data-required="benchmark"]'), true);
  // 2. Part of the ln_rent coefficient is mechanical (the shared denominator).
  assert.match(await text(page, '[data-required="shared-denominator"]'), /mechanical/);
  // 3. The rent-growth reading changes with model form, from B21.
  const growth = UI.findings.h2.predictors.find((predictor) => predictor.id === "rent_growth_pct");
  assert.equal(growth.model_form_agrees, false);
  assert.match(await text(page, '[data-predictor="rent_growth_pct"] td.reading'), /depends on model form/);
  assert.equal(await page.isVisible('[data-required="sample-selection"]'), true);
  await page.close();
});

test("the About page fits a phone with no sideways scroll (X10)", async () => {
  const { page } = await about({ viewport: { width: 360, height: 640 } });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), 0);
  await page.close();
});

test("an empty prose slot is hidden, and so is a section with nothing else in it", async () => {
  const { page } = await about();
  const slots = await page.evaluate(() =>
    [...document.querySelectorAll(".prose")].map((slot) => ({
      id: slot.dataset.prose,
      written: slot.textContent.trim() !== "",
      hidden: slot.hidden,
      sectionHidden: slot.closest("section").hidden,
      sectionHasData: [...slot.closest("section").children].some((child) => !/^H[1-6]$/.test(child.tagName) && !child.classList.contains("prose")),
    })),
  );
  for (const slot of slots) {
    assert.equal(slot.hidden, !slot.written, slot.id);
    if (!slot.written && !slot.sectionHasData) assert.equal(slot.sectionHidden, true, slot.id);
  }
  // The results always show, written or not.
  assert.equal(await page.isVisible("#results"), true);
  await page.close();
});

// Reports, without failing, which prose slots the author has still to write.
test("every prose slot is written", { todo: "the author writes the C21 prose" }, async () => {
  const { page } = await about();
  const empty = await page.evaluate(() => [...document.querySelectorAll(".prose")].filter((slot) => slot.hidden).map((slot) => slot.dataset.prose));
  await page.close();
  assert.deepEqual(empty, []);
});

test("if B21 cannot be loaded the page says so and shows no results tables", async () => {
  const { page } = await about({}, { pattern: "**/ui_metadata_2026.json", handler: (route) => route.fulfill({ status: 404, body: "" }) });
  assert.equal(await page.evaluate(() => document.documentElement.dataset.state), "error");
  assert.equal(await page.isVisible("#about-error"), true);
  assert.equal(await page.isVisible('[data-render="h1"]'), false);
  await page.close();
});

test("the map's footer links to the About page (C21)", async () => {
  const page = await browser.newPage();
  await page.goto(origin);
  await page.waitForFunction(() => document.documentElement.dataset.state === "ready", null, { timeout: 60_000 });
  await page.getByRole("link", { name: "About this map" }).click();
  await page.waitForFunction(() => document.documentElement.dataset.state === "ready", null, { timeout: 30_000 });
  assert.match(page.url(), /about(\.html)?$/);
  await page.getByRole("link", { name: "Back to the map" }).click();
  await page.waitForURL((url) => !/about/.test(url.pathname));
  await page.close();
});
