# Session handover — 2026-08-20 (first end-to-end test session; ten divergences seeded)

## Read this first

**A full candidate session was run and it worked as far as step 7.** A simulated
Barcelona construction worker (handle `perico`, `fiction: true`) went through
steps 0 → 1 → 2 → 3 → 7 → 8 → 9 with the S11 meta channel open. The notes are in
the test-mode ledger for session `test-2026-08-20-a`; read it with
`query_notes.py --id test-2026-08-20-a`.

**It broke at exactly the two steps whose gates are `not_implemented`.** That is
the single most useful result of the session, and it is not a coincidence:

| step | gate state | outcome |
|---|---|---|
| 0, 1, 2, 3, 7 | implemented | ran correctly; checkpoints exit 0 honestly |
| **8 understanding** | **not_implemented** | `extract()` settled **0 of 25** dimensions on all seven adverts — the dimension model is entirely software-sector. Reported success anyway. |
| **9 ranking** | **not_implemented** | the card was assembled by a model, which T44 forbids, and dropped `offer.url` although every record carried it |

**`run_checkpoint.py` printed `"gate_state": "not_implemented"` for both and
exited 0.** Artefact presence stood in for a check nobody ran. That is D-21.

**Every offer sourced was already dead.** Owner verified: the two jobtoday
listings 403, every tablondeanuncios one reads "puesto ocupado". They came from
a generic `WebSearch` over indexed pages, and a search index outlives the
advert. `offer_schema_violations` passed regardless — **schema validity is not
liveness**. Owner's rule, now D-18: real searches run **inside the portals**; a
generic `WebSearch` is for *discovering* portals, not for collecting adverts.

## What landed

**PR #89 merged (`f598590`)** — ten divergences, ten plan rows, ten issue
handles (#90–#99). All five gates green locally before the merge.

| task | issue | |
|---|---|---|
| `t-bd59e70b` | #98 | D-13 say what the tool is doing before a long silent setup |
| `t-05892c87` | #90 | D-14 never offer autónomo as a thing the candidate might want |
| `t-65ecce18` | #93 | D-15 stop offering to end the session at every step boundary |
| `t-221adf32` | #92 | D-16 sourcing has no real connector — say so, offer to build one |
| `t-c40f0f88` | #99 | D-17 ranked offers must carry their URL |
| `t-b1355b65` | #96 | D-18 offers stale on arrival — check freshness at source |
| `t-e6546af7` | #97 | D-19 the dimension model is software-only |
| `t-6f79e090` | #94 | D-20 no constraint field holds a commutable radius |
| `t-20ca057d` | #91 | D-21 a `not_implemented` gate must not exit 0 as `coverage_met` |
| `t-6f9328ab` | #95 | D-22 the repo gate is required by prose and enforced by nothing |

**Every gate is the failing `false` placeholder.** None is claimable until
somebody writes a real one, which for most means the test named in its plan row
— which does not exist yet. That is deliberate, not an oversight.

`task_select.py` returns **D-14** as the next unblocked task.

## Two things to know before starting

**1. `plan_v2` is stricter than it looks, and it is right.** The first attempt
titled these `S12-N`. `test_the_committed_plan_and_queue_agree` refused the
board: `S12-1` is not a label (`_LABEL_RE` accepts `T\d+`, `S\d+`, `D-\d+`
only), membership is checked **both ways**, and a plan row's `Depends` must
match the payload's own `deps`. Two tasks needed real deps wired to `lo-a22a`
(T44) and `lo-9e41` (T26). Seed through the plan table, not around it.

**2. Nothing runs the repo gate. That is D-22, and it bit this session.** The
five commands ran only because the owner asked. Actions is still out of runner
minutes, so `ci.yml` and `arsenal-queue.yml` never fire — which also means the
issue handles above were opened **by hand**, not by the workflow.
`open_task_pr.sh` re-runs only a task's own payload gate, and `keyword-guard`
fires only on `arsenal/**` branches. Until D-22 lands, run before every merge:

```bash
make lint && make test && make evidence && make verify-subtree && make verify-gates
```

## One is upstream, nine are ours

Checked deliberately, because a fix to the vendored tree gets overwritten by the
next `make arsenal-upgrade` and fails `make verify-subtree` in the meantime.

**Nine are host-owned** — `.claude/skills/step-*` (D-13, D-14, D-15, D-17, and
`run_checkpoint.py` for D-21), `src/jobsearch/*` (D-18, D-19, D-20, D-21),
`dimensions/` and `connectors/` (D-16, D-19). Nothing under `claude-arsenal/`.

**D-22 was mixed, and is now split.** Its bundle half —
`claude-arsenal/agents/worker.md` step 4 asks a worker to "run the host lint
gate if one exists" and no script enforces it, while `open_task_pr.sh` re-runs
`gate_run.sh` and never asks about the repo gate — is filed upstream as
**`claude-arsenal#175`**. The host half stays here: a `make gate` target
running all five, for upstream's proposed `host-gate` config key to point at.

`keyword-guard` firing only on `arsenal/**` is **correct** and was ruled out,
not filed: a PR that is not a task PR should not need `Closes #<issue>`.

## Left open

- **A permissions edit the owner has to make.** `Bash(gh pr merge:*)`,
  `Bash(gh run list:*)`, `Bash(gh run view:*)` in `.claude/settings.json`'s
  `permissions.allow`. A session cannot widen its own permissions — the
  classifier blocks both the merge and the edit, correctly.
- **`tools/profile_guard.sh` matches a candidate path mentioned in *prose*, not
  only one being opened.** Writing this handover was refused because an earlier
  draft named a ledger path in its text. Not yet seeded; decide whether the
  guard should inspect the tool's target rather than the whole command string.
- **D-12 (`t-e1ca8374`, #83) still waits on the owner.** Untouched by this
  session; resolution B exists since arsenal v0.33.0 (`gate: unmeasured`).
- **`query_status` flags a pre-existing mixed-priority board**: 32 tasks on the
  size scale, 2 carrying 70/60. Not from this session — every task seeded here
  is priority 10.
- **Steps 5, 6, 10, 11, 12 are still `not_implemented`** and were not reached.
  Step 4 (traits) is implemented but was skipped; the runtime offered
  `reactions`, `understanding`, `application`, `interview_log`.
