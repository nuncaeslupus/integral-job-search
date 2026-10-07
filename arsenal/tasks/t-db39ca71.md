---
id: t-db39ca71
title: "T298: T230 follow-ups: run the period backfill on the real store; a systematic failure in load_offers reads as zero offers"
priority: 5
requires: [human:gate]
---

Imported from issue #696

These follow-ups come out of the second read of #695.

- **Operator step.** Run `python -m integral.salary_period_backfill` as a dry run on the candidate's real store. It has never been run there.
  - Read its `dropped salary` rows. Any spelling a real board sends goes into `salary_period._TABLE`, with its provenance, as a task of its own.
  - Only after that, run `--apply`.
- **N1 (optional).** `load_offers` catches `ValueError` per record. A programming bug that raises `ValueError` on every record therefore produces 0 offers, with every record listed as skipped, instead of a crash. Two possible fixes:
  - re-raise when every record fails with the same exception type, or
  - have step 08 tell the candidate when anything was skipped.
- **N2 (optional).** The constructed-store measurement test only stores spellings that map, so "no salary lost" is true by construction. It also accepts either outcome for the unmappable record. In addition, the plan metric `stored_offers_that_do_not_load == 0` is not committed evidence.
- `load_offers` has no in-repo production caller apart from the step-08 skill text.

## Acceptance gate

<!-- This task came from an issue, so its "gate" is prose. Write a real check
     below, then DELETE the `requires: [human:gate]` line in the front matter.
     Until that line is gone the selector will not offer this task, which is
     deliberate: a prose gate runs nothing, and a gate that runs nothing passes
     everything. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
false
```
