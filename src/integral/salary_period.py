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
    # Lever's Postings API, `salaryRange.interval` — the label Lever's own
    # posting JSON carries, per `connectors/lever_en/connector.yaml`'s header
    # ("`interval` is Lever's own period label (`per-year-salary`)"), and the
    # set the task that filed this table measured on 2026-09-10 (#454). Egress
    # to Lever's own API docs is blocked from this environment, so this table
    # commits only the four labels this repository has direct, dated evidence
    # for; a fifth Lever label (`per-week-salary` is sometimes described
    # elsewhere) is deliberately left OUT rather than guessed at — an
    # unlisted label already falls to "no stated salary" below, which is the
    # safe side for a label nobody here has verified.
    "per-year-salary": "year",
    "per-month-salary": "month",
    "per-hour-wage": "hour",
    "per-day-wage": "day",
    # `one-time` is intentionally absent: it is Lever's label for a lump sum,
    # not a pay period, and `normalize_period` must refuse it rather than
    # silently drop it to "no period" (see `build_offer`).
    #
    # Himalayas' public API, `salaryPeriod` — the only two values this
    # library has ever captured from it, in `connectors/himalayas_en/fixture/
    # list.html` (a dated, sampled response per that connector's `meta.yaml`).
    "annual": "year",
    "hourly": "hour",
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
    compares against `normalize_period`.
    """

    board: str
    raw: str | None
    expected: SalaryPeriod | None
    citation: str


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
    ),
    PeriodContract(
        "schema.org unitText",
        "MONTH",
        "month",
        'connectors/justjoin_en/fixture/detail.html: "unitText": "MONTH"',
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
    # --- Lever Postings API, `salaryRange.interval` — the exact labels T170's
    # own filing measured from `connectors/lever_en` on 2026-09-10 (#454). ---
    PeriodContract(
        "Lever salaryRange.interval",
        "per-year-salary",
        "year",
        "connectors/lever_en/connector.yaml header; #454 measurement, 2026-09-10",
    ),
    PeriodContract(
        "Lever salaryRange.interval",
        "per-month-salary",
        "month",
        "connectors/lever_en/connector.yaml header; #454 measurement, 2026-09-10",
    ),
    PeriodContract(
        "Lever salaryRange.interval",
        "per-hour-wage",
        "hour",
        "connectors/lever_en/connector.yaml header; #454 measurement, 2026-09-10",
    ),
    PeriodContract(
        "Lever salaryRange.interval",
        "per-day-wage",
        "day",
        "connectors/lever_en/connector.yaml header; #454 measurement, 2026-09-10",
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
    # A Lever-shaped label this table has no dated evidence for. The design
    # says an unrepresentable label drops the salary rather than being
    # guessed at — proving that is the point of this row, not an oversight
    # that it is missing from `_TABLE`.
    PeriodContract(
        "Lever salaryRange.interval",
        "per-week-salary",
        None,
        "not in this repository's dated evidence for Lever's enum — refused, "
        "not guessed (see _TABLE's comment)",
    ),
    # --- Himalayas' public API, `salaryPeriod` — the only two values this
    # library has ever captured, dated in that connector's own meta.yaml. ---
    PeriodContract(
        "Himalayas salaryPeriod",
        "annual",
        "year",
        'connectors/himalayas_en/fixture/list.html: "salaryPeriod": "annual"',
    ),
    PeriodContract(
        "Himalayas salaryPeriod",
        "hourly",
        "hour",
        'connectors/himalayas_en/fixture/list.html: "salaryPeriod": "hourly"',
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
    # A Himalayas value this table has no dated capture for — same refusal
    # rule as Lever's `per-week-salary` above.
    PeriodContract(
        "Himalayas salaryPeriod",
        "monthly",
        None,
        "not in this repository's dated capture of Himalayas' salaryPeriod "
        "values — refused, not guessed",
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
        "not a member of any surveyed board's documented vocabulary",
    ),
)

#: The floor. `CONTRACT_CASES` held 28 rows when this task landed; set below
#: that so appending a case never trips it, and deleting most of the table
#: does (T100's convention — a count committed exactly drifts on every PR that
#: touches this file for an unrelated reason).
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
