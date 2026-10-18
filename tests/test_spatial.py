"""
Tests for the 2.6 spatial-statistics nodes against a synthetic map.

  B16  spatial weights (build_weights.py)

    python -m unittest discover -s tests -v        (or: make test)

The fixture is a 5 x 5 grid of one-degree squares in the central U.S.
(codes TX001-TX025, row by row from the north-west corner), one detached
square far to the east (GA099), and one Alaska square (AK400). The scripts
run as subprocesses, exactly as the Makefile calls them. Needs geopandas and
libpysal (requirements.txt).
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
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "pipeline" / "spatial" / "build_weights.py"

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


class SpatialFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.geometry = write_geometry(self.d / "mha_2026.geojson")
        self.out = self.d / "spatial"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_weights(self, *extra: str, geometry: Path | None = None,
                    out: Path | None = None) -> subprocess.CompletedProcess:
        args = ["--geometry", str(geometry or self.geometry), "--out", str(out or self.out), *extra]
        return subprocess.run([sys.executable, str(WEIGHTS), *args], capture_output=True, text=True)


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


if __name__ == "__main__":
    unittest.main()
