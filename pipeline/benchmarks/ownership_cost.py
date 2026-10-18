#!/usr/bin/env python3
"""
ownership_cost.py  (A7 + B9 + A8/A9 tax and insurance [+ B8] -> B11 ownership monthly cost at MHA)

Turn each MHA's typical home value (B9 ZHVI) into the monthly cost of owning it,
so buy mode can be compared with BAH on the same monthly-dollar footing as rent.

    python pipeline/benchmarks/ownership_cost.py \
        --zhvi data/interim/benchmarks_2026/mha_zhvi.csv \
        --pmms data/raw/PMMS_history.csv \
        --zori data/interim/benchmarks_2026/mha_zori.csv \
        --tax-insurance data/interim/benchmarks_2026/mha_tax_insurance.csv \
        --out data/interim/benchmarks_2026

------------------------------------------------------------------------------
Model (parameters in config/ownership.json)
------------------------------------------------------------------------------
  V        = zhvi_median (B9)
  loan     = V * (1 - down_payment_share) * (1 + funding_fee_share)   [fee financed]
  r        = mean 30-year PMMS rate over the window / 12              (A7)
  P&I      = loan * r / (1 - (1 + r)^-n),  n = term_years * 12
  tax      = V * effective_tax_rate / 12        (per MHA, ACS taxes / value, A9 via A8 rollup)
  ins      = insurance_annual_usd / 12          (per MHA, FIO average premium, A8 rollup)
  MI       = loan * mortgage_insurance_annual_share / 12              (0 for VA)

  own_housing_monthly = P&I + tax + ins + MI          ("PITI")
  own_total_monthly   = own_housing_monthly + utilities_usd (B8)

Default financing is a VA purchase loan, first use: 0% down, 2.15% funding fee
financed, no mortgage insurance. One mortgage rate applies nationwide (PMMS is a
national survey), so spatial variation in B11 comes from home values, local
property-tax rates and insurance premiums, plus utilities via B8. Tax rates and
premiums come per MHA from tax_insurance_to_mha.py, each with a source flag
(`locality` or `state_fallback`). Insurance is used as published (FIO, data year
in the config), not scaled to the BAH year (decision N2).

------------------------------------------------------------------------------
Inputs
------------------------------------------------------------------------------
  --zhvi   B9 mha_zhvi.csv (needs mha, zhvi_median)
  --pmms   Freddie Mac PMMS_history.csv: date (M/D/YYYY), pmms30 (%) ...; blank
           cells may hold a single space
  --zori   B8 mha_zori.csv (optional; supplies utilities_usd). Without it,
           own_total_monthly is blank everywhere and the manifest says so.
  --tax-insurance  mha_tax_insurance.csv from tax_insurance_to_mha.py (needs mha,
           effective_tax_rate, tax_source, insurance_annual_usd, insurance_source)
  --window YYYY-MM:YYYY-MM for the rate average. Default: read from the B9
           manifest so rate and home value cover the same months; falls back to
           the BAH year.

------------------------------------------------------------------------------
Output (written to --out)
------------------------------------------------------------------------------
  mha_ownership.csv            mha, zhvi_median, loan_amount, rate_pct, pi_monthly,
                               tax_rate, tax_monthly, tax_source,
                               insurance_annual_usd, insurance_monthly, insurance_source,
                               mi_monthly, own_housing_monthly, utilities_usd,
                               own_total_monthly
  mha_ownership_manifest.json  parameters used, PMMS weeks averaged, tax and
                               insurance source counts, limitations, counts, warnings

------------------------------------------------------------------------------
Validation (loud)
------------------------------------------------------------------------------
  * every config field present and in range (shares in [0, 0.5), term 10-40 years)
  * PMMS has date + pmms30 columns, at least 4 weekly observations in the window,
    every rate in (0.5, 25) percent
  * MHA codes in B8 and B9 agree; every B9 MHA has a tax and insurance row with a
    rate in (0, 5%) and a premium in (0, 20,000) dollars a year
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
    tax, ins = cfg.get("property_tax", {}), cfg.get("insurance", {})
    if tax.get("method") != "locality_effective_rate":
        problems.append("property_tax.method must be 'locality_effective_rate' (A8 via the A9 ACS pull)")
    if ins.get("method") != "locality_average_premium":
        problems.append("insurance.method must be 'locality_average_premium' (A8, Treasury FIO)")
    num("property_tax", "acs_vintage", 2015, 2100)
    num("insurance", "data_year", 2015, 2100)
    for section, node in (("property_tax", "A9"), ("insurance", "A8")):
        if cfg.get(section, {}).get("source_node") != node:
            problems.append(f"{section}.source_node must be '{node}'")
        if cfg.get(section, {}).get("fallback") != "state":
            problems.append(f"{section}.fallback must be 'state' (the only fallback wired up)")
    if ins.get("scaled_to_bah_year") is not False:
        problems.append("insurance.scaled_to_bah_year must be false (decision N2: used as published)")
    agg.fail_if(problems, TOOL)
    return cfg


TAX_FIELDS = {"mha", "effective_tax_rate", "tax_source", "insurance_annual_usd", "insurance_source"}
SOURCE_FLAGS = ("locality", "state_fallback")


def read_tax_insurance(path: Path) -> dict[str, dict]:
    """Per-MHA tax rate and premium from tax_insurance_to_mha.py, validated."""
    rows = read_mha_table(path, TAX_FIELDS)
    problems = []
    for m, r in rows.items():
        try:
            rate, prem = float(r["effective_tax_rate"]), float(r["insurance_annual_usd"])
        except ValueError:
            problems.append(f"{m}: tax rate {r['effective_tax_rate']!r} or premium "
                            f"{r['insurance_annual_usd']!r} is not a number")
            continue
        if not 0 < rate < 0.05:
            problems.append(f"{m}: effective_tax_rate {rate} outside (0, 0.05); a percent typed as a share?")
        if not 0 < prem < 20_000:
            problems.append(f"{m}: insurance_annual_usd {prem} outside (0, 20000)")
        for col in ("tax_source", "insurance_source"):
            if r[col] not in SOURCE_FLAGS:
                problems.append(f"{m}: {col} {r[col]!r} is not one of {SOURCE_FLAGS}")
    agg.fail_if(problems[:25], TOOL)
    return rows


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
    ap.add_argument("--tax-insurance", type=Path, required=True,
                    help="mha_tax_insurance.csv (A8 rollup: per-MHA tax rate and premium)")
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
    taxins = read_tax_insurance(args.tax_insurance)
    missing = sorted(set(zhvi) - set(taxins))
    if missing:
        agg.die(TOOL, f"{len(missing)} B9 MHA(s) have no tax/insurance row in {args.tax_insurance.name}: "
                      f"{', '.join(missing[:10])} (rerun `make taxins`)")
    rate, weeks, rates = read_pmms(args.pmms, window)

    n = int(loan_cfg["term_years"] * 12)
    down, fee = loan_cfg["down_payment_share"], loan_cfg["funding_fee_share"]
    fee_mult = (1 + fee) if loan_cfg["funding_fee_financed"] else 1.0
    mi_share = loan_cfg["mortgage_insurance_annual_share"]

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
        ti = taxins[mha]
        tax_rate, premium = float(ti["effective_tax_rate"]), float(ti["insurance_annual_usd"])
        loan = v * (1 - down) * fee_mult
        pi = payment(loan, rate, n)
        tax = v * tax_rate / 12
        ins_month = premium / 12
        mi = loan * mi_share / 12
        housing = pi + tax + ins_month + mi
        out.update({
            "loan_amount": agg.fmt(loan), "pi_monthly": agg.fmt(pi),
            "tax_rate": f"{tax_rate:.6f}", "tax_monthly": agg.fmt(tax), "tax_source": ti["tax_source"],
            "insurance_annual_usd": agg.fmt(premium), "insurance_monthly": agg.fmt(ins_month),
            "insurance_source": ti["insurance_source"], "mi_monthly": agg.fmt(mi),
            "own_housing_monthly": agg.fmt(housing), "utilities_usd": util_raw,
        })
        if util_raw:
            out["own_total_monthly"] = agg.fmt(housing + float(util_raw))
        else:
            no_util += 1
        rows.append(out)

    fields = ["mha", "zhvi_median", "loan_amount", "rate_pct", "pi_monthly", "tax_rate", "tax_monthly",
              "tax_source", "insurance_annual_usd", "insurance_monthly", "insurance_source", "mi_monthly",
              "own_housing_monthly", "utilities_usd", "own_total_monthly"]
    agg.write_csv(args.out / "mha_ownership.csv", fields, rows)

    warnings = []
    costed = [r for r in rows if r.get("own_housing_monthly")]
    sources = {col: {f: sum(r[col] == f for r in costed) for f in SOURCE_FLAGS}
               for col in ("tax_source", "insurance_source")}
    bah_year = json.loads(args.profiles.read_text(encoding="utf-8")).get("bah_year") \
        if args.profiles.exists() else None
    limitations = [f"insurance premiums are Treasury FIO data-year {ins_cfg['data_year']} values, used as "
                   f"published and not scaled to the BAH year {bah_year} (decision N2), so 2026 premiums "
                   "are understated"]
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
        "inputs": {"B9": args.zhvi.name, "A7": args.pmms.name, "B8": args.zori.name if args.zori else None,
                   "A8": args.tax_insurance.name},
        "input_sha256": {"A7": agg.sha256(args.pmms), "B9": agg.sha256(args.zhvi),
                         "A8": agg.sha256(args.tax_insurance),
                         **({"B8": agg.sha256(args.zori)} if args.zori else {})},
        "config": str(args.config.relative_to(ROOT)) if args.config.is_relative_to(ROOT) else str(args.config),
        "config_sha256": agg.sha256(args.config),
        "generated_at": agg.now_utc(),
        "rate": {"series": "pmms30", "window": f"{window[0]}:{window[1]}", "weeks": len(rates),
                 "first_week": weeks[0], "last_week": weeks[-1], "mean_pct": round(rate, 4),
                 "min_pct": min(rates), "max_pct": max(rates)},
        "parameters": {"loan": loan_cfg, "property_tax": tax_cfg, "insurance": ins_cfg},
        "tax_insurance_sources": sources,
        "limitations": limitations,
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
    print(f"  tax: {sources['tax_source']['locality']} locality, {sources['tax_source']['state_fallback']} "
          f"state fallback; insurance: {sources['insurance_source']['locality']} locality, "
          f"{sources['insurance_source']['state_fallback']} state fallback")
    for w in warnings:
        print(f"  warning: {w}")
    print(f"  -> {args.out / 'mha_ownership.csv'}")


if __name__ == "__main__":
    main()
