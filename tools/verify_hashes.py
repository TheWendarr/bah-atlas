#!/usr/bin/env python3
"""Verify every SHA-256 the project records, so evidence and inputs provably agree.

Each pipeline stage writes a manifest that records the SHA-256 of the files it
read (and some record the files they wrote). `make evidence` copies those
manifests into docs/evidence/. This script reads every committed manifest and
checks four things:

  1. evidence   each committed copy in docs/evidence/ matches the hash recorded
                for it in docs/evidence/index.csv (`copy_sha256`)
  2. configs    every hash a stage recorded for a project config
                (config/profiles.json A12, config/classification.json A13,
                config/ownership.json) matches the config as it is now
  3. chain      every file named by more than one manifest carries the same hash
                everywhere: a stage's recorded input equals what the fetcher or the
                producing stage recorded for that file, and two stages that read
                the same file read the same version
  4. live       with data/ present (your workstation), every hashed file found
                under data/ or config/ matches its recorded hash, and every
                evidence copy is current with the pipeline manifest it came from

Checks 1-3 need only the repository; check 4 is skipped where data/ is absent
(a fresh clone, CI). A file named in a manifest but not present locally is
reported as skipped, never as passing.

Usage:
    python tools/verify_hashes.py              (or: make verify)
    python tools/verify_hashes.py --repo-only  # skip check 4
    python tools/verify_hashes.py -v           # also list every skipped item

Exit status 1 if any check fails. Stdlib only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEX64 = set("0123456789abcdef")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def is_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX64


@dataclass(frozen=True)
class Claim:
    """One recorded statement: file `name` had hash `sha`, according to `where`."""
    name: str
    sha: str
    where: str
    role: str  # "input" (a stage read it) or "output" (fetched or written by a stage)


def claims_in(manifest: object, label: str) -> list[Claim]:
    """Every (file, sha256) statement in one manifest, whatever its layout.

    Layouts in use:
      inputs {node: file} + input_sha256 {node: sha}      (B6, B7, B11, B12-B18, B28)
      input_file + input_sha256                            (B5, B8-B10)
      config + config_sha256                               (B11)
      output_file + output_sha256                          (B7)
      outputs [files] + output_sha256 {file: sha}          (B1-B4, B6, B28)
      {"filename": ..., "sha256": ...} anywhere            (fetch manifest entries)
      {"artifact": path, "sha256": ...} anywhere           (A12 cost-share PDF)
    """
    out: list[Claim] = []

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            ins, shas = node.get("inputs"), node.get("input_sha256")
            if isinstance(ins, dict) and isinstance(shas, dict):
                for key, fname in ins.items():
                    if isinstance(fname, str) and is_sha(shas.get(key)):
                        out.append(Claim(Path(fname).name, shas[key], f"{label} {path}input_sha256.{key}", "input"))
            if isinstance(node.get("input_file"), str) and is_sha(node.get("input_sha256")):
                out.append(Claim(Path(node["input_file"]).name, node["input_sha256"], f"{label} {path}input_sha256", "input"))
            if isinstance(node.get("config"), str) and is_sha(node.get("config_sha256")):
                out.append(Claim(Path(node["config"]).name, node["config_sha256"], f"{label} {path}config_sha256", "input"))
            if isinstance(node.get("output_file"), str) and is_sha(node.get("output_sha256")):
                out.append(Claim(Path(node["output_file"]).name, node["output_sha256"], f"{label} {path}output_sha256", "output"))
            if isinstance(node.get("output_sha256"), dict):
                for fname, sha in node["output_sha256"].items():
                    if is_sha(sha):
                        out.append(Claim(Path(fname).name, sha, f"{label} {path}output_sha256.{fname}", "output"))
            if isinstance(node.get("filename"), str) and is_sha(node.get("sha256")):
                out.append(Claim(Path(node["filename"]).name, node["sha256"], f"{label} {path}sha256", "output"))
            if isinstance(node.get("artifact"), str) and is_sha(node.get("sha256")):
                out.append(Claim(Path(node["artifact"]).name, node["sha256"], f"{label} {path}sha256", "input"))
            for key, value in node.items():
                walk(value, f"{path}{key}.")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}{i}.")

    walk(manifest, "")
    return out


class Report:
    def __init__(self) -> None:
        self.passed: dict[str, int] = {}
        self.failed: list[str] = []
        self.skipped: list[str] = []

    def ok(self, check: str) -> None:
        self.passed[check] = self.passed.get(check, 0) + 1

    def fail(self, check: str, msg: str) -> None:
        self.failed.append(f"[{check}] {msg}")

    def skip(self, check: str, msg: str) -> None:
        self.skipped.append(f"[{check}] {msg}")


def load_index(root: Path) -> list[dict]:
    index = root / "docs" / "evidence" / "index.csv"
    if not index.exists():
        return []
    with index.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_claims(root: Path, rows: list[dict]) -> list[Claim]:
    claims: list[Claim] = []
    for r in rows:
        if not r["file"].endswith(".json"):
            continue
        path = root / "docs" / "evidence" / r["file"]
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        claims += claims_in(manifest, r["file"])
        # A manifest that another stage reads (B16's weights manifest) is itself a
        # produced file: its pipeline-side hash is the one index.csv records.
        if is_sha(r.get("sha256")):
            claims.append(Claim(Path(r["source"]).name, r["sha256"], f"index.csv {r['file']}", "output"))
    # Authored config that records a hash of a raw artifact (A12 cost-share PDF).
    profiles = root / "config" / "profiles.json"
    if profiles.exists():
        try:
            claims += claims_in(json.loads(profiles.read_text(encoding="utf-8")), "config/profiles.json")
        except json.JSONDecodeError:
            pass
    return claims


def check_evidence(root: Path, rows: list[dict], rep: Report) -> None:
    for r in rows:
        copy = root / "docs" / "evidence" / r["file"]
        if not copy.exists():
            rep.fail("evidence", f"{r['file']} is listed in index.csv but missing")
        elif not is_sha(r.get("copy_sha256")):
            rep.skip("evidence", f"{r['file']}: index.csv has no copy_sha256 (run `make evidence`)")
        elif sha256_file(copy) != r["copy_sha256"]:
            rep.fail("evidence", f"{r['file']} was changed after `make evidence` copied it")
        else:
            rep.ok("evidence")


def check_configs(root: Path, claims: list[Claim], rep: Report) -> None:
    config_dir = root / "config"
    for c in claims:
        target = config_dir / c.name
        if c.role != "input" or not target.exists():
            continue
        if sha256_file(target) == c.sha:
            rep.ok("configs")
        else:
            rep.fail("configs", f"{c.where}: config/{c.name} has changed since this stage ran "
                                f"(recorded {c.sha[:12]}, now {sha256_file(target)[:12]}); rerun the stage")


def check_chain(claims: list[Claim], rep: Report) -> None:
    by_name: dict[str, list[Claim]] = {}
    for c in claims:
        by_name.setdefault(c.name, []).append(c)
    for name, group in sorted(by_name.items()):
        if len(group) < 2:
            continue
        shas = {c.sha for c in group}
        if len(shas) == 1:
            rep.ok("chain")
        else:
            detail = "; ".join(f"{c.where} = {c.sha[:12]}" for c in group)
            rep.fail("chain", f"{name} is recorded with {len(shas)} different hashes: {detail}")


def find_live(root: Path, name: str) -> list[Path]:
    hits = [root / "config" / name] if (root / "config" / name).exists() else []
    data = root / "data"
    if data.is_dir():
        hits += [p for p in data.rglob(name) if p.is_file()]
    return hits


def has_pipeline_data(root: Path) -> bool:
    """True when data/ holds more than the tracked skeleton (.gitkeep, README.md)."""
    data = root / "data"
    return data.is_dir() and any(p.is_file() and p.name not in (".gitkeep", "README.md")
                                 for p in data.rglob("*"))


def check_live(root: Path, rows: list[dict], claims: list[Claim], rep: Report) -> None:
    if not has_pipeline_data(root):
        rep.skip("live", "no pipeline data under data/; live checks run on the workstation that holds it")
        return
    for r in rows:
        src = root / r["source"]
        if not src.exists():
            rep.skip("live", f"{r['file']}: pipeline source {r['source']} not present")
        elif sha256_file(src) == r.get("sha256"):
            rep.ok("live")
        else:
            rep.fail("live", f"{r['file']} is older than {r['source']}; run `make evidence`")
    seen: set[tuple[str, str]] = set()
    for c in claims:
        if (c.name, c.sha) in seen:
            continue
        seen.add((c.name, c.sha))
        hits = find_live(root, c.name)
        if not hits:
            rep.skip("live", f"{c.name} not found under data/ or config/ ({c.where})")
            continue
        if any(sha256_file(p) == c.sha for p in hits):
            rep.ok("live")
        else:
            where = ", ".join(str(p.relative_to(root)) for p in hits)
            rep.fail("live", f"{c.where}: {where} no longer matches the recorded {c.sha[:12]}; "
                             f"rerun from this stage onward")


def verify(root: Path, repo_only: bool = False) -> Report:
    rep = Report()
    rows = load_index(root)
    if not rows:
        rep.fail("evidence", "docs/evidence/index.csv is missing or empty; run `make evidence`")
        return rep
    claims = load_claims(root, rows)
    check_evidence(root, rows, rep)
    check_configs(root, claims, rep)
    check_chain(claims, rep)
    if not repo_only:
        check_live(root, rows, claims, rep)
    return rep


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-only", action="store_true", help="skip the checks that need data/")
    ap.add_argument("-v", "--verbose", action="store_true", help="list every skipped item")
    args = ap.parse_args()
    rep = verify(ROOT, args.repo_only)
    for check in ("evidence", "configs", "chain", "live"):
        n = rep.passed.get(check, 0)
        bad = sum(f.startswith(f"[{check}]") for f in rep.failed)
        skip = sum(s.startswith(f"[{check}]") for s in rep.skipped)
        print(f"{check:9} {n:4} passed  {bad:3} failed  {skip:3} skipped")
    if args.verbose:
        for line in rep.skipped:
            print(f"  skip  {line}")
    elif rep.skipped:
        print(f"  ({len(rep.skipped)} skipped item(s); list them with -v)")
    for line in rep.failed:
        print(f"  FAIL  {line}")
    print("verify_hashes: " + ("FAILED" if rep.failed else "all recorded hashes agree"))
    sys.exit(1 if rep.failed else 0)


if __name__ == "__main__":
    main()
