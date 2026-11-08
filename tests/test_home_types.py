"""
Tests for the home-type benchmarks (D19, D34): B29 rent and B30 ownership cost by
home type, and the blend formula every stage and the map share (home_types.py).

D34 (7 Nov 2026): a Zillow type ratio compares typical homes of different sizes, so
it is size-matched before the bedroom ratio is applied, and buy mode treats the
all-homes value as the 3 BR home it measures as.

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
        self.assertEqual(ht.describe(ht.standard(cfg, "E5", True), labels), "a 2 BR townhouse")
        self.assertEqual(ht.describe(ht.standard(cfg, "O7", True), labels), "a 4 BR single-family home, plus 2%")


class TestMetroNames(unittest.TestCase):
    def test_principal_city_keys(self) -> None:
        import rent_by_type as rb
        self.assertEqual(rb.metro_key("Atlanta-Sandy Springs-Alpharetta, GA"), ("atlanta", "GA"))
        self.assertEqual(rb.metro_key("Washington-Arlington-Alexandria, DC-VA-MD-WV"), ("washington", "DC"))
        self.assertEqual(rb.metro_key("Louisville/Jefferson County, KY-IN"), ("louisville", "KY"))
        names = {"Atlanta-Sandy Springs-Alpharetta, GA", "Colorado Springs, CO", "Albany-Lebanon, OR",
                 "Albany-Schenectady-Troy, NY", "Alice, TX", "Portland-Vancouver-Hillsboro, OR-WA"}
        a15 = {"Atlanta, GA", "Colorado Springs, CO", "Albany, OR", "Albany, NY", "Portland, OR", "Portland, ME"}
        out, stats = rb.match_metros(names, a15)
        self.assertEqual(out["Atlanta-Sandy Springs-Alpharetta, GA"], "Atlanta, GA")
        self.assertEqual(out["Albany-Schenectady-Troy, NY"], "Albany, NY")       # the state decides
        self.assertEqual(out["Portland-Vancouver-Hillsboro, OR-WA"], "Portland, OR")
        self.assertEqual((stats["matched_exact"], stats["matched_by_principal_city"], stats["unmatched"]),
                         (1, 4, ["Alice, TX"]))
        _, amb = rb.match_metros({"Springfield-X, MA"}, {"Springfield, MA", "Springfield-Y, MA"})
        self.assertEqual(amb["ambiguous"], ["Springfield-X, MA"])               # never guessed


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
        # The ZIP files carry full census metro names; Alpha's matches A15 by principal city, Beta's exactly.
        metros = {"00501": "Alpha-Gamma-Delta, NY-NJ", "00502": "Alpha-Gamma-Delta, NY-NJ",
                  "10001": "Beta, NY", "10002": "Beta, NY"}
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
        # A15: MFR / all = 0.9 in both metros and nationally; SFR / all = 1.43 in Alpha, none in Beta,
        # 1.1 nationally. At equal bedrooms (D34, SFR series = 3 BR): Alpha 1.43 / 1.3 = 1.1, a 10% premium
        # over the townhouse; national 1.1 / 1.3 = 0.846, below the townhouse, so the floor sets it to 1.
        self.metro_all = metro_file(d / "Metro_all.csv", {"United States": 1800, "Alpha, NY": 2000, "Beta, NY": 3000})
        self.metro_mfr = metro_file(d / "Metro_mfr.csv", {"United States": 1620, "Alpha, NY": 1800, "Beta, NY": 2700})
        self.metro_sfr = metro_file(d / "Metro_sfr.csv", {"United States": 1980, "Alpha, NY": 2860})

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_b29(self, *extra: str) -> subprocess.CompletedProcess:
        return run("rent_by_type.py", "--zori", str(self.out / "mha_zori.csv"), "--safmr", str(self.safmr),
                   "--metro-sfr", str(self.metro_sfr), "--metro-mfr", str(self.metro_mfr),
                   "--metro-all", str(self.metro_all), "--zip-metro", str(self.zhvi_all),
                   "--crosswalk", str(self.crosswalk), "--out", str(self.out), *extra)

    def standards_with(self, **series) -> Path:
        cfg = json.loads(ht.STANDARDS.read_text(encoding="utf-8"))
        cfg["rent_type_series"].update(series)
        path = self.d / "housing_standards.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        return path

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
        # D34: Alpha's SFR ratio 1.43 is a typical (3 BR) house against a typical home, so it is
        # size-matched first: 1.43 / 1.3 = 1.1, then the bedrooms are added once.
        self.assertEqual((a["sfh3"]["building_factor"], a["sfh3"]["size_matched_factor"],
                          a["sfh3"]["applied_factor"], a["sfh3"]["floored"]), ("1.430000", "1.100000", "1.100000", "0"))
        self.assertEqual(a["sfh3"]["rent_monthly"], "2681.25")             # 1875 x 1.1 x 1.3 (was 1875 x 1.43 x 1.3)
        self.assertEqual(a["sfh4"]["rent_monthly"], "3093.75")             # 1875 x 1.1 x 1.5
        self.assertEqual(a["sfh3"]["utilities_usd"], "536.25")             # 375 x 1.1 x 1.3
        self.assertEqual(a["apt1"]["rent_monthly"], "1350.00")             # 1875 x 0.9 (Alpha MFR, a 2 BR series) x 0.8
        self.assertEqual(a["apt1"]["utilities_usd"], "270.00")             # 375 x 0.9 x 0.8
        self.assertEqual((a["sfh3"]["factor_source"], a["th3"]["factor_source"]), ("metro", "reference"))
        self.assertEqual(a["sfh3"]["series_bedrooms"], "3")
        b = {t: rows[("AA002", t)] for t in ht.TYPE_IDS}                    # Beta has no SFR series
        self.assertEqual((b["sfh3"]["factor_source"], b["sfh3"]["building_factor"]), ("national", "1.100000"))
        # National 1.1 / 1.3 = 0.846 is below the townhouse, so the floor holds it at the 3 BR townhouse.
        self.assertEqual((b["sfh3"]["size_matched_factor"], b["sfh3"]["applied_factor"], b["sfh3"]["floored"]),
                         ("0.846154", "1.000000", "1"))
        self.assertEqual(b["sfh3"]["rent_monthly"], b["th3"]["rent_monthly"])
        self.assertEqual(b["sfh3"]["rent_monthly"], "3986.67")             # 3066.67 x 1.3 (was 3066.67 x 1.1 x 1.3)
        for m in ("AA001", "AA002"):                                       # DoD's order holds in rent mode
            vals = [float(rows[(m, t)]["rent_monthly"]) for t in ("apt1", "apt2", "th2", "th3", "sfh3", "sfh4")]
            self.assertEqual(vals, sorted(vals), m)
        c = rows[("AA003", "apt2")]
        self.assertEqual((c["status"], c["rent_monthly"], c["factor_source"]), ("no_zori", "", "national"))
        man = json.loads((self.out / "mha_rent_by_type_manifest.json").read_text())
        self.assertEqual(man["building_factors"]["single_family"]["mhas_national_fallback"], 2)
        self.assertEqual(man["building_factors"]["single_family"]["mhas_floored_to_townhouse"], 1)   # Beta
        self.assertEqual(man["series_bedrooms"], {"townhouse": 2, "apartment": 2, "single_family": 3})
        self.assertIn("D34", man["decision"])
        self.assertEqual(man["metros"]["zip_metro_names_matched"], 2)
        self.assertEqual((man["metros"]["matching"]["matched_exact"],
                          man["metros"]["matching"]["matched_by_principal_city"]), (1, 1))
        self.assertEqual(set(man["inputs"]), {"B8", "B10", "A15.sfr", "A15.mfr", "A15.all", "A4", "B1", "A14"})

    def test_b29_without_the_floor_keeps_the_measured_factor(self) -> None:
        p = self.run_b29("--standards", str(self.standards_with(single_family_not_below_townhouse=False)))
        self.assertEqual(p.returncode, 0, p.stderr)
        b = read(self.out / "mha_rent_by_type.csv")[("AA002", "sfh3")]
        self.assertEqual((b["applied_factor"], b["floored"], b["rent_monthly"]), ("0.846154", "0", "3373.34"))

    def test_b29_stops_on_a_bad_series_size(self) -> None:
        p = self.run_b29("--standards", str(self.standards_with(single_family_bedrooms=7)))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("rent_type_series", p.stderr)

    def test_b29_stops_when_metro_names_do_not_match(self) -> None:
        metro_file(self.metro_all, {"United States": 1800, "Alpha-Town": 2000, "Beta-Town": 3000})
        p = self.run_b29()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("name metros differently", p.stderr)

    def run_b30(self, config: Path | None = None, condo: dict | None = None) -> subprocess.CompletedProcess:
        """B29, B11 and B30 on the fixture. A16 is built so each Zillow series sits at a realistic size:
        the all-homes value equals the 3 BR value ZIP by ZIP (as the 2026 data measure), single-family
        homes sit near 3 BR and condos near 2 BR."""
        self.assertEqual(self.run_b29().returncode, 0)
        d = self.d
        pmms = write(d / "PMMS_history.csv", [["date", "pmms30"], ["1/1/2026", "6.40"], ["1/8/2026", "6.60"],
                                               ["2/5/2026", "6.40"], ["3/5/2026", "6.60"]])
        self.taxins = taxins = write(d / "mha_tax_insurance.csv", [
            ["mha", "effective_tax_rate", "tax_source", "insurance_annual_usd", "insurance_source"],
            ["AA001", "0.008900", "locality", "1569.00", "locality"],
            ["AA002", "0.012000", "locality", "2000.00", "state_fallback"],
            ["AA003", "0.010000", "state_fallback", "1800.00", "locality"]])
        p = run("ownership_cost.py", "--zhvi", str(self.out / "mha_zhvi.csv"), "--zori", str(self.out / "mha_zori.csv"),
                "--pmms", str(pmms), "--tax-insurance", str(taxins), "--out", str(self.out))
        self.assertEqual(p.returncode, 0, p.stderr)
        # Bedrooms: 3 BR = the all-homes value; 2 BR = all / 1.25; 1 BR 0.8x and 4 BR 1.5x of 2 BR.
        # SFR / all per ZIP 1.05, 1.15 (AA001 median 1.10), 1.02, 0.98 (AA002 1.00); national 1.035.
        # Condo / all only in AA001's ZIPs: 0.8, 0.7 -> 0.75, also the national median.
        all_homes = {"00501": 200000, "00502": 400000, "10001": 500000, "10002": 300000}
        sfr = {"00501": 1.05, "00502": 1.15, "10001": 1.02, "10002": 0.98}
        a16 = {"sfr": {z: all_homes[z] * k for z, k in sfr.items()},
               "condo": condo or {"00501": 160000, "00502": 280000}}
        br2 = {z: v / 1.25 for z, v in all_homes.items()}
        for n, k in ((1, 0.8), (2, 1.0), (3, 1.25), (4, 1.5)):
            a16[f"br{n}"] = {z: v * k for z, v in br2.items()}
        files = {k: zip_file(d / f"Zip_zhvi_{k}.csv", v) for k, v in a16.items()}
        return run("ownership_by_type.py", "--zhvi", str(self.out / "mha_zhvi.csv"), "--zhvi-all", str(self.zhvi_all),
                   "--zhvi-sfr", str(files["sfr"]), "--zhvi-condo", str(files["condo"]),
                   *[x for n in (1, 2, 3, 4) for x in (f"--zhvi-br{n}", str(files[f"br{n}"]))],
                   "--crosswalk", str(self.crosswalk), "--rent-by-type", str(self.out / "mha_rent_by_type.csv"),
                   "--tax-insurance", str(taxins), "--pmms", str(pmms), "--ownership", str(self.out / "mha_ownership.csv"),
                   "--out", str(self.out), *(["--config", str(config)] if config else []))

    def test_b30_ownership_by_type(self) -> None:
        p = self.run_b30()
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = read(self.out / "mha_ownership_by_type.csv")
        b11 = {m: r for (m, _), r in read(self.out / "mha_ownership.csv").items()}
        a = {t: rows[("AA001", t)] for t in ht.TYPE_IDS}
        # D34: the all-homes value (300k) is a 3 BR home. At equal bedrooms the condo factor is
        # 0.75 x 1.25 = 0.9375 (a 2 BR series against a 3 BR base), single-family 1.10 (both 3 BR),
        # and the townhouse halfway between them (D22): 0.9375 + 0.5 x 0.1625 = 1.01875.
        self.assertEqual((a["apt2"]["building_factor"], a["apt2"]["zillow_type_ratio"]), ("0.937500", "0.750000"))
        self.assertEqual((a["sfh3"]["building_factor"], a["sfh3"]["zillow_type_ratio"]), ("1.100000", "1.100000"))
        self.assertEqual((a["th2"]["building_factor"], a["th2"]["zillow_type_ratio"]), ("1.018750", ""))
        expected = {"apt1": "180000.00",    # 300k x 0.9375 x 0.8 / 1.25: the condo value at 1 BR, as before
                    "apt2": "225000.00",    # 300k x 0.9375 / 1.25 = the typical condo, as before
                    "th2": "244500.00",     # 300k x 1.01875 / 1.25
                    "th3": "305625.00",     # 300k x 1.01875
                    "sfh3": "330000.00",    # 300k x 1.10: the typical single-family home (was 300k x 1.25 x 1.25)
                    "sfh4": "396000.00"}    # 300k x 1.10 x 1.5 / 1.25
        self.assertEqual({t: a[t]["home_value"] for t in expected}, expected)
        self.assertEqual((a["sfh3"]["bedroom_ratio"], a["sfh3"]["bedroom_source"]), ("1.000000", "reference"))
        self.assertEqual((a["th2"]["bedroom_ratio"], a["th2"]["bedroom_source"]), ("0.800000", "zip"))
        self.assertEqual(a["sfh3"]["tax_monthly"], "244.75")               # 330,000 x 0.89% / 12
        self.assertEqual(a["sfh3"]["insurance_monthly"], "130.75")         # same premium for every type
        total = float(a["sfh3"]["own_housing_monthly"]) + 536.25            # B29 sfh3 utilities (D34)
        self.assertAlmostEqual(float(a["sfh3"]["own_total_monthly"]), total, delta=0.011)
        # The 2 BR townhouse is no longer the all-homes value; B11 still is (model identity, checked inside).
        self.assertLess(float(a["th2"]["own_housing_monthly"]), float(b11["AA001"]["own_housing_monthly"]))
        for m in ("AA001", "AA002", "AA003"):                               # DoD's order holds in buy mode
            vals = [float(rows[(m, t)]["home_value"]) for t in ("apt1", "apt2", "th2", "th3", "sfh3", "sfh4")]
            self.assertEqual(vals, sorted(vals), m)
        # AA002: condo on the national 0.75 -> 0.9375; single-family 1.00; townhouse 0.96875 on 400k.
        b = {t: rows[("AA002", t)] for t in ht.TYPE_IDS}
        self.assertEqual((b["apt2"]["building_source"], b["apt2"]["building_factor"]), ("national", "0.937500"))
        self.assertEqual((b["th2"]["building_factor"], b["th2"]["building_source"], b["th2"]["home_value"]),
                         ("0.968750", "national", "310000.00"))
        self.assertEqual(b["sfh3"]["home_value"], "400000.00")
        # AA003: no A16 ZIPs, no ZORI; every ratio national. SFR 1.035 (median of four ZIPs) on 150k.
        c = {t: rows[("AA003", t)] for t in ht.TYPE_IDS}
        self.assertEqual((c["sfh3"]["building_source"], c["sfh3"]["bedroom_source"], c["sfh3"]["status"]),
                         ("national", "reference", "piti_only_no_zori"))
        self.assertEqual(c["sfh3"]["home_value"], "155250.00")
        self.assertEqual((c["th2"]["bedroom_source"], c["th2"]["home_value"]), ("national", "118350.00"))
        man = json.loads((self.out / "mha_ownership_by_type_manifest.json").read_text())
        self.assertEqual(man["ratios"]["building_apartment"]["mhas_national_fallback"], 2)
        self.assertEqual(man["ratios"]["building_townhouse"]["mhas_national_fallback"], 2)
        self.assertEqual(man["ratios"]["building_townhouse"]["townhouse_position"], 0.5)
        self.assertIn("reproduces B11", man["model_identity"])
        self.assertIn("D34", man["decision"])
        self.assertEqual(man["series_bedrooms"], {"all_homes": 3, "condo": 2, "single_family": 3})
        self.assertEqual(man["coverage"]["sfh4"]["status"], {"ok": 2, "piti_only_no_zori": 1, "no_home_value": 0})
        self.assertEqual(man["reference_check"]["all_homes_over_2br"]["median"], 1.25)
        self.assertEqual(man["reference_check"]["all_homes_over_3br"]["median"], 1.0)
        self.assertEqual({k: v["nearest_bedrooms"] for k, v in man["reference_check"]["series"].items()},
                         {"all_homes": 3, "condo": 2, "single_family": 3})

    def test_b30_keeps_dod_order_where_condos_cost_more(self) -> None:
        # AA002 gains condo ZIPs at 0.85 x all homes: at equal bedrooms 0.85 x 1.25 = 1.0625, above its
        # single-family factor 1.00. The single-family factor is raised to 1.0625, and the townhouse
        # midpoint lands there too, so a 2 BR apartment, townhouse and (scaled) house share one level.
        condo = {"00501": 160000, "00502": 280000, "10001": 425000, "10002": 255000}
        p = self.run_b30(condo=condo)
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = read(self.out / "mha_ownership_by_type.csv")
        b = {t: rows[("AA002", t)] for t in ht.TYPE_IDS}
        self.assertEqual({t: b[t]["building_factor"] for t in ("apt2", "th2", "sfh3")},
                         {"apt2": "1.062500", "th2": "1.062500", "sfh3": "1.062500"})
        self.assertEqual((b["apt2"]["floored"], b["th2"]["floored"], b["sfh3"]["floored"]), ("0", "1", "1"))
        self.assertEqual((b["apt2"]["home_value"], b["th2"]["home_value"], b["sfh3"]["home_value"]),
                         ("340000.00", "340000.00", "425000.00"))      # 400k x 1.0625 / 1.25; 400k x 1.0625
        self.assertEqual(rows[("AA001", "sfh3")]["floored"], "0")
        for m in ("AA001", "AA002", "AA003"):
            vals = [float(rows[(m, t)]["home_value"]) for t in ("apt1", "apt2", "th2", "th3", "sfh3", "sfh4")]
            self.assertEqual(vals, sorted(vals), m)
        man = json.loads((self.out / "mha_ownership_by_type_manifest.json").read_text())
        th = man["ratios"]["building_townhouse"]
        self.assertEqual((th["mhas_condo_above_single_family"], th["mhas_floored_to_condo"]), (1, 1))
        self.assertTrue(man["keep_dod_order"])
        self.assertFalse(any("not between the two" in w for w in man["warnings"]))

    def test_b30_stops_when_a_series_size_is_misconfigured(self) -> None:
        cfg = json.loads((ROOT / "config" / "ownership.json").read_text(encoding="utf-8"))
        cfg["home_types"]["all_homes_bedrooms"] = 2                         # the pre-D34 assumption
        path = self.d / "ownership.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        p = self.run_b30(path)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("all_homes: configured 2 BR, the data sit nearest 3 BR", p.stderr)

if __name__ == "__main__":
    unittest.main()
