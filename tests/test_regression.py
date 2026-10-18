"""
Tests for B19 spatial regression (pipeline/spatial/regression.py).

    python -m unittest discover -s tests -v        (or: make test)

Two layers:
  * fit() and choose_model() on a 12 x 12 lattice with known data-generating
    processes: no spatial dependence (OLS kept, coefficients recovered) and a
    spatial lag process (rho = 0.6; the rule picks the lag model and recovers rho).
  * the script end to end on a synthetic CONUS grid with every input file the
    Makefile passes, where rent growth is planted in a ZORI history and must be
    recovered exactly, plus the lineage stops.
Needs geopandas, libpysal, esda and spreg (requirements.txt).
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "pipeline" / "spatial" / "regression.py"
WEIGHTS = ROOT / "pipeline" / "spatial" / "build_weights.py"
sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(ROOT / "pipeline" / "benchmarks"))
import regression as rg  # noqa: E402
import mha_agg as agg  # noqa: E402

TRUE_BETA = np.array([0.5, -0.30, 0.02, 0.04])      # constant, ln_rent, growth (per pp), ln_density


def read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write(path: Path, rows: list[list]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)
    return path


class TestChooseModel(unittest.TestCase):
    def lm(self, lag: float, err: float, rlag: float = 1.0, rerr: float = 1.0,
           rlag_stat: float = 1.0, rerr_stat: float = 1.0) -> dict:
        return {"lm_lag": [5.0, lag], "lm_error": [5.0, err], "rlm_lag": [rlag_stat, rlag],
                "rlm_error": [rerr_stat, rerr], "lm_sarma": [9.0, 0.01]}

    def test_rule(self) -> None:
        self.assertEqual(rg.choose_model(self.lm(0.4, 0.3), 0.05)[0], "ols")
        self.assertEqual(rg.choose_model(self.lm(0.01, 0.3), 0.05)[0], "lag")
        self.assertEqual(rg.choose_model(self.lm(0.4, 0.01), 0.05)[0], "error")
        self.assertEqual(rg.choose_model(self.lm(0.01, 0.01, rlag=0.5, rerr=0.02), 0.05)[0], "error")
        self.assertEqual(rg.choose_model(self.lm(0.01, 0.01, rlag=0.02, rerr=0.5), 0.05)[0], "lag")
        both = self.lm(0.01, 0.01, rlag=0.01, rerr=0.02, rlag_stat=3.0, rerr_stat=8.0)
        self.assertEqual(rg.choose_model(both, 0.05)[0], "error")      # larger robust statistic


class TestFit(unittest.TestCase):
    """12 x 12 rook lattice (libpysal lat2W), three standard-normal predictors."""

    def setUp(self) -> None:
        from libpysal.weights import lat2W
        self.w = lat2W(12, 12)
        self.w.transform = "r"
        rng = np.random.default_rng(7)
        self.X = rng.normal(size=(self.w.n, 3))
        self.e = rng.normal(scale=0.05, size=self.w.n)

    def test_no_spatial_dependence_keeps_ols(self) -> None:
        y = TRUE_BETA[0] + self.X @ TRUE_BETA[1:] + self.e
        result, r_ols, r_model = rg.fit(y, self.X, rg.PREDICTORS, self.w, 0.05, 999, 2026)
        self.assertEqual(result["choice"]["model"], "ols", result["lm_tests"])
        b = [c["b"] for c in result["ols"]["coefficients"]]
        np.testing.assert_allclose(b, TRUE_BETA, atol=0.02)
        self.assertNotIn("spatial", result)
        self.assertTrue(np.allclose(r_ols, r_model))
        for c in result["ols"]["coefficients"][1:]:
            self.assertLess(c["vif"], 1.5)                       # independent draws: no collinearity

    def test_lag_process_picks_lag_and_recovers_rho(self) -> None:
        rho = 0.6
        A = np.linalg.inv(np.eye(self.w.n) - rho * self.w.full()[0])
        y = A @ (TRUE_BETA[0] + self.X @ TRUE_BETA[1:] + self.e)
        result, r_ols, _ = rg.fit(y, self.X, rg.PREDICTORS, self.w, 0.05, 999, 2026)
        self.assertEqual(result["choice"]["model"], "lag", result["lm_tests"])
        sp = result["spatial"]
        self.assertAlmostEqual(sp["rho"], rho, delta=0.08)
        self.assertLess(result["ols"]["residual_moran"]["p_sim"], 0.01)     # OLS leaves dependence
        self.assertGreater(sp["residual_moran"]["p_sim"], 0.05)            # the lag model absorbs it
        ln_rent = next(c for c in sp["coefficients"] if c["name"] == "ln_rent")
        self.assertAlmostEqual(ln_rent["total_impact"], ln_rent["b"] / (1 - sp["rho"]), delta=1e-3)  # rho is rounded


class TestScript(unittest.TestCase):
    """A 12 x 12 grid of one-degree squares (TX001-TX144) plus AK400, one ZIP each.

    Per MHA i: ZORI level, 5-year growth and density are drawn once; the ZORI history
    holds 2021-01..03 at start and 2026-01..03 at start x (1 + g)^5, so the script must
    recover g exactly. adequacy_gap follows TRUE_BETA with small independent noise.
    TX144 has no density (B24 blank) and is left out; AK400 is out of scope.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        d = self.d = Path(self.tmp.name)
        rng = np.random.default_rng(11)
        codes = [f"TX{i + 1:03d}" for i in range(144)]
        geoms = [box(-100 + i % 12, 42 - i // 12 - 1, -100 + i % 12 + 1, 42 - i // 12) for i in range(144)]
        gpd.GeoDataFrame({"mha": codes + ["AK400"]}, geometry=geoms + [box(-150, 61, -149, 62)],
                         crs="EPSG:4326").to_file(d / "mha_2026.geojson", driver="GeoJSON")
        self.geometry = d / "mha_2026.geojson"
        self.out = d / "spatial"
        p = subprocess.run([sys.executable, str(WEIGHTS), "--geometry", str(self.geometry), "--out", str(self.out)],
                           capture_output=True, text=True)
        assert p.returncode == 0, p.stderr

        rent = rng.uniform(900, 3000, 145)
        self.growth = rng.uniform(0.01, 0.08, 145)
        dens = np.exp(rng.uniform(1, 8, 145))
        gap = (TRUE_BETA[0] + TRUE_BETA[1] * np.log(rent) + TRUE_BETA[2] * self.growth * 100
               + TRUE_BETA[3] * np.log(dens) + rng.normal(scale=0.01, size=145))
        allc = codes + ["AK400"]
        self.zips = {c: f"{10000 + i}" for i, c in enumerate(allc)}
        self.crosswalk = write(d / "zip_mha.csv", [["zip", "mha", "mha_class"]] +
                               [[z, c, "mha"] for c, z in self.zips.items()])
        head = ["RegionID", "SizeRank", "RegionName", "RegionType", "StateName", "State", "City", "Metro",
                "CountyName", "2021-01-31", "2021-02-28", "2021-03-31", "2026-01-31", "2026-02-28", "2026-03-31"]
        zrows = [head]
        for i, c in enumerate(allc):
            start = rent[i] / (1 + self.growth[i]) ** 5
            zrows.append([i, i, self.zips[c], "zip", "", "TX", "", "", "", *[f"{start:.6f}"] * 3,
                          *[f"{rent[i]:.6f}"] * 3])
        self.zori_csv = write(d / "Zip_zori.csv", zrows)
        self.zori = write(d / "mha_zori.csv", [["mha", "zori_median"]] +
                          [[c, f"{rent[i]:.2f}"] for i, c in enumerate(allc)])
        self.zori_manifest = d / "mha_zori_manifest.json"
        self.zori_manifest.write_text(json.dumps({"node": "B8", "input_file": self.zori_csv.name,
                                                  "input_sha256": agg.sha256(self.zori_csv),
                                                  "window_months_used": ["2026-01", "2026-02", "2026-03"]}))
        ctx = d / "context"
        ctx.mkdir()
        self.density = write(ctx / "mha_density.csv", [["mha", "density_per_km2", "pw_density_per_km2"]] +
                             [[c, "" if c == "TX144" else f"{dens[i]:.3f}",
                               "" if c == "TX144" else f"{dens[i] * 3:.3f}"] for i, c in enumerate(allc)])
        (ctx / "mha_density_manifest.json").write_text(json.dumps(
            {"nodes": ["B24"], "output_sha256": {"mha_density.csv": agg.sha256(self.density)}}))
        metric_rows = [["profile", "mha", "status", "adequacy_gap"]]
        for prof, shift in (("e5_dep", 0.0), ("o3_dep", 0.05)):
            for i, c in enumerate(allc):
                metric_rows.append([prof, c, "ok", f"{gap[i] + shift:.6f}"])
        self.metrics = write(d / "mha_rent_metrics.csv", metric_rows)
        self.profiles = d / "profiles.json"
        self.profiles.write_text(json.dumps({"default_profile": "e5_dep",
                                             "profiles": [{"id": "e5_dep"}, {"id": "o3_dep"}]}))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_script(self, **override: Path) -> subprocess.CompletedProcess:
        a = {"geometry": self.geometry, "weights-manifest": self.out / "weights_manifest.json",
             "rent-metrics": self.metrics, "zori": self.zori, "zori-manifest": self.zori_manifest,
             "zori-csv": self.zori_csv, "crosswalk": self.crosswalk, "density": self.density, "out": self.out,
             "profiles": self.profiles, **{k.replace("_", "-"): v for k, v in override.items()}}
        args = [x for k, v in a.items() for x in (f"--{k}", str(v))] + ["--permutations", "999"]
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)

    def test_end_to_end(self) -> None:
        p = self.run_script()
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = read(self.out / "mha_regression.csv")
        e5 = {r["mha"]: r for r in rows if r["profile"] == "e5_dep"}
        self.assertNotIn("AK400", e5)                                       # out of scope
        self.assertEqual(e5["TX144"]["status"], "no_density")
        self.assertEqual(sum(r["status"] == "modelled" for r in e5.values()), 143)
        i = 4
        self.assertAlmostEqual(float(e5["TX005"]["rent_growth_pct"]), self.growth[i] * 100, places=3)
        man = json.loads((self.out / "regression_manifest.json").read_text())
        self.assertEqual(man["nodes"], ["B19"])
        self.assertEqual(man["growth_window"]["start_window_months"], ["2021-01", "2021-02", "2021-03"])
        self.assertEqual(man["not_modelled"]["e5_dep"], {"no_density": 1})
        roles = [(r["profile"], r["specification"], r["role"]) for r in man["runs"]]
        self.assertEqual(roles, [("e5_dep", "primary", "primary"), ("e5_dep", "pw_density", "sensitivity"),
                                 ("o3_dep", "primary", "sensitivity")])
        head = man["headline"]
        self.assertEqual((head["n"], head["model"]), (143, "ols"))
        b = {c["predictor"]: c["b"] for c in head["predictors"]}
        self.assertAlmostEqual(b["ln_rent"], TRUE_BETA[1], delta=0.01)
        self.assertAlmostEqual(b["rent_growth_pct"], TRUE_BETA[2], delta=0.002)
        self.assertAlmostEqual(b["ln_density"], TRUE_BETA[3], delta=0.005)
        self.assertIn("mha_regression.csv", man["output_sha256"])
        self.assertEqual(sorted(man["inputs"]), ["A12", "A3", "B1", "B12", "B16", "B24", "B6", "B8"])

    def test_b8_from_another_zori_file_stops(self) -> None:
        other = write(self.d / "other.csv", [["RegionName"]])
        p = self.run_script(zori_csv=other)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("B8 was built from a different A3 file", p.stderr)

    def test_density_not_recorded_by_b24_stops(self) -> None:
        with self.density.open("a", encoding="utf-8") as fh:
            fh.write("ZZ999,1,1\n")
        p = self.run_script()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("not the file B24 recorded", p.stderr)

    def test_growth_window_outside_history_stops(self) -> None:
        p = subprocess.run([sys.executable, str(SCRIPT), "--geometry", str(self.geometry),
                            "--weights-manifest", str(self.out / "weights_manifest.json"),
                            "--rent-metrics", str(self.metrics), "--zori", str(self.zori),
                            "--zori-manifest", str(self.zori_manifest), "--zori-csv", str(self.zori_csv),
                            "--crosswalk", str(self.crosswalk), "--density", str(self.density),
                            "--out", str(self.out), "--profiles", str(self.profiles), "--growth-years", "7"],
                           capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("7-year growth needs 2019-01", p.stderr)


if __name__ == "__main__":
    unittest.main()
