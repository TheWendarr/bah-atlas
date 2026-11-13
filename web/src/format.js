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

// Ratios arrive rounded to 4 places (ICD 3). One decimal of a percent is a second rounding,
// done half away from zero like every other rounding in the contract. It works on the whole
// number of ten-thousandths, because (value * 100).toFixed(1) rounds the binary value, which
// sends about four ties in ten the other way: 2.2655 would read 226.5%.
export function percent(value) {
  if (value === null || value === undefined) return "—";
  const tenThousandths = Math.round(Math.abs(value) * 10000);
  const tenths = Math.floor((tenThousandths + 5) / 10);
  const sign = value < 0 && tenths > 0 ? MINUS : "";
  return `${sign}${(tenths / 10).toFixed(1)}%`;
}

export function formatMetric(value, format) {
  return format === "usd" ? signedUsd(value) : percent(value);
}
