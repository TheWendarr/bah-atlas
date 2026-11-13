#!/usr/bin/env python3
"""C14: write every grid view from the reference formula, for the browser parity test.

web/test/grid.test.mjs compares web/src/grid.js with this output field by field, for
all 339 areas x 23 ranks x 2 x 7 x 2 modes (218,316 views). The file is about 60 MB,
so it is generated and git-ignored.

C27 (D36): the same for the ZIP view (contract.zip_view) in a second file: every B36 ZIP
at the two research profiles' standard views in both modes, and every 50th ZIP at
every view.

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
    ap.add_argument("--zip-out", type=Path, default=ROOT / "web" / "test" / ".golden" / "zipgrid.jsonl")
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

    zipgrid = json.loads((ROOT / "delivery" / str(args.year) / f"zipgrid_{args.year}.json").read_text(encoding="utf-8"))
    research = [("E5", "with"), ("O3", "with")]
    count = 0
    with args.zip_out.open("w", encoding="utf-8") as fh:
        for n, z in enumerate(zipgrid["zips"]):
            cells = ([(r, d, h) for r in grid["ranks"] for d in grid["dependents"]
                      for h in [c.STANDARD, *grid["home_types"]]] if n % 50 == 0
                     else [(r, d, c.STANDARD) for r, d in research])
            for rank, dependents, home_type in cells:
                for mode in grid["modes"]:
                    view = c.zip_view(grid, zipgrid, z, rank, dependents, home_type, mode)
                    fh.write(json.dumps([z, rank, dependents, home_type, mode, view]) + "\n")
                    count += 1
    print(f"grid_golden: {count:,} ZIP views in {args.zip_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
