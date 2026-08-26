# Session handover — 2026-08-26 ~15:20 UTC, orchestrator, third fleet round

Board: **106 gates**, 124 tasks. `main` at `2a3b8dd`. **Six PRs merged today**, every one
gate-verified by the orchestrator on that exact commit, never on a worker's word.

| PR | task | outcome |
|---|---|---|
| [#226](https://github.com/nuncaeslupus/integral-job-search/pull/226) | T81 keyword coverage | merged `0033160`, #210 closed |
| [#228](https://github.com/nuncaeslupus/integral-job-search/pull/228) | T85 evidence reach | merged `7adf423`, #217 closed |
| [#225](https://github.com/nuncaeslupus/integral-job-search/pull/225) | claude-arsenal v2.4.22 | merged `928e957`, one thread left open by decision |
| [#229](https://github.com/nuncaeslupus/integral-job-search/pull/229) | adversarial-fixture rule | merged `9d15d76` |
| [#230](https://github.com/nuncaeslupus/integral-job-search/pull/230) | T74 liveness identity | merged `2241a91`, #213 closed |
| [#233](https://github.com/nuncaeslupus/integral-job-search/pull/233) | T74 follow-up fix | merged `ddcdc4e` |
| [#231](https://github.com/nuncaeslupus/integral-job-search/pull/231) | T75 dedup | merged `c77ba8f`, #211 closed |
| [#232](https://github.com/nuncaeslupus/integral-job-search/pull/232) | T82 status vocabulary | merged `2a3b8dd`, #214 closed |

## Open, and both waiting only on the owner

| PR | state |
|---|---|
| [#221](https://github.com/nuncaeslupus/integral-job-search/pull/221) T72 | `62996f5`. **HELD by the owner.** Zero open threads, Merge Risk Minimal, `make host-gate` exit 0. Six verified defects fixed today. Squash message must omit `Closes #203`. |
| [#227](https://github.com/nuncaeslupus/integral-job-search/pull/227) T70 | `fac3cac`. Four fail-opens fixed, audit reported. **Blocked by the fixture-report gap below**, not by a known defect. |

## The finding of the day: a check can be correct by coincidence

Fourteen real defects were fixed across these PRs, and the ones that mattered shared a
shape — **the gate was green because the fixtures happened not to exercise the broken
case**, not because the code was right.

- **T74**: `title_in_body` searched the whole document, so any listings page *mentioning*
  the vacancy read as the advert. The fixtures passed only because their listings page
  happens not to contain the word `CISO`. Now matched against `<title>`/`<h1>` only.
- **T70**: `Disallow:` with an empty value was stored as the pattern `""`, which matches
  every path — so the "allow all" idiom made a whole site unfetchable. Every existing
  fixture asserted a *refusal* was correct, so none could see it. **Fail-closed defects
  are invisible to a fixture set built around fail-open.**
- **T82**: guarding the *read* of a corrupt record left the *write* overwriting it. The
  guarantee was unmet while the code claimed it was met.

The rule that follows, now in `CLAUDE.md`: **a test that checks the function behaves is
not a test that checks the guarantee holds.** Write the second.

## Decisions the owner made today

1. **#227**: fix the three fail-opens, then a separate session audits from the spec. Done.
2. **#225**: merge over the parked thread — the finding is upstream's (`claude-arsenal#253`).
3. **Fleet: three** — T75, T74, T82. All three merged.
4. **Adopt the adversarial-fixture rule**, strengthened after review caught that its first
   wording was satisfiable without a single independent case ever running.

## Still owed by the owner

1. **The `.claude/settings.json` paste** — here *and* in `nuncaeslupus/opos`. A session is
   hard-blocked from applying it, correctly.
2. **#221's hold.**
3. **#227's fixture gap** (below): re-run the audit with durable output, or accept the two
   failures as its deliverable.

## The process error worth not repeating

The T70 audit derived **19 spec cases; 17 passed, 2 failed**. Only the 2 are committed.
The other 17 lived solely in that session's final message, and the session is an
unreachable cloud session — `ListAgents` shows nothing, so the report is gone.

**The dispatch asked the auditor to report in its final message rather than to write its
cases to a file and push a branch.** A report that lives only in a transcript is exactly
the "evidence that cannot be re-run" this repository refuses everywhere else, built into
the process created to fix that. Fix the dispatch prompt before the next audit.

## Mechanics worth keeping

- **Re-read PR threads at the moment of merging, not once beforehand.** #230 was merged
  over a Major posted ninety seconds earlier; the next PR, #232, had two findings arrive
  three minutes before its merge and the re-read caught them.
- A `409 Head branch is out of date` can appear while `git rev-list` says **0 behind** —
  GitHub had not indexed the push. Verify before assuming a conflict.
- `git add -A` during conflict resolution swept a source fix into a commit labelled
  `chore: regenerate evidence`. Squash-merge makes the landed record right; check what a
  conflict-resolution commit actually contains.
- Three `create_branch` calls in one message all succeed. The one-per-message limit is
  specific to `create_session`.

## Unchanged and still true

CI is red repository-wide: `runner_id: 0`, no runner assigned, ~3s per job, red on `main`.
Never gate merging on it.

Commit before gating (`make evidence` compares committed evidence). Never put an
angle-bracket placeholder in a GitHub body. Vendored `claude-arsenal/` and
`.claude/skills/` are refreshed by `/init`, never hand-edited.

All three task files this round named their denominator two ways — prose
`<metric>_evaluated`, dated section a domain name. **The template that generates those
sections is producing the mismatch**; workers were told to write both keys.

Skip `lo-4b17` (T59), `lo-6f53` (T56), `lo-7c14` (T57). Next unblocked: `lo-25b1` (T15),
`t-e6f1dc24` (T76).
