"""Tests for the two ingest translators on synthetic releases (no downloads).

  B1-B4  pipeline/ingest/ingest_bah_ascii.py        the DTMO BAH ASCII zip
  B5     pipeline/ingest/ingest_rate_components.py  the rate component breakdown

The rate files are the point of the first group. A release with a pay grade added or
removed must stop the run: fitted to the 27 known grades it would put every rate under
the wrong grade, or blank the last one, and nothing later would notice.
"""
from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "ingest"))
import ingest_bah_ascii as bah  # noqa: E402
import ingest_rate_components as rc  # noqa: E402

GRADES = len(bah.PAY_GRADES)


def rate_line(code: str, grades: int = GRADES, start: int = 1000) -> str:
    return ",".join([code, *[str(start + 10 * i) for i in range(grades)]])


def release(path: Path, with_deps: str, without: str, yy: str = "26", rates_yy: str | None = None) -> Path:
    """A minimal BAH-ASCII zip: two MHAs, one County Cost Group and the territory bucket."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"sorted_zipmha{yy}.txt", "00501 AA001\r\n00502 AA001\r\n10001 AA002\r\n30001 ZZ001\r\n00901 XX001\r\n")
        zf.writestr(f"mhanames{yy}.txt", "AA001;ALPHA, NY\r\nAA002;BETA, NY\r\nZZ001;COUNTY COST GROUP 001\r\nXX001;UNKNOWN, NA\r\n")
        zf.writestr(f"bahw{rates_yy or yy}.txt", with_deps)
        zf.writestr(f"bahwo{rates_yy or yy}.txt", without)
        zf.writestr(f"bahw{yy} - old.txt", "superseded")       # never read
    return path


class RateColumnsTest(unittest.TestCase):
    def test_the_published_layout_parses(self) -> None:
        long = bah.parse_rates(rate_line("AA001") + "\r\n" + rate_line("aa002", start=2000) + "\r\n", True)
        self.assertEqual(len(long), 2 * GRADES)
        e1 = long[(long["mha"] == "AA001") & (long["pay_grade"] == "E1")]["monthly_rate"].item()
        o10 = long[(long["mha"] == "AA002") & (long["pay_grade"] == "O10")]["monthly_rate"].item()
        self.assertEqual((e1, o10), (1000, 2000 + 10 * (GRADES - 1)))
        self.assertTrue(long["has_dependents"].all())

    def test_an_added_pay_grade_stops_the_run(self) -> None:
        # Before the fix this parsed without complaint: the codes became the row index and
        # the E-1 rate landed in the `mha` column.
        with self.assertRaises(SystemExit) as cm:
            bah.parse_rates(rate_line("AA001", GRADES + 1) + "\n", True)
        self.assertIn(f"{GRADES + 1} pay-grade columns", str(cm.exception))
        self.assertIn("update PAY_GRADES", str(cm.exception))

    def test_a_removed_pay_grade_stops_the_run(self) -> None:
        # Before the fix the last grade (O-10) was filled with blanks.
        with self.assertRaises(SystemExit) as cm:
            bah.parse_rates(rate_line("AA001", GRADES - 1) + "\n", False)
        self.assertIn(f"{GRADES - 1} pay-grade columns", str(cm.exception))

    def test_one_short_row_stops_the_run(self) -> None:
        text = rate_line("AA001") + "\n" + rate_line("AA002", GRADES - 2) + "\n"
        with self.assertRaises(SystemExit) as cm:
            bah.parse_rates(text, True)
        self.assertIn(f"{GRADES - 2}, {GRADES} pay-grade columns", str(cm.exception))


class ReleaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.rates = "".join(rate_line(c, start=s) + "\r\n" for c, s in (("AA001", 1000), ("AA002", 2000), ("ZZ001", 900)))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def ingest(self, zip_path: Path) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(ROOT / "pipeline" / "ingest" / "ingest_bah_ascii.py"),
                               "--zip", str(zip_path), "--out", str(self.dir / "out")], capture_output=True, text=True)

    def test_a_release_becomes_four_tables_and_a_manifest(self) -> None:
        p = self.ingest(release(self.dir / "BAH-ASCII-2026.zip", self.rates, self.rates))
        self.assertEqual(p.returncode, 0, p.stderr)
        out = self.dir / "out"
        m = json.loads((out / "manifest.json").read_text())
        self.assertEqual(m["source_year"], 2026)
        self.assertEqual(m["counts"]["zips_by_class"], {"mha": 3, "ccg": 1, "unknown": 1})
        self.assertEqual(m["counts"]["rate_rows"], 2 * 3 * GRADES)
        with (out / "zip_mha_geo.csv").open(newline="") as fh:
            self.assertEqual({r["mha"] for r in csv.DictReader(fh)}, {"AA001", "AA002"})    # real MHAs only
        with (out / "bah_rates.csv").open(newline="") as fh:
            rows = list(csv.DictReader(fh))
        e5 = [r for r in rows if (r["mha"], r["pay_grade"], r["has_dependents"]) == ("AA002", "E5", "True")]
        self.assertEqual([r["monthly_rate"] for r in e5], ["2040"])
        self.assertEqual(set(m["output_sha256"]), {"zip_mha.csv", "zip_mha_geo.csv", "mha_names.csv", "bah_rates.csv"})

    def test_a_release_with_a_grade_added_writes_nothing(self) -> None:
        wide = "".join(rate_line(c, GRADES + 1) + "\r\n" for c in ("AA001", "AA002", "ZZ001"))
        p = self.ingest(release(self.dir / "BAH-ASCII-2026.zip", wide, wide))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("update PAY_GRADES", p.stderr)
        self.assertFalse((self.dir / "out" / "bah_rates.csv").exists())

    def test_members_from_two_years_stop_the_run(self) -> None:
        p = self.ingest(release(self.dir / "BAH-ASCII-2026.zip", self.rates, self.rates, yy="26", rates_yy="25"))
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("different years", p.stderr)


class RateComponentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def components(self, text: str, expect: int) -> tuple[int, str]:
        src = self.dir / "components_2026.txt"
        src.write_text(text, encoding="utf-8")
        argv = ["ingest_rate_components.py", "--text", str(src), "--out", str(self.dir / "out"), "--expect", str(expect)]
        err = io.StringIO()
        with unittest.mock.patch.object(sys, "argv", argv), redirect_stderr(err), redirect_stdout(io.StringIO()):
            try:
                rc.main()
            except SystemExit as e:
                return (e.code if isinstance(e.code, int) else 1), err.getvalue() + str(e.code or "")
        return 0, err.getvalue()

    def test_shares_are_renormalised_to_one(self) -> None:
        code, _ = self.components("AK400 KETCHIKAN, AK 79% 21%\nAL001 ANNISTON, AL 80% 21%\n", 2)
        self.assertEqual(code, 0)
        with (self.dir / "out" / "rate_components.csv").open(newline="") as fh:
            rows = {r["mha"]: r for r in csv.DictReader(fh)}
        self.assertEqual((rows["AK400"]["rent_share"], rows["AK400"]["utilities_share"]), ("0.79", "0.21"))
        self.assertEqual(rows["AL001"]["rent_share"], "0.7921")          # 80 / 101: the source rounds to 1%

    def test_a_row_of_zero_percent_is_reported_not_a_crash(self) -> None:
        # 0% + 0% used to divide by zero before the validation could list the row.
        code, err = self.components("AK400 KETCHIKAN, AK 0% 0%\nAL001 ANNISTON, AL 80% 20%\n", 2)
        self.assertEqual(code, 1)
        self.assertIn("AK400: rent 0% + utilities 0% = 0%", err)
        self.assertNotIn("ZeroDivisionError", err)
        self.assertFalse((self.dir / "out" / "rate_components.csv").exists())


if __name__ == "__main__":
    unittest.main()
