#!/usr/bin/env python3
"""
build_manifest.py  (every stage manifest + B7 -> B22 build manifest)

Gathers the provenance of one build into a single file (data contract section 8):
the raw inputs and their SHA-256, the configs, every stage manifest with its hash
and warnings, the benchmark windows, software versions, the git commit, and the
B7 tile archive. Its own SHA-256 is the `build_id` that B20, B21 and B27 carry,
so it is written before them and does not list them; SHA256SUMS covers all five.

    python pipeline/handoff/build_manifest.py --year 2026 \
        --out data/processed/handoff/build_manifest_2026.json

Stops if any stage manifest is missing. `make handoff` runs `make verify` first,
so the hash chain between these manifests is already proven when this runs.
Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
from pathlib import Path

import contract as c

TOOL = "build_manifest"
ROOT = Path(__file__).resolve().parents[2]


def stage_paths(data: Path, year: int) -> list[tuple[str, Path]]:
    """Every stage manifest a handoff build depends on, in pipeline order."""
    interim, bench = data / "interim" / f"bah_{year}", data / "interim" / f"benchmarks_{year}"
    metrics, spatial, processed = (data / "interim" / f"metrics_{year}", data / "interim" / f"spatial_{year}",
                                   data / "processed")
    return [
        ("A1-A9 A12", data / "raw" / "fetch_manifest.json"),
        ("B1-B4", interim / "manifest.json"),
        ("B5", interim / "rate_components_manifest.json"),
        ("B6", processed / f"mha_{year}_geometry_manifest.json"),
        ("B28", processed / f"non_mha_{year}_geometry_manifest.json"),
        ("B7", processed / f"areas_{year}_manifest.json"),
        ("B8", bench / "mha_zori_manifest.json"),
        ("B9", bench / "mha_zhvi_manifest.json"),
        ("B10", bench / "mha_safmr_manifest.json"),
        ("A8", bench / "mha_tax_insurance_manifest.json"),
        ("B11", bench / "mha_ownership_manifest.json"),
        ("B12-B15", metrics / "coverage_metrics_manifest.json"),
        ("B16", spatial / "weights_manifest.json"),
        ("B17-B18", spatial / "spatial_stats_manifest.json"),
    ]


def git_state(repo: Path) -> dict:
    def run(*args: str) -> str:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else ""
    commit = run("rev-parse", "HEAD")
    return {"commit": commit or None, "dirty": bool(run("status", "--porcelain")) if commit else None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--config-dir", type=Path, default=ROOT / "config")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    stages, problems = [], []
    manifests: dict[str, dict] = {}
    for nodes, path in stage_paths(args.data, args.year):
        if not path.exists():
            problems.append(f"{nodes}: stage manifest missing: {path}")
            continue
        m = c.read_json(path, TOOL)
        manifests[nodes] = m
        stages.append({"nodes": nodes, "file": path.name, "sha256": c.sha256(path),
                       "generated_at": (m.get("generated_at") or m.get("ingested_at_utc")
                                        if isinstance(m, dict) else None),
                       "warnings": m.get("warnings", []) if isinstance(m, dict) else []})
    c.fail_if(problems, TOOL)

    fetch = manifests["A1-A9 A12"]
    raw_inputs = {node: {k: rec.get(k) for k in ("filename", "sha256", "bytes", "source_url", "retrieved_at")}
                  for node, rec in sorted(fetch.items()) if isinstance(rec, dict) and rec.get("sha256")}
    configs = {p.name: c.sha256(p) for p in sorted(args.config_dir.glob("*.json"))}

    cov, tax = manifests["B12-B15"], manifests["A8"]
    b7 = manifests["B7"]
    spatial = manifests["B17-B18"]
    windows = {
        "rent_zori_months": cov.get("windows", {}).get("B8"),
        "home_value_zhvi_months": cov.get("windows", {}).get("B9"),
        "mortgage_rate_window": cov.get("windows", {}).get("B11_rate"),
        "safmr": cov.get("windows", {}).get("B10"),
        "property_tax_acs": tax.get("property_tax", {}).get("acs_period"),
        "insurance_fio_year": tax.get("insurance", {}).get("data_year"),
    }
    if not b7.get("output_file") or not b7.get("output_sha256"):
        c.die(TOOL, "the B7 manifest has no output_file / output_sha256; rerun `make tiles`")

    manifest = {
        "node": "B22",
        "schema_version": c.SCHEMA_VERSION,
        "bah_year": args.year,
        "generated_at": c.now_utc(),
        "git": git_state(ROOT),
        "software": {"python": platform.python_version(), "tippecanoe": b7.get("tippecanoe"),
                     **spatial.get("method", {}).get("software", {})},
        "raw_inputs": raw_inputs,
        "configs": configs,
        "stages": stages,
        "windows": windows,
        "spatial": {k: spatial.get("method", {}).get(k) for k in ("permutations", "seed", "alpha")},
        "outputs": {"B7": {"file": b7["output_file"], "sha256": b7["output_sha256"],
                           "features_by_class": b7.get("features_by_class")}},
        "build_order": "stage manifests, B28 -> B7 -> B22 -> B20, B21, B27 -> SHA256SUMS",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    dirty = " (working tree has uncommitted changes)" if manifest["git"]["dirty"] else ""
    print(f"B22 build manifest: {len(stages)} stage manifests, {len(raw_inputs)} raw inputs, "
          f"{len(configs)} configs; commit {(manifest['git']['commit'] or 'unknown')[:12]}{dirty}")
    print(f"  build_id {c.sha256(args.out)}")
    print(f"  -> {args.out}")


if __name__ == "__main__":
    main()
