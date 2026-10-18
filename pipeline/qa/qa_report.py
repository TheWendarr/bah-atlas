#!/usr/bin/env python3
"""
qa_report.py  (B23 QA / validation report: data contract check 9 and the M6 QA plan)

Reads a finished handoff and the pipeline tables behind it, and writes one
report a reviewer can read top to bottom:

    python pipeline/qa/qa_report.py --year 2026 \
        --handoff data/processed/handoff --out data/processed/qa

------------------------------------------------------------------------------
What it checks and reports
------------------------------------------------------------------------------
  0  verdict       one line per check below, PASS / FAIL / NOTE
  1  conformance   runs validate_handoff.py (contract checks 3-8) and
                   tools/verify_hashes.py (check 2), and records their output
  2  provenance    the B22 git commit, and that no pipeline code, config or
                   Makefile changed between that commit and HEAD or is
                   uncommitted now: the handoff was built from committed code.
                   B22's own `dirty` flag is shown but not judged, because a
                   rebuild rewrites the docs/evidence copies before B22 runs.
  3  files         size, gzip size and SHA-256 of the five delivered files
                   (check 9), and SHA256SUMS
  4  status        area counts by class, and value-block counts by profile,
                   mode and status (check 9)
  5  rounding      every MHA value whose map class (B21 breaks, class rule
                   bisect_right) differs between the unrounded pipeline value
                   and the rounded B20 value (check 9)
  6  polygons      B20 codes with no B6/B28 polygon (check 4's listed exceptions)
  7  join coverage ZIP -> ZCTA dropout (B6, B28), benchmark coverage (B8-B10),
                   A8 ZCTA and fallback counts, B24 coverage, B19 sample
  8  warnings      every warning carried in the stage manifests
  9  traces        three MHAs followed from the ZIP values to B20 and B27: one
                   in surplus, one short of design, one on a fallback. Each
                   ratio is recomputed from its inputs and compared with B12/B14
                   and B20. Pick them with --trace CODE CODE CODE, or let the
                   script choose (stated in the report). The per-ZIP values are
                   listed so the median can be checked by hand.
  10 ZORI vs SAFMR agreement of the primary benchmark with the HUD cross-check
  11 statistics    H1 (B17/B18: FDR result, permutation floor, k sensitivity,
                   scope) and H2 (B19: chosen model, collinearity, residual
                   Moran's I, reading per predictor)
  12 limitations   every caveat and global caveat text the map will show (B21)

------------------------------------------------------------------------------
Output (written to --out; data/processed/ is git-ignored, so the report enters
the repository only with the D10 delivery commit)
------------------------------------------------------------------------------
  qa_<year>.md               the report
  qa_<year>_manifest.json    node B23: inputs and SHA-256 (the five delivered
                             files among them), verdict per check, the counts,
                             class differences, traces, output SHA-256

Exit status 1 when any check FAILS (the report is still written, so the failure
can be read). Stdlib only.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "handoff"))
import contract as c  # noqa: E402

TOOL = "qa_report"
CODE_PATHS = ["pipeline", "config", "tools", "Makefile", "requirements.txt"]
TOLERANCE = 0.00005          # half a unit in the 4th decimal: the B20 ratio rounding


# --- small helpers --------------------------------------------------------------

def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        c.die(TOOL, f"not found: {path}")
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def read_json(path: Path) -> dict:
    return c.read_json(path, TOOL)


def num(raw: object) -> float | None:
    try:
        s = str(raw).strip()
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def run(cmd: list[str], cwd: Path = ROOT) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def git(*args: str) -> tuple[int, str]:
    return run(["git", "-C", str(ROOT), *args])


def md_table(head: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


def fmt(v: object, places: int = 4) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, float):
        return f"{v:.{places}f}"
    return str(v)


def n_(v: object) -> str:
    """Thousands separator for counts; anything else as text."""
    return f"{v:,}" if isinstance(v, int) and not isinstance(v, bool) else ("—" if v is None else str(v))


def class_of(value: float, breaks: list[float]) -> int:
    return bisect.bisect_right(breaks, value)


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None

    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    return statistics.correlation(ra, rb)


# --- provenance -------------------------------------------------------------------

def code_unchanged_since(commit: str | None) -> tuple[bool, str]:
    """True when `commit` is an ancestor of HEAD and no code path differs from it, committed or not."""
    if not commit:
        return False, "B22 records no git commit"
    rc, _ = git("merge-base", "--is-ancestor", commit, "HEAD")
    if rc != 0:
        return False, f"B22 commit {commit[:12]} is not an ancestor of HEAD"
    _, changed = git("diff", "--name-only", commit, "HEAD", "--", *CODE_PATHS)
    _, dirty = git("status", "--porcelain", "--", *CODE_PATHS)
    if changed.strip():
        return False, f"code changed since B22 commit {commit[:12]}: {', '.join(changed.split()[:8])}"
    if dirty.strip():
        return False, f"uncommitted code changes now: {', '.join(l[3:] for l in dirty.splitlines()[:8])}"
    return True, f"B22 commit {commit[:12]} is an ancestor of HEAD; {', '.join(CODE_PATHS)} unchanged since"


# --- main -------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--handoff", type=Path, required=True, help="folder holding the delivered files")
    ap.add_argument("--out", type=Path, required=True, help="output folder (data/processed/qa)")
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--profiles", type=Path, default=ROOT / "config" / "profiles.json")
    ap.add_argument("--trace", nargs=3, metavar="CODE", help="three MHA codes to trace (default: chosen)")
    ap.add_argument("--no-verify", action="store_true", help="skip tools/verify_hashes.py (tests)")
    ap.add_argument("--no-git", action="store_true", help="skip the provenance check (tests)")
    args = ap.parse_args()

    y, d = args.year, args.data
    interim, bench = d / "interim" / f"bah_{y}", d / "interim" / f"benchmarks_{y}"
    metrics_dir, spatial = d / "interim" / f"metrics_{y}", d / "interim" / f"spatial_{y}"
    context, processed = d / "interim" / f"context_{y}", d / "processed"
    names = c.file_names(y)
    files = {node: args.handoff / name for node, name in names.items()}
    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        c.die(TOOL, f"delivered file(s) missing: {', '.join(missing)} (run `make handoff`)")

    verdict: list[tuple[str, str, str]] = []          # (check, PASS/FAIL/NOTE, detail)
    sec: dict[str, str] = {}

    def judge(check: str, ok: bool, detail: str, note: bool = False) -> None:
        verdict.append((check, "NOTE" if note else ("PASS" if ok else "FAIL"), detail))

    payload, ui, hot, b22 = (read_json(files[n]) for n in ("B20", "B21", "B27", "B22"))
    build_id = c.sha256(files["B22"])
    prof_cfg = read_json(args.profiles)
    profiles = {p["id"]: p for p in prof_cfg["profiles"]}
    primary = prof_cfg.get("default_profile") or next(iter(profiles))

    # 1. conformance ----------------------------------------------------------------
    rc, out = run([sys.executable, str(ROOT / "pipeline" / "handoff" / "validate_handoff.py"),
                   "--year", str(y), "--handoff", str(args.handoff), "--data", str(d), "--profiles",
                   str(args.profiles)])
    judge("Contract checks 3-8 (validate_handoff.py)", rc == 0,
          "the handoff conforms to the data contract" if rc == 0 else "validator reported failures")
    sec["validator"] = out
    if args.no_verify:
        verify_out = "skipped (--no-verify)"
        judge("Check 2: recorded hashes (verify_hashes.py)", True, "skipped", note=True)
    else:
        vrc, verify_out = run([sys.executable, str(ROOT / "tools" / "verify_hashes.py")])
        last = verify_out.splitlines()[-1] if verify_out else ""
        judge("Check 2: recorded hashes (verify_hashes.py)", vrc == 0, last)

    # 2. provenance -----------------------------------------------------------------
    git_rec = b22.get("git") or {}
    if args.no_git:
        prov_ok, prov = True, "skipped (--no-git)"
        judge("Provenance: built from committed code", True, prov, note=True)
    else:
        prov_ok, prov = code_unchanged_since(git_rec.get("commit"))
        judge("Provenance: built from committed code", prov_ok, prov)

    # 3. files -------------------------------------------------------------------------
    file_rows, sizes = [], {}
    for node, path in files.items():
        raw = path.read_bytes()
        gz = len(gzip.compress(raw, compresslevel=9))
        sizes[path.name] = {"bytes": len(raw), "gzip_bytes": gz, "sha256": c.sha256(path)}
        file_rows.append([node, f"`{path.name}`", f"{len(raw):,}", f"{gz:,}", f"`{sizes[path.name]['sha256'][:16]}…`"])
    sums_path = args.handoff / "SHA256SUMS"
    sums_ok = sums_path.exists()
    if sums_ok:
        rec = {}
        for line in sums_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                sha, nm = line.split(maxsplit=1)
                rec[nm.lstrip("*")] = sha
        sums_ok = all(rec.get(p.name) == sizes[p.name]["sha256"] for p in files.values())
    pay_gz = sizes[files["B20"].name]["gzip_bytes"]
    judge("Check 9: file sizes recorded; SHA256SUMS matches", sums_ok,
          f"B20 payload {pay_gz / 1024:,.0f} KB gzipped (plan expectation: under 300 KB)")
    if pay_gz > 300 * 1024:
        judge("B20 size against the plan's 300 KB (gzip) expectation", False, f"{pay_gz / 1024:,.0f} KB", note=True)

    # 4. status counts ------------------------------------------------------------------
    areas = payload.get("areas", {})
    by_class: dict[str, int] = {}
    status_counts: dict[str, dict[str, dict[str, int]]] = {}
    for code, a in areas.items():
        by_class[a["class"]] = by_class.get(a["class"], 0) + 1
        for pid in payload.get("profiles", []):
            for mode in c.MODES:
                st = a[pid][mode]["status"]
                status_counts.setdefault(pid, {}).setdefault(mode, {})
                status_counts[pid][mode][st] = status_counts[pid][mode].get(st, 0) + 1
    status_rows = [[pid, mode, st, n] for pid, modes in status_counts.items() for mode, sts in modes.items()
                   for st, n in sorted(sts.items())]
    judge("Check 9: counts by status recorded", True,
          f"{len(areas)} areas: " + ", ".join(f"{k} {v}" for k, v in sorted(by_class.items())))

    # 5. rounding at breaks -----------------------------------------------------------
    sources = {"rent": {(r["profile"], r["mha"]): r for r in read_csv(metrics_dir / "mha_rent_metrics.csv")},
               "buy": {(r["profile"], r["mha"]): r for r in read_csv(metrics_dir / "mha_buy_metrics.csv")}}
    class_diffs, near_break = [], 0
    for metric, spec in (ui.get("metrics") or {}).items():
        breaks = spec["breaks"]
        for code, a in areas.items():
            if a["class"] != "mha":
                continue
            for pid in payload.get("profiles", []):
                for mode in spec.get("modes", []):
                    rounded = a[pid][mode].get(metric)
                    src = sources[mode].get((pid, code)) or {}
                    unrounded = num(src.get(metric))
                    if rounded is None or unrounded is None:
                        continue
                    if any(abs(unrounded - b) <= (0.5 if metric in c.DOLLAR_FIELDS else TOLERANCE) for b in breaks):
                        near_break += 1
                    cu, cr = class_of(unrounded, breaks), class_of(float(rounded), breaks)
                    if cu != cr:
                        class_diffs.append({"area": code, "profile": pid, "mode": mode, "metric": metric,
                                            "unrounded": unrounded, "rounded": rounded,
                                            "class_unrounded": cu, "class_rounded": cr})
    judge("Check 9: classes that differ between rounded and unrounded values", True,
          f"{len(class_diffs)} value(s) change class; {near_break} sit within rounding of a break",
          note=bool(class_diffs))

    # 6. polygons ---------------------------------------------------------------------
    def poly_codes(path: Path) -> set[str]:
        return {str(f["properties"]["mha"]) for f in read_json(path).get("features", [])}
    polys = poly_codes(processed / f"mha_{y}.geojson") | poly_codes(processed / f"non_mha_{y}.geojson")
    no_polygon = sorted(set(areas) - polys)
    judge("Check 4: B20 codes without a polygon listed", True,
          f"{len(no_polygon)}: {', '.join(no_polygon) if no_polygon else 'none'}")

    # 7. join coverage ------------------------------------------------------------------
    stage = {
        "B6": processed / f"mha_{y}_geometry_manifest.json", "B28": processed / f"non_mha_{y}_geometry_manifest.json",
        "B8": bench / "mha_zori_manifest.json", "B9": bench / "mha_zhvi_manifest.json",
        "B10": bench / "mha_safmr_manifest.json", "A8": bench / "mha_tax_insurance_manifest.json",
        "B11": bench / "mha_ownership_manifest.json", "B12-B15": metrics_dir / "coverage_metrics_manifest.json",
        "B16": spatial / "weights_manifest.json", "B17-B18": spatial / "spatial_stats_manifest.json",
        "B24": context / "mha_density_manifest.json", "B19": spatial / "regression_manifest.json",
    }
    absent = [n for n, p in stage.items() if not p.exists()]
    judge("Every Layer 2 stage manifest present (B6-B19, B24, B28)", not absent,
          "all present" if not absent else f"missing: {', '.join(absent)}")
    man = {n: read_json(p) for n, p in stage.items() if p.exists()}
    cov_rows = []
    b6c = (man.get("B6") or {}).get("counts") or {}
    real_zips = ((man.get("B8") or {}).get("crosswalk") or {}).get("real_mha_zips")
    if b6c:
        cov_rows.append(["B6 ZIP → ZCTA (MHAs)", f"{n_(b6c.get('zips_without_zcta'))} of {n_(real_zips)} ZIPs "
                         "have no ZCTA polygon", f"{b6c.get('mhas', '—')} MHA polygons written"])
    b28 = man.get("B28") or {}
    if b28:
        bc = b28.get("counts") or {}
        cov_rows.append(["B28 ZIP → ZCTA (CCGs, territory)",
                         f"{n_(bc.get('zips_without_zcta'))} of {n_(sum((bc.get('zips_by_class') or {}).values()))} "
                         f"ZIPs have no ZCTA polygon ({json.dumps(bc.get('zips_without_zcta_by_class'))})",
                         f"codes without polygon: {', '.join(b28.get('codes_without_polygon') or []) or 'none'}"])
    for n in ("B8", "B9", "B10"):
        cv = (man.get(n) or {}).get("coverage") or {}
        if cv:
            cov_rows.append([f"{n} benchmark", f"{n_(cv.get('source_zips_in_real_mhas'))} source ZIPs in real MHAs; "
                             f"median ZIP coverage {fmt(cv.get('median_zip_coverage'))}",
                             f"{cv.get('mhas_with_data')} MHAs with data; without: "
                             f"{', '.join(cv.get('mhas_without_data') or []) or 'none'}"])
    a8 = man.get("A8") or {}
    if a8:
        pt, ins = a8.get("property_tax") or {}, a8.get("insurance") or {}
        cov_rows.append(["A8 property tax (ACS)", f"{n_(pt.get('zctas_usable'))} of {n_(pt.get('zctas_in_file'))} "
                         f"ZCTAs usable ({pt.get('acs_period')})",
                         f"{pt.get('mhas_locality')} locality; state fallback: {pt.get('mhas_state_fallback') or 'none'}"])
        cov_rows.append(["A8 insurance (FIO)", f"data year {ins.get('data_year')}, not scaled to {y} (N2)",
                         f"{ins.get('mhas_locality')} locality; state fallback: {ins.get('mhas_state_fallback') or 'none'}"])
    b24 = man.get("B24") or {}
    if b24:
        cov_rows.append(["B24 density (ACS + A2)", f"{n_(b24.get('real_mha_zips_with_usable_zcta'))} real-MHA ZIPs "
                         "matched a usable ZCTA", f"{b24.get('mhas_with_data')} MHAs with a density; without: "
                         f"{', '.join(b24.get('mhas_without_data') or []) or 'none'}"])
    b19 = man.get("B19") or {}
    if b19:
        gw = b19.get("growth_window") or {}
        cov_rows.append(["B19 rent growth (A3 history)", f"{n_(gw.get('zips_with_growth'))} ZIPs with ZORI in both "
                         f"windows ({(gw.get('start_window_months') or ['?'])[0]} → "
                         f"{(gw.get('end_window_months') or ['?'])[0]})",
                         f"{gw.get('mhas_with_growth')} MHAs with growth; not modelled: "
                         f"{json.dumps((b19.get('not_modelled') or {}).get(primary, {}))}"])

    # 8. warnings -----------------------------------------------------------------------
    warn_rows = [[n, w] for n, m in man.items() for w in (m.get("warnings") or [])]

    # 9. traces -------------------------------------------------------------------------
    zori = {r["mha"]: r for r in read_csv(bench / "mha_zori.csv")}
    zip_zori: dict[str, list[tuple[str, str]]] = {}
    for r in read_csv(bench / "zip_zori.csv"):
        zip_zori.setdefault(r["mha"], []).append((r["zip"], r["value"]))
    own = {r["mha"]: r for r in read_csv(bench / "mha_ownership.csv")}
    n_zips: dict[str, int] = {}
    for r in read_csv(interim / "zip_mha.csv"):
        n_zips[r["mha"]] = n_zips.get(r["mha"], 0) + 1

    def pick() -> list[tuple[str, str]]:
        rent_ok = [(m, num(r["adequacy_gap"])) for (p, m), r in sources["rent"].items()
                   if p == primary and r.get("status") == "ok" and num(r["adequacy_gap"]) is not None]
        chosen: list[tuple[str, str]] = []
        for sign, label in ((1, "surplus: adequacy gap nearest the median of the positive gaps"),
                            (-1, "short of design: adequacy gap nearest the median of the negative gaps")):
            side = [(m, g) for m, g in rent_ok if g * sign > 0]
            conus = [(m, g) for m, g in side if areas.get(m, {}).get("cluster_scope")]
            side = conus or side                     # prefer MHAs inside the spatial-statistics scope
            if side:
                med = statistics.median(g for _, g in side)
                chosen.append((min(side, key=lambda t: (abs(t[1] - med), t[0]))[0], label))
        # The third MHA shows a fallback path. An A8 state fallback is preferred; the PITI-only buy cost
        # (decision 2.4) is used when none exists or when the only candidates are already traced.
        taken = {m for m, _ in chosen}
        fb = [m for m in sorted(own) if m not in taken
              and "state_fallback" in (own[m].get("tax_source"), own[m].get("insurance_source"))]
        piti = sorted(m for (p, m), r in sources["buy"].items()
                      if p == primary and r.get("status") == "piti_only_no_zori" and m not in taken)
        piti.sort(key=lambda m: not areas.get(m, {}).get("cluster_scope"))      # CONUS first
        if fb:
            chosen.append((fb[0], "fallback: property tax or insurance from the A8 state fallback"))
        elif piti:
            chosen.append((piti[0], "fallback: buy cost on PITI alone, no ZORI for utilities (decision 2.4)"))
        return chosen

    picks = [(code, "chosen by the author (--trace)") for code in args.trace] if args.trace else pick()
    traces, trace_md, trace_ok = [], [], True
    for code, why in picks:
        if code not in areas:
            judge(f"Trace {code}", False, "not an area code in B20")
            trace_ok = False
            continue
        t: dict = {"area": code, "why": why, "rows": []}
        lines = [f"### {code} — {ui.get('areas', {}).get(code, {}).get('name', '')}", "", f"*Why this MHA:* {why}.", ""]
        z = zori.get(code, {})
        zips = sorted(zip_zori.get(code, []))
        zvals = [num(v) for _, v in zips if num(v) is not None]
        lines.append(f"- **B1**: {n_zips.get(code, 0)} ZIPs assigned by DTMO.")
        if zips:
            med = statistics.median(zvals)
            lines.append(f"- **B8**: {len(zips)} ZIPs with ZORI in the window: " +
                         ", ".join(f"{zz} ${float(v):,.2f}" for zz, v in zips[:12]) +
                         (f" … and {len(zips) - 12} more" if len(zips) > 12 else "") +
                         f". Median recomputed **${med:,.2f}**; B8 `zori_median` ${float(z.get('zori_median') or 0):,.2f}.")
            t["zori_median_recomputed"] = round(med, 2)
            t["zori_median_b8"] = num(z.get("zori_median"))
            if t["zori_median_b8"] is not None and abs(med - t["zori_median_b8"]) > 0.01:
                trace_ok = False
            share, adj = num(z.get("rent_share")), num(z.get("zori_utilities_adjusted"))
            if share and adj:
                lines.append(f"- **B5 → B8**: rent share {share:.4f}; utilities-inclusive cost "
                             f"{med:,.2f} ÷ {share:.4f} = **{med / share:,.2f}** (B8: {adj:,.2f}).")
                if abs(med / share - adj) > 0.02:
                    trace_ok = False
        else:
            lines.append("- **B8**: no ZIP in this MHA has ZORI in the window.")
        o = own.get(code, {})
        if o:
            lines.append(f"- **B11**: PITI {fmt(num(o.get('own_housing_monthly')), 2)}, with utilities "
                         f"{fmt(num(o.get('own_total_monthly')), 2)}; tax {o.get('tax_source')}, "
                         f"insurance {o.get('insurance_source')}.")
        rows = []
        for pid in payload.get("profiles", []):
            for mode in c.MODES:
                s = sources[mode].get((pid, code)) or {}
                blk = areas[code][pid][mode]
                bah, cs, cost = num(s.get("bah_monthly")), num(s.get("cost_share_monthly")), num(s.get("cost_monthly"))
                recomputed = (bah + cs) / cost if None not in (bah, cs, cost) and cost else None
                pipe, sent = num(s.get("adequacy_ratio")), blk.get("adequacy_ratio")
                agree = (recomputed is None and sent is None) or (
                    recomputed is not None and pipe is not None and sent is not None
                    and abs(recomputed - pipe) <= 2 * TOLERANCE and abs(float(sent) - recomputed) <= 2 * TOLERANCE)
                trace_ok &= agree
                hs = ((hot.get("areas") or {}).get(code) or {}).get(pid, {}).get(mode, {})
                rows.append([pid, mode, blk["status"], fmt(bah, 2), fmt(cs, 2), fmt(cost, 2), fmt(recomputed),
                             fmt(pipe), fmt(sent), "yes" if agree else "**NO**",
                             hs.get("cluster") or "—", "yes" if hs.get("lisa_fdr_significant") else "—"])
                t["rows"].append({"profile": pid, "mode": mode, "status": blk["status"], "bah": bah,
                                  "cost_share": cs, "cost": cost, "adequacy_recomputed": recomputed,
                                  "adequacy_b12_b14": pipe, "adequacy_b20": sent, "agree": agree,
                                  "b27_cluster": hs.get("cluster")})
        lines += ["", md_table(["profile", "mode", "status", "BAH (B4)", "cost share (A12)", "cost (B8/B11)",
                                "(BAH + share) ÷ cost", "B12/B14", "B20", "agree", "B27 cluster", "FDR"], rows),
                  "", "- Hand-check against the raw files: record initials, date and result in the progress note's B23 "
                  "entry. This report is not edited, so its SHA-256 stays as B23 recorded it.", ""]
        traces.append(t)
        trace_md += lines
    judge("Traces: three MHAs recomputed from inputs to B20", trace_ok and len(traces) == 3,
          ", ".join(f"{t['area']}" for t in traces) + (" agree at every step" if trace_ok else " — see section 9"))

    # 10. ZORI vs SAFMR -------------------------------------------------------------------
    agree_rows = []
    for pid in profiles:
        pairs = [(num(r["cost_monthly"]), num(r["safmr_monthly"]), num(r["adequacy_ratio"]),
                  num(r["safmr_adequacy_ratio"]))
                 for (p, m), r in sources["rent"].items() if p == pid and r.get("status") == "ok"]
        pairs = [x for x in pairs if None not in x and x[1]]
        if not pairs:
            continue
        ratios = [a / b for a, b, _, _ in pairs]
        q = statistics.quantiles(ratios, n=4) if len(ratios) >= 4 else [None, None, None]
        same = sum((ar < 1) == (sr < 1) for _, _, ar, sr in pairs)
        rho = spearman([a for a, *_ in pairs], [b for _, b, *_ in pairs])
        agree_rows.append([pid, profiles[pid].get("anchor_bedrooms"), len(pairs), fmt(statistics.median(ratios), 3),
                           f"{fmt(q[0], 3)} – {fmt(q[2], 3)}", fmt(rho, 3),
                           sum(ar < 1 for *_, ar, _ in pairs), sum(sr < 1 for *_, sr in pairs),
                           f"{same / len(pairs):.1%}"])

    # 11. statistics ----------------------------------------------------------------------
    sp = man.get("B17-B18") or {}
    head = sp.get("headline") or {}
    prim = next((t for t in sp.get("tests", []) if t.get("role") == "primary"), {})
    stat_lines = []
    if head:
        meth = sp.get("method") or {}
        stat_lines += [
            f"- **H1, confirmatory (B17):** {head.get('test')}: Moran's I = {head.get('moran_I')}, pseudo p = "
            f"{head.get('p_sim')}, n = {head.get('n')} — {head.get('h1_reading')}.",
            f"- **Permutation floor:** {n_(meth.get('permutations'))} permutations (seed {meth.get('seed')}); smallest "
            f"attainable p: global {((meth.get('min_attainable_p_sim') or {}).get('global'))}, local two-sided "
            f"{((meth.get('min_attainable_p_sim') or {}).get('local_two_sided'))}.",
            f"- **Local clusters, exploratory (B18, D2):** {json.dumps(head.get('lisa_clusters'))} at p < "
            f"{meth.get('alpha')}; {head.get('lisa_fdr_significant')} survive the Benjamini–Hochberg correction "
            f"(cut-off p = {(prim.get('lisa') or {}).get('fdr_cutoff_p')}).",
            f"- **k sensitivity of the global I:** {json.dumps(prim.get('moran_sensitivity'))}.",
            f"- **Scope:** {((sp.get('scope') or {}).get('rule'))}; excluded: "
            f"{', '.join((sp.get('scope') or {}).get('excluded') or [])}."]
    rh = b19.get("headline") or {}
    if rh:
        prim_run = next((r for r in b19.get("runs", []) if r.get("role") == "primary"), {})
        vifs = [cc.get("vif") for cc in (prim_run.get("ols") or {}).get("coefficients", []) if cc.get("vif")]
        stat_lines += [
            f"- **H2 (B19):** {rh.get('test')}, n = {rh.get('n')}: model **{rh.get('model')}** "
            f"({rh.get('choice_reason')}); OLS R² {rh.get('ols_r2')}; largest VIF {max(vifs) if vifs else '—'}.",
            f"- **Residual Moran's I:** OLS {json.dumps(rh.get('residual_moran_ols') or (prim_run.get('ols') or {}).get('residual_moran'))}"
            + (f", chosen model {json.dumps(rh.get('residual_moran_model'))}" if rh.get("residual_moran_model") else "") + "."]
        for p_ in rh.get("predictors", []):
            stat_lines.append(f"  - `{p_['predictor']}`: b = {p_['b']}, p = {p_['p']} — {p_['reading']}.")
        stat_lines.append(f"- **Shared denominator:** {((b19.get('method') or {}).get('caveat'))}.")

    # 12. limitations -----------------------------------------------------------------------
    lim_rows = [[f"`{cid}`", cv.get("level"), cv.get("title"), cv.get("text")]
                for cid, cv in (ui.get("caveats") or {}).items()]
    lim_rows += [[f"`{g.get('id')}`", "global", g.get("title"), g.get("text")] for g in ui.get("global_caveats") or []]

    # --- write ------------------------------------------------------------------------------
    failed = [v for v in verdict if v[1] == "FAIL"]
    lines = [
        f"# QA / validation report — BAH Atlas {y} handoff (B23)", "",
        f"*Generated {c.now_utc()} by `pipeline/qa/qa_report.py`. build_id `{build_id}` · schema "
        f"{payload.get('schema_version')} · B22 commit `{(git_rec.get('commit') or '?')[:12]}` "
        f"(B22 `dirty`: {git_rec.get('dirty')}).*", "",
        f"**Verdict: {'FAIL — ' + str(len(failed)) + ' check(s) failed' if failed else 'PASS'}**", "",
        "## 0. Checks", "", md_table(["Check", "Result", "Detail"], [list(v) for v in verdict]), "",
        "## 1. Contract conformance", "", "`validate_handoff.py` (checks 3–8):", "", "```", sec["validator"], "```", "",
        "`verify_hashes.py` (check 2):", "", "```", verify_out[-3000:], "```", "",
        "## 2. Provenance", "", f"- {prov}",
        "- B22's own `dirty` flag records the tree when B22 ran. A rebuild rewrites the `docs/evidence/` copies "
        "before B22 runs, so `dirty: true` alone does not mean code was uncommitted; the check above compares the "
        "code paths directly.", "",
        "## 3. Delivered files (check 9)", "", md_table(["Node", "File", "Bytes", "gzip bytes", "SHA-256"], file_rows), "",
        f"`SHA256SUMS` matches all five: {'yes' if sums_ok else '**no**'}.", "",
        "## 4. Counts by status (check 9)", "",
        "Areas by class: " + ", ".join(f"{k} {v}" for k, v in sorted(by_class.items())) + ".", "",
        md_table(["Profile", "Mode", "Status", "Areas"], status_rows), "",
        "## 5. Classes changed by rounding (check 9)", "",
        "The map classifies the rounded B20 values; the pipeline counted classes on unrounded values "
        "(ICD section 6, class rule `bisect_right`).", "",
        (md_table(["Area", "Profile", "Mode", "Metric", "Unrounded", "B20", "Class (unrounded)", "Class (B20)"],
                  [[x["area"], x["profile"], x["mode"], x["metric"], x["unrounded"], x["rounded"],
                    x["class_unrounded"], x["class_rounded"]] for x in class_diffs])
         if class_diffs else "None: no MHA value changes class."), "",
        f"{near_break} value(s) sit within rounding distance of a break.", "",
        "## 6. Areas without a polygon (check 4)", "",
        (", ".join(no_polygon) if no_polygon else "None: every B20 code has a B6 or B28 polygon."), "",
        "## 7. Join coverage", "", md_table(["Step", "Coverage", "Result"], cov_rows), "",
        "## 8. Warnings carried in the stage manifests", "",
        md_table(["Stage", "Warning"], warn_rows) if warn_rows else "None.", "",
        "## 9. Traces: three MHAs from the ZIP values to B20", "",
        "Each adequacy ratio is recomputed from its inputs and compared with the pipeline table (B12/B14, "
        "tolerance 0.0001) and with B20 after the contract's rounding.", "", *trace_md,
        "## 10. ZORI against SAFMR (rent cross-check)", "",
        "Cost = utilities-inclusive ZORI (B8); SAFMR = HUD FY2026 at the profile's anchor bedrooms (B10, gross "
        "rent at the 40th percentile, so expected to sit below a median benchmark).", "",
        md_table(["Profile", "Bedrooms", "MHAs", "Median ZORI ÷ SAFMR", "IQR", "Spearman ρ",
                  "Below design (ZORI)", "Below design (SAFMR)", "Same verdict"], agree_rows) if agree_rows else "No rows.", "",
        "## 11. Statistical caveats", "", *(stat_lines or ["No spatial manifests found."]), "",
        "## 12. Limitations shown on the map (B21)", "",
        md_table(["Id", "Level", "Title", "Text"], lim_rows) if lim_rows else "None.", "",
    ]
    args.out.mkdir(parents=True, exist_ok=True)
    report = args.out / f"qa_{y}.md"
    report.write_text("\n".join(lines), encoding="utf-8")

    inputs = {**{n: p for n, p in files.items()}, "B12": metrics_dir / "mha_rent_metrics.csv",
              "B14": metrics_dir / "mha_buy_metrics.csv", "B8": bench / "mha_zori.csv", "B11": bench / "mha_ownership.csv"}
    manifest = {
        "nodes": ["B23"],
        "generated_at": c.now_utc(),
        "build_id": build_id,
        "schema_version": payload.get("schema_version"),
        "inputs": {k: v.name for k, v in inputs.items()},
        "input_sha256": {k: c.sha256(v) for k, v in inputs.items()},
        "verdict": "FAIL" if failed else "PASS",
        "checks": [{"check": a, "result": b, "detail": d_} for a, b, d_ in verdict],
        "provenance": {"b22_commit": git_rec.get("commit"), "b22_dirty": git_rec.get("dirty"), "detail": prov},
        "files": sizes,
        "areas_by_class": by_class,
        "status_counts": status_counts,
        "rounding_class_differences": class_diffs,
        "values_near_a_break": near_break,
        "codes_without_polygon": no_polygon,
        "traces": traces,
        "outputs": [report.name, f"qa_{y}_manifest.json"],
        "output_sha256": {report.name: c.sha256(report)},
    }
    (args.out / f"qa_{y}_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                                  encoding="utf-8")

    for check, result, detail in verdict:
        print(f"  {result:4}  {check}: {detail}")
    print(f"B23 QA report: {'FAIL' if failed else 'PASS'} -> {report}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
