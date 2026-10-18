#!/usr/bin/env python3
"""
regression.py  (2.6 B19 spatial regression: hypothesis H2, reduced chain D8)

    python pipeline/spatial/regression.py \
        --geometry data/processed/mha_2026.gpkg \
        --weights-manifest data/interim/spatial_2026/weights_manifest.json \
        --rent-metrics data/interim/metrics_2026/mha_rent_metrics.csv \
        --zori data/interim/benchmarks_2026/mha_zori.csv \
        --zori-manifest data/interim/benchmarks_2026/mha_zori_manifest.json \
        --zori-csv data/raw/Zip_zori_uc_sfrcondomfr_sm_month.csv \
        --crosswalk data/interim/bah_2026/zip_mha.csv \
        --density data/interim/context_2026/mha_density.csv \
        --out data/interim/spatial_2026

------------------------------------------------------------------------------
What is tested
------------------------------------------------------------------------------
H2 (research proposal, reduced 18 Oct, decision D8): what the adequacy gaps are
associated with. The rent-mode adequacy_gap (B12) of every A12 profile, the
default profile (E-5 with dependents) primary, is regressed on

  ln_rent          ln(B8 zori_median): the local asking-rent level, before the
                   B5 utilities gross-up
  rent_growth_pct  annualised ZORI growth over the 5 years before the B8 window,
                   in percent per year (A3 history; --growth-years)
  ln_density       ln(B24 density_per_km2): urbanicity

H1 (B17) found the gaps clustered, so ordinary least squares alone would
understate the standard errors if the clustering is left in the residuals. The
regression therefore runs on the same scope and weights as B17: CONUS MHAs
(AK and HI excluded, decision 2.2) with a rent status of `ok`, and B16's
k-nearest-neighbour weights rebuilt on the MHAs in the model, row-standardized.

------------------------------------------------------------------------------
Method
------------------------------------------------------------------------------
  1. Rent growth. For each ZIP in a real MHA: the mean ZORI over the months B8
     used (its manifest's window_months_used, e.g. 2026-01..2026-07), and the
     mean over the same calendar months --growth-years earlier (2021-01..07).
     Matching calendar months keeps seasonality out of the change. A ZIP needs
     --min-months observations in each window (default 3, B8's rule). ZIP growth
     = (end / start) ^ (1 / years) - 1; MHA growth = median over its ZIPs (the
     B8-B10 rule). ZORI covers fewer ZIPs in earlier years, so an MHA's growth
     can rest on fewer ZIPs than its rent level; both counts are written.
  2. OLS (PySAL spreg) with the spatial diagnostics: Moran's I of the residuals
     and the Lagrange-multiplier tests LM-lag, LM-error and their robust forms.
     Collinearity: variance inflation factor per predictor (warning above 5)
     and the condition number.
  3. Model choice, the Anselin (2005) decision rule at --alpha:
       neither LM-lag nor LM-error significant      -> OLS is kept
       only one significant                         -> that model
       both significant                             -> the model whose robust
                                                       test is significant; if
                                                       both or neither are, the
                                                       larger robust statistic
  4. The chosen spatial model by maximum likelihood (spreg ML_Lag or ML_Error,
     full Jacobian). In the lag model the coefficients are not marginal effects:
     with row-standardized weights the average total impact of a predictor is
     beta / (1 - rho), reported beside it. Residual Moran's I is tested again on
     the chosen model (permutation, fixed seed) to show whether it absorbed the
     spatial dependence.
  5. Sensitivity: the primary profile is rerun with the population-weighted
     density (B24 pw_density_per_km2) in place of the crude density, and every
     other A12 profile is run with the primary specification.

  Shared-denominator caveat: the dependent variable divides by the utilities-
  inclusive ZORI, and ln_rent is the log of the same ZORI before the gross-up.
  A negative ln_rent coefficient therefore partly restates that BAH rises less
  than one-for-one with measured rent; it is reported, and the write-up says so.

------------------------------------------------------------------------------
Output (written to --out)
------------------------------------------------------------------------------
  mha_regression.csv            long: one row per profile x CONUS MHA with the
                                variables, growth inputs, the status (modelled
                                or why not), and the OLS and chosen-model
                                residuals for the primary specification
  regression_manifest.json      inputs and SHA-256, windows, method, one entry
                                per model run (OLS table with VIF and
                                standardized betas, diagnostics, choice, spatial
                                model table, residual Moran's I), the headline
                                H2 reading, output SHA-256, warnings

------------------------------------------------------------------------------
Validation (loud)
------------------------------------------------------------------------------
  * B16 was built from the B6 file passed here; B8 was built from the A3 file
    passed here; the B24 file is the one its manifest recorded
  * the growth window lies inside the A3 file
  * every model has more MHAs than k and than predictors + 10, and no predictor
    is constant
  * warns (does not stop) on VIF above 5 and on MHAs left out for want of a
    predictor
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "benchmarks"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mha_agg as agg  # noqa: E402
import zillow_to_mha as zl  # noqa: E402
import build_weights as bw  # noqa: E402

TOOL = "regression"

try:
    import esda
    import numpy as np
    import spreg
    from spreg.diagnostics import vif as spreg_vif
except ImportError as e:  # pragma: no cover - environment problem, reported loudly
    sys.exit(f"{TOOL}: {e.name} is not installed. Run `pip install -r requirements.txt`.")

PREDICTORS = ["ln_rent", "rent_growth_pct", "ln_density"]
VIF_WARN = 5.0
FIELDS = ["profile", "mha", "status", "adequacy_gap", "zori_median", "ln_rent", "rent_growth_pct",
          "growth_zips", "density_per_km2", "ln_density", "pw_density_per_km2", "ln_pw_density",
          "resid_ols", "resid_model"]


# --- inputs -------------------------------------------------------------------

def load_json(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        agg.die(TOOL, f"{what} not found: {path}")
    except json.JSONDecodeError as e:
        agg.die(TOOL, f"{path} is not valid JSON: {e}")
    raise AssertionError


def read_csv(path: Path, needed: set[str], what: str) -> list[dict]:
    if not path.exists():
        agg.die(TOOL, f"{what} not found: {path}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not needed <= set(reader.fieldnames):
            agg.die(TOOL, f"{what} {path.name} needs {sorted(needed)}; found {reader.fieldnames}")
        return list(reader)


def num(raw: object) -> float | None:
    try:
        v = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def shift_months(months: list[str], years: int) -> list[str]:
    return [f"{int(m[:4]) - years:04d}{m[4:]}" for m in months]


def rent_growth(zori_csv: Path, crosswalk: dict[str, str], end_months: list[str], years: int,
                min_months: int) -> tuple[dict[str, tuple[float, int]], dict]:
    """{mha: (annualised growth, ZIPs used)} from ZIP growth between the two windows."""
    lo, hi = zl.SERIES["zori"]["range"]
    start_months = shift_months(end_months, years)
    with zori_csv.open(newline="", encoding="utf-8-sig") as fh:
        header = next(csv.reader(fh), [])
    in_file = sorted(h[:7] for h in header if zl.MONTH_COL.match(h))
    absent = [m for m in start_months + end_months if m not in in_file]
    if absent:
        span = f"{in_file[0]} to {in_file[-1]}" if in_file else "no month columns"
        agg.die(TOOL, f"{years}-year growth needs {', '.join(absent)} in {zori_csv.name} (file spans {span}); "
                      "re-pull A3 or shorten --growth-years")
    end_vals, _, end_used, p1, _, _ = zl.read_zillow(zori_csv, (end_months[0], end_months[-1]), min_months, lo, hi)
    start_vals, _, start_used, p2, _, _ = zl.read_zillow(zori_csv, (start_months[0], start_months[-1]),
                                                         min_months, lo, hi)
    agg.fail_if((p1 + p2)[:25], TOOL)
    by_mha: dict[str, list[float]] = {}
    zips = 0
    for z, mha in crosswalk.items():
        if z in end_vals and z in start_vals and start_vals[z] > 0:
            by_mha.setdefault(mha, []).append((end_vals[z] / start_vals[z]) ** (1 / years) - 1)
            zips += 1
    growth = {m: (statistics.median(v), len(v)) for m, v in by_mha.items()}
    stats = {"end_window_months": end_used, "start_window_months": start_used, "years": years,
             "min_months_per_window": min_months, "zips_with_end": sum(z in end_vals for z in crosswalk),
             "zips_with_start": sum(z in start_vals for z in crosswalk), "zips_with_growth": zips,
             "mhas_with_growth": len(growth)}
    return growth, stats


# --- models ---------------------------------------------------------------------

def pair(t: object) -> list[float]:
    stat, p = t
    return [round(float(stat), 4), round(float(p), 6)]


def choose_model(lm: dict[str, list[float]], alpha: float) -> tuple[str, str]:
    """Anselin (2005) rule on the OLS LM tests. Returns (model, reason)."""
    lag, err = lm["lm_lag"][1] < alpha, lm["lm_error"][1] < alpha
    if not lag and not err:
        return "ols", f"neither LM-lag nor LM-error significant at {alpha}"
    if lag != err:
        return ("lag" if lag else "error"), f"only LM-{'lag' if lag else 'error'} significant at {alpha}"
    rlag, rerr = lm["rlm_lag"][1] < alpha, lm["rlm_error"][1] < alpha
    if rlag != rerr:
        return ("lag" if rlag else "error"), (f"both LM tests significant; only robust LM-"
                                              f"{'lag' if rlag else 'error'} significant at {alpha}")
    model = "lag" if lm["rlm_lag"][0] >= lm["rlm_error"][0] else "error"
    which = "both" if rlag else "neither"
    return model, f"both LM tests significant; {which} robust test significant, larger robust statistic"


def residual_moran(resid: "np.ndarray", w, permutations: int, seed: int) -> dict:
    np.random.seed(seed)                    # esda.Moran draws from numpy's global generator
    m = esda.Moran(np.asarray(resid, dtype=float).ravel(), copy.deepcopy(w), transformation="r",
                   permutations=permutations)
    return {"I": round(float(m.I), 4), "p_sim": round(float(m.p_sim), 5)}


def fit(y: "np.ndarray", X: "np.ndarray", names: list[str], w, alpha: float, permutations: int,
        seed: int) -> tuple[dict, "np.ndarray", "np.ndarray"]:
    """OLS with diagnostics, the rule's choice, and the spatial model when chosen.
    Returns (result, OLS residuals, chosen-model residuals)."""
    n, kx = X.shape
    w = copy.deepcopy(w)
    w.transform = "r"
    yc = y.reshape(-1, 1)
    ols = spreg.OLS(yc, X, w=w, spat_diag=True, moran=True, name_y="adequacy_gap", name_x=names)
    sd_y = float(np.std(y, ddof=1))
    vifs = spreg_vif(ols)
    coefs = []
    for j, name in enumerate(["CONSTANT"] + names):
        t, p = ols.t_stat[j]
        row = {"name": name, "b": round(float(ols.betas[j, 0]), 6), "se": round(float(ols.std_err[j]), 6),
               "t": round(float(t), 3), "p": round(float(p), 6)}
        if j:
            row["std_beta"] = round(float(ols.betas[j, 0]) * float(np.std(X[:, j - 1], ddof=1)) / sd_y, 4)
            row["vif"] = round(float(vifs[j][0]), 3)
        coefs.append(row)
    lm = {"lm_lag": pair(ols.lm_lag), "lm_error": pair(ols.lm_error), "rlm_lag": pair(ols.rlm_lag),
          "rlm_error": pair(ols.rlm_error), "lm_sarma": pair(ols.lm_sarma)}
    resid_ols = np.asarray(ols.u).ravel()
    result: dict = {
        "n": n,
        "ols": {"coefficients": coefs, "r2": round(float(ols.r2), 4), "adj_r2": round(float(ols.ar2), 4),
                "logll": round(float(ols.logll), 3), "aic": round(float(ols.aic), 3),
                "condition_number": round(float(ols.mulColli), 3),
                "jarque_bera_p": round(float(ols.jarque_bera["pvalue"]), 6),
                "breusch_pagan_p": round(float(ols.breusch_pagan["pvalue"]), 6),
                "residual_moran": residual_moran(resid_ols, w, permutations, seed)},
        "lm_tests": lm,
    }
    model, reason = choose_model(lm, alpha)
    result["choice"] = {"model": model, "reason": reason, "rule": "Anselin (2005)", "alpha": alpha}
    resid_model = resid_ols
    if model != "ols":
        cls = spreg.ML_Lag if model == "lag" else spreg.ML_Error
        sp = cls(yc, X, w=w, method="full", name_y="adequacy_gap", name_x=names)
        param = float(sp.rho if model == "lag" else sp.lam)
        rows = []
        for j, name in enumerate(sp.name_x):
            z, p = sp.z_stat[j]
            row = {"name": name, "b": round(float(sp.betas[j, 0]), 6), "se": round(float(sp.std_err[j]), 6),
                   "z": round(float(z), 3), "p": round(float(p), 6)}
            if model == "lag" and name in names:
                row["total_impact"] = round(float(sp.betas[j, 0]) / (1 - param), 6)
            rows.append(row)
        resid_model = np.asarray(sp.u if model == "lag" else sp.e_filtered).ravel()
        result["spatial"] = {
            "model": f"ML_{model.title()}", "method": "full", ("rho" if model == "lag" else "lambda"): round(param, 4),
            "coefficients": rows, "pseudo_r2": round(float(sp.pr2), 4), "logll": round(float(sp.logll), 3),
            "aic": round(float(sp.aic), 3),
            "residual_moran": residual_moran(resid_model, w, permutations, seed),
            "residuals": "u (lag model)" if model == "lag" else "e_filtered (spatially filtered, error model)"}
    return result, resid_ols, resid_model


def reading(result: dict, alpha: float) -> list[dict]:
    """Sign and significance of each predictor in the chosen model."""
    table = (result.get("spatial") or {}).get("coefficients") or result["ols"]["coefficients"]
    stat = "z" if result.get("spatial") else "t"
    out = []
    for row in table:
        if row["name"] not in PREDICTORS:
            continue
        sig = row["p"] < alpha
        out.append({"predictor": row["name"], "b": row["b"], stat: row[stat], "p": row["p"],
                    "reading": (f"{'positive' if row['b'] > 0 else 'negative'} association, significant at {alpha}"
                                if sig else f"no association significant at {alpha}")})
    return out


# --- main -----------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geometry", type=Path, required=True, help="B6 mha_YYYY.gpkg (the file B16 was built from)")
    ap.add_argument("--weights-manifest", type=Path, required=True, help="B16 weights_manifest.json")
    ap.add_argument("--rent-metrics", type=Path, required=True, help="B12 mha_rent_metrics.csv")
    ap.add_argument("--zori", type=Path, required=True, help="B8 mha_zori.csv")
    ap.add_argument("--zori-manifest", type=Path, required=True, help="B8 mha_zori_manifest.json")
    ap.add_argument("--zori-csv", type=Path, required=True, help="A3 Zillow ZORI ZIP CSV (full history)")
    ap.add_argument("--crosswalk", type=Path, required=True, help="B1 zip_mha.csv")
    ap.add_argument("--density", type=Path, required=True, help="B24 mha_density.csv")
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    ap.add_argument("--profiles", type=Path, default=ROOT / "config" / "profiles.json")
    ap.add_argument("--growth-years", type=int, default=5)
    ap.add_argument("--min-months", type=int, default=3)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--permutations", type=int, default=9999, help="for the residual Moran's I")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    if args.growth_years < 1:
        agg.die(TOOL, "--growth-years must be at least 1")

    warnings: list[str] = []

    # --- lineage ---
    wman = load_json(args.weights_manifest, "B16 weights manifest")
    if (wman.get("input_sha256") or {}).get("B6") != (agg.sha256(args.geometry) if args.geometry.exists() else None):
        agg.die(TOOL, f"B16 was built from a different B6 file than {args.geometry.name}. Run `make weights`.")
    k = (wman.get("primary") or {}).get("k")
    if (wman.get("primary") or {}).get("scheme") != "knn" or not isinstance(k, int):
        agg.die(TOOL, f"{args.weights_manifest.name} has no KNN spec (primary.scheme / primary.k)")
    zman = load_json(args.zori_manifest, "B8 manifest")
    if not args.zori_csv.exists():
        agg.die(TOOL, f"A3 ZORI CSV not found: {args.zori_csv}")
    if zman.get("input_sha256") != agg.sha256(args.zori_csv):
        agg.die(TOOL, f"B8 was built from a different A3 file than {args.zori_csv.name}. Run `make zori`.")
    end_months = list(zman.get("window_months_used") or [])
    if not end_months:
        agg.die(TOOL, f"{args.zori_manifest.name} has no window_months_used")
    dman_path = args.density.with_name("mha_density_manifest.json")
    if dman_path.exists():
        recorded = (load_json(dman_path, "B24 manifest").get("output_sha256") or {}).get(args.density.name)
        if recorded and recorded != agg.sha256(args.density):
            agg.die(TOOL, f"{args.density.name} is not the file B24 recorded. Run `make density`.")
    else:
        warnings.append(f"no B24 manifest beside {args.density.name}; its lineage is not checked")

    pcfg = load_json(args.profiles, "A12 profiles config")
    profiles = [p["id"] for p in pcfg.get("profiles") or [] if p.get("id")]
    primary_profile = pcfg.get("default_profile") or profiles[0]

    # --- variables ---
    crosswalk, _ = agg.load_crosswalk(args.crosswalk, TOOL)
    print(f"B19 spatial regression: rent adequacy_gap on {', '.join(PREDICTORS)}; KNN k={k} (B16); "
          f"growth {args.growth_years} years")
    growth, gstats = rent_growth(args.zori_csv, crosswalk, end_months, args.growth_years, args.min_months)
    zori = {r["mha"]: num(r["zori_median"]) for r in read_csv(args.zori, {"mha", "zori_median"}, "B8")}
    dens = {r["mha"]: (num(r["density_per_km2"]), num(r["pw_density_per_km2"]))
            for r in read_csv(args.density, {"mha", "density_per_km2", "pw_density_per_km2"}, "B24")}
    metrics = read_csv(args.rent_metrics, {"profile", "mha", "status", "adequacy_gap"}, "B12")

    g_all = bw.load_geometry(args.geometry, tool=TOOL)
    geo_index = {m: i for i, m in enumerate(g_all["mha"])}
    xy_all = bw.points(g_all)

    out_rows: list[dict] = []
    runs: list[dict] = []
    excluded_summary: dict[str, dict[str, int]] = {}
    for profile in profiles:
        rows = sorted((r for r in metrics if r["profile"] == profile and bw.in_scope(r["mha"])),
                      key=lambda r: r["mha"])
        if not rows:
            warnings.append(f"{args.rent_metrics.name} has no CONUS rows for profile {profile}")
            continue
        data, reasons = [], {}
        for r in rows:
            m = r["mha"]
            y = num(r["adequacy_gap"])
            rent = zori.get(m)
            gr = growth.get(m)
            d, pw = dens.get(m, (None, None))
            base = {"profile": profile, "mha": m, "adequacy_gap": r["adequacy_gap"],
                    "zori_median": agg.fmt(rent), "ln_rent": agg.fmt(math.log(rent), 6) if rent else "",
                    "rent_growth_pct": agg.fmt(gr[0] * 100, 4) if gr else "", "growth_zips": gr[1] if gr else 0,
                    "density_per_km2": agg.fmt(d, 3), "ln_density": agg.fmt(math.log(d), 6) if d else "",
                    "pw_density_per_km2": agg.fmt(pw, 3), "ln_pw_density": agg.fmt(math.log(pw), 6) if pw else ""}
            reason = ("status_" + (r["status"] or "blank") if (r["status"] or "ok") != "ok" or y is None
                      else "no_geometry" if m not in geo_index
                      else "no_rent" if not rent
                      else "no_growth" if not gr
                      else "no_density" if not d or not pw
                      else None)
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
                out_rows.append({**base, "status": reason})
            else:
                data.append((m, y, math.log(rent), gr[0] * 100, math.log(d), math.log(pw), base))
        excluded_summary[profile] = reasons
        n = len(data)
        if n <= max(k, len(PREDICTORS) + 10):
            agg.die(TOOL, f"{profile}: {n} MHAs with every variable; needs more than {max(k, len(PREDICTORS) + 10)}")
        ids = [t[0] for t in data]
        y = np.array([t[1] for t in data])
        idx = [geo_index[m] for m in ids]
        w, _ = bw.knn_weights(ids, xy_all[idx], k, tool=TOOL)
        specs = [("primary", [2, 3, 4])]
        if profile == primary_profile:
            specs.append(("pw_density", [2, 3, 5]))
        for spec, cols in specs:
            X = np.column_stack([[t[c] for t in data] for c in cols])
            names = PREDICTORS if spec == "primary" else ["ln_rent", "rent_growth_pct", "ln_pw_density"]
            constant = [names[j] for j in range(X.shape[1]) if float(np.std(X[:, j])) == 0.0]
            if constant or float(np.std(y)) == 0.0:
                agg.die(TOOL, f"{profile} {spec}: constant variable(s) {constant or ['adequacy_gap']}")
            result, r_ols, r_model = fit(y, X, names, w, args.alpha, args.permutations, args.seed)
            role = ("primary" if profile == primary_profile and spec == "primary"
                    else "sensitivity")
            high = [c["name"] for c in result["ols"]["coefficients"] if c.get("vif", 0) > VIF_WARN]
            if high:
                warnings.append(f"{profile} {spec}: VIF above {VIF_WARN} for {', '.join(high)}")
            runs.append({"profile": profile, "specification": spec, "role": role, "predictors": names,
                         "weights": f"knn k={k}, row-standardized", **result,
                         "h2_reading": reading(result, args.alpha),
                         "not_modelled": reasons})
            if spec == "primary":
                for i, (m, *_rest, base) in enumerate(data):
                    out_rows.append({**base, "status": "modelled", "resid_ols": f"{r_ols[i]:.6f}",
                                     "resid_model": f"{r_model[i]:.6f}"})
            chosen = result["choice"]["model"]
            print(f"  {profile:7} {spec:10} n={result['n']:3}  R2={result['ols']['r2']:.3f}  "
                  f"LM-lag p={result['lm_tests']['lm_lag'][1]:.4f}  LM-error p={result['lm_tests']['lm_error'][1]:.4f}"
                  f"  -> {chosen}")

    out_rows.sort(key=lambda r: (r["profile"], r["mha"]))
    out_csv = args.out / "mha_regression.csv"
    agg.write_csv(out_csv, FIELDS, out_rows)

    primary = next((r for r in runs if r["role"] == "primary"), None)
    headline = None
    if primary:
        headline = {"test": f"{primary_profile} rent adequacy_gap", "n": primary["n"],
                    "model": primary["choice"]["model"], "choice_reason": primary["choice"]["reason"],
                    "ols_r2": primary["ols"]["r2"], "predictors": primary["h2_reading"]}
        sp = primary.get("spatial")
        if sp:
            headline["spatial_parameter"] = {k_: sp[k_] for k_ in ("rho", "lambda") if k_ in sp}
            headline["residual_moran_ols"] = primary["ols"]["residual_moran"]
            headline["residual_moran_model"] = sp["residual_moran"]

    inputs = {"A12": args.profiles, "A3": args.zori_csv, "B1": args.crosswalk, "B6": args.geometry,
              "B8": args.zori, "B12": args.rent_metrics, "B16": args.weights_manifest, "B24": args.density}
    manifest = {
        "nodes": ["B19"],
        "generated_at": agg.now_utc(),
        "inputs": {k_: v.name for k_, v in inputs.items()},
        "input_sha256": {k_: agg.sha256(v) for k_, v in inputs.items()},
        "hypothesis": "H2: adequacy gaps are associated with the local rent level, recent rent growth and "
                      "urbanicity (reduced chain, decision D8)",
        "variables": {
            "adequacy_gap": "B12 rent mode, (BAH + cost share) / utilities-inclusive ZORI - 1 (dependent)",
            "ln_rent": "ln(B8 zori_median), asking rent before the B5 utilities gross-up",
            "rent_growth_pct": f"annualised ZORI growth over {args.growth_years} years, percent per year; "
                               "median over the MHA's ZIPs of (end mean / start mean)^(1/years) - 1",
            "ln_density": "ln(B24 density_per_km2), sum(population) / sum(land km2)",
            "ln_pw_density": "ln(B24 pw_density_per_km2), population-weighted (sensitivity only)",
        },
        "growth_window": gstats,
        "method": {
            "scope": "CONUS MHAs (AK, HI excluded; decision 2.2) with rent status ok and every predictor",
            "weights": f"knn k={k} from B16, rebuilt on the modelled MHAs, row-standardized",
            "ols": "spreg.OLS with spat_diag and Moran's I of residuals; VIF per predictor, condition number",
            "choice": "Anselin (2005) decision rule on LM-lag, LM-error and their robust forms",
            "spatial": "spreg ML_Lag or ML_Error, full Jacobian; lag model total impact = beta / (1 - rho)",
            "residual_moran": f"esda Moran's I, {args.permutations} permutations, seed {args.seed}",
            "alpha": args.alpha,
            "caveat": "shared denominator: adequacy_gap divides by utilities-inclusive ZORI and ln_rent is the "
                      "log of ZORI, so part of a negative ln_rent coefficient is mechanical",
            "software": {"spreg": spreg.__version__, "esda": getattr(esda, "__version__", "?"),
                         "libpysal": __import__("libpysal").__version__, "numpy": np.__version__},
        },
        "not_modelled": excluded_summary,
        "headline": headline,
        "runs": runs,
        "outputs": [out_csv.name, "regression_manifest.json"],
        "output_sha256": {out_csv.name: agg.sha256(out_csv)},
        "warnings": warnings,
    }
    agg.write_manifest(args.out / "regression_manifest.json", manifest)

    if headline:
        print(f"  primary ({headline['test']}): {headline['model']} ({headline['choice_reason']})")
        for p_ in headline["predictors"]:
            print(f"    {p_['predictor']:16} b={p_['b']:+.5f}  p={p_['p']:.4f}  {p_['reading']}")
    for w_ in warnings:
        print(f"  WARNING: {w_}")
    print(f"  wrote {args.out}/" + ", ".join(manifest["outputs"]))


if __name__ == "__main__":
    main()
