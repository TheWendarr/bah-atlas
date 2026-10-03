#!/usr/bin/env python3
"""
fetch_sources.py — BAH Atlas Layer 1 source acquisition.

Pulls the external Layer 1 source nodes into the raw data folder, records
provenance (URL, sha256, byte size, retrieval time) into a fetch manifest, and
validates every download loudly so a stale URL or an anti-bot HTML page fails
instead of quietly poisoning the pipeline.

Design decisions (stated so they can be overridden):
  * Stdlib only. No new dependency is added to a supply-chain-sensitive repo;
    urllib does streaming, headers, and redirects fine.
  * Raw sources are immutable. Existing files are never overwritten unless
    --force is passed; each fetch is written atomically via a .part temp file.
  * Provenance over convenience. Every successful pull updates
    fetch_manifest.json. Once a node's sha256 is known, paste it into the
    registry as expected_sha256 and future fetches verify against it, which
    catches silent upstream mutation.
  * Heterogeneous acquisition. Not every node is a direct file download.
    Each source declares how it is obtained; only 'direct' sources with a URL
    are auto-pulled. The rest print actionable instructions and are not
    counted as run failures.

Acquisition classes:
  direct  — stable direct-download URL; auto-pulled. (URL may be None if it
            still needs verification; then it is reported as "action needed".)
  browser — a stable URL whose host refuses scripted clients (HTTP 403). Download
            it once in a web browser and save it under `filename` in data/raw;
            the fetcher then validates it and records its sha256 like any pull.
  manual  — a human retrieval or a modeling decision; cannot be auto-pulled.
  api     — obtained through a query API, not a file copy; out of scope here.
  build   — produced by a local build step (e.g. tiling), not a download.

URL verification log (2026-10-03):
  A3, A4  Zillow public_csvs paths, ZIP geography; both resolved.
  A5      HUD FY2026 SAFMR, *revised* release (effective 2026-05-21) chosen
          over the original (effective 2025-10-01); see the note on A5.
  A6      DTMO 2026 BAH Rate Component Breakdown PDF; per-MHA rent% / utilities%.
          travel.dod.mil answers scripted requests with 403, so A6 is 'browser'.
  A5      HUD answers *range* requests with an empty 202; full GETs (what this
          script does) return the xlsx normally.
  A7      Switched from FRED to Freddie Mac's own PMMS_history.csv: FRED silently
          drops scripted requests (curl and urllib both time out with 0 bytes).

Filenames follow the vendor's own name where one exists, so files downloaded by
hand earlier are recognised and checksummed instead of downloaded a second time.
  A11     Protomaps daily builds at build.protomaps.com/YYYYMMDD.pmtiles
          (retained ~1 week) -> see pipeline/tiles/build_basemap.sh.

Usage:
  python pipeline/fetch/fetch_sources.py --list     # registry
  python pipeline/fetch/fetch_sources.py            # every auto-pullable source
  python pipeline/fetch/fetch_sources.py A3 A4      # selected nodes
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import socket
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# --- configuration you may want to change ------------------------------------

DEFAULT_DEST = Path("data/raw")          # relative to repo root
MANIFEST_NAME = "fetch_manifest.json"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36 bah-atlas-fetch/0.2"
)
DEFAULT_TIMEOUT = 120     # seconds per request (Zillow ZIP files are 30-100 MB)
DEFAULT_RETRIES = 3       # retries on transient (network / 5xx) errors
CHUNK = 1 << 16           # 64 KiB streaming chunks


# --- source registry ---------------------------------------------------------

@dataclass
class Source:
    node_id: str
    name: str
    filename: str
    acquisition: str                 # direct | browser | manual | api | build
    url: str | None = None
    landing_url: str | None = None   # human page to verify/resolve the URL
    license: str | None = None
    min_bytes: int = 1024            # loud floor to catch error/empty pages
    expected_sha256: str | None = None
    notes: str = ""


SOURCES: list[Source] = [
    Source(
        node_id="A1",
        name="DTMO BAH ASCII 2026",
        filename="BAH-ASCII-2026.zip",
        acquisition="direct",
        url=None,  # already ingested; paste the direct ASCII zip URL to re-pull
        landing_url="https://www.travel.dod.mil/Allowances/Basic-Allowance-for-Housing/BAH-Rate-Files-Alt/",
        license="U.S. Government work (public domain)",
        min_bytes=100_000,
        notes="Already ingested. Current archive includes temporary TX270 rates "
              "(May 16–Dec 31, 2026); re-pull + re-checksum if your copy predates that.",
    ),
    Source(
        node_id="A2",
        name="Census 2020 ZCTA cartographic boundary (1:500k)",
        filename="cb_2020_us_zcta520_500k.zip",
        acquisition="direct",
        url="https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_zcta520_500k.zip",
        landing_url="https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.2020.html",
        license="U.S. Government work (public domain)",
        min_bytes=5_000_000,
        notes="Single 2020 vintage; 1:500k layers were realigned 2023-05-19.",
    ),
    Source(
        node_id="A3",
        name="Zillow ZORI, ZIP-level (smoothed, all homes + multifamily)",
        filename="Zip_zori_uc_sfrcondomfr_sm_month.csv",
        acquisition="direct",
        url="https://files.zillowstatic.com/research/public_csvs/zori/Zip_zori_uc_sfrcondomfr_sm_month.csv",
        landing_url="https://www.zillow.com/research/data/",
        license="Zillow Group, Inc.; free use with attribution (zillow.com/research/data)",
        min_bytes=1_000_000,
        notes="Wide CSV: RegionID, SizeRank, RegionName (ZIP, may lose leading zeros), "
              "RegionType, StateName, State, City, Metro, CountyName, then one column per "
              "month. No bedroom breakdown. Utilities-EXCLUSIVE (gross-up via B5).",
    ),
    Source(
        node_id="A4",
        name="Zillow ZHVI, ZIP-level (all homes, mid-tier, smoothed, SA)",
        filename="Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
        acquisition="direct",
        url="https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
        landing_url="https://www.zillow.com/research/data/",
        license="Zillow Group, Inc.; free use with attribution (zillow.com/research/data)",
        min_bytes=1_000_000,
        notes="Same wide layout as A3. Bedroom-count variants follow the pattern "
              "Zip_zhvi_bdrmcnt_<N>_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv if the "
              "buy-mode anchor needs them later.",
    ),
    Source(
        node_id="A5",
        name="HUD Small Area FMRs FY2026 (revised)",
        filename="fy2026_safmrs_revised.xlsx",
        acquisition="direct",
        url="https://www.huduser.gov/portal/datasets/fmr/fmr2026/fy2026_safmrs_revised.xlsx",
        landing_url="https://www.huduser.gov/portal/datasets/fmr/smallarea/index.html",
        license="U.S. Government work (public domain)",
        min_bytes=100_000,
        notes="Revised FY2026 SAFMRs, effective 2026-05-21, chosen as the current "
              "authoritative vintage. The original (effective 2025-10-01) is "
              "fy2026_safmrs.xlsx in the same folder; record the choice for temporal "
              "alignment. Utilities-INCLUSIVE, by bedroom count (0-4BR).",
    ),
    Source(
        node_id="A6",
        name="DoD BAH Rate Component Breakdown 2026",
        filename="dod_bah_rate_components_2026.pdf",
        acquisition="browser",
        url="https://www.travel.dod.mil/Portals/119/Documents/BAH/PDF_BAH-Rate-Component-Breakdown/2026-BAH-Rate-Component-Breakdown.pdf",
        landing_url="https://www.travel.dod.mil/Allowances/Basic-Allowance-for-Housing/",
        license="U.S. Government work (public domain)",
        min_bytes=10_000,
        notes="One row per MHA (299): rent and utilities as average % of the total BAH "
              "rate, rounded to 1%. Parsed into B5 by pipeline/ingest/ingest_rate_components.py.",
    ),
    Source(
        node_id="A7",
        name="Freddie Mac PMMS weekly history (30-yr and 15-yr fixed)",
        filename="PMMS_history.csv",
        acquisition="direct",
        url="https://www.freddiemac.com/pmms/docs/PMMS_history.csv",
        landing_url="https://www.freddiemac.com/pmms",
        license="Freddie Mac; attribution required (Freddie Mac Primary Mortgage Market Survey)",
        min_bytes=10_000,
        notes="Original publisher, weekly since 1971-04-02. Columns: date (M/D/YYYY), pmms30, "
              "pmms30p (points), pmms15, pmms15p, pmms51, pmms51p, pmms51m, pmms51spread; "
              "blank cells may contain a space. Methodology changed 2022-11-17. FRED's "
              "MORTGAGE30US mirror drops scripted requests, so it is not used.",
    ),
    Source(
        node_id="A8",
        name="Property tax + insurance",
        filename="(n/a)",
        acquisition="manual",
        landing_url="https://data.census.gov",
        notes="Modeling decision, not a file. Property tax: ACS table B25103/DP04 (via A9). "
              "Insurance: NAIC report or a documented flat assumption. [optional] node.",
    ),
    Source(
        node_id="A9",
        name="Census ACS",
        filename="(n/a)",
        acquisition="api",
        landing_url="https://api.census.gov/data/",
        notes="Query the Census Data API (e.g. .../{year}/acs/acs5) with a pinned "
              "year + variable list; do not save a data.census.gov table URL. [optional]",
    ),
    Source(
        node_id="A10",
        name="BEA Regional Price Parities",
        filename="(n/a)",
        acquisition="api",
        landing_url="https://apps.bea.gov/api/",
        notes="Pull the Regional dataset (RPP table) via the BEA API; iTable URLs are "
              "the fragile ones. Needs a free BEA API key. [optional]",
    ),
    Source(
        node_id="A11",
        name="Protomaps basemap (OSM-derived)",
        filename="(build)",
        acquisition="build",
        landing_url="https://docs.protomaps.com/basemaps/downloads",
        license="ODbL; OpenStreetMap attribution required",
        notes="Run `make basemap` (pipeline/tiles/build_basemap.sh): pmtiles-extracts a "
              "region from a daily planet build at build.protomaps.com/YYYYMMDD.pmtiles "
              "into data/processed/basemap.pmtiles. Not a raw-folder download.",
    ),
]


# --- helpers -----------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def human(n: int) -> str:
    x = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if x < 1024 or unit == "GB":
            return f"{x:.1f} {unit}" if unit != "B" else f"{int(x)} B"
        x /= 1024
    return f"{x:.1f} GB"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def looks_like_html(head: bytes) -> bool:
    sniff = head[:512].lstrip().lower()
    return sniff.startswith(b"<!doctype html") or sniff.startswith(b"<html") or b"<head" in sniff[:200]


def validate_file(path: Path, source: Source) -> tuple[bool, str]:
    size = path.stat().st_size
    if size < source.min_bytes:
        return False, f"too small ({human(size)} < floor {human(source.min_bytes)}) — likely an error page"
    with path.open("rb") as f:
        head = f.read(1024)
    if looks_like_html(head):
        return False, "content is HTML, not the expected file — URL is stale or blocked"
    ext = path.suffix.lower()
    if ext in (".zip", ".xlsx"):
        if not zipfile.is_zipfile(path):
            return False, "not a valid zip/xlsx container"
    elif ext == ".pdf":
        if not head.startswith(b"%PDF"):
            return False, "missing %PDF header"
    elif ext == ".csv":
        first_line = head.split(b"\n", 1)[0]
        if b"," not in first_line:
            return False, "first line has no commas — not a CSV"
    return True, "ok"


# --- download ----------------------------------------------------------------

def _stream_to(url: str, tmp: Path, timeout: int) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as out:
        # Some CDNs (Zillow's included) can serve objects gzip-encoded even when the
        # client did not ask; urllib does not decode that, so do it here.
        body = resp
        if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
            body = gzip.GzipFile(fileobj=resp)
        while True:
            chunk = body.read(CHUNK)
            if not chunk:
                break
            out.write(chunk)


def download_direct(source: Source, dest_dir: Path, *, force: bool,
                    timeout: int, retries: int) -> dict:
    """Return a manifest record dict, or raise on failure."""
    target = dest_dir / source.filename
    tmp = target.with_suffix(target.suffix + ".part")

    if target.exists() and not force:
        digest = sha256_file(target)
        if source.expected_sha256 and digest != source.expected_sha256:
            raise RuntimeError(
                f"cached file sha256 {digest[:12]}… != expected {source.expected_sha256[:12]}…"
            )
        ok, reason = validate_file(target, source)
        if not ok:
            raise RuntimeError(f"existing {target.name} failed validation: {reason} "
                               "(delete it or re-run with --force)")
        mtime = datetime.fromtimestamp(target.stat().st_mtime, timezone.utc)
        return {
            "status": "cached", "node_id": source.node_id, "name": source.name,
            "filename": source.filename, "source_url": source.url,
            "sha256": digest, "bytes": target.stat().st_size,
            # Not downloaded by this run: the file's modification time is the best
            # available retrieval date (an earlier manifest record is kept instead).
            "retrieved_at": mtime.isoformat(timespec="seconds"),
            "retrieved_at_basis": "file mtime", "license": source.license,
        }

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            _stream_to(source.url, tmp, timeout)
            break
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"HTTP {e.code} {e.reason} — check the URL") from e
            last_err = e
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            last_err = e
        if attempt < retries:
            time.sleep(2 ** (attempt - 1))
    else:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"network error after {retries} attempts: {last_err}")

    ok, reason = validate_file(tmp, source)
    if not ok:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(reason)

    digest = sha256_file(tmp)
    if source.expected_sha256 and digest != source.expected_sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"sha256 {digest[:12]}… != expected {source.expected_sha256[:12]}… — upstream changed"
        )

    tmp.replace(target)  # atomic promote
    return {
        "status": "fetched", "node_id": source.node_id, "name": source.name,
        "filename": source.filename, "source_url": source.url,
        "sha256": digest, "bytes": target.stat().st_size,
        "retrieved_at": now_iso(), "license": source.license,
    }


def verify_local(source: Source, dest_dir: Path) -> dict | None:
    """Validate and checksum a browser-downloaded file. None if it is not there yet."""
    target = dest_dir / source.filename
    if not target.exists():
        return None
    ok, reason = validate_file(target, source)
    if not ok:
        raise RuntimeError(f"{target} failed validation: {reason}")
    digest = sha256_file(target)
    if source.expected_sha256 and digest != source.expected_sha256:
        raise RuntimeError(f"sha256 {digest[:12]}… != expected {source.expected_sha256[:12]}…")
    mtime = datetime.fromtimestamp(target.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    return {
        "status": "local", "node_id": source.node_id, "name": source.name,
        "filename": source.filename, "source_url": source.url,
        "acquisition": "browser", "sha256": digest, "bytes": target.stat().st_size,
        "retrieved_at": mtime, "license": source.license,
    }


# --- manifest ----------------------------------------------------------------

def load_manifest(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


# --- cli ---------------------------------------------------------------------

def print_registry() -> None:
    print(f"{'NODE':4}  {'ACQ':7}  {'FILE':34}  SOURCE")
    for s in SOURCES:
        where = s.url or (s.landing_url or "")
        auto = "auto" if (s.acquisition == "direct" and s.url) else s.acquisition
        print(f"{s.node_id:4}  {auto:7}  {s.filename:34}  {where}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch BAH Atlas Layer 1 sources into the raw folder.")
    ap.add_argument("nodes", nargs="*", help="node ids to fetch (default: all direct sources)")
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST, help=f"raw folder (default: {DEFAULT_DEST})")
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    ap.add_argument("--list", action="store_true", help="list the registry and exit")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    args = ap.parse_args(argv)

    if args.list:
        print_registry()
        return 0

    selected = SOURCES
    if args.nodes:
        want = {n.upper() for n in args.nodes}
        selected = [s for s in SOURCES if s.node_id.upper() in want]
        missing = want - {s.node_id.upper() for s in selected}
        if missing:
            print(f"unknown node ids: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    args.dest.mkdir(parents=True, exist_ok=True)
    manifest_path = args.dest / MANIFEST_NAME
    manifest = load_manifest(manifest_path)

    fetched, cached, failed, action = [], [], [], []

    for s in selected:
        if s.acquisition == "browser":
            try:
                rec = verify_local(s, args.dest)
            except RuntimeError as e:
                failed.append((s, str(e)))
                print(f"  FAIL  {s.node_id}  {s.name}: {e}")
                continue
            if rec is None:
                action.append(s)
                continue
            manifest[s.node_id] = {k: v for k, v in rec.items() if k != "status"}
            cached.append(s)
            print(f"  local {s.node_id}  {s.name}  {human(rec['bytes'])}  sha {rec['sha256'][:12]}…  (browser download, verified)")
            continue
        if s.acquisition != "direct" or not s.url:
            action.append(s)
            continue
        try:
            rec = download_direct(s, args.dest, force=args.force,
                                  timeout=args.timeout, retries=args.retries)
        except Exception as e:  # noqa: BLE001 — report per-node, keep going
            failed.append((s, str(e)))
            print(f"  FAIL  {s.node_id}  {s.name}: {e}")
            continue
        prior = manifest.get(s.node_id)
        if rec["status"] == "cached" and prior and prior.get("sha256") == rec["sha256"] \
                and prior.get("retrieved_at"):
            pass  # same bytes as an earlier recorded pull: keep that record
        else:
            manifest[s.node_id] = {k: v for k, v in rec.items() if k != "status"}
        if rec["status"] == "fetched":
            fetched.append(s)
            print(f"  GET   {s.node_id}  {s.name}  {human(rec['bytes'])}  sha {rec['sha256'][:12]}…")
        else:
            cached.append(s)
            print(f"  cache {s.node_id}  {s.name}  {human(rec['bytes'])}  (present)")

    save_manifest(manifest_path, manifest)

    if action:
        print("\nAction needed (not auto-pullable):")
        for s in action:
            if s.acquisition == "browser":
                reason = (f"download in a web browser and save as {args.dest / s.filename}\n"
                          f"        {s.url}")
            elif s.acquisition == "direct":
                reason = f"URL not yet verified — resolve at {s.landing_url}"
            elif s.acquisition == "manual":
                reason = "manual retrieval / modeling decision"
            elif s.acquisition == "api":
                reason = "obtain via API, not a file download"
            else:
                reason = "produced by a local build step"
            print(f"  {s.node_id}  {s.name}: {reason}")

    print(f"\nfetched {len(fetched)}  present {len(cached)}  failed {len(failed)}  "
          f"action-needed {len(action)}  ->  {manifest_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
