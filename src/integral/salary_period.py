"""T170 — one pay-period vocabulary, and the table every board's own words map onto.

`connectors/lever_en` mapped `salary_period: salaryRange.interval` straight
through, and Lever writes that field as labels: `per-year-salary`,
`per-month-salary`, `per-hour-wage`, `per-day-wage`, `one-time`.
`bulk_filter._below_pay_floor` compares `offer.salary.period == floor.period`,
and a floor names `year` or `month` (`candidate.Salary.period`) — so the
candidate's pay floor never dropped a Lever offer at all. Lever was not alone:
`himalayas_en` writes `annual`/`hourly`, and `justjoin_en` and `jobfluent_es`
write schema.org's `unitText` (`MONTH`, `YEAR`, ...). Every route arrived at
the comparison in its source's own words, and the comparison never matched
(found by the second reader on #445, T144 finding F13; measured wider here on
2026-09-10, #454).

**The fix is one table, in one place.** `offers.Salary.period` is now
`SalaryPeriod | None` — a closed `Literal` — so nothing, connector or
producer, can construct a `Salary` whose period is not one of its five
members. `normalize_period` below is the only function that may map a board's
raw word onto that vocabulary, and `connectors.build_offer` is its one call
site: every connector route passes through it, so joining the vocabulary
never again means teaching a per-connector `take:` about periods.

**A period stated but not representable drops the whole salary, not just the
period.** Lever's `one-time` is not a period at all — it is a lump sum — and a
label absent from the table is a period this system refuses to guess at,
exactly as `salary_recovery._periods_in` already refuses one it cannot bound.
Reading `one-time` as "no period" and keeping the figures would let a one-time
payment through comparisons built for a wage; reading it as "unknown period"
and keeping `stated=True` would tell the ranking a wage was named when it was
not. `build_offer` treats "period given, not representable" and "no salary at
all" the same way. An **absent** `salary_period` field is unaffected — that is
today's "no period stated" and stays exactly what it was.

**The table is closed, not inferred.** `_TABLE` is a literal mapping from a
case-folded, trimmed raw string to a `SalaryPeriod` member — no stemming, no
substring match, no regex. `"yearly-bonus"` and `"per-year"` are not `"year"`:
they merely contain letters that overlap it, and a normaliser that treated
resemblance as equivalence would be the fail-open shape this task exists to
close (`salary` silently reading the wrong unit is worse than reading none).
Nothing in `_TABLE` is generated from `SalaryPeriod`'s members either — a
board's word for "month" is not derivable from the English word "month", so
this vocabulary is inherently an enumeration of what has actually been
observed or documented, not a closed grammar. What *is* closed and derived,
never restated, is the target vocabulary itself: every value `_TABLE` may map
to is asserted (`test_table_values_are_offer_periods`) to be a member of
`typing.get_args(offers.SalaryPeriod)`, so a typo that invented a sixth period
is caught structurally rather than by remembering to look.

`CONTRACT_CASES` is the adversarial table T170's design calls for: each row
names the board, the raw value, the period the source's own documentation (or,
where no public doc URL survives egress, this connector's own dated
fixture/probe capture — the closest thing to a spec this repository can read)
says it means, and the citation. Positive rows exercise the real vocabulary
plus case/whitespace variation the table must survive; negative rows are the
fail-open shapes this task was filed over — an unmapped board word, a value
that only resembles a period, and the `one-time` label Lever actually sends.
`period_contracts_failing` is a mismatch between a row's `expected` and what
`normalize_period` actually returns for it, so a broken case-fold, a dropped
row, or a table entry mapped to the wrong period all show up the same way: a
count that is not zero.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, NamedTuple, get_args

from integral.offers import SalaryPeriod

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T170.json"

#: The closed table (T170). Keys are already case-folded and trimmed — look-up
#: does the same to whatever it is given, never the reverse — so this dict is
#: the one and only place a board's word is spelled out.
_TABLE: dict[str, SalaryPeriod] = {
    # schema.org's `JobPosting.baseSalary.value.unitText` — Google's structured
    # data guidance for job postings documents exactly these five values, and
    # both connectors in this library that read the field send them upper-case
    # (`connectors/justjoin_en/fixture/detail.html`: `"unitText": "MONTH"`;
    # `connectors/jobfluent_es/fixture/detail.html`: `unitText" content="YEAR"`).
    "year": "year",
    "month": "month",
    "week": "week",
    "day": "day",
    "hour": "hour",
    # Lever's Postings API reference documents `salaryRange.interval` as an
    # enum of per-year-salary/per-hour-wage/per-month-salary/per-day-wage/
    # per-week-salary/semi-month-salary/bi-month-salary/bi-week-salary/
    # one-time. The five below map onto this vocabulary directly (the first
    # four also carry this repository's own direct, dated capture, per
    # `connectors/lever_en/connector.yaml`'s header and the #454 measurement,
    # 2026-09-10). `semi-month-salary`, `bi-month-salary` and `bi-week-salary`
    # are deliberately NOT here: SalaryPeriod has no twice-a-month or
    # fortnight-shaped member for them to land on, and admitting one under
    # the nearest wrong period would misstate the wage rather than merely
    # omit it — refused below for that reason (see CONTRACT_CASES'
    # semi-month-salary/bi-month-salary/bi-week-salary rows), the same way as
    # `one-time`, not omitted for lack of evidence. Leaving a documented,
    # representable label OUT of this table is what F2 (second-reader report
    # on #487) found: `per-week-salary` used to be missing the same way, and
    # a real Lever week-paid offer fell to "no salary" instead of being
    # compared against the candidate's floor — worse than `main`, which at
    # least kept the raw figures. An unlisted label is not the safe side; it
    # is a hole, closed here by listing every label this table has an actual
    # target period for and refusing, with a reason, every one it does not.
    "per-year-salary": "year",
    "per-month-salary": "month",
    "per-hour-wage": "hour",
    "per-day-wage": "day",
    "per-week-salary": "week",
    # `one-time` is intentionally absent: it is Lever's label for a lump sum,
    # not a pay period, and `normalize_period` must refuse it rather than
    # silently drop it to "no period" (see `build_offer`).
    #
    # Himalayas' Remote Jobs API Reference documents `salaryPeriod` as an
    # enum: hourly, weekly, fortnightly, monthly, annual. `annual` and
    # `hourly` also carry this repository's own direct, dated capture, in
    # `connectors/himalayas_en/fixture/list.html` (per that connector's
    # `meta.yaml`). `monthly` and `weekly` were missing the same way
    # `per-week-salary` was above (F1, same report): a documented, real
    # Himalayas value with no table entry falls to "no stated salary" in
    # `build_offer`, so a real monthly-paid offer below the candidate's floor
    # was admitted instead of dropped — the floor never got to compare it.
    # `fortnightly` is deliberately NOT here, for the same reason as Lever's
    # semi-month/bi-* labels above: no fortnight-shaped member of
    # SalaryPeriod exists to land it on, so it is refused below rather than
    # guessed at (see CONTRACT_CASES' fortnightly row).
    "annual": "year",
    "hourly": "hour",
    "monthly": "month",
    "weekly": "week",
}


def normalize_period(raw: str | None) -> SalaryPeriod | None:
    """A board's own word for a pay period, mapped onto the closed vocabulary.

    Case-folded and trimmed before lookup, so `"MONTH"`, `" Month "` and
    `"month"` all land on the same table entry. Anything the table does not
    name — an unrecognised label, a near-miss like `"yearly-bonus"`, or the
    empty string — returns `None`: unrepresentable, never guessed at.
    """
    if raw is None:
        return None
    return _TABLE.get(raw.strip().casefold())


class PeriodContract(NamedTuple):
    """One board's documented word, and what it must mean.

    `board` and `citation` are provenance, read by nobody but a human auditing
    a failure; `raw` and `expected` are what `_check_contracts` actually
    compares against `normalize_period`. `connector` names the connector
    package (`connectors/<connector>/`) this row is direct evidence for — set
    only on a positive row whose value is a real, board-documented word for
    one specific connector's own vocabulary, never on a generic schema.org
    row shared by several connectors or on a pure case/whitespace variant.
    `tests/test_salary_period.py`'s connector-coverage test reads it to check,
    against the real `connectors/` tree, that every package whose field map
    actually names `salary_period` is backed by at least one such row — a
    closed, self-growing check in place of a row count a whole board's rows
    could be deleted out from under (F3, second-reader report on #487).
    """

    board: str
    raw: str | None
    expected: SalaryPeriod | None
    citation: str
    connector: str | None = None


#: The adversarial contract table T170's design requires: derived from each
#: board's own documented (or, failing that, directly observed and dated)
#: period vocabulary — never from this module's implementation. Positive rows
#: cover the real values plus the case/whitespace variation `normalize_period`
#: must survive; negative rows are the fail-open shapes #454 was filed over.
CONTRACT_CASES: tuple[PeriodContract, ...] = (
    # --- schema.org `unitText` (Google's JobPosting structured-data guide
    # names HOUR/DAY/WEEK/MONTH/YEAR) — the two actually seen in this
    # library's own fixtures, cited by file, plus the three the same
    # connectors' grammar can equally receive. ---
    PeriodContract(
        "schema.org unitText",
        "YEAR",
        "year",
        'connectors/jobfluent_es/fixture/detail.html: unitText content="YEAR"',
        connector="jobfluent_es",
    ),
    PeriodContract(
        "schema.org unitText",
        "MONTH",
        "month",
        'connectors/justjoin_en/fixture/detail.html: "unitText": "MONTH"',
        connector="justjoin_en",
    ),
    PeriodContract(
        "schema.org unitText",
        "WEEK",
        "week",
        "schema.org JobPosting/Google job-posting guide: unitText enum "
        "(HOUR, DAY, WEEK, MONTH, YEAR)",
    ),
    PeriodContract(
        "schema.org unitText",
        "DAY",
        "day",
        "schema.org JobPosting/Google job-posting guide: unitText enum",
    ),
    PeriodContract(
        "schema.org unitText",
        "HOUR",
        "hour",
        "schema.org JobPosting/Google job-posting guide: unitText enum",
    ),
    # Case and whitespace variants a real document could equally send —
    # schema.org does not mandate upper case, and HTML attribute values are
    # trimmed by nothing upstream of this parser.
    PeriodContract("schema.org unitText", "year", "year", "same enum, lower case"),
    PeriodContract("schema.org unitText", "Year", "year", "same enum, title case"),
    PeriodContract("schema.org unitText", " YEAR ", "year", "same enum, padded"),
    PeriodContract("schema.org unitText", "month", "month", "same enum, lower case"),
    PeriodContract("schema.org unitText", "week", "week", "same enum, lower case"),
    # --- Lever Postings API, `salaryRange.interval` — the four labels T170's
    # own filing measured from `connectors/lever_en` on 2026-09-10 (#454),
    # plus the rest of the documented enum added for F2 (#487). ---
    PeriodContract(
        "Lever salaryRange.interval",
        "per-year-salary",
        "year",
        "connectors/lever_en/connector.yaml header; #454 measurement, 2026-09-10",
        connector="lever_en",
    ),
    PeriodContract(
        "Lever salaryRange.interval",
        "per-month-salary",
        "month",
        "connectors/lever_en/connector.yaml header; #454 measurement, 2026-09-10",
        connector="lever_en",
    ),
    PeriodContract(
        "Lever salaryRange.interval",
        "per-hour-wage",
        "hour",
        "connectors/lever_en/connector.yaml header; #454 measurement, 2026-09-10",
        connector="lever_en",
    ),
    PeriodContract(
        "Lever salaryRange.interval",
        "per-day-wage",
        "day",
        "connectors/lever_en/connector.yaml header; #454 measurement, 2026-09-10",
        connector="lever_en",
    ),
    PeriodContract(
        "Lever salaryRange.interval",
        "per-week-salary",
        "week",
        "Lever Postings API reference: salaryRange.interval enum "
        "(per-year-salary, per-hour-wage, per-month-salary, per-day-wage, "
        "per-week-salary, semi-month-salary, bi-month-salary, "
        "bi-week-salary, one-time) — F2, second-reader report on #487: "
        "omitting a documented, representable label dropped every real "
        "week-paid Lever offer to 'no salary' instead of comparing it "
        "against the floor, which is worse than `main`, not safer",
        connector="lever_en",
    ),
    PeriodContract(
        "Lever salaryRange.interval",
        "PER-YEAR-SALARY",
        "year",
        "same label, upper case — the table folds case regardless of source",
    ),
    # Lever's `one-time` is a lump sum, not a period: it must be refused, not
    # read as "no period" (that is the fail-open the task exists to close).
    PeriodContract(
        "Lever salaryRange.interval",
        "one-time",
        None,
        "connectors/lever_en's task filing (#454): "
        '"Lever writes that field as labels: ... one-time"',
    ),
    # Lever-documented labels with no matching SalaryPeriod member — refused
    # by design, not by omission (F2, #487): SalaryPeriod has no twice-a-month
    # or fortnight-shaped member, so none of the three has anywhere correct
    # to land, and admitting one under the nearest wrong period would
    # misstate the wage rather than merely drop it.
    PeriodContract(
        "Lever salaryRange.interval",
        "semi-month-salary",
        None,
        "Lever Postings API reference: salaryRange.interval enum — no "
        "twice-a-month member of SalaryPeriod exists to map it onto",
    ),
    PeriodContract(
        "Lever salaryRange.interval",
        "bi-month-salary",
        None,
        "Lever Postings API reference: salaryRange.interval enum — no "
        "bi-monthly member of SalaryPeriod exists to map it onto",
    ),
    PeriodContract(
        "Lever salaryRange.interval",
        "bi-week-salary",
        None,
        "Lever Postings API reference: salaryRange.interval enum — no "
        "fortnight-shaped member of SalaryPeriod exists to map it onto",
    ),
    # --- Himalayas' public API, `salaryPeriod` — the Remote Jobs API
    # Reference's full enum (F1, #487): `annual`/`hourly` are also this
    # library's own direct, dated capture, in that connector's own
    # meta.yaml/fixture. ---
    PeriodContract(
        "Himalayas salaryPeriod",
        "annual",
        "year",
        'connectors/himalayas_en/fixture/list.html: "salaryPeriod": "annual"',
        connector="himalayas_en",
    ),
    PeriodContract(
        "Himalayas salaryPeriod",
        "hourly",
        "hour",
        'connectors/himalayas_en/fixture/list.html: "salaryPeriod": "hourly"',
        connector="himalayas_en",
    ),
    PeriodContract(
        "Himalayas salaryPeriod",
        "Annual",
        "year",
        "same value, title case",
    ),
    PeriodContract(
        "Himalayas salaryPeriod",
        "  hourly  ",
        "hour",
        "same value, padded",
    ),
    PeriodContract(
        "Himalayas salaryPeriod",
        "monthly",
        "month",
        "Himalayas Remote Jobs API Reference: salaryPeriod enum (hourly, "
        "weekly, fortnightly, monthly, annual) — F1, second-reader report on "
        "#487: this label was missing from _TABLE, so a real Himalayas "
        "monthly-paid offer below the candidate's floor was admitted "
        "instead of dropped",
        connector="himalayas_en",
    ),
    PeriodContract(
        "Himalayas salaryPeriod",
        "weekly",
        "week",
        "Himalayas Remote Jobs API Reference: salaryPeriod enum (hourly, "
        "weekly, fortnightly, monthly, annual)",
        connector="himalayas_en",
    ),
    PeriodContract(
        "Himalayas salaryPeriod",
        "Monthly",
        "month",
        "same value, title case",
    ),
    PeriodContract(
        "Himalayas salaryPeriod",
        "  monthly  ",
        "month",
        "same value, padded",
    ),
    # `fortnightly` is Himalayas-documented and still refused: SalaryPeriod
    # has no fortnight-shaped member for it to land on, so guessing it onto
    # "week" or "month" would misstate the wage rather than merely drop it —
    # the same refusal as Lever's semi-month/bi-* labels, not an oversight.
    PeriodContract(
        "Himalayas salaryPeriod",
        "fortnightly",
        None,
        "Himalayas Remote Jobs API Reference: salaryPeriod enum (hourly, "
        "weekly, fortnightly, monthly, annual) — no fortnight-shaped member "
        "of SalaryPeriod exists to map it onto",
    ),
    # --- Generic fail-open shapes: nothing board-specific, everything this
    # task was filed to close a hole for. ---
    PeriodContract(
        "n/a — absent field",
        None,
        None,
        "no salary_period at all is not a period this table is asked about; "
        "build_offer, not normalize_period, decides what an absent field means",
    ),
    PeriodContract(
        "n/a — empty string",
        "",
        None,
        "an empty label names no period; the table has no entry for it",
    ),
    PeriodContract(
        "n/a — whitespace only",
        "   ",
        None,
        "whitespace-only is empty after stripping; the table has no entry for it",
    ),
    PeriodContract(
        "n/a — resembles a period",
        "yearly-bonus",
        None,
        "T170's own filing names this shape: 'a value that only resembles a "
        "period (yearly-bonus)' is a fail-closed row, not a match on 'year'",
    ),
    PeriodContract(
        "n/a — resembles a period",
        "per-year",
        None,
        "missing the '-salary' Lever actually sends; a prefix match would be "
        "the same fail-open shape as 'yearly-bonus'",
    ),
    PeriodContract(
        "n/a — resembles a period",
        "year2024",
        None,
        "contains the letters of 'year' without being it",
    ),
    PeriodContract(
        "n/a — unrelated word",
        "biweekly",
        None,
        "not literally documented by any surveyed board — Lever spells the "
        "same concept `bi-week-salary` and Himalayas spells it "
        "`fortnightly` (see those rows), both refused too. The reason "
        "either way is the same and does not depend on wording: SalaryPeriod "
        "has no fortnight-shaped member for any of the three to land on",
    ),
)

#: The floor. `CONTRACT_CASES` held 36 rows when this task landed; set below
#: that so appending a case never trips it, and deleting most of the table
#: does (T100's convention — a count committed exactly drifts on every PR that
#: touches this file for an unrelated reason). It is not, on its own, a
#: substitute for the connector-coverage check in `tests/test_salary_period.
#: py` — a floor this far below the real count can still be cleared by
#: deleting a whole board's rows, which is exactly what F3 (second-reader
#: report on #487) measured: every Lever row deleted from both `_TABLE` and
#: `CONTRACT_CASES` still left this floor satisfied. That test asserts what a
#: row count cannot: every connector whose field map names `salary_period`,
#: derived from the real `connectors/` tree, is backed by a positive row here.
MINIMUM_PERIOD_CONTRACTS = 20


def _check_contracts() -> tuple[int, int, list[str]]:
    defects = []
    for case in CONTRACT_CASES:
        actual = normalize_period(case.raw)
        if actual != case.expected:
            defects.append(
                f"{case.board} {case.raw!r}: expected {case.expected!r}, got {actual!r} "
                f"(per {case.citation})"
            )
    return len(defects), len(CONTRACT_CASES), defects


def measure() -> dict[str, Any]:
    """T170's gate: `period_contracts_failing`.

    A count of zero over zero cases evaluated is what a check that never ran
    also reports, so `gate_status` reads `unmeasured` while the table is
    empty, and the committed record asserts `period_contracts_at_least`
    rather than the count of the day (T100/T122).
    """
    failing, evaluated, defects = _check_contracts()
    return {
        "period_contracts_failing": failing,
        "period_contracts_evaluated": evaluated,
        "gate_status": "measured" if evaluated else "unmeasured",
        "table_size": len(_TABLE),
        "vocabulary": sorted(get_args(SalaryPeriod)),
        "defects": defects,
    }


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed: the floor in place of the case count (T100)."""
    committed = {
        key: value for key, value in measured.items() if key != "period_contracts_evaluated"
    }
    committed["period_contracts_at_least"] = MINIMUM_PERIOD_CONTRACTS
    return committed


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T170.json`; return what was measured."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str] | None = None) -> int:
    """`python -m integral.salary_period [--check]`."""
    check_only = argv is not None and "--check" in argv
    measured = measure() if check_only else write_evidence()
    print(json.dumps(measured, ensure_ascii=False))
    for defect in measured["defects"]:
        print(f"✗ {defect}", file=sys.stderr)
    if measured["gate_status"] == "unmeasured":
        return 3
    if measured["period_contracts_failing"]:
        return 1
    if measured["period_contracts_evaluated"] < MINIMUM_PERIOD_CONTRACTS:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
