"""
Tests for the fetcher's API sources (pipeline/fetch/fetch_sources.py): the Census
key is added to the request only, never recorded or printed, and an API answer
that is not a Census table is rejected. No network: the download is replaced by a
function that writes a canned response. Stdlib only.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
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
