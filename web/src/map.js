// C5, C8, C9: MapLibre setup, the area layers and the value join.

import { MapLibreMap, addProtocol, setWorkerUrl } from "maplibre-gl";
import { Protocol } from "pmtiles";
import { NO_CLASS } from "./classify.js";

const SOURCE = "areas";
const CONUS_BOUNDS = [-124.9, 24.4, -66.9, 49.5]; // D29: opens on the 48 states
const LAND = "#e9e6df";

export async function createMap({ container, areasUrl, workerPath }) {
  setWorkerUrl(new URL(workerPath, location.href).href);
  addProtocol("pmtiles", new Protocol().tile);

  const map = new MapLibreMap({
    container,
    style: {
      version: 8,
      sources: {},
      layers: [{ id: "land", type: "background", paint: { "background-color": LAND } }],
    },
    bounds: CONUS_BOUNDS,
    fitBoundsOptions: { padding: 16 },
  });
  await new Promise((resolve) => map.once("load", resolve));

  // ICD section 4. promoteId makes `code` the feature id that every join uses.
  map.addSource(SOURCE, { type: "vector", url: `pmtiles://${areasUrl}`, promoteId: "code" });
  return map;
}

// Each area's feature-state holds a class index, so the class rule lives in one tested
// function and a null value never reaches the paint expression.
export function addAreaLayers(map, { colors, noDataColor }) {
  const fill = ["match", ["coalesce", ["feature-state", "class"], NO_CLASS]];
  colors.forEach((color, index) => fill.push(index, color));
  fill.push(noDataColor);

  map.addLayer({ id: "area-fill", type: "fill", source: SOURCE, "source-layer": SOURCE, paint: { "fill-color": fill } });
  map.addLayer({
    id: "mha-outline",
    type: "line",
    source: SOURCE,
    "source-layer": SOURCE,
    filter: ["==", ["get", "class"], "mha"],
    paint: { "line-color": "#ffffff", "line-width": 0.5 },
  });
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
