---
name: step-00-identify
description: Step 0 (`identify`) of the candidate process — resolves who the candidate is, before any file under profiles/ is touched. Do NOT use for a session already past identification (current_step is already recorded and not `identify`) — resume there instead via the process runtime.
---

# step-00-identify

The candidate is greeted by name, told when they were last here and where they stopped, and can carry on without re-explaining themselves.

CANARY: step-00-identify-loaded-2026-08-18-f42ed484-4826385d60392bea

**Which kind of session this is** is decided before this step runs, and by one rule only: see `CLAUDE.md`, section "Which kind of session this is". This step is for a candidate session, or for a test of one.

**Required.** No candidate reaches a ranking without this step — §2.5 promises every *offered* step may be declined, and this is not one of those.

## When to load

Load when the candidate's session is at step 0 (`identify`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `identify` as where this candidate should
be. Phase: **first_run**.

## Preconditions and inputs

None — this is the one step with no preconditions, because every other step depends on this one. Nothing under `profiles/` is read or written before it completes, including on a question that seems to need no identity.

**Reads:** `profiles/*/identity.json` — display names only, to offer a list; plus, on the `--handle` path alone, the one profile's creation date (the day only), so two people who share a name can be told apart. No other file in any profile opens until a handle resolves.

## Protocol — the manner, not the mechanism

- Open by asking who this is, in one short friendly line.
- **Resolve and open with one command, never by walking `profiles/` by hand.** `uv run python -m integral.step0_open open [--name <what they said>] [--handle <handle>] [--confirmed] [--include-fiction]` does the whole of the next bullet's order: it reads display names only until the candidate has said yes, then reads the recorded position once, writes `last_activity` and returns the opening line. Run it with no flags first (a test-mode session adds `--include-fiction` so its simulated candidate is reachable) and relay its question to the candidate. **Keep what they say apart.** A name goes in `--name`, which matches display names only (NFC, caseless); `--handle` matches handles only and is used only after the tool has said several profiles share a name and the candidate has answered by giving their handle — the short name they chose. Neither opens anyone: each first returns `Is this <name>?` (on the `--handle` path, `Is this <name>, whose profile was started on <date>?` — put it to the candidate verbatim, and if the date is not theirs the answer is no: do not pass `--confirmed`, and ask them for their own handle again), and only the candidate's yes, passed as `--confirmed` on the same flag, opens the profile. The tool never lists handles before someone has said who they are (display names are the only cross-profile data step 0 shows). An `unreadable` outcome means a saved profile could not be read; it names nothing — say so, do not improvise. An `ambiguous` outcome means a profile cannot be told apart from another automatically (same name, same start day): say it needs manual help and open nothing. That is two calls for a returning candidate who is the only profile or names themselves, three when they first choose or give a handle (T207) — listing directories, opening `identity.json` or `session/state.json` one file at a time, and working the resumption out yourself is the minutes of silence the owner reported, and is not done. Say one line before the first call ("Let me find you — one moment") and say what it returned when it comes back.
- Resolve in order: an explicit name or handle (offered back for confirmation, never opened directly); exactly one profile exists — name it and ask for confirmation, never assume; otherwise list display names and ask; no match — offer to create a profile.
- On a first run, ask what they would like to be called and derive a directory-safe handle from the answer. A nickname is fine; a legal name is not required and is not asked for. The name they choose is the identifier, unless it is already taken.
- Record the language they wrote in — the rest of the process happens in it.
- **On a return, open with the substance and not only the position.** The tool's `say` line is the opening's position half, and it is the only call step 0 makes; `integral.sourcing_scope_review.resurface` builds the substance half **in the same turn, from decisions already in hand, with no further file reads** (none are stored in the profile yet), and builds the opening from the recorded position *and* every standing scope decision (§5.7): what the search was narrowed onto, and what widening was refused — a refusal is evidence and is not permanent, so it comes back too. Any of them can be corrected right there, and the correction is a new recorded decision rather than an edit to the old one. Consent nobody can review is not consent. A topic they ruled out in earlier sessions, before exclusions were kept (`search/exclusions.json`), is confirmed with them here and recorded — `uv run python -m integral.sourcing_exclusions record …` with `--term` forms in Spanish, English and Catalan (see step 2); nothing reads it back out of their old statements.

**Say this is a conversation, and say it again later.** Not a form. An anecdote, a good or
bad experience, what they do in their spare time, what they are like off the clock — all of
it tells the search something no field ever will, and none of it is a digression. Say so
here, where the tone of the whole thing is set, and say it again at least twice more before
the first ranking; a candidate who hears it once treats it as a disclaimer and answers only
what was asked.

```text
"Before anything else: this is a conversation, not a form. There's no wrong answer and nothing is off-topic — a bad week, a side project, whatever comes to mind. The more you tell me, the better I can tell two jobs apart later."
```

**Say what is happening before a silence.** Work the candidate waits through — creating their profile, running a check, saving what they have just said — is named **before** it starts, in one short line, and closed when it finishes. Acknowledge the person first, then do the work, then come back to them; never open a run of tool calls on someone who has just answered. An unexplained pause is indistinguishable from a tool that has hung, and the candidate has no way to ask.

In this step that sounds like:

```text
"Nice to meet you, Marcos. Let me get your profile set up — one moment."
…then, once it is done…
"Thanks for waiting. Here's how this works: …"
```

**Never:**

- Never read or write anything under `profiles/` before a handle resolves — not even to answer a question that seems to need no identity.
- Never guess an identity from one profile existing — confirm it, always.
- Never invent a suffix (`-2`) to resolve a handle collision — ask for something that tells the two people apart.

## Lead with the recommendation

§3.3 makes the shortcut the candidate's to take and the full run the default, and says why: the
more the tool knows, the better the results. So at the end of this step the offered skip is
never a neutral pair — recommend finishing, with the reason in a clause, then name the skip
second. The tool never takes the skip for them.

```text
"I'd recommend we finish this — it's what keeps your profile separate from anyone else's and lets everything after it be saved to you. We can stop here and look at real jobs with what I have, but nothing would be kept for you. Shall we finish?"
```

## Stop rule

A handle is resolved and confirmed, or a new profile is created. **Hard cap: three attempts** — past that, say plainly that who this is cannot be told, and stop rather than guess.

## When declined

A candidate who will not identify themselves cannot be served, and this is the one place where that is true — say so plainly and without pressure, and offer to answer general questions that touch no stored data. No evidence row is written for an unidentified session.

## Outputs

`identity.json` (handle, display name, language, locale, created_at) on a first run; `session/state.json` touched on every run.

## Boundary

**Invite forward; never close by offering to end the session.** Leaving is always allowed and
never the suggestion — the exit is offered only when the session has actually run long, or the
candidate sounds tired, and never as the standard close of this step. Naming it every time asks
someone who has answered four steps four separate times whether they would rather leave.
This governs the **exit** alone. §3.3's *offered skip* — "we can stop here and go look at real
jobs with what I have" — is a move **forward** to a provisional ranking, not a way out, and is
offered at the end of every first-run step exactly as that section requires.

What the tool says out loud when the step ends, verbatim — the settled example from the spec.
`resurface()` supplies the **substance** (the position, and one line per standing decision);
the wording below is the guide's, so the two are not expected to match string for string:

```text
"Hello again, Marcos — last time we were partway through your work history, about three weeks ago. The search is still narrowed onto employers like Acme (you accepted that in cycle 3) and still not widened outside Spain (you refused that). I'd pick your history back up first, because everything I rank with later is read out of it. Pick up there, change any of it, or something else?"
```

Writes `last_activity` immediately, before any other step begins.

If the conversation is already long, `CLAUDE.md`, section "Suggest compacting once, at a step boundary", says whether and how to suggest compacting here.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`cross_user_leaks == 0`**,
owned by **S3**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `identify` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide.

Exit 0 means that half is satisfied *and* this step's acceptance gate is built, so the run
may be read as the step having passed. Exit 1 means coverage is not met (still open, or
blocked on a missing input). Exit 2 means the candidate or step could not be read. Exit 3
means coverage is met but the gate is not built, so the step cannot be certified — a
covered step is not a passed one (D-21).

The script writes its result to the candidate's own tree at `session/checkpoint-identify.json`, never to a shared or
global path.

## Gotchas

- **Enforce the boundary below the tool, not only inside it.** A `PreToolUse` hook (S3) refuses any `profiles/` read or write outside the identified handle, regardless of what the conversation believes it is doing — a rule the process cannot violate is stronger than one it is asked to respect.
- Display names are the only cross-profile data any session ever reads, and only to offer a choice — nothing else leaves the machine.
