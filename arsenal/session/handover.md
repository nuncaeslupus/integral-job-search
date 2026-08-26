# Session handover — 2026-08-26 ~02:00 UTC, parallel fleet run: 3 tasks, 2 merged, 1 held

Board: **101 gates asserted** (was 99). `main` at `e8d1921`.

| PR | task | outcome |
|---|---|---|
| [#220](https://github.com/nuncaeslupus/integral-job-search/pull/220) | docs: cloud capability model | merged `2571bef` |
| [#222](https://github.com/nuncaeslupus/integral-job-search/pull/222) | T80 ATS text-layer contract | merged `f627666`, #208 closed |
| [#223](https://github.com/nuncaeslupus/integral-job-search/pull/223) | T84 step-11 drafting rules | merged `e8d1921`, #219 closed |
| [#221](https://github.com/nuncaeslupus/integral-job-search/pull/221) | T72 connector health | **HELD — owner decision** |

## The capability map, measured — this shapes every fleet design

| | interactive session | any session it spawns |
|---|---|---|
| `mcp__*` tools | yes | **NO — none at all** |
| REST | 403 | 403 |
| `git` fetch / ls-remote / **push** | yes | **yes** |
| `git push --delete` | **blocked**, and lies (`Everything up-to-date`, ref survives) | blocked |

**Be precise about which half is measured.** The `create_session` path IS measured: two
children reported *"GitHub access denied (403); no MCP tools available"* and blocked.
The **routine-fired path is inferred, not run** — a probe trigger built to test it was
deleted before firing, so the evidence there is the trigger API's own statement at
creation (*"this trigger stores no MCP connectors, so the sessions it fires will run
without connector tools"*) plus the absence of any `mcp__*` entry in the returned
`allowed_tools`. Strong, but not a measurement; say so rather than rounding it up.

Separately measured: `create_trigger`'s `connectors` parameter returns **"not available
for this organization"**, so the grant cannot be passed to a fired session even
deliberately. Since `create_session` is itself an MCP tool, a spawned session cannot
spawn anything either — which is what makes a fresh-orchestrator-per-tick design
impossible, and leaves interactively opened sessions as the only holders of the grant.

**Permissions ≠ tool availability.** `.claude/settings.json` (committed, 10 allow rules)
decides whether an existing call *prompts*; it cannot make an absent MCP tool exist. It
is also read at session **startup**, so pulling it into a running session does nothing —
that session keeps prompting until `/hooks` is opened or it restarts.

## Traps that each cost real time

- `make host-gate`'s evidence check compares **committed** evidence against measured.
  Commit first, then gate. Gating an uncommitted tree reports drift forever.
- Task PRs all touch `status/evidence/D12.json`; after one merges the rest conflict.
  Merge `main` in and regenerate with `make evidence` — never hand-edit evidence JSON.
- **Never put a placeholder in angle brackets in a GitHub body.** GitHub silently strips
  it: `ARSENAL_TASK_ISSUE=<n>` rendered as `ARSENAL_TASK_ISSUE=`, making the instruction
  wrong. Same hazard `AGENTS.md` warns about for issue bodies.
- CI is red for everyone — Actions is out of runner minutes. `runner_id: 0`, no runner
  assigned, 3-5s, red on `main` too. Confirm that signature; never gate merging on CI.
- CodeRabbit allows **10 reviews/hour** and every push spends one. Three concurrent PRs
  saturate it — a throughput ceiling independent of worker count.

## The finding worth internalising

Three workers each shipped a **green host-gate and passing tests**. Review found **six**
issues across them, five real. Three were defects in the *measurement itself*:

- **T72** — `default_fetch` reads the same `fixture/list.html` that `assess_package` uses
  as `baseline_html`, so the production path compares a string with itself.
  `silent_connector_failures` can only ever be 0, on a task whose purpose is detecting
  parser rot — and its evidence says `"gate_status": "measured"`.
- **T80** — `documents_missing_a_required_text_layer_field` counted corruption-only
  violations too, so a document with every field present but a mojibake text layer was
  reported as missing a field. Fixed before merge.
- **T84** (merged, minor) — the rule-detection regexes search the whole `SKILL.md`, so a
  paraphrase dropping one backtrack tier could still match the word elsewhere and read as
  present. Not fixed; a small follow-up task if wanted.

**A green gate is necessary, never sufficient.** Every automated check in the repo passed
on all three.

## Needs the owner

1. **T72 (#221).** Fix the tautological probe — which makes the gate `unmeasured`,
   un-completes T72 and drops 101 → 100 — or accept and document the limitation? It is a
   scoping decision like T15's threshold, not a patch. Proposed patch is in the PR.
2. **Fleet cost.** ~$5.45 per completed worker; **at least $18** spent (three completed
   at $5.97/$4.56/$5.82, plus $1.75 burned by two that blocked before the GitHub-free
   worker prompt existed, plus one interrupted worker not accounted). Three concurrent workers
   also triple CodeRabbit traffic and the notification load on the orchestrator.
   No workers were dispatched after the first round, pending this decision.
3. **`/hooks`** in any long-running session that predates the permissions commit.

## Fleet recipe that works

Orchestrator (interactive, holds the grant): fetch board → claim via
`create_branch` on `arsenal/claims/<id>` (success = won, "Reference already exists" =
lost, obey it) → `create_session` child **with explicit `source_url`** → open its PR →
verify `make host-gate` yourself → merge when CodeRabbit threads are all resolved.

Worker (git-only): worktree off `origin/main`, implement, `make host-gate`,
`ARSENAL_TASK_ISSUE=<number> open_task_pr.sh <id>` (its final PR step 403s — expected,
the push is the deliverable), report branch + sha, stop.

**The PR body must carry `Closes #NNN` as a literal number.** That is the whole
completion mechanism: merging closes the issue and archives the task file in one move,
so a PR opened without it merges while leaving the queue stale. `open_task_pr.sh` also
writes it into the commit message, which is what survives a squash.

Selection: `worktree_probe.sh > /tmp/wt-sentinel.txt` then `task_select.py
--isolation-sentinel /tmp/wt-sentinel.txt` — the sentinel records the probe's real
verdict; `--no-isolation-clamp` just disables the check.

Skip `lo-4b17` (T59), `lo-6f53` (T56), `lo-7c14` (T57): label floors unmet and T15's
threshold needs a decision, so a worker cannot pass those gates.

## Upstream

`claude-arsenal` **#245–#248** filed from tonight's findings: budget_check inert on cloud
plus a round cap that never resets (reads `CLAUDE_SESSION_ID`, which is unset here);
the injected protocol and `agents/worker.md` assuming every session has the API;
worktree isolation unconfirmable for separate-session workers; `github_channel.sh
--detect` reporting `rest` where REST 403s. **Deduplicate by content before filing more**
— a sibling session files as the same GitHub user.
