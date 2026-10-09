"""
Tests for the 2.3 / 2.4 benchmark nodes (B8-B11) against small synthetic fixtures
that mirror the vendor layouts documented in docs/SOURCES.md.

    python -m unittest discover -s tests -v        (or: make test)

Each script runs as a subprocess, exactly as the Makefile calls it. Expected
numbers are worked out by hand in the comments so a reader can check them.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "pipeline" / "benchmarks"


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(BENCH / script), *args],
                          capture_output=True, text=True)


def read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write(path: Path, rows: list[list]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)
    return path


class Fixture(unittest.TestCase):
    """Three real MHAs and one County Cost Group.

    AA001: ZIPs 00501, 00502       (both have Zillow data)
    AA002: ZIPs 10001, 10002, 10003 (10003 has only 2 months -> dropped at min 3)
    AA003: ZIP 20001               (no Zillow data at all)
    ZZ001: ZIP 30001               (CCG, excluded from aggregation)
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.out = self.d / "out"
        self.crosswalk = write(self.d / "zip_mha.csv", [
            ["zip", "mha", "mha_class"],
            ["00501", "AA001", "mha"], ["00502", "AA001", "mha"],
            ["10001", "AA002", "mha"], ["10002", "AA002", "mha"], ["10003", "AA002", "mha"],
            ["20001", "AA003", "mha"],
            ["30001", "ZZ001", "ccg"],
        ])
        self.components = write(self.d / "rate_components.csv", [
            ["mha", "name", "rent_pct", "utilities_pct", "rent_share", "utilities_share"],
            ["AA001", "ONE", 80, 20, "0.8000", "0.2000"],
            ["AA002", "TWO", 75, 25, "0.7500", "0.2500"],
            ["AA003", "THREE", 85, 15, "0.8500", "0.1500"],
        ])
        head = ["RegionID", "SizeRank", "RegionName", "RegionType", "StateName", "State",
                "City", "Metro", "CountyName", "2025-11-30", "2025-12-31",
                "2026-01-31", "2026-02-28", "2026-03-31"]
        # Window 2026-01:2026-12 -> the three 2026 columns. ZIP 501 has lost its zeros.
        self.zori = write(self.d / "Zip_zori.csv", [
            head,
            [1, 1, "501", "zip", "", "NY", "", "", "", 900, 950, 1000, 1100, 1200],   # mean 1100
            [2, 2, "502", "zip", "", "NY", "", "", "", 0, 0, 2000, 2000, 2000],       # mean 2000 (the 2025 zeros fall outside the window)
            [3, 3, "10001", "zip", "", "NY", "", "", "", "", "", 3000, 3000, 3000],   # 3000
            [4, 4, "10002", "zip", "", "NY", "", "", "", "", "", 1500, 1600, 1700],   # 1600
            [5, 5, "10003", "zip", "", "NY", "", "", "", "", "", "", 9000, 9000],     # 2 months -> dropped
            [6, 6, "30001", "zip", "", "TX", "", "", "", "", "", 800, 800, 800],      # CCG
        ])

    def tearDown(self) -> None:
        self.tmp.cleanup()


class TestZillow(Fixture):
    def test_zori_b8(self) -> None:
        # The 2025 zeros in ZIP 502 sit outside the window, so the range check never sees them.
        p = run("zillow_to_mha.py", "--series", "zori", "--csv", str(self.zori),
                "--crosswalk", str(self.crosswalk), "--rate-components", str(self.components),
                "--out", str(self.out), "--window", "2026-01:2026-12")
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = {r["mha"]: r for r in read(self.out / "mha_zori.csv")}
        self.assertEqual(sorted(rows), ["AA001", "AA002", "AA003"])           # CCG left out
        # AA001: median(1100, 2000) = 1550; / 0.80 = 1937.50; utilities 387.50
        self.assertEqual(rows["AA001"]["zori_median"], "1550.00")
        self.assertEqual(rows["AA001"]["zori_utilities_adjusted"], "1937.50")
        self.assertEqual(rows["AA001"]["utilities_usd"], "387.50")
        # AA002: 10003 dropped (2 months) -> median(3000, 1600) = 2300; coverage 2/3
        self.assertEqual(rows["AA002"]["zori_median"], "2300.00")
        self.assertEqual(rows["AA002"]["n_zips_with_data"], "2")
        self.assertEqual(rows["AA002"]["zip_coverage"], "0.6667")
        # AA003 has no data but still gets a row
        self.assertEqual(rows["AA003"]["n_zips_with_data"], "0")
        self.assertEqual(rows["AA003"]["zori_median"], "")
        man = json.loads((self.out / "mha_zori_manifest.json").read_text())
        self.assertEqual(man["window_months_used"], ["2026-01", "2026-02", "2026-03"])
        self.assertEqual(man["coverage"]["mhas_without_data"], ["AA003"])
        self.assertEqual(man["crosswalk"]["zips_skipped_by_class"], {"ccg": 1})
        zips = {r["zip"] for r in read(self.out / "zip_zori.csv")}
        self.assertIn("00501", zips)                                          # zero-padded
        self.assertNotIn("30001", zips)

    def test_zori_requires_components(self) -> None:
        p = run("zillow_to_mha.py", "--series", "zori", "--csv", str(self.zori),
                "--crosswalk", str(self.crosswalk), "--out", str(self.out))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--rate-components", p.stderr)

    def test_zhvi_b9_and_short_window(self) -> None:
        with self.zori.open(newline="") as fh:
            rows = list(csv.reader(fh))
        for r in rows[1:]:                      # rents x 200 -> home values
            r[9:] = [str(int(v) * 200) if v else "" for v in r[9:]]
        zhvi = write(self.d / "Zip_zhvi.csv", rows)
        p = run("zillow_to_mha.py", "--series", "zhvi", "--csv", str(zhvi),
                "--crosswalk", str(self.crosswalk), "--out", str(self.out), "--window", "2026-01:2026-12")
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = {r["mha"]: r for r in read(self.out / "mha_zhvi.csv")}
        self.assertEqual(rows["AA001"]["zhvi_median"], "310000.00")       # median(220k, 400k)
        p = run("zillow_to_mha.py", "--series", "zhvi", "--csv", str(zhvi),
                "--crosswalk", str(self.crosswalk), "--out", str(self.out), "--window", "2026-03:2026-12")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("need at least 3", p.stderr)

    def test_out_of_range_value_fails(self) -> None:
        bad = self.d / "bad.csv"
        with self.zori.open(newline="") as fh:
            rows = list(csv.reader(fh))
        rows[1][-1] = "5"                       # a $5 rent
        write(bad, rows)
        p = run("zillow_to_mha.py", "--series", "zori", "--csv", str(bad),
                "--crosswalk", str(self.crosswalk), "--rate-components", str(self.components),
                "--out", str(self.out), "--window", "2026-01:2026-12")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("outside plausible range", p.stderr)


class TestSafmr(Fixture):
    def make_xlsx(self, headers: list[str], rows: list[list]) -> Path:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        for r in rows:
            ws.append(r)
        path = self.d / "safmr.xlsx"
        wb.save(path)
        return path

    HEAD = ["ZIP\nCode", "HUD Area Code", "HUD Fair Market Rent Area Name"] + [
        h for b in range(5) for h in (f"SAFMR\n{b}BR", f"SAFMR\n{b}BR - 90%\nPayment\nStandard",
                                      f"SAFMR\n{b}BR - 110%\nPayment\nStandard")]

    @staticmethod
    def row(z, area, base: list[int]) -> list:
        return [z, area, "Area"] + [v for b in base for v in (b, round(b * 0.9), round(b * 1.1))]

    def test_b10(self) -> None:
        x = self.make_xlsx(self.HEAD, [
            self.row(501, "A1", [1000, 1100, 1300, 1700, 2000]),      # integer ZIP, lost zeros
            self.row("00502", "A1", [1200, 1300, 1500, 1900, 2200]),
            self.row("10001", "A2", [2000, 2100, 2400, 3000, 3300]),
            self.row("10001", "A3", [2200, 2300, 2600, 3200, 3500]),  # straddles two HUD areas
        ])
        p = run("safmr_to_mha.py", "--xlsx", str(x), "--crosswalk", str(self.crosswalk), "--out", str(self.out))
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = {(r["mha"], r["bedrooms"]): r for r in read(self.out / "mha_safmr.csv")}
        self.assertEqual(len(rows), 15)                                   # 3 MHAs x 5 bedroom counts
        self.assertEqual(rows[("AA001", "2")]["safmr_median"], "1400.00")  # median(1300, 1500)
        self.assertEqual(rows[("AA002", "2")]["safmr_median"], "2500.00")  # mean of two area rows
        self.assertEqual(rows[("AA002", "2")]["zip_coverage"], "0.3333")
        self.assertEqual(rows[("AA003", "3")]["safmr_median"], "")
        man = json.loads((self.out / "mha_safmr_manifest.json").read_text())
        self.assertEqual(man["header_map"]["br2"], "SAFMR 2BR")             # base column, not payment std
        self.assertTrue(any("more than one HUD area" in w for w in man["warnings"]))

    def test_missing_columns_print_headers(self) -> None:
        x = self.make_xlsx(["ZIP Code", "Two Bedroom"], [["00501", 1000]])
        p = run("safmr_to_mha.py", "--xlsx", str(x), "--crosswalk", str(self.crosswalk), "--out", str(self.out))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("two bedroom", p.stderr)                            # shows what it saw

    def test_mislabelled_bedrooms_fail(self) -> None:
        x = self.make_xlsx(self.HEAD, [self.row("00501", "A1", [2000, 1800, 1600, 1400, 1200])])
        p = run("safmr_to_mha.py", "--xlsx", str(x), "--crosswalk", str(self.crosswalk), "--out", str(self.out))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("mislabelled", p.stderr)


class TestOwnership(Fixture):
    def test_b11(self) -> None:
        zhvi = write(self.d / "mha_zhvi.csv", [
            ["mha", "n_zips", "n_zips_with_data", "zip_coverage", "zhvi_median"],
            ["AA001", 2, 2, "1.0000", "300000.00"], ["AA002", 3, 0, "0.0000", ""],
            ["AA003", 1, 1, "1.0000", "200000.00"]])
        zori = write(self.d / "mha_zori.csv", [
            ["mha", "utilities_usd"], ["AA001", "387.50"], ["AA002", "400.00"], ["AA003", ""]])
        # Blank cells hold a single space, as in Freddie Mac's file; one row outside the window.
        pmms = write(self.d / "PMMS_history.csv", [
            ["date", "pmms30", "pmms30p", "pmms15"],
            ["12/26/2025", "9.00", " ", " "],
            ["1/1/2026", "6.40", " ", " "], ["1/8/2026", "6.60", " ", " "],
            ["2/5/2026", "6.40", " ", " "], ["3/5/2026", "6.60", " ", " "]])
        p = run("ownership_cost.py", "--zhvi", str(zhvi), "--zori", str(zori), "--pmms", str(pmms),
                "--out", str(self.out), "--window", "2026-01:2026-12")
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = {r["mha"]: r for r in read(self.out / "mha_ownership.csv")}
        a = rows["AA001"]
        self.assertEqual(a["rate_pct"], "6.500")                            # 9.00 week excluded
        self.assertEqual(a["loan_amount"], "306450.00")                     # 300k + 2.15% fee, 0% down
        # $300,000 at 6.5%/30y is $1,896.20/mo, so $306,450 is $1,936.97
        self.assertAlmostEqual(float(a["pi_monthly"]), 1936.97, delta=0.02)
        self.assertEqual(a["tax_monthly"], "222.50")                        # 300k x 0.89% / 12
        self.assertEqual(a["insurance_monthly"], "130.75")                  # 1569 / 12
        self.assertAlmostEqual(float(a["own_housing_monthly"]), 1936.97 + 222.50 + 130.75, delta=0.03)
        self.assertAlmostEqual(float(a["own_total_monthly"]), float(a["own_housing_monthly"]) + 387.50, delta=0.01)
        self.assertEqual(rows["AA002"].get("own_housing_monthly", ""), "")  # no home value
        self.assertEqual(rows["AA003"]["own_total_monthly"], "")            # no utilities estimate
        man = json.loads((self.out / "mha_ownership_manifest.json").read_text())
        self.assertEqual(man["rate"]["weeks"], 4)
        self.assertTrue(any("placeholder" in w for w in man["warnings"]))

    def test_bad_config_fails(self) -> None:
        cfg = json.loads((ROOT / "config" / "ownership.json").read_text())
        cfg["property_tax"]["annual_share"] = 0.89                          # percent typed as share
        bad = self.d / "ownership.json"
        bad.write_text(json.dumps(cfg))
        p = run("ownership_cost.py", "--zhvi", str(self.d / "x.csv"), "--pmms", str(self.d / "y.csv"),
                "--out", str(self.out), "--config", str(bad))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("property_tax.annual_share", p.stderr)


if __name__ == "__main__":
    unittest.main()
