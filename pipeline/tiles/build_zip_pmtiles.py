#!/usr/bin/env python3
"""
build_zip_pmtiles.py  (A2 + B1 -> B35 ZIP code polygons and tiles)

The ZIP layer of the map's "Show by: ZIP code" view (decision D36, data contract
section 4b). One feature per ZIP code that DTMO assigns to a real Military Housing
Area and that has a Census ZCTA polygon. ZIPs in County Cost Groups and the
territory bucket are left out: they have no benchmark (decision 2.2), so the area
layer (B7) keeps drawing them in ZIP view.

  * One vector layer, `zips`. Each feature carries exactly two properties: `zip`
    (five digits, the join key; the frontend declares the source with
    promoteId: "zip") and `area` (the MHA code, as in B1). No values are baked in.
  * Zoom 6 to 10 by default. Below zoom 6 the ~15,000 polygons are too small to
    read, and the national tiles would be several times the size of B7's, so the
    map shows the MHA layer there (M8 plan, Z5).
  * Every ZCTA is matched to a ZIP directly (zip == zcta), as B6 does, so each ZIP
    polygon lies inside its MHA's B6 polygon.

    python pipeline/tiles/build_zip_pmtiles.py \\
        --zcta data/raw/cb_2020_us_zcta520_500k.zip \\
        --crosswalk data/interim/bah_2026/zip_mha.csv \\
        --out data/processed/zipcodes_2026.pmtiles

Writes beside the archive:
  zipcodes_<year>_features.csv   zip, area: the features in the archive (read by B36
                                 and by validate_handoff.py, check 4)
  zipcodes_<year>_manifest.json  inputs and SHA-256, counts, zooms, tippecanoe
                                 version, output SHA-256

Requires geopandas (to read the shapefile) and tippecanoe >= 2.17.
"""

from __future__ import annotations

import argparse
import csv
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
LAYER = "zips"
ID_FIELD = "zip"
AREA_FIELD = "area"
ZIP = re.compile(r"^[0-9]{5}$")
CODE = re.compile(r"^[A-Z]{2}[0-9]{3}$")
WEB_CRS = "EPSG:4326"
ATTRIBUTION = ("ZIP code geometry: U.S. Census ZCTAs, matched to DoD DTMO's ZIP-to-MHA assignments by "
               "BAH Atlas")


def die(msg: str) -> None:
    sys.exit(f"build_zip_pmtiles: {msg}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def read_crosswalk(path: Path) -> dict[str, str]:
    """{zip: mha} for ZIPs in real MHAs (B1 class `mha`)."""
    if not path.exists():
        die(f"B1 {path} not found (run `make ingest`)")
    out: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not {"zip", "mha", "mha_class"} <= set(reader.fieldnames):
            die(f"{path.name} needs zip, mha and mha_class columns")
        for r in reader:
            z, code, cls = r["zip"].strip(), r["mha"].strip().upper(), r["mha_class"].strip().lower()
            if not ZIP.match(z) or not CODE.match(code):
                die(f"{path.name} has a malformed row: ZIP {z!r}, area {code!r}")
            if z in out:
                die(f"{path.name} lists ZIP {z} twice")
            if cls == "mha":
                out[z] = code
    if not out:
        die(f"{path.name} has no real-MHA ZIPs")
    return out


def zcta_column(columns: list[str]) -> str:
    for col in columns:
        if "ZCTA5" in col.upper() or col.upper() in ("GEOID20", "GEOID10", "GEOID"):
            return col
    die(f"no ZCTA code column among {columns}")
    raise AssertionError


def tippecanoe_version() -> str:
    out = subprocess.run([TIPPECANOE, "--version"], capture_output=True, text=True)
    text = (out.stdout or out.stderr).strip()
    return text.splitlines()[0] if text else "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zcta", type=Path, required=True, help="A2 Census ZCTA shapefile (.zip)")
    ap.add_argument("--crosswalk", type=Path, required=True, help="B1 zip_mha.csv")
    ap.add_argument("--out", type=Path, required=True, help="output .pmtiles path")
    ap.add_argument("--minzoom", type=int, default=6)
    ap.add_argument("--maxzoom", type=int, default=10)
    args = ap.parse_args()

    if args.out.suffix != ".pmtiles":
        die("--out must end in .pmtiles")
    if not args.zcta.exists():
        die(f"A2 {args.zcta} not found (run `make fetch`)")
    if shutil.which(TIPPECANOE) is None:
        die("tippecanoe not found. Fedora: `sudo dnf install tippecanoe`; macOS: `brew install tippecanoe`")
    import geopandas as gpd  # geometry work only; the checks above need no third-party package

    crosswalk = read_crosswalk(args.crosswalk)
    zcta = gpd.read_file(f"zip://{args.zcta.resolve()}" if args.zcta.suffix == ".zip" else args.zcta)
    col = zcta_column(list(zcta.columns))
    zcta = zcta.rename(columns={col: ID_FIELD})[[ID_FIELD, "geometry"]]
    zcta[ID_FIELD] = zcta[ID_FIELD].astype(str).str.zfill(5)
    if zcta[ID_FIELD].duplicated().any():
        die(f"{args.zcta.name} holds a ZCTA code twice")
    zcta = zcta[zcta[ID_FIELD].isin(crosswalk)].copy()
    if zcta.empty:
        die("no ZCTA matches a real-MHA ZIP")
    zcta[AREA_FIELD] = zcta[ID_FIELD].map(crosswalk)
    bad = zcta[~zcta.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    if len(bad):
        die(f"{len(bad)} ZCTA(s) are not polygons, e.g. {bad[ID_FIELD].iloc[0]}")
    zcta = zcta.to_crs(WEB_CRS).sort_values(ID_FIELD)

    matched = set(zcta[ID_FIELD])
    without = sorted(set(crosswalk) - matched)
    mhas_with = set(zcta[AREA_FIELD])
    mhas_without = sorted(set(crosswalk.values()) - mhas_with)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_name(args.out.stem + ".tmp.pmtiles")
    src = args.out.with_name(args.out.stem + ".tmp.input.geojson")
    src.write_text(zcta[[ID_FIELD, AREA_FIELD, "geometry"]].to_json(drop_id=True), encoding="utf-8")
    cmd = [
        TIPPECANOE,
        "--output", str(tmp), "--force",
        "--layer", LAYER,
        "--name", "BAH Atlas ZIP codes",
        "--attribution", ATTRIBUTION,
        "--minimum-zoom", str(args.minzoom),
        "--maximum-zoom", str(args.maxzoom),
        "--include", ID_FIELD,              # the join key
        "--include", AREA_FIELD,            # the MHA the ZIP belongs to
        "--detect-shared-borders",          # neighbouring ZIPs simplify the same way: no slivers
        "--no-tiny-polygon-reduction",      # a small ZIP must not vanish
        "--no-feature-limit",
        "--no-tile-size-limit",             # never drop a ZIP; the largest tile is measured below
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

    features = args.out.with_name(args.out.stem + "_features.csv")
    with features.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow([ID_FIELD, AREA_FIELD])
        w.writerows(zcta[[ID_FIELD, AREA_FIELD]].itertuples(index=False))

    manifest = {
        "node": "B35",
        "source_nodes": ["A2", "B1"],
        "inputs": {"A2": args.zcta.name, "B1": args.crosswalk.name},
        "input_sha256": {"A2": sha256(args.zcta), "B1": sha256(args.crosswalk)},
        "features": int(len(zcta)),
        "real_mha_zips": len(crosswalk),
        "zips_without_zcta": len(without),
        "mhas_with_zip_polygons": len(mhas_with),
        "mhas_without_zip_polygons": mhas_without,
        "layer": LAYER,
        "id_property": ID_FIELD,
        "area_property": AREA_FIELD,
        "maplibre_source_hint": {"type": "vector", "url": f"pmtiles://{args.out.name}", "promoteId": ID_FIELD},
        "contract": "docs/data-contract.md section 4b (decision D36)",
        "minzoom": args.minzoom,
        "maxzoom": args.maxzoom,
        "tippecanoe": tippecanoe_version(),
        "outputs": [args.out.name, features.name],
        "output_sha256": {args.out.name: sha256(args.out), features.name: sha256(features)},
        "output_file": args.out.name,
        "output_bytes": args.out.stat().st_size,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    manifest_path = args.out.with_name(args.out.stem + "_manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"B35 ZIP PMTiles: {len(zcta):,} ZIP polygons in {len(mhas_with)} MHAs, z{args.minzoom}-z{args.maxzoom}, "
          f"{args.out.stat().st_size / 1e6:.1f} MB")
    print(f"  {len(without):,} of {len(crosswalk):,} real-MHA ZIPs have no ZCTA polygon (PO boxes, single sites)")
    if mhas_without:
        print(f"  MHAs with no ZIP polygon: {', '.join(mhas_without)}")
    print(f"  -> {args.out}")


if __name__ == "__main__":
    main()
