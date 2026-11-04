#!/usr/bin/env python3
"""
build_zip_lookup.py  (B1 + B22 -> B32 ZIP lookup)

The delivered file behind ZIP search (C15, data contract section 7b): every ZIP in
DTMO's crosswalk under its area code. Grouping by area makes the file about half
the size of a flat ZIP-to-code map.

    python pipeline/handoff/build_zip_lookup.py --year 2026 \
        --zip-mha data/interim/bah_2026/zip_mha.csv \
        --build-manifest data/processed/handoff/build_manifest_2026.json \
        --out data/processed/handoff/zips_2026.json

Stops on a malformed ZIP or area code, or a ZIP listed twice. Stdlib only.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import contract as c

TOOL = "build_zip_lookup"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--zip-mha", type=Path, required=True, help="B1 zip_mha.csv")
    ap.add_argument("--build-manifest", type=Path, required=True, help="B22, whose hash is the build_id")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    rows = c.read_csv(args.zip_mha, {"zip", "mha"}, TOOL)
    areas: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    problems: list[str] = []
    for r in rows:
        code, zip_code = r["mha"], r["zip"]
        if not c.ZIP.match(zip_code) or not c.CODE.match(code):
            problems.append(f"malformed row: ZIP {zip_code!r}, area {code!r}")
        if zip_code in seen:
            problems.append(f"ZIP {zip_code} is listed twice")
        seen.add(zip_code)
        areas[code].append(zip_code)
    c.fail_if(problems, TOOL)

    c.write_json(args.out, {**c.header(args.build_manifest, args.year),
                            "areas": {code: sorted(areas[code]) for code in sorted(areas)}})
    print(f"B32 ZIP lookup: {len(seen):,} ZIPs in {len(areas)} areas")
    print(f"  {args.out.stat().st_size / 1024:.0f} KB -> {args.out}")


if __name__ == "__main__":
    main()
