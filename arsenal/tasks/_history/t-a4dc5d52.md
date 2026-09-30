---
id: t-a4dc5d52
title: "T218: A profile begun before T203 states its ruled-out topics only as evidence rows, and step 7 never says so"
priority: 10
status: merged
---

Found 2026-09-30 on a real candidate profile: 9 ruled-out topics stated across several sessions (evidence rows, steps `identify` / `constraints`), **zero** in `search/exclusions.json`. T203 (#571) made `source()` apply that file, but nothing ever wrote it for a profile begun before — so its exclusions filtered nothing, the candidate kept seeing the sectors they had ruled out, and nothing looked wrong: an absent file reads, correctly, as "nothing ruled out".

## Remedy

- `integral.sourcing_exclusions.unrecorded_statements(store)`: live evidence rows of steps `identify` / `constraints` whose words carry a refusal cue (ES/EN/CA, deliberately broad) and that no recorded exclusion `matches`.
- `backfill_warning(store)`: a `WARNING` when such rows exist and nothing is recorded; a quieter note on a partial backfill.
- Step 7's checkpoint reports `exclusions_recorded`, `unrecorded_exclusion_statements` and `exclusion_backfill_warning` (stderr too); exit code unchanged.
- CLI `python -m integral.sourcing_exclusions unrecorded --handle H` — exit 1 while anything is left, so the backfill loop is closable.
- Step 7's SKILL.md documents the backfill: one `record` per topic, words quoted from the row, `--term` in ES/EN/CA.

Ceiling: a row naming several topics counts as covered once any one of them is recorded — free text cannot be split into topics, so the skill asks for every topic a row names. Step 2's own write of a pinned field (salary, location, …) is never listed, so a topic said inside its quote is not seen either.

## Acceptance gate

```bash
uv run pytest tests/test_exclusion_backfill.py
```
