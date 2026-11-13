// X9: first load and repaint, on a throttled connection and processor. Run with
// `make web-perf`, which builds the local site and writes the measurements to
// docs/evidence/web_perf.json. It is kept out of `make web-e2e` because timings in a
// shared CI runner, drawing WebGL in software, are not a fair reading.
//
// Profile: 9 Mbps down, 1.5 Mbps up, 60 ms round trip, processor 4x slower, 360 x 640.
// Text files are gzipped by the test server as the live host compresses them.

import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { serve } from "../serve.mjs";

const DIST = fileURLToPath(new URL("../../dist", import.meta.url));
const OUT = process.env.PERF_OUT;
const WEBGL = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];
const PROFILE = { downloadKbps: 9000, uploadKbps: 1500, latencyMs: 60, cpuSlowdown: Number(process.env.PERF_CPU ?? 4), viewport: { width: 360, height: 640 } };
const BUDGET = { firstLoadBytes: 1_000_000, usableMs: 3000, repaintMs: 100 };
// The basemap is excluded from the first-load budget: the choropleth does not wait for it.
const BASEMAP = /\/basemap\/|basemap_\d{4}\./;

let browser;
let site;
const results = { profile: PROFILE, budget: BUDGET };

before(async () => {
  site = await serve(DIST, { compress: true });
  browser = await chromium.launch({ args: WEBGL });
});

after(async () => {
  await browser.close();
  site.server.close();
  if (OUT) {
    results.measured_at = new Date().toISOString();
    writeFileSync(OUT, `${JSON.stringify(results, null, 2)}\n`);
  }
});

async function throttled() {
  const context = await browser.newContext({ viewport: PROFILE.viewport });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", {
    offline: false,
    latency: PROFILE.latencyMs,
    downloadThroughput: (PROFILE.downloadKbps * 1000) / 8,
    uploadThroughput: (PROFILE.uploadKbps * 1000) / 8,
  });
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: PROFILE.cpuSlowdown });
  const urls = new Map();
  const bytes = new Map();
  cdp.on("Network.requestWillBeSent", ({ requestId, request }) => urls.set(requestId, request.url));
  cdp.on("Network.loadingFinished", ({ requestId, encodedDataLength }) => bytes.set(requestId, encodedDataLength));
  return { context, page, urls, bytes };
}

// "Usable" is the first moment the coloured areas are on screen with the controls showing.
// "Ready" waits further, for every tile in view to be drawn and the map to fall idle.
test("first load: under 1 MB on the wire before the basemap, usable in under 3 s (X9)", async () => {
  const { context, page, urls, bytes } = await throttled();
  const start = Date.now();
  await page.goto(site.origin);
  await page.waitForFunction(
    () => window.bahAtlas && !document.getElementById("controls").hidden && window.bahAtlas.renderedAreas() > 0,
    null,
    { timeout: 60_000, polling: 50 },
  );
  const usableMs = Date.now() - start;
  await page.waitForFunction(() => document.documentElement.dataset.state === "ready", null, { timeout: 60_000, polling: 50 });
  const readyMs = Date.now() - start;
  let firstLoadBytes = 0;
  let basemapBytes = 0;
  const files = [];
  for (const [id, size] of bytes) {
    const url = urls.get(id) ?? "";
    if (BASEMAP.test(url)) basemapBytes += size;
    else firstLoadBytes += size;
    files.push({ path: new URL(url).pathname, bytes: size });
  }
  results.first_load = { usable_ms: usableMs, ready_ms: readyMs, bytes_before_basemap: firstLoadBytes, basemap_bytes: basemapBytes, requests: files.length };
  console.log(`first load: ${firstLoadBytes} bytes before the basemap, usable in ${usableMs} ms, idle in ${readyMs} ms`);
  assert.ok(firstLoadBytes <= BUDGET.firstLoadBytes, `${firstLoadBytes} bytes`);
  assert.ok(usableMs <= BUDGET.usableMs, `${usableMs} ms`);
  await context.close();
});

test("a selection change repaints in under 100 ms (X9)", async () => {
  const { context, page } = await throttled();
  // The MHA view; a bare visit (the first-load test) opens on ZIP codes at the national zoom (D37).
  await page.goto(`${site.origin}/#rank=E5&dep=with&home=standard&mode=rent&show=adequacy_ratio&geo=mha`);
  await page.waitForFunction(() => document.documentElement.dataset.state === "ready", null, { timeout: 60_000 });
  const ranks = ["O3", "E1", "W2", "O9", "E7", "E5"];
  const times = await page.evaluate(async (ranks) => {
    const out = [];
    const idleOrTimeout = () => Promise.race([window.bahAtlas.nextIdle(), new Promise((resolve) => setTimeout(resolve, 5000))]);
    for (const rank of ranks) {
      const idle = idleOrTimeout();
      const t0 = performance.now();
      window.bahAtlas.set({ rank });
      const update = performance.now() - t0;
      await idle;
      out.push({ rank, update_ms: Math.round(update * 10) / 10, to_idle_ms: Math.round(performance.now() - t0) });
    }
    return out;
  }, ranks);
  const update = Math.max(...times.map((t) => t.update_ms));
  results.repaint = { changes: times, max_update_ms: update };
  console.log(`repaint: state to feature-state at most ${update} ms; to idle ${times.map((t) => t.to_idle_ms).join(", ")} ms`);
  assert.ok(update <= BUDGET.repaintMs, `${update} ms`);
  await context.close();
});

// C27 (D36): the ZIP view rewrites up to ~15,000 ZIP codes' feature-state on each change, the
// risk the ZIP-view plan named. Measured zoomed in on Colorado Springs, on the same profile.
test("a selection change in the ZIP view repaints in under 100 ms (X9, C27)", async () => {
  const { context, page } = await throttled();
  await page.goto(`${site.origin}/#rank=E5&dep=with&home=standard&mode=rent&show=adequacy_ratio&geo=zip`);
  await page.waitForFunction(() => document.documentElement.dataset.state === "ready", null, { timeout: 60_000 });
  // D37: B36 loads once the reader zooms toward the ZIP zooms, not at the national view.
  await page.evaluate(() => window.bahAtlas.zoomTo([-104.8, 38.85], 9));
  await page.waitForFunction(() => document.documentElement.dataset.zip === "ready", null, { timeout: 120_000 });
  await page.waitForFunction(() => window.bahAtlas.idle(), null, { timeout: 60_000 });
  const ranks = ["O3", "E1", "W2", "O9", "E7", "E5"];
  const times = await page.evaluate(async (ranks) => {
    const out = [];
    const idleOrTimeout = () => Promise.race([window.bahAtlas.nextIdle(), new Promise((resolve) => setTimeout(resolve, 5000))]);
    for (const rank of ranks) {
      const idle = idleOrTimeout();
      const t0 = performance.now();
      window.bahAtlas.set({ rank });
      const update = performance.now() - t0;
      await idle;
      out.push({ rank, update_ms: Math.round(update * 10) / 10, to_idle_ms: Math.round(performance.now() - t0) });
    }
    return out;
  }, ranks);
  const update = Math.max(...times.map((t) => t.update_ms));
  results.zip_repaint = { changes: times, max_update_ms: update };
  console.log(`ZIP repaint: state to feature-state at most ${update} ms; to idle ${times.map((t) => t.to_idle_ms).join(", ")} ms`);
  assert.ok(update <= BUDGET.repaintMs, `${update} ms`);
  await context.close();
});
