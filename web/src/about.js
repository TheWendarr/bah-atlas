// C21: the About page. Fills the results and caveat sections from B21 (ui_metadata), so
// they always match the delivered build: the H1 and H2 findings, the cluster labels, every
// global caveat and the build id (ICD 9, must 7). The prose around them is the author's,
// in about.html; an empty prose slot hides itself, and so does a section left with
// nothing but empty slots.

import "./about.css";
import { checkContract } from "./contract.js";

/* global __SITE__ */
const SITE = __SITE__;

// Interface wording that describes no data (D29), and the statistical vocabulary of the
// result tables.
const UI = {
  error: "The data for this page could not be loaded, so the results and caveats are not shown.",
  scope: (profile, mode) => `Both tests use ${profile}, ${mode.toLowerCase()} mode, on the variable `,
  observations: "Areas analysed",
  moranI: "Moran's I",
  pseudoP: "Pseudo p-value",
  fdr: "Clusters still significant after the false-discovery-rate correction",
  clusterClass: "Local cluster class (pseudo p < 0.05, exploratory)",
  areas: "Areas",
  modelled: "Areas modelled",
  eligible: "Areas eligible",
  model: "Model chosen",
  olsR2: "OLS R²",
  ambiguous: "Model form",
  ambiguousYes: "Ambiguous: the spatial lag and spatial error models were both fitted",
  ambiguousNo: "Clear",
  predictor: "Predictor",
  b: "Coefficient",
  p: "p-value",
  reading: "Reading",
  alternative: (model) => `Under ${model}`,
  agrees: "the same reading",
  build: (id) => `Results from build ${id.slice(0, 8)}.`,
};

const MODEL_NAMES = { error: "Spatial error (ML_Error)", lag: "Spatial lag (ML_Lag)" };

function element(tag, className = "", text = null) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== null) el.textContent = text;
  return el;
}

const code = (text) => element("code", "", text);

// Coefficients and p-values as the evidence prints them; a p-value of 0 is below the
// smallest value the file records.
const number = (value, places = 4) => (Number.isInteger(value) ? String(value) : String(Number(value.toFixed(places))));
const pValue = (value) => (value === 0 ? "< 0.00001" : String(value));
// "p = 0.034" or "p < 0.00001".
const pText = (value) => (value === 0 ? `p ${pValue(value)}` : `p = ${pValue(value)}`);

// A two-column table of label and value rows.
function factTable(table, rows) {
  const tbody = element("tbody");
  for (const [label, value] of rows) {
    const tr = element("tr");
    const th = element("th", "", label);
    th.scope = "row";
    const td = element("td");
    td.append(value instanceof Node ? value : document.createTextNode(String(value)));
    tr.append(th, td);
    tbody.append(tr);
  }
  table.classList.add("facts");
  table.replaceChildren(tbody);
}

function renderH1(ui) {
  const { h1 } = ui.findings;
  factTable(document.querySelector('[data-render="h1"]'), [
    [UI.observations, h1.n],
    [UI.moranI, number(h1.moran_i)],
    [UI.pseudoP, pValue(h1.p_sim)],
    [UI.fdr, h1.fdr_significant],
  ]);

  const table = document.querySelector('[data-render="h1-clusters"]');
  const thead = element("thead");
  const head = element("tr");
  for (const text of [UI.clusterClass, UI.areas]) {
    const th = element("th", "", text);
    th.scope = "col";
    head.append(th);
  }
  thead.append(head);
  const tbody = element("tbody");
  for (const [id, count] of Object.entries(h1.clusters)) {
    const tr = element("tr");
    tr.dataset.cluster = id;
    const th = element("th", "", ui.clusters.classes[id].label);
    th.scope = "row";
    tr.append(th, element("td", "", String(count)));
    tbody.append(tr);
  }
  table.replaceChildren(thead, tbody);
}

function renderH2(ui) {
  const { h2 } = ui.findings;
  factTable(document.querySelector('[data-render="h2-model"]'), [
    [UI.modelled, h2.n],
    [UI.eligible, h2.eligible],
    [UI.model, MODEL_NAMES[h2.model] ?? h2.model],
    [UI.olsR2, number(h2.ols_r2)],
    [UI.ambiguous, h2.ambiguous_form ? UI.ambiguousYes : UI.ambiguousNo],
  ]);

  const table = document.querySelector('[data-render="h2"]');
  table.classList.add("predictors");
  const thead = element("thead");
  const head = element("tr");
  for (const text of [UI.predictor, UI.b, UI.p, UI.reading]) {
    const th = element("th", "", text);
    th.scope = "col";
    head.append(th);
  }
  thead.append(head);
  const tbody = element("tbody");
  for (const predictor of h2.predictors) {
    const tr = element("tr");
    tr.dataset.predictor = predictor.id;
    const name = element("th");
    name.scope = "row";
    name.append(code(predictor.id));
    const reading = element("td", "reading", predictor.reading);
    const alt = predictor.alternative;
    if (alt) {
      const note = element(
        "span",
        predictor.model_form_agrees ? "about-alt" : "about-alt differs",
        `${UI.alternative(alt.model)}: b = ${number(alt.b)}, ${pText(alt.p)}; ${predictor.model_form_agrees ? UI.agrees : alt.reading}.`,
      );
      reading.append(element("br"), note);
    }
    tr.append(name, element("td", "num coef", number(predictor.b)), element("td", predictor.p === 0 ? "num pval below" : "num pval", pValue(predictor.p)), reading);
    tbody.append(tr);
  }
  table.replaceChildren(thead, tbody);
}

function renderCaveats(ui) {
  const root = document.querySelector('[data-render="global-caveats"]');
  root.replaceChildren(
    ...ui.global_caveats.map((caveat) => {
      const item = element("div", "about-caveat");
      item.dataset.caveat = caveat.id;
      item.append(element("h3", "", caveat.title), element("p", "", caveat.text));
      return item;
    }),
  );
}

// Profile ids in the benchmark table become their B21 labels.
function renderProfiles(ui) {
  for (const cell of document.querySelectorAll('[data-render="profile-label"]')) {
    const profile = ui.profiles.find((p) => p.id === cell.closest("[data-profile]").dataset.profile);
    if (profile) cell.textContent = profile.label;
  }
}

// An empty prose slot hides; so does a section whose content is only empty slots.
export function hideEmptyProse(root = document) {
  for (const slot of root.querySelectorAll(".prose")) {
    slot.hidden = slot.children.length === 0 && slot.textContent.trim() === "";
  }
  for (const section of root.querySelectorAll("main > section")) {
    const content = [...section.children].filter((child) => !/^H[1-6]$/.test(child.tagName));
    section.hidden = content.length > 0 && content.every((child) => child.classList.contains("prose") && child.hidden);
  }
}

async function start() {
  hideEmptyProse();
  const response = await fetch(`${SITE.dataPath}/ui_metadata_${SITE.year}.json`);
  if (!response.ok) throw new Error(`ui_metadata: HTTP ${response.status}`);
  const ui = await response.json();
  const problems = checkContract({ ui });
  if (problems.length) throw new Error(problems.join(" "));

  const h1 = ui.findings.h1;
  const profile = ui.profiles.find((p) => p.id === h1.profile)?.label ?? h1.profile;
  const mode = ui.modes.find((m) => m.id === h1.mode)?.label ?? h1.mode;
  document.querySelector('[data-render="scope"]').append(UI.scope(profile, mode), code(h1.variable), ".");

  renderH1(ui);
  renderH2(ui);
  renderProfiles(ui);
  renderCaveats(ui);
  document.querySelector('[data-render="build"]').textContent = UI.build(ui.build_id);
  document.documentElement.dataset.state = "ready";
}

start().catch((error) => {
  const box = document.getElementById("about-error");
  box.textContent = `${UI.error} (${error.message})`;
  box.hidden = false;
  for (const el of document.querySelectorAll("[data-render]")) el.closest(".table-wrap")?.setAttribute("hidden", "");
  document.documentElement.dataset.state = "error";
});
