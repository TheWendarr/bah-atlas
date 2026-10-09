#!/usr/bin/env python3
"""
zillow_to_mha.py  (A3 -> B8 ZORI at MHA, utilities-adjusted;  A4 -> B9 ZHVI at MHA)

Translate a Zillow ZIP-level research CSV (ZORI rent or ZHVI home value) into one
benchmark value per Military Housing Area, over a pinned time window aligned to
the BAH year.

    # B8: ZORI, grossed up to utilities-inclusive with B5
    python pipeline/benchmarks/zillow_to_mha.py --series zori \
        --csv data/raw/Zip_zori_uc_sfrcondomfr_sm_month.csv \
        --crosswalk data/interim/bah_2026/zip_mha.csv \
        --rate-components data/interim/bah_2026/rate_components.csv \
        --out data/interim/benchmarks_2026

    # B9: ZHVI
    python pipeline/benchmarks/zillow_to_mha.py --series zhvi \
        --csv data/raw/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv \
        --crosswalk data/interim/bah_2026/zip_mha.csv \
        --out data/interim/benchmarks_2026

------------------------------------------------------------------------------
Input layout (Zillow research CSVs, "wide")
------------------------------------------------------------------------------
  RegionID, SizeRank, RegionName (ZIP; may have lost leading zeros), RegionType
  ("zip"), StateName, State, City, Metro, CountyName, then one column per month
  named YYYY-MM-DD (month-end date). Blank cell = no estimate that month.

------------------------------------------------------------------------------
Method
------------------------------------------------------------------------------
  1. Time window. Default: the calendar year of the BAH release (A12 bah_year),
     i.e. 2026-01:2026-12, using whichever of those months the file contains.
     BAH 2026 is paid from 1 Jan to 31 Dec 2026, so the benchmark is what housing
     cost in the same months members drew that BAH. Override with --window.
  2. ZIP value = mean of that ZIP's non-blank months inside the window. A ZIP
     needs at least --min-months observations (default 3) to count.
  3. MHA value = median across its ZIPs (see mha_agg.py for the rule).
  4. B8 only: ZORI is asking rent WITHOUT utilities, while BAH's ~95% target
     covers rent PLUS utilities. B5 gives each MHA's rent share s_r of total BAH
     (DTMO's published split), so the utilities-inclusive benchmark is

         zori_utilities_adjusted = zori_median / s_r
         utilities_usd           = zori_utilities_adjusted - zori_median

     Dividing by the share uses only DTMO's cost structure, never the BAH dollar
     amount, so the benchmark stays independent of the BAH numerator it is
     compared with. Shares are rounded to 1% at source (about +/-0.5 pp).

------------------------------------------------------------------------------
Output (written to --out)
------------------------------------------------------------------------------
  zip_<series>.csv            zip, mha, value, months_used      (ZIPs in real MHAs)
  mha_<series>.csv            mha, n_zips, n_zips_with_data, zip_coverage,
                              <series>_median, _mean, _min, _max
                              [+ rent_share, zori_utilities_adjusted, utilities_usd for B8]
  mha_<series>_manifest.json  source, sha256, window and months used, counts,
                              MHAs without data, warnings

------------------------------------------------------------------------------
Validation (loud)
------------------------------------------------------------------------------
  * required Zillow columns present; at least one YYYY-MM-DD month column
  * every row is RegionType "zip"; ZIPs are 1-5 digits; no repeated ZIP
  * the window holds at least --min-months of the file's months
  * every value is inside a plausible range for the series
  * B8: every real MHA has a B5 rent share in (0, 1]
"""

from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mha_agg as agg  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TOOL = "zillow_to_mha"
MONTH_COL = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
REQUIRED = {"RegionName", "RegionType"}

SERIES = {
    "zori": {
        "node": "B8", "source_node": "A3",
        "source": "Zillow Observed Rent Index (ZORI), all homes plus multifamily, smoothed, ZIP level",
        "unit": "USD per month (asking rent, excludes utilities)",
        "range": (100.0, 50_000.0),
    },
    "zhvi": {
        "node": "B9", "source_node": "A4",
        "source": "Zillow Home Value Index (ZHVI), SFR+condo, mid tier (33rd-67th pct), smoothed and seasonally adjusted, ZIP level",
        "unit": "USD (typical home value)",
        "range": (1_000.0, 50_000_000.0),
    },
}


def read_zillow(path: Path, window: tuple[str, str], min_months: int,
                lo: float, hi: float) -> tuple[dict[str, float], dict[str, int], list[str], list[str], int]:
    """Return ({zip: window mean}, {zip: months used}, months in window, problems, ZIPs too short)."""
    problems: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            agg.die(TOOL, f"{path} is empty")
        if header and header[0].lstrip().startswith("<"):
            agg.die(TOOL, f"{path} looks like HTML, not a Zillow CSV (re-run `make fetch`)")
        missing = REQUIRED - set(header)
        if missing:
            agg.die(TOOL, f"{path.name} lacks columns {sorted(missing)}; header starts {header[:10]}")
        month_idx = {i: h[:7] for i, h in enumerate(header) if MONTH_COL.match(h)}
        if not month_idx:
            agg.die(TOOL, f"{path.name} has no YYYY-MM-DD month columns; header starts {header[:12]}")
        in_window = {i: ym for i, ym in month_idx.items() if window[0] <= ym <= window[1]}
        if len(in_window) < min_months:
            all_months = sorted(month_idx.values())
            agg.die(TOOL, f"window {window[0]}:{window[1]} holds {len(in_window)} month(s) of "
                          f"{path.name} (file spans {all_months[0]} to {all_months[-1]}); "
                          f"need at least {min_months}. Re-pull the source or pass --window.")
        i_name, i_type = header.index("RegionName"), header.index("RegionType")

        values: dict[str, float] = {}
        used: dict[str, int] = {}
        short = 0
        for line_no, row in enumerate(reader, start=2):
            if not row or not any(c.strip() for c in row):
                continue
            if row[i_type].strip().lower() != "zip":
                problems.append(f"line {line_no}: RegionType {row[i_type]!r}, expected 'zip'")
                continue
            z = agg.zip5(row[i_name])
            if z is None:
                problems.append(f"line {line_no}: malformed ZIP {row[i_name]!r}")
                continue
            if z in values or z in used:
                problems.append(f"ZIP {z} appears more than once")
                continue
            obs = []
            for i in in_window:
                cell = row[i].strip() if i < len(row) else ""
                if not cell:
                    continue
                try:
                    v = float(cell)
                except ValueError:
                    problems.append(f"line {line_no}: non-numeric value {cell!r} in {header[i]}")
                    continue
                if not lo <= v <= hi:
                    problems.append(f"ZIP {z} {header[i]}: {v:,.0f} outside plausible range {lo:,.0f}-{hi:,.0f}")
                    continue
                obs.append(v)
            if len(obs) >= min_months:
                values[z] = statistics.fmean(obs)
                used[z] = len(obs)
            else:
                used[z] = len(obs)    # remembered so duplicates are still caught
                short += 1
    used = {z: n for z, n in used.items() if z in values}
    return values, used, sorted(in_window.values()), problems, short


def load_rent_shares(path: Path) -> dict[str, float]:
    if not path.exists():
        agg.die(TOOL, f"rate components not found: {path} (run `make components` for B5)")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not {"mha", "rent_share"} <= set(reader.fieldnames):
            agg.die(TOOL, f"{path} needs mha and rent_share columns; found {reader.fieldnames}")
        return {r["mha"].strip().upper(): float(r["rent_share"]) for r in reader}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", choices=sorted(SERIES), required=True)
    ap.add_argument("--csv", type=Path, required=True, help="Zillow ZIP-level research CSV")
    ap.add_argument("--crosswalk", type=Path, required=True, help="B1 zip_mha.csv")
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    ap.add_argument("--rate-components", type=Path, help="B5 rate_components.csv (required for zori)")
    ap.add_argument("--window", help="YYYY-MM:YYYY-MM (default: BAH year from config/profiles.json)")
    ap.add_argument("--min-months", type=int, default=3, help="minimum months per ZIP (default 3)")
    ap.add_argument("--profiles", type=Path, default=ROOT / "config" / "profiles.json")
    args = ap.parse_args()

    spec = SERIES[args.series]
    if args.series == "zori" and not args.rate_components:
        agg.die(TOOL, "B8 is the utilities-adjusted ZORI: pass --rate-components (B5 rate_components.csv)")
    if not args.csv.exists():
        agg.die(TOOL, f"input not found: {args.csv} (run `make fetch`)")
    window_spec = args.window or agg.default_window(args.profiles)
    try:
        window = agg.parse_window(window_spec)
    except ValueError as e:
        agg.die(TOOL, str(e))

    crosswalk, cw_stats = agg.load_crosswalk(args.crosswalk, TOOL)
    lo, hi = spec["range"]
    print(f"{spec['node']} {args.series.upper()} at MHA: reading {args.csv.name}")
    zip_values, months_used, window_months, problems, short = read_zillow(args.csv, window, args.min_months, lo, hi)
    agg.fail_if(problems[:25] + ([f"... and {len(problems) - 25} more"] if len(problems) > 25 else []), TOOL)

    rows, agg_stats = agg.aggregate(zip_values, crosswalk)
    warnings: list[str] = []
    if short:
        warnings.append(f"{short} ZIP(s) had fewer than {args.min_months} months in the window and were left out")
    if agg_stats["mhas_with_data"] < 0.5 * len(rows):
        warnings.append(f"only {agg_stats['mhas_with_data']} of {len(rows)} MHAs have {args.series.upper()} data")

    s = args.series
    out_rows: list[dict] = []
    for r in rows:
        out = {
            "mha": r["mha"], "n_zips": r["n_zips"], "n_zips_with_data": r["n_zips_with_data"],
            "zip_coverage": f"{r['zip_coverage']:.4f}",
            f"{s}_median": agg.fmt(r["median"]), f"{s}_mean": agg.fmt(r["mean"]),
            f"{s}_min": agg.fmt(r["min"]), f"{s}_max": agg.fmt(r["max"]),
        }
        out_rows.append(out)
    fields = ["mha", "n_zips", "n_zips_with_data", "zip_coverage",
              f"{s}_median", f"{s}_mean", f"{s}_min", f"{s}_max"]

    adjust_note = None
    if s == "zori":
        shares = load_rent_shares(args.rate_components)
        bad = [m for m in (r["mha"] for r in rows) if not 0 < shares.get(m, 0) <= 1]
        agg.fail_if([f"{len(bad)} real MHA(s) lack a valid B5 rent_share: {', '.join(bad[:10])}"] if bad else [], TOOL)
        for r, out in zip(rows, out_rows):
            share = shares[r["mha"]]
            out["rent_share"] = f"{share:.4f}"
            if r["median"] is None:
                out["zori_utilities_adjusted"] = out["utilities_usd"] = ""
            else:
                adj = r["median"] / share
                out["zori_utilities_adjusted"] = agg.fmt(adj)
                out["utilities_usd"] = agg.fmt(adj - r["median"])
        fields += ["rent_share", "zori_utilities_adjusted", "utilities_usd"]
        adjust_note = ("zori_utilities_adjusted = zori_median / rent_share (B5, DTMO component split). "
                       "Uses DTMO's cost structure, not the BAH dollar amount. Shares rounded to 1% at source.")

    zip_rows = [{"zip": z, "mha": crosswalk[z], "value": agg.fmt(v), "months_used": months_used[z]}
                for z, v in sorted(zip_values.items()) if z in crosswalk]
    agg.write_csv(args.out / f"zip_{s}.csv", ["zip", "mha", "value", "months_used"], zip_rows)
    agg.write_csv(args.out / f"mha_{s}.csv", fields, out_rows)

    medians = [r["median"] for r in rows if r["median"] is not None]
    manifest = {
        "node": spec["node"],
        "source_node": spec["source_node"],
        "source": spec["source"],
        "unit": spec["unit"],
        "input_file": args.csv.name,
        "input_sha256": agg.sha256(args.csv),
        "generated_at": agg.now_utc(),
        "window_requested": f"{window[0]}:{window[1]}",
        "window_months_used": window_months,
        "min_months_per_zip": args.min_months,
        "aggregation": "median of ZIP window-means across the MHA's ZIPs (unweighted); real MHAs only",
        "utilities_adjustment": adjust_note,
        "crosswalk": cw_stats,
        "coverage": agg_stats,
        "mha_median_summary": ({"min": round(min(medians), 2), "median": round(statistics.median(medians), 2),
                                "max": round(max(medians), 2)} if medians else None),
        "warnings": warnings,
        "outputs": [f"zip_{s}.csv", f"mha_{s}.csv"],
    }
    agg.write_manifest(args.out / f"mha_{s}_manifest.json", manifest)

    print(f"  window {window_months[0]} to {window_months[-1]} ({len(window_months)} months)")
    print(f"  {len(zip_values):,} ZIPs with data; {agg_stats['source_zips_in_real_mhas']:,} fall in real MHAs")
    print(f"  {agg_stats['mhas_with_data']} of {len(rows)} MHAs have data; "
          f"median ZIP coverage {agg_stats['median_zip_coverage']:.0%}")
    if medians:
        print(f"  MHA {s.upper()} median: min {min(medians):,.0f} / median "
              f"{statistics.median(medians):,.0f} / max {max(medians):,.0f}")
    for w in warnings:
        print(f"  warning: {w}")
    print(f"  -> {args.out / f'mha_{s}.csv'}")


if __name__ == "__main__":
    main()
