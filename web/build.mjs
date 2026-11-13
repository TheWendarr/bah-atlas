// C22: build the static site into web/dist.
//
//   node build.mjs          production: tiles are read from the R2 host (D24)
//   node build.mjs --dev    local: tiles are copied into dist/tiles
//
// The build reads only delivery/<year>/ (ICD section 12), and stops if any delivered
// file differs from SHA256SUMS. JSON goes under a path named for the build, so a new
// delivery gets new URLs and its files always change together.

import { createHash } from "node:crypto";
import { copyFileSync, cpSync, existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { areaBounds } from "./tools/area_bounds.mjs";

const WEB = dirname(fileURLToPath(import.meta.url));
const DIST = join(WEB, "dist");
const site = JSON.parse(readFileSync(join(WEB, "site.config.json"), "utf8"));
const DELIVERY = join(WEB, "..", "delivery", String(site.year));
const LOCAL_BASEMAP = join(WEB, "..", "data", "processed", "basemap.pmtiles");
const dev = process.argv.includes("--dev");

const sha256 = (data) => createHash("sha256").update(data).digest("hex");

function die(message) {
  console.error(`build: ${message}`);
  process.exit(1);
}

// One line per file: "<sha256>  <name>".
function verifyDelivery() {
  const sums = new Map();
  for (const line of readFileSync(join(DELIVERY, "SHA256SUMS"), "utf8").trim().split("\n")) {
    const [hash, name] = line.split(/\s+/);
    if (sha256(readFileSync(join(DELIVERY, name))) !== hash) die(`${name} does not match SHA256SUMS`);
    sums.set(name, hash);
  }
  return sums;
}

function contentSecurityPolicy() {
  return [
    "default-src 'none'",
    "script-src 'self'",
    "worker-src 'self' blob:",
    `connect-src 'self' ${site.tilesOrigin}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'",
  ].join("; ");
}

// C24: Cloudflare Pages reads this file. Named assets and build-id data never change.
function headersFile() {
  return [
    "/*",
    `  Content-Security-Policy: ${contentSecurityPolicy()}`,
    "  Strict-Transport-Security: max-age=31536000",
    "  X-Content-Type-Options: nosniff",
    "  Referrer-Policy: strict-origin-when-cross-origin",
    "  Permissions-Policy: camera=(), geolocation=(), microphone=()",
    "/assets/*",
    "  Cache-Control: public, max-age=31536000, immutable",
    "/data/*",
    "  Cache-Control: public, max-age=31536000, immutable",
    "/basemap/*",
    "  Cache-Control: public, max-age=86400",
    "",
  ].join("\n");
}

const sums = verifyDelivery();
const year = site.year;
const buildId = sums.get(`build_manifest_${year}.json`);
const areasName = `areas_${year}.pmtiles`;
const hashedAreas = `areas_${year}.${sums.get(areasName).slice(0, 8)}.pmtiles`;
// C27 (D36): the ZIP code tiles (B35), on the same host under a content-hashed name.
const zipsName = `zipcodes_${year}.pmtiles`;
if (!sums.has(zipsName) || !sums.has(`zipgrid_${year}.json`)) {
  die(`the delivery has no ${zipsName} or zipgrid_${year}.json; run \`make layer2\` and \`make deliver REPLACE=1\` (data contract 1.3.0)`);
}
const hashedZips = `zipcodes_${year}.${sums.get(zipsName).slice(0, 8)}.pmtiles`;
const dataPath = `data/${buildId.slice(0, 8)}`;

rmSync(DIST, { recursive: true, force: true });
mkdirSync(join(DIST, dataPath), { recursive: true });
mkdirSync(join(DIST, "assets"), { recursive: true });

for (const name of sums.keys()) {
  if (name.endsWith(".json")) copyFileSync(join(DELIVERY, name), join(DIST, dataPath, name));
}

cpSync(join(WEB, "public"), DIST, { recursive: true });

// Without a local extract (it is built by `make basemap`, and CI has none), a local site
// reads the area tiles as its basemap. They hold no basemap layers, so the style loads in
// full and draws water color alone.
let localBasemap = `tiles/${hashedAreas}`;
if (dev) {
  mkdirSync(join(DIST, "tiles"));
  copyFileSync(join(DELIVERY, areasName), join(DIST, "tiles", hashedAreas));
  copyFileSync(join(DELIVERY, zipsName), join(DIST, "tiles", hashedZips));
  if (existsSync(LOCAL_BASEMAP)) {
    localBasemap = `tiles/${site.basemap}`;
    copyFileSync(LOCAL_BASEMAP, join(DIST, localBasemap));
  }
}

// MapLibre 6 finds its worker beside its own module, which bundling hides, so the
// worker ships as a named file and the app passes its address to setWorkerUrl.
const workerSource = join(WEB, "node_modules", "maplibre-gl", "dist", "maplibre-gl-worker.mjs");
const workerName = `maplibre-gl-worker-${sha256(readFileSync(workerSource)).slice(0, 8)}.mjs`;
copyFileSync(workerSource, join(DIST, "assets", workerName));

// C15, C17: each area's bounding box, from the archive just checked above. It is named by
// its content, like the scripts, and loaded only when the map moves to an area.
const bounds = JSON.stringify(await areaBounds(join(DELIVERY, areasName)));
const boundsName = `area-bounds-${sha256(bounds).slice(0, 8)}.json`;
writeFileSync(join(DIST, "assets", boundsName), bounds);
// C27: the same for each ZIP code, for ZIP search and links in the ZIP view.
const zipBounds = JSON.stringify(await areaBounds(join(DELIVERY, zipsName), "zips", "zip", { deepest: true }));
const zipBoundsName = `zip-bounds-${sha256(zipBounds).slice(0, 8)}.json`;
writeFileSync(join(DIST, "assets", zipBoundsName), zipBounds);

const SITE = {
  year,
  dataPath,
  areasUrl: dev ? `tiles/${hashedAreas}` : `${site.tilesOrigin}/${hashedAreas}`,
  zipsUrl: dev ? `tiles/${hashedZips}` : `${site.tilesOrigin}/${hashedZips}`,
  basemapPath: "basemap/",
  basemapUrl: dev ? localBasemap : `${site.tilesOrigin}/${site.basemap}`,
  workerPath: `assets/${workerName}`,
  boundsPath: `assets/${boundsName}`,
  zipBoundsPath: `assets/${zipBoundsName}`,
};

const result = await build({
  absWorkingDir: WEB,
  entryPoints: { app: "src/main.js", about: "src/about.js" },
  bundle: true,
  format: "esm",
  target: "es2022",
  minify: true,
  outdir: "dist/assets",
  entryNames: "[name]-[hash]",
  define: { __SITE__: JSON.stringify(SITE) },
  metafile: true,
  logLevel: "warning",
});

const outputs = Object.keys(result.metafile.outputs);
// Each page gets the script built from its entry point and that script's stylesheet.
function page(name, entry) {
  const [js, meta] = Object.entries(result.metafile.outputs).find(([, out]) => out.entryPoint === entry);
  const html = readFileSync(join(WEB, name), "utf8")
    .replace("{{CSS}}", `assets/${basename(meta.cssBundle)}`)
    .replace("{{JS}}", `assets/${basename(js)}`);
  writeFileSync(join(DIST, name), html);
}
page("index.html", "src/main.js");
page("about.html", "src/about.js");
writeFileSync(join(DIST, "_headers"), headersFile());

const size = (file) => `${(statSync(join(WEB, file)).size / 1024).toFixed(0)} KB`;
for (const file of outputs) console.log(`${file}  ${size(file)}`);
console.log(`build: ${dev ? "local" : "production"} site in web/dist, data path ${dataPath}, tiles ${SITE.areasUrl} and ${SITE.zipsUrl}`);
