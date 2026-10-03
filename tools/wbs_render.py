#!/usr/bin/env python3
"""Render the living Work Breakdown Structure (WBS) for BAH Atlas.

Single source of truth:
    docs/wbs/nodes.csv       one row per tracked node (status lives here)
    docs/wbs/milestones.csv  milestone titles, due dates, and the sub-layers each covers

Outputs:
    docs/WBS.md              generated -- never edit by hand
    docs/progress/<date>.md  (only with --new-entry) a pre-filled weekly log entry

Usage:
    python tools/wbs_render.py                    # regenerate docs/WBS.md as of today
    python tools/wbs_render.py --as-of 2026-10-10
    python tools/wbs_render.py --new-entry        # also scaffold this week's log entry

Weekly routine: edit `status` / `completed` in nodes.csv -> `make wbs-week` ->
write the narrative in the new log entry -> commit -> push.

Stdlib only, matching the pipeline's supply-chain posture.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODES_CSV = ROOT / "docs" / "wbs" / "nodes.csv"
MILESTONES_CSV = ROOT / "docs" / "wbs" / "milestones.csv"
WBS_MD = ROOT / "docs" / "WBS.md"
PROGRESS_DIR = ROOT / "docs" / "progress"

REPO_URL = "https://github.com/TheWendarr/bah-atlas"

STATUSES = ("complete", "in_progress", "not_started")

# Display class -> (emoji, label, Mermaid fill, Mermaid text colour).
# Mirrors the WAR colour key: black / green / purple / red.
CLASSES = {
    "done": ("⚫", "Complete (before this week)", "#1f1f1f", "#ffffff"),
    "week": ("🟢", "Completed this week", "#2e7d32", "#ffffff"),
    "prog": ("🟣", "In progress", "#7b1fa2", "#ffffff"),
    "todo": ("🔴", "Not started", "#c62828", "#ffffff"),
}

LAYERS = {
    "1": ("Layer 1 — Authoritative Sources",
          "External inputs and project-authored config. Deterministic: identical inputs, identical results."),
    "2": ("Layer 2 — Data Processing",
          "The offline Python pipeline that turns Layer 1 into compact, web-ready packages."),
    "3": ("Layer 3 — Front-End",
          "The static MapLibre site. Visualizes Layer 2 output; performs no data manipulation."),
}

SUBLAYERS = {
    "1":   "Sources and Config",
    "2.1": "Ingest Outputs",
    "2.2": "Geometry",
    "2.3": "MHA Benchmarks",
    "2.4": "Ownership Metrics",
    "2.5": "Computed Metrics",
    "2.6": "Spatial Statistics",
    "2.7": "Front-End Payload",
    "2.8": "Writeup, QA and Enrichments",
    "3.1": "Served Artifacts",
    "3.2": "Map and UI Runtime",
    "3.3": "Build and Delivery",
}


# --------------------------------------------------------------------------- load

def die(msg: str) -> None:
    sys.exit(f"wbs_render: {msg}")


def parse_date(text: str, where: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        die(f"{where}: '{text}' is not a YYYY-MM-DD date")
        raise  # unreachable


def load_nodes() -> list[dict]:
    with NODES_CSV.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    seen: set[str] = set()
    for i, r in enumerate(rows, start=2):
        where = f"nodes.csv line {i} ({r.get('id')})"
        r = {k: (v or "").strip() for k, v in r.items()}
        rows[i - 2] = r
        if not r["id"]:
            die(f"{where}: empty id")
        if r["id"] in seen:
            die(f"{where}: duplicate id")
        seen.add(r["id"])
        if r["sublayer"] not in SUBLAYERS:
            die(f"{where}: unknown sublayer '{r['sublayer']}'")
        if r["status"] not in STATUSES:
            die(f"{where}: status must be one of {STATUSES}")
        if r["required"] not in ("required", "optional"):
            die(f"{where}: required must be 'required' or 'optional'")
        if r["completed"]:
            if r["status"] != "complete":
                die(f"{where}: has a completed date but status is '{r['status']}'")
            r["completed_date"] = parse_date(r["completed"], where)
        else:
            r["completed_date"] = None
        r["input_ids"] = r["inputs"].split() if r["inputs"] else []
    for r in rows:
        for dep in r["input_ids"]:
            if dep not in seen:
                die(f"nodes.csv: {r['id']} lists unknown input '{dep}'")
    return rows


def load_milestones() -> list[dict]:
    with MILESTONES_CSV.open(newline="", encoding="utf-8") as fh:
        rows = [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]
    claimed: dict[str, str] = {}
    for r in rows:
        r["due_date"] = parse_date(r["due"], f"milestones.csv ({r['id']})")
        r["sublayer_list"] = r["sublayers"].split(";")
        for s in r["sublayer_list"]:
            if s not in SUBLAYERS:
                die(f"milestones.csv ({r['id']}): unknown sublayer '{s}'")
            if s in claimed:
                die(f"milestones.csv: sublayer {s} is in both {claimed[s]} and {r['id']}")
            claimed[s] = r["id"]
    return rows


# --------------------------------------------------------------------------- logic

def display_class(node: dict, as_of: dt.date) -> str:
    if node["status"] == "in_progress":
        return "prog"
    if node["status"] == "not_started":
        return "todo"
    done_on = node["completed_date"]
    if done_on and as_of - dt.timedelta(days=6) <= done_on <= as_of:
        return "week"
    return "done"


def milestone_for(sublayer: str, milestones: list[dict]) -> dict | None:
    for m in milestones:
        if sublayer in m["sublayer_list"]:
            return m
    return None


def progress_bar(done: int, total: int, width: int = 10) -> str:
    if total == 0:
        return "—"
    filled = round(width * done / total)
    return f"{'█' * filled}{'░' * (width - filled)} {round(100 * done / total)}%"


def milestone_state(m: dict, done: int, total: int, as_of: dt.date) -> str:
    days = (m["due_date"] - as_of).days
    if total and done == total:
        return "✅ Complete"
    if days < 0:
        return f"⚠️ Overdue by {-days} day{'s' if -days != 1 else ''}"
    if days == 0:
        return "⏰ Due today"
    if days <= 7:
        return f"⏳ Due in {days} day{'s' if days != 1 else ''}"
    return "🗓️ Upcoming"


def short_label(name: str) -> str:
    """Compact node label for the Mermaid map."""
    for sep in (" - ", " ("):
        if sep in name:
            name = name.split(sep, 1)[0]
    return name.replace('"', "#quot;")


# --------------------------------------------------------------------------- render

def render_mermaid(nodes: list[dict], as_of: dt.date) -> str:
    lines = ["```mermaid", "flowchart LR"]
    by_sub: dict[str, list[dict]] = {}
    for n in nodes:
        by_sub.setdefault(n["sublayer"], []).append(n)

    for layer_key, (layer_title, _) in LAYERS.items():
        lines.append(f'    subgraph L{layer_key}["{layer_title}"]')
        lines.append("        direction TB")
        for sub in SUBLAYERS:
            if sub.split(".")[0] != layer_key or sub not in by_sub:
                continue
            sid = "S" + sub.replace(".", "_")
            lines.append(f'        subgraph {sid}["{sub} {SUBLAYERS[sub]}"]')
            for n in by_sub[sub]:
                lines.append(f'            {n["id"]}["{n["id"]} {short_label(n["name"])}"]')
            lines.append("        end")
        lines.append("    end")

    for n in nodes:
        for dep in n["input_ids"]:
            lines.append(f"    {dep} --> {n['id']}")

    for key, (_, _, fill, text) in CLASSES.items():
        lines.append(f"    classDef {key} fill:{fill},stroke:#000,color:{text}")
    lines.append("    classDef opt stroke-dasharray:5 4,stroke-width:2px,stroke:#9e9e9e")
    groups: dict[str, list[str]] = {k: [] for k in CLASSES}
    for n in nodes:
        groups[display_class(n, as_of)].append(n["id"])
    for key, ids in groups.items():
        if ids:
            lines.append(f"    class {','.join(ids)} {key}")
    optional = [n["id"] for n in nodes if n["required"] == "optional"]
    if optional:
        lines.append(f"    class {','.join(optional)} opt")
    lines.append("```")
    return "\n".join(lines)


def progress_entries() -> list[Path]:
    if not PROGRESS_DIR.is_dir():
        return []
    entries = []
    for p in PROGRESS_DIR.glob("*.md"):
        try:
            dt.date.fromisoformat(p.stem)
        except ValueError:
            continue
        entries.append(p)
    return sorted(entries, reverse=True)


def render_wbs(nodes: list[dict], milestones: list[dict], as_of: dt.date) -> str:
    counts = {k: 0 for k in CLASSES}
    for n in nodes:
        counts[display_class(n, as_of)] += 1

    out: list[str] = []
    w = out.append
    w("# BAH Atlas — Work Breakdown Structure")
    w("")
    w("<!-- GENERATED FILE. Edit docs/wbs/nodes.csv or docs/wbs/milestones.csv, then run `make wbs`. -->")
    w("")
    w(f"**Status as of:** {as_of:%d %B %Y}  ")
    w(f"**Nodes tracked:** {len(nodes)}  ·  "
      + "  ·  ".join(f"{CLASSES[k][0]} {CLASSES[k][1]}: {counts[k]}" for k in CLASSES))
    w("")
    w("This page is the live project tracker. It is regenerated from "
      "[`docs/wbs/nodes.csv`](wbs/nodes.csv) every time progress changes, so the "
      "commit history of that file is the project's change log. Narrative updates "
      "(what was done, what is next, setbacks and changes) are in the "
      "[weekly progress log](#weekly-progress-log).")
    w("")

    # ---- milestones
    w("## Milestones")
    w("")
    w("Progress counts **required** nodes only; optional nodes are tracked but do not gate a milestone.")
    w("")
    w("| Milestone | Due | Required complete | Progress | Status |")
    w("|---|---|---|---|---|")
    for m in milestones:
        req = [n for n in nodes if n["sublayer"] in m["sublayer_list"] and n["required"] == "required"]
        done = sum(1 for n in req if n["status"] == "complete")
        w(f"| **{m['id']}** {m['title']} | {m['due_date']:%a %d %b} | {done} / {len(req)} "
          f"| `{progress_bar(done, len(req))}` | {milestone_state(m, done, len(req), as_of)} |")
    w("")

    # ---- open work
    active = [n for n in nodes if n["status"] == "in_progress"]
    w("## In progress now")
    w("")
    if active:
        for n in active:
            m = milestone_for(n["sublayer"], milestones)
            due = f" — due {m['due_date']:%d %b} ({m['id']})" if m else ""
            w(f"- 🟣 **{n['id']}** {n['name']}{due}")
    else:
        w("_Nothing marked in progress._")
    w("")

    # ---- map
    w("## Nodal map")
    w("")
    w("Colour key: " + "  ·  ".join(f"{e} {label}" for e, label, _, _ in CLASSES.values())
      + "  ·  dashed border = optional node. Arrows point from an input to the node built from it.")
    w("")
    w(render_mermaid(nodes, as_of))
    w("")

    # ---- node tables
    w("## Master node list")
    w("")
    for layer_key, (layer_title, layer_desc) in LAYERS.items():
        w(f"### {layer_title}")
        w("")
        w(layer_desc)
        w("")
        for sub in SUBLAYERS:
            if sub.split(".")[0] != layer_key:
                continue
            rows = [n for n in nodes if n["sublayer"] == sub]
            if not rows:
                continue
            m = milestone_for(sub, milestones)
            due = f" — due {m['due_date']:%d %B %Y} ({m['id']})" if m else ""
            heading = SUBLAYERS[sub] if sub == "1" else f"{sub} {SUBLAYERS[sub]}"
            w(f"#### {heading}{due}")
            w("")
            w("| Status | ID | Node | Type | Inputs | Notes |")
            w("|:---:|---|---|---|---|---|")
            for n in rows:
                emoji = CLASSES[display_class(n, as_of)][0]
                inputs = ", ".join(n["input_ids"]) or "—"
                note = n["notes"]
                if n["completed_date"]:
                    note = (note + "; " if note else "") + f"completed {n['completed_date']:%d %b}"
                w(f"| {emoji} | **{n['id']}** | {n['name']} | {n['required']} | {inputs} | {note or ''} |")
            w("")

    # ---- weekly log index
    w("## Weekly progress log")
    w("")
    entries = progress_entries()
    if entries:
        for p in entries:
            d = dt.date.fromisoformat(p.stem)
            w(f"- [Week of {d:%d %B %Y}](progress/{p.name})")
    else:
        w("_No entries yet._")
    w("")
    w("## Live views on GitHub")
    w("")
    w(f"- [Milestones]({REPO_URL}/milestones) and [issues]({REPO_URL}/issues) mirror this table "
      "(synced one-way from `nodes.csv` with `make wbs-sync`).")
    w(f"- [Commit history]({REPO_URL}/commits/main) for every change to code and documentation.")
    w("")
    w("---")
    w("")
    w("*AI-assistance disclosure: Claude (Anthropic) assisted in identifying the project's nodes "
      "and in creating this documentation and its tooling. All project decisions, data work, and "
      "status reporting are the author's.*")
    w("")
    return "\n".join(out)


def render_entry(nodes: list[dict], milestones: list[dict], as_of: dt.date) -> str:
    week_start = as_of - dt.timedelta(days=6)
    finished = [n for n in nodes if display_class(n, as_of) == "week"]
    active = [n for n in nodes if n["status"] == "in_progress"]
    upcoming = [m for m in milestones if m["due_date"] >= as_of][:2]
    overdue = []
    for m in milestones:
        if m["due_date"] < as_of:
            open_req = [n for n in nodes if n["sublayer"] in m["sublayer_list"]
                        and n["required"] == "required" and n["status"] != "complete"]
            if open_req:
                overdue.append((m, open_req))

    def bullets(items: list[dict]) -> list[str]:
        return [f"- **{n['id']}** {n['name']}" for n in items] or ["- _None._"]

    out = [
        f"# Week of {as_of:%d %B %Y}",
        "",
        f"_Covers {week_start:%d %b} – {as_of:%d %b %Y}. Status lists below were generated from "
        "[`nodes.csv`](../wbs/nodes.csv); the narrative sections are written by hand._",
        "",
        "## Summary",
        "",
        "<!-- TODO: two to four sentences on what this week was about. -->",
        "",
        "## Completed this week",
        "",
        *bullets(finished),
        "",
        "## In progress",
        "",
        *bullets(active),
        "",
        "## Next",
        "",
    ]
    for m in upcoming:
        open_nodes = [n for n in nodes if n["sublayer"] in m["sublayer_list"] and n["status"] != "complete"]
        out.append(f"- **{m['id']} {m['title']}** — due {m['due_date']:%d %b}: "
                   + (", ".join(n["id"] for n in open_nodes) or "all nodes complete"))
    out += [
        "",
        "<!-- TODO: add the specific tasks planned for next week. -->",
        "",
        "## Shortfalls, setbacks, and changes",
        "",
    ]
    if overdue:
        for m, open_req in overdue:
            out.append(f"- {m['id']} ({m['title']}, due {m['due_date']:%d %b}) is past due with "
                       f"{len(open_req)} required node(s) open: {', '.join(n['id'] for n in open_req)}.")
    else:
        out.append("- No milestones past due.")
    out += [
        "",
        "<!-- TODO: explain any slip above, plus scope or design changes made this week. -->",
        "",
    ]
    return "\n".join(out)


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", help="status date YYYY-MM-DD (default: today)")
    ap.add_argument("--new-entry", action="store_true",
                    help="also create docs/progress/<as-of>.md if it does not exist")
    args = ap.parse_args()
    as_of = parse_date(args.as_of, "--as-of") if args.as_of else dt.date.today()

    nodes = load_nodes()
    milestones = load_milestones()

    if args.new_entry:
        PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
        entry = PROGRESS_DIR / f"{as_of.isoformat()}.md"
        if entry.exists():
            print(f"kept existing {entry.relative_to(ROOT)}")
        else:
            entry.write_text(render_entry(nodes, milestones, as_of), encoding="utf-8")
            print(f"wrote {entry.relative_to(ROOT)}")

    WBS_MD.write_text(render_wbs(nodes, milestones, as_of), encoding="utf-8")
    print(f"wrote {WBS_MD.relative_to(ROOT)} ({len(nodes)} nodes, as of {as_of})")


if __name__ == "__main__":
    main()
