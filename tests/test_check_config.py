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


if __name__ == "__main__":
    unittest.main()
