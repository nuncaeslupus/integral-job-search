# S3: Multi-user profile tree, identification, and session state

## Acceptance gate

```gate
cross_user_leaks == 0
evidence: status/evidence/S3.json
key: cross_user_leaks
```

```bash
echo "no gate command defined for S3 — replace this line with the command that writes status/evidence/S3.json" >&2; exit 1
```

## What this is

Multi-user from day one (owner's decision, 2026-08-16). A directory tree per
person under `profiles/<handle>/`, the tree in `status/spec-v2-brief.md` §5, and
**identification at the start of every session before anything is read or
written**.

Expect a handful of users. Simple and file-based; not a multi-tenant service.

## The gate

`cross_user_leaks` counts any operation that reads or writes outside the
identified user's tree. Zero is the only acceptable value, and it must be
measured rather than asserted — every store function takes the handle and
resolves paths beneath it, so a test can point one user's operations at another's
tree and prove they fail.

## Session state

`session/state.json` per user: current step, position within it, last activity.
This is what makes "let's carry on" work the day after a candidate stopped
mid-interview, without a command being typed (brief §2.5).

## Tests

`test_an_operation_cannot_touch_another_users_tree`;
`test_session_resumes_at_the_recorded_position`;
`test_no_user_identified_refuses_to_read_or_write` — the failure must be a
refusal, not a default to the first handle found.

## Location

Service: **PROFILE** · Size: M · Depends: S1

Source: `status/spec-v2-brief.md` §1.3, §5
