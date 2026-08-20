# Session handover — 2026-08-20 (D-15 worked; the bundle is two versions stale)

## Read this first

**D-15 is done and pushed, awaiting merge.** PR
[#102](https://github.com/nuncaeslupus/job-search/pull/102) carries `Closes #93`
in both the commit and the body; the task file is archived at
`arsenal/tasks/_history/t-65ecce18.md` with `status: merged`. All five gates were
run locally and pass. Qodo was reviewing when this was written — **check #102 for
review comments before starting anything else.**

`task_select.py` returns **D-13** (`t-20ca057d`, #91) next once #102 merges.
Eight divergences remain open, all at priority 10, so read the selector rather
than the numeric order of the D-labels.

## The one thing worth acting on next: the bundle is stale, and nothing said so

`claude-arsenal/bin/check_update.sh --check-only` reports:

> no 'arsenal' remote configured — update checking is INERT for this repo (the
> bundle was copied, not added as a git subtree)

So no session has ever been told about an upgrade. The vendored bundle is
**v0.33.0**; upstream is at **v0.35.0**. The remote is now wired up locally
(`git remote add arsenal https://github.com/nuncaeslupus/claude-arsenal`), but a
git remote is machine-local and does **not** travel with the repo — the next
cloud session will find the check inert again unless this is fixed properly.

**`claude-arsenal#177` has landed upstream.** `AGENTS.md` at v0.35.0 is
**185 lines / 9,983 bytes** against the vendored **762 lines / 39,424 bytes** —
roughly 14.7k → 3.7k tokens resident on *every turn of every session*, since it
is imported into `CLAUDE.md`. That is the single largest fixed cost this repo
carries. Measured this session: ~66k of the context window is resident before
the first tool call, and `AGENTS.md` is 14.7k of it.

Upgrade deliberately — `make arsenal-upgrade REF=v0.35.0` — then **`make reader`
and `make evidence`**, per `CLAUDE.md`. Two versions of changes to read first
(v0.34.0 and v0.35.0), and `verify-subtree` compares 26 assets, so expect the
bundle half of D-22 (`claude-arsenal#175`) to have moved too.

Not seeded as a task: it is an upgrade, not a divergence. Seed one if it is not
done next session.

## What D-15 turned out to be

Not four bad sentences — a rule that **already existed** in the one document the
model never reads, contradicted by everything that does.

`status/spec-v2-steps.md` has carried "Invite forward, do not offer an exit …
Stopping is always allowed and never the default suggestion" since the document
was settled (7370cd6, 2026-08-18). Two documents diverged from it in opposite
directions, and the live session sat between them:

| where | what it said |
|---|---|
| `spec-v2-steps.md`, cross-cutting rule 4 | do not offer an exit |
| `spec-v2-steps.md`, per-step Boundary examples | *"or leave it here?"*, *"Leave it there?"*, *"or pause?"*, *"or leave it?"* (steps 1, 4, 5, 10) |
| `spec-v2-process.md` §3.2 | required the offer, in as many words |
| all thirteen step skills | the examples verbatim, and no rule at all |

Four worked demonstrations of the behaviour, zero statements of the rule. It
behaved exactly as instructed.

**This is a shape worth looking for again.** D-14 was silence; D-15 is silence
*plus a contradicting example*, which is strictly worse — the model does not
improvise, it copies. When a defect looks like bad prose, check whether the rule
already exists somewhere the model never loads.

`jobsearch.session_exit` measures it on two limbs (fenced example offers to stop;
Boundary carries no governing rule), reading the two halves of the section
separately so the rule sentence does not trip the check it satisfies. It reads
the requirement **out of the step spec** rather than restating it, and reports
`-1` if that rule is ever dropped: a gate must stop reading as a pass when the
policy it enforces is withdrawn. `step_boundaries_offering_an_exit`: 13 → 0,
verified against a `git archive HEAD` copy of the pre-fix library.

## Review round (Qodo, PR #102) — four findings, one root cause, all fixed

All four were real, and they shared one mistake: **the process calls two
different things stopping, and the first cut collapsed them.**

- the **exit** ends the sitting — D-15's subject;
- §3.3's **offered skip** — *"we can stop here and go look at real jobs with what
  I have"* — ends the *first-run climb* and sends the candidate **forward** to a
  provisional L1 ranking. §3.3 requires it at the end of every first-run step.

`_EXIT_OFFER_RE` matched `stop here`, so §3.3's prescribed sentence read as an
offender: a compliant boundary would have failed the gate, and the gate would
have enforced the opposite of the process contract. The skills' rule ("never
close by offering to stop") read as forbidding the skip too — in all thirteen
files. Four exit phrasings ("wrap up here?", "end here?", "take a break and
resume tomorrow?", "enough for one sitting") passed straight through.

Fixed in `1c09d82`: a forward-shortcut licence requiring a real destination
(skips recorded in the evidence, never silently dropped), the rule reworded to
name the exit and preserve the skip, §3.2 and §3.3 each saying which stop they
mean, and the pattern widened. Five tests, each failing against the pre-fix code.

**Two lessons worth keeping.** Step 11's "Ready to send, or sit on it?" already
had an exclusion for being a forward choice — one was excluded and the mandated
one was not, so *if a check excludes one false positive, look for its siblings.*
And the fix for D-15 reproduced D-15's own failure mode: a rule in one document
contradicted by another. Fixing a cross-document divergence means reading every
document that touches the subject, not just the two the task names.

## The board, read this session

`query_status.py`: 91 tasks — open 13, claimed 0, done 1, cancelled 1,
blocked 19, merged 57. One flag, the pre-existing one:

> mixed-priority-convention: 31 task(s) use the size scale [10, 5, 1, 0] and 2
> use other values [70, 60]

`handle_sync.py` reports every task has an issue handle.

## Surface facts (unchanged, re-confirmed)

**`github_channel.sh --detect` prints `rest`, and `rest` does not work here.**
Fetch issues with the MCP `list_issues` tool and hand-write the JSON the scripts
read (`number`, `state`, `body` carrying `arsenal-task: <id>`, `labels`,
`assignees`). `claim_task.sh` exits 5 with a `manual POST` line — make that call
with `mcp__github__create_branch` (201 = won, 422 = lost). Won #93 that way.

**`gate_run.sh` cannot re-run an archived task's gate here.** Once the payload
moves to `arsenal/tasks/_history/`, it falls back to fetching from the default
branch and dies at exit 128 with no output, because
`git symbolic-ref refs/remotes/origin/HEAD` is unset in this clone. Not a gate
failure — `make verify-gates` is the check that reads `_history/`, and it does
assert D-15 by name (proven by deleting the evidence: it fails `t-65ecce18`
specifically). Possible upstream report if it recurs.

**`open_task_pr.sh` was not used**, again: it cuts `arsenal/<id>-<slug>` off the
default branch and this surface only permits pushing the session's designated
branch. The archive, the `Closes #93` in both places, and the PR were done by
hand to the same shape. **Do not skip the archive** — it is what makes merging
complete the task.

## CI is still out of runner minutes (re-confirmed on #102)

Job `pytest` on `d24c8ff`: `runner_id: 0`, `runner_name: ""`, 16:09:37 → 16:09:40
— three seconds, no runner ever assigned. All five jobs the same. `main`'s own
runs are identically red. It is not the diff; do not push speculative fixes.

All five gates were run locally and pass:

```bash
make lint && make test && make evidence && make verify-subtree && make verify-gates
```

`make test` 1103 passed / 1 skipped · `make evidence` no drift ·
`make verify-gates` 59 terminal tasks, 59 gates asserted, 0 without a fenced
block · `make verify-subtree` 0 diverging.

That the repo gate runs only because somebody asks is **D-22**, still open.

## Left open (carried forward)

- **The bundle upgrade above** — the highest-value item on this list.
- **A permissions edit the owner has to make**: `Bash(gh pr merge:*)`,
  `Bash(gh run list:*)`, `Bash(gh run view:*)` in `.claude/settings.json`.
  A session cannot widen its own permissions.
- **Turn off MCP connectors this repo never uses.** Still ~12.1k tokens of
  GitHub + remote-session tool schemas resident per turn; most are never called.
- **`tools/profile_guard.sh` matches a candidate path mentioned in *prose***,
  not only one being opened. Not seeded yet.
- **D-12 (`t-e1ca8374`, #83) still waits on the owner.** Resolution B exists
  since arsenal v0.33.0 (`gate: unmeasured`).
- **Steps 5, 6, 10, 11, 12 are still `not_implemented`**, and steps 8 and 9
  still certify over unbuilt gates until D-21 lands.
