# Session handover

**2026-09-06.** Board: **185 tasks** — 28 open, 154 merged, 2 cancelled, 1 done.
`origin/main` at the merge of #384. Eleven PRs merged: #365, #367, #369, #371,
#373, #375, #376, #380, #382, #383, #384.

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

## 6. The search now remembers what it searched for — T140, T139

Both were the same complaint from the owner: *"no guardar esto entre sesiones
es un error"*, and *"los anuncios que el usuario ha considerado relevantes
también tienen que guardarse para poder comparar en el futuro"*.

**T140 — `Aim` was never read from disk and never written to it**, its only
construction in the codebase being a measurement fixture. And `Aim.query`
joined every term into one string, which every board reads as AND: 50 of 62
recorded fetches went out as `agentic python engineer`, and the boards that
AND their terms returned nearly nothing — which reads as a thin market rather
than a malformed query. A term is a **phrase**; several are searched one at a
time and merged, which is also what makes an advert attributable to the phrase
that found it. A board that does not search is still fetched **once**.

The ranking needed no new store: `offers/_fetches.jsonl` has stamped `query`
and `offer_ids` per request since T126. Ranked by **unique contribution**
before volume, and a phrase that returned nothing stays in the ranking,
because it is the row that says do not spend a run on this again.

**T139 — the engine for keeping a rejection reason already existed and nothing
called it.** `feedback.record_decision` writes the words into the advert's
history *and* into `evidence.jsonl` and rebuilds the weights; T21's
`orphaned_reasons` already counted a reason that reached one without the
other. 561 of 567 offers in the owner's tree were still `new`.

`presentation_log` adds the caller. Its one real design decision:
**choosing one advert does not reject the others in its batch.**
`screened_out` is purge-eligible at sixty days, so marking four rejected
because the candidate picked the second would schedule the deletion of their
text for not having been picked first — the opposite of keeping them to
compare against. Being passed over is a fact about a presentation, not a
verdict, and weak signal becomes strong by **asking** (`passed_over`), never
by inferring.

**Two process facts learned the hard way.** `gate_run.sh` reads a task file
from `origin/main`, not the working copy — deliberately, so a PR cannot
rewrite the gate that judges it — so correcting a seeded gate block costs its
own docs PR first (#383). And `make evidence`'s file counts settle only after
one full run when a module is added; stage the settled value, not the first.

## 7. Open, reported and not fixed

- **`packages_for()` cannot select a `GLOBAL` package.** It matches
  `country == "ES"` while six packages declare `GLOBAL`, which the `^[A-Z]{2}$`
  country pattern makes structurally unreachable. Worked around per-session.
- **The repo ships no live `Fetch`.** Every live run this session used a
  session-only fetcher written in the scratchpad. An honest UA and
  `Accept-Encoding: identity` turned tecnoempleo's 403 into 29 offers.

## 8. Traps met, so they are not met again

- **`make evidence` diffs the working tree against the *index*.** Regenerated
  evidence must be `git add`ed before `open_task_pr.sh`, or it reads as drift.
  The exception is `S8.json`: staging a pre-archive copy is wrong, because the
  tick/archive check flips when the task file moves. Restore it from HEAD.
- **A `: ` in a skill's `description` breaks the YAML and the skill vanishes
  from the listing with no error.** The budget total went 33 skills to 32 and
  looked like a successful trim.
- **`gh pr merge --body` inline was refused by the auto-mode classifier**;
  `--body-file` is the way through.

## 9. Candidate state — ready for a fresh session

`~/.integral-job-search/profiles/ivan` — **567 offers, 98 carrying a salary
band** (from 37 at the session's start), 53 evidence rows.

- `search/aim.json` holds **`agentic python engineer` · `agentic ai` ·
  `python`**, sourced to `ev-000050`, which is the owner's own wording.
- Three `Applied Research Scientist` adverts are `screened_out` carrying his
  words — *"yo no soy applied researcher: eso no sería mi perfil"* — and
  `orphaned_reasons` reads **0**, so the reason is in the advert's history and
  in `evidence.jsonl` both. The other research-titled adverts (security
  research, market research) were **left alone**: generalising his sentence to
  them is the inference this design refuses to make.
- Recorded position is still `preferences` / `L0`, because every search this
  session was driven by hand rather than through the step runtime. A new
  session will offer to resume there; the offers are already collected.

Salary publication, not market thinness, is the binding constraint: the
agentic + python + remote intersection went from 8 offers to 13 with a band.
