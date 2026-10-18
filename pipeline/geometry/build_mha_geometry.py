#!/usr/bin/env python3
"""
build_mha_geometry.py

Synthesize Military Housing Area (MHA) boundary polygons.

There is NO official DoD-published MHA polygon layer. DoD defines each MHA as a
set of ZIP Codes (DTMO: "DoD and the Services define these MHAs by sets of ZIP
Codes"). This script builds MHA geometry by:

  1. reading the authoritative ZIP -> MHA crosswalk (from DTMO),
  2. attaching each ZIP to a ZIP Code Tabulation Area (ZCTA) polygon (Census),
  3. dissolving ZCTA polygons up to the MHA level.

------------------------------------------------------------------------------
Inputs you supply
------------------------------------------------------------------------------
  --crosswalk   CSV with columns: zip, mha
                zip  -> 5-char string ("01001"); mha -> e.g. "CO018", "HI001"
                Source: DTMO annual ZIP-to-MHA release / BAH Rate Lookup.

  --zcta        ZCTA polygon file (.shp / .gpkg / .geojson).
                Source: Census cartographic boundary file
                cb_2020_us_zcta520_500k (A2; use the cartographic boundary, not
                full TIGER, for clean coastlines).

  --valid-mha   OPTIONAL text file, one MHA code per line, taken from the
                official MHA list for YOUR BAH year. If given, only these codes
                survive -- the safest filter. If omitted, a code-pattern filter
                is used instead (two letters + three digits).

  --zip-to-zcta OPTIONAL CSV (columns: zip, zcta) to bridge ZIPs that do NOT
                share a code with any ZCTA (PO-box / point ZIPs). Source: HUD
                USPS ZIP crosswalk. If omitted, a direct zip==zcta match is used
                and unmatched ZIPs are reported for you to audit.

------------------------------------------------------------------------------
Output
------------------------------------------------------------------------------
  --out         GeoPackage (.gpkg), one row per MHA, plus a .geojson twin and a
                provenance manifest <out stem>_geometry_manifest.json (node B6):
                input and output SHA-256, counts, and the build report below.

A build report prints at the end: MHAs written, non-contiguous (multipolygon)
MHAs, ZIPs dropped as non-MHA (CCG/placeholder), and ZIPs with no ZCTA match.
Reconcile the MHA count against the official list for your BAH year.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

# Real MHA codes are two letters + three digits, e.g. CO018, HI001, VA125.
# County Cost Group / non-MHA placeholders (historically "ZZ###") are excluded.
MHA_CODE = re.compile(r"^[A-Z]{2}\d{3}$")

# MapLibre / web tiles expect lon-lat WGS84.
WEB_CRS = "EPSG:4326"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_crosswalk(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    cols = {c.lower(): c for c in df.columns}
    if "zip" not in cols or "mha" not in cols:
        sys.exit(f"--crosswalk needs 'zip' and 'mha' columns; found {list(df.columns)}")
    df = df.rename(columns={cols["zip"]: "zip", cols["mha"]: "mha"})
    df["zip"] = df["zip"].str.strip().str.zfill(5)
    df["mha"] = df["mha"].str.strip().str.upper()
    return df.dropna(subset=["zip", "mha"]).drop_duplicates(subset=["zip"])


def load_zcta(path: str) -> gpd.GeoDataFrame:
    z = gpd.read_file(path)
    # Census names the ZCTA code column differently by vintage
    # (ZCTA5CE20, ZCTA5CE10, GEOID20, ZCTA5CE, ...). Take the first match.
    candidates = [
        c for c in z.columns
        if "ZCTA5" in c.upper() or c.upper() in ("GEOID20", "GEOID10", "GEOID")
    ]
    if not candidates:
        sys.exit(f"No ZCTA code column found in {list(z.columns)}")
    z = z.rename(columns={candidates[0]: "zcta"})
    z["zcta"] = z["zcta"].astype(str).str.strip().str.zfill(5)
    return z[["zcta", "geometry"]]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build MHA polygons from a ZIP->MHA crosswalk and ZCTA polygons."
    )
    ap.add_argument("--crosswalk", required=True)
    ap.add_argument("--zcta", required=True)
    ap.add_argument("--valid-mha", default=None)
    ap.add_argument("--zip-to-zcta", default=None)
    ap.add_argument("--out", default="mha.gpkg")
    args = ap.parse_args()

    xwalk = load_crosswalk(args.crosswalk)

    # Keep only real MHA codes: drop CCG counties, ZZ placeholders, malformed rows.
    before = len(xwalk)
    xwalk = xwalk[xwalk["mha"].str.match(MHA_CODE)]
    dropped_codes = before - len(xwalk)

    # Safest filter: restrict to the official MHA list for the BAH year, if given.
    if args.valid_mha:
        valid = {
            line.strip().upper()
            for line in Path(args.valid_mha).read_text().splitlines()
            if line.strip()
        }
        xwalk = xwalk[xwalk["mha"].isin(valid)]

    # Optional rigorous ZIP -> ZCTA bridge (HUD/Census). Rewrites 'zip' to the
    # ZCTA it falls in, so the join below lands the PO-box / point ZIPs too.
    if args.zip_to_zcta:
        bridge = pd.read_csv(args.zip_to_zcta, dtype=str)
        bcols = {c.lower(): c for c in bridge.columns}
        bridge = bridge.rename(columns={bcols["zip"]: "zip", bcols["zcta"]: "zcta"})
        bridge["zip"] = bridge["zip"].str.strip().str.zfill(5)
        bridge["zcta"] = bridge["zcta"].str.strip().str.zfill(5)
        xwalk = xwalk.merge(bridge[["zip", "zcta"]], on="zip", how="left")
        xwalk["zip"] = xwalk["zcta"].fillna(xwalk["zip"])
        xwalk = xwalk.drop(columns="zcta")

    zcta = load_zcta(args.zcta)

    # Attach polygons by code match, then reconcile.
    merged = xwalk.merge(zcta, left_on="zip", right_on="zcta", how="left")
    unmatched = int(merged["geometry"].isna().sum())
    matched = gpd.GeoDataFrame(
        merged.dropna(subset=["geometry"]), geometry="geometry", crs=zcta.crs
    )

    # Dissolve ZCTA polygons up to MHA. Non-contiguous MHAs become MultiPolygons.
    mha = matched.dissolve(by="mha", as_index=False)[["mha", "geometry"]]
    mha = mha.to_crs(WEB_CRS)

    out = Path(args.out)
    mha.to_file(out, driver="GPKG")
    mha.to_file(out.with_suffix(".geojson"), driver="GeoJSON")

    multi = int((mha.geometry.geom_type == "MultiPolygon").sum())
    geojson = out.with_suffix(".geojson")
    inputs = {"A2": Path(args.zcta), "B2": Path(args.crosswalk)}
    if args.valid_mha:
        inputs["valid_mha"] = Path(args.valid_mha)
    if args.zip_to_zcta:
        inputs["zip_to_zcta"] = Path(args.zip_to_zcta)
    manifest = {
        "node": "B6",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "ZCTA polygons dissolved to MHA through the DTMO ZIP-to-MHA crosswalk "
                  "(direct zip == zcta match unless --zip-to-zcta is given); no DoD MHA polygons exist",
        "inputs": {k: p.name for k, p in inputs.items()},
        "input_sha256": {k: sha256_file(p) for k, p in inputs.items()},
        "crs": WEB_CRS,
        "counts": {
            "mhas": int(len(mha)),
            "multipolygon_mhas": multi,
            "zips_dropped_non_mha": int(dropped_codes),
            "zips_without_zcta": unmatched,
        },
        "outputs": [out.name, geojson.name],
        "output_sha256": {out.name: sha256_file(out), geojson.name: sha256_file(geojson)},
    }
    man_path = out.with_name(f"{out.stem}_geometry_manifest.json")
    man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print("---- MHA geometry build report ----")
    print(f"MHAs written:             {len(mha)}")
    print(f"  non-contiguous (multi): {multi}")
    print(f"ZIPs dropped (non-MHA):   {dropped_codes}  (CCG / ZZ / malformed)")
    print(f"ZIPs with no ZCTA match:  {unmatched}  (PO-box/point ZIPs; use --zip-to-zcta)")
    print(f"Output:                   {out}  +  {geojson}  +  {man_path.name}")
    print("Reconcile 'MHAs written' against the official MHA count for your BAH year.")
    # NOTE: do NOT simplify here. Simplifying dissolved polygons creates slivers
    # and gaps. Simplify at tile generation instead (tippecanoe -> PMTiles),
    # which is already in your stack and does it topology-safely.


if __name__ == "__main__":
    main()
