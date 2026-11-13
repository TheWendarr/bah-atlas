#!/usr/bin/env python3
"""
zip_ownership_by_type.py  (B9 + B30 + A9 + A8 + A8 rollup + A7 + B1 -> B34 ownership cost by home type for each ZIP)

Decision D36 (13 Nov 2026), the ZIP view, buy mode: the monthly cost of owning each
of DoD's six home types in every ZIP code of a real MHA, with B11's model and B30's
home-type factors.

    python pipeline/benchmarks/zip_ownership_by_type.py \
        --zip-zhvi data/interim/benchmarks_2026/zip_zhvi.csv \
        --zhvi data/interim/benchmarks_2026/mha_zhvi.csv \
        --own-by-type data/interim/benchmarks_2026/mha_ownership_by_type.csv \
        --tax-insurance data/interim/benchmarks_2026/mha_tax_insurance.csv \
        --acs data/raw/acs5_2024_zcta.json \
        --fio data/raw/Supporting_Underlying_Metrics_and_Disclaimer_for_Analyses_of_US_Homeowners_Insurance_Markets_2018-2022.xlsx \
        --pmms data/raw/PMMS_history.csv \
        --crosswalk data/interim/bah_2026/zip_mha.csv \
        --out data/interim/benchmarks_2026

------------------------------------------------------------------------------
Method (per ZIP z in MHA m and home type t), M8 plan Z3, Z4, Z9
------------------------------------------------------------------------------
  value(t)   ZHVI(z) x B30 home_value(m, t) / B9 zhvi_median(m)
             The MHA's home-type factors (B30's value over B9's), never one ZIP's.
  tax rate   the ZIP's ZCTA effective rate from A9 (taxes / value, as the A8 rollup
             computes it for an MHA) where usable and in (0, 5%); otherwise the MHA's
  premium    the ZIP's FIO premium per policy (A8) where published; otherwise the MHA's
  cost       B11's model unchanged (config/ownership.json, B30's mortgage-rate window):
               own_housing_monthly(t) = P&I + tax + insurance + MI
               own_total_monthly(t)   = own_housing_monthly(t) + B30 utilities_usd(m, t)
             Utilities stay at the MHA's estimate: DTMO publishes its rent/utilities
             split by MHA, not by ZIP.

  Band (Z9): a ZHVI outside [1/3, 3] x the MHA's B9 value is not used (zip_outlier).

Status per row: ok | piti_only_no_zori (the MHA has no utilities estimate, as in B30)
| zip_no_benchmark (Zillow publishes no ZHVI for the ZIP) | zip_outlier.

Identity: the MHA's own value, tax rate and premium reproduce B30's PITI in every MHA
and home type (to the cent), so B34 and B30 run one model.

Output: zip_ownership_by_type.csv (long: ZIP x home type) and its manifest.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fio_insurance as fio  # noqa: E402
import home_types as ht  # noqa: E402
import mha_agg as agg  # noqa: E402
import ownership_cost as oc  # noqa: E402
import tax_insurance_to_mha as ti  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "handoff"))
import contract as c  # noqa: E402

TOOL = "zip_ownership_by_type"
IDENTITY_TOLERANCE = 0.011        # B30 rounds the home value and PITI to cents


def read(path: Path, needed: set[str]) -> list[dict]:
    if not path.exists():
        agg.die(TOOL, f"not found: {path}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not needed <= set(reader.fieldnames):
            agg.die(TOOL, f"{path.name} needs {sorted(needed)}; found {reader.fieldnames}")
        return list(reader)


def num(raw: str | None) -> float | None:
    s = (raw or "").strip()
    return float(s) if s else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip-zhvi", type=Path, required=True, help="B9 zip_zhvi.csv")
    ap.add_argument("--zhvi", type=Path, required=True, help="B9 mha_zhvi.csv")
    ap.add_argument("--own-by-type", type=Path, required=True, help="B30 mha_ownership_by_type.csv")
    ap.add_argument("--tax-insurance", type=Path, required=True, help="A8 rollup mha_tax_insurance.csv")
    ap.add_argument("--acs", type=Path, required=True, help="A9 ACS ZCTA table")
    ap.add_argument("--fio", type=Path, required=True, help="A8 FIO workbook")
    ap.add_argument("--pmms", type=Path, required=True, help="A7 PMMS_history.csv")
    ap.add_argument("--crosswalk", type=Path, required=True, help="B1 zip_mha.csv")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "ownership.json")
    ap.add_argument("--standards", type=Path, default=ht.STANDARDS)
    ap.add_argument("--window", help="YYYY-MM:YYYY-MM, as passed to B11 and B30 (default: the B9 window)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    crosswalk, cw_stats = agg.load_crosswalk(args.crosswalk, TOOL)
    types = [t["id"] for t in ht.types(ht.load(args.standards))]
    cfg = oc.load_config(args.config)
    loan = cfg["loan"]
    spec = args.window or oc.window_from_b9(args.zhvi)
    if spec is None:
        agg.die(TOOL, f"mha_zhvi_manifest.json not found beside {args.zhvi} (run `make zhvi`)")
    try:
        window = agg.parse_window(spec)
    except ValueError as e:
        agg.die(TOOL, str(e))
    rate, _, rates = oc.read_pmms(args.pmms, window)

    b9 = {r["mha"]: num(r["zhvi_median"]) for r in read(args.zhvi, {"mha", "zhvi_median"})}
    zhvi = {r["zip"]: float(r["value"]) for r in read(args.zip_zhvi, {"zip", "mha", "value"}) if r["value"].strip()}
    b30 = {(r["mha"], r["home_type"]): r for r in read(
        args.own_by_type, {"mha", "home_type", "home_value", "own_housing_monthly", "utilities_usd", "building_source",
                           "bedroom_source", "status"})}
    mha_ti = oc.read_tax_insurance(args.tax_insurance)
    zcta_tax, _ = ti.read_acs(args.acs)
    zip_rate = {z: t / v for z, (t, v) in zcta_tax.items() if ti.RATE_RANGE[0] < t / v < ti.RATE_RANGE[1]}
    zip_premium, _ = fio.read(args.fio, cfg["insurance"]["data_year"], TOOL)
    zip_premium = {z: p for z, p in zip_premium.items() if ti.PREMIUM_RANGE[0] < p < ti.PREMIUM_RANGE[1]}

    mhas = sorted(set(crosswalk.values()))
    problems = []
    if set(b9) != set(mhas):
        problems.append("B9 and B1 cover different MHAs")
    gaps = [f"{m} {t}" for m in mhas for t in types if (m, t) not in b30]
    if gaps:
        problems.append(f"B30 lacks {len(gaps)} MHA x type row(s): {', '.join(gaps[:10])} (run `make own-types`)")
    missing = [m for m in mhas if m not in mha_ti]
    if missing:
        problems.append(f"{len(missing)} MHA(s) have no tax/insurance row: {', '.join(missing[:10])}")
    agg.fail_if(problems, TOOL)

    n_months = int(loan["term_years"] * 12)
    fee_mult = (1 + loan["funding_fee_share"]) if loan["funding_fee_financed"] else 1.0
    down, mi_share = loan["down_payment_share"], loan["mortgage_insurance_annual_share"]

    def piti(v: float, tax_rate: float, premium: float) -> float:
        """B11's arithmetic, in B11's order (as B30 runs it)."""
        loan_amt = v * (1 - down) * fee_mult
        return (oc.payment(loan_amt, rate, n_months) + v * tax_rate / 12 + premium / 12
                + loan_amt * mi_share / 12)

    # Identity: the MHA's own inputs reproduce B30.
    identity_fail = []
    for m in mhas:
        tax_m, prem_m = float(mha_ti[m]["effective_tax_rate"]), float(mha_ti[m]["insurance_annual_usd"])
        for t in types:
            r = b30[(m, t)]
            value, want = num(r.get("home_value")), num(r["own_housing_monthly"])
            if (value is None) != (want is None) or (value is not None and abs(piti(value, tax_m, prem_m) - want)
                                                     > IDENTITY_TOLERANCE):
                identity_fail.append(f"{m} {t}")
    agg.fail_if([f"the MHA's own inputs do not reproduce B30 in {len(identity_fail)} MHA x type cell(s): "
                 f"{', '.join(identity_fail[:10])} (rebuild B30 and B34 from the same inputs)"] if identity_fail
                else [], TOOL)

    def mha_flag(raw: str) -> str:
        return "state_fallback" if raw == "state_fallback" else "mha"

    rows, by_status = [], {}
    tax_from_zip = premium_from_zip = 0
    for z in sorted(crosswalk):
        m = crosswalk[z]
        med = b9[m]
        tax_rate, tax_src = ((zip_rate[z], "zip") if z in zip_rate
                             else (float(mha_ti[m]["effective_tax_rate"]), mha_flag(mha_ti[m]["tax_source"])))
        premium, ins_src = ((zip_premium[z], "zip") if z in zip_premium
                            else (float(mha_ti[m]["insurance_annual_usd"]), mha_flag(mha_ti[m]["insurance_source"])))
        value_z = zhvi.get(z)
        if med is None or value_z is None:
            status = "zip_no_benchmark"
        elif not c.ZIP_BAND[0] <= value_z / med <= c.ZIP_BAND[1]:
            status = "zip_outlier"
        else:
            status = None                         # decided per type: utilities may be missing
            tax_from_zip += tax_src == "zip"
            premium_from_zip += ins_src == "zip"
        for t in types:
            r = b30[(m, t)]
            out = {"zip": z, "mha": m, "home_type": t, "zhvi_ratio": "", "home_value": "", "tax_rate": "",
                   "tax_source": "", "insurance_annual_usd": "", "insurance_source": "", "own_housing_monthly": "",
                   "utilities_usd": "", "own_total_monthly": "", "building_source": r["building_source"],
                   "bedroom_source": r["bedroom_source"], "status": status}
            mha_value = num(r.get("home_value"))
            if status is None and mha_value is not None:
                v = value_z * mha_value / med
                housing = piti(v, tax_rate, premium)
                util = num(r["utilities_usd"])
                out.update({"zhvi_ratio": agg.fmt(value_z / med, 4), "home_value": agg.fmt(v),
                            "tax_rate": f"{tax_rate:.6f}", "tax_source": tax_src,
                            "insurance_annual_usd": agg.fmt(premium), "insurance_source": ins_src,
                            "own_housing_monthly": agg.fmt(housing), "utilities_usd": agg.fmt(util),
                            "own_total_monthly": agg.fmt(housing + util) if util is not None else "",
                            "status": "ok" if util is not None else "piti_only_no_zori"})
            elif status is None:
                out["status"] = "zip_no_benchmark"
            by_status[out["status"]] = by_status.get(out["status"], 0) + 1
            rows.append(out)

    fields = ["zip", "mha", "home_type", "zhvi_ratio", "home_value", "tax_rate", "tax_source", "insurance_annual_usd",
              "insurance_source", "own_housing_monthly", "utilities_usd", "own_total_monthly", "building_source",
              "bedroom_source", "status"]
    agg.write_csv(args.out / "zip_ownership_by_type.csv", fields, rows)

    zips_valued = sum(1 for r in rows if r["home_type"] == ht.REFERENCE and r["home_value"])
    ratios = [float(r["zhvi_ratio"]) for r in rows if r["zhvi_ratio"] and r["home_type"] == ht.REFERENCE]
    warnings = []
    outliers = by_status.get("zip_outlier", 0) // len(types)
    if outliers:
        warnings.append(f"{outliers} ZIP(s) have a ZHVI outside the band (status zip_outlier)")

    inputs = {"B9.zip": args.zip_zhvi, "B9": args.zhvi, "B30": args.own_by_type, "A8.rollup": args.tax_insurance,
              "A9": args.acs, "A8": args.fio, "A7": args.pmms, "B1": args.crosswalk, "A14": args.standards}
    manifest = {
        "node": "B34",
        "generated_at": agg.now_utc(),
        "inputs": {k: v.name for k, v in inputs.items()},
        "input_sha256": {k: agg.sha256(v) for k, v in inputs.items()},
        "config": str(args.config.relative_to(ROOT)) if args.config.is_relative_to(ROOT) else str(args.config),
        "config_sha256": agg.sha256(args.config),
        "window_months": f"{window[0]}:{window[1]}",
        "rate": {"series": "pmms30", "weeks": len(rates), "mean_pct": round(rate, 4)},
        "decision": "D36 (13 Nov 2026): ZIP view; the ZIP's ZHVI with the MHA's B30 home-type factors; ZIP tax "
                    "rate and premium where published; MHA utilities; values outside the band left out",
        "method": {
            "home_value": "ZHVI(z) x B30 home_value(m, t) / B9 zhvi_median(m)",
            "tax_rate": "A9 taxes / value for the ZIP's ZCTA, in (0, 5%); else the MHA's (A8 rollup)",
            "insurance": "A8 premium per policy for the ZIP; else the MHA's (A8 rollup)",
            "cost": "B11 model (config/ownership.json): P&I + tax + insurance + MI, plus B30 utilities_usd(m, t)",
            "band": f"ZHVI(z) / B9 zhvi_median(m) within [{c.ZIP_BAND[0]:.4f}, {c.ZIP_BAND[1]}]",
        },
        "crosswalk": cw_stats,
        "coverage": {"zips": len(crosswalk), "zips_with_value": zips_valued,
                     "zips_tax_rate_from_zip": tax_from_zip, "zips_premium_from_zip": premium_from_zip,
                     "rows_by_status": by_status},
        "zhvi_ratio_summary": ({"min": round(min(ratios), 4), "median": round(statistics.median(ratios), 4),
                                "max": round(max(ratios), 4)} if ratios else None),
        "model_identity": "the MHA's own value, tax rate and premium reproduce B30 in every MHA and home type (checked)",
        "limitations": ["utilities are the MHA's estimate in every ZIP", "a ZCTA's ACS tax estimate rests on a small "
                        "sample in thinly populated ZIPs; rates outside (0, 5%) are not used"],
        "warnings": warnings,
        "outputs": ["zip_ownership_by_type.csv"],
    }
    agg.write_manifest(args.out / "zip_ownership_by_type_manifest.json", manifest)

    print(f"B34 ownership cost by home type per ZIP: {len(crosswalk):,} ZIPs, {zips_valued:,} with a value")
    print(f"  tax rate from the ZIP in {tax_from_zip:,}, premium from the ZIP in {premium_from_zip:,}")
    print(f"  rows by status: {by_status}")
    print("  the MHA's own inputs reproduce B30 in every MHA")
    for w in warnings:
        print(f"  warning: {w}")
    print(f"  -> {args.out / 'zip_ownership_by_type.csv'}")


if __name__ == "__main__":
    main()
