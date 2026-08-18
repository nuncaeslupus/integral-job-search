# D-3: the `story_failure_fraction` floor contradicts the revised History protocol

## Acceptance gate

```gate
spec_gate_contradictions == 0
evidence: status/evidence/D3.json
key: spec_gate_contradictions
```

```bash
echo "no gate command defined for D-3 — replace this line with the command that writes status/evidence/D3.json" >&2; exit 1
```

## What the spec requires

`status/specification.md` lists `story_failure_fraction >= 0.33` among the v1
success criteria, and `docs/METHODS.md` carries its rationale: success stories
are rehearsed and reveal less.

## What the code — and now the specification — does

`status/spec-v2-steps.md` step 3, revised in S2r on the owner's instruction,
says successes evidence traits as precisely as failures and that the tool takes
a failure when it comes **rather than digging for one**. A floor of one third
requires digging. An implementation must break the protocol or miss the gate;
there is no behaviour satisfying both.

S2r superseded the floor inside the step specification and said so there. **This
task reconciles the two documents that still assert it**, so the contradiction
does not survive in the place a future reader looks first.

## The fix

Not deletion — the concern was real. A bank of nothing but rehearsed successes
does reveal less, and something should say so. Replace the floor with the shape
requirement the step spec now states:

- once a bank holds **four or more episodes it should contain both kinds**;
- `story_failure_fraction` is **reported, never floored**, so a monotone bank is
  visible without anyone being interrogated into fixing it.

Update `status/specification.md` §"Success criteria", the METHODS entry, and any
gate table row that still carries the threshold.

## Why it matters beyond tidiness

A gate nobody can satisfy honestly is worse than no gate: it teaches whoever
implements the step that the numbers are decorative. This project's whole
discipline rests on them not being.

## Tests

`test_no_gate_requires_behaviour_a_step_protocol_forbids` — if that can be
expressed mechanically across the spec documents, it is worth far more than this
one instance; if it cannot, say so plainly rather than writing a test that only
looks like it checks something.

## Location

Service: **PROFILE** · Size: S · Depends: —

Source: PR #18 review · `status/spec-v2-steps.md` step 3 · `status/specification.md` · `docs/METHODS.md`
