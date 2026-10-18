#!/usr/bin/env python3
"""
coverage_metrics.py  (2.5 computed metrics: B12-B15)

  B12  rent coverage ratio   A12 + B4 + B8   (+ B10 cross-check)
  B13  rent surplus / gap    A12 + B4 + B8   (+ B10 cross-check)
  B14  buy coverage ratio    A12 + B4 + B11
  B15  buy surplus / gap     A12 + B4 + B11

    python pipeline/metrics/coverage_metrics.py \
        --bah-rates data/interim/bah_2026/bah_rates.csv \
        --zori data/interim/benchmarks_2026/mha_zori.csv \
        --safmr data/interim/benchmarks_2026/mha_safmr.csv \
        --ownership data/interim/benchmarks_2026/mha_ownership.csv \
        --out data/interim/metrics_2026

------------------------------------------------------------------------------
The statutory target
------------------------------------------------------------------------------
37 U.S.C. 403(b)(3) sets BAH for an area as the local monthly cost of adequate
housing MINUS a percentage (5% since 2019) of the NATIONAL average cost for the
member's pay grade and dependency status. The deduction is a flat dollar amount
per grade, the same at every duty station (DTMO publishes it each year; A12
cost_share_monthly). BAH therefore covers exactly 95% of local cost only where
local cost equals the national mean: more in expensive MHAs, less in cheap ones.
A fixed 95% test would score that design as a gap, and because cost levels
cluster in space it would also plant spatial autocorrelation in the test
variable before 2.6 measures any.

------------------------------------------------------------------------------
Metrics, per A12 profile p and real MHA m
------------------------------------------------------------------------------
  BAH = B4 monthly_rate for (m, p.pay_grade, p.has_dependents)
  A   = p.cost_share_monthly (DTMO member cost share, A12)
  C   = local monthly cost of the anchor dwelling
          rent mode: B8 zori_utilities_adjusted   (A12 benchmarks.rent_primary)
          buy mode:  B11 own_total_monthly        (PITI + B8 utilities)

  coverage_ratio   R = BAH / C               share of benchmark cost BAH pays (descriptive)
  design_coverage    = 1 - A / C             share BAH is designed to pay at this cost level
  adequacy_ratio     = (BAH + A) / C         DoD's implied local cost vs the benchmark; target 1.00
  adequacy_gap       = adequacy_ratio - 1    = R - design_coverage; the test variable for 2.6
  surplus_usd        = BAH - C               full-cost dollars
  design_gap_usd     = BAH + A - C           dollars over (+) or short of (-) the statutory design
  flat95_gap         = R - 0.95              sensitivity: the simple fixed-95% reading

Rent cross-check (B10): coverage ratio, adequacy ratio and gap vs design against
the HUD SAFMR median at the profile's anchor_bedrooms. ZORI has one series for
every bedroom count, so without this the E-5 vs O-3 contrast in rent mode comes
only from the BAH numerator. SAFMR is gross rent (utilities included) at HUD's
40th percentile, so it sits below a median benchmark; it is reported beside the
primary values and never replaces them.

Every real MHA gets one row per profile, including MHAs with no benchmark. The
`status` column says why a value is blank:
  rent:  ok | no_zori
  buy:   ok | no_home_value (B9 had no ZHVI) |
         piti_only_no_zori (home value but no ZORI, so no utilities estimate: the
         metrics are computed against PITI alone, decision 2.4. They are map-only
         values: the buy summaries below and the 2.6 tests use `ok` rows only, so
         a cost without utilities is never compared with costs that include them)

------------------------------------------------------------------------------
Output (written to --out)
------------------------------------------------------------------------------
  mha_rent_metrics.csv            B12 + B13, long: one row per profile x MHA
  mha_buy_metrics.csv             B14 + B15, long: one row per profile x MHA
  coverage_metrics_manifest.json  input hashes, cost-share parameters, data
                                  windows, per-profile summaries, A13 class
                                  counts, flat-95% vs statutory comparison, warnings

------------------------------------------------------------------------------
Validation (loud)
------------------------------------------------------------------------------
  * A12 profiles are well formed and each carries a cost_share_monthly
  * B4 has a positive rate for every real MHA x profile
  * B8, B10 and B11 cover the same MHAs; B10 has the anchor bedroom row for each
  * every non-blank cost is a finite number > 0
  * B8 and B9 were built over the same months (temporal alignment); B11 was
    built from the same B8 and B9 files that sit beside it (SHA-256 lineage)
  * warns (does not stop) on a coverage ratio outside 0.3-2.5, which usually
    means a join or units error rather than a real market
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "benchmarks"))
import mha_agg as agg  # noqa: E402

TOOL = "coverage_metrics"
PLAUSIBLE_RATIO = (0.3, 2.5)
CLASSED = ("adequacy_ratio", "design_gap_usd", "coverage_ratio", "surplus_usd")

METRIC_FIELDS = ["coverage_ratio", "design_coverage", "adequacy_ratio", "adequacy_gap",
                 "surplus_usd", "design_gap_usd", "flat95_gap"]
BASE_FIELDS = ["profile", "mha", "pay_grade", "has_dependents", "bah_monthly", "cost_share_monthly",
               "cost_monthly"]
RENT_FIELDS = BASE_FIELDS + METRIC_FIELDS + [
    "zori_zip_coverage", "safmr_bedrooms", "safmr_monthly", "safmr_coverage_ratio",
    "safmr_adequacy_ratio", "safmr_design_gap_usd", "status"]
BUY_FIELDS = BASE_FIELDS + ["own_housing_monthly"] + METRIC_FIELDS + ["status"]


# --- inputs -------------------------------------------------------------------

def load_json(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        agg.die(TOOL, f"{what} not found: {path}")
    except json.JSONDecodeError as e:
        agg.die(TOOL, f"{path} is not valid JSON: {e}")
    raise AssertionError


def load_profiles(path: Path) -> tuple[list[dict], float, dict]:
    cfg = load_json(path, "A12 profiles config")
    problems: list[str] = []
    target = cfg.get("coverage_target")
    if not isinstance(target, (int, float)) or isinstance(target, bool) or not 0 < target <= 1:
        problems.append(f"coverage_target = {target!r}; expected a number in (0, 1]")
    profiles = cfg.get("profiles") or []
    if not profiles:
        problems.append("no profiles defined")
    for p in profiles:
        pid = p.get("id", "?")
        if not p.get("id") or not p.get("pay_grade"):
            problems.append(f"profile {pid}: id and pay_grade are required")
        if not isinstance(p.get("has_dependents"), bool):
            problems.append(f"profile {pid}: has_dependents must be true or false")
        if not isinstance(p.get("anchor_bedrooms"), int) or not 0 <= p["anchor_bedrooms"] <= 4:
            problems.append(f"profile {pid}: anchor_bedrooms must be an integer 0-4")
        share = p.get("cost_share_monthly")
        if not isinstance(share, (int, float)) or isinstance(share, bool) or not 0 < share < 1000:
            problems.append(f"profile {pid}: cost_share_monthly must be the DTMO out-of-pocket dollars "
                            f"for this cell (found {share!r})")
    agg.fail_if([f"{path.name}: {p}" for p in problems], TOOL)
    return profiles, float(target), cfg.get("cost_share") or {}


def load_classes(path: Path) -> dict:
    """A13 breaks per metric, for the class counts in the manifest."""
    cfg = load_json(path, "A13 classification config")
    metrics = cfg.get("metrics") or {}
    for name in CLASSED:
        if name not in metrics or "breaks" not in metrics[name] or "class_labels" not in metrics[name]:
            agg.die(TOOL, f"{path.name} needs metrics.{name}.breaks and class_labels (run `make check-config`)")
    return metrics


def read_table(path: Path, needed: set[str], node: str) -> list[dict]:
    if not path.exists():
        agg.die(TOOL, f"{node} not found: {path} (run `make benchmarks` first)")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not needed <= set(reader.fieldnames):
            agg.die(TOOL, f"{node} {path.name} needs {sorted(needed)}; found {reader.fieldnames}")
        return list(reader)


def parse_bool(raw: str) -> bool | None:
    return {"true": True, "1": True, "false": False, "0": False}.get(raw.strip().lower())


def load_bah(path: Path, problems: list[str]) -> dict[tuple[str, str, bool], float]:
    rates: dict[tuple[str, str, bool], float] = {}
    for line, r in enumerate(read_table(path, {"mha", "pay_grade", "has_dependents", "monthly_rate"}, "B4"),
                             start=2):
        deps = parse_bool(r["has_dependents"])
        try:
            rate = float(r["monthly_rate"])
        except ValueError:
            rate = float("nan")
        if deps is None:
            problems.append(f"B4 line {line}: has_dependents {r['has_dependents']!r} is not true/false")
            continue
        if not math.isfinite(rate) or rate <= 0:
            problems.append(f"B4 line {line}: monthly_rate {r['monthly_rate']!r} is not a positive number")
            continue
        rates[(r["mha"].strip().upper(), r["pay_grade"].strip().upper(), deps)] = rate
    return rates


def cost(raw: str | None, where: str, problems: list[str]) -> float | None:
    """A blank cell means no benchmark; anything else must be a finite number > 0."""
    s = (raw or "").strip()
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        problems.append(f"{where}: {s!r} is not a number")
        return None
    if not math.isfinite(v) or v <= 0:
        problems.append(f"{where}: {s!r} must be greater than zero")
        return None
    return v


def manifest_beside(csv_path: Path, name: str) -> dict | None:
    p = csv_path.with_name(name)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# --- metric arithmetic ----------------------------------------------------------

def num(v: float, places: int) -> str:
    """Fixed decimals, never '-0.00' (float noise around an exact zero)."""
    return f"{round(v, places) + 0.0:.{places}f}"


def metrics(bah: float, share: float, c: float | None, target: float) -> dict:
    if c is None:
        return {k: "" for k in METRIC_FIELDS}
    r = bah / c
    adequacy = (bah + share) / c
    return {"coverage_ratio": num(r, 4), "design_coverage": num(1 - share / c, 4),
            "adequacy_ratio": num(adequacy, 4), "adequacy_gap": num(adequacy - 1, 4),
            "surplus_usd": num(bah - c, 2), "design_gap_usd": num(bah + share - c, 2),
            "flat95_gap": num(r - target, 4)}


def class_counts(values: list[float], spec: dict) -> dict[str, int]:
    """Half-open [lower, upper) classes, as A13 defines them."""
    counts = {label: 0 for label in spec["class_labels"]}
    for v in values:
        counts[spec["class_labels"][bisect.bisect_right(spec["breaks"], v)]] += 1
    return counts


def col(rows: list[dict], name: str) -> list[float]:
    return [float(r[name]) for r in rows if r.get(name)]


def summarize(rows: list[dict], target: float, classes: dict) -> dict:
    valued = [r for r in rows if r["adequacy_ratio"]]
    if not valued:
        return {"mhas": len(rows), "mhas_with_value": 0}
    adequacy, ratio = col(valued, "adequacy_ratio"), col(valued, "coverage_ratio")
    short_flat = {r["mha"] for r in valued if float(r["coverage_ratio"]) < target}
    short_design = {r["mha"] for r in valued if float(r["adequacy_ratio"]) < 1}
    return {
        "mhas": len(rows),
        "mhas_with_value": len(valued),
        "adequacy_ratio": {"min": min(adequacy), "median": round(statistics.median(adequacy), 4),
                           "max": max(adequacy)},
        "coverage_ratio": {"min": min(ratio), "median": round(statistics.median(ratio), 4), "max": max(ratio)},
        "design_coverage_median": round(statistics.median(col(valued, "design_coverage")), 4),
        "design_gap_usd_median": round(statistics.median(col(valued, "design_gap_usd")), 2),
        "mhas_below_design": len(short_design),
        "mhas_at_or_above_full_cost": sum(r >= 1 for r in ratio),
        "flat95_vs_design": {
            "mhas_below_flat_95": len(short_flat),
            "short_under_flat_95_only": sorted(short_flat - short_design),
            "short_under_design_only": sorted(short_design - short_flat),
        },
        **{f"{name}_classes": class_counts(col(valued, name), classes[name]) for name in CLASSED},
    }


def summarize_crosscheck(rows: list[dict]) -> dict:
    valued = [r for r in rows if r["safmr_adequacy_ratio"]]
    if not valued:
        return {"mhas_with_value": 0}
    adequacy = col(valued, "safmr_adequacy_ratio")
    both = [float(r["adequacy_ratio"]) - float(r["safmr_adequacy_ratio"]) for r in valued if r["adequacy_ratio"]]
    return {
        "mhas_with_value": len(valued),
        "adequacy_ratio": {"min": min(adequacy), "median": round(statistics.median(adequacy), 4),
                           "max": max(adequacy)},
        "mhas_below_design": sum(a < 1 for a in adequacy),
        "median_adequacy_diff_zori_minus_safmr": round(statistics.median(both), 4) if both else None,
    }


# --- main -----------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bah-rates", type=Path, required=True, help="B4 bah_rates.csv")
    ap.add_argument("--zori", type=Path, required=True, help="B8 mha_zori.csv")
    ap.add_argument("--safmr", type=Path, help="B10 mha_safmr.csv (rent cross-check)")
    ap.add_argument("--ownership", type=Path, help="B11 mha_ownership.csv (needed for buy mode)")
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    ap.add_argument("--mode", choices=["both", "rent", "buy"], default="both")
    ap.add_argument("--profiles", type=Path, default=ROOT / "config" / "profiles.json")
    ap.add_argument("--classification", type=Path, default=ROOT / "config" / "classification.json")
    args = ap.parse_args()

    do_rent, do_buy = args.mode in ("both", "rent"), args.mode in ("both", "buy")
    if do_rent and not args.safmr:
        agg.die(TOOL, "rent mode needs --safmr (B10) for the bedroom-matched cross-check")
    if do_buy and not args.ownership:
        agg.die(TOOL, "buy mode needs --ownership (B11 mha_ownership.csv)")

    profiles, target, cost_share_cfg = load_profiles(args.profiles)
    classes = load_classes(args.classification)
    problems: list[str] = []
    warnings: list[str] = []
    print("2.5 computed metrics: adequacy = (BAH + member cost share) / benchmark, target 1.00")
    print("  " + ", ".join(f"{p['id']} (cost share ${p['cost_share_monthly']:,.0f})" for p in profiles))

    # B8 defines the MHA universe: every real MHA, one row each.
    zori = {r["mha"]: r for r in read_table(args.zori, {"mha", "zip_coverage", "zori_utilities_adjusted"}, "B8")}
    mhas = sorted(zori)
    bah = load_bah(args.bah_rates, problems)
    agg.fail_if(problems[:25], TOOL)

    for p in profiles:
        missing = [m for m in mhas if (m, p["pay_grade"].upper(), p["has_dependents"]) not in bah]
        if missing:
            problems.append(f"B4 has no {p['pay_grade']} {'with' if p['has_dependents'] else 'without'}-"
                            f"dependents rate for {len(missing)} MHA(s) ({p['id']}): {', '.join(missing[:10])}")

    safmr: dict[tuple[str, int], dict] = {}
    if do_rent:
        for r in read_table(args.safmr, {"mha", "bedrooms", "safmr_median"}, "B10"):
            safmr[(r["mha"], int(r["bedrooms"]))] = r
        if {m for m, _ in safmr} != set(mhas):
            diff = sorted({m for m, _ in safmr} ^ set(mhas))
            problems.append(f"B8 and B10 cover different MHAs ({len(diff)}): {', '.join(diff[:10])}")
        for p in profiles:
            gaps = [m for m in mhas if (m, p["anchor_bedrooms"]) not in safmr]
            if gaps:
                problems.append(f"B10 has no {p['anchor_bedrooms']}-bedroom row for {len(gaps)} MHA(s): "
                                f"{', '.join(gaps[:10])}")

    own: dict[str, dict] = {}
    if do_buy:
        own = {r["mha"]: r for r in read_table(
            args.ownership, {"mha", "zhvi_median", "own_housing_monthly", "own_total_monthly"}, "B11")}
        if set(own) != set(mhas):
            diff = sorted(set(own) ^ set(mhas))
            problems.append(f"B8 and B11 cover different MHAs ({len(diff)}): {', '.join(diff[:10])}")
    agg.fail_if(problems, TOOL)

    # Temporal alignment and lineage, read from the manifests the benchmark steps wrote.
    b8_man = manifest_beside(args.zori, "mha_zori_manifest.json")
    if b8_man is None:
        agg.die(TOOL, f"mha_zori_manifest.json not found beside {args.zori} (run `make zori`)")
    windows = {"B8": b8_man.get("window_months_used")}
    if do_buy:
        b9_man = manifest_beside(args.ownership, "mha_zhvi_manifest.json")
        b11_man = manifest_beside(args.ownership, "mha_ownership_manifest.json")
        if b9_man is None or b11_man is None:
            agg.die(TOOL, f"mha_zhvi_manifest.json and mha_ownership_manifest.json must sit beside "
                          f"{args.ownership} (run `make benchmarks`)")
        windows["B9"] = b9_man.get("window_months_used")
        windows["B11_rate"] = b11_man.get("rate", {}).get("window")
        if windows["B8"] != windows["B9"]:
            problems.append(f"B8 (ZORI) and B9 (ZHVI) cover different months: {windows['B8']} vs "
                            f"{windows['B9']}. Rebuild both with the same WINDOW.")
        for node, fname in (("B8", "mha_zori.csv"), ("B9", "mha_zhvi.csv")):
            beside = args.ownership.with_name(fname)
            recorded = b11_man.get("input_sha256", {}).get(node)
            if beside.exists() and recorded and recorded != agg.sha256(beside):
                problems.append(f"B11 was built from a different {fname} than the one beside it. "
                                "Run `make ownership` again.")
        b9_months = windows["B9"] or []
        if b9_months and windows["B11_rate"] != f"{b9_months[0]}:{b9_months[-1]}":
            warnings.append(f"B11 mortgage rate window {windows['B11_rate']} differs from the B9 home value "
                            f"months {b9_months[0]}:{b9_months[-1]}")
    agg.fail_if(problems, TOOL)

    # --- compute ---
    rent_rows: list[dict] = []
    buy_rows: list[dict] = []
    for p in profiles:
        grade, deps, beds = p["pay_grade"].upper(), p["has_dependents"], p["anchor_bedrooms"]
        share = float(p["cost_share_monthly"])
        for m in mhas:
            b = bah[(m, grade, deps)]
            base = {"profile": p["id"], "mha": m, "pay_grade": grade, "has_dependents": str(deps).lower(),
                    "bah_monthly": agg.fmt(b), "cost_share_monthly": agg.fmt(share)}
            if do_rent:
                c = cost(zori[m]["zori_utilities_adjusted"], f"B8 {m} zori_utilities_adjusted", problems)
                s = cost(safmr[(m, beds)]["safmr_median"], f"B10 {m} {beds}BR safmr_median", problems)
                cross = metrics(b, share, s, target)
                rent_rows.append({
                    **base, "cost_monthly": agg.fmt(c), **metrics(b, share, c, target),
                    "zori_zip_coverage": zori[m]["zip_coverage"], "safmr_bedrooms": beds,
                    "safmr_monthly": agg.fmt(s), "safmr_coverage_ratio": cross["coverage_ratio"],
                    "safmr_adequacy_ratio": cross["adequacy_ratio"],
                    "safmr_design_gap_usd": cross["design_gap_usd"],
                    "status": "ok" if c is not None else "no_zori",
                })
            if do_buy:
                o = own[m]
                c = cost(o["own_total_monthly"], f"B11 {m} own_total_monthly", problems)
                housing = cost(o["own_housing_monthly"], f"B11 {m} own_housing_monthly", problems)
                if c is not None:
                    status = "ok"
                elif housing is not None:
                    status, c = "piti_only_no_zori", housing     # decision 2.4: PITI alone
                else:
                    status = "no_home_value"
                buy_rows.append({**base, "cost_monthly": agg.fmt(c), "own_housing_monthly": agg.fmt(housing),
                                 **metrics(b, share, c, target), "status": status})
    agg.fail_if(problems[:25] + ([f"... and {len(problems) - 25} more"] if len(problems) > 25 else []), TOOL)

    lo, hi = PLAUSIBLE_RATIO
    for label, rows, prefixes in (("rent", rent_rows, ("", "safmr_")), ("buy", buy_rows, ("",))):
        for prefix in prefixes:
            odd = [f"{r['profile']}/{r['mha']}={r[prefix + 'coverage_ratio']}" for r in rows
                   if r[prefix + "coverage_ratio"] and not lo <= float(r[prefix + "coverage_ratio"]) <= hi]
            if odd:
                warnings.append(f"{len(odd)} {label} {prefix or 'primary '}coverage ratio(s) outside "
                                f"{lo}-{hi}; check joins and units: {', '.join(odd[:5])}")

    # --- write ---
    outputs: list[str] = []
    if do_rent:
        agg.write_csv(args.out / "mha_rent_metrics.csv", RENT_FIELDS, rent_rows)
        outputs.append("mha_rent_metrics.csv")
    if do_buy:
        agg.write_csv(args.out / "mha_buy_metrics.csv", BUY_FIELDS, buy_rows)
        outputs.append("mha_buy_metrics.csv")

    summaries: dict = {}
    for p in profiles:
        entry: dict = {"pay_grade": p["pay_grade"], "has_dependents": p["has_dependents"],
                       "anchor_bedrooms": p["anchor_bedrooms"], "cost_share_monthly": p["cost_share_monthly"]}
        if do_rent:
            mine = [r for r in rent_rows if r["profile"] == p["id"]]
            entry["rent"] = summarize(mine, target, classes)
            entry["rent"]["status_counts"] = {s: sum(r["status"] == s for r in mine) for s in ("ok", "no_zori")}
            entry["rent_safmr_crosscheck"] = summarize_crosscheck(mine)
        if do_buy:
            mine = [r for r in buy_rows if r["profile"] == p["id"]]
            # Summaries compare like with like: PITI-only rows are mapped but not summarized.
            entry["buy"] = {**summarize([r for r in mine if r["status"] == "ok"], target, classes),
                            "mhas": len(mine)}
            entry["buy"]["status_counts"] = {s: sum(r["status"] == s for r in mine)
                                             for s in ("ok", "piti_only_no_zori", "no_home_value")}
        summaries[p["id"]] = entry

    inputs = {"A12": args.profiles, "A13": args.classification, "B4": args.bah_rates, "B8": args.zori}
    if do_rent:
        inputs["B10"] = args.safmr
    if do_buy:
        inputs["B11"] = args.ownership
    nodes = [n for n, on in (("B12", do_rent), ("B13", do_rent), ("B14", do_buy), ("B15", do_buy)) if on]
    manifest = {
        "nodes": nodes,
        "generated_at": agg.now_utc(),
        "inputs": {k: v.name for k, v in inputs.items()},
        "input_sha256": {k: agg.sha256(v) for k, v in inputs.items()},
        "statutory_basis": ("37 U.S.C. 403(b)(3): BAH = local cost of adequate housing - 5% of the national average "
                            "cost for the pay grade and dependency status"),
        "cost_share": {**{k: v for k, v in cost_share_cfg.items() if not k.startswith("_")},
                       "per_profile": {p["id"]: p["cost_share_monthly"] for p in profiles}},
        "flat_95_sensitivity_target": target,
        "definitions": {
            "coverage_ratio": "BAH / cost_monthly",
            "design_coverage": "1 - cost_share_monthly / cost_monthly",
            "adequacy_ratio": "(BAH + cost_share_monthly) / cost_monthly; target 1.00",
            "adequacy_gap": "adequacy_ratio - 1 (= coverage_ratio - design_coverage); the 2.6 test variable",
            "surplus_usd": "BAH - cost_monthly",
            "design_gap_usd": "BAH + cost_share_monthly - cost_monthly",
            "flat95_gap": "coverage_ratio - flat_95_sensitivity_target",
            "rent_cost": "B8 zori_utilities_adjusted (ZORI grossed up to utilities-inclusive with B5)",
            "rent_crosscheck_cost": "B10 safmr_median at the profile's anchor_bedrooms (gross rent, HUD 40th pct)",
            "buy_cost": "B11 own_total_monthly (PITI + B8 utilities)",
        },
        "windows": {**windows, "B10": "HUD FY2026 SAFMR (fixed vintage, no monthly window)"},
        "mhas": len(mhas),
        "profiles": summaries,
        "warnings": warnings,
        "outputs": outputs,
    }
    agg.write_manifest(args.out / "coverage_metrics_manifest.json", manifest)

    if windows["B8"]:
        print(f"  benchmark months {windows['B8'][0]} to {windows['B8'][-1]}; {len(mhas)} MHAs")
    for pid, s in summaries.items():
        for mode in ("rent", "rent_safmr_crosscheck", "buy"):
            if mode in s and s[mode].get("mhas_with_value"):
                a = s[mode]["adequacy_ratio"]
                line = (f"  {pid:8} {mode:22} adequacy median {a['median']:.3f} "
                        f"(min {a['min']:.3f}, max {a['max']:.3f}); "
                        f"{s[mode]['mhas_below_design']} of {s[mode]['mhas_with_value']} below design")
                if "flat95_vs_design" in s[mode]:
                    line += f" (flat 95%: {s[mode]['flat95_vs_design']['mhas_below_flat_95']})"
                print(line)
    for w in warnings:
        print(f"  warning: {w}")
    for o in outputs:
        print(f"  -> {args.out / o}")


if __name__ == "__main__":
    main()
