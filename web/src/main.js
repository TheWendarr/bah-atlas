// C5: start the app. Nothing renders until the delivered files pass the contract gate.

import "./app.css";
import { classIndex } from "./classify.js";
import { checkContract, loadFiles } from "./contract.js";
import { gridView } from "./grid.js";
import { addAreaLayers, applyClasses, createMap, jumpTo } from "./map.js";

const SITE = __SITE__;

function showError(detail) {
  document.getElementById("map").hidden = true;
  document.getElementById("jump").hidden = true;
  document.getElementById("error").hidden = false;
  document.getElementById("error-detail").textContent = detail;
  document.documentElement.dataset.state = "error";
}

function classesFor(files, view) {
  const { grid, ui } = files;
  const { breaks } = ui.metrics[view.metric];
  const classes = new Map();
  for (const code of Object.keys(grid.areas)) {
    const result = gridView(grid, code, view.rank, view.dependents, view.homeType, view.mode);
    classes.set(code, classIndex(result[view.metric], breaks));
  }
  return classes;
}

async function start() {
  const files = await loadFiles(SITE.dataPath, SITE.year);
  const problems = checkContract(files);
  if (problems.length) {
    showError(problems.join("\n"));
    return;
  }

  const { ui } = files;
  const view = {
    rank: ui.grid.default_rank,
    dependents: ui.grid.default_dependents,
    homeType: ui.grid.default_home_type,
    mode: ui.modes[0].id,
    metric: ui.default_metric,
  };

  const map = await createMap({
    container: "map",
    areasUrl: SITE.areasUrl,
    basemapPath: SITE.basemapPath,
    basemapUrl: SITE.basemapUrl,
    workerPath: SITE.workerPath,
  });
  addAreaLayers(map, { colors: ui.metrics[view.metric].colors, noDataColor: ui.no_data_color });
  const classes = applyClasses(map, classesFor(files, view));
  const jump = document.getElementById("jump");
  jump.hidden = false;
  jump.addEventListener("click", (event) => {
    const region = event.target.closest("button")?.dataset.region;
    if (region) jumpTo(map, region);
  });
  map.once("idle", () => {
    document.documentElement.dataset.state = "ready";
  });

  // Read by the end-to-end tests.
  window.bahAtlas = {
    classOf: (code) => classes.get(code),
    featureState: (code) => map.getFeatureState({ source: "areas", sourceLayer: "areas", id: code }),
    center: () => map.getCenter().toArray(),
    moving: () => map.isMoving(),
    layerOrder: () => map.getLayersOrder(),
    basemapFeatures: (sourceLayer) => map.querySourceFeatures("basemap", { sourceLayer }).length,
    attribution: () => document.querySelector(".maplibregl-ctrl-attrib-inner")?.textContent ?? "",
  };
}

start().catch((error) => showError(error.message));
