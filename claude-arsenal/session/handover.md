# Session handover — 2026-08-19 (T5 closed; the labelling campaign is retired)

## Read this first

**The hand-labelling campaign is over, by the owner's decision.** They worked
through four pre-marked ads, judged the model's read good enough, and said:

> *"some other dimensions can be added, but the job you did is really good. So I
> don't think we need to do this annotation step. The LLM must read the text and
> find those dimensions alone. If, when working on a test session I can see some
> other dimensions to be added, we'll use that time to do that."*

Do not restart it. Do not ask the owner to label ads. Human labels accrue from
ordinary use of the tool from here on.

## State

| what | where |
|------|-------|
| PR #41 — 828 pre-marks, banked labels, span-merge on import, `talking_clients` | **merged** as `2b6c57a` |
| PR #42 — T5's measurement, harness inside the drift loop | **merged** as `e71db04` |
| T5 (`lo-d2b2`) | **`merged`** on `arsenal-queue`, `--pr` #42 |
| Corpus | 100 ads · 828 pre-marks over 84 · 16 blind-control · **39 human labels over 4 ads** |
| Dimension model | **25** (added `talking_clients`, `leadership`, `collaboration_mode`) — at the planned ceiling |

`queue_doctor.sh`: 0 findings. All five local gates green on `7faa498`.

## What T5 closing unblocks

T5 was the choke point: T9, T14 and D-2 blocked on it directly, and T15's whole
chain (T16, T17, T18, T19, T20, T21, T42, T43, T44, T45, T46, S6, T47) through
T14. Unblocked and `open` now:

```
p5   lo-b422  T9   reaction elicitation
p5   lo-3100  T14  lexical prefilter          ← read its scope note first
p5   lo-77a6  D-2  the measurement            ← recommended next
p5   lo-803e  T53  connector contract pack
p5   lo-9f72  T55  rename to integral-job-search
p70  lo-1af2  T25  [LAPTOP] broaden the corpus
p1   lo-277b  T12  [LAPTOP] portal connector
```

`[LAPTOP]`-tagged tasks are refused by `release.sh done` in a cloud session.

## The one thing that must not be got wrong

Skipping the annotation step did not remove the measurement problem — it moved
it up a layer, and D-2 (`lo-77a6`) now records the new shape.

The old failure: gold spans mined with the dimensions' own cues, so scoring
extraction against them asked a regex to re-find the string it was written from.
That is closed, and measured rather than asserted —
`suggestion_cue_agreement == 0.372`, `cue_unreachable == 520/828`.

The new failure, one layer up: **the extractor T15 builds is the same kind of
reader that wrote `suggestions.json`, doing the same job on the same adverts.**
Scoring it against those marks measures self-consistency and passes near 1.0 for
exactly the reason the cue-derived gold did. Independence from the cues is not
independence from the model. The only independent reader left is the owner.

So, binding on T14 and T15 alike:

1. Score only labels whose `source` is `human`, `confirmed` or `edited`. Never
   `suggestions.json`, never `extraction.gold`.
2. Emit `n` beside every score, and **refuse to emit the score at all** below a
   per-dimension label floor — naming the dimensions that could not be measured.
   Unmeasured is a third outcome, not a pass and not a fail.
3. Agreement against the pre-marks may still be computed. It is not F1 and must
   never be written to the `extraction_macro_f1` key.

`status/evidence/T5.json` carries the counts this rests on, regenerated on every
`make evidence` run: 14 labels in the evaluation half, no dimension above 4, and
`mission_alignment`, `process_formality`, `social_intensity`, `work_intensity`
with none at all.

## Recommended order

1. **D-2 (`lo-77a6`)** — small, and it is the contract T14/T15 have to satisfy.
   Give `extraction.gold` its `derived_from: cue | human` field so rule 1 is
   enforceable by the schema rather than by memory.
2. **T14 (`lo-3100`)** — but read its scope note first. The recommendation is to
   **fold it into T15** as the rules stage T15's own v2 note already describes,
   rather than give it a separate gate against a corpus that cannot support one.
   That is a scope decision: raise it with the owner, do not decide it inside a
   worker run.
3. **T15 (`lo-25b1`)** — the task that *is* the owner's decision. Blocked until
   T14 resolves either way.

## Two things carried forward, both needing the owner

- **Coining dimensions is now a live-session activity** (T26, and S11's test
  mode). Three have been coined that way. What makes one usable: a distinct
  value per rung, a name recognisable six months later, and a `tell` — the
  wording that rung actually takes in an advert. `leadership` arrived with two
  rungs meaning the same thing; `collaboration_mode` arrived as a non-monotone
  scale named `autonomy`, colliding with `team_autonomy`. Both were repaired in
  #41 and the reasoning is in each file's header comment.
- **`dimensions/process_formality.yaml`** scores manfred-8360 at **+0.5** on a
  span opening *"se huye de los sprints infinitos"* — the ad rejecting ceremony
  — while the shipped suggestion reads it as **−0.6**. Inside D-2's scope; flagged
  on #41, not seeded as a duplicate task.

## Known: the two ledgers drift, and only one is authoritative

`claude-arsenal/queue/tasks.jsonl` exists on **both** the default branch and
`arsenal-queue`, and they do not agree. **`arsenal-queue` is the source of
truth** — `claim.sh` and `release.sh` write there and nowhere else. As of this
handover T5 reads `merged` there and still reads `open` on `main`.

This is structural, not a slip. `queue_sync.sh` ports rows that are *absent*
from the coordination branch and by design never touches existing claim/release
state, so a status recorded on `main` never reaches `arsenal-queue` and nothing
detects the divergence. `queue_doctor.sh` reports 0 findings either way: it
audits one ledger for internal consistency, and cross-branch divergence is
outside what it looks at. A previous session found **17 rows** apart this way
and `queue_eval.sh` handed out a task that had merged two months earlier.

So: run `queue_branch.sh` and read the coordination worktree, exactly as the
session protocol says. Do not decide anything from the copy in the main tree.
Worth carrying upstream as a `queue_sync.sh --reconcile-status` and a
`queue_doctor.sh` cross-ledger check.

`reconcile_merged.sh` needs `gh`, which a cloud session does not have — GitHub
reaches it through MCP instead. Flip `done` → `merged` by hand there with
`release.sh <id> merged --pr <url>`, or leave it for a laptop session; both
statuses are terminal and both satisfy blocking deps, so nothing stalls either
way.

## Environment

GitHub Actions is out of runner minutes. Every job on every workflow fails in
3–5 seconds with `runner_id: 0`, `runner_name: ""`, `main`'s own HEAD included.
Confirmed on `da389b1` (job 96236765689) and `7faa498` (job 96241015351).
**Diagnose once per head, then run the five gates locally** — never push a
speculative CI fix:

```bash
make lint && make test && make evidence && make verify-subtree && make verify-gates
```
