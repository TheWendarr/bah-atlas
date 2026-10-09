"""
mha_agg.py — shared helpers for the 2.3 / 2.4 benchmark nodes (B8-B11).

Every benchmark source in Layer 1 is keyed by ZIP (Zillow ZORI/ZHVI, HUD SAFMR).
BAH is keyed by MHA. This module owns the one step they all share: roll a
ZIP-level value up to the MHA through the DTMO crosswalk (B1), and say how much
of each MHA the value actually covers.

Aggregation rule (documented once, used everywhere):
  * Only real MHAs (mha_class == "mha", 299 in 2026) are aggregated. County Cost
    Groups (ZZ###) and the territory bucket (XX###) have no polygon and no B5
    rent/utilities split, so they are counted in the manifest and left out.
  * The MHA value is the MEDIAN of its ZIP values (the mean is carried alongside).
    No housing-unit weights are applied: ZIP-level household counts would come
    from ACS (A9, optional, not yet pulled). The median keeps one expensive or
    cheap ZIP from dragging a small MHA.
  * Every real MHA gets a row, including MHAs with no ZIP data at all (value
    blank, n_zips_with_data = 0). Missing coverage is a finding for the
    clustering question, so it is reported rather than dropped.

Stdlib only, so the aggregation logic has no third-party dependency.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

MHA_CODE = re.compile(r"^[A-Z]{2}\d{3}$")
YEAR_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def die(tool: str, msg: str) -> None:
    sys.exit(f"{tool}: {msg}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def zip5(raw: str) -> str | None:
    """Normalise a ZIP that may have lost its leading zeros ("501" -> "00501")."""
    s = str(raw).strip()
    if s.endswith(".0"):            # spreadsheet float artefact: 2108.0
        s = s[:-2]
    if not s.isdigit() or len(s) > 5:
        return None
    return s.zfill(5)


def parse_window(spec: str) -> tuple[str, str]:
    """'2026-01:2026-12' -> ('2026-01', '2026-12'); validates both ends."""
    try:
        start, end = spec.split(":")
    except ValueError:
        raise ValueError(f"window '{spec}' must look like YYYY-MM:YYYY-MM")
    for part in (start, end):
        m = YEAR_MONTH.match(part)
        if not m or not 1 <= int(m.group(2)) <= 12:
            raise ValueError(f"window end '{part}' is not YYYY-MM")
    if start > end:
        raise ValueError(f"window '{spec}' starts after it ends")
    return start, end


def default_window(profiles_path: Path) -> str:
    """The calendar year of the BAH release in config/profiles.json (A12)."""
    try:
        year = json.loads(profiles_path.read_text(encoding="utf-8"))["bah_year"]
    except (OSError, KeyError, json.JSONDecodeError):
        year = datetime.now(timezone.utc).year
    return f"{year}-01:{year}-12"


def load_crosswalk(path: Path, tool: str) -> tuple[dict[str, str], dict]:
    """Read B1 zip_mha.csv. Returns ({zip: mha} for real MHAs, stats)."""
    if not path.exists():
        die(tool, f"crosswalk not found: {path} (run `make ingest` first)")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not {"zip", "mha"} <= set(reader.fieldnames):
            die(tool, f"{path} needs zip and mha columns; found {reader.fieldnames}")
        rows = list(reader)
    real: dict[str, str] = {}
    skipped: dict[str, int] = {}
    for r in rows:
        z, mha = zip5(r["zip"]), r["mha"].strip().upper()
        cls = (r.get("mha_class") or "mha").strip().lower()
        if z is None:
            die(tool, f"crosswalk has a malformed ZIP: {r['zip']!r}")
        if cls != "mha" or not MHA_CODE.match(mha):
            skipped[cls] = skipped.get(cls, 0) + 1
            continue
        if z in real and real[z] != mha:
            die(tool, f"ZIP {z} maps to two MHAs ({real[z]}, {mha}) in {path.name}")
        real[z] = mha
    if not real:
        die(tool, f"no real-MHA rows in {path}")
    stats = {
        "crosswalk_file": path.name,
        "real_mha_zips": len(real),
        "real_mhas": len(set(real.values())),
        "zips_skipped_by_class": skipped,
    }
    return real, stats


def aggregate(zip_values: dict[str, float], crosswalk: dict[str, str]) -> tuple[list[dict], dict]:
    """Roll {zip: value} up to one row per real MHA.

    Returns (rows, stats). Each row: mha, n_zips, n_zips_with_data, zip_coverage,
    median, mean, min, max (value fields are None when the MHA has no data).
    """
    members: dict[str, list[str]] = {}
    for z, mha in crosswalk.items():
        members.setdefault(mha, []).append(z)

    rows: list[dict] = []
    for mha in sorted(members):
        zips = members[mha]
        vals = [zip_values[z] for z in zips if z in zip_values]
        rows.append({
            "mha": mha,
            "n_zips": len(zips),
            "n_zips_with_data": len(vals),
            "zip_coverage": round(len(vals) / len(zips), 4),
            "median": statistics.median(vals) if vals else None,
            "mean": statistics.fmean(vals) if vals else None,
            "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
        })

    matched = sum(1 for z in zip_values if z in crosswalk)
    stats = {
        "source_zips": len(zip_values),
        "source_zips_in_real_mhas": matched,
        "source_zips_outside_real_mhas": len(zip_values) - matched,
        "mhas_with_data": sum(1 for r in rows if r["n_zips_with_data"]),
        "mhas_without_data": [r["mha"] for r in rows if not r["n_zips_with_data"]],
        "median_zip_coverage": statistics.median(r["zip_coverage"] for r in rows),
    }
    return rows, stats


def fmt(v: float | None, places: int = 2) -> str:
    return "" if v is None else f"{v:.{places}f}"


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def fail_if(problems: list[str], tool: str) -> None:
    if problems:
        print(f"{tool}: validation failed:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)
