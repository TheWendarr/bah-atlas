"""
Tests for the 2.5 computed-metric nodes (B12-B15) against small synthetic
benchmark tables shaped like the B4, B8, B10 and B11 outputs.

    python -m unittest discover -s tests -v        (or: make test)

The script runs as a subprocess, exactly as the Makefile calls it. Expected
numbers are worked out by hand in the comments.
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
SCRIPT = ROOT / "pipeline" / "metrics" / "coverage_metrics.py"
MONTHS = ["2026-01", "2026-02", "2026-03"]


def read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write(path: Path, rows: list[list]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fixture(unittest.TestCase):
    """Three real MHAs and two profiles.

    AA001: has ZORI, SAFMR, full ownership cost
    AA002: has ZORI and SAFMR; no ZHVI            -> buy status no_home_value
    AA003: no ZORI; has SAFMR and a home value     -> rent no_zori, buy no_utilities
    ZZ001: County Cost Group, present only in B4   -> ignored
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.bench = self.d / "bench"
        self.bench.mkdir()
        self.out = self.d / "out"
        self.profiles = self.d / "profiles.json"
        self.profiles.write_text(json.dumps({
            "coverage_target": 0.95,
            "profiles": [
                {"id": "e5_dep", "pay_grade": "E5", "has_dependents": True, "anchor_bedrooms": 2},
                {"id": "o3_dep", "pay_grade": "O3", "has_dependents": True, "anchor_bedrooms": 3},
            ]}))
        self.bah = write(self.d / "bah_rates.csv", [
            ["mha", "pay_grade", "has_dependents", "monthly_rate"],
            ["AA001", "E5", "True", 1900.0], ["AA001", "E5", "False", 1500.0],   # without-deps row must be ignored
            ["AA001", "O3", "True", 2600.0],
            ["AA002", "E5", "True", 2400.0], ["AA002", "O3", "True", 3000.0],
            ["AA003", "E5", "True", 1500.0], ["AA003", "O3", "True", 2000.0],
            ["ZZ001", "E5", "True", 1200.0],
        ])
        self.zori = write(self.bench / "mha_zori.csv", [
            ["mha", "n_zips", "n_zips_with_data", "zip_coverage", "zori_median", "rent_share",
             "zori_utilities_adjusted", "utilities_usd"],
            ["AA001", 2, 2, "1.0000", "1600.00", "0.8000", "2000.00", "400.00"],
            ["AA002", 3, 2, "0.6667", "2400.00", "0.8000", "3000.00", "600.00"],
            ["AA003", 1, 0, "0.0000", "", "0.8500", "", ""],
        ])
        self.zhvi = write(self.bench / "mha_zhvi.csv", [
            ["mha", "zhvi_median"], ["AA001", "300000.00"], ["AA002", ""], ["AA003", "150000.00"]])
        self.safmr = write(self.bench / "mha_safmr.csv", [
            ["mha", "bedrooms", "safmr_median"],
            ["AA001", 2, "1800.00"], ["AA001", 3, "2400.00"],
            ["AA002", 2, "2500.00"], ["AA002", 3, "3200.00"],
            ["AA003", 2, "1000.00"], ["AA003", 3, "1300.00"],
        ])
        self.own = write(self.bench / "mha_ownership.csv", [
            ["mha", "zhvi_median", "own_housing_monthly", "utilities_usd", "own_total_monthly"],
            ["AA001", "300000.00", "2100.00", "400.00", "2500.00"],
            ["AA002", "", "", "", ""],
            ["AA003", "150000.00", "1100.00", "", ""],
        ])
        self.write_manifests()

    def write_manifests(self, b9_months: list[str] = MONTHS) -> None:
        (self.bench / "mha_zori_manifest.json").write_text(json.dumps({"window_months_used": MONTHS}))
        (self.bench / "mha_zhvi_manifest.json").write_text(json.dumps({"window_months_used": b9_months}))
        (self.bench / "mha_ownership_manifest.json").write_text(json.dumps({
            "rate": {"window": "2026-01:2026-03"},
            "input_sha256": {"B8": sha(self.zori), "B9": sha(self.zhvi)}}))

    def run_metrics(self, *extra: str) -> subprocess.CompletedProcess:
        args = ["--bah-rates", str(self.bah), "--zori", str(self.zori), "--safmr", str(self.safmr),
                "--ownership", str(self.own), "--out", str(self.out), "--profiles", str(self.profiles)]
        return subprocess.run([sys.executable, str(SCRIPT), *args, *extra], capture_output=True, text=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()


class TestMetrics(Fixture):
    def test_rent_b12_b13(self) -> None:
        p = self.run_metrics()
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = {(r["profile"], r["mha"]): r for r in read(self.out / "mha_rent_metrics.csv")}
        self.assertEqual(len(rows), 6)                                       # 2 profiles x 3 MHAs, no ZZ001
        a = rows[("e5_dep", "AA001")]
        # 1900 / 2000 = 0.95, exactly on target; full-cost gap -100, target gap 1900 - 0.95 x 2000 = 0
        self.assertEqual(a["bah_monthly"], "1900.00")                        # with-deps rate, not 1500
        self.assertEqual((a["coverage_ratio"], a["gap_vs_target"]), ("0.9500", "0.0000"))
        self.assertEqual((a["surplus_usd"], a["target_gap_usd"]), ("-100.00", "0.00"))
        # SAFMR 2BR cross-check: 1900 / 1800 = 1.0556, surplus +100
        self.assertEqual((a["safmr_bedrooms"], a["safmr_coverage_ratio"], a["safmr_surplus_usd"]),
                         ("2", "1.0556", "100.00"))
        b = rows[("e5_dep", "AA002")]
        # 2400 / 3000 = 0.80, gap -0.15; target gap 2400 - 2850 = -450
        self.assertEqual((b["coverage_ratio"], b["gap_vs_target"], b["target_gap_usd"]),
                         ("0.8000", "-0.1500", "-450.00"))
        c = rows[("e5_dep", "AA003")]
        self.assertEqual((c["status"], c["coverage_ratio"]), ("no_zori", ""))
        self.assertEqual(c["safmr_coverage_ratio"], "1.5000")                # cross-check still reported
        o = rows[("o3_dep", "AA001")]
        # O-3 uses the 3BR SAFMR: 2600 / 2400 = 1.0833; ZORI has no bedroom split: 2600 / 2000 = 1.30
        self.assertEqual((o["coverage_ratio"], o["safmr_bedrooms"], o["safmr_coverage_ratio"]),
                         ("1.3000", "3", "1.0833"))

    def test_buy_b14_b15(self) -> None:
        p = self.run_metrics()
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = {(r["profile"], r["mha"]): r for r in read(self.out / "mha_buy_metrics.csv")}
        a = rows[("e5_dep", "AA001")]
        # 1900 / 2500 = 0.76; surplus -600; target gap 1900 - 2375 = -475
        self.assertEqual((a["coverage_ratio"], a["surplus_usd"], a["target_gap_usd"]),
                         ("0.7600", "-600.00", "-475.00"))
        self.assertEqual(rows[("e5_dep", "AA002")]["status"], "no_home_value")
        c = rows[("e5_dep", "AA003")]
        self.assertEqual((c["status"], c["coverage_ratio"], c["own_housing_monthly"]),
                         ("no_utilities", "", "1100.00"))

    def test_manifest_summary(self) -> None:
        p = self.run_metrics()
        self.assertEqual(p.returncode, 0, p.stderr)
        man = json.loads((self.out / "coverage_metrics_manifest.json").read_text())
        self.assertEqual(man["nodes"], ["B12", "B13", "B14", "B15"])
        self.assertEqual(man["windows"]["B8"], MONTHS)
        rent = man["profiles"]["e5_dep"]["rent"]
        self.assertEqual((rent["mhas"], rent["mhas_with_value"], rent["mhas_below_target"]), (3, 2, 1))
        self.assertEqual(rent["status_counts"], {"ok": 2, "no_zori": 1})
        # A13 half-open classes: 0.95 sits in [0.94, 0.96), 0.80 below 0.85
        self.assertEqual(rent["coverage_ratio_classes"]["94-96%: at the 95% target"], 1)
        self.assertEqual(rent["coverage_ratio_classes"]["Below 85%: severe shortfall"], 1)
        # median(0.95 - 1.0556, 0.80 - 0.96) = median(-0.1056, -0.16) = -0.1328
        self.assertAlmostEqual(
            man["profiles"]["e5_dep"]["rent_safmr_crosscheck"]["median_ratio_diff_zori_minus_safmr"],
            -0.1328, places=3)
        self.assertEqual(man["profiles"]["e5_dep"]["buy"]["status_counts"],
                         {"ok": 1, "no_home_value": 1, "no_utilities": 1})
        self.assertEqual(man["warnings"], [])

    def test_rent_only_mode(self) -> None:
        p = subprocess.run([sys.executable, str(SCRIPT), "--mode", "rent", "--bah-rates", str(self.bah),
                            "--zori", str(self.zori), "--safmr", str(self.safmr), "--out", str(self.out),
                            "--profiles", str(self.profiles)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.out / "mha_rent_metrics.csv").exists())
        self.assertFalse((self.out / "mha_buy_metrics.csv").exists())

    def test_implausible_ratio_warns(self) -> None:
        rows = read(self.bah)
        rows[0]["monthly_rate"] = "9000.0"                                  # AA001 E5: 9000 / 2000 = 4.5
        write(self.bah, [list(rows[0])] + [list(r.values()) for r in rows])
        p = self.run_metrics()
        self.assertEqual(p.returncode, 0, p.stderr)
        man = json.loads((self.out / "coverage_metrics_manifest.json").read_text())
        self.assertTrue(any("outside 0.3-2.5" in w and "e5_dep/AA001=4.5000" in w for w in man["warnings"]))


class TestValidation(Fixture):
    def assertFails(self, needle: str) -> None:
        p = self.run_metrics()
        self.assertNotEqual(p.returncode, 0, "expected a failure")
        self.assertIn(needle, p.stderr)

    def test_missing_bah_cell(self) -> None:
        rows = [r for r in read(self.bah) if not (r["mha"] == "AA003" and r["pay_grade"] == "O3")]
        write(self.bah, [list(rows[0])] + [list(r.values()) for r in rows])
        self.assertFails("B4 has no O3 with-dependents rate for 1 MHA(s) (o3_dep): AA003")

    def test_safmr_mha_mismatch(self) -> None:
        rows = [r for r in read(self.safmr) if r["mha"] != "AA002"]
        write(self.safmr, [list(rows[0])] + [list(r.values()) for r in rows])
        self.assertFails("B8 and B10 cover different MHAs")

    def test_window_mismatch(self) -> None:
        self.write_manifests(b9_months=["2026-01", "2026-02"])
        self.assertFails("cover different months")

    def test_stale_b11(self) -> None:
        rows = read(self.zori)                                              # B8 changes after B11 was built
        rows[0]["zori_utilities_adjusted"] = "2100.00"
        write(self.zori, [list(rows[0])] + [list(r.values()) for r in rows])
        self.assertFails("B11 was built from a different mha_zori.csv")

    def test_zero_cost_fails(self) -> None:
        rows = read(self.safmr)
        rows[0]["safmr_median"] = "0"
        write(self.safmr, [list(rows[0])] + [list(r.values()) for r in rows])
        self.assertFails("must be greater than zero")


if __name__ == "__main__":
    unittest.main()
