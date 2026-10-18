#!/usr/bin/env python3
"""
spatial_stats.py  (2.6 spatial statistics: B17 global Moran's I, B18 LISA / Getis-Ord Gi*)

  B17  global Moran's I                 B12/B14 metrics + B16 weights
  B18  LISA and Gi* cluster classes     B12/B14 metrics + B16 weights

    python pipeline/spatial/spatial_stats.py \
        --geometry data/processed/mha_2026.gpkg \
        --weights-manifest data/interim/spatial_2026/weights_manifest.json \
        --rent-metrics data/interim/metrics_2026/mha_rent_metrics.csv \
        --buy-metrics data/interim/metrics_2026/mha_buy_metrics.csv \
        --out data/interim/spatial_2026

------------------------------------------------------------------------------
What is tested
------------------------------------------------------------------------------
Hypothesis H1 (research proposal): adequacy gaps are spatially autocorrelated
across MHAs rather than randomly placed. One test is run for every

  profile   each A12 profile (e5_dep primary, o3_dep contrast)
  mode      rent (B12/B13, primary) and buy (B14/B15)
  variable  adequacy_gap  = (BAH + cost share) / benchmark - 1   primary
            flat95_gap    = BAH / benchmark - 0.95               sensitivity

The primary test is the A12 default profile, rent mode, adequacy_gap. The
flat-95% gap is kept because the statutory cost share is the same dollars
everywhere, so a fixed 95% target scores cheap MHAs short and expensive MHAs
over by design. Cost levels cluster, so the flat-95% gap should show more
autocorrelation than adequacy_gap; the manifest reports both values of I
side by side, which measures how much the fixed-95% reading would add.

------------------------------------------------------------------------------
Method
------------------------------------------------------------------------------
  weights   k-nearest neighbours as specified by B16 (k, CRS, scope, tie
            break), rebuilt for each test on the MHAs that have a value.
            Taking a subset of the full KNN matrix instead would leave some
            MHAs with fewer than k neighbours.
  B17       Moran's I with row-standardized weights; inference by random
            permutation (pseudo p-value, p_sim) with the normal approximation
            reported beside it (one-sided pseudo p, esda's global default).
            For the adequacy_gap tests, I is also
            computed with k = 4 and k = 8 and with queen contiguity (islands
            dropped) to show the result does not depend on the choice of k.
  B18 LISA  local Moran's I_i with row-standardized weights and conditional
            permutation. Quadrant HH / LH / LL / HL by the sign of the MHA's
            value and of its neighbours' average, both relative to the mean.
            An MHA is given its quadrant as a cluster class when
            p_sim < alpha, and NS otherwise (A13 cluster codes).
            Benjamini-Hochberg false-discovery-rate significance is
            reported in a separate column (lisa_fdr_significant).
  B18 Gi*   Getis-Ord Gi* (self included) with binary weights. It is
            computed on the ratio behind each gap (adequacy_ratio for
            adequacy_gap, coverage_ratio for flat95_gap). The two differ by
            a constant, and the standardized Gi* z-score and its permutation
            p-value are unchanged by adding a constant, so the result is the
            Gi* of the gap. The ratio is used because the unstandardized G
            divides by the sum of the variable, which is near zero for a gap.
            hot = z > 0 and p_sim < alpha; cold = z < 0 and p_sim < alpha.
  inference permutations and seed are fixed (defaults 9999 and 2026), so the
            same inputs give the same output. Local tests (LISA, Gi*) use
            two-sided pseudo p-values, set explicitly because esda's default
            is changing between releases. With n permutations the smallest
            attainable p_sim is 1 / (n + 1) for the global test and about
            2 / (n + 1) for the two-sided local tests; 9999 permutations keep
            that floor (0.0002) well below the Benjamini-Hochberg cut-offs
            for ~290 local tests, where 999 (floor 0.002) would not.

------------------------------------------------------------------------------
Output (written to --out)
------------------------------------------------------------------------------
  mha_spatial_stats.csv          long: one row per test x MHA, including MHAs
                                 that were not tested (status says why)
  spatial_stats_manifest.json    inputs and hashes, method parameters, one
                                 entry per test (global I, sensitivity, LISA
                                 and Gi* class counts, FDR cut-off), the
                                 headline result, warnings
  mha_lisa_<profile>_rent_map.png  LISA cluster map of the primary test
                                 (needs matplotlib; skipped with a warning
                                 if it is missing, or with --no-map)

------------------------------------------------------------------------------
Validation (loud)
------------------------------------------------------------------------------
  * B16 was built from the same B6 file passed here (SHA-256 lineage)
  * metrics tables have the needed columns, and every profile in them is in A12
  * every tested value is a finite number, and each test has more than k MHAs
    and a variable that is not constant
  * warns (does not stop) when an in-scope MHA in the metrics has no polygon
    in B6, and when an MHA's adequacy_gap and adequacy_ratio disagree
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "benchmarks"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mha_agg as agg  # noqa: E402
import build_weights as bw  # noqa: E402

TOOL = "spatial_stats"

try:
    import esda
    import numpy as np
except ImportError as e:  # pragma: no cover - environment problem, reported loudly
    sys.exit(f"{TOOL}: {e.name} is not installed. Run `pip install -r requirements.txt`.")

# (variable tested, positive ratio it is a constant shift of, role)
VARIABLES = [("adequacy_gap", "adequacy_ratio", 1.0, "primary"),
             ("flat95_gap", "coverage_ratio", None, "sensitivity")]
NEEDED = {"profile", "mha", "status", "adequacy_gap", "adequacy_ratio", "flat95_gap", "coverage_ratio"}
QUADRANT = {1: "HH", 2: "LH", 3: "LL", 4: "HL"}          # PySAL scheme (geoda_quads=False)
LOCAL_ALTERNATIVE = "two-sided"
FIELDS = ["profile", "mode", "variable", "mha", "status", "value", "neighbors",
          "lisa_i", "lisa_quadrant", "lisa_p_sim", "lisa_fdr_significant", "cluster",
          "gi_z", "gi_p_sim", "gi_class"]


# --- inputs -------------------------------------------------------------------

def load_json(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        agg.die(TOOL, f"{what} not found: {path}")
    except json.JSONDecodeError as e:
        agg.die(TOOL, f"{path} is not valid JSON: {e}")
    raise AssertionError


def read_metrics(path: Path, node: str) -> list[dict]:
    if not path.exists():
        agg.die(TOOL, f"{node} not found: {path} (run `make metrics` first)")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not NEEDED <= set(reader.fieldnames):
            agg.die(TOOL, f"{node} {path.name} needs {sorted(NEEDED)}; found {reader.fieldnames}")
        return list(reader)


def number(raw: str, where: str, problems: list[str]) -> float | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        problems.append(f"{where}: {s!r} is not a number")
        return None
    if not math.isfinite(v):
        problems.append(f"{where}: {s!r} is not finite")
        return None
    return v


# --- statistics -----------------------------------------------------------------

def bh_significant(p: "np.ndarray", alpha: float) -> tuple["np.ndarray", float | None]:
    """Benjamini-Hochberg (1995) step-up: reject every p at or below the largest
    p_(i) with p_(i) <= i * alpha / n. Returns the mask and that cut-off."""
    n = len(p)
    order = np.sort(p)
    ok = order <= alpha * np.arange(1, n + 1) / n
    if not ok.any():
        return np.zeros(n, dtype=bool), None
    cut = float(order[np.nonzero(ok)[0].max()])
    return p <= cut, cut


def moran(y: "np.ndarray", w, permutations: int, seed: int) -> dict:
    w = copy.deepcopy(w)
    np.random.seed(seed)                    # esda.Moran draws from numpy's global generator
    m = esda.Moran(y, w, transformation="r", permutations=permutations)
    return {"I": round(float(m.I), 4), "EI": round(float(m.EI), 4),
            "z_norm": round(float(m.z_norm), 3), "p_norm": round(float(m.p_norm), 5),
            "z_sim": round(float(m.z_sim), 3), "p_sim": round(float(m.p_sim), 5)}


def run_test(ids: list[str], y: "np.ndarray", gi_y: "np.ndarray", xy: "np.ndarray", g_sub, k: int,
             sens_k: list[int], args, sensitivity: bool) -> tuple[dict, list[dict]]:
    n = len(ids)
    w, _ = bw.knn_weights(ids, xy, k, tool=TOOL)
    result: dict = {"n": n, "weights": f"knn k={k}", "moran": moran(y, w, args.permutations, args.seed)}

    if sensitivity:
        sens: dict = {}
        for k2 in sens_k:
            if k2 == k:
                continue
            if k2 >= n:
                sens[f"knn{k2}"] = {"skipped": f"k={k2} needs more than {k2} MHAs"}
                continue
            wk, _ = bw.knn_weights(ids, xy, k2, tool=TOOL)
            sens[f"knn{k2}"] = {k_: v for k_, v in moran(y, wk, args.permutations, args.seed).items()
                                if k_ in ("I", "p_sim")}
        q = bw.queen_weights(g_sub)
        keep = [i for i, m in enumerate(ids) if q.cardinalities[m] > 0]
        if len(keep) < 3:
            sens["queen"] = {"skipped": f"only {len(keep)} MHA(s) touch another MHA",
                             "islands_dropped": n - len(keep)}
        else:
            g_keep = g_sub.iloc[keep].reset_index(drop=True)
            qk = bw.queen_weights(g_keep)
            if qk.islands:   # cannot happen after dropping islands, but never test on a broken graph
                agg.die(TOOL, f"queen weights still have islands after dropping them: {qk.islands[:5]}")
            sens["queen"] = {**{k_: v for k_, v in moran(y[keep], qk, args.permutations, args.seed).items()
                                if k_ in ("I", "p_sim")},
                             "n": len(keep), "islands_dropped": n - len(keep)}
        result["moran_sensitivity"] = sens

    # alternative is set explicitly: esda's default for local permutation tests is changing, and an
    # unpinned default would let a library upgrade change these p-values without any code change.
    lisa = esda.Moran_Local(y, copy.deepcopy(w), transformation="r", permutations=args.permutations,
                            seed=args.seed, n_jobs=1, alternative=LOCAL_ALTERNATIVE)
    gi = esda.G_Local(gi_y, copy.deepcopy(w), transform="B", permutations=args.permutations, star=True,
                      seed=args.seed, n_jobs=1, alternative=LOCAL_ALTERNATIVE)
    lisa_p = np.asarray(lisa.p_sim, dtype=float)
    fdr_mask, fdr_cut = bh_significant(lisa_p, args.alpha)
    rows = []
    for i, m in enumerate(ids):
        quad = QUADRANT[int(lisa.q[i])]
        sig = lisa_p[i] < args.alpha
        gz, gp = float(gi.Zs[i]), float(gi.p_sim[i])
        rows.append({
            "mha": m, "status": "tested", "neighbors": k,
            "lisa_i": f"{float(lisa.Is[i]):.4f}", "lisa_quadrant": quad, "lisa_p_sim": f"{lisa_p[i]:.4f}",
            "lisa_fdr_significant": str(bool(fdr_mask[i])).lower(),
            "cluster": quad if sig else "NS",
            "gi_z": f"{gz:.3f}", "gi_p_sim": f"{gp:.4f}",
            "gi_class": ("hot" if gz > 0 else "cold") if gp < args.alpha else "ns"})

    clusters = {c: sum(r["cluster"] == c for r in rows) for c in ("HH", "LL", "HL", "LH", "NS")}
    gi_counts = {c: sum(r["gi_class"] == c for r in rows) for c in ("hot", "cold", "ns")}
    result["lisa"] = {
        "clusters": clusters,
        "significant": n - clusters["NS"],
        "fdr_cutoff_p": fdr_cut,
        "fdr_significant": int(fdr_mask.sum()),
        "fdr_clusters": {c: sum(r["cluster"] == c and r["lisa_fdr_significant"] == "true" for r in rows)
                         for c in ("HH", "LL", "HL", "LH")},
    }
    result["gi_star"] = {
        **gi_counts,
        "hh_also_hot": sum(r["cluster"] == "HH" and r["gi_class"] == "hot" for r in rows),
        "ll_also_cold": sum(r["cluster"] == "LL" and r["gi_class"] == "cold" for r in rows),
    }
    return result, rows


# --- map ------------------------------------------------------------------------

def draw_map(path: Path, g_all, rows: list[dict], test: dict, label: str, classes: dict,
             warnings: list[str]) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Patch
    except ImportError:
        warnings.append("matplotlib is not installed; cluster map skipped (pip install -r requirements.txt)")
        return False
    by = {r["mha"]: r for r in rows}
    g = g_all[g_all["mha"].map(bw.in_scope)].copy()
    g["cluster"] = g["mha"].map(lambda m: by[m]["cluster"] if m in by and by[m]["status"] == "tested" else "")
    fig, ax = plt.subplots(figsize=(11, 7), dpi=110)
    untested = g[g["cluster"] == ""]
    if len(untested):
        untested.plot(ax=ax, facecolor="none", edgecolor="#9a9a9a", linewidth=0.4, hatch="////")
    handles = []
    for code in ("HH", "LL", "HL", "LH", "NS"):
        part = g[g["cluster"] == code]
        spec = classes.get(code, {})
        color = spec.get("color", "#cccccc")
        if len(part):
            part.plot(ax=ax, color=color, edgecolor="#555555", linewidth=0.25)
        handles.append(Patch(facecolor=color, edgecolor="#555555",
                             label=f"{spec.get('label', code)} ({len(part)})"))
    if len(untested):
        handles.append(Patch(facecolor="none", edgecolor="#9a9a9a", hatch="////",
                             label=f"No value ({len(untested)})"))
    mo = test["moran"]
    ax.set_title(f"LISA clusters of the adequacy gap: {label}, rent mode\n"
                 f"Global Moran's I = {mo['I']:.3f} (pseudo p = {mo['p_sim']:.4f}, n = {test['n']}), "
                 f"{test['weights']}, {test['permutations']} permutations, p < {test['alpha']}",
                 fontsize=11)
    # Below the map, so it never covers an MHA.
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=3, fontsize=8,
              frameon=False)
    ax.set_axis_off()
    fig.text(0.99, 0.01, "BAH Atlas · CONUS MHAs (EPSG:5070) · DTMO BAH vs Zillow ZORI, utilities-adjusted",
             ha="right", fontsize=7, color="#555555")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return True


# --- main -----------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geometry", type=Path, required=True, help="B6 mha_YYYY.gpkg (the file B16 was built from)")
    ap.add_argument("--weights-manifest", type=Path, required=True, help="B16 weights_manifest.json")
    ap.add_argument("--rent-metrics", type=Path, required=True, help="B12/B13 mha_rent_metrics.csv")
    ap.add_argument("--buy-metrics", type=Path, help="B14/B15 mha_buy_metrics.csv (optional)")
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    ap.add_argument("--profiles", type=Path, default=ROOT / "config" / "profiles.json")
    ap.add_argument("--classification", type=Path, default=ROOT / "config" / "classification.json")
    ap.add_argument("--permutations", type=int, default=9999)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--sensitivity-k", type=int, nargs="*", default=[4, 8],
                    help="other k values for the global-I sensitivity check (default 4 8)")
    ap.add_argument("--no-map", action="store_true", help="skip the cluster map PNG")
    args = ap.parse_args()
    if args.permutations < 99:
        agg.die(TOOL, "--permutations must be at least 99")
    if not 0 < args.alpha < 1:
        agg.die(TOOL, "--alpha must be between 0 and 1")

    problems: list[str] = []
    warnings: list[str] = []

    # --- B16 lineage and spec ---
    wman = load_json(args.weights_manifest, "B16 weights manifest")
    recorded = (wman.get("input_sha256") or {}).get("B6")
    geometry_sha = agg.sha256(args.geometry) if args.geometry.exists() else None
    if recorded != geometry_sha:
        agg.die(TOOL, f"B16 was built from a different B6 file than {args.geometry.name}. "
                      "Run `make weights` again.")
    spec = wman.get("primary") or {}
    k = spec.get("k")
    if spec.get("scheme") != "knn" or not isinstance(k, int):
        agg.die(TOOL, f"{args.weights_manifest.name} has no KNN spec (primary.scheme / primary.k)")
    if wman.get("crs") != bw.ANALYSIS_CRS:
        agg.die(TOOL, f"B16 used CRS {wman.get('crs')}; this script expects {bw.ANALYSIS_CRS}")
    if list((wman.get("scope") or {}).get("excluded_prefixes", [])) != list(bw.OUT_OF_SCOPE_PREFIXES):
        agg.die(TOOL, "B16 was built with a different scope rule; run `make weights` again")

    # --- A12 / A13 ---
    pcfg = load_json(args.profiles, "A12 profiles config")
    profiles = [p for p in pcfg.get("profiles") or [] if p.get("id")]
    if not profiles:
        agg.die(TOOL, f"{args.profiles.name} defines no profiles")
    labels = {p["id"]: p.get("label", p["id"]) for p in profiles}
    roles = {p["id"]: p.get("role", "") for p in profiles}
    primary_profile = pcfg.get("default_profile") or profiles[0]["id"]
    ccfg = load_json(args.classification, "A13 classification config")
    classes = (ccfg.get("clusters") or {}).get("classes") or {}
    missing = [c for c in ("HH", "LL", "HL", "LH", "NS") if c not in classes]
    if missing:
        agg.die(TOOL, f"{args.classification.name} clusters.classes lacks {missing} (run `make check-config`)")

    # --- geometry and metrics ---
    g_all = bw.load_geometry(args.geometry, tool=TOOL)
    geo_index = {m: i for i, m in enumerate(g_all["mha"])}
    xy_all = bw.points(g_all)

    tables = {"rent": (read_metrics(args.rent_metrics, "B12"), args.rent_metrics)}
    if args.buy_metrics:
        tables["buy"] = (read_metrics(args.buy_metrics, "B14"), args.buy_metrics)
    for mode, (rows, path) in tables.items():
        unknown = sorted({r["profile"] for r in rows} - set(labels))
        if unknown:
            problems.append(f"{path.name}: profile(s) {unknown} are not in {args.profiles.name}")
    agg.fail_if(problems, TOOL)

    no_geometry = sorted({r["mha"] for rows, _ in tables.values() for r in rows
                          if bw.in_scope(r["mha"]) and r["mha"] not in geo_index})
    if no_geometry:
        warnings.append(f"{len(no_geometry)} in-scope MHA(s) in the metrics have no B6 polygon and are not "
                        f"tested: {', '.join(no_geometry[:10])}")

    print(f"2.6 spatial statistics: KNN k={k} (B16), {args.permutations} permutations, seed {args.seed}, "
          f"alpha {args.alpha}")

    # --- run every test ---
    out_rows: list[dict] = []
    tests: list[dict] = []
    for mode, (rows, path) in tables.items():
        for p in profiles:
            mine = sorted((r for r in rows if r["profile"] == p["id"]), key=lambda r: r["mha"])
            if not mine:
                warnings.append(f"{path.name} has no rows for profile {p['id']}")
                continue
            for var, ratio_col, shift, var_role in VARIABLES:
                tested: list[tuple[str, float, float]] = []
                status: dict[str, tuple[str, str]] = {}
                for r in mine:
                    m = r["mha"]
                    where = f"{mode} {p['id']} {m}"
                    v = number(r[var], f"{where} {var}", problems)
                    ratio = number(r[ratio_col], f"{where} {ratio_col}", problems)
                    if not bw.in_scope(m):
                        status[m] = ("out_of_scope", "" if v is None else r[var])
                    elif m not in geo_index:
                        status[m] = ("no_geometry", "" if v is None else r[var])
                    elif v is None or ratio is None or (r.get("status") or "ok") != "ok":
                        # Not `ok` (e.g. buy piti_only_no_zori, decision 2.4): a cost without
                        # utilities is not comparable with the others, so it is not tested.
                        status[m] = ("no_value", "")
                    else:
                        if shift is not None and abs((ratio - shift) - v) > 1e-3:
                            warnings.append(f"{where}: {var} {v} is not {ratio_col} {ratio} - {shift}")
                        tested.append((m, v, ratio))
                agg.fail_if(problems[:25], TOOL)
                n = len(tested)
                if n <= k:
                    agg.die(TOOL, f"{mode} {p['id']} {var}: {n} MHAs with a value; needs more than k={k}")
                ids = [t[0] for t in tested]
                y = np.array([t[1] for t in tested])
                if float(np.std(y)) == 0.0:
                    agg.die(TOOL, f"{mode} {p['id']} {var}: every value is the same; nothing to test")
                gi_y = np.array([t[2] for t in tested])
                idx = [geo_index[m] for m in ids]
                g_sub = g_all.iloc[idx].reset_index(drop=True)
                result, rows_t = run_test(ids, y, gi_y, xy_all[idx], g_sub, k, args.sensitivity_k, args,
                                          sensitivity=(var == "adequacy_gap"))
                by = {r["mha"]: r for r in rows_t}
                for r in mine:
                    m = r["mha"]
                    base = {"profile": p["id"], "mode": mode, "variable": var, "mha": m}
                    if m in by:
                        out_rows.append({**base, **by[m], "value": r[var]})
                    else:
                        st, val = status[m]
                        out_rows.append({**base, "status": st, "value": val})
                role = ("primary" if (p["id"] == primary_profile and mode == "rent" and var_role == "primary")
                        else "sensitivity" if var_role == "sensitivity"
                        else roles.get(p["id"]) or "secondary")
                entry = {"profile": p["id"], "mode": mode, "variable": var, "gi_star_on": ratio_col,
                         "role": role, **result,
                         "not_tested": {s: sum(st == s for st, _ in status.values())
                                        for s in ("no_value", "no_geometry", "out_of_scope")}}
                tests.append(entry)
                mo = result["moran"]
                print(f"  {mode:4} {p['id']:7} {var:13} n={n:3}  I={mo['I']:+.4f}  p_sim={mo['p_sim']:.4f}  "
                      f"clusters HH {result['lisa']['clusters']['HH']} LL {result['lisa']['clusters']['LL']} "
                      f"HL {result['lisa']['clusters']['HL']} LH {result['lisa']['clusters']['LH']}  "
                      f"Gi* hot {result['gi_star']['hot']} cold {result['gi_star']['cold']}")

    # --- headline: the primary test and the flat-95% comparison ---
    def find(profile: str, mode: str, var: str) -> dict | None:
        return next((t for t in tests if (t["profile"], t["mode"], t["variable"]) == (profile, mode, var)), None)

    comparison = []
    for t in tests:
        if t["variable"] != "adequacy_gap":
            continue
        f = find(t["profile"], t["mode"], "flat95_gap")
        if f:
            comparison.append({"profile": t["profile"], "mode": t["mode"],
                               "I_adequacy_gap": t["moran"]["I"], "I_flat95_gap": f["moran"]["I"],
                               "I_difference_flat95_minus_adequacy": round(f["moran"]["I"] - t["moran"]["I"], 4)})
    primary = find(primary_profile, "rent", "adequacy_gap")
    headline = None
    if primary:
        sig = primary["moran"]["p_sim"] < args.alpha
        sign = "positive" if primary["moran"]["I"] > primary["moran"]["EI"] else "negative"
        reading = (f"reject spatial randomness at alpha {args.alpha}: {sign} spatial autocorrelation" if sig
                   else f"do not reject spatial randomness at alpha {args.alpha}")
        headline = {
            "test": f"{primary_profile} rent adequacy_gap",
            "n": primary["n"],
            "moran_I": primary["moran"]["I"],
            "p_sim": primary["moran"]["p_sim"],
            "h1_reading": reading,
            "lisa_clusters": primary["lisa"]["clusters"],
            "lisa_fdr_significant": primary["lisa"]["fdr_significant"],
            "gi_star_hot": primary["gi_star"]["hot"],
            "gi_star_cold": primary["gi_star"]["cold"],
        }

    # --- write ---
    agg.write_csv(args.out / "mha_spatial_stats.csv", FIELDS, out_rows)
    outputs = ["mha_spatial_stats.csv"]
    if primary and not args.no_map:
        map_name = f"mha_lisa_{primary_profile}_rent_map.png"
        test_rows = [r for r in out_rows
                     if (r["profile"], r["mode"], r["variable"]) == (primary_profile, "rent", "adequacy_gap")]
        if draw_map(args.out / map_name, g_all, test_rows,
                    {**primary, "permutations": args.permutations, "alpha": args.alpha},
                    labels[primary_profile], classes, warnings):
            outputs.append(map_name)

    inputs = {"A12": args.profiles, "A13": args.classification, "B6": args.geometry,
              "B12": args.rent_metrics, "B16": args.weights_manifest}
    if args.buy_metrics:
        inputs["B14"] = args.buy_metrics
    manifest = {
        "nodes": ["B17", "B18"],
        "generated_at": agg.now_utc(),
        "inputs": {k_: v.name for k_, v in inputs.items()},
        "input_sha256": {k_: agg.sha256(v) for k_, v in inputs.items()},
        "hypothesis": "H1: adequacy gaps are spatially autocorrelated across CONUS MHAs, not randomly placed",
        "method": {
            "weights": {"scheme": "knn", "k": k, "crs": bw.ANALYSIS_CRS, "source": "B16 spec, rebuilt per test "
                        "on the MHAs with a value", "moran_and_lisa": "row-standardized", "gi_star": "binary, "
                        "self included"},
            "permutations": args.permutations,
            "seed": args.seed,
            "alpha": args.alpha,
            "min_attainable_p_sim": {"global": round(1 / (args.permutations + 1), 6),
                                     "local_two_sided": round(2 / (args.permutations + 1), 6)},
            "global": "Moran's I; p_sim from random permutation, p_norm from the normal approximation",
            "lisa": f"local Moran's I_i, conditional permutation, {LOCAL_ALTERNATIVE} pseudo p-value; "
                    "cluster = quadrant where lisa_p_sim < alpha, else NS",
            "fdr": "Benjamini-Hochberg step-up on the LISA p_sim values of each test, at alpha",
            "gi_star": f"Getis-Ord Gi* on the ratio behind each gap (a constant shift: same z and p_sim), "
                       f"conditional permutation, {LOCAL_ALTERNATIVE} pseudo p-value; hot/cold where "
                       "gi_p_sim < alpha",
            "quadrants": "HH, LH, LL, HL: sign of the MHA's value and of its neighbours' average, relative to "
                         "the mean (PySAL scheme)",
            "sensitivity": f"adequacy_gap tests repeat the global I with k in {args.sensitivity_k} and with "
                           "queen contiguity (islands dropped)",
            "software": {"esda": getattr(esda, "__version__", "?"),
                         "libpysal": __import__("libpysal").__version__, "numpy": np.__version__},
        },
        "variables": {
            "adequacy_gap": "(BAH + cost share) / benchmark - 1; target 0 (statutory design). Primary.",
            "flat95_gap": "BAH / benchmark - 0.95. Sensitivity: the fixed-95% reading.",
        },
        "scope": {"rule": (wman.get("scope") or {}).get("rule"),
                  "excluded": (wman.get("scope") or {}).get("excluded", []),
                  "in_scope_without_geometry": no_geometry},
        "headline": headline,
        "flat95_vs_adequacy_moran": comparison,
        "tests": tests,
        "outputs": outputs + ["spatial_stats_manifest.json"],
        "warnings": warnings,
    }
    agg.write_manifest(args.out / "spatial_stats_manifest.json", manifest)

    if headline:
        print(f"  primary ({headline['test']}): I = {headline['moran_I']}, p_sim = {headline['p_sim']}: "
              f"{headline['h1_reading']}")
    for c in comparison:
        print(f"  {c['mode']} {c['profile']}: I flat-95% {c['I_flat95_gap']:+.4f} vs adequacy "
              f"{c['I_adequacy_gap']:+.4f}")
    for w_ in warnings[:10]:
        print(f"  WARNING: {w_}")
    if len(warnings) > 10:
        print(f"  ... and {len(warnings) - 10} more warnings in the manifest")
    print(f"  wrote {args.out}/" + ", ".join(manifest["outputs"]))


if __name__ == "__main__":
    main()
