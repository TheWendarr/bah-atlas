#!/usr/bin/env python3
"""
build_mha_geometry.py  (B6, and B28 with --classes ccg,unknown)

Synthesize Military Housing Area (MHA) boundary polygons (B6), and the County
Cost Group and territory-bucket polygons beside them (B28).

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

  --classes     Which area classes to build (default: mha).
                  mha          B6: real MHAs, from B2 zip_mha_geo.csv.
                  ccg,unknown  B28: County Cost Groups (ZZ###) and the territory
                               bucket (XX###), from B1 zip_mha.csv, which carries
                               the mha_class column. DoD publishes no polygons
                               for either, so every feature is marked
                               non-authoritative (decision 2.1, D9). Kept out
                               of the spatial statistics; B7 tiles them with B6.
                B6 and B28 are separate runs so B6, and everything built on it
                (B16-B18), never changes when B28 does.

------------------------------------------------------------------------------
Output
------------------------------------------------------------------------------
  --out         GeoPackage (.gpkg), one row per MHA, plus a .geojson twin and a
                provenance manifest <out stem>_geometry_manifest.json (node B6):
                input and output SHA-256, counts, and the build report below.
                With --classes ccg,unknown (node B28) each row also carries
                `class` and `geometry_source`, and the manifest adds counts by
                class, area codes left without a polygon, ZCTAs claimed by more
                than one area (the build stops on any), and the ZIP3 prefixes of
                the territory bucket so its territory can be confirmed.

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

# Area codes are two letters + three digits, e.g. CO018, HI001, VA125. County
# Cost Groups (ZZ###) and the territory bucket (XX###) share the pattern, so B6
# relies on its input, B2, which already holds real MHAs only.
MHA_CODE = re.compile(r"^[A-Z]{2}\d{3}$")

# MapLibre / web tiles expect lon-lat WGS84.
WEB_CRS = "EPSG:4326"

# Area classes as the B1 crosswalk names them (ingest_bah_ascii.py).
CLASSES = ("mha", "ccg", "unknown")
# Shown wherever B28 polygons appear (ICD caveat `ccg_geometry`).
GEOMETRY_SOURCE = "ZCTA dissolve of DTMO ZIP assignments (non-authoritative)"


def die(msg: str) -> None:
    sys.exit(f"build_mha_geometry: {msg}")


def parse_classes(text: str) -> list[str]:
    classes = [c.strip().lower() for c in text.split(",") if c.strip()]
    unknown = [c for c in classes if c not in CLASSES]
    if not classes or unknown:
        die(f"--classes takes a comma list of {', '.join(CLASSES)}; got {text!r}")
    if "mha" in classes and len(classes) > 1:
        die("build MHAs (B6) and the non-MHA classes (B28) in separate runs, "
            "so B6 and the spatial statistics built on it never change with B28")
    return sorted(set(classes), key=CLASSES.index)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_crosswalk(path: str, need_class: bool = False) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    cols = {c.lower(): c for c in df.columns}
    if "zip" not in cols or "mha" not in cols:
        sys.exit(f"--crosswalk needs 'zip' and 'mha' columns; found {list(df.columns)}")
    if need_class and "mha_class" not in cols:
        die(f"--classes other than mha needs the B1 crosswalk (zip_mha.csv) with an "
            f"'mha_class' column; {Path(path).name} has {list(df.columns)}")
    df = df.rename(columns={cols["zip"]: "zip", cols["mha"]: "mha"})
    if need_class:
        df = df.rename(columns={cols["mha_class"]: "mha_class"})
        df["mha_class"] = df["mha_class"].str.strip().str.lower()
    df["zip"] = df["zip"].str.strip().str.zfill(5)
    df["mha"] = df["mha"].str.strip().str.upper()
    return df.dropna(subset=["zip", "mha"]).drop_duplicates(subset=["zip"])


def apply_bridge(xwalk: pd.DataFrame, path: str) -> pd.DataFrame:
    """Rewrite 'zip' to the ZCTA each ZIP falls in (HUD/Census bridge file)."""
    bridge = pd.read_csv(path, dtype=str)
    bcols = {c.lower(): c for c in bridge.columns}
    bridge = bridge.rename(columns={bcols["zip"]: "zip", bcols["zcta"]: "zcta"})
    bridge["zip"] = bridge["zip"].str.strip().str.zfill(5)
    bridge["zcta"] = bridge["zcta"].str.strip().str.zfill(5)
    xwalk = xwalk.merge(bridge[["zip", "zcta"]], on="zip", how="left")
    xwalk["zip"] = xwalk["zcta"].fillna(xwalk["zip"])
    return xwalk.drop(columns="zcta")


def shared_zctas(xwalk: pd.DataFrame) -> dict[str, list[str]]:
    """ZCTAs that ZIPs of more than one area code land in (they would overlap)."""
    codes = xwalk.groupby("zip")["mha"].agg(lambda s: sorted(set(s)))
    return {z: c for z, c in codes.items() if len(c) > 1}


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
    ap.add_argument("--classes", default="mha",
                    help="mha (B6, the default) or ccg,unknown (B28); see the module docstring")
    args = ap.parse_args()

    classes = parse_classes(args.classes)
    if classes != ["mha"]:
        build_non_mha(args, classes)
        return

    xwalk = load_crosswalk(args.crosswalk)

    # Keep only well-formed area codes; B2 already excludes CCG and territory codes.
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
        xwalk = apply_bridge(xwalk, args.zip_to_zcta)

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


def build_non_mha(args: argparse.Namespace, classes: list[str]) -> None:
    """B28: County Cost Group and territory polygons, by the same dissolve as B6."""
    full = load_crosswalk(args.crosswalk, need_class=True)
    bad_class = sorted(set(full["mha_class"]) - set(CLASSES))
    if bad_class:
        die(f"unexpected mha_class values in {Path(args.crosswalk).name}: {bad_class}")
    bad_code = sorted(set(full.loc[~full["mha"].str.match(MHA_CODE), "mha"]))
    if bad_code:
        die(f"malformed area codes in {Path(args.crosswalk).name}: {bad_code[:10]}")
    if args.zip_to_zcta:
        full = apply_bridge(full, args.zip_to_zcta)

    xwalk = full[full["mha_class"].isin(classes)]
    if xwalk.empty:
        die(f"no ZIPs of class {', '.join(classes)} in {Path(args.crosswalk).name}")
    code_class = xwalk.drop_duplicates("mha").set_index("mha")["mha_class"].to_dict()

    # A ZCTA reached by ZIPs of two areas would draw both polygons over the same
    # ground. With the direct zip == zcta match this cannot happen; a bridge file can.
    shared = shared_zctas(full)
    clash = {z: c for z, c in shared.items() if any(code in code_class for code in c)}
    if clash:
        sample = "; ".join(f"{z}: {', '.join(c)}" for z, c in list(clash.items())[:10])
        die(f"{len(clash)} ZCTA(s) belong to more than one area, so polygons would overlap: {sample}")

    zcta = load_zcta(args.zcta)
    merged = xwalk.merge(zcta, left_on="zip", right_on="zcta", how="left")
    unmatched = merged[merged["geometry"].isna()]
    matched = gpd.GeoDataFrame(merged.dropna(subset=["geometry"]), geometry="geometry", crs=zcta.crs)
    if matched.empty:
        die("no ZIP of the requested classes matches a ZCTA polygon")

    areas = matched.dissolve(by="mha", as_index=False)[["mha", "geometry"]].to_crs(WEB_CRS)
    areas.insert(1, "class", areas["mha"].map(code_class))
    areas.insert(2, "geometry_source", GEOMETRY_SOURCE)
    areas = areas.sort_values("mha").reset_index(drop=True)

    out = Path(args.out)
    geojson = out.with_suffix(".geojson")
    areas.to_file(out, driver="GPKG")
    areas.to_file(geojson, driver="GeoJSON")

    without_polygon = sorted(set(code_class) - set(areas["mha"]))
    warnings = []
    if without_polygon:
        warnings.append(f"{len(without_polygon)} area code(s) have no ZIP matching a ZCTA and get "
                        f"no polygon: {', '.join(without_polygon)}")
    unknown_zips = xwalk.loc[xwalk["mha_class"] == "unknown", "zip"]
    prefixes = {str(k): int(v) for k, v in unknown_zips.str[:3].value_counts().sort_index().items()}
    inputs = {"A2": Path(args.zcta), "B1": Path(args.crosswalk)}
    if args.zip_to_zcta:
        inputs["zip_to_zcta"] = Path(args.zip_to_zcta)
    manifest = {
        "node": "B28",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "ZCTA polygons dissolved to County Cost Group and territory-bucket codes through the "
                  "DTMO ZIP-to-area crosswalk (direct zip == zcta match unless --zip-to-zcta is given); "
                  "the same dissolve as B6",
        "authority": "DoD publishes no polygons for County Cost Groups or the territory bucket; these "
                     "are non-authoritative and are kept out of the spatial statistics (B16-B18)",
        "geometry_source": GEOMETRY_SOURCE,
        "classes": classes,
        "inputs": {k: p.name for k, p in inputs.items()},
        "input_sha256": {k: sha256_file(p) for k, p in inputs.items()},
        "crs": WEB_CRS,
        "counts": {
            "areas": int(len(areas)),
            "areas_by_class": {c: int((areas["class"] == c).sum()) for c in classes},
            "codes_in_crosswalk_by_class": {c: int(sum(v == c for v in code_class.values())) for c in classes},
            "multipolygon_areas": int((areas.geometry.geom_type == "MultiPolygon").sum()),
            "zips_by_class": {c: int((xwalk["mha_class"] == c).sum()) for c in classes},
            "zips_without_zcta": int(len(unmatched)),
            "zips_without_zcta_by_class": {c: int((unmatched["mha_class"] == c).sum()) for c in classes},
            "zctas_in_more_than_one_area": 0,
        },
        "codes_without_polygon": without_polygon,
        "unknown_zip3_prefixes": prefixes,
        "outputs": [out.name, geojson.name],
        "output_sha256": {out.name: sha256_file(out), geojson.name: sha256_file(geojson)},
        "warnings": warnings,
    }
    man_path = out.with_name(f"{out.stem}_geometry_manifest.json")
    man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print("---- B28 non-MHA geometry build report ----")
    for c in classes:
        print(f"{c:8} areas written: {manifest['counts']['areas_by_class'][c]:4} "
              f"of {manifest['counts']['codes_in_crosswalk_by_class'][c]} codes "
              f"({manifest['counts']['zips_by_class'][c]} ZIPs, "
              f"{manifest['counts']['zips_without_zcta_by_class'][c]} with no ZCTA)")
    if "unknown" in classes:
        print(f"territory bucket ZIP3 prefixes: {prefixes or 'none'}")
    for w in warnings:
        print(f"WARNING: {w}")
    print(f"Output: {out}  +  {geojson}  +  {man_path.name}")


if __name__ == "__main__":
    main()
