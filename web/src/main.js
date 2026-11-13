// C5: start the app. Nothing renders until the delivered files pass the contract gate.

import "./app.css";
import { checkContract, checkManifest, loadFiles } from "./contract.js";
import { createControls } from "./controls.js";
import { renderClusterLegend, renderLegend } from "./legend.js";
import { EXPORT_LABEL, download, fileName, toCsv } from "./export.js";
import { showArea } from "./locate.js";
import { stateFromHash, writeHash } from "./permalink.js";
import { NO_VALUE } from "./research.js";
import { createSearch } from "./search.js";
import { renderCompare } from "./compare.js";
import {
  addAreaLayers,
  addClusterLayers,
  addPinnedLayer,
  addSelectionLayer,
  applyClasses,
  applyClusters,
  basemapStyle,
  createMap,
  jumpTo,
  onAreaClick,
  reveal,
  setOverlay,
  setPinned,
  setSelected,
} from "./map.js";
import { renderDetail } from "./panel.js";
import { computeView } from "./render.js";
import { areaAttribution, renderFooterBuild, renderSources } from "./sources.js";
import { MAX_COMPARE, createStore, initialState } from "./state.js";

const SITE = __SITE__;

// Two causes share the error screen, each with its own explanation: files from different
// builds (ICD 9, must 6), and anything else that stops the map, such as a file that did
// not load or a browser without WebGL.
function showError(detail, cause = "load") {
  for (const id of ["map", "map-problem", "jump", "controls", "notice", "legend", "panel", "search"]) {
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
  // C17: a link opens the view it names; set() checks every value it carries.
  const store = createStore(ui, stateFromHash(initialState(ui), location.hash));
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
  addClusterLayers(map, {
    colors: Object.values(ui.clusters.classes).map((cluster) => cluster.color),
    noDataColor: ui.no_data_color,
    fdr: ui.clusters.fdr_marker,
  });

  const controlsRoot = document.getElementById("controls");
  const noticeEl = document.getElementById("notice");
  const legendEl = document.getElementById("legend");
  const panelEl = document.getElementById("panel");
  const updateControls = createControls(controlsRoot, ui, store);
  controlsRoot.hidden = false;
  noticeEl.hidden = false;
  legendEl.hidden = false;

  let classes = new Map();
  let clusterStates = new Map();
  let shown = null;
  const locate = (code) =>
    showArea(map, SITE.boundsPath, code, panelEl).catch((error) => console.warn(`Area bounds: ${error.message}`));

  function render(state, previous = null) {
    const view = computeView(files, state);
    classes = applyClasses(map, view.classes, classes);
    if (!previous || previous.selected !== state.selected) setSelected(map, state.selected, previous?.selected ?? null);
    if (!previous || previous.compare !== state.compare) setPinned(map, state.compare, previous?.compare ?? []);
    // C16: the overlay replaces the choropleth's colours and legend while it shows.
    if (view.overlay) clusterStates = applyClusters(map, view.clusters, clusterStates);
    setOverlay(map, view.overlay);
    updateControls(state, view.standardView, view.research);
    noticeEl.textContent = view.notice;
    noticeEl.classList.toggle("off-standard", !view.standardView);
    if (view.overlay) {
      const noValue = [...view.clusters.values()].some((cluster) => cluster.index === NO_VALUE);
      renderClusterLegend(legendEl, ui, { noValue });
    } else {
      renderLegend(legendEl, ui, view.scale);
    }
    // One panel holds the selected area's detail (C11) above the comparison (C12), so an
    // area just clicked is always in view.
    const sections = [
      renderDetail(files, state, view.selected, view.scales, view.selectedCluster),
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
    // C17: the address follows the selection.
    writeHash(state);
    shown = view;
  }

  store.subscribe((state, previous) => render(state, previous));
  render(store.get());
  // A link that names an area opens on it.
  if (store.get().selected !== null) locate(store.get().selected);
  // An address edited by hand, or a link followed from the same page.
  window.addEventListener("hashchange", () => {
    const before = store.get().selected;
    const { state } = store.set(stateFromHash(initialState(ui), location.hash));
    if (state.selected !== null && state.selected !== before) locate(state.selected);
  });

  // C15: ZIP search, in the header.
  const searchEl = document.getElementById("search");
  createSearch(searchEl, {
    ui,
    url: `${SITE.dataPath}/zips_${SITE.year}.json`,
    onFound: (code) => {
      store.set({ selected: code });
      locate(code);
    },
  });
  searchEl.hidden = false;

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
  // C19: the current view as CSV.
  const exportButton = document.createElement("button");
  exportButton.type = "button";
  exportButton.className = "footer-export";
  exportButton.dataset.action = "export-csv";
  exportButton.textContent = EXPORT_LABEL;
  footerBuild.querySelector(".footer-about").after(exportButton);
  footerBuild.addEventListener("click", (event) => {
    if (event.target.closest("[data-action=open-sources]")) sourcesDialog.showModal();
    if (event.target.closest("[data-action=export-csv]")) {
      const state = store.get();
      download(toCsv(files, state), fileName(ui, state));
    }
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
    overlayShown: () => map.getLayoutProperty("cluster-fill", "visibility") === "visible",
    bounds: () => map.getBounds().toArray(),
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
