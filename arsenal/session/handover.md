# Session handover — 2026-08-24, two sourcing tasks in parallel, and a merge policy that now blocks

A worker session on the laptop. Three PRs open, **none merged** — see the next
section, which is the only thing that needs a decision.

## Start here — the merge policy was changed and nothing is agent-mergeable

The owner set `merge-policy = "after-ci-and-review"` (PR **#178**). Runners have
**not** returned: every job on every head still dies in 2–5s with no runner
assigned, which is the documented outage signature, not a signal about any diff.

`claude-arsenal/references/github-automation.md` is explicit about this exact
combination — *"Absent is not green. […] `after-ci` and `after-ci-and-review` are
unsatisfied, and stay that way for as long as the outage lasts. […] that state is
precisely why `after-review` exists."* So the three open PRs can be taken to
review-clean and no further; a human merges, or the policy goes back to
`after-review` until CI reports again. **Do not decide at merge time that today
the gate did not mean anything** — that is the failure the reference names.

The config comment records the state it was set in, so this is not lost.

## Open PRs

| PR | What | Gate, measured |
|---|---|---|
| #178 | `merge-policy` → `after-ci-and-review` | — (config) |
| #179 | **T62** — exhaustion as a measurement | `exhaustion_triggers_without_a_reason = 0` |
| #180 | **T61** — the §1 amendment across D-3's three documents | `spec_consistency_violations = 0` |

Both task PRs were verified independently of their worker's report: gate re-run in
the worktree, `Closes #<issue>` confirmed in body *and* commit, `gate` block
untouched, T55 refresh present as a second commit. `make host-gate` green on both.

## The queue is blocked on those merges

T63–T68 all chain off T62; T61 unblocks nothing by itself. **T69 is `[HUMAN]`**
(`requires: [surface:human]`) and its prerequisite is the exhaustion signal having
been watched on a real cycle — a dep cannot express that. Do not remove `requires`
to unblock the queue.

So there is no dispatchable work until #179 merges. Board at session end:
107 tasks — open 6, claimed 2, done 1, cancelled 2, blocked 7, merged 91.

## Two findings from this session

**`init.py` downgraded the bundle, 2.4.2 → 2.4.0, printing "Upgrading".** It
reverted `AGENTS.md`, `gate_run.sh`, `evidence-gates.md`, `create_reader.py` and
`issue_import.py` — undoing #162's pickup of the upstream placeholder-gate fix
that T60–T69 depend on. Caught and reverted before any work was done on it.
**Upstream v2.4.3 fixes exactly this** (`fix(core): init refreshes forward only,
and says so when it cannot`, #221): versions are compared before anything is
written, the direction is printed even under `--silent`, and going backward needs
`--allow-downgrade`. The tag is fetched locally but **not merged** — do that when
no workers are live, since the subtree merge writes history into the main tree.

**`make evidence` compares the working tree against the index, not HEAD.** Both
workers hit it independently: with new or edited evidence files uncommitted, it
reports drift until `git add status/evidence`. Staging, not committing — the
uncommitted-edits workflow `open_task_pr.sh` requires still holds. Worth folding
into CLAUDE.md if it recurs a third time.

Also noted, smaller: editing `status/spec-v2-steps.md` obliges `make reader-steps`,
because `docs/spec-v2-steps/{spec-reader.html,spec-annotated.md}` are generated
but committed and a test enforces no diff. Two large generated files ride along.

## Answered this session, so nobody re-derives it

The five `merge-policy` values are already documented, and were before v2.4.3 —
`claude-arsenal/references/github-automation.md` lines 54–58, byte-identical in the
new tag. `always` · `after-ci` (every required check **reported** and green) ·
`after-review` (a review landed and every comment fixed or answered; CI not
consulted) · `after-ci-and-review` (both) · `never` (a human merges).
