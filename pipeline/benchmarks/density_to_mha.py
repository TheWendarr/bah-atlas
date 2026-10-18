#!/usr/bin/env python3
"""
density_to_mha.py  (A9 ACS + A2 ZCTA + B1 -> B24 population density per MHA)

Urbanicity for hypothesis H2 (reduced chain, decision D8): one population density
per real MHA, the third explanatory variable in the B19 spatial regression.

    python pipeline/benchmarks/density_to_mha.py \
        --acs data/raw/acs5_2024_zcta.json \
        --zcta data/raw/cb_2020_us_zcta520_500k.zip \
        --crosswalk data/interim/bah_2026/zip_mha.csv \
        --out data/interim/context_2026

------------------------------------------------------------------------------
Inputs
------------------------------------------------------------------------------
  A9  B01003_001E  total population per ZCTA, from the same pinned ACS 5-year
                   query that serves A8 property tax (no second pull)
  A2  ALAND20      land area per ZCTA in square metres, an attribute of the
                   Census cartographic boundary file. The published land area is
                   used rather than the area of the generalized 500k polygon.
  B1  zip_mha.csv  ZIP -> MHA; ZIP and ZCTA are matched directly (zip == zcta),
                   as B6 and A8 do.

------------------------------------------------------------------------------
Method
------------------------------------------------------------------------------
  For each real MHA, over the ZCTAs of its ZIPs that have both a population
  estimate and a positive land area:

    density_per_km2       = sum(population) / sum(land km2)
                            the plan's measure (M6 plan, H2 chain): people per
                            square kilometre of the MHA's land. B19 uses it.
    pw_density_per_km2    = sum(pop_i * density_i) / sum(pop_i)
                            population-weighted density: the density the average
                            resident lives at. An MHA with one dense city and a
                            large rural fringe scores low on the first measure
                            and high on this one. Written for B19's sensitivity
                            run; B19's primary model does not use it.

  ZCTAs with a negative ACS annotation code, a null estimate or zero land area
  are skipped and counted. An MHA with no usable ZCTA keeps its row with blank
  values (n_zctas_with_data = 0) and is listed as a warning; B19 leaves it out.

------------------------------------------------------------------------------
Output (written to --out)
------------------------------------------------------------------------------
  mha_density.csv             mha, n_zips, n_zctas_with_data, population,
                              land_km2, density_per_km2, pw_density_per_km2
  mha_density_manifest.json   inputs and SHA-256 (A9, A2, B1), ACS vintage,
                              ZCTA counts, MHAs without data, summaries,
                              output SHA-256, warnings

------------------------------------------------------------------------------
Validation (loud)
------------------------------------------------------------------------------
  * the ACS file is a Census API table with B01003_001E and a ZCTA column
  * the ZCTA file has a ZCTA code column and ALAND20 (or ALAND10 / ALAND)
  * every density is finite and positive, and below 30,000 people per km2
    (above any U.S. ZCTA aggregate; a higher figure means a units error)
  * at least one real MHA has data
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mha_agg as agg  # noqa: E402
import tax_insurance_to_mha as ti  # noqa: E402  (ACS parsing and vintage helpers)

TOOL = "density_to_mha"
POP_VAR = ti.POP_VAR
LAND_COLUMNS = ("ALAND20", "ALAND10", "ALAND")
MAX_DENSITY = 30_000.0      # people per km2
FIELDS = ["mha", "n_zips", "n_zctas_with_data", "population", "land_km2",
          "density_per_km2", "pw_density_per_km2"]


def read_population(path: Path) -> tuple[dict[str, float], dict]:
    """{zcta: population} for ZCTAs with a usable B01003_001E estimate."""
    if not path.exists():
        agg.die(TOOL, f"ACS file not found: {path} (run `make fetch` with CENSUS_API_KEY set)")
    try:
        table = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        agg.die(TOOL, f"{path.name} is not valid JSON: {e}")
    if not (isinstance(table, list) and len(table) > 1 and isinstance(table[0], list)):
        agg.die(TOOL, f"{path.name} is not a Census API table (header row, then data rows)")
    header = table[0]
    missing = [c for c in (POP_VAR, ti.ZCTA_COL) if c not in header]
    if missing:
        agg.die(TOOL, f"{path.name} lacks {missing}; header is {header}")
    i_pop, i_z = header.index(POP_VAR), header.index(ti.ZCTA_COL)
    pop: dict[str, float] = {}
    missing_est = 0
    for row in table[1:]:
        z = agg.zip5(row[i_z])
        if z is None:
            agg.die(TOOL, f"{path.name} has a malformed ZCTA {row[i_z]!r}")
        v = ti.acs_number(row[i_pop])
        if v is None:
            missing_est += 1
        else:
            pop[z] = v
    return pop, {"zctas_in_acs": len(table) - 1, "zctas_with_population": len(pop),
                 "zctas_missing_population": missing_est}


def read_land(path: Path) -> tuple[dict[str, float], dict]:
    """{zcta: land km2} from the ZCTA file's attribute table (geometry is not read)."""
    if not path.exists():
        agg.die(TOOL, f"ZCTA file not found: {path} (run `make fetch`)")
    try:
        import geopandas as gpd
    except ImportError:  # pragma: no cover - environment problem, reported loudly
        agg.die(TOOL, "geopandas is not installed. Run `pip install -r requirements.txt`.")
    table = gpd.read_file(path, ignore_geometry=True)
    cols = list(table.columns)
    code = next((c for c in cols if "ZCTA5" in c.upper() or c.upper() in ("GEOID20", "GEOID10", "GEOID")), None)
    land = next((c for c in cols if c.upper() in LAND_COLUMNS), None)
    if code is None or land is None:
        agg.die(TOOL, f"{path.name} needs a ZCTA code column and one of {LAND_COLUMNS}; found {cols}")
    out: dict[str, float] = {}
    zero = 0
    for z_raw, a_raw in zip(table[code], table[land]):
        z = agg.zip5(z_raw)
        if z is None:
            agg.die(TOOL, f"{path.name} has a malformed ZCTA {z_raw!r}")
        try:
            a = float(a_raw)
        except (TypeError, ValueError):
            agg.die(TOOL, f"{path.name}: {land} for {z} is {a_raw!r}, not a number")
        if not math.isfinite(a) or a <= 0:
            zero += 1
            continue
        out[z] = a / 1_000_000.0
    return out, {"zcta_file_column_code": code, "zcta_file_column_land": land,
                 "zctas_in_boundary_file": len(table), "zctas_with_land": len(out),
                 "zctas_zero_land": zero}


def densities(members: dict[str, list[str]], pop: dict[str, float], land: dict[str, float]) -> list[dict]:
    rows = []
    for mha in sorted(members):
        hits = [(pop[z], land[z]) for z in members[mha] if z in pop and z in land]
        p, a = sum(h[0] for h in hits), sum(h[1] for h in hits)
        crude = p / a if a > 0 else None
        pw = (sum(pi * (pi / ai) for pi, ai in hits) / p) if p > 0 else None
        rows.append({"mha": mha, "n_zips": len(members[mha]), "n_zctas_with_data": len(hits),
                     "population": round(p) if hits else None, "land_km2": a if hits else None,
                     "density_per_km2": crude, "pw_density_per_km2": pw})
    return rows


def summary(values: list[float]) -> dict | None:
    if not values:
        return None
    return {"min": round(min(values), 2), "median": round(statistics.median(values), 2),
            "max": round(max(values), 2)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--acs", type=Path, required=True, help="A9 ACS 5-year ZCTA table (Census API JSON)")
    ap.add_argument("--zcta", type=Path, required=True, help="A2 Census ZCTA cartographic boundary file")
    ap.add_argument("--crosswalk", type=Path, required=True, help="B1 zip_mha.csv")
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    args = ap.parse_args()

    print("B24 population density per MHA")
    crosswalk, xstats = agg.load_crosswalk(args.crosswalk, TOOL)
    members: dict[str, list[str]] = {}
    for z, mha in crosswalk.items():
        members.setdefault(mha, []).append(z)

    warnings: list[str] = []
    vintage = ti.acs_vintage_from_fetch(args.acs)
    if vintage is None:
        warnings.append(f"no fetch-manifest record for {args.acs.name}; ACS vintage not confirmed")

    pop, pop_stats = read_population(args.acs)
    land, land_stats = read_land(args.zcta)
    rows = densities(members, pop, land)

    problems = []
    for r in rows:
        for f in ("density_per_km2", "pw_density_per_km2"):
            v = r[f]
            if v is not None and not (math.isfinite(v) and 0 < v < MAX_DENSITY):
                problems.append(f"{r['mha']}: {f} {v} outside (0, {MAX_DENSITY:,.0f})")
    with_data = [r for r in rows if r["density_per_km2"] is not None]
    if not with_data:
        problems.append("no real MHA has both population and land area; check the ACS and ZCTA files")
    agg.fail_if(problems[:25], TOOL)

    without = [r["mha"] for r in rows if r["density_per_km2"] is None]
    if without:
        warnings.append(f"{len(without)} MHA(s) have no ZCTA with population and land area and get no "
                        f"density (left out of B19): {', '.join(without)}")
    used_zips = sum(r["n_zctas_with_data"] for r in rows)

    out_rows = [{**r, "population": "" if r["population"] is None else r["population"],
                 "land_km2": agg.fmt(r["land_km2"], 3), "density_per_km2": agg.fmt(r["density_per_km2"], 3),
                 "pw_density_per_km2": agg.fmt(r["pw_density_per_km2"], 3)} for r in rows]
    out_csv = args.out / "mha_density.csv"
    agg.write_csv(out_csv, FIELDS, out_rows)

    manifest = {
        "nodes": ["B24"],
        "role": "population density per MHA (urbanicity) for the B19 spatial regression (reduced H2, D8)",
        "generated_at": agg.now_utc(),
        "inputs": {"A9": args.acs.name, "A2": args.zcta.name, "B1": args.crosswalk.name},
        "input_sha256": {"A9": agg.sha256(args.acs), "A2": agg.sha256(args.zcta),
                         "B1": agg.sha256(args.crosswalk)},
        "acs_vintage": vintage,
        "acs_period": f"{vintage - 4}-{vintage}" if vintage else None,
        "variables": {"population": POP_VAR, "land_area": land_stats["zcta_file_column_land"]},
        "method": {
            "join": "direct zip == zcta over the MHA's B1 ZIPs, as B6 and A8",
            "density_per_km2": "sum(population) / sum(land km2) over the MHA's usable ZCTAs (B19 primary)",
            "pw_density_per_km2": "sum(pop_i * density_i) / sum(pop_i): population-weighted (B19 sensitivity)",
        },
        "crosswalk": xstats,
        **pop_stats, **land_stats,
        "real_mha_zips_with_usable_zcta": used_zips,
        "mhas": len(rows),
        "mhas_with_data": len(with_data),
        "mhas_without_data": without,
        "density_summary": summary([r["density_per_km2"] for r in with_data]),
        "pw_density_summary": summary([r["pw_density_per_km2"] for r in with_data]),
        "outputs": [out_csv.name],
        "output_sha256": {out_csv.name: agg.sha256(out_csv)},
        "warnings": warnings,
    }
    agg.write_manifest(args.out / "mha_density_manifest.json", manifest)

    print(f"  ACS {manifest['acs_period'] or '(vintage unconfirmed)'}: {pop_stats['zctas_with_population']} ZCTAs "
          f"with population; {land_stats['zctas_with_land']} with land area")
    print(f"  {len(with_data)} of {len(rows)} MHAs have a density; {used_zips} of "
          f"{xstats['real_mha_zips']} real-MHA ZIPs matched a usable ZCTA")
    print(f"  density per km2 {manifest['density_summary']}; population-weighted {manifest['pw_density_summary']}")
    for w in warnings:
        print(f"  warning: {w}")
    print(f"  -> {out_csv}")


if __name__ == "__main__":
    main()
