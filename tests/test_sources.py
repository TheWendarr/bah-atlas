"""
Tests for the Layer 1 source archive (tools/package_sources.py).

    python -m unittest discover -s tests -v        (or: make test)

A synthetic data/raw/ with a fetch manifest: public-domain files that must be
archived and checked against their recorded SHA-256, a Zillow file that must only be
listed, and incompressible payloads sized to force a split. Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "package_sources.py"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class TestSourceArchive(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.raw, self.out = d / "raw", d / "sources"
        self.raw.mkdir()
        rng = random.Random(2026)
        files = {
            "A1": ("BAH-ASCII-2026.zip", rng.randbytes(150_000)),          # stored, incompressible
            "A2": ("cb_2020_us_zcta520_500k.zip", rng.randbytes(150_000)),
            "A3": ("Zip_zori_uc_sfrcondomfr_sm_month.csv", b"RegionName,2026-01-31\n80901,1800\n"),
            "A9": ("acs5_2024_zcta.json", json.dumps([["B01003_001E", "zip code tabulation area"],
                                                       ["900", "00501"]] * 500).encode()),
        }
        manifest = {}
        for node, (name, data) in files.items():
            (self.raw / name).write_bytes(data)
            manifest[node] = {"filename": name, "name": f"source {node}", "node_id": node, "sha256": sha(data),
                              "bytes": len(data), "retrieved_at": "2026-10-18T00:00:00+00:00",
                              "source_url": f"https://example.gov/{name}", "license": "test"}
        self.manifest = manifest
        self.write_manifest()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_manifest(self) -> None:
        (self.raw / "fetch_manifest.json").write_text(json.dumps(self.manifest))

    def run_tool(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), "--year", "2026", "--raw", str(self.raw),
                               "--out", str(self.out), *extra], capture_output=True, text=True)

    def test_single_volume_public_domain_only(self) -> None:
        p = self.run_tool()
        self.assertEqual(p.returncode, 0, p.stderr)
        vol = self.out / "layer1_sources_2026.zip"
        with zipfile.ZipFile(vol) as zf:
            names = sorted(zf.namelist())
            self.assertEqual(names, ["A1/BAH-ASCII-2026.zip", "A2/cb_2020_us_zcta520_500k.zip",
                                     "A9/acs5_2024_zcta.json", "SOURCES_INDEX.txt"])
            self.assertEqual(sha(zf.read("A9/acs5_2024_zcta.json")), self.manifest["A9"]["sha256"])
            self.assertEqual(zf.getinfo("A1/BAH-ASCII-2026.zip").compress_type, zipfile.ZIP_STORED)
            self.assertEqual(zf.getinfo("A9/acs5_2024_zcta.json").compress_type, zipfile.ZIP_DEFLATED)
            index = zf.read("SOURCES_INDEX.txt").decode()
        self.assertIn("A3 Zip_zori_uc_sfrcondomfr_sm_month.csv", index)          # listed, not archived
        man = json.loads((self.out / "sources_manifest.json").read_text())
        self.assertEqual([a["node"] for a in man["archived"]], ["A1", "A2", "A9"])
        self.assertEqual([t["node"] for t in man["listed_only"]], ["A3"])
        self.assertEqual((self.out / "SHA256SUMS").read_text().split()[0], sha(vol.read_bytes()))
        readme = (self.out / "README.md").read_text()
        self.assertIn("https://example.gov/Zip_zori_uc_sfrcondomfr_sm_month.csv", readme)
        self.assertIn("## Listed only: third-party data", readme)

    def test_reproducible(self) -> None:
        self.assertEqual(self.run_tool().returncode, 0)
        first = (self.out / "layer1_sources_2026.zip").read_bytes()
        self.assertEqual(self.run_tool().returncode, 0)
        self.assertEqual(sha(first), sha((self.out / "layer1_sources_2026.zip").read_bytes()))

    def test_split_under_the_limit(self) -> None:
        p = self.run_tool("--max-mb", "0.25")            # 250 kB: the two 150 kB files cannot share a volume
        self.assertEqual(p.returncode, 0, p.stderr)
        vols = sorted(self.out.glob("layer1_sources_2026_part*.zip"))
        self.assertEqual(len(vols), 2)
        self.assertFalse((self.out / "layer1_sources_2026.zip").exists())
        members = set()
        for v in vols:
            self.assertLess(v.stat().st_size, 250_000)
            with zipfile.ZipFile(v) as zf:
                self.assertIn("SOURCES_INDEX.txt", zf.namelist())
                members |= set(zf.namelist()) - {"SOURCES_INDEX.txt"}
        self.assertEqual(len(members), 3)
        self.assertEqual(len((self.out / "SHA256SUMS").read_text().splitlines()), 2)

    def test_file_over_the_limit_stops(self) -> None:
        p = self.run_tool("--max-mb", "0.1")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("volume limit; it cannot be committed as one file", p.stderr)

    def test_changed_file_stops(self) -> None:
        (self.raw / "acs5_2024_zcta.json").write_text("[]")
        p = self.run_tool()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("A9: acs5_2024_zcta.json SHA-256", p.stderr)
        self.assertFalse(self.out.exists())

    def test_unclassified_source_stops(self) -> None:
        (self.raw / "new.csv").write_text("x")
        self.manifest["A99"] = {"filename": "new.csv", "sha256": sha(b"x")}
        self.write_manifest()
        p = self.run_tool()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("A99 (new.csv) is not classified", p.stderr)

    def test_check_writes_nothing(self) -> None:
        p = self.run_tool("--check")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("check only", p.stdout)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
