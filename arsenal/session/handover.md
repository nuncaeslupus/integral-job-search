# Session handover — 2026-08-27 ~13:00 UTC, orchestrator, fourth fleet round

Board: **108 gates**, 124 tasks. `main` at `ff059aa`. **Eleven PRs merged across this run.**

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
| [#221](https://github.com/nuncaeslupus/integral-job-search/pull/221) | T72 connector health | merged `88dd3dc` (gated on `7a63627`). **Closes nothing, and its gate did not pass** — #203 stays open, the task file is not archived, and `python -m integral.connector_health` exits 3 with `gate_status: unmeasured`. Finishing it needs a probe capture on the laptop. Squash message deliberately carries no closing keyword. |
| [#227](https://github.com/nuncaeslupus/integral-job-search/pull/227) | T70 robots matching | merged `7cb26bc` (gated on `af1e57b`), #209 closed. Four fail-opens fixed; the round-2 audit's 32 accepted cases committed as fixtures, `robots_verdicts_evaluated` 24 → 56. |
| [#235](https://github.com/nuncaeslupus/integral-job-search/pull/235) | T76 eligibility gate | merged `ff059aa` (gated on `4fcce80`), #218 closed. Unblocks five tasks. |

## In flight

| task | issue | worker | notes |
|---|---|---|---|
| T77 `t-4cfbcbd1` | #206 | `session_01V5xWu1C4WWtyCU5wLc2Mao` | Every disqualification carries the advert's own sentence. |
| T78 `t-4921255b` | #205 | `session_014x1rgBHS4NhXF7te4RLMWh` | `language_requirement` as a hard field the ranker never reads. |

**These two edit the same two files** — `src/integral/eligibility.py` and
`tests/test_eligibility.py`. Lanes were scoped in each dispatch (T77: the verdict record and
the quote guarantee; T78: the hard field and the ranker boundary), and both were told to
append tests rather than interleave. Expect to resolve one merge by hand; do not expect the
workers to have seen each other.

## Two follow-ups filed rather than lost

Both are `arsenal:queue` issues, to be imported as tasks by `issue_import.py`.

- [#236](https://github.com/nuncaeslupus/integral-job-search/issues/236) — T70 audit case 22: does a rule's product token match as a **prefix** of a longer crawler token? Deliberately not committed as a fixture, because recording the implementation's own answer as the expectation is the circularity the audit exists to break. **Needs a surface whose egress is not blocked** — every host serving RFC 9309 is refused here by the proxy, for the auditor and the orchestrator alike. That means the laptop.
- [#237](https://github.com/nuncaeslupus/integral-job-search/issues/237) — eligibility target vocabulary. A candidate declaring `DE` is excluded by "must hold German citizenship"; the code cannot tell that from `ES` against the same advert. **Must land before T77/T78/T79 wire the gate into ranking** — until then nothing imports `eligibility`, so the false FAIL reaches no candidate. Owner's steer: a *scoped* ES/EN/CA table, unknown terms resolving to FLAG, and **no clearance taxonomy**.

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

## Standing environment facts

- **CI is red repo-wide and it is not any diff**: Actions is out of runner minutes, jobs die in
  3–5 seconds with `runner_id: 0`, on `main` too. Never gate a merge on it.
- The **GitHub MCP server dropped once mid-run** (`400: invalid session`) and came back. Plain
  `git` kept working throughout. If it drops again: fetch, gate and push still work; merging,
  commenting and opening PRs do not.
- Spawned sessions have **no `mcp__*` tools** and REST 403s. Workers get their task id, issue
  number and lane from the dispatch, and stop after pushing.
- `open_task_pr.sh` gates *then* archives the task file, so `T55.files_scanned` ships one
  behind. A second commit on the branch it leaves you on fixes it; the squash folds it in.
