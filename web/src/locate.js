// C15, C17: move the map to one area. The boxes come from the area tiles at build time
// (tools/area_bounds.mjs) and load on first use. C27: the same for a ZIP code, from the
// ZIP tiles, in a file of its own.

const pending = new Map();

export function loadBounds(path) {
  if (!pending.has(path)) {
    pending.set(
      path,
      fetch(path).then((response) => {
        if (!response.ok) throw new Error(`Bounds: HTTP ${response.status}`);
        return response.json();
      }),
    );
  }
  return pending.get(path);
}

// A box wider than half the globe is the territory bucket, whose parts lie in the
// Caribbean and the western Pacific (ICD 4). Fitting it would show the whole Pacific, so
// the map stays where it is.
export function fitsOnMap(box) {
  return Array.isArray(box) && box[2] - box[0] <= 180;
}

// Leaves room for the detail panel: beside it on a wide screen, above it on a phone,
// where it is a bottom sheet.
export function paddingFor(container, panel) {
  const base = 24;
  const padding = { top: base, right: base, bottom: base, left: base };
  if (!panel || panel.hidden) return padding;
  const box = container.getBoundingClientRect();
  const sheet = panel.getBoundingClientRect();
  if (!sheet.width || !sheet.height) return padding;
  const bottomSheet = sheet.left <= box.left + 1 && sheet.right >= box.right - 1;
  if (bottomSheet) padding.bottom = Math.min(Math.max(base, box.bottom - sheet.top + base), box.height * 0.6);
  else padding.right = Math.min(Math.max(base, box.right - sheet.left + base), box.width * 0.6);
  return padding;
}

// Returns true when the map moved. A ZIP code is small, so the map may come closer to it.
export async function showArea(map, boundsPath, code, panel, maxZoom = 9) {
  const boxes = await loadBounds(boundsPath);
  const box = boxes[code];
  if (!fitsOnMap(box)) return false;
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  map.fitBounds(box, { padding: paddingFor(map.getContainer(), panel), maxZoom, duration: still ? 0 : 700 });
  return true;
}
