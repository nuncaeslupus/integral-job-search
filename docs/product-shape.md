# How the tool is used — shape, steps, and what moves them along

**Status: decided.** Every question this document opened carries a decision or a
named blocker — see "What needed deciding" at the end. Its step list follows
specification v2 (`status/spec-v2-process.md`), which is authoritative for what
ends each step; what is authoritative here is the shape argument — a conversation, steps as skills,
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
the step is done; the conversation moves on. A way to *resume or jump* to a step
exists too, but it is not the primary path. Someone returning after a week should be able to say "let's
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

## The steps

Each step is a skill, and each ends on a checkpoint a script can measure: a step
does not end because it feels finished. The ids below are the ones the process
runtime uses (`src/integral/step_runtime.py`), in order.

0. **identify** — resolves who the candidate is, before any file under `profiles/` is touched.
1. **intake** — captures the CV or working history into the store, with provenance.
2. **constraints** — settles what would rule a job out: residence, pay floor, mobility, permits.
3. **history** — builds the story bank of episodes from past roles.
4. **traits** — scores traits from accumulated evidence, never from a personality quiz.
5. **reactions** — captures reactions to real adverts, to learn what the candidate actually values.
6. **preferences** — turns reactions into salary-equivalent weights through forced pairwise choices.
7. **sourcing** — fetches and dedupes live offers against the constraints.
8. **understanding** — extracts dimension values and verbatim evidence spans from new offers.
9. **ranking** — presents the live offers in order, each position's reason cited from the ad.
10. **feedback** — captures what the candidate thinks of the ranked offers, and re-ranks.
11. **application** — builds a CV and edits the candidate's own letter for one shortlisted offer.
12. **interview_log** — prepares for, then records, one interview.

These are the candidate's journey, numbered independently of the delivery phases
in `status/specification.md` §"Phases", which are about build order. The first
steps build the profile; the later ones are the loop the candidate lives in
afterwards, and **feedback feeds back into the profile**: every reaction is more
evidence, so the interview is not a thing that happens once. The checkpoint for
each step is defined in `status/spec-v2-process.md`, not here.

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
src/integral/           schema, harness, extraction, ranking (exists)
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
   `position` written continuously during a step rather than at
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
   **Decided: `integral-job-search`.** "integral" carries both senses the tool
   needs — whole, and accumulated over time, which is what the evidence log
   actually does. Nothing in the design depended on the string, so the rename is
   mechanical: it is tracked as T55 and touches the package path, the imports,
   the environment variable already written as `$INTEGRAL_HOME`, and the
   documents that name the repository.
