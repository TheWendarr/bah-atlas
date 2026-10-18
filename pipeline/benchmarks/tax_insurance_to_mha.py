#!/usr/bin/env python3
"""
tax_insurance_to_mha.py  (A9 ACS + A8 FIO + B1 -> per-MHA property tax rate and
                          homeowners premium, read by B11)

Replaces the national placeholders B11 used until M6 (decision 2.7). Every real
MHA gets one effective property-tax rate and one annual homeowners premium, each
with a source flag saying whether it is local to the MHA or a state fallback.

    python pipeline/benchmarks/tax_insurance_to_mha.py \
        --acs data/raw/acs5_2024_zcta.json \
        --fio data/raw/Supporting_Underlying_Metrics_and_Disclaimer_for_Analyses_of_US_Homeowners_Insurance_Markets_2018-2022.xlsx \
        --crosswalk data/interim/bah_2026/zip_mha.csv \
        --out data/interim/benchmarks_2026

------------------------------------------------------------------------------
Property tax (A9: ACS 5-year, ZCTA)
------------------------------------------------------------------------------
  B25090_001E  aggregate real estate taxes paid   } both for owner-occupied
  B25079_001E  aggregate value                    } housing units

  MHA effective rate = sum(taxes) / sum(value) over the ZCTAs of the MHA's ZIPs
  (direct zip == zcta match, as B6 does). Summing the aggregates weights each
  ZCTA by its owner-occupied housing stock and avoids a ratio of medians. ZCTAs
  where either estimate is missing (null, or a negative ACS annotation code), or
  where the aggregate value is 0, are skipped.

  Fallback: an MHA with no usable ZCTA takes its state's rate: the same ratio
  over every real-MHA ZIP whose MHA code starts with that state's two letters.
  Flag `state_fallback`.

------------------------------------------------------------------------------
Insurance (A8: Treasury FIO ZIP-level metrics, 2018-2022)
------------------------------------------------------------------------------
  "Premiums Per Policy" (written premium / policies in force at year end) for
  the data year in config/ownership.json (insurance.data_year), used as
  published (decision N2). FIO publishes only ZIPs with at least 10 insurers and
  50 policies, by year; fio_insurance.py reads the workbook.

  MHA premium = median over the MHA's ZIPs that FIO publishes (the B8-B10 rule).
  Fallback: the median over the published ZIPs of every real MHA in the same
  state (the MHA code's two letters), as for tax. Flag `state_fallback`.

------------------------------------------------------------------------------
Output (written to --out)
------------------------------------------------------------------------------
  mha_tax_insurance.csv            one row per real MHA: mha, n_zips,
                                   tax_zips_with_data, effective_tax_rate,
                                   tax_source, insurance_zips_with_data,
                                   insurance_annual_usd, insurance_source
  mha_tax_insurance_manifest.json  inputs and SHA-256 (A9, A8, B1, the config),
                                   ACS vintage and variables, counts, state
                                   rates used, fallbacks, summaries, warnings

------------------------------------------------------------------------------
Validation (loud)
------------------------------------------------------------------------------
  * the ACS file is a Census API table with the three variables and a ZCTA column
  * the ACS vintage recorded in the fetch manifest matches property_tax.acs_vintage
  * every effective rate is in (0, 5%) and every premium in (0, 20,000) dollars
  * every real MHA gets both values (a state with no data at all stops the run)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mha_agg as agg  # noqa: E402
import fio_insurance as fio  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TOOL = "tax_insurance_to_mha"
TAX_VAR, VALUE_VAR, POP_VAR = "B25090_001E", "B25079_001E", "B01003_001E"
ZCTA_COL = "zip code tabulation area"
RATE_RANGE = (0.0, 0.05)
PREMIUM_RANGE = (0.0, 20_000.0)


def acs_number(raw: object) -> float | None:
    """ACS value, or None when missing. Negative values are annotation codes (-666666666 etc.)."""
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def read_acs(path: Path) -> tuple[dict[str, tuple[float, float]], dict]:
    """{zcta: (taxes, value)} for ZCTAs with both estimates and a positive value."""
    if not path.exists():
        agg.die(TOOL, f"ACS file not found: {path} (run `make fetch` with CENSUS_API_KEY set)")
    try:
        table = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        agg.die(TOOL, f"{path.name} is not valid JSON: {e}")
    if not (isinstance(table, list) and len(table) > 1 and isinstance(table[0], list)):
        agg.die(TOOL, f"{path.name} is not a Census API table (header row, then data rows)")
    header = table[0]
    missing = [c for c in (TAX_VAR, VALUE_VAR, ZCTA_COL) if c not in header]
    if missing:
        agg.die(TOOL, f"{path.name} lacks {missing}; header is {header}")
    i_tax, i_val, i_z = header.index(TAX_VAR), header.index(VALUE_VAR), header.index(ZCTA_COL)
    usable: dict[str, tuple[float, float]] = {}
    missing_est = zero_value = 0
    for row in table[1:]:
        z = agg.zip5(row[i_z])
        if z is None:
            agg.die(TOOL, f"{path.name} has a malformed ZCTA {row[i_z]!r}")
        t, v = acs_number(row[i_tax]), acs_number(row[i_val])
        if t is None or v is None:
            missing_est += 1
        elif v == 0:
            zero_value += 1
        else:
            usable[z] = (t, v)
    stats = {"zctas_in_file": len(table) - 1, "zctas_usable": len(usable),
             "zctas_missing_estimate": missing_est, "zctas_zero_value": zero_value}
    return usable, stats


def acs_vintage_from_fetch(acs_path: Path) -> int | None:
    """The year in the ACS query URL that the fetch manifest beside the file recorded."""
    man = acs_path.with_name("fetch_manifest.json")
    try:
        records = json.loads(man.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for rec in records.values():
        if isinstance(rec, dict) and rec.get("filename") == acs_path.name:
            url = rec.get("source_url") or ""
            parts = url.split("/data/", 1)
            if len(parts) == 2 and parts[1][:4].isdigit():
                return int(parts[1][:4])
    return None


def state_of(mha: str) -> str:
    return mha[:2]


def tax_rates(members: dict[str, list[str]], zcta: dict[str, tuple[float, float]]
              ) -> tuple[dict[str, dict], dict[str, float]]:
    """Per-MHA {n, rate} from summed aggregates, and per-state rates for the fallback."""
    per_mha: dict[str, dict] = {}
    state_sums: dict[str, list[float]] = {}
    for mha, zips in members.items():
        hits = [zcta[z] for z in zips if z in zcta]
        t, v = sum(h[0] for h in hits), sum(h[1] for h in hits)
        per_mha[mha] = {"n": len(hits), "rate": t / v if v > 0 else None}
        s = state_sums.setdefault(state_of(mha), [0.0, 0.0])
        s[0] += t
        s[1] += v
    states = {st: t / v for st, (t, v) in state_sums.items() if v > 0}
    return per_mha, states


def premiums(members: dict[str, list[str]], zip_premium: dict[str, float]
             ) -> tuple[dict[str, dict], dict[str, float]]:
    """Per-MHA {n, premium} as the median of published ZIPs, and per-state medians."""
    per_mha = {}
    by_state: dict[str, list[float]] = {}
    for mha, zips in members.items():
        vals = [zip_premium[z] for z in zips if z in zip_premium]
        per_mha[mha] = {"n": len(vals), "premium": statistics.median(vals) if vals else None}
        by_state.setdefault(state_of(mha), []).extend(vals)
    return per_mha, {st: statistics.median(v) for st, v in by_state.items() if v}


def summary(values: list[float], places: int) -> dict | None:
    if not values:
        return None
    return {"min": round(min(values), places), "median": round(statistics.median(values), places),
            "max": round(max(values), places)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--acs", type=Path, required=True, help="A9 ACS 5-year ZCTA table (Census API JSON)")
    ap.add_argument("--fio", type=Path, required=True, help="A8 Treasury FIO ZIP-level workbook (.xlsx)")
    ap.add_argument("--crosswalk", type=Path, required=True, help="B1 zip_mha.csv")
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "ownership.json")
    args = ap.parse_args()

    try:
        cfg = json.loads(args.config.read_text(encoding="utf-8"))
        vintage, data_year = int(cfg["property_tax"]["acs_vintage"]), int(cfg["insurance"]["data_year"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
        agg.die(TOOL, f"{args.config} needs property_tax.acs_vintage and insurance.data_year ({e})")

    print("A8 property tax and insurance at MHA")
    crosswalk, xstats = agg.load_crosswalk(args.crosswalk, TOOL)
    members: dict[str, list[str]] = {}
    for z, mha in crosswalk.items():
        members.setdefault(mha, []).append(z)

    warnings: list[str] = []
    recorded = acs_vintage_from_fetch(args.acs)
    if recorded is None:
        warnings.append(f"no fetch-manifest record for {args.acs.name}; ACS vintage {vintage} not confirmed")
    elif recorded != vintage:
        agg.die(TOOL, f"{args.acs.name} was fetched from the {recorded} ACS, but config/ownership.json "
                      f"says acs_vintage {vintage}. Re-fetch A9 or correct the config.")

    zcta, acs_stats = read_acs(args.acs)
    tax_mha, tax_state = tax_rates(members, zcta)
    zip_premium, fio_stats = fio.read(args.fio, data_year, TOOL)
    fio_stats["zips_in_real_mhas"] = sum(z in crosswalk for z in zip_premium)
    ins_mha, ins_state = premiums(members, zip_premium)

    rows, problems = [], []
    tax_fallback, ins_fallback = [], []
    lo_r, hi_r = RATE_RANGE
    lo_p, hi_p = PREMIUM_RANGE
    for mha in sorted(members):
        st = state_of(mha)
        t, i = tax_mha[mha], ins_mha[mha]
        rate, tax_src = t["rate"], "locality"
        if rate is None:
            rate, tax_src = tax_state.get(st), "state_fallback"
            tax_fallback.append(mha)
        prem, ins_src = i["premium"], "locality"
        if prem is None:
            prem, ins_src = ins_state.get(st), "state_fallback"
            ins_fallback.append(mha)
        if rate is None:
            problems.append(f"{mha}: no ACS tax data in the MHA or its state {st}")
        elif not lo_r < rate < hi_r:
            problems.append(f"{mha}: effective tax rate {rate:.5f} outside ({lo_r}, {hi_r})")
        if prem is None:
            problems.append(f"{mha}: no FIO premium in the MHA or its state {st}")
        elif not lo_p < prem < hi_p:
            problems.append(f"{mha}: premium {prem:.0f} outside ({lo_p:.0f}, {hi_p:.0f})")
        rows.append({
            "mha": mha, "n_zips": len(members[mha]),
            "tax_zips_with_data": t["n"], "effective_tax_rate": "" if rate is None else f"{rate:.6f}",
            "tax_source": tax_src,
            "insurance_zips_with_data": i["n"], "insurance_annual_usd": agg.fmt(prem),
            "insurance_source": ins_src,
        })
    agg.fail_if(problems[:25] + ([f"... and {len(problems) - 25} more"] if len(problems) > 25 else []), TOOL)

    fields = ["mha", "n_zips", "tax_zips_with_data", "effective_tax_rate", "tax_source",
              "insurance_zips_with_data", "insurance_annual_usd", "insurance_source"]
    out_csv = args.out / "mha_tax_insurance.csv"
    agg.write_csv(out_csv, fields, rows)

    if tax_fallback:
        warnings.append(f"{len(tax_fallback)} MHA(s) use the state property-tax rate: {', '.join(tax_fallback)}")
    if ins_fallback:
        warnings.append(f"{len(ins_fallback)} MHA(s) use the state median premium: {', '.join(ins_fallback)}")
    used_states = sorted({state_of(m) for m in tax_fallback + ins_fallback})
    manifest = {
        "nodes": ["A8"],
        "role": "per-MHA property tax rate (A9 ACS) and homeowners premium (A8 FIO) for B11",
        "generated_at": agg.now_utc(),
        "inputs": {"A9": args.acs.name, "A8": args.fio.name, "B1": args.crosswalk.name},
        "input_sha256": {"A9": agg.sha256(args.acs), "A8": agg.sha256(args.fio),
                         "B1": agg.sha256(args.crosswalk)},
        "config": str(args.config.relative_to(ROOT)) if args.config.is_relative_to(ROOT) else str(args.config),
        "config_sha256": agg.sha256(args.config),
        "crosswalk": xstats,
        "property_tax": {
            "acs_vintage": vintage, "acs_period": f"{vintage - 4}-{vintage}",
            "variables": {"taxes": TAX_VAR, "value": VALUE_VAR},
            "method": "sum(B25090_001E) / sum(B25079_001E) over the MHA's ZCTAs (direct zip == zcta)",
            **acs_stats,
            "mhas_locality": len(members) - len(tax_fallback),
            "mhas_state_fallback": tax_fallback,
            "effective_rate_summary": summary([float(r["effective_tax_rate"]) for r in rows], 5),
        },
        "insurance": {
            "data_year": data_year, "scaled_to_bah_year": False,
            "method": "median FIO average premium over the MHA's published ZIPs",
            **fio_stats,
            "mhas_locality": len(members) - len(ins_fallback),
            "mhas_state_fallback": ins_fallback,
            "premium_summary": summary([float(r["insurance_annual_usd"]) for r in rows], 0),
        },
        "state_values_used": {st: {"tax_rate": round(tax_state[st], 6) if st in tax_state else None,
                                   "premium": round(ins_state[st], 2) if st in ins_state else None}
                              for st in used_states},
        "mhas": len(rows),
        "outputs": [out_csv.name],
        "output_sha256": {out_csv.name: agg.sha256(out_csv)},
        "warnings": warnings,
    }
    agg.write_manifest(args.out / "mha_tax_insurance_manifest.json", manifest)

    pt, ins = manifest["property_tax"], manifest["insurance"]
    print(f"  ACS {pt['acs_period']} ({vintage} vintage): {pt['zctas_usable']} of {pt['zctas_in_file']} ZCTAs usable")
    print(f"  property tax: {pt['mhas_locality']} MHAs local, {len(tax_fallback)} state fallback; "
          f"rate {pt['effective_rate_summary']}")
    print(f"  insurance {data_year}: {ins['mhas_locality']} MHAs local, {len(ins_fallback)} state fallback; "
          f"premium {ins['premium_summary']}")
    for w in warnings:
        print(f"  warning: {w}")
    print(f"  -> {out_csv}")


if __name__ == "__main__":
    main()
