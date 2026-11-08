#!/usr/bin/env python3
"""
ownership_by_type.py  (B9 + A4 + A16 + B1 + B29 + A7 + A8 rollup + A14 -> B30 ownership cost by home type)

Decision D19, option B, buy mode: the monthly cost of owning each of DoD's six
housing profiles in every MHA, on the same footing as B11. Decision D22, option B
(1 Nov 2026): the townhouse is priced between the condo/co-op and single-family
values, because Zillow has no townhouse series.

    python pipeline/benchmarks/ownership_by_type.py \
        --zhvi data/interim/benchmarks_2026/mha_zhvi.csv \
        --zhvi-all data/raw/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv \
        --zhvi-sfr data/raw/Zip_zhvi_uc_sfr_tier_0.33_0.67_sm_sa_month.csv \
        --zhvi-condo data/raw/Zip_zhvi_uc_condo_tier_0.33_0.67_sm_sa_month.csv \
        --zhvi-br1 ... --zhvi-br2 ... --zhvi-br3 ... --zhvi-br4 ... \
        --crosswalk data/interim/bah_2026/zip_mha.csv \
        --rent-by-type data/interim/benchmarks_2026/mha_rent_by_type.csv \
        --tax-insurance data/interim/benchmarks_2026/mha_tax_insurance.csv \
        --pmms data/raw/PMMS_history.csv \
        --ownership data/interim/benchmarks_2026/mha_ownership.csv \
        --out data/interim/benchmarks_2026

------------------------------------------------------------------------------
Method (per MHA m and home type t = building b, n bedrooms), D34 (7 Nov 2026)
------------------------------------------------------------------------------
  value(t) = B9 zhvi_median(m) x a_b(m) x h_n(m) / h_K(m)

  h_n  bedroom ladder: ZHVI n BR / ZHVI 2 BR per ZIP, median over the MHA (h_2 = 1).
  K    the bedroom count the all-homes value B9 stands for (config/ownership.json
       home_types.all_homes_bedrooms, 3). Zillow's typical home is a 3 BR home:
       all-homes / 3 BR is 1.003 (median of 20,431 ZIPs, 2026 run), and B30
       re-measures this every run (reference_check) and stops if the configured
       count is no longer the nearest.
  a_b  building factor at equal bedrooms, from Zillow's type ratio g_b (condo/co-op
       ZHVI / all-homes ZHVI for apartments, SFR ZHVI / all-homes ZHVI for
       single-family homes; per ZIP, median over the MHA). A type series has its
       own typical size k_b (condo 2 BR, single-family 3 BR, measured the same way),
       so the ratio carries a size difference that D34 removes:
         a_b = g_b x h_K / h_k_b
       townhouse (D22 option B) = a_apartment + p x (a_single_family - a_apartment),
       p = home_types.townhouse_position (0.5), so the townhouse sits between the
       apartment and the single-family home of the same bedrooms.
  An MHA with no ZIP holding both series of a ratio takes the national median of
  the ZIP ratios; building_source and bedroom_source say which (zip | national), and
  a factor is `zip` only when every ratio in it is.

Before D34, value(t) = B9 x g_b x h_n treated B9 and both type series as 2 BR
homes, so every home with more than two bedrooms was priced as if its extra rooms
came on top of a 3 BR value, and a single-family home's size was counted twice.
B11 stays the all-homes ownership cost: B30 recomputes it with a = 1 and no bedroom
scaling, and stops if it differs, which checks that B30 and B11 run one model.

  Then B11's model unchanged (config/ownership.json, the same PMMS window, the
  MHA's own tax rate and insurance premium from the A8 rollup):
    own_housing_monthly(t) = P&I(value) + value x tax rate / 12 + premium / 12 + MI
    own_total_monthly(t)   = own_housing_monthly(t) + B29 utilities_usd(t)

  The premium is the MHA's average homeowners premium for every type (FIO
  publishes no premium by dwelling type); see the limitation in the manifest.


Status per row: ok | piti_only_no_zori (B29 has no utilities: decision 2.4) |
no_home_value (no B9 value).

Output: mha_ownership_by_type.csv (long: MHA x home type) and its manifest.
Stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import home_types as ht  # noqa: E402
import mha_agg as agg  # noqa: E402
import ownership_cost as oc  # noqa: E402
import zillow_to_mha as zm  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TOOL = "ownership_by_type"
FACTOR_RANGE = (0.2, 5.0)
ZHVI_RANGE = zm.SERIES["zhvi"]["range"]


def zip_series(path: Path, window: tuple[str, str], min_months: int, node: str) -> dict[str, float]:
    if not path.exists():
        agg.die(TOOL, f"{node} not found: {path} (run `make fetch`)")
    values, _, _, problems, _, _ = zm.read_zillow(path, window, min_months, *ZHVI_RANGE)
    agg.fail_if([f"{path.name}: {p}" for p in problems[:25]], TOOL)
    return values


def ratio_by_mha(num: dict[str, float], den: dict[str, float], members: dict[str, list[str]],
                 label: str) -> tuple[dict[str, tuple[float, str, int]], float, dict]:
    """Per-ZIP num/den, MHA median, national median fallback. Returns ({mha: (factor, source, zips)}, national, stats)."""
    per_zip = {z: num[z] / den[z] for z in num if z in den and den[z] > 0}
    if not per_zip:
        agg.die(TOOL, f"{label}: no ZIP has both series")
    national = statistics.median(per_zip.values())
    bad = [f"{z}={v:.3f}" for z, v in per_zip.items() if not FACTOR_RANGE[0] <= v <= FACTOR_RANGE[1]]
    out = {}
    for m, zips in members.items():
        vals = [per_zip[z] for z in zips if z in per_zip]
        out[m] = (statistics.median(vals), "zip", len(vals)) if vals else (national, "national", 0)
    stats = {"zips_with_both": len(per_zip), "national_median": round(national, 4),
             "mhas_national_fallback": sum(v[1] == "national" for v in out.values()),
             "zips_outside_range": len(bad)}
    return out, national, stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zhvi", type=Path, required=True, help="B9 mha_zhvi.csv")
    ap.add_argument("--zhvi-all", type=Path, required=True, help="A4 ZIP ZHVI, all homes")
    ap.add_argument("--zhvi-sfr", type=Path, required=True, help="A16.sfr")
    ap.add_argument("--zhvi-condo", type=Path, required=True, help="A16.condo")
    for n in (1, 2, 3, 4):
        ap.add_argument(f"--zhvi-br{n}", type=Path, required=True, help=f"A16.br{n}")
    ap.add_argument("--crosswalk", type=Path, required=True, help="B1 zip_mha.csv")
    ap.add_argument("--rent-by-type", type=Path, required=True, help="B29 mha_rent_by_type.csv (utilities)")
    ap.add_argument("--tax-insurance", type=Path, required=True, help="A8 rollup mha_tax_insurance.csv")
    ap.add_argument("--pmms", type=Path, required=True, help="A7 PMMS_history.csv")
    ap.add_argument("--ownership", type=Path, required=True, help="B11 mha_ownership.csv (identity check)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "ownership.json")
    ap.add_argument("--standards", type=Path, default=ht.STANDARDS)
    ap.add_argument("--profiles", type=Path, default=ROOT / "config" / "profiles.json")
    ap.add_argument("--min-months", type=int, default=3)
    ap.add_argument("--window", help="YYYY-MM:YYYY-MM, as passed to B11 (default: the B9 window)")
    args = ap.parse_args()

    cfg = ht.load(args.standards)
    own_cfg = oc.load_config(args.config)
    loan = own_cfg["loan"]
    th_pos = own_cfg["home_types"]["townhouse_position"]
    series_bedrooms = {"all_homes": own_cfg["home_types"]["all_homes_bedrooms"],
                       "condo": own_cfg["home_types"]["condo_bedrooms"],
                       "single_family": own_cfg["home_types"]["single_family_bedrooms"]}
    spec = args.window or oc.window_from_b9(args.zhvi)
    if spec is None:
        agg.die(TOOL, f"mha_zhvi_manifest.json not found beside {args.zhvi} (run `make zhvi`)")
    window = agg.parse_window(spec)
    print(f"B30 ownership cost by home type: B9 months {window[0]} to {window[1]}")

    crosswalk, cw_stats = agg.load_crosswalk(args.crosswalk, TOOL)
    members: dict[str, list[str]] = {}
    for z, m in crosswalk.items():
        members.setdefault(m, []).append(z)

    b9 = oc.read_mha_table(args.zhvi, {"mha", "zhvi_median"})
    b11 = oc.read_mha_table(args.ownership, {"mha", "own_housing_monthly", "own_total_monthly"})
    taxins = oc.read_tax_insurance(args.tax_insurance)
    rent = {}
    with args.rent_by_type.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rent[(r["mha"], r["home_type"])] = r
    mhas = sorted(b9)
    problems = []
    if set(mhas) != set(members):
        problems.append("B9 and B1 cover different MHAs")
    if set(b11) != set(mhas):
        problems.append("B9 and B11 cover different MHAs")
    missing = [m for m in mhas if m not in taxins]
    if missing:
        problems.append(f"{len(missing)} MHA(s) have no tax/insurance row: {', '.join(missing[:10])}")
    gaps = [f"{m} {t}" for m in mhas for t in ht.TYPE_IDS if (m, t) not in rent]
    if gaps:
        problems.append(f"B29 lacks {len(gaps)} MHA x type row(s): {', '.join(gaps[:10])} (run `make rent-types`)")
    agg.fail_if(problems, TOOL)

    paths = {"all": args.zhvi_all, "sfr": args.zhvi_sfr, "condo": args.zhvi_condo,
             **{f"br{n}": getattr(args, f"zhvi_br{n}") for n in (1, 2, 3, 4)}}
    nodes = {"all": "A4", "sfr": "A16.sfr", "condo": "A16.condo", **{f"br{n}": f"A16.br{n}" for n in (1, 2, 3, 4)}}
    series = {}
    for key, path in paths.items():
        print(f"  reading {path.name}")
        series[key] = zip_series(path, window, args.min_months, nodes[key])

    bedroom, stats = {}, {}
    for n in (1, 3, 4):
        bedroom[n], _, stats[f"bedrooms_{n}"] = ratio_by_mha(series[f"br{n}"], series["br2"], members, f"{n} BR")

    def ladder(m: str, n: int) -> tuple[float, str]:
        """h_n for one MHA and where it came from: 2 BR is the ladder's base (h_2 = 1)."""
        if n == 2:
            return 1.0, "reference"
        value, src, _ = bedroom[n][m]
        return value, src

    def combined(*sources: str) -> str:
        return "national" if "national" in sources else "zip"

    # D34: which bedroom count each Zillow series stands for, measured ZIP by ZIP (median of the
    # series over each bedroom series). The nearest to 1, on a log scale, is its typical size;
    # B30 stops if the configured count is not that one, so the method follows the data.
    reference_check, measured = {}, {}
    for name, key in (("all_homes", "all"), ("condo", "condo"), ("single_family", "sfr")):
        per_n = {}
        for n in (1, 2, 3, 4):
            both = [series[key][z] / series[f"br{n}"][z] for z in series[key]
                    if z in series[f"br{n}"] and series[f"br{n}"][z] > 0]
            if both:
                per_n[n] = {"zips": len(both), "median": round(statistics.median(both), 4)}
            if name == "all_homes" and n >= 2:                             # the keys B23 and earlier runs used
                reference_check[f"all_homes_over_{n}br"] = per_n.get(n)
        nearest = min(per_n, key=lambda n: abs(math.log(per_n[n]["median"]))) if per_n else None
        measured[name] = {"over_n_br": per_n, "nearest_bedrooms": nearest,
                          "configured_bedrooms": series_bedrooms[name]}
    mismatch = [f"{k}: configured {v['configured_bedrooms']} BR, the data sit nearest {v['nearest_bedrooms']} BR "
                f"({json.dumps({n: x['median'] for n, x in v['over_n_br'].items()})})"
                for k, v in measured.items() if v["nearest_bedrooms"] != v["configured_bedrooms"]]
    agg.fail_if([f"Zillow series sizes changed (D34): {'; '.join(mismatch)}. Update config/ownership.json "
                 "home_types and docs/configuration.md, then rerun"] if mismatch else [], TOOL)

    building = {}
    for b, key in (("apartment", "condo"), ("single_family", "sfr")):
        building[b], _, stats[f"building_{b}"] = ratio_by_mha(series[key], series["all"], members, b)
    k_all = series_bedrooms["all_homes"]
    size_matched = {}
    for b, name in (("apartment", "condo"), ("single_family", "single_family")):
        size_matched[b] = {}
        for m in members:
            g, gsrc, gz = building[b][m]
            if series_bedrooms[name] == k_all:                 # same typical size: nothing to remove
                size_matched[b][m] = (g, gsrc, gz)
                continue
            h_all, s_all = ladder(m, k_all)
            h_k, s_k = ladder(m, series_bedrooms[name])
            size_matched[b][m] = (g * h_all / h_k, combined(gsrc, s_all, s_k), gz)
        vals = [v[0] for v in size_matched[b].values()]
        stats[f"building_{b}"]["size_matched_median"] = round(statistics.median(vals), 4)
    # D22 option B, at equal bedrooms (D34): the townhouse between the MHA's two size-matched factors.
    size_matched["townhouse"], inverted = {}, []
    for m in members:
        (aa, sa, za), (as_, ss, zs) = size_matched["apartment"][m], size_matched["single_family"][m]
        size_matched["townhouse"][m] = (aa + th_pos * (as_ - aa), combined(sa, ss), min(za, zs))
        if aa > as_:
            inverted.append(m)
    th_vals = [v[0] for v in size_matched["townhouse"].values()]
    stats["building_townhouse"] = {
        "method": f"apartment factor + {th_pos} x (single-family factor - apartment factor), per MHA, "
                  "both at equal bedrooms (D34)",
        "townhouse_position": th_pos, "median_factor": round(statistics.median(th_vals), 4),
        "mhas_national_fallback": sum(v[1] == "national" for v in size_matched["townhouse"].values()),
        "mhas_condo_above_single_family": len(inverted)}

    rate, weeks, rates = oc.read_pmms(args.pmms, window)
    n_months = int(loan["term_years"] * 12)
    fee_mult = (1 + loan["funding_fee_share"]) if loan["funding_fee_financed"] else 1.0
    down, mi_share = loan["down_payment_share"], loan["mortgage_insurance_annual_share"]

    def piti(v: float, tax_rate: float, premium: float) -> tuple[float, float, float, float, float]:
        """B11's arithmetic, in B11's order, so the all-homes value reproduces B11 exactly."""
        loan_amt = v * (1 - down) * fee_mult
        pi = oc.payment(loan_amt, rate, n_months)
        tax = v * tax_rate / 12
        ins = premium / 12
        mi = loan_amt * mi_share / 12
        return pi, tax, ins, mi, pi + tax + ins + mi

    rows, identity_fail = [], []
    for m in mhas:
        raw = b9[m]["zhvi_median"].strip()
        ti = taxins[m]
        tax_rate, premium = float(ti["effective_tax_rate"]), float(ti["insurance_annual_usd"])
        for t in ht.types(cfg):
            b, n = t["building"], t["bedrooms"]
            g, gsrc, _ = size_matched[b][m]
            h_n, s_n = ladder(m, n)
            h_all, s_all = ladder(m, k_all)
            h = h_n / h_all
            hsrc = "reference" if n == k_all else combined(s_n, s_all)
            out = {"mha": m, "home_type": t["id"], "building_factor": f"{g:.6f}", "building_source": gsrc,
                   "zillow_type_ratio": "" if b == "townhouse" else f"{building[b][m][0]:.6f}",
                   "bedroom_ratio": f"{h:.6f}", "bedroom_source": hsrc, "rate_pct": f"{rate:.3f}"}
            if not raw:
                out["status"] = "no_home_value"
                rows.append(out)
                continue
            v = float(raw) * g * h
            pi, tax, ins, mi, housing = piti(v, tax_rate, premium)
            util = rent[(m, t["id"])]["utilities_usd"].strip()
            out.update({"home_value": agg.fmt(v), "pi_monthly": agg.fmt(pi), "tax_monthly": agg.fmt(tax),
                        "tax_source": ti["tax_source"], "insurance_monthly": agg.fmt(ins),
                        "insurance_source": ti["insurance_source"], "mi_monthly": agg.fmt(mi),
                        "own_housing_monthly": agg.fmt(housing), "utilities_usd": util,
                        "own_total_monthly": agg.fmt(housing + float(util)) if util else "",
                        "status": "ok" if util else "piti_only_no_zori"})
            rows.append(out)
        # Model identity: the all-homes value (g = h = 1) with B8's utilities must reproduce B11.
        if raw:
            housing_all = piti(float(raw), tax_rate, premium)[4]
            util_ref = rent[(m, ht.REFERENCE)]["utilities_usd"].strip()
            total_all = agg.fmt(housing_all + float(util_ref)) if util_ref else ""
            if (agg.fmt(housing_all), total_all) != (b11[m]["own_housing_monthly"].strip(),
                                                     b11[m]["own_total_monthly"].strip()):
                identity_fail.append(m)
    agg.fail_if([f"the all-homes value does not reproduce B11 in {len(identity_fail)} MHA(s): "
                 f"{', '.join(identity_fail[:10])} (rebuild B11 and B30 from the same inputs)"]
                if identity_fail else [], TOOL)

    fields = ["mha", "home_type", "building_factor", "building_source", "zillow_type_ratio", "bedroom_ratio",
              "bedroom_source",
              "home_value", "rate_pct", "pi_monthly", "tax_monthly", "tax_source", "insurance_monthly",
              "insurance_source", "mi_monthly", "own_housing_monthly", "utilities_usd", "own_total_monthly",
              "status"]
    agg.write_csv(args.out / "mha_ownership_by_type.csv", fields, rows)

    coverage = {}
    for t in ht.TYPE_IDS:
        mine = [r for r in rows if r["home_type"] == t]
        vals = [float(r["own_housing_monthly"]) for r in mine if r.get("own_housing_monthly")]
        coverage[t] = {"status": {s: sum(r["status"] == s for r in mine)
                                  for s in ("ok", "piti_only_no_zori", "no_home_value")},
                       "national_fallback": sum("national" in (r["building_source"], r["bedroom_source"])
                                                for r in mine),
                       "own_housing_monthly": ({"min": round(min(vals), 2), "median": round(statistics.median(vals), 2),
                                                "max": round(max(vals), 2)} if vals else None)}
    warnings = [f"{s['mhas_national_fallback']} MHA(s) take the national {k.replace('_', ' ')} ratio "
                f"({s['national_median']})" for k, s in stats.items()
                if k != "building_townhouse" and s["mhas_national_fallback"]]
    if stats["building_townhouse"]["mhas_national_fallback"]:
        warnings.append(f"{stats['building_townhouse']['mhas_national_fallback']} MHA(s) build the townhouse factor "
                        "from at least one national ratio (caveat type_factor_national)")
    medians = {t: (cv["own_housing_monthly"] or {}).get("median") for t, cv in coverage.items()}
    for cheaper, dearer in (("apt1", "apt2"), ("apt2", "th2"), ("th2", "th3"), ("th3", "sfh3"), ("sfh3", "sfh4")):
        if None not in (medians[cheaper], medians[dearer]) and medians[dearer] < medians[cheaper]:
            warnings.append(f"median PITI of {dearer} ({medians[dearer]:,.0f}) is below {cheaper} "
                            f"({medians[cheaper]:,.0f}): the home types are out of DoD's order in buy mode "
                            "(see reference_check)")
    if inverted:
        warnings.append(f"{len(inverted)} MHA(s) have a condo/co-op factor above the single-family factor, so "
                        f"their townhouse is not between the two in DoD's order: {', '.join(sorted(inverted)[:10])}")
    warnings += [f"{s['zips_outside_range']} ZIP {k.replace('_', ' ')} ratio(s) outside {FACTOR_RANGE}; kept, "
                 "the MHA median limits their pull" for k, s in stats.items() if s.get("zips_outside_range")]

    inputs = {"B9": args.zhvi, "A4": args.zhvi_all, "A16.sfr": args.zhvi_sfr, "A16.condo": args.zhvi_condo,
              **{f"A16.br{n}": getattr(args, f"zhvi_br{n}") for n in (1, 2, 3, 4)},
              "B1": args.crosswalk, "B29": args.rent_by_type, "A8": args.tax_insurance, "A7": args.pmms,
              "B11": args.ownership, "A14": args.standards}
    manifest = {
        "node": "B30",
        "generated_at": agg.now_utc(),
        "inputs": {k: v.name for k, v in inputs.items()},
        "input_sha256": {k: agg.sha256(v) for k, v in inputs.items()},
        "config": str(args.config.relative_to(ROOT)) if args.config.is_relative_to(ROOT) else str(args.config),
        "config_sha256": agg.sha256(args.config),
        "window_months": f"{window[0]}:{window[1]}",
        "rate": {"series": "pmms30", "weeks": len(rates), "mean_pct": round(rate, 4)},
        "decision": "D34 (7 Nov 2026): B9 and each Zillow type series are placed at their measured typical "
                    "bedroom count before bedrooms are scaled",
        "series_bedrooms": series_bedrooms,
        "method": {
            "home_value": "B9 zhvi_median x building_factor x bedroom_ratio",
            "building_factor": "at equal bedrooms: zillow_type_ratio x h(all-homes size) / h(series size); "
                               "zillow_type_ratio = condo/co-op ZHVI / all-homes ZHVI (apartment) or SFR ZHVI / "
                               "all-homes ZHVI (single-family), per ZIP, median over the MHA, national median "
                               f"fallback; townhouse = apartment + {th_pos} x (single-family - apartment) per MHA "
                               "(D22 option B)",
            "bedroom_ratio": f"h(n) / h({k_all}), h = ZHVI n BR / 2 BR per ZIP, median over the MHA; national "
                             f"median fallback; B9 stands for a {k_all} BR home",
            "cost": "B11 model (config/ownership.json): P&I + tax + insurance + MI, plus B29 utilities",
        },
        "ratios": stats,
        "reference_check": {**reference_check, "series": measured,
                            "reading": "series ZHVI / n-bedroom ZHVI per ZIP, median; the one nearest 1.0 (log "
                                       "scale) is the bedroom count the series stands for. B30 stops if a "
                                       "configured count (D34) is not that one."},
        "limitations": ["the homeowners premium is the MHA average for every home type (FIO has no premium by "
                        "dwelling type), so it is overstated for apartments and understated for 4 BR homes",
                        "each Zillow series' typical size is taken as a whole bedroom count (the nearest one "
                        "measured), so any remainder stays in its type ratio",
                        "a condo/co-op value stands for an apartment in buy mode",
                        "Zillow has no townhouse series: the townhouse is priced at a fixed position between the "
                        "condo/co-op and single-family values (D22 option B), an assumption rather than a "
                        "measurement"],
        "crosswalk": cw_stats,
        "coverage": coverage,
        "model_identity": "all-homes value (g = h = 1) reproduces B11 in every MHA (checked); since D22 the "
                          "2 BR townhouse is not B11",
        "mhas": len(mhas),
        "warnings": warnings,
        "outputs": ["mha_ownership_by_type.csv"],
    }
    agg.write_manifest(args.out / "mha_ownership_by_type_manifest.json", manifest)

    rc = ", ".join(f"{k.replace('all_homes_over_', '')} {v['median']}" for k, v in reference_check.items() if v)
    print(f"  all-homes ZHVI / n-bedroom ZHVI (median per ZIP): {rc}")
    for k, s in stats.items():
        if k == "building_townhouse":
            print(f"  {k:24} MHA median {s['median_factor']} (position {s['townhouse_position']}); "
                  f"{s['mhas_national_fallback']} MHA(s) with a national side")
            continue
        print(f"  {k:24} national median {s['national_median']}; {s['zips_with_both']:,} ZIPs; "
              f"{s['mhas_national_fallback']} MHA(s) on the national ratio")
    for t, cv in coverage.items():
        h = cv["own_housing_monthly"]
        print(f"  {t:5} {cv['status']}" + (f", PITI median {h['median']:,.0f}" if h else ""))
    print("  all-homes value = B11 in every MHA (model identity)")
    for w in warnings:
        print(f"  warning: {w}")
    print(f"  -> {args.out / 'mha_ownership_by_type.csv'}")


if __name__ == "__main__":
    main()
