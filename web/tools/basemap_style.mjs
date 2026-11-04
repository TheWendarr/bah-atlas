// C4: write the basemap style, fonts and sprites into web/public/basemap (D25).
//
//   make web-style
//
// Run this only to change the look. The result is committed as static files, so
// @protomaps/basemaps stays a build-time tool. ASSETS is a checkout of
// protomaps/basemaps-assets, which the make target pins to one commit.

import { cpSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { layers, namedFlavor } from "@protomaps/basemaps";

const ASSETS = process.env.ASSETS;
if (!ASSETS) throw new Error("set ASSETS to a checkout of protomaps/basemaps-assets");

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "basemap");
const FLAVOR = "grayscale";
const FONTS = ["Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic"];
// Latin, Greek, Cyrillic and punctuation. The labels are English where a name exists.
const GLYPH_RANGES = ["0-255", "256-511", "512-767", "768-1023", "1024-1279", "7680-7935", "8192-8447", "8448-8703"];

const LAND = "#e9e6df";
const WATER = "#dde4e7";
const VEGETATION = "#e3e0d7"; // quieter than the flavor's gray, which reads as a data class

const flavor = { ...namedFlavor(FLAVOR), background: WATER, earth: LAND, water: WATER };
for (const key of Object.keys(flavor)) {
  if (/^(park|wood|scrub)_/.test(key)) flavor[key] = VEGETATION;
}

const all = layers("basemap", flavor, { lang: "en" });

// The choropleth goes between these two groups, so water keeps the coastline sharp and
// labels and boundaries stay readable on every class color.
const drawsAbove = (layer) => layer.type === "symbol" || layer.id.startsWith("boundaries") || layer.id.startsWith("water");
const below = all.filter((layer) => !drawsAbove(layer));
const above = all.filter(drawsAbove);

const style = {
  version: 8,
  metadata: { "bah-atlas:areas-before": above[0].id },
  glyphs: "fonts/{fontstack}/{range}.pbf",
  sprite: `sprites/${FLAVOR}`,
  sources: { basemap: { type: "vector", url: "pmtiles://basemap" } },
  layers: [...below, ...above],
};

rmSync(OUT, { recursive: true, force: true });
mkdirSync(join(OUT, "sprites"), { recursive: true });
writeFileSync(join(OUT, "style.json"), `${JSON.stringify(style)}\n`);
for (const name of [`${FLAVOR}.json`, `${FLAVOR}.png`, `${FLAVOR}@2x.json`, `${FLAVOR}@2x.png`]) {
  cpSync(join(ASSETS, "sprites", "v4", name), join(OUT, "sprites", name));
}
for (const font of FONTS) {
  mkdirSync(join(OUT, "fonts", font), { recursive: true });
  for (const range of GLYPH_RANGES) {
    cpSync(join(ASSETS, "fonts", font, `${range}.pbf`), join(OUT, "fonts", font, `${range}.pbf`));
  }
}
cpSync(join(ASSETS, "fonts", "OFL.txt"), join(OUT, "fonts", "OFL.txt"));
console.log(`style: ${style.layers.length} layers, areas before ${above[0].id}, ${FONTS.length} fonts`);
