"""T147 — a voice correction made once is not asked for twice.

The property under test is not "the seven regexes match their seven drafts".
It is: **a live stored preference governs every line a generation renders, from
any section, and a retracted one governs nothing.** So the cases are driven by
the generator's own section list rather than a list of sections written here,
and every case needs a compliant twin through, so refusing all prose cannot
pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import integral.generate as generate_module
from integral.cv_store import (
    CVMaster,
    Education,
    Episode,
    Experience,
    Skill,
    SourcedText,
)
from integral.generate import _CLAIMABLE, GenerationError, generate, read_manifest
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog, rebuild
from integral.retraction import retract, unretract
from integral.voice import (
    SEEDS,
    VoiceError,
    decode_preference,
    encode_preference,
    measure,
    notice,
    record,
    stored_preferences,
    violations,
)
from integral.voice import _main as voice_main

ENFORCEABLE = [seed for seed in SEEDS if seed[1]]
AT = "2026-01-01"


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


def _master_with(section: str, text: str) -> CVMaster:
    """One entry of `section` whose rendered line contains `text`."""
    if section == "headline":
        return CVMaster(headline=SourcedText(text=text))
    if section == "experience":
        return CVMaster(experience=(Experience(title="T", organisation="O", description=text),))
    if section == "education":
        return CVMaster(education=(Education(qualification=text, institution="U"),))
    if section == "skills":
        return CVMaster(skills=(Skill(name=text),))
    raise AssertionError(section)


def _documents(store: ProfileStore, offer: str, version: int) -> str:
    root = store.path("cv", "generated", offer, f"v{version}")
    return (root / "cv.md").read_text(encoding="utf-8") + (root / "letter.md").read_text(
        encoding="utf-8"
    )


# Sections a plain `master` can hold an entry in, taken from the generator's
# own list: a section added there and unreachable here fails this assertion
# instead of silently going unchecked.
_BUILDABLE = ("headline", "experience", "education", "skills")


def test_every_claimable_section_is_exercised() -> None:
    assert set(_CLAIMABLE) - {"certifications", "languages"} == set(_BUILDABLE)


@pytest.mark.parametrize("seed", ENFORCEABLE, ids=lambda s: s[0][:30])
@pytest.mark.parametrize("section", _BUILDABLE)
def test_a_violating_entry_is_withheld_in_any_section_and_its_twin_is_not(
    store: ProfileStore, seed: tuple[str, tuple[str, ...], str, str], section: str
) -> None:
    pref = record(EvidenceLog(store), seed[0], seed[1], at=AT)
    advert = f"{seed[2]} {seed[3]}"  # lets a skills entry be selected at all

    bad = generate(store, _master_with(section, seed[2]), offer_id="bad", advert=advert)
    assert seed[2] not in _documents(store, "bad", bad.version)
    omitted = [o for o in bad.omissions if seed[2] in o.text]
    assert len(omitted) == 1 and pref.statement in omitted[0].reason

    good = generate(store, _master_with(section, seed[3]), offer_id="good", advert=advert)
    assert seed[3] in _documents(store, "good", good.version)


def test_an_approved_episode_is_held_to_the_same_rule(store: ProfileStore) -> None:
    seed = ENFORCEABLE[0]
    record(EvidenceLog(store), seed[0], seed[1], at=AT)
    master = CVMaster(
        episodes=(Episode(kind="lesson", text=seed[2]), Episode(kind="lesson", text=seed[3]))
    )
    manifest = generate(store, master, offer_id="o", advert="x", _approved_episodes=(0, 1))
    text = _documents(store, "o", manifest.version)
    assert seed[2] not in text and seed[3] in text


def test_retraction_stops_a_preference_and_restoring_it_resumes(store: ProfileStore) -> None:
    log = EvidenceLog(store)
    seed = ENFORCEABLE[2]
    pref = record(log, seed[0], seed[1], at=AT)
    master = _master_with("experience", seed[2])

    live = generate(store, master, offer_id="a", advert="x")
    assert seed[2] not in _documents(store, "a", live.version)
    assert [a.row_id for a in live.voice_applied] == [pref.row_id]

    retraction = retract(log, pref.row_id, at=AT)
    gone = generate(store, master, offer_id="b", advert="x")
    assert seed[2] in _documents(store, "b", gone.version)
    assert gone.voice_applied == ()
    assert stored_preferences(log) == ()

    unretract(log, retraction.id, at=AT)
    back = generate(store, master, offer_id="c", advert="x")
    assert seed[2] not in _documents(store, "c", back.version)


def test_retracting_one_preference_leaves_the_others_in_force(store: ProfileStore) -> None:
    log = EvidenceLog(store)
    stored = [record(log, s[0], s[1], at=AT) for s in ENFORCEABLE]
    retract(log, stored[0].row_id, at=AT)
    live = {p.row_id for p in stored_preferences(log)}
    assert live == {p.row_id for p in stored[1:]}
    for seed in ENFORCEABLE[1:]:
        assert violations(seed[2], stored_preferences(log))
    assert not violations(ENFORCEABLE[0][2], stored_preferences(log))


def test_the_manifest_lists_what_was_applied_and_survives_a_round_trip(
    store: ProfileStore,
) -> None:
    log = EvidenceLog(store)
    for seed in SEEDS:
        record(log, seed[0], seed[1], at=AT)
    manifest = generate(store, _master_with("experience", "ok"), offer_id="o", advert="x")
    assert len(manifest.voice_applied) == len(SEEDS)
    assert read_manifest(store, "o", manifest.version) == manifest
    assert sum(1 for a in manifest.voice_applied if not a.enforced) == 1


def test_the_notice_counts_and_lists_and_marks_advisory(store: ProfileStore) -> None:
    log = EvidenceLog(store)
    prefs = [record(log, s[0], s[1], at=AT) for s in SEEDS]
    text = notice(prefs)
    assert text.splitlines()[0] == f"applied {len(SEEDS)} of your stored preferences:"
    for pref in prefs:
        assert pref.statement in text
    assert text.count("advisory") == 1
    assert notice([]) == "applied 0 of your stored preferences"


def test_a_scaffold_line_that_breaks_a_preference_refuses_and_writes_nothing(
    store: ProfileStore,
) -> None:
    record(EvidenceLog(store), "No offering to talk.", (r"glad to talk it through",), at=AT)
    with pytest.raises(GenerationError):
        generate(store, _master_with("experience", "ok"), offer_id="o", advert="x")
    assert not store.path("cv", "generated", "o").exists()


def test_matching_is_not_stepped_round_by_spacing_or_width(store: ProfileStore) -> None:
    log = EvidenceLog(store)
    seed = ENFORCEABLE[2]
    pref = record(log, seed[0], seed[1], at=AT)
    for variant in ("I  automated it", "I\tautomated it", "\uff29 automated it", "i AUTOMATED it"):
        assert violations(variant, [pref]), variant


def test_a_row_that_is_not_a_preference_is_never_one(store: ProfileStore) -> None:
    log = EvidenceLog(store)
    rows = [
        log.append(
            recorded_at=AT,
            step="preferences",
            kind="reaction",
            text='{"a": 1}',
            source="conversation",
        ),
        log.append(
            recorded_at=AT,
            step="preferences",
            kind="statement",
            text="plain words",
            source="conversation",
        ),
        log.append(
            recorded_at=AT,
            step="intake",
            kind="statement",
            text=encode_preference("right text, wrong step", (r"x",)),
            source="conversation",
        ),
        log.append(
            recorded_at=AT,
            step="preferences",
            kind="statement",
            text=json.dumps({"voice_preference": {"statement": "bad", "forbid": ["("]}}),
            source="conversation",
        ),
    ]
    assert [decode_preference(r) for r in rows] == [None] * len(rows)
    assert stored_preferences(log) == ()


def test_a_preference_that_would_forbid_everything_is_refused() -> None:
    for pattern in ("", ".*", "x?", "(", "[a"):
        with pytest.raises(VoiceError):
            encode_preference("s", (pattern,))
    with pytest.raises(VoiceError):
        encode_preference("   ", ())


def test_voice_rows_do_not_break_a_rebuild(store: ProfileStore) -> None:
    log = EvidenceLog(store)
    for seed in SEEDS:
        record(log, seed[0], seed[1], at=AT)
    rebuild(store)
    assert len(stored_preferences(log)) == len(SEEDS)


def test_each_seed_draft_breaks_only_its_own_preference(store: ProfileStore) -> None:
    prefs = [record(EvidenceLog(store), s[0], s[1], at=AT) for s in SEEDS]
    for seed, pref in zip(SEEDS, prefs, strict=True):
        if not seed[1]:
            continue
        assert [p.row_id for p in violations(seed[2], prefs)] == [pref.row_id]
        assert violations(seed[3], prefs) == []


def test_the_gate_measures_zero_and_checks_every_enforceable_seed() -> None:
    measured = measure()
    assert measured["voice_preference_defects"] == 0, measured["defects"]
    assert measured["preferences_checked"] == len(ENFORCEABLE)
    # A literal, not derived from the seeds: deleting a seed lowers both sides
    # of the line above and nothing else would notice.
    assert measured["preferences_checked"] == 6
    assert measured["preferences_stored"] == 7
    assert measured["preferences_stored"] == len(SEEDS)


def test_the_gate_notices_a_generator_that_ignores_preferences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generate_module, "_voice_filter", lambda master, chosen, prefs: (chosen, [])
    )
    measured = measure()
    assert measured["voice_preference_defects"] >= len(ENFORCEABLE)


def test_the_gate_notices_a_generator_that_ignores_retraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import integral.profile as profile_module

    # Suppression is never applied: retracted rows stay "effective".
    monkeypatch.setattr(
        profile_module.EvidenceLog,
        "suppressed_ids",
        lambda self: frozenset(),
    )
    assert measure()["voice_preference_defects"] > 0


def test_the_command_writes_evidence_only_where_told(tmp_path: Path) -> None:
    target = tmp_path / "T147.json"
    assert voice_main(["voice", str(target)]) == 0
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["voice_preference_defects"] == 0
