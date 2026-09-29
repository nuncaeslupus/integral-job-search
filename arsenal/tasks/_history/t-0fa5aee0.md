---
id: t-0fa5aee0
title: "T188: Triage the 51 test-mode notes captured across past sessions that were never seeded"
priority: 10
tags: [test-mode]
status: merged
---

Audit (2026-09-16): every historical `.test-mode/*.jsonl` ledger (5 sessions, 51
notes total) shows `captured == shown` — the ledger mechanism has never lost a note
it successfully parsed — but grepping `arsenal/tasks/` (live and `_history/`) for
the `Test-mode note` title pattern this skill's own seed command produces returns
zero matches. So the end-of-session triage step (test-mode skill: "print every note,
ask which to address, seed only what's confirmed") has apparently never been run to
completion in any past session — notes accumulate silently and are never surfaced
for a decision.

Action: read through the 5 historical ledgers, present each note to the owner, and
seed (or explicitly discard) each one — closing out the backlog once. Worth deciding
separately: should ending a test session enforce running triage before the session
is considered closed, rather than leaving it to be remembered each time?


## Triage (2026-09-29)

58 notes across 7 ledgers (the audit above counted 51 in 5; two more sessions since).

- **Seeded:** T207 (slow step 0), T208 (ask a developer for GitHub), T209 (recommend rather than list options; strong and weak points), T210 (suggest compacting), T211 (application status table), T212 (send/ folder), T213 (enforce triage at the end of a test session, as the owner decided).
- **Folded into T145:** ask for empty dimensions (26470ef3 #9).
- **Discarded:** 1b31d8e2 #1 (no context), b461d09a #1 (meta note), 56011f26 #5 (test mode itself is the mechanism), b461d09a #8 (already covered by T95's vocabulary).
- **Already covered, 47 notes:**
  - D-13 to D-17
  - T45, T47, T54, T62 to T68
  - T91 to T99
  - T118, T134, T136 to T140, T142, T144, T147, T172, T173
  - T180 to T182, T187, T190, T191, T202, T203

## Acceptance gate

```bash
# Every seeded note has its task, and the one folded note sits in T145.
for t in T207 T208 T209 T210 T211 T212 T213; do
  grep -q "^title: \"$t:" arsenal/tasks/*.md || { echo "missing $t"; exit 1; }
done
grep -q 'Folded in by T188' arsenal/tasks/t-dad9f885.md
```
