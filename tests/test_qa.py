"""
Tests for B23, the QA / validation report (pipeline/qa/qa_report.py).

    python -m unittest discover -s tests -v        (or: make test)

Builds the miniature handoff from test_handoff.py, adds the files the report
reads beyond the handoff (B1 crosswalk, B8 tables, B24 and B19 manifests), and
runs the report as `make qa` does, with the hash and git checks switched off
because the fixture lives outside the repository. Stdlib only.

ZORI in the fixture (B5 shares 0.85 and 0.80):
  CO001  ZIPs 80901 1800.00, 80902 1818.15, 80903 1900.00 -> median 1818.15 / 0.85 = 2139.00
  AK400  ZIP  99701 1920.00                              -> 1920.00 / 0.80 = 2400.00
E-5 rent adequacy: CO001 (2112 + 126) / 2139 = 1.0463 (surplus), AK400 2238 / 2400 = 0.9325 (short).
AK400 also carries the only insurance state fallback, so the third trace falls to
CO002, the PITI-only buy row (decision 2.4).
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_handoff as th  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "pipeline" / "qa" / "qa_report.py"
Y = th.YEAR


class QAFixture(th.Fixture):
    def setUp(self) -> None:
        super().setUp()
        d = self.data
        interim, bench = d / "interim" / f"bah_{Y}", d / "interim" / f"benchmarks_{Y}"
        th.write_csv(interim / "zip_mha.csv", ["zip", "mha", "mha_class"], [
            {"zip": z, "mha": m, "mha_class": k} for z, m, k in (
                ("80901", "CO001", "mha"), ("80902", "CO001", "mha"), ("80903", "CO001", "mha"),
                ("81001", "CO002", "mha"), ("99701", "AK400", "mha"), ("50001", "ZZ001", "ccg"))])
        th.write_csv(bench / "mha_zori.csv", ["mha", "zori_median", "rent_share", "zori_utilities_adjusted"], [
            {"mha": "AK400", "zori_median": "1920.00", "rent_share": "0.8000", "zori_utilities_adjusted": "2400.00"},
            {"mha": "CO001", "zori_median": "1818.15", "rent_share": "0.8500", "zori_utilities_adjusted": "2139.00"},
            {"mha": "CO002", "zori_median": "", "rent_share": "0.8000", "zori_utilities_adjusted": ""}])
        th.write_csv(bench / "zip_zori.csv", ["zip", "mha", "value", "months_used"], [
            {"zip": "80901", "mha": "CO001", "value": "1800.00", "months_used": 7},
            {"zip": "80902", "mha": "CO001", "value": "1818.15", "months_used": 7},
            {"zip": "80903", "mha": "CO001", "value": "1900.00", "months_used": 7},
            {"zip": "99701", "mha": "AK400", "value": "1920.00", "months_used": 7}])
        th.write_json(d / "interim" / f"context_{Y}" / "mha_density_manifest.json",
                      {"nodes": ["B24"], "mhas_with_data": 3, "mhas_without_data": [], "warnings": []})
        th.write_json(d / "interim" / f"spatial_{Y}" / "regression_manifest.json", {
            "nodes": ["B19"], "growth_window": {"zips_with_growth": 4, "mhas_with_growth": 2},
            "not_modelled": {"e5_dep": {"no_growth": 1}}, "warnings": ["e5_dep primary: VIF above 5 for ln_rent"],
            "headline": {"test": "e5_dep rent adequacy_gap", "n": 2, "model": "error", "choice_reason": "test",
                         "ols_r2": 0.5, "predictors": [{"predictor": "ln_rent", "b": -0.2, "p": 0.01,
                                                        "reading": "negative association, significant at 0.05",
                                                        "alternative": {"model": "ML_Lag", "b": -0.19, "p": 0.02,
                                                                        "reading": "x"},
                                                        "model_form_agrees": True}],
                         "ambiguous_form": {"aic": {"error": -10.0, "lag": -9.0}, "lower_aic": "error",
                                            "alternative_parameter": {"rho": 0.3},
                                            "alternative_residual_moran": {"I": 0.01, "p_sim": 0.4}},
                         "sample_selection": {"modelled": {"n": 2, "median_adequacy_gap": 0.15,
                                                           "median_ln_density": 5.2},
                                              "no_growth": {"n": 1, "median_adequacy_gap": 0.05,
                                                            "median_ln_density": 3.8},
                                              "eligible": 3, "mann_whitney_p": {"adequacy_gap": 0.001},
                                              "differs_at_alpha": ["adequacy_gap"]},
                         "growth_sensitivity": {"years": 3, "n": 3, "model": "lag", "ambiguous": False,
                                                "predictors": [{"predictor": "ln_rent", "reading": "y"}]}},
            "runs": [], "method": {"caveat": "shared denominator"}})

    def run_qa(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(QA), "--year", str(Y), "--handoff", str(self.out),
                               "--out", str(self.data / "processed" / "qa"), "--data", str(self.data),
                               "--no-verify", "--no-git", *extra], capture_output=True, text=True)

    def manifest(self) -> dict:
        return json.loads((self.data / "processed" / "qa" / f"qa_{Y}_manifest.json").read_text())


class TestQA(QAFixture):
    def test_passing_build(self) -> None:
        self.build()
        p = self.run_qa()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        man = self.manifest()
        self.assertEqual((man["nodes"], man["verdict"]), (["B23"], "PASS"))
        self.assertEqual([t["area"] for t in man["traces"]], ["CO001", "AK400", "CO002"])
        self.assertTrue(all(r["agree"] for t in man["traces"] for r in t["rows"]))
        self.assertEqual(man["traces"][0]["zori_median_recomputed"], 1818.15)
        self.assertEqual(man["areas_by_class"], {"mha": 3, "ccg": 1, "unknown": 1})
        self.assertEqual(man["status_counts"]["e5_dep"]["rent"], {"ok": 2, "no_zori": 1, "ccg_no_benchmark": 1,
                                                                   "no_rate": 1})
        self.assertEqual((man["codes_without_polygon"], man["rounding_class_differences"]), ([], []))
        self.assertEqual(set(man["files"]), {f"areas_{Y}.pmtiles", f"payload_{Y}.json", f"ui_metadata_{Y}.json",
                                             f"hotspots_{Y}.json", f"build_manifest_{Y}.json"})
        report = (self.data / "processed" / "qa" / f"qa_{Y}.md").read_text()
        for heading in ("## 0. Checks", "## 5. Classes changed by rounding", "## 9. Traces",
                        "## 10. ZORI against SAFMR", "## 12. Limitations"):
            self.assertIn(heading, report)
        self.assertIn("VIF above 5 for ln_rent", report)          # stage warnings are carried
        self.assertIn("**Model form ambiguous:**", report)
        self.assertIn("**Sample selection:** 2 of 3 eligible MHAs modelled", report)
        self.assertIn("**3-year growth sensitivity:** n = 3", report)
        notes = {c["check"]: c["result"] for c in man["checks"]}
        self.assertEqual((notes["B19: spatial model form"], notes["B19: sample selection"]), ("NOTE", "NOTE"))
        self.assertIn("Hand-check against the raw files", report)

    def test_value_at_a_break_is_reported(self) -> None:
        # O-3 rent design gap 49.60 rounds to 50 in B20: below the $50 break unrounded, on it rounded.
        path = self.data / "interim" / f"metrics_{Y}" / "mha_rent_metrics.csv"
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            if (r["profile"], r["mha"]) == ("o3_dep", "CO001"):
                r["design_gap_usd"] = "49.60"
        th.write_csv(path, th.RENT_FIELDS, rows)
        self.build()
        p = self.run_qa()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        diffs = self.manifest()["rounding_class_differences"]
        self.assertEqual([(x["area"], x["profile"], x["metric"], x["rounded"]) for x in diffs],
                         [("CO001", "o3_dep", "design_gap_usd", 50)])

    def test_nonconforming_handoff_fails_but_writes_the_report(self) -> None:
        self.build()
        pay = self.payload()
        pay["areas"]["CO001"]["e5_dep"]["rent"]["bah_monthly"] = 9999
        (self.out / f"payload_{Y}.json").write_text(json.dumps(pay))
        p = self.run_qa()
        self.assertEqual(p.returncode, 1)
        man = self.manifest()
        self.assertEqual(man["verdict"], "FAIL")
        failed = [c["check"] for c in man["checks"] if c["result"] == "FAIL"]
        self.assertIn("Contract checks 3-8 (validate_handoff.py)", failed)

    def test_unknown_trace_code_fails(self) -> None:
        self.build()
        p = self.run_qa("--trace", "CO001", "AK400", "QQ999")
        self.assertEqual(p.returncode, 1)
        self.assertIn("FAIL  Trace QQ999", p.stdout)


if __name__ == "__main__":
    unittest.main()
