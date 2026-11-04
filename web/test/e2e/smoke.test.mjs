// The built site in a real browser. Run after `node build.mjs --dev`, or set SITE_URL
// to test a deployed site, where the tiles come from the real host.

import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { serve } from "../serve.mjs";

const DIST = fileURLToPath(new URL("../../dist", import.meta.url));
// D33: Bot Fight Mode adds an inline script to the live page, and the site's policy blocks
// it. Only a live run forgives that one error; make site-check has already shown that the
// script is the only change to the page, and a local run allows no inline script at all.
const LIVE = Boolean(process.env.SITE_URL);
const BLOCKED_INLINE_SCRIPT = /^Executing inline script violates/;
const WEBGL = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];

let browser;
let site;
let origin;

before(async () => {
  if (LIVE) {
    origin = process.env.SITE_URL;
  } else {
    site = await serve(DIST);
    origin = site.origin;
  }
  browser = await chromium.launch({ args: WEBGL });
});

after(async () => {
  await browser.close();
  site?.server.close();
});

async function open(context = {}, change = null) {
  const page = await browser.newPage(context);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    if (LIVE && BLOCKED_INLINE_SCRIPT.test(message.text())) return;
    errors.push(message.text());
  });
  if (change) {
    await page.route("**/grid_2026.json", async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: change(await response.json()) });
    });
  }
  await page.goto(origin);
  await page.waitForFunction(() => document.documentElement.dataset.state, null, { timeout: 60_000 });
  return { page, errors };
}

const state = (page) => page.evaluate(() => document.documentElement.dataset.state);

test("the default view renders with no errors or CSP violations", async () => {
  const { page, errors } = await open();
  assert.equal(await state(page), "ready");
  assert.deepEqual(errors, []);
  await page.close();
});

test("feature-state carries the class computed for each area", async () => {
  const { page } = await open();
  // E-5 with dependents, rent, adequacy: Colorado Springs is 1.1486, class 5; Fort Bragg
  // 0.9213, class 2; a County Cost Group has no value.
  const classes = await page.evaluate(() => ["CO046", "NC182", "ZZ580"].map((code) => window.bahAtlas.featureState(code).class));
  assert.deepEqual(classes, [5, 2, -1]);
  await page.close();
});

test("the area fills draw below water, boundaries and labels", async () => {
  const { page } = await open();
  const order = await page.evaluate(() => window.bahAtlas.layerOrder());
  assert.ok(order.indexOf("earth") < order.indexOf("area-fill"));
  assert.ok(order.indexOf("mha-outline") < order.indexOf("water"));
  assert.ok(order.indexOf("water") < order.indexOf("boundaries"));
  assert.ok(order.indexOf("boundaries") < order.indexOf("places_locality"));
  await page.close();
});

test("the live basemap draws and is credited", { skip: !LIVE }, async () => {
  const { page } = await open();
  assert.ok((await page.evaluate(() => window.bahAtlas.basemapFeatures("water"))) > 0);
  assert.match(await page.evaluate(() => window.bahAtlas.attribution()), /OpenStreetMap/);
  await page.close();
});

test("the map fits a phone with no horizontal scroll", async () => {
  const { page } = await open({ viewport: { width: 360, height: 640 } });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert.equal(overflow, 0);
  await page.close();
});

test("a mismatched build id shows the error screen and no map", async () => {
  const { page } = await open({}, (grid) => ({ ...grid, build_id: "0".repeat(64) }));
  assert.equal(await state(page), "error");
  assert.equal(await page.isVisible("#map"), false);
  assert.match(await page.textContent("#error-detail"), /one build id/);
  await page.close();
});

test("an unknown major version shows the error screen and no map", async () => {
  const { page } = await open({}, (grid) => ({ ...grid, schema_version: "2.0.0" }));
  assert.equal(await state(page), "error");
  assert.equal(await page.isVisible("#map"), false);
  await page.close();
});
