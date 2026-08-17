# S2: Specification v2 — one spec per step

## Acceptance gate

```gate
step_specs_complete >= 12
evidence: status/evidence/S2.json
key: step_specs_complete
```

```bash
echo "no gate command defined for S2 — replace this line with the command that writes status/evidence/S2.json" >&2; exit 1
```

## What this is

One specification per step, each filling the template in
`status/spec-v2-brief.md` §4: purpose, preconditions, inputs, protocol, stop
rule, outputs, gate, resume, re-run, privacy.

Reviewable as HTML, one document per step or one document with a section per
step — S1 decides which.

**The threshold is the step count S1 settles**, not necessarily 12. Update it
to match, and do not lower it to match what got written.

## The two fields most likely to be skipped

- **Stop rule.** Every step is a short, directed conversation with an end. A
  step with no cap runs until the candidate gives up, which is the failure mode
  the owner explicitly asked to avoid.
- **Re-run.** "The user updated their CV" and "the user left their job" both
  re-enter at an earlier step. Each output must say what a second pass
  preserves and what it replaces, or re-running will silently destroy work.

## Tests

`test_every_step_spec_fills_the_template` — a step whose specification omits a
template field is not counted; `test_every_step_has_a_stop_rule` — the one
field that cannot be defaulted.

## Location

Service: **ONTOLOGY** · Size: L · Depends: S1

Source: `status/spec-v2-brief.md`
