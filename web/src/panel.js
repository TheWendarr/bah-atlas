// C11: the detail panel for one area. It shows the selected rank's BAH against the local
// cost of the selected home, to rent and to buy, side by side. Every value comes from
// gridView; status and caveat texts come from B21 (ICD 9, musts 3 and 4).
// C28 (D36): the same panel for a ZIP code, with its MHA's figure for the chosen measure
// beside it and the zip-level caveat (one BAH rate per MHA).

import { formatMetric, usd } from "./format.js";
import { labelOf } from "./notice.js";
import { MAX_COMPARE, isZip } from "./state.js";

// Interface wording that describes no data (D29).
const UI = {
  close: "Close",
  bah: "Monthly BAH",
  share: "Member cost share",
  cost: "Local monthly cost",
  piti: "Mortgage, tax and insurance",
  utilities: "Utilities",
  notes: "About these numbers",
  pin: "Pin to compare",
  unpin: "Unpin",
  full: "Two areas are pinned. Unpin one to compare this area.",
  cluster: "Local cluster",
  pValue: "Pseudo p-value",
  zip: (zip) => `ZIP ${zip}`,
  inArea: (name) => `In ${name}`,
  areaLine: (name) => `${name}, the MHA as a whole`,
};

// The name a place is shown by: an area's display name, or "ZIP 80903".
export function placeName(files, id) {
  if (isZip(id)) return UI.zip(id);
  const area = files.ui.areas[id];
  return area.display_name ?? area.name;
}

// The MHA a ZIP code belongs to, from B36.
export function zipArea(files, zip) {
  return files.zipgrid?.zips[zip]?.area ?? null;
}

// The cluster-analysis caveat belongs with the research overlay (ICD 9, must 9).
const PANEL_AREA_CAVEATS = (id) => id !== "outside_cluster_scope";

export function element(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

function row(label, values, current, className = "") {
  const tr = element("tr", className);
  const th = element("th", "", label);
  th.scope = "row";
  tr.append(th);
  values.forEach((text, index) => {
    const td = element("td", index === current ? "current" : "", text);
    tr.append(td);
  });
  return tr;
}

// The selection a panel describes: rank, dependents and home type.
export function contextLine(ui, state) {
  return [
    labelOf(ui.grid.ranks, state.rank),
    labelOf(ui.grid.dependents, state.dependents),
    labelOf(ui.grid.home_types, state.homeType),
  ].join(" · ");
}

// One B21 status text, with an optional prefix such as a mode or an area name.
export function statusBox(ui, status, prefix = "", attribute = "status") {
  const text = ui.statuses[status];
  const box = element("div", "panel-status");
  box.dataset[attribute] = status;
  box.append(element("strong", "", prefix ? `${prefix}: ${text.label}` : text.label), element("p", "", text.text));
  return box;
}

// The B21 caveat texts for a list of ids, in a disclosure.
export function caveatList(ui, ids, open, heading = UI.notes) {
  const details = element("details", "panel-caveats");
  details.open = open;
  details.append(element("summary", "", heading));
  for (const id of ids) {
    const { title, text } = ui.caveats[id];
    const item = element("div", "panel-caveat");
    item.dataset.caveat = id;
    item.append(element("strong", "", title), element("p", "", text));
    details.append(item);
  }
  return details;
}

// Area-level caveats from B20 plus the row-level caveats of the views shown. A ZIP code's
// list opens with the B21 caveats of level `zip` (ICD 5c): one BAH rate per MHA.
export function caveatIds(files, code, views) {
  const zipLevel = isZip(code)
    ? Object.entries(files.ui.caveats).filter(([, caveat]) => caveat.level === "zip").map(([id]) => id)
    : [];
  return [
    ...new Set([
      ...zipLevel,
      ...(files.payload.areas[code]?.caveats ?? []).filter(PANEL_AREA_CAVEATS),
      ...views.flatMap((view) => view.caveats),
    ]),
  ].filter((id) => id in files.ui.caveats);
}

// The pin button for C12: pins or unpins this area, and is disabled when two others are
// already pinned.
function pinButton(code, compare) {
  const pinned = compare.includes(code);
  const button = element("button", "panel-pin", pinned ? UI.unpin : UI.pin);
  button.type = "button";
  button.dataset.action = pinned ? "unpin" : "pin";
  button.dataset.code = code;
  button.setAttribute("aria-pressed", String(pinned));
  if (!pinned && compare.length >= MAX_COMPARE) {
    button.disabled = true;
    button.title = UI.full;
  }
  return button;
}

// C16: the selected area's B27 result while the overlay shows. Labels come from B21
// `clusters`; the p-value is shown as delivered, to 5 decimals.
function clusterBox(ui, entry) {
  const box = element("div", "panel-cluster");
  box.append(element("strong", "", UI.cluster));
  if (entry === null) {
    box.dataset.cluster = "out_of_scope";
    box.append(element("p", "", ui.clusters.out_of_scope_label));
    return box;
  }
  box.dataset.cluster = entry.cluster ?? "no_value";
  const label = entry.cluster === null ? ui.no_data_label : ui.clusters.classes[entry.cluster].label;
  box.append(element("p", "", label));
  if (entry.lisa_p_sim !== null) box.append(element("p", "panel-cluster-p", `${UI.pValue} ${entry.lisa_p_sim.toFixed(5)}`));
  if (entry.lisa_fdr_significant) box.append(element("p", "panel-cluster-fdr", ui.clusters.fdr_marker.label));
  return box;
}

// Returns the panel section, or null when no area is selected. `cluster` is set only while
// the overlay shows (render.js), with the area's B27 entry or null outside the analysis.
export function renderDetail(files, state, views, scales, cluster = null, areaViews = null) {
  const code = state.selected;
  if (code === null || views === null) return null;

  const { ui } = files;
  const zip = isZip(code);
  const area = zip ? { name: UI.zip(code), class: "zip" } : ui.areas[code];
  const modes = ui.modes;
  const current = modes.findIndex((mode) => mode.id === state.mode);
  const byMode = modes.map((mode) => views[mode.id]);
  const first = byMode[0];

  const section = element("section", "panel-detail");
  section.setAttribute("aria-labelledby", "panel-title");

  const head = element("div", "panel-head");
  const title = element("h2", "", area.display_name ?? area.name);
  title.id = "panel-title";
  const close = element("button", "panel-close", "×");
  close.type = "button";
  close.setAttribute("aria-label", UI.close);
  close.dataset.action = "close";
  head.append(title, close);

  const summary = element("dl", "panel-summary");
  for (const [label, value] of [
    [UI.bah, usd(first.bah_monthly)],
    [UI.share, usd(first.cost_share_monthly)],
  ]) {
    summary.append(element("dt", "", label), element("dd", "", value));
  }

  const table = element("table", "panel-table");
  const thead = element("thead");
  const headRow = element("tr");
  headRow.append(element("td"));
  modes.forEach((mode, index) => {
    const th = element("th", index === current ? "current" : "", mode.label);
    th.scope = "col";
    headRow.append(th);
  });
  thead.append(headRow);
  const tbody = element("tbody");
  tbody.append(row(UI.cost, byMode.map((view) => usd(view.cost_monthly)), current));
  // Buy mode splits the cost into PITI and utilities, both from B30 (D28). Rent has no
  // delivered split, so its cells stay empty. Utilities are shown as the difference of the
  // two whole-dollar figures above them, so the three always add up.
  const split = byMode.map((view) => view.own_housing_monthly !== null && view.own_housing_monthly !== undefined);
  if (split.some(Boolean)) {
    tbody.append(
      row(UI.piti, byMode.map((view, index) => (split[index] ? usd(view.own_housing_monthly) : "")), current, "part"),
      row(
        UI.utilities,
        byMode.map((view, index) => {
          if (!split[index]) return "";
          // Under piti_only_no_zori the cost is PITI alone: no utilities estimate exists.
          if (view.status !== "ok" || view.cost_monthly === null) return "—";
          return usd(view.cost_monthly - view.own_housing_monthly);
        }),
        current,
        "part",
      ),
    );
  }
  for (const metric of ui.grid.metrics) {
    const scale = scales[metric];
    tbody.append(
      row(scale.shortLabel, byMode.map((view) => formatMetric(view[metric], scale.format)), current,
        metric === state.metric ? "chosen" : ""),
    );
  }
  table.append(thead, tbody);

  section.append(head);
  if (zip) section.append(element("p", "panel-area", UI.inArea(placeName(files, zipArea(files, code)))));
  section.append(element("p", "panel-context", contextLine(ui, state)), summary, table);

  // C28: the MHA's figure for the chosen measure, in both modes, so a ZIP reads against it.
  if (zip && areaViews) {
    const scale = scales[state.metric];
    const line = element("table", "panel-table panel-area-table");
    const tr = element("tr");
    const th = element("th", "", `${UI.areaLine(placeName(files, zipArea(files, code)))}: ${scale.shortLabel}`);
    th.scope = "row";
    tr.append(th);
    modes.forEach((mode, index) => {
      const td = element("td", index === current ? "current" : "", formatMetric(areaViews[mode.id][state.metric], scale.format));
      td.dataset.field = "area-metric";
      tr.append(td);
    });
    const body = element("tbody");
    body.append(tr);
    line.append(body);
    section.append(line);
  }

  // A status other than ok explains why a value is missing or limited. One that both
  // modes share is shown once.
  const statuses = byMode.map((view) => view.status);
  const shared = statuses.every((status) => status === statuses[0]);
  modes.forEach((mode, index) => {
    const status = statuses[index];
    if (status === "ok" || (shared && index > 0)) return;
    section.append(statusBox(ui, status, shared ? "" : mode.label));
  });

  // The overlay's caveats join the list while it shows: the exploratory note always, and the
  // out-of-scope note for an area outside the analysis.
  let ids = caveatIds(files, code, byMode);
  if (cluster) {
    section.append(clusterBox(ui, cluster.entry));
    const extra = ["lisa_exploratory", ...(cluster.entry === null ? ["outside_cluster_scope"] : [])];
    ids = [...new Set([...ids, ...extra])].filter((id) => id in ui.caveats);
  }
  // County Cost Groups and the territory bucket open with their approximate-boundary note
  // in view (ICD 9, must 4); a ZIP code opens with the note that BAH is set for its MHA.
  if (ids.length) section.append(caveatList(ui, ids, area.class !== "mha" || cluster !== null));

  section.append(pinButton(code, state.compare));
  return section;
}
