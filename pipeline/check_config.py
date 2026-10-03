#!/usr/bin/env python3
"""Validate the project-authored config nodes A12 and A13 (stdlib only).

    python pipeline/check_config.py            # checks config/profiles.json + config/classification.json

Fails loudly (exit 1) on anything Layer 2 or Layer 3 would trip over later:
unknown pay grades, bedroom counts outside the SAFMR range, break lists that are
not ascending, colour/label counts that do not match the class count, invalid
hex colours, a neutral value outside the middle class, or the two files
disagreeing on the coverage target.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "config" / "profiles.json"
CLASSIFICATION = ROOT / "config" / "classification.json"
BAH_INGEST = ROOT / "pipeline" / "ingest" / "ingest_bah_ascii.py"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
SAFMR_BEDROOMS = range(0, 5)   # HUD publishes 0-4 bedroom SAFMRs


def pay_grades() -> list[str]:
    """Read PAY_GRADES from the BAH ingest script so the two never drift apart."""
    tree = ast.parse(BAH_INGEST.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "PAY_GRADES" for t in node.targets):
            return list(ast.literal_eval(node.value))
    sys.exit(f"check_config: PAY_GRADES not found in {BAH_INGEST}")
    raise AssertionError


def load(path: Path, errors: list[str]) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"{path.relative_to(ROOT)} is missing")
    except json.JSONDecodeError as e:
        errors.append(f"{path.relative_to(ROOT)} is not valid JSON: {e}")
    return {}


def check_profiles(cfg: dict, grades: list[str], errors: list[str]) -> None:
    profiles = cfg.get("profiles") or []
    if not profiles:
        errors.append("profiles.json: no profiles defined")
        return
    ids = [p.get("id") for p in profiles]
    if len(set(ids)) != len(ids):
        errors.append(f"profiles.json: duplicate profile ids {ids}")
    if cfg.get("default_profile") not in ids:
        errors.append(f"profiles.json: default_profile '{cfg.get('default_profile')}' is not a profile id")
    primaries = [p["id"] for p in profiles if p.get("role") == "primary"]
    if len(primaries) != 1:
        errors.append(f"profiles.json: need exactly one primary profile, found {primaries}")
    for p in profiles:
        pid = p.get("id", "?")
        if p.get("pay_grade") not in grades:
            errors.append(f"profiles.json [{pid}]: pay_grade '{p.get('pay_grade')}' not in BAH grades {grades}")
        if not isinstance(p.get("has_dependents"), bool):
            errors.append(f"profiles.json [{pid}]: has_dependents must be true or false")
        beds = p.get("anchor_bedrooms")
        if not isinstance(beds, int) or beds not in SAFMR_BEDROOMS:
            errors.append(f"profiles.json [{pid}]: anchor_bedrooms must be an integer 0-4 (SAFMR range)")
        for key in ("label", "anchor_dwelling"):
            if not p.get(key):
                errors.append(f"profiles.json [{pid}]: missing {key}")
    target = cfg.get("coverage_target")
    if not isinstance(target, (int, float)) or not 0 < target <= 1:
        errors.append("profiles.json: coverage_target must be a number in (0, 1]")


def check_classification(cfg: dict, target: float | None, errors: list[str]) -> None:
    if not HEX.match(cfg.get("no_data_color", "")):
        errors.append("classification.json: no_data_color must be #RRGGBB")
    if target is not None and cfg.get("coverage_target") != target:
        errors.append(f"classification.json coverage_target {cfg.get('coverage_target')} "
                      f"!= profiles.json {target}")
    metrics = cfg.get("metrics") or {}
    if not metrics:
        errors.append("classification.json: no metrics defined")
    for name, m in metrics.items():
        where = f"classification.json [{name}]"
        breaks, colors, labels = m.get("breaks", []), m.get("colors", []), m.get("class_labels", [])
        if any(b2 <= b1 for b1, b2 in zip(breaks, breaks[1:])):
            errors.append(f"{where}: breaks must be strictly ascending: {breaks}")
        if len(colors) != len(breaks) + 1:
            errors.append(f"{where}: {len(breaks)} breaks need {len(breaks) + 1} colours, found {len(colors)}")
        if len(labels) != len(colors):
            errors.append(f"{where}: {len(colors)} colours but {len(labels)} class labels")
        bad = [c for c in colors if not HEX.match(c)]
        if bad:
            errors.append(f"{where}: invalid colours {bad}")
        neutral = m.get("neutral")
        if neutral is not None and breaks and len(breaks) % 2 == 0:
            mid = len(breaks) // 2
            lo, hi = breaks[mid - 1], breaks[mid]
            if not lo <= neutral < hi:
                errors.append(f"{where}: neutral {neutral} is outside the middle class [{lo}, {hi})")
    for code, c in ((cfg.get("clusters") or {}).get("classes") or {}).items():
        if not HEX.match(c.get("color", "")):
            errors.append(f"classification.json [clusters.{code}]: invalid colour {c.get('color')}")


def main() -> None:
    errors: list[str] = []
    profiles = load(PROFILES, errors)
    classification = load(CLASSIFICATION, errors)
    if profiles:
        check_profiles(profiles, pay_grades(), errors)
    if classification:
        check_classification(classification, profiles.get("coverage_target") if profiles else None, errors)
    if errors:
        print("Config check FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    names = ", ".join(f"{p['id']} ({p['pay_grade']}, {p['anchor_bedrooms']}BR)" for p in profiles["profiles"])
    print(f"A12 profiles OK: {names}")
    print(f"A13 classification OK: {', '.join(classification['metrics'])}; "
          f"{len(classification.get('clusters', {}).get('classes', {}))} cluster classes")


if __name__ == "__main__":
    main()
