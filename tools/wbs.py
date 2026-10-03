#!/usr/bin/env python3
"""Update node status in one command, then regenerate docs/WBS.md.

    python tools/wbs.py start A3 A6        # mark in progress
    python tools/wbs.py done A3-A6 B5      # mark complete today (ranges allowed)
    python tools/wbs.py done B7 --on 2026-10-02
    python tools/wbs.py reset A8           # back to not started
    python tools/wbs.py show               # print every node's status
    python tools/wbs.py show A3-A6 B5      # print selected nodes

Make shortcuts:  make start N="A3 A6"   make done N="A3-A6 B5"   make wbs-show

Edits docs/wbs/nodes.csv in place (same columns, same row order), so the change
shows up as a one-line diff per node in your next commit.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wbs_render as wbs  # noqa: E402

RANGE = re.compile(r"^([A-Z])(\d+)-(?:\1)?(\d+)$")
ACTIONS = {"start": "in_progress", "done": "complete", "reset": "not_started"}


def expand(tokens: list[str], known: list[str]) -> list[str]:
    out: list[str] = []
    for tok in tokens:
        for part in tok.replace(",", " ").split():
            part = part.upper()
            m = RANGE.match(part)
            ids = ([f"{m.group(1)}{i}" for i in range(int(m.group(2)), int(m.group(3)) + 1)]
                   if m else [part])
            for i in ids:
                if i not in known:
                    sys.exit(f"wbs: unknown node '{i}'. Known ids look like A1, B12, C3, W1.")
                if i not in out:
                    out.append(i)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=[*ACTIONS, "show"])
    ap.add_argument("nodes", nargs="*", help="node ids or ranges, e.g. A3 A4 or A3-A6")
    ap.add_argument("--on", help="completion date for `done` (YYYY-MM-DD, default today)")
    ap.add_argument("--no-render", action="store_true", help="skip regenerating docs/WBS.md")
    args = ap.parse_args()

    with wbs.NODES_CSV.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames
        rows = list(reader)
    known = [r["id"] for r in rows]

    if args.action == "show":
        pick = set(expand(args.nodes, known)) if args.nodes else set(known)
        for r in rows:
            if r["id"] in pick:
                when = f"  ({r['completed']})" if r["completed"] else ""
                print(f"{r['id']:4} {r['status']:12} {r['name']}{when}")
        return

    if not args.nodes:
        sys.exit("wbs: name at least one node, e.g. `python tools/wbs.py done A3`")
    targets = expand(args.nodes, known)
    on = (wbs.parse_date(args.on, "--on") if args.on else dt.date.today()).isoformat()
    new_status = ACTIONS[args.action]

    for r in rows:
        if r["id"] not in targets:
            continue
        before = r["status"]
        r["status"] = new_status
        r["completed"] = on if new_status == "complete" else ""
        print(f"{r['id']:4} {before} -> {new_status}" + (f" ({on})" if new_status == "complete" else ""))

    with wbs.NODES_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    if not args.no_render:
        nodes = wbs.load_nodes()
        milestones = wbs.load_milestones()
        wbs.WBS_MD.write_text(wbs.render_wbs(nodes, milestones, dt.date.today()), encoding="utf-8")
        print(f"regenerated {wbs.WBS_MD.relative_to(wbs.ROOT)}")


if __name__ == "__main__":
    main()
