#!/usr/bin/env python3
"""
zip_rent_by_type.py  (B8 + B10 + B29 + B1 -> B33 rent by home type for each ZIP)

Decision D36 (13 Nov 2026), the ZIP view: the rent benchmark of each of DoD's six
home types in every ZIP code of a real Military Housing Area, on the footing B29
uses for the MHA, so a ZIP and its MHA can be read side by side.

    python pipeline/benchmarks/zip_rent_by_type.py \
        --zip-zori data/interim/benchmarks_2026/zip_zori.csv \
        --zori data/interim/benchmarks_2026/mha_zori.csv \
        --zip-safmr data/interim/benchmarks_2026/zip_safmr.csv \
        --safmr data/interim/benchmarks_2026/mha_safmr.csv \
        --rent-by-type data/interim/benchmarks_2026/mha_rent_by_type.csv \
        --crosswalk data/interim/bah_2026/zip_mha.csv \
        --out data/interim/benchmarks_2026

------------------------------------------------------------------------------
Method (per ZIP z in MHA m and home type t), M8 plan Z2, Z3, Z9
------------------------------------------------------------------------------
  base(z)    the ZIP's utilities-inclusive rent for B8's reference home:
               ZORI(z) / rent_share(m)                              base_source zori
             where Zillow publishes no ZORI for z (or its ZORI falls outside the band):
               SAFMR 2 BR(z) x B8 zori_utilities_adjusted(m) / B10 SAFMR 2 BR median(m)
                                                                     base_source safmr_scaled
             HUD's figure is scaled so that the MHA's typical HUD rent equals its typical
             Zillow rent: it supplies the difference between ZIPs, Zillow the level.
  rent(t)    base(z) x B29 applied_factor(m, t) x B29 bedroom_ratio(m, t)
             The MHA's home-type factors, never one ZIP's: at ZIP level every ratio would
             rest on one ZIP, the cause of the Ketchikan values in the 12 Nov audit.

  Band (Z9): a base outside [1/3, 3] x the MHA's value is not used. If neither source
  gives a base inside the band, the ZIP's status is zip_outlier.

Status per row: ok | no_zori (the MHA has no ZORI, so neither source can be placed)
| zip_no_benchmark (neither source covers the ZIP) | zip_outlier.

Identity: base = B8's MHA value reproduces B29's rent in every MHA and home type
(checked to the cent), so B33 and B29 run one model.

The ZIPs with both a ZORI and a SAFMR give a check of the scaled SAFMR against the
ZORI it stands in for (manifest `safmr_check`).

Output: zip_rent_by_type.csv (long: ZIP x home type) and its manifest. Stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import home_types as ht  # noqa: E402
import mha_agg as agg  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "handoff"))
import contract as c  # noqa: E402

TOOL = "zip_rent_by_type"
IDENTITY_TOLERANCE = 0.011        # B29 rounds to cents; the factors here are its 6-place columns


def read(path: Path, needed: set[str]) -> list[dict]:
    if not path.exists():
        agg.die(TOOL, f"not found: {path}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not needed <= set(reader.fieldnames):
            agg.die(TOOL, f"{path.name} needs {sorted(needed)}; found {reader.fieldnames}")
        return list(reader)


def num(raw: str | None) -> float | None:
    s = (raw or "").strip()
    return float(s) if s else None


def in_band(value: float, reference: float) -> bool:
    return c.ZIP_BAND[0] <= value / reference <= c.ZIP_BAND[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip-zori", type=Path, required=True, help="B8 zip_zori.csv")
    ap.add_argument("--zori", type=Path, required=True, help="B8 mha_zori.csv")
    ap.add_argument("--zip-safmr", type=Path, required=True, help="B10 zip_safmr.csv")
    ap.add_argument("--safmr", type=Path, required=True, help="B10 mha_safmr.csv")
    ap.add_argument("--rent-by-type", type=Path, required=True, help="B29 mha_rent_by_type.csv")
    ap.add_argument("--crosswalk", type=Path, required=True, help="B1 zip_mha.csv")
    ap.add_argument("--standards", type=Path, default=ht.STANDARDS)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    crosswalk, cw_stats = agg.load_crosswalk(args.crosswalk, TOOL)
    types = [t["id"] for t in ht.types(ht.load(args.standards))]
    b8 = {r["mha"]: r for r in read(args.zori, {"mha", "rent_share", "zori_utilities_adjusted"})}
    zori = {r["zip"]: float(r["value"]) for r in read(args.zip_zori, {"zip", "mha", "value"}) if r["value"].strip()}
    safmr2 = {r["mha"]: float(r["safmr_median"]) for r in read(args.safmr, {"mha", "bedrooms", "safmr_median"})
              if r["bedrooms"] == "2" and r["safmr_median"].strip()}
    zip_safmr = {r["zip"]: float(r["br2"]) for r in read(args.zip_safmr, {"zip", "mha", "br2"}) if r["br2"].strip()}
    b29 = {(r["mha"], r["home_type"]): r for r in read(
        args.rent_by_type, {"mha", "home_type", "applied_factor", "bedroom_ratio", "factor_source", "rent_monthly",
                            "status"})}

    mhas = sorted(set(crosswalk.values()))
    problems = []
    if set(b8) != set(mhas):
        problems.append("B8 and B1 cover different MHAs; rebuild B8 from this crosswalk")
    gaps = [f"{m} {t}" for m in mhas for t in types if (m, t) not in b29]
    if gaps:
        problems.append(f"B29 lacks {len(gaps)} MHA x type row(s): {', '.join(gaps[:10])} (run `make rent-types`)")
    stray = sorted(z for z in zori if z not in crosswalk)
    if stray:
        problems.append(f"zip_zori.csv holds {len(stray)} ZIP(s) outside B1's real MHAs: {', '.join(stray[:5])}")
    agg.fail_if(problems, TOOL)

    def factor(m: str, t: str) -> float:
        r = b29[(m, t)]
        return float(r["applied_factor"]) * float(r["bedroom_ratio"])

    # Identity: the MHA's own base reproduces B29.
    identity_fail = []
    for m in mhas:
        adj = num(b8[m]["zori_utilities_adjusted"])
        for t in types:
            want = num(b29[(m, t)]["rent_monthly"])
            if (adj is None) != (want is None) or (adj is not None and abs(adj * factor(m, t) - want) > IDENTITY_TOLERANCE):
                identity_fail.append(f"{m} {t}")
    agg.fail_if([f"the MHA base does not reproduce B29 in {len(identity_fail)} MHA x type cell(s): "
                 f"{', '.join(identity_fail[:10])} (rebuild B29 and B33 from the same B8)"] if identity_fail else [],
                TOOL)

    rows, by_status, by_source, rejected_zori = [], {}, {}, []
    check = []                                   # (scaled SAFMR, ZORI) where both are in the band
    for z in sorted(crosswalk):
        m = crosswalk[z]
        adj, share = num(b8[m]["zori_utilities_adjusted"]), num(b8[m]["rent_share"])
        base, source, status = None, "none", "ok"
        if adj is None:
            status = "no_zori"
        else:
            from_zori = zori[z] / share if z in zori else None
            scale = adj / safmr2[m] if m in safmr2 else None
            from_safmr = zip_safmr[z] * scale if (z in zip_safmr and scale) else None
            if from_zori is not None and from_safmr is not None and in_band(from_zori, adj) and in_band(from_safmr, adj):
                check.append((from_safmr, from_zori))
            if from_zori is not None and in_band(from_zori, adj):
                base, source = from_zori, "zori"
            elif from_safmr is not None and in_band(from_safmr, adj):
                base, source = from_safmr, "safmr_scaled"
                if from_zori is not None:
                    rejected_zori.append(z)
            elif from_zori is not None or from_safmr is not None:
                status = "zip_outlier"
            else:
                status = "zip_no_benchmark"
        by_status[status] = by_status.get(status, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1
        for t in types:
            r = b29[(m, t)]
            rows.append({"zip": z, "mha": m, "home_type": t, "base_source": source,
                         "base_monthly": agg.fmt(base), "base_ratio": agg.fmt(base / adj, 4) if base else "",
                         "rent_monthly": agg.fmt(base * factor(m, t)) if base else "",
                         "factor_source": r["factor_source"], "status": status})

    fields = ["zip", "mha", "home_type", "base_source", "base_monthly", "base_ratio", "rent_monthly",
              "factor_source", "status"]
    agg.write_csv(args.out / "zip_rent_by_type.csv", fields, rows)

    ratios = [float(r["base_ratio"]) for r in rows if r["base_ratio"] and r["home_type"] == ht.REFERENCE]
    errors = sorted(abs(s / zr - 1) for s, zr in check)
    safmr_check = None
    if errors:
        safmr_check = {
            "zips_with_both": len(errors),
            "median_abs_pct_error": round(100 * statistics.median(errors), 2),
            "share_within_10_pct": round(sum(e <= 0.10 for e in errors) / len(errors), 4),
            "share_within_20_pct": round(sum(e <= 0.20 for e in errors) / len(errors), 4),
            "reading": "scaled SAFMR against the ZORI-based base in ZIPs that have both: how far the stand-in "
                       "sits from the figure it replaces",
        }
    warnings = []
    if rejected_zori:
        warnings.append(f"{len(rejected_zori)} ZIP(s) have a ZORI outside the band and use the scaled SAFMR: "
                        f"{', '.join(rejected_zori[:10])}")
    if by_status.get("zip_outlier"):
        warnings.append(f"{by_status['zip_outlier']} ZIP(s) have no value inside the band (status zip_outlier)")

    inputs = {"B8.zip": args.zip_zori, "B8": args.zori, "B10.zip": args.zip_safmr, "B10": args.safmr,
              "B29": args.rent_by_type, "B1": args.crosswalk, "A14": args.standards}
    manifest = {
        "node": "B33",
        "generated_at": agg.now_utc(),
        "inputs": {k: v.name for k, v in inputs.items()},
        "input_sha256": {k: agg.sha256(v) for k, v in inputs.items()},
        "decision": "D36 (13 Nov 2026): ZIP view; base from ZORI, else HUD SAFMR scaled to the MHA's ZORI level; "
                    "the MHA's B29 home-type factors; values outside the band left out",
        "method": {
            "base_zori": "ZORI(z) / B8 rent_share(m)",
            "base_safmr_scaled": "SAFMR 2 BR(z) x B8 zori_utilities_adjusted(m) / B10 SAFMR 2 BR median(m)",
            "rent": "base(z) x B29 applied_factor(m, t) x B29 bedroom_ratio(m, t)",
            "band": f"base / B8 zori_utilities_adjusted(m) within [{c.ZIP_BAND[0]:.4f}, {c.ZIP_BAND[1]}]",
        },
        "crosswalk": cw_stats,
        "coverage": {"zips": len(crosswalk), "status": by_status, "base_source": by_source},
        "base_ratio_summary": ({"min": round(min(ratios), 4), "median": round(statistics.median(ratios), 4),
                                "max": round(max(ratios), 4)} if ratios else None),
        "safmr_check": safmr_check,
        "model_identity": "the MHA base reproduces B29 in every MHA and home type (checked)",
        "warnings": warnings,
        "outputs": ["zip_rent_by_type.csv"],
    }
    agg.write_manifest(args.out / "zip_rent_by_type_manifest.json", manifest)

    print(f"B33 rent by home type per ZIP: {len(crosswalk):,} ZIPs in {len(mhas)} MHAs")
    print(f"  base source: {by_source}")
    print(f"  status:      {by_status}")
    if safmr_check:
        print(f"  scaled SAFMR vs ZORI in {safmr_check['zips_with_both']:,} ZIPs: median error "
              f"{safmr_check['median_abs_pct_error']}%, {safmr_check['share_within_10_pct']:.0%} within 10%")
    print("  the MHA base reproduces B29 in every MHA")
    for w in warnings:
        print(f"  warning: {w}")
    print(f"  -> {args.out / 'zip_rent_by_type.csv'}")


if __name__ == "__main__":
    main()
