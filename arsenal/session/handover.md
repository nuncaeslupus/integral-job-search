# Session handover

**2026-09-07/08.** Board: **195 tasks** — 36 open, 154 merged, 2 cancelled,
1 done, 2 blocked. `origin/main` at #385. One pull request open: **#396**,
which seeds T141–T150.

A **live candidate session for the repository owner**, run to the end: the tool
was taken from the first question to a **sent application** (Grafana Labs, Staff
AI Engineer, 2nd Horizon, Spain). Only step 12, interview preparation, was not
exercised. Almost everything below started as a defect that real run hit.

## 1. The application was sent, and that is the fixture we now have

Thirteen document revisions produced a two-page CV and a one-page letter, built
by hand from `docgen.py` + `build_docs.sh` + `style.css` in the candidate's own
tree. **Those tools are not in this repository** — T142 and T143 are the tasks
that bring them in, and `docgen.py` is named as the *reference implementation*,
not a sketch: its shape held across all thirteen revisions.

T149 is the task to freeze the run's **shape** as an end-to-end fixture over the
fictional candidate in `tests/fixtures/generation/master.json`. The real run
stays in `~/.integral-job-search/` and is never committed.

## 2. The profile was nearly empty when the application went out — T145

This is the finding that matters most, and it is the owner's own:

> "todo lo que dice el candidato es oro […] aquí he hecho el trabajo más yo que
> tú."

**Measured.** When the CV and letter were sent, `profile/evidence.jsonl` held
**62 rows spanning one dimension**. A backfill of what that same session had
already said produced **34 more rows spanning 26 dimensions** — Honeycomb, the
saxophone, scripts-inside-skills, the leap of faith about no longer reading his
own PRs, seven voice preferences, and the project figures cut from the CV for
being stale or unintelligible but worth keeping for an interview.

None of it was new. All of it had been said aloud, or written by the candidate
into his own CV, hours earlier.

Two causes, and T145 covers both:

- **Capture is opt-in per step.** `profile_capture.capture` is reached only from
  the intake, constraints, history, traits and feedback drivers. The
  `application` step — the whole document stretch, where a candidate talks most
  freely about how they work — has no writer attached.
- **Nothing elicits.** Even where capture existed, nobody asked. The owner
  listed the questions that were never put to him: how you work, what kind of
  projects you make, what you do with your free time, what matters to you while
  working, what you always try to improve, how you face challenges and what
  those were, how you react to rules.

**Until T145 lands, a session does this by hand**, and announces it in one line
— *"Añado lo de tus clases de pintura a tu perfil"* — rather than asking.
`source: "cv_document"` is the right source for anything the candidate writes
into a document himself; it had **zero rows** before the backfill.

## 3. A letter went out with a false claim about the candidate — T146

The letter said *"I have not used observability tools"*. The candidate had used
**Honeycomb at Flanks** for years and understands queries and traces. T45's
manifest traces assertions and has no row to demand for an **absence**, so
`cv_generation_traceability == 1.0` was green over an invented fact about the
candidate, in the direction of making him smaller, sent over his name.

`ev-000062` has been retracted in his profile and the corrected rows written.
The same task covers a **count** that went stale inside one session — *"~1,600
commits across seven repositories, six published"*.

## 4. The offer that worked came from the employer's own board — T144

Not from an aggregator. Every connector in `connectors/` points at an aggregator
or a job board and **none at an ATS host**, so "the market is exhausted" means
"our aggregators are exhausted". Greenhouse, Lever, Ashby, Workable,
SmartRecruiters, Teamtailor, Personio and Recruitee each host thousands of
employers behind one URL shape — one connector per host, bought as data.

Distinct from **T75** (prefers the employer's copy only when both copies arrive)
and from **T91** (fixes the loop, not what it has to loop over).

## 5. Two silent document corruptions, neither of which failed anything — T148

Paragraphs edited **by index** after an earlier edit had removed one: the
leap-of-faith and honest-gaps paragraphs were overwritten with duplicates of two
others. The write, the render and the paragraph count were all correct. And
`if b.get("text") is not None` dropped the letter's `to` block, so the letter was
addressed to nobody.

Both were found by running `pdftotext` and reading. `integral.ats.check_document`
passed both times, **correctly** — the text layer was intact and simply said the
wrong thing. An ATS contract asserts a document can be read, never that it says
what it should.

## 6. `files_checked` moves on any docs PR — T150, found by #396 itself

Nine task files, no Python touched, and `make evidence` went red: `453 -> 462`.
Since **ruff 0.16, `ruff format` formats Markdown**, so
`status/evidence/T125.json` counts every `.md` in the repository —
`arsenal/tasks/` alone is 189 of it. Regenerated to 463 in #396; T150 makes it a
floor.

That is T100's fix for T55 applied to a key T100 could not see:
`archive_sensitive_evidence_keys` compares the committed record across
*archiving* a task file, and adding one is not archiving one.

## What the next session should know

- **#396 must merge before any fresh clone can see T141–T150.** `task_select.py`
  reads task files from the default branch.
- **T148 and T143 are blocked on T142** — the block vocabulary lives there.
- **T145 is sized L and is the most valuable of the ten.** Everything else in
  this list is one gap; T145 is the mechanism whose absence produced several of
  them.
- **The gate is green and CI is still dead.** `bash tools/verified_gate.sh <sha>`
  is the substitute, verdict block on the pull request, and merge only while the
  head is the SHA it names.
- The candidate's evidence rows are written in **Spanish**, matching the 62 rows
  already there. The repository itself is English.
