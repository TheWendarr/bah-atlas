"""Tests for tools/verify_hashes.py on a synthetic repository tree (stdlib only).

The fixture is a tiny project: one raw file fetched by A1, one stage that read
it plus config/profiles.json, and docs/evidence/ holding both manifests. Each
test breaks one link and checks that exactly that check fails.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import verify_hashes as vh  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class VerifyHashesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir()
        (self.root / "data" / "raw").mkdir(parents=True)
        (self.root / "data" / "interim").mkdir(parents=True)
        self.ev = self.root / "docs" / "evidence"
        self.ev.mkdir(parents=True)

        self.raw = b"zip,mha\n00001,AA001\n"
        (self.root / "data" / "raw" / "source.csv").write_bytes(self.raw)
        self.cfg = b'{"profiles": []}\n'
        (self.root / "config" / "profiles.json").write_bytes(self.cfg)
        self.out = b"mha,value\nAA001,1\n"
        (self.root / "data" / "interim" / "result.csv").write_bytes(self.out)

        fetch = {"A1": {"filename": "source.csv", "sha256": sha(self.raw)}}
        stage = {
            "node": "B1",
            "inputs": {"A1": "source.csv", "A12": "profiles.json"},
            "input_sha256": {"A1": sha(self.raw), "A12": sha(self.cfg)},
            "outputs": ["result.csv"],
            "output_sha256": {"result.csv": sha(self.out)},
        }
        self.write_manifest("fetch_manifest.json", "data/raw/fetch_manifest.json", fetch)
        self.write_manifest("stage_manifest.json", "data/interim/stage_manifest.json", stage)
        self.write_index()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_manifest(self, name: str, source: str, manifest: dict) -> None:
        text = json.dumps(manifest, indent=2) + "\n"
        (self.root / source).write_text(text, encoding="utf-8")
        (self.ev / name).write_text(text, encoding="utf-8")

    def write_index(self) -> None:
        rows = []
        for name, source in (("fetch_manifest.json", "data/raw/fetch_manifest.json"),
                             ("stage_manifest.json", "data/interim/stage_manifest.json")):
            rows.append({"file": name, "nodes": "", "source": source, "generated_at": "",
                         "sha256": sha((self.root / source).read_bytes()),
                         "copy_sha256": sha((self.ev / name).read_bytes())})
        with (self.ev / "index.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    def failures(self, check: str, repo_only: bool = False) -> list[str]:
        rep = vh.verify(self.root, repo_only)
        return [f for f in rep.failed if f.startswith(f"[{check}]")]

    def test_clean_tree_passes_every_check(self):
        rep = vh.verify(self.root)
        self.assertEqual(rep.failed, [])
        for check in ("evidence", "configs", "chain", "live"):
            self.assertGreater(rep.passed.get(check, 0), 0, check)

    def test_edited_config_fails_configs(self):
        (self.root / "config" / "profiles.json").write_text('{"profiles": [1]}\n')
        self.assertEqual(len(self.failures("configs", repo_only=True)), 1)

    def test_hand_edited_evidence_copy_fails_evidence(self):
        with (self.ev / "stage_manifest.json").open("a") as fh:
            fh.write(" ")
        self.assertEqual(len(self.failures("evidence", repo_only=True)), 1)

    def test_disagreeing_manifests_fail_chain(self):
        fetch = {"A1": {"filename": "source.csv", "sha256": sha(b"a newer download")}}
        self.write_manifest("fetch_manifest.json", "data/raw/fetch_manifest.json", fetch)
        self.write_index()
        self.assertEqual(len(self.failures("chain", repo_only=True)), 1)

    def test_changed_data_file_fails_live_only(self):
        (self.root / "data" / "interim" / "result.csv").write_bytes(b"mha,value\nAA001,2\n")
        self.assertEqual(self.failures("live", repo_only=True), [])
        self.assertEqual(len(self.failures("live")), 1)

    def test_stale_evidence_fails_live(self):
        stage = json.loads((self.root / "data/interim/stage_manifest.json").read_text())
        stage["warnings"] = ["rerun after the copy"]
        (self.root / "data/interim/stage_manifest.json").write_text(json.dumps(stage))
        self.assertTrue(any("older than" in f for f in self.failures("live")))

    def test_skeleton_data_folder_skips_live(self):
        for p in sorted((self.root / "data").rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        (self.root / "data" / "raw").mkdir(parents=True)
        (self.root / "data" / "raw" / ".gitkeep").write_text("")
        rep = vh.verify(self.root)
        self.assertEqual(rep.failed, [])
        self.assertTrue(any(s.startswith("[live]") for s in rep.skipped))

    def test_missing_copy_sha_is_skipped_not_passed(self):
        with (self.ev / "index.csv").open(newline="") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            r["copy_sha256"] = ""
        with (self.ev / "index.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        rep = vh.verify(self.root, repo_only=True)
        self.assertEqual(rep.passed.get("evidence", 0), 0)
        self.assertEqual(sum(s.startswith("[evidence]") for s in rep.skipped), 2)


if __name__ == "__main__":
    unittest.main()
