# Session handover — 2026-08-20 (arsenal v0.30.0; D-10/D-11/T14 settled; T15 built, D-12 found)

## Read this first

**One decision is waiting on you: D-12 (`t-e1ca8374`, #83).** Everything else
from the previous handover is settled and merged.

D-2 binds T15 to three outcomes — a score, a failure, or **unmeasured**. With 14
evaluation labels against a floor of 10 per dimension, unmeasured is the only
honest one, and `jobsearch.extraction` records it as `null` +
`extraction_status`. `gate_evidence` has only two outcomes: it reads that null
as `non-numeric value` and hard-fails. So **T15 cannot reach terminal however
finished its code is**, and fifteen of the twenty-six live tasks sit behind it —
the exact shape T14 was in before #81 folded it.

Two resolutions, in #83's payload. **A** splits T15's acceptance (close it on
`prefilter_suppressed_positives == 0`, which holds today; move
`extraction_macro_f1 >= 0.75` to its own task blocked on T25/T26). **B** gives
the gate layer a third outcome — filed upstream as claude-arsenal#168.

Do not resolve it by lowering the floor or by scoring cue-derived gold as if a
person placed it. That is the failure D-2 exists to prevent, and it already
happened once.

**PRs merged this session:** #81 (arsenal v0.30.0, D-10, D-11, T14 fold, T9),
#82 (history + a lint that #81 merged red). **#84 is open** with T15's
implementation and closes nothing, deliberately.

Merge any PR carrying a subtree pull **with a merge commit, never a squash**.

## State

| what | where |
|------|-------|
| PR #81 — arsenal v0.30.0, D-10, D-11, T14 fold, T9 | **merged** `96c45b0` |
| PR #82 — task history, T53 glyph, lint fix | **merged** `53cdfff` |
| PR #84 — T15 staged extraction | **open**; closes nothing until D-12 is decided |
| D-12 (`t-e1ca8374`, #83) | **new, needs your decision** — see above |
| T15 (`lo-25b1`, #52) | code merged-ready, gate unmeetable; issue claimed |
| D-10 (`t-2583900f`, #78) | **resolved — resolution A**, `parse.py` withdrawn from the shape |
| D-11 (`t-296eb71a`, #80) | **new and fixed in the same PR** — found while investigating D-10 |
| T14 (`lo-3100`, #46) | **cancelled**, absorbed into T15; payload in `_history`, `status: cancelled` |
| T9 (`lo-b422`, #47) | now declares `requires: [surface:egress]` |
| Bundle | **v0.30.0**; `merge-policy = "after-review"` |

## What was decided, and how to reverse it

**D-10 → resolution A.** `parse.py` is out of `docs/distribution.md` §5 and out
of `OPTIONAL_ENTRIES`; a package containing one is refused by rule 1 with a
message that explains rather than lints. Decided on three grounds: B is a
milestone (separate interpreter, no network namespace, read-only fs, CPU/memory
caps, plus a `parse(text) -> str` contract), the hatch had no user, and **T54
(#70) was already written assuming A** — its disclosure list names connector,
fixture and metadata. That last one is why D-10 had to be settled *before* T54.

To reverse: `jobsearch.connector_shape` holds `EXECUTED_ENTRIES`, declared and
empty. Building the isolated runner means adding `parse.py` there, restoring it
to §5 and to `OPTIONAL_ENTRIES`, and re-inverting
`test_a_parse_module_is_refused_however_well_behaved_it_is`. The gate stays
green honestly at every step, which is the point of the constant.

**T14 → folded into T15.** Its gate was `prefilter_recall >= 0.98` against
corpus positives T5 never supplied (39 labels, 4 ads, 14 in evaluation, four
dimensions with none). Kept separate it blocked T15 and, through it, **fifteen
of the twenty-six live tasks**.

Three mechanics that are each wrong alone — check them if you revisit this:
1. `lo-3100` came out of T15's `deps` **first**; a cancelled task left in the
   list blocks T15 permanently.
2. The payload is in `_history` with `status: cancelled`, deliberately **not**
   terminal, so nothing reads it as a completed prefilter and `verify-gates`
   does not assert a gate that was never measurable.
3. #46 was closed with `arsenal:cancelled`, **not** by a `Closes #46` — a PR
   keyword closes as *completed*, which upstream reads as `done`.

## D-11 — the defect worth remembering

`docs/distribution.md` §5 hands a contributor
`python -m jobsearch.connector_contract --connectors <their dir>`. That wrote
**our** `status/evidence/T53.json`, so a check over somebody else's library
replaced the number T53's gate is asserted against. It was hit by accident, on
the first run, while investigating something else.

The fix is that evidence is written only when the caller named a destination or
the check ran over our own library. The part worth carrying forward is the gate:
`evidence_writes_for_a_foreign_library` is asserted over `evidence_target` —
the function `_main` actually calls — not over a restatement of the rule. **A
gate that restates a rule agrees with prose the code has stopped following.**
That is the shape of all six holes review found on #77 and of D-10 itself.

The same discipline is applied pre-emptively to `connector_shape --doc`.

## Where the board stands

`plan_queue_task_drift == 0`; `verify-gates` asserts **53/53**.

Unblocked and autonomous-safe once #81 merges:

- **T15 (`lo-25b1`, #52)** — now unblocked, and it is the keystone: fifteen
  tasks sit behind it. Its payload carries the prefilter requirements as items
  4 and 5 of the scope section. Note D-2's binding: with
  `evaluation_gold_count` at 0, refusing to emit `extraction_macro_f1` and
  naming the unscoreable dimensions is currently the only correct output. Do
  not "fix" that by relabelling cue gold as human.
- **T54 (`lo-892b`, #70)** — no longer gated on D-10; it can be taken as
  written.
- **T55 (`lo-9f72`, #49)** — mechanical but wide, and the GitHub repo rename is
  not something a session can do.
- **T9 (`lo-b422`, #47)** — now correctly held out of cloud sessions.

## Three things that will bite you

### CI still cannot pass, and it is still not the code

Diagnosed again this session on `1bada3d`: all five checks failed, every one
with `runner_id: 0`, `runner_name: ""`, and a 3-second duration (09:04:27 →
09:04:30). Both criteria in CLAUDE.md hold. Do not push speculative fixes.

`merge-policy` is now **`after-review`** (claude-arsenal v0.30.0), so the config
says this in a value it validates rather than in a prose note redefining "ci".
The five gates are still run locally on every head and quoted on the PR — they
are simply no longer *called* CI.

### `make arsenal-remote` pulls and commits

It runs `check_update.sh` **without** `--check-only`, so reading the version
merged v0.30.0 and committed it — the exact hazard AGENTS.md step 0a warns
about, reached through a Makefile target rather than a direct call. It also
leaves the job half done: the pull is one of `arsenal-upgrade`'s four steps, so
the assembled bundle sat at 0.29.1 while the subtree said 0.30.0 until
`update-skills` + `assemble-bundle` were run by hand. Worth a queue task.

### Claiming still needs one manual step

Unchanged from v0.29.1: `claim_task.sh` exits **5** and prints the call; make it
with the MCP `create_branch` tool on `arsenal/claims/<task-id>` (201 = won,
422 = lost), then label, self-assign and comment the session id.

## Follow-ups not in #81

- Once #81 merges, D-10 and D-11's payloads want moving to `_history` with
  `status: merged` and their PR — the chore #79 did for T53. Until then
  `verify-gates` counts 53, not 55.
- Upstream claude-arsenal#167 deferred the better fix — letting `after-ci` be
  satisfied by a locally recorded gate result, as the evidence gates already
  work — "for its own issue", and **no such issue exists**. It is the change
  that would make a local gate run count as evidence rather than as prose.
- `make arsenal-remote`'s side effect, above.

## Environment

Five gates on `1bada3d`, all green:

```
lint            ruff + strict mypy clean, 90 files
test            971 passed, 1 skipped
evidence        no drift
verify-subtree  0 diverging, 22 assets compared
verify-gates    53/53
```

---

## What T15 settled (PR #84)

`jobsearch.extraction` runs three stages — normalise, cues, then the model on
what is left. It **does not call a model**: as with `elicit_extract` (T8), the
model is the session running the step skill, so the module says what is
unsettled (`model_request`) and validates what comes back
(`accept_model_scores` refuses a span not in the advert, a dimension nobody
asked about, and a dimension scored twice). `ModelRequest` has no field a
profile could arrive through — step 8's "never send the candidate's profile
with the advert", made structural.

**Two rules came out of measurement rather than argument.** The folded T14
prefilter check found two real suppressions in the committed corpus:

1. **A bipolar dimension is not settled by one keyword.** "Ejecutar las tareas
   asignadas con autonomía" contains *autonomía* and means close to its
   opposite — a person labelled it −0.6 while one +0.7 cue settled it +1. One
   keyword is evidence of the topic, not of a direction. Unipolar dimensions are
   exempt.
2. **Unipolar scales have no negative class.** "Sin viajes ni guardias" was
   labelled `0.0, negated=True` (−1) while the cue for that phrase carries `0.0`
   (0). Two encodings of one agreement read as a disagreement.

If you change the cue sets, `prefilter_suppressed_positives` is the thing to
watch — 0 over 36 positives now, and a test inverts a committed cue to prove the
check still fails when it should.

## For a first test session

Steps 0–4 run today. Step 8 can use `jobsearch.extraction` now. What is still
missing before a candidate reaches a ranked list:

- **T18/T19** (#57/#58) — ordering and explanations, the part the candidate sees.
- **T12** (#51) — one live connector against recorded fixtures. `[LAPTOP]` +
  egress, so it is yours; without it there are no real offers to rank.
- Steps 5–6 (T9/T10) are optional for a first pass — ranking degrades to
  unweighted rather than breaking.

**S11 — "test mode" — is not built** (#63, blocked behind S10 #71). A session
will run the steps; the meta channel for improving skills mid-session will not
exist.
