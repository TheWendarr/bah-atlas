"""
Tests for the fetcher's API sources (pipeline/fetch/fetch_sources.py): the Census
key is added to the request only, never recorded or printed, and an API answer
that is not a Census table is rejected. No network: the download is replaced by a
function that writes a canned response. Stdlib only.

StreamTest runs the real download against a server on 127.0.0.1: a body cut off
part-way must not be kept, and a failure while the body streams is retried.
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "fetch"))
import fetch_sources as fs  # noqa: E402

KEY = "abc123secretkey"
TABLE = [["B25090_001E", "B25079_001E", "B01003_001E", "zip code tabulation area"]] + \
        [[str(i * 10), str(i * 1000), str(i), f"{i:05d}"] for i in range(1, 400)]


def api_source(**kw) -> fs.Source:
    base = dict(node_id="A9", name="ACS test", filename="acs_test.json", acquisition="api",
                url="https://api.census.gov/data/2024/acs/acs5?get=B25090_001E&for=zcta:*",
                min_bytes=100, api_key_env="CENSUS_API_KEY")
    base.update(kw)
    return fs.Source(**base)


class ApiSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_registry_pins_the_acs_query(self) -> None:
        a9 = next(s for s in fs.SOURCES if s.node_id == "A9")
        self.assertEqual(a9.acquisition, "api")
        self.assertIn("/data/2024/acs/acs5?", a9.url)
        for var in ("B25090_001E", "B25079_001E", "B01003_001E"):
            self.assertIn(var, a9.url)
        self.assertNotIn("key=", a9.url)
        self.assertEqual(a9.api_key_env, "CENSUS_API_KEY")

    def test_missing_key_is_a_clear_error(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as cm:
                fs.request_url(api_source())
        self.assertIn("CENSUS_API_KEY", str(cm.exception))

    def test_key_reaches_the_request_but_not_the_manifest(self) -> None:
        seen: list[str] = []

        def fake_stream(url: str, tmp: Path, timeout: int) -> None:
            seen.append(url)
            tmp.write_text(json.dumps(TABLE))

        with mock.patch.dict(os.environ, {"CENSUS_API_KEY": KEY}), \
                mock.patch.object(fs, "_stream_to", fake_stream):
            rec = fs.download_direct(api_source(), self.dest, force=False, timeout=5, retries=1)
        self.assertTrue(seen[0].endswith(f"&key={KEY}"))
        self.assertNotIn(KEY, json.dumps(rec))
        self.assertEqual(rec["source_url"], api_source().url)
        self.assertEqual(json.loads((self.dest / "acs_test.json").read_text())[0][0], "B25090_001E")

    def test_key_is_redacted_from_errors(self) -> None:
        def failing_stream(url: str, tmp: Path, timeout: int) -> None:
            raise fs.urllib.error.URLError(f"cannot reach {url}")

        with mock.patch.dict(os.environ, {"CENSUS_API_KEY": KEY}), \
                mock.patch.object(fs, "_stream_to", failing_stream):
            with self.assertRaises(RuntimeError) as cm:
                fs.download_direct(api_source(), self.dest, force=False, timeout=5, retries=1)
        self.assertNotIn(KEY, str(cm.exception))
        self.assertIn("REDACTED", str(cm.exception))

    def test_api_error_page_is_rejected(self) -> None:
        def error_page(url: str, tmp: Path, timeout: int) -> None:
            tmp.write_text('{"error": "error: unknown variable"}' + " " * 200)

        with mock.patch.dict(os.environ, {"CENSUS_API_KEY": KEY}), \
                mock.patch.object(fs, "_stream_to", error_page):
            with self.assertRaises(RuntimeError) as cm:
                fs.download_direct(api_source(), self.dest, force=False, timeout=5, retries=1)
        self.assertIn("Census-style table", str(cm.exception))
        self.assertFalse((self.dest / "acs_test.json").exists())



class BrowserRecordTest(unittest.TestCase):
    """A browser-download file already recorded keeps its original retrieval date, as cached
    direct downloads do; a changed file gets a new record."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self.tmp.name)
        self.a6 = next(s for s in fs.SOURCES if s.node_id == "A6")
        pdf = self.dest / self.a6.filename
        pdf.write_bytes(b"%PDF-1.7\n" + b"x" * 4096)
        self.sha = fs.sha256_file(pdf)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_a6(self, prior_sha: str) -> dict:
        (self.dest / "fetch_manifest.json").write_text(json.dumps({"A6": {
            "filename": self.a6.filename, "sha256": prior_sha, "retrieved_at": "2026-10-03T19:28:11+00:00"}}))
        with mock.patch.object(fs, "validate_file", return_value=(True, "")):
            self.assertEqual(fs.main(["A6", "--dest", str(self.dest)]), 0)
        return json.loads((self.dest / "fetch_manifest.json").read_text())["A6"]

    def test_same_bytes_keep_the_recorded_date(self) -> None:
        self.assertEqual(self.run_a6(self.sha)["retrieved_at"], "2026-10-03T19:28:11+00:00")

    def test_changed_bytes_get_a_new_record(self) -> None:
        rec = self.run_a6("0" * 64)
        self.assertEqual(rec["sha256"], self.sha)
        self.assertNotEqual(rec["retrieved_at"], "2026-10-03T19:28:11+00:00")

if __name__ == "__main__":
    unittest.main()


class MultiFileNodeTest(unittest.TestCase):
    """A15 and A16 (D19) are several files each, keyed A15.sfr, A16.br3, ..."""

    def test_registry_lists_the_grid_series(self) -> None:
        ids = [s.node_id for s in fs.SOURCES]
        self.assertEqual([i for i in ids if i.startswith("A15")], ["A15.sfr", "A15.mfr", "A15.all"])
        self.assertEqual([i for i in ids if i.startswith("A16")],
                         ["A16.sfr", "A16.condo", "A16.br1", "A16.br2", "A16.br3", "A16.br4"])
        self.assertEqual(len(ids), len(set(ids)))
        names = [s.filename for s in fs.SOURCES if s.filename.endswith(".csv")]
        self.assertEqual(len(names), len(set(names)))
        for s in fs.SOURCES:
            if s.node_id.startswith("A15"):
                self.assertTrue(s.filename.startswith("Metro_zori_"), s.filename)
            if s.node_id.startswith("A16"):
                self.assertTrue(s.filename.startswith("Zip_zhvi_") and s.url.endswith(s.filename), s.filename)

    def test_node_id_selects_all_its_files(self) -> None:
        seen: list[str] = []

        def fake_download(source, dest_dir, **_kw):
            seen.append(source.node_id)
            return {"status": "cached", "node_id": source.node_id, "name": source.name,
                    "filename": source.filename, "sha256": "0" * 64, "bytes": 1,
                    "retrieved_at": "2026-10-24T00:00:00+00:00"}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fs, "download_direct", fake_download):
            rc = fs.main(["A16", "A15.mfr", "--dest", tmp])
            manifest = json.loads((Path(tmp) / fs.MANIFEST_NAME).read_text())
        self.assertEqual(rc, 0)
        self.assertEqual(seen, ["A15.mfr", "A16.sfr", "A16.condo", "A16.br1", "A16.br2", "A16.br3", "A16.br4"])
        self.assertIn("A16.br3", manifest)

    def test_unknown_node_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(fs.main(["A17", "--dest", tmp]), 2)


CSV = b"RegionName,RegionType,2026-01-31\n" + b"".join(b"%05d,zip,1500.0\n" % i for i in range(1, 2001))


class StreamTest(unittest.TestCase):
    """The real _stream_to, against a local server whose behaviour each test sets."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self.tmp.name)
        self.plan: list[str] = []          # one entry per request: "full", "cut" or "503"
        plan = self.plan

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                step = plan.pop(0) if plan else "full"
                if step == "503":
                    self.send_error(503)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/csv")
                self.send_header("Content-Length", str(len(CSV)))
                self.end_headers()
                self.wfile.write(CSV if step == "full" else CSV[: len(CSV) // 2])
                self.wfile.flush()
                if step == "cut":           # drop the connection with half the body sent
                    self.connection.shutdown(socket.SHUT_RDWR)

            def log_message(self, *_args) -> None:
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.source = fs.Source(node_id="A3", name="ZORI test", filename="zori_test.csv", acquisition="direct",
                                url=f"http://127.0.0.1:{self.server.server_address[1]}/zori_test.csv",
                                min_bytes=1000)
        env = mock.patch.dict(os.environ, {"no_proxy": "127.0.0.1", "NO_PROXY": "127.0.0.1"})
        env.start()
        self.addCleanup(env.stop)
        sleep = mock.patch.object(fs.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def fetch(self, retries: int) -> dict:
        return fs.download_direct(self.source, self.dest, force=False, timeout=5, retries=retries)

    def test_a_complete_download_is_kept(self) -> None:
        rec = self.fetch(retries=1)
        self.assertEqual(rec["status"], "fetched")
        self.assertEqual((self.dest / "zori_test.csv").read_bytes(), CSV)
        self.assertEqual(rec["bytes"], len(CSV))

    def test_a_cut_off_download_is_not_kept(self) -> None:
        # Half the body is still above the size floor and still reads as a CSV, so only the
        # byte count against Content-Length can tell it from the whole file.
        self.plan += ["cut", "cut"]
        with self.assertRaises(RuntimeError) as cm:
            self.fetch(retries=2)
        self.assertIn("connection closed after", str(cm.exception))
        self.assertEqual(list(self.dest.iterdir()), [])        # neither the file nor its .part

    def test_a_cut_off_download_is_retried(self) -> None:
        self.plan += ["cut"]
        rec = self.fetch(retries=2)
        self.assertEqual((self.dest / "zori_test.csv").read_bytes(), CSV)
        self.assertEqual(rec["sha256"], fs.sha256_file(self.dest / "zori_test.csv"))

    def test_a_server_error_is_retried(self) -> None:
        self.plan += ["503"]
        self.assertEqual(self.fetch(retries=2)["status"], "fetched")


class RegistryHousekeepingTest(unittest.TestCase):
    def test_a_scrapped_node_is_not_asked_for(self) -> None:
        # A10 (BEA RPP) was scrapped on 18 Oct 2026; it must not come back as "action needed".
        self.assertNotIn("A10", [s.node_id for s in fs.SOURCES])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(fs.main(["A10", "--dest", tmp]), 2)

    def test_a_key_is_redacted_in_the_form_the_request_carried(self) -> None:
        key = "ab/cd+ef"                    # quoted in the URL as ab/cd%2Bef
        with mock.patch.dict(os.environ, {"CENSUS_API_KEY": key}):
            url = fs.request_url(api_source())
            self.assertNotIn(key, url)
            self.assertNotIn("ef", fs.redact(f"cannot reach {url}", api_source()).split("key=")[1])
            self.assertNotIn(key, fs.redact(f"bad key {key}", api_source()))
