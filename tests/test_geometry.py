"""
Tests for the area-polygon nodes against a synthetic crosswalk and ZCTA layer.

  B6   MHA polygons (build_mha_geometry.py, default --classes mha)
  B28  County Cost Group and territory polygons (--classes ccg,unknown)

    python -m unittest discover -s tests -v        (or: make test)

The fixture is a row of one-degree ZCTA squares. ZIPs 00001-00003 belong to the
MHA TX001, 00004-00005 to the County Cost Group ZZ001, 00006 to ZZ002, and
00900-00901 to the territory bucket XX001. Two ZIPs have no ZCTA polygon: 00901
(XX001 still gets a polygon from 00900) and 99999, the only ZIP of ZZ003, which
therefore gets none. The script runs as a subprocess, exactly as the Makefile
calls it. Needs geopandas (requirements.txt).
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
SCRIPT = ROOT / "pipeline" / "geometry" / "build_mha_geometry.py"

# zip, area code, class; ZIPs with a ZCTA square are listed in ZCTAS below.
CROSSWALK = [
    ("00001", "TX001", "mha"), ("00002", "TX001", "mha"), ("00003", "TX001", "mha"),
    ("00004", "ZZ001", "ccg"), ("00005", "ZZ001", "ccg"),
    ("00006", "ZZ002", "ccg"),
    ("99999", "ZZ003", "ccg"),
    ("00900", "XX001", "unknown"), ("00901", "XX001", "unknown"),
]
ZCTAS = ["00001", "00002", "00003", "00004", "00005", "00006", "00900"]


def write_csv(path: Path, header: list[str], rows: list[tuple]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return path


class GeometryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        squares = [box(-100 + i, 30, -99 + i, 31) for i in range(len(ZCTAS))]
        gpd.GeoDataFrame({"ZCTA5CE20": ZCTAS}, geometry=squares, crs="EPSG:4269").to_file(
            self.dir / "zcta.geojson", driver="GeoJSON")
        self.zcta = self.dir / "zcta.geojson"
        self.b1 = write_csv(self.dir / "zip_mha.csv", ["zip", "mha", "mha_class"], CROSSWALK)
        self.b2 = write_csv(self.dir / "zip_mha_geo.csv", ["zip", "mha"],
                            [(z, m) for z, m, c in CROSSWALK if c == "mha"])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_geometry(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), "--zcta", str(self.zcta), *args],
                              capture_output=True, text=True)

    def build_b28(self, *extra: str) -> tuple[gpd.GeoDataFrame, dict]:
        out = self.dir / "non_mha_2026.gpkg"
        p = self.run_geometry("--classes", "ccg,unknown", "--crosswalk", str(self.b1), "--out", str(out), *extra)
        self.assertEqual(p.returncode, 0, p.stderr)
        manifest = json.loads((self.dir / "non_mha_2026_geometry_manifest.json").read_text())
        return gpd.read_file(out.with_suffix(".geojson")), manifest

    def test_b28_polygons_carry_class_and_source(self) -> None:
        areas, _ = self.build_b28()
        self.assertEqual(list(areas["mha"]), ["XX001", "ZZ001", "ZZ002"])
        self.assertEqual(dict(zip(areas["mha"], areas["class"])),
                         {"XX001": "unknown", "ZZ001": "ccg", "ZZ002": "ccg"})
        self.assertTrue((areas["geometry_source"].str.contains("non-authoritative")).all())
        self.assertEqual(str(areas.crs).upper(), "EPSG:4326")
        # ZZ001 is the dissolve of two adjacent squares.
        self.assertAlmostEqual(areas.set_index("mha").loc["ZZ001"].geometry.area, 2.0, places=6)

    def test_b28_manifest_reports_gaps_and_territory(self) -> None:
        _, m = self.build_b28()
        self.assertEqual(m["node"], "B28")
        self.assertEqual(sorted(m["inputs"]), ["A2", "B1"])
        self.assertEqual(m["inputs"]["B1"], "zip_mha.csv")
        c = m["counts"]
        self.assertEqual(c["areas"], 3)
        self.assertEqual(c["areas_by_class"], {"ccg": 2, "unknown": 1})
        self.assertEqual(c["codes_in_crosswalk_by_class"], {"ccg": 3, "unknown": 1})
        self.assertEqual(c["zips_by_class"], {"ccg": 4, "unknown": 2})
        self.assertEqual(c["zips_without_zcta"], 2)
        self.assertEqual(c["zips_without_zcta_by_class"], {"ccg": 1, "unknown": 1})
        self.assertEqual(c["zctas_in_more_than_one_area"], 0)
        self.assertEqual(m["codes_without_polygon"], ["ZZ003"])
        self.assertEqual(m["unknown_zip3_prefixes"], {"009": 2})
        self.assertTrue(any("ZZ003" in w for w in m["warnings"]))
        self.assertEqual(set(m["output_sha256"]), {"non_mha_2026.gpkg", "non_mha_2026.geojson"})

    def test_b6_unchanged_by_classes_option(self) -> None:
        out = self.dir / "mha_2026.gpkg"
        p = self.run_geometry("--crosswalk", str(self.b2), "--out", str(out))
        self.assertEqual(p.returncode, 0, p.stderr)
        areas = gpd.read_file(out.with_suffix(".geojson"))
        self.assertEqual(list(areas.columns), ["mha", "geometry"])
        self.assertEqual(list(areas["mha"]), ["TX001"])
        m = json.loads((self.dir / "mha_2026_geometry_manifest.json").read_text())
        self.assertEqual(m["node"], "B6")
        self.assertEqual(sorted(m["inputs"]), ["A2", "B2"])

    def test_b6_and_b28_must_be_separate_runs(self) -> None:
        p = self.run_geometry("--classes", "mha,ccg", "--crosswalk", str(self.b1), "--out", str(self.dir / "x.gpkg"))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("separate runs", p.stderr)

    def test_b28_needs_the_class_column(self) -> None:
        p = self.run_geometry("--classes", "ccg,unknown", "--crosswalk", str(self.b2), "--out", str(self.dir / "x.gpkg"))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("mha_class", p.stderr)

    def test_b28_stops_on_a_zcta_shared_with_an_mha(self) -> None:
        # A bridge that puts a ZZ001 ZIP into TX001's ZCTA would draw overlapping polygons.
        bridge = write_csv(self.dir / "bridge.csv", ["zip", "zcta"], [("00004", "00001")])
        p = self.run_geometry("--classes", "ccg,unknown", "--crosswalk", str(self.b1),
                              "--zip-to-zcta", str(bridge), "--out", str(self.dir / "x.gpkg"))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("more than one area", p.stderr)
        self.assertIn("TX001", p.stderr)


if __name__ == "__main__":
    unittest.main()
