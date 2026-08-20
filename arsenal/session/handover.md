# Session handover — 2026-08-20 (S10 settled, S11 built; a test session can now run)

## Read this first

**The tool can now be tested.** Steps 0–4 run, and the meta channel S11 exists to
carry notes about them is built and merged-ready in **PR #86** (`Closes #71`,
`Closes #63`). Start a session, type `[[…]]` when the protocol is wrong, and
end with the triage pass. The `test-mode` skill carries the protocol.

**D-12 (`t-e1ca8374`, #83) is still the one decision waiting on the owner.** It
was not touched this session. T15 still cannot reach terminal, and fifteen live
tasks still sit behind it. Nothing here changed that — S10/S11 were an
independent branch of the graph.

## State

| what | where |
|------|-------|
| PR #86 — S10 + S11 | **open**, closes #71 and #63 |
| S10 (`lo-5efb`, #71) | **resolved** — 13,000-char budget declared here; `requires: [surface:human]` dropped |
| S11 (`lo-5530`, #63) | **built** — marker decided (option 3), ledger outside every profile tree |
| D-12 (`t-e1ca8374`, #83) | **unchanged, still needs the owner** |
| PR #84 — T15 staged extraction | merged as `c9b0455` |
| Bundle | v0.30.0; `merge-policy = "after-review"` |

Merge any PR carrying a subtree pull **with a merge commit, never a squash**.

## What was decided, and how to reverse it

**S10 → the budget lives in this repository.** The owner's 2026-08-18 decision
("raise it") was never blocked; *where the raised number lives* was, because
upstream's `LISTING_BUDGET_CHARS` has no override and `vendor/` must not be
patched. So `jobsearch.skill_budget` declares **13,000**, and measures 12,138
across 33 skills with 862 spare.

The part worth carrying forward is not the number, it is the three properties
that keep a raised threshold from being a fitted one — because a cap tuned to
the measurement reports the same clean zero as a cap somebody chose:

1. `check_declaration` refuses a budget that is not a multiple of 1,000 or that
   leaves under 400 chars spare;
2. evidence records `budget_source`, and the committed file says `declared` —
   an `--budget` / `JOBSEARCH_LISTING_BUDGET_CHARS` reading is marked
   `override` and a test asserts the commit was not measured that way;
3. `overage_against_upstream_default` keeps "deliberately 4,138 above the 8,000
   default" visible rather than hidden by the raise.

To reverse: change `LISTING_BUDGET_CHARS` and re-run `make evidence`. Lowering
it below 12,138 makes the gate fail honestly, which is the point.
`claude-arsenal#143` stays open as a convenience — when it lands, the flag can
read the same declared value instead of the module owning it.

**`audit_library.py` is deliberately not S10's gate command.** It measures
against upstream's 8,000, which this repository has risen above on purpose, so
it reports a finding by design. It is still run by
`test_the_measurement_agrees_with_the_upstream_audit`, for the one thing it is
authoritative about: the total.

**S11 → marker option 3.** `[[note]]` silent, `[[! note]]` act now, no meta
parsing inside a paste. Two placements went one step stricter than the payload
asked for, and both are load-bearing:

- **the note ledger is outside every profile tree** —
  `<profiles root>/.test-mode/<session id>.jsonl`, not the candidate's
  `session/`. It cannot reach a derived file because it is not inside a
  candidate; it exists before identification does, so a step-0 note has
  somewhere real to go instead of an in-memory buffer a crash would empty; and
  the leading dot means `list_identities` already skips it;
- **the fiction mark is excluded by the reader, by default.**
  `Identity.fiction` is a field, and `list_identities` drops fiction unless
  `include_fiction=True` is asked for by name. Every existing reader stopped
  counting simulated candidates without being changed — the opposite of a flag
  each caller must remember to check.

## The defect shape worth remembering

Silent capture makes its own failures invisible **by construction**. A note
mis-parsed, eaten by the paste guard, or dropped before the review is
indistinguishable at runtime from no note having been made.

So the work was not the capture; it was the audit trail around it.
`unparsed_markers` counts what a guard declined, `unclosed_markers` counts a
`[[` that never closed, both print in the review, and `render_review` prints
even when empty — because "nothing was noted" and "something was noted and
lost" must not look the same.

The same discipline is in the gate. `probe_notes_reaching_evidence` does not
assert that the writer never calls `EvidenceLog.append`; it runs a whole
simulated session, writes real evidence rows alongside the notes, then sweeps
**every byte of every profile tree** for each note's text — and
`test_the_leak_probe_catches_a_leak_that_is_really_there` mutates a real leak
in to prove the sweep is not passing vacuously. A gate that restates a rule
agrees with prose the code has stopped following (D-11).

## Where the board stands

`plan_queue_task_drift == 0`; `verify-gates` asserts **55/55**; 1,052 tests
pass. Once #86 merges, S10 and S11 leave the queue and **nothing is blocked
behind them**.

Unblocked and autonomous-safe today: **T55** (`lo-9f72`, #49) and **T54**
(`lo-892b`, #70) — what `task_select` offers.

## For the next test session

What is still missing before a candidate reaches a ranked list is unchanged:

- **T18/T19** (#57/#58) — ordering and explanations, the part the candidate sees.
- **T12** (#51) — one live connector against recorded fixtures. `[LAPTOP]` +
  egress, so it is the owner's.
- Steps 5–6 (T9/T10) stay optional for a first pass — ranking degrades to
  unweighted rather than breaking.

**New dimensions come from here now.** T26's scope note records the owner's
decision that a dimension is coined when a live session turns one up. Test mode
is the channel that carries it: `[[the model has no name for this]]` at the
step where it was noticed, triaged at the end.

## Verified for the next session — 2026-08-20

Run on `claude/confident-johnson-ac4jvh` at `b11f7b0`:

| step | result |
|------|--------|
| `make lint` | ruff + strict mypy, 97 files, clean |
| `make test` | **1052 passed**, 1 skipped |
| `make evidence` | no drift |
| `make verify-subtree` | 0 diverging |
| `make verify-gates` | **55/55** |
| `plan_v2` | drift 0 |
| `gate_run.sh lo-5efb` / `lo-5530` | `gate: passed`, both |
| `validate.py .claude/skills/test-mode` | 0 fail, 1 warn (`--seed`, outside the argument canon; documented in the script) |

**GitHub Actions is still out of runner minutes.** Every job on #86 failed in
3–4 seconds with `runner_id: 0` and `runner_name: ""` — the signature
`CLAUDE.md` documents, which hits `main` as much as any branch. Do not read a
red CI here as a statement about the code, and do not push a fix for it.

Upstream issues open: **#143** (no listing-budget override — now a convenience,
not a blocker), **#168** (a gate has no "unmeasured" outcome), **#169**, **#170**,
**#171**.
