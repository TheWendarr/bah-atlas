// C14: one grid view, computed by the ICD section 5b.4 formula. Pure: no DOM, no map.
// pipeline/handoff/contract.py (grid_view) is the reference; web/test/grid.test.mjs
// compares every field of every view against it. C27: a ZIP's view is the same formula on
// its B36 costs and its MHA's B31 BAH (ICD 5c.3, zip_view).

export const STANDARD = "standard";

// toFixed rounds the exact binary value half away from zero, as the ICD requires.
// Adding 0 turns the -0 that a small negative value rounds to into 0.
const round = (value, places) => Number(value.toFixed(places)) + 0;

// Step 4: the cost of the selection from the per-type values it uses. A blended standard
// is rounded to cents; a single home type's value is already in cents.
// `lower` and `upper` are the values of the selection's one or two home types (upper is
// undefined for one).
function blend(lower, upper, homeType, std) {
  if (homeType !== STANDARD) return lower;
  if (lower === null || upper === null) return null;
  if (std.upper === null) return round(lower * (1 + std.share), 2);
  return round(lower + std.share * (upper - lower), 2);
}

export function gridView(grid, code, rank, dependents, homeType, mode) {
  return areaView(grid, grid.areas[code], rank, dependents, homeType, mode);
}

// A B36 block with its caveat-set indexes replaced by the lists they name (ICD 5c.2).
export function expandZipBlock(zipgrid, block) {
  return { ...block, caveats: block.caveats.map((index) => zipgrid.caveat_sets[index]) };
}

// BAH is set by MHA, so every ZIP of an MHA has its MHA's BAH and cost share.
export function zipView(grid, zipgrid, zip, rank, dependents, homeType, mode) {
  const entry = zipgrid.zips[zip];
  const area = { bah: grid.areas[entry.area].bah, [mode]: expandZipBlock(zipgrid, entry[mode]) };
  return areaView(grid, area, rank, dependents, homeType, mode);
}

// The rank's standard and the home-type indexes a selection blends (5b.4 steps 1-3).
function selection(grid, rank, dependents, homeType) {
  const i = grid.ranks.indexOf(rank);
  const std = grid.standards[dependents][i];
  const parts = homeType === STANDARD ? [std.lower, ...(std.upper ? [std.upper] : [])] : [homeType];
  return { i, std, indexes: parts.map((type) => grid.home_types.indexOf(type)) };
}

// 5b.4 step 5: the four metrics from BAH, the cost share and the blended cost.
const METRICS = {
  adequacy_ratio: (bah, share, cost) => round((bah + share) / cost, 4),
  design_gap_usd: (bah, share, cost) => round(bah + share - cost, 0),
  coverage_ratio: (bah, share, cost) => round(bah / cost, 4),
  surplus_usd: (bah, share, cost) => round(bah - cost, 0),
};

// The section 5b.4 formula on one entry shaped like a B31 area (bah, rent, buy).
export function areaView(grid, area, rank, dependents, homeType, mode) {
  const { i, std, indexes } = selection(grid, rank, dependents, homeType);
  const block = area[mode];

  const status = indexes.map((j) => block.status[j]).find((s) => s !== "ok") ?? "ok";
  const caveats = [...new Set(indexes.flatMap((j) => block.caveats[j]))];

  const [a, b] = indexes;
  const cost = blend(block.cost[a], b === undefined ? undefined : block.cost[b], homeType, std);
  // Buy mode only: PITI alone, blended by the same rule, as the pipeline does for B20's
  // own_housing_monthly. It is a part of the cost, not a metric.
  const housing =
    mode === "buy" ? blend(block.own_housing[a], b === undefined ? undefined : block.own_housing[b], homeType, std) : null;

  const noRate = status === "no_rate";
  const bah = noRate ? null : area.bah[dependents][i];
  const share = noRate ? null : grid.cost_share_monthly[dependents][i];
  const anchor = std.upper === null && !std.share;

  const view = {
    status,
    caveats,
    bah_monthly: bah,
    cost_share_monthly: share,
    cost_monthly: cost === null ? null : round(cost, 0),
    own_housing_monthly: housing === null ? null : round(housing, 0),
    standard_view: homeType === STANDARD || (anchor && homeType === std.lower),
  };

  if (bah === null || cost === null) {
    return { ...view, adequacy_ratio: null, design_gap_usd: null, coverage_ratio: null, surplus_usd: null };
  }
  const out = { ...view };
  for (const [name, compute] of Object.entries(METRICS)) out[name] = compute(bah, share, cost);
  return out;
}

// C27: one metric for every B36 ZIP code at once, for the map's classes. It runs the same
// steps as areaView (the selection, the blend, the metric) without building a view object
// for each of ~15,000 ZIP codes, which kept a change under the 100 ms repaint budget (X9).
// web/test/ui.test.mjs checks it against zipView for every ZIP code.
// One pass over B36 into flat lists, kept for the life of the file.
const prepared = new WeakMap();
function prepare(zipgrid) {
  let flat = prepared.get(zipgrid);
  if (!flat) {
    const zips = Object.keys(zipgrid.zips);
    flat = {
      zips,
      areas: zips.map((zip) => zipgrid.zips[zip].area),
      rent: zips.map((zip) => zipgrid.zips[zip].rent.cost),
      buy: zips.map((zip) => zipgrid.zips[zip].buy.cost),
    };
    prepared.set(zipgrid, flat);
  }
  return flat;
}

export function zipMetricValues(grid, zipgrid, rank, dependents, homeType, mode, metric) {
  const { i, std, indexes } = selection(grid, rank, dependents, homeType);
  const share = grid.cost_share_monthly[dependents][i];
  const compute = METRICS[metric];
  const flat = prepare(zipgrid);
  const costs = flat[mode];
  const bahOf = new Map();
  const [a, b] = indexes;
  const values = new Array(flat.zips.length);
  for (let n = 0; n < flat.zips.length; n++) {
    const area = flat.areas[n];
    let bah = bahOf.get(area);
    if (bah === undefined) {
      bah = grid.areas[area].bah[dependents][i];
      bahOf.set(area, bah);
    }
    const row = costs[n];
    const cost = blend(row[a], b === undefined ? undefined : row[b], homeType, std);
    values[n] = bah === null || cost === null ? null : compute(bah, share, cost);
  }
  return { zips: flat.zips, values };
}
