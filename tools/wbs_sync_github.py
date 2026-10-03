#!/usr/bin/env python3
"""Mirror the WBS onto GitHub milestones and issues (one-way: CSV -> GitHub).

docs/wbs/nodes.csv stays the single source of truth. This script makes GitHub
match it, so the repository's Milestones page shows live progress bars:

  * one label set: wbs-node, layer-1/2/3, optional, status: in-progress
  * one milestone per row of docs/wbs/milestones.csv (title "M1: ...", due date)
  * one issue per node, titled "[A1] <name>", in its milestone
      complete     -> issue closed (completed)
      in_progress  -> issue open + "status: in-progress" label
      not_started  -> issue open

Safe to re-run: it only creates what is missing and changes what differs.
It never deletes anything, and it ignores issues whose titles do not start
with a node id in brackets, so ordinary issues are left alone.

Requires the GitHub CLI (https://cli.github.com), authenticated with `gh auth login`.

Usage:
    python tools/wbs_sync_github.py --dry-run   # print the plan, change nothing
    python tools/wbs_sync_github.py             # apply it
    python tools/wbs_sync_github.py --repo TheWendarr/bah-atlas
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wbs_render as wbs  # noqa: E402  (shares CSV loading + validation)

GH = os.environ.get("GH_BIN", "gh")
PAUSE = float(os.environ.get("WBS_SYNC_PAUSE", "1.0"))  # GitHub asks ~1 write/sec

LABELS = {
    "wbs-node": ("5319e7", "Tracked node in the work breakdown structure"),
    "layer-1": ("0e8a16", "Layer 1 — authoritative sources"),
    "layer-2": ("1d76db", "Layer 2 — data processing"),
    "layer-3": ("d93f0b", "Layer 3 — front-end"),
    "optional": ("cfd3d7", "Optional node; does not gate its milestone"),
    "status: in-progress": ("7b1fa2", "Node is currently being worked"),
}
IN_PROGRESS = "status: in-progress"
TITLE_RE = re.compile(r"^\[([A-Z]\d+)\]\s")


class GitHub:
    def __init__(self, repo: str, dry_run: bool):
        self.repo = repo
        self.dry_run = dry_run
        self.changes = 0

    def read(self, *args: str) -> str:
        proc = subprocess.run([GH, *args], capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit(f"wbs_sync: `gh {' '.join(args)}` failed:\n{proc.stderr.strip()}")
        return proc.stdout

    def write(self, *args: str) -> str:
        self.changes += 1
        shown = " ".join(
            a if (a and " " not in a) else repr(a if len(a) <= 70 else a[:67] + "...")
            for a in args)
        if self.dry_run:
            print(f"  [dry-run] gh {shown}")
            return ""
        print(f"  gh {shown}")
        out = self.read(*args)
        time.sleep(PAUSE)
        return out


def milestone_title(m: dict) -> str:
    return f"{m['id']}: {m['title']}"


def issue_title(n: dict) -> str:
    return f"[{n['id']}] {n['name']}"


def issue_body(n: dict, m: dict | None) -> str:
    sub = n["sublayer"]
    sub_name = wbs.SUBLAYERS[sub] if sub == "1" else f"{sub} {wbs.SUBLAYERS[sub]}"
    lines = [
        f"**Node:** {n['id']} — {n['name']}",
        f"**Layer:** {wbs.LAYERS[sub.split('.')[0]][0]}",
        f"**Sub-layer:** {sub_name}",
        f"**Type:** {n['required']}",
        f"**Inputs:** {', '.join(n['input_ids']) or 'none'}",
    ]
    if m:
        lines.append(f"**Milestone:** {milestone_title(m)} (due {m['due']})")
    if n["notes"]:
        lines.append(f"**Notes:** {n['notes']}")
    lines += [
        "",
        f"Status is managed in [`docs/wbs/nodes.csv`]({wbs.REPO_URL}/blob/main/docs/wbs/nodes.csv) and "
        "mirrored here by `tools/wbs_sync_github.py`. Use this issue for discussion, and "
        f"reference it from commits (for example `Refs #<this issue>` or `Closes #<this issue>`).",
    ]
    return "\n".join(lines)


def node_labels(n: dict) -> list[str]:
    labels = ["wbs-node", f"layer-{n['sublayer'].split('.')[0]}"]
    if n["required"] == "optional":
        labels.append("optional")
    return labels


def sync(gh: GitHub, nodes: list[dict], milestones: list[dict]) -> None:
    # ---- labels
    print("Labels")
    existing_labels = {l["name"] for l in json.loads(
        gh.read("label", "list", "-R", gh.repo, "--limit", "500", "--json", "name") or "[]")}
    for name, (color, desc) in LABELS.items():
        if name not in existing_labels:
            gh.write("label", "create", name, "-R", gh.repo, "--color", color, "--description", desc)

    # ---- milestones
    print("Milestones")
    remote_ms = json.loads(gh.read(
        "api", f"repos/{gh.repo}/milestones?state=all&per_page=100") or "[]")
    by_id = {}
    for rm in remote_ms:
        mid = rm["title"].split(":", 1)[0].strip()
        by_id.setdefault(mid, rm)
    for m in milestones:
        want_title = milestone_title(m)
        want_due = f"{m['due']}T23:59:59Z"
        desc = f"Sub-layers {', '.join(m['sublayer_list'])}. Mirrored from docs/wbs/milestones.csv."
        rm = by_id.get(m["id"])
        if rm is None:
            gh.write("api", "-X", "POST", f"repos/{gh.repo}/milestones",
                     "-f", f"title={want_title}", "-f", f"due_on={want_due}",
                     "-f", f"description={desc}")
        elif rm["title"] != want_title or (rm.get("due_on") or "")[:10] != m["due"]:
            gh.write("api", "-X", "PATCH", f"repos/{gh.repo}/milestones/{rm['number']}",
                     "-f", f"title={want_title}", "-f", f"due_on={want_due}",
                     "-f", f"description={desc}")

    # ---- issues
    print("Issues")
    remote_issues = json.loads(gh.read(
        "issue", "list", "-R", gh.repo, "--state", "all", "--limit", "1000",
        "--json", "number,title,state,labels,milestone") or "[]")
    by_node = {}
    for ri in remote_issues:
        hit = TITLE_RE.match(ri["title"])
        if hit:
            by_node.setdefault(hit.group(1), ri)

    for n in nodes:
        m = wbs.milestone_for(n["sublayer"], milestones)
        m_title = milestone_title(m) if m else None
        ri = by_node.get(n["id"])

        if ri is None:
            args = ["issue", "create", "-R", gh.repo, "--title", issue_title(n),
                    "--body", issue_body(n, m)]
            for label in node_labels(n) + ([IN_PROGRESS] if n["status"] == "in_progress" else []):
                args += ["--label", label]
            if m_title:
                args += ["--milestone", m_title]
            url = gh.write(*args).strip()
            if n["status"] == "complete":
                ref = url.rsplit("/", 1)[-1] if url else f"<new {n['id']} issue>"
                gh.write("issue", "close", ref, "-R", gh.repo, "--reason", "completed")
            continue

        num = str(ri["number"])
        have_labels = {l["name"] for l in ri.get("labels", [])}
        edit: list[str] = []
        if ri["title"] != issue_title(n):
            edit += ["--title", issue_title(n)]
        have_ms = (ri.get("milestone") or {}).get("title")
        if m_title and have_ms != m_title:
            edit += ["--milestone", m_title]
        for label in node_labels(n):
            if label not in have_labels:
                edit += ["--add-label", label]
        if n["status"] == "in_progress" and IN_PROGRESS not in have_labels:
            edit += ["--add-label", IN_PROGRESS]
        if n["status"] != "in_progress" and IN_PROGRESS in have_labels:
            edit += ["--remove-label", IN_PROGRESS]
        if edit:
            gh.write("issue", "edit", num, "-R", gh.repo, *edit)

        is_open = ri["state"].upper() == "OPEN"
        if n["status"] == "complete" and is_open:
            gh.write("issue", "close", num, "-R", gh.repo, "--reason", "completed")
        elif n["status"] != "complete" and not is_open:
            gh.write("issue", "reopen", num, "-R", gh.repo)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print planned changes without making them")
    ap.add_argument("--repo", help="OWNER/REPO (default: the repo of the current directory)")
    args = ap.parse_args()

    if shutil.which(GH) is None:
        sys.exit("wbs_sync: the GitHub CLI `gh` is not installed. See https://cli.github.com")

    nodes = wbs.load_nodes()
    milestones = wbs.load_milestones()

    probe = GitHub("", args.dry_run)
    repo = args.repo or probe.read("repo", "view", "--json", "nameWithOwner",
                                   "-q", ".nameWithOwner").strip()
    gh = GitHub(repo, args.dry_run)
    print(f"Syncing {len(nodes)} nodes and {len(milestones)} milestones to {repo}"
          + (" (dry run)" if args.dry_run else ""))
    sync(gh, nodes, milestones)
    verb = "would make" if args.dry_run else "made"
    print(f"Done: {verb} {gh.changes} change(s).")


if __name__ == "__main__":
    main()
