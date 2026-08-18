---
name: step-07-sourcing
description: Triggered by a candidate's session at step 7 (`sourcing`) of the job-search process (`status/spec-v2-steps.json`) — fetches and dedupes live offers against the candidate's constraints. Do NOT use for reading what an offer's text actually means — that is step 8, which runs after this step's offers land.
---

# step-07-sourcing

The candidate gets live offers worth looking at, with the stale ones retired and nothing they have already rejected coming back.

CANARY: step-07-sourcing-loaded-2026-08-18-f42ed484-55019180c91ff6e0

**Required.** No candidate reaches a ranking without this step — §2.5 promises every *offered* step may be declined, and this is not one of those.

## When to load

Load when the candidate's session is at step 7 (`sourcing`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `sourcing` as where this candidate should
be. Phase: **loop**.

If the runtime (`jobsearch.step_runtime.offered`) is not offering `sourcing` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

`profile/constraints.json`, which decides where and what to search for. Required; runs on a schedule, on request, or when constraints change.

**Reads:** `profile/constraints.json`; `offers/*.json` and `offers/tombstones.jsonl` for dedup; connector configuration.

## Protocol — the manner, not the mechanism

- Mostly automatic, with one conversational duty: establish how far the search can travel, at the moment it becomes relevant — remote, commuting distance, relocation, and cross-border employment (employed or contracting, paid where, taxed where).
- Reach beyond the obvious portals to boards specialised in the candidate's field, and go to employers directly where the field has obvious ones.
- **Deduplication is by similarity, not by hash** — the same job at two boards is rarely byte-identical.
- Where a source needs a login, drive the candidate's **own browser session** rather than storing credentials — nothing to leak, nothing to rotate.

**Never:**

- Never store a credential in a connector file — authenticated sources use the candidate's own browser session.
- Never send anything but constraints (role, place, band) to a job source — no profile, episode, trait or CV content.

## Stop rule

All configured sources have been polled and results normalised. **Hard cap: a per-run offer ceiling**, so one badly-scoped query cannot deliver hundreds of adverts nobody will read.

## When declined

Not applicable to the fetch, which is required. The conversational reach question is declinable per question: an unanswered mobility question leaves the reach at its current setting.

## Outputs

`offers/<offer_id>.json` (normalised, status `new`), tombstone updates, expiry marks on offers no longer live at source.

## Boundary

What the tool says out loud when the step ends, verbatim — the settled example from the spec:

```text
"Fourteen new, six duplicates, and four have closed since last week. Want to see the new ones ranked?"
```

Writes `last_activity`.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`offer_schema_violations == 0`**,
owned by **T11**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `sourcing` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide. Exit 0 means that half is satisfied; exit 1 means it is not (still open, or blocked on
a missing input); exit 2 means the candidate or step could not be read. The script writes its
result to the candidate's own tree at `session/checkpoint-sourcing.json`, never to a shared or
global path.

## Gotchas

- An advert already stored is updated, not duplicated; one matching a tombstone by canonical URL or normalised text hash is **not re-added as new**.
- Purge runs here: offers never shortlisted and older than 60 days lose their body and keep their tombstone — reported rather than done silently.
