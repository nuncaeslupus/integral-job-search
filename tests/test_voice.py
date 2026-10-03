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
import sys
import unicodedata
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
from integral.profile import EvidenceLog, Kind, rebuild
from integral.retraction import retract, unretract
from integral.voice import (
    SEEDS,
    VoiceError,
    VoicePreference,
    decode_preference,
    encode_preference,
    is_invisible,
    measure,
    notice,
    record,
    stored_preferences,
    unreadable_preferences,
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
    assert text.splitlines()[0] == f"{len(SEEDS)} stored, {len(SEEDS)} applied, 0 unreadable:"
    for pref in prefs:
        assert pref.statement in text
    assert text.count("advisory") == 1
    assert notice([]) == "0 stored, 0 applied, 0 unreadable"


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


# ---------------------------------------------------------------------------
# B1 - a stored correction nothing can read is shown, never dropped

# The seven corrections as a prose backfill leaves them: statements in the
# preferences step whose text is the candidate's own sentence.
PROSE = [f"Style correction {n}: {seed[0]}" for n, seed in enumerate(SEEDS, start=1)]


def _prose_rows(log: EvidenceLog) -> list[str]:
    return [
        log.append(
            recorded_at=AT, step="preferences", kind="statement", text=text, source="conversation"
        ).id
        for text in PROSE
    ]


def test_prose_corrections_are_listed_as_unreadable_not_dropped(store: ProfileStore) -> None:
    log = EvidenceLog(store)
    ids = _prose_rows(log)
    assert stored_preferences(log) == ()
    unreadable = unreadable_preferences(log)
    assert [u.row_id for u in unreadable] == ids
    text = notice([], unreadable)
    assert text.splitlines()[0] == "7 stored, 0 applied, 7 unreadable:"
    for row_id, prose in zip(ids, PROSE, strict=True):
        assert row_id in text and prose[:60] in text


def test_the_manifest_carries_the_unreadable_rows_into_every_package(store: ProfileStore) -> None:
    log = EvidenceLog(store)
    ids = _prose_rows(log)
    good = record(log, "No sentiment.", (r"\bpassion",), at=AT)
    manifest = generate(store, _master_with("experience", "ok"), offer_id="o", advert="x")
    assert [u.row_id for u in manifest.voice_unreadable] == ids
    assert [a.row_id for a in manifest.voice_applied] == [good.row_id]
    assert read_manifest(store, "o", manifest.version) == manifest
    head = notice(manifest.voice_applied, manifest.voice_unreadable).splitlines()[0]
    assert head == "8 stored, 1 applied, 7 unreadable:"


def test_only_statements_in_the_preferences_step_can_be_unreadable(store: ProfileStore) -> None:
    log = EvidenceLog(store)
    log.append(
        recorded_at=AT, step="preferences", kind="reaction", text='{"a":1}', source="conversation"
    )
    log.append(recorded_at=AT, step="intake", kind="statement", text="prose", source="conversation")
    assert unreadable_preferences(log) == ()


def test_a_retracted_unreadable_row_is_dismissed(store: ProfileStore) -> None:
    log = EvidenceLog(store)
    first, *_ = _prose_rows(log)
    retract(log, first, at=AT)
    assert first not in {u.row_id for u in unreadable_preferences(log)}
    assert len(unreadable_preferences(log)) == len(PROSE) - 1


def _cli(root: Path, *extra: str) -> int:
    return voice_main(["voice", *extra, "--id", "ada", "--input-dir", str(root)])


def test_the_record_command_stores_a_preference_that_generation_applies(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    seed = ENFORCEABLE[2]
    code = _cli(
        store.root,
        "record",
        "--statement",
        seed[0],
        "--forbid",
        seed[1][0],
        "--at",
        AT,
    )
    assert code == 0
    assert "1 stored, 1 applied, 0 unreadable" in capsys.readouterr().out
    manifest = generate(store, _master_with("experience", seed[2]), offer_id="o", advert="x")
    assert seed[2] not in _documents(store, "o", manifest.version)


def test_the_record_command_refuses_a_bad_pattern_and_writes_nothing(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _cli(store.root, "record", "--statement", "s", "--forbid", "(") == 2
    assert EvidenceLog(store).rows() == []
    assert "voice:" in capsys.readouterr().err


def test_the_notice_command_shows_unreadable_rows(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    ids = _prose_rows(EvidenceLog(store))
    assert _cli(store.root, "notice") == 0
    out = capsys.readouterr().out
    assert "7 stored, 0 applied, 7 unreadable" in out and ids[0] in out


def test_the_record_command_refuses_a_root_inside_a_work_tree(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_inside = Path(__file__).resolve().parent
    assert _cli(repo_inside, "record", "--statement", "s") == 2


# ---------------------------------------------------------------------------
# B2 - invisible characters and typographic quotes do not dodge a rule

CF = [chr(c) for c in range(sys.maxunicode + 1) if unicodedata.category(chr(c)) == "Cf"]

# Characters Unicode itself names as rendering as nothing, found by NAME rather
# than by the rule under test, so the population is independent of `is_invisible`.
_INVISIBLE_NAMES = frozenset(
    {
        "SOFT HYPHEN",
        "COMBINING GRAPHEME JOINER",
        "WORD JOINER",
        "ZERO WIDTH SPACE",
        "ZERO WIDTH NON-JOINER",
        "ZERO WIDTH JOINER",
        "ZERO WIDTH NO-BREAK SPACE",
        "HANGUL FILLER",
        "HANGUL CHOSEONG FILLER",
        "HANGUL JUNGSEONG FILLER",
        "HALFWIDTH HANGUL FILLER",
        "FUNCTION APPLICATION",
        "INVISIBLE TIMES",
        "INVISIBLE SEPARATOR",
        "INVISIBLE PLUS",
    }
)
NAMED_INVISIBLE = [
    chr(c)
    for c in range(sys.maxunicode + 1)
    if unicodedata.name(chr(c), "") in _INVISIBLE_NAMES
    or "VARIATION SELECTOR" in unicodedata.name(chr(c), "")
]

# Looked up by name, so the list does not restate the code's own rule.
SINGLE_MARKS = [
    unicodedata.lookup(name)
    for name in (
        "RIGHT SINGLE QUOTATION MARK",
        "LEFT SINGLE QUOTATION MARK",
        "SINGLE HIGH-REVERSED-9 QUOTATION MARK",
        "MODIFIER LETTER APOSTROPHE",
        "FULLWIDTH APOSTROPHE",
        "PRIME",
        "ARMENIAN APOSTROPHE",
        "ACUTE ACCENT",
        "GRAVE ACCENT",
        "MODIFIER LETTER PRIME",
    )
]
DOUBLE_MARKS = [
    unicodedata.lookup(name)
    for name in (
        "LEFT DOUBLE QUOTATION MARK",
        "RIGHT DOUBLE QUOTATION MARK",
        "DOUBLE LOW-9 QUOTATION MARK",
        "FULLWIDTH QUOTATION MARK",
    )
]


def test_the_invisible_and_quote_populations_are_not_trivial() -> None:
    assert len(CF) > 20 and "\u200b" in CF and "\u00ad" in CF
    assert {"\u034f", "\ufe0f", "\u3164", "\u200b", "\u00ad"} <= set(NAMED_INVISIBLE)
    assert len(SINGLE_MARKS) == 10 and "\u2032" in SINGLE_MARKS and "\u201c" in DOUBLE_MARKS


def test_every_character_unicode_names_as_blank_is_treated_as_invisible() -> None:
    missed = [hex(ord(ch)) for ch in NAMED_INVISIBLE if not is_invisible(ch)]
    assert not missed, missed
    assert all(is_invisible(ch) for ch in CF)
    assert not any(is_invisible(ch) for ch in "aZ 0-'\u2019\u00e9")


def _sentimental(store: ProfileStore) -> list[VoicePreference]:
    seed = ENFORCEABLE[3]
    return [record(EvidenceLog(store), seed[0], seed[1], at=AT)]


def test_a_typographic_single_mark_does_not_dodge_the_sentiment_rule(store: ProfileStore) -> None:
    prefs = _sentimental(store)
    for mark in SINGLE_MARKS:
        assert violations(f"It{mark}s also personal.", prefs), hex(ord(mark))


def test_the_prime_and_double_quote_folds_are_pinned(store: ProfileStore) -> None:
    prefs = _sentimental(store)
    assert violations("It\u2032s also personal.", prefs)  # PRIME has no "apostrophe" in its name
    quoted = [record(EvidenceLog(store), "No scare quotes.", (r'"hi"',), at=AT)]
    for mark in DOUBLE_MARKS:
        assert violations(f"say {mark}hi{mark} now", quoted), hex(ord(mark))
    assert not violations("say hi now", quoted)


def test_the_spec_sentence_with_a_curly_apostrophe_is_withheld_by_generate(
    store: ProfileStore,
) -> None:
    _sentimental(store)
    draft = "It\u2019s also personal: I care about this field."
    manifest = generate(store, _master_with("experience", draft), offer_id="o", advert="x")
    assert draft not in _documents(store, "o", manifest.version)
    assert any(draft in o.text for o in manifest.omissions)


def test_an_invisible_character_never_hides_a_phrase_from_violations(store: ProfileStore) -> None:
    author = [record(EvidenceLog(store), ENFORCEABLE[2][0], ENFORCEABLE[2][1], at=AT)]
    term = [record(EvidenceLog(store), ENFORCEABLE[4][0], ENFORCEABLE[4][1], at=AT)]
    for mark in {*CF, *NAMED_INVISIBLE}:
        assert violations(f"I{mark}automated it", author), hex(ord(mark))
        assert violations(f"I {mark}automated it", author), hex(ord(mark))
        assert violations(f"dra{mark}wspec", term), hex(ord(mark))


# The round-2 reviewer's probes, and lines mixing a between-words invisible with
# an inside-a-word one, which no fixed pair of readings catches.
MIXED = [
    "I\u200bauto\u200dmated a good deal of my team's tasks with AI.",
    "I\u200bautomated a good deal of my team's tasks with AI.",
    "I auto\u034fmated it",
    "I\ufe0f automated it",
    "I\u3164automated it",
]


@pytest.mark.parametrize("draft", MIXED)
def test_a_mixed_invisible_line_is_withheld_by_generate_and_recorded(
    store: ProfileStore, draft: str
) -> None:
    record(EvidenceLog(store), ENFORCEABLE[2][0], ENFORCEABLE[2][1], at=AT)
    manifest = generate(store, _master_with("experience", draft), offer_id="o", advert="x")
    assert draft not in _documents(store, "o", manifest.version)
    (omission,) = manifest.omissions
    assert draft in omission.text
    assert "invisible" in omission.reason


@pytest.mark.parametrize(
    ("seed", "draft"),
    [
        (3, "It is close\u200b to my he\u00adart."),
        (3, "close\u200bto my heart"),
        (4, "draws\ufe0fpec"),
    ],
)
def test_the_reviewers_other_probes_are_withheld(
    store: ProfileStore, seed: int, draft: str
) -> None:
    record(EvidenceLog(store), ENFORCEABLE[seed][0], ENFORCEABLE[seed][1], at=AT)
    manifest = generate(store, _master_with("experience", draft), offer_id="o", advert="x")
    assert draft not in _documents(store, "o", manifest.version)


def test_an_invisible_character_costs_nothing_when_no_preference_can_check_it(
    store: ProfileStore,
) -> None:
    record(EvidenceLog(store), SEEDS[-1][0], (), at=AT)  # advisory only
    draft = "Built a diagram\u200b tool."
    manifest = generate(store, _master_with("experience", draft), offer_id="o", advert="x")
    assert draft in _documents(store, "o", manifest.version)


def test_the_contraction_form_of_a_stored_phrasing_is_caught(store: ProfileStore) -> None:
    seed = ENFORCEABLE[1]
    prefs = [record(EvidenceLog(store), seed[0], seed[1], at=AT)]
    assert violations("without worrying whether they\u2019re perfectly structured", prefs)


# ---------------------------------------------------------------------------
# O2 and O4


@pytest.mark.parametrize(
    ("heading", "section"),
    [
        ("Experience", "experience"),
        ("Summary", "headline"),
        ("Education", "education"),
        ("Skills", "skills"),
    ],
)
def test_a_section_heading_that_breaks_a_preference_refuses(
    store: ProfileStore, heading: str, section: str
) -> None:
    record(EvidenceLog(store), "No such heading.", (rf"\b{heading}\b",), at=AT)
    with pytest.raises(GenerationError):
        generate(store, _master_with(section, "ok"), offer_id="o", advert="ok")
    assert not store.path("cv", "generated", "o").exists()


def test_a_heading_the_cv_does_not_emit_cannot_refuse_it(store: ProfileStore) -> None:
    record(EvidenceLog(store), "No such heading.", (r"\bcertifications\b",), at=AT)
    manifest = generate(store, _master_with("experience", "ok"), offer_id="o", advert="x")
    assert "ok" in _documents(store, "o", manifest.version)


def test_one_candidates_preferences_never_reach_another(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    ada = ProfileStore(root, create_profile(root, "Ada L", handle="ada", language="en").handle)
    bob = ProfileStore(root, create_profile(root, "Bob K", handle="bob", language="en").handle)
    seed = ENFORCEABLE[2]
    record(EvidenceLog(ada), seed[0], seed[1], at=AT)
    EvidenceLog(bob).append(
        recorded_at=AT, step="preferences", kind="statement", text="prose", source="conversation"
    )
    master = _master_with("experience", seed[2])
    for_ada = generate(ada, master, offer_id="o", advert="x")
    for_bob = generate(bob, master, offer_id="o", advert="x")
    assert len(for_ada.voice_applied) == 1 and for_ada.voice_unreadable == ()
    assert seed[2] in _documents(bob, "o", for_bob.version)
    assert for_bob.voice_applied == () and len(for_bob.voice_unreadable) == 1
    assert [p.row_id for p in stored_preferences(EvidenceLog(bob))] == []


# ---------------------------------------------------------------------------
# B4, O6, O7


def test_record_for_a_handle_nobody_identified_is_refused_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    code = voice_main(
        ["voice", "record", "--id", "ghost", "--input-dir", str(empty), "--statement", "No X"]
    )
    assert code == 2
    assert not (empty / "ghost").exists()
    assert "voice:" in capsys.readouterr().err
    assert voice_main(["voice", "notice", "--id", "ghost", "--input-dir", str(empty)]) == 2
    assert not (empty / "ghost").exists()


@pytest.mark.parametrize("kind", ["statement", "constraint", "episode", "outcome"])
def test_an_unreadable_row_of_any_kind_is_listed(store: ProfileStore, kind: Kind) -> None:
    log = EvidenceLog(store)
    row = log.append(
        recorded_at=AT, step="preferences", kind=kind, text="prose", source="conversation"
    )
    assert [u.row_id for u in unreadable_preferences(log)] == [row.id]


def test_the_notice_travels_with_the_manifest(store: ProfileStore) -> None:
    log = EvidenceLog(store)
    _prose_rows(log)
    record(log, "No sentiment.", (r"\bpassion",), at=AT)
    manifest = generate(store, _master_with("experience", "ok"), offer_id="o", advert="x")
    assert manifest.voice_notice == notice(manifest.voice_applied, manifest.voice_unreadable)
    assert manifest.voice_notice.startswith("8 stored, 1 applied, 7 unreadable:")
    assert read_manifest(store, "o", manifest.version).voice_notice == manifest.voice_notice


def test_the_notice_travels_with_the_approval_payload(store: ProfileStore) -> None:
    from integral.approval import PersonalDetails, prepare, read_payload

    log = EvidenceLog(store)
    _prose_rows(log)
    payload = prepare(
        store,
        _master_with("experience", "ok"),
        offer_id="o",
        advert="x",
        recipient="hiring team",
        details=PersonalDetails(full_name="Ada Lovelace", email="ada@example.invalid"),
    )
    assert payload.voice_notice.startswith("7 stored, 0 applied, 7 unreadable:")
    assert read_payload(store, "o", 1).voice_notice == payload.voice_notice
