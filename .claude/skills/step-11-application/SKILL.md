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

**Reads:** `cv/master.json`; the offer and its extraction; `profile/stories.jsonl`; previous versions in `cv/generated/<offer_id>/`.

## Protocol — the manner, not the mechanism

- **Letter first, and it is theirs.** Before any letter exists, the first artefact is a prompt to the candidate, in their own language, asking for the letter in their own words, however rough — "write it as if you were telling a friend why you want this job". Not a form and not questions with slots. See "The letter is an edit" below.
- Select the CV's content from the store against what the advert asks for, and show the candidate what was chosen and what was left out — omissions are as much a decision as inclusions. **Every claim traces to a store entry.**
- Use the advert's own language, with restraint, only over ground the candidate actually holds — mirroring a phrase the candidate cannot back is a lie with good vocabulary.
- Where the advert asks for something they lack, say so and offer the options honestly: apply anyway and address the gap in the letter, or leave this one.
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

## Stop rule

A CV and the candidate's letter (edited, with its authorship recorded) exist for this offer and the candidate has approved them, or has parked them. **Hard cap: three regeneration rounds per offer** — each new CV version or fresh round of edits to the letter counts — after which the useful move is to talk about what is wrong rather than generate a fourth.

## When declined

Offered per offer. Declining generates nothing and leaves the offer `shortlisted`. A candidate who writes a letter but wants no edits to it gets it back unchanged, with the authorship table all `candidate`; one who wants no letter at all, or only the CV, gets exactly that — the skill never writes one in their place.

## Outputs

`cv/generated/<offer_id>/v<N>/` — CV and letter, versioned, plus a manifest of which store entries each claim came from. On send, `applications/<offer_id>/` records what went and when, immutable thereafter.

**`send/` is the output of this step, for every candidate.** Once the candidate has approved the payload, collect the final files with `integral.approval.stage_send(store, master, offer_id, version, confirms=<payload digest>)`: it makes `cv/generated/<offer_id>/v<N>/send/` holding exactly the payload's documents (CV and letter), byte for byte what was measured, and nothing else — no manifest, traceability table or notes. Hand the candidate that one folder; do not collect files by hand. What is in `send/` is what was approved: `integral.approval.verify_send` names any file edited, added, removed or linked in afterwards, and `record_sent` refuses a version whose `send/` fails it. Staging uses the same check as `record_sent` (re-measured documents, digest confirmation), so nothing unapproved can be put there. The folder holds the Markdown documents only; rendered HTML is not part of the approved payload.

Each version also gets `carta.html` and `cv.html`, rendered from the Markdown by `integral.application_render.render_document(markdown, title=..., kind="letter"|"cv", photo=<optional bytes>, photo_mime=..., lang=..., palette=<optional BrandPalette>)` — one printable file each (A4, inline style, photo as a `data:` URI). The Markdown is the source; never edit the HTML by hand, regenerate it.

**Colours are the employer's own.** Measure the employer site's colours (count the elements carrying each computed colour), call `integral.brand_palette.extract_palette({colour: count})`, pass the result as `palette=` to `render_document`, and append `trazabilidad_section(palette, site_url)` to `trazabilidad.md` so the measurement is on record. The palette keeps the exact brand accent for rules and a darkened variant (at least 4.5:1 on the paper) for text; if the site cannot be read it falls back to a neutral palette and says so. Never pick a brand colour by guess.

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
