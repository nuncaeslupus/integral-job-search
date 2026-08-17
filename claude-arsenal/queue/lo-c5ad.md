# T30: Step inputs/outputs in the step list, gated on required-subset closure

## Acceptance gate

```gate
required_subset_closure_violations == 0
evidence: status/evidence/T30.json
key: required_subset_closure_violations
```

```bash
echo "no gate command defined for T30 — replace this line with the command that writes status/evidence/T30.json" >&2; exit 1
```

## What this is

`status/spec-v2-process.md` §3.1 declares what each step reads and produces, but
it declares it in a prose code block. `spec-v2-steps.json` carries the step list
without inputs or outputs, so nothing checks the graph.

Move the declarations into the JSON — `reads` and `produces` per step, with
optional inputs marked — and validate the property §2.5 depends on:

> **Every input of a required step is produced by another required step, or is
> external, or is optional.**

That is what "any offered step may be declined without blocking" actually means.
Stated in prose it is a promise; checked, it is a guarantee.

## Why this is worth a task

It is not hypothetical. PR #16 introduced the graph and, in the same diff,
violated it: required **Constraints** read `claimed facts`, which only the
*offered* **Intake** step produces. A candidate with no CV — exactly the person
§2.5 exists to serve — would have hit a required step with a missing input. A
reviewer caught it; a closure check would have caught it before the commit.

## What this replaces

`collect_violations` currently asserts only that *some* step is required. That
is too weak to mean anything: a process with only `identify` required passes it
and can rank nothing.

**Do not replace it with a hardcoded list of the five settled ids.** Which steps
are required is an owner decision recorded in `spec-v2-steps.json`; copying the
ids into the validator puts the decision in two places, and the next legitimate
change makes the gate fail until someone edits the constant to match. A check
that gets edited to pass protects nothing. Tests pin decisions
(`test_the_required_steps_are_the_five_the_owner_settled`); validators enforce
invariants that hold whatever the owner decides.

## Sequencing

S2 writes per-step preconditions and will need the same declarations, so this
lands with S2 rather than before it — one encoding, not two.

## Tests

`test_a_required_step_reading_an_offered_steps_output_is_rejected` — the PR #16
defect, as a fixture; `test_an_optional_input_does_not_break_closure` — the
`claimed facts?` case must pass; `test_the_prose_graph_and_the_json_agree` — §3.1
and `spec-v2-steps.json` cannot drift, or the checked graph stops being the
documented one.

## Location

Service: **ONTOLOGY** · Size: M · Depends: S2

Source: `status/spec-v2-process.md` §2.5, §3.1 · PR #16 review thread
