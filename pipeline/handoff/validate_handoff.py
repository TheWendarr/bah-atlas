#!/usr/bin/env python3
"""
validate_handoff.py  (data contract section 11, checks 3-8)

Checks the delivered files against the contract and against the pipeline tables
they were built from, independently of the builders:

  3  every JSON file has its required fields, types and closed-list values;
     ratios have at most 4 decimals (p-values 5), dollars are whole
  4  the area codes in B7 (the B6 and B28 polygons it was tiled from) match the
     codes in B20, apart from codes with no polygon, which B28 lists
  5  every non-null B20 value equals its source row (B4, B12-B15) after rounding
  6  every status code and caveat id in B20 and B27 has an entry in B21
  7  B20, B21 and B27 carry one build_id, equal to the SHA-256 of B22
  8  SHA256SUMS matches the five delivered files (skipped with --no-sums)

    python pipeline/handoff/validate_handoff.py --year 2026 --handoff data/processed/handoff

Exit status 1 on any failure. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import contract as c

TOOL = "validate_handoff"
ROOT = Path(__file__).resolve().parents[2]


class Check:
    def __init__(self) -> None:
        self.failed: list[str] = []
        self.passed: dict[int, int] = {}

    def ok(self, n: int) -> None:
        self.passed[n] = self.passed.get(n, 0) + 1

    def fail(self, n: int, msg: str) -> None:
        self.failed.append(f"[{n}] {msg}")

    def expect(self, n: int, cond: bool, msg: str) -> None:
        self.ok(n) if cond else self.fail(n, msg)


def is_dollar(v: object) -> bool:
    return v is None or (isinstance(v, int) and not isinstance(v, bool))


def is_ratio(v: object, places: int = c.RATIO_PLACES) -> bool:
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and c.decimals_of(v) <= places)


def check_header(ck: Check, name: str, doc: dict, year: int, build_id: str) -> None:
    ck.expect(3, str(doc.get("schema_version", "")).split(".")[0] == c.SCHEMA_VERSION.split(".")[0],
              f"{name}: schema_version {doc.get('schema_version')!r} is not major {c.SCHEMA_VERSION.split('.')[0]}")
    ck.expect(3, doc.get("bah_year") == year, f"{name}: bah_year {doc.get('bah_year')!r} is not {year}")
    ck.expect(7, doc.get("build_id") == build_id, f"{name}: build_id is not the SHA-256 of B22")


def check_payload(ck: Check, p: dict, sources: dict) -> tuple[set[str], set[str]]:
    statuses, caveats = set(), set()
    profiles = p.get("profiles") or []
    ck.expect(3, list(p.get("modes") or []) == list(c.MODES), f"B20: modes {p.get('modes')} are not {c.MODES}")
    codes = list(p.get("areas", {}))
    ck.expect(3, codes == sorted(codes), "B20: areas are not sorted by code")
    for code, a in p.get("areas", {}).items():
        where = f"B20 {code}"
        if not c.CODE.match(code) or a.get("class") not in c.CLASSES or not isinstance(a.get("cluster_scope"), bool):
            ck.fail(3, f"{where}: bad code, class or cluster_scope")
            continue
        for cv in a.get("caveats", []):
            caveats.add(cv)
            ck.expect(3, c.CAVEATS.get(cv) == "area", f"{where}: {cv!r} is not an area-level caveat")
        for prof in profiles:
            for mode in c.MODES:
                b = (a.get(prof) or {}).get(mode)
                w = f"{where} {prof} {mode}"
                if not isinstance(b, dict):
                    ck.fail(3, f"{w}: block missing")
                    continue
                st = b.get("status")
                statuses.add(st)
                if st not in c.STATUSES[mode]:
                    ck.fail(3, f"{w}: status {st!r} not in the contract")
                    continue
                want = ["status", *c.MODE_FIELDS[mode], "caveats"]
                ck.expect(3, list(b) == want, f"{w}: fields {list(b)} are not {want}")
                allowed = c.NON_NULL[st]
                for f in c.MODE_FIELDS[mode]:
                    v = b.get(f)
                    good = is_dollar(v) if f in c.DOLLAR_FIELDS else is_ratio(v)
                    ck.expect(3, good, f"{w}: {f} = {v!r} breaks the rounding rule")
                    if allowed != "all" and f not in allowed:
                        ck.expect(3, v is None, f"{w}: {f} must be null under status {st}")
                for cv in b.get("caveats", []):
                    caveats.add(cv)
                    ck.expect(3, c.CAVEATS.get(cv) == "row", f"{w}: {cv!r} is not a row-level caveat")
                check_source(ck, w, code, a["class"], prof, mode, b, sources)
    return statuses, caveats


def check_source(ck: Check, w: str, code: str, cls: str, prof: str, mode: str, b: dict, s: dict) -> None:
    """Check 5: every non-null value equals its source row after rounding."""
    if cls == "mha":
        row = s[mode].get((prof, code))
        if row is None:
            ck.fail(5, f"{w}: no source row in B12-B15")
            return
        ck.expect(5, row["status"] == b["status"], f"{w}: status {b['status']} != source {row['status']}")
        for f in c.MODE_FIELDS[mode]:
            if b[f] is None:
                continue
            src = c.dollars(row.get(f)) if f in c.DOLLAR_FIELDS else c.ratio(row.get(f))
            ck.expect(5, b[f] == src, f"{w}: {f} = {b[f]} but the source row rounds to {src}")
    elif b["bah_monthly"] is not None:
        p = s["profiles"][prof]
        src = c.dollars(s["bah"].get((code, p["pay_grade"].upper(), str(bool(p["has_dependents"])).lower())))
        ck.expect(5, b["bah_monthly"] == src, f"{w}: bah_monthly {b['bah_monthly']} != B4 {src}")


def check_ui(ck: Check, ui: dict) -> None:
    ck.expect(3, set(ui.get("statuses", {})) == set(c.ALL_STATUSES), "B21: statuses differ from the contract")
    ck.expect(3, set(ui.get("caveats", {})) == set(c.CAVEATS), "B21: caveats differ from the contract")
    for cid, cv in ui.get("caveats", {}).items():
        ck.expect(3, cv.get("level") == c.CAVEATS.get(cid) and cv.get("title") and cv.get("text"),
                  f"B21: caveat {cid} needs title, text and level {c.CAVEATS.get(cid)}")
    for key in ("profiles", "default_profile", "modes", "metrics", "default_metric", "no_data_color", "clusters",
                "areas", "global_caveats", "windows", "sources", "geometry"):
        ck.expect(3, key in ui, f"B21: missing {key}")
    for mid, m in ui.get("metrics", {}).items():
        n = len(m.get("breaks") or [])
        ck.expect(3, len(m.get("colors") or []) == n + 1 == len(m.get("class_labels") or []),
                  f"B21: metric {mid} has {n} breaks but {len(m.get('colors') or [])} colours")


def check_hotspots(ck: Check, h: dict, payload: dict) -> None:
    ck.expect(3, h.get("variable") == c.B27_VARIABLE, f"B27: variable is not {c.B27_VARIABLE}")
    ck.expect(6, h.get("caveats") == ["lisa_exploratory"], "B27: caveats must be ['lisa_exploratory']")
    scope = {code for code, a in payload["areas"].items() if a["cluster_scope"]}
    ck.expect(3, set(h.get("areas", {})) == scope, "B27: areas are not exactly the payload's cluster-scope MHAs")
    for prof, modes in h.get("tests", {}).items():
        for mode, t in modes.items():
            ck.expect(3, is_ratio(t.get("moran_i")) and is_ratio(t.get("moran_p_sim"), c.P_PLACES)
                      and is_ratio(t.get("fdr_cutoff"), c.P_PLACES), f"B27 test {prof} {mode}: rounding")
    for code, profs in h.get("areas", {}).items():
        for prof, modes in profs.items():
            for mode, e in modes.items():
                w = f"B27 {code} {prof} {mode}"
                st = e.get("status")
                ck.expect(3, st in c.B27_STATUSES, f"{w}: status {st!r}")
                if st == "tested":
                    ck.expect(3, e.get("cluster") in c.CLUSTER_CODES and e.get("gi_class") in c.GI_CLASSES
                              and isinstance(e.get("lisa_fdr_significant"), bool)
                              and is_ratio(e.get("lisa_p_sim"), c.P_PLACES), f"{w}: fields or rounding")
                else:
                    ck.expect(3, all(e.get(k) is None for k in ("cluster", "lisa_p_sim", "lisa_fdr_significant",
                                                                 "gi_class")), f"{w}: untested area has values")


def polygon_codes(path: Path) -> set[str]:
    data = c.read_json(path, TOOL)
    return {str(f["properties"]["mha"]) for f in data.get("features", [])}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--handoff", type=Path, required=True, help="folder holding the delivered files")
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--profiles", type=Path, default=ROOT / "config" / "profiles.json")
    ap.add_argument("--no-sums", action="store_true", help="skip check 8 (before SHA256SUMS is written)")
    args = ap.parse_args()

    y, d = args.year, args.data
    names = c.file_names(y)
    files = {node: args.handoff / name for node, name in names.items()}
    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        c.die(TOOL, f"delivered file(s) missing: {', '.join(missing)}")
    ck = Check()
    build_id = c.sha256(files["B22"])
    payload, ui, hot = (c.read_json(files[n], TOOL) for n in ("B20", "B21", "B27"))
    b22 = c.read_json(files["B22"], TOOL)
    ck.expect(3, b22.get("node") == "B22" and b22.get("stages"), "B22: not a build manifest")
    for name, doc in (("B20", payload), ("B21", ui), ("B27", hot)):
        check_header(ck, name, doc, y, build_id)

    interim, metrics = d / "interim" / f"bah_{y}", d / "interim" / f"metrics_{y}"
    prof_cfg = c.read_json(args.profiles, TOOL)
    sources = {
        "rent": {(r["profile"], r["mha"]): r for r in c.read_csv(metrics / "mha_rent_metrics.csv", {"profile"}, TOOL)},
        "buy": {(r["profile"], r["mha"]): r for r in c.read_csv(metrics / "mha_buy_metrics.csv", {"profile"}, TOOL)},
        "bah": {(r["mha"], r["pay_grade"].upper(), r["has_dependents"].strip().lower()): r["monthly_rate"]
                for r in c.read_csv(interim / "bah_rates.csv", {"mha", "monthly_rate"}, TOOL)},
        "profiles": {p["id"]: p for p in prof_cfg["profiles"]},
    }
    statuses, caveats = check_payload(ck, payload, sources)
    check_ui(ck, ui)
    check_hotspots(ck, hot, payload)

    # Check 6: everything referenced resolves in B21.
    for st in statuses:
        ck.expect(6, st in ui.get("statuses", {}), f"status {st!r} has no B21 entry")
    for cv in caveats | set(hot.get("caveats", [])):
        ck.expect(6, cv in ui.get("caveats", {}), f"caveat {cv!r} has no B21 entry")
    for code in payload.get("areas", {}):
        ck.expect(6, code in ui.get("areas", {}), f"area {code} has no B21 name")

    # Check 4: B7's polygons and B20's codes.
    processed = d / "processed"
    polys = polygon_codes(processed / f"mha_{y}.geojson") | polygon_codes(processed / f"non_mha_{y}.geojson")
    b28_man = c.read_json(processed / f"non_mha_{y}_geometry_manifest.json", TOOL)
    no_polygon = set(b28_man.get("codes_without_polygon", []))
    b7_man = c.read_json(processed / f"areas_{y}_manifest.json", TOOL)
    codes = set(payload.get("areas", {}))
    ck.expect(4, polys <= codes, f"B7 polygons with no B20 entry: {sorted(polys - codes)[:10]}")
    ck.expect(4, codes - polys <= no_polygon,
              f"B20 codes with no polygon that B28 does not list: {sorted(codes - polys - no_polygon)[:10]}")
    ck.expect(4, b7_man.get("features") == len(polys), f"B7 has {b7_man.get('features')} features, "
              f"the B6 + B28 polygons number {len(polys)}")
    ck.expect(4, c.sha256(files["B7"]) == b7_man.get("output_sha256"), "B7 in the handoff folder is not the "
              "archive the B7 manifest recorded")

    # Check 8: SHA256SUMS.
    sums = args.handoff / "SHA256SUMS"
    if not args.no_sums:
        if not sums.exists():
            ck.fail(8, "SHA256SUMS missing")
        else:
            recorded = {}
            for line in sums.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    sha, name = line.split(maxsplit=1)
                    recorded[name.lstrip("*")] = sha
            for node, path in files.items():
                ck.expect(8, recorded.get(path.name) == c.sha256(path),
                          f"SHA256SUMS does not match {path.name} ({node})")

    for n in (3, 4, 5, 6, 7, 8):
        bad = sum(f.startswith(f"[{n}]") for f in ck.failed)
        skipped = n == 8 and args.no_sums
        print(f"check {n}: {ck.passed.get(n, 0):6} passed  {bad:4} failed" + ("  (skipped)" if skipped else ""))
    for f in ck.failed[:40]:
        print(f"  FAIL  {f}")
    if len(ck.failed) > 40:
        print(f"  ... and {len(ck.failed) - 40} more")
    sizes = ", ".join(f"{p.name} {p.stat().st_size / 1024:,.0f} KB" for p in files.values())
    print(f"sizes: {sizes}")
    print("validate_handoff: " + ("FAILED" if ck.failed else "the handoff conforms to the data contract"))
    raise SystemExit(1 if ck.failed else 0)


if __name__ == "__main__":
    main()
