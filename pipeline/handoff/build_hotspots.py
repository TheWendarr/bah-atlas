#!/usr/bin/env python3
"""
build_hotspots.py  (B18 + B17 + B20 + B22 -> B27 hotspot overlay)

The local cluster results for the primary variable `adequacy_gap`, keyed like
the payload, for the optional hotspot overlay (data contract section 7;
decisions D2 and D5). Only areas the payload marks `cluster_scope: true` appear.
Each test also carries its global Moran's I, the confirmatory result for H1.

    python pipeline/handoff/build_hotspots.py --year 2026 \
        --spatial-stats data/interim/spatial_2026/mha_spatial_stats.csv \
        --spatial-manifest data/interim/spatial_2026/spatial_stats_manifest.json \
        --payload data/processed/handoff/payload_2026.json \
        --build-manifest data/processed/handoff/build_manifest_2026.json \
        --out data/processed/handoff/hotspots_2026.json

p-values are written to 5 decimal places: at 99,999 permutations the resolution
is 0.00001 (ICD 1.0.2). Stdlib only.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import contract as c

TOOL = "build_hotspots"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--spatial-stats", type=Path, required=True, help="B18 mha_spatial_stats.csv")
    ap.add_argument("--spatial-manifest", type=Path, required=True, help="B17/B18 manifest")
    ap.add_argument("--payload", type=Path, required=True, help="B20 payload (cluster scope)")
    ap.add_argument("--build-manifest", type=Path, required=True, help="B22, whose hash is the build_id")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    payload = c.read_json(args.payload, TOOL)
    build_id = c.sha256(args.build_manifest)
    if payload.get("build_id") != build_id:
        c.die(TOOL, "the payload was built from a different B22; rebuild B20 first")
    in_scope = {code for code, a in payload["areas"].items() if a["cluster_scope"]}
    profiles, modes = payload["profiles"], payload["modes"]

    man = c.read_json(args.spatial_manifest, TOOL)
    method = man.get("method", {})
    tests: dict[str, dict] = {p: {} for p in profiles}
    for t in man.get("tests", []):
        if t.get("variable") != c.B27_VARIABLE or t.get("profile") not in tests:
            continue
        k = re.search(r"k\s*=\s*(\d+)", str(t.get("weights", "")))
        tests[t["profile"]][t["mode"]] = {
            "n": t["n"], "k": int(k.group(1)) if k else None, "permutations": method.get("permutations"),
            "alpha": method.get("alpha"), "moran_i": c.ratio(t["moran"]["I"]),
            "moran_p_sim": c.ratio(t["moran"]["p_sim"], c.P_PLACES),
            "fdr_cutoff": c.ratio(t["lisa"].get("fdr_cutoff_p"), c.P_PLACES),
        }
    missing = [f"{p}/{m}" for p in profiles for m in modes if m not in tests[p]]
    if missing:
        c.die(TOOL, f"the spatial manifest has no {c.B27_VARIABLE} test for {', '.join(missing)}")

    rows = c.read_csv(args.spatial_stats, {"profile", "mode", "variable", "mha", "status", "cluster",
                                           "lisa_p_sim", "lisa_fdr_significant", "gi_class"}, TOOL)
    areas: dict[str, dict] = {}
    problems: list[str] = []
    for r in rows:
        if r["variable"] != c.B27_VARIABLE or r["profile"] not in tests:
            continue
        code = r["mha"]
        if code not in in_scope:
            if r["status"] in c.B27_STATUSES:
                problems.append(f"{code} was tested ({r['profile']} {r['mode']}) but is outside the payload's cluster scope")
            continue
        if r["status"] not in c.B27_STATUSES:
            problems.append(f"{code} {r['profile']} {r['mode']}: status {r['status']!r} for an in-scope area")
            continue
        tested = r["status"] == "tested"
        areas.setdefault(code, {}).setdefault(r["profile"], {})[r["mode"]] = {
            "status": r["status"],
            "cluster": r["cluster"] if tested else None,
            "lisa_p_sim": c.ratio(r["lisa_p_sim"], c.P_PLACES) if tested else None,
            "lisa_fdr_significant": (r["lisa_fdr_significant"].strip().lower() == "true") if tested else None,
            "gi_class": r["gi_class"] if tested else None,
        }
    gaps = [f"{code} {p} {m}" for code in sorted(in_scope) for p in profiles for m in modes
            if m not in areas.get(code, {}).get(p, {})]
    problems += [f"no B18 row for in-scope area {g}" for g in gaps[:20]]
    c.fail_if(problems, TOOL)

    overlay = {**c.header(args.build_manifest, args.year), "variable": c.B27_VARIABLE,
               "caveats": ["lisa_exploratory"], "tests": tests,
               "areas": {code: areas[code] for code in sorted(areas)}}
    c.write_json(args.out, overlay)
    p0 = tests[profiles[0]]["rent"]
    fdr = sum(1 for a in areas.values() if (a.get(profiles[0], {}).get("rent") or {}).get("lisa_fdr_significant"))
    print(f"B27 hotspot overlay: {len(areas)} in-scope MHAs x {len(profiles)} profiles x {len(modes)} modes; "
          f"primary test I = {p0['moran_i']}, p = {p0['moran_p_sim']}, {fdr} FDR-significant")
    print(f"  {args.out.stat().st_size / 1024:.0f} KB -> {args.out}")


if __name__ == "__main__":
    main()
