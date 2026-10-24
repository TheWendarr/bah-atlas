"""
Tests for the home-type benchmarks (D19): B29 rent and B30 ownership cost by home
type, and the blend formula every stage and the map share (home_types.py).

    python -m unittest discover -s tests -v        (or: make test)

The fixture runs the real chain as the Makefile does: B8 and B9 from ZIP-level
Zillow files, B11, then B29 and B30. Expected numbers are worked by hand below.

  AA001  ZIPs 00501, 00502   metro "Alpha, NY": SFR and MFR metro series both present
  AA002  ZIPs 10001, 10002   metro "Beta, NY": MFR only, so single-family takes the national ratio;
                             no condo ZHVI, so apartments take the national buy ratio
  AA003  ZIP 20001           no metro, no ZORI (status no_zori / piti_only_no_zori), ZHVI all-homes only
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
sys.path.insert(0, str(BENCH))
import home_types as ht  # noqa: E402

MONTHS = ["2026-01-31", "2026-02-28", "2026-03-31"]
WINDOW = "2026-01:2026-12"


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(BENCH / script), *args], capture_output=True, text=True)


def write(path: Path, rows: list[list]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)
    return path


def read(path: Path) -> dict[tuple[str, str], dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {(r["mha"], r.get("home_type", "")): r for r in csv.DictReader(fh)}


def zip_file(path: Path, values: dict[str, float], metros: dict[str, str] | None = None) -> Path:
    head = ["RegionID", "SizeRank", "RegionName", "RegionType", "StateName", "State", "City", "Metro",
            "CountyName", *MONTHS]
    rows = [[i, i, z, "zip", "", "NY", "", (metros or {}).get(z, ""), "", v, v, v]
            for i, (z, v) in enumerate(values.items(), start=1)]
    return write(path, [head, *rows])


def metro_file(path: Path, values: dict[str, float]) -> Path:
    head = ["RegionID", "SizeRank", "RegionName", "RegionType", "StateName", *MONTHS]
    rows = [[i, i, name, "country" if name == "United States" else "msa", "", v, v, v]
            for i, (name, v) in enumerate(values.items())]
    return write(path, [head, *rows])


class TestBlend(unittest.TestCase):
    costs = {"apt1": 1000.0, "apt2": 1200.0, "th2": 1500.0, "th3": 1900.0, "sfh3": 2300.0, "sfh4": 2700.0}

    def test_anchor_interpolated_and_above_top(self) -> None:
        self.assertEqual(ht.blend(self.costs, {"lower": "th2", "upper": None, "share": 0}), 1500.0)
        # O-3 with dependents: 1900 + 0.98 x 400 = 2292
        self.assertAlmostEqual(ht.blend(self.costs, {"lower": "th3", "upper": "sfh3", "share": 0.98}), 2292.0)
        # O-7 with dependents: 2700 x 1.02 = 2754
        self.assertAlmostEqual(ht.blend(self.costs, {"lower": "sfh4", "upper": None, "share": 0.02}), 2754.0)

    def test_null_side_makes_the_standard_null(self) -> None:
        costs = {**self.costs, "sfh3": None}
        self.assertIsNone(ht.blend(costs, {"lower": "th3", "upper": "sfh3", "share": 0.98}))
        self.assertEqual(ht.blend(costs, {"lower": "th3", "upper": None, "share": 0}), 1900.0)

    def test_repository_standards_describe(self) -> None:
        cfg = ht.load()
        labels = {"th3": "3 BR townhouse", "sfh3": "3 BR single-family home", "th2": "2 BR townhouse",
                  "sfh4": "4 BR single-family home"}
        self.assertEqual(ht.describe(ht.standard(cfg, "O3", True), labels),
                         "98% of the way from a 3 BR townhouse to a 3 BR single-family home")
        self.assertEqual(ht.describe(ht.standard(cfg, "E5", True), labels), "2 BR townhouse")
        self.assertEqual(ht.describe(ht.standard(cfg, "O7", True), labels), "4 BR single-family home, plus 2%")


class TestChain(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        d = self.d = Path(self.tmp.name)
        self.out = d / "bench"
        self.crosswalk = write(d / "zip_mha.csv", [
            ["zip", "mha", "mha_class"], ["00501", "AA001", "mha"], ["00502", "AA001", "mha"],
            ["10001", "AA002", "mha"], ["10002", "AA002", "mha"], ["20001", "AA003", "mha"],
            ["30001", "ZZ001", "ccg"]])
        components = write(d / "rate_components.csv", [
            ["mha", "rent_share"], ["AA001", "0.8000"], ["AA002", "0.7500"], ["AA003", "0.8500"]])
        metros = {"00501": "Alpha, NY", "00502": "Alpha, NY", "10001": "Beta, NY", "10002": "Beta, NY"}
        # B8: AA001 median(1000, 2000) = 1500 / 0.80 = 1875.00 (utilities 375.00);
        #     AA002 median(3000, 1600) = 2300 / 0.75 = 3066.67 (utilities 766.67); AA003 none
        zori = zip_file(d / "Zip_zori.csv", {"00501": 1000, "00502": 2000, "10001": 3000, "10002": 1600}, metros)
        self.zhvi_all = zip_file(d / "Zip_zhvi_all.csv", {"00501": 200000, "00502": 400000, "10001": 500000,
                                                          "10002": 300000, "20001": 150000}, metros)
        for series, csvf, extra in (("zori", zori, ["--rate-components", str(components)]),
                                    ("zhvi", self.zhvi_all, [])):
            p = run("zillow_to_mha.py", "--series", series, "--csv", str(csvf), "--crosswalk", str(self.crosswalk),
                    "--out", str(self.out), "--window", WINDOW, *extra)
            self.assertEqual(p.returncode, 0, p.stderr)
        # B10: 1 BR / 2 BR = 0.8, 3 BR / 2 BR = 1.3, 4 BR / 2 BR = 1.5 everywhere
        safmr = [["mha", "bedrooms", "safmr_median"]]
        for m, base in (("AA001", 1250), ("AA002", 1500), ("AA003", 1250)):
            for n, k in ((0, 0.64), (1, 0.8), (2, 1.0), (3, 1.3), (4, 1.5)):
                safmr.append([m, n, f"{base * k:.2f}"])
        self.safmr = write(self.out / "mha_safmr.csv", safmr)
        # A15: MFR / all = 0.9 in both metros and nationally; SFR / all = 1.2 in Alpha, none in Beta, 1.1 nationally
        self.metro_all = metro_file(d / "Metro_all.csv", {"United States": 1800, "Alpha, NY": 2000, "Beta, NY": 3000})
        self.metro_mfr = metro_file(d / "Metro_mfr.csv", {"United States": 1620, "Alpha, NY": 1800, "Beta, NY": 2700})
        self.metro_sfr = metro_file(d / "Metro_sfr.csv", {"United States": 1980, "Alpha, NY": 2400})

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_b29(self) -> subprocess.CompletedProcess:
        return run("rent_by_type.py", "--zori", str(self.out / "mha_zori.csv"), "--safmr", str(self.safmr),
                   "--metro-sfr", str(self.metro_sfr), "--metro-mfr", str(self.metro_mfr),
                   "--metro-all", str(self.metro_all), "--zip-metro", str(self.zhvi_all),
                   "--crosswalk", str(self.crosswalk), "--out", str(self.out))

    def test_b29_rent_by_type(self) -> None:
        p = self.run_b29()
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = read(self.out / "mha_rent_by_type.csv")
        b8 = {m: r for (m, _), r in read(self.out / "mha_zori.csv").items()}
        for m in ("AA001", "AA002"):                                       # D19: 2 BR townhouse = B8
            self.assertEqual(rows[(m, "th2")]["rent_monthly"], b8[m]["zori_utilities_adjusted"])
            self.assertEqual(rows[(m, "th2")]["utilities_usd"], b8[m]["utilities_usd"])
        a = {t: rows[("AA001", t)] for t in ht.TYPE_IDS}
        self.assertEqual(a["th3"]["rent_monthly"], "2437.50")              # 1875 x 1.3
        self.assertEqual(a["sfh3"]["rent_monthly"], "2925.00")             # 1875 x 1.2 (Alpha SFR) x 1.3
        self.assertEqual(a["sfh4"]["rent_monthly"], "3375.00")             # 1875 x 1.2 x 1.5
        self.assertEqual(a["apt1"]["rent_monthly"], "1350.00")             # 1875 x 0.9 (Alpha MFR) x 0.8
        self.assertEqual(a["apt1"]["utilities_usd"], "270.00")             # 375 x 0.9 x 0.8
        self.assertEqual((a["sfh3"]["factor_source"], a["th3"]["factor_source"]), ("metro", "reference"))
        b = rows[("AA002", "sfh3")]                                        # Beta has no SFR series
        self.assertEqual((b["factor_source"], b["building_factor"]), ("national", "1.100000"))
        self.assertEqual(b["rent_monthly"], "4385.34")                     # 3066.67 x 1.1 x 1.3
        c = rows[("AA003", "apt2")]
        self.assertEqual((c["status"], c["rent_monthly"], c["factor_source"]), ("no_zori", "", "national"))
        man = json.loads((self.out / "mha_rent_by_type_manifest.json").read_text())
        self.assertEqual(man["building_factors"]["single_family"]["mhas_national_fallback"], 2)
        self.assertEqual(man["metros"]["zip_metro_names_matched"], 2)
        self.assertEqual(set(man["inputs"]), {"B8", "B10", "A15.sfr", "A15.mfr", "A15.all", "A4", "B1", "A14"})

    def test_b29_stops_when_metro_names_do_not_match(self) -> None:
        metro_file(self.metro_all, {"United States": 1800, "Alpha-Town": 2000, "Beta-Town": 3000})
        p = self.run_b29()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("name metros differently", p.stderr)

    def test_b30_ownership_by_type(self) -> None:
        self.assertEqual(self.run_b29().returncode, 0)
        d = self.d
        pmms = write(d / "PMMS_history.csv", [["date", "pmms30"], ["1/1/2026", "6.40"], ["1/8/2026", "6.60"],
                                               ["2/5/2026", "6.40"], ["3/5/2026", "6.60"]])
        taxins = write(d / "mha_tax_insurance.csv", [
            ["mha", "effective_tax_rate", "tax_source", "insurance_annual_usd", "insurance_source"],
            ["AA001", "0.008900", "locality", "1569.00", "locality"],
            ["AA002", "0.012000", "locality", "2000.00", "state_fallback"],
            ["AA003", "0.010000", "state_fallback", "1800.00", "locality"]])
        p = run("ownership_cost.py", "--zhvi", str(self.out / "mha_zhvi.csv"), "--zori", str(self.out / "mha_zori.csv"),
                "--pmms", str(pmms), "--tax-insurance", str(taxins), "--out", str(self.out))
        self.assertEqual(p.returncode, 0, p.stderr)
        # A16: SFR / all per ZIP 1.2, 1.3 (AA001 median 1.25), 1.2, 1.1 (AA002 1.15); national median 1.2.
        # Condo only in AA001's ZIPs: 0.8, 0.7 -> 0.75, which is also the national median.
        # Bedrooms: 1 BR 0.8x, 3 BR 1.25x, 4 BR 1.5x of 2 BR in every ZIP.
        a16 = {"sfr": {"00501": 240000, "00502": 520000, "10001": 600000, "10002": 330000},
               "condo": {"00501": 160000, "00502": 280000}}
        br2 = {"00501": 200000, "00502": 400000, "10001": 500000, "10002": 300000}
        for n, k in ((1, 0.8), (2, 1.0), (3, 1.25), (4, 1.5)):
            a16[f"br{n}"] = {z: v * k for z, v in br2.items()}
        files = {k: zip_file(d / f"Zip_zhvi_{k}.csv", v) for k, v in a16.items()}
        p = run("ownership_by_type.py", "--zhvi", str(self.out / "mha_zhvi.csv"), "--zhvi-all", str(self.zhvi_all),
                "--zhvi-sfr", str(files["sfr"]), "--zhvi-condo", str(files["condo"]),
                *[x for n in (1, 2, 3, 4) for x in (f"--zhvi-br{n}", str(files[f"br{n}"]))],
                "--crosswalk", str(self.crosswalk), "--rent-by-type", str(self.out / "mha_rent_by_type.csv"),
                "--tax-insurance", str(taxins), "--pmms", str(pmms), "--ownership", str(self.out / "mha_ownership.csv"),
                "--out", str(self.out))
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = read(self.out / "mha_ownership_by_type.csv")
        b11 = {m: r for (m, _), r in read(self.out / "mha_ownership.csv").items()}
        for m in ("AA001", "AA002", "AA003"):                              # D19: 2 BR townhouse = B11
            self.assertEqual(rows[(m, "th2")]["own_housing_monthly"], b11[m]["own_housing_monthly"])
            self.assertEqual(rows[(m, "th2")]["own_total_monthly"], b11[m].get("own_total_monthly", ""))
        self.assertEqual(rows[("AA001", "th3")]["home_value"], "375000.00")     # 300k x 1.25
        self.assertEqual(rows[("AA001", "sfh3")]["home_value"], "468750.00")    # 300k x 1.25 x 1.25
        self.assertEqual(rows[("AA001", "apt1")]["home_value"], "180000.00")    # 300k x 0.75 x 0.8
        self.assertEqual(rows[("AA001", "sfh3")]["tax_monthly"], "347.66")      # 468,750 x 0.89% / 12
        self.assertEqual(rows[("AA001", "sfh3")]["insurance_monthly"], "130.75")  # same premium for every type
        total = float(rows[("AA001", "sfh3")]["own_housing_monthly"]) + 2925.00 * (375 / 1875)
        self.assertAlmostEqual(float(rows[("AA001", "sfh3")]["own_total_monthly"]), total, delta=0.011)
        b = rows[("AA002", "apt2")]
        self.assertEqual((b["building_source"], b["building_factor"]), ("national", "0.750000"))
        c = rows[("AA003", "sfh3")]                                         # no A16 ZIPs, no ZORI
        self.assertEqual((c["building_source"], c["bedroom_source"], c["status"]),
                         ("national", "national", "piti_only_no_zori"))
        self.assertEqual(c["home_value"], "225000.00")                      # 150k x 1.2 x 1.25
        man = json.loads((self.out / "mha_ownership_by_type_manifest.json").read_text())
        self.assertEqual(man["ratios"]["building_apartment"]["mhas_national_fallback"], 2)
        self.assertEqual(man["coverage"]["sfh4"]["status"], {"ok": 2, "piti_only_no_zori": 1, "no_home_value": 0})


if __name__ == "__main__":
    unittest.main()
