"""
home_types.py — the six DoD housing profiles (A14) and the one formula that blends them.

Shared by B29 (rent by home type), B30 (ownership cost by home type), B12-B15
(each research profile's benchmark is its DoD standard) and B23. The map uses the
same formula, written out in the data contract (ICD section 5b), so the pipeline
and the browser cannot disagree about what a grade's standard costs.

    standard cost = cost(lower)                                  anchor (upper null, share 0)
                  = cost(lower) + share x (cost(upper) - cost(lower))   interpolated
                  = cost(lower) x (1 + share)                    above the highest profile

A null cost on either side makes the standard null. Stdlib only.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDARDS = ROOT / "config" / "housing_standards.json"
TYPE_IDS = ("apt1", "apt2", "th2", "th3", "sfh3", "sfh4")
REFERENCE = "th2"     # the dwelling B8 and B9 stand for (D19)


def load(path: Path = STANDARDS) -> dict:
    """A14, with the minimum shape every reader relies on (make check-config does the full check)."""
    cfg = json.loads(path.read_text(encoding="utf-8"))
    types = [t["id"] for t in cfg.get("home_types", [])]
    if tuple(types) != TYPE_IDS or cfg.get("reference_type") != REFERENCE:
        raise SystemExit(f"{path.name}: home_types must be {list(TYPE_IDS)} with reference_type {REFERENCE} "
                         "(run `make check-config`)")
    return cfg


def types(cfg: dict) -> list[dict]:
    return list(cfg["home_types"])


def standard(cfg: dict, grade: str, has_dependents: bool) -> dict:
    return cfg["standards"][grade.upper()]["with" if has_dependents else "without"]


def blend(costs: dict[str, float | None], cell: dict) -> float | None:
    """Cost of a standard from the six home-type costs of one area."""
    lo = costs.get(cell["lower"])
    if lo is None:
        return None
    if cell["upper"] is None:
        return lo * (1 + cell["share"])
    up = costs.get(cell["upper"])
    if up is None:
        return None
    return lo + cell["share"] * (up - lo)


def describe(cell: dict, labels: dict[str, str]) -> str:
    """Plain-language statement of a standard, for the map's notice (C25)."""
    lo = labels[cell["lower"]]
    if cell["upper"] is None and not cell["share"]:
        return f"a {lo}"
    if cell["upper"] is None:
        return f"a {lo}, plus {cell['share']:.0%}"
    return f"{cell['share']:.0%} of the way from a {lo} to a {labels[cell['upper']]}"
