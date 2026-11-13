// C19: the current view as CSV, one row per area. Every value comes from gridView, so the
// file matches the map; labels come from B21. Pure apart from download().
// C28: in the ZIP view, one row per ZIP code from zipView, with its MHA in `area`.

import { gridView, zipView } from "./grid.js";
import { labelOf } from "./notice.js";

// Interface wording that describes no data (D29).
export const EXPORT_LABEL = "Download this view (CSV)";

export const COLUMNS = [
  "code",
  "name",
  "class",
  "area",
  "rank",
  "dependents",
  "home_type",
  "mode",
  "standard_view",
  "status",
  "status_label",
  "bah_monthly",
  "cost_share_monthly",
  "cost_monthly",
  "own_housing_monthly",
  "adequacy_ratio",
  "design_gap_usd",
  "coverage_ratio",
  "surplus_usd",
  "caveats",
  "build_id",
];

// A spreadsheet runs a cell that starts with one of these as a formula. A text cell that
// does is written with a leading apostrophe, which spreadsheets show as text. Numbers are
// written as numbers, so a negative gap keeps its sign.
const FORMULA_START = /^[=+\-@\t\r]/;

export function textCell(value) {
  let text = String(value);
  if (FORMULA_START.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function numberCell(value) {
  return value === null || value === undefined ? "" : String(value);
}

export function viewRows(files, state) {
  const { grid, ui } = files;
  const selection = {
    rank: labelOf(ui.grid.ranks, state.rank),
    dependents: labelOf(ui.grid.dependents, state.dependents),
    home_type: labelOf(ui.grid.home_types, state.homeType),
    mode: labelOf(ui.modes, state.mode),
  };
  const zipRows = state.geography === "zip" && files.zipgrid;
  const ids = zipRows ? Object.keys(files.zipgrid.zips) : Object.keys(grid.areas);
  return ids.map((code) => {
    const areaCode = zipRows ? files.zipgrid.zips[code].area : code;
    const area = ui.areas[areaCode];
    const view = zipRows
      ? zipView(grid, files.zipgrid, code, state.rank, state.dependents, state.homeType, state.mode)
      : gridView(grid, code, state.rank, state.dependents, state.homeType, state.mode);
    return {
      code,
      name: zipRows ? `ZIP ${code}` : area.display_name ?? area.name,
      class: zipRows ? "zip" : area.class,
      area: areaCode,
      ...selection,
      standard_view: view.standard_view,
      status: view.status,
      status_label: ui.statuses[view.status].label,
      bah_monthly: view.bah_monthly,
      cost_share_monthly: view.cost_share_monthly,
      cost_monthly: view.cost_monthly,
      own_housing_monthly: view.own_housing_monthly,
      adequacy_ratio: view.adequacy_ratio,
      design_gap_usd: view.design_gap_usd,
      coverage_ratio: view.coverage_ratio,
      surplus_usd: view.surplus_usd,
      caveats: view.caveats.join(";"),
      build_id: ui.build_id,
    };
  });
}

const NUMBERS = new Set([
  "bah_monthly",
  "cost_share_monthly",
  "cost_monthly",
  "own_housing_monthly",
  "adequacy_ratio",
  "design_gap_usd",
  "coverage_ratio",
  "surplus_usd",
]);

// RFC 4180: a header row, CRLF line ends.
export function toCsv(files, state) {
  const lines = [COLUMNS.join(",")];
  for (const row of viewRows(files, state)) {
    lines.push(
      COLUMNS.map((column) => {
        if (NUMBERS.has(column)) return numberCell(row[column]);
        if (column === "standard_view") return row[column] ? "true" : "false";
        return textCell(row[column]);
      }).join(","),
    );
  }
  return `${lines.join("\r\n")}\r\n`;
}

export function fileName(ui, state) {
  const zip = state.geography === "zip" ? "_zip" : "";
  return `bah-atlas_${ui.bah_year}_${state.rank}_${state.dependents}_${state.homeType}_${state.mode}${zip}.csv`;
}

export function download(text, name) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
