// Number display for the formats B21 names. Values arrive already rounded by grid.js.

const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const MINUS = "−";

export function usd(value) {
  if (value === null || value === undefined) return "—";
  return value < 0 ? `${MINUS}${dollars.format(-value)}` : dollars.format(value);
}

// For differences, where the sign is the point.
export function signedUsd(value) {
  if (value === null || value === undefined) return "—";
  return value > 0 ? `+${usd(value)}` : usd(value);
}

export function percent(value) {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

export function formatMetric(value, format) {
  return format === "usd" ? signedUsd(value) : percent(value);
}
