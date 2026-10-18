"""
Tests for the B7 area tiles (build_mha_pmtiles.py; decision D9, ICD section 4).

    python -m unittest discover -s tests -v        (or: make test)

The merge of the B6 and B28 polygons into one `areas` layer is tested directly.
The full tippecanoe run is tested only where tippecanoe is installed (set
TIPPECANOE to its path if it is not on PATH); elsewhere that test is skipped,
never passed. Stdlib only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "pipeline" / "tiles" / "build_mha_pmtiles.py"
sys.path.insert(0, str(SCRIPT.parent))
import build_mha_pmtiles as bt  # noqa: E402


def square(x: float, y: float) -> dict:
    return {"type": "Polygon", "coordinates": [[[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]]}


def feature(code: str, x: float, cls: str | None = None) -> dict:
    props = {"mha": code}
    if cls:
        props.update({"class": cls, "geometry_source": "ZCTA dissolve of DTMO ZIP assignments (non-authoritative)"})
    return {"type": "Feature", "properties": props, "geometry": square(x, 30)}


B6 = [feature("TX002", -99), feature("TX001", -100)]
B28 = [feature("ZZ001", -98, "ccg"), feature("XX001", -97, "unknown")]


class MergeTest(unittest.TestCase):
    def test_one_layer_with_code_and_class_only(self) -> None:
        merged = bt.merge_areas(B6, B28)
        props = [f["properties"] for f in merged["features"]]
        self.assertEqual(props, [
            {"code": "TX001", "class": "mha"}, {"code": "TX002", "class": "mha"},
            {"code": "XX001", "class": "unknown"}, {"code": "ZZ001", "class": "ccg"},
        ])

    def test_duplicate_code_across_inputs_stops(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            bt.merge_areas(B6, [feature("TX001", -96, "ccg")])
        self.assertIn("more than once", str(cm.exception))

    def test_b28_class_must_be_ccg_or_unknown(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            bt.merge_areas(B6, [feature("ZZ009", -96, "mha")])
        self.assertIn("expected ccg or unknown", str(cm.exception))

    def test_malformed_code_stops(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            bt.merge_areas([feature("TX01", -100)], B28)
        self.assertIn("malformed", str(cm.exception))


TIPPECANOE = os.environ.get("TIPPECANOE", "tippecanoe")


@unittest.skipUnless(shutil.which(TIPPECANOE), "tippecanoe not installed")
class TippecanoeRunTest(unittest.TestCase):
    def test_build_writes_areas_archive_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for name, feats in (("mha_2026.geojson", B6), ("non_mha_2026.geojson", B28)):
                (d / name).write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
            out = d / "areas_2026.pmtiles"
            p = subprocess.run([sys.executable, str(SCRIPT), "--geojson", str(d / "mha_2026.geojson"),
                                "--non-mha", str(d / "non_mha_2026.geojson"), "--out", str(out)],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(out.read_bytes()[:7], b"PMTiles")
            self.assertFalse(list(d.glob("*.tmp.*")), "temporary files left behind")
            m = json.loads((d / "areas_2026_manifest.json").read_text())
            self.assertEqual(m["node"], "B7")
            self.assertEqual(m["layer"], "areas")
            self.assertEqual(m["id_property"], "code")
            self.assertEqual(m["maplibre_source_hint"]["promoteId"], "code")
            self.assertEqual(m["features_by_class"], {"mha": 2, "ccg": 1, "unknown": 1})
            self.assertEqual(m["inputs"], {"B6": "mha_2026.geojson", "B28": "non_mha_2026.geojson"})
            self.assertEqual(m["output_file"], "areas_2026.pmtiles")


if __name__ == "__main__":
    unittest.main()
