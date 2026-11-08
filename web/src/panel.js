// C11: the detail panel for one area. It shows the selected rank's BAH against the local
// cost of the selected home, to rent and to buy, side by side. Every value comes from
// gridView; status and caveat texts come from B21 (ICD 9, musts 3 and 4).

import { usd, formatMetric } from "./format.js";
import { labelOf } from "./notice.js";

// Interface wording that describes no data (D29).
const UI = {
  close: "Close",
  bah: "Monthly BAH",
  share: "Member cost share",
  cost: "Local monthly cost",
  notes: "About these numbers",
};

// The cluster-analysis caveat belongs with the research overlay (ICD 9, must 9).
const PANEL_AREA_CAVEATS = (id) => id !== "outside_cluster_scope";

function row(label, values, current, className = "") {
  const tr = document.createElement("tr");
  if (className) tr.className = className;
  const th = document.createElement("th");
  th.scope = "row";
  th.textContent = label;
  tr.append(th);
  values.forEach((text, index) => {
    const td = document.createElement("td");
    td.textContent = text;
    if (index === current) td.className = "current";
    tr.append(td);
  });
  return tr;
}

function paragraph(className, text) {
  const p = document.createElement("p");
  p.className = className;
  p.textContent = text;
  return p;
}

// Returns false when there is nothing to show, so the caller can hide the panel.
export function renderPanel(root, files, state, views, scales) {
  const code = state.selected;
  root.replaceChildren();
  if (code === null) return false;

  const { ui, payload } = files;
  const area = ui.areas[code];
  const modes = ui.modes;
  const current = modes.findIndex((mode) => mode.id === state.mode);
  const byMode = modes.map((mode) => views[mode.id]);
  const first = byMode[0];

  const head = document.createElement("div");
  head.className = "panel-head";
  const title = document.createElement("h2");
  title.id = "panel-title";
  title.textContent = area.display_name ?? area.name;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "panel-close";
  close.setAttribute("aria-label", UI.close);
  close.textContent = "×";
  close.dataset.action = "close";
  head.append(title, close);

  const context = paragraph(
    "panel-context",
    [
      labelOf(ui.grid.ranks, state.rank),
      labelOf(ui.grid.dependents, state.dependents),
      labelOf(ui.grid.home_types, state.homeType),
    ].join(" · "),
  );

  const summary = document.createElement("dl");
  summary.className = "panel-summary";
  for (const [label, value] of [
    [UI.bah, usd(first.bah_monthly)],
    [UI.share, usd(first.cost_share_monthly)],
  ]) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    summary.append(dt, dd);
  }

  const table = document.createElement("table");
  table.className = "panel-table";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headRow.append(document.createElement("td"));
  modes.forEach((mode, index) => {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = mode.label;
    if (index === current) th.className = "current";
    headRow.append(th);
  });
  thead.append(headRow);
  const tbody = document.createElement("tbody");
  tbody.append(row(UI.cost, byMode.map((view) => usd(view.cost_monthly)), current));
  for (const metric of ui.grid.metrics) {
    const scale = scales[metric];
    tbody.append(
      row(scale.shortLabel, byMode.map((view) => formatMetric(view[metric], scale.format)), current,
        metric === state.metric ? "chosen" : ""),
    );
  }
  table.append(thead, tbody);

  root.append(head, context, summary, table);

  // A status other than ok explains why a value is missing or limited. One that both
  // modes share is shown once.
  const statuses = byMode.map((view) => view.status);
  const shared = statuses.every((status) => status === statuses[0]);
  modes.forEach((mode, index) => {
    const status = statuses[index];
    if (status === "ok" || (shared && index > 0)) return;
    const text = ui.statuses[status];
    const box = document.createElement("div");
    box.className = "panel-status";
    box.dataset.status = status;
    const heading = document.createElement("strong");
    heading.textContent = shared ? text.label : `${mode.label}: ${text.label}`;
    box.append(heading, paragraph("", text.text));
    root.append(box);
  });

  const caveatIds = [
    ...new Set([
      ...(payload.areas[code]?.caveats ?? []).filter(PANEL_AREA_CAVEATS),
      ...byMode.flatMap((view) => view.caveats),
    ]),
  ].filter((id) => id in ui.caveats);
  if (caveatIds.length) {
    const details = document.createElement("details");
    details.className = "panel-caveats";
    // County Cost Groups and the territory bucket open with their approximate-boundary
    // note in view (ICD 9, must 4).
    details.open = area.class !== "mha";
    const summaryEl = document.createElement("summary");
    summaryEl.textContent = UI.notes;
    details.append(summaryEl);
    for (const id of caveatIds) {
      const { title: name, text } = ui.caveats[id];
      const item = document.createElement("div");
      item.className = "panel-caveat";
      item.dataset.caveat = id;
      const strong = document.createElement("strong");
      strong.textContent = name;
      item.append(strong, paragraph("", text));
      details.append(item);
    }
    root.append(details);
  }
  return true;
}
