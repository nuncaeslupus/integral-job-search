# Session handover

**2026-09-05.** Board: **142 terminal tasks**, `verify-gates` 141/142, 2793
tests. Two PRs merged (#346, #347), four issues queued (#343, #344, #345, #348).
The session began as "get a live candidate session ready" and ended having found
that a live session is not possible yet — for a reason no checkpoint reports.

## 1. Step 7 has no implementation that fetches — #348

The two ends of sourcing exist and have never been connected. Measured on
`main` at 1fbf836:

- `load_connectors` / `usable_connectors` are imported by exactly two modules,
  `connectors.py` and `connector_exchange.py`. Neither touches a `ProfileStore`.
- `build_offer` / `build_search_offer` are called from exactly two places and
  **both are gates** — `connector_contract.py`, `connector_coverage.py`.
- `collect_offer`, the only writer into a candidate's tree, is called from
  `reaction_elicit.py` (handed its offers by the caller) and from `lifecycle.py`'s
  own probe fixtures. Nowhere else.
- `build_list_urls` / `build_list_requests` have **no production caller at all**.

There is no path from `constraints.json` to a live board to
`profiles/<handle>/offers/`. The `ivan` profile's 106 offers were placed by a
session by hand, and are dated 2026-08-15.

**Why nothing reported it.** Step 7's `run_checkpoint.py` returns
`artefacts_present: true`, `coverage_met: true`, `runnable: true`. It checks that
offer files exist, not that anything can produce them — so a step whose artefacts
were placed by hand is indistinguishable from one whose implementation works. The
same fail-open shape this repo keeps finding, one layer further out than usual:
not a metric that counts the wrong thing, but a *coverage check* satisfied by
artefacts nobody produced.

`tools/collect_ads.py` is **not** this and was briefly mistaken for it here. It
writes `corpus/raw/ads.jsonl` from hand-written `from_<board>` functions with
hardcoded URLs and never touches the connector engine. It is the corpus
collector.

## 2. What merged

**#346 (T124)** — `url_pattern` admitted only `{page}`, so every candidate got
the query its YAML author wrote: `?te=python` on tecnoempleo,
`atencion_al_cliente` on trabajos. Adds `{query}` as a second allowed literal
(the brace check still refuses `{0.__class__}`, `{query!r}`, `{}`, `{QUERY}`),
refuses to substitute an empty query, adds `accepts_query()`, and records the
terms in `candidate.Aim` — deliberately **outside** `FIELD_MODELS`, because
D-20's gate says a pinned constraint nothing filters on is a lie and the aim
steers the fetch rather than narrowing the result.

Two boards wired, four left alone, each decided by a **differential live fetch**
rather than by reading a form's `name` attribute:

| board | param | verdict |
|---|---|---|
| tecnoempleo | `te` | wired — 30/27/29 cards for three queries, titles matching |
| jobfluent | `q` | wired — different first cards per query |
| trabajos | `BUSCAR` | ignored — byte-identical 40 items for both queries |
| ticjob | `keywords` | GET returns 3 and 2 items whose titles do not match; real form is POST |
| infojobs | — | no form inputs in 1.2 MB; JS-rendered |
| getmanfred | — | no slot by design; the API returns the whole active list |

**#347 (T107)** — 24 candidate-facing strings, `en` (source) / `es` / `ca`, in
`strings/catalogue.json`. Each translation records `of`: the sha256 of the source
text it was made from, so editing the English makes its translations *provably*
stale. `presentation.py` looks strings up through `_t(key, language)`; `render()`,
`card()` and every helper take a `language`. Card columns are **derived** from
label widths (`ubicación` is longer than `location`); the pay period is rendered
(without it a Spanish card read `EUR/year`).

**Completeness and staleness are gated. Quality is not, and is not claimed** —
nothing can tell whether a contributed German pack is good German, so a pack
records who made it and when. An unserved language falls back on every string and
`untranslated(language)` names every one: silent English was the defect, announced
English is the feature.

## 3. Merged without CI, and the evidence trail was repaired late

Actions is still dry (checks fail in 2–4s, `runner_id: 0`). The owner instructed
merging anyway. `make host-gate` was green over each tree before its PR opened —
but `tools/verified_gate.sh` was **not** run, its block **not** pasted before the
merge, and the results **not** quoted in either squash message. All three are the
procedure the 2026-09-04 handover records. The block was produced afterwards over
the merged tip and posted on both PRs, which is weaker evidence than the
procedure asks for. Next session: run it first.

Note `CLAUDE.md`'s "Known environment state" still says Actions recovered on
2026-09-01 and that a red CI is a signal again. **That is stale** — a session
trusting it will chase a phantom failure.

## 4. Two costs worth not paying twice

- **Seeding a task needs its `status/plan.md` row already marked `☑`.** The gate
  runs *after* `open_task_pr.sh` archives the task file, so a `☐` row fails
  post-archive while a `☑` row fails pre-archive. Check instantly with
  `plan_v2.measure()['violations']` instead of discovering it through a
  four-minute helper run. Cost here: three wasted runs across two PRs.
- **`make evidence` diffs the working tree against the *index*.** A regenerated
  evidence file must be `git add`ed before `open_task_pr.sh`, or the gate reports
  drift about a change that is already correct. Adding `strings.py` bumped
  `gate_modules_discovered` 92 → 93 — a growth-sensitive key of exactly the shape
  T111 flags.
- **`make format` is a repo-wide rewrite.** `make lint` never checked formatting,
  so `ruff format .` on a clean checkout rewrites **33 files** (`cue_audit.py`
  alone by 683 lines). It swept a third of `src/` into T124's diff and had to be
  reverted file by file. Queued as #345 — do it when no PR is open.

## 5. Queued, in the order they unblock each other

- **#348** — the sourcing driver. Blocks any live session.
- **#345** — format once, add `ruff format --check` to `make lint`. Small, and
  wants a moment with no PR open.
- **#344** — the corpus ships 208 verbatim adverts, full text, 485k characters.
  The excerpting rule the *fixtures* obey ("the adverts are the board's content,
  not ours") was never applied to it. Blocks making the repo public — which in
  turn is what would end the Actions problem, since Actions is free and unlimited
  on public repositories.
- **#343** — contributed connectors and language packs should arrive
  review-ready: generate the PR body from `meta.yaml`, guard the paths in CI.

## 6. Housekeeping

**63 claim refs** on the remote and a dozen stale worktrees, including several
under `.claude/worktrees/`. Noise in every `git worktree list`; nobody's task yet.
