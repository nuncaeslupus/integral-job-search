# S3: Multi-user profile tree, identification, and session state

## Acceptance gate

```gate
cross_user_leaks == 0
evidence: status/evidence/S3.json
key: cross_user_leaks
```

```bash
uv run --extra dev pytest tests/test_identity.py -q
uv run --extra dev python -m jobsearch.identity status/evidence/S3.json
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

---

## Scope change — v2 plan, 2026-08-18

**Narrowed.** S3 keeps identity and the tree: handle resolution before any path
under `profiles/` is read *or written*, the four-step resolution order, and the
`PreToolUse` hook that refuses reads and writes under another handle's tree. It
owns step 0's gate, `cross_user_leaks == 0`, and the hook must be written so
correct operation never trips it.

**Session state and resumption split out as T35** — `session/state.json`, the
continuous-write rule, and the five-rule resumption order. They are a different
concern with a different gate, and T35 depends on this task and on T6.

The key is **a handle the candidate chooses**, not a legal name. Later sessions
greet by display name and ask for confirmation. Where exactly one profile
exists, that is a confirmation and never a default: silently assuming the only
profile is how one person's evidence ends up in another person's history, and
the log is append-only, so it is a mess to unpick rather than a mistake to
undo.
