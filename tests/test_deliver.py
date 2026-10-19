"""
Tests for the D10 delivery gates (tools/deliver_handoff.py).

    python -m unittest discover -s tests -v        (or: make test)

The gates that read the handoff and the B23 output run on the test_qa fixture;
the tracker and write-up gates run on small files written here. The contract,
hash and provenance gates reuse validate_handoff.py, verify_hashes.py and
qa_report.code_unchanged_since, which have tests of their own. Stdlib only.
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools"))
import deliver_handoff as dh  # noqa: E402
import test_handoff as th  # noqa: E402
import test_qa as tq  # noqa: E402

Y = th.YEAR


def nodes_csv(path: Path, statuses: dict[str, tuple[str, str]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["id", "sublayer", "name", "required", "inputs", "status", "completed", "notes"])
        for nid, (sub, status) in statuses.items():
            w.writerow([nid, sub, nid, "required", "", status, "", ""])
    return path


class TestTrackerAndWriteup(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_tracker(self) -> None:
        base = {"A1": ("1", "complete"), "A10": ("1", "scrapped"), "B19": ("2.6", "complete"),
                "W1": ("2.8", "in_progress"), "C1": ("3.1", "not_started")}
        ok, detail = dh.gate_tracker(nodes_csv(self.d / "n.csv", base), {"W1"})
        self.assertTrue(ok, detail)                                   # Layer 3 and W1 do not block
        ok, detail = dh.gate_tracker(nodes_csv(self.d / "n.csv", {**base, "B23": ("2.8", "in_progress")}), {"W1"})
        self.assertFalse(ok)
        self.assertIn("B23 (in_progress)", detail)

    def test_writeup(self) -> None:
        w = self.d / "layer2-writeup.md"
        self.assertFalse(dh.gate_writeup(w)[0] if w.exists() else False)
        w.write_text(f"# W1\n\n## 1. Purpose\n\n> {dh.AUTHOR_MARKER}: write this section.\n")
        ok, detail = dh.gate_writeup(w)
        self.assertFalse(ok)
        self.assertIn("1 section(s)", detail)
        w.write_text("# W1\n\n## 1. Purpose\n\nThe pipeline turns Layer 1 into Layer 3.\n")
        self.assertTrue(dh.gate_writeup(w)[0])


class TestQAGate(tq.QAFixture):
    def files(self) -> dict[str, Path]:
        return {node: self.out / name for node, name in dh.c.file_names(Y).items()}

    def test_qa_gate(self) -> None:
        self.build()
        qa_dir = self.data / "processed" / "qa"
        self.assertFalse(dh.gate_qa(qa_dir, Y, self.files())[0])         # no B23 yet
        self.assertEqual(self.run_qa().returncode, 0)
        ok, detail = dh.gate_qa(qa_dir, Y, self.files())
        self.assertTrue(ok, detail)
        report = qa_dir / f"qa_{Y}.md"
        report.write_text(report.read_text() + "\nedited\n")
        ok, detail = dh.gate_qa(qa_dir, Y, self.files())
        self.assertFalse(ok)
        self.assertIn("must not be edited", detail)

    def test_qa_gate_rejects_another_build(self) -> None:
        self.build()
        self.assertEqual(self.run_qa().returncode, 0)
        b22 = self.out / f"build_manifest_{Y}.json"                     # a different B22 -> a new build_id
        b22.write_text(b22.read_text().replace('"node"', '"_rebuilt": true, "node"', 1))
        ok, detail = dh.gate_qa(self.data / "processed" / "qa", Y, self.files())
        self.assertFalse(ok)
        self.assertIn("different build", detail)


class TestDeliverCopy(tq.QAFixture):
    """main() with the repository-bound gates (tracker, validator, hashes, provenance, write-up) passed
    through, so the copy and its re-hash run on the fixture."""

    def deliver(self, *extra: str) -> int:
        from unittest import mock
        argv = ["deliver_handoff.py", "--year", str(Y), "--handoff", str(self.out),
                "--qa", str(self.data / "processed" / "qa"), "--dest", str(self.dest), *extra]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(dh, "gate_tracker", return_value=(True, "ok")), \
             mock.patch.object(dh, "gate_writeup", return_value=(True, "ok")), \
             mock.patch.object(dh.qa, "run", return_value=(0, "ok")), \
             mock.patch.object(dh.qa, "code_unchanged_since", return_value=(True, "ok")):
            try:
                dh.main()
            except SystemExit as e:
                return e.code if isinstance(e.code, int) else (1 if e.code else 0)
        return 0

    def test_copies_and_rehashes(self) -> None:
        self.build()
        self.assertEqual(self.run_qa().returncode, 0)
        self.dest = self.data.parent / "delivery" / str(Y)
        self.assertEqual(self.deliver("--check"), 0)
        self.assertFalse(self.dest.exists())                            # --check copies nothing
        self.assertEqual(self.deliver(), 0)
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()),
                         sorted([*dh.c.file_names(Y).values(), "SHA256SUMS", f"qa_{Y}.md", f"qa_{Y}_manifest.json"]))
        self.assertEqual(self.deliver(), 1)                             # an existing delivery needs --replace
        self.assertEqual(self.deliver("--replace"), 0)


if __name__ == "__main__":
    unittest.main()
