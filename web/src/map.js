// C5, C8, C9: MapLibre setup, the area layers and the value join.

import { MapLibreMap, addProtocol, setWorkerUrl } from "maplibre-gl";
import { Protocol } from "pmtiles";
import { NO_CLASS } from "./classify.js";

const SOURCE = "areas";
// D29: the map opens on the 48 states; the jump buttons reach the rest.
const REGIONS = {
  conus: [-124.9, 24.4, -66.9, 49.5],
  alaska: [-168.5, 51.2, -129.5, 71.6],
  hawaii: [-160.7, 18.8, -154.7, 22.3],
};
const CONUS_BOUNDS = REGIONS.conus;
const MAX_ZOOM = 12;

// C4: public/basemap/style.json holds relative addresses, and the tile address changes
// with the extract, so both are set here. MapLibre needs absolute addresses for these.
async function basemapStyle(basemapPath, basemapUrl) {
  const base = new URL(basemapPath, location.href).href;
  const response = await fetch(`${base}style.json`);
  if (!response.ok) throw new Error(`The basemap style could not be loaded (HTTP ${response.status}).`);
  const style = await response.json();
  style.glyphs = `${base}${style.glyphs}`;
  style.sprite = `${base}${style.sprite}`;
  style.sources.basemap.url = `pmtiles://${new URL(basemapUrl, location.href).href}`;
  return style;
}

export async function createMap({ container, areasUrl, basemapPath, basemapUrl, workerPath }) {
  setWorkerUrl(new URL(workerPath, location.href).href);
  addProtocol("pmtiles", new Protocol().tile);

  const map = new MapLibreMap({
    container,
    style: await basemapStyle(basemapPath, basemapUrl),
    bounds: CONUS_BOUNDS,
    maxZoom: MAX_ZOOM,
    fitBoundsOptions: { padding: 16 },
  });
  await new Promise((resolve) => map.once("load", resolve));

  // ICD section 4. promoteId makes `code` the feature id that every join uses.
  map.addSource(SOURCE, { type: "vector", url: `pmtiles://${new URL(areasUrl, location.href).href}`, promoteId: "code" });
  return map;
}

// C5: move the view to one of the regions above.
export function jumpTo(map, region) {
  const bounds = REGIONS[region];
  if (!bounds) return;
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  map.fitBounds(bounds, { padding: 16, duration: still ? 0 : 600 });
}

// Each area's feature-state holds a class index, so the class rule lives in one tested
// function and a null value never reaches the paint expression.
export function addAreaLayers(map, { colors, noDataColor }) {
  const fill = ["match", ["coalesce", ["feature-state", "class"], NO_CLASS]];
  colors.forEach((color, index) => fill.push(index, color));
  fill.push(noDataColor);

  // D25: below water, boundaries and labels.
  const before = map.getStyle().metadata["bah-atlas:areas-before"];
  map.addLayer({ id: "area-fill", type: "fill", source: SOURCE, "source-layer": SOURCE, paint: { "fill-color": fill } }, before);
  map.addLayer(
    {
      id: "mha-outline",
      type: "line",
      source: SOURCE,
      "source-layer": SOURCE,
      filter: ["==", ["get", "class"], "mha"],
      paint: { "line-color": "#ffffff", "line-width": 0.5 },
    },
    before,
  );
}

// Writes only the areas whose class changed.
export function applyClasses(map, classes, previous = new Map()) {
  for (const [code, value] of classes) {
    if (previous.get(code) !== value) {
      map.setFeatureState({ source: SOURCE, sourceLayer: SOURCE, id: code }, { class: value });
    }
  }
  return classes;
}
