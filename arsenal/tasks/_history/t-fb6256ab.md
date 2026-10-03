---
id: t-fb6256ab
title: "T230: 68 stored offers cannot be loaded (salary.period is 'YEAR', 'MONTH', 'hourly'), and one of them aborts any loop over the store"
label: "T230: 68 stored offers cannot"
priority: 10
status: merged
---

Filed from a candidate session (test-mode 658fcce2).

Measured 2026-10-02: 68 of 2,908 files in one candidate's `offers/` raise `OfferError` in `load_offer`, every one on `salary.period` (`hourly` 15, `MONTH` 11, `YEAR`, ...), which the schema limits to `year|month|week|day|hour`. Something writes offers without going through the model. Find that writer, normalise the period where it is read from the board, repair the stored records, and make list-wide readers report an unreadable record instead of raising in the middle of a ranking.


## Acceptance gate

Variant spellings derived from `SalaryPeriod` load, an unmappable period is refused
by name, one bad record leaves a loop over the store complete and is recorded, and
`save_offer` refuses a variant. The migration of stored records is
`integral.salary_period_backfill` (dry run by default; `--apply` backs up first).

```bash
uv run pytest tests/test_offer_period_read.py tests/test_salary_period_backfill.py -q
```
