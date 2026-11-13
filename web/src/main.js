// C5: start the app. Nothing renders until the delivered files pass the contract gate.

import "./app.css";
import { checkContract, checkManifest, loadFiles } from "./contract.js";
import { createControls } from "./controls.js";
import { renderLegend } from "./legend.js";
import { renderCompare } from "./compare.js";
import {
  addAreaLayers,
  addPinnedLayer,
  addSelectionLayer,
  applyClasses,
  basemapStyle,
  createMap,
  jumpTo,
  onAreaClick,
  reveal,
  setPinned,
  setSelected,
} from "./map.js";
import { renderDetail } from "./panel.js";
import { computeView } from "./render.js";
import { areaAttribution, renderFooterBuild, renderSources } from "./sources.js";
import { MAX_COMPARE, createStore } from "./state.js";

const SITE = __SITE__;

// Two causes share the error screen, each with its own explanation: files from different
// builds (ICD 9, must 6), and anything else that stops the map, such as a file that did
// not load or a browser without WebGL.
function showError(detail, cause = "load") {
  for (const id of ["map", "map-problem", "jump", "controls", "notice", "legend", "panel"]) {
    const el = document.getElementById(id);
    if (el) el.hidden = true;
  }
  document.getElementById("error").hidden = false;
  document.getElementById(cause === "contract" ? "error-contract" : "error-load").hidden = false;
  document.getElementById("error-detail").textContent = detail;
  document.documentElement.dataset.state = "error";
}

async function start() {
  // The basemap style loads alongside the data files (X9). A failure surfaces when the map
  // awaits it, after the contract gate.
  const style = basemapStyle(SITE.basemapPath, SITE.basemapUrl);
  style.catch(() => {});
  const { files, manifest } = await loadFiles(SITE.dataPath, SITE.year);
  const problems = checkContract(files);
  if (!problems.length) problems.push(...checkManifest(manifest, files.ui.build_id));
  if (problems.length) {
    showError(problems.join("\n"), "contract");
    return;
  }

  const { ui } = files;
  const store = createStore(ui);
  let areasAvailable = true;

  const map = await createMap({
    container: "map",
    areasUrl: SITE.areasUrl,
    areasAttribution: areaAttribution(ui),
    style,
    workerPath: SITE.workerPath,
    // The tiles come from their own host. If it cannot be reached the map has no areas to
    // colour, and without this notice the page would show an empty map with no reason.
    onAreasUnavailable: () => {
      areasAvailable = false;
      document.getElementById("map-problem").hidden = false;
      document.documentElement.dataset.state = "areas-unavailable";
    },
  });
  // Both colour scales share one set of colours (D27), so the paint never changes.
  addAreaLayers(map, { colors: ui.metrics[ui.default_metric].colors, noDataColor: ui.no_data_color });
  addSelectionLayer(map);
  addPinnedLayer(map);

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
    if (!previous || previous.compare !== state.compare) setPinned(map, state.compare, previous?.compare ?? []);
    updateControls(state, view.standardView);
    noticeEl.textContent = view.notice;
    noticeEl.classList.toggle("off-standard", !view.standardView);
    renderLegend(legendEl, ui, view.scale);
    // One panel holds the selected area's detail (C11) above the comparison (C12), so an
    // area just clicked is always in view.
    const sections = [
      renderDetail(files, state, view.selected, view.scales),
      renderCompare(files, state, view.compared, view.scales),
    ].filter(Boolean);
    // Keep the reader's place, and keyboard focus on the same button, when the panel is
    // rebuilt.
    const scroll = panelEl.scrollTop;
    const focused = panelEl.contains(document.activeElement) ? document.activeElement : null;
    panelEl.replaceChildren(...sections);
    panelEl.scrollTop = scroll;
    if (focused?.matches("button")) {
      const same = [...panelEl.querySelectorAll("button")].find(
        (button) => button.className === focused.className && button.dataset.code === focused.dataset.code,
      );
      (same ?? panelEl.querySelector("button"))?.focus();
    }
    panelEl.hidden = sections.length === 0;
    panelEl.setAttribute("aria-label", sections.map((section) => section.querySelector("h2").textContent).join(", "));
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
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const { action, code } = button.dataset;
    const { compare } = store.get();
    if (action === "close") store.set({ selected: null });
    else if (action === "pin") {
      // Pinning the second area completes the comparison, which then has the panel to itself.
      const next = [...compare, code];
      store.set(next.length === MAX_COMPARE ? { compare: next, selected: null } : { compare: next });
    }
    else if (action === "unpin") store.set({ compare: compare.filter((pinned) => pinned !== code) });
    else if (action === "clear-compare") store.set({ compare: [] });
  });
  document.addEventListener("keydown", (event) => {
    // The open sources dialog handles its own Escape.
    if (document.getElementById("sources").open) return;
    if (event.key === "Escape" && store.get().selected !== null) store.set({ selected: null });
  });

  // C20: the footer and the sources dialog.
  const footerBuild = document.getElementById("footer-build");
  const sourcesDialog = document.getElementById("sources");
  renderFooterBuild(footerBuild, ui, manifest);
  renderSources(sourcesDialog, ui, manifest);
  footerBuild.addEventListener("click", (event) => {
    if (event.target.closest("[data-action=open-sources]")) sourcesDialog.showModal();
  });
  sourcesDialog.addEventListener("click", (event) => {
    // A click on the close button, or on the backdrop outside the dialog box, closes it.
    if (event.target.closest("[data-action=close-sources]") || event.target === sourcesDialog) sourcesDialog.close();
  });

  const jump = document.getElementById("jump");
  jump.hidden = false;
  jump.addEventListener("click", (event) => {
    const region = event.target.closest("button")?.dataset.region;
    if (region) jumpTo(map, region);
  });
  map.once("idle", () => {
    if (areasAvailable) document.documentElement.dataset.state = "ready";
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
    nextIdle: () => new Promise((resolve) => map.once("idle", resolve)),
    renderedAreas: () => map.queryRenderedFeatures({ layers: ["area-fill"] }).length,
    layerOrder: () => map.getLayersOrder(),
    basemapFeatures: (sourceLayer) => map.querySourceFeatures("basemap", { sourceLayer }).length,
    attribution: () => document.querySelector(".maplibregl-ctrl-attrib-inner")?.textContent ?? "",
  };
}

start().catch((error) => showError(error.message));
