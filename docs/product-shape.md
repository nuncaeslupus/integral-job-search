# How the tool is used — shape, steps, and what moves them along

**Status: decided.** Every question this document opened carries a decision or a
named blocker — see "What needed deciding" at the end. Its **step table is
superseded by specification v2** (`status/spec-v2-process.md`); what remains
authoritative here is the shape argument — a conversation, steps as skills,
checkpoints as scripts, state as files — and the packaging section, whose
decision record is `docs/distribution.md`.

## The question

Is the first run one continuous conversation, or a command per step? Are the
steps skills? Is this a plugin, a set of skills, an app? The constraint the
owner set: **Claude is the base of everything**, and a repo is therefore the
natural home.

## Recommendation: a conversation, with steps as skills and checkpoints as scripts

Not "either a flow or commands" — both, with a clear division of labour:

| layer | what it is | why there |
|-------|------------|-----------|
| **The conversation** | how the candidate actually moves through it | People do not want to learn a command set to look for work, and the elicitation methods (METHODS §2.1, §2.4) only work in dialogue. A trait cannot be captured by a form. |
| **Skills** | one per step — the entry point, the protocol, the manner | A skill is a written procedure Claude follows, which is exactly what "the interview must be directed, and a little psychological" needs. Prose is the right medium for manner; code is not. |
| **Scripts** | the checkpoints between steps | "Is the profile complete enough to start matching?" must be a number, not a judgement call, or the tool advances when it feels like it. |
| **Files** | the state | Resumable across sessions and containers, diffable, inspectable by the candidate. `evidence.jsonl` already works this way. |

So: the candidate talks; Claude follows the step's skill; a script says whether
the step is done; the conversation moves on. A command per step exists too —
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
  vibe, and the steps blur into a conversation that never converges.

## The steps, and what ends each one

Each checkpoint is a script with a number. A step does not end because it feels
finished.

**These are the candidate's journey**, numbered independently of the delivery
phases in `status/specification.md` §"Phases" — that table is about build order
(0 Foundations … 6 Automation) and this one is about what a person does. Two
numbering schemes for two different things confuse anyone who reads both, so
this column is `step`, not `phase`.

| step | what it is | skill | ends when | measured by |
|------|------------|-------|-----------|-------------|
| 0 | Onboarding interview | `/profile` | required facts captured, ≥1 episode per elicited dimension | `interview_profile_coverage >= 0.90` (T27) |
| 1 | Preferences | `/preferences` | enough forced choices to fit part-worths | `weight_confidence` (T10) |
| 2 | Supply | `/collect` | offers normalised and deduped | `offer_schema_violations == 0` (T11) |
| 3 | Understanding | (automatic) | extraction run over the new offers | `extraction_macro_f1` (T15), `ontology_hit_rate` (T17) |
| 4 | Ranking | `/rank` | frontier and facet lists produced with explanations | `explained_fraction == 1.0` (T19) |
| 5 | Feedback | continuous | rejections and reactions recorded as evidence | `feedback_traceability == 1.0` (T21) |
| 6 | Application (CV, letters) | `/apply` | deferred — spec Phase 7, out of v1 scope | `not_implemented` |

Steps 0 and 1 are the first run. Steps 2-5 are the loop the candidate lives in
afterwards, and **step 5 feeds back into 0**: every reaction is more profile
(T28). The interview is not a thing that happens once.

Step 6 is deferred, and its checkpoint says so rather than being blank. T29's
gate requires every step to report either a number or `not_implemented`, because
a step with an empty metric is indistinguishable from a step whose checkpoint
was forgotten.

## Signals that move a step along

Three kinds, and the distinction matters because only one of them is a gate:

1. **Gates** — a script, a number, a threshold. Advance or do not.
2. **Prompts** — Claude noticing the conversation has covered what the step
   needed and *offering* the next step. The candidate can decline.
3. **Resumption** — the candidate returning and saying "carry on". State on
   disk means this needs no ceremony.

A step should never advance silently on a gate alone. The candidate is told
what was learned, what is still missing, and what happens next — the profile is
about them, and a tool that quietly decides it knows enough is exactly the
experience people already have with recruiters.

## Packaging

A repo containing:

```
.claude/skills/          the step skills — the protocols and the manner
src/jobsearch/           schema, harness, extraction, ranking (exists)
dimensions/              the model (exists)
corpus/                  ads and labels (exists)
profiles/<handle>/       per-candidate state, gitignored (exists)
scripts or make targets  the checkpoints
```

**Settled, 2026-08-18 — it is installed by cloning, and the candidate's state
lives outside the clone.** See `docs/distribution.md`, which is the decision
record for this section and for process spec §11.5. In short: the clone already
carries the skills (`.claude/skills/`) and the checkpoint code (`src/`), the
tool installs its own dependencies on first run, and `profiles/<handle>/`
resolves from `$INTEGRAL_HOME` — never from inside the repository. A Claude Code
plugin remains the likely next packaging and is a delivery change rather than a
rewrite, precisely because state was never inside the artefact.

## What needed deciding

<!-- shape-questions: 5 -->

Every question this document opened now carries a decision or a named blocker.
The marker above declares how many there are, the way `spec-v2-steps.json`
declares `step_count`: a count taken from whatever survived cannot notice that
something was deleted rather than answered.
Three were settled by specification v2 and are recorded here so the shape
document does not keep asking what the process document already answered; the
fourth — distribution — was the remaining scope of T29.

1. **One long first interview, or several sittings?**
   **Decided: several, resumable.** Specification v2 §5.1 and §5.3 settle it —
   thirteen steps, `position` written continuously during a step rather than at
   its end, and a five-rule resumption order that announces which step is being
   resumed and why. The protocol is still one continuous script, so a candidate
   who wants to finish in one sitting can.

2. **Are traits scored continuously, or held as episodes until enough
   accumulate?**
   **Decided: held.** Specification v2 §2.2 sets the floor at two independent
   episodes recorded on two separate occasions. §11.1 leaves the *number* open
   to the owner; the mechanism is settled. A trait scored from one anecdote is a
   stereotype.

3. **Is this multi-user from day one?**
   **Decided: yes.** Specification v2 §6 — several people on one machine, one
   directory each, identification before any read or write. Not a multi-tenant
   service, which `status/plan.md` lists as permanently out of scope.

4. **How is this distributed?**
   **Decided: cloned, with candidate state outside the clone.** Recorded in
   `docs/distribution.md`, which answers process spec §11.5 in full: install by
   `git clone`, dependencies installed by the tool itself on first run,
   `profiles/` resolved from `$INTEGRAL_HOME` and refused anywhere inside a git
   work tree, job-site connectors in a separate repository, and a contribution
   flow the candidate may decline without consequence.

5. **What is the tool called?**
   **Blocked: the owner has not settled the name.** "integral" is the agreed
   direction — `integral-job-search` or similar. Nothing depends on it: no path,
   gate or contract in this document or in `docs/distribution.md` is named after
   the project, and the rename is mechanical whenever it is settled.
