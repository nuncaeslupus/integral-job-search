# Session handover — 2026-08-27 ~18:35 UTC, interactive, laptop

Board: **110 gates on `main`**, 124 tasks. `main` at `e53ca9c` — **unchanged this
session**. Nothing merged into this repo; one PR is open and one upstream PR merged.

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
| [#242](https://github.com/nuncaeslupus/integral-job-search/pull/242) | T86 eligibility vocabulary → closes #237 | **open**, head `fcaeccc`. CodeRabbit round 1 answered; round 2 not yet in. |

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

**It is merged but not tagged.** The newest tag on `arsenal` is still `v2.4.22`, so
`check_update.sh` reports the bundle current and the host cannot pull the fix. This
is the `UNTAGGED UPSTREAM RELEASE` case, and its fix is upstream `make tag` — a
public release, so it was left for the owner. Until then, run the fixed copy
directly:

```bash
python3 ~/dev/claude-arsenal/plugins/core/skills/init/assets/scripts/issue_import.py \
    --issues /tmp/arsenal-import.json --tasks-dir arsenal/tasks --apply
```

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
2. `make tag` upstream, then refresh the bundle here so `issue_import.py` works
   from the vendored copy.
3. `task_select.py` returns **T71** (`t-490e52d5`, priority 10, dep T70 merged) —
   read the robots policy with a browser agent when the honest one is refused.
   That one needs the live browser session and was deliberately left.
