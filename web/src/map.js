// C5, C8, C9: MapLibre setup, the area layers and the value join. C27: the ZIP code layers.

import { MapLibreMap, addProtocol, setWorkerUrl } from "maplibre-gl";
import { Protocol } from "pmtiles";
import { NO_CLASS } from "./classify.js";
import { NO_VALUE, OUT_OF_SCOPE } from "./research.js";

const SOURCE = "areas";
// C27 (D36, ICD 4b): the ZIP code tiles, one layer `zips` keyed on `zip`, from zoom 6.
const ZIP_SOURCE = "zips";
export const ZIP_MIN_ZOOM = 6;
const ZIP = /^\d{5}$/;
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
export async function basemapStyle(basemapPath, basemapUrl) {
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

// `style` is the promise basemapStyle returned, started before the data files load so the
// two requests overlap (X9).
export async function createMap({
  container,
  areasUrl,
  areasAttribution,
  style,
  workerPath,
  onAreasUnavailable = () => {},
}) {
  setWorkerUrl(new URL(workerPath, location.href).href);
  addProtocol("pmtiles", new Protocol().tile);

  const map = new MapLibreMap({
    container,
    style: await style,
    bounds: CONUS_BOUNDS,
    minZoom: MIN_ZOOM,
    maxZoom: MAX_ZOOM,
    fitBoundsOptions: { padding: 16 },
  });
  await new Promise((resolve) => map.once("load", resolve));

  // An error from the area source with no tile attached means the archive itself could not
  // be read; one failed tile is left to MapLibre, which asks again when the view changes.
  // MapLibre writes errors to the console only while nothing listens for them, so every
  // error is still written here.
  map.on("error", (event) => {
    console.error(event.error ?? event);
    if (event.sourceId === SOURCE && !event.tile) onAreasUnavailable(event.error);
  });

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

// C16: the cluster overlay. Its own fill sits above the choropleth and its FDR outline
// above the area outlines; both stay hidden until a research view asks for them. Areas
// outside the analysis are left unfilled, so no cluster is ever drawn for them (ICD 9,
// must not 3). Colours and the outline come from B21 `clusters`.
export function addClusterLayers(map, { colors, noDataColor, fdr }) {
  const fill = ["match", ["coalesce", ["feature-state", "cluster"], OUT_OF_SCOPE], NO_VALUE, noDataColor];
  colors.forEach((color, index) => fill.push(index, color));
  fill.push("transparent");
  map.addLayer(
    {
      id: "cluster-fill",
      type: "fill",
      source: SOURCE,
      "source-layer": SOURCE,
      layout: { visibility: "none" },
      paint: { "fill-color": fill },
    },
    "mha-outline",
  );
  map.addLayer(
    {
      id: "cluster-fdr",
      type: "line",
      source: SOURCE,
      "source-layer": SOURCE,
      layout: { visibility: "none" },
      paint: {
        "line-color": fdr.outline_color,
        "line-width": fdr.outline_width,
        "line-opacity": ["case", ["boolean", ["feature-state", "fdr"], false], 1, 0],
      },
    },
    "area-pinned",
  );
}

// C27: the ZIP code layers, added the first time the reader chooses the ZIP view, so the
// first load never fetches the ZIP archive. They sit above the area fills and below the
// MHA outlines, so each MHA's edge stays visible over its ZIP codes.
export function addZipLayers(map, { zipsUrl, attribution, colors, noDataColor }) {
  if (map.getSource(ZIP_SOURCE)) return;
  map.addSource(ZIP_SOURCE, {
    type: "vector",
    url: `pmtiles://${new URL(zipsUrl, location.href).href}`,
    promoteId: "zip",
    attribution,
  });
  const fill = ["match", ["coalesce", ["feature-state", "class"], NO_CLASS]];
  colors.forEach((color, index) => fill.push(index, color));
  fill.push(noDataColor);
  const common = { source: ZIP_SOURCE, "source-layer": ZIP_SOURCE, minzoom: ZIP_MIN_ZOOM, layout: { visibility: "none" } };
  map.addLayer({ id: "zip-fill", type: "fill", ...common, paint: { "fill-color": fill } }, "mha-outline");
  map.addLayer(
    { id: "zip-outline", type: "line", ...common, paint: { "line-color": "#ffffff", "line-width": 0.4 } },
    "mha-outline",
  );
  map.addLayer(
    {
      id: "zip-pinned",
      type: "line",
      ...common,
      paint: {
        "line-color": "#1b2327",
        "line-width": 2,
        "line-dasharray": [2, 1.5],
        "line-opacity": ["case", ["boolean", ["feature-state", "pinned"], false], 1, 0],
      },
    },
    "area-selected",
  );
  map.addLayer(
    {
      id: "zip-selected",
      type: "line",
      ...common,
      paint: {
        "line-color": "#1b2327",
        "line-width": 2.5,
        "line-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 1, 0],
      },
    },
    "area-selected",
  );
  pointerOver(map, "zip-fill");
}

const ZIP_LAYERS = ["zip-fill", "zip-outline", "zip-pinned", "zip-selected"];

// The choropleth stays in place, transparent, while the overlay shows: it is the layer a
// click is read from, and it returns at once when the overlay is turned off. In the ZIP
// view (C27) the MHA fills give way to the ZIP fills from zoom 6, where the ZIP tiles
// begin; County Cost Groups and the territory bucket keep their area fill, and below
// zoom 6 the map shows MHAs. The MHA outlines widen so each MHA reads over its ZIPs.
export function setLayers(map, { overlay, geography }) {
  const zip = geography === "zip" && Boolean(map.getLayer("zip-fill"));
  const visibility = overlay ? "visible" : "none";
  if (map.getLayoutProperty("cluster-fill", "visibility") !== visibility) {
    map.setLayoutProperty("cluster-fill", "visibility", visibility);
    map.setLayoutProperty("cluster-fdr", "visibility", visibility);
  }
  const opacity = overlay ? 0 : zip ? ["step", ["zoom"], 1, ZIP_MIN_ZOOM, ["case", ["==", ["get", "class"], "mha"], 0, 1]] : 1;
  map.setPaintProperty("area-fill", "fill-opacity", opacity);
  map.setPaintProperty("mha-outline", "line-width", zip ? ["step", ["zoom"], 0.5, ZIP_MIN_ZOOM, 1.8] : 0.5);
  if (map.getLayer("zip-fill")) {
    for (const id of ZIP_LAYERS) map.setLayoutProperty(id, "visibility", zip ? "visible" : "none");
  }
}

// Whether the ZIP layer is what the reader sees: the ZIP view, zoomed in far enough.
export function zipLayerShown(map) {
  return Boolean(map.getLayer("zip-fill")) && map.getLayoutProperty("zip-fill", "visibility") === "visible"
    && map.getZoom() >= ZIP_MIN_ZOOM;
}

// The feature a selection or pin names: a five-digit ZIP code is in the ZIP layer.
function target(id) {
  return ZIP.test(id) ? { source: ZIP_SOURCE, sourceLayer: ZIP_SOURCE, id } : { source: SOURCE, sourceLayer: SOURCE, id };
}

function setState(map, id, state) {
  const where = target(id);
  if (where.source === ZIP_SOURCE && !map.getSource(ZIP_SOURCE)) return;
  map.setFeatureState(where, state);
}

// Writes only the areas whose cluster or FDR mark changed.
export function applyClusters(map, clusters, previous = new Map()) {
  for (const [code, value] of clusters) {
    const before = previous.get(code);
    if (before?.index !== value.index || before?.fdr !== value.fdr) {
      map.setFeatureState({ source: SOURCE, sourceLayer: SOURCE, id: code }, { cluster: value.index, fdr: value.fdr });
    }
  }
  return clusters;
}

export function setPinned(map, codes, previous = []) {
  for (const code of previous) {
    if (!codes.includes(code)) setState(map, code, { pinned: false });
  }
  for (const code of codes) setState(map, code, { pinned: true });
}

export function setSelected(map, code, previous) {
  if (previous !== null && previous !== code) setState(map, previous, { selected: false });
  if (code !== null) setState(map, code, { selected: true });
}

// Calls back with the clicked area's code (or, where the ZIP layer shows, the clicked ZIP
// code), or null for a click outside every area, and the clicked point in map pixels.
export function onAreaClick(map, callback) {
  map.on("click", (event) => {
    if (zipLayerShown(map)) {
      const [zip] = map.queryRenderedFeatures(event.point, { layers: ["zip-fill"] });
      if (zip) {
        callback(String(zip.id), event.point);
        return;
      }
    }
    const [feature] = map.queryRenderedFeatures(event.point, { layers: ["area-fill"] });
    callback(feature ? String(feature.id) : null, event.point);
  });
  pointerOver(map, "area-fill");
}

function pointerOver(map, layer) {
  map.on("mouseenter", layer, () => {
    map.getCanvas().style.cursor = "pointer";
  });
  map.on("mouseleave", layer, () => {
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

// C27: writes only the ZIP codes whose class changed.
export function applyZipClasses(map, classes, previous = new Map()) {
  if (!map.getSource(ZIP_SOURCE)) return previous;
  for (const [zip, value] of classes) {
    if (previous.get(zip) !== value) {
      map.setFeatureState({ source: ZIP_SOURCE, sourceLayer: ZIP_SOURCE, id: zip }, { class: value });
    }
  }
  return classes;
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
