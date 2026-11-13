// C26, C27, C28 in a real browser: the "Show by: ZIP code" view (D36). Run after
// `node build.mjs --dev`, or set SITE_URL to test a deployed site.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { classIndex, scaleFor } from "../../src/classify.js";
import { toCsv } from "../../src/export.js";
import { percent } from "../../src/format.js";
import { zipView } from "../../src/grid.js";
import { serve } from "../serve.mjs";

const DIST = fileURLToPath(new URL("../../dist", import.meta.url));
const delivered = (name) => JSON.parse(readFileSync(new URL(`../../../delivery/2026/${name}`, import.meta.url), "utf8"));
const UI = delivered("ui_metadata_2026.json");
const GRID = delivered("grid_2026.json");
const ZIPGRID = delivered("zipgrid_2026.json");
const LIVE = Boolean(process.env.SITE_URL);
const BLOCKED_INLINE_SCRIPT = /^Executing inline script violates/;
const WEBGL = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];
const BASE = "#rank=E5&dep=with&home=standard&mode=rent&show=adequacy_ratio";
const SPRINGS = [-104.8, 38.85];

// A Colorado Springs (CO046) ZIP code with a rent value for every home type.
const ZIP = Object.keys(ZIPGRID.zips).find(
  (zip) => ZIPGRID.zips[zip].area === "CO046" && ZIPGRID.zips[zip].rent.status.every((s) => s === "ok"),
);

let browser;
let site;
let origin;

before(async () => {
  if (LIVE) origin = process.env.SITE_URL.replace(/\/$/, "");
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

async function open(hash = "", context = {}, prepare = null) {
  const page = await browser.newPage(context);
  const errors = [];
  const requests = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    if (LIVE && BLOCKED_INLINE_SCRIPT.test(message.text())) return;
    errors.push(message.text());
  });
  page.on("request", (request) => requests.push(request.url()));
  if (prepare) await prepare(page);
  await page.goto(`${origin}/${hash}`);
  await page.waitForFunction(() => document.documentElement.dataset.state, null, { timeout: 60_000 });
  return { page, errors, requests };
}

const stateOf = (page) => page.evaluate(() => window.bahAtlas.state());
const zipReady = (page) =>
  page.waitForFunction(() => ["ready", "failed"].includes(document.documentElement.dataset.zip), null, { timeout: 30_000 });
const settle = (page) => page.waitForFunction(() => window.bahAtlas.idle(), null, { timeout: 30_000 });

async function zoomToSprings(page, zoom = 9) {
  await page.evaluate(([center, z]) => window.bahAtlas.zoomTo(center, z), [SPRINGS, zoom]);
  await settle(page);
}

test("the first load fetches no ZIP data; choosing ZIP code loads it and says to zoom in (C26, C27)", async () => {
  const { page, errors, requests } = await open(BASE);
  await settle(page);
  assert.ok(!requests.some((url) => /zipgrid_|zipcodes_/.test(url)), "ZIP files fetched before the ZIP view was chosen");
  await page.selectOption("#geography", "zip");
  await zipReady(page);
  assert.equal(await page.evaluate(() => document.documentElement.dataset.zip), "ready");
  assert.match(await page.evaluate(() => location.hash), /&geo=zip$/);
  assert.equal(await page.isVisible("#zip-hint"), true);
  assert.match(await page.textContent("#zip-hint"), /Zoom in/);
  await zoomToSprings(page);
  assert.equal(await page.isVisible("#zip-hint"), false);
  assert.equal(await page.evaluate(() => window.bahAtlas.zipLayerShown()), true);
  assert.ok((await page.evaluate(() => window.bahAtlas.renderedZips())) > 10);
  assert.deepEqual(errors, []);
  await page.close();
});

test("each ZIP code's feature-state holds the class of its zipView (C27)", async () => {
  const { page } = await open(`${BASE}&geo=zip`);
  await zipReady(page);
  const scale = scaleFor(UI.metrics.adequacy_ratio, true);
  const sample = Object.keys(ZIPGRID.zips).filter((_, i) => i % 211 === 0).concat(ZIP);
  const states = await page.evaluate((zips) => zips.map((zip) => [window.bahAtlas.zipFeatureState(zip).class, window.bahAtlas.zipClassOf(zip)]), sample);
  sample.forEach((zip, i) => {
    const view = zipView(GRID, ZIPGRID, zip, "E5", "with", "standard", "rent");
    const expected = classIndex(view.adequacy_ratio, scale.breaks);
    assert.deepEqual(states[i], [expected, expected], zip);
  });
  // A rank change recolours the ZIP codes from the same formula.
  await page.selectOption("#rank", "O3");
  const after = await page.evaluate((zip) => window.bahAtlas.zipClassOf(zip), ZIP);
  assert.equal(after, classIndex(zipView(GRID, ZIPGRID, ZIP, "O3", "with", "standard", "rent").adequacy_ratio, scale.breaks));
  await page.close();
});

test("a link to a ZIP code opens its panel beside its MHA's figure, with the BAH note open (C17, C28)", async () => {
  const { page, errors } = await open(`${BASE}&geo=zip&area=${ZIP}`);
  await zipReady(page);
  await page.waitForSelector("#panel-title");
  assert.equal(await page.textContent("#panel-title"), `ZIP ${ZIP}`);
  assert.match(await page.textContent(".panel-area"), /COLORADO SPRINGS, CO/);
  const view = zipView(GRID, ZIPGRID, ZIP, "E5", "with", "standard", "rent");
  assert.equal(await page.textContent(".panel-detail > .panel-table tbody tr.chosen td.current"), percent(view.adequacy_ratio));
  assert.equal(await page.locator(".panel-area-table td[data-field=area-metric]").count(), 2);
  assert.equal(await page.locator(".panel-caveats[open] [data-caveat=zip_bah_constant]").count(), 1);
  await page.waitForFunction(() => window.bahAtlas.center()[2] > 8, null, { timeout: 10_000 });
  assert.deepEqual(await page.evaluate((zip) => window.bahAtlas.zipFeatureState(zip).selected, ZIP), true);
  assert.deepEqual(errors, []);
  await page.close();
});

test("clicking a ZIP code opens it; returning to MHAs opens its MHA (C26, C27)", async () => {
  const { page } = await open(`${BASE}&geo=zip`);
  await zipReady(page);
  await zoomToSprings(page, 10);
  const point = await page.evaluate((center) => window.bahAtlas.pointOf(center), SPRINGS);
  await page.mouse.click(point[0], point[1] + 50);
  await page.waitForFunction(() => /^\d{5}$/.test(window.bahAtlas.state().selected ?? ""));
  const zip = (await stateOf(page)).selected;
  assert.equal(ZIPGRID.zips[zip].area, "CO046");
  await page.selectOption("#geography", "mha");
  await page.waitForFunction(() => window.bahAtlas.state().geography === "mha");
  assert.equal((await stateOf(page)).selected, "CO046");
  assert.doesNotMatch(await page.evaluate(() => location.hash), /geo=/);
  await page.close();
});

test("ZIP search opens the ZIP code in the ZIP view and its area in the MHA view (C15, C28)", async () => {
  const search = async (page, text) => {
    await page.fill("#zip", text);
    await page.press("#zip", "Enter");
    await page.waitForFunction(() => {
      const t = document.getElementById("zip-result").textContent;
      return t && !t.startsWith("Loading");
    });
  };
  const { page } = await open(`${BASE}&geo=zip`);
  await zipReady(page);
  await search(page, ZIP);
  await page.waitForFunction((zip) => window.bahAtlas.state().selected === zip, ZIP);
  const { page: mha } = await open(BASE);
  await search(mha, ZIP);
  await mha.waitForFunction(() => window.bahAtlas.state().selected === "CO046");
  await page.close();
  await mha.close();
});

test("the ZIP view has no cluster overlay and says why (C16, must 9)", async () => {
  const { page } = await open(`${BASE}&clusters=on&geo=zip`);
  await zipReady(page);
  assert.equal(await page.isDisabled("#overlay"), true);
  assert.match(await page.textContent("#overlay-hint"), /between MHAs/);
  assert.equal(await page.evaluate(() => window.bahAtlas.overlayShown()), false);
  await page.close();
});

test("the CSV download in the ZIP view holds one row per ZIP code, equal to the export (C19, C28)", async () => {
  const { page } = await open(`#rank=E1&dep=without&home=sfh4&mode=buy&show=adequacy_ratio&geo=zip`, { acceptDownloads: true });
  await zipReady(page);
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download this view (CSV)" }).click()]);
  assert.equal(download.suggestedFilename(), "bah-atlas_2026_E1_without_sfh4_buy_zip.csv");
  const chunks = [];
  for await (const chunk of await download.createReadStream()) chunks.push(chunk);
  const state = await stateOf(page);
  assert.equal(Buffer.concat(chunks).toString("utf8"), toCsv({ ui: UI, grid: GRID, zipgrid: ZIPGRID }, state));
  await page.close();
});

test("a ZIP grid from another build is refused and the map stays on MHAs (C27, must 6)", async () => {
  const other = (page) =>
    page.route("**/zipgrid_2026.json", async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), build_id: "0".repeat(64) } });
    });
  const { page } = await open(`${BASE}&geo=zip&area=${ZIP}`, {}, other);
  await zipReady(page);
  assert.equal(await page.evaluate(() => document.documentElement.dataset.zip), "failed");
  assert.match(await page.textContent("#zip-hint"), /different build/);
  await zoomToSprings(page);
  assert.equal(await page.evaluate(() => window.bahAtlas.zipLayerShown()), false);
  assert.equal(await page.evaluate((zip) => window.bahAtlas.zipClassOf(zip), ZIP), undefined);
  await page.close();
});

test("the ZIP view fits a phone, and the selector is in the controls sheet (X10)", async () => {
  const { page } = await open(`${BASE}&geo=zip`, { viewport: { width: 360, height: 640 } });
  await zipReady(page);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert.equal(overflow, 0);
  await page.locator(".controls-chip").click();
  assert.equal(await page.isVisible("#geography"), true);
  assert.equal(await page.getByRole("combobox", { name: UI.grid.titles.geography }).count(), 1);
  await page.close();
});
