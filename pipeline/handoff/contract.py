"""
contract.py — the Layer 2 -> Layer 3 data contract (docs/data-contract.md) in code.

Every handoff builder (B20, B21, B22, B27) and the validator import their names,
codes and rounding rules from here, so the files and the checks cannot drift
apart. When the ICD changes, this module changes in the same commit, and
SCHEMA_VERSION follows the ICD's versioning rules (section 10).

Stdlib only.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

SCHEMA_VERSION = "1.0.3"
CODE = re.compile(r"^[A-Z]{2}[0-9]{3}$")
CLASSES = ("mha", "ccg", "unknown")
MODES = ("rent", "buy")

# ICD 5.3: value-block fields, by kind, in the order they are written.
DOLLAR_FIELDS = {"bah_monthly", "cost_share_monthly", "cost_monthly", "design_gap_usd", "surplus_usd",
                 "safmr_monthly", "safmr_design_gap_usd", "own_housing_monthly"}
RATIO_FIELDS = {"adequacy_ratio", "coverage_ratio", "design_coverage", "flat95_gap", "safmr_adequacy_ratio"}
COMMON_FIELDS = ["bah_monthly", "cost_share_monthly", "cost_monthly", "adequacy_ratio", "design_gap_usd",
                 "coverage_ratio", "design_coverage", "surplus_usd", "flat95_gap"]
MODE_FIELDS = {
    "rent": COMMON_FIELDS + ["safmr_monthly", "safmr_adequacy_ratio", "safmr_design_gap_usd"],
    "buy": COMMON_FIELDS + ["own_housing_monthly"],
}

# ICD 5.4: status codes by mode, and which fields may be non-null under each.
STATUSES = {
    "rent": ("ok", "no_zori", "ccg_no_benchmark", "no_rate"),
    "buy": ("ok", "piti_only_no_zori", "no_home_value", "ccg_no_benchmark", "no_rate"),
}
ALL_STATUSES = ("ok", "no_zori", "piti_only_no_zori", "no_home_value", "ccg_no_benchmark", "no_rate")
NON_NULL = {
    "ok": "all",
    "piti_only_no_zori": "all",
    "no_zori": {"bah_monthly", "cost_share_monthly", "safmr_monthly", "safmr_adequacy_ratio",
                "safmr_design_gap_usd"},
    "no_home_value": {"bah_monthly", "cost_share_monthly"},
    "ccg_no_benchmark": {"bah_monthly", "cost_share_monthly"},
    "no_rate": set(),
}

# ICD 5.5: caveat ids and the level each is attached at.
CAVEATS = {
    "ccg_geometry": "area",
    "outside_cluster_scope": "area",
    "ccg_no_benchmark": "row",
    "utilities_grossed_up": "row",
    "piti_only_no_zori": "row",
    "tax_insurance_locality": "row",
    "tax_state_fallback": "row",
    "insurance_state_fallback": "row",
    "insurance_2022_dollars": "row",
    "lisa_exploratory": "overlay",
}

# ICD 7: the hotspot overlay.
B27_VARIABLE = "adequacy_gap"
CLUSTER_CODES = ("HH", "LL", "HL", "LH", "NS")
GI_CLASSES = ("hot", "cold", "ns")
B27_STATUSES = ("tested", "no_value")
P_PLACES = 5          # p-values: the 99,999-permutation resolution is 0.00001 (ICD 1.0.2)
RATIO_PLACES = 4

# ICD 2: the delivered files, by node.
def file_names(year: int) -> dict[str, str]:
    return {"B7": f"areas_{year}.pmtiles", "B20": f"payload_{year}.json", "B21": f"ui_metadata_{year}.json",
            "B27": f"hotspots_{year}.json", "B22": f"build_manifest_{year}.json"}


# --- rounding (ICD 3) -------------------------------------------------------

def _dec(raw: object) -> Decimal | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError(f"{raw!r} is not a number")


def dollars(raw: object) -> int | None:
    """Whole dollars, half away from zero."""
    d = _dec(raw)
    return None if d is None else int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ratio(raw: object, places: int = RATIO_PLACES) -> float | None:
    """A plain decimal rounded to `places`, half away from zero."""
    d = _dec(raw)
    return None if d is None else float(d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def decimals_of(x: float) -> int:
    """Decimal places in the shortest repr of a float (0.744 -> 3)."""
    s = repr(float(x))
    if "e" in s or "E" in s:
        return len(f"{x:.12f}".rstrip("0").split(".")[1])
    return len(s.split(".")[1].rstrip("0")) if "." in s else 0


# --- small I/O helpers -------------------------------------------------------

def die(tool: str, msg: str) -> None:
    sys.exit(f"{tool}: {msg}")


def fail_if(problems: list[str], tool: str) -> None:
    if problems:
        print(f"{tool}: FAILED", file=sys.stderr)
        for p in problems[:40]:
            print(f"  - {p}", file=sys.stderr)
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more", file=sys.stderr)
        sys.exit(1)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_csv(path: Path, needed: set[str], tool: str) -> list[dict]:
    if not path.exists():
        die(tool, f"not found: {path}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not needed <= set(reader.fieldnames):
            die(tool, f"{path.name} needs {sorted(needed)}; found {reader.fieldnames}")
        return list(reader)


def read_json(path: Path, tool: str) -> object:
    if not path.exists():
        die(tool, f"not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(tool, f"{path} is not valid JSON: {e}")


def write_json(path: Path, data: object) -> None:
    """Compact, key order as built, UTF-8, one trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def header(build_manifest: Path, year: int) -> dict:
    """The three fields every handoff JSON file starts with."""
    return {"schema_version": SCHEMA_VERSION, "bah_year": year, "build_id": sha256(build_manifest)}
