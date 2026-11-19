"""Follow-up reminder at 21 days and `stalled` at 60, from the application date."""

from datetime import date, timedelta

import pytest

from integral.applications_board import (
    FOLLOW_UP,
    STALLED,
    Board,
    Fit,
    Row,
    follow_up,
    render,
)

SENT = date(2026, 1, 1)


def at(days: int, status: str = "applied") -> str:
    return follow_up(status, SENT.isoformat(), SENT + timedelta(days=days))


def test_day_20_shows_nothing() -> None:
    assert at(20) == ""


def test_day_21_reminds_and_holds_until_stalled() -> None:
    assert at(21) == FOLLOW_UP
    assert at(59) == FOLLOW_UP


def test_day_60_is_stalled() -> None:
    assert at(60) == STALLED
    assert at(400) == STALLED


@pytest.mark.parametrize("status", ["interview", "rejected", "hired", "offer", "no response"])
def test_a_recorded_response_clears_both(status: str) -> None:
    assert at(30, status) == ""
    assert at(90, status) == ""


def test_time_alone_never_yields_rejected() -> None:
    assert {at(d) for d in range(1000)} <= {"", FOLLOW_UP, STALLED}


def test_no_usable_date_shows_nothing() -> None:
    assert follow_up("applied", "not recorded", SENT) == ""


def test_the_reminder_shows_once_on_the_card() -> None:
    row = Row(
        "o", "Acme", "Dev", SENT.isoformat(), "sent", "applied", "x", "x", "", "", Fit(False),
        follow_up=FOLLOW_UP,
    )  # fmt: skip
    assert render(Board((row,), {}), generated_at="now").count(FOLLOW_UP) == 1
