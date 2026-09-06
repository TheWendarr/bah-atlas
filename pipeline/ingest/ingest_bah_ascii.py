#!/usr/bin/env python3
"""
ingest_bah_ascii.py

Translate the DTMO "BAH ASCII" release (BAH-ASCII-YYYY.zip) into tidy,
project-ready CSVs plus a provenance manifest.

This is the reference pattern for endpoint-ingestion scripts in this project:
  raw vendor artifact  ->  validated parse  ->  tidy CSVs + manifest.json
Future translators (Zillow ZORI/ZHVI, HUD FMR, Census ZCTA) should mirror this
shape: read as-is, validate loudly, emit stable outputs, record lineage.

------------------------------------------------------------------------------
Input
------------------------------------------------------------------------------
  --zip   Path to BAH-ASCII-YYYY.zip exactly as published by DTMO at
          travel.dod.mil/.../BAH_Rates_All_Locations_All_Pay_Grades/ASCII/.
          The year is detected from the member filenames, so the script is not
          hard-coded to 2026. Superseded "... - old" and ".dat" members are
          ignored; the canonical ".txt" members are used.

Members consumed (per the release's ASCII-FILE-FORMAT.pdf):
  sorted_zipmhaYY.txt  single-space delimited:  ZIPCODE(5)  MHA(5)
  mhanamesYY.txt       semicolon delimited:     MHA(5) ; NAME(40)
  bahwYY.txt           comma delimited:  MHA(5), <27 pay-grade rates>  (with deps)
  bahwoYY.txt          comma delimited:  MHA(5), <27 pay-grade rates>  (without)

------------------------------------------------------------------------------
Output (written to --out)
------------------------------------------------------------------------------
  zip_mha.csv      zip, mha, mha_class              (full crosswalk, nothing dropped)
  zip_mha_geo.csv  zip, mha                         (real MHAs only; feeds build_mha_geometry.py)
  mha_names.csv    mha, name, mha_class
  bah_rates.csv    mha, pay_grade, has_dependents, monthly_rate   (tidy/long)
  manifest.json    source + year + row counts + class breakdown + schema + warnings

------------------------------------------------------------------------------
MHA classes
------------------------------------------------------------------------------
  mha      real Military Housing Area (ZIP-defined, geometry-eligible)
  ccg      County Cost Group placeholder (code ZZ###); has rates, no ZIP polygon
  unknown  territory / unresolved bucket (code XX###, e.g. Puerto Rico); no rate
"""

import argparse
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Pay-grade columns of the rate files, in file order. The release's 2003-era
# ASCII-FILE-FORMAT.pdf documents O1-O7 (24 grades); the modern files carry 27,
# extending through O10 (the top grades plateau at the O-cap). Validated against
# the field count at run time -- if a future release changes this, the script
# stops rather than mislabel a column.
PAY_GRADES = [
    "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9",
    "W1", "W2", "W3", "W4", "W5",
    "O1E", "O2E", "O3E",
    "O1", "O2", "O3", "O4", "O5", "O6", "O7", "O8", "O9", "O10",
]

SOURCE = "U.S. DoD Defense Travel Management Office (DTMO), BAH ASCII release"

# Canonical members we want (year-agnostic); excludes "... - old" and ".dat".
MEMBER_PATTERNS = {
    "crosswalk": re.compile(r"^sorted_zipmha(\d{2})\.txt$", re.I),
    "names":     re.compile(r"^mhanames(\d{2})\.txt$", re.I),
    "rates_w":   re.compile(r"^bahw(\d{2})\.txt$", re.I),
    "rates_wo":  re.compile(r"^bahwo(\d{2})\.txt$", re.I),
}


def classify(code: str) -> str:
    c = code.upper()
    if c.startswith("ZZ"):
        return "ccg"
    if c.startswith("XX"):
        return "unknown"
    return "mha"


def _read_member(zf: zipfile.ZipFile, name: str) -> str:
    # Decode latin-1 (safe for this ASCII data) and normalise CRLF.
    return zf.read(name).decode("latin-1").replace("\r\n", "\n")


def _locate_members(zf: zipfile.ZipFile) -> tuple[dict, str]:
    found, year = {}, None
    for info in zf.infolist():
        base = Path(info.filename).name
        for key, pat in MEMBER_PATTERNS.items():
            m = pat.fullmatch(base)
            if m and key not in found:      # first canonical match wins
                found[key] = info.filename
                year = year or m.group(1)
    missing = [k for k in MEMBER_PATTERNS if k not in found]
    if missing:
        raise SystemExit(f"Zip is missing expected members: {missing}")
    return found, year


def parse_crosswalk(text: str) -> pd.DataFrame:
    df = pd.read_csv(
        io.StringIO(text), sep=r"\s+", header=None,
        names=["zip", "mha"], dtype=str, engine="python",
    )
    df["zip"] = df["zip"].str.strip().str.zfill(5)
    df["mha"] = df["mha"].str.strip().str.upper()
    df["mha_class"] = df["mha"].map(classify)
    return df


def parse_names(text: str) -> pd.DataFrame:
    df = pd.read_csv(
        io.StringIO(text), sep=";", header=None,
        names=["mha", "name"], dtype=str,
    )
    df["mha"] = df["mha"].str.strip().str.upper()
    df["name"] = df["name"].str.strip()
    df["mha_class"] = df["mha"].map(classify)
    return df


def parse_rates(text: str, has_deps: bool) -> pd.DataFrame:
    wide = pd.read_csv(
        io.StringIO(text), header=None,
        names=["mha"] + PAY_GRADES, dtype={"mha": str},
    )
    ncols = wide.shape[1] - 1
    if ncols != len(PAY_GRADES):
        raise SystemExit(
            f"Rate file has {ncols} pay-grade columns; script expects "
            f"{len(PAY_GRADES)}. The release schema changed -- update PAY_GRADES."
        )
    wide["mha"] = wide["mha"].str.strip().str.upper()
    long = wide.melt(id_vars="mha", var_name="pay_grade", value_name="monthly_rate")
    long["has_dependents"] = has_deps
    return long


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest a DTMO BAH-ASCII zip into tidy CSVs.")
    ap.add_argument("--zip", required=True, help="Path to BAH-ASCII-YYYY.zip")
    ap.add_argument("--out", default="./out", help="Output directory")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    with zipfile.ZipFile(args.zip) as zf:
        members, yy = _locate_members(zf)
        crosswalk = parse_crosswalk(_read_member(zf, members["crosswalk"]))
        names = parse_names(_read_member(zf, members["names"]))
        rates = pd.concat([
            parse_rates(_read_member(zf, members["rates_w"]), True),
            parse_rates(_read_member(zf, members["rates_wo"]), False),
        ], ignore_index=True)

    source_year = 2000 + int(yy)

    # --- integrity checks (reported, not fatal) ---
    dupes = int(crosswalk.duplicated(subset="zip").sum())
    if dupes:
        warnings.append(f"{dupes} duplicate ZIPs in crosswalk; keeping first occurrence.")
        crosswalk = crosswalk.drop_duplicates(subset="zip", keep="first")

    cw_codes, name_codes = set(crosswalk["mha"]), set(names["mha"])
    orphan_cw = cw_codes - name_codes
    if orphan_cw:
        warnings.append(f"{len(orphan_cw)} crosswalk MHA codes absent from mhanames.")
    rate_codes = set(rates["mha"])
    named_no_rate = {c for c in name_codes if c not in rate_codes and classify(c) != "unknown"}
    if named_no_rate:
        warnings.append(f"{len(named_no_rate)} non-unknown MHAs lack a rate row.")

    # --- write outputs ---
    crosswalk[["zip", "mha", "mha_class"]].to_csv(out / "zip_mha.csv", index=False)
    (crosswalk.loc[crosswalk["mha_class"] == "mha", ["zip", "mha"]]
        .to_csv(out / "zip_mha_geo.csv", index=False))
    names[["mha", "name", "mha_class"]].to_csv(out / "mha_names.csv", index=False)
    rates[["mha", "pay_grade", "has_dependents", "monthly_rate"]].to_csv(
        out / "bah_rates.csv", index=False)

    class_counts = crosswalk["mha_class"].value_counts().to_dict()
    manifest = {
        "source": SOURCE,
        "source_artifact": Path(args.zip).name,
        "source_year": source_year,
        "ingested_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pay_grade_schema": PAY_GRADES,
        "counts": {
            "crosswalk_zips": int(len(crosswalk)),
            "distinct_mha_codes": int(crosswalk["mha"].nunique()),
            "real_mhas": int(names.loc[names["mha_class"] == "mha", "mha"].nunique()),
            "ccg_codes": int(names.loc[names["mha_class"] == "ccg", "mha"].nunique()),
            "unknown_codes": int(names.loc[names["mha_class"] == "unknown", "mha"].nunique()),
            "zips_by_class": {k: int(v) for k, v in class_counts.items()},
            "rate_rows": int(len(rates)),
        },
        "outputs": ["zip_mha.csv", "zip_mha_geo.csv", "mha_names.csv", "bah_rates.csv"],
        "warnings": warnings,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"Ingested {SOURCE} {source_year}")
    print(f"  crosswalk ZIPs:   {manifest['counts']['crosswalk_zips']:,}")
    print(f"  real MHAs:        {manifest['counts']['real_mhas']}  "
          f"(+{manifest['counts']['ccg_codes']} CCG, "
          f"{manifest['counts']['unknown_codes']} unknown)")
    print(f"  rate rows (long): {manifest['counts']['rate_rows']:,}")
    print(f"  ZIPs by class:    {manifest['counts']['zips_by_class']}")
    for w in warnings:
        print(f"  WARNING: {w}")
    print(f"  -> {out}/  (4 CSVs + manifest.json)")


if __name__ == "__main__":
    main()
