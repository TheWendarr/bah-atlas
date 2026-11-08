// C5: start the app. Nothing renders until the delivered files pass the contract gate.

import "./app.css";
import { checkContract, loadFiles } from "./contract.js";
import { createControls } from "./controls.js";
import { renderLegend } from "./legend.js";
import {
  addAreaLayers,
  addSelectionLayer,
  applyClasses,
  createMap,
  jumpTo,
  onAreaClick,
  reveal,
  setSelected,
} from "./map.js";
import { renderPanel } from "./panel.js";
import { computeView } from "./render.js";
import { createStore } from "./state.js";

const SITE = __SITE__;

function showError(detail) {
  for (const id of ["map", "jump", "controls", "notice", "legend", "panel"]) {
    const el = document.getElementById(id);
    if (el) el.hidden = true;
  }
  document.getElementById("error").hidden = false;
  document.getElementById("error-detail").textContent = detail;
  document.documentElement.dataset.state = "error";
}

async function start() {
  const files = await loadFiles(SITE.dataPath, SITE.year);
  const problems = checkContract(files);
  if (problems.length) {
    showError(problems.join("\n"));
    return;
  }

  const { ui } = files;
  const store = createStore(ui);

  const map = await createMap({
    container: "map",
    areasUrl: SITE.areasUrl,
    basemapPath: SITE.basemapPath,
    basemapUrl: SITE.basemapUrl,
    workerPath: SITE.workerPath,
  });
  // Both colour scales share one set of colours (D27), so the paint never changes.
  addAreaLayers(map, { colors: ui.metrics[ui.default_metric].colors, noDataColor: ui.no_data_color });
  addSelectionLayer(map);

  const controlsRoot = document.getElementById("controls");
  const noticeEl = document.getElementById("notice");
  const legendEl = document.getElementById("legend");
  const panelEl = document.getElementById("panel");
  const updateControls = createControls(controlsRoot, ui, store);
  controlsRoot.hidden = false;
  noticeEl.hidden = false;
  legendEl.hidden = false;

  let classes = new Map();
  let shown = null;

  function render(state, previous = null) {
    const view = computeView(files, state);
    classes = applyClasses(map, view.classes, classes);
    if (!previous || previous.selected !== state.selected) setSelected(map, state.selected, previous?.selected ?? null);
    updateControls(state, view.standardView);
    noticeEl.textContent = view.notice;
    noticeEl.classList.toggle("off-standard", !view.standardView);
    renderLegend(legendEl, ui, view.scale);
    panelEl.hidden = !renderPanel(panelEl, files, state, view.selected, view.scales);
    document.body.classList.toggle("panel-open", !panelEl.hidden);
    shown = view;
  }

  store.subscribe((state, previous) => render(state, previous));
  render(store.get());

  onAreaClick(map, (code, point) => {
    store.set({ selected: code });
    if (code !== null) reveal(map, point, panelEl);
  });
  panelEl.addEventListener("click", (event) => {
    if (event.target.closest("[data-action=close]")) store.set({ selected: null });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && store.get().selected !== null) store.set({ selected: null });
  });

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
    state: () => store.get(),
    set: (patch) => store.set(patch).state,
    classOf: (code) => classes.get(code),
    standardView: () => shown.standardView,
    featureState: (code) => map.getFeatureState({ source: "areas", sourceLayer: "areas", id: code }),
    pointOf: (lngLat) => {
      const point = map.project(lngLat);
      return [point.x, point.y];
    },
    center: () => [...map.getCenter().toArray(), map.getZoom()],
    moving: () => map.isMoving(),
    idle: () => map.loaded() && !map.isMoving(),
    renderedAreas: () => map.queryRenderedFeatures({ layers: ["area-fill"] }).length,
    layerOrder: () => map.getLayersOrder(),
    basemapFeatures: (sourceLayer) => map.querySourceFeatures("basemap", { sourceLayer }).length,
    attribution: () => document.querySelector(".maplibregl-ctrl-attrib-inner")?.textContent ?? "",
  };
}

start().catch((error) => showError(error.message));
