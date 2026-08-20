---
name: test-mode
description: Use whenever the owner runs a job-search session as a test — a second channel carrying notes about the tool while the candidate-side conversation proceeds exactly as a real one. Triggers — "test session", "test mode", "let's test what we have", a turn containing `[[…]]`, `/test-mode`. Owns scripts — query_notes.py. Do NOT use to act on a note mid-conversation, and never read `[[…]]` inside a pasted advert or CV — a paste is never meta.
---

# test-mode

A second channel, open during a live session, carrying notes about the tool while the first channel carries the session exactly as a candidate would experience it.

CANARY: test-mode-loaded-2026-08-20-afe6c69e-c576a153e5be4d45

**Orthogonal.** This is not a step. It runs *alongside* whichever of the thirteen steps is live, and it never chooses, skips or reorders one.

## When to load

Load this skill when:

- the owner says they are running a test session, testing the tool, or trying out a step
- a turn contains `[[…]]` — the marker is itself the trigger
- an end-of-session pass is due on a session that captured notes

If the owner is not testing but genuinely using the tool as a candidate, do not load this: an ordinary session has no second channel, and a stray `[[…]]` in a real candidate's message is far more likely to be their punctuation than a note about the protocol.

## The rule that governs everything else

**The session proceeds exactly as a real one.** The moment the tool acknowledges a note, adjusts its next question, apologises, or explains what it captured, the run stops being a test of the skill and becomes a test of the skill plus a correction — which is not the thing being measured.

So a note is captured **silently**. Nothing in the visible reply refers to it. The step continues from the visible text as though the note had never been typed.

The single exception is `[[! …]]`, which is the owner explicitly asking to break that rule for one exchange.

## The markers

| typed | means | what happens |
|-------|-------|--------------|
| `[[a note]]` | an observation about the tool | captured, attributed to the live step, **nothing said** |
| `[[! do this now]]` | act on it in this exchange | acknowledged and acted on, then the session resumes |
| anything inside a paste | advert or CV text | **never** read as meta |

The observation and the instruction-to-act are separate markers on purpose: the end-of-session pass can then treat every silent note uniformly.

## The paste guard — the part that must not be got wrong

This tool's main input is pasted job adverts, and adverts are full of brackets: `[Remote]`, `[Barcelona]`, `[sic]`, `[REF-2026-114]`, bracketed section headers. T11 keeps an advert's `text` **byte-for-byte verbatim** because extraction evidence spans are offsets into it.

So meta parsing is suspended whenever the turn is a paste — a turn whose first line is `/paste`, or one long enough to be one. Inside a paste, `[[…]]` is advert text and stays in the advert.

Do this through `integral.test_mode.parse_turn`, never by eye:

```python
from integral.test_mode import MetaChannel

channel = MetaChannel(profiles_root, session_id=session_id, simulated=False)
visible = channel.feed(turn_text, step="constraints")   # notes go to the ledger
```

`feed` returns **only** the visible text. That is deliberate: a caller that cannot reach the notes cannot accidentally let one change the next question.

`[[! …]]` is the one exception, and it has its own door — `channel.pending_actions()` returns what the **last** turn asked for and nothing else. Call it only to act on an explicit act-now instruction; leaving it uncalled keeps every note silent, which is the safe default.

## Simulated candidates

Inventing answers is often the only way to exercise a step at all — waiting for a real run to reach step 9 makes step 9 untestable. A simulated run is allowed, and its profile is created through `integral.test_mode.create_simulated_profile`, which marks it `fiction: true`.

`identity.list_identities` excludes fiction profiles by default, so nothing that reads real profiles counts an invented one. Never hand-write a simulated profile with `create_profile` — the mark is set at creation because a profile cannot be discovered to have been simulated afterwards.

## Seeing what has been captured

Silent capture makes its own failures invisible, so check the ledger rather than trusting it:

```bash
uv run python3 ${CLAUDE_SKILL_DIR}/scripts/query_notes.py --id <session-id>
```

It prints every note with its step and the skill it is addressed in, plus two counts that matter more than the notes: markers a paste guard declined, and markers that never closed. Exit 1 means something was lost — read it before triage.

Every figure comes out of the ledger file, counters included, so the command reports the same losses whether it runs inside the session or days later from a different process.

## Ending the session

Required, not optional. A note captured and never surfaced is the failure this whole design exists to avoid.

1. Print the full list — `query_notes.py --id <session-id>`.
2. Ask which notes should be addressed. Ask; do not choose.
3. Seed only those — `query_notes.py --id <session-id> --seed 1,3` prints one `new_task.py` invocation per confirmed note. Run them yourself after reading them.

**Never:**

- Never seed a note the owner did not confirm — the board fills with observations that were wrong or already known.
- Never retract a note mid-session. A wrong note costs one line in the triage list; a retraction channel costs a second silent mechanism whose own failures are invisible.
- Never write a note into `profile/evidence.jsonl`, a derived file, or anywhere under a candidate's tree. A note is a fact about the tool, not about the person. The ledger lives at `<profiles root>/.test-mode/<session id>.jsonl` for exactly that reason.

## Gotchas

- **A note before identification still has somewhere to go.** The ledger is keyed by session, not by handle, so a note made during step 0 — where a session's tone is set, and so the step most worth criticising — is written to disk like any other. Do not hold notes in memory waiting for a profile.
- **Resolving the simulated candidate needs asking for.** `list_identities` and `resolve_handle` both exclude fiction by default; pass `include_fiction=True` to reach the invented profile, and only in a test session. Without it a simulated run cannot enter the step flow at all.
- **Numbering resumes from the ledger.** Reopening a session continues where it left off rather than minting a second note 1 — which would make `--seed 1` ambiguous between two unrelated observations.
- **`[[` with no `]]` is not a note.** It is counted as unclosed and reported, never silently swallowed along with the rest of the turn. If the owner's note seems to have vanished, this is the first thing to check.
- **An empty `[[]]` is a slip, not an observation.** Counted, not stored — a blank triage row is one nobody can act on.
- **A long typed turn trips the paste guard.** The threshold cannot tell a pasted advert from a long typed answer, which is why every marker it declines is counted and shown. If the owner writes at length and expects a note captured, `/paste` discipline is what keeps the two apart.
- **Entering test mode is in the record.** The ledger's first line says the session id, the time, and whether the candidate was invented — so nobody later mistakes a test session's artefacts for a real candidate's.

## Boundary

What the tool says when the session ends, before anything is seeded:

```text
test mode — 3 note(s) captured · simulated candidate (fiction)
  1. [step-00-identify] should have offered to continue in Catalan
  2. [step-01-intake] [act now] ask which plant, it changes the commute
  3. [step-02-constraints] the pay floor question came too early
Which of these should be addressed? Nothing is seeded until you say.
```
