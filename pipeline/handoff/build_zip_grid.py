#!/usr/bin/env python3
"""
build_zip_grid.py  (B33 + B34 + B35 features + B22 -> B36 ZIP grid)

The ZIP view's values (decision D36, data contract section 5c): for every ZIP code
the B35 tiles draw, its MHA code and the six home-type costs to rent and to buy,
each with its status and caveat ids, in the shape of a B31 area entry without BAH.
A ZIP's caveat list is written as an index into the top-level `caveat_sets`, because
the same few lists repeat in every ZIP and would otherwise make up most of the file.
BAH is set by MHA, so the browser takes it, and the cost share and standards, from
B31 by the ZIP's `area` and runs the same section 5b.4 formula (ICD 5c.3).

    python pipeline/handoff/build_zip_grid.py --year 2026 \
        --zip-rent data/interim/benchmarks_2026/zip_rent_by_type.csv \
        --zip-own data/interim/benchmarks_2026/zip_ownership_by_type.csv \
        --features data/processed/zipcodes_2026_features.csv \
        --build-manifest data/processed/handoff/build_manifest_2026.json \
        --out data/processed/handoff/zipgrid_2026.json

Costs are whole dollars (M8 plan Z8): no ZIP value has a B20 counterpart to match to
the fourth decimal. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import contract as c

TOOL = "build_zip_grid"


def rent_caveats(row: dict) -> list[str]:
    if row["status"] != "ok":
        return []
    cav = ["utilities_grossed_up"]
    if row["base_source"] == "safmr_scaled":
        cav.append("zip_safmr_scaled")
    if row["factor_source"] == "national":
        cav.append("type_factor_national")
    return cav


def buy_caveats(row: dict) -> list[str]:
    if row["status"] not in c.ZIP_VALUED:
        return []
    cav = ["piti_only_no_zori"] if row["status"] == "piti_only_no_zori" else []
    cav.append("zip_tax_insurance")
    if row["tax_source"] == "state_fallback":
        cav.append("tax_state_fallback")
    if row["insurance_source"] == "state_fallback":
        cav.append("insurance_state_fallback")
    cav.append("insurance_2022_dollars")
    if "national" in (row["building_source"], row["bedroom_source"]):
        cav.append("type_factor_national")
    return cav


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--zip-rent", type=Path, required=True, help="B33 zip_rent_by_type.csv")
    ap.add_argument("--zip-own", type=Path, required=True, help="B34 zip_ownership_by_type.csv")
    ap.add_argument("--features", type=Path, required=True, help="B35 zipcodes_<year>_features.csv")
    ap.add_argument("--build-manifest", type=Path, required=True, help="B22, whose hash is the build_id")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    features = {r["zip"]: r["area"] for r in c.read_csv(args.features, {"zip", "area"}, TOOL)}
    rent = {(r["zip"], r["home_type"]): r for r in c.read_csv(
        args.zip_rent, {"zip", "mha", "home_type", "base_source", "rent_monthly", "factor_source", "status"}, TOOL)}
    own = {(r["zip"], r["home_type"]): r for r in c.read_csv(
        args.zip_own, {"zip", "mha", "home_type", "own_housing_monthly", "own_total_monthly", "tax_source",
                       "insurance_source", "building_source", "bedroom_source", "status"}, TOOL)}

    problems: list[str] = []
    zips: dict[str, dict] = {}
    caveat_sets: list[list[str]] = [[]]
    set_index: dict[tuple[str, ...], int] = {(): 0}
    counts = {m: {} for m in c.MODES}
    for z in sorted(features):
        area = features[z]
        if not c.ZIP.match(z) or not c.CODE.match(area):
            problems.append(f"B35 feature row ZIP {z!r}, area {area!r} is malformed")
            continue
        entry: dict = {"area": area}
        for mode, table in (("rent", rent), ("buy", own)):
            block: dict = {"cost": [], **({"own_housing": []} if mode == "buy" else {}), "status": [], "caveats": []}
            for t in c.HOME_TYPES:
                row = table.get((z, t))
                if row is None:
                    problems.append(f"ZIP {z} {t}: no {'B33' if mode == 'rent' else 'B34'} row")
                    continue
                if row["mha"] != area:
                    problems.append(f"ZIP {z}: {'B33' if mode == 'rent' else 'B34'} places it in {row['mha']}, "
                                    f"B35 in {area}")
                status = row["status"]
                if status not in c.ZIP_STATUSES[mode]:
                    problems.append(f"ZIP {z} {t} {mode}: status {status!r} is not in the contract")
                    continue
                valued = status in c.ZIP_VALUED
                if mode == "rent":
                    cost, cav = (row["rent_monthly"] if valued else None), rent_caveats(row)
                else:
                    cost = (row["own_total_monthly"] if status == "ok"
                            else row["own_housing_monthly"] if status == "piti_only_no_zori" else None)
                    cav = buy_caveats(row)
                    block["own_housing"].append(c.dollars(row["own_housing_monthly"]) if valued else None)
                block["cost"].append(c.dollars(cost))
                block["status"].append(status)
                key = tuple(sorted(cav, key=list(c.CAVEATS).index))
                if key not in set_index:
                    set_index[key] = len(caveat_sets)
                    caveat_sets.append(list(key))
                block["caveats"].append(set_index[key])
                counts[mode][status] = counts[mode].get(status, 0) + 1
            entry[mode] = block
        zips[z] = entry
    c.fail_if(problems[:40], TOOL)

    doc = {
        **c.header(args.build_manifest, args.year),
        "home_types": list(c.HOME_TYPES),
        "modes": list(c.MODES),
        "caveat_sets": caveat_sets,
        "zips": zips,
    }
    c.write_json(args.out, doc)
    print(f"B36 ZIP grid: {len(zips):,} ZIPs in {len(set(features.values()))} MHAs x {len(c.HOME_TYPES)} home types")
    for mode in c.MODES:
        print(f"  {mode:4} home-type statuses: {json.dumps(counts[mode], sort_keys=True)}")
    print(f"  {args.out.stat().st_size / 1024:.0f} KB -> {args.out}")


if __name__ == "__main__":
    main()
