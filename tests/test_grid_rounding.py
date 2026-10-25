"""
The grid formula (ICD 5b.4) against the research-profile path, value by value.

B20's numbers for a research profile pass through three steps: home_types.blend()
gives the standard's cost, coverage_metrics.metrics() writes the metrics to the
B12-B15 tables (cents, 4-decimal ratios), and build_payload rounds those to the
contract (whole dollars). The map computes the same view from B31 in one step
(contract.grid_view). B23 requires the two to agree exactly, so this test drives
both with many random standards and costs, including blends that land on a
fraction of a cent, and compares every field. Stdlib only.

    python -m unittest tests.test_grid_rounding
"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "handoff"))
sys.path.insert(0, str(ROOT / "pipeline" / "benchmarks"))
sys.path.insert(0, str(ROOT / "pipeline" / "metrics"))
import contract as c  # noqa: E402
import coverage_metrics as cm  # noqa: E402
import home_types as ht  # noqa: E402

FIELDS = {"cost_monthly": "dollars", "adequacy_ratio": "ratio", "design_gap_usd": "dollars",
          "coverage_ratio": "ratio", "surplus_usd": "dollars"}


def pipeline_view(costs: dict[str, float], std: dict, bah: float, share: int) -> dict:
    """B12-B15 then B20: blend, write the metrics table's strings, round them per the contract."""
    cost = ht.blend(costs, std)
    row = {"cost_monthly": cm.agg.fmt(cost), **cm.metrics(bah, share, cost, 0.95)}
    return {f: (c.dollars(row[f]) if kind == "dollars" else c.ratio(row[f])) for f, kind in FIELDS.items()}


def grid_of(costs: dict[str, float], std: dict, bah: int, share: int) -> dict:
    """A one-area, one-rank B31 holding these costs."""
    return {"ranks": ["X"], "home_types": list(c.HOME_TYPES), "cost_share_monthly": {"with": [share]},
            "standards": {"with": [std]},
            "areas": {"AA001": {"class": "mha", "bah": {"with": [bah]},
                                "rent": {"cost": [costs[t] for t in c.HOME_TYPES], "status": ["ok"] * 6,
                                         "caveats": [[] for _ in c.HOME_TYPES]}}}}


class GridMatchesPipeline(unittest.TestCase):
    def check(self, costs: dict[str, float], std: dict, bah: int, share: int) -> None:
        want = pipeline_view(costs, std, float(bah), share)
        got = c.grid_view(grid_of(costs, std, bah, share), "AA001", "X", "with", c.STANDARD, "rent")
        self.assertEqual({f: got[f] for f in FIELDS}, want, (costs, std, bah, share))

    def test_half_cent_blend(self) -> None:
        # The NC178 case from the first real run, in miniature: a blend ending in half a cent.
        # 2500.00 + 0.98 x (3000.25 - 2500.00) = 2990.245
        costs = dict(zip(c.HOME_TYPES, [1500.0, 1800.0, 2100.0, 2500.0, 3000.25, 3500.0]))
        self.check(costs, {"lower": "th3", "upper": "sfh3", "share": 0.98}, 2869, 151)

    def test_exact_binary_ties_round_away_from_zero(self) -> None:
        # A 50% blend of $612.50 and $613.75 is exactly $613.125 in binary: half away from zero gives $613.13
        # (Python's round() would give $613.12, toward the even digit).
        costs = dict(zip(c.HOME_TYPES, [500.0, 612.5, 613.75, 900.0, 1000.0, 1100.0]))
        cell = {"lower": "apt2", "upper": "th2", "share": 0.5}
        self.assertEqual(ht.blend(costs, cell), 613.13)
        self.check(costs, cell, 2273, 143)
        # A ratio exactly dyadic at the fifth decimal: (3,174 + 126) / 3,200 = 1.03125 -> 1.0313
        costs = dict(zip(c.HOME_TYPES, [2000.0, 2500.0, 3200.0, 3600.0, 4000.0, 4400.0]))
        self.check(costs, {"lower": "th2", "upper": None, "share": 0}, 3174, 126)
        self.assertEqual(cm.metrics(3174.0, 126, 3200.0, 0.95)["adequacy_ratio"], "1.0313")

    def test_random_standards_and_costs(self) -> None:
        rng = random.Random(2026)
        cfg = ht.load()
        cells = [cfg["standards"][g][d] for g in cfg["grades"] for d in ("with", "without")]
        for _ in range(20000):
            base = rng.randint(60000, 600000) / 100
            costs = {t: round(base * f * rng.uniform(0.97, 1.03), 2)
                     for t, f in zip(c.HOME_TYPES, (0.75, 0.9, 1.0, 1.3, 1.55, 1.8))}
            self.check(costs, rng.choice(cells), rng.randint(500, 6000), rng.randint(90, 215))

    def test_anchor_costs_pass_through_unchanged(self) -> None:
        # D19: E-5's standard is the 2 BR townhouse, so its cost is B8/B11 exactly, never re-rounded.
        for v in (1960.0, 2139.0, 3066.67, 0.01, 12345.67):
            self.assertEqual(ht.blend({"th2": v}, {"lower": "th2", "upper": None, "share": 0}), v)


if __name__ == "__main__":
    unittest.main()
