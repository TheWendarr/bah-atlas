# Progress-note template

Every note in this folder uses the same five parts, in this order, so status can be read without
reconstructing it from earlier notes. `make wbs-week` writes a new note with the *generated* parts
already filled from [`nodes.csv`](../wbs/nodes.csv), git history, and [`docs/evidence/`](../evidence/);
the author fills the parts marked *author*.

## Weekly routine

1. Finish work in commits whose subject starts with the node id: `B16: queen contiguity weights`.
   Put `Refs #N` (or `Closes #N`) in the body; `make wbs-show N=B16` prints the issue number.
2. `make done N="B16"` — marks the node complete and regenerates the WBS.
3. `make evidence` — copies the pipeline's result manifests and the test result into `docs/evidence/`.
4. `make wbs-week` — scaffolds `docs/progress/<date>.md` and refreshes the [progress index](README.md).
   Add `M=M5` to report against a specific milestone.
5. Fill in the *author* parts, delete the TODO comments, commit (`Close M5: ...` or `M5: progress note 24 Oct`), push.
6. Optional: `make wbs-sync` updates GitHub milestones and issues, including links from each issue back to the notes that mention it.

## The five parts

### Header (generated)

A short machine-readable block at the top of the file:

```yaml
---
type: progress-note
date: 2026-10-24             # reporting date
period: 2026-10-18 to 2026-10-24
milestone: M5                # the planned deliverable this note reports against
milestone_due: 2026-10-24
milestone_status: open       # complete | open | overdue
nodes_completed: [B16, B17]  # completed during the period
nodes_remaining: [B18]       # required nodes still open in the milestone
next_milestone: M6
next_due: 2026-10-30
schedule_changed: false      # true if milestones.csv changed since the previous note
blockers_open: 0             # author: number of rows in part 4 still needing action or input
---
```

### 1. Reporting date and milestone

- *Generated:* reporting date and period, the milestone with links to the WBS and the GitHub milestone, its due date, status, and nodes.
- *Author:* **In brief** — two to four sentences on what the period delivered toward the milestone.

### 2. Completed work and evidence

- *Generated:* one row per node completed in the period, with its issue, completion date, the commits that name it, the tests that exercise it, and the result manifest it produced.
- *Author:* **What changed and what the results show** — what the evidence demonstrates, with at least one headline result (a number from the results file, a map, or a screenshot) linked.

### 3. Remaining work

- *Generated:* required nodes in the milestone that are still open, and any optional ones.
- *Author:* work that is not a node but has to happen before the milestone is done (QA, documentation, fixes). "None." is a valid answer.

### 4. Blockers and decisions

- *Generated:* any milestone past its due date, with its open nodes.
- *Author:* one table row per blocker or decision:

  | Node | Type | What happened | What I tried / decided | Input needed |
  |---|---|---|---|---|
  | B16 | Blocker | *(example)* Some MHA polygons have no contiguous neighbour | Built queen contiguity; listed the isolated MHAs | **Yes:** drop them or switch to k-nearest neighbours? |

  **Input needed** says *Yes* plus the question when the instructor's answer is requested, *No* when the row is for the record.

### 5. Next steps and dates

- *Generated:* every open required node in this milestone and the next one, with the date its milestone falls due, and whether milestone dates changed since the previous note (checked against the git history of [`milestones.csv`](../wbs/milestones.csv)).
- *Author:* **Next concrete step** — the first piece of work, the node it belongs to, and the date it will be done, stated as an output: *Wed 21 Oct — B16: spatial weights file for all 299 MHAs, with the isolate list.*

## Conventions

- **Stable ids.** Node ids (`A1`–`A13`, `B1`–`B27`, `C1`–`C24`, `W1`) and milestone ids (`M1`–`M7`) never change meaning. A dropped node keeps its id retired rather than reused.
- **One issue per node**, titled `[B16] <name>`, created and kept in step by `make wbs-sync`; [`docs/wbs/issues.csv`](../wbs/issues.csv) maps ids to issue numbers.
- **Commit subjects name the node** (`B16: ...`) or milestone (`Close M5: ...`); `meta:` covers housekeeping. `make hooks` turns on a check for this.
- **Evidence is committed.** Pipeline outputs under `data/` are not in git; their manifests (input hashes, row counts, validation results, summaries) are copied to `docs/evidence/` by `make evidence`, and notes link those copies.
