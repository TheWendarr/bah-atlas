// C20: attribution and methodology. The map credits the sources whose licences ask for
// attribution; a dialog lists every B21 source with its data period, the geometry
// statements, and the build that produced the data (B22). Source names, licences,
// periods and statements all come from B21 (ICD 9, must 7); B22 gives the build date and
// the pipeline commit.

import { element } from "./panel.js";

// Interface wording that describes no data (D29).
const UI = {
  open: "Sources and method",
  title: "Sources and method",
  close: "Close",
  geometry: "How the areas are drawn",
  sources: "Data sources",
  provider: "Provider",
  license: "Licence",
  usedFor: "Used for",
  period: "Period",
  build: "This build",
  buildId: "Build id",
  generated: "Data built",
  commit: "Pipeline commit",
  dirty: "built with uncommitted changes",
};

// The basemap source credits itself on the map (map.js), so it is not repeated here.
const BASEMAP_SOURCE = "A11";

// Which B21 source each B21 data window belongs to. Keys and ids only, no wording; a test
// fails if B21 gains a window that is not placed here.
export const WINDOW_SOURCE = {
  bah_rates: "A1",
  rent_zillow_zori: "A3",
  home_value_zillow_zhvi: "A4",
  mortgage_rate_pmms: "A7",
  rent_crosscheck_hud_safmr: "A5",
  property_tax_acs: "A9",
  insurance_fio: "A8",
};

const escapeHtml = (text) =>
  String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// The map's attribution for the area layer: each provider whose licence asks for
// attribution, once, linked to its source page. Returned as HTML for MapLibre.
export function areaAttribution(ui) {
  const providers = new Map();
  for (const source of ui.sources) {
    if (source.id === BASEMAP_SOURCE || !/attribution/i.test(source.license)) continue;
    if (!providers.has(source.provider)) providers.set(source.provider, source.url);
  }
  return [...providers]
    .map(([provider, url]) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(provider)}</a>`)
    .join(" · ");
}

// B22's generated_at as a date in UTC, for example "8 Nov 2026".
export function buildDate(manifest) {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(
    new Date(manifest.content.generated_at),
  );
}

function definitionList(pairs) {
  const dl = element("dl", "sources-facts");
  for (const [term, value] of pairs) {
    if (value === null || value === undefined) continue;
    dl.append(element("dt", "", term), element("dd", "", value));
  }
  return dl;
}

export function renderSources(dialog, ui, manifest) {
  dialog.replaceChildren();

  const head = element("div", "sources-head");
  const title = element("h2", "", UI.title);
  title.id = "sources-title";
  const close = element("button", "sources-close", "×");
  close.type = "button";
  close.setAttribute("aria-label", UI.close);
  close.dataset.action = "close-sources";
  head.append(title, close);

  const geometry = element("section", "sources-section");
  geometry.append(
    element("h3", "", UI.geometry),
    element("p", "", ui.geometry.method),
    element("p", "", ui.geometry.authority),
  );

  const periods = {};
  for (const [key, period] of Object.entries(ui.windows)) {
    const id = WINDOW_SOURCE[key];
    if (id) periods[id] = periods[id] ? `${periods[id]}; ${period}` : period;
  }
  const list = element("ul", "sources-list");
  for (const source of ui.sources) {
    const item = element("li", "sources-item");
    item.dataset.source = source.id;
    const link = element("a", "", source.title);
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    item.append(
      link,
      definitionList([
        [UI.provider, source.provider],
        [UI.usedFor, source.used_for],
        [UI.period, periods[source.id] ?? null],
        [UI.license, source.license],
      ]),
    );
    list.append(item);
  }
  const sources = element("section", "sources-section");
  sources.append(element("h3", "", UI.sources), list);

  const { git } = manifest.content;
  const commit = git?.commit ? `${git.commit.slice(0, 12)}${git.dirty ? ` (${UI.dirty})` : ""}` : null;
  const build = element("section", "sources-section");
  build.append(
    element("h3", "", UI.build),
    definitionList([
      [UI.buildId, ui.build_id],
      [UI.generated, buildDate(manifest)],
      [UI.commit, commit],
    ]),
  );
  build.querySelector("dd").classList.add("sources-id");

  dialog.append(head, geometry, sources, build);
}

// The footer line: the disclaimer stays in index.html; this adds the dialog button and
// the short build id and date.
export function renderFooterBuild(root, ui, manifest) {
  root.replaceChildren();
  const button = element("button", "footer-sources", UI.open);
  button.type = "button";
  button.dataset.action = "open-sources";
  button.setAttribute("aria-haspopup", "dialog");
  const build = element("span", "footer-build", `${UI.buildId} ${ui.build_id.slice(0, 8)} · ${buildDate(manifest)}`);
  build.title = ui.build_id;
  root.append(button, build);
}
