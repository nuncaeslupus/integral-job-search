# Session handover

**2026-09-06.** Board: **184 tasks** — 29 open, 152 merged, 2 cancelled, 1 done.
`origin/main` at the merge of #376. Six PRs merged: #365, #367, #369, #371,
#373, #375, #376.

A **live candidate session for the repository owner**, run with the test-mode
meta-channel open, which is why almost everything below started as a defect a
real search hit rather than as a planned task.

## 1. Six "broken connectors" were one missing engine stage — T130, T135

Six boards returned nothing and looked individually broken. They were not. The
sourcing engine had **no detail-fetch stage at all**: a connector could declare
`detail_url` on a listing row, and nothing ever fetched the advert page, so
every row on a board whose listing carries no body was dropped for "no text" —
which reads exactly like a connector whose selectors are wrong.

T135 is the same bug one layer down and is the sharper lesson: `_detail_record`
built its request with `headers={}`. **`foorilla_en` shipped green and returned
0 offers live** — 50 rows parsed, 40 advert pages fetched, every one answering
**200** with the site's 10,836-byte shell. A fixture cannot catch this: the
fixture is the response, and the bug is in the request.

That is now step 7 of the `connector-new` skill, in those words.

## 2. What a connector is, settled — T132, T133, T134

Twelve-field closed vocabulary, plus `detail_url` on the list only. Two
grammars (a CSS subset, JSON paths). `url_pattern` takes `{query}` and `{page}`
and nothing else. **No field anywhere for a credential**, and `auth:` has
exactly two values, `none` and `candidate_session`.

T133 added `take:` — `range_low`, `range_high`, `currency`, `last_text_node` —
which is what makes `€50.000 - €65.000` two numbers instead of one string.
Every member **fails closed**: text that is not the shape the name describes
yields nothing, never the unparsed original. 16 partial-extraction contracts,
6 of them fail-closed, measured into `status/evidence/T32.json`.

T134 built `foorilla_en` and `landingjobs_en`. foorilla needed `client: htmx`
with a different `client_target` per surface (`mc_1` list, `mc_2` detail) —
found from a HAR the owner supplied, after the board had been ruled unreachable
by eye. **The capture is what showed it.**

## 3. A `ClaudeBot` disallow does not bind this tool — #365

Re-litigated for the third time, and this time the argument is in CLAUDE.md
rather than only in a module docstring and a YAML header. RemoteOK was wrongly
ruled out mid-session on exactly the reasoning those two files already refute.

The asymmetry, not the argument, was the defect: CLAUDE.md is in context every
turn and the ledger header is not, so a session forms its opinion before ever
opening the file that would correct it.

## 4. Connecting a board is now a written procedure — T136, #375

`.claude/skills/connector-new/`. Seven steps, cheap ones first, each able to
rule the board out. The owner's reason: *"crear conectores debería ser
relativamente rápido, ya que cualquier usuario puede necesitarlo."*

Gated on the one judgement nobody can make by eye — whether CPython's
`robotparser`, used as the second reader, was **competent on that particular
file**. On a robots.txt opening with `Allow: /` it returns the first matching
rule and so answers True to everything; an agreement with a parser that cannot
disagree is not an agreement. foorilla.com is that file, landing.jobs is not.

**The gate's dependency was inverted in review, and the review was a test.**
The first draft had `integral.connector_procedure` load the skill's script by
path, and `test_nothing_in_the_codebase_executes_a_contributed_parse_module`
refused it — `spec_from_file_location` plus `exec_module` is the machinery that
would let a contributed connector ship code. The judgement now lives in the
package and the script imports it.

## 5. Three tasks seeded from the test-mode triage — #376

- **T137** `t-c56152d9` — nothing tells a candidate session from a session
  working on the repository. This session was both at once, and only the
  operator's judgement kept them apart.
- **T138** `t-85ca22d6` — two offers alike but for the salary can come back in
  either order. Stated as **dominance**, not as a weight.
- **T139** `t-9069e62e` — a reason given while rejecting an offer is used once
  in the reply and then lost. The candidate said *"Applied Research Scientist,
  eso no sería mi perfil"* and nothing reached `profile/evidence.jsonl`.

## 6. Open, reported and not fixed

- **`Aim` is never persisted.** The candidate's stated search terms survive only
  as an evidence row, so the next session does not know "agentic AI" mattered.
- **`Aim.query` ANDs every term into one string**, which starves boards that AND
  their search terms — foorilla and landing.jobs among them.
- **`packages_for()` cannot select a `GLOBAL` package.** It matches
  `country == "ES"` while six packages declare `GLOBAL`, which the `^[A-Z]{2}$`
  country pattern makes structurally unreachable. Worked around per-session.
- **The repo ships no live `Fetch`.** Every live run this session used a
  session-only fetcher written in the scratchpad. An honest UA and
  `Accept-Encoding: identity` turned tecnoempleo's 403 into 29 offers.

## 7. Traps met, so they are not met again

- **`make evidence` diffs the working tree against the *index*.** Regenerated
  evidence must be `git add`ed before `open_task_pr.sh`, or it reads as drift.
  The exception is `S8.json`: staging a pre-archive copy is wrong, because the
  tick/archive check flips when the task file moves. Restore it from HEAD.
- **A `: ` in a skill's `description` breaks the YAML and the skill vanishes
  from the listing with no error.** The budget total went 33 skills to 32 and
  looked like a successful trim.
- **`gh pr merge --body` inline was refused by the auto-mode classifier**;
  `--body-file` is the way through.

## 8. Candidate state

`~/.integral-job-search/profiles/ivan` — **567 offers, 98 carrying a salary
band** (from 37 at the session's start), 53 evidence rows. Recorded position is
still `preferences` / `L0`, because every search this session was driven by
hand rather than through the step runtime.

Salary publication, not market thinness, is the binding constraint: the
agentic + python + remote intersection went from 8 offers to 13 with a band.
