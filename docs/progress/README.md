# Progress notes

<!-- GENERATED FILE. Run `make wbs` to refresh. -->

One note per reporting week, each written against a planned milestone using the five-part [template](TEMPLATE.md): reporting date and milestone · completed work and evidence · remaining work · blockers and decisions · next steps and dates. Status as of **18 October 2026**.

**Latest note:** [24 October 2026](2026-10-24.md) — M5

## Milestone status

| Milestone | Due | Required complete | Status | Latest note |
|---|---|---|---|---|
| **M1** Layer 1 Sources + 2.1 Ingest Outputs | Sat 26 Sep | 15 / 15 | ✅ Complete | [03 Oct](2026-10-03.md) |
| **M2** 2.2 Geometry | Sat 03 Oct | 2 / 2 | ✅ Complete | [03 Oct](2026-10-03.md) |
| **M3** 2.3 MHA Benchmarks + 2.4 Ownership Metrics | Sat 10 Oct | 4 / 4 | ✅ Complete 08 Oct (2 days early) | [10 Oct](2026-10-10.md) |
| **M4** 2.5 Computed Metrics | Sat 17 Oct | 4 / 4 | ✅ Complete 17 Oct (on its due date) | [17 Oct](2026-10-17.md) |
| **M5** 2.6 Spatial Statistics | Sat 24 Oct | 3 / 3 | ✅ Complete 18 Oct (6 days early) | [24 Oct](2026-10-24.md) |
| **M6** 2.7 Front-End Payload + 2.8 Writeup | Fri 30 Oct | 0 / 7 | ⏳ Open, due in 12 days | — |
| **M7** Layer 3 Front-End | Mon 16 Nov | 0 / 19 | ⏳ Open, due in 29 days | — |

## How a note connects to the rest of the project

Every task has a **stable node id** (`A1`–`A13`, `B1`–`B27`, `C1`–`C24`, `W1`), and that id is the key everywhere:

| Where | How the id appears | Example |
|---|---|---|
| [`nodes.csv`](../wbs/nodes.csv) → [WBS](../WBS.md) | row id; status and completion date live here | `B16`, not_started |
| GitHub issue | title starts with the id in brackets; one issue per node | [#29](https://github.com/TheWendarr/bah-atlas/issues/29) `[B16] Spatial weights matrix` |
| Commit | subject starts with the id; body says `Refs #N` or `Closes #N` | `B16: queen contiguity weights for 299 MHAs` |
| Progress note | tables list the id with links to its issue, commits, tests, and results | sections 2 and 5 of each note |
| Evidence | pipeline manifests copied to [`docs/evidence/`](../evidence/) record which node produced them | `coverage_metrics_manifest.json` → B12–B15 |

Each note opens with a small machine-readable header (`milestone`, `milestone_status`, `nodes_completed`, `nodes_remaining`, `next_due`, `schedule_changed`, `blockers_open`) so notes can be summarized automatically. Those summaries are a starting point; the deliverables and evidence the notes link to are what establish status.

## All notes

- [24 October 2026](2026-10-24.md) — M5 · complete
- [17 October 2026](2026-10-17.md) — M4 · complete
- [10 October 2026](2026-10-10.md) — M3 · earlier format
- [03 October 2026](2026-10-03.md) — M1, M2 · earlier format

Notes before 17 October 2026 use the earlier weekly-log layout; their headers tag the milestones they cover.
