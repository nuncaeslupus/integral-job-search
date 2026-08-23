# Session handover — 2026-08-23 (second session of the day)

## What merged

Three tasks, all built in parallel by workers and all merged after review:

| PR | Task | Gate | Merged as |
|---|---|---|---|
| #130 | T54 connector exchange | `unconsented_contributions == 0` | `c93f4be` |
| #128 | T47 mock interview | `mock_interview_character_breaks == 0` | `269501e` |
| #129 | T46 send boundary | `unapproved_episode_disclosures == 0` | `8057d06` |

`main` is green: `make host-gate` passes, `evidence: no drift`,
`verify-gates: 77 terminal task(s); 77 gate(s) asserted, 0 carry no fenced gate block`.
Issues 68/69/70 closed, task files archived, all claim refs pruned (0 remain).

Board after: 95 tasks — 3 open, 0 claimed, 1 done, 1 cancelled, 14 blocked, 76 merged.

## The thing worth carrying forward

All three PRs passed the full local gate on their first submission and **all three
were wrong**. 25 confirmed defects were found by an adversarial review pass run
after the gate was green, plus 6 by CodeRabbit. The repo's gate discipline catches
a broken implementation; it says nothing about a measurement that was never able
to fail.

One pattern accounted for a third of the findings, and it will recur:

> **The thing that decides the scope of a check must be inside the check.**

Three separate instances, in three unrelated modules:
- the `closing` turn bounded the transcript scan and was itself unscanned, so one
  planted `closing` at index 1 blinded the whole file;
- the `announcement` turn set the scan's start index and was itself unscanned, so
  a candidate-authored announcement passed and was never held to the in-character
  rules;
- the package name anchored the containment check and was itself unvalidated, so
  an escaped join became its own happy root (arbitrary write outside
  `$INTEGRAL_HOME` from an unauthenticated manifest).

A second pattern, equally worth naming: **a check whose evidence the writer
authors is not a check.** T54's "reads no candidate data" compared the recorded
path list against the very rule that decided what went into it — always empty,
whatever the code did. The fix was an independent witness that reads the profile
directory and searches the output, consulting nothing the writer reported.

Third: **a harness that constructs both sides of its own equality certifies
nothing.** T46's `measure()` derived the documents and the approvals from one
tuple in one call, so 8 of 9 mutations — including deleting the approval check
outright — left the committed evidence byte-identical. Fixed with 13 scenarios
that are defects on purpose, and a floor so they cannot quietly stop running.

**Recommendation for the next session:** when a task's gate is a `== 0` / `== 1.0`
structural claim, run a mutation pass before opening the PR. Strip each guard in
turn and confirm the gate goes red. Every worker here did that *after* review and
it took one round; doing it first would have saved three.

## Stated ceilings, deliberately not built

- T47: a maintainer editing one of the seven probe strings into coaching cannot be
  caught by any measurement (writer and reader then agree). Defence is a pinned
  finite vocabulary + a test, so it is a deliberate act, not a slip. Said plainly
  in the module docstring and PR body.
- T46: shingle matching beats punctuation/spacing/case/truncation, not a genuine
  paraphrase. Upgrade path noted: embedding comparison. Reformatted dates still
  slip past the personal-detail scan; upgrade path is a per-field parser.
- T46: `confirms` proves *which* payload was named, never *who* named it. Said in
  the docstring rather than hidden behind the word "approval".
- T54: `candidate_data_in_output` is substring matching, so a leak that
  *transforms* text escapes it. It is the independent witness, not the guarantee;
  the guarantee remains `_read_bundle`'s single root.
- T54: the sources repository (`nuncaeslupus/integral-connectors`) **does not
  exist**. Everything runs against `tests/fixtures/exchange/manifest.json`; the
  fork/branch/PR is assembled into an outbox command and never executed.
- T47: no production caller. Nothing in `.claude/skills/step-12-interview-log/` or
  `step_runtime` reaches `Rehearsal`; the 96 transcripts are a fixture measuring a
  fixture. Wiring it is unowned work.

## Environment notes

- **`gh` works on this surface.** `github_channel.sh --detect` prints `gh` and auth
  is live. `CLAUDE.md`'s "This surface has no scriptable GitHub channel" section is
  stale for a local session and should be scoped to the cloud surface or removed —
  three independent workers hit it and worked around it. **Unowned.**
- GitHub Actions still out of runner minutes; `MERGEABLE/UNSTABLE` on every PR is
  that, not the diff.
- Parallel branches all touch `status/evidence/T55.json` (`files_scanned`) and
  `D12.json` (`evidence_gates_read`), so every branch after the first merge needs a
  rebase + `make evidence` + amend. Budget for it when fanning out.

## Open, and what is actually next

3 open tasks; **all three need live egress to job boards** and cannot be done by a
cloud or sandboxed session:
- T25 (`lo-1af2`) — broaden the corpus to ≥6 job families, ≥15 ads each
- T12 (`lo-277b`) — one live portal connector against recorded fixtures
- T9 (`lo-b422`) — reaction elicitation from live stimuli

**T25 is the bottleneck for the whole board.** The extractor score (T56), the
negation score (T59), the ontology hit rate (T57) and the dimension model (T26)
are all blocked behind it, and two step gates are sitting at `unmeasured` because
of it. It is a human afternoon with a browser, not an engineering task.

## Standing warning nobody owns

`query_status` reports `mixed-priority-convention` every session: 16 tasks use the
size scale (10/5/1/0), 2 use 70/60. Every value above 10 outranks every sized task
regardless of intent — and one of the two is T25, which is genuinely the most
important thing left. Flagged to the user twice now; changing selection order is
the user's call, not an agent's.
