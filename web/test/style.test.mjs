// C4: the committed basemap style is valid and every file it asks for ships with it.

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec";

const BASEMAP = fileURLToPath(new URL("../public/basemap/", import.meta.url));
const style = JSON.parse(readFileSync(`${BASEMAP}style.json`, "utf8"));

// Fonts appear as a literal list or inside a case expression.
function fontsIn(value, found = new Set()) {
  if (typeof value === "string" && value.startsWith("Noto Sans")) found.add(value);
  if (Array.isArray(value)) value.forEach((item) => fontsIn(item, found));
  return found;
}

test("the style passes the MapLibre style specification", () => {
  assert.deepEqual(validateStyleMin({ ...style, glyphs: `https://x/${style.glyphs}`, sprite: `https://x/${style.sprite}` }), []);
});

test("the first label range ships for every font the layers use", () => {
  const fonts = fontsIn(style.layers.map((layer) => layer.layout?.["text-font"]));
  assert.ok(fonts.size > 0);
  for (const font of fonts) assert.ok(existsSync(`${BASEMAP}fonts/${font}/0-255.pbf`), font);
});

test("the sprite sheet ships at both pixel densities", () => {
  for (const name of ["", "@2x"]) {
    assert.ok(existsSync(`${BASEMAP}${style.sprite}${name}.json`));
    assert.ok(existsSync(`${BASEMAP}${style.sprite}${name}.png`));
  }
});

test("water, boundaries and labels draw above the place where the areas go", () => {
  const ids = style.layers.map((layer) => layer.id);
  const split = ids.indexOf(style.metadata["bah-atlas:areas-before"]);
  assert.ok(split > 0);
  const above = style.layers.slice(split);
  for (const id of ["water", "boundaries", "places_locality"]) assert.ok(above.some((layer) => layer.id === id), id);
  assert.ok(!above.some((layer) => layer.id === "earth" || layer.id.startsWith("roads_highway")));
});
