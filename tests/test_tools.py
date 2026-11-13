"""Tests for two repository tools on synthetic trees (stdlib only).

tools/collect_evidence.py  a clone that has not run the pipeline must keep its evidence
                           index; a clone that has must have it rewritten from the manifests
tools/wbs.py               a status change regenerates the progress index with the WBS page
"""
from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import collect_evidence as ce  # noqa: E402
import wbs  # noqa: E402
import wbs_progress  # noqa: E402
import wbs_render  # noqa: E402

INDEX_FIELDS = ["file", "nodes", "source", "generated_at", "sha256", "copy_sha256"]


class CollectEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.out = self.root / "docs" / "evidence"
        (self.data / "raw").mkdir(parents=True)
        self.out.mkdir(parents=True)
        # What a fresh clone holds: a committed raw file, and the evidence of an earlier run.
        (self.data / "raw" / "source.zip").write_bytes(b"PK")
        (self.out / "stage_manifest.json").write_text('{"node": "B1"}\n', encoding="utf-8")
        with (self.out / "index.csv").open("w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=INDEX_FIELDS)
            wr.writeheader()
            wr.writerow({"file": "stage_manifest.json", "nodes": "B1", "source": "data/interim/stage_manifest.json",
                         "generated_at": "2026-11-08T00:00:00+00:00", "sha256": "a" * 64, "copy_sha256": "b" * 64})
        self.patches = [mock.patch.object(ce, "ROOT", self.root), mock.patch.object(ce, "DATA", self.data),
                        mock.patch.object(ce, "OUT", self.out)]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def run_main(self) -> str:
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["collect_evidence.py", "--no-tests"]), redirect_stdout(buf):
            ce.main()
        return buf.getvalue()

    def index_rows(self) -> list[dict]:
        with (self.out / "index.csv").open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def test_a_clone_without_pipeline_output_keeps_its_index(self) -> None:
        before = (self.out / "index.csv").read_bytes()
        printed = self.run_main()
        self.assertEqual((self.out / "index.csv").read_bytes(), before)
        self.assertEqual(len(self.index_rows()), 1)
        self.assertIn("left as they are", printed)

    def test_pipeline_output_rewrites_the_index_from_the_manifests(self) -> None:
        stage = self.data / "interim" / "bah_2026"
        stage.mkdir(parents=True)
        (stage / "manifest.json").write_text(json.dumps({"nodes": ["B1", "B2"], "ingested_at_utc": "t"}),
                                             encoding="utf-8")
        self.run_main()
        rows = self.index_rows()
        self.assertEqual([r["file"] for r in rows], ["bah_2026_manifest.json"])
        self.assertEqual(rows[0]["nodes"], "B1 B2")
        self.assertTrue((self.out / "bah_2026_manifest.json").exists())


class WbsStatusTest(unittest.TestCase):
    """`make done` must leave docs/WBS.md and docs/progress/README.md telling one story."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        wbs_dir, self.progress = self.root / "docs" / "wbs", self.root / "docs" / "progress"
        wbs_dir.mkdir(parents=True)
        self.nodes = wbs_dir / "nodes.csv"
        self.nodes.write_text(
            "id,sublayer,name,required,inputs,status,completed,notes\n"
            "A1,1,A source,required,,complete,2026-09-20,\n"
            "B1,2.1,An ingest output,required,A1,in_progress,,\n", encoding="utf-8")
        milestones = wbs_dir / "milestones.csv"
        milestones.write_text("id,title,due,sublayers,nodes\nM1,Sources and ingest,2026-09-26,1;2.1,\n",
                              encoding="utf-8")
        self.index = self.progress / "README.md"
        self.patches = [
            mock.patch.object(wbs_render, "ROOT", self.root),
            mock.patch.object(wbs_render, "NODES_CSV", self.nodes),
            mock.patch.object(wbs_render, "MILESTONES_CSV", milestones),
            mock.patch.object(wbs_render, "WBS_MD", self.root / "docs" / "WBS.md"),
            mock.patch.object(wbs_render, "PROGRESS_DIR", self.progress),
            mock.patch.object(wbs_progress, "PROGRESS_DIR", self.progress),
            mock.patch.object(wbs_progress, "INDEX_MD", self.index),
            mock.patch.object(wbs_progress, "ISSUES_CSV", wbs_dir / "issues.csv"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def run_wbs(self, *argv: str) -> None:
        with mock.patch.object(sys, "argv", ["wbs.py", *argv]), redirect_stdout(io.StringIO()):
            wbs.main()

    def test_done_refreshes_the_progress_index_with_the_wbs_page(self) -> None:
        self.run_wbs("done", "B1", "--on", "2026-09-25")
        index = self.index.read_text(encoding="utf-8")
        self.assertIn("| 2 / 2 |", index)
        self.assertIn("Complete 25 Sep (1 day early)", index)
        self.assertIn("2 / 2", (self.root / "docs" / "WBS.md").read_text(encoding="utf-8"))

    def test_reopening_a_node_reopens_the_milestone_in_the_index(self) -> None:
        self.run_wbs("done", "B1", "--on", "2026-09-25")
        self.run_wbs("start", "B1")
        index = self.index.read_text(encoding="utf-8")
        self.assertIn("| 1 / 2 |", index)
        self.assertNotIn("Complete 25 Sep", index)

    def test_no_render_leaves_both_pages_alone(self) -> None:
        self.run_wbs("done", "B1", "--no-render")
        self.assertFalse(self.index.exists())
        self.assertFalse((self.root / "docs" / "WBS.md").exists())


if __name__ == "__main__":
    unittest.main()
