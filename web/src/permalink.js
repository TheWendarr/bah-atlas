// C17: the selection in the address, so a view can be shared and the tests can open any
// view directly. The hash holds the selection; set() in state.js checks every value, so a
// link from another build, or one edited by hand, falls back to the defaults field by
// field. Pure apart from the two functions at the end that touch window.location.

// Field in the state object, and its key in the address.
const KEYS = [
  ["rank", "rank"],
  ["dependents", "dep"],
  ["homeType", "home"],
  ["mode", "mode"],
  ["metric", "show"],
  // C26: written only for the ZIP view, so every link made before it keeps its meaning.
  ["geography", "geo"],
  ["selected", "area"],
  ["compare", "compare"],
  ["overlay", "clusters"],
];

// The selection is always written in full, so a link keeps its meaning if a later build
// changes the defaults. An area (or ZIP code), pinned places, the overlay and the ZIP view
// are written only when set.
export function toHash(state) {
  const parts = [];
  for (const [field, key] of KEYS) {
    const value = state[field];
    if (field === "selected" && value === null) continue;
    if (field === "compare" && !value.length) continue;
    if (field === "overlay" && !value) continue;
    if (field === "geography" && value !== "zip") continue;
    const text = field === "compare" ? value.map(encodeURIComponent).join(",") : encodeURIComponent(field === "overlay" ? "on" : value);
    parts.push(`${key}=${text}`);
  }
  return `#${parts.join("&")}`;
}

// A patch for set(): only the fields the hash names, as written. Unknown keys are ignored.
export function fromHash(hash) {
  const patch = {};
  const text = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!text) return patch;
  for (const pair of text.split("&")) {
    const at = pair.indexOf("=");
    if (at < 1) continue;
    const key = pair.slice(0, at);
    const entry = KEYS.find(([, k]) => k === key);
    if (!entry) continue;
    const [field] = entry;
    const raw = pair.slice(at + 1);
    let value;
    try {
      value = field === "compare" ? (raw ? raw.split(",").map(decodeURIComponent) : []) : decodeURIComponent(raw);
    } catch {
      continue;
    }
    if (field === "compare") patch.compare = value;
    else if (field === "overlay") patch.overlay = value === "on";
    else patch[field] = value;
  }
  return patch;
}

// The state a link opens: the defaults, then whatever the hash names.
export function stateFromHash(defaults, hash) {
  return { ...defaults, ...fromHash(hash) };
}

// Keeps the address in step with the state without adding history entries, so the back
// button leaves the page instead of stepping through every dropdown change.
export function writeHash(state) {
  const hash = toHash(state);
  if (hash !== location.hash) history.replaceState(null, "", hash);
}
