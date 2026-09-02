# Session handover

**Written 2026-09-02, ~17:40 UTC.** Board: **126 merged of 147**. Six PRs open, every
one CI-green, **none merged** — and the reason is the single most important thing on
this page.

## The reviewer is the bottleneck, and its green signals lie

`merge-policy` is `after-ci-and-review` (T103, #304). CI is mechanically checked;
**the review half has no reader**. A session decides by looking, and every signal it
would naturally look at reads as success over an unreviewed head. Four variants
measured today, all filed on **#313**:

1. `CodeRabbit  pass  Review skipped: draft pull request`
2. `CodeRabbit  pass  Review rate limited`
3. `CodeRabbit  pass  Review completed` — on a **superseded** commit
4. `@coderabbitai review` → `✅ Action performed — Review finished`, **producing no
   review of the head**

(4) is the dangerous one: it is the *repair* path failing. Its own note says the
command "is applicable only when automatic reviews are paused" — and a review that
**bounced off the rate limit** was never paused. So the careful sequence (request,
wait for the acknowledgement, merge) returns success over unreviewed code. Use
`@coderabbitai full review`, not `@coderabbitai review`.

**Exactly one signal has survived all four.** Check this and nothing else:

```bash
R=nuncaeslupus/integral-job-search
h=$(gh pr view $N --json headRefOid --jq '.headRefOid[0:7]')
gh api repos/$R/pulls/$N/reviews \
  --jq "[.[]|select(.user.login==\"coderabbitai[bot]\")|select(.commit_id[0:7]==\"$h\")]|length"
```

Zero means not reviewed, whatever the checks say. **All six PRs answer zero right now.**

Also: a review's **inline-comment count is not a proxy for "nothing found"**. #295's
review reported zero inline comments and carried a real defect, posted as an *outside
diff range* comment in the review body. Read the body.

### The quota, measured

Plan **Team**, profile **CHILL**, **8 included reviews per window**. Spent by 09:36,
partially refilled ~15:29, spent again by 16:00. **Every push queues a re-review**, so
N open PRs × M fix rounds burn N×M against a fixed window, and #288's refresh-main
churn multiplies it. Do not open a seventh PR while six wait — it deepens the queue
without increasing throughput. The user's standing instruction:

> "If CodeRabbit is unavailable, wait for it's limits to restore"

Silence is not approval. Do not merge past it.

## Open PRs — what each waits on

| PR | task | head | CI | waits on |
|---|---|---|---|---|
| #264 | getmanfred connector | `02ec73a` | CLEAN | review (request bounced 16:00) |
| #295 | T89 GET-only | `fb6844b` | CLEAN | review of the fix head |
| #297 | T104 stale-PR gate | `0fcf2ff` | CLEAN | review (`full review` bounced 16:14) |
| #305 | D-24 retraction | `5a60aaa` | CLEAN | review of the fix head |
| #307 | T98 corpus scope | `a4f6dfa` | CLEAN | review (request bounced 16:00) |
| #312 | T92 salary parser | `d1a2f0d` | CLEAN | review of round-2 fixes |

Every one has had its findings answered on the PR. Nothing is waiting on work.

## What landed today

Merged: T99 (#289), T101 (#291), T96 (#287), T83 (#286), T95 (#290), T93 (#292),
**T103 (#304)**, **#260** (four JSON connector packages).

Three **second-reader audits**, every one finding defects behind a green
`make host-gate`:

- **#297 (T104)** — 7 findings, 2 blocking. Floors unenforceable. CodeRabbit then found
  **write-before-check** one layer down, and `task_gate` had it too — with an existing
  test asserting the false claim was present.
- **#264 (getmanfred)** — 4 blockers. Probe byte-identical to fixture (T72's defect,
  with `T72.json` already recording `healthy, probed: true` on a comparison that could
  not fail). Now a genuine second read: `cmp` exits 1 at byte 432.
- **#305 (D-24)** — 8 fail-open inputs. Byte-equality join defeated by a full stop, a
  curly apostrophe, a doubled space, casing, NFC/NFD and paraphrase. `kind == "episode"`
  excluded `kind="statement"`, which is what the only production path writes.
- **#312 (T92)** — do-not-merge, 6 blocking fail-opens. Worst: `_period_of` documents
  *"the segment says two things; it has said nothing"* and the caller then treats that
  `None` as "no period" and infers year, so `6.000 € al mes, amb revisió anual` became
  `6000 EUR/year stated=True` — a €72k role shown as €6k, on ordinary CA/ES boilerplate.

## Two patterns to check first on any new gate

**The exit-3 fail-open.** `Makefile:58-70` maps exit 3 to `unmeasured (recorded)` and
**continues**; only `*)` fails. A module returning 3 on a floor breach does not fail
`make evidence`. Combined with a `record()` writing `<metric>_at_least: <floor>`
unconditionally, the committed file states a falsehood with zero drift. Found in
`task_gate` and `plan_v2` (fixed); still open in `naming._main` (**#309**). **Return 1.**

**Write-before-check.** `write_evidence` calling `record(measured)` *before* validating
floors, so a failing run leaves evidence claiming success.

**Fixing a fail-open can open a fail-closed hole one layer out.** T92 round 1 made
`Recovered.__post_init__` raise on an impossible band — correct — and `recover_all`
did not catch it, so one bad estimator ended the batch and discarded every recovery
already collected. Caught in round 2. CLAUDE.md records the same shape for T70: eight
of ten defects introduced by the session fixing the previous one.

## `status/plan.md` states things no gate reads — three instances

Filed, not fixed: **#308** (47 of 123 archived-merged tasks had unticked rows — fixed on
main, gate not built) and **#314** (the milestone rows still list **82 of 89** merged
labels; M1 and cross-cutting entirely, while the contract says merged tasks are not
listed). A third surfaced on #305: a task file's `deps: []` contradicting its own plan
row. Derive merged state from `arsenal/tasks/_history/*.md` (`status: merged`) — never
from the plan's own ticks, since a check reading the document it checks measures nothing.

Note `deps` takes task **ids** (`t-…`/`lo-…`), not plan labels — CodeRabbit suggested
`deps: [D-24, T46]`, which would have declared two dependencies no task file declares.

## Filed and unclaimed

**#313** (the review-half reader, four variants above), **#314** (milestone rows),
**#309** (`naming._main` exit 3), **#311** (`ticjob_es` probe byte-identical to its
fixture — the same defect #264 just fixed), #293 (T105), #294, #296, #298–#302, #306,
#308, #310. Plus **T106** (`t-6b3ce41f`, US tax rules — per-figure `citations` under
`probe_pay`'s intact refusal of `source: verified`) and **D-26** (`t-f03571d1`, ships
with #305; its purge must skip versions named in `applications/` or it destroys the only
copy of what was sent).

## Candidate track

Step 0's `.active.json` binding is **per session** — the next session must re-run
`write_active_handle(profiles_root(), 'ivan', session_id=<this session's id>)` before
anything under `profiles/` opens. Both Spanish reports are complete in the scratchpad
and **await owner review before anything goes out**. Not in the repo, and no candidate
PII may enter it.

## Worktrees

`../ijs-manfred-conn` stays while #264 is open. `tmp/refresh_pr.sh <worktree>` merges
main, auto-resolves `status/evidence/` conflicts by re-measuring, re-runs `make evidence`
and pushes — mechanical, not a judgement. Several `.claude/worktrees/agent-*` are stale
from merged PRs and can be pruned.
