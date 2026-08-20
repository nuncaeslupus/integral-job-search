"""T6 — the append-only evidence log, and rebuild.

The gate is `profile_rebuild_deterministic == 1`, and it is worth something
only because the derived files are a pure function of the log. Two properties
carry the task:

* **two rebuilds of one log are byte-identical** — the moment a rebuild reads
  the clock, the environment or another profile, this fails and says so;
* **writing profile B leaves profile A byte-identical** — easy to state, easy
  to believe, and only true if somebody compares the bytes.

Retraction is tested here rather than left to T38 because it is inherent to
"rebuild from the log": a retracted row must be absent from everything derived
while the row itself survives, or the log is not append-only after all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral.identity import ProfileStore, create_profile
from integral.profile import (
    DERIVED,
    EVIDENCE_PARTS,
    EvidenceLog,
    EvidenceRow,
    EvidenceSubject,
    ProfileError,
    ProfileRevision,
    derived_bytes,
    probe_legacy_rows_load_without_a_subject,
    rebuild,
    tree_bytes,
)


def _log(root: Path, display_name: str) -> EvidenceLog:
    identity = create_profile(root, display_name, language="en")
    return EvidenceLog(ProfileStore(root, identity.handle))


def _populate(log: EvidenceLog) -> None:
    """A small, realistic log: an episode, a constraint, a reaction, a statement."""
    log.append(
        recorded_at="2026-08-17T10:04:11Z",
        occurred_at="2026-03-01",
        occurred_precision="month",
        step="history",
        kind="episode",
        dimensions=["team_autonomy"],
        text="They let me pick the stack and nobody second-guessed it.",
        source="conversation",
    )
    log.append(
        recorded_at="2026-08-17T10:06:02Z",
        step="constraints",
        kind="constraint",
        dimensions=["remote_work"],
        text="Fully remote, or nothing.",
        source="conversation",
    )
    log.append(
        recorded_at="2026-08-17T10:09:40Z",
        step="reactions",
        kind="reaction",
        dimensions=["on_call"],
        text="On-call every third week? No.",
        source="offer_reaction",
    )
    log.append(
        recorded_at="2026-08-17T10:11:15Z",
        step="history",
        kind="statement",
        dimensions=["team_autonomy", "company_size"],
        text="I have only ever worked in small teams.",
        source="conversation",
    )


@pytest.fixture
def two_profiles(tmp_path: Path) -> tuple[EvidenceLog, EvidenceLog]:
    """The two-profile fixture T6 asks for."""
    root = tmp_path / "profiles"
    first = _log(root, "Ada Lovelace")
    second = _log(root, "Grace Hopper")
    _populate(first)
    return first, second


# --- determinism -----------------------------------------------------------


def test_rebuild_twice_produces_identical_bytes(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    first, _ = two_profiles
    once = rebuild(first.store)
    on_disk_once = derived_bytes(first.store)
    twice = rebuild(first.store)
    assert once == twice
    assert on_disk_once == derived_bytes(first.store)
    assert set(once) == {artefact.filename for artefact in DERIVED}


def test_rebuild_of_an_empty_log_is_still_deterministic(tmp_path: Path) -> None:
    """A profile with no evidence is a profile, not a special case."""
    log = _log(tmp_path / "profiles", "Ada Lovelace")
    assert rebuild(log.store) == rebuild(log.store)
    constraints = json.loads(rebuild(log.store)["constraints.json"])
    assert constraints["profile_revision"] == ProfileRevision.of_nothing().as_json()
    assert constraints["scored_at"] is None


def test_a_rebuild_does_not_depend_on_when_it_ran(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    """`scored_at` is the newest evidence incorporated, never the wall clock.

    A wall-clock stamp would make two rebuilds of one log differ, which
    destroys the only mechanical check that the rebuild is a function of the
    log — and §3.4 computes staleness from the revision anyway.
    """
    first, _ = two_profiles
    traits = json.loads(rebuild(first.store)["traits.json"])
    assert traits["scored_at"] == "2026-08-17T10:11:15Z"
    assert traits["scored_at"] == max(row.recorded_at for row in first.effective_rows())


def test_the_revision_moves_only_when_the_log_does(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    first, _ = two_profiles
    before = first.revision()
    rebuild(first.store)
    assert first.revision() == before, "rebuilding is not evidence"
    first.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="history",
        kind="statement",
        text="One more thing.",
        source="conversation",
    )
    after = first.revision()
    assert after.rows == before.rows + 1
    assert after.sha256 != before.sha256


# --- one profile cannot reach another --------------------------------------


def test_second_profile_does_not_leak_into_first(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    first, second = two_profiles
    rebuild(first.store)
    before = tree_bytes(first.store)

    _populate(second)
    second.append(
        recorded_at="2026-08-17T11:00:00Z",
        step="history",
        kind="statement",
        dimensions=["team_autonomy"],
        text="Grace's own words, which are nobody else's business.",
        source="conversation",
    )
    rebuild(second.store)

    assert tree_bytes(first.store) == before
    assert b"Grace" not in b"".join(tree_bytes(first.store).values())
    assert first.revision() != second.revision()


def test_ids_are_per_profile_and_start_again_at_one(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    first, second = two_profiles
    row = second.append(
        recorded_at="2026-08-17T11:00:00Z",
        step="history",
        kind="statement",
        text="First thing Grace said.",
        source="conversation",
    )
    assert row.id == "ev-000001"
    assert [r.id for r in first.rows()][-1] == "ev-000004"


# --- append-only -----------------------------------------------------------


def test_the_log_only_grows(two_profiles: tuple[EvidenceLog, EvidenceLog]) -> None:
    first, _ = two_profiles
    before = first.raw_bytes()
    first.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="history",
        kind="statement",
        text="Added later.",
        source="conversation",
    )
    assert first.raw_bytes().startswith(before)


def test_the_next_id_comes_from_the_highest_id_not_the_row_count(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    """A duplicate id is what would let a retraction suppress the wrong row."""
    first, _ = two_profiles
    path = first.store.path("profile", "evidence.jsonl")
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:2]) + "\n" + lines[3] + "\n", encoding="utf-8")
    assert first.next_id() == "ev-000005"


def test_a_malformed_line_is_reported_with_its_number(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    first, _ = two_profiles
    path = first.store.path("profile", "evidence.jsonl")
    path.write_text(path.read_text(encoding="utf-8") + '{"id": "nope"}\n', encoding="utf-8")
    with pytest.raises(ProfileError, match=r"evidence\.jsonl:5"):
        first.rows()


# --- retraction ------------------------------------------------------------


def test_a_retracted_row_is_absent_from_everything_derived_and_still_in_the_log(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    first, _ = two_profiles
    episode = first.rows()[0]
    first.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="history",
        kind="retraction",
        text="Forget what I said about that job.",
        source="conversation",
        retracts=episode.id,
    )
    written = rebuild(first.store)
    assert episode.text not in "".join(written.values())
    assert episode.id not in written["traits.json"]
    assert episode.text in first.raw_bytes().decode("utf-8"), "the log is append-only"
    assert episode.id in {row.id for row in first.rows()}
    assert episode.id not in {row.id for row in first.effective_rows()}


def test_retracting_a_retraction_puts_the_row_back(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    first, _ = two_profiles
    episode = first.rows()[0]
    undo = first.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="history",
        kind="retraction",
        text="Forget that.",
        source="conversation",
        retracts=episode.id,
    )
    assert episode.id in first.suppressed_ids()
    first.append(
        recorded_at="2026-08-18T09:01:00Z",
        step="history",
        kind="retraction",
        text="No, keep it after all.",
        source="conversation",
        retracts=undo.id,
    )
    assert episode.id not in first.suppressed_ids()
    assert episode.id in {row.id for row in first.effective_rows()}


def test_undoing_an_undo_nests_rather_than_alternating_once(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    """Three levels deep, which a single pass over the log gets wrong.

    "Forget that" → "no, keep it" → "actually, forget it" must leave the row
    suppressed. A one-pass resolution revives it, because it only ever looks
    one link up the chain.
    """
    first, _ = two_profiles
    episode = first.rows()[0]
    chain = [episode.id]
    for index, text in enumerate(("Forget that.", "No, keep it.", "Actually, forget it.")):
        row = first.append(
            recorded_at=f"2026-08-18T09:0{index}:00Z",
            step="history",
            kind="retraction",
            text=text,
            source="conversation",
            retracts=chain[-1],
        )
        chain.append(row.id)
    assert episode.id in first.suppressed_ids()
    assert episode.id not in {row.id for row in first.effective_rows()}


def test_a_retraction_row_is_not_itself_evidence(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    """A derived file listing retractions answers "what has been forgotten"."""
    first, _ = two_profiles
    first.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="history",
        kind="retraction",
        text="Forget that.",
        source="conversation",
        retracts=first.rows()[0].id,
    )
    assert all(row.kind != "retraction" for row in first.effective_rows())


def test_retracting_a_row_that_does_not_exist_is_refused(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    first, _ = two_profiles
    with pytest.raises(ProfileError, match="no such row"):
        first.append(
            recorded_at="2026-08-18T09:00:00Z",
            step="history",
            kind="retraction",
            text="Forget the thing I never said.",
            source="conversation",
            retracts="ev-999999",
        )


# --- the row contract ------------------------------------------------------


def test_a_retraction_must_name_what_it_retracts() -> None:
    with pytest.raises(ValueError, match="must name the row"):
        EvidenceRow(
            id="ev-000001",
            recorded_at="2026-08-18T09:00:00Z",
            step="history",
            kind="retraction",
            text="Forget something, unspecified.",
            source="conversation",
        )


def test_only_a_retraction_may_retract() -> None:
    with pytest.raises(ValueError, match="only a retraction row"):
        EvidenceRow(
            id="ev-000001",
            recorded_at="2026-08-18T09:00:00Z",
            step="history",
            kind="statement",
            text="Sneaking a suppression into an ordinary row.",
            source="conversation",
            retracts="ev-000000",
        )


def test_a_precision_without_a_date_says_nothing() -> None:
    with pytest.raises(ValueError, match="says nothing"):
        EvidenceRow(
            id="ev-000001",
            recorded_at="2026-08-18T09:00:00Z",
            occurred_precision="month",
            step="history",
            kind="statement",
            text="Some time ago.",
            source="conversation",
        )


def test_an_unknown_field_is_an_error_not_an_ignored_setting() -> None:
    """A typo'd key reads as a setting that took effect, so it must be refused.

    Validated from a dict rather than by keyword: the type checker rejects the
    call form, and this test is about the *runtime* refusal — a row arriving
    from a log file has never been through a type checker.
    """
    with pytest.raises(ValueError):
        EvidenceRow.model_validate(
            {
                "id": "ev-000001",
                "recorded_at": "2026-08-18T09:00:00Z",
                "step": "history",
                "kind": "statement",
                "text": "…",
                "source": "conversation",
                "confidence": 0.9,
            }
        )


def test_an_episode_stays_private_unless_it_was_approved(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    """§6.2 — recounting a failure to the tool is not consent to send it."""
    first, _ = two_profiles
    stories = [json.loads(line) for line in rebuild(first.store)["stories.jsonl"].splitlines()]
    assert stories, "the fixture has an episode in it"
    assert all(story["disclosure"] == "private" for story in stories)


# --- D-8: `about` — a capture can name the artefact it was about -----------


def test_a_row_carrying_a_subject_round_trips_through_the_log(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    first, _ = two_profiles
    subject = EvidenceSubject(kind="offer", id=f"sha256:{'c' * 64}")
    row = first.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="feedback",
        kind="statement",
        text="Too far from home.",
        source="offer_reaction",
        about=subject,
    )
    assert row.about == subject
    reread = next(r for r in EvidenceLog(first.store).rows() if r.id == row.id)
    assert reread.about == subject


def test_a_row_with_no_subject_defaults_to_none(
    two_profiles: tuple[EvidenceLog, EvidenceLog],
) -> None:
    first, _ = two_profiles
    row = first.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="history",
        kind="statement",
        text="I've only ever worked in small teams.",
        source="conversation",
    )
    assert row.about is None
    assert "about" not in row.canonical()


def test_evidence_subject_rejects_a_malformed_offer_id() -> None:
    with pytest.raises(ValueError, match="not a T11 offer id"):
        EvidenceSubject(kind="offer", id="not-an-offer-id")


def test_a_pre_d8_row_with_no_about_key_on_disk_still_loads(tmp_path: Path) -> None:
    """`EvidenceRow` is `extra="forbid"` and frozen, but that polices keys
    *present* in the data — a row minted before `about` existed has no such
    key on disk at all, and must parse exactly as it always did."""
    root = tmp_path / "profiles"
    identity = create_profile(root, "Probe Legacy Direct", handle="probe-legacy-direct")
    store = ProfileStore(root, identity.handle)
    legacy_line = json.dumps(
        {
            "dimensions": [],
            "id": "ev-000001",
            "kind": "statement",
            "recorded_at": "2026-08-01T09:00:00Z",
            "source": "offer_reaction",
            "step": "feedback",
            "text": "Too far from home.",
        },
        sort_keys=True,
    )
    path = store.path(*EVIDENCE_PARTS)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(legacy_line + "\n", encoding="utf-8")

    log = EvidenceLog(store)
    rows = log.rows()
    assert rows[0].about is None
    assert rebuild(store) == rebuild(store)


def test_probe_legacy_rows_load_without_a_subject_reports_no_failures(
    tmp_path: Path,
) -> None:
    """T6's own adversarial probe for D-8's backward-compatibility claim —
    wired into `probe_rebuild` so a regression here fails
    `profile_rebuild_deterministic`, the shipped gate, not just this test."""
    failures = probe_legacy_rows_load_without_a_subject(tmp_path / "profiles")
    assert failures == []
