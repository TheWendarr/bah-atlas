#!/usr/bin/env python3
"""
standards_check.py  (A14 evidence: the housing standards table against the 2026 BAH rates)

DoD sets BAH for a pay grade as the local cost of the grade's housing standard
minus the grade's member cost share. Six grade-and-dependency cells are anchors
(their standard is one housing profile), so each anchor's rate plus its cost share
is that profile's local cost in the MHA:

    2 BR townhouse     E-5 with dependents        1 BR apartment   E-4 without
    3 BR townhouse     E-6 with dependents        2 BR apartment   O-1 without
    3 BR single-family W-3 with dependents
    4 BR single-family O-5 with dependents

Every other cell in config/housing_standards.json (A14) then predicts its own rate:

    interpolated:     cost = lower + share x (upper - lower)
    above the top:    cost = lower x (1 + share)            (upper is null, share > 0)
    rate              = cost - cost share

This script runs that prediction for every real MHA and every A14 cell and
records, per cell, the share the 2026 rates imply (median over MHAs) beside the
share A14 holds. It stops if any cell disagrees by more than the tolerance, so a
mistyped percentage or a DoD change to the standards cannot pass silently.

Without-dependents rates carry a floor: since 2008 they are at least 75% of the
with-dependents rate for the grade. Where that floor sets the rate the standard
does not, so those MHA cells are left out of the implied share and counted.

    python pipeline/benchmarks/standards_check.py \
        --bah-rates data/interim/bah_2026/bah_rates.csv \
        --out data/interim/benchmarks_2026

Output: standards_check_manifest.json (per-cell table, floor counts, verdict).
The manifest is evidence for W1 and B23; nothing downstream reads its numbers.
Stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mha_agg as agg  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TOOL = "standards_check"
ANCHORS = {"th2": ("E5", "with"), "th3": ("E6", "with"), "sfh3": ("W3", "with"), "sfh4": ("O5", "with"),
           "apt1": ("E4", "without"), "apt2": ("O1", "without")}
FLOOR_SHARE = 0.75          # without-dependents floor, share of the with-dependents rate
FLOOR_MARGIN = 2.0          # dollars: a rate within this of the floor is treated as set by it
TOL_INTERPOLATED = 0.05     # implied share vs A14, interpolated cells
TOL_ABOVE_TOP = 0.005       # implied markup vs A14, cells above the top anchor
MIN_SPREAD = 50.0           # dollars between the two profiles before a share is read from an MHA


def load_rates(path: Path) -> dict[tuple[str, str, str], float]:
    if not path.exists():
        agg.die(TOOL, f"B4 not found: {path} (run `make ingest` first)")
    rates = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            dep = "with" if r["has_dependents"].strip().lower() in ("true", "1") else "without"
            rates[(r["mha"].strip().upper(), r["pay_grade"].strip().upper(), dep)] = float(r["monthly_rate"])
    return rates


def implied(cell: dict, cost_g: float, prof: dict[str, float]) -> float | None:
    lo, up = prof[cell["lower"]], prof[cell["upper"]] if cell["upper"] else None
    if up is None:
        return cost_g / lo - 1
    if abs(up - lo) < MIN_SPREAD:
        return None
    return (cost_g - lo) / (up - lo)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bah-rates", type=Path, required=True, help="B4 bah_rates.csv")
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    ap.add_argument("--standards", type=Path, default=ROOT / "config" / "housing_standards.json")
    args = ap.parse_args()

    cfg = json.loads(args.standards.read_text(encoding="utf-8"))
    shares = cfg["cost_share_monthly"]
    rates = load_rates(args.bah_rates)
    mhas = sorted({m for m, _, _ in rates if agg.MHA_CODE.match(m) and not m.startswith(("ZZ", "XX"))})
    missing = [f"{g} {d}" for g in cfg["grades"] for d in ("with", "without")
               if any((m, g, d) not in rates for m in mhas)]
    agg.fail_if([f"B4 lacks rates for {', '.join(missing[:10])}"] if missing else [], TOOL)

    def cost(m: str, g: str, d: str) -> float:
        return rates[(m, g, d)] + shares[g][d]

    profiles = {m: {t: cost(m, g, d) for t, (g, d) in ANCHORS.items()} for m in mhas}
    cells, problems = [], []
    floor_cells = 0
    for g in cfg["grades"]:
        for d in ("with", "without"):
            cell = cfg["standards"][g][d]
            vals, residuals, floored = [], [], 0
            for m in mhas:
                prof = profiles[m]
                lo = prof[cell["lower"]]
                c = (lo * (1 + cell["share"]) if cell["upper"] is None
                     else lo + cell["share"] * (prof[cell["upper"]] - lo))
                actual = rates[(m, g, d)]
                if d == "without" and actual <= FLOOR_SHARE * rates[(m, g, "with")] + FLOOR_MARGIN:
                    floored += 1
                    continue
                residuals.append(actual - (c - shares[g][d]))
                v = implied(cell, actual + shares[g][d], prof)
                if v is not None:
                    vals.append(v)
            floor_cells += floored
            anchor = cell["upper"] is None and cell["share"] == 0
            entry = {"grade": g, "dependents": d, **cell, "anchor": anchor, "mhas_used": len(vals),
                     "mhas_at_75pct_floor": floored,
                     "implied_share_median": round(statistics.median(vals), 4) if vals and not anchor else None,
                     "median_residual_usd": round(statistics.median(residuals), 2) if residuals else None,
                     "median_abs_residual_usd": round(statistics.median(abs(x) for x in residuals), 2)
                     if residuals else None}
            if vals and not anchor:
                q = statistics.quantiles(vals, n=4)
                entry["implied_share_iqr"] = [round(q[0], 4), round(q[2], 4)]
                tol = TOL_ABOVE_TOP if cell["upper"] is None else TOL_INTERPOLATED
                diff = entry["implied_share_median"] - cell["share"]
                entry["difference"] = round(diff, 4)
                if abs(diff) > tol:
                    problems.append(f"{g} {d}: A14 share {cell['share']} but the 2026 rates imply "
                                    f"{entry['implied_share_median']} (tolerance {tol})")
            cells.append(entry)

    noted = [e for e in cells if e.get("difference") is not None and abs(e["difference"]) >= 0.02]
    manifest = {
        "node": "A14",
        "check": "housing standards table reproduces the 2026 BAH rates",
        "generated_at": agg.now_utc(),
        "inputs": {"B4": args.bah_rates.name, "A14": args.standards.name},
        "input_sha256": {"B4": agg.sha256(args.bah_rates), "A14": agg.sha256(args.standards)},
        "method": {"anchors": {t: f"{g} {d} dependents" for t, (g, d) in ANCHORS.items()},
                   "interpolated": "cost = lower + share x (upper - lower)",
                   "above_top_anchor": "cost = lower x (1 + share)",
                   "rate": "cost - cost_share_monthly",
                   "without_floor": f"rates within ${FLOOR_MARGIN:.0f} of {FLOOR_SHARE:.0%} of the "
                                    "with-dependents rate are set by the floor and left out",
                   "tolerance": {"interpolated": TOL_INTERPOLATED, "above_top_anchor": TOL_ABOVE_TOP}},
        "mhas": len(mhas),
        "cells": cells,
        "cells_at_75pct_floor": floor_cells,
        "differences_of_0_02_or_more": [f"{e['grade']} {e['dependents']}: A14 {e['share']}, implied "
                                        f"{e['implied_share_median']}" for e in noted],
        "verdict": "FAIL" if problems else "PASS",
        "problems": problems,
    }
    agg.write_manifest(args.out / "standards_check_manifest.json", manifest)

    print(f"A14 standards check: {len(cells)} cells x {len(mhas)} MHAs against the 2026 rates")
    worst = max((e for e in cells if e.get("difference") is not None), key=lambda e: abs(e["difference"]))
    print(f"  largest difference: {worst['grade']} {worst['dependents']} A14 {worst['share']} vs implied "
          f"{worst['implied_share_median']}")
    print(f"  {floor_cells} MHA cells set by the 75% without-dependents floor (left out)")
    for e in noted:
        print(f"  note: {e['grade']} {e['dependents']}: A14 {e['share']}, the rates imply {e['implied_share_median']}")
    print(f"  -> {args.out / 'standards_check_manifest.json'}")
    agg.fail_if(problems, TOOL)


if __name__ == "__main__":
    main()
