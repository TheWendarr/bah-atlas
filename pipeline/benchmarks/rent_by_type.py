#!/usr/bin/env python3
"""
rent_by_type.py  (B8 + B10 + A15 + A4 metro names + B1 + A14 -> B29 rent benchmark by home type)

Decision D19, option B: the rent benchmark for each of DoD's six housing profiles
in every MHA, so the map can show any rank in any home type (D18) and each
research profile can be measured against its own DoD standard.

    python pipeline/benchmarks/rent_by_type.py \
        --zori data/interim/benchmarks_2026/mha_zori.csv \
        --safmr data/interim/benchmarks_2026/mha_safmr.csv \
        --metro-sfr data/raw/Metro_zori_uc_sfr_sm_month.csv \
        --metro-mfr data/raw/Metro_zori_uc_mfr_sm_month.csv \
        --metro-all data/raw/Metro_zori_uc_sfrcondomfr_sm_month.csv \
        --zip-metro data/raw/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv \
        --crosswalk data/interim/bah_2026/zip_mha.csv \
        --out data/interim/benchmarks_2026

------------------------------------------------------------------------------
Method (per MHA m and home type t = building b, n bedrooms)
------------------------------------------------------------------------------
  rent(t)  = B8 zori_utilities_adjusted(m) x f_b(m) x s_n(m)

  f_b  building-type factor. B8 is the all-homes ZORI and stands for a 2 BR
       townhouse (A14 reference_type), so f = 1 for townhouses. For apartments
       and single-family homes it is the ratio of Zillow's multifamily or
       single-family ZORI to its all-homes ZORI, both over B8's months:
         Zillow publishes those two series at metro level only (A15), so each ZIP
         takes the ratio of its metro (the Metro column of the A4 ZIP file names
         it), and the MHA takes the median over its ZIPs (mha_agg rule). An MHA
         with no ZIP in a metro that has the series takes the national ratio
         (the A15 row with RegionType "country"); factor_source says which.
  s_n  bedroom ratio: HUD SAFMR n BR / 2 BR within the MHA (B10 medians).

  utilities_usd(t) = B8 utilities_usd(m) x f_b(m) x s_n(m)   (B30 adds these to PITI)

The 2-bedroom townhouse therefore equals B8 exactly in every MHA; the script
checks this and stops if it does not hold. An MHA with no B8 value (status
no_zori) has no value for any type.

------------------------------------------------------------------------------
Output (written to --out)
------------------------------------------------------------------------------
  mha_rent_by_type.csv            long: one row per MHA x home type
                                  mha, home_type, building, bedrooms, building_factor,
                                  factor_source (reference|metro|national), factor_zips,
                                  bedroom_ratio, rent_monthly, utilities_usd, status
  mha_rent_by_type_manifest.json  inputs and hashes, window, metro match counts,
                                  factor summaries, coverage by type, the B8 identity
                                  check, warnings

Stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import home_types as ht  # noqa: E402
import mha_agg as agg  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TOOL = "rent_by_type"
MONTH_COL = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
SERIES_FOR = {"apartment": "mfr", "single_family": "sfr"}
FACTOR_RANGE = (0.3, 3.0)        # a type ratio outside this is a units or join error
MIN_METRO_MATCH = 0.5            # share of metro-named MHA ZIPs whose metro must appear in A15


def read_metro(path: Path, window: tuple[str, str], min_months: int) -> tuple[dict[str, float], float | None, int]:
    """Window mean per metro name, the national ('country') value, and rows read."""
    if not path.exists():
        agg.die(TOOL, f"A15 file not found: {path} (run `make fetch`)")
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        if header and header[0].lstrip().startswith("<"):
            agg.die(TOOL, f"{path.name} looks like HTML, not a Zillow CSV (re-run `make fetch`)")
        if not {"RegionName", "RegionType"} <= set(header):
            agg.die(TOOL, f"{path.name} lacks RegionName/RegionType; header starts {header[:8]}")
        cols = [i for i, h in enumerate(header) if MONTH_COL.match(h) and window[0] <= h[:7] <= window[1]]
        if len(cols) < min_months:
            agg.die(TOOL, f"{path.name} has {len(cols)} month(s) in {window[0]}:{window[1]}; need {min_months}")
        i_name, i_type = header.index("RegionName"), header.index("RegionType")
        metros, national, n = {}, None, 0
        for row in reader:
            if not row:
                continue
            n += 1
            vals = [float(row[i]) for i in cols if i < len(row) and row[i].strip()]
            if len(vals) < min_months:
                continue
            mean = statistics.fmean(vals)
            kind = row[i_type].strip().lower()
            if kind == "country":
                national = mean
            elif kind == "msa":
                metros[row[i_name].strip()] = mean
    return metros, national, n


def read_zip_metro(path: Path, crosswalk: dict[str, str]) -> dict[str, str]:
    """{zip: metro name} for ZIPs in real MHAs, from the Metro column of a Zillow ZIP file."""
    if not path.exists():
        agg.die(TOOL, f"ZIP file for metro names not found: {path} (A4; run `make fetch`)")
    out = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not {"RegionName", "Metro"} <= set(reader.fieldnames):
            agg.die(TOOL, f"{path.name} needs RegionName and Metro columns; found {reader.fieldnames[:10] if reader.fieldnames else None}")
        for r in reader:
            z = agg.zip5(r["RegionName"])
            metro = (r.get("Metro") or "").strip()
            if z and z in crosswalk and metro:
                out[z] = metro
    return out


def b8_window(zori: Path) -> tuple[str, str]:
    man = zori.with_name("mha_zori_manifest.json")
    try:
        months = json.loads(man.read_text(encoding="utf-8"))["window_months_used"]
        return months[0], months[-1]
    except (OSError, KeyError, IndexError, json.JSONDecodeError):
        agg.die(TOOL, f"mha_zori_manifest.json not found or unreadable beside {zori} (run `make zori`)")
        raise AssertionError


def num(raw: str) -> float | None:
    s = (raw or "").strip()
    return float(s) if s else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zori", type=Path, required=True, help="B8 mha_zori.csv")
    ap.add_argument("--safmr", type=Path, required=True, help="B10 mha_safmr.csv")
    ap.add_argument("--metro-sfr", type=Path, required=True, help="A15.sfr metro single-family ZORI")
    ap.add_argument("--metro-mfr", type=Path, required=True, help="A15.mfr metro multifamily ZORI")
    ap.add_argument("--metro-all", type=Path, required=True, help="A15.all metro all-homes ZORI")
    ap.add_argument("--zip-metro", type=Path, required=True, help="A4 ZIP ZHVI file (its Metro column)")
    ap.add_argument("--crosswalk", type=Path, required=True, help="B1 zip_mha.csv")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-months", type=int, default=3)
    ap.add_argument("--standards", type=Path, default=ht.STANDARDS)
    args = ap.parse_args()

    cfg = ht.load(args.standards)
    crosswalk, cw_stats = agg.load_crosswalk(args.crosswalk, TOOL)
    window = b8_window(args.zori)
    print(f"B29 rent benchmark by home type: B8 months {window[0]} to {window[1]}")

    b8 = {}
    with args.zori.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        need = {"mha", "zori_utilities_adjusted", "utilities_usd"}
        if not reader.fieldnames or not need <= set(reader.fieldnames):
            agg.die(TOOL, f"{args.zori.name} needs {sorted(need)}; found {reader.fieldnames}")
        for r in reader:
            b8[r["mha"]] = r
    safmr: dict[tuple[str, int], float] = {}
    with args.safmr.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["safmr_median"].strip():
                safmr[(r["mha"], int(r["bedrooms"]))] = float(r["safmr_median"])
    mhas = sorted(b8)
    problems = [f"{m}: B10 has no {n} BR SAFMR" for m in mhas for n in {t["bedrooms"] for t in ht.types(cfg)} | {2}
                if (m, n) not in safmr]
    if set(mhas) != set(crosswalk.values()):
        problems.append("B8 and B1 cover different MHAs; rebuild B8 from this crosswalk")
    agg.fail_if(problems[:25], TOOL)

    # A15: metro ratios type / all homes, and the national fallback.
    all_m, all_nat, _ = read_metro(args.metro_all, window, args.min_months)
    ratios: dict[str, dict[str, float]] = {}
    national: dict[str, float] = {}
    series_rows = {}
    for key, path in (("sfr", args.metro_sfr), ("mfr", args.metro_mfr)):
        m, nat, rows = read_metro(path, window, args.min_months)
        series_rows[key] = {"metros_with_value": len(m), "rows": rows}
        ratios[key] = {name: v / all_m[name] for name, v in m.items() if name in all_m and all_m[name] > 0}
        if nat is None or not all_nat:
            agg.die(TOOL, f"{path.name} or {args.metro_all.name} has no national (RegionType 'country') row")
        national[key] = nat / all_nat
    bad = [f"{k} {name}: {v:.3f}" for k, d in ratios.items() for name, v in d.items()
           if not FACTOR_RANGE[0] <= v <= FACTOR_RANGE[1]]
    agg.fail_if([f"type ratio outside {FACTOR_RANGE}: {', '.join(bad[:10])}"] if bad else [], TOOL)

    zip_metro = read_zip_metro(args.zip_metro, crosswalk)
    named = set(zip_metro.values())
    matched = {name for name in named if name in all_m}
    match_share = len(matched) / len(named) if named else 0.0
    if match_share < MIN_METRO_MATCH:
        agg.die(TOOL, f"only {len(matched)} of {len(named)} metro names in {args.zip_metro.name} appear in "
                      f"{args.metro_all.name}; the two files name metros differently")

    members: dict[str, list[str]] = {}
    for z, m in crosswalk.items():
        members.setdefault(m, []).append(z)

    factors: dict[tuple[str, str], tuple[float, str, int]] = {}
    for m in mhas:
        for building, key in SERIES_FOR.items():
            vals = [ratios[key][zip_metro[z]] for z in members[m] if zip_metro.get(z) in ratios[key]]
            factors[(m, building)] = ((statistics.median(vals), "metro", len(vals)) if vals
                                      else (national[key], "national", 0))

    rows, identity_fail = [], []
    for m in mhas:
        adj, util = num(b8[m]["zori_utilities_adjusted"]), num(b8[m]["utilities_usd"])
        for t in ht.types(cfg):
            b, n = t["building"], t["bedrooms"]
            f, src, nz = (1.0, "reference", 0) if b == "townhouse" else factors[(m, b)]
            s = 1.0 if n == 2 else safmr[(m, n)] / safmr[(m, 2)]
            out = {"mha": m, "home_type": t["id"], "building": b, "bedrooms": n,
                   "building_factor": f"{f:.6f}", "factor_source": src, "factor_zips": nz,
                   "bedroom_ratio": f"{s:.6f}"}
            if adj is None:
                out.update({"rent_monthly": "", "utilities_usd": "", "status": "no_zori"})
            else:
                out.update({"rent_monthly": agg.fmt(adj * f * s),
                            "utilities_usd": agg.fmt(util * f * s) if util is not None else "", "status": "ok"})
            if t["id"] == ht.REFERENCE and (out["rent_monthly"], out["utilities_usd"]) != (
                    b8[m]["zori_utilities_adjusted"].strip(), b8[m]["utilities_usd"].strip()):
                identity_fail.append(m)
            rows.append(out)
    agg.fail_if([f"the 2 BR townhouse differs from B8 in {len(identity_fail)} MHA(s): "
                 f"{', '.join(identity_fail[:10])}"] if identity_fail else [], TOOL)

    fields = ["mha", "home_type", "building", "bedrooms", "building_factor", "factor_source", "factor_zips",
              "bedroom_ratio", "rent_monthly", "utilities_usd", "status"]
    agg.write_csv(args.out / "mha_rent_by_type.csv", fields, rows)

    coverage = {}
    for t in ht.types(cfg):
        mine = [r for r in rows if r["home_type"] == t["id"]]
        vals = [float(r["rent_monthly"]) for r in mine if r["rent_monthly"]]
        coverage[t["id"]] = {
            "mhas_with_value": len(vals),
            "factor_source": {k: sum(r["factor_source"] == k for r in mine) for k in ("reference", "metro", "national")},
            "rent_monthly": ({"min": round(min(vals), 2), "median": round(statistics.median(vals), 2),
                              "max": round(max(vals), 2)} if vals else None),
        }
    fac_summary = {}
    for building in SERIES_FOR:
        vals = [factors[(m, building)][0] for m in mhas]
        fac_summary[building] = {"median": round(statistics.median(vals), 4), "min": round(min(vals), 4),
                                 "max": round(max(vals), 4),
                                 "national": round(national[SERIES_FOR[building]], 4),
                                 "mhas_national_fallback": sum(factors[(m, building)][1] == "national" for m in mhas)}
    warnings = []
    for building, sm in fac_summary.items():
        if sm["mhas_national_fallback"]:
            warnings.append(f"{sm['mhas_national_fallback']} MHA(s) take the national {building} factor "
                            f"({sm['national']}): none of their ZIPs lies in a metro with the A15 series")
    unmatched = sorted(named - matched)
    if unmatched:
        warnings.append(f"{len(unmatched)} metro name(s) in the ZIP file have no A15 all-homes row: "
                        f"{', '.join(unmatched[:8])}")

    inputs = {"B8": args.zori, "B10": args.safmr, "A15.sfr": args.metro_sfr, "A15.mfr": args.metro_mfr,
              "A15.all": args.metro_all, "A4": args.zip_metro, "B1": args.crosswalk, "A14": args.standards}
    manifest = {
        "node": "B29",
        "generated_at": agg.now_utc(),
        "inputs": {k: v.name for k, v in inputs.items()},
        "input_sha256": {k: agg.sha256(v) for k, v in inputs.items()},
        "window_months": f"{window[0]}:{window[1]}",
        "method": {
            "rent": "B8 zori_utilities_adjusted x building_factor x bedroom_ratio",
            "utilities": "B8 utilities_usd x building_factor x bedroom_ratio",
            "building_factor": "townhouse 1 (B8 stands for a 2 BR townhouse); apartment = metro MFR / all-homes "
                               "ZORI, single-family = metro SFR / all-homes ZORI, median over the MHA's ZIPs; "
                               "national ratio where no ZIP lies in a metro with the series",
            "bedroom_ratio": "B10 SAFMR n BR / 2 BR within the MHA",
        },
        "crosswalk": cw_stats,
        "metros": {"A15.all_with_value": len(all_m), **{f"A15.{k}": v for k, v in series_rows.items()},
                   "zip_metro_names": len(named), "zip_metro_names_matched": len(matched),
                   "mha_zips_with_metro": len(zip_metro)},
        "building_factors": fac_summary,
        "coverage": coverage,
        "reference_identity": "2 BR townhouse = B8 in every MHA (checked)",
        "mhas": len(mhas),
        "warnings": warnings,
        "outputs": ["mha_rent_by_type.csv"],
    }
    agg.write_manifest(args.out / "mha_rent_by_type_manifest.json", manifest)

    print(f"  {len(matched)} of {len(named)} metro names matched A15; {len(zip_metro):,} MHA ZIPs have a metro")
    for building, sm in fac_summary.items():
        print(f"  {building} factor: median {sm['median']} (min {sm['min']}, max {sm['max']}); national "
              f"{sm['national']} used by {sm['mhas_national_fallback']} MHA(s)")
    for tid, cv in coverage.items():
        r = cv["rent_monthly"]
        print(f"  {tid:5} {cv['mhas_with_value']} MHAs" + (f", median {r['median']:,.0f}" if r else ""))
    print("  2 BR townhouse = B8 in every MHA")
    for w in warnings:
        print(f"  warning: {w}")
    print(f"  -> {args.out / 'mha_rent_by_type.csv'}")


if __name__ == "__main__":
    main()
