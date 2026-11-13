// C15, C16, C17, C19 in a real browser: ZIP search, the cluster overlay, links and the CSV
// export. Run after `node build.mjs --dev`, or set SITE_URL to test a deployed site.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { toCsv } from "../../src/export.js";
import { initialState } from "../../src/state.js";
import { serve } from "../serve.mjs";

const DIST = fileURLToPath(new URL("../../dist", import.meta.url));
const delivered = (name) => JSON.parse(readFileSync(new URL(`../../../delivery/2026/${name}`, import.meta.url), "utf8"));
const UI = delivered("ui_metadata_2026.json");
const HOTSPOTS = delivered("hotspots_2026.json");
const FILES = { ui: UI, grid: delivered("grid_2026.json") };
const LIVE = Boolean(process.env.SITE_URL);
const BLOCKED_INLINE_SCRIPT = /^Executing inline script violates/;
const WEBGL = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];

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
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    if (LIVE && BLOCKED_INLINE_SCRIPT.test(message.text())) return;
    errors.push(message.text());
  });
  if (prepare) await prepare(page);
  await page.goto(`${origin}/${hash}`);
  await page.waitForFunction(() => document.documentElement.dataset.state, null, { timeout: 60_000 });
  return { page, errors };
}

const stateOf = (page) => page.evaluate(() => window.bahAtlas.state());
const hashOf = (page) => page.evaluate(() => location.hash);
const settle = (page) => page.waitForFunction(() => window.bahAtlas.idle(), null, { timeout: 30_000 });
const inBox = ([lng, lat], [w, s, e, n]) => lng > w && lng < e && lat > s && lat < n;

// C17 ------------------------------------------------------------------------------------

test("a link opens the view it names, with the area's panel open and the map on it (C17)", async () => {
  const { page, errors } = await open("#rank=O3&dep=with&home=sfh3&mode=buy&show=surplus_usd&area=CO046&compare=NC182");
  assert.deepEqual(await stateOf(page), {
    ...initialState(UI), rank: "O3", homeType: "sfh3", mode: "buy", metric: "surplus_usd", selected: "CO046", compare: ["NC182"],
  });
  assert.equal(await page.inputValue("#rank"), "O3");
  assert.equal(await page.inputValue("#metric"), "surplus_usd");
  assert.equal(await page.textContent("#panel-title"), "COLORADO SPRINGS, CO");
  await page.waitForFunction(() => window.bahAtlas.center()[2] > 6, null, { timeout: 10_000 });
  await settle(page);
  assert.ok(inBox(await page.evaluate(() => window.bahAtlas.center()), [-105.5, 38.4, -103.6, 39.5]));
  assert.deepEqual(errors, []);
  await page.close();
});

test("a link with values this build does not know falls back, and the address is corrected (C17)", async () => {
  const { page } = await open("#rank=E10&dep=with&home=castle&mode=rent&show=adequacy_ratio&area=ZZ000");
  const state = await stateOf(page);
  assert.equal(state.rank, "E5");
  assert.equal(state.homeType, "standard");
  assert.equal(state.selected, null);
  assert.equal(await hashOf(page), "#rank=E5&dep=with&home=standard&mode=rent&show=adequacy_ratio");
  await page.close();
});

test("the address follows the controls without adding history, and the same address reopens the view (C17)", async () => {
  const { page } = await open();
  const length = await page.evaluate(() => history.length);
  await page.selectOption("#rank", "E7");
  await page.selectOption("#home-type", "apt2");
  await page.getByRole("radio", { name: "Buy (VA loan)" }).check({ force: true });
  await page.evaluate(() => window.bahAtlas.set({ selected: "NC182" }));
  const hash = await hashOf(page);
  assert.equal(hash, "#rank=E7&dep=with&home=apt2&mode=buy&show=adequacy_ratio&area=NC182");
  assert.equal(await page.evaluate(() => history.length), length);
  const state = await stateOf(page);
  const second = await open(hash);
  assert.deepEqual(await stateOf(second.page), state);
  await second.page.close();
  await page.close();
});

test("editing the address changes the view (C17)", async () => {
  const { page } = await open();
  await page.evaluate(() => {
    location.hash = "#rank=W2&dep=without&home=apt1&mode=rent&show=design_gap_usd";
  });
  await page.waitForFunction(() => window.bahAtlas.state().rank === "W2");
  const state = await stateOf(page);
  assert.deepEqual([state.dependents, state.homeType, state.metric], ["without", "apt1", "design_gap_usd"]);
  await page.close();
});

// C16 ------------------------------------------------------------------------------------

test("the cluster switch works only on research views and says which ones (C16, must 9)", async () => {
  const { page } = await open();
  assert.equal(await page.isDisabled("#overlay"), false);
  assert.equal(await page.isVisible("#overlay-hint"), false);
  await page.selectOption("#rank", "E1");
  assert.equal(await page.isDisabled("#overlay"), true);
  assert.match(await page.textContent("#overlay-hint"), /E-5 with dependents and O-3 with dependents/);
  await page.selectOption("#rank", "O3");
  await page.selectOption("#home-type", "sfh4");
  assert.equal(await page.isDisabled("#overlay"), true);
  await page.close();
});

test("the overlay draws B27's clusters, marks FDR areas and leaves non-CONUS areas unfilled (C16, musts 5, 9; must not 3)", async () => {
  const { page, errors } = await open();
  await page.check("#overlay");
  assert.equal(await page.evaluate(() => window.bahAtlas.overlayShown()), true);
  assert.match(await hashOf(page), /&clusters=on$/);
  const order = Object.keys(UI.clusters.classes);
  const tested = Object.keys(HOTSPOTS.areas).filter((code) => HOTSPOTS.areas[code].e5_dep.rent.status === "tested");
  const fdr = tested.filter((code) => HOTSPOTS.areas[code].e5_dep.rent.lisa_fdr_significant);
  const sample = [...new Set([...tested.slice(0, 20), ...fdr])];
  const states = await page.evaluate((codes) => codes.map((code) => window.bahAtlas.featureState(code)), sample);
  sample.forEach((code, i) => {
    const entry = HOTSPOTS.areas[code].e5_dep.rent;
    assert.equal(states[i].cluster, order.indexOf(entry.cluster), code);
    assert.equal(states[i].fdr, entry.lisa_fdr_significant, code);
  });
  assert.ok(fdr.length > 0);
  // Outside the analysis: no cluster, no outline.
  const outside = await page.evaluate(() => ["AK400", "ZZ510", "XX499"].map((code) => window.bahAtlas.featureState(code)));
  for (const s of outside) assert.deepEqual([s.cluster, s.fdr], [-2, false]);
  // The legend is the overlay's, labelled exploratory, with the FDR marker.
  assert.equal(await page.textContent(".legend-title"), UI.clusters.legend_title);
  assert.match(UI.clusters.legend_title, /exploratory/);
  assert.equal(await page.textContent("[data-cluster=fdr]"), UI.clusters.fdr_marker.label);
  assert.equal(await page.locator(".legend-list li").count(), order.length + 2 + (await page.locator("[data-cluster=no_value]").count()));
  assert.deepEqual(errors, []);
  await page.close();
});

test("with the overlay on, a click opens the area with its cluster result and caveats (C16)", async () => {
  const { page } = await open("#rank=E5&dep=with&home=standard&mode=rent&show=adequacy_ratio&clusters=on");
  await settle(page);
  const [x, y] = await page.evaluate(() => window.bahAtlas.pointOf([-104.75, 38.85]));
  const box = await page.locator("#map").boundingBox();
  await page.mouse.click(box.x + x, box.y + y);
  await page.waitForSelector(".panel-cluster");
  const entry = HOTSPOTS.areas.CO046.e5_dep.rent;
  assert.equal(await page.getAttribute(".panel-cluster", "data-cluster"), entry.cluster);
  assert.match(await page.textContent(".panel-cluster"), new RegExp(UI.clusters.classes[entry.cluster].label.replace(/[()]/g, "\\$&")));
  assert.match(await page.textContent(".panel-cluster"), new RegExp(entry.lisa_p_sim.toFixed(5)));
  assert.equal(await page.isVisible(".panel-detail [data-caveat=lisa_exploratory]"), true);
  // An Alaska MHA says it is outside the analysis, with its caveat.
  await page.evaluate(() => window.bahAtlas.set({ selected: "AK400" }));
  assert.equal(await page.getAttribute(".panel-cluster", "data-cluster"), "out_of_scope");
  assert.equal(await page.isVisible(".panel-detail [data-caveat=outside_cluster_scope]"), true);
  await page.close();
});

test("leaving the research view hides the overlay and brings back the metric legend; returning restores it (C16)", async () => {
  const { page } = await open("#rank=E5&dep=with&home=standard&mode=rent&show=adequacy_ratio&clusters=on&area=CO046");
  await page.selectOption("#rank", "E1");
  assert.equal(await page.evaluate(() => window.bahAtlas.overlayShown()), false);
  assert.equal(await page.textContent(".legend-title"), UI.metrics.adequacy_ratio.label);
  assert.equal(await page.locator(".panel-cluster").count(), 0);
  assert.equal(await page.locator(".panel-detail [data-caveat=lisa_exploratory]").count(), 0);
  await page.selectOption("#rank", "E5");
  assert.equal(await page.evaluate(() => window.bahAtlas.overlayShown()), true);
  await page.uncheck("#overlay");
  assert.equal(await page.evaluate(() => window.bahAtlas.overlayShown()), false);
  assert.doesNotMatch(await hashOf(page), /clusters/);
  await page.close();
});

// C15 ------------------------------------------------------------------------------------

async function search(page, text) {
  await page.fill("#zip", text);
  await page.press("#zip", "Enter");
  await page.waitForFunction(() => {
    const text = document.getElementById("zip-result").textContent;
    return text && !text.startsWith("Loading");
  });
  return page.textContent("#zip-result");
}

test("ZIP search finds an MHA, a County Cost Group and the territory bucket, and opens each (C15)", async () => {
  const { page, errors } = await open();
  assert.match(await search(page, "80913"), /80913 is in COLORADO SPRINGS, CO/);
  assert.equal((await stateOf(page)).selected, "CO046");
  assert.equal(await page.textContent("#panel-title"), "COLORADO SPRINGS, CO");
  await page.waitForFunction(() => window.bahAtlas.center()[2] > 6, null, { timeout: 10_000 });
  await settle(page);
  assert.ok(inBox(await page.evaluate(() => window.bahAtlas.center()), [-106, 38, -103, 40]));

  assert.match(await search(page, "23938"), /COUNTY COST GROUP 510/);
  assert.equal((await stateOf(page)).selected, "ZZ510");
  assert.equal(await page.locator(".panel-detail [data-status=ccg_no_benchmark]").count(), 1);

  // The territory bucket spans the Pacific, so the map stays where it is.
  await settle(page);
  const center = await page.evaluate(() => window.bahAtlas.center());
  assert.match(await search(page, "00601"), /00601 is in/);
  assert.equal((await stateOf(page)).selected, "XX499");
  assert.equal(await page.locator(".panel-detail [data-status=no_rate]").count(), 1);
  assert.deepEqual(await page.evaluate(() => window.bahAtlas.center()), center);
  assert.deepEqual(errors, []);
  await page.close();
});

test("an unknown or malformed ZIP says so and changes nothing (C15)", async () => {
  const { page } = await open("#rank=E5&dep=with&home=standard&mode=rent&show=adequacy_ratio&area=NC182");
  assert.match(await search(page, "00000"), /00000 is not in the 2026 BAH ZIP list/);
  assert.equal((await stateOf(page)).selected, "NC182");
  assert.equal(await search(page, "8091"), "Enter a five-digit ZIP code.");
  assert.match(await search(page, "80913-4401"), /80913 is in/);
  await page.close();
});

test("a ZIP list from another build is refused (C15, must 6)", async () => {
  const other = (page) =>
    page.route("**/zips_2026.json", async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), build_id: "0".repeat(64) } });
    });
  const { page } = await open("", {}, other);
  assert.match(await search(page, "80913"), /different build/);
  assert.equal((await stateOf(page)).selected, null);
  await page.close();
});

// C19 ------------------------------------------------------------------------------------

test("the CSV download holds the current view, equal to the export of gridView (C19)", async () => {
  const { page } = await open("#rank=E1&dep=without&home=sfh4&mode=buy&show=adequacy_ratio", { acceptDownloads: true });
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download this view (CSV)" }).click()]);
  assert.equal(download.suggestedFilename(), "bah-atlas_2026_E1_without_sfh4_buy.csv");
  const chunks = [];
  for await (const chunk of await download.createReadStream()) chunks.push(chunk);
  const state = await stateOf(page);
  assert.equal(Buffer.concat(chunks).toString("utf8"), toCsv(FILES, state));
  await page.close();
});

// Phone ----------------------------------------------------------------------------------

test("search, the overlay and its legend fit a phone with no sideways scroll (C15, C16, X10)", async () => {
  const { page } = await open("#rank=E5&dep=with&home=standard&mode=rent&show=adequacy_ratio&clusters=on", { viewport: { width: 360, height: 640 } });
  assert.equal(await page.isVisible("#zip"), true);
  assert.equal(await page.isVisible(".legend-title"), true);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert.equal(overflow, 0);
  await page.locator(".controls-chip").click();
  assert.equal(await page.isVisible("#overlay"), true);
  await page.close();
});

test("every new control has an accessible name and is reached by the keyboard (X10)", async () => {
  const { page } = await open();
  for (const [role, name] of [["checkbox", "Show local clusters"], ["textbox", "ZIP code"], ["button", "Find"], ["button", "Download this view (CSV)"]]) {
    assert.equal(await page.getByRole(role, { name }).count(), 1, name);
  }
  await page.focus("#zip");
  await page.keyboard.type("80913");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => window.bahAtlas.state().selected === "CO046");
  await page.close();
});
