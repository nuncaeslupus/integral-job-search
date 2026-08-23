# Session handover — 2026-08-23/24 (fourth session)

## What is open

| PR | Task | Gate | State |
|---|---|---|---|
| #133 | T12 live portal connector | `connector_fixture_parse_f1 == 1.0` | open; another session holds `arsenal/claims/lo-277b` |

That is the only PR left open, and it is not this session's to touch.

Merged this session: **#131** (T25 corpus), **#132** (one priority scale), **#134** (T9
reaction elicitation), **#136** (T10 preference weights), **#137** (T18 Pareto frontier).
Issues 50, 47, 61 and 57 closed by themselves; `lo-1af2`, `lo-b422`, `lo-bacf` and
`lo-bbc7` were archived by their own PRs.

Board: 95 tasks — open 3, claimed 1, blocked 9, merged 80. `task_select` offers **T22**
(`lo-364b`, `methods_ref` link check, priority 10 — S) next, and that one has no
preconditions.

## `merge-policy: after-review` now has a definition

The owner settled it: **a bot reviews (CodeRabbit today), the session evaluates the
findings, fixes the real ones, and merges.** It is not "wait for a human". Three PRs were
merged under it this session.

Evaluating means evaluating. Of nine CodeRabbit findings, seven were real and fixed, two
were declined with reasons posted to the PR:

- *"don't mark the task merged while the PR is open"* — that is `open_task_pr.sh` working
  as designed: the archive is in the same diff so one merge closes the issue and archives
  the file atomically.
- *"remove the stale failing-command paragraph"* — arsenal template text, carried into
  every archive including `_history/lo-b422.md`. Editing one copy makes drift, not less.

## Also carried forward — read the whole robots.txt, not the block that confirms you

T12 was most of the way to a connector on tecnoempleo.com when its robots.txt was read;
the recordings were deleted and the board switched. The switch was fine; the **reason
recorded for it was wrong**, and it stayed wrong in three documents for a day.

tecnoempleo names `ClaudeBot`, `Claude`, `anthropic-ai`, `Claude-Web`, `Claude-SearchBot`
and `AnthropicBot` with `Disallow: /` — and its `User-agent: *` block disallows four
specific paths, **none of them the job listings**. Bingbot gets a `Crawl-delay`, not a
refusal. remoteok is the same shape and says outright that those crawlers may "crawl and
cite public job listings". The rule is about **who is asking**, not about the paths.
Reading the named block and stopping turned "AI crawlers excluded" into "the board says
no", which is not what either file says.

What followed (PR #138):

- `tools/collect_ads.py` had sent a **Chrome user-agent string** since T4b. robots.txt is
  addressed to whoever the client says it is, so that was evasion, not compliance — and it
  bought nothing, since `*` allowed those paths all along.
- `src/integral/robots.py` (stdlib-only, like `integral.corpus`) decides every fetch inside
  `get()`. An unreadable robots.txt refuses; only a 404 permits.
- CodeRabbit then found the hole in it: `requests` follows redirects itself, so the check
  saw the first URL and the fetch returned the last. Redirects are now followed by hand,
  one hop at a time, each asking that origin's own rules.

**Still the owner's call**: `from_tecnoempleo`/`from_remoteok` and the 53 committed
tecnoempleo ads stay. Both are on permitted paths, so there is no compliance reason to
remove them — only a preference.

## A fixture can publish the recording machine's own IP

`trabajos.com` stamps the *client's* address into every response
(`<!-- IP: … - CODPAIS:100 -->`). Saved verbatim, the fixture published a home IP — here
and in the public `integral-connectors` repo it is copied into. Redacted in both, that
repo's history rewritten, and `tests/test_connector_contract.py` now refuses an IPv4
literal in **any** fixture, because the next board will write it somewhere else.

## The thing worth carrying forward

**A regulariser will answer a question the data cannot, and say nothing about it.**

T10 fits a ridge-penalised logit. The ridge is there because a perfectly consistent
candidate separates the data and a separated logit has no finite maximum. But it also
makes the Hessian invertible when two dimensions moved together in every pair — so a
rank-deficient design did not fail, it *fitted*, and split the joint effect evenly. With
`commute` copying `remote`, both came back at −54.0 €/month: a number the candidate would
be shown and the ranking would use, invented by the penalty. CodeRabbit caught that one.

The generalisation is that **anything which guarantees an answer exists will produce one
where none is warranted**, and the check has to sit on the *input* — the rank of the
design — not on whether the solver converged. `_solve` even carried a message claiming to
detect exactly this, and could never fire.

Two shapes of the same discipline now live in the code and are worth reusing:

- `Fit.separated` — the fit is finite but its magnitudes are the penalty's choice, so it
  says so instead of quoting €566 for something worth €200.
- `rank.dominance_violations` — audits the *published* `pareto`/`dominated` lists and
  re-derives dominance from the candidates. A count the construction hands itself can only
  ever be zero.

## Mutation passes keep paying, and the useful part is the survivors

T10: 17 mutants, T18: 21. Both reached zero survivors, but only after three rounds each,
and every survivor was a real gap:

- *ridge dropped from the gradient* survived every value test, because it converges to the
  unpenalised MLE and only differs where the ridge matters. Killed by recomputing the
  penalised gradient from its definition and asserting the returned coefficients are a
  stationary point of it — two independent computations agreeing.
- *identifiability off by one* survived because the probe used three choices where the
  boundary is four. **Probes belong on the boundary.**
- *audit peers only* looked unkillable, and nearly was. Dominance is transitive, so on a
  well-formed ranking scanning published peers and scanning every candidate always agree.
  They differ on exactly one shape: a dominator **filed as collapsed under a collapser that
  does not dominate it**. The partition check stays silent because the partition is
  complete, and the dominator is no longer a published peer. Finding that case was worth
  more than the mutant.
- Two mutants I wrote were no-ops (`# noqa` on a return, `{} or {...}`). A mutation pass
  reports `killed` for a mutant that changed nothing — check the mutant, not just the tally.

## Stated ceilings, deliberately not built

- **T10's part-worths are linear in a dimension's score, not one per named level.** Seven
  dimensions × three rungs is fourteen coefficients against a twenty-choice cap. §4.3's
  ranking total is linear in score already, so this is not a lesser model than the ranker
  wants.
- **The twenty-choice cap is not enforced in `fit`.** It is the conversation's stop rule;
  a rule about talking has no place in an estimator. Nothing checks it yet — step 6's
  checkpoint script is where it belongs.
- **T18 produces no `explanations`.** That is T19 (`lo-b313`), and the offer card is T44
  (`lo-a22a`). Step 9's own gate is `explained_fraction`, owned by T19, so
  `spec-v2-steps.json` still reads `ranking: not_implemented` and correctly so.

## T26 needs a decision before anyone claims it

`task_select` offers **T26** (`lo-9e41`) next. It should not be taken as written:

1. Its gate is `ontology_hit_rate >= 0.85`, and that metric is **`unmeasured` today** —
   `tally()` refuses the ratio because the only concept source, `suggestions.json`, has no
   top-level `unmapped` key and so *cannot contradict itself*. Making it measurable is
   **T57** (`lo-7c14`), a separate open task that T26 does not declare as a dep.
2. Its job (1) — widening the matched dimensions — was **already retired by the owner**.
   The 2026-08-19 scope change inside the task file says dimensions are now coined when a
   live session turns one up, not by a corpus sweep.

Job (2) — the four candidate-trait dimensions, `side: candidate_trait`, no cues, elicited
only — is buildable now and independent of both problems. It could be split out.

## Environment

`open_task_pr.sh` **cannot open a PR for a freshly seeded task.** It hardcodes
`ARSENAL_GATE_FROM_DEFAULT=1`, so the ```bash``` block it runs is the one on `main` — which
is the placeholder that exits 1 by design and that the task text tells you to replace as
part of the work. #136 and #137 were opened by hand: verify `gate_run.sh` exits 0 on the
branch, check the task-file diff against `main` is only that one line, then `git mv` to
`_history/` with `status: merged`, put `Closes #<n>` in both the commit and the PR body,
push, and `gh pr create`. Worth an upstream issue.

GitHub Actions is still out of runner minutes: `runner_id: 0`, empty `runner_name`, jobs
ending in 3–6 seconds. Red CI here says nothing about the code. `make host-gate` locally is
the real gate.

**Do not work in the primary checkout itself** (`~/dev/`, the clone without a `-wt` suffix). Another session lives there and the
branch moves under you — it went `task/lo-1af2` → `task/lo-277b` → `connectors-sources-repo`
during this session, and an edit of mine was silently overwritten inside forty seconds. Cut
a `git worktree` off `origin/main` per task and remove it when the PR merges.
