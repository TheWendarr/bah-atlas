"""
Tests for the 2.5 computed-metric nodes (B12-B15) against small synthetic
benchmark tables shaped like the B4, B8, B10, B11, B29 and B30 outputs. Each
profile's cost is its A14 standard (D19): E-5 the 2 BR townhouse (= B8, B11),
O-3 98% of the way from a 3 BR townhouse to a 3 BR single-family home.

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
TYPES = ["apt1", "apt2", "th2", "th3", "sfh3", "sfh4"]


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
    """Three real MHAs and two profiles. Cost shares: E-5 $100, O-3 $150.

    AA001: has ZORI, SAFMR, full ownership cost. Below 95% of cost, but exactly at
           the statutory design point (BAH + cost share = benchmark)
    AA002: has ZORI and SAFMR; no ZHVI            -> buy status no_home_value
    AA003: no ZORI; has SAFMR and a home value     -> rent no_zori, buy piti_only_no_zori
    ZZ001: County Cost Group, present only in B4   -> ignored
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.bench = self.d / "bench"
        self.bench.mkdir()
        self.out = self.d / "out"
        self.profile_cfg = {
            "coverage_target": 0.95,
            "cost_share": {"source": "test", "url": "https://example.invalid", "sha256": "0" * 64},
            "profiles": [
                {"id": "e5_dep", "pay_grade": "E5", "has_dependents": True, "anchor_bedrooms": 2,
                 "cost_share_monthly": 100},
                {"id": "o3_dep", "pay_grade": "O3", "has_dependents": True, "anchor_bedrooms": 3,
                 "cost_share_monthly": 150},
            ]}
        self.profiles = self.d / "profiles.json"
        self.profiles.write_text(json.dumps(self.profile_cfg))
        self.bah = write(self.d / "bah_rates.csv", [
            ["mha", "pay_grade", "has_dependents", "monthly_rate"],
            ["AA001", "E5", "True", 1860.0], ["AA001", "E5", "False", 1500.0],   # without-deps row must be ignored
            ["AA001", "O3", "True", 2600.0],
            ["AA002", "E5", "True", 2400.0], ["AA002", "O3", "True", 3000.0],
            ["AA003", "E5", "True", 1500.0], ["AA003", "O3", "True", 2000.0],
            ["ZZ001", "E5", "True", 1200.0],
        ])
        self.zori = write(self.bench / "mha_zori.csv", [
            ["mha", "n_zips", "n_zips_with_data", "zip_coverage", "zori_median", "rent_share",
             "zori_utilities_adjusted", "utilities_usd"],
            ["AA001", 2, 2, "1.0000", "1568.00", "0.8000", "1960.00", "392.00"],
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
            ["AA001", "300000.00", "2108.00", "392.00", "2500.00"],
            ["AA002", "", "", "", ""],
            ["AA003", "150000.00", "1100.00", "", ""],
        ])
        # A14 with the fixture's cost shares (the repository file holds the real $126 and $151).
        std = json.loads((ROOT / "config" / "housing_standards.json").read_text())
        std["cost_share_monthly"]["E5"]["with"], std["cost_share_monthly"]["O3"]["with"] = 100, 150
        self.standards = self.d / "housing_standards.json"
        self.standards.write_text(json.dumps(std))
        # B29: the 2 BR townhouse is B8; AA001 th3 2548, sfh3 2940; AA002 th3 3900, sfh3 4500.
        rent = {"AA001": {"th2": "1960.00", "th3": "2548.00", "sfh3": "2940.00"},
                "AA002": {"th2": "3000.00", "th3": "3900.00", "sfh3": "4500.00"}, "AA003": {}}
        self.rent_types = write(self.bench / "mha_rent_by_type.csv", [["mha", "home_type", "rent_monthly", "status"]] + [
            [m, t, rent[m].get(t, "1000.00" if rent[m] else ""), "ok" if rent[m] else "no_zori"]
            for m in rent for t in TYPES])
        # B30: the 2 BR townhouse is B11; AA001 th3 total 3100 (PITI 2700), sfh3 3600 (3150); AA003 PITI only.
        own = {"AA001": {"th2": ("2108.00", "2500.00"), "th3": ("2700.00", "3100.00"), "sfh3": ("3150.00", "3600.00")},
               "AA002": {}, "AA003": {"th2": ("1100.00", ""), "th3": ("1300.00", ""), "sfh3": ("1500.00", "")}}
        self.own_types = write(self.bench / "mha_ownership_by_type.csv",
                               [["mha", "home_type", "own_housing_monthly", "own_total_monthly"]] + [
            [m, t, *own[m].get(t, ("900.00", "1000.00" if m == "AA001" else "") if own[m] else ("", ""))]
            for m in own for t in TYPES])
        self.write_manifests()
        self.write_type_manifests()

    def write_manifests(self, b9_months: list[str] = MONTHS) -> None:
        (self.bench / "mha_zori_manifest.json").write_text(json.dumps({"window_months_used": MONTHS}))
        (self.bench / "mha_zhvi_manifest.json").write_text(json.dumps({"window_months_used": b9_months}))
        (self.bench / "mha_ownership_manifest.json").write_text(json.dumps({
            "rate": {"window": "2026-01:2026-03"},
            "input_sha256": {"B8": sha(self.zori), "B9": sha(self.zhvi)}}))

    def write_type_manifests(self) -> None:
        (self.bench / "mha_rent_by_type_manifest.json").write_text(json.dumps({"input_sha256": {"B8": sha(self.zori)}}))
        (self.bench / "mha_ownership_by_type_manifest.json").write_text(
            json.dumps({"input_sha256": {"B11": sha(self.own)}}))

    def run_metrics(self, *extra: str) -> subprocess.CompletedProcess:
        args = ["--bah-rates", str(self.bah), "--zori", str(self.zori), "--safmr", str(self.safmr),
                "--rent-by-type", str(self.rent_types), "--ownership", str(self.own),
                "--own-by-type", str(self.own_types), "--out", str(self.out), "--profiles", str(self.profiles),
                "--standards", str(self.standards)]
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
        # BAH 1860, cost 1960, share 100. R = 0.9490, under a flat 95% ...
        self.assertEqual(a["bah_monthly"], "1860.00")                        # with-deps rate, not 1500
        self.assertEqual((a["coverage_ratio"], a["flat95_gap"]), ("0.9490", "-0.0010"))
        # ... but (1860 + 100) / 1960 = 1.00: exactly the statutory design. Designed share 1 - 100/1960 = 0.9490
        self.assertEqual((a["adequacy_ratio"], a["adequacy_gap"], a["design_coverage"]),
                         ("1.0000", "0.0000", "0.9490"))
        self.assertEqual((a["surplus_usd"], a["design_gap_usd"], a["cost_share_monthly"]),
                         ("-100.00", "0.00", "100.00"))
        # SAFMR 2BR cross-check: 1860 / 1800 = 1.0333; (1860 + 100) / 1800 = 1.0889; gap +160
        self.assertEqual((a["safmr_bedrooms"], a["safmr_coverage_ratio"], a["safmr_adequacy_ratio"],
                          a["safmr_design_gap_usd"]), ("2", "1.0333", "1.0889", "160.00"))
        b = rows[("e5_dep", "AA002")]
        # 2400 / 3000 = 0.80; (2400 + 100) / 3000 = 0.8333, gap -0.1667; design gap 2500 - 3000 = -500
        self.assertEqual((b["coverage_ratio"], b["adequacy_ratio"], b["adequacy_gap"], b["design_gap_usd"]),
                         ("0.8000", "0.8333", "-0.1667", "-500.00"))
        c = rows[("e5_dep", "AA003")]
        self.assertEqual((c["status"], c["adequacy_ratio"]), ("no_zori", ""))
        self.assertEqual(c["safmr_adequacy_ratio"], "1.6000")                # (1500 + 100) / 1000
        self.assertEqual(a["standard"], "th2")
        o = rows[("o3_dep", "AA001")]
        # O-3 standard: 2548 + 0.98 x (2940 - 2548) = 2932.16; (2600 + 150) / 2932.16 = 0.9379
        # 3BR SAFMR cross-check: (2600 + 150) / 2400 = 1.1458
        self.assertEqual((o["standard"], o["cost_monthly"], o["adequacy_ratio"], o["safmr_bedrooms"],
                          o["safmr_adequacy_ratio"]), ("th3-sfh3 0.98", "2932.16", "0.9379", "3", "1.1458"))

    def test_buy_b14_b15(self) -> None:
        p = self.run_metrics()
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = {(r["profile"], r["mha"]): r for r in read(self.out / "mha_buy_metrics.csv")}
        a = rows[("e5_dep", "AA001")]
        # 1860 / 2500 = 0.7440; (1860 + 100) / 2500 = 0.7840; design gap 1960 - 2500 = -540
        self.assertEqual((a["coverage_ratio"], a["adequacy_ratio"], a["design_gap_usd"]),
                         ("0.7440", "0.7840", "-540.00"))
        self.assertEqual(rows[("e5_dep", "AA002")]["status"], "no_home_value")
        c = rows[("e5_dep", "AA003")]
        # Decision 2.4: no utilities estimate, so the cost is PITI alone: (1500 + 100) / 1100 = 1.4545
        self.assertEqual((c["status"], c["cost_monthly"], c["adequacy_ratio"], c["coverage_ratio"]),
                         ("piti_only_no_zori", "1100.00", "1.4545", "1.3636"))
        o = rows[("o3_dep", "AA001")]
        # 3100 + 0.98 x 500 = 3590 (PITI 2700 + 0.98 x 450 = 3141); (2600 + 150) / 3590 = 0.7660
        self.assertEqual((o["cost_monthly"], o["own_housing_monthly"], o["adequacy_ratio"]),
                         ("3590.00", "3141.00", "0.7660"))
        o3 = rows[("o3_dep", "AA003")]                                       # PITI only: 1300 + 0.98 x 200
        self.assertEqual((o3["status"], o3["cost_monthly"]), ("piti_only_no_zori", "1496.00"))

    def test_manifest_summary(self) -> None:
        p = self.run_metrics()
        self.assertEqual(p.returncode, 0, p.stderr)
        man = json.loads((self.out / "coverage_metrics_manifest.json").read_text())
        self.assertEqual(man["nodes"], ["B12", "B13", "B14", "B15"])
        self.assertEqual(man["windows"]["B8"], MONTHS)
        self.assertEqual(man["cost_share"]["per_profile"], {"e5_dep": 100, "o3_dep": 150})
        rent = man["profiles"]["e5_dep"]["rent"]
        self.assertEqual((rent["mhas"], rent["mhas_with_value"], rent["mhas_below_design"]), (3, 2, 1))
        self.assertEqual(rent["status_counts"], {"ok": 2, "no_zori": 1})
        # AA001 is short only under the flat-95% reading
        self.assertEqual(rent["flat95_vs_design"], {"mhas_below_flat_95": 2,
                                                    "short_under_flat_95_only": ["AA001"],
                                                    "short_under_design_only": []})
        # A13 half-open classes: 1.00 sits in [0.97, 1.03); 0.8333 below 0.85
        self.assertEqual(rent["adequacy_ratio_classes"]["97-103%: at the statutory design point"], 1)
        self.assertEqual(rent["adequacy_ratio_classes"]["Below 85%: far below the statutory design"], 1)
        self.assertEqual(rent["design_gap_usd_classes"]["Within $50 of design"], 1)
        # median(1.0000 - 1.0889, 0.8333 - 1.0000) = median(-0.0889, -0.1667) = -0.1278
        self.assertAlmostEqual(
            man["profiles"]["e5_dep"]["rent_safmr_crosscheck"]["median_adequacy_diff_zori_minus_safmr"],
            -0.1278, places=3)
        buy = man["profiles"]["e5_dep"]["buy"]
        self.assertEqual(buy["status_counts"], {"ok": 1, "piti_only_no_zori": 1, "no_home_value": 1})
        # Summaries compare like with like: the PITI-only row is mapped but not summarized.
        self.assertEqual((buy["mhas"], buy["mhas_with_value"]), (3, 1))
        self.assertEqual(man["warnings"], [])

    def test_rent_only_mode(self) -> None:
        p = subprocess.run([sys.executable, str(SCRIPT), "--mode", "rent", "--bah-rates", str(self.bah),
                            "--zori", str(self.zori), "--safmr", str(self.safmr), "--out", str(self.out),
                            "--rent-by-type", str(self.rent_types), "--profiles", str(self.profiles),
                            "--standards", str(self.standards)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.out / "mha_rent_metrics.csv").exists())
        self.assertFalse((self.out / "mha_buy_metrics.csv").exists())

    def test_implausible_ratio_warns(self) -> None:
        rows = read(self.bah)
        rows[0]["monthly_rate"] = "9000.0"                                  # AA001 E5: 9000 / 1960 = 4.59
        write(self.bah, [list(rows[0])] + [list(r.values()) for r in rows])
        p = self.run_metrics()
        self.assertEqual(p.returncode, 0, p.stderr)
        man = json.loads((self.out / "coverage_metrics_manifest.json").read_text())
        self.assertTrue(any("outside 0.3-2.5" in w and "e5_dep/AA001=4.5918" in w for w in man["warnings"]))


class TestValidation(Fixture):
    def assertFails(self, needle: str) -> None:
        p = self.run_metrics()
        self.assertNotEqual(p.returncode, 0, "expected a failure")
        self.assertIn(needle, p.stderr)

    def test_missing_cost_share(self) -> None:
        del self.profile_cfg["profiles"][1]["cost_share_monthly"]
        self.profiles.write_text(json.dumps(self.profile_cfg))
        self.assertFails("profile o3_dep: cost_share_monthly")

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
        self.write_type_manifests()                                         # B29 rebuilt, B11 not
        self.assertFails("B11 was built from a different mha_zori.csv")

    def test_stale_b29(self) -> None:
        rows = read(self.zori)                                              # B8 changes after B29 was built
        rows[1]["zori_utilities_adjusted"] = "3100.00"
        write(self.zori, [list(rows[0])] + [list(r.values()) for r in rows])
        self.assertFails("B29 was built from a different mha_zori.csv")

    def test_profile_cost_share_must_match_a14(self) -> None:
        self.profile_cfg["profiles"][0]["cost_share_monthly"] = 126
        self.profiles.write_text(json.dumps(self.profile_cfg))
        self.assertFails("profile e5_dep: cost_share_monthly 126 != A14 100")

    def test_zero_cost_fails(self) -> None:
        rows = read(self.safmr)
        rows[0]["safmr_median"] = "0"
        write(self.safmr, [list(rows[0])] + [list(r.values()) for r in rows])
        self.assertFails("must be greater than zero")


if __name__ == "__main__":
    unittest.main()
