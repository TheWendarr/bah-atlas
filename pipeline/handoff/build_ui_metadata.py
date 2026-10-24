#!/usr/bin/env python3
"""
build_ui_metadata.py  (A12 + A13 + A14 + ui_text + B3 + stage manifests + B22 -> B21 UI metadata)

Everything the map needs to label and colour the B20 payload, so no wording or
class break is hard-coded in Layer 3 (data contract section 6): profiles (A12),
the seven map layers with their classes and colours and the cluster legend (A13),
area names (B3), status and caveat texts and source attributions
(config/ui_text.json), the benchmark windows from the stage manifests, and the
grid block for the rank, dependents and home-type dropdowns with the plain-language
DoD standard for each of the 46 cells (A14, decision D18, ICD 6.1).

    python pipeline/handoff/build_ui_metadata.py --year 2026 \
        --names data/interim/bah_2026/mha_names.csv \
        --coverage-manifest data/interim/metrics_2026/coverage_metrics_manifest.json \
        --tax-manifest data/interim/benchmarks_2026/mha_tax_insurance_manifest.json \
        --build-manifest data/processed/handoff/build_manifest_2026.json \
        --out data/processed/handoff/ui_metadata_2026.json

Stops if ui_text.json misses or adds a status code or caveat id the contract does
not list, or if A13 lacks a field the contract requires. Stdlib only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import contract as c

TOOL = "build_ui_metadata"
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "benchmarks"))
import home_types as ht  # noqa: E402
METRIC_KEYS = ("label", "short_label", "role", "modes", "format", "neutral", "breaks", "colors", "class_labels")
PROFILE_KEYS = ("id", "label", "role", "pay_grade", "has_dependents", "anchor_dwelling", "anchor_bedrooms",
                "cost_share_monthly")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--names", type=Path, required=True, help="B3 mha_names.csv")
    ap.add_argument("--coverage-manifest", type=Path, required=True, help="B12-B15 manifest (windows)")
    ap.add_argument("--tax-manifest", type=Path, required=True, help="A8 rollup manifest (ACS and FIO years)")
    ap.add_argument("--build-manifest", type=Path, required=True, help="B22, whose hash is the build_id")
    ap.add_argument("--profiles", type=Path, default=ROOT / "config" / "profiles.json")
    ap.add_argument("--classification", type=Path, default=ROOT / "config" / "classification.json")
    ap.add_argument("--ui-text", type=Path, default=ROOT / "config" / "ui_text.json")
    ap.add_argument("--standards", type=Path, default=ht.STANDARDS)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    prof, cls_cfg, text = (c.read_json(p, TOOL) for p in (args.profiles, args.classification, args.ui_text))
    problems: list[str] = []

    statuses, caveats = text.get("statuses", {}), text.get("caveats", {})
    for kind, have, want in (("status code", set(statuses), set(c.ALL_STATUSES)),
                             ("caveat id", set(caveats), set(c.CAVEATS))):
        if have != want:
            problems.append(f"ui_text.json {kind}s differ from the contract: missing {sorted(want - have)}, "
                            f"extra {sorted(have - want)}")
    for code, s in statuses.items():
        if not s.get("label") or not s.get("text"):
            problems.append(f"ui_text.json status {code} needs a label and a text")
    for cid, cv in caveats.items():
        if not cv.get("title") or not cv.get("text"):
            problems.append(f"ui_text.json caveat {cid} needs a title and a text")
    if set(text.get("modes", {})) != set(c.MODES):
        problems.append(f"ui_text.json modes must be exactly {c.MODES}")
    gt = text.get("grid", {})
    if set(gt.get("home_types", {})) != {c.STANDARD, *c.HOME_TYPES}:
        problems.append(f"ui_text.json grid.home_types must label exactly {[c.STANDARD, *c.HOME_TYPES]}")
    if set(gt.get("dependents", {})) != set(c.GRID_DEPENDENTS):
        problems.append(f"ui_text.json grid.dependents must label exactly {c.GRID_DEPENDENTS}")
    notice = gt.get("notice", {})
    off = notice.get("off_standard", "")
    if "{standard}" not in notice.get("standard", "") or "{standard}" not in off or "{home_type}" not in off:
        problems.append("ui_text.json grid.notice needs a 'standard' text with {standard} and an 'off_standard' "
                        "text with {standard} and {home_type}")

    metrics = {}
    for mid, m in cls_cfg.get("metrics", {}).items():
        missing = [k for k in METRIC_KEYS if k not in m]
        if missing:
            problems.append(f"A13 metric {mid} lacks {missing}")
        metrics[mid] = {k: m.get(k) for k in METRIC_KEYS}
    if len(metrics) != 7:
        problems.append(f"A13 has {len(metrics)} metrics; the contract's map has 7 layers")
    c.fail_if(problems, TOOL)

    names = c.read_csv(args.names, {"mha", "name", "mha_class"}, TOOL)
    cov, tax = c.read_json(args.coverage_manifest, TOOL), c.read_json(args.tax_manifest, TOOL)
    win = cov.get("windows", {})
    b8 = win.get("B8") or []

    def span(months: list[str]) -> str | None:
        return f"{months[0]} to {months[-1]}" if months else None

    std = ht.load(args.standards)
    labels = gt["home_types"]
    primary = next(p for p in prof["profiles"] if p.get("role") == "primary")
    grid = {
        "ranks": [{"id": g, "label": f"{g[0]}-{g[1:]}"} for g in std["grades"]],
        "dependents": [{"id": d, "label": gt["dependents"][d]} for d in c.GRID_DEPENDENTS],
        "home_types": [{"id": c.STANDARD, "label": labels[c.STANDARD]}] +
                      [{"id": t["id"], "label": labels[t["id"]], "building": t["building"], "bedrooms": t["bedrooms"]}
                       for t in std["home_types"]],
        "default_rank": primary["pay_grade"].upper(),
        "default_dependents": "with" if primary["has_dependents"] else "without",
        "default_home_type": c.STANDARD,
        "metrics": list(c.GRID_METRICS),
        "standards_text": {g: {d: ht.describe(std["standards"][g][d], labels) for d in c.GRID_DEPENDENTS}
                           for g in std["grades"]},
        "notice": notice,
        "titles": {k: gt[k] for k in ("rank", "home_type")},
    }

    meta = {
        **c.header(args.build_manifest, args.year),
        "profiles": [{k: p.get(k) for k in PROFILE_KEYS} for p in prof["profiles"]],
        "default_profile": prof["default_profile"],
        "modes": [{"id": m, "label": text["modes"][m]} for m in c.MODES],
        "metrics": metrics,
        "default_metric": cls_cfg["default_metric"],
        "no_data_color": cls_cfg["no_data_color"],
        "clusters": cls_cfg["clusters"],
        "areas": {r["mha"]: {"name": r["name"], "class": r["mha_class"]}
                  for r in sorted(names, key=lambda r: r["mha"])},
        "statuses": {code: statuses[code] for code in c.ALL_STATUSES},
        "caveats": {cid: {**caveats[cid], "level": level} for cid, level in c.CAVEATS.items()},
        "global_caveats": text.get("global_caveats", []),
        "windows": {
            "bah_rates": str(args.year),
            "rent_zillow_zori": span(b8),
            "home_value_zillow_zhvi": span(win.get("B9") or []),
            "mortgage_rate_pmms": (win.get("B11_rate") or "").replace(":", " to ") or None,
            "rent_crosscheck_hud_safmr": "FY2026 (revised)" if "2026" in str(win.get("B10", "")) else win.get("B10"),
            "property_tax_acs": tax.get("property_tax", {}).get("acs_period"),
            "insurance_fio": str(tax.get("insurance", {}).get("data_year")),
        },
        "sources": text.get("sources", []),
        "geometry": text.get("geometry", {}),
        "grid": grid,
    }
    c.write_json(args.out, meta)
    print(f"B21 UI metadata: {len(meta['profiles'])} profiles, {len(metrics)} map layers, "
          f"{len(meta['areas'])} area names, {len(meta['statuses'])} statuses, {len(meta['caveats'])} caveats, "
          f"{len(meta['sources'])} sources")
    print(f"  {args.out.stat().st_size / 1024:.0f} KB -> {args.out}")


if __name__ == "__main__":
    main()
