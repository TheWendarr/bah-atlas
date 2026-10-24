#!/usr/bin/env python3
"""
deliver_handoff.py  (decision D10; data contract section 12)

Copies a validated handoff into the repository's delivery folder, but only when
every gate below passes. Until then processed data stays on the workstation
(data/ is git-ignored), as D10 requires.

    python tools/deliver_handoff.py --year 2026 --check     # gates only (make deliver-check)
    python tools/deliver_handoff.py --year 2026             # gates, then copy (make deliver)

------------------------------------------------------------------------------
Gates (all must pass; --check prints each and changes nothing)
------------------------------------------------------------------------------
  1  tracker     every Layer 1 and Layer 2 node in docs/wbs/nodes.csv is
                 complete or scrapped, except those named by --allow-open
                 (default W1, which is completed in the delivery commit itself)
  2  contract    validate_handoff.py passes on the handoff folder (checks 3-8)
  3  hashes      tools/verify_hashes.py passes (check 2)
  4  QA          the B23 manifest's verdict is PASS, its build_id is the
                 SHA-256 of the B22 file being delivered, it recorded the same
                 SHA-256 for all six delivered files, and the report beside it
                 is the one it recorded (the report is not edited after it is
                 generated)
  5  provenance  the B22 commit is an ancestor of HEAD, and the pipeline code,
                 configs, tools, Makefile and requirements are unchanged since
                 and have no uncommitted changes
  6  write-up    docs/layer2-writeup.md (W1) exists and no section still
                 carries the scaffold's author marker

------------------------------------------------------------------------------
Delivery
------------------------------------------------------------------------------
  delivery/<year>/  the six delivered files, SHA256SUMS, qa_<year>.md and
                    qa_<year>_manifest.json; each copy is re-hashed against
                    SHA256SUMS and the B23 manifest. An existing, non-empty
                    folder is replaced only with --replace (a re-delivery is a
                    deliberate act, recorded in the ICD change log).

Then: `make done N=W1`, stage delivery/<year>/, docs/layer2-writeup.md and the
tracker, and commit them together (the script prints the commands).
Stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "handoff"))
sys.path.insert(0, str(ROOT / "pipeline" / "qa"))
import contract as c  # noqa: E402
import qa_report as qa  # noqa: E402

TOOL = "deliver_handoff"
AUTHOR_MARKER = "✎ AUTHOR"
LAYER_PREFIXES = ("A", "B", "W")


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def gate_tracker(nodes_csv: Path, allow_open: set[str]) -> tuple[bool, str]:
    with nodes_csv.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    open_nodes = [f"{r['id']} ({r['status']})" for r in rows
                  if r["id"].startswith(LAYER_PREFIXES) and not r["sublayer"].startswith("3")
                  and r["status"] not in ("complete", "scrapped") and r["id"] not in allow_open]
    if open_nodes:
        return False, "open Layer 1-2 nodes: " + ", ".join(open_nodes)
    return True, f"every Layer 1-2 node complete or scrapped (allowed open: {', '.join(sorted(allow_open)) or 'none'})"


def gate_qa(qa_dir: Path, year: int, files: dict[str, Path]) -> tuple[bool, str]:
    man_path, report = qa_dir / f"qa_{year}_manifest.json", qa_dir / f"qa_{year}.md"
    if not man_path.exists() or not report.exists():
        return False, f"B23 output missing in {qa_dir} (run `make qa`)"
    man = json.loads(man_path.read_text(encoding="utf-8"))
    problems = []
    if man.get("verdict") != "PASS":
        problems.append(f"B23 verdict is {man.get('verdict')}")
    if man.get("build_id") != c.sha256(files["B22"]):
        problems.append("B23 was run on a different build (build_id differs); rerun `make qa`")
    recorded = man.get("files") or {}
    stale = [p.name for p in files.values() if (recorded.get(p.name) or {}).get("sha256") != c.sha256(p)]
    if stale:
        problems.append(f"B23 recorded other versions of {', '.join(stale)}")
    if (man.get("output_sha256") or {}).get(report.name) != c.sha256(report):
        problems.append(f"{report.name} differs from the report B23 wrote (it must not be edited)")
    return (not problems), ("; ".join(problems) if problems else
                            f"B23 PASS on build {man['build_id'][:12]}; report unchanged")


def gate_writeup(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"{rel(path)} not found"
    left = sum(AUTHOR_MARKER in line for line in path.read_text(encoding="utf-8").splitlines())
    if left:
        return False, f"{left} section(s) still carry the scaffold marker '{AUTHOR_MARKER}'"
    return True, f"{rel(path)} written (no scaffold markers left)"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--handoff", type=Path, default=ROOT / "data" / "processed" / "handoff")
    ap.add_argument("--qa", type=Path, default=ROOT / "data" / "processed" / "qa")
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--dest", type=Path, default=None, help="default delivery/<year>")
    ap.add_argument("--writeup", type=Path, default=ROOT / "docs" / "layer2-writeup.md")
    ap.add_argument("--nodes", type=Path, default=ROOT / "docs" / "wbs" / "nodes.csv")
    ap.add_argument("--allow-open", nargs="*", default=["W1"], help="node ids allowed to be open (default W1)")
    ap.add_argument("--check", action="store_true", help="run the gates only")
    ap.add_argument("--replace", action="store_true", help="replace an existing delivery folder")
    args = ap.parse_args()

    y = args.year
    dest = args.dest or ROOT / "delivery" / str(y)
    files = {node: args.handoff / name for node, name in c.file_names(y).items()}
    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        c.die(TOOL, f"delivered file(s) missing: {', '.join(missing)} (run `make layer2`)")

    gates: list[tuple[str, bool, str]] = []
    gates.append(("1 tracker", *gate_tracker(args.nodes, set(args.allow_open))))
    rc, out = qa.run([sys.executable, str(ROOT / "pipeline" / "handoff" / "validate_handoff.py"),
                      "--year", str(y), "--handoff", str(args.handoff), "--data", str(args.data)])
    gates.append(("2 contract", rc == 0, out.splitlines()[-1] if out else "no output"))
    rc, out = qa.run([sys.executable, str(ROOT / "tools" / "verify_hashes.py")])
    gates.append(("3 hashes", rc == 0, out.splitlines()[-1] if out else "no output"))
    gates.append(("4 QA", *gate_qa(args.qa, y, files)))
    b22 = c.read_json(files["B22"], TOOL)
    gates.append(("5 provenance", *qa.code_unchanged_since((b22.get("git") or {}).get("commit"))))
    gates.append(("6 write-up", *gate_writeup(args.writeup)))

    for name, ok, detail in gates:
        print(f"  {'PASS' if ok else 'FAIL'}  gate {name}: {detail}")
    if not all(ok for _, ok, _ in gates):
        print(f"{TOOL}: not delivered; processed data stays out of the repository until every gate passes")
        raise SystemExit(1)
    if args.check:
        print(f"{TOOL}: every gate passes; `make deliver` will copy the handoff to {rel(dest)}/")
        return

    if dest.exists() and any(dest.iterdir()):
        if not args.replace:
            c.die(TOOL, f"{dest} already holds a delivery; pass --replace to supersede it (and log it in ICD section 13)")
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    to_copy = list(files.values()) + [args.handoff / "SHA256SUMS", args.qa / f"qa_{y}.md",
                                      args.qa / f"qa_{y}_manifest.json"]
    for src in to_copy:
        shutil.copy2(src, dest / src.name)
    bad = []
    for line in (dest / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if line.strip():
            sha, name = line.split(maxsplit=1)
            if c.sha256(dest / name.lstrip("*")) != sha:
                bad.append(name)
    qa_man = json.loads((dest / f"qa_{y}_manifest.json").read_text(encoding="utf-8"))
    if qa_man["output_sha256"][f"qa_{y}.md"] != c.sha256(dest / f"qa_{y}.md"):
        bad.append(f"qa_{y}.md")
    if bad:
        c.die(TOOL, f"copies in {dest} do not match their recorded SHA-256: {', '.join(bad)}")
    where = rel(dest)
    print(f"{TOOL}: delivered {len(to_copy)} files to {where}/ and checked them against SHA256SUMS and B23")
    print("next:")
    print("  make done N=W1")
    print(f"  git add {where} docs/layer2-writeup.md docs/wbs docs/WBS.md docs/progress docs/evidence")
    print(f'  git commit -m "Close M6: Layer 2 handoff delivered to {where}/ with the W1 write-up"')


if __name__ == "__main__":
    main()
