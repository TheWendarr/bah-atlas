// The built site in a real browser. Run after `node build.mjs --dev`, or set SITE_URL
// to test a deployed site, where the tiles come from the real host.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { scaleFor } from "../../src/classify.js";
import { formatMetric, signedUsd, usd } from "../../src/format.js";
import { gridView } from "../../src/grid.js";
import { serve } from "../serve.mjs";

const DIST = fileURLToPath(new URL("../../dist", import.meta.url));
const delivered = (name) => JSON.parse(readFileSync(new URL(`../../../delivery/2026/${name}`, import.meta.url), "utf8"));
const PAYLOAD = delivered("payload_2026.json");
const GRID = delivered("grid_2026.json");
const UI = delivered("ui_metadata_2026.json");
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

test("the jump buttons move the map to Alaska, Hawaii and back", async () => {
  const { page } = await open();
  const centerAfter = async (name) => {
    await page.getByRole("button", { name }).click();
    await page.waitForFunction(() => !window.bahAtlas.moving());
    return page.evaluate(() => window.bahAtlas.center());
  };
  const [alaskaLng, alaskaLat] = await centerAfter("Alaska");
  assert.ok(alaskaLng < -140 && alaskaLat > 55);
  const [hawaiiLng, hawaiiLat] = await centerAfter("Hawaii");
  assert.ok(hawaiiLng < -150 && hawaiiLat < 25);
  const [lng, lat] = await centerAfter("Lower 48");
  assert.ok(lng > -110 && lng < -85 && lat > 30 && lat < 45);
  await page.close();
});

test("the basemap is credited to OpenStreetMap", async () => {
  const { page } = await open();
  assert.match(await page.evaluate(() => window.bahAtlas.attribution()), /OpenStreetMap/);
  await page.close();
});

test("the map fits a phone with no horizontal scroll", async () => {
  const { page } = await open({ viewport: { width: 360, height: 640 } });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert.equal(overflow, 0);
  await page.close();
});

test("a phone draws the areas on the opening view", async () => {
  // The area tiles start at zoom 2; below it MapLibre draws nothing (fixed by minZoom).
  const { page } = await open({ viewport: { width: 360, height: 640 } });
  assert.ok((await page.evaluate(() => window.bahAtlas.renderedAreas())) > 0);
  await page.close();
});

test("changing rank recolours the map from the grid (C7, C8)", async () => {
  const { page } = await open();
  await page.selectOption("#rank", "O3");
  const result = await page.evaluate(() =>
    ["CO046", "NC182", "CA038"].map((code) => [window.bahAtlas.classOf(code), window.bahAtlas.featureState(code).class]),
  );
  for (const [computed, painted] of result) assert.equal(painted, computed);
  assert.equal((await page.evaluate(() => window.bahAtlas.state())).rank, "O3");
  await page.close();
});

test("an off-standard home type switches the notice, scale and metric names (C25, D27)", async () => {
  const { page } = await open();
  await page.selectOption("#rank", "E1");
  await page.selectOption("#home-type", "sfh4");
  assert.equal(await page.evaluate(() => window.bahAtlas.standardView()), false);
  assert.match(await page.textContent("#notice"), /not the statutory test/);
  assert.match(await page.textContent("#legend"), /Below 50%/);
  assert.equal(await page.locator("#metric option:checked").textContent(), "BAH + cost share covers");
  await page.selectOption("#home-type", "standard");
  assert.match(await page.textContent("#notice"), /its statutory target/);
  await page.close();
});

test("the rent/buy control changes the mode (C13)", async () => {
  const { page } = await open();
  await page.getByRole("radio", { name: "Buy (VA loan)" }).check({ force: true });
  assert.equal((await page.evaluate(() => window.bahAtlas.state())).mode, "buy");
  await page.close();
});

test("clicking an area opens its panel with BAH against rent and buy (C11)", async () => {
  const { page } = await open();
  const [x, y] = await page.evaluate(() => window.bahAtlas.pointOf([-104.75, 38.85]));
  const box = await page.locator("#map").boundingBox();
  await page.mouse.click(box.x + x, box.y + y);
  await page.waitForSelector("#panel:not([hidden])");
  assert.equal(await page.textContent("#panel-title"), "COLORADO SPRINGS, CO");
  const text = await page.textContent("#panel");
  // E-5 with dependents is a research profile, so the panel must show its payload values.
  const { rent, buy } = PAYLOAD.areas.CO046.e5_dep;
  const usd = (value) => `${value < 0 ? "\u2212" : ""}$${Math.abs(value).toLocaleString("en-US")}`;
  for (const value of [usd(rent.bah_monthly), usd(rent.cost_monthly), usd(buy.cost_monthly), `${rent.design_gap_usd > 0 ? "+" : ""}${usd(rent.design_gap_usd)}`]) {
    assert.ok(text.includes(value), value);
  }
  assert.equal((await page.evaluate(() => window.bahAtlas.featureState("CO046"))).selected, true);
  await page.keyboard.press("Escape");
  assert.equal(await page.isVisible("#panel"), false);
  await page.close();
});

test("a County Cost Group shows its BAH rate, status text and boundary note (C11, must 4)", async () => {
  const { page } = await open();
  await page.evaluate(() => window.bahAtlas.set({ selected: "ZZ580" }));
  assert.equal(await page.locator("[data-status=ccg_no_benchmark]").count(), 1);
  assert.equal(await page.isVisible("[data-caveat=ccg_geometry]"), true);
  assert.match(await page.textContent("#panel"), /\$1,380/);
  await page.close();
});

test("on a phone the controls open from the summary chip (D32 layout C)", async () => {
  const { page } = await open({ viewport: { width: 360, height: 640 } });
  assert.equal(await page.isVisible("#rank"), false);
  await page.locator(".controls-chip").click();
  assert.equal(await page.isVisible("#rank"), true);
  await page.selectOption("#rank", "E7");
  assert.match(await page.textContent(".controls-chip"), /E-7/);
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

// The text of each data cell in one table row, by row heading.
const rowCells = (page, scope, heading) =>
  page.evaluate(
    ([scope, heading]) => {
      const row = [...document.querySelectorAll(`${scope} tbody tr`)].find((tr) => tr.querySelector("th").textContent === heading);
      return row ? [...row.querySelectorAll("td")].map((td) => td.textContent) : null;
    },
    [scope, heading],
  );

test("buy mode splits the local cost into PITI and utilities that add up (C11)", async () => {
  const { page } = await open();
  await page.evaluate(() => window.bahAtlas.set({ selected: "CO046" }));
  const buy = gridView(GRID, "CO046", "E5", "with", "standard", "buy");
  assert.deepEqual(await rowCells(page, ".panel-detail", "Local monthly cost"), [
    usd(gridView(GRID, "CO046", "E5", "with", "standard", "rent").cost_monthly),
    usd(buy.cost_monthly),
  ]);
  assert.deepEqual(await rowCells(page, ".panel-detail", "Mortgage, tax and insurance"), ["", usd(buy.own_housing_monthly)]);
  assert.deepEqual(await rowCells(page, ".panel-detail", "Utilities"), ["", usd(buy.cost_monthly - buy.own_housing_monthly)]);
  await page.close();
});

test("an area with no rent index shows both statuses and a PITI-only cost (C11, must 3)", async () => {
  const { page } = await open();
  await page.evaluate(() => window.bahAtlas.set({ selected: "AK400" }));
  // Rent has no benchmark; buy compares BAH with PITI alone.
  assert.equal(await page.locator(".panel-detail [data-status=no_zori]").count(), 1);
  assert.equal(await page.locator(".panel-detail [data-status=piti_only_no_zori]").count(), 1);
  assert.match(await page.textContent(".panel-detail [data-status=no_zori]"), new RegExp(UI.statuses.no_zori.label));
  const buy = gridView(GRID, "AK400", "E5", "with", "standard", "buy");
  assert.equal(buy.status, "piti_only_no_zori");
  assert.deepEqual(await rowCells(page, ".panel-detail", "Local monthly cost"), ["—", usd(buy.cost_monthly)]);
  assert.deepEqual(await rowCells(page, ".panel-detail", "Utilities"), ["", "—"]);
  const scale = scaleFor(UI.metrics.adequacy_ratio, true);
  assert.deepEqual(await rowCells(page, ".panel-detail", scale.shortLabel), ["—", formatMetric(buy.adequacy_ratio, scale.format)]);
  await page.close();
});

test("the territory bucket shows no BAH rate and its status text (C11, must 4)", async () => {
  const { page } = await open();
  await page.evaluate(() => window.bahAtlas.set({ selected: "XX499" }));
  assert.equal(await page.locator(".panel-detail [data-status=no_rate]").count(), 1);
  assert.match(await page.textContent(".panel-detail [data-status=no_rate]"), new RegExp(UI.statuses.no_rate.label));
  assert.equal(await page.textContent(".panel-summary dd"), "—");
  assert.equal(await page.locator(".panel-detail tr.part").count(), 0);
  await page.close();
});

test("the legend matches B21 for every metric, on both scales (C10)", async () => {
  const { page } = await open();
  const views = [
    { rank: "E5", homeType: "standard", standard: true },
    { rank: "E1", homeType: "sfh4", standard: false },
  ];
  for (const metric of UI.grid.metrics) {
    for (const { rank, homeType, standard } of views) {
      const mode = UI.metrics[metric].modes[0];
      const label = `${metric} ${rank} ${homeType}`;
      await page.evaluate((patch) => window.bahAtlas.set(patch), { rank, homeType, metric, mode });
      const scale = scaleFor(UI.metrics[metric], standard);
      const shown = await page.evaluate(() => ({
        title: document.querySelector(".legend-title").textContent,
        short: document.querySelector(".legend-title-short").textContent,
        scaleNote: document.querySelector(".legend-scale")?.textContent ?? null,
        items: [...document.querySelectorAll(".legend-list li")].map((li) => [li.textContent, li.querySelector(".legend-swatch").style.backgroundColor]),
        ends: [...document.querySelectorAll(".legend-ends span")].map((span) => span.textContent),
      }));
      const rgb = (hex) => `rgb(${[1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(", ")})`;
      assert.equal(shown.title, scale.label, label);
      assert.equal(shown.short, scale.shortLabel, label);
      assert.deepEqual(
        shown.items,
        [...scale.classLabels.map((text, i) => [text, rgb(scale.colors[i])]), [UI.no_data_label, rgb(UI.no_data_color)]],
        label,
      );
      assert.deepEqual(shown.ends, scale.rampLabels, label);
      // The legend names the active scale (D27).
      const off = UI.grid.off_standard_scale;
      assert.equal(shown.scaleNote, scale.offStandard ? `${off.title}: ${off.subtitle}` : null, label);
    }
  }
  await page.close();
});

test("two pinned areas compare side by side, equal to gridView, and follow the controls (C12)", async () => {
  const { page } = await open();
  const pin = async (code) => {
    await page.evaluate((code) => window.bahAtlas.set({ selected: code }), code);
    await page.getByRole("button", { name: "Pin to compare" }).click();
  };
  await pin("CO046");
  assert.match(await page.textContent(".panel-compare"), /COLORADO SPRINGS, CO is pinned/);
  await pin("AK400");
  assert.deepEqual((await page.evaluate(() => window.bahAtlas.state())).compare, ["CO046", "AK400"]);

  const fields = ["bah_monthly", "cost_monthly", ...UI.grid.metrics];
  const check = async (mode) => {
    const scales = Object.fromEntries(UI.grid.metrics.map((id) => [id, scaleFor(UI.metrics[id], true)]));
    const shown = await page.evaluate(() =>
      Object.fromEntries([...document.querySelectorAll(".compare-table td[data-field]")].map((td) => [`${td.dataset.code} ${td.dataset.field}`, td.textContent])),
    );
    const views = Object.fromEntries(["CO046", "AK400"].map((code) => [code, gridView(GRID, code, "E5", "with", "standard", mode)]));
    for (const code of ["CO046", "AK400"]) {
      for (const field of fields) {
        const value = views[code][field];
        const expected = field in scales ? formatMetric(value, scales[field].format) : usd(value);
        assert.equal(shown[`${code} ${field}`], expected, `${mode} ${code} ${field}`);
      }
    }
    for (const field of ["design_gap_usd", "surplus_usd"]) {
      const [a, b] = [views.CO046[field], views.AK400[field]];
      assert.equal(shown[`difference ${field}`], a === null || b === null ? "—" : signedUsd(b - a), `${mode} difference ${field}`);
    }
    return views;
  };
  // Rent: AK400 has no rent index, so its metrics are null and the difference is "—".
  const rent = await check("rent");
  assert.equal(rent.AK400.adequacy_ratio, null);
  assert.equal(await page.locator("[data-compare-status=no_zori]").count(), 1);
  // Buy: both have values, and the comparison follows the mode.
  await page.getByRole("radio", { name: "Buy (VA loan)" }).check({ force: true });
  const buy = await check("buy");
  assert.notEqual(buy.AK400.adequacy_ratio, null);
  assert.equal(await page.locator("[data-compare-status=piti_only_no_zori]").count(), 1);

  const pinned = await page.evaluate(() => ["CO046", "AK400", "NC182"].map((code) => window.bahAtlas.featureState(code).pinned ?? false));
  assert.deepEqual(pinned, [true, true, false]);
  // A third area cannot be pinned while two are.
  await page.evaluate(() => window.bahAtlas.set({ selected: "NC182" }));
  assert.equal(await page.getByRole("button", { name: "Pin to compare" }).isDisabled(), true);

  await page.getByRole("button", { name: "Clear comparison" }).click();
  assert.equal(await page.locator(".panel-compare").count(), 0);
  assert.equal(await page.evaluate(() => window.bahAtlas.featureState("CO046").pinned), false);
  await page.close();
});

test("the comparison fits a phone, and closing the area keeps it open (C12, D32)", async () => {
  const { page } = await open({ viewport: { width: 360, height: 640 } });
  await page.evaluate(() => window.bahAtlas.set({ compare: ["NC182", "CA038"], selected: "CO046" }));
  assert.equal(await page.isVisible(".compare-table"), true);
  const overflow = await page.evaluate(() => ({
    page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    panel: document.getElementById("panel").scrollWidth - document.getElementById("panel").clientWidth,
  }));
  assert.deepEqual(overflow, { page: 0, panel: 0 });
  await page.keyboard.press("Escape");
  assert.equal(await page.isVisible(".panel-detail"), false);
  assert.equal(await page.isVisible(".compare-table"), true);
  await page.close();
});

test("pinning keeps keyboard focus on the pin button (C12, X10)", async () => {
  const { page } = await open();
  await page.evaluate(() => window.bahAtlas.set({ selected: "CO046" }));
  await page.getByRole("button", { name: "Pin to compare" }).focus();
  await page.keyboard.press("Enter");
  assert.equal(await page.evaluate(() => document.activeElement.textContent), "Unpin");
  await page.keyboard.press("Enter");
  assert.equal(await page.evaluate(() => document.activeElement.textContent), "Pin to compare");
  await page.close();
});
