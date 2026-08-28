# A prompt that simulates this tool

For someone who does not have [Claude Code](https://claude.com/claude-code) and
cannot run the real thing. Paste §3 into a plain Claude conversation and it will
run the interview's *manner*. It is a simulation and it says so to whoever uses
it — the failure worth preventing is somebody believing they ran the tool.

**This file is the whole offering.** There is no cut-down mode, no Project setup,
no portable state file. §4 says why, and §5 says how to keep this in sync.

---

## 1. What it cannot do

The tool has four mechanisms and only one of them is prose. The step protocols
(`.claude/skills/step-*/SKILL.md`) survive being pasted. The checkpoints
(`src/integral/`), the candidate store (`$INTEGRAL_HOME/profiles/<handle>/`) and
the containment hook (`PreToolUse`, S3) do not — there is no clone to import
`integral.*` from, sandbox storage does not outlive a conversation, and there are
no hooks.

So nothing is saved between conversations, no advert is fetched, no weight is
fitted, no gate is measured, and two people's data is kept apart by good manners
rather than by a rule the process cannot violate.

## 2. What survives, step by step

**Faithful** — carried by dialogue, so prose reproduces it. **Degraded** — the
step happens but something load-bearing becomes an estimate. **Manual** — the
work moves to the person.

| # | step | verdict | why |
|---|---|---|---|
| 0 | identify | faithful | dialogue — but isolation was the hook, and that is gone |
| 1 | intake | faithful | dialogue plus a pasted document |
| 2 | constraints | faithful | dialogue; every field resolved or explicitly unknown |
| 3 | history | faithful | dialogue; episodes |
| 4 | traits | faithful | scored from episodes, if the evidence is carried honestly |
| 5 | reactions | degraded | no live stimuli, no corpus split to keep elicitation and evaluation apart |
| 6 | preferences | degraded | part-worths estimated, not fitted — `weights.py` is the code |
| 7 | sourcing | manual | connectors, robots.txt, dedup, expiry: all code |
| 8 | understanding | degraded | the staged pipeline collapses onto the model, which is what step 8 exists to avoid |
| 9 | ranking | faithful | ordered list, one cited span per position |
| 10 | feedback | faithful | dialogue |
| 11 | application | degraded | the text is prose; the send boundary is `approval.py` |
| 12 | interview_log | faithful | dialogue |

Eight faithful, three degraded, one manual, one split. The losses land exactly
where compiled code does the work: fetching, extracting, fitting, consenting.

**And every one of the thirteen loses its gate.** Coverage — "is the artefact
there?" — is a structural question a reader can answer. The acceptance gates
(`constraint_field_resolution == 1.0`, `extraction_macro_f1 >= 0.75`, eleven
more) measure whether those artefacts are any good, at build time, over a
labelled corpus. A conversation has neither the corpus nor the code, so the
honest word for all thirteen is `unmeasured` (D-21).

## 3. The prompt

```text
You are simulating an interviewer for finding work, built around one idea: the
same vocabulary — how social the office is, whether "remote" means remote,
whether the schedule survives a school run — should carry across every stage,
from the first question to the interview afterwards.

Start by telling me, in two sentences, that you are a simulation of a tool called
integral-job-search, that the real one keeps a durable profile and verifies each
stage with scripts, and that you can do neither: nothing here is saved when this
conversation ends, and nothing you conclude has been measured. Then begin.

Work through these stages in order, and say which one we are in as we go:

 0 Identify    who I am, what to call me, and the language to continue in.
 1 Intake      my working history — from a CV I paste, or built with you if I
               have none. Record what a document *claims* as a claim, not a fact.
 2 Constraints what would rule a job out: where I live, currency, permits,
               languages, hours, pay floor, mobility. Leave anything unresolved
               marked "unknown" rather than blank or guessed.
 3 History     episodes from past roles — specific occasions, not self-assessment.
 4 Traits      scored only from what those episodes show. If two independent
               episodes do not support a trait, say "insufficient" and the count.
 5 Reactions   my reaction to real adverts I paste, to learn what I actually value.
 6 Preferences forced either/or choices between offers, to turn those reactions
               into rough salary-equivalent trade-offs.
 7 Sourcing    I bring the adverts. You cannot fetch them.
 8 Understanding  read each advert against the vocabulary, quoting the exact span
               that justifies every reading.
 9 Ranking     order them, and give one cited reason per position.
10 Feedback    what I think of the order, then re-rank.
11 Application a CV and letter for one specific offer.
12 Interview   prepare for it, then record what happened.

Stages 1, 3, 4, 5, 6, 10, 11 and 12 are optional and I may decline any of them.
0, 2, 7, 8 and 9 are needed for a ranking to mean anything.

How to behave:

- Say what you are about to do before any pause, and acknowledge what I said
  before doing it.
- Invite me forward at the end of each stage. Do not offer to end the session
  unless I sound tired or we have been at this a long time.
- Ask about one thing at a time. Cap yourself: roughly a dozen questions per
  stage, fewer if the shape of an answer is already there.
- Never ask for a legal name, address, telephone number, ID number or date of
  birth until stage 11, and then only for the document that needs it.
- Never turn stage 4 into a personality quiz. Traits come from episodes.
- Never write a CV before there is a specific advert to write it for.
- Never quote a reason I rejected a job to any employer.
- Everything I tell you is private. Before any sentence of mine goes into an
  application, show me the whole thing that would be sent and ask about that
  specific document — never as a standing permission.

At the end of every stage, say plainly: what you captured, what is still missing,
and "unmeasured" — because the real tool checks each stage with a script and you
have not checked anything.

If I ask for the real thing: it needs Claude Code, Python 3.12+ and uv, and lives
at github.com/nuncaeslupus/integral-job-search.
```

## 4. Why this, and not a working cut-down mode

A fuller version was drafted — a Project, a portable state file mirroring
`EvidenceRow`, a per-step paste procedure — and discarded. Three reasons, each
of which a prompt avoids.

**The steps that survive are the ones a person least needs help with.** The
conversation is portable; sourcing, extraction and weight fitting are the work
nobody can do in their head, and those are exactly what does not survive.

**Every protection becomes an instruction.** With no hook and no
`measure_prepared`, the containment boundary and the per-use disclosure rule turn
into sentences. The discarded draft ended up asking a candidate to personally
verify, before every send, that nothing in a document had lost its backing —
which is asking a person to be a gate.

**Its own drafting was the evidence.** Twelve review findings over four rounds,
and the two worst were mechanisms its author invented rather than looked up: a
row-level approval flag the design had explicitly rejected, and then a safety
property that does not exist, asserted in a security section and believed for
three commits. All three of the worst were in the invented state schema. **A
prompt has no schema to get wrong**, which is most of why it is the safer
artifact — and a prompt carries its own disclaimer into every session, which
settings spread across a Project cannot.

That drafting did turn up one real defect, now tracked on its own: a retracted
episode stays sendable, because `measure_prepared` backs an episode line by
`approvals.json` alone and nothing invalidates an approval when its evidence is
retracted.

## 5. Keeping it in sync

This file is the one thing to update, and it is **an impression of the step
skills, never a mirror**. `.claude/skills/step-*/SKILL.md` remain the
specification; if the two disagree, the skills are right.

Update §3 when any of these change, and nothing else:

| change | what to edit |
|---|---|
| A step is added, removed, or renamed | its line in the stage list |
| A step moves between required and offered | the two lines under the stage list |
| A rule in a skill's **Never** block changes | the "How to behave" bullets |
| §6.2's disclosure or send rule changes | the privacy bullet |
| The tool's dependencies change | the closing line |

A change to a gate, a threshold, a script or the dimension catalogue needs **no**
edit here: none of them are reachable from a conversation, which is what §1 says.

## 6. What this does not change

Nothing in the tool. `docs/distribution.md` remains the distribution decision —
installed by cloning, candidate state outside the clone. `status/plan.md`'s
exclusions are untouched, in particular "an interactive UI … anything with state
of its own waits", which a browser-side state holder would have crossed.
