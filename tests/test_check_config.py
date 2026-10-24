"""Tests for pipeline/check_config.py: the repo's configs pass, and prose is kept out of them."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import check_config as cc  # noqa: E402


class CheckConfigTest(unittest.TestCase):
    def load(self, name: str) -> dict:
        return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))

    def test_repository_configs_pass(self):
        errors: list[str] = []
        profiles, classification = self.load("profiles.json"), self.load("classification.json")
        for cfg, name in ((profiles, "profiles.json"), (classification, "classification.json")):
            cc.check_values_only(cfg, name, errors)
            cc.check_doc_pointer(cfg, name, errors)
        cc.check_profiles(profiles, cc.pay_grades(), errors)
        cc.check_classification(classification, profiles["coverage_target"], errors)
        self.assertEqual(errors, [])

    def test_prose_fields_are_rejected(self):
        errors: list[str] = []
        cc.check_values_only({"metrics": {"x": {"note": "why"}}, "rationale": "why",
                              "profiles": [{"coverage_target_note": "why"}]}, "t.json", errors)
        self.assertEqual(len(errors), 3)

    def test_cluster_block_needs_legend_title_and_fdr_marker(self):
        cfg = self.load("classification.json")
        del cfg["clusters"]["legend_title"]
        del cfg["clusters"]["fdr_marker"]
        errors: list[str] = []
        cc.check_classification(cfg, 0.95, errors)
        self.assertEqual(len(errors), 2)

    def test_metric_needs_known_role_and_modes(self):
        cfg = self.load("classification.json")
        cfg["metrics"]["flat95_gap"]["role"] = "headline"
        cfg["metrics"]["safmr_adequacy_ratio"]["modes"] = ["lease"]
        errors: list[str] = []
        cc.check_classification(cfg, 0.95, errors)
        self.assertEqual(len(errors), 2)

    def test_housing_standards_pass_and_agree_with_profiles(self):
        errors: list[str] = []
        cfg = self.load("housing_standards.json")
        cc.check_values_only(cfg, "housing_standards.json", errors)
        cc.check_doc_pointer(cfg, "housing_standards.json", errors)
        cc.check_standards(cfg, cc.pay_grades(), self.load("profiles.json"), errors)
        self.assertEqual(errors, [])
        # D19: the O-3 contrast standard is 98% of the way from a 3 BR townhouse to a 3 BR single-family home
        self.assertEqual(cfg["standards"]["O3"]["with"], {"lower": "th3", "upper": "sfh3", "share": 0.98})
        self.assertEqual(cfg["standards"]["E5"]["with"], {"lower": "th2", "upper": None, "share": 0})

    def test_housing_standards_reject_bad_cells(self):
        cfg = self.load("housing_standards.json")
        cfg["standards"]["E7"]["with"] = {"lower": "sfh3", "upper": "th3", "share": 0.36}   # upper before lower
        cfg["standards"]["W2"]["without"]["share"] = 1.2
        cfg["cost_share_monthly"]["O9"]["with"] = 999                                      # derived from O7
        del cfg["standards"]["O4"]["without"]
        errors: list[str] = []
        cc.check_standards(cfg, cc.pay_grades(), {}, errors)
        self.assertEqual(len(errors), 4, errors)

    def test_profile_cost_share_must_match_a14(self):
        profiles = self.load("profiles.json")
        profiles["profiles"][1]["cost_share_monthly"] = 150
        errors: list[str] = []
        cc.check_standards(self.load("housing_standards.json"), cc.pay_grades(), profiles, errors)
        self.assertEqual(errors, ["profiles.json [o3_dep]: cost_share_monthly 150 != A14 O3 with 151"])


if __name__ == "__main__":
    unittest.main()
