# Session handover — 2026-08-27 ~15:20 UTC, orchestrator, fourth fleet round

Board: **110 gates**, 124 tasks. `main` at `768cb9b`. **Thirteen PRs merged across this run.**

**No worker is in flight and no branch is unmerged.** Every `arsenal-worker` session is idle
with its branch merged; `git ls-remote origin 'refs/heads/arsenal/t-*'` returns nothing. The
next round starts from `task_select.py`, not from anything left running.

On each, the orchestrator ran `make host-gate` itself and saw exit 0 — on the **branch head**
immediately before merging, never on a worker's word. The SHAs in the table below are the
*squash* commits on `main`; they carry the same tree, but no gate ran against them by that
name, so do not go looking for one.

**Exit 0 from `host-gate` is not the same as a task's own gate passing.** T72 is the case that
proves it: `make evidence` records an exit-3 module as `unmeasured (recorded)` and carries on,
so the run is green while `silent_connector_failures` remains unscored. That is the intended
behaviour and the entire point of #221 — a gate that refuses to score itself.

## Merged since the last handover

| PR | task | outcome |
|---|---|---|
| [#221](https://github.com/nuncaeslupus/integral-job-search/pull/221) | T72 connector health | merged `88dd3dc` (gated on `7a63627`). **Closes nothing, and its gate did not pass** — #203 stays open, the task file is not archived, and `python -m integral.connector_health` exits 3 with `gate_status: unmeasured`. Finishing it needs a probe capture on the laptop. Squash message deliberately carried no closing keyword — **and that is not a supported way to hold a task open.** `.github/workflows/arsenal-queue.yml`'s `pr-closed` job fires on any merged `arsenal/` PR and runs `queue_hooks.py pr-closed`, which closes the issue and archives the task whatever the squash message says. It did not fire here only because Actions has no runners. When minutes return, the same technique will not work: hold a task open by **not merging it**, or by parking the task file. |
| [#227](https://github.com/nuncaeslupus/integral-job-search/pull/227) | T70 robots matching | merged `7cb26bc` (gated on `af1e57b`), #209 closed. Four fail-opens fixed; the round-2 audit's 32 accepted cases committed as fixtures, `robots_verdicts_evaluated` 24 → 56. |
| [#235](https://github.com/nuncaeslupus/integral-job-search/pull/235) | T76 eligibility gate | merged `ff059aa` (gated on `4fcce80`), #218 closed. Unblocks five tasks. |
| [#239](https://github.com/nuncaeslupus/integral-job-search/pull/239) | T77 quoted disqualifications | merged `d54d6de`, #206 closed. Every disqualification carries a byte-for-byte advert span; `_require_advert_span` raises `QuoteProvenanceError` on anything else. |
| [#240](https://github.com/nuncaeslupus/integral-job-search/pull/240) | T78 language_requirement | merged `768cb9b` (gated on `4885248`), #205 closed. **Five defects across four review rounds, four of them in the gate's own audit machinery rather than in the feature.** See below. |

## In flight

**Nothing.** T77 and T78 both merged; see the table above.

## Two follow-ups filed rather than lost

Both are `arsenal:queue` issues, to be imported as tasks by `issue_import.py`.

- [#236](https://github.com/nuncaeslupus/integral-job-search/issues/236) — T70 audit case 22: does a rule's product token match as a **prefix** of a longer crawler token? Deliberately not committed as a fixture, because recording the implementation's own answer as the expectation is the circularity the audit exists to break. **Needs a surface whose egress is not blocked** — every host serving RFC 9309 is refused here by the proxy, for the auditor and the orchestrator alike. That means the laptop.
- [#237](https://github.com/nuncaeslupus/integral-job-search/issues/237) — eligibility target vocabulary. A candidate declaring `DE` is excluded by "must hold German citizenship"; the code cannot tell that from `ES` against the same advert. **T77 and T78 have now merged and this is still true** — verified at handover time, nothing in `src/` or `tools/` imports `integral.eligibility`. **T79 is the one that changes that**, so #237 must land before T79 — until then nothing imports `eligibility`, so the false FAIL reaches no candidate. Owner's steer: a *scoped* ES/EN/CA table, unknown terms resolving to FLAG, and **no clearance taxonomy**.

## What this round taught, and what to keep doing

**The durable-output dispatch works, and the transcript-output one destroys work.** The first
T70 audit derived 19 cases, reported them in its final chat message, disconnected, and 17 were
lost. Round 2 was told to write its cases to a file and push a branch; it did, and 32 of them
are now fixtures. Any commissioned report gets pushed, never narrated.

**An audit that reports before reading the code is worth the extra step.** Round 2's cases were
committed in `21ad1af` *before* `robots.py` was opened, and one modelling error it later found
in its own case was corrected in a separate commit citing the section — not because the code
disagreed. That ordering is what makes the 32 accepted cases mean anything.

**Re-read the thread list at the moment of merging.** Not once beforehand. This was learned the
hard way earlier in the run and has now paid off three times.

**A green gate is necessary and never sufficient** — again. T76 arrived with 20 passing tests,
a gate at exit 0, and a live fail-open: a stated TS/SCI bar returned PASS because "not
necessary" bled in from the previous sentence. Both of its Major findings were reproduced
before being touched, and both are now probes as well as fixes.

**Four of T78's five defects were in the gate's own audit machinery, not in the feature** — and
two of those four were the same shape: *an audit that enumerates the syntax you thought of
first, rather than the routes to the thing.* The import audit collected `ast.ImportFrom.module`
and missed `from integral import rank`. The boundary scan walked `ast.Attribute` and missed
`getattr(offer, "language_requirement")`. Both reported clean over exactly the case they
existed to catch, and both were behind a green gate.

The rule that falls out, for the next static audit written here: **enumerate the routes, then
prove each one fires by injection.** Every fix on that PR was reproduced before being made and
each new test shown to fail against the code it replaced — which is the only reason there is
any confidence the fifth round found the last of them rather than the last one anybody looked
for.

Where a route cannot be resolved statically — `getattr(offer, key)` with a computed key — the
answer is `unmeasured`, not `0`. A zero obtained by not looking is the empty-input failure
wearing a full denominator, and this repo already has the vocabulary for it (exit 3, D-12).

**Four rounds of review is a signal, and it was not a signal to stop.** Round 4's finding was
the most serious of the five. Counts fell 3 → 1 → 1 → 1 with no reshaped duplicates, which is
convergence; a reviewer still landing real fail-opens on round four is not the same thing as a
reviewer churning.

## Standing environment facts

- **CI is red repo-wide and it is not any diff** — *while the signature below holds, and not a
  moment longer.* Actions is out of runner minutes: jobs die in seconds with `runner_id: 0` and
  an empty `runner_name`, meaning no runner was ever assigned, on `main` as much as any branch.
  **Confirm that signature on the actual job record before discounting a red check**; a red CI
  without it is a real failure and gates the merge. Two live costs of having written this
  unconditionally the first time: it reads as a permanent CI bypass, and a dead Actions is *also*
  a dead `arsenal-queue.yml` — every queue transition in that file (`pr-closed`, `sync-handles`,
  `sweep-claims`, `keyword-guard`) is silently not running, which is how T72 above came to look
  like a supported exception.
- The **GitHub MCP server dropped once mid-run** (`400: invalid session`) and came back. Plain
  `git` kept working throughout. If it drops again: fetch, gate and push still work; merging,
  commenting and opening PRs do not.
- Spawned sessions have **no `mcp__*` tools** and REST 403s. Workers get their task id, issue
  number and lane from the dispatch, and stop after pushing.
- `open_task_pr.sh` gates *then* archives the task file, so `T55.files_scanned` ships one
  behind. A second commit on the branch it leaves you on fixes it; the squash folds it in.
