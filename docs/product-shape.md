# How the tool is used — shape, phases, and what moves them along

**Status: a proposal with a recommendation. Needs the owner's decision before
T27 is claimed**, because the interview's design depends on it.

## The question

Is the first run one continuous conversation, or a command per phase? Are the
phases skills? Is this a plugin, a set of skills, an app? The constraint the
owner set: **Claude is the base of everything**, and a repo is therefore the
natural home.

## Recommendation: a conversation, with phases as skills and checkpoints as scripts

Not "either a flow or commands" — both, with a clear division of labour:

| layer | what it is | why there |
|-------|------------|-----------|
| **The conversation** | how the candidate actually moves through it | People do not want to learn a command set to look for work, and the elicitation methods (METHODS §2.1, §2.4) only work in dialogue. A trait cannot be captured by a form. |
| **Skills** | one per phase — the entry point, the protocol, the manner | A skill is a written procedure Claude follows, which is exactly what "the interview must be directed, and a little psychological" needs. Prose is the right medium for manner; code is not. |
| **Scripts** | the checkpoints between phases | "Is the profile complete enough to start matching?" must be a number, not a judgement call, or the tool advances when it feels like it. |
| **Files** | the state | Resumable across sessions and containers, diffable, inspectable by the candidate. `evidence.jsonl` already works this way. |

So: the candidate talks; Claude follows the phase's skill; a script says whether
the phase is done; the conversation moves on. A command per phase exists too —
`/profile`, `/collect`, `/rank` — but as a way to *resume or jump*, not the
primary path. Someone returning after a week should be able to say "let's
carry on" and have it work.

### Why not the alternatives

- **A standalone app (web or desktop).** Loses the thing that makes this
  possible: the conversation *is* the elicitation instrument. An app would end
  up rebuilding a worse chat interface, and the profile quality would fall with
  it.
- **Pure scripts and a CLI.** Fine for the corpus and the gates, hopeless for
  the interview. `set <ad-id> <dimension> <value>` is right for a labeller and
  wrong for a person describing why they left their last job.
- **Skills with no scripts.** This is the failure mode the whole repo is built
  against. Without measurable checkpoints, "the profile is complete" becomes a
  vibe, and the phases blur into a conversation that never converges.

## The phases, and what ends each one

Each checkpoint is a script with a number. A phase does not end because it feels
finished.

| # | phase | skill | ends when | measured by |
|---|-------|-------|-----------|-------------|
| 0 | Onboarding interview | `/profile` | required facts captured, ≥1 episode per elicited dimension | `interview_profile_coverage >= 0.90` (T27) |
| 1 | Preferences | `/preferences` | enough forced choices to fit part-worths | `weight_confidence` (T10) |
| 2 | Supply | `/collect` | offers normalised and deduped | `offer_schema_violations == 0` (T11) |
| 3 | Understanding | (automatic) | extraction run over the new offers | `extraction_macro_f1` (T15), `ontology_hit_rate` (T17) |
| 4 | Ranking | `/rank` | frontier and facet lists produced with explanations | `explained_fraction == 1.0` (T19) |
| 5 | Feedback | continuous | rejections and reactions recorded as evidence | `feedback_traceability == 1.0` (T21) |
| 6 | Application | `/apply` | (Phase 7, deferred) | — |

Phases 0 and 1 are the first run. Phases 2–5 are the loop the candidate lives
in afterwards, and **phase 5 feeds back into 0**: every reaction is more profile
(T28). The interview is not a thing that happens once.

## Signals that move a phase along

Three kinds, and the distinction matters because only one of them is a gate:

1. **Gates** — a script, a number, a threshold. Advance or do not.
2. **Prompts** — Claude noticing the conversation has covered what the phase
   needed and *offering* the next step. The candidate can decline.
3. **Resumption** — the candidate returning and saying "carry on". State on
   disk means this needs no ceremony.

A phase should never advance silently on a gate alone. The candidate is told
what was learned, what is still missing, and what happens next — the profile is
about them, and a tool that quietly decides it knows enough is exactly the
experience people already have with recruiters.

## Packaging

A repo containing:

```
.claude/skills/          the phase skills — the protocols and the manner
src/jobsearch/           schema, harness, extraction, ranking (exists)
dimensions/              the model (exists)
corpus/                  ads and labels (exists)
profiles/<handle>/       per-candidate state, gitignored (exists)
scripts or make targets  the checkpoints
```

Installable as a **Claude Code plugin** so the skills and commands come with it,
which is the `ai-job-search` precedent the owner cited and the lowest-friction
path for someone who already has Claude. Nothing in that choice prevents a thin
UI later — the state is files and the logic is scripts, so a web front end would
be additive rather than a rewrite.

## What needs deciding

1. **One long first interview, or several sittings?** (Open since the scope
   extension.) The recommendation, stated so it can be argued with: several
   sittings, resumable, with the first covering facts and the last job, because
   an hour of questions before any value is returned is how people abandon
   onboarding — but the *protocol* should be one continuous script, so a
   candidate who wants to finish in one go can.
2. **Are traits scored continuously, or held as episodes until enough
   accumulate?** Recommendation: held, with a stated minimum before a trait
   gets a value. A trait scored from one anecdote is a stereotype.
3. **Is this multi-user from day one?** The spec says the profile schema must
   be multi-user; if the packaging is a plugin someone installs, that is
   effectively single-user per machine. Worth settling before the profile store
   grows.
