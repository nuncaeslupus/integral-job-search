# Session handover — 2026-08-20 (S10 settled, S11 built; a test session can now run)

## Read this first

**The tool can now be tested.** Steps 0–4 run, and the meta channel S11 exists
to carry notes about them is **merged** (PR #86, `3da8bd6`). Start a session,
type `[[…]]` when the protocol is wrong, and end with the triage pass. The
`test-mode` skill carries the protocol.

**Arsenal is at v0.33.0** (PR #87). That release lands `claude-arsenal#143`, so
`audit_library.py` now reads `arsenal/config.toml`'s `listing-budget` instead of
its hardcoded 8,000 — the auditor and `jobsearch.skill_budget` read the same key,
which is why S10 put the number in the settings file rather than in a constant.

**D-12 (`t-e1ca8374`, #83) is still the one decision waiting on the owner — but
the choice has changed.** S10/S11 were an independent branch of the graph and
did not touch it. The **arsenal upgrade did**: `claude-arsenal#168` landed in
v0.33.0, so **resolution B now exists**.

`gate_evidence.py` takes an optional `status-key` — a dotted path to a string
reading `unmeasured` — and exits **3**, which `gate_run.sh` prints as
`gate: unmeasured` rather than collapsing into a failure. That is exactly the
third outcome D-2 requires and the gate layer lacked: a score, a failure, or
"the check ran and found the measurement cannot honestly be made".

So T15 could declare `extraction_status` as its `status-key` and stop being
stuck, without splitting its acceptance (resolution A) and without lowering the
floor or scoring cue-derived gold (which D-2 forbids and which already happened
once). **A is still available and still cheaper. B is no longer blocked.** The
decision is the owner's; what changed is that it is now a real choice between
two live options rather than one option and an upstream wait.

## State

| what | where |
|------|-------|
| PR #86 — S10 + S11 | **merged** `3da8bd6`, closed #71 and #63 |
| PR #87 — arsenal v0.33.0 | **open** — merge with a merge commit, never a squash |
| S10 (`lo-5efb`, #71) | **resolved** — 13,000-char budget declared here; `requires: [surface:human]` dropped |
| S11 (`lo-5530`, #63) | **built** — marker decided (option 3), ledger outside every profile tree |
| D-12 (`t-e1ca8374`, #83) | **unchanged, still needs the owner** |
| PR #84 — T15 staged extraction | merged as `c9b0455` |
| Bundle | **v0.33.0**; `merge-policy = "after-review"`, `queue-automation = true` |

Merge any PR carrying a subtree pull **with a merge commit, never a squash**.

## What was decided, and how to reverse it

**S10 → the budget lives in `arsenal/config.toml`.** The owner's 2026-08-18
decision ("raise it") was never blocked; *where the raised number lives* was.
Arsenal already defined the `listing-budget` key for exactly this, so
**13,000** goes there and `jobsearch.skill_budget` reads it — no Python
constant beside it, because two copies of a threshold are two thresholds.
Measured: 12,138 across 33 skills, 862 spare.

The part worth carrying forward is not the number, it is the three properties
that keep a raised threshold from being a fitted one — because a cap tuned to
the measurement reports the same clean zero as a cap somebody chose:

1. `check_declaration` refuses a budget that is not a multiple of 1,000 or that
   leaves under 400 chars spare;
2. evidence records `budget_source`, and the committed file says `config` —
   `--budget` / `JOBSEARCH_LISTING_BUDGET_CHARS` mark a reading `override`, and
   a missing settings file marks it `fallback` (at upstream's 8,000, never our
   number, so an absent config cannot be mistaken for a present one). Only
   `config` satisfies the gate;
3. `overage_against_upstream_default` keeps "deliberately 4,138 above the 8,000
   default" visible rather than hidden by the raise.

To reverse: change `listing-budget` in `arsenal/config.toml` and re-run
`make evidence`. Lowering it below 12,138 makes the gate fail honestly, which is
the point. **`claude-arsenal#143` has since landed in v0.33.0**, so the auditor
reads the same key — the prediction the placement was made on, confirmed within
the hour.

**`audit_library.py` is still not S10's gate command**, but no longer because
it disagrees: since v0.33.0 it reads the same key and reports `0 fail`. It is not
the gate because it does not write evidence and does not check that the budget
was *declared* rather than fitted. It is run by
`test_the_measurement_agrees_with_the_upstream_audit`, for the one thing it is
authoritative about: the total.

Its remaining warning — "within 10% of 13000" — is the budget working. 862 chars
spare, revisit at roughly three more skills. **Do not silence it by raising the
number**; that is the fitted-threshold move the declaration checks exist to catch.

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

`plan_queue_task_drift == 0`; `verify-gates` asserts **55/55**; 1,069 tests
pass. S10 and S11 are closed and **nothing is blocked behind them**.

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

Run on `claude/confident-johnson-ac4jvh` after the v0.33.0 upgrade:

| step | result |
|------|--------|
| `make lint` | ruff + strict mypy, 97 files, clean |
| `make test` | **1069 passed**, 1 skipped |
| `make evidence` | no drift |
| `make verify-subtree` | 26 assets, 0 diverging |
| `check_update.sh --check-only` | `v0.33.0 — current with the newest tag` |
| `audit_library.py` | library **0 fail** (reads `listing-budget` since #143) |
| `make verify-gates` | **55/55** |
| `plan_v2` | drift 0 |
| `gate_run.sh lo-5efb` / `lo-5530` | `gate: passed`, both |
| `validate.py .claude/skills/test-mode` | 0 fail, 1 warn (`--seed`, outside the argument canon; documented in the script) |

**GitHub Actions is still out of runner minutes.** Every job on #86 failed in
3–4 seconds with `runner_id: 0` and `runner_name: ""` — the signature
`CLAUDE.md` documents, which hits `main` as much as any branch. Do not read a
red CI here as a statement about the code, and do not push a fix for it.

**Two upgrade consequences worth knowing about, both already handled:**
`create_reader.py` changed, so both generated spec readers went stale —
`make reader` fixes it and `test_regenerating_the_reader_produces_no_diff`
catches it. And the bundle grew 22 → 26 assets, moving S9's evidence; its gate
is unchanged.

**`.github/workflows/arsenal-queue.yml` is new**, installed by `init.py` and
recorded as `queue-automation = true`. It closes queue holes a session cannot:
a merged task PR whose `Closes` did not fire, a claim held by a crashed session,
a task file merged with no issue handle. It cannot run until runner minutes
return. Deleting the file is the opt-out.

Upstream issues open: **#168** (a gate has no "unmeasured" outcome), **#169**
(`handle_sync.py` proposes handles for `_history` work), **#170**
(`check_update.sh` upgrades as a side effect of reporting), **#171**.
**#143 is closed** — v0.33.0.
