"""T207 — step 0 resolves and opens in one command, in a bounded number of calls."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from integral import step0_open
from integral.identity import ProfileStore, create_profile
from integral.session import SessionStore
from integral.step0_open import EXPECTED_CALLS, drive, run

NOW = datetime(2026, 10, 4, tzinfo=UTC)
SKILL = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "step-00-identify" / "SKILL.md"
STAMP = "2026-09-13T09:00:00+00:00"


def _profile(root: Path, handle: str, display: str, *, stamp: str = STAMP) -> ProfileStore:
    create_profile(root, display, language="en", handle=handle)
    store = ProfileStore(root, handle)
    SessionStore(store).record(at=stamp, current_step="history")
    return store


def test_calls_per_arrival_are_exactly_what_the_skill_prescribes(tmp_path: Path) -> None:
    """A ceiling alone passes a one-call step split in two; the counts are pinned each."""
    solo = tmp_path / "solo"
    _profile(solo, "marcos", "Marcos")
    assert (
        drive(solo, [], NOW, first={"handle": "marcos"})[0]
        == EXPECTED_CALLS["names_themselves"]
        == 1
    )
    assert (
        drive(solo, [{"confirmed": True}], NOW)[0] == EXPECTED_CALLS["only_profile_confirms"] == 2
    )

    several = tmp_path / "several"
    _profile(several, "marcos", "Marcos")
    _profile(several, "nuria", "Núria")
    assert drive(several, [{"handle": "marcos"}], NOW)[0] == EXPECTED_CALLS["one_of_several"] == 2
    assert max(EXPECTED_CALLS.values()) <= 3


def test_nothing_inside_a_profile_is_read_or_written_before_a_handle_resolves(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    first = _profile(root, "marcos", "Marcos", stamp="2026-01-01T00:00:00+00:00")
    _profile(root, "nuria", "Núria", stamp="2026-01-02T00:00:00+00:00")
    before = first.path("session", "state.json").read_bytes()

    attempts: list[dict[str, Any]] = [{}, {"handle": "nobody"}]
    for kwargs in attempts:
        said = json.dumps(run(root, now=NOW, **kwargs).as_json())
        assert "2026-01-01" not in said and "history" not in said
    assert first.path("session", "state.json").read_bytes() == before


def test_a_sole_profile_is_offered_and_never_assumed(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    store = _profile(root, "marcos", "Marcos")
    before = store.path("session", "state.json").read_bytes()
    result = run(root, now=NOW)
    assert result.outcome == "confirm" and result.handle is None
    assert store.path("session", "state.json").read_bytes() == before


def test_an_unknown_name_offers_to_create(tmp_path: Path) -> None:
    result = run(tmp_path / "profiles", handle="ada", now=NOW)
    assert result.outcome == "create"


def test_opening_says_when_and_where_and_writes_last_activity(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    store = _profile(root, "marcos", "Marcos")
    result = run(root, handle="marcos", now=NOW)
    assert result.outcome == "opened" and result.handle == "marcos"
    assert "Hello again, Marcos, about 3 weeks ago." in result.say
    assert result.last_activity == STAMP
    after = SessionStore(store).read()
    assert after is not None and after.last_activity == "2026-10-04T00:00:00+00:00"


def test_a_first_visit_is_not_told_it_is_a_return(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    create_profile(root, "Ada", language="en", handle="ada")
    result = run(root, handle="ada", now=NOW)
    assert result.outcome == "opened"
    assert "again" not in result.say and result.last_activity is None


@pytest.mark.parametrize(
    ("then", "phrase"),
    [
        ("2026-10-04T00:00:00+00:00", "earlier today"),
        ("2026-10-03T00:00:00+00:00", "yesterday"),
        ("2026-09-29T00:00:00+00:00", "5 days ago"),
        ("2026-06-04T00:00:00+00:00", "about 4 months ago"),
        ("not a date", None),
    ],
)
def test_elapsed_time_reads_naturally(then: str, phrase: str | None) -> None:
    assert step0_open._ago(then, NOW) == phrase


def test_the_command_line_prints_one_json_opening(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "profiles"
    _profile(root, "marcos", "Marcos")
    assert step0_open._main(["x", "open", "--root", str(root), "--handle", "marcos"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["outcome"] == "opened" and printed["handle"] == "marcos"


def test_the_bare_command_measures_and_never_opens_a_profile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`make evidence` runs every module bare; that run must not touch a real profile."""
    target = tmp_path / "T207.json"
    assert step0_open._main(["x", str(target)]) == 0
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["scenario_calls"] == EXPECTED_CALLS
    assert written["step0_calls_before_profile_read"] <= 3
    assert "slowest_seconds" not in written  # a timing would drift on every run


def test_the_skill_names_the_command_and_refuses_the_hand_walk() -> None:
    """The measured count is the tool's; this is what keeps a session to the tool."""
    text = SKILL.read_text(encoding="utf-8")
    assert "integral.step0_open open" in text
    assert "never by walking `profiles/` by hand" in text
