---
id: t-8c36ace9
title: "T220: Refusals stated in steps 5, 6 and 10 are never surfaced as unrecorded exclusions"
priority: 10
deps: [t-a4dc5d52]
tags: [BACKEND]
---


Filed 2026-10-01 from the second-reader report on #598 (T218, finding F2).

## Problem

`integral.sourcing_exclusions.unrecorded_statements` reads only rows whose step is in `STATEMENT_STEPS = ("identify", "constraints")`. A candidate rules topics out in later steps too, and those rows are never listed, so step 7 never warns and `source()` never filters them. Fail-open: the candidate keeps seeing what they refused.

Measured on fixtures against #598's head (each `states_a_refusal` → true, each row skipped):

| step | kind | words |
|---|---|---|
| `feedback` (10) | `reaction` | "no me enseñéis más bancos" |
| `reactions` (5) | `reaction` | "nada de apuestas" |
| `preferences` (6) | `statement` | "no quiero consultoras" |

Step 10 is the most likely place: it is where the candidate reacts to the ranked list ("stop showing me banks").

## Remedy (sketch)

- Add `reactions`, `preferences` and `feedback` to `STATEMENT_STEPS`, or derive the set from the process spec rather than listing it.
- A reaction to **one** advert ("this one is a bank, no") is not always a topic refusal. Decide and document whether such rows are listed (over-read costs one review line, per T218's rule) or filtered by `about.kind == "offer"` — and pin the choice with a test either way.
- Step 7's SKILL.md backfill section names the new steps.

## Acceptance gate

```bash
uv run pytest tests/test_exclusion_backfill.py
```

The gate file must gain one fixture per added step (the three rows above at least), each asserted **listed** while unrecorded and **gone** once recorded, plus one row from an unrelated step (`history`) still asserted skipped. Mutation: removing any one step from the set must turn the scoped run red.
