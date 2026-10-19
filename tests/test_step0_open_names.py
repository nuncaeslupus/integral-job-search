"""#747 — step 0: look-alike names, accent-insensitive names, and a stateless --confirmed."""

# ruff: noqa: RUF001
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from integral.identity import ProfileStore, create_profile
from integral.session import SessionStore
from integral.step0_open import run

NOW = datetime(2026, 10, 4, tzinfo=UTC)
STAMP = "2026-09-13T09:00:00+00:00"


def _profile(root: Path, handle: str, display: str) -> ProfileStore:
    create_profile(root, display, language="en", handle=handle, now=NOW)
    store = ProfileStore(root, handle)
    SessionStore(store).record(at=STAMP, current_step="history")
    return store


# L1: names that differ only by characters a reader cannot tell apart collide.
@pytest.mark.parametrize(
    "lookalike",
    ["Аna", "Ａna", "A​na", "Anа"],  # Cyrillic A, fullwidth A, ZWSP, Cyrillic a
    ids=["cyrillic-capital", "fullwidth", "zero-width-space", "cyrillic-final"],
)
def test_a_lookalike_twin_is_a_collision_by_name(tmp_path: Path, lookalike: str) -> None:
    root = tmp_path / "profiles"
    _profile(root, "ana", "Ana")
    _profile(root, "ana-2", lookalike)
    assert run(root, name="Ana", now=NOW).outcome == "choose"
    assert run(root, name=lookalike, now=NOW).outcome == "choose"


def test_a_lookalike_twin_started_the_same_day_cannot_be_opened_by_handle(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _profile(root, "ana", "Ana")
    _profile(root, "ana-2", "Аna")
    assert run(root, handle="ana", now=NOW).outcome == "ambiguous"
    assert run(root, handle="ana-2", now=NOW).outcome == "ambiguous"


def test_distinct_names_are_not_merged(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _profile(root, "ana", "Ana")
    _profile(root, "ada", "Ada")
    assert run(root, name="Ana", now=NOW).outcome == "confirm"


# L3: an unaccented spelling finds the accented profile instead of saying "no profile".
def test_a_name_typed_without_accents_finds_the_accented_profile(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _profile(root, "nuria", "Núria")
    result = run(root, name="nuria", now=NOW)
    assert result.outcome == "confirm" and result.say == "Is this Núria?"


# L5: --confirmed on its own is not an answer.
@pytest.mark.parametrize("kwargs", [{"name": "Marcos"}, {"handle": "marcos"}, {}])
def test_confirmed_without_a_prior_question_asks_instead_of_opening(
    tmp_path: Path, kwargs: dict[str, Any]
) -> None:
    root = tmp_path / "profiles"
    store = _profile(root, "marcos", "Marcos")
    before = store.path("session", "state.json").read_bytes()
    assert run(root, confirmed=True, now=NOW, **kwargs).outcome == "confirm"
    assert store.path("session", "state.json").read_bytes() == before
    # the question has now been asked, so a yes opens
    assert run(root, confirmed=True, now=NOW, **kwargs).outcome == "opened"


def test_a_yes_to_one_profile_does_not_open_another(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _profile(root, "marcos", "Marcos")
    other = _profile(root, "nuria", "Núria")
    before = other.path("session", "state.json").read_bytes()
    assert run(root, name="Marcos", now=NOW).outcome == "confirm"
    assert run(root, name="Núria", confirmed=True, now=NOW).outcome == "confirm"
    assert other.path("session", "state.json").read_bytes() == before


def test_a_yes_is_spent_once_opened(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    _profile(root, "marcos", "Marcos")
    run(root, name="Marcos", now=NOW)
    assert run(root, name="Marcos", confirmed=True, now=NOW).outcome == "opened"
    assert run(root, name="Marcos", confirmed=True, now=NOW).outcome == "confirm"
