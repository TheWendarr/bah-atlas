// C11: the detail panel for one area. It shows the selected rank's BAH against the local
// cost of the selected home, to rent and to buy, side by side. Every value comes from
// gridView; status and caveat texts come from B21 (ICD 9, musts 3 and 4).

import { formatMetric, usd } from "./format.js";
import { labelOf } from "./notice.js";

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
};

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

// Area-level caveats from B20 plus the row-level caveats of the views shown.
export function caveatIds(files, code, views) {
  return [
    ...new Set([
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
  if (!pinned && compare.length >= 2) {
    button.disabled = true;
    button.title = UI.full;
  }
  return button;
}

// Returns the panel section, or null when no area is selected.
export function renderDetail(files, state, views, scales) {
  const code = state.selected;
  if (code === null) return null;

  const { ui } = files;
  const area = ui.areas[code];
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

  section.append(head, element("p", "panel-context", contextLine(ui, state)), summary, table);

  // A status other than ok explains why a value is missing or limited. One that both
  // modes share is shown once.
  const statuses = byMode.map((view) => view.status);
  const shared = statuses.every((status) => status === statuses[0]);
  modes.forEach((mode, index) => {
    const status = statuses[index];
    if (status === "ok" || (shared && index > 0)) return;
    section.append(statusBox(ui, status, shared ? "" : mode.label));
  });

  const ids = caveatIds(files, code, byMode);
  // County Cost Groups and the territory bucket open with their approximate-boundary note
  // in view (ICD 9, must 4).
  if (ids.length) section.append(caveatList(ui, ids, area.class !== "mha"));

  section.append(pinButton(code, state.compare));
  return section;
}
