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


if __name__ == "__main__":
    unittest.main()
