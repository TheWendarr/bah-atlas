#!/usr/bin/env python3
"""C1, C4, C24: check that a host serves a PMTiles archive the way the map needs.

PMTiles reads a file by HTTP range request. Some hosts answer with the whole file,
or with a slice of a compressed copy that the browser cannot decode, and a page
cannot work around either. This script asks for the real file the way a browser
does (`Accept-Encoding: gzip, br` and an `Origin`), and compares the bytes that come
back with the local copy.

    python tools/check_host.py --url https://HOST/FILE.pmtiles \\
        --local delivery/2026/areas_2026.pmtiles \\
        --origin https://bah-atlas.mcgowanserver.com

    make host-check URL=https://HOST/FILE.pmtiles

Checks:
  range      header, tile-data and last-byte ranges each return 206, the right
             Content-Range and the same bytes as the local file
  encoding   no Content-Encoding on a range response
  etag       an ETag is present and stable between requests
  cors       the origin is allowed on GET, ETag is exposed, and a preflight allows
             the `range` and `if-match` request headers

Exit status 1 if any check fails. Stdlib only.
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

USER_AGENT = "bah-atlas-check-host/1.0"
BROWSER_ENCODING = "gzip, deflate, br"
HEADER_BYTES = 16_384


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    body: bytes


def request(url: str, method: str = "GET", headers: dict[str, str] | None = None, timeout: float = 30) -> Reply:
    """One HTTP exchange. Error statuses are returned, because they are results here."""
    sent = {"User-Agent": USER_AGENT, **(headers or {})}
    req = urllib.request.Request(url, method=method, headers=sent)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return Reply(resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read())
    except urllib.error.HTTPError as err:
        return Reply(err.code, {k.lower(): v for k, v in err.headers.items()}, err.read())


def ranges_for(size: int) -> list[tuple[str, int, int]]:
    """The start of the file, a slice from the middle, and the last bytes."""
    if size < 1:
        raise ValueError("the local file is empty")
    head = min(HEADER_BYTES, size) - 1
    mid = size // 2
    tail = max(size - 1024, 0)
    return [("header", 0, head), ("tile data", mid, min(mid + HEADER_BYTES - 1, size - 1)), ("last bytes", tail, size - 1)]


def check_range(url: str, local: Path, name: str, start: int, end: int, size: int) -> list[str]:
    reply = request(url, headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": BROWSER_ENCODING})
    problems = []
    if reply.status != 206:
        return [f"{name}: HTTP {reply.status}, expected 206 (the host did not honour the range)"]
    expected_range = f"bytes {start}-{end}/{size}"
    if reply.headers.get("content-range") != expected_range:
        problems.append(f"{name}: Content-Range is {reply.headers.get('content-range')!r}, expected {expected_range!r}")
    encoding = reply.headers.get("content-encoding", "identity").lower()
    if encoding != "identity":
        problems.append(f"{name}: Content-Encoding is {encoding!r}; the browser cannot decode a slice of a compressed file")
    with local.open("rb") as fh:
        fh.seek(start)
        wanted = fh.read(end - start + 1)
    if reply.body != wanted:
        problems.append(f"{name}: {len(reply.body):,} bytes returned do not match the local file")
    return problems


def check_etag(url: str) -> list[str]:
    tags = [request(url, headers={"Range": "bytes=0-126"}).headers.get("etag") for _ in range(2)]
    if not tags[0]:
        return ["etag: no ETag header; PMTiles cannot detect a replaced file"]
    if tags[0] != tags[1]:
        return [f"etag: changed between requests ({tags[0]} then {tags[1]})"]
    return []


def check_cors(url: str, origin: str) -> list[str]:
    problems = []
    reply = request(url, headers={"Range": "bytes=0-126", "Origin": origin})
    allowed = reply.headers.get("access-control-allow-origin")
    if allowed not in (origin, "*"):
        problems.append(f"cors: GET allows origin {allowed!r}, expected {origin!r}")
    exposed = reply.headers.get("access-control-expose-headers", "").lower()
    if "etag" not in exposed and "*" not in exposed:
        problems.append("cors: ETag is not in Access-Control-Expose-Headers")
    pre = request(url, method="OPTIONS", headers={
        "Origin": origin, "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "range,if-match"})
    if pre.status not in (200, 204):
        problems.append(f"cors: preflight returned HTTP {pre.status}")
    else:
        headers = pre.headers.get("access-control-allow-headers", "").lower()
        missing = [h for h in ("range", "if-match") if h not in headers and "*" not in headers]
        if missing:
            problems.append(f"cors: preflight does not allow {', '.join(missing)}")
    return problems


def check(url: str, local: Path, origin: str | None) -> list[str]:
    size = local.stat().st_size
    problems: list[str] = []
    for name, start, end in ranges_for(size):
        problems += check_range(url, local, name, start, end, size)
    problems += check_etag(url)
    if origin:
        problems += check_cors(url, origin)
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", required=True, help="the archive on the host")
    ap.add_argument("--local", required=True, type=Path, help="the same archive on disk")
    ap.add_argument("--origin", help="the site origin that will read it (enables the CORS checks)")
    args = ap.parse_args()
    if not args.local.is_file():
        sys.exit(f"check_host: {args.local} not found")
    try:
        problems = check(args.url, args.local, args.origin)
    except (OSError, ValueError) as err:
        sys.exit(f"check_host: could not reach {args.url}: {err}")
    for line in problems:
        print(f"FAIL  {line}")
    if problems:
        print(f"check_host: {len(problems)} problem(s) at {args.url}")
        return 1
    print(f"check_host: {args.url} serves {os.path.getsize(args.local):,} bytes correctly by range")
    return 0


if __name__ == "__main__":
    sys.exit(main())
