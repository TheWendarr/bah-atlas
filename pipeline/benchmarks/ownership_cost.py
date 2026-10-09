#!/usr/bin/env python3
"""
ownership_cost.py  (A7 + B9 [+ B8] -> B11 ownership monthly cost at MHA)

Turn each MHA's typical home value (B9 ZHVI) into the monthly cost of owning it,
so buy mode can be compared with BAH on the same monthly-dollar footing as rent.

    python pipeline/benchmarks/ownership_cost.py \
        --zhvi data/interim/benchmarks_2026/mha_zhvi.csv \
        --pmms data/raw/PMMS_history.csv \
        --zori data/interim/benchmarks_2026/mha_zori.csv \
        --out data/interim/benchmarks_2026

------------------------------------------------------------------------------
Model (parameters in config/ownership.json)
------------------------------------------------------------------------------
  V        = zhvi_median (B9)
  loan     = V * (1 - down_payment_share) * (1 + funding_fee_share)   [fee financed]
  r        = mean 30-year PMMS rate over the window / 12              (A7)
  P&I      = loan * r / (1 - (1 + r)^-n),  n = term_years * 12
  tax      = V * property_tax.annual_share / 12                       (placeholder until A8)
  ins      = insurance.annual_usd / 12                                (placeholder until A8)
  MI       = loan * mortgage_insurance_annual_share / 12              (0 for VA)

  own_housing_monthly = P&I + tax + ins + MI          ("PITI")
  own_total_monthly   = own_housing_monthly + utilities_usd (B8)

Default financing is a VA purchase loan, first use: 0% down, 2.15% funding fee
financed, no mortgage insurance. One rate applies nationwide (PMMS is a national
survey), so spatial variation in B11 comes from home values, plus utilities via B8.

------------------------------------------------------------------------------
Inputs
------------------------------------------------------------------------------
  --zhvi   B9 mha_zhvi.csv (needs mha, zhvi_median)
  --pmms   Freddie Mac PMMS_history.csv: date (M/D/YYYY), pmms30 (%) ...; blank
           cells may hold a single space
  --zori   B8 mha_zori.csv (optional; supplies utilities_usd). Without it,
           own_total_monthly is blank everywhere and the manifest says so.
  --window YYYY-MM:YYYY-MM for the rate average. Default: read from the B9
           manifest so rate and home value cover the same months; falls back to
           the BAH year.

------------------------------------------------------------------------------
Output (written to --out)
------------------------------------------------------------------------------
  mha_ownership.csv            mha, zhvi_median, loan_amount, rate_pct, pi_monthly,
                               tax_monthly, insurance_monthly, mi_monthly,
                               own_housing_monthly, utilities_usd, own_total_monthly
  mha_ownership_manifest.json  parameters used (with sources and placeholder
                               flags), PMMS weeks averaged, counts, warnings

------------------------------------------------------------------------------
Validation (loud)
------------------------------------------------------------------------------
  * every config field present and in range (shares in [0, 0.5), term 10-40 years)
  * PMMS has date + pmms30 columns, at least 4 weekly observations in the window,
    every rate in (0.5, 25) percent
  * MHA codes in B8 and B9 agree
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mha_agg as agg  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TOOL = "ownership_cost"
MIN_WEEKS = 4


def load_config(path: Path) -> dict:
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        agg.die(TOOL, f"config not found: {path}")
    except json.JSONDecodeError as e:
        agg.die(TOOL, f"{path} is not valid JSON: {e}")
    problems: list[str] = []

    def num(section: str, key: str, lo: float, hi: float) -> float:
        v = cfg.get(section, {}).get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v < hi:
            problems.append(f"{section}.{key} = {v!r}; expected a number in [{lo}, {hi})")
            return 0.0
        return float(v)

    num("loan", "term_years", 10, 41)
    num("loan", "down_payment_share", 0, 0.5)
    num("loan", "funding_fee_share", 0, 0.05)
    num("loan", "mortgage_insurance_annual_share", 0, 0.03)
    if not isinstance(cfg.get("loan", {}).get("funding_fee_financed"), bool):
        problems.append("loan.funding_fee_financed must be true or false")
    if cfg.get("loan", {}).get("rate_series") != "pmms30":
        problems.append("loan.rate_series must be 'pmms30' (the only series wired up)")
    if cfg.get("property_tax", {}).get("method") != "annual_share_of_value":
        problems.append("property_tax.method must be 'annual_share_of_value'")
    num("property_tax", "annual_share", 0, 0.05)
    if cfg.get("insurance", {}).get("method") != "flat_annual_usd":
        problems.append("insurance.method must be 'flat_annual_usd'")
    num("insurance", "annual_usd", 0, 50_000)
    for section in ("property_tax", "insurance"):
        if not cfg.get(section, {}).get("source"):
            problems.append(f"{section}.source is required (cite where the number comes from)")
    agg.fail_if(problems, TOOL)
    return cfg


def window_from_b9(zhvi_path: Path) -> str | None:
    man = zhvi_path.with_name("mha_zhvi_manifest.json")
    try:
        months = json.loads(man.read_text(encoding="utf-8"))["window_months_used"]
        return f"{months[0]}:{months[-1]}"
    except (OSError, KeyError, IndexError, json.JSONDecodeError):
        return None


def read_pmms(path: Path, window: tuple[str, str]) -> tuple[float, list[str], list[float]]:
    """Mean pmms30 over the window. Returns (mean %, dates used, rates)."""
    if not path.exists():
        agg.die(TOOL, f"PMMS file not found: {path} (run `make fetch`)")
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields = [f.strip() for f in (reader.fieldnames or [])]
        if not {"date", "pmms30"} <= set(fields):
            agg.die(TOOL, f"{path.name} needs date and pmms30 columns; found {fields[:12]}")
        reader.fieldnames = fields
        dates, rates, problems = [], [], []
        for line, row in enumerate(reader, start=2):
            raw_d, raw_r = (row.get("date") or "").strip(), (row.get("pmms30") or "").strip()
            if not raw_d:
                continue
            try:
                d = datetime.strptime(raw_d, "%m/%d/%Y").date()
            except ValueError:
                problems.append(f"line {line}: date {raw_d!r} is not M/D/YYYY")
                continue
            ym = f"{d.year:04d}-{d.month:02d}"
            if not window[0] <= ym <= window[1] or not raw_r:
                continue
            try:
                rate = float(raw_r)
            except ValueError:
                problems.append(f"line {line}: pmms30 {raw_r!r} is not a number")
                continue
            if not 0.5 < rate < 25:
                problems.append(f"line {line}: pmms30 {rate} outside 0.5-25%")
                continue
            dates.append(d.isoformat())
            rates.append(rate)
    agg.fail_if(problems[:25], TOOL)
    if len(rates) < MIN_WEEKS:
        agg.die(TOOL, f"only {len(rates)} PMMS week(s) in {window[0]}:{window[1]}; need {MIN_WEEKS}. "
                      "Re-pull A7 or pass --window.")
    return statistics.fmean(rates), dates, rates


def read_mha_table(path: Path, needed: set[str]) -> dict[str, dict]:
    if not path.exists():
        agg.die(TOOL, f"not found: {path}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not needed <= set(reader.fieldnames):
            agg.die(TOOL, f"{path.name} needs {sorted(needed)}; found {reader.fieldnames}")
        return {r["mha"]: r for r in reader}


def payment(principal: float, annual_rate_pct: float, months: int) -> float:
    r = annual_rate_pct / 100 / 12
    if r == 0:
        return principal / months
    return principal * r / (1 - (1 + r) ** -months)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zhvi", type=Path, required=True, help="B9 mha_zhvi.csv")
    ap.add_argument("--pmms", type=Path, required=True, help="A7 PMMS_history.csv")
    ap.add_argument("--zori", type=Path, help="B8 mha_zori.csv (utilities_usd)")
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "ownership.json")
    ap.add_argument("--window", help="YYYY-MM:YYYY-MM (default: the B9 window)")
    ap.add_argument("--profiles", type=Path, default=ROOT / "config" / "profiles.json")
    args = ap.parse_args()

    cfg = load_config(args.config)
    loan_cfg, tax_cfg, ins_cfg = cfg["loan"], cfg["property_tax"], cfg["insurance"]
    window_spec = args.window or window_from_b9(args.zhvi) or agg.default_window(args.profiles)
    try:
        window = agg.parse_window(window_spec)
    except ValueError as e:
        agg.die(TOOL, str(e))

    print("B11 ownership monthly cost at MHA")
    zhvi = read_mha_table(args.zhvi, {"mha", "zhvi_median"})
    zori = read_mha_table(args.zori, {"mha", "utilities_usd"}) if args.zori else None
    if zori is not None and set(zori) != set(zhvi):
        diff = sorted(set(zori) ^ set(zhvi))
        agg.die(TOOL, f"B8 and B9 cover different MHAs ({len(diff)}): {', '.join(diff[:10])}")
    rate, weeks, rates = read_pmms(args.pmms, window)

    n = int(loan_cfg["term_years"] * 12)
    down, fee = loan_cfg["down_payment_share"], loan_cfg["funding_fee_share"]
    fee_mult = (1 + fee) if loan_cfg["funding_fee_financed"] else 1.0
    mi_share, tax_share = loan_cfg["mortgage_insurance_annual_share"], tax_cfg["annual_share"]
    ins_month = ins_cfg["annual_usd"] / 12

    rows, no_value, no_util = [], 0, 0
    for mha in sorted(zhvi):
        raw = zhvi[mha]["zhvi_median"].strip()
        util_raw = (zori[mha]["utilities_usd"].strip() if zori else "")
        out = {"mha": mha, "zhvi_median": raw, "rate_pct": f"{rate:.3f}"}
        if not raw:
            no_value += 1
            rows.append(out)
            continue
        v = float(raw)
        loan = v * (1 - down) * fee_mult
        pi = payment(loan, rate, n)
        tax = v * tax_share / 12
        mi = loan * mi_share / 12
        housing = pi + tax + ins_month + mi
        out.update({
            "loan_amount": agg.fmt(loan), "pi_monthly": agg.fmt(pi), "tax_monthly": agg.fmt(tax),
            "insurance_monthly": agg.fmt(ins_month), "mi_monthly": agg.fmt(mi),
            "own_housing_monthly": agg.fmt(housing), "utilities_usd": util_raw,
        })
        if util_raw:
            out["own_total_monthly"] = agg.fmt(housing + float(util_raw))
        else:
            no_util += 1
        rows.append(out)

    fields = ["mha", "zhvi_median", "loan_amount", "rate_pct", "pi_monthly", "tax_monthly",
              "insurance_monthly", "mi_monthly", "own_housing_monthly", "utilities_usd", "own_total_monthly"]
    agg.write_csv(args.out / "mha_ownership.csv", fields, rows)

    warnings = []
    for section, sec_cfg in (("property_tax", tax_cfg), ("insurance", ins_cfg)):
        if "placeholder" in str(sec_cfg.get("status", "")):
            warnings.append(f"{section} uses a national placeholder ({sec_cfg['status']})")
    if zori is None:
        warnings.append("no --zori given: own_total_monthly (with utilities) is blank for every MHA")
    elif no_util:
        warnings.append(f"{no_util} MHA(s) have a home value but no ZORI utilities estimate; "
                        "own_total_monthly is blank there")
    if no_value:
        warnings.append(f"{no_value} MHA(s) have no ZHVI and get no ownership cost")

    housing_vals = [float(r["own_housing_monthly"]) for r in rows if r.get("own_housing_monthly")]
    manifest = {
        "node": "B11",
        "inputs": {"B9": args.zhvi.name, "A7": args.pmms.name, "B8": args.zori.name if args.zori else None},
        "input_sha256": {"A7": agg.sha256(args.pmms), "B9": agg.sha256(args.zhvi),
                         **({"B8": agg.sha256(args.zori)} if args.zori else {})},
        "config": str(args.config.relative_to(ROOT)) if args.config.is_relative_to(ROOT) else str(args.config),
        "config_sha256": agg.sha256(args.config),
        "generated_at": agg.now_utc(),
        "rate": {"series": "pmms30", "window": f"{window[0]}:{window[1]}", "weeks": len(rates),
                 "first_week": weeks[0], "last_week": weeks[-1], "mean_pct": round(rate, 4),
                 "min_pct": min(rates), "max_pct": max(rates)},
        "parameters": {"loan": loan_cfg, "property_tax": tax_cfg, "insurance": ins_cfg},
        "mhas": len(rows),
        "mhas_with_housing_cost": len(housing_vals),
        "mhas_with_total_cost": len(housing_vals) - no_util,
        "own_housing_monthly_summary": ({"min": round(min(housing_vals), 2),
                                         "median": round(statistics.median(housing_vals), 2),
                                         "max": round(max(housing_vals), 2)} if housing_vals else None),
        "warnings": warnings,
        "outputs": ["mha_ownership.csv"],
    }
    agg.write_manifest(args.out / "mha_ownership_manifest.json", manifest)

    print(f"  30-yr rate {rate:.2f}% (mean of {len(rates)} PMMS weeks, {weeks[0]} to {weeks[-1]})")
    print(f"  {loan_cfg['program']}: {down:.0%} down, {fee:.2%} funding fee"
          f"{' financed' if loan_cfg['funding_fee_financed'] else ''}, {loan_cfg['term_years']} years")
    print(f"  {len(housing_vals)} of {len(rows)} MHAs costed; {len(housing_vals) - no_util} include utilities")
    if housing_vals:
        print(f"  PITI: min {min(housing_vals):,.0f} / median {statistics.median(housing_vals):,.0f} / "
              f"max {max(housing_vals):,.0f} per month")
    for w in warnings:
        print(f"  warning: {w}")
    print(f"  -> {args.out / 'mha_ownership.csv'}")


if __name__ == "__main__":
    main()
