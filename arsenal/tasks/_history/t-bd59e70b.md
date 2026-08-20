---
id: t-bd59e70b
title: "D-13: say what the tool is doing before a long silent setup"
priority: 10
status: merged
---

Captured during a test session at step `intake` (ledger `test-2026-08-20-a`).

> You are doing a lot of things and the user is waiting. You should answer the user and tell him
> "Nice to meet you, XXX. Let me prepare the environment, it will take a moment" or similar. Then,
> you prepare the folders, run your scripts and finally answer something like "Thanks for waiting,
> XXX / Here's how this works..."

The candidate sees `Skill(step-02-constraints) Successfully loaded` and a run of Bash calls with no
narration. Two changes, both in the step skills rather than in code:

1. Acknowledge the person BEFORE profile creation, then do the setup, then continue.
2. Name what is happening in one short line when a step does visible work.

Addressed in: `step-00-identify`, and the shared protocol prose every step skill inherits.


## Acceptance gate

```gate
step_skills_without_a_progress_disclosure_rule == 0
evidence: status/evidence/D-13.json
key: step_skills_without_a_progress_disclosure_rule
```

```bash
uv run --extra dev pytest tests/test_step_skills.py -q
```

The number is measured over the step-skill library itself — the prose actually
put in front of the model — rather than over a restatement of the rule.

A skill counts as **lacking a progress disclosure rule** on any of three limbs:

1. its `## Protocol` prose carries no rule governing what is said before work
   the candidate waits through;
2. it carries no spoken example performing the disclosure — a line naming the
   work *and* marking the wait, which is the text a model copies; or
3. at step 0, where the candidate first says who they are, the spoken example
   names the setup before it acknowledges them.

Limbs 1 and 2 read different halves of the section — limb 1 only the prose,
limb 2 only the fenced blocks. Without that split the sentence stating the rule
would trip the check it satisfies, and no library could pass.

Verified by running the gate against the pre-fix library (`--skills-dir` over a
`git archive HEAD` copy): **13** offenders, all thirteen failing both limb 1 and
limb 2, and step 0 additionally failing limb 3. After the fix: 0.

## What the spec requires

Nothing, before this task — and that is the finding. §5.4 of the process spec
required the tool to **say why**: each step opens with what it is for and what
it will store. That governs the *subject* of a step and says nothing about the
seconds in which the tool is executing, which is the interval the candidate was
actually sitting in.

So the rule was absent rather than broken, and the model, given no instruction,
did the efficient thing and worked in silence. **Say what is happening before a
silence** is now the fifth cross-cutting rule in `status/spec-v2-steps.md` and a
bullet of §5.4 in `status/spec-v2-process.md` — added to both at once, because
D-15's root cause was one rule stated in one document and contradicted in the
other, with the live session sitting between them.

## The fix

All thirteen step skills carry the rule in their own `## Protocol` section,
where the model reads it, followed by a worked example in that step's own words
— *"Searching the boards with your constraints on — this takes a moment."*
Step 0's example carries both halves in order: the acknowledgement, then the
setup, then the return.

`jobsearch.step_narration` measures it, as a module of its own for the reason
D-14 records: `make evidence` runs each module once with no arguments, so a gate
reachable only behind a flag is a gate whose drift nothing notices. It reads the
requirement out of the step spec rather than restating it, and reports `-1` when
that rule is gone.

## The false positive worth not rediscovering

Limb 3's subject — which step must greet — is read from the settled step list
(`n == 0`), never from a regex over the skill's prose. The first cut detected it
by searching for "creates their profile" in the text, and matched **all thirteen
skills**: the shared rule sentence names profile creation, so the probe found
the rule rather than the behaviour and reported twelve false offenders.

That is the self-trip `session_exit` split its two limbs to avoid, in a second
disguise — and the general lesson is that a check whose subject can be named by
the very sentence that satisfies it is not a check.

## Location

`src/jobsearch/step_narration.py` (new), `.claude/skills/step-*/SKILL.md` (all
thirteen), `status/spec-v2-steps.md`, `status/spec-v2-process.md`,
`tests/test_step_skills.py`, `status/evidence/D-13.json`, `status/plan.md`
(the D-13 row).
