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
// The area tiles start at zoom 2, and MapLibre draws nothing from a vector source below
// its minzoom. On a phone the lower 48 fit at about zoom 1.99, which left the map empty.
const MIN_ZOOM = 2;

// The PMTiles protocol passes no attribution from the archive, so the credit OpenStreetMap's
// licence requires is set on the source here, where it cannot drop out with a new extract.
const BASEMAP_ATTRIBUTION =
  '<a href="https://protomaps.com">Protomaps</a> © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

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
  style.sources.basemap.attribution = BASEMAP_ATTRIBUTION;
  return style;
}

export async function createMap({ container, areasUrl, areasAttribution, basemapPath, basemapUrl, workerPath }) {
  setWorkerUrl(new URL(workerPath, location.href).href);
  addProtocol("pmtiles", new Protocol().tile);

  const map = new MapLibreMap({
    container,
    style: await basemapStyle(basemapPath, basemapUrl),
    bounds: CONUS_BOUNDS,
    minZoom: MIN_ZOOM,
    maxZoom: MAX_ZOOM,
    fitBoundsOptions: { padding: 16 },
  });
  await new Promise((resolve) => map.once("load", resolve));

  // ICD section 4. promoteId makes `code` the feature id that every join uses.
  // C20: the area layer credits the data sources whose licences ask for it.
  map.addSource(SOURCE, {
    type: "vector",
    url: `pmtiles://${new URL(areasUrl, location.href).href}`,
    promoteId: "code",
    attribution: areasAttribution,
  });
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

// C11: the selected area gets a dark outline drawn above the fills and below the labels,
// driven by feature-state so selection never rebuilds a layer.
export function addSelectionLayer(map) {
  const before = map.getStyle().metadata["bah-atlas:areas-before"];
  map.addLayer(
    {
      id: "area-selected",
      type: "line",
      source: SOURCE,
      "source-layer": SOURCE,
      paint: {
        "line-color": "#1b2327",
        "line-width": 2.5,
        "line-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 1, 0],
      },
    },
    before,
  );
}

// C12: pinned areas keep a dashed outline while they are compared, drawn below the
// selection outline so a pinned area that is also selected reads as selected.
export function addPinnedLayer(map) {
  map.addLayer(
    {
      id: "area-pinned",
      type: "line",
      source: SOURCE,
      "source-layer": SOURCE,
      paint: {
        "line-color": "#1b2327",
        "line-width": 2,
        "line-dasharray": [2, 1.5],
        "line-opacity": ["case", ["boolean", ["feature-state", "pinned"], false], 1, 0],
      },
    },
    "area-selected",
  );
}

export function setPinned(map, codes, previous = []) {
  for (const code of previous) {
    if (!codes.includes(code)) map.setFeatureState({ source: SOURCE, sourceLayer: SOURCE, id: code }, { pinned: false });
  }
  for (const code of codes) map.setFeatureState({ source: SOURCE, sourceLayer: SOURCE, id: code }, { pinned: true });
}

export function setSelected(map, code, previous) {
  if (previous !== null && previous !== code) {
    map.setFeatureState({ source: SOURCE, sourceLayer: SOURCE, id: previous }, { selected: false });
  }
  if (code !== null) map.setFeatureState({ source: SOURCE, sourceLayer: SOURCE, id: code }, { selected: true });
}

// Calls back with the clicked area's code, or null for a click outside every area, and
// the clicked point in map pixels.
export function onAreaClick(map, callback) {
  map.on("click", (event) => {
    const [feature] = map.queryRenderedFeatures(event.point, { layers: ["area-fill"] });
    callback(feature ? String(feature.id) : null, event.point);
  });
  map.on("mouseenter", "area-fill", () => {
    map.getCanvas().style.cursor = "pointer";
  });
  map.on("mouseleave", "area-fill", () => {
    map.getCanvas().style.cursor = "";
  });
}

// Pans the map so a point hidden under the detail panel moves into the open part of the
// map: above the panel on a phone, where it is a bottom sheet, and to its left elsewhere.
export function reveal(map, point, panel) {
  const box = map.getContainer().getBoundingClientRect();
  const sheet = panel.getBoundingClientRect();
  const x = box.left + point.x;
  const y = box.top + point.y;
  const covered = x >= sheet.left && x <= sheet.right && y >= sheet.top && y <= sheet.bottom;
  if (!covered) return;
  const bottomSheet = sheet.left <= box.left + 1 && sheet.right >= box.right - 1;
  const target = bottomSheet
    ? { x: box.width / 2, y: (sheet.top - box.top) / 2 }
    : { x: (sheet.left - box.left) / 2, y: box.height / 2 };
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  map.panBy([point.x - target.x, point.y - target.y], { duration: still ? 0 : 400 });
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
