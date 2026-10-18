"""
Tests for the 2.6 spatial-statistics nodes against a synthetic map.

  B16  spatial weights (build_weights.py)
  B17  global Moran's I (spatial_stats.py)
  B18  LISA and Getis-Ord Gi* clusters (spatial_stats.py)

    python -m unittest discover -s tests -v        (or: make test)

The fixture is a 5 x 5 grid of one-degree squares in the central U.S.
(codes TX001-TX025, row by row from the north-west corner), one detached
square far to the east (GA099), and one Alaska square (AK400). The metrics
fixture gives the two western columns a surplus and the two eastern columns a
shortfall, so the grid is clustered by construction. The scripts run as
subprocesses, exactly as the Makefile calls them. Needs geopandas, libpysal and
esda (requirements.txt).
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
WEIGHTS = ROOT / "pipeline" / "spatial" / "build_weights.py"
STATS = ROOT / "pipeline" / "spatial" / "spatial_stats.py"
sys.path.insert(0, str(STATS.parent))
import build_weights as bw  # noqa: E402
import spatial_stats as ss  # noqa: E402

METRIC_FIELDS = ["profile", "mha", "status", "adequacy_ratio", "adequacy_gap", "coverage_ratio", "flat95_gap"]
PROFILES = {"default_profile": "e5_dep", "profiles": [
    {"id": "e5_dep", "label": "E-5 with dependents", "role": "primary"},
    {"id": "o3_dep", "label": "O-3 with dependents", "role": "contrast"}]}

GRID = 5
WEST, NORTH = -100.0, 40.0


def read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def grid_code(row: int, col: int) -> str:
    return f"TX{row * GRID + col + 1:03d}"


def write_geometry(path: Path, extra: list[tuple[str, object]] | None = None) -> Path:
    """The 5 x 5 grid plus GA099 (detached) and AK400 (out of scope), in EPSG:4326 like B6."""
    rows = [(grid_code(r, c), box(WEST + c, NORTH - r - 1, WEST + c + 1, NORTH - r))
            for r in range(GRID) for c in range(GRID)]
    rows += [("GA099", box(-84.0, 32.0, -83.0, 33.0)), ("AK400", box(-150.0, 61.0, -149.0, 62.0))]
    rows += extra or []
    gdf = gpd.GeoDataFrame({"mha": [r[0] for r in rows]}, geometry=[r[1] for r in rows], crs="EPSG:4326")
    gdf.to_file(path, driver="GeoJSON")
    return path


def grid_gap(row: int, col: int) -> float:
    """West surplus, east shortfall; a small row term keeps every value distinct."""
    return round({0: 0.30, 1: 0.25, 2: 0.02, 3: -0.15, 4: -0.20}[col] + 0.003 * row, 4)


def metric_row(profile: str, mha: str, gap: float | None, cost_share_effect: float = 0.06) -> dict:
    """One B12/B14-shaped row. coverage_ratio = adequacy_ratio - (cost share / cost)."""
    if gap is None:
        return {"profile": profile, "mha": mha, "status": "no_zori", "adequacy_ratio": "", "adequacy_gap": "",
                "coverage_ratio": "", "flat95_gap": ""}
    cov = gap + 1 - cost_share_effect
    return {"profile": profile, "mha": mha, "status": "ok", "adequacy_ratio": f"{gap + 1:.4f}",
            "adequacy_gap": f"{gap:.4f}", "coverage_ratio": f"{cov:.4f}", "flat95_gap": f"{cov - 0.95:.4f}"}


def write_metrics(path: Path, rows: list[dict]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=METRIC_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return path


def grid_metrics(path: Path) -> Path:
    """Both profiles; TX025 has no benchmark; GA099 and AK400 have values."""
    rows = []
    for profile, offset in (("e5_dep", 0.0), ("o3_dep", 0.05)):
        for r in range(GRID):
            for c in range(GRID):
                code = grid_code(r, c)
                rows.append(metric_row(profile, code, None if code == "TX025" else grid_gap(r, c) + offset,
                                       0.06 - 0.02 * c))
        rows += [metric_row(profile, "GA099", 0.05), metric_row(profile, "AK400", 0.40)]
    return write_metrics(path, rows)


class SpatialFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.geometry = write_geometry(self.d / "mha_2026.geojson")
        self.out = self.d / "spatial"
        self.profiles = self.d / "profiles.json"
        self.profiles.write_text(json.dumps(PROFILES))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_weights(self, *extra: str, geometry: Path | None = None,
                    out: Path | None = None) -> subprocess.CompletedProcess:
        args = ["--geometry", str(geometry or self.geometry), "--out", str(out or self.out), *extra]
        return subprocess.run([sys.executable, str(WEIGHTS), *args], capture_output=True, text=True)

    def run_stats(self, *extra: str, metrics: Path, geometry: Path | None = None, out: Path | None = None,
                  weights_manifest: Path | None = None, buy: Path | None = None) -> subprocess.CompletedProcess:
        out = out or self.out
        args = ["--geometry", str(geometry or self.geometry),
                "--weights-manifest", str(weights_manifest or self.out / "weights_manifest.json"),
                "--rent-metrics", str(metrics), "--out", str(out), "--profiles", str(self.profiles),
                "--permutations", "999"]
        if buy:
            args += ["--buy-metrics", str(buy)]
        return subprocess.run([sys.executable, str(STATS), *args, *extra], capture_output=True, text=True)


class TestWeightsB16(SpatialFixture):
    def test_scope_excludes_alaska(self) -> None:
        p = self.run_weights()
        self.assertEqual(p.returncode, 0, p.stderr)
        man = json.loads((self.out / "weights_manifest.json").read_text())
        self.assertEqual(man["node"], "B16")
        self.assertEqual(man["scope"]["mhas_in_b6"], 27)
        self.assertEqual(man["scope"]["mhas_in_scope"], 26)
        self.assertEqual(man["scope"]["excluded"], ["AK400"])
        self.assertEqual(man["crs"], "EPSG:5070")
        summary = {r["mha"]: r for r in read(self.out / "mha_weights_summary.csv")}
        self.assertEqual(summary["AK400"]["in_scope"], "false")
        links = read(self.out / "mha_neighbors.csv")
        self.assertNotIn("AK400", {r["mha"] for r in links} | {r["neighbor"] for r in links})

    def test_queen_counts_and_island(self) -> None:
        p = self.run_weights()
        self.assertEqual(p.returncode, 0, p.stderr)
        summary = {r["mha"]: r for r in read(self.out / "mha_weights_summary.csv")}
        self.assertEqual(summary[grid_code(0, 0)]["queen_neighbors"], "3")     # corner
        self.assertEqual(summary[grid_code(0, 2)]["queen_neighbors"], "5")     # edge
        self.assertEqual(summary[grid_code(2, 2)]["queen_neighbors"], "8")     # interior
        self.assertEqual(summary["GA099"]["queen_neighbors"], "0")
        man = json.loads((self.out / "weights_manifest.json").read_text())
        self.assertEqual(man["diagnostic_queen"]["island_mhas"], ["GA099"])
        self.assertEqual(man["diagnostic_queen"]["components"], 2)            # the grid, and GA099 alone
        self.assertTrue(any("queen contiguity leaves 1 of 26" in w for w in man["warnings"]))

    def test_knn_gives_every_mha_k_neighbours(self) -> None:
        p = self.run_weights("--k", "4")
        self.assertEqual(p.returncode, 0, p.stderr)
        links = read(self.out / "mha_neighbors.csv")
        per = {}
        for r in links:
            per.setdefault(r["mha"], []).append(r)
        self.assertEqual(len(per), 26)
        for mha, rs in per.items():
            self.assertEqual([r["rank"] for r in rs], ["1", "2", "3", "4"], mha)
            self.assertNotIn(mha, {r["neighbor"] for r in rs})
            ds = [float(r["distance_km"]) for r in rs]
            self.assertEqual(ds, sorted(ds), mha)
        # The detached square is no longer an island: its nearest neighbours are grid squares.
        self.assertTrue(all(r["neighbor"].startswith("TX") for r in per["GA099"]))
        # Every rook neighbour of an interior square is among its four nearest.
        centre = {r["neighbor"] for r in per[grid_code(2, 2)]}
        self.assertEqual(centre, {grid_code(1, 2), grid_code(3, 2), grid_code(2, 1), grid_code(2, 3)})
        self.assertTrue(all(r["queen"] == "true" for r in per[grid_code(2, 2)]))
        gal = (self.out / "mha_weights_knn4.gal").read_text().splitlines()
        self.assertEqual(gal[0], "0 26")
        man = json.loads((self.out / "weights_manifest.json").read_text())
        self.assertEqual((man["primary"]["scheme"], man["primary"]["k"]), ("knn", 4))
        self.assertGreaterEqual(man["primary"]["links_over_500_km"], 1)       # GA099 is far from the grid

    def test_reproducible(self) -> None:
        other = self.d / "again"
        for out in (self.out, other):
            p = self.run_weights(out=out)
            self.assertEqual(p.returncode, 0, p.stderr)
        for name in ("mha_neighbors.csv", "mha_weights_summary.csv", "mha_weights_knn6.gal"):
            self.assertEqual((self.out / name).read_bytes(), (other / name).read_bytes(), name)

    def test_duplicate_code_fails(self) -> None:
        bad = write_geometry(self.d / "dupe.geojson", extra=[("TX001", box(-90.0, 30.0, -89.0, 31.0))])
        p = self.run_weights(geometry=bad)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("appear more than once", p.stderr)

    def test_k_too_large_fails(self) -> None:
        p = self.run_weights("--k", "26")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("k = 26", p.stderr)



class TestStatsB17B18(SpatialFixture):
    def setUp(self) -> None:
        super().setUp()
        p = self.run_weights()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.metrics = grid_metrics(self.d / "mha_rent_metrics.csv")

    def stats(self, *extra: str, **kw) -> tuple[dict, dict]:
        p = self.run_stats("--no-map", *extra, metrics=self.metrics, **kw)
        self.assertEqual(p.returncode, 0, p.stderr)
        man = json.loads((self.out / "spatial_stats_manifest.json").read_text())
        rows = {(r["profile"], r["mode"], r["variable"], r["mha"]): r
                for r in read(self.out / "mha_spatial_stats.csv")}
        return man, rows

    def test_b17_clustered_grid_rejects_randomness(self) -> None:
        man, _ = self.stats()
        self.assertEqual(man["nodes"], ["B17", "B18"])
        primary = man["tests"][0]
        self.assertEqual((primary["profile"], primary["mode"], primary["variable"], primary["role"]),
                         ("e5_dep", "rent", "adequacy_gap", "primary"))
        self.assertEqual(primary["n"], 25)                                    # 24 grid squares + GA099
        self.assertEqual(primary["not_tested"], {"no_value": 1, "no_geometry": 0, "out_of_scope": 1})
        self.assertGreater(primary["moran"]["I"], 0.3)
        self.assertLessEqual(primary["moran"]["p_sim"], 0.01)
        self.assertTrue(man["headline"]["h1_reading"].startswith("reject spatial randomness"))
        # Sensitivity: positive and significant at every k and under queen (GA099 dropped as an island).
        sens = primary["moran_sensitivity"]
        for key in ("knn4", "knn8", "queen"):
            self.assertGreater(sens[key]["I"], 0.3, key)
            self.assertLessEqual(sens[key]["p_sim"], 0.01, key)
        self.assertEqual((sens["queen"]["n"], sens["queen"]["islands_dropped"]), (24, 1))
        # 2 profiles x 2 variables, rent only; the flat-95% comparison is reported for each profile.
        self.assertEqual(len(man["tests"]), 4)
        self.assertEqual({(c["profile"], c["mode"]) for c in man["flat95_vs_adequacy_moran"]},
                         {("e5_dep", "rent"), ("o3_dep", "rent")})
        self.assertEqual(man["method"]["min_attainable_p_sim"], {"global": 0.001, "local_two_sided": 0.002})

    def test_b18_lisa_and_gi_classes(self) -> None:
        _, rows = self.stats()
        key = lambda m: ("e5_dep", "rent", "adequacy_gap", m)              # noqa: E731
        west, east = rows[key(grid_code(1, 0))], rows[key(grid_code(1, 4))]
        self.assertEqual((west["cluster"], west["gi_class"]), ("HH", "hot"))
        self.assertEqual((east["cluster"], east["gi_class"]), ("LL", "cold"))
        self.assertGreater(float(west["lisa_i"]), 0)
        self.assertEqual(rows[key("TX025")]["status"], "no_value")
        self.assertEqual(rows[key("AK400")]["status"], "out_of_scope")
        self.assertEqual(rows[key("AK400")]["cluster"], "")
        tested = [r for k_, r in rows.items() if k_[:3] == ("e5_dep", "rent", "adequacy_gap")
                  and r["status"] == "tested"]
        self.assertTrue(all(r["neighbors"] == "6" for r in tested))
        for r in tested:                                                      # class rule, row by row
            sig = float(r["lisa_p_sim"]) < 0.05
            self.assertEqual(r["cluster"], r["lisa_quadrant"] if sig else "NS", r["mha"])
            self.assertIn(r["cluster"], {"HH", "LL", "HL", "LH", "NS"})

    def test_gi_star_on_ratio_equals_gi_star_on_gap(self) -> None:
        """The script runs Gi* on adequacy_ratio; the z-score must equal Gi* on the gap itself."""
        import esda
        _, rows = self.stats()
        tested = sorted(r["mha"] for k_, r in rows.items()
                        if k_[:3] == ("e5_dep", "rent", "adequacy_gap") and r["status"] == "tested")
        g = bw.load_geometry(self.geometry)
        g = g[g["mha"].isin(tested)].sort_values("mha").reset_index(drop=True)
        w, _ = bw.knn_weights(g["mha"].tolist(), bw.points(g), 6)
        gap = np.array([float(rows[("e5_dep", "rent", "adequacy_gap", m)]["value"]) for m in g["mha"]])
        direct = esda.G_Local(gap, w, transform="B", permutations=999, star=True, seed=2026, n_jobs=1,
                              alternative=ss.LOCAL_ALTERNATIVE)
        for i, m in enumerate(g["mha"]):
            self.assertAlmostEqual(float(rows[("e5_dep", "rent", "adequacy_gap", m)]["gi_z"]),
                                   float(direct.Zs[i]), places=3, msg=m)

    def test_hand_worked_moran(self) -> None:
        """Four squares in a row with gaps of 1, 1.5 and 2 degrees between their left edges, k = 1.
        Nearest neighbours: A->B, B->A, C->B, D->C. Values 1, 2, 3, 4: z = -1.5, -0.5, 0.5, 1.5,
        sum z^2 = 5. Links: 0.75 + 0.75 - 0.25 + 0.75 = 2. S0 = 4 (row-standardized, one link each).
        I = (n / S0) * 2 / 5 = (4 / 4) * 0.4 = 0.4; E[I] = -1 / 3."""
        line = [("TX001", -100.0), ("TX002", -99.0), ("TX003", -97.5), ("TX004", -95.5)]
        gdf = gpd.GeoDataFrame({"mha": [c for c, _ in line]},
                               geometry=[box(x, 35.0, x + 0.4, 35.4) for _, x in line], crs="EPSG:4326")
        geo = self.d / "line.geojson"
        gdf.to_file(geo, driver="GeoJSON")
        out = self.d / "line"
        p = self.run_weights("--k", "1", geometry=geo, out=out)
        self.assertEqual(p.returncode, 0, p.stderr)
        links = {(r["mha"], r["neighbor"]) for r in read(out / "mha_neighbors.csv")}
        self.assertEqual(links, {("TX001", "TX002"), ("TX002", "TX001"), ("TX003", "TX002"), ("TX004", "TX003")})
        metrics = write_metrics(self.d / "line.csv", [metric_row("e5_dep", c, float(v))
                                                      for v, (c, _) in enumerate(line, start=1)])
        p = self.run_stats("--no-map", metrics=metrics, geometry=geo, out=out,
                           weights_manifest=out / "weights_manifest.json")
        self.assertEqual(p.returncode, 0, p.stderr)
        man = json.loads((out / "spatial_stats_manifest.json").read_text())
        moran = man["tests"][0]["moran"]
        self.assertEqual((moran["I"], moran["EI"]), (0.4, round(-1 / 3, 4)))
        sens = man["tests"][0]["moran_sensitivity"]
        self.assertIn("skipped", sens["knn4"])
        self.assertIn("skipped", sens["queen"])                              # no square touches another

    def test_reproducible(self) -> None:
        self.stats()
        first = (self.out / "mha_spatial_stats.csv").read_bytes()
        man1 = json.loads((self.out / "spatial_stats_manifest.json").read_text())
        self.stats()
        self.assertEqual(first, (self.out / "mha_spatial_stats.csv").read_bytes())
        man2 = json.loads((self.out / "spatial_stats_manifest.json").read_text())
        self.assertEqual(man1["tests"], man2["tests"])

    def test_buy_mode_and_map(self) -> None:
        buy = grid_metrics(self.d / "mha_buy_metrics.csv")
        p = self.run_stats(metrics=self.metrics, buy=buy)
        self.assertEqual(p.returncode, 0, p.stderr)
        man = json.loads((self.out / "spatial_stats_manifest.json").read_text())
        self.assertEqual(len(man["tests"]), 8)
        self.assertIn("B14", man["inputs"])
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib not installed")
        png = self.out / "mha_lisa_e5_dep_rent_map.png"
        self.assertTrue(png.exists())
        self.assertLess(png.stat().st_size, 1_000_000)                        # small enough for make evidence
        self.assertIn(png.name, man["outputs"])

    def test_buy_rows_not_ok_are_not_tested(self) -> None:
        """A PITI-only buy row (decision 2.4) has values but is not comparable, so it is not tested."""
        buy_path = grid_metrics(self.d / "mha_buy_metrics.csv")
        with buy_path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        target = grid_code(2, 2)
        for r in rows:
            if r["mha"] == target:
                r["status"] = "piti_only_no_zori"
        write_metrics(buy_path, rows)
        p = self.run_stats("--no-map", metrics=self.metrics, buy=buy_path)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = {(r["profile"], r["mode"], r["variable"], r["mha"]): r
               for r in read(self.out / "mha_spatial_stats.csv")}
        self.assertEqual(out[("e5_dep", "buy", "adequacy_gap", target)]["status"], "no_value")
        self.assertEqual(out[("e5_dep", "rent", "adequacy_gap", target)]["status"], "tested")
        man = json.loads((self.out / "spatial_stats_manifest.json").read_text())
        buy_test = next(t for t in man["tests"] if (t["profile"], t["mode"], t["variable"])
                        == ("e5_dep", "buy", "adequacy_gap"))
        self.assertEqual(buy_test["n"], 24)                                   # one fewer than rent's 25

    def test_weights_from_other_geometry_fails(self) -> None:
        other = write_geometry(self.d / "other.geojson", extra=[("TX099", box(-90.0, 30.0, -89.0, 31.0))])
        p = self.run_stats("--no-map", metrics=self.metrics, geometry=other)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("different B6", p.stderr)

    def test_constant_variable_fails(self) -> None:
        flat = write_metrics(self.d / "flat.csv", [metric_row("e5_dep", grid_code(r, c), 0.1)
                                                   for r in range(GRID) for c in range(GRID)])
        p = self.run_stats("--no-map", metrics=flat)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("every value is the same", p.stderr)


class TestFalseDiscoveryRate(unittest.TestCase):
    def test_benjamini_hochberg(self) -> None:
        # Cut-offs i * 0.05 / 8: 0.00625, 0.0125, 0.01875, ... Only the two smallest pass.
        p = np.array([0.041, 0.001, 0.205, 0.039, 0.008, 0.042, 0.06, 0.074])
        mask, cut = ss.bh_significant(p, 0.05)
        self.assertEqual(cut, 0.008)
        self.assertEqual(mask.tolist(), [False, True, False, False, True, False, False, False])

    def test_step_up_keeps_earlier_values(self) -> None:
        # p_(3) = 0.03 <= 3 * 0.05 / 4 = 0.0375, so all three pass even though p_(2) = 0.026 > 0.025.
        mask, cut = ss.bh_significant(np.array([0.01, 0.026, 0.03, 0.9]), 0.05)
        self.assertEqual((mask.tolist(), cut), ([True, True, True, False], 0.03))

    def test_nothing_significant(self) -> None:
        mask, cut = ss.bh_significant(np.array([0.2, 0.5, 0.9]), 0.05)
        self.assertEqual((mask.any(), cut), (False, None))


if __name__ == "__main__":
    unittest.main()
