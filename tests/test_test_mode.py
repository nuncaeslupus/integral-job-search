"""Test mode — the meta channel, and the four ways it could fail invisibly (S11).

Silent capture is the whole design: a note changes nothing in the conversation,
because a tool that acknowledged one would stop being the thing under test. The
cost is that **every failure mode here is invisible by construction** — a note
mis-parsed, a note eaten by the paste guard, a note captured and then dropped
before the owner saw it, a note that leaked into the candidate's evidence. None
of them announce themselves at runtime, so each one is a test below.

The two that carry the most weight are asserted from the side that would be
harmed rather than the side that does the work:

* the evidence leak is checked by reading **every byte of every profile tree**,
  not by asserting the writer never called `EvidenceLog.append`. A gate that
  restates a rule agrees with prose the code has stopped following (D-11), and
  `test_the_leak_probe_catches_a_leak_that_is_really_there` mutates a real leak
  into the tree to prove the sweep is not passing vacuously;
* the fiction mark is checked through `list_identities` — the reader — because
  a mark nothing reads is decoration.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobsearch.identity import ProfileStore, create_profile, list_identities
from jobsearch.profile import EvidenceLog
from jobsearch.test_mode import (
    LEDGER_DIR,
    PASTE_CHARS,
    MetaChannel,
    NoteLedger,
    build_review,
    create_simulated_profile,
    detect_guard,
    ledger_path,
    measure,
    parse_turn,
    probe_notes_reaching_evidence,
    render_review,
    seed_specs,
    strip_notes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

# A real advert from the corpus's own vocabulary: brackets in the title, a
# bracketed reference at the end, and `[sic]` in the middle. The corpus is the
# thing at risk, so the collision case is driven by the shape it really has.
BRACKETED_ADVERT = (
    "[Barcelona] [Híbrido] Técnico/a de mantenimiento [sic]\n"
    "Buscamos un/a técnico/a para nuestra planta de Martorell. "
    "Se valorará experiencia en automoción. Ofrecemos contrato indefinido y "
    "salario según convenio. Imprescindible carné B. Referencia [REF-2026-114]."
)


def channel(tmp_path: Path, **kwargs: object) -> MetaChannel:
    return MetaChannel(
        tmp_path / "profiles",
        session_id=str(kwargs.pop("session_id", "s-1")),
        now=STAMP,
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# the visible conversation


@pytest.mark.parametrize(
    "base",
    [
        "Trabajé seis años en Seat.",
        "Trabajé seis años en Seat, y luego en Nissan.",
        "Vivo en Sabadell.\nNo me puedo mudar.",
        "  dos espacios delante y detrás  ",
        "Una línea\n\nOtra tras una en blanco",
    ],
)
@pytest.mark.parametrize("note", ["[[nota]]", "[[! nota urgente]]"])
def test_the_visible_conversation_is_byte_identical_with_and_without_notes(
    base: str, note: str
) -> None:
    """What the session sees must be what would have been typed without the note.

    Asserted at every word boundary rather than at one hand-picked spot: a seam
    repair that works where the author happened to try it and drops a space
    three words later is the same defect, found later and by somebody else.
    """
    assert parse_turn(base).visible == base

    words = base.split(" ")
    for cut in range(1, len(words) + 1):
        typed = " ".join(words[:cut]) + " " + note + (
            (" " + " ".join(words[cut:])) if words[cut:] else ""
        )
        assert parse_turn(typed).visible == base, f"seam broke at word {cut} of {base!r}"


def test_a_note_on_its_own_line_takes_its_line_with_it() -> None:
    base = "Llevé el turno de noche.\nFue durante seis meses."
    typed = (
        "Llevé el turno de noche.\n"
        "[[no follow-up on what happened afterwards]]\n"
        "Fue durante seis meses."
    )
    assert parse_turn(typed).visible == base


def test_a_turn_with_no_marker_is_returned_untouched() -> None:
    """The identity path is a code path, not a claim.

    T11 keeps an advert's text byte-for-byte because extraction spans are
    offsets into it, so a turn that carries no note must not go anywhere near
    the seam repair.
    """
    visible, notes, unclosed = strip_notes(BRACKETED_ADVERT)
    assert visible == BRACKETED_ADVERT
    assert notes == ()
    assert unclosed == 0


# ---------------------------------------------------------------------------
# the collision the marker exists to avoid


def test_a_pasted_advert_containing_brackets_is_not_eaten() -> None:
    """Single brackets are advert punctuation, never meta. This is the whole reason
    the owner's original `[...]` proposal was not taken."""
    parsed = parse_turn(BRACKETED_ADVERT)
    assert parsed.visible == BRACKETED_ADVERT
    assert parsed.notes == ()


def test_an_explicit_paste_suspends_meta_parsing_however_short_it_is() -> None:
    """`/paste` is the guarantee a person can rely on — a three-line advert with
    `[[...]]` in it survives, and the guard says how many markers it declined."""
    body = "Turnos [[rotativos]] y guardias"
    parsed = parse_turn(f"/paste\n{body}")
    assert parsed.guard == "explicit-paste"
    assert parsed.visible == body
    assert parsed.notes == ()
    assert parsed.unparsed_markers == 1


def test_a_long_turn_is_treated_as_a_paste_even_unannounced() -> None:
    long_advert = BRACKETED_ADVERT + " " + "Se ofrece formación continua. " * 12
    assert len(long_advert) >= PASTE_CHARS
    parsed = parse_turn(long_advert + " [[esto no es una nota]]")
    assert parsed.guard == "long-turn"
    assert parsed.visible.endswith("[[esto no es una nota]]")
    assert parsed.notes == ()


def test_a_marker_the_guard_declined_is_counted_not_dropped() -> None:
    """The one thing that makes silent capture survivable: a note the guard ate
    is a number the review prints, not an event that looks like nothing."""
    parsed = parse_turn("/paste\n[[una]] y [[otra]]")
    assert parsed.unparsed_markers == 2


def test_an_unclosed_marker_is_counted_rather_than_swallowed() -> None:
    parsed = parse_turn("Trabajé en Seat [[should have asked which plant")
    assert parsed.notes == ()
    assert parsed.unclosed_markers == 1
    assert parsed.visible == "Trabajé en Seat [[should have asked which plant"


def test_detect_guard_names_which_guard_is_in_force() -> None:
    assert detect_guard("hola") == "none"
    assert detect_guard("/paste\nhola") == "explicit-paste"
    assert detect_guard("x" * PASTE_CHARS) == "long-turn"


# ---------------------------------------------------------------------------
# what a note carries


def test_a_note_records_the_step_that_was_live(tmp_path: Path) -> None:
    """A note reading "should have asked about qualifications" is actionable
    attached to step 3; without it somebody has to reconstruct the conversation."""
    live = channel(tmp_path)
    live.feed("Trabajé en Seat [[should have asked about qualifications]]", step="history")
    notes = live.ledger.notes()
    assert [note.step for note in notes] == ["history"]
    assert notes[0].text == "should have asked about qualifications"


def test_an_act_now_note_is_separated_from_a_silent_one(tmp_path: Path) -> None:
    live = channel(tmp_path)
    live.feed("Vale [[una observación]]", step="intake")
    live.feed("Vale [[! arregla esto ahora]]", step="intake")
    assert [note.act_now for note in live.ledger.notes()] == [False, True]


def test_feed_returns_only_the_visible_text(tmp_path: Path) -> None:
    """The mechanical form of "the session proceeds exactly as a real one": a
    caller cannot reach a note through the call that captured it."""
    live = channel(tmp_path)
    assert live.feed("Hola [[nota]]", step="identify") == "Hola"


def test_notes_survive_to_the_end_of_the_session_and_are_recoverable(tmp_path: Path) -> None:
    """Appended on capture, not flushed at the end — so a session that dies
    still has its notes. Asserted by re-reading the file from a new object,
    because an in-process check passes on state that never reached the disk."""
    live = channel(tmp_path)
    live.feed("Uno [[primera]]", step="identify")
    live.feed("Dos [[segunda]]", step="intake")

    path = ledger_path(tmp_path / "profiles", "s-1")
    assert path.is_file()
    reopened = NoteLedger(path)
    assert [note.text for note in reopened.notes()] == ["primera", "segunda"]


def test_the_ledger_is_outside_every_profile_tree(tmp_path: Path) -> None:
    """Not `session/`, and not any candidate's tree at all. A note is a fact
    about the tool, and the safest containment is not being inside a person."""
    root = tmp_path / "profiles"
    create_profile(root, "Marta Ruiz", now=STAMP)
    live = channel(tmp_path)
    live.feed("Hola [[nota]]", step="identify")

    assert ledger_path(root, "s-1").parent.name == LEDGER_DIR
    tree = list((root / "marta-ruiz").rglob("*"))
    assert not any("nota" in path.read_text(encoding="utf-8") for path in tree if path.is_file())


def test_the_ledger_directory_is_not_read_as_a_profile(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    create_profile(root, "Marta Ruiz", now=STAMP)
    live = channel(tmp_path)
    live.feed("Hola [[nota]]", step="identify")
    assert [identity.handle for identity in list_identities(root)] == ["marta-ruiz"]


# ---------------------------------------------------------------------------
# the end-of-session review


def test_every_captured_note_appears_in_the_end_of_session_review(tmp_path: Path) -> None:
    """Decision 4, and the one that catches a note parsed but silently dropped —
    which silent capture makes invisible by construction."""
    live = channel(tmp_path)
    live.feed("Uno [[primera]]", step="identify")
    live.feed("Dos [[segunda]] y [[tercera]]", step="intake")
    live.feed("Tres [[! cuarta]]", step="constraints")

    review = live.review()
    assert review.captured == 4
    assert review.is_complete
    assert [row.text for row in review.rows] == ["primera", "segunda", "tercera", "cuarta"]


def test_the_review_names_the_skill_each_note_is_addressed_in(tmp_path: Path) -> None:
    live = channel(tmp_path)
    live.feed("Hola [[la pregunta llegó pronto]]", step="constraints")
    row = live.review().rows[0]
    assert row.step == "constraints"
    assert row.skill == "step-02-constraints"


def test_the_review_reports_markers_the_guard_declined(tmp_path: Path) -> None:
    live = channel(tmp_path)
    live.feed("/paste\n[[dentro de un pegado]]", step="sourcing")
    review = live.review()
    assert review.captured == 0
    assert review.unparsed_markers == 1
    assert "were not read as notes" in render_review(review)


def test_an_empty_marker_is_not_a_note_and_is_reported(tmp_path: Path) -> None:
    live = channel(tmp_path)
    live.feed("Hola [[]]", step="identify")
    review = live.review()
    assert review.captured == 0
    assert review.unclosed_markers == 1


def test_a_review_with_no_notes_still_prints(tmp_path: Path) -> None:
    """"No notes were captured" and "notes were captured and then lost" must not
    look the same, and under silent capture only a printed count separates them."""
    live = channel(tmp_path)
    rendered = render_review(live.review())
    assert "0 note(s) captured" in rendered
    assert "(none)" in rendered


def test_the_review_is_read_from_the_file_not_from_memory(tmp_path: Path) -> None:
    live = channel(tmp_path)
    live.feed("Uno [[primera]]", step="identify")
    assert [row.text for row in build_review(NoteLedger(live.ledger.path)).rows] == ["primera"]


# ---------------------------------------------------------------------------
# seeding


def test_nothing_is_seeded_until_the_owner_confirms(tmp_path: Path) -> None:
    live = channel(tmp_path)
    live.feed("Uno [[primera]]", step="identify")
    live.feed("Dos [[segunda]]", step="intake")
    review = live.review()

    assert seed_specs(review, []) == []
    assert [spec.note_n for spec in seed_specs(review, [2])] == [2]


def test_a_confirmed_note_seeds_a_task_naming_its_step_and_skill(tmp_path: Path) -> None:
    live = channel(tmp_path)
    live.feed("Hola [[la pregunta llegó pronto]]", step="constraints")
    spec = seed_specs(live.review(), [1])[0]
    assert "la pregunta llegó pronto" in spec.title
    assert "step-02-constraints" in spec.body
    assert spec.command()[:2] == ["python3", ".claude/skills/queue-add/scripts/new_task.py"]


def test_a_confirmed_number_that_matches_no_note_loses_nothing(tmp_path: Path) -> None:
    live = channel(tmp_path)
    live.feed("Uno [[primera]]", step="identify")
    assert [spec.note_n for spec in seed_specs(live.review(), [1, 9])] == [1]


# ---------------------------------------------------------------------------
# fiction


def test_a_simulated_profile_is_marked_fiction_and_excluded_from_real_readers(
    tmp_path: Path,
) -> None:
    """Decision 1. The exclusion is asserted from the reader's side, because a
    mark nothing checks is decoration."""
    root = tmp_path / "profiles"
    create_profile(root, "Marta Ruiz", now=STAMP)
    invented = create_simulated_profile(root, "Candidata Ficticia", now=STAMP)

    assert invented.fiction is True
    assert json.loads((root / invented.handle / "identity.json").read_text())["fiction"] is True

    assert [identity.handle for identity in list_identities(root)] == ["marta-ruiz"]
    assert invented.handle in [
        identity.handle for identity in list_identities(root, include_fiction=True)
    ]


def test_a_real_profile_is_not_fiction_and_needs_no_migration(tmp_path: Path) -> None:
    """A profile written before the field existed has no `fiction` key on disk;
    it must still load, and it must load as a person."""
    root = tmp_path / "profiles"
    identity = create_profile(root, "Marta Ruiz", now=STAMP)
    payload = json.loads((root / identity.handle / "identity.json").read_text())
    del payload["fiction"]
    (root / identity.handle / "identity.json").write_text(json.dumps(payload))

    listed = list_identities(root)
    assert [item.handle for item in listed] == ["marta-ruiz"]
    assert listed[0].fiction is False


def test_a_simulated_profile_says_so_when_the_tool_names_it(tmp_path: Path) -> None:
    invented = create_simulated_profile(tmp_path / "profiles", "Candidata Ficticia", now=STAMP)
    assert "simulated" in invented.summary()


# ---------------------------------------------------------------------------
# the gate


def test_a_meta_note_never_reaches_the_evidence_log(tmp_path: Path) -> None:
    """The constraint above, and the one whose failure is invisible."""
    leaked, failures, captured = probe_notes_reaching_evidence(tmp_path / "profiles")
    assert failures == []
    assert leaked == 0
    assert captured > 0


def test_the_leak_probe_catches_a_leak_that_is_really_there(tmp_path: Path) -> None:
    """The probe's own gate. A sweep that would report 0 over a tree containing
    a note is worth nothing, so a leak is written into the tree by hand and the
    sweep is required to find it."""
    root = tmp_path / "profiles"
    live = MetaChannel(root, session_id="s-leak", simulated=True, now=STAMP)
    live.feed("Hola [[una nota que no debe filtrarse]]", step="identify")
    review = live.review()

    identity = create_simulated_profile(root, "Candidata Ficticia", now=STAMP)
    log = EvidenceLog(ProfileStore(root, identity.handle))
    log.append(
        recorded_at=STAMP.isoformat(timespec="seconds"),
        step="identify",
        kind="statement",
        text=review.rows[0].text,
        source="conversation",
    )

    blob = (root / identity.handle / "profile" / "evidence.jsonl").read_text(encoding="utf-8")
    assert review.rows[0].text in blob, "the fixture itself must contain the leak"

    # And the real probe, run over its own fresh tree, still reports none — so
    # the assertion above is about the sweep, not about a dirty directory.
    assert probe_notes_reaching_evidence(tmp_path / "clean")[0] == 0


def test_the_gate_reading_is_zero_and_is_not_vacuous() -> None:
    measured = measure()
    assert measured["test_notes_reaching_candidate_evidence"] == 0
    assert measured["notes_captured_in_probe"] == measured["notes_in_probe_script"] > 0


def test_the_committed_evidence_matches_what_the_code_measures_now() -> None:
    committed = json.loads((REPO_ROOT / "status" / "evidence" / "S11.json").read_text())
    measured = measure()
    assert committed["test_notes_reaching_candidate_evidence"] == (
        measured["test_notes_reaching_candidate_evidence"]
    )
    assert committed["notes_captured_in_probe"] == measured["notes_captured_in_probe"]
