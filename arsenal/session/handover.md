# Session handover — 2026-08-26 ~11:45 UTC, orchestrator, third fleet round

Board: **104 gates**, 124 tasks. `main` at `928e957`. Three of five PRs merged today.
Every merge was gate-verified by the orchestrator on that exact commit, never on a
worker's word.

| PR | task | state |
|---|---|---|
| [#226](https://github.com/nuncaeslupus/integral-job-search/pull/226) | T81 keyword coverage | **merged** `0033160`; #210 auto-closed |
| [#228](https://github.com/nuncaeslupus/integral-job-search/pull/228) | T85 evidence reach | **merged** `7adf423`; #217 auto-closed |
| [#225](https://github.com/nuncaeslupus/integral-job-search/pull/225) | claude-arsenal v2.4.22 | **merged** `928e957`, one thread deliberately left open |
| [#221](https://github.com/nuncaeslupus/integral-job-search/pull/221) | T72 connector health | gate `unmeasured` by decision; recipe conflict resolved; `60ee9f1` gates clean. **Ready except for the owner's hold.** Squash message must omit `Closes #203`. |
| [#227](https://github.com/nuncaeslupus/integral-job-search/pull/227) | T70 robots | three fail-opens fixed, `da8a26a` gates clean. Held for the independent fixture audit. |

## In flight — four sessions dispatched, none reported yet

| session | doing |
|---|---|
| `session_01Mhs7ToDehR1828s7VdjupD` | T75 dedup (`t-854ae281`, #211) |
| `session_01RtHwY4S7aNf7afWCn3tDwS` | T74 liveness (`t-921a4ef5`, #213) |
| `session_011LT2gtztb6PDeNmXpy43wa` | T82 status vocabulary (`t-9e5a05a0`, #214) |
| `session_014PVqB2HnzAsTQhTm3sktHs` | **adversarial fixture audit of T70** — reports, does not push |

All three task claims won at `0033160` (201). Each worker was told to stop after the
push; the orchestrator opens the PR. **Three `create_branch` calls in one message all
succeed** — the one-per-message rule is specific to `create_session`.

Each task file named its denominator two different ways (prose `<metric>_evaluated`,
dated section `duplicate_groups_evaluated` / `pages_checked` /
`application_records_checked`). Workers were told to write **both keys**. Worth fixing
in the template that generates these.

## Decisions the owner made this session

1. **#227**: fix the three verified fail-opens, then have a separate session write
   spec-derived fixtures. Both done; the audit is running.
2. **#225**: merge over the parked thread — the finding is upstream's
   (`claude-arsenal#253`) and this repo structurally cannot fix a vendored file.
3. **Fleet: three** — T75, T74, T82.
4. **Adopt the adversarial-fixture process change.** Written into `CLAUDE.md`.

## Still owed

1. **The `.claude/settings.json` paste** — here *and* in `nuncaeslupus/opos`. A session
   is hard-blocked from applying it, correctly. See "auto mode" below.
2. **#221's hold.** The T72 decision is made and implemented; the PR gates clean and all
   its threads are resolved. Only the standing "do not merge #221" instruction remains.

## The three fail-opens fixed in #227, and how they were found

Each was verified against the code by hand before being touched, and each fixture was
run RED against the pre-fix functions and green after — the check the previous four
rounds skipped.

- **A raw `%`** canonicalised to itself while `Disallow: /100%25` canonicalised to
  `/100%25`. Same octet, two spellings, rule never matched. `%` left the safe set and
  `_canon` now quotes the runs *between* escapes individually.
- **A bare `?`**: `urlsplit` reports an empty query for both `/foo` and `/foo?`, so the
  delimiter was dropped and the target escaped `Disallow: /foo?`.
- **`_product_token`** split on the first `/` and answered `Mozilla` for a browser-style
  agent — reading the group a site wrote for browsers, ignoring the one written for us
  by name. It now **raises** rather than guessing; RFC 9309 §2.2.1 gives a crawler one
  token. This is the case T71 (#204) walks into by design.

## The #221 / #228 conflict resolved — and git did most of it

Git auto-merged the `evidence` recipe body into exactly the combined form. **Only the
two comment paragraphs conflicted**; both were kept. The merged recipe uses
`repo_gate --list-evidence-modules` (T85's half) *and* the `case` recording exit 3 as
unmeasured (T72's half), and the merged run is the proof both were needed:

```
connector_health   silent_connector_failures: UNMEASURED — 1 connector(s) evaluated
                   but only 0 probed … Not a pass and not a fail.
```

`main`'s half alone turns that exit 3 into `GATE FAILED`; #221's old half alone never
discovers the module. First end-to-end run of D-12's mechanism.

## Unchanged and still true

CI is red repository-wide: `runner_id: 0`, no runner assigned, ~3s per job, red on
`main`. Never gate merging on it.

Commit before gating (`make evidence` compares committed evidence). Never put an
angle-bracket placeholder in a GitHub body. Vendored `claude-arsenal/` and
`.claude/skills/` are refreshed by `/init`, never hand-edited.

**Auto mode has a second permission gate** under a top-level `autoMode` key, distinct
from `permissions.allow` — which is why allow-listed tools still prompt. It also
hard-blocks a session editing `.claude/settings.json`. That is correct; do not route
around it.

Skip `lo-4b17` (T59), `lo-6f53` (T56), `lo-7c14` (T57). Next unblocked after the
current three: `lo-25b1` (T15), `t-e6f1dc24` (T76).

## Upstream

`claude-arsenal#253` filed (v2.4.22's skew-probe fallback still picks a winner among
ambiguous candidates instead of declining). #245–#251 open; **#249's proposed fix is
falsified** and that is commented on the issue. Deduplicate by content before filing.
