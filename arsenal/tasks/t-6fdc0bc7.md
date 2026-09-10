---
id: t-6fdc0bc7
title: "T170: salary periods arrive in each board's own words, so the pay floor applies to no connector's salary"
priority: 5
deps: [t-ee67736b]
tags: [BACKEND]
---

Found by the second reader on #445 (T144, finding F13), and wider than that
finding says.

`connectors/lever_en` maps `salary_period: salaryRange.interval`, and Lever
writes that field as labels: `per-year-salary`, `per-month-salary`,
`per-hour-wage`, `per-day-wage`, `one-time`. `bulk_filter._below_pay_floor`
compares `offer.salary.period == floor.period`, and a floor names `year` or
`month` (`candidate.Salary.period`). So the candidate's pay floor never drops a
Lever offer, which is fail-open. Presentation prints `/per-year-salary`.

**It is not only Lever: the floor applies to no salary any connector states.**
Measured 2026-09-10 on `main`'s fixtures:

| connector | route | what `salary_period` holds |
|---|---|---|
| lever_en (#445) | JSON `salaryRange.interval` | `per-year-salary`, … |
| himalayas_en | JSON `salaryPeriod` | `annual`, `hourly` |
| justjoin_en | JSON-LD `unitText` | `MONTH` |
| jobfluent_es | microdata `unitText` | `YEAR` |

The only producer that already writes `year`/`month`/`day`/`hour` is
`salary_recovery`. `strings/catalogue.json` carries only `period_year` and
`period_month`, so any other period prints in raw English to an ES or CA
candidate. That breaks the rule that the three supported languages behave
identically.

## Design (owner-approved 2026-09-10)

- **One vocabulary, enforced by type.** `offers.Salary.period` becomes
  `Literal["year", "month", "week", "day", "hour"] | None`. No route can then
  build a salary with a period outside it: not a connector, not
  `salary_recovery`, not a future producer. No stored offer carries a period
  today (checked 2026-09-10), so nothing on disk stops validating.
- **One table, one place.** `build_offer`, which every connector route passes
  through, maps each board's documented words onto the vocabulary. The match
  is case-folded and trimmed, and the table is closed. It is not a per-connector
  `take:`, because that would need every connector to remember it.
- **A period stated but not representable drops the salary.** Lever's
  `one-time`, or any label absent from the table, means no stated salary. The
  period is not simply left blank. This matches `salary_recovery`, which
  refuses a period it cannot store, and it stops a one-time payment reading as
  a wage. An **absent** period stays what it is today.
- **The catalogue covers the vocabulary.** Add `period_week`, `period_day` and
  `period_hour` in EN, ES and CA. The check is derived from the `Literal`'s own
  members, never from a list.

Currency is not in scope: every board surveyed already sends an ISO code.

## Tests

- `test_period_contracts`: the second session's table, below.
- `test_a_connector_salary_below_the_floor_is_dropped`: for **each** period a
  candidate's floor can name (`typing.get_args` over `candidate.Salary.period`,
  never a list), a connector-built offer stating less than the floor is dropped
  by `bulk_filter`. This is the fail-open the task exists to close, pinned end
  to end rather than at the table.
- `test_floor_periods_are_offer_periods`: every period a floor can name is in
  the offer vocabulary, so the two `Literal`s cannot drift apart.
- `test_every_period_has_a_catalogue_entry_in_every_language`: derived from the
  `Literal`.
- `test_an_unrepresentable_period_states_no_salary`: `one-time` with figures
  gives `salary is None`.

**The contract table is written by a session other than the implementer**
(CLAUDE.md, "Fixtures for a correctness-critical gate are written by a second
session"). It derives each row from the board's own published documentation,
before opening the implementation: Lever's Postings API for
`salaryRange.interval`, Himalayas' API docs for `salaryPeriod`, and schema.org /
Google's `JobPosting` docs for `unitText` (`HOUR`, `DAY`, `WEEK`, `MONTH`,
`YEAR`). Each row cites the page its value came from. Unknown labels, case
variants, surrounding whitespace, and a value that only resembles a period
(`yearly-bonus`) are fail-closed rows. Every accepted row is committed before
merge.

## References

- `src/integral/connectors.py` `build_offer`: the one place every connector salary is built.
- `src/integral/offers.py` `Salary`: the type to tighten.
- `src/integral/bulk_filter.py` `_below_pay_floor`: the comparison that never matches today.
- `src/integral/candidate.py` `Salary.period`: the periods a floor can name.
- `src/integral/salary_recovery.py` `_BOUNDS`, `_periods_in`: the producer already on the vocabulary, and the precedent for refusing a period it cannot store.
- `src/integral/presentation.py` salary rendering, and `strings/catalogue.json` `period_*`.
- `tests/test_connectors.py` (~1342): asserts `"MONTH"` today, and flips to `"month"`.

## Acceptance gate

```gate
period_contracts_failing == 0
evidence: status/evidence/T170.json
key: period_contracts_failing
```

```bash
uv run --extra dev pytest tests/test_salary_period.py -q
make evidence
```

The denominator, `period_contracts_at_least`, is a literal floor per T122, so a
table that shrank reads `unmeasured` rather than a clean zero.
