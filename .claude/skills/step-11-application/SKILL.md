---
name: step-11-application
description: Step 11 (`application`) of the candidate process — builds a CV and edits the candidate's own letter for one specific shortlisted offer. Do NOT use for preparing for the interview that follows an application — that is step 12, which reads this step's generated documents.
---

# step-11-application

The candidate gets a CV and a covering letter for one specific advert, drawn only from things they actually said. The CV is selected from the store; **the letter is the candidate's own, and this step edits it — it never composes it.**

CANARY: step-11-application-loaded-2026-08-18-f42ed484-1acb16a96c555ddf

**Offered.** May be declined at any time; declining never blocks a required step downstream (§2.5).

## When to load

Load when the candidate's session is at step 11 (`application`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `application` as where this candidate should
be. Phase: **per_opportunity**.

If the runtime (`integral.step_runtime.offered`) is not offering `application` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

An offer with status `shortlisted`, and `cv/master.json` with enough in it to draw on. With a thin store, say what is missing and offer Intake or History rather than producing a padded document.

**Reads:** `cv/master.json`; the offer and its extraction; `profile/stories.jsonl`; previous versions in `cv/generated/<offer_id>/`; and the digest of the candidate's other generated documents (next section).

## Lead with the recommendation

A gap is a decision the tool is better placed to frame than the candidate. Recommend: when the
gap is a skill the rest of the profile makes learnable, recommend applying and addressing it in
the letter; when it is a hard requirement the store cannot meet (a permit, a language), recommend
leaving this one. Give the reason in a clause and name the other option second — never two equal
options and a shrug.

```text
"I'd recommend applying anyway — Kubernetes is the only gap and the rest of the advert is ground you hold. You can address the gap in your own letter. Or we can leave this one. Which?"
```

## Before drafting — look at what already exists

Run the digest **before drafting any CV or letter**, so work the candidate has already polished for another offer is weighed rather than rebuilt from zero:

```bash
python -m integral.prior_documents --id <handle> [--input-dir <profiles-root>]
```

It walks every `cv/generated/<offer_id>/v<N>/manifest.json` and the document text beside it, for **all** of the candidate's offers, and prints per offer: company and title, how many versions exist, which documents each holds and any other file it did not read, the **sections beyond the standard set** (a "How I work" block, say), and the **story-bank episodes cited**. A script does this so the session does not re-read N full documents.

The reuse rule, stated once and pinned by its own test, so change it only by changing the rule:

```text
Propose reuse; never apply it silently.
A story-bank episode carried over from another offer's documents needs a fresh per-use approval for this posting and company; the earlier approval does not travel.
An episode count the digest marks UNDETERMINED is not zero: read the named documents.
```

- Where an earlier offer's framing, section or phrasing looks good, say which one and why, and propose carrying it over **adapted to this posting and this company** — never pasted. The candidate decides. Every claim in the new document still traces to a store entry, and the letter is still the candidate's own words (see "The letter is an edit").
- The digest ends with a `SKIPPED` list and **exit 1** when any manifest, document, offer record or story row could not be read. Say which items, by name, before relying on the rest; never treat an unlisted offer as one with nothing to reuse.
- No generated documents yet is a normal first run: say nothing about it and draft.

## Protocol — the manner, not the mechanism

- **Letter first, and it is theirs.** Before any letter exists, the first artefact is a prompt to the candidate, in their own language, asking for the letter in their own words, however rough — "write it as if you were telling a friend why you want this job". Not a form and not questions with slots. See "The letter is an edit" below.
- Select the CV's content from the store against what the advert asks for, and show the candidate what was chosen and what was left out — omissions are as much a decision as inclusions. **Every claim traces to a store entry.**
- Use the advert's own language, with restraint, only over ground the candidate actually holds — mirroring a phrase the candidate cannot back is a lie with good vocabulary.
- Where the advert asks for something they lack, say so and offer the options honestly — but lead with the one you recommend and why (see "Lead with the recommendation"): apply anyway and address the gap in the letter, or leave this one.
- **This is where personal details are collected** — the name to print, contact details, whatever this employer's form requires — asked for the document being produced, not gathered speculatively months earlier.

**The candidate's voice is stored, not re-corrected.** When the candidate objects to how a draft sounds, that is a rule for every later document: record it at once with `python -m integral.voice record --id <handle> --statement "<the rule in their words>" [--forbid "<regex for the phrasing>"]` (no `--forbid` makes it advisory, listed but not checked). Generation applies every stored preference, and **every generated package is shown with the notice** — `integral.voice.notice(manifest.voice_applied, manifest.voice_unreadable)` or `python -m integral.voice notice --id <handle>`: "N stored, M applied, K unreadable", each preference listed, each unreadable row listed by id. Say plainly that an unreadable row is **not** being applied, offer to re-record it in readable form, and let the candidate retract any preference that is wrong. A preference that forbids a phrase leaves out any entry containing it — including a whole job — and the manifest's omissions say which; tell the candidate when that happens.

**Relevance-weighted cutting.** When a draft runs long, score each line by three things: relevance to *this* posting, uniqueness in the document, and narrative load — whether the cover letter depends on it. If cutting the line would force a letter paragraph to be rewritten, it is load-bearing. Cut the lowest-scoring lines first, ignoring section boundaries — a weak line in a strong section goes before a strong line in a weak one. This is the method for choosing what to leave out, not a reason to stop saying so.

**The interview backtrack test.** Before a claim goes in, ask whether the candidate could comfortably explain it in an interview without backtracking — without ever needing to say "well, what I actually meant was…". Three tiers: **OK** — stands as written; **Flag it** — say so to the candidate before including it; **Never** — leave it out. Traceability is not defensibility: a true fact can still be framed past what its owner can hold up under questioning.

**Say what is happening before a silence.** Work the candidate waits through — creating their profile, running a check, saving what they have just said — is named **before** it starts, in one short line, and closed when it finishes. Acknowledge the person first, then do the work, then come back to them; never open a run of tool calls on someone who has just answered. An unexplained pause is indistinguishable from a tool that has hung, and the candidate has no way to ask.

In this step that sounds like:

```text
"Going through your letter and pulling the CV together for this one — this takes a moment."
…then, once the work is finished…
"Thanks for waiting — here's your letter with my changes marked, and the CV. …"
```

**Never:**

- Never compose the letter before the candidate has written theirs, and never rewrite it in the assistant's register.
- Never claim a qualification, a year of experience or a language the store does not hold — the generated document is the candidate's word, the one thing here that reaches a stranger.
- Never include a story-bank episode without per-use approval — recounting a failure to the tool was never consent to send it to a company.

## The letter is an edit

The rule, verbatim — the test pins these sentences, so change them only by changing the rule:

```text
The skill never writes a letter the candidate has not written first.
What the skill produces from the candidate's draft is an edit: their text with named changes, each one a sentence they can veto.
A sentence the skill wrote and the candidate did not say is marked assistant in trazabilidad.md.
Every sentence of the candidate's draft is harvested to the evidence log in the same pass.
```

Why: the first letter this repository generated for a real application was fluent, correctly sourced and rejected in three words — *"suena mucho a Claude"* — and the two strongest facts in the finished application came out of the candidate's own draft, not the store. Register is a step-11 concern: a sentence the candidate would not say is a claim about the candidate that no entry supports.

1. Ask for the draft (above). If the candidate has none and declines to write one, the letter is declined (see "When declined"); do not compose a substitute.
2. Harvest the draft in the same pass: `integral.application_authorship.harvest_draft(store, draft, recorded_at=...)` writes each sentence as an evidence row with `kind="candidate_statement"`, `source="application_draft"`, and returns the row ids.
3. Edit surgically. Report each change by name and let the candidate veto it. A rewrite in the assistant's register is the failure this step exists to prevent. When a gap needs a sentence the candidate has not said, ask them for it; do not write it for them.
4. Record who wrote each paragraph of `carta.md` in a `## Authorship` table in `trazabilidad.md`, one row per paragraph (headings excepted), `| paragraph number | author | evidence ids | changes |`. Authors are `candidate` (their words untouched: the paragraph is exactly the cited sentences, in order), `edited` (their sentence with a named change, so `changes` must say what changed, not `-` or `none`, and the paragraph must still contain most of the cited sentence) and `assistant` (nothing the candidate said, so no evidence ids). `candidate` and `edited` must cite the harvested ids. `carta.md` has no headings, because a heading is a line nobody on record wrote.
5. Before ending the step run `integral.application_authorship.check_package(<cv/generated/<offer_id>/v<N>>, store)`; a paragraph with no named author, or a candidate source that is not a live harvested row, fails it.

This is not a template with the candidate's phrases pasted in. Whether the letter can be read aloud without flinching is for the candidate to say, and no gate checks it; the gate checks only the mechanical half, that the package says who wrote each paragraph.

## Public projects

A public project in `cv/master.json` is an `episode` with the link in `text`; this step surfaces such a link only through the story-bank route, pinned verbatim by its test. (Episodes step 3 writes to `profile/evidence.jsonl` do not reach `cv/master.json` yet, so `approval.prepare` cannot see them; that path is a follow-up.)

```text
A public project is offered, never added: when the advert is in software or data and the story bank holds an episode whose text carries a link, propose it for this posting and company.
It goes in the letter only as an approved episode, with the link exactly as the candidate gave it; a declined or unanswered proposal sends nothing.
```

The approval is per use (see "Never" above): the earlier approval for another offer does not travel, and no step writes a link into the CV by itself.

## An open application

A candidate who wants to send a CV to an employer's open form has no advert. Record it with `integral.presentation_log.record_open_application(store, company, url, form_questions, at=...)`, never with a hand-written `Offer`; it is stored shortlisted, so this step accepts it. What differs, pinned verbatim by its test:

```text
There is no advert to tailor against: select the CV from the store and what the employer's own site says it does, and never claim a requirement nobody stated.
The employer's own site is the reference for the language, the products and the colours.
A form answer takes the place of the letter: answer each recorded form question in the candidate's own words, asked for first, edited and harvested exactly as a letter is.
```

## Form answers

Most ATS forms ask free-text questions (why us, notice period, salary expectation, work permit, where you heard of us), often with a character limit. They are an output of this step, not a scratch file beside the documents.

- **Drafted from store entries only.** Each answer is a `integral.form_answers.FormAnswer(question, text, char_limit, evidence_ids)`: it cites the live evidence rows it rests on, as the letter's authorship table does. A row that is missing, retracted, a `reaction` or an `outcome` (a step-10 rejection reason or an interview lesson never leaves the machine) backs nothing. Every word of the answer, whatever its length, must occur in a cited row (only articles, "I"/"my", "and"/"or" and plain prepositions are exempt; "am", "is", "was" and the like must occur in a cited row too), so an invented permit, certification or tool (UK, EU, PhD, AWS) is refused, and a hyphenated word ("non-EU", "ex-employee") is one word whose prefix cannot be dropped, however common the words around it. A number must be in the words cited. A cited row that holds a denial anywhere in it (any line, any sentence; "without", "sin", "zero" and a bare "n't" count) is quoted **whole or not at all**, and citing it without quoting it whole is refused: the answer carries all of that row's words, token for token (a leading list marker such as "1." or "-" does not count), and no word of the answer outside such a quote may rest on it. So a "No." or "Not yet." on a later line, a hard-wrapped "I do not / need", a scope or condition on another line, an attribution or an abbreviation before the denial, and a claim added after the quote are all refused by the one rule; a row with no denial in it can still be reworded freely. This is stricter than it looks, on purpose: you cannot take the denial out of a longer row, so when the candidate wants only that part sent, ask them to restate it as a row of its own. The question is a line sent to the employer too: one short sentence, with no first-person word, number or denial. An answer with no store source is not written; ask the candidate for the fact instead.
- **A stated limit is kept.** Fit an answer with `integral.form_answers.shorten(text, limit)`: it keeps whole leading sentences and refuses rather than cut one. If the first sentence alone is over the limit, ask the candidate for a shorter one.
- **Story-bank episodes need per-use approval.** An `episode` row may be cited only for an episode approved for this version (`approved_episodes`), and the document sweep treats the answers' lines like the letter's.
- **Staged with the payload.** Pass the answers to `integral.approval.prepare(..., form_answers=(...))`. They are written as `form_answers.md`, so they are a payload document, in the digest the candidate confirms, and `stage_send` puts them in `send/`; the record `form_answers.json` stays beside, never inside it. An answer line edited afterwards, or whose cited row is retracted, is no longer backed and staging is refused.

## Stop rule

A CV and the candidate's letter (edited, with its authorship recorded) exist for this offer and the candidate has approved them, or has parked them. **There is no cap on versions:** as many rounds as the candidate needs, each one a new `v<N+1>`.

## When the candidate says it was sent or the advert closed

When the candidate says the application went out, or the advert has closed, run `uv run python -m integral.applications mark <offer_id> applied|expired|rejected --id <handle> [--at DATE] [--reason TEXT]` instead of a scratch script: it writes the lifecycle transition and the application status under one timestamp and refuses a transition the lifecycle table forbids. An application with no advert is created by `record_open_application` (stored `shortlisted`); once it is sent, mark it `applied` with this same command.

## When declined

Offered per offer. Declining generates nothing and leaves the offer `shortlisted`. A candidate who writes a letter but wants no edits to it gets it back unchanged, with the authorship table all `candidate`; one who wants no letter at all, or only the CV, gets exactly that — the skill never writes one in their place.

## Outputs

`cv/generated/<offer_id>/v<N>/` — CV and letter, versioned, plus a manifest of which store entries each claim came from. On send, `applications/<offer_id>/` records what went and when, immutable thereafter.

**`send/` is the output of this step, for every candidate.** Once the candidate has approved the payload, collect the final files with `integral.approval.stage_send(store, master, offer_id, version, confirms=<payload digest>)`: it makes `cv/generated/<offer_id>/v<N>/send/` holding exactly the payload's documents (CV and letter), byte for byte what was measured, and nothing else — no manifest, traceability table or notes. Hand the candidate that one folder; do not collect files by hand. What is in `send/` is what was approved: `integral.approval.verify_send` names any file edited, added, removed or linked in afterwards, and `record_sent` refuses a version whose `send/` fails it. Staging uses the same check as `record_sent` (re-measured documents, digest confirmation), so nothing unapproved can be put there. The folder holds the approved Markdown plus the **sendable set derived from it** (`integral.send_set`, T338), so nothing is finished by hand: `<First>-<Last>-CV.pdf` and `<First>-<Last>-Cover-Letter.pdf` (the name comes from `identity.json`'s display name; never `cv.pdf`), `<First>-<Last>-Application.pdf` (one PDF for a portal that takes a single upload, **letter first**, then the CV) and `Cover-Letter.txt` (the letter as plain text for a portal with a text box). The PDFs need the optional engine (`uv sync --extra pdf`); without it `stage_send` refuses before writing anything. `verify_send` covers every file it writes: the text file is regenerated from the approved letter and compared, a PDF must be a PDF whose text layer holds the approved document(s) re-rendered from the version dir (the letter, then the CV, in the combined file), so a PDF rewritten together with `send.json` is refused, and the set of names must be exactly this one. Reading a real engine's PDF needs `pypdf` (`uv sync --extra cv`); without it `verify_send` reports the PDFs as unchecked. A display name with no Latin letters yields the stem `Candidate`. Rendered HTML other than what feeds those PDFs is not part of the approved payload.

**Every delivery ends with a link and a path.** The offer directory is named by a digest (`cv/generated/sha256:…`), so the first time an offer is generated, add a symlink beside it named for the employer with `integral.generate.link_employer(store, offer_id, <employer-slug>)`, a relative link inside `cv/generated/`; it refuses a slug that already names another offer, so for a second offer from the same employer use `<employer-slug>-<role-slug>` — and at the end of every delivery print `cv/generated/<employer-slug>/v<N>/send` as an absolute path on its own line, as `file://` and plain, so the candidate can click it. Never copy the files elsewhere: a copy can drift from what was approved, a link cannot.

Each version also gets `carta.html` and `cv.html`, rendered from the Markdown by `integral.application_render.render_document(markdown, title=..., kind="letter"|"cv", photo=<optional bytes>, photo_mime=..., lang=..., palette=<optional BrandPalette>)` — one printable file each (A4, inline style, photo as a `data:` URI). The Markdown is the source; never edit the HTML by hand, regenerate it.

**For the printable CV and letter, fill the block schema; never hand-write HTML.** Write `cv.json` and `letter.json` beside the Markdown in the version directory (blocks `header`, `summary`, `section`, `job`, `project`, `bullets`, `grid`, `board`; `letter`, `to`, `text`, `sign`; see `integral.document_render.sample_cv` and `sample_letter`), then run `python -m integral.document_render version cv/generated/<offer_id>/v<N> --country <recipient country> --language <lang>`. The accent is not yours to pick: the command reads it from the version's recorded `palette.json` (the colours paragraph below), refuses a version that has none, and refuses an `--accent` that is not the measured one, so a hand colour never overrides a measurement; measure the employer's site first. It writes `cv.html`/`cv.pdf` and `letter.html`/`letter.pdf` beside the JSON, with the page size taken from the country. The PDF needs the `pdf` extra (`uv run --extra pdf`); without it the command fails and writes nothing, HTML included. It refuses a version that has a `send/` folder (a sent version is never re-rendered; regenerate as `v<N+1>`), and it names a missing `cv.json` or `letter.json` on stderr while rendering the other. For one file, use `python -m integral.document_render render <doc.json> --output x.html --pdf x.pdf`.

**Colours are the employer's own, and measured by shipped tools (T342).** Open the employer's site in the browser, paste `tools/measure_colours.js` into the console and run `copy(JSON.stringify(measureColours()))`: it returns `{"#rrggbb": elements}`, each rendered element counted once per colour. Save that JSON and run `uv run python -m integral.brand_measure --site <url> --counts <file> --root <profiles root> --handle <handle> --offer <offer_id> --version <N> --trazabilidad <path to trazabilidad.md>`. It prints the palette's `trazabilidad_section`, appends it to the file, and records the counts in the version's `palette.json` (`--json` prints the palette instead). `stage_send` renders the sendable PDFs with the palette those recorded counts give (`integral.brand_measure.palette_for`) and **refuses a version that has no `palette.json`**, so the accent is never one you picked; the counts are `#rrggbb` in lower case only, and the CLI refuses any other spelling instead of dropping it. The snippet converts `oklch()`, `oklab()`, `lab()`, `lch()` and `color()` values to sRGB, and throws on a colour function it cannot read. For your own `render_document` calls pass the same `palette=`. `integral.brand_measure.versions_without_measurement(store)` lists the generated versions that still have no measurement: record one for each before staging (staging refuses without it). The palette keeps the exact brand accent for rules and a darkened variant (at least 4.5:1 on the paper) for text; if the site cannot be read, save `{}` and it falls back to a neutral palette and says so. Never pick a brand colour by guess.

**The applications board.** When the candidate asks for the list of what they have sent, run `python -m integral.applications_board --id <handle> [--input-dir <profiles-root>]`; it writes `reports/applications.html` from the records on disk (employer, role, date, status, advert and tracking links, and per application what the advert required against what the profile holds, lacks or does not record). A tracking link the candidate reports later goes in with `--track <offer_id> <url>`, never into `applications/`. A status-only application shows the day it was noted, and the page says so; do not call that the send date, and do not call a skill "lacking" when the board says "not on record".

## Boundary

**Invite forward; never close by offering to end the session.** Leaving is always allowed and
never the suggestion — the exit is offered only when the session has actually run long, or the
candidate sounds tired, and never as the standard close of this step. Naming it every time asks
someone who has answered four steps four separate times whether they would rather leave.
This governs the **exit** alone. §3.3's *offered skip* — "we can stop here and go look at real
jobs with what I have" — is a move **forward** to a provisional ranking, not a way out, and is
offered at the end of every first-run step exactly as that section requires.

What the tool says out loud when the step ends, for example:

```text
"That's the CV and your letter for the Girona role. I left your wording alone except for two marked changes, led the CV with the migration work and left out the teaching — say if any of that is wrong. I'd send it today rather than polish it, because the posting is already a fortnight old. Ready to send, or sit on it?"
```

Writes `last_activity`.

If the conversation is already long, `CLAUDE.md`, section "Suggest compacting once, at a step boundary", says whether and how to suggest compacting here.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`cv_generation_traceability == 1.0`**,
owned by **T45**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `application` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide.

Exit 0 means that half is satisfied *and* this step's acceptance gate is built, so the run
may be read as the step having passed. Exit 1 means coverage is not met (still open, or
blocked on a missing input). Exit 2 means the candidate or step could not be read. Exit 3
means coverage is met but the gate is not built, so the step cannot be certified — a
covered step is not a passed one (D-21).

**`cv_generation_traceability` is built (T45), so this checkpoint can reach 0.** The gate is a
build-time measurement over `manifest.json` against the store, not something this skill computes
or asserts in prose — what it means for the conversation is that every claim in a generated
document names the store entry it came from, and a line that names none is a failure the gate
sees. An omission is a decision too: say what was left out, and let the candidate say it was
wrong.

The script writes its result to the candidate's own tree at `session/checkpoint-application.json`, never to a shared or
global path.

## Gotchas

- **Never overwrites.** A regeneration writes `v<N+1>` and preserves every earlier version — an earlier one may already be with an employer.
- The tool stops one step short of sending: the documents or the text to paste. The candidate presses send.
