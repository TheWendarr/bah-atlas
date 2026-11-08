// C14: one grid view, computed by the ICD section 5b.4 formula. Pure: no DOM, no map.
// pipeline/handoff/contract.py (grid_view) is the reference; web/test/grid.test.mjs
// compares every field of every view against it.

export const STANDARD = "standard";

// toFixed rounds the exact binary value half away from zero, as the ICD requires.
// Adding 0 turns the -0 that a small negative value rounds to into 0.
const round = (value, places) => Number(value.toFixed(places)) + 0;

// Step 4: the cost of the selection from the per-type values it uses. A blended standard
// is rounded to cents; a single home type's value is already in cents.
function blend(values, homeType, std) {
  if (homeType !== STANDARD) return values[0];
  if (values.includes(null)) return null;
  if (std.upper === null) return round(values[0] * (1 + std.share), 2);
  return round(values[0] + std.share * (values[1] - values[0]), 2);
}

export function gridView(grid, code, rank, dependents, homeType, mode) {
  const area = grid.areas[code];
  const i = grid.ranks.indexOf(rank);
  const block = area[mode];
  const std = grid.standards[dependents][i];

  const parts = homeType === STANDARD ? [std.lower, ...(std.upper ? [std.upper] : [])] : [homeType];
  const indexes = parts.map((type) => grid.home_types.indexOf(type));

  const status = indexes.map((j) => block.status[j]).find((s) => s !== "ok") ?? "ok";
  const caveats = [...new Set(indexes.flatMap((j) => block.caveats[j]))];

  const cost = blend(indexes.map((j) => block.cost[j]), homeType, std);
  // Buy mode only: PITI alone, blended by the same rule, as the pipeline does for B20's
  // own_housing_monthly. It is a part of the cost, not a metric.
  const housing = mode === "buy" ? blend(indexes.map((j) => block.own_housing[j]), homeType, std) : null;

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
  return {
    ...view,
    adequacy_ratio: round((bah + share) / cost, 4),
    design_gap_usd: round(bah + share - cost, 0),
    coverage_ratio: round(bah / cost, 4),
    surplus_usd: round(bah - cost, 0),
  };
}
