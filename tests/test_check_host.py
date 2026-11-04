"""
Tests for the host check (tools/check_host.py), against a local HTTP server that can
behave like a good host or fail the ways real hosts do.

    python -m unittest tests.test_check_host

Stdlib only.
"""

from __future__ import annotations

import gzip
import re
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import check_host as ch  # noqa: E402

ORIGIN = "https://site.example"
DATA = bytes(range(256)) * 400


def server_for(fault: str | None = None, data: bytes = DATA) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def cors(self) -> None:
            if fault != "no_cors" and self.headers.get("Origin"):
                self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
                self.send_header("Access-Control-Expose-Headers", "ETag")

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.cors()
            self.send_header("Access-Control-Allow-Headers", "range" if fault == "no_if_match" else "range, if-match")
            self.end_headers()

        def do_GET(self) -> None:
            body, wanted = data, re.fullmatch(r"bytes=(\d+)-(\d+)", self.headers.get("Range", ""))
            if fault == "no_range" or not wanted:
                self.send_response(200)
            else:
                start, end = int(wanted[1]), int(wanted[2])
                self.send_response(206)
                total = len(data)
                if fault == "gzip_slice":
                    body = gzip.compress(data)[start:end + 1]
                    self.send_header("Content-Encoding", "gzip")
                else:
                    body = data[start:end + 1]
                if fault == "stale_bytes":
                    body = bytes(len(body))
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
            if fault != "no_etag":
                self.send_header("ETag", '"abc"')
            self.cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class TestCheckHost(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.local = Path(self.tmp.name) / "areas.pmtiles"
        self.local.write_bytes(DATA)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def problems(self, fault: str | None) -> list[str]:
        server = server_for(fault)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return ch.check(f"http://127.0.0.1:{server.server_address[1]}/a.pmtiles", self.local, ORIGIN)

    def test_good_host_passes(self) -> None:
        self.assertEqual(self.problems(None), [])

    def test_whole_file_answer_fails(self) -> None:
        self.assertTrue(any("expected 206" in p for p in self.problems("no_range")))

    def test_slice_of_a_compressed_copy_fails(self) -> None:
        self.assertTrue(any("Content-Encoding" in p for p in self.problems("gzip_slice")))

    def test_wrong_bytes_fail(self) -> None:
        self.assertTrue(any("do not match" in p for p in self.problems("stale_bytes")))

    def test_missing_etag_fails(self) -> None:
        self.assertTrue(any(p.startswith("etag") for p in self.problems("no_etag")))

    def test_missing_cors_fails(self) -> None:
        self.assertTrue(any("cors: GET" in p for p in self.problems("no_cors")))

    def test_preflight_without_if_match_fails(self) -> None:
        self.assertTrue(any("if-match" in p for p in self.problems("no_if_match")))

    def test_ranges_stay_inside_a_small_file(self) -> None:
        for _, start, end in ch.ranges_for(100):
            self.assertLessEqual(start, end)
            self.assertLess(end, 100)


BOT_SCRIPT = b"<script>(function(){var u='/cdn-cgi/challenge-platform/scripts/jsd/main.js?ray=a1';})();</script>"
PAGE_CHANGES = {
    "bot_script": lambda page: page.replace(b"</body>", BOT_SCRIPT + b"</body>"),
    "other_script": lambda page: page.replace(b"</body>", b"<script>steal()</script></body>"),
    "bot_script_and_edit": lambda page: page.replace(b"<p>", b"<p>changed ").replace(b"</body>", BOT_SCRIPT + b"</body>"),
}


def site_server(root: Path, fault: str | None = None) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def do_GET(self) -> None:
            path = self.path.lstrip("/") or "index.html"
            file = root / path
            if not file.is_file() or (fault == "missing" and path.endswith(".mjs")):
                self.send_response(404)
                self.end_headers()
                return
            body = file.read_bytes()
            if fault == "stale" and path.endswith(".json"):
                body = b"{}"
            if path.endswith(".html") and fault in PAGE_CHANGES:
                body = PAGE_CHANGES[fault](body)
            self.send_response(200)
            kinds = {".html": "text/html", ".mjs": "text/javascript", ".json": "application/json"}
            kind = "text/plain" if fault == "bad_type" else kinds[file.suffix]
            self.send_header("Content-Type", kind)
            if fault != "no_nosniff":
                self.send_header("X-Content-Type-Options", "nosniff")
            if path.startswith("assets/"):
                self.send_header("Cache-Control", "immutable")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class TestCheckSite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dist = Path(self.tmp.name)
        (self.dist / "assets").mkdir()
        (self.dist / "index.html").write_text("<!doctype html><body><p>map</p></body>")
        (self.dist / "assets" / "worker.mjs").write_text("export {}")
        (self.dist / "data.json").write_text('{"a": 1}')
        (self.dist / "_headers").write_text("/*\n  X-Content-Type-Options: nosniff\n/assets/*\n  Cache-Control: immutable\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def problems(self, fault: str | None) -> list[str]:
        server = site_server(self.dist, fault)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return ch.check_site(f"http://127.0.0.1:{server.server_address[1]}/", self.dist)

    def test_matching_site_passes(self) -> None:
        self.assertEqual(self.problems(None), [])

    def test_missing_file_fails(self) -> None:
        self.assertTrue(any("HTTP 404" in p for p in self.problems("missing")))

    def test_stale_bytes_fail(self) -> None:
        self.assertTrue(any("differ from dist" in p for p in self.problems("stale")))

    def test_wrong_type_fails(self) -> None:
        self.assertTrue(any("Content-Type" in p for p in self.problems("bad_type")))

    def test_missing_header_fails(self) -> None:
        self.assertTrue(any("x-content-type-options" in p for p in self.problems("no_nosniff")))

    def test_cloudflare_bot_script_passes(self) -> None:
        self.assertEqual(self.problems("bot_script"), [])

    def test_any_other_added_script_fails(self) -> None:
        self.assertTrue(any("differ from dist" in p for p in self.problems("other_script")))

    def test_bot_script_does_not_hide_another_change(self) -> None:
        self.assertTrue(any("differ from dist" in p for p in self.problems("bot_script_and_edit")))

    def test_a_changed_page_shows_where_it_differs(self) -> None:
        self.assertTrue(any("steal()" in p for p in self.problems("other_script")))

    def test_bot_script_is_removed_only_from_the_end_of_the_body(self) -> None:
        page = b"<body>" + BOT_SCRIPT + b"<p>map</p></body>"
        self.assertEqual(ch.without_bot_script(page), page)


if __name__ == "__main__":
    unittest.main()
