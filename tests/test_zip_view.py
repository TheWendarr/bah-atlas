"""
Tests for the ZIP view's Layer 2 nodes (decision D36): B33 rent and B34 ownership cost
by home type for each ZIP, and the B35 ZIP tiles.

    python -m unittest discover -s tests -v        (or: make test)

B33 and B34 run on the real chain from test_home_types.py (B8, B9, B10, B11, B29, B30
on synthetic Zillow files), with the ZIP files then edited to give every case:

  B33 (rent)  00501  no ZORI and no SAFMR              -> zip_no_benchmark
              00502  ZORI 2000 / 0.80 = 2500.00        -> base from ZORI; SAFMR 1500 x 1.5 = 2250 is
                                                          10% below it (the scaled-SAFMR check)
              10001  ZORI 12000 / 0.75 = 16000, 5.2x   -> outside the band; SAFMR 2000 x 3066.67 / 1500
                     its MHA's 3066.67                    = 4088.89 is used instead
              10002  ZORI 100 / 0.75 = 133.33, no SAFMR -> zip_outlier
              20001  AA003 has no ZORI                 -> no_zori
  B34 (buy)   00501  ZHVI 200k against AA001's 300k; its own ACS tax rate (1%) and FIO premium (1,200)
              00502  no ZHVI                           -> zip_no_benchmark
              10002  ZHVI 5,000,000, 12.5x AA002's     -> zip_outlier
              20001  AA003's only ZIP, at its MHA value -> B30's own PITI, from the MHA's tax and premium

The B35 run needs tippecanoe and is skipped, never passed, where it is not installed.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_home_types as tht  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TILES = ROOT / "pipeline" / "tiles" / "build_zip_pmtiles.py"


def rows(path: Path) -> dict[tuple[str, str], dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return {(r["zip"], r["home_type"]): r for r in csv.DictReader(fh)}


def edit_zip_values(path: Path, values: dict[str, str | None]) -> None:
    """Set (or, with None, drop) ZIP values in a B8/B9 zip_<series>.csv."""
    with path.open(newline="", encoding="utf-8") as fh:
        data = list(csv.DictReader(fh))
    out = []
    for r in data:
        if r["zip"] in values:
            if values[r["zip"]] is None:
                continue
            r["value"] = values[r["zip"]]
        out.append(r)
    tht.write(path, [list(data[0])] + [list(r.values()) for r in out])


class TestZipRent(tht.TestChain):
    def run_b33(self) -> subprocess.CompletedProcess:
        self.assertEqual(self.run_b29().returncode, 0)
        edit_zip_values(self.out / "zip_zori.csv", {"00501": None, "10001": "12000.00", "10002": "100.00"})
        tht.write(self.out / "zip_safmr.csv", [["zip", "mha", "br0", "br1", "br2", "br3", "br4"],
                                               ["00502", "AA001", "", "", "1500.00", "", ""],
                                               ["10001", "AA002", "", "", "2000.00", "", ""],
                                               ["20001", "AA003", "", "", "1250.00", "", ""]])
        return tht.run("zip_rent_by_type.py", "--zip-zori", str(self.out / "zip_zori.csv"),
                       "--zori", str(self.out / "mha_zori.csv"), "--zip-safmr", str(self.out / "zip_safmr.csv"),
                       "--safmr", str(self.safmr), "--rent-by-type", str(self.out / "mha_rent_by_type.csv"),
                       "--crosswalk", str(self.crosswalk), "--out", str(self.out))

    def test_b33_every_case(self) -> None:
        p = self.run_b33()
        self.assertEqual(p.returncode, 0, p.stderr)
        r = rows(self.out / "zip_rent_by_type.csv")
        self.assertEqual({z: r[(z, "th2")]["status"] for z in ("00501", "00502", "10001", "10002", "20001")},
                         {"00501": "zip_no_benchmark", "00502": "ok", "10001": "ok", "10002": "zip_outlier",
                          "20001": "no_zori"})
        a = r[("00502", "th2")]
        self.assertEqual((a["base_source"], a["base_monthly"], a["base_ratio"], a["rent_monthly"]),
                         ("zori", "2500.00", "1.3333", "2500.00"))
        self.assertEqual(r[("00502", "th3")]["rent_monthly"], "3250.00")      # 2500 x 1.3, AA001's bedroom ratio
        self.assertEqual(r[("00502", "sfh3")]["rent_monthly"], "3575.00")     # 2500 x 1.1 x 1.3: AA001's factors
        b = r[("10001", "th2")]
        self.assertEqual((b["base_source"], b["base_monthly"]), ("safmr_scaled", "4088.89"))
        self.assertEqual(r[("10001", "sfh3")]["factor_source"], "national")   # AA002's factor source, carried
        self.assertEqual(r[("10002", "th2")]["rent_monthly"], "")
        man = json.loads((self.out / "zip_rent_by_type_manifest.json").read_text())
        self.assertEqual(man["coverage"]["base_source"], {"none": 3, "zori": 1, "safmr_scaled": 1})
        self.assertEqual((man["safmr_check"]["zips_with_both"], man["safmr_check"]["median_abs_pct_error"]), (1, 10.0))
        self.assertTrue(any("10001" in w for w in man["warnings"]))          # the ZORI it set aside
        self.assertIn("reproduces B29", man["model_identity"])
        self.assertIn("D36", man["decision"])

    def test_b33_stops_when_b29_is_from_another_b8(self) -> None:
        self.assertEqual(self.run_b29().returncode, 0)
        b29 = self.out / "mha_rent_by_type.csv"
        b29.write_text(b29.read_text().replace("2437.50", "2437.90"), encoding="utf-8")
        tht.write(self.out / "zip_safmr.csv", [["zip", "mha", "br2"]])
        p = tht.run("zip_rent_by_type.py", "--zip-zori", str(self.out / "zip_zori.csv"),
                    "--zori", str(self.out / "mha_zori.csv"), "--zip-safmr", str(self.out / "zip_safmr.csv"),
                    "--safmr", str(self.safmr), "--rent-by-type", str(b29),
                    "--crosswalk", str(self.crosswalk), "--out", str(self.out))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("does not reproduce B29", p.stderr)


class TestZipOwnership(tht.TestChain):
    def make_acs_fio(self) -> tuple[Path, Path]:
        import openpyxl
        acs = self.d / "acs.json"
        acs.write_text(json.dumps([["B25090_001E", "B25079_001E", "B01003_001E", "zip code tabulation area"],
                                   ["3000", "300000", "900", "00501"], ["-666666666", "1", "10", "10001"]]))
        wb = openpyxl.Workbook()
        wb.active.title = "Disclaimer & Background"
        ws = wb.create_sheet("Supporting Underlying Metrics")
        ws.append(["ZIP Code", "Year", "Policy Decile Grouping", "Claim Frequency", "Claim Severity", "Loss Ratio",
                   "Premiums Per Policy", "Nonrenewal Rate", "Nonpayment Cancellation Rate",
                   "Other than Nonpayment Cancellation Rate"])
        ws.append([501, 2022, 5, 0.03, 10000, 0.4, 1200, 0.01, 0.02, 0.01])
        fio = self.d / "fio.xlsx"
        wb.save(fio)
        return acs, fio

    def run_b34(self) -> subprocess.CompletedProcess:
        p = self.run_b30()
        self.assertEqual(p.returncode, 0, p.stderr)
        edit_zip_values(self.out / "zip_zhvi.csv", {"00502": None, "10002": "5000000.00"})
        acs, fio = self.make_acs_fio()
        return tht.run("zip_ownership_by_type.py", "--zip-zhvi", str(self.out / "zip_zhvi.csv"),
                       "--zhvi", str(self.out / "mha_zhvi.csv"),
                       "--own-by-type", str(self.out / "mha_ownership_by_type.csv"),
                       "--tax-insurance", str(self.taxins), "--acs", str(acs), "--fio", str(fio),
                       "--pmms", str(self.d / "PMMS_history.csv"), "--crosswalk", str(self.crosswalk),
                       "--out", str(self.out))

    def test_b34_every_case(self) -> None:
        p = self.run_b34()
        self.assertEqual(p.returncode, 0, p.stderr)
        r = rows(self.out / "zip_ownership_by_type.csv")
        b30 = tht.read(self.out / "mha_ownership_by_type.csv")
        self.assertEqual({z: r[(z, "th2")]["status"] for z in ("00501", "00502", "10001", "10002", "20001")},
                         {"00501": "ok", "00502": "zip_no_benchmark", "10001": "ok", "10002": "zip_outlier",
                          "20001": "piti_only_no_zori"})
        a = r[("00501", "sfh3")]
        # AA001's sfh3 value is 330k on a 300k median: 200k x 330/300 = 220k.
        self.assertEqual((a["zhvi_ratio"], a["home_value"]), ("0.6667", "220000.00"))
        self.assertEqual((a["tax_rate"], a["tax_source"], a["insurance_annual_usd"], a["insurance_source"]),
                         ("0.010000", "zip", "1200.00", "zip"))
        self.assertAlmostEqual(float(a["own_total_monthly"]) - float(a["own_housing_monthly"]), 536.25, delta=0.011)
        b = r[("10001", "th2")]                                              # ACS annotation code: the MHA's rate
        self.assertEqual((b["tax_source"], b["insurance_source"], b["tax_rate"]), ("mha", "state_fallback", "0.012000"))
        for t in tht.ht.TYPE_IDS:                                           # 20001 is AA003 at its own value
            self.assertEqual(r[("20001", t)]["home_value"], b30[("AA003", t)]["home_value"])
            self.assertAlmostEqual(float(r[("20001", t)]["own_housing_monthly"]),
                                   float(b30[("AA003", t)]["own_housing_monthly"]), delta=0.011)
            self.assertEqual(r[("20001", t)]["tax_source"], "state_fallback")
        man = json.loads((self.out / "zip_ownership_by_type_manifest.json").read_text())
        self.assertEqual((man["coverage"]["zips_tax_rate_from_zip"], man["coverage"]["zips_premium_from_zip"]), (1, 1))
        self.assertIn("reproduce B30", man["model_identity"])
        self.assertTrue(any("zip_outlier" in w for w in man["warnings"]))


# The two classes above reuse TestChain's fixture; its own tests run in test_home_types.py only.
for _cls in (TestZipRent, TestZipOwnership):
    for _name in dir(tht.TestChain):
        if _name.startswith("test_"):
            setattr(_cls, _name, None)


@unittest.skipUnless(shutil.which("tippecanoe"), "tippecanoe not installed")
class TestZipTiles(unittest.TestCase):
    def test_b35_tiles_only_real_mha_zips(self) -> None:
        import tempfile

        import geopandas as gpd
        from shapely.geometry import box
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            zctas = ["00501", "00502", "30001", "40001"]
            gpd.GeoDataFrame({"ZCTA5CE20": zctas}, geometry=[box(-100 + i, 30, -99.9 + i, 30.1) for i in range(4)],
                             crs="EPSG:4269").to_file(d / "zcta.geojson", driver="GeoJSON")
            cw = tht.write(d / "zip_mha.csv", [["zip", "mha", "mha_class"], ["00501", "AA001", "mha"],
                                               ["00502", "AA001", "mha"], ["00503", "AA001", "mha"],
                                               ["30001", "ZZ001", "ccg"]])
            out = d / "zipcodes_2026.pmtiles"
            p = subprocess.run([sys.executable, str(TILES), "--zcta", str(d / "zcta.geojson"), "--crosswalk", str(cw),
                                "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(out.read_bytes()[:7], b"PMTiles")
            with (d / "zipcodes_2026_features.csv").open(newline="") as fh:
                self.assertEqual(list(csv.reader(fh)), [["zip", "area"], ["00501", "AA001"], ["00502", "AA001"]])
            man = json.loads((d / "zipcodes_2026_manifest.json").read_text())
            self.assertEqual((man["node"], man["features"], man["zips_without_zcta"], man["minzoom"], man["layer"]),
                             ("B35", 2, 1, 6, "zips"))
            self.assertEqual(set(man["output_sha256"]), {out.name, "zipcodes_2026_features.csv"})


if __name__ == "__main__":
    unittest.main()
