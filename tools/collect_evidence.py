#!/usr/bin/env python3
"""Copy pipeline results into docs/evidence/ so progress notes can link to them.

Pipeline outputs live under data/ and are gitignored (they are large and
reproducible). Each stage also writes a small JSON manifest: input hashes,
row counts, validation results, per-profile summaries, warnings. Those
manifests are the analysis results a reviewer needs to see, so this script
copies them into docs/evidence/, where they are committed and linkable.

    docs/evidence/<name>_manifest.json   one per pipeline manifest found under data/
    docs/evidence/<name>_map.png         result maps a pipeline step drew (e.g. the B18 LISA
                                         cluster map), credited to the nodes of the manifest
                                         beside it that lists the map in its outputs
    docs/evidence/index.csv              file, nodes it records, source path, generated time,
                                         sha256 (of the pipeline file) and copy_sha256 (of the
                                         committed copy, which has machine paths scrubbed)
    docs/evidence/tests.txt              result of the unit-test suite, summary on the first line

File names stay the same from week to week, so `git log -p docs/evidence/` shows
how the results changed over the project.

Usage:
    python tools/collect_evidence.py            (or: make evidence)
    python tools/collect_evidence.py --no-tests

Stdlib only.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "docs" / "evidence"
MAX_BYTES = 1_000_000
NODE_KEY = re.compile(r"^[ABCW]\d{1,2}(\.[a-z0-9]+)?$")   # A16.br3: one file of a multi-file node


def nodes_of(manifest: object) -> list[str]:
    if not isinstance(manifest, dict):
        return []
    if isinstance(manifest.get("nodes"), list):
        return [str(n) for n in manifest["nodes"]]
    if isinstance(manifest.get("node"), str):
        return [manifest["node"]]
    # fetch_manifest.json is keyed by node id
    return sorted((k for k in manifest if NODE_KEY.match(k)),
                  key=lambda k: (k[0], int(k[1:].split(".")[0]), k))


def generated_at(manifest: object) -> str:
    if isinstance(manifest, dict):
        for key in ("generated_at", "ingested_at_utc", "built_at_utc", "created_at", "fetched_at_utc"):
            if isinstance(manifest.get(key), str):
                return manifest[key]
    return ""


def scrub(text: str) -> str:
    """Drop machine-specific absolute paths so the committed copy has none."""
    text = text.replace(str(ROOT) + "/", "")
    return re.sub(r"(/home|/Users)/[^/\"]+/", "~/", text)


def collect() -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    used: set[str] = set()
    for src in sorted(DATA.rglob("*manifest*.json")):
        if src.stat().st_size > MAX_BYTES:
            print(f"  skip {src.relative_to(ROOT)} (over {MAX_BYTES // 1000} kB)")
            continue
        raw = src.read_text(encoding="utf-8")
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError:
            print(f"  skip {src.relative_to(ROOT)} (not valid JSON)")
            continue
        name = src.name if src.name != "manifest.json" else f"{src.parent.name}_manifest.json"
        if name in used:
            name = f"{src.parent.name}_{name}"
        used.add(name)
        text = scrub(raw)
        text = text if text.endswith("\n") else text + "\n"
        (OUT / name).write_text(text, encoding="utf-8")
        rows.append({
            "file": name,
            "nodes": " ".join(nodes_of(manifest)),
            "source": src.relative_to(ROOT).as_posix(),
            "generated_at": generated_at(manifest),
            "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "copy_sha256": hashlib.sha256((OUT / name).read_bytes()).hexdigest(),
        })
        print(f"  {src.relative_to(ROOT)} -> docs/evidence/{name}  [{rows[-1]['nodes'] or 'no node id'}]")
    rows += collect_maps(used)
    with (OUT / "index.csv").open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=["file", "nodes", "source", "generated_at", "sha256", "copy_sha256"])
        wr.writeheader()
        wr.writerows(rows)
    return rows


def collect_maps(used: set[str]) -> list[dict]:
    """Copy result maps (*_map.png) and credit each to the manifest that lists it as an output."""
    rows: list[dict] = []
    for src in sorted(DATA.rglob("*_map.png")):
        if src.stat().st_size > MAX_BYTES:
            print(f"  skip {src.relative_to(ROOT)} (over {MAX_BYTES // 1000} kB)")
            continue
        owner: object = None
        for man in sorted(src.parent.glob("*manifest*.json")):
            try:
                data = json.loads(man.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and src.name in (data.get("outputs") or []):
                owner = data
                break
        name = src.name if src.name not in used else f"{src.parent.name}_{src.name}"
        used.add(name)
        raw = src.read_bytes()
        (OUT / name).write_bytes(raw)
        rows.append({
            "file": name,
            "nodes": " ".join(nodes_of(owner)),
            "source": src.relative_to(ROOT).as_posix(),
            "generated_at": generated_at(owner),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "copy_sha256": hashlib.sha256(raw).hexdigest(),
        })
        print(f"  {src.relative_to(ROOT)} -> docs/evidence/{name}  [{rows[-1]['nodes'] or 'no node id'}]")
    return rows


def run_tests() -> str:
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                          cwd=ROOT, capture_output=True, text=True)
    log = proc.stderr + proc.stdout
    ran = re.search(r"Ran (\d+) tests? in ([\d.]+)s", log)
    verdict = re.search(r"^(OK.*|FAILED.*)$", log, re.MULTILINE)
    summary = (f"{dt.date.today().isoformat()} — "
               f"{ran.group(0) if ran else 'no test run found'} — "
               f"{verdict.group(1) if verdict else 'exit code ' + str(proc.returncode)}")
    (OUT / "tests.txt").write_text(summary + "\n\n" + scrub(log), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-tests", action="store_true", help="skip running the unit tests")
    args = ap.parse_args()
    if not DATA.is_dir():
        sys.exit("collect_evidence: no data/ folder; run the pipeline first")
    print("Pipeline manifests")
    rows = collect()
    maps = sum(r["file"].endswith(".png") for r in rows)
    print(f"copied {len(rows) - maps} manifest(s) and {maps} map(s) to docs/evidence/")
    if not args.no_tests:
        print("Unit tests")
        print("  " + run_tests())


if __name__ == "__main__":
    main()
