#!/usr/bin/env python3
"""
build_mha_pmtiles.py  (B6 + B28 -> B7)

Tile every area polygon into a single PMTiles archive for MapLibre.

Contract with Layer 3 (docs/data-contract.md, section 4; decision D9):
  * One vector layer, `areas`, one feature per area code: the B6 Military Housing
    Areas plus the B28 County Cost Groups and territory bucket.
  * Each feature carries exactly two properties: `code` (e.g. "CO018", "ZZ001"),
    the join key, and `class` (`mha`, `ccg` or `unknown`). No metrics are baked
    into the tiles; values arrive separately in the B20 payload and are joined in
    the browser with feature-state. MapLibre needs a feature id for that, so the
    frontend declares the source with `promoteId: "code"`.
  * All areas go through one tippecanoe run with shared-border detection, so the
    border between an MHA and a neighbouring County Cost Group is simplified the
    same way on both sides: no slivers or overlaps at any zoom.

Requires tippecanoe >= 2.17 (writes .pmtiles directly):
  Fedora:  sudo dnf install tippecanoe        (or build from github.com/felt/tippecanoe)
  macOS:   brew install tippecanoe

Usage:
  python pipeline/tiles/build_mha_pmtiles.py \\
      --geojson data/processed/mha_2026.geojson \\
      --non-mha data/processed/non_mha_2026.geojson \\
      --out data/processed/areas_2026.pmtiles
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TIPPECANOE = os.environ.get("TIPPECANOE", "tippecanoe")
LAYER = "areas"
ID_FIELD = "code"
CLASS_FIELD = "class"
CLASSES = ("mha", "ccg", "unknown")
CODE = re.compile(r"^[A-Z]{2}\d{3}$")
ATTRIBUTION = ("Area geometry: BAH Atlas, from U.S. Census ZCTAs and the DoD DTMO ZIP-to-area "
               "crosswalk; County Cost Group and territory polygons are non-authoritative")


def die(msg: str) -> None:
    sys.exit(f"build_mha_pmtiles: {msg}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def read_features(path: Path, node: str) -> list[dict]:
    """Read one GeoJSON FeatureCollection and validate it before spending time tiling."""
    if not path.exists():
        die(f"{node} {path} not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"{node} {path} is not valid JSON: {e}")
    if data.get("type") != "FeatureCollection":
        die(f"{node} {path} is not a GeoJSON FeatureCollection")
    feats = data.get("features") or []
    if not feats:
        die(f"{node} {path} has no features")
    for i, f in enumerate(feats):
        code = (f.get("properties") or {}).get("mha")
        if not code:
            die(f"{node} feature {i} has no 'mha' property")
        gtype = (f.get("geometry") or {}).get("type")
        if gtype not in ("Polygon", "MultiPolygon"):
            die(f"{node} feature {code} has geometry type {gtype}; expected (Multi)Polygon")
    return feats


def merge_areas(mha: list[dict], non_mha: list[dict]) -> dict:
    """One FeatureCollection with only `code` and `class` on each feature (ICD section 4).

    B6 features are class `mha`; B28 features keep the class B28 wrote (`ccg` or
    `unknown`). Every code must be well formed and appear once across both inputs.
    """
    out: list[dict] = []
    for feats, node in ((mha, "B6"), (non_mha, "B28")):
        for f in feats:
            props = f.get("properties") or {}
            code = str(props.get("mha", "")).strip().upper()
            cls = "mha" if node == "B6" else str(props.get(CLASS_FIELD, "")).strip().lower()
            if not CODE.match(code):
                die(f"{node} feature has a malformed area code {code!r}")
            if node == "B28" and cls not in ("ccg", "unknown"):
                die(f"B28 feature {code} has class {cls!r}; expected ccg or unknown")
            out.append({"type": "Feature", "properties": {ID_FIELD: code, CLASS_FIELD: cls},
                        "geometry": f["geometry"]})
    codes = [f["properties"][ID_FIELD] for f in out]
    dupes = sorted({c for c in codes if codes.count(c) > 1})
    if dupes:
        die(f"area codes appear more than once across B6 and B28: {', '.join(dupes[:10])}")
    out.sort(key=lambda f: f["properties"][ID_FIELD])
    return {"type": "FeatureCollection", "features": out}


def tippecanoe_version() -> str:
    out = subprocess.run([TIPPECANOE, "--version"], capture_output=True, text=True)
    text = (out.stdout or out.stderr).strip()
    return text.splitlines()[0] if text else "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geojson", type=Path, required=True, help="B6 MHA polygons (GeoJSON, EPSG:4326)")
    ap.add_argument("--non-mha", type=Path, required=True,
                    help="B28 County Cost Group and territory polygons (GeoJSON, EPSG:4326)")
    ap.add_argument("--out", type=Path, required=True, help="output .pmtiles path")
    ap.add_argument("--minzoom", type=int, default=2)
    ap.add_argument("--maxzoom", type=int, default=10,
                    help="10 keeps area edges crisp at metro scale; MapLibre overzooms beyond it")
    args = ap.parse_args()

    if args.out.suffix != ".pmtiles":
        die("--out must end in .pmtiles")
    if shutil.which(TIPPECANOE) is None:
        die("tippecanoe not found. Fedora: `sudo dnf install tippecanoe`; "
            "or build it from https://github.com/felt/tippecanoe (make && sudo make install)")

    merged = merge_areas(read_features(args.geojson, "B6"), read_features(args.non_mha, "B28"))
    feats = merged["features"]
    by_class = {c: sum(f["properties"][CLASS_FIELD] == c for f in feats) for c in CLASSES}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_name(args.out.stem + ".tmp.pmtiles")
    src = args.out.with_name(args.out.stem + ".tmp.input.geojson")
    src.write_text(json.dumps(merged), encoding="utf-8")
    cmd = [
        TIPPECANOE,
        "--output", str(tmp), "--force",
        "--layer", LAYER,
        "--name", "BAH Atlas areas",
        "--attribution", ATTRIBUTION,
        "--minimum-zoom", str(args.minzoom),
        "--maximum-zoom", str(args.maxzoom),
        "--include", ID_FIELD,              # the join key
        "--include", CLASS_FIELD,           # mha | ccg | unknown, for styling before B20 loads
        "--detect-shared-borders",          # no slivers between neighbouring areas of any class
        "--no-tiny-polygon-reduction",      # small areas must not vanish at low zoom
        "--no-feature-limit",
        "--no-tile-size-limit",             # ~340 polygons; never drop features
        "--quiet",
        str(src),
    ]
    print("running:", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        src.unlink(missing_ok=True)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        die(f"tippecanoe failed ({proc.returncode}):\n{proc.stderr.strip()}")
    if not tmp.exists() or tmp.stat().st_size < 1024:
        die("tippecanoe produced no usable output")
    with tmp.open("rb") as fh:
        if fh.read(7) != b"PMTiles":
            tmp.unlink(missing_ok=True)
            die("output is not a PMTiles archive (is tippecanoe older than 2.17?)")
    tmp.replace(args.out)

    manifest = {
        "node": "B7",
        "source_nodes": ["B6", "B28"],
        "inputs": {"B6": args.geojson.name, "B28": args.non_mha.name},
        "input_sha256": {"B6": sha256(args.geojson), "B28": sha256(args.non_mha)},
        "features": len(feats),
        "features_by_class": by_class,
        "layer": LAYER,
        "id_property": ID_FIELD,
        "class_property": CLASS_FIELD,
        "maplibre_source_hint": {"type": "vector", "url": f"pmtiles://{args.out.name}", "promoteId": ID_FIELD},
        "contract": "docs/data-contract.md section 4 (decision D9)",
        "minzoom": args.minzoom,
        "maxzoom": args.maxzoom,
        "tippecanoe": tippecanoe_version(),
        "output_file": args.out.name,
        "output_sha256": sha256(args.out),
        "output_bytes": args.out.stat().st_size,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    manifest_path = args.out.with_name(args.out.stem + "_manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"B7 area PMTiles: {len(feats)} areas ({by_class['mha']} MHA, {by_class['ccg']} CCG, "
          f"{by_class['unknown']} territory), z{args.minzoom}-z{args.maxzoom}, "
          f"{args.out.stat().st_size / 1e6:.1f} MB -> {args.out}")


if __name__ == "__main__":
    main()
