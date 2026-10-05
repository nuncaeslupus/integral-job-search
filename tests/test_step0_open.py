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
YES = {"confirmed": True}


def _profile(root: Path, handle: str, display: str, *, stamp: str = STAMP) -> ProfileStore:
    create_profile(root, display, language="en", handle=handle)
    store = ProfileStore(root, handle)
    SessionStore(store).record(at=stamp, current_step="history")
    return store


def _state(store: ProfileStore) -> bytes:
    return store.path("session", "state.json").read_bytes()


def test_calls_per_arrival_are_exactly_what_the_skill_prescribes(tmp_path: Path) -> None:
    """A ceiling alone passes one call split in two; the counts are pinned each."""
    solo = tmp_path / "solo"
    _profile(solo, "marcos", "Marcos")
    named = drive(solo, [{"name": "Marcos", **YES}], NOW, first={"name": "Marcos"})[0]
    assert named == EXPECTED_CALLS["names_themselves"] == 2
    assert drive(solo, [YES], NOW)[0] == EXPECTED_CALLS["only_profile_confirms"] == 2

    several = tmp_path / "several"
    _profile(several, "marcos", "Marcos")
    _profile(several, "nuria", "Núria")
    answers: list[dict[str, Any]] = [{"name": "Marcos"}, {"name": "Marcos", **YES}]
    assert drive(several, answers, NOW)[0] == EXPECTED_CALLS["one_of_several"] == 3
    assert max(EXPECTED_CALLS.values()) <= 3


def test_nothing_inside_a_profile_is_read_or_written_before_a_handle_resolves(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    first = _profile(root, "marcos", "Marcos", stamp="2026-01-01T00:00:00+00:00")
    _profile(root, "nuria", "Núria", stamp="2026-01-02T00:00:00+00:00")
    before = _state(first)

    attempts: list[dict[str, Any]] = [
        {},
        {"name": "nobody"},
        {"name": "Marcos"},
        {"handle": "marcos"},
    ]
    for kwargs in attempts:
        said = json.dumps(run(root, now=NOW, **kwargs).as_json())
        assert "2026-01-01" not in said and "history" not in said
    assert _state(first) == before


def test_a_sole_profile_offered_for_confirmation_reveals_nothing_from_inside_it(
    tmp_path: Path,
) -> None:
    """The confirm path: the one arrival where a profile's contents could reach someone
    who has not yet said they are that person."""
    root = tmp_path / "profiles"
    store = _profile(root, "marcos", "Marcos", stamp="2026-01-01T00:00:00+00:00")
    before = _state(store)
    result = run(root, now=NOW)
    said = json.dumps(result.as_json())
    assert result.outcome == "confirm"
    assert "2026-01-01" not in said and "history" not in said
    assert _state(store) == before


def test_a_sole_profile_is_offered_and_never_assumed(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    store = _profile(root, "marcos", "Marcos")
    before = _state(store)
    result = run(root, now=NOW)
    assert result.outcome == "confirm" and result.handle is None
    assert _state(store) == before


def test_an_unknown_name_offers_to_create(tmp_path: Path) -> None:
    result = run(tmp_path / "profiles", name="ada", now=NOW)
    assert result.outcome == "create"


def test_opening_says_when_and_where_and_writes_last_activity(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    store = _profile(root, "marcos", "Marcos")
    result = run(root, name="Marcos", confirmed=True, now=NOW)
    assert result.outcome == "opened" and result.handle == "marcos"
    assert "Hello again, Marcos, about 3 weeks ago." in result.say
    assert result.last_activity == STAMP
    after = SessionStore(store).read()
    assert after is not None and after.last_activity == "2026-10-04T00:00:00+00:00"


def test_a_first_visit_is_not_told_it_is_a_return(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    create_profile(root, "Ada", language="en", handle="ada")
    result = run(root, name="Ada", confirmed=True, now=NOW)
    assert result.outcome == "opened"
    assert "again" not in result.say and result.last_activity is None


def test_a_name_never_opens_anyone_without_a_yes(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    store = _profile(root, "marcos", "Marcos")
    before = _state(store)
    result = run(root, name="Marcos", now=NOW)
    assert result.outcome == "confirm" and result.say == "Is this Marcos?"
    assert _state(store) == before


def test_a_name_that_is_another_persons_handle_never_opens_that_profile(tmp_path: Path) -> None:
    """`profiles/ana` is Bea; Ana is `bea-x`. Ana typing `ana` is a name, not a handle."""
    root = tmp_path / "profiles"
    bea = _profile(root, "ana", "Bea")
    ana = _profile(root, "bea-x", "Ana")
    before = (_state(bea), _state(ana))
    result = run(root, name="ana", now=NOW)
    assert result.outcome == "confirm" and result.say == "Is this Ana?"
    assert (_state(bea), _state(ana)) == before
    # Even the answer to the confirmation is bound to the profile named Ana.
    assert run(root, name="ana", confirmed=True, now=NOW).handle == "bea-x"


def test_a_mistyped_handle_is_confirmed_by_name_before_it_opens_anyone(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    bea = _profile(root, "ana", "Bea")
    before = _state(bea)
    result = run(root, handle="ana", now=NOW)
    assert result.outcome == "confirm" and result.say.startswith("Is this Bea, whose profile")
    assert _state(bea) == before


def test_the_second_of_two_same_named_people_typing_the_first_handle_opens_nothing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    first, second = _twins(
        root, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 20, tzinfo=UTC)
    )
    before = (_state(first), _state(second))
    by_name = run(root, name="marcos", now=NOW)
    assert by_name.outcome == "choose" and by_name.handle is None
    assert run(root, name="marcos", confirmed=True, now=NOW).outcome == "choose"
    by_handle = run(root, handle="marcos", now=NOW)
    assert by_handle.outcome == "confirm" and by_handle.handle is None
    assert "started on" in by_handle.say
    assert (_state(first), _state(second)) == before


def test_the_handle_question_carries_the_target_profiles_own_start_date(tmp_path: Path) -> None:
    """Past the yes: the second Marcos guesses `marcos`, and the question shows him the
    first Marcos's date, which is not his. The skill tells the agent to answer no then."""
    root = tmp_path / "profiles"
    first_day = datetime(2026, 9, 1, tzinfo=UTC)
    second_day = datetime(2026, 9, 20, tzinfo=UTC)
    create_profile(root, "Marcos", language="en", handle="marcos", now=first_day)
    create_profile(root, "Marcos", language="en", handle="marcos-b", now=second_day)
    for handle in ("marcos", "marcos-b"):
        SessionStore(ProfileStore(root, handle)).record(at=STAMP, current_step="history")
    asked = run(root, handle="marcos", now=NOW)
    assert asked.outcome == "confirm" and asked.handle is None
    assert asked.say == "Is this Marcos, whose profile was started on 2026-09-01?"
    assert "2026-09-20" not in asked.say  # the other twin's date is not shown
    assert "history" not in asked.say and STAMP[:10] not in asked.say
    other = run(root, handle="marcos-b", now=NOW)
    assert other.say == "Is this Marcos, whose profile was started on 2026-09-20?"
    skill = SKILL.read_text(encoding="utf-8")
    assert "if the date is not theirs the answer is no" in skill


def test_two_profiles_with_one_display_name_ask_for_a_handle_and_list_none(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    _twins(root, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 20, tzinfo=UTC))
    for said in (run(root, now=NOW).say, run(root, name="Marcos", now=NOW).say):
        assert "give me your handle" in said
        assert "marcos-b" not in said
        assert "marcos" not in said.lower().replace("marcos, marcos", "")


def test_either_of_two_same_named_profiles_opens_by_its_own_handle(tmp_path: Path) -> None:
    """The first handle is the one derived from the shared name — it must resolve too."""
    root = tmp_path / "profiles"
    _twins(root, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 20, tzinfo=UTC))
    for handle in ("marcos", "marcos-b"):
        answers: list[dict[str, Any]] = [{"handle": handle}, {"handle": handle, **YES}]
        assert drive(root, answers, NOW)[1].handle == handle


def test_names_compare_in_nfc_so_a_decomposed_name_still_collides(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _profile(root, "nuria-a", "Núria")
    _profile(root, "nuria-b", "Núria")
    assert "give me your handle" in run(root, now=NOW).say
    assert run(root, name="NÚRIA", now=NOW).outcome == "choose"


def test_the_collision_wording_does_not_count(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    for handle in ("sam-a", "sam-b", "sam-c"):
        _profile(root, handle, "Sam")
    said = run(root, now=NOW).say
    assert "two" not in said.lower() and "give me your handle" in said


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
    base = ["x", "open", "--root", str(root), "--name", "Ada", "--confirmed"]
    assert step0_open._main(base) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "create"
    assert step0_open._main([*base, "--include-fiction"]) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "opened"


def test_a_leftover_simulated_profile_does_not_block_or_name_a_real_candidate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    _profile(root, "marcos", "Marcos")
    create_profile(root, "Ada", language="en", handle="sim-ada", fiction=True)
    sole = run(root, now=NOW)
    assert sole.outcome == "confirm" and sole.say == "Is this Marcos?"
    newcomer = run(root, name="zoe", now=NOW)
    assert newcomer.outcome == "create"
    assert "sim-ada" not in json.dumps(newcomer.as_json())


def test_a_stray_directory_blocks_nobody_and_is_never_named(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _profile(root, "marcos", "Marcos")
    _profile(root, "nuria", "Núria")
    (root / "zz-half-written").mkdir()
    assert run(root, now=NOW).outcome == "choose"
    assert run(root, name="ada", now=NOW).outcome == "create"
    assert run(root, name="zz-half-written", now=NOW).outcome == "create"
    assert run(root, handle="zz-half-written", now=NOW).outcome == "create"


def test_a_root_holding_only_a_stray_directory_offers_create(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    (root / "zz-half-written").mkdir(parents=True)
    assert run(root, now=NOW).outcome == "create"


def test_a_directory_with_a_state_file_but_no_identity_is_unreadable_not_stray(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    store = _profile(root, "marcos", "Marcos")
    store.path("identity.json").unlink()
    result = run(root, handle="marcos", now=NOW)
    assert result.outcome == "unreadable" and "marcos" not in result.say.lower()
    assert run(root, now=NOW).outcome == "unreadable"


def test_a_corrupt_profile_blocks_only_its_own_arrival_and_names_nothing(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _profile(root, "marcos", "Marcos")
    broken = _profile(root, "nuria", "Núria")
    broken.path("identity.json").write_text("{not json", encoding="utf-8")
    assert run(root, handle="nuria", now=NOW).outcome == "unreadable"
    assert run(root, name="ada", now=NOW).outcome == "create"
    assert run(root, now=NOW).outcome == "confirm"
    said = json.dumps(run(root, handle="nuria", now=NOW).as_json())
    assert "nuria" not in said.lower().replace("unreadable", "")


def test_a_corrupt_profile_named_by_its_display_name_is_matched_like_any_name(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    broken = _profile(root, "marcos", "Marcos")
    _profile(root, "nuria", "Núria")
    broken.path("identity.json").write_text("{not json", encoding="utf-8")
    for spelled in ("Marcos", "marcos", "MARCOS"):
        assert run(root, name=spelled, now=NOW).outcome == "unreadable"
    assert run(root, name="Ada", now=NOW).outcome == "create"


def test_a_corrupt_profile_is_matched_through_the_handle_its_name_would_derive(
    tmp_path: Path,
) -> None:
    """`Núria` derives `nuria`, which casefolding the name alone never produces."""
    root = tmp_path / "profiles"
    broken = _profile(root, "nuria", "Núria")
    _profile(root, "marcos", "Marcos")
    broken.path("identity.json").write_text("{not json", encoding="utf-8")
    for spelled in ("Núria", "NÚRIA"):
        assert run(root, name=spelled, now=NOW).outcome == "unreadable"


def test_a_corrupt_state_file_is_reported_not_raised_and_left_alone(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    store = _profile(root, "marcos", "Marcos")
    store.path("session", "state.json").write_text("{not json", encoding="utf-8")
    result = run(root, handle="marcos", confirmed=True, now=NOW)
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
    args = ["x", "open", "--root", str(root), "--name", "Marcos", "--confirmed"]
    assert step0_open._main(args) == 0
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


def test_the_skill_keeps_names_and_handles_apart() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "never opened directly" in text
    assert "An `ambiguous` outcome" in text
    assert "Keep what they say apart" in text
    assert "`--name`" in text and "`--handle`" in text
    assert "used only after" in text and "giving their handle" in text
    assert "never lists handles" in text


def _twins(root: Path, first: datetime, second: datetime) -> tuple[ProfileStore, ProfileStore]:
    create_profile(root, "Marcos", language="en", handle="marcos", now=first)
    create_profile(root, "Marcos", language="en", handle="marcos-b", now=second)
    stores = (ProfileStore(root, "marcos"), ProfileStore(root, "marcos-b"))
    for store in stores:
        SessionStore(store).record(at=STAMP, current_step="history")
    return stores


@pytest.mark.parametrize("junk", ["", "   ", "not a date at all", "01/09/2026 08:00"])
def test_an_unparseable_start_date_is_unreadable_on_both_calls(tmp_path: Path, junk: str) -> None:
    root = tmp_path / "profiles"
    first, second = _twins(
        root, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 20, tzinfo=UTC)
    )
    path = first.path("identity.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    record["created_at"] = junk
    path.write_text(json.dumps(record), encoding="utf-8")
    before = (_state(first), _state(second))
    both: list[dict[str, Any]] = [{}, YES]
    for kwargs in both:
        result = run(root, handle="marcos", now=NOW, **kwargs)
        assert result.outcome != "opened" and "started on" not in result.say
    assert (_state(first), _state(second)) == before


def test_same_day_twins_cannot_be_opened_by_handle_even_after_a_yes(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    day = datetime(2026, 9, 1, 8, tzinfo=UTC)
    first, second = _twins(root, day, datetime(2026, 9, 1, 17, tzinfo=UTC))
    before = (_state(first), _state(second))
    both: list[dict[str, Any]] = [{}, YES]
    for handle in ("marcos", "marcos-b"):
        for kwargs in both:
            result = run(root, handle=handle, now=NOW, **kwargs)
            assert result.outcome == "ambiguous" and "started on" not in result.say
            assert "marcos" not in result.say.lower() and "17:00" not in result.say
    assert (_state(first), _state(second)) == before


def test_twins_started_on_different_days_still_open_after_a_yes(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _twins(root, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 20, tzinfo=UTC))
    for handle in ("marcos", "marcos-b"):
        answers: list[dict[str, Any]] = [{"handle": handle}, {"handle": handle, **YES}]
        calls, opened = drive(root, answers, NOW)
        assert calls == 3 and opened.handle == handle


def test_a_unique_name_is_not_held_to_the_day_rule(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _profile(root, "marcos", "Marcos")
    _profile(root, "nuria", "Núria")  # both created today
    assert run(root, handle="marcos", confirmed=True, now=NOW).outcome == "opened"


def test_a_twin_whose_own_date_cannot_be_read_blocks_the_other_from_opening(
    tmp_path: Path,
) -> None:
    """The other profile's day is unknown, so it cannot be shown to differ: fail closed."""
    root = tmp_path / "profiles"
    first, second = _twins(
        root, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 20, tzinfo=UTC)
    )
    path = second.path("identity.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    record["created_at"] = "junk"
    path.write_text(json.dumps(record), encoding="utf-8")
    before = (_state(first), _state(second))
    both: list[dict[str, Any]] = [{}, YES]
    for kwargs in both:
        assert run(root, handle="marcos", now=NOW, **kwargs).outcome != "opened"
    assert (_state(first), _state(second)) == before
