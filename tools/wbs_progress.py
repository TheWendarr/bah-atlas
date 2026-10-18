#!/usr/bin/env python3
"""Progress notes for BAH Atlas: scaffold a note and build the progress index.

Every progress note follows the five-part template in docs/progress/TEMPLATE.md:

    1. Reporting date and milestone     which planned deliverable this update addresses
    2. Completed work and evidence      what changed, linked to commits, tests and results
    3. Remaining work                   what still has to happen before the milestone closes
    4. Blockers and decisions           what is in the way, what was tried, input needed
    5. Next steps and dates             what comes next, by when, and any schedule change

The traceability key is the node id (A1, B12, C3, W1). The same id appears in
docs/wbs/nodes.csv, docs/WBS.md, the GitHub issue title ("[B12] ..."), the commit
subject ("B12: ..."), and the progress note. This module reads those sources and
fills in everything that can be checked mechanically; the author writes the rest.

Sources it reads (all optional except the CSVs):
    docs/wbs/nodes.csv, docs/wbs/milestones.csv   status and due dates
    docs/wbs/issues.csv                           node id -> issue number (written by `make wbs-sync`)
    docs/evidence/index.csv                       pipeline manifests copied by `make evidence`
    docs/evidence/tests.txt                       last unit-test result copied by `make evidence`
    git log                                       commits that name a node id

Used by tools/wbs_render.py (`make wbs`, `make wbs-week`); not run directly.
Stdlib only.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
import subprocess
import urllib.parse
from pathlib import Path

import wbs_render as wbs

ROOT = wbs.ROOT
PROGRESS_DIR = wbs.PROGRESS_DIR
INDEX_MD = PROGRESS_DIR / "README.md"
ISSUES_CSV = ROOT / "docs" / "wbs" / "issues.csv"
EVIDENCE_DIR = ROOT / "docs" / "evidence"
EVIDENCE_INDEX = EVIDENCE_DIR / "index.csv"
TESTS_TXT = EVIDENCE_DIR / "tests.txt"
TESTS_DIR = ROOT / "tests"
REPO = wbs.REPO_URL

# A node id or a range of them: B12, B12-B15, B12–15, W1.
ID_RE = re.compile(r"(?<![A-Za-z0-9])([ABCW])(\d{1,2})(?:\s*[-–]\s*(?:\1)?(\d{1,2}))?(?![0-9])")
MILESTONE_RE = re.compile(r"(?<![A-Za-z0-9])M(\d{1,2})(?![0-9])")
MAX_COMMITS_PER_NODE = 4


# --------------------------------------------------------------------------- ids

def ids_in(text: str, known: set[str]) -> list[str]:
    """Node ids mentioned in text, ranges expanded, unknown ids dropped, order kept."""
    out: list[str] = []
    for m in ID_RE.finditer(text):
        letter, start, end = m.group(1), int(m.group(2)), m.group(3)
        span = range(start, int(end) + 1) if end and int(end) >= start else [start]
        for i in span:
            nid = f"{letter}{i}"
            if nid in known and nid not in out:
                out.append(nid)
    return out


def milestones_in(text: str) -> list[str]:
    out: list[str] = []
    for m in MILESTONE_RE.finditer(text):
        mid = f"M{m.group(1)}"
        if mid not in out:
            out.append(mid)
    return out


# --------------------------------------------------------------------------- front matter

def read_front_matter(path: Path) -> tuple[dict, str]:
    """Split a note into ({key: value}, body). Values in [a, b] become lists."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    meta: dict = {}
    for line in text[4:end].splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, val = line.split(":", 1)
        val = val.split(" #", 1)[0].strip()
        if val.startswith("[") and val.endswith("]"):
            meta[key.strip()] = [v.strip() for v in val[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = val
    return meta, text[end + 5:]


def front_matter(fields: list[tuple[str, object]]) -> str:
    lines = ["---"]
    for key, val in fields:
        if isinstance(val, list):
            val = "[" + ", ".join(str(v) for v in val) + "]"
        lines.append(f"{key}: {val}")
    lines.append("---")
    return "\n".join(lines)


def note_milestones(meta: dict) -> list[str]:
    ms = meta.get("milestones") or meta.get("milestone") or []
    return ms if isinstance(ms, list) else [ms]


# --------------------------------------------------------------------------- links

def load_issue_map() -> dict[str, str]:
    if not ISSUES_CSV.exists():
        return {}
    with ISSUES_CSV.open(newline="", encoding="utf-8") as fh:
        return {r["id"]: r["issue"] for r in csv.DictReader(fh) if r.get("issue")}


def issue_link(nid: str, issues: dict[str, str]) -> str:
    if nid in issues:
        return f"[#{issues[nid]}]({REPO}/issues/{issues[nid]})"
    q = urllib.parse.quote(f'is:issue in:title "[{nid}]"')
    return f"[{nid} issue]({REPO}/issues?q={q})"


def milestone_link(m: dict) -> str:
    q = urllib.parse.quote(f"{m['id']}:")
    return f"[GitHub milestone]({REPO}/milestones?state=all&q={q})"


def rel(path: Path) -> str:
    """Path relative to docs/progress/, for links inside a note."""
    return Path("..", "..", path.relative_to(ROOT)).as_posix()


# --------------------------------------------------------------------------- git

def git(*args: str) -> str:
    try:
        proc = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def load_commits(known: set[str]) -> list[dict]:
    """Every commit, newest first, with the node and milestone ids it mentions."""
    raw = git("log", "--format=%H%x1f%ad%x1f%s%x1f%b%x1e", "--date=short")
    commits = []
    for rec in raw.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, date, subject, body = (rec.split("\x1f") + ["", "", "", ""])[:4]
        commits.append({
            "sha": sha, "date": date, "subject": subject,
            # The subject is the convention; the body catches older commits.
            "nodes": ids_in(subject, known) or ids_in(body, known),
            "milestones": milestones_in(subject),
        })
    return commits


def commit_link(c: dict) -> str:
    return f"[`{c['sha'][:7]}`]({REPO}/commit/{c['sha']})"


def files_changed_since(path: Path, since: dt.date, until: dt.date) -> list[dict]:
    raw = git("log", f"--since={since.isoformat()} 00:00", f"--until={until.isoformat()} 23:59",
              "--format=%H%x1f%ad%x1f%s", "--date=short", "--", str(path.relative_to(ROOT)))
    out = []
    for line in raw.splitlines():
        sha, date, subject = (line.split("\x1f") + ["", "", ""])[:3]
        out.append({"sha": sha, "date": date, "subject": subject})
    return out


# --------------------------------------------------------------------------- evidence

def load_evidence() -> list[dict]:
    if not EVIDENCE_INDEX.exists():
        return []
    with EVIDENCE_INDEX.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["node_list"] = r.get("nodes", "").split()
    return rows


def tests_for(nid: str) -> list[Path]:
    if not TESTS_DIR.is_dir():
        return []
    pat = re.compile(rf"(?<![A-Za-z0-9]){nid}(?![0-9])", re.IGNORECASE)
    return sorted(p for p in TESTS_DIR.glob("test_*.py") if pat.search(p.read_text(encoding="utf-8")))


def last_test_result() -> str | None:
    if not TESTS_TXT.exists():
        return None
    lines = [l for l in TESTS_TXT.read_text(encoding="utf-8").splitlines() if l.strip()]
    return lines[0] if lines else None


# --------------------------------------------------------------------------- milestones

def required_in(m: dict, nodes: list[dict]) -> list[dict]:
    return [n for n in nodes if n["sublayer"] in m["sublayer_list"] and n["required"] == "required"]


def milestone_status(m: dict, nodes: list[dict], as_of: dt.date) -> str:
    """complete | overdue | open -- the machine-readable value for front matter."""
    req = required_in(m, nodes)
    if req and all(n["status"] == "complete" for n in req):
        return "complete"
    return "overdue" if m["due_date"] < as_of else "open"


def closed_on(m: dict, nodes: list[dict]) -> dt.date | None:
    dates = [n["completed_date"] for n in required_in(m, nodes)]
    if not dates or any(d is None for d in dates):
        return None
    return max(dates)


def status_phrase(m: dict, nodes: list[dict], as_of: dt.date) -> str:
    req = required_in(m, nodes)
    done = sum(n["status"] == "complete" for n in req)
    count = f"{done} / {len(req)} required nodes complete"
    state = milestone_status(m, nodes, as_of)
    if state == "complete":
        when = closed_on(m, nodes)
        if when is None:
            return f"✅ Complete — {count}"
        late = (when - m["due_date"]).days
        timing = ("on its due date" if late == 0 else
                  f"{-late} day{'s' if -late != 1 else ''} early" if late < 0 else
                  f"{late} day{'s' if late != 1 else ''} late")
        return f"✅ Complete {when:%d %b} ({timing}) — {count}"
    if state == "overdue":
        days = (as_of - m["due_date"]).days
        return f"⚠️ Overdue by {days} day{'s' if days != 1 else ''} — {count}"
    days = (m["due_date"] - as_of).days
    return f"⏳ Open, due in {days} day{'s' if days != 1 else ''} — {count}"


def choose_milestone(milestones: list[dict], nodes: list[dict], as_of: dt.date) -> dict:
    """The milestone a note on `as_of` reports against.

    1. one that falls due inside the reporting week, else
    2. the earliest milestone that is still open, else
    3. the last milestone.
    """
    week_start = as_of - dt.timedelta(days=6)
    for m in milestones:
        if week_start <= m["due_date"] <= as_of:
            return m
    for m in sorted(milestones, key=lambda m: m["due_date"]):
        if milestone_status(m, nodes, as_of) != "complete":
            return m
    return milestones[-1]


def next_milestone(m: dict, milestones: list[dict]) -> dict | None:
    later = sorted((x for x in milestones if x["due_date"] > m["due_date"]), key=lambda x: x["due_date"])
    return later[0] if later else None


# --------------------------------------------------------------------------- notes on disk

def list_notes() -> list[tuple[dt.date, Path, dict]]:
    """Dated notes, newest first, with their front matter."""
    out = []
    for p in wbs.progress_entries():
        meta, _ = read_front_matter(p)
        out.append((dt.date.fromisoformat(p.stem), p, meta))
    return out


def notes_mentioning(nid: str, known: set[str]) -> list[tuple[dt.date, Path]]:
    hits = []
    for d, p, _ in list_notes():
        _, body = read_front_matter(p)
        if nid in ids_in(body, known):
            hits.append((d, p))
    return hits


# --------------------------------------------------------------------------- render: note

TODO = "<!-- TODO (author): {} -->"


def render_note(nodes: list[dict], milestones: list[dict], as_of: dt.date, milestone_id: str | None) -> str:
    known = {n["id"] for n in nodes}
    by_id = {n["id"]: n for n in nodes}
    issues = load_issue_map()
    commits = load_commits(known)
    evidence = load_evidence()
    tests_line = last_test_result()

    if milestone_id:
        hits = [m for m in milestones if m["id"] == milestone_id.upper()]
        if not hits:
            wbs.die(f"unknown milestone '{milestone_id}'")
        m = hits[0]
    else:
        m = choose_milestone(milestones, nodes, as_of)
    nxt = next_milestone(m, milestones)

    week_start = as_of - dt.timedelta(days=6)
    in_m = [n for n in nodes if n["sublayer"] in m["sublayer_list"]]
    req = [n for n in in_m if n["required"] == "required"]
    done_week = [n for n in nodes if n["completed_date"] and week_start <= n["completed_date"] <= as_of]
    remaining = [n for n in req if n["status"] != "complete"]
    optional_open = [n for n in in_m if n["required"] == "optional" and n["status"] != "complete"]
    state = milestone_status(m, nodes, as_of)

    previous = [d for d, _, _ in list_notes() if d < as_of]
    since = (previous[0] + dt.timedelta(days=1)) if previous else week_start
    schedule_commits = files_changed_since(wbs.MILESTONES_CSV, since, as_of)

    fm = front_matter([
        ("type", "progress-note"),
        ("date", as_of.isoformat()),
        ("period", f"{week_start.isoformat()} to {as_of.isoformat()}"),
        ("milestone", m["id"]),
        ("milestone_due", m["due"]),
        ("milestone_status", state),
        ("nodes_completed", [n["id"] for n in done_week]),
        ("nodes_remaining", [n["id"] for n in remaining]),
        ("next_milestone", nxt["id"] if nxt else "none"),
        ("next_due", nxt["due"] if nxt else "none"),
        ("schedule_changed", "true" if schedule_commits else "false"),
        ("blockers_open", 0),
    ])

    out: list[str] = [fm, ""]
    w = out.append
    w(f"# Progress note — {as_of:%d %B %Y} · {m['id']} {m['title']}")
    w("")
    w("_Follows the [progress-note template](TEMPLATE.md) · all notes and milestone status: "
      "[progress index](README.md) · full tracker: [WBS](../WBS.md). Tables marked *generated* "
      "are filled from `nodes.csv`, git history and `docs/evidence/`; parts marked *author* are written by hand._")
    w("")

    # ---- 1
    w("## 1. Reporting date and milestone")
    w("")
    w("| | |")
    w("|---|---|")
    w(f"| **Reporting date** | {as_of:%a %d %b %Y} (covers {week_start:%d %b} – {as_of:%d %b}) |")
    w(f"| **Milestone** | **{m['id']}** {m['title']} — [WBS](../WBS.md#milestones) · {milestone_link(m)} |")
    w(f"| **Due** | {m['due_date']:%a %d %b %Y} |")
    w(f"| **Status** | {status_phrase(m, nodes, as_of)} |")
    w(f"| **Nodes in milestone** | {', '.join(n['id'] for n in req) or '—'}"
      + (f" (optional: {', '.join(n['id'] for n in in_m if n['required'] == 'optional')})"
         if any(n["required"] == "optional" for n in in_m) else "") + " |")
    w("")
    w("**In brief** *(author)*:")
    w("")
    w(TODO.format("two to four sentences: what this week delivered toward the milestone."))
    w("")

    # ---- 2
    w("## 2. Completed work and evidence")
    w("")
    if done_week:
        w("*Generated.* Nodes completed this reporting period, with the commits, tests, and pipeline "
          "results that support each one.")
        w("")
        w("| Node | Issue | Done | Commits | Tests | Results |")
        w("|---|---|---|---|---|---|")
        for n in done_week:
            # Status-only commits ("Close M4: ...") are listed separately as milestone commits.
            mine = [c for c in commits if n["id"] in c["nodes"] and not c["milestones"]][:MAX_COMMITS_PER_NODE]
            c_cell = ", ".join(commit_link(c) for c in mine) or "—"
            t_files = tests_for(n["id"])
            t_cell = ", ".join(f"[{p.name}]({rel(p)})" for p in t_files) or "—"
            ev = [e for e in evidence if n["id"] in e["node_list"]]
            e_cell = ", ".join(f"[{e['file']}](../evidence/{e['file']})" for e in ev) or "— *(run `make evidence`)*"
            w(f"| **{n['id']}** {n['name']} | {issue_link(n['id'], issues)} | {n['completed_date']:%d %b} "
              f"| {c_cell} | {t_cell} | {e_cell} |")
        w("")
        if tests_line:
            w(f"Unit tests at last `make evidence`: `{tests_line}` ([log](../evidence/tests.txt)).")
            w("")
    else:
        w("*Generated.* No node was marked complete this reporting period.")
        w("")
    m_commits = [c for c in commits if m["id"] in c["milestones"]
                 and week_start.isoformat() <= c["date"] <= as_of.isoformat()]
    if m_commits:
        w("Milestone commits: " + ", ".join(f"{commit_link(c)} {c['subject']}" for c in m_commits))
        w("")
    w("**What changed and what the results show** *(author)*:")
    w("")
    w(TODO.format("what the evidence above demonstrates; include one headline result "
                  "(a number from the results file, a map, or a screenshot) and link it."))
    w("")

    # ---- 3
    w("## 3. Remaining work")
    w("")
    w(f"*Generated* — required nodes still open in {m['id']}:")
    w("")
    if remaining:
        for n in remaining:
            label = "in progress" if n["status"] == "in_progress" else "not started"
            w(f"- **{n['id']}** {n['name']} — {label} · {issue_link(n['id'], issues)}")
    else:
        w(f"- None. Every required node in {m['id']} is complete.")
    if optional_open:
        w("")
        w("Optional nodes in this milestone (do not gate it): "
          + ", ".join(f"**{n['id']}** {n['name']}" for n in optional_open) + ".")
    w("")
    w("**Other work before this milestone is done** *(author)*:")
    w("")
    w(TODO.format("anything not captured by a node — QA, documentation, fixes found this week. "
                  "Write 'None.' if nothing."))
    w("")

    # ---- 4
    w("## 4. Blockers and decisions")
    w("")
    overdue = [(x, [n for n in required_in(x, nodes) if n["status"] != "complete"])
               for x in milestones if milestone_status(x, nodes, as_of) == "overdue"]
    if overdue:
        w("*Generated* — milestones past due:")
        w("")
        for x, open_req in overdue:
            w(f"- **{x['id']}** {x['title']} (due {x['due_date']:%d %b}) has {len(open_req)} required "
              f"node(s) open: {', '.join(n['id'] for n in open_req)}.")
    else:
        w("*Generated:* no milestone is past due.")
    w("")
    w("*Author* — one row per blocker or decision. **Input needed** is where the instructor's answer is "
      "requested; write *No* when the row is for the record only. Update `blockers_open` in the header.")
    w("")
    w("| Node | Type | What happened | What I tried / decided | Input needed |")
    w("|---|---|---|---|---|")
    w(TODO.format("replace the example row; delete it if there is nothing to report."))
    w("| B?? | Blocker / Decision | | | No |")
    w("")

    # ---- 5
    w("## 5. Next steps and dates")
    w("")
    w("*Generated* — open required nodes and the date each is due by its milestone (⚠️ = already past due):")
    w("")
    w("| Due by | Node | Issue | Milestone |")
    w("|---|---|---|---|")
    # Earlier milestones still open come first, then this one, then the next.
    rows = [(x, n) for x in milestones if x["due_date"] < m["due_date"]
            for n in required_in(x, nodes) if n["status"] != "complete"]
    rows += [(m, n) for n in remaining]
    if nxt:
        rows += [(nxt, n) for n in required_in(nxt, nodes) if n["status"] != "complete"]
    for x, n in rows:
        flag = " ⚠️" if x["due_date"] < as_of else ""
        w(f"| {x['due_date']:%a %d %b}{flag} | **{n['id']}** {n['name']} | {issue_link(n['id'], issues)} | {x['id']} |")
    if not rows:
        w("| — | All milestones complete | | |")
    w("")
    w("**Next concrete step** *(author)* — the first piece of work, with the date it will be done:")
    w("")
    w("- " + TODO.format("Sat DD Mon — NODE: what will exist by then (a file, a result, a map)."))
    w("")
    if schedule_commits:
        w("**Schedule** *(generated)*: milestone dates changed since the previous note — "
          + "; ".join(f"{commit_link(c)} {c['subject']} ({c['date']})" for c in schedule_commits)
          + ". " + TODO.format("explain the change."))
    else:
        w(f"**Schedule** *(generated)*: no change to milestone dates since "
          f"{'the previous note' if previous else 'the start of this period'} "
          f"([`milestones.csv`](../wbs/milestones.csv) unchanged since {since:%d %b}).")
    w("")
    w("---")
    w("")
    w("*AI-assistance disclosure: Claude (Anthropic) assisted in building the tooling that generates "
      "the marked sections of this note. The narrative, decisions, and status reporting are the author's.*")
    w("")
    return "\n".join(out)


# --------------------------------------------------------------------------- render: index

def render_index(nodes: list[dict], milestones: list[dict], as_of: dt.date) -> str:
    notes = list_notes()
    issues = load_issue_map()
    out: list[str] = []
    w = out.append
    w("# Progress notes")
    w("")
    w("<!-- GENERATED FILE. Run `make wbs` to refresh. -->")
    w("")
    w(f"One note per reporting week, each written against a planned milestone using the five-part "
      f"[template](TEMPLATE.md): reporting date and milestone · completed work and evidence · remaining "
      f"work · blockers and decisions · next steps and dates. Status as of **{as_of:%d %B %Y}**.")
    w("")
    if notes:
        d, p, meta = notes[0]
        ms = ", ".join(note_milestones(meta)) or "—"
        w(f"**Latest note:** [{d:%d %B %Y}]({p.name}) — {ms}")
        w("")

    w("## Milestone status")
    w("")
    w("| Milestone | Due | Required complete | Status | Latest note |")
    w("|---|---|---|---|---|")
    for m in milestones:
        req = required_in(m, nodes)
        done = sum(n["status"] == "complete" for n in req)
        latest = next(((d, p) for d, p, meta in notes if m["id"] in note_milestones(meta)), None)
        link = f"[{latest[0]:%d %b}]({latest[1].name})" if latest else "—"
        w(f"| **{m['id']}** {m['title']} | {m['due_date']:%a %d %b} | {done} / {len(req)} "
          f"| {status_phrase(m, nodes, as_of).split(' — ')[0]} | {link} |")
    w("")

    w("## How a note connects to the rest of the project")
    w("")
    w("Every task has a **stable node id** (`A1`–`A13`, `B1`–`B27`, `C1`–`C24`, `W1`), and that id is "
      "the key everywhere:")
    w("")
    w("| Where | How the id appears | Example |")
    w("|---|---|---|")
    ex = "B16"
    w(f"| [`nodes.csv`](../wbs/nodes.csv) → [WBS](../WBS.md) | row id; status and completion date live here | `{ex}`, not_started |")
    w(f"| GitHub issue | title starts with the id in brackets; one issue per node | {issue_link(ex, issues)} `[{ex}] Spatial weights matrix` |")
    w(f"| Commit | subject starts with the id; body says `Refs #N` or `Closes #N` | `{ex}: queen contiguity weights for 299 MHAs` |")
    w(f"| Progress note | tables list the id with links to its issue, commits, tests, and results | sections 2 and 5 of each note |")
    w(f"| Evidence | pipeline manifests copied to [`docs/evidence/`](../evidence/) record which node produced them | `coverage_metrics_manifest.json` → B12–B15 |")
    w("")
    w("Each note opens with a small machine-readable header (`milestone`, `milestone_status`, "
      "`nodes_completed`, `nodes_remaining`, `next_due`, `schedule_changed`, `blockers_open`) so notes can be "
      "summarized automatically. Those summaries are a starting point; the deliverables and evidence the notes "
      "link to are what establish status.")
    w("")

    w("## All notes")
    w("")
    if not notes:
        w("_No notes yet._")
    for d, p, meta in notes:
        ms = ", ".join(note_milestones(meta)) or "—"
        tag = " · earlier format" if meta.get("format") == "legacy" else (
            f" · {meta['milestone_status']}" if meta.get("milestone_status") else "")
        w(f"- [{d:%d %B %Y}]({p.name}) — {ms}{tag}")
    w("")
    w("Notes before 17 October 2026 use the earlier weekly-log layout; their headers tag the milestones they cover.")
    w("")
    return "\n".join(out)
