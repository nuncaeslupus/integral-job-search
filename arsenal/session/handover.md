# Session handover — 2026-08-27 ~18:35 UTC, interactive, laptop

Board: **110 gates on `main`**, 124 tasks. `make host-gate` exit 0 on `main`, and
`verify-gates` reports **110 terminal task(s); 110 gate(s) asserted, 0 carry no
fenced gate block** — the count alone would not say whether the gate passed or
whether any terminal task was ungated, which is the whole point of recording it.

`main` was at `e53ca9c` for the working part of this session; #244 has since
merged and moved it. Two PRs are open here, and two merged upstream in
`claude-arsenal` (plus the `v2.4.23` tag).

The session was asked to fix whatever could be fixed without a live human/browser
session, and to stop the routines.

## Routines are off

One routine was live: **`arsenal orchestrator — hourly tick`**
(`trig_015sxLyaFivf7aduKX6xQQur`, cron `16 * * * *`, last fired 17:16). It is now
`enabled: false`. The other 18 in the account are spent one-shot reminders
(`ended_reason: run_once_fired`).

**The API has no delete verb** — `enabled: false` is the stop, and it is one
`RemoteTrigger update` to bring back. Note also that `list` **ignores its cursor**
and re-serves the same page, so `has_more: true` there is not a promise of more
rows you can reach.

That routine was **self-bound**: `persist_session: true` with
`persistent_session_id: session_014yfFpB2ofL8TKeY199XQRH`. It did not create a
session, it woke one — which is forced, because a trigger that creates a session
stores no MCP connectors and would have no GitHub channel at all. Filed as
[claude-arsenal#255](https://github.com/nuncaeslupus/claude-arsenal/issues/255):
the tick's *contract* belongs in `references/orchestrator-tick.md`; only the clock
is surface-specific. Today that contract exists solely inside a trigger object on
one account — unversioned, unreviewed, and already drifted between copies.

## Open

| PR | task | state |
|---|---|---|
| [#242](https://github.com/nuncaeslupus/integral-job-search/pull/242) | T86 eligibility vocabulary → closes #237 | head `fcaeccc`. CodeRabbit round 1 answered; round 2 not yet in. **Blocked on the independent fixture pass**, not on review — see below. |
| [#243](https://github.com/nuncaeslupus/integral-job-search/pull/243) | this handover | closes no task. |

[#244](https://github.com/nuncaeslupus/integral-job-search/pull/244) (bundle →
v2.4.23) **merged**. Only #242 moves the board (110 → 111) and only #242 closes
an issue.

`arsenal/claims/t-fdc8e19f` is held by this session. Issue #237 now carries
`arsenal-task: t-fdc8e19f` and the `arsenal:task` label.

### T86 — what it fixes

`"DE"` against *"must hold German citizenship"* returned FAIL, and `"ES"` against
the same advert returned FAIL identically: indistinguishable to the code. A false
FAIL is the invisible direction, because an excluded job is one the candidate
never sees. A scoped ES/EN/CA table resolves both sides; a term outside it goes to
FLAG, never FAIL, so coverage is a quality dial rather than a correctness
precondition. Clearances stay out by decision.

`_normalize` also **deleted** accented characters rather than folding them, so
`alemán` became `alemn` — a key matching neither spelling. It folds now.

Its own gate counts the direction nothing counted: `false_disqualifications`,
**0 of 15** evaluated, and **10 of 15** with the vocabulary switched off. That
second number is asserted by a test, so the zero is a measurement rather than a
tautology — the T72 failure mode, checked for.

### T86 — the review round is the lesson again

CodeRabbit found **two real correctness defects, both in the new code, both false
disqualifications** — the very failure the gate was written to expose, sitting in
the gate's own fixtures:

- `_BLOCS["EEA"]` holds country codes, so it never contains the string `"EU"`.
  Neither containment branch could settle a **bloc-against-bloc** pair, and `EEA`
  against a bar naming `EU` fell through to a confident FAIL.
- `held_codes` is a set, so `("ES", "España")` collapses to one code. Comparing
  its size against the tuple's read that collapse as an unresolved term and
  downgraded a correct FAIL to FLAG.

Neither case existed in the probe set, so `false_disqualifications` read 0 over
both gaps. Both are now probes **and** tests; the denominator rose 13 → 15.

**The independent fixture pass still has not run.** `CLAUDE.md` requires a session
other than the implementer to derive adversarial cases from the spec before the
implementation is opened, and this is squarely that class of code. The nine
original probes were written by the implementing session. Two review findings
inside one round is the argument for that rule, not against it. **#242 is blocked
on that audit, not on review.**

## `open_task_pr.sh` cannot open a PR in this repo

It runs the host gate **twice** — before the archive (line 118) and again after
(line 495). `arsenal/tasks/` is counted by T55; `_history/` is correctly
allowlisted, because a ledger is not edited afterwards. So the archive moves the
count and the two runs demand different committed values:

| tree state | `T55.files_scanned` |
|---|---|
| task file in `arsenal/tasks/` | 561 |
| task file in `arsenal/tasks/_history/` | 560 |

No single committed value passes both. **The `CLAUDE.md` note about fixing this
with "a second commit on the branch the script left you on" no longer applies** —
the script now stops *before* committing, so there is no branch to add it to. #242
was branched, archived, regenerated, committed, pushed and opened by hand.

Filed as [claude-arsenal#256](https://github.com/nuncaeslupus/claude-arsenal/issues/256)
with three ordered fix options. The rollback path itself is clean — it restores,
deletes the archive, and asserts both — so a failed run does not leave the tree
half-done.

## Upstream: `issue_import.py` crashed on the second issue of every run

Protocol step 4b was dead. `importable()` took an unused `known_ids` parameter and
ran `del known_ids` **inside** its loop: the first issue unbound the name, the
second raised `UnboundLocalError`. Every gate in `issue_import_test.sh` fed
exactly one importable issue, which is why it shipped green.

[claude-arsenal#254](https://github.com/nuncaeslupus/claude-arsenal/pull/254)
**merged** — parameter removed, a gate added that feeds two and asserts two task
files, verified to fail against the unfixed copy.

**It merged without its version bump**, which is the part worth remembering:
#254's own `version bump` check failed and went unaddressed, so the fix sat on
`main` untaggable — `make tag` answered `v2.4.22 already published — nothing to
release`, and every consumer's `check_update.sh` reported the bundle *current*
while still carrying the crash. A merged fix nobody can install reads exactly
like no fix at all.

Closed out the same session:

| | |
|---|---|
| [claude-arsenal#257](https://github.com/nuncaeslupus/claude-arsenal/pull/257) | merged — `make bump` 2.4.22 → 2.4.23, all seven checks green including `version bump` |
| `make tag` | **`v2.4.23` published** from `main` |
| [#244](https://github.com/nuncaeslupus/integral-job-search/pull/244) | open — bundle refreshed here, `make host-gate` exit 0 |

Verified from the **vendored** copy after the refresh: three `arsenal:queue`
issues enumerated in one run, where the second used to raise.

Two facts about refreshing that cost time to establish:

- **`claude-arsenal/` here is not a git subtree**, so `git subtree pull` is not
  the update path — `check_update.sh` says so and re-vendoring with
  `init.py --repo-path . --silent` is what works.
- `init.py` prints a `refreshed: session/handover.md` line that names the
  **bundle's own template**, not this file. It does not touch this repo's
  session record — but check the working tree before committing a refresh
  rather than trusting that sentence.

The plugin cache at `~/.claude/plugins/cache/claude-arsenal/core/` is stale at
2.0.0. That blocks nothing, because `init.py` vendors from the checkout, but a
future `/init` run from the cache would write *older* files over the bundle.
`/plugin update claude-arsenal` is a user action; no session can do it.

## The CI note in `CLAUDE.md` is repo-scoped, not account-wide

`claude-arsenal` is **public** and its CI runs normally — 15–30 s, real runner
ids, checks passing. `integral-job-search` is **private** and still shows the
documented signature: 5–6 s, `runner_id: 0`, no runner assigned, red on `main` too.
So this is private-repo billing, not a broken account, and the note should say so.
Do not read a green run on the sibling repo as evidence that this one recovered.

## Not imported, and why

`issue_import.py` works now, but an imported task is not finished work here: this
repo's `plan_v2` gate requires every queue task to carry a `T##`/`D-##` label
**and** a matching row in `status/plan.md` with a real gate expression. That is a
scoping act, not a mechanical one.

- **#236** — robots product-token prefix matching (T70 audit case 22). Answerable
  from RFC 9309, but it is a correctness-critical matcher, so `CLAUDE.md` wants a
  second session to derive the cases. Left as `arsenal:queue`.
- **#182** — merge-policy to `after-ci-and-review`. Genuinely blocked until runner
  minutes return. Writing a plan row and a gate for it now would be speculative.

Both keep the `arsenal:queue` label and neither has a task file.

## Next

1. **#242**: CodeRabbit round 2, then the independent fixture pass, then merge.
   Board goes 110 → 111.
2. **#244**: merge the bundle update. **#243**: this file.
3. `/plugin update claude-arsenal` when convenient, so the cache stops being
   three minor versions behind what is vendored.
4. `task_select.py` returns **T71** (`t-490e52d5`, priority 10, dep T70 merged) —
   read the robots policy with a browser agent when the honest one is refused.
   That one needs the live browser session and was deliberately left.
