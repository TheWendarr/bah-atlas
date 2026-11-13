// C15: find the area a ZIP code belongs to. The lookup is B32 (zips_<year>.json, ICD 7b),
// about 100 KB compressed, so it loads on first use and must come from the same build as
// the files the map already holds (ICD 9, must 6). Everything above createSearch is pure.

const SUPPORTED_MAJOR = 1;

// Interface wording that describes no data (D29).
const UI = {
  label: "ZIP code",
  find: "Find",
  invalid: "Enter a five-digit ZIP code.",
  loading: "Loading the ZIP list…",
  found: (zip, name) => `ZIP ${zip} is in ${name}.`,
  none: (zip, year) => `ZIP ${zip} is not in the ${year} BAH ZIP list.`,
  failed: "The ZIP list did not load. Check the connection and try again.",
  mismatch: "The ZIP list comes from a different build than the map, so it was not used. Reload the page.",
};

// Five digits, or a ZIP+4 whose first five are used. Anything else is null.
export function normalizeZip(text) {
  const match = /^\s*(\d{5})(?:-\d{4})?\s*$/.exec(text);
  return match ? match[1] : null;
}

// The same checks the contract gate applies to the other files. Also used for the ZIP grid
// (B36, C27), which loads on first use in the same way.
export function checkZipFile(file, buildId, name = "zips") {
  const problems = [];
  const major = Number(String(file.schema_version).split(".")[0]);
  if (major !== SUPPORTED_MAJOR) problems.push(`${name}: schema_version ${file.schema_version}`);
  if (file.build_id !== buildId) problems.push(`${name}: build id begins ${String(file.build_id).slice(0, 8)}`);
  return problems;
}

// B32 is keyed by area; search needs ZIP to area.
export function zipIndex(file) {
  const index = new Map();
  for (const [code, zips] of Object.entries(file.areas)) {
    for (const zip of zips) index.set(zip, code);
  }
  return index;
}

// The outcome of one search: { zip, code } when found, or { message } alone.
export function findZip(index, ui, text) {
  const zip = normalizeZip(text);
  if (zip === null) return { message: UI.invalid };
  const code = index.get(zip) ?? null;
  if (code === null) return { zip, code, message: UI.none(zip, ui.bah_year) };
  const area = ui.areas[code];
  return { zip, code, message: UI.found(zip, area.display_name ?? area.name) };
}

export function createSearch(root, { ui, url, onFound }) {
  const form = document.createElement("form");
  form.className = "zip-search";
  form.setAttribute("role", "search");
  form.noValidate = true;
  const label = document.createElement("label");
  label.htmlFor = "zip";
  label.className = "zip-label";
  label.textContent = UI.label;
  const input = document.createElement("input");
  input.id = "zip";
  input.name = "zip";
  input.type = "text";
  input.inputMode = "numeric";
  input.autocomplete = "postal-code";
  input.maxLength = 10;
  input.size = 6;
  input.setAttribute("aria-describedby", "zip-result");
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = UI.find;
  const result = document.createElement("p");
  result.id = "zip-result";
  result.className = "zip-result";
  result.setAttribute("role", "status");
  form.append(label, input, button, result);
  root.append(form);

  let index = null;
  let loading = null;
  const load = () => {
    loading ??= fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((file) => {
        if (checkZipFile(file, ui.build_id).length) return "mismatch";
        index = zipIndex(file);
        return "ok";
      })
      .catch(() => {
        loading = null;
        return "failed";
      });
    return loading;
  };
  // Start loading as soon as the reader shows an interest, so the first search is quick.
  input.addEventListener("focus", load, { once: true });

  const say = (text) => {
    result.textContent = text;
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (normalizeZip(input.value) === null) {
      say(UI.invalid);
      return;
    }
    if (!index) say(UI.loading);
    const outcome = await load();
    if (outcome === "failed") return say(UI.failed);
    if (outcome === "mismatch") return say(UI.mismatch);
    const found = findZip(index, ui, input.value);
    say(found.message);
    if (found.code) onFound(found.code, found.zip);
  });

  return { clear: () => say("") };
}
