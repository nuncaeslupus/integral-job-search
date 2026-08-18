# T38: Retraction rows, and deletion of a person

## Acceptance gate

```gate
retracted_rows_surviving_rebuild == 0
evidence: status/evidence/T38.json
key: retracted_rows_surviving_rebuild
```

```bash
echo "no gate command defined for T38 — replace this line with the command that writes status/evidence/T38.json" >&2; exit 1
```

## What this is

Two operations of different size, both of which must exist.

**Retraction** handles one fact. The log is append-only, so "forget that" is a
`retraction` row naming the row it suppresses — never a deletion. Derived
artefacts honour retractions when rebuilt; the original row survives so a
rebuild stays deterministic and so an accidental retraction can itself be
undone.

**Deleting a person** removes `profiles/<handle>/` entirely — evidence log,
stories, CV store, offers, rankings, applications, interviews, and the
tombstones, which are per-profile. Confirmed once by naming what goes, and not
reversible. That is the point of it.

## The rule that matters

**Deleting another profile is permitted, after confirming the target by
name.** Anyone who can run the tool can delete the directory with a file
manager, so a refusal protects nothing and makes the tool useless to a household
sharing a laptop. What the tool adds is that the target is stated before it
happens — and **an instruction that does not name a profile deletes nothing.**

"What do you know about me?", "forget that" and "delete everything" work at any
point in any step, and are answered before the step continues.

## Tests

Write these RED before any production code:

`test_retracted_row_is_absent_from_every_derived_file` in
`tests/test_retraction.py`; `test_retraction_is_itself_reversible` — the
suppressed row survives in the log; `test_deletion_without_a_named_target_deletes_nothing`;
`test_deleting_a_profile_removes_its_tombstones_too`.

## Location

Service: **RUNTIME** · Size: M · Depends: T6

Design: `status/plan.md` (RUNTIME) · Spec: `status/spec-v2-process.md` §4.1 and §4.3
