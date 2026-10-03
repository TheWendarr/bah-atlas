#!/usr/bin/env python3
"""
build_mha_pmtiles.py  (B6 -> B7)

Tile the dissolved MHA polygons into a single PMTiles archive for MapLibre.

Contract with Layer 3 (see the nodal architecture, B7 / C8):
  * One vector layer, `mha`, one feature per Military Housing Area.
  * Each feature carries exactly one property, `mha` (e.g. "CO018"). No metrics are
    baked into the tiles; values arrive separately in the B20 payload and are joined
    in the browser with feature-state. MapLibre needs a feature id for that, so the
    frontend declares the source with `promoteId: "mha"`.
  * Shared borders between neighbouring MHAs are detected so simplification never
    opens slivers between them.

Requires tippecanoe >= 2.17 (writes .pmtiles directly):
  Fedora:  sudo dnf install tippecanoe        (or build from github.com/felt/tippecanoe)
  macOS:   brew install tippecanoe

Usage:
  python pipeline/tiles/build_mha_pmtiles.py \
      --geojson data/processed/mha_2026.geojson \
      --out data/processed/mha_2026.pmtiles
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TIPPECANOE = os.environ.get("TIPPECANOE", "tippecanoe")
LAYER = "mha"
ID_FIELD = "mha"
ATTRIBUTION = "MHA geometry: BAH Atlas, from U.S. Census ZCTAs and DoD DTMO ZIP-to-MHA crosswalk"


def die(msg: str) -> None:
    sys.exit(f"build_mha_pmtiles: {msg}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def check_geojson(path: Path) -> int:
    """Validate the B6 GeoJSON before spending time tiling it."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"{path} is not valid JSON: {e}")
    if data.get("type") != "FeatureCollection":
        die(f"{path} is not a GeoJSON FeatureCollection")
    feats = data.get("features") or []
    if not feats:
        die(f"{path} has no features")
    codes = []
    for i, f in enumerate(feats):
        code = (f.get("properties") or {}).get(ID_FIELD)
        if not code:
            die(f"feature {i} has no '{ID_FIELD}' property")
        gtype = (f.get("geometry") or {}).get("type")
        if gtype not in ("Polygon", "MultiPolygon"):
            die(f"feature {code} has geometry type {gtype}; expected (Multi)Polygon")
        codes.append(code)
    dupes = sorted({c for c in codes if codes.count(c) > 1})
    if dupes:
        die(f"duplicate MHA codes in {path.name}: {', '.join(dupes[:10])}")
    return len(feats)


def tippecanoe_version() -> str:
    out = subprocess.run([TIPPECANOE, "--version"], capture_output=True, text=True)
    return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--geojson", type=Path, required=True, help="B6 MHA polygons (GeoJSON, EPSG:4326)")
    ap.add_argument("--out", type=Path, required=True, help="output .pmtiles path")
    ap.add_argument("--minzoom", type=int, default=2)
    ap.add_argument("--maxzoom", type=int, default=10,
                    help="10 keeps MHA edges crisp at metro scale; MapLibre overzooms beyond it")
    args = ap.parse_args()

    if args.out.suffix != ".pmtiles":
        die("--out must end in .pmtiles")
    if shutil.which(TIPPECANOE) is None:
        die("tippecanoe not found. Fedora: `sudo dnf install tippecanoe`; "
            "or build it from https://github.com/felt/tippecanoe (make && sudo make install)")
    if not args.geojson.exists():
        die(f"{args.geojson} not found — run `make geometry` first")

    n = check_geojson(args.geojson)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_name(args.out.stem + ".tmp.pmtiles")
    cmd = [
        TIPPECANOE,
        "--output", str(tmp), "--force",
        "--layer", LAYER,
        "--name", "BAH Atlas MHAs",
        "--attribution", ATTRIBUTION,
        "--minimum-zoom", str(args.minzoom),
        "--maximum-zoom", str(args.maxzoom),
        "--include", ID_FIELD,              # keep only the join key
        "--detect-shared-borders",          # no slivers between neighbouring MHAs
        "--no-tiny-polygon-reduction",      # small MHAs must not vanish at low zoom
        "--no-feature-limit",
        "--no-tile-size-limit",             # ~300 polygons; never drop features
        "--quiet",
        str(args.geojson),
    ]
    print("running:", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
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
        "source_node": "B6",
        "input_file": args.geojson.name,
        "input_sha256": sha256(args.geojson),
        "features": n,
        "layer": LAYER,
        "id_property": ID_FIELD,
        "maplibre_source_hint": {"type": "vector", "url": f"pmtiles://{args.out.name}", "promoteId": ID_FIELD},
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
    print(f"B7 MHA PMTiles: {n} MHAs, z{args.minzoom}-z{args.maxzoom}, "
          f"{args.out.stat().st_size / 1e6:.1f} MB -> {args.out}")


if __name__ == "__main__":
    main()
