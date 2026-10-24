#!/usr/bin/env python3
"""
build_grid.py  (B3 + B4 + A14 + B29 + B30 + B11 flags + B22 -> B31 rank x dependents x home type grid)

Decisions D18-D20 (18 Oct 2026). The map lets a user pick any rank (E-1 to O-9),
with or without dependents, in any of DoD's six home types or the grade's own DoD
standard. Precomputing all 322 views per mode would be about 60 MB, so B31
carries the factors instead (data contract section 5b) and the browser computes
each view with the formula in ICD 5b.4:

  per area   BAH for the 23 ranks x 2 dependency statuses (B4), and for each mode
             the six home-type benchmarks (B29 rent, B30 ownership), each with its
             status and caveat ids
  top level  the rank, dependents and home-type orders, the 46 member cost shares
             and the 46 DoD standards (A14)

    python pipeline/handoff/build_grid.py --year 2026 \
        --names data/interim/bah_2026/mha_names.csv \
        --bah-rates data/interim/bah_2026/bah_rates.csv \
        --rent-by-type data/interim/benchmarks_2026/mha_rent_by_type.csv \
        --own-by-type data/interim/benchmarks_2026/mha_ownership_by_type.csv \
        --ownership data/interim/benchmarks_2026/mha_ownership.csv \
        --build-manifest data/processed/handoff/build_manifest_2026.json \
        --out data/processed/handoff/grid_2026.json

Costs carry cents (ICD 5b.3) so the browser's ratios for the research profiles
equal B20's to the fourth decimal; BAH and cost shares are whole dollars. Areas
follow B20: real MHAs with values, County Cost Groups with BAH only
(ccg_no_benchmark), the territory bucket with nothing (no_rate). Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import contract as c
from build_payload import INSURANCE_CAVEAT_YEAR, buy_caveats

TOOL = "build_grid"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "benchmarks"))
import home_types as ht  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--names", type=Path, required=True, help="B3 mha_names.csv")
    ap.add_argument("--bah-rates", type=Path, required=True, help="B4 bah_rates.csv")
    ap.add_argument("--rent-by-type", type=Path, required=True, help="B29 mha_rent_by_type.csv")
    ap.add_argument("--own-by-type", type=Path, required=True, help="B30 mha_ownership_by_type.csv")
    ap.add_argument("--ownership", type=Path, required=True, help="B11 mha_ownership.csv (tax/insurance flags)")
    ap.add_argument("--build-manifest", type=Path, required=True, help="B22, whose hash is the build_id")
    ap.add_argument("--standards", type=Path, default=ht.STANDARDS)
    ap.add_argument("--ownership-config", type=Path, default=ROOT / "config" / "ownership.json")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    std = ht.load(args.standards)
    if std.get("bah_year") != args.year:
        c.die(TOOL, f"config/housing_standards.json is for {std.get('bah_year')}, not {args.year}")
    if tuple(t["id"] for t in std["home_types"]) != c.HOME_TYPES:
        c.die(TOOL, f"A14 home types differ from the contract's {c.HOME_TYPES}")
    if c.read_json(args.ownership_config, TOOL).get("insurance", {}).get("data_year") != INSURANCE_CAVEAT_YEAR:
        c.die(TOOL, "insurance data_year differs from the contract's insurance caveat year")
    if not args.build_manifest.exists():
        c.die(TOOL, f"B22 not found: {args.build_manifest} (run build_manifest.py first)")
    ranks = list(std["grades"])

    names = c.read_csv(args.names, {"mha", "name", "mha_class"}, TOOL)
    bah = {(r["mha"], r["pay_grade"].upper(), "with" if r["has_dependents"].strip().lower() in ("true", "1")
            else "without"): r["monthly_rate"]
           for r in c.read_csv(args.bah_rates, {"mha", "pay_grade", "has_dependents", "monthly_rate"}, TOOL)}
    rent = {(r["mha"], r["home_type"]): r for r in c.read_csv(
        args.rent_by_type, {"mha", "home_type", "rent_monthly", "factor_source", "status"}, TOOL)}
    own = {(r["mha"], r["home_type"]): r for r in c.read_csv(
        args.own_by_type, {"mha", "home_type", "own_housing_monthly", "own_total_monthly", "building_source",
                           "bedroom_source", "status"}, TOOL)}
    flags = {r["mha"]: r for r in c.read_csv(args.ownership, {"mha", "tax_source", "insurance_source"}, TOOL)}

    problems: list[str] = []
    areas: dict[str, dict] = {}
    counts = {m: {} for m in c.MODES}
    for r in sorted(names, key=lambda r: r["mha"]):
        code, cls = r["mha"].strip().upper(), r["mha_class"].strip().lower()
        if not c.CODE.match(code) or cls not in c.CLASSES:
            problems.append(f"B3 row {code!r} has class {cls!r}")
            continue
        entry: dict = {"class": cls, "bah": {d: [c.dollars(bah.get((code, g, d))) for g in ranks]
                                             for d in c.GRID_DEPENDENTS}}
        has_rate = any(v is not None for d in c.GRID_DEPENDENTS for v in entry["bah"][d])
        if cls == "mha" and not all(v is not None for d in c.GRID_DEPENDENTS for v in entry["bah"][d]):
            problems.append(f"{code}: B4 lacks a rate for some of the 46 rank and dependents cells")
        for mode in c.MODES:
            block: dict = {"cost": [], **({"own_housing": []} if mode == "buy" else {}), "status": [], "caveats": []}
            for t in c.HOME_TYPES:
                if cls == "mha":
                    row = (rent if mode == "rent" else own).get((code, t))
                    if row is None:
                        problems.append(f"{code} {t}: no {'B29' if mode == 'rent' else 'B30'} row")
                        continue
                    status = row["status"]
                    if status not in c.STATUSES[mode]:
                        problems.append(f"{code} {t} {mode}: status {status!r} is not in the contract")
                        continue
                    if mode == "rent":
                        cost = row["rent_monthly"] if status == "ok" else None
                        cav = ["utilities_grossed_up"] if status == "ok" else []
                        national = row["factor_source"] == "national"
                    else:
                        cost = (row["own_total_monthly"] if status == "ok"
                                else row["own_housing_monthly"] if status == "piti_only_no_zori" else None)
                        cav = buy_caveats(status, flags.get(code))
                        national = "national" in (row["building_source"], row["bedroom_source"])
                        block["own_housing"].append(c.cents(row["own_housing_monthly"])
                                                    if status in ("ok", "piti_only_no_zori") else None)
                    if national and status in ("ok", "piti_only_no_zori"):
                        cav.append("type_factor_national")
                else:
                    status = "ccg_no_benchmark" if (cls == "ccg" and has_rate) else "no_rate"
                    cost, cav = None, (["ccg_no_benchmark"] if status == "ccg_no_benchmark" else [])
                    if mode == "buy":
                        block["own_housing"].append(None)
                block["cost"].append(c.cents(cost))
                block["status"].append(status)
                block["caveats"].append(sorted(cav, key=list(c.CAVEATS).index))
                counts[mode][status] = counts[mode].get(status, 0) + 1
            entry[mode] = block
        areas[code] = entry
    c.fail_if(problems[:40], TOOL)

    grid = {
        **c.header(args.build_manifest, args.year),
        "ranks": ranks,
        "dependents": list(c.GRID_DEPENDENTS),
        "home_types": list(c.HOME_TYPES),
        "modes": list(c.MODES),
        "cost_share_monthly": {d: [std["cost_share_monthly"][g][d] for g in ranks] for d in c.GRID_DEPENDENTS},
        "standards": {d: [std["standards"][g][d] for g in ranks] for d in c.GRID_DEPENDENTS},
        "areas": areas,
    }
    c.write_json(args.out, grid)
    by_class = {cls: sum(a["class"] == cls for a in areas.values()) for cls in c.CLASSES}
    print(f"B31 grid: {len(areas)} areas ({by_class['mha']} MHA, {by_class['ccg']} CCG, {by_class['unknown']} "
          f"territory) x {len(ranks)} ranks x 2 dependency statuses x {len(c.HOME_TYPES)} home types")
    for mode in c.MODES:
        print(f"  {mode:4} home-type statuses: {json.dumps(counts[mode], sort_keys=True)}")
    print(f"  {args.out.stat().st_size / 1024:.0f} KB -> {args.out}")


if __name__ == "__main__":
    main()
