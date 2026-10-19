#!/usr/bin/env python3
"""
package_sources.py  (Layer 1 source archive: sources/)

Packs the authoritative Layer 1 source files from data/raw/ into .zip volumes under
sources/, so the exact inputs behind the 2026 build stay with the repository even if
a provider moves or replaces a file.

    python tools/package_sources.py --year 2026            (or: make sources-zip)
    python tools/package_sources.py --year 2026 --check    # validate and plan only

------------------------------------------------------------------------------
What goes in (decided 18 Oct 2026)
------------------------------------------------------------------------------
  archived     U.S. Government works, not subject to domestic copyright:
               A1 DTMO BAH ASCII, A2 Census ZCTA boundaries, A5 HUD SAFMR,
               A6 DTMO rate components, A8 Treasury FIO workbook, A9 Census ACS
               query result, A12 DTMO out-of-pocket table
  listed only  third-party data whose terms do not clearly allow re-posting the raw
               file: A3 and A4 (Zillow ZORI, ZHVI) and A7 (Freddie Mac PMMS). They
               are named in sources/README.md with their download URL, retrieval
               date and SHA-256, so anyone can fetch them and prove the copy matches.
  not archived A11 Protomaps basemap (an ODbL planet extract built by `make basemap`,
               recorded in its own provenance file); configs A12-A13 (in config/)

A node in the fetch manifest that is in neither list stops the run: a new source
needs a decision before it is published.

------------------------------------------------------------------------------
How
------------------------------------------------------------------------------
  * every file is checked against the SHA-256 the fetch manifest recorded when it
    was pulled (a mismatch stops the run: the archive must hold the files the build
    used)
  * members are stored as <node>/<vendor file name>; files that are already
    compressed (.zip, .xlsx, .pdf) are stored, the rest deflated at level 9; every
    member gets the same fixed timestamp, so a rerun on the same files gives the
    same archive
  * volumes are filled largest file first and kept under --max-mb (default 95, below
    GitHub's 100 MB per-file limit). One file larger than the limit stops the run.
  * each volume carries SOURCES_INDEX.txt describing its own members and the terms

------------------------------------------------------------------------------
Output (sources/, committed)
------------------------------------------------------------------------------
  layer1_sources_<year>[_partN].zip   the volume(s)
  SHA256SUMS                          SHA-256 of every volume
  sources_manifest.json               every Layer 1 node: archived (volume, member,
                                      bytes, SHA-256) or listed only (URL, SHA-256),
                                      with name, retrieval date and license
  README.md                           the same, for people

Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = "package_sources"
PUBLIC_DOMAIN = {"A1", "A2", "A5", "A6", "A8", "A9", "A12"}
LISTED_ONLY = {
    "A3": "Zillow terms: free for public use with attribution; re-posting the raw file is not addressed",
    "A4": "Zillow terms: free for public use with attribution; re-posting the raw file is not addressed",
    "A7": "Freddie Mac content-use policy: republishing PMMS is licensed for websites under its terms",
}
STORED = {".zip", ".xlsx", ".pdf", ".pmtiles", ".png"}
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
GITHUB_LIMIT_MB = 100


def die(msg: str) -> None:
    sys.exit(f"{TOOL}: {msg}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def member_info(name: str, suffix: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
    info.compress_type = zipfile.ZIP_STORED if suffix in STORED else zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    return info


def compressed_size(path: Path, name: str) -> int:
    """Size the file takes inside a zip, measured by writing it to a scratch archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compresslevel=9) as zf:
        with path.open("rb") as src, zf.open(member_info(name, path.suffix.lower()), "w") as dst:
            for block in iter(lambda: src.read(1 << 20), b""):
                dst.write(block)
    return buf.tell()


def pack(items: list[dict], limit: int) -> list[list[dict]]:
    """First-fit decreasing by compressed size; each volume stays under `limit` bytes."""
    volumes: list[list[dict]] = []
    sizes: list[int] = []
    overhead = 64 * 1024                      # index file, central directory
    for it in sorted(items, key=lambda i: (-i["zip_bytes"], i["member"])):
        if it["zip_bytes"] + overhead > limit:
            die(f"{it['member']} is {it['zip_bytes'] / 1e6:.1f} MB compressed, over the "
                f"{limit / 1e6:.0f} MB volume limit; it cannot be committed as one file")
        for i, used in enumerate(sizes):
            if used + it["zip_bytes"] + overhead <= limit:
                volumes[i].append(it)
                sizes[i] += it["zip_bytes"]
                break
        else:
            volumes.append([it])
            sizes.append(it["zip_bytes"])
    return [sorted(v, key=lambda i: i["member"]) for v in volumes]


def index_text(year: int, volume: str, members: list[dict], listed: list[dict]) -> str:
    lines = [f"BAH Atlas {year} - Layer 1 source archive, volume {volume}",
             "Built by tools/package_sources.py. Full register: docs/SOURCES.md and sources/README.md.",
             "Every file below is a U.S. Government work, not subject to domestic copyright.", ""]
    for m in members:
        lines += [f"{m['member']}", f"  {m['name']}", f"  source:    {m['source_url']}",
                  f"  retrieved: {m['retrieved_at']}", f"  sha256:    {m['sha256']}",
                  f"  bytes:     {m['bytes']}", ""]
    if listed:
        lines += ["Not in this archive (third-party terms); download from the source and compare SHA-256:", ""]
        for t in listed:
            lines += [f"{t['node']} {t['filename']}", f"  {t['source_url']}", f"  sha256: {t['sha256']}",
                      f"  why not archived: {t['reason']}", ""]
    return "\n".join(lines)


def readme(year: int, archived: list[dict], listed: list[dict], vols: dict[str, str]) -> str:
    rows = "\n".join(f"| {m['node']} | {m['name']} | `{m['volume']}` → `{m['member']}` | {m['bytes']:,} | "
                     f"{m['retrieved_at'][:10]} | `{m['sha256']}` |" for m in archived)
    trows = "\n".join(f"| {t['node']} | {t['name']} | {t['source_url']} | {t['retrieved_at'][:10]} | "
                      f"`{t['sha256']}` | {t['reason']} |" for t in listed)
    vrows = "\n".join(f"| `{v}` | `{s}` |" for v, s in vols.items())
    return f"""# Layer 1 source archive ({year})

The authoritative source files behind the {year} build, as they were when the pipeline
read them. Written by `make sources-zip` (`tools/package_sources.py`); every file was
checked against the SHA-256 recorded when it was pulled (`data/raw/fetch_manifest.json`,
copied to [`docs/evidence/fetch_manifest.json`](../docs/evidence/fetch_manifest.json)).
The register of every source, with roles and licences, is [`docs/SOURCES.md`](../docs/SOURCES.md).

To use: unzip the volumes and copy each `<node>/<file>` into `data/raw/`; `make fetch`
then re-validates the files without downloading them again.

## Volumes

| Volume | SHA-256 |
|---|---|
{vrows}

## Archived: U.S. Government works

Not subject to domestic copyright (17 U.S.C. § 105).

| Node | Source | Volume → member | Bytes | Retrieved | SHA-256 |
|---|---|---|---|---|---|
{rows}

## Listed only: third-party data

Decided 18 Oct 2026: these files are not re-posted here, because their providers'
terms do not clearly allow it. Download each from its URL; a copy matching the SHA-256
below is byte-identical to the one the {year} build used. Zillow data must be
attributed to Zillow; PMMS data to Freddie Mac.

| Node | Source | URL | Retrieved | SHA-256 | Why not archived |
|---|---|---|---|---|---|
{trows}

## Not archived

- **A11** Protomaps basemap: an extract of an OpenStreetMap planet build (ODbL), cut by
  `make basemap`; its build date and SHA-256 are in `basemap_provenance.json`.
- **A12–A13** project configs: committed in `config/`.
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--out", type=Path, default=ROOT / "sources")
    ap.add_argument("--max-mb", type=float, default=95.0, help="largest volume in MB (default 95)")
    ap.add_argument("--check", action="store_true", help="validate and print the plan; write nothing")
    args = ap.parse_args()
    if not 0 < args.max_mb < GITHUB_LIMIT_MB:
        die(f"--max-mb must be between 0 and {GITHUB_LIMIT_MB} (GitHub's per-file limit)")

    man_path = args.raw / "fetch_manifest.json"
    try:
        records = json.loads(man_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"{man_path} not found (run `make fetch`)")
    except json.JSONDecodeError as e:
        die(f"{man_path} is not valid JSON: {e}")

    problems, archived, listed = [], [], []
    for node, rec in sorted(records.items(), key=lambda kv: (kv[0][0], int(kv[0][1:]) if kv[0][1:].isdigit() else 0)):
        if not isinstance(rec, dict) or not rec.get("filename"):
            continue
        base = {"node": node, "name": rec.get("name", ""), "filename": rec["filename"],
                "source_url": rec.get("source_url", ""), "retrieved_at": rec.get("retrieved_at") or "",
                "sha256": rec.get("sha256", ""), "license": rec.get("license", "")}
        if node in LISTED_ONLY:
            listed.append({**base, "reason": LISTED_ONLY[node]})
            continue
        if node not in PUBLIC_DOMAIN:
            problems.append(f"{node} ({rec['filename']}) is not classified; add it to PUBLIC_DOMAIN or LISTED_ONLY")
            continue
        path = args.raw / rec["filename"]
        if not path.exists():
            problems.append(f"{node}: {path} not found")
            continue
        actual = sha256(path)
        if actual != base["sha256"]:
            problems.append(f"{node}: {path.name} SHA-256 {actual[:12]}… differs from the fetch manifest's "
                            f"{base['sha256'][:12]}… (re-run `make fetch` or restore the file the build used)")
            continue
        archived.append({**base, "path": path, "bytes": path.stat().st_size,
                         "member": f"{node}/{rec['filename']}"})
    if problems:
        print(f"{TOOL}: cannot build the archive:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)
    if not archived:
        die("no archivable source files found")

    for it in archived:
        it["zip_bytes"] = compressed_size(it["path"], it["member"])
    volumes = pack(archived, int(args.max_mb * 1e6))
    names = ([f"layer1_sources_{args.year}.zip"] if len(volumes) == 1 else
             [f"layer1_sources_{args.year}_part{i + 1}.zip" for i in range(len(volumes))])
    for name, vol in zip(names, volumes):
        for it in vol:
            it["volume"] = name
        print(f"  {name}: {', '.join(i['member'] for i in vol)} "
              f"(~{sum(i['zip_bytes'] for i in vol) / 1e6:.1f} MB)")
    print(f"  listed only (not archived): {', '.join(t['node'] for t in listed) or 'none'}")
    if args.check:
        print(f"{TOOL}: check only; {len(archived)} files would go into {len(volumes)} volume(s) under {args.out}")
        return

    args.out.mkdir(parents=True, exist_ok=True)
    for old in args.out.glob(f"layer1_sources_{args.year}*.zip"):
        old.unlink()
    vol_sha: dict[str, str] = {}
    for name, vol in zip(names, volumes):
        target = args.out / name
        with zipfile.ZipFile(target, "w", compresslevel=9) as zf:
            zf.writestr(member_info("SOURCES_INDEX.txt", ".txt"),
                        index_text(args.year, name, vol, listed).encode("utf-8"))
            for it in vol:
                with it["path"].open("rb") as src, zf.open(member_info(it["member"], it["path"].suffix.lower()),
                                                           "w") as dst:
                    for block in iter(lambda: src.read(1 << 20), b""):
                        dst.write(block)
        size = target.stat().st_size
        if size >= GITHUB_LIMIT_MB * 1e6:
            die(f"{name} came out at {size / 1e6:.1f} MB, over GitHub's {GITHUB_LIMIT_MB} MB limit")
        with zipfile.ZipFile(target) as zf:            # read back: every member intact
            bad = zf.testzip()
            if bad:
                die(f"{name}: member {bad} failed its CRC check")
        vol_sha[name] = sha256(target)
        print(f"  wrote {target.relative_to(ROOT) if target.is_relative_to(ROOT) else target} ({size / 1e6:.1f} MB)")

    (args.out / "SHA256SUMS").write_text("".join(f"{s}  {n}\n" for n, s in vol_sha.items()), encoding="utf-8")
    manifest = {
        "year": args.year,
        "tool": "tools/package_sources.py",
        "policy": "U.S. Government works archived; third-party data listed by URL and SHA-256 (decided 18 Oct 2026)",
        "volumes": {n: {"sha256": s, "bytes": (args.out / n).stat().st_size} for n, s in vol_sha.items()},
        "archived": [{k: v for k, v in it.items() if k not in ("path", "zip_bytes")} for it in archived],
        "listed_only": listed,
        "not_archived": {"A11": "ODbL basemap extract built by make basemap; see basemap_provenance.json",
                         "A12-A13 configs": "committed in config/"},
    }
    (args.out / "sources_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (args.out / "README.md").write_text(readme(args.year, archived, listed, vol_sha), encoding="utf-8")
    print(f"{TOOL}: {len(archived)} files in {len(vol_sha)} volume(s); {len(listed)} listed only -> "
          f"{args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}/")


if __name__ == "__main__":
    main()
