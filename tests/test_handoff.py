"""
Tests for the Layer 2 -> Layer 3 handoff (pipeline/handoff/; docs/data-contract.md).

    python -m unittest discover -s tests -v        (or: make test)

The fixture is a miniature data/ tree with five areas:
  CO001  MHA, rent ok, buy ok, in cluster scope
  CO002  MHA, rent no_zori, buy piti_only_no_zori, in scope but untested
  AK400  MHA outside cluster scope (Alaska)
  ZZ001  County Cost Group (BAH rate only)
  XX001  territory bucket (no rate)
B4 holds all 46 rank and dependents cells. B29 and B30 hold the six home types, and
each research profile's B12-B15 cost is its A14 standard blended from them (D19):
E-5 the 2 BR townhouse, O-3 98% of the way from th3 to sfh3, as B31's browser
formula (ICD 5b.4) recomputes it.
Every builder runs as a subprocess, as `make handoff` calls it, against the
repository's own configs; then the validator checks the result. Each negative
test breaks one link and checks that the right check fails. Stdlib only.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "pipeline" / "handoff"
YEAR = 2026
RENT_FIELDS = ["profile", "mha", "pay_grade", "has_dependents", "bah_monthly", "cost_share_monthly",
               "cost_monthly", "coverage_ratio", "design_coverage", "adequacy_ratio", "adequacy_gap",
               "surplus_usd", "design_gap_usd", "flat95_gap", "zori_zip_coverage", "safmr_bedrooms",
               "safmr_monthly", "safmr_coverage_ratio", "safmr_adequacy_ratio", "safmr_design_gap_usd", "status"]
BUY_FIELDS = ["profile", "mha", "pay_grade", "has_dependents", "bah_monthly", "cost_share_monthly",
              "cost_monthly", "own_housing_monthly", "coverage_ratio", "design_coverage", "adequacy_ratio",
              "adequacy_gap", "surplus_usd", "design_gap_usd", "flat95_gap", "status"]
PROFILES = {"e5_dep": ("E5", 126, 2112.0), "o3_dep": ("O3", 151, 2900.0)}
GRADES = [f"E{i}" for i in range(1, 10)] + [f"W{i}" for i in range(1, 6)] + [f"O{i}" for i in range(1, 10)]
TYPES = ["apt1", "apt2", "th2", "th3", "sfh3", "sfh4"]
# B29 rent by home type (CO002 has no ZORI). O-3 = th3 + 0.98 x (sfh3 - th3): CO001 2990.00, AK400 3290.00
RENT_TYPES = {"CO001": [1500.0, 1800.0, 2139.0, 2500.0, 3000.0, 3500.0],
              "AK400": [1700.0, 2000.0, 2400.0, 2800.0, 3300.0, 3900.0]}
# B30 totals (PITI + utilities) by home type; CO002 is PITI only. O-3: AK400 3990, CO001 3790, CO002 2490
OWN_TYPES = {"AK400": [2300.0, 2600.0, 3100.0, 3500.0, 4000.0, 4600.0],
             "CO001": [2100.0, 2400.0, 2905.0, 3300.0, 3800.0, 4400.0],
             "CO002": [1300.0, 1500.0, 1850.5, 2000.0, 2500.0, 3000.0]}
# B33/B34 for the ZIP view (D36): the ZIPs B35 draws and each one's case.
#   80901 CO001  rent from its ZORI at 1.1 x the MHA; buy ok at 1.05 x the MHA's PITI, ZIP tax and premium
#   80902 CO001  rent from scaled SAFMR at 0.9 x the MHA; no ZHVI (zip_no_benchmark)
#   81001 CO002  no ZORI in the MHA (no_zori); buy PITI only at 0.95 x the MHA
#   99701 AK400  rent outside the band (zip_outlier); buy ok at the MHA's PITI, insurance from the state
ZIP_FEATURES = {"80901": "CO001", "80902": "CO001", "81001": "CO002", "99701": "AK400"}
COSTS = {"e5_dep": {"AK400": (2400.0, 3100.0), "CO001": (2139.0, 2905.0), "CO002": (None, 1850.5)},
         "o3_dep": {"AK400": (3290.0, 3990.0), "CO001": (2990.0, 3790.0), "CO002": (None, 2490.0)}}


def rate(code: str, grade: str, deps: bool) -> float:
    """Fixture BAH: the two research cells as in the README above, every other cell a simple rule."""
    for g, _, r in PROFILES.values():
        if (grade, deps) == (g, True):
            return r
    return 1500.0 + 40 * GRADES.index(grade) - (0 if deps else 200) + (300 if code == "AK400" else 0)


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def metrics(bah: float, share: float, cost: float | None) -> dict:
    if cost is None:
        return {k: "" for k in ("cost_monthly", "coverage_ratio", "design_coverage", "adequacy_ratio",
                                "adequacy_gap", "surplus_usd", "design_gap_usd", "flat95_gap")}
    r = bah / cost
    return {"cost_monthly": f"{cost:.2f}", "coverage_ratio": f"{r:.4f}", "design_coverage": f"{1 - share / cost:.4f}",
            "adequacy_ratio": f"{(bah + share) / cost:.4f}", "adequacy_gap": f"{(bah + share) / cost - 1:.4f}",
            "surplus_usd": f"{bah - cost:.2f}", "design_gap_usd": f"{bah + share - cost:.2f}",
            "flat95_gap": f"{r - 0.95:.4f}"}


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "data"
        self.out = self.data / "processed" / "handoff"
        d, y = self.data, YEAR
        interim, bench = d / "interim" / f"bah_{y}", d / "interim" / f"benchmarks_{y}"
        met, spatial, proc = d / "interim" / f"metrics_{y}", d / "interim" / f"spatial_{y}", d / "processed"

        write_csv(interim / "mha_names.csv", ["mha", "name", "mha_class"], [
            {"mha": "AK400", "name": "FAIRBANKS, AK", "mha_class": "mha"},
            {"mha": "CO001", "name": "COLORADO SPRINGS, CO", "mha_class": "mha"},
            {"mha": "CO002", "name": "PUEBLO, CO", "mha_class": "mha"},
            {"mha": "XX001", "name": "TERRITORIES", "mha_class": "unknown"},
            {"mha": "ZZ001", "name": "COUNTY COST GROUP 1", "mha_class": "ccg"}])
        bah_rows = [{"mha": code, "pay_grade": g, "has_dependents": str(dep), "monthly_rate": f"{rate(code, g, dep):.1f}"}
                    for code in ("AK400", "CO001", "CO002", "ZZ001") for g in GRADES for dep in (True, False)]
        write_csv(interim / "bah_rates.csv", ["mha", "pay_grade", "has_dependents", "monthly_rate"], bah_rows)
        write_csv(interim / "zip_mha.csv", ["zip", "mha", "mha_class"], [
            {"zip": "99701", "mha": "AK400", "mha_class": "mha"}, {"zip": "80901", "mha": "CO001", "mha_class": "mha"},
            {"zip": "80902", "mha": "CO001", "mha_class": "mha"}, {"zip": "81001", "mha": "CO002", "mha_class": "mha"},
            {"zip": "00901", "mha": "XX001", "mha_class": "unknown"}, {"zip": "59001", "mha": "ZZ001", "mha_class": "ccg"}])

        rent, buy, own = [], [], []
        for pid, (grade, share, bah) in PROFILES.items():
            for code, buy_status in (("AK400", "ok"), ("CO001", "ok"), ("CO002", "piti_only_no_zori")):
                rent_cost, buy_cost = COSTS[pid][code]
                base = {"profile": pid, "mha": code, "pay_grade": grade, "has_dependents": "true",
                        "bah_monthly": f"{bah:.2f}", "cost_share_monthly": f"{share:.2f}"}
                rent.append({**base, **metrics(bah, share, rent_cost), "zori_zip_coverage": "0.5000",
                             "safmr_bedrooms": 2, "safmr_monthly": "2190.00", "safmr_coverage_ratio": "0.9644",
                             "safmr_adequacy_ratio": f"{(bah + share) / 2190:.4f}",
                             "safmr_design_gap_usd": f"{bah + share - 2190:.2f}",
                             "status": "ok" if rent_cost else "no_zori"})
                buy.append({**base, **metrics(bah, share, buy_cost), "own_housing_monthly": "1850.50",
                            "status": buy_status})
        for code in ("AK400", "CO001", "CO002"):
            own.append({"mha": code, "tax_source": "locality",
                         "insurance_source": "state_fallback" if code == "AK400" else "locality"})
        write_csv(met / "mha_rent_metrics.csv", RENT_FIELDS, rent)
        write_csv(met / "mha_buy_metrics.csv", BUY_FIELDS, buy)
        write_csv(bench / "mha_ownership.csv", ["mha", "tax_source", "insurance_source"], own)
        write_csv(bench / "mha_rent_by_type.csv", ["mha", "home_type", "rent_monthly", "factor_source", "status"], [
            {"mha": code, "home_type": t, "rent_monthly": f"{RENT_TYPES[code][j]:.2f}" if code in RENT_TYPES else "",
             "factor_source": "national" if (code, t) in (("AK400", "apt1"), ("AK400", "apt2"), ("CO001", "sfh4"))
             else "reference" if t.startswith("th") else "metro",
             "status": "ok" if code in RENT_TYPES else "no_zori"}
            for code in ("AK400", "CO001", "CO002") for j, t in enumerate(TYPES)])
        write_csv(bench / "mha_ownership_by_type.csv", ["mha", "home_type", "own_housing_monthly", "own_total_monthly",
                                                         "building_source", "bedroom_source", "status"], [
            {"mha": code, "home_type": t,
             "own_housing_monthly": f"{(OWN_TYPES[code][j] if code == 'CO002' else OWN_TYPES[code][j] - 400):.2f}",
             "own_total_monthly": "" if code == "CO002" else f"{OWN_TYPES[code][j]:.2f}",
             "building_source": "zip", "bedroom_source": "national" if (code, t) == ("CO001", "apt1") else "zip",
             "status": "piti_only_no_zori" if code == "CO002" else "ok"}
            for code in ("AK400", "CO001", "CO002") for j, t in enumerate(TYPES)])

        stats, tests = [], []
        for pid in PROFILES:
            for mode in ("rent", "buy"):
                for var in ("adequacy_gap", "flat95_gap"):
                    tests.append({"profile": pid, "mode": mode, "variable": var, "n": 1, "weights": "knn k=6",
                                  "moran": {"I": 0.151512, "p_sim": 0.00001},
                                  "lisa": {"fdr_cutoff_p": 0.000113}})
                    for code, status in (("AK400", "out_of_scope"),
                                         ("CO001", "tested"),
                                         ("CO002", "no_value")):
                        t = status == "tested"
                        stats.append({"profile": pid, "mode": mode, "variable": var, "mha": code, "status": status,
                                      "cluster": "HH" if t else "", "lisa_p_sim": "0.000123" if t else "",
                                      "lisa_fdr_significant": "true" if t else "", "gi_class": "hot" if t else ""})
        write_csv(spatial / "mha_spatial_stats.csv", ["profile", "mode", "variable", "mha", "status", "cluster",
                                                      "lisa_p_sim", "lisa_fdr_significant", "gi_class"], stats)
        write_json(spatial / "regression_manifest.json", {
            "nodes": ["B19"], "headline": {
                "test": "e5_dep rent adequacy_gap", "n": 2, "model": "error", "ols_r2": 0.29271,
                "ambiguous_form": {"models": ["ML_Error", "ML_Lag"]}, "sample_selection": {"eligible": 3},
                "predictors": [{"predictor": "ln_rent", "b": -0.210614, "p": 2.6e-05, "reading": "negative association",
                                "model_form_agrees": True, "alternative": {"model": "ML_Lag", "b": -0.151069,
                                                                           "p": 5.8e-05, "reading": "negative association"}}]}})
        write_json(spatial / "spatial_stats_manifest.json", {
            "headline": {"test": "e5_dep rent adequacy_gap", "n": 1, "moran_I": 0.1515, "p_sim": 1e-05,
                         "lisa_clusters": {"HH": 1, "LL": 0, "HL": 0, "LH": 0, "NS": 0}, "lisa_fdr_significant": 1},
            "nodes": ["B17", "B18"], "scope": {"excluded": ["AK400"]},
            "method": {"permutations": 99999, "seed": 2026, "alpha": 0.05, "software": {"esda": "2.10.0"}},
            "tests": tests})
        write_json(spatial / "weights_manifest.json", {"node": "B16"})

        def square(x: float) -> dict:
            return {"type": "Polygon", "coordinates": [[[x, 38], [x + 1, 38], [x + 1, 39], [x, 39], [x, 38]]]}
        write_json(proc / f"mha_{y}.geojson", {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"mha": c}, "geometry": square(-105 + i)}
            for i, c in enumerate(("AK400", "CO001", "CO002"))]})
        write_json(proc / f"non_mha_{y}.geojson", {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"mha": c, "class": k}, "geometry": square(-100 + i)}
            for i, (c, k) in enumerate((("XX001", "unknown"), ("ZZ001", "ccg")))]})
        tiles = proc / f"areas_{y}.pmtiles"
        tiles.write_bytes(b"PMTiles" + b"\0" * 2048)
        write_json(proc / f"areas_{y}_manifest.json", {
            "node": "B7", "features": 5, "features_by_class": {"mha": 3, "ccg": 1, "unknown": 1},
            "tippecanoe": "tippecanoe v2.82.0", "output_file": tiles.name,
            "output_sha256": hashlib.sha256(tiles.read_bytes()).hexdigest()})
        write_json(proc / f"non_mha_{y}_geometry_manifest.json", {"node": "B28", "codes_without_polygon": []})
        self.write_zip_view()
        write_json(proc / f"mha_{y}_geometry_manifest.json", {"node": "B6"})
        write_json(interim / "manifest.json", {"nodes": ["B1", "B2", "B3", "B4"]})
        write_json(interim / "rate_components_manifest.json", {"node": "B5"})
        for name in ("mha_zori", "mha_zhvi", "mha_safmr", "mha_ownership", "mha_rent_by_type", "mha_ownership_by_type"):
            write_json(bench / f"{name}_manifest.json", {"node": name})
        write_json(bench / "standards_check_manifest.json", {"node": "A14", "verdict": "PASS"})
        write_json(bench / "mha_tax_insurance_manifest.json", {
            "nodes": ["A8"], "property_tax": {"acs_period": "2020-2024"}, "insurance": {"data_year": 2022}})
        write_json(met / "coverage_metrics_manifest.json", {"nodes": ["B12"], "windows": {
            "B8": ["2026-01", "2026-07"], "B9": ["2026-01", "2026-07"], "B11_rate": "2026-01:2026-07",
            "B10": "HUD FY2026 SAFMR (fixed vintage, no monthly window)"}})
        write_json(d / "raw" / "fetch_manifest.json", {"A9": {"filename": "acs5_2024_zcta.json", "sha256": "0" * 64}})

    def write_zip_view(self) -> None:
        """B33, B34 and B35 as the ZIP view's builder reads them (D36)."""
        d, y = self.data, YEAR
        bench, proc = d / "interim" / f"benchmarks_{y}", d / "processed"
        rent_rows, own_rows = [], []
        for z, code in ZIP_FEATURES.items():
            for j, t in enumerate(TYPES):
                src = "national" if (code, t) in (("AK400", "apt1"), ("AK400", "apt2"), ("CO001", "sfh4")) else "metro"
                rent = {"zip": z, "mha": code, "home_type": t, "base_source": "none", "rent_monthly": "",
                        "factor_source": src, "status": {"81001": "no_zori", "99701": "zip_outlier"}.get(z, "ok")}
                if z in ("80901", "80902"):
                    k, source = (1.1, "zori") if z == "80901" else (0.9, "safmr_scaled")
                    rent.update({"base_source": source, "rent_monthly": f"{RENT_TYPES[code][j] * k:.2f}"})
                rent_rows.append(rent)
                own = {"zip": z, "mha": code, "home_type": t, "own_housing_monthly": "", "own_total_monthly": "",
                       "tax_source": "", "insurance_source": "", "building_source": "zip",
                       "bedroom_source": "national" if (code, t) == ("CO001", "apt1") else "zip"}
                if z == "80901":
                    housing = (OWN_TYPES[code][j] - 400) * 1.05
                    own.update({"own_housing_monthly": f"{housing:.2f}", "own_total_monthly": f"{housing + 400:.2f}",
                                "tax_source": "zip", "insurance_source": "zip", "status": "ok"})
                elif z == "81001":
                    own.update({"own_housing_monthly": f"{OWN_TYPES[code][j] * 0.95:.2f}", "tax_source": "mha",
                                "insurance_source": "mha", "status": "piti_only_no_zori"})
                elif z == "99701":
                    own.update({"own_housing_monthly": f"{OWN_TYPES[code][j] - 400:.2f}",
                                "own_total_monthly": f"{OWN_TYPES[code][j]:.2f}", "tax_source": "mha",
                                "insurance_source": "state_fallback", "status": "ok"})
                else:
                    own["status"] = "zip_no_benchmark"
                own_rows.append(own)
        write_csv(bench / "zip_rent_by_type.csv", ["zip", "mha", "home_type", "base_source", "rent_monthly",
                                                   "factor_source", "status"], rent_rows)
        write_csv(bench / "zip_ownership_by_type.csv", ["zip", "mha", "home_type", "own_housing_monthly",
                                                        "own_total_monthly", "tax_source", "insurance_source",
                                                        "building_source", "bedroom_source", "status"], own_rows)
        write_csv(proc / f"zipcodes_{y}_features.csv", ["zip", "area"],
                  [{"zip": z, "area": a} for z, a in sorted(ZIP_FEATURES.items())])
        tiles = proc / f"zipcodes_{y}.pmtiles"
        tiles.write_bytes(b"PMTiles" + b"\1" * 2048)
        write_json(proc / f"zipcodes_{y}_manifest.json", {
            "node": "B35", "features": len(ZIP_FEATURES), "output_file": tiles.name,
            "output_sha256": {tiles.name: hashlib.sha256(tiles.read_bytes()).hexdigest()}})
        write_json(bench / "zip_rent_by_type_manifest.json", {"node": "B33", "coverage": {
            "base_source": {"zori": 1, "safmr_scaled": 1, "none": 2}},
            "safmr_check": {"zips_with_both": 1, "median_abs_pct_error": 10.0, "share_within_10_pct": 1.0,
                            "share_within_20_pct": 1.0}})
        write_json(bench / "zip_ownership_by_type_manifest.json", {"node": "B34", "coverage": {
            "zips_with_value": 3, "zips_tax_rate_from_zip": 1, "zips_premium_from_zip": 1}})

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_py(self, script: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(HANDOFF / script), *args], capture_output=True, text=True)

    def build(self, ui_text: Path | None = None) -> None:
        d, y, o = self.data, str(YEAR), self.out
        interim, met = d / "interim" / f"bah_{y}", d / "interim" / f"metrics_{y}"
        bench, spatial = d / "interim" / f"benchmarks_{y}", d / "interim" / f"spatial_{y}"
        o.mkdir(parents=True, exist_ok=True)
        (o / f"areas_{y}.pmtiles").write_bytes((d / "processed" / f"areas_{y}.pmtiles").read_bytes())
        (o / f"zipcodes_{y}.pmtiles").write_bytes((d / "processed" / f"zipcodes_{y}.pmtiles").read_bytes())
        b22 = o / f"build_manifest_{y}.json"
        steps = [
            ("build_manifest.py", "--year", y, "--data", str(d), "--out", str(b22)),
            ("build_payload.py", "--year", y, "--names", str(interim / "mha_names.csv"),
             "--bah-rates", str(interim / "bah_rates.csv"), "--rent", str(met / "mha_rent_metrics.csv"),
             "--buy", str(met / "mha_buy_metrics.csv"), "--ownership", str(bench / "mha_ownership.csv"),
             "--spatial-manifest", str(spatial / "spatial_stats_manifest.json"),
             "--build-manifest", str(b22), "--out", str(o / f"payload_{y}.json")),
            ("build_ui_metadata.py", "--year", y, "--names", str(interim / "mha_names.csv"),
             "--coverage-manifest", str(met / "coverage_metrics_manifest.json"),
             "--tax-manifest", str(bench / "mha_tax_insurance_manifest.json"),
             "--spatial-manifest", str(spatial / "spatial_stats_manifest.json"),
             "--regression-manifest", str(spatial / "regression_manifest.json"),
             "--build-manifest", str(b22), "--out", str(o / f"ui_metadata_{y}.json"),
             *(["--ui-text", str(ui_text)] if ui_text else [])),
            ("build_hotspots.py", "--year", y, "--spatial-stats", str(spatial / "mha_spatial_stats.csv"),
             "--spatial-manifest", str(spatial / "spatial_stats_manifest.json"),
             "--payload", str(o / f"payload_{y}.json"), "--build-manifest", str(b22),
             "--out", str(o / f"hotspots_{y}.json")),
            ("build_grid.py", "--year", y, "--names", str(interim / "mha_names.csv"),
             "--bah-rates", str(interim / "bah_rates.csv"), "--rent-by-type", str(bench / "mha_rent_by_type.csv"),
             "--own-by-type", str(bench / "mha_ownership_by_type.csv"), "--ownership", str(bench / "mha_ownership.csv"),
             "--build-manifest", str(b22), "--out", str(o / f"grid_{y}.json")),
            ("build_zip_lookup.py", "--year", y, "--zip-mha", str(interim / "zip_mha.csv"),
             "--build-manifest", str(b22), "--out", str(o / f"zips_{y}.json")),
            ("build_zip_grid.py", "--year", y, "--zip-rent", str(bench / "zip_rent_by_type.csv"),
             "--zip-own", str(bench / "zip_ownership_by_type.csv"),
             "--features", str(d / "processed" / f"zipcodes_{y}_features.csv"),
             "--build-manifest", str(b22), "--out", str(o / f"zipgrid_{y}.json")),
        ]
        for script, *args in steps:
            p = self.run_py(script, *args)
            self.assertEqual(p.returncode, 0, f"{script}: {p.stderr}")
        self.write_sums()

    def write_sums(self) -> None:
        y = YEAR
        lines = [f"{hashlib.sha256((self.out / n).read_bytes()).hexdigest()}  {n}"
                 for n in (f"areas_{y}.pmtiles", f"payload_{y}.json", f"ui_metadata_{y}.json",
                           f"hotspots_{y}.json", f"grid_{y}.json", f"zips_{y}.json", f"zipcodes_{y}.pmtiles",
                           f"zipgrid_{y}.json", f"build_manifest_{y}.json")]
        (self.out / "SHA256SUMS").write_text("\n".join(lines) + "\n")

    def validate(self) -> subprocess.CompletedProcess:
        return self.run_py("validate_handoff.py", "--year", str(YEAR), "--handoff", str(self.out),
                           "--data", str(self.data))

    def payload(self) -> dict:
        return json.loads((self.out / f"payload_{YEAR}.json").read_text())


class TestHandoff(Fixture):
    def test_builds_and_conforms(self) -> None:
        self.build()
        p = self.validate()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("conforms to the data contract", p.stdout)

    def test_payload_contents(self) -> None:
        self.build()
        pay = self.payload()
        b22 = hashlib.sha256((self.out / f"build_manifest_{YEAR}.json").read_bytes()).hexdigest()
        self.assertEqual((pay["schema_version"], pay["bah_year"], pay["build_id"]), ("1.3.0", 2026, b22))
        self.assertEqual(list(pay["areas"]), ["AK400", "CO001", "CO002", "XX001", "ZZ001"])
        co = pay["areas"]["CO001"]
        self.assertEqual((co["class"], co["cluster_scope"], co["caveats"]), ("mha", True, []))
        rent = co["e5_dep"]["rent"]
        # (2112 + 126) / 2139 = 1.0463; design gap 2238 - 2139 = 99; dollars whole, ratios 4 dp
        self.assertEqual((rent["status"], rent["bah_monthly"], rent["cost_monthly"], rent["adequacy_ratio"],
                          rent["design_gap_usd"], rent["caveats"]), ("ok", 2112, 2139, 1.0463, 99,
                                                                      ["utilities_grossed_up"]))
        self.assertEqual(list(rent)[-4:], ["safmr_monthly", "safmr_adequacy_ratio", "safmr_design_gap_usd", "caveats"])
        self.assertEqual(co["e5_dep"]["buy"]["caveats"], ["tax_insurance_locality", "insurance_2022_dollars"])
        c2 = pay["areas"]["CO002"]["e5_dep"]
        self.assertEqual((c2["rent"]["status"], c2["rent"]["adequacy_ratio"], c2["rent"]["safmr_monthly"]),
                         ("no_zori", None, 2190))
        self.assertEqual((c2["buy"]["status"], c2["buy"]["cost_monthly"]), ("piti_only_no_zori", 1851))  # 1850.50 -> 1851
        self.assertEqual(c2["buy"]["caveats"][0], "piti_only_no_zori")
        ak = pay["areas"]["AK400"]
        self.assertEqual((ak["cluster_scope"], ak["caveats"]), (False, ["outside_cluster_scope"]))
        self.assertIn("insurance_state_fallback", ak["e5_dep"]["buy"]["caveats"])
        zz = pay["areas"]["ZZ001"]
        self.assertEqual(zz["caveats"], ["ccg_geometry", "outside_cluster_scope"])
        self.assertEqual((zz["o3_dep"]["rent"]["status"], zz["o3_dep"]["rent"]["bah_monthly"],
                          zz["o3_dep"]["rent"]["cost_share_monthly"], zz["o3_dep"]["rent"]["adequacy_ratio"]),
                         ("ccg_no_benchmark", 2900, 151, None))
        xx = pay["areas"]["XX001"]["e5_dep"]["buy"]
        self.assertEqual((xx["status"], xx["bah_monthly"], xx["cost_share_monthly"], xx["caveats"]),
                         ("no_rate", None, None, []))

    def test_ui_metadata_and_hotspots(self) -> None:
        self.build()
        ui = json.loads((self.out / f"ui_metadata_{YEAR}.json").read_text())
        self.assertEqual(len(ui["metrics"]), 7)
        self.assertEqual(ui["caveats"]["lisa_exploratory"]["level"], "overlay")
        self.assertEqual(ui["areas"]["CO001"], {"name": "COLORADO SPRINGS, CO", "display_name": "COLORADO SPRINGS, CO",
                                               "class": "mha"})
        self.assertEqual(ui["windows"]["property_tax_acs"], "2020-2024")
        hot = json.loads((self.out / f"hotspots_{YEAR}.json").read_text())
        self.assertEqual(set(hot["areas"]), {"CO001", "CO002"})                 # cluster scope only
        self.assertEqual(hot["areas"]["CO001"]["e5_dep"]["rent"],
                         {"status": "tested", "cluster": "HH", "lisa_p_sim": 0.00012,
                          "lisa_fdr_significant": True, "gi_class": "hot"})
        self.assertEqual(hot["areas"]["CO002"]["e5_dep"]["buy"]["cluster"], None)
        self.assertEqual(hot["tests"]["e5_dep"]["rent"],
                         {"n": 1, "k": 6, "permutations": 99999, "alpha": 0.05, "moran_i": 0.1515,
                          "moran_p_sim": 1e-05, "fdr_cutoff": 0.00011})

    def test_zip_lookup_matches_b1(self) -> None:
        self.build()
        zips = json.loads((self.out / f"zips_{YEAR}.json").read_text())
        self.assertEqual(zips["areas"]["CO001"], ["80901", "80902"])
        self.assertEqual(list(zips["areas"]), sorted(zips["areas"]))
        self.assertEqual(self.validate().returncode, 0)

    def test_changed_zip_fails_check_5(self) -> None:
        self.build()
        path = self.out / f"zips_{YEAR}.json"
        doc = json.loads(path.read_text())
        doc["areas"]["CO001"][1] = "80903"
        write_json(path, doc)
        self.write_sums()
        p = self.validate()
        self.assertEqual(p.returncode, 1)
        self.assertIn("B32 differs from B1", p.stdout)

    def zipgrid(self) -> dict:
        return json.loads((self.out / f"zipgrid_{YEAR}.json").read_text())

    def test_zip_grid_contents(self) -> None:
        self.build()
        zg = self.zipgrid()
        self.assertEqual(list(zg["zips"]), ["80901", "80902", "81001", "99701"])
        self.assertEqual(zg["build_id"], self.payload()["build_id"])
        a = zg["zips"]["80901"]
        self.assertEqual(a["area"], "CO001")
        self.assertEqual(a["rent"]["cost"][2], 2353)                         # 2139 x 1.1 = 2352.90, whole dollars
        sets = zg["caveat_sets"]                                             # one copy of each list
        self.assertEqual(sets[0], [])
        self.assertEqual(len(sets), len({tuple(x) for x in sets}))
        self.assertEqual(sets[a["rent"]["caveats"][2]], ["utilities_grossed_up"])
        self.assertEqual(sets[a["rent"]["caveats"][5]], ["utilities_grossed_up", "type_factor_national"])
        self.assertEqual(sets[a["buy"]["caveats"][2]], ["insurance_2022_dollars", "zip_tax_insurance"])
        self.assertEqual(sets[a["buy"]["caveats"][0]],
                         ["insurance_2022_dollars", "type_factor_national", "zip_tax_insurance"])
        self.assertEqual((a["buy"]["cost"][2], a["buy"]["own_housing"][2]), (3030, 2630))  # 2505 x 1.05 = 2630.25, + 400
        b = zg["zips"]["80902"]
        self.assertEqual(sets[b["rent"]["caveats"][0]], ["utilities_grossed_up", "zip_safmr_scaled"])
        self.assertEqual((b["buy"]["status"][0], b["buy"]["cost"][0], b["buy"]["caveats"][0]),
                         ("zip_no_benchmark", None, 0))
        c = zg["zips"]["81001"]
        self.assertEqual((c["rent"]["status"][0], c["rent"]["cost"][0]), ("no_zori", None))
        self.assertEqual((c["buy"]["status"][2], c["buy"]["cost"][2], sets[c["buy"]["caveats"][2]][0]),
                         ("piti_only_no_zori", 1758, "piti_only_no_zori"))    # 1850.50 x 0.95 = 1757.98
        k = zg["zips"]["99701"]
        self.assertEqual(k["rent"]["status"], ["zip_outlier"] * 6)
        self.assertIn("insurance_state_fallback", sets[k["buy"]["caveats"][2]])

    def test_zip_view_runs_the_grid_formula(self) -> None:
        sys.path.insert(0, str(HANDOFF))
        import contract as c
        self.build()
        grid = json.loads((self.out / f"grid_{YEAR}.json").read_text())
        zg = self.zipgrid()
        v = c.zip_view(grid, zg, "80901", "E5", "with", c.STANDARD, "rent")
        # E-5 standard is the 2 BR townhouse; BAH and cost share come from CO001 in B31.
        self.assertEqual((v["bah_monthly"], v["cost_share_monthly"], v["cost_monthly"]), (2112, 126, 2353))
        self.assertEqual((v["adequacy_ratio"], v["design_gap_usd"], v["standard_view"]), (0.9511, -115, True))
        mha = c.grid_view(grid, "CO001", "E5", "with", c.STANDARD, "rent")
        self.assertEqual((mha["bah_monthly"], mha["adequacy_ratio"]), (2112, 1.0463))
        out = c.zip_view(grid, zg, "99701", "E5", "with", c.STANDARD, "rent")
        self.assertEqual((out["status"], out["adequacy_ratio"], out["bah_monthly"]), ("zip_outlier", None, 2112))
        self.assertEqual(c.zip_view(grid, zg, "80902", "E5", "with", "th2", "rent")["caveats"],
                         ["utilities_grossed_up", "zip_safmr_scaled"])

    def test_bad_caveat_index_fails_check_3(self) -> None:
        self.build()
        path = self.out / f"zipgrid_{YEAR}.json"
        doc = self.zipgrid()
        doc["zips"]["80901"]["rent"]["caveats"][0] = 99
        write_json(path, doc)
        self.write_sums()
        p = self.validate()
        self.assertEqual(p.returncode, 1)
        self.assertIn("is not an index into caveat_sets", p.stdout)

    def test_changed_zip_cost_fails_check_5(self) -> None:
        self.build()
        path = self.out / f"zipgrid_{YEAR}.json"
        doc = self.zipgrid()
        doc["zips"]["80901"]["rent"]["cost"][2] = 2354
        write_json(path, doc)
        self.write_sums()
        p = self.validate()
        self.assertEqual(p.returncode, 1)
        self.assertIn("[5] B36 80901 rent th2: cost 2354", p.stdout)

    def test_zip_missing_from_b35_fails_check_4(self) -> None:
        self.build()
        path = self.out / f"zipgrid_{YEAR}.json"
        doc = self.zipgrid()
        del doc["zips"]["99701"]
        write_json(path, doc)
        self.write_sums()
        p = self.validate()
        self.assertEqual(p.returncode, 1)
        self.assertIn("B36 and B35 hold different ZIPs", p.stdout)

    def test_ui_metadata_additions(self) -> None:
        self.build()
        ui = json.loads((self.out / f"ui_metadata_{YEAR}.json").read_text())
        self.assertEqual(ui["no_data_label"], "No adequacy measure")
        self.assertEqual(ui["areas"]["CO001"]["display_name"], "COLORADO SPRINGS, CO")
        self.assertEqual(ui["grid"]["titles"]["metric"], "Show")
        self.assertEqual(ui["grid"]["titles"]["geography"], "Show by")
        self.assertEqual([g["id"] for g in ui["grid"]["geographies"]], ["mha", "zip"])
        self.assertEqual(ui["grid"]["default_geography"], "mha")
        self.assertEqual(ui["caveats"]["zip_bah_constant"]["level"], "zip")
        self.assertIn("zip_outlier", ui["statuses"])
        self.assertEqual(ui["metrics"]["adequacy_ratio"]["off_standard"]["breaks"], [0.5, 0.7, 0.9, 1.1, 1.4, 1.8])
        self.assertNotIn("off_standard", ui["metrics"]["flat95_gap"])
        self.assertEqual(len(ui["metrics"]["flat95_gap"]["ramp_labels"]), 3)
        self.assertEqual(ui["findings"]["h1"]["moran_i"], 0.1515)
        self.assertEqual(ui["findings"]["h2"]["predictors"][0]["b"], -0.2106)
        self.assertEqual(ui["findings"]["h2"]["predictors"][0]["p"], 0.00003)

    def test_changed_finding_fails_check_5(self) -> None:
        self.build()
        path = self.out / f"ui_metadata_{YEAR}.json"
        doc = json.loads(path.read_text())
        doc["findings"]["h1"]["moran_i"] = 0.2
        write_json(path, doc)
        self.write_sums()
        p = self.validate()
        self.assertEqual(p.returncode, 1)
        self.assertIn("findings differ", p.stdout)

    def test_zero_p_value_fails_check_3(self) -> None:
        self.build()
        path = self.out / f"hotspots_{YEAR}.json"
        doc = json.loads(path.read_text())
        doc["areas"]["CO001"]["e5_dep"]["rent"]["lisa_p_sim"] = 0.0
        write_json(path, doc)
        self.write_sums()
        p = self.validate()
        self.assertEqual(p.returncode, 1)
        self.assertIn("cannot be 0", p.stdout)

    def test_changed_value_fails_check_5(self) -> None:
        self.build()
        path = self.out / f"payload_{YEAR}.json"
        pay = self.payload()
        pay["areas"]["CO001"]["e5_dep"]["rent"]["cost_monthly"] = 2140
        path.write_text(json.dumps(pay))
        self.write_sums()
        p = self.validate()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("[5] B20 CO001 e5_dep rent: cost_monthly = 2140", p.stdout)

    def test_stale_build_id_fails_check_7_and_8(self) -> None:
        self.build()
        b22 = self.out / f"build_manifest_{YEAR}.json"
        b22.write_text(b22.read_text().replace('"B22"', '"B22" ', 1))       # a rebuilt B22, payload not rebuilt
        p = self.validate()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("[7] B20: build_id is not the SHA-256 of B22", p.stdout)
        self.assertIn("[8] SHA256SUMS does not match build_manifest_2026.json", p.stdout)

    def test_missing_polygon_fails_check_4(self) -> None:
        self.build()
        geo = self.data / "processed" / f"non_mha_{YEAR}.geojson"
        data = json.loads(geo.read_text())
        data["features"] = data["features"][:1]                               # drop ZZ001's polygon
        geo.write_text(json.dumps(data))
        p = self.validate()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("ZZ001", p.stdout)

    def test_ui_text_must_match_the_contract(self) -> None:
        text = json.loads((ROOT / "config" / "ui_text.json").read_text())
        del text["caveats"]["piti_only_no_zori"]
        bad = Path(self.tmp.name) / "ui_text.json"
        bad.write_text(json.dumps(text))
        with self.assertRaises(AssertionError) as cm:
            self.build(ui_text=bad)
        self.assertIn("missing ['piti_only_no_zori']", str(cm.exception))

    def grid(self) -> dict:
        return json.loads((self.out / f"grid_{YEAR}.json").read_text())

    def test_grid_contents(self) -> None:
        self.build()
        g = self.grid()
        self.assertEqual((g["schema_version"], g["ranks"][:5], g["home_types"], g["dependents"]),
                         ("1.3.0", GRADES[:5], TYPES, ["with", "without"]))
        self.assertEqual((g["cost_share_monthly"]["with"][4], g["cost_share_monthly"]["without"][22]), (126, 187))
        self.assertEqual(g["standards"]["with"][GRADES.index("O3")], {"lower": "th3", "upper": "sfh3", "share": 0.98})
        co = g["areas"]["CO001"]
        self.assertEqual(co["bah"]["with"][GRADES.index("E5")], 2112)
        self.assertEqual(co["rent"]["cost"], RENT_TYPES["CO001"])                       # cents kept
        self.assertEqual(co["rent"]["caveats"][5], ["utilities_grossed_up", "type_factor_national"])
        self.assertEqual(co["buy"]["caveats"][0][-1], "type_factor_national")             # national bedroom ratio
        c2 = g["areas"]["CO002"]
        self.assertEqual((c2["rent"]["status"][0], c2["rent"]["cost"][0]), ("no_zori", None))
        self.assertEqual((c2["buy"]["status"][3], c2["buy"]["cost"][3], c2["buy"]["caveats"][3][0]),
                         ("piti_only_no_zori", 2000.0, "piti_only_no_zori"))
        zz, xx = g["areas"]["ZZ001"], g["areas"]["XX001"]
        self.assertEqual((zz["rent"]["status"], zz["rent"]["cost"]), (["ccg_no_benchmark"] * 6, [None] * 6))
        self.assertEqual(zz["bah"]["without"][0], 1300)
        self.assertEqual((xx["buy"]["status"][0], xx["bah"]["with"][0]), ("no_rate", None))
        ui = json.loads((self.out / f"ui_metadata_{YEAR}.json").read_text())["grid"]
        self.assertEqual((ui["default_rank"], ui["default_dependents"], ui["default_home_type"]), ("E5", "with", "standard"))
        self.assertEqual(ui["standards_text"]["O3"]["with"],
                         "98% of the way from a 3-bedroom townhouse to a 3-bedroom single-family home")
        self.assertEqual(ui["standards_text"]["E1"]["without"], "a 1-bedroom apartment")

    def test_browser_formula_reproduces_the_research_profiles(self) -> None:
        """ICD 5b.4 on B31 alone gives B20's E-5 and O-3 values in every MHA and mode."""
        self.build()
        g, pay = self.grid(), self.payload()
        sys.path.insert(0, str(HANDOFF))
        import contract as c
        checked = 0
        for code, a in pay["areas"].items():
            for pid, (grade, _, _) in PROFILES.items():
                for mode in ("rent", "buy"):
                    v = c.grid_view(g, code, grade, "with", "standard", mode)
                    b = a[pid][mode]
                    self.assertEqual(v["status"], b["status"], (code, pid, mode))
                    for f in ("bah_monthly", "cost_share_monthly", "cost_monthly", "adequacy_ratio", "design_gap_usd",
                              "coverage_ratio", "surplus_usd"):
                        self.assertEqual(v[f], b[f], (code, pid, mode, f))
                    self.assertTrue(v["standard_view"])
                    checked += 1
        self.assertEqual(checked, 5 * 2 * 2)

    def test_browser_formula_off_standard_examples(self) -> None:
        """ICD 5b.5 worked examples: E-1 in a 4 BR single-family home, O-9 in a 1 BR apartment (CO001, rent)."""
        self.build()
        sys.path.insert(0, str(HANDOFF))
        import contract as c
        g = self.grid()
        e1 = c.grid_view(g, "CO001", "E1", "with", "sfh4", "rent")
        # BAH 1500, cost share 115, cost 3500: (1500 + 115) / 3500 = 0.4614; 1615 - 3500 = -1885
        self.assertEqual((e1["bah_monthly"], e1["cost_share_monthly"], e1["cost_monthly"], e1["adequacy_ratio"],
                          e1["design_gap_usd"], e1["standard_view"]), (1500, 115, 3500, 0.4614, -1885, False))
        self.assertEqual(e1["caveats"], ["utilities_grossed_up", "type_factor_national"])
        o9 = c.grid_view(g, "CO001", "O9", "with", "apt1", "rent")
        # BAH 1500 + 40 x 22 = 2380, share 212 (O-7's), cost 1500: 2592 / 1500 = 1.7280; surplus 880
        self.assertEqual((o9["bah_monthly"], o9["cost_share_monthly"], o9["adequacy_ratio"], o9["surplus_usd"]),
                         (2380, 212, 1.728, 880))
        o7 = c.grid_view(g, "CO001", "O7", "with", "standard", "rent")
        # O-7 with dependents: 4 BR single-family x 1.02 = 3570
        self.assertEqual(o7["cost_monthly"], 3570)

    def test_changed_grid_cost_fails_check_5(self) -> None:
        self.build()
        path = self.out / f"grid_{YEAR}.json"
        g = self.grid()
        g["areas"]["AK400"]["buy"]["cost"][2] = 3101.0
        path.write_text(json.dumps(g))
        self.write_sums()
        p = self.validate()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("[5] B31 AK400 buy th2: cost 3101.0", p.stdout)

    def test_missing_stage_manifest_stops_b22(self) -> None:
        (self.data / "interim" / f"spatial_{YEAR}" / "weights_manifest.json").unlink()
        p = self.run_py("build_manifest.py", "--year", str(YEAR), "--data", str(self.data),
                        "--out", str(self.out / "b22.json"))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("B16: stage manifest missing", p.stderr)


if __name__ == "__main__":
    unittest.main()
