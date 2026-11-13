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
  // C26: always written. A link from before the key existed has none and opens on MHAs,
  // as it did when it was made (D37: a bare visit now opens on ZIP codes).
  ["geography", "geo"],
  ["selected", "area"],
  ["compare", "compare"],
  ["overlay", "clusters"],
];

// The selection is always written in full, so a link keeps its meaning if a later build
// changes the defaults. An area (or ZIP code), pinned places and the overlay are written only
// when set.
export function toHash(state) {
  const parts = [];
  for (const [field, key] of KEYS) {
    const value = state[field];
    if (field === "selected" && value === null) continue;
    if (field === "compare" && !value.length) continue;
    if (field === "overlay" && !value) continue;
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

// The state a link opens: the defaults, then whatever the hash names. A link that names a
// selection but no geography was made when the map had only MHAs (or opened on them), so it
// opens on MHAs; only a bare visit takes the default geography.
export function stateFromHash(defaults, hash) {
  const patch = fromHash(hash);
  const legacy = Object.keys(patch).length > 0 && !("geography" in patch);
  return { ...defaults, ...(legacy ? { geography: "mha" } : {}), ...patch };
}

// Keeps the address in step with the state without adding history entries, so the back
// button leaves the page instead of stepping through every dropdown change.
export function writeHash(state) {
  const hash = toHash(state);
  if (hash !== location.hash) history.replaceState(null, "", hash);
}
