#!/usr/bin/env python3
"""C14: write every grid view from the reference formula, for the browser parity test.

web/test/grid.test.mjs compares web/src/grid.js with this output field by field, for
all 339 areas x 23 ranks x 2 x 7 x 2 modes (218,316 views). The file is about 60 MB,
so it is generated and git-ignored.

    python tools/grid_golden.py        (or: make web-golden)

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "handoff"))
import contract as c  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=ROOT / "web" / "test" / ".golden" / "grid.jsonl")
    args = ap.parse_args()

    grid = json.loads((ROOT / "delivery" / str(args.year) / f"grid_{args.year}.json").read_text(encoding="utf-8"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with args.out.open("w", encoding="utf-8") as fh:
        for code in grid["areas"]:
            for rank in grid["ranks"]:
                for dependents in grid["dependents"]:
                    for home_type in [c.STANDARD, *grid["home_types"]]:
                        for mode in grid["modes"]:
                            view = c.grid_view(grid, code, rank, dependents, home_type, mode)
                            fh.write(json.dumps([code, rank, dependents, home_type, mode, view]) + "\n")
                            count += 1
    print(f"grid_golden: {count:,} views in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
