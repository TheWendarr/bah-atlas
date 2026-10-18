#!/usr/bin/env python3
"""Validate the project-authored config nodes A12 and A13, and the B11 config (stdlib only).

    python pipeline/check_config.py            # checks config/profiles.json, config/classification.json
                                               # and config/ownership.json

Fails loudly (exit 1) on anything Layer 2 or Layer 3 would trip over later:
unknown pay grades, bedroom counts outside the SAFMR range, a missing or
uncited member cost share (cost_share_monthly), break lists that are
not ascending, colour/label counts that do not match the class count, invalid
hex colours, a neutral value outside the middle class, the two files
disagreeing on the coverage target, a metric without a role or with an unknown
mode, or a cluster block without its legend title and FDR marker.

All three files hold values only (ownership.json's values themselves are
validated by ownership_cost.py, which reads it). Explanations live in docs/configuration.md,
because pipeline stages record each config's SHA-256 and a wording edit inside
the JSON would make that evidence stale. So this check also fails on prose
fields (`_about`, `rationale`, `note`, `*_note`) and on a missing `_doc` pointer.
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
OWNERSHIP = ROOT / "config" / "ownership.json"
UI_TEXT = ROOT / "config" / "ui_text.json"
BAH_INGEST = ROOT / "pipeline" / "ingest" / "ingest_bah_ascii.py"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
SAFMR_BEDROOMS = range(0, 5)   # HUD publishes 0-4 bedroom SAFMRs
CONFIG_DOC = ROOT / "docs" / "configuration.md"
METRIC_ROLES = ("primary", "descriptive", "sensitivity")
MODES = ("rent", "buy")
CLUSTER_CODES = ("HH", "LL", "HL", "LH", "NS")


def check_values_only(cfg: object, name: str, errors: list[str], path: str = "") -> None:
    """Explanations belong in docs/configuration.md, not in the hashed config."""
    if isinstance(cfg, dict):
        for key, value in cfg.items():
            where = f"{path}{key}"
            if key in ("_about", "rationale", "note") or key.endswith("_note"):
                errors.append(f"{name}: '{where}' is explanation; move it to docs/configuration.md")
            check_values_only(value, name, errors, f"{where}.")
    elif isinstance(cfg, list):
        for i, value in enumerate(cfg):
            check_values_only(value, name, errors, f"{path}{i}.")


def check_doc_pointer(cfg: dict, name: str, errors: list[str]) -> None:
    doc = cfg.get("_doc", "")
    if "docs/configuration.md" not in doc:
        errors.append(f"{name}: '_doc' must point to docs/configuration.md")
    elif not CONFIG_DOC.exists():
        errors.append(f"{name}: '_doc' points to docs/configuration.md, which is missing")


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
        share = p.get("cost_share_monthly")
        if not isinstance(share, (int, float)) or isinstance(share, bool) or not 0 < share < 1000:
            errors.append(f"profiles.json [{pid}]: cost_share_monthly must be the DTMO out-of-pocket dollars "
                          f"for this cell (0 < x < 1000), found {share!r}")
    cs = cfg.get("cost_share") or {}
    for key in ("source", "url", "sha256"):
        if not cs.get(key):
            errors.append(f"profiles.json: cost_share.{key} is required (cite where the dollars come from)")
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
        if m.get("role") not in METRIC_ROLES:
            errors.append(f"{where}: role must be one of {METRIC_ROLES}, found {m.get('role')!r}")
        modes = m.get("modes")
        if not isinstance(modes, list) or not modes or any(x not in MODES for x in modes):
            errors.append(f"{where}: modes must be a non-empty list drawn from {MODES}, found {modes!r}")
    if cfg.get("default_metric") not in metrics:
        errors.append(f"classification.json: default_metric '{cfg.get('default_metric')}' is not a metric")
    clusters = cfg.get("clusters") or {}
    classes = clusters.get("classes") or {}
    missing = [c for c in CLUSTER_CODES if c not in classes]
    if missing:
        errors.append(f"classification.json [clusters]: classes lacks {missing}")
    for code, c in classes.items():
        if not HEX.match(c.get("color", "")):
            errors.append(f"classification.json [clusters.{code}]: invalid colour {c.get('color')}")
        if not c.get("label"):
            errors.append(f"classification.json [clusters.{code}]: missing label")
    if not clusters.get("legend_title"):
        errors.append("classification.json [clusters]: legend_title is required (decision D2: label clusters exploratory)")
    alpha = clusters.get("alpha")
    if not isinstance(alpha, (int, float)) or not 0 < alpha < 1:
        errors.append(f"classification.json [clusters]: alpha must be in (0, 1), found {alpha!r}")
    marker = clusters.get("fdr_marker") or {}
    if not marker.get("label") or not HEX.match(marker.get("outline_color", "")):
        errors.append("classification.json [clusters.fdr_marker]: needs a label and a #RRGGBB outline_color "
                      "(decision D2: mark FDR-significant MHAs)")


def main() -> None:
    errors: list[str] = []
    profiles = load(PROFILES, errors)
    classification = load(CLASSIFICATION, errors)
    ownership = load(OWNERSHIP, errors)
    ui_text = load(UI_TEXT, errors)
    for cfg, name in ((profiles, "profiles.json"), (classification, "classification.json"),
                      (ownership, "ownership.json"), (ui_text, "ui_text.json")):
        if cfg:
            check_values_only(cfg, name, errors)
            check_doc_pointer(cfg, name, errors)
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
    print("B11 ownership.json OK: values only, documented in docs/configuration.md")
    print("A13 ui_text.json OK: documented in docs/configuration.md (B21 checks it against the data contract)")


if __name__ == "__main__":
    main()
