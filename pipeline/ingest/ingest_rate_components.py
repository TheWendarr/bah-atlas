#!/usr/bin/env python3
"""
ingest_rate_components.py  (A6 -> B5)

Translate the DTMO "BAH Rate Component Breakdown" PDF into a tidy per-MHA table
of rent vs utilities shares, plus a provenance manifest.

Why this node exists: Zillow ZORI (A3) measures rent only, while BAH's ~95%
coverage target is set against rent PLUS utilities. B5 supplies each MHA's
utilities share so B8 can gross ZORI up to a utilities-inclusive benchmark:

    utilities_inclusive_rent = zori_rent / rent_share

------------------------------------------------------------------------------
Input
------------------------------------------------------------------------------
  --pdf   2026-BAH-Rate-Component-Breakdown.pdf exactly as published by DTMO
          (fetched as data/raw/dod_bah_rate_components_2026.pdf by `make fetch`).
          One row per MHA: "AK400 KETCHIKAN, AK 79% 21%" =
          code, name, rent (avg % of total BAH), utilities (avg % of total BAH).
  --text  Alternative to --pdf: a text dump, e.g. `pdftotext -layout in.pdf out.txt`.
          Use it if the PDF's text layer extracts out of order.

  Text is extracted with pypdf when installed, else with poppler's `pdftotext`.

------------------------------------------------------------------------------
Output (written to --out)
------------------------------------------------------------------------------
  rate_components.csv            mha, name, rent_pct, utilities_pct, rent_share, utilities_share
  rate_components_manifest.json  source, sha256, row count, validation results

------------------------------------------------------------------------------
Validation (loud)
------------------------------------------------------------------------------
  * MHA codes match two letters + three digits and are unique
  * rent_pct + utilities_pct is within 100 +/- 1 (the source rounds to 1%)
  * row count equals --expect (default 299, the 2026 MHA count)
  * with --mha-names (B3), every parsed code must be a real MHA in that list,
    and every real MHA must appear in the PDF

Shares are renormalised to sum to exactly 1.0, because the source percentages
are rounded independently. Precision is therefore about +/-0.5 percentage points
per MHA; carry that as a stated limitation of the utilities adjustment.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROW = re.compile(
    r"(?<![A-Z0-9])(?P<mha>[A-Z]{2}\d{3})\s+"     # MHA code
    r"(?P<name>[^%\n]+?)\s+"                        # name (no % or newline)
    r"(?P<rent>\d{1,3})\s*%\s+"                     # rent %
    r"(?P<util>\d{1,3})\s*%"                        # utilities %
)
MHA_CODE = re.compile(r"^[A-Z]{2}\d{3}$")
SOURCE = "U.S. DoD Defense Travel Management Office (DTMO), BAH Rate Component Breakdown"


def die(msg: str) -> None:
    sys.exit(f"ingest_rate_components: {msg}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def pdf_text(pdf: Path) -> tuple[str, str]:
    """Return (text, extractor) using pypdf if available, else pdftotext."""
    try:
        from pypdf import PdfReader
    except ImportError:
        PdfReader = None
    if PdfReader is not None:
        reader = PdfReader(str(pdf))
        return "\n".join((page.extract_text() or "") for page in reader.pages), "pypdf"
    if shutil.which("pdftotext"):
        out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                             check=True, capture_output=True, text=True)
        return out.stdout, "pdftotext -layout"
    die("no PDF text extractor: `pip install pypdf` (in requirements.txt) "
        "or install poppler-utils for `pdftotext`")
    raise AssertionError  # unreachable


def parse(text: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for m in ROW.finditer(text):
        code = m["mha"]
        if code in seen:
            die(f"MHA {code} appears twice in the source text")
        seen.add(code)
        rent, util = int(m["rent"]), int(m["util"])
        rows.append({
            "mha": code,
            "name": " ".join(m["name"].split()),
            "rent_pct": rent,
            "utilities_pct": util,
        })
    return rows


def load_real_mhas(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    if not rows or "mha" not in rows[0]:
        die(f"{path} has no 'mha' column")
    keep = set()
    for r in rows:
        code = (r.get("mha") or "").strip().upper()
        cls = (r.get("mha_class") or "").strip().lower()
        if MHA_CODE.match(code) and cls in ("", "mha", "real"):
            keep.add(code)
    return keep


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pdf", type=Path, help="DTMO component breakdown PDF")
    src.add_argument("--text", type=Path, help="pre-extracted text of the PDF")
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    ap.add_argument("--year", type=int, default=None, help="BAH year (default: detected from filename)")
    ap.add_argument("--expect", type=int, default=299, help="expected MHA rows (default 299)")
    ap.add_argument("--mha-names", type=Path, help="B3 mha_names.csv to cross-check codes")
    args = ap.parse_args()

    in_path = args.pdf or args.text
    if not in_path.exists():
        die(f"input not found: {in_path} (run `make fetch` to download A6)")
    if args.pdf:
        with in_path.open("rb") as fh:
            if not fh.read(5).startswith(b"%PDF"):
                die(f"{in_path} is not a PDF (missing %PDF header)")
        text, extractor = pdf_text(in_path)
    else:
        text, extractor = in_path.read_text(encoding="utf-8", errors="replace"), "pre-extracted text"

    year = args.year
    if year is None:
        m = re.search(r"(20\d{2})", in_path.name)
        year = int(m.group(1)) if m else None

    rows = parse(text)
    problems: list[str] = []
    warnings: list[str] = []

    if not rows:
        die("no MHA rows found. If this is the right PDF, its text layer may extract "
            "out of order: run `pdftotext -layout <pdf> out.txt` and pass --text out.txt")

    for r in rows:
        total = r["rent_pct"] + r["utilities_pct"]
        if abs(total - 100) > 1:
            problems.append(f"{r['mha']}: rent {r['rent_pct']}% + utilities {r['utilities_pct']}% = {total}%")
        r["rent_share"] = round(r["rent_pct"] / total, 4)
        r["utilities_share"] = round(1 - r["rent_share"], 4)

    if len(rows) != args.expect:
        problems.append(f"parsed {len(rows)} MHA rows; expected {args.expect}")

    if args.mha_names:
        real = load_real_mhas(args.mha_names)
        parsed = {r["mha"] for r in rows}
        extra, missing = sorted(parsed - real), sorted(real - parsed)
        if extra:
            problems.append(f"{len(extra)} code(s) not in {args.mha_names.name}: {', '.join(extra[:10])}")
        if missing:
            problems.append(f"{len(missing)} real MHA(s) missing from the PDF: {', '.join(missing[:10])}")
    else:
        warnings.append("no --mha-names given; codes not cross-checked against B3")

    if problems:
        print("Validation failed:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)

    args.out.mkdir(parents=True, exist_ok=True)
    out_csv = args.out / "rate_components.csv"
    fields = ["mha", "name", "rent_pct", "utilities_pct", "rent_share", "utilities_share"]
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["mha"]))

    shares = [r["utilities_share"] for r in rows]
    manifest = {
        "node": "B5",
        "source_node": "A6",
        "source": SOURCE,
        "bah_year": year,
        "input_file": in_path.name,
        "input_sha256": sha256(in_path),
        "text_extractor": extractor,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": len(rows),
        "utilities_share": {"min": min(shares), "max": max(shares),
                            "mean": round(sum(shares) / len(shares), 4)},
        "precision_note": "Source percentages are rounded to 1%; shares renormalised to sum to 1.",
        "warnings": warnings,
        "outputs": [out_csv.name],
    }
    (args.out / "rate_components_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"B5 rate components: {len(rows)} MHAs -> {out_csv}")
    print(f"  utilities share min {manifest['utilities_share']['min']:.2f} / "
          f"mean {manifest['utilities_share']['mean']:.2f} / max {manifest['utilities_share']['max']:.2f}")
    for w_ in warnings:
        print(f"  warning: {w_}")


if __name__ == "__main__":
    main()
