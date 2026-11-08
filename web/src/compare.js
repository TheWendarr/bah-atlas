// C12: the A/B comparison. Up to two pinned areas, side by side, for the current rank,
// dependents, home type and mode, so it follows the controls. Every value comes from
// gridView; status and caveat texts come from B21 (ICD 9, musts 3 and 4).

import { formatMetric, signedUsd, usd } from "./format.js";
import { labelOf } from "./notice.js";
import { caveatIds, caveatList, contextLine, element, statusBox } from "./panel.js";

// Interface wording that describes no data (D29).
const UI = {
  title: "Compare",
  one: (name) => `${name} is pinned. Open another area and pin it to compare the two.`,
  bah: "Monthly BAH",
  cost: "Local monthly cost",
  difference: "Difference",
  differenceNote: "Difference is the second area minus the first, in dollars.",
  notes: (name) => `About these numbers: ${name}`,
  unpin: "Unpin",
  unpinName: (name) => `Unpin ${name}`,
  clear: "Clear comparison",
};

// The dollar gap is the one difference shown (M7 plan, C12): BAH alone or with the cost
// share, against the local cost.
const DIFFERENCE = new Set(["design_gap_usd", "surplus_usd"]);

const nameOf = (ui, code) => ui.areas[code].display_name ?? ui.areas[code].name;

function cell(tag, text, field = null, code = null) {
  const el = element(tag, "", text);
  if (field) el.dataset.field = field;
  if (code) el.dataset.code = code;
  return el;
}

function unpinButton(ui, code) {
  const button = element("button", "compare-unpin", UI.unpin);
  button.type = "button";
  button.dataset.action = "unpin";
  button.dataset.code = code;
  button.setAttribute("aria-label", UI.unpinName(nameOf(ui, code)));
  return button;
}

// Returns the comparison section, or null when nothing is pinned.
export function renderCompare(files, state, compared, scales) {
  if (!compared.length) return null;
  const { ui } = files;

  const section = element("section", "panel-compare");
  section.setAttribute("aria-labelledby", "compare-title");
  const title = element("h2", "compare-title", UI.title);
  title.id = "compare-title";
  section.append(title);

  if (compared.length === 1) {
    const [{ code }] = compared;
    const line = element("div", "compare-one");
    line.append(element("p", "", UI.one(nameOf(ui, code))), unpinButton(ui, code));
    section.append(line);
    return section;
  }

  section.append(
    element("p", "panel-context", `${contextLine(ui, state)} · ${labelOf(ui.modes, state.mode)}`),
  );

  const table = element("table", "panel-table compare-table");
  const thead = element("thead");
  const headRow = element("tr");
  headRow.append(element("td"));
  // Each column carries its own Unpin, so the button sits under the name it removes.
  for (const { code } of compared) {
    const th = cell("th", null, null, code);
    th.scope = "col";
    th.append(element("span", "compare-name", nameOf(ui, code)), unpinButton(ui, code));
    headRow.append(th);
  }
  const diffHead = element("th", "compare-difference", UI.difference);
  diffHead.scope = "col";
  headRow.append(diffHead);
  thead.append(headRow);

  const tbody = element("tbody");
  const addRow = (label, field, format, className = "") => {
    const tr = element("tr", className);
    const th = element("th", "", label);
    th.scope = "row";
    tr.append(th);
    for (const { code, view } of compared) tr.append(cell("td", format(view[field]), field, code));
    let difference = "";
    if (DIFFERENCE.has(field)) {
      const [a, b] = compared.map(({ view }) => view[field]);
      difference = a === null || b === null ? "—" : signedUsd(b - a);
    }
    tr.append(cell("td", difference, field, "difference"));
    tbody.append(tr);
  };
  addRow(UI.bah, "bah_monthly", usd);
  addRow(UI.cost, "cost_monthly", usd);
  for (const metric of ui.grid.metrics) {
    const scale = scales[metric];
    addRow(scale.shortLabel, metric, (value) => formatMetric(value, scale.format), metric === state.metric ? "chosen" : "");
  }
  table.append(thead, tbody);
  section.append(table, element("p", "compare-note", UI.differenceNote));

  for (const { code, view } of compared) {
    if (view.status !== "ok") section.append(statusBox(ui, view.status, nameOf(ui, code), "compareStatus"));
  }
  for (const { code, view } of compared) {
    const ids = caveatIds(files, code, [view]);
    if (ids.length) {
      const details = caveatList(ui, ids, ui.areas[code].class !== "mha", UI.notes(nameOf(ui, code)));
      details.dataset.code = code;
      section.append(details);
    }
  }

  const actions = element("div", "compare-actions");
  const clear = element("button", "compare-clear", UI.clear);
  clear.type = "button";
  clear.dataset.action = "clear-compare";
  actions.append(clear);
  section.append(actions);
  return section;
}
