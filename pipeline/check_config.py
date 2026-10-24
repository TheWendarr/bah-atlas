#!/usr/bin/env python3
"""Validate the project-authored config nodes A12, A13 and A14, and the B11 config (stdlib only).

    python pipeline/check_config.py            # checks config/profiles.json, config/classification.json,
                                               # config/housing_standards.json and config/ownership.json

Fails loudly (exit 1) on anything Layer 2 or Layer 3 would trip over later:
unknown pay grades, bedroom counts outside the SAFMR range, a missing or
uncited member cost share (cost_share_monthly), break lists that are
not ascending, colour/label counts that do not match the class count, invalid
hex colours, a neutral value outside the middle class, the two files
disagreeing on the coverage target, a metric without a role or with an unknown
mode, or a cluster block without its legend title and FDR marker. For A14 (D18): the
six home types, a standard for every dropdown grade with and without dependents
that names known types in cost order, a cost share for every cell, and A12's
research profiles agreeing with A14 on their cost share.

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
STANDARDS = ROOT / "config" / "housing_standards.json"
BAH_INGEST = ROOT / "pipeline" / "ingest" / "ingest_bah_ascii.py"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
SAFMR_BEDROOMS = range(0, 5)   # HUD publishes 0-4 bedroom SAFMRs
CONFIG_DOC = ROOT / "docs" / "configuration.md"
METRIC_ROLES = ("primary", "descriptive", "sensitivity")
MODES = ("rent", "buy")
CLUSTER_CODES = ("HH", "LL", "HL", "LH", "NS")
# A14 (D18): DoD's six housing profiles, cheapest first. A standard interpolates from a
# lower to a higher profile, so `upper` must come after `lower` in this order.
HOME_TYPE_ORDER = ("apt1", "apt2", "th2", "th3", "sfh3", "sfh4")
BUILDINGS = ("apartment", "townhouse", "single_family")
# The rank dropdown (D18): O-1E to O-3E and O-10 are left out.
DROPDOWN_GRADES = tuple([f"E{i}" for i in range(1, 10)] + [f"W{i}" for i in range(1, 6)]
                        + [f"O{i}" for i in range(1, 10)])


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


def check_standards(cfg: dict, grades: list[str], profiles: dict, errors: list[str]) -> None:
    """A14 (D18): housing standard and member cost share for every dropdown cell."""
    where = "housing_standards.json"
    types = cfg.get("home_types") or []
    ids = [t.get("id") for t in types]
    if tuple(ids) != HOME_TYPE_ORDER:
        errors.append(f"{where}: home_types must be {list(HOME_TYPE_ORDER)} in that order, found {ids}")
    for t in types:
        if t.get("building") not in BUILDINGS:
            errors.append(f"{where} [{t.get('id')}]: building must be one of {BUILDINGS}")
        if not isinstance(t.get("bedrooms"), int) or t.get("bedrooms") not in SAFMR_BEDROOMS:
            errors.append(f"{where} [{t.get('id')}]: bedrooms must be an integer 0-4 (SAFMR range)")
    ref = next((t for t in types if t.get("id") == cfg.get("reference_type")), None)
    if not ref or (ref.get("building"), ref.get("bedrooms")) != ("townhouse", 2):
        errors.append(f"{where}: reference_type must be the 2-bedroom townhouse, the dwelling B8 and B9 "
                      "stand for (D19)")
    listed = list(cfg.get("grades") or [])
    if tuple(listed) != DROPDOWN_GRADES:
        errors.append(f"{where}: grades must be the 23 dropdown grades {list(DROPDOWN_GRADES)} in order")
    unknown = [g for g in listed if g not in grades]
    if unknown:
        errors.append(f"{where}: grades {unknown} are not BAH grades {grades}")
    order = {t: i for i, t in enumerate(HOME_TYPE_ORDER)}
    standards, shares = cfg.get("standards") or {}, cfg.get("cost_share_monthly") or {}
    for g in listed:
        for dep in ("with", "without"):
            cell = (standards.get(g) or {}).get(dep)
            w = f"{where} [{g} {dep}]"
            if not isinstance(cell, dict):
                errors.append(f"{w}: standard missing")
                continue
            lo, up, share = cell.get("lower"), cell.get("upper"), cell.get("share")
            if lo not in order or (up is not None and up not in order):
                errors.append(f"{w}: lower/upper must be home type ids, found {lo!r}/{up!r}")
                continue
            if not isinstance(share, (int, float)) or isinstance(share, bool) or not 0 <= share < 1:
                errors.append(f"{w}: share must be a number in [0, 1), found {share!r}")
            elif up is not None and (order[up] <= order[lo] or share == 0):
                errors.append(f"{w}: an interpolated standard needs upper after lower and a share above 0")
            amount = (shares.get(g) or {}).get(dep)
            if not isinstance(amount, int) or isinstance(amount, bool) or not 0 < amount < 1000:
                errors.append(f"{w}: cost_share_monthly must be whole DTMO out-of-pocket dollars, found {amount!r}")
    for g, src in (cfg.get("cost_share_derived") or {}).items():
        if shares.get(g) != shares.get(src) or standards.get(g) != standards.get(src):
            errors.append(f"{where}: {g} is derived from {src} but its standard or cost share differs")
    cs = (cfg.get("sources") or {}).get("cost_share") or {}
    for key in ("standards", "cost_share"):
        if not (cfg.get("sources") or {}).get(key, {}).get("url"):
            errors.append(f"{where}: sources.{key}.url is required")
    if profiles:
        if cs.get("sha256") != (profiles.get("cost_share") or {}).get("sha256"):
            errors.append(f"{where}: sources.cost_share.sha256 differs from profiles.json cost_share.sha256 "
                          "(both cite the same DTMO PDF)")
        for p in profiles.get("profiles") or []:
            g, dep = p.get("pay_grade"), "with" if p.get("has_dependents") else "without"
            a14 = (shares.get(g) or {}).get(dep)
            if a14 is None:
                errors.append(f"{where}: no cell for A12 profile {p.get('id')} ({g} {dep})")
            elif a14 != p.get("cost_share_monthly"):
                errors.append(f"profiles.json [{p.get('id')}]: cost_share_monthly {p.get('cost_share_monthly')} "
                              f"!= A14 {g} {dep} {a14}")


def main() -> None:
    errors: list[str] = []
    profiles = load(PROFILES, errors)
    classification = load(CLASSIFICATION, errors)
    ownership = load(OWNERSHIP, errors)
    ui_text = load(UI_TEXT, errors)
    standards = load(STANDARDS, errors)
    for cfg, name in ((profiles, "profiles.json"), (classification, "classification.json"),
                      (ownership, "ownership.json"), (ui_text, "ui_text.json"),
                      (standards, "housing_standards.json")):
        if cfg:
            check_values_only(cfg, name, errors)
            check_doc_pointer(cfg, name, errors)
    if profiles:
        check_profiles(profiles, pay_grades(), errors)
    if classification:
        check_classification(classification, profiles.get("coverage_target") if profiles else None, errors)
    if standards:
        check_standards(standards, pay_grades(), profiles, errors)
    if errors:
        print("Config check FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    names = ", ".join(f"{p['id']} ({p['pay_grade']}, {p['anchor_bedrooms']}BR)" for p in profiles["profiles"])
    print(f"A12 profiles OK: {names}")
    print(f"A13 classification OK: {', '.join(classification['metrics'])}; "
          f"{len(classification.get('clusters', {}).get('classes', {}))} cluster classes")
    print(f"A14 housing_standards.json OK: {len(standards['grades'])} grades x with/without dependents, "
          f"{len(standards['home_types'])} home types")
    print("B11 ownership.json OK: values only, documented in docs/configuration.md")
    print("A13 ui_text.json OK: documented in docs/configuration.md (B21 checks it against the data contract)")


if __name__ == "__main__":
    main()
