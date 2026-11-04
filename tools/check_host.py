#!/usr/bin/env python3
"""C1, C4, C24: check that the hosts serve the tiles and the site the way the map needs.

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

Site mode compares the deployed site with web/dist, after a deployment:

    python tools/check_host.py --site https://bah-atlas.mcgowanserver.com --dist web/dist --wait 120

  files      every file in dist answers 200 with the same bytes and the right type
  headers    each header in dist/_headers is on the live response, unchanged

Cloudflare's Bot Fight Mode adds one script before </body> of an HTML page (D33). The
comparison removes that script and nothing else, so any other change to a page fails.

--wait retries until the deployment has reached the site, then reports what still fails.

Exit status 1 if any check fails. Stdlib only.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
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


def read_header_rules(path: Path) -> dict[str, dict[str, str]]:
    """Cloudflare's _headers file: a path rule, then its indented `Name: value` lines."""
    rules: dict[str, dict[str, str]] = {}
    current: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith((" ", "\t")) and line.strip():
            name, value = line.strip().split(":", 1)
            current[name.strip().lower()] = value.strip()
        elif line.strip():
            current = rules.setdefault(line.strip(), {})
    return rules


def expected_type(path: str) -> str | None:
    for suffix, kind in ((".mjs", "javascript"), (".js", "javascript"), (".css", "text/css"),
                         (".json", "json"), (".html", "text/html")):
        if path.endswith(suffix):
            return kind
    return None


def without_bot_script(html: bytes) -> bytes:
    """The page with Cloudflare's script removed, if that script is what ends the body."""
    end = html.rfind(b"</script></body>")
    start = html.rfind(b"<script>", 0, end)
    if end < 0 or start < 0 or b"/cdn-cgi/challenge-platform/" not in html[start:end]:
        return html
    return html[:start] + html[end + len(b"</script>"):]


def check_site(site: str, dist: Path) -> list[str]:
    site = site.rstrip("/")
    rules = read_header_rules(dist / "_headers")
    problems: list[str] = []
    for file in sorted(p for p in dist.rglob("*") if p.is_file() and p.name != "_headers"):
        path = file.relative_to(dist).as_posix()
        reply = request(f"{site}/{'' if path == 'index.html' else path}")
        if reply.status != 200:
            problems.append(f"{path}: HTTP {reply.status}")
            continue
        body = without_bot_script(reply.body) if path.endswith(".html") else reply.body
        if body != file.read_bytes():
            problems.append(f"{path}: the live bytes differ from dist")
        kind = expected_type(path)
        if kind and kind not in reply.headers.get("content-type", ""):
            problems.append(f"{path}: Content-Type is {reply.headers.get('content-type')!r}, expected {kind}")
        wanted = dict(rules.get("/*", {}))
        for rule, headers in rules.items():
            if rule != "/*" and path.startswith(rule.strip("/*") + "/"):
                wanted.update(headers)
        for name, value in wanted.items():
            if reply.headers.get(name) != value:
                problems.append(f"{path}: {name} is {reply.headers.get(name)!r}, expected {value!r}")
    return problems


def run_site(site: str, dist: Path, wait: float) -> int:
    deadline = time.monotonic() + wait
    while True:
        problems = check_site(site, dist)
        if not problems or time.monotonic() >= deadline:
            break
        time.sleep(10)
    for line in problems:
        print(f"FAIL  {line}")
    if problems:
        print(f"check_host: {len(problems)} problem(s) at {site}")
        return 1
    print(f"check_host: {site} matches {dist}, files and headers")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", help="the archive on the host")
    ap.add_argument("--local", type=Path, help="the same archive on disk")
    ap.add_argument("--origin", help="the site origin that will read it (enables the CORS checks)")
    ap.add_argument("--site", help="the deployed site, compared with --dist")
    ap.add_argument("--dist", type=Path, help="the built site on disk")
    ap.add_argument("--wait", type=float, default=0, help="seconds to keep retrying the site check")
    args = ap.parse_args()
    if args.site:
        if not args.dist or not (args.dist / "_headers").is_file():
            sys.exit("check_host: --site needs --dist, a built site with a _headers file")
        try:
            return run_site(args.site, args.dist, args.wait)
        except OSError as err:
            sys.exit(f"check_host: could not reach {args.site}: {err}")
    if not args.url or not args.local:
        sys.exit("check_host: give --url and --local, or --site and --dist")
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
