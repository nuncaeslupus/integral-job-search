# Session handover — 2026-08-20 (D-13 in review; four issues filed upstream)

## Read this first

**[#105](https://github.com/nuncaeslupus/job-search/pull/105) — D-13** is open on
`claude/continue-3avmas` as `d4ff6d2`, closing
[#97](https://github.com/nuncaeslupus/job-search/issues/97). Task archived at
`arsenal/tasks/_history/t-bd59e70b.md`. All five gates pass locally on that
head. **It was deliberately not merged**: Qodo's review was still running, and
its round on #102 found four real defects, so merging past it throws away the
most useful check this repo has.

`task_select.py` returns the next task once #105 lands. Seven divergences remain
open — read the selector, not the numeric order of the D-labels.

## D-13, and the false positive worth not rediscovering

The fix: a fifth cross-cutting rule — **"Say what is happening before a
silence"** — in `status/spec-v2-steps.md` *and* §5.4 of
`status/spec-v2-process.md`, added to both at once because D-15's root cause was
one rule stated in one document and contradicted in the other. All thirteen step
skills carry it in their `## Protocol` section with a worked example in that
step's own words. `jobsearch.step_narration` measures it.

**The rule was absent, not broken.** §5.4 already required the tool to *say why*
— what a step is for and what it stores — which governs the *subject* of a step
and says nothing about the seconds spent executing inside it. Given no
instruction, the model did the efficient thing and worked in silence.

**The first cut of limb 3 flagged twelve false offenders**, and the mechanism
generalises. Limb 3 asks whether the step where the candidate first says who
they are acknowledges them *before* the setup. Detecting which step that is by
searching the prose for "creates their profile" matched **all thirteen skills**
— because the shared rule sentence I had just added names profile creation. The
probe found the rule rather than the behaviour.

> A check whose subject can be named by the very sentence that satisfies it is
> not a check.

It is `session_exit`'s prose/fence split in a second disguise, and it will
appear a third time. Limb 3's subject is now read from the settled step list
(`n == 0`), never from prose. `test_the_greeting_limb_is_read_from_the_step_list_not_the_prose`
locks it.

Verified against the pre-fix library via `git archive HEAD`: **13** offenders,
all thirteen on limbs 1 and 2, step 0 additionally on limb 3. After: **0**.

## Four issues filed upstream, three of them about context cost

The owner asked for anything that looks wrong to go to `claude-arsenal`.

- **[#181](https://github.com/nuncaeslupus/claude-arsenal/issues/181)** —
  `task_id_from_issue` resolves only from the issue **body**, so the session-start
  fetch must pull every task issue's full prose into context: **~9k tokens** on
  this 40-issue board, of which the useful payload is one identifier per issue.
  Proposed a **title fallback** — the titles already match the task files'
  `title:` verbatim, because `handle_sync.py` and `arsenal-queue.yml` both title
  the handle from the task file. With it, the documented fetch drops `body` and
  costs **~1.2k**.
- **[#182](https://github.com/nuncaeslupus/claude-arsenal/issues/182)** —
  `github_channel.sh --detect` prints `rest` here because the agent proxy answers
  `GET /rate_limit` **itself**, 200, without the credentials ever reaching
  GitHub. Real calls then 403. This is *not* the read/write gap the code's
  comment already anticipates — the probe never left the proxy. A false `rest` is
  worse than `none`, which is a handled outcome. Proposed probing `GET /user`.
- **[#183](https://github.com/nuncaeslupus/claude-arsenal/issues/183)** —
  `check_update.sh` reports a missing `arsenal` remote as *"the bundle was
  copied, not added as a git subtree"*. Two independent facts: remotes are not
  cloned. `verify-subtree` says `subtree_recorded_in_history: true` on the same
  tree, and the script's own line 197 does the correct check but is unreachable.
- **[#184](https://github.com/nuncaeslupus/claude-arsenal/issues/184)** — the
  protocol asks a worker to follow an existing module's shape and names no cheap
  way to read one. Reading `session_exit.py` whole cost ~6k for a shape worth
  ~400 tokens. Proposed a `references/worker-loop.md` note and a `bin/outline.sh`.

## Context economy — what actually costs, measured

The owner asked directly. On this surface, per session:

| item | cost | note |
|---|---|---|
| task-issue fetch with bodies | **~9k** | the big one — see #181 |
| MCP tool schemas (github + CCR) | ~12k resident | most of github's 60 tools are deferred |
| system tools + prompt | ~30k | fixed |
| `handover.md` | **~1.9k** | **not** worth shrinking; it is what stops re-derivation |
| `AGENTS.md` + `CLAUDE.md` | ~6k | already won by #177's chunking |

**Gmail/Calendar/Drive are gone** — the owner deleted them, and `ListConnectors`
now returns `[]`. Remove the "turn off unused connectors" item from any future
carry-forward list; it is done.

`claude-arsenal` was attached with `add_repo` for issue filing and **deliberately
not cloned** — the API is all a filing session needs, and a shallow clone through
the proxy costs 5–10 minutes for nothing.

## CI is still out of runner minutes

Re-confirmed on `d4ff6d2`: all five checks failed, `runner_id: 0`, empty
`runner_name`, job **completed 3 seconds after it started** (17:43:04 →
17:43:07). Not the diff. Do not push speculative fixes.

All five gates run locally on that head:

```bash
make lint && make test && make evidence && make verify-subtree && make verify-gates
```

`make test` 1123 passed / 1 skipped · `make evidence` no drift ·
`make verify-subtree` 0 diverging, 33 assets · `make verify-gates` **60**
terminal tasks, 60 gates asserted, 0 without a fenced block.

`status/evidence/D3.json` moved by eleven lines — it records where a superseded
expression sits in the step spec, and the new rule shifted it. Expected, and
regenerated with `make evidence`, never by hand.

## Surface facts, unchanged and re-confirmed

**`github_channel.sh --detect` prints `rest`, and `rest` does not work here** —
now filed as #182. Fetch issues with the MCP `list_issues` tool and hand-write
the JSON the scripts read (`number`, `state`, `body` carrying the task id,
`labels`, `assignees`). Older `lo-*` issues carry no `arsenal-task:` line — they
resolve through the `arsenal/tasks/<id>.md` payload link, so keep that link.

**`claim_task.sh` returns `manual POST`** on this surface; `create_branch` on
`arsenal/claims/<id>` is the compare-and-swap. 201 = won.

**`open_task_pr.sh` still was not used** — it cuts `arsenal/<id>-<slug>` off the
default branch, and this surface restricts pushes to the session's designated
branch. Archive, `Closes #<issue>` in both commit and PR body, and the PR were
done by hand to the same shape.

**Merging works** via the MCP `merge_pull_request` tool.

## Left open (carried forward)

- **#105 needs Qodo's review addressed, then merging.**
- **A permissions edit only the owner can make**: `Bash(gh run list:*)` and
  `Bash(gh run view:*)` in `.claude/settings.json`.
- **`tools/profile_guard.sh` matches a candidate path mentioned in *prose***,
  not only one being opened. Still not seeded.
- **D-12 (`t-e1ca8374`, #83) still waits on the owner.** Resolution B has existed
  since v0.33.0 (`gate: unmeasured`).
- **`claude-arsenal#180`** — `open_task_pr.sh` reads `host-gate` from the git
  root and runs it in the cwd. Inert here while `host-gate` is unset.
- **Steps 5, 6, 10, 11, 12 are still `not_implemented`**, and steps 8 and 9
  certify over unbuilt gates until D-21 lands.
- **One pre-existing board flag**: mixed-priority-convention — 30 tasks use the
  size scale [10, 5, 1, 0] and 2 use other values [70, 60].
