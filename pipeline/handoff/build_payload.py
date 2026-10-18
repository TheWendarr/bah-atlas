#!/usr/bin/env python3
"""
build_payload.py  (B3 + B4 + B11 + B12-B15 + A12 + B22 -> B20 attribute payload)

Packs the measured values for every area code into the attribute payload the map
joins to the B7 polygons (data contract section 5). It computes nothing new:
every number comes from B4 or the B12-B15 tables, rounded per the contract
(ratios to 4 decimals, dollars whole, half away from zero).

    python pipeline/handoff/build_payload.py --year 2026 \
        --names data/interim/bah_2026/mha_names.csv \
        --bah-rates data/interim/bah_2026/bah_rates.csv \
        --rent data/interim/metrics_2026/mha_rent_metrics.csv \
        --buy data/interim/metrics_2026/mha_buy_metrics.csv \
        --ownership data/interim/benchmarks_2026/mha_ownership.csv \
        --spatial-manifest data/interim/spatial_2026/spatial_stats_manifest.json \
        --build-manifest data/processed/handoff/build_manifest_2026.json \
        --out data/processed/handoff/payload_2026.json

Areas: every code in the DTMO registry (B3): real MHAs with their B12-B15 values,
County Cost Groups with their BAH rate only (status ccg_no_benchmark, decision
N1), and the territory bucket (status no_rate). `cluster_scope` is true only for
the MHAs the spatial statistics tested the scope of (CONUS; decision 2.2).
Stdlib only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import contract as c

TOOL = "build_payload"
ROOT = Path(__file__).resolve().parents[2]
INSURANCE_CAVEAT_YEAR = 2022   # the year in the caveat id insurance_2022_dollars


def value_block(mode: str, row: dict | None, status: str) -> dict:
    """One profile x mode block, every contract field present, nulls per ICD 5.4."""
    allowed = c.NON_NULL[status]
    out: dict = {"status": status}
    for f in c.MODE_FIELDS[mode]:
        raw = row.get(f) if row else None
        if allowed != "all" and f not in allowed:
            raw = None
        out[f] = c.dollars(raw) if f in c.DOLLAR_FIELDS else c.ratio(raw)
    return out


def buy_caveats(status: str, own: dict | None) -> list[str]:
    if status not in ("ok", "piti_only_no_zori"):
        return []
    caveats = ["piti_only_no_zori"] if status == "piti_only_no_zori" else []
    tax, ins = (own or {}).get("tax_source"), (own or {}).get("insurance_source")
    if tax == "locality" and ins == "locality":
        caveats.append("tax_insurance_locality")
    if tax == "state_fallback":
        caveats.append("tax_state_fallback")
    if ins == "state_fallback":
        caveats.append("insurance_state_fallback")
    caveats.append("insurance_2022_dollars")
    return caveats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--names", type=Path, required=True, help="B3 mha_names.csv")
    ap.add_argument("--bah-rates", type=Path, required=True, help="B4 bah_rates.csv")
    ap.add_argument("--rent", type=Path, required=True, help="B12/B13 mha_rent_metrics.csv")
    ap.add_argument("--buy", type=Path, required=True, help="B14/B15 mha_buy_metrics.csv")
    ap.add_argument("--ownership", type=Path, required=True, help="B11 mha_ownership.csv (tax/insurance flags)")
    ap.add_argument("--spatial-manifest", type=Path, required=True, help="B17/B18 manifest (cluster scope)")
    ap.add_argument("--build-manifest", type=Path, required=True, help="B22, whose hash is the build_id")
    ap.add_argument("--profiles", type=Path, default=ROOT / "config" / "profiles.json")
    ap.add_argument("--ownership-config", type=Path, default=ROOT / "config" / "ownership.json")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    profiles_cfg = c.read_json(args.profiles, TOOL)
    if profiles_cfg.get("bah_year") != args.year:
        c.die(TOOL, f"config/profiles.json is for {profiles_cfg.get('bah_year')}, not {args.year}")
    profiles = profiles_cfg["profiles"]
    data_year = c.read_json(args.ownership_config, TOOL).get("insurance", {}).get("data_year")
    if data_year != INSURANCE_CAVEAT_YEAR:
        c.die(TOOL, f"insurance data_year is {data_year}, but the contract's caveat id is "
                    f"insurance_{INSURANCE_CAVEAT_YEAR}_dollars; revise the ICD caveat list first")
    if not args.build_manifest.exists():
        c.die(TOOL, f"B22 not found: {args.build_manifest} (run build_manifest.py first)")

    names = c.read_csv(args.names, {"mha", "name", "mha_class"}, TOOL)
    bah = {(r["mha"], r["pay_grade"].upper(), r["has_dependents"].strip().lower()): r["monthly_rate"]
           for r in c.read_csv(args.bah_rates, {"mha", "pay_grade", "has_dependents", "monthly_rate"}, TOOL)}
    rent = {(r["profile"], r["mha"]): r for r in c.read_csv(args.rent, {"profile", "mha", "status"}, TOOL)}
    buy = {(r["profile"], r["mha"]): r for r in c.read_csv(args.buy, {"profile", "mha", "status"}, TOOL)}
    own = {r["mha"]: r for r in c.read_csv(args.ownership, {"mha", "tax_source", "insurance_source"}, TOOL)}
    excluded = set(c.read_json(args.spatial_manifest, TOOL).get("scope", {}).get("excluded", []))

    problems: list[str] = []
    areas: dict[str, dict] = {}
    counts: dict[str, dict[str, int]] = {m: {} for m in c.MODES}
    for r in sorted(names, key=lambda r: r["mha"]):
        code, cls = r["mha"].strip().upper(), r["mha_class"].strip().lower()
        if not c.CODE.match(code) or cls not in c.CLASSES:
            problems.append(f"B3 row {code!r} has class {cls!r}; expected a code like CO018 and one of {c.CLASSES}")
            continue
        scope = cls == "mha" and code not in excluded
        entry: dict = {"class": cls, "cluster_scope": scope,
                       "caveats": (["ccg_geometry"] if cls != "mha" else []) +
                                  ([] if scope else ["outside_cluster_scope"])}
        for p in profiles:
            grade, deps = p["pay_grade"].upper(), str(bool(p["has_dependents"])).lower()
            blocks: dict = {}
            for mode, table in (("rent", rent), ("buy", buy)):
                row = table.get((p["id"], code))
                if cls == "mha":
                    if row is None:
                        problems.append(f"{code} {p['id']}: no {mode} row in B12-B15")
                        continue
                    status = row["status"]
                    if status not in c.STATUSES[mode]:
                        problems.append(f"{code} {p['id']} {mode}: status {status!r} is not in the contract")
                        continue
                    block = value_block(mode, row, status)
                    caveats = (["utilities_grossed_up"] if mode == "rent" and status == "ok"
                               else buy_caveats(status, own.get(code)) if mode == "buy" else [])
                else:
                    rate = bah.get((code, grade, deps))
                    status = "ccg_no_benchmark" if (cls == "ccg" and rate) else "no_rate"
                    block = value_block(mode, {"bah_monthly": rate, "cost_share_monthly": p["cost_share_monthly"]},
                                        status)
                    caveats = ["ccg_no_benchmark"] if status == "ccg_no_benchmark" else []
                block["caveats"] = caveats
                blocks[mode] = block
                counts[mode][status] = counts[mode].get(status, 0) + 1
            entry[p["id"]] = blocks
        areas[code] = entry
    c.fail_if(problems, TOOL)

    payload = {**c.header(args.build_manifest, args.year),
               "profiles": [p["id"] for p in profiles], "modes": list(c.MODES), "areas": areas}
    c.write_json(args.out, payload)
    by_class = {cls: sum(a["class"] == cls for a in areas.values()) for cls in c.CLASSES}
    print(f"B20 attribute payload: {len(areas)} areas ({by_class['mha']} MHA, {by_class['ccg']} CCG, "
          f"{by_class['unknown']} territory), {len(profiles)} profiles x 2 modes; "
          f"{sum(a['cluster_scope'] for a in areas.values())} in cluster scope")
    for mode in c.MODES:
        print(f"  {mode:4} statuses: {json.dumps(counts[mode], sort_keys=True)}")
    print(f"  {args.out.stat().st_size / 1024:.0f} KB -> {args.out}")


if __name__ == "__main__":
    main()
