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


def test_a_sole_profile_offered_for_confirmation_reveals_nothing_from_inside_it(
    tmp_path: Path,
) -> None:
    """The confirm path: the one arrival where a profile's contents could reach someone
    who has not yet said they are that person."""
    root = tmp_path / "profiles"
    store = _profile(root, "marcos", "Marcos", stamp="2026-01-01T00:00:00+00:00")
    before = store.path("session", "state.json").read_bytes()
    result = run(root, now=NOW)
    said = json.dumps(result.as_json())
    assert result.outcome == "confirm"
    assert "2026-01-01" not in said and "history" not in said
    assert store.path("session", "state.json").read_bytes() == before


def test_two_profiles_with_one_display_name_ask_for_a_handle_and_list_none(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    _profile(root, "marcos", "Marcos")
    _profile(root, "marcos-b", "Marcos")
    said = run(root, now=NOW).say
    assert "give me your handle" in said
    assert "marcos" not in said.lower().replace("marcos, marcos", "")
    assert "marcos-b" not in said


def test_either_of_two_same_named_profiles_opens_by_its_own_handle(tmp_path: Path) -> None:
    """The first handle is the one derived from the shared name — it must resolve too."""
    root = tmp_path / "profiles"
    _profile(root, "marcos", "Marcos")
    _profile(root, "marcos-b", "Marcos")
    assert drive(root, [{"handle": "marcos"}], NOW)[1].handle == "marcos"
    assert drive(root, [{"handle": "marcos-b"}], NOW)[1].handle == "marcos-b"


def test_names_compare_in_nfc_so_a_decomposed_name_still_collides(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _profile(root, "nuria-a", "N\u00faria")
    _profile(root, "nuria-b", "Nu\u0301ria")
    assert "give me your handle" in run(root, now=NOW).say


def test_distinct_names_are_not_cluttered_with_handles(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _profile(root, "marcos", "Marcos")
    _profile(root, "nuria", "Núria")
    assert "(" not in run(root, now=NOW).say


def test_a_simulated_candidate_is_reachable_only_when_asked_for(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "profiles"
    create_profile(root, "Ada", language="en", handle="ada", fiction=True)
    assert step0_open._main(["x", "open", "--root", str(root), "--handle", "ada"]) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "create"
    args = ["x", "open", "--root", str(root), "--handle", "ada", "--include-fiction"]
    assert step0_open._main(args) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "opened"


def test_a_leftover_simulated_profile_does_not_block_or_name_a_real_candidate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    _profile(root, "marcos", "Marcos")
    create_profile(root, "Ada", language="en", handle="sim-ada", fiction=True)
    sole = run(root, now=NOW)
    assert sole.outcome == "confirm" and sole.say == "Is this Marcos?"
    newcomer = run(root, handle="zoe", now=NOW)
    assert newcomer.outcome == "create"
    assert "sim-ada" not in json.dumps(newcomer.as_json())


def test_a_stray_directory_blocks_nobody_and_is_never_named(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _profile(root, "marcos", "Marcos")
    _profile(root, "nuria", "Núria")
    (root / "zz-half-written").mkdir()
    assert run(root, now=NOW).outcome == "choose"
    assert run(root, handle="ada", now=NOW).outcome == "create"
    assert run(root, handle="zz-half-written", now=NOW).outcome == "create"


def test_a_root_holding_only_a_stray_directory_offers_create(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    (root / "zz-half-written").mkdir(parents=True)
    assert run(root, now=NOW).outcome == "create"


def test_a_corrupt_profile_blocks_only_its_own_arrival_and_names_nothing(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _profile(root, "marcos", "Marcos")
    broken = _profile(root, "nuria", "Núria")
    broken.path("identity.json").write_text("{not json", encoding="utf-8")
    assert run(root, handle="nuria", now=NOW).outcome == "unreadable"
    assert run(root, handle="ada", now=NOW).outcome == "create"
    assert run(root, now=NOW).outcome == "confirm"
    said = json.dumps(run(root, handle="nuria", now=NOW).as_json())
    assert "nuria" not in said.lower().replace("unreadable", "")


def test_a_corrupt_state_file_is_reported_not_raised_and_left_alone(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    store = _profile(root, "marcos", "Marcos")
    store.path("session", "state.json").write_text("{not json", encoding="utf-8")
    result = run(root, handle="marcos", now=NOW)
    assert result.outcome == "unreadable" and result.handle == "marcos"
    assert store.path("session", "state.json").read_text(encoding="utf-8") == "{not json"


def test_a_corrupt_sole_identity_is_never_reported_as_no_profile(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    store = _profile(root, "marcos", "Marcos")
    store.path("identity.json").write_text("{not json", encoding="utf-8")
    result = run(root, now=NOW)
    assert result.outcome == "unreadable" and "marcos" not in result.say.lower()
    assert "don't have a profile" not in result.say


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
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`make evidence` runs every module bare; that run must not touch a real profile."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("INTEGRAL_HOME", str(home))
    target = tmp_path / "T207.json"
    assert step0_open._main(["x", str(target)]) == 0
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["scenario_calls"] == EXPECTED_CALLS
    assert written["step0_calls_before_profile_read"] <= 3
    assert "slowest_seconds" not in written  # a timing would drift on every run
    assert list(home.rglob("*")) == [], "the evidence run wrote under the candidate store"


def test_the_skill_names_the_command_and_refuses_the_hand_walk() -> None:
    """The measured count is the tool's; this is what keeps a session to the tool."""
    text = SKILL.read_text(encoding="utf-8")
    assert "integral.step0_open open" in text
    assert "never by walking `profiles/` by hand" in text


def test_the_skill_does_not_ask_for_a_second_call_to_build_the_opening() -> None:
    """The metric counts the tool's calls; the skill must not add one the evidence cannot see."""
    text = SKILL.read_text(encoding="utf-8")
    assert "it is the only call step 0 makes" in text
    assert "with no further file reads" in text
    assert "--include-fiction" in text
    assert "give me your handle" in text or "give their handle" in text
