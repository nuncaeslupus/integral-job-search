"""T239 — a lesson learned in one candidate's session has a route to the process.

The gate is `candidate_session_corrections_left_untriaged == 0`, measured over
the *corrections in the evidence log*, not over the lessons a session chose to
record: a correction nobody routed has to show up as open, by construction.
The second property is that the task carries the rule and never the candidate.
"""

from __future__ import annotations

import json
import shlex
from datetime import UTC, datetime
from pathlib import Path

import pytest

from integral import lesson_triage
from integral.identity import ProfileStore, create_profile, write_active_handle
from integral.lesson_triage import (
    CORRECTION_KINDS,
    LessonError,
    LessonLedger,
    _main,
    measure,
    render_session,
)
from integral.profile import EvidenceLog

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
FROM = "2026-10-05T00:00:00+00:00"  # TRIAGE_FROM, stated here as a literal
JUST_BEFORE = "2026-10-04T23:59:59+00:00"
BEFORE = "2026-10-04T09:00:00+00:00"
DURING = "2026-10-05T10:00:00+00:00"
STEP = "step-11-application"
SAID = "I never want my cover letter to mention the redundancy at my last employer"
RULE = "A cover letter states dates and never the reason a role ended"
OTHER = "Gap wording says dates and not reasons"


def _say(store: ProfileStore, text: str, *, kind: str = "statement", at: str = BEFORE) -> str:
    return (
        EvidenceLog(store)
        .append(recorded_at=at, step="constraints", kind=kind, text=text, source="conversation")  # type: ignore[arg-type]
        .id
    )


def _correct(store: ProfileStore, text: str = "she amends an answer") -> str:
    return _say(store, text, at=DURING)


def _setup(
    tmp_path: Path, name: str = "Marta Quintana", handle: str | None = None, session: str = "s1"
) -> tuple[LessonLedger, ProfileStore]:
    identity = create_profile(tmp_path, name, handle=handle)
    store = ProfileStore(tmp_path, identity.handle)
    write_active_handle(tmp_path, identity.handle, session_id=session, now=T0)
    _say(store, SAID)
    tasks = tmp_path / "tasks"
    (tasks / "_history").mkdir(parents=True)
    return LessonLedger(store, tasks_dir=tasks), store


def _task(ledger: LessonLedger, task_id: str, rule: str, *, archived: bool = False) -> None:
    folder = ledger.tasks_dir / "_history" if archived else ledger.tasks_dir
    (folder / f"{task_id}.md").write_text(f"Rule: {rule}\n", encoding="utf-8")


# -- B1: the population is the evidence log ----------------------------------


def test_a_correction_nobody_recorded_is_open_and_fails_the_check(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    assert ledger.untriaged() == []  # nothing corrected yet: a real zero
    row = _correct(store)
    left = ledger.untriaged()
    assert [item.ref for item in left] == [row]
    assert "NO LESSON AND NOT DISMISSED" in render_session(ledger)
    base = ["x", "--root", str(tmp_path), "--handle", store.handle]
    assert _main([*base, "check"]) == 1


# Literal, not derived from the constant under test: a kind dropped from the constant
# must drop out of this list's coverage visibly, not silently with it.
KINDS = ("statement", "constraint", "retraction", "candidate_statement")


def test_the_correction_kinds_are_exactly_these() -> None:
    assert frozenset(KINDS) == CORRECTION_KINDS


@pytest.mark.parametrize("kind", KINDS)
def test_every_correction_kind_is_in_the_population(tmp_path: Path, kind: str) -> None:
    ledger, store = _setup(tmp_path)
    target = _say(store, "an earlier answer") if kind == "retraction" else None
    row = (
        EvidenceLog(store)
        .append(
            recorded_at=DURING, step="constraints", kind=kind, text="x y z",  # type: ignore[arg-type]
            source="conversation", retracts=target,
        )
        .id
    )  # fmt: skip
    assert [item.ref for item in ledger.untriaged()] == [row]


def test_rows_outside_the_window_or_kind_are_not_corrections(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    _say(store, "said last week", at=BEFORE)
    _say(store, "history from intake", kind="episode", at=DURING)
    _say(store, "a view on one advert", kind="reaction", at=DURING)
    assert ledger.untriaged() == []


def test_a_lesson_dismissal_or_candidate_specific_decision_each_close_a_row(
    tmp_path: Path,
) -> None:
    ledger, store = _setup(tmp_path)
    a, b, c = _correct(store, "one"), _correct(store, "two"), _correct(store, "three")
    one = ledger.record(RULE, session_id="s1", step=STEP, at=DURING, evidence_id=a)
    assert {item.ref for item in ledger.untriaged()} == {one.id, b, c}  # undecided lesson
    _task(ledger, "t-0123abcd", RULE)
    ledger.decide(one.id, "seeded", at=DURING, task_id="t-0123abcd")
    two = ledger.record(OTHER, session_id="s1", step=STEP, at=DURING, evidence_id=b)
    ledger.decide(two.id, "candidate_specific", at=DURING, reason="turns on her own visa")
    assert [item.ref for item in ledger.untriaged()] == [c]
    ledger.dismiss(c, reason="a plain fact", at=DURING)
    assert ledger.untriaged() == []
    again = LessonLedger(ProfileStore(store.root, store.handle), tasks_dir=ledger.tasks_dir)
    assert again.untriaged() == []
    text = render_session(again)
    assert "seeded as t-0123abcd" in text and "candidate-specific (turns on her own visa)" in text
    assert "not a lesson (a plain fact)" in text


def test_a_lesson_with_no_evidence_row_still_needs_a_decision(tmp_path: Path) -> None:
    ledger, _ = _setup(tmp_path)
    lesson = ledger.record(RULE, session_id="s1", step=STEP, at=DURING)
    assert [item.ref for item in ledger.untriaged()] == [lesson.id]
    ledger.decide(lesson.id, "candidate_specific", at=DURING, reason="her own case")
    assert ledger.untriaged() == []


def test_an_unknown_profile_exits_2_and_a_known_one_with_nothing_open_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger, store = _setup(tmp_path)
    for bad in ("nobody", "../escape", ""):
        assert _main(["x", "--root", str(tmp_path), "--handle", bad, "check"]) == 2
    base = ["x", "--root", str(tmp_path), "--handle", store.handle]
    assert _main([*base, "check"]) == 0
    for bad in ("no such session!!", ""):
        with pytest.raises(LessonError):
            ledger.record(RULE, session_id=bad, step=STEP, at=DURING)
    assert "no such profile" in capsys.readouterr().err


def test_the_population_does_not_move_when_the_session_marker_is_rewritten(
    tmp_path: Path,
) -> None:
    ledger, store = _setup(tmp_path)
    row = _correct(store)
    # the session re-identifies (the guard's own restore line) after the correction
    write_active_handle(
        tmp_path, store.handle, session_id="s1", now=datetime(2026, 10, 5, 11, tzinfo=UTC)
    )
    write_active_handle(
        tmp_path, store.handle, session_id="s2", now=datetime(2026, 10, 6, 9, tzinfo=UTC)
    )
    assert [item.ref for item in ledger.untriaged()] == [row]


def test_an_open_row_carries_over_to_the_next_session(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    row = _correct(store)
    ledger.record(RULE, session_id="s2", step=STEP, at=DURING)  # another session works on
    assert row in {item.ref for item in ledger.untriaged()}
    assert row in render_session(ledger)


def test_triage_from_is_the_only_bound_and_an_unreadable_stamp_is_open(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    _say(store, "one second before", at=JUST_BEFORE)
    on = _say(store, "exactly on the date", at=FROM)
    garbled = _say(store, "stamp nobody can read", at="sometime last week")
    assert {item.ref for item in ledger.untriaged()} == {on, garbled}


# -- B4: exactly one outcome per evidence row ------------------------------------


def test_a_second_lesson_on_one_row_is_refused_and_cannot_stand_in_for_the_first(
    tmp_path: Path,
) -> None:
    ledger, store = _setup(tmp_path)
    row = _correct(store)
    first = ledger.record(RULE, session_id="s1", step=STEP, at=DURING, evidence_id=row)
    with pytest.raises(LessonError, match="already has a lesson"):
        ledger.record(OTHER, session_id="s1", step=STEP, at=DURING, evidence_id=row)
    # the same state written by hand is refused by the reader, not tolerated
    second = json.loads(ledger.path.read_text(encoding="utf-8").splitlines()[0])
    second.update(id="ls-0002", rule=OTHER)
    with ledger.path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(second) + "\n")
    with pytest.raises(LessonError, match="more than one outcome"):
        ledger.untriaged()
    assert first.id


def test_every_lesson_is_owed_a_decision_whatever_its_rows_coverage(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    row = _correct(store)
    lesson = ledger.record(RULE, session_id="s1", step=STEP, at=DURING, evidence_id=row)
    other = ledger.record(OTHER, session_id="s1", step=STEP, at=DURING)
    ledger.decide(other.id, "candidate_specific", at=DURING, reason="her own case here")
    assert [item.ref for item in ledger.untriaged()] == [lesson.id]


def test_a_dismissal_reason_is_not_a_full_stop(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    row = _correct(store)
    for bad in (".", "ok", "a b"):
        with pytest.raises(LessonError, match="at least 3 words"):
            ledger.dismiss(row, reason=bad, at=DURING)
    ledger.dismiss(row, reason="a plain fact", at=DURING)
    lesson = ledger.record(RULE, session_id="s1", step=STEP, at=DURING)
    with pytest.raises(LessonError, match="at least 3 words"):
        ledger.decide(lesson.id, "candidate_specific", at=DURING, reason="no")


def test_short_name_tokens_are_guarded(tmp_path: Path) -> None:
    ledger, _ = _setup(tmp_path, name="Ana Li Gil")
    for rule in ("Ana wants gaps worded gently", "Li wants gaps worded gently",
                 "Gil wants gaps worded gently"):  # fmt: skip
        with pytest.raises(LessonError, match="name or handle"):
            ledger.record(rule, session_id="s1", step=STEP, at=DURING)


# -- the decision rules --------------------------------------------------------


def test_a_decision_is_not_overwritable(tmp_path: Path) -> None:
    ledger, _ = _setup(tmp_path)
    lesson = ledger.record(RULE, session_id="s1", step=STEP, at=DURING)
    ledger.decide(lesson.id, "candidate_specific", at=DURING, reason="her own case")
    _task(ledger, "t-0123abcd", RULE)
    with pytest.raises(LessonError, match="already has a decision"):
        ledger.decide(lesson.id, "seeded", at=DURING, task_id="t-0123abcd")
    with pytest.raises(LessonError, match="not re-opened"):
        ledger.seed_spec(lesson.id)


def test_a_decision_needs_its_evidence(tmp_path: Path) -> None:
    ledger, _ = _setup(tmp_path)
    lesson = ledger.record(RULE, session_id="s1", step=STEP, at=DURING)
    for bad in (None, "", "TASK-1", "t-xyz"):
        with pytest.raises(LessonError):
            ledger.decide(lesson.id, "seeded", at=DURING, task_id=bad)
    for reason in (None, "", "   "):
        with pytest.raises(LessonError):
            ledger.decide(lesson.id, "candidate_specific", at=DURING, reason=reason)
    with pytest.raises(LessonError, match="no lesson"):
        ledger.decide("ls-9999", "candidate_specific", at=DURING, reason="x")
    assert len(ledger.untriaged()) == 1


def test_seeded_must_name_a_real_task_that_carries_the_rule(tmp_path: Path) -> None:
    ledger, _ = _setup(tmp_path)
    lesson = ledger.record(RULE, session_id="s1", step=STEP, at=DURING)
    with pytest.raises(LessonError, match="not a task"):
        ledger.decide(lesson.id, "seeded", at=DURING, task_id="t-00000000")  # shaped, absent
    _task(ledger, "t-00000001", "some unrelated rule")
    with pytest.raises(LessonError, match="not a task"):
        ledger.decide(lesson.id, "seeded", at=DURING, task_id="t-00000001")  # exists, wrong rule
    _task(ledger, "t-00000002", RULE, archived=True)  # an archived task counts
    assert ledger.decide(lesson.id, "seeded", at=DURING, task_id="t-00000002").task_id


def test_the_reader_refuses_a_ledger_that_contradicts_itself(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    ev = _correct(store)
    first = ledger.record(RULE, session_id="s1", step=STEP, at=DURING, evidence_id=ev)
    ledger.decide(first.id, "candidate_specific", at=DURING, reason="her own case")
    original = ledger.path.read_text(encoding="utf-8").splitlines()
    lesson_row, decision_row = original[0], original[1]
    duplicate = json.loads(decision_row)
    duplicate.update(decision="seeded", task_id="t-0123abcd")
    cases = {
        "same lesson id twice": [lesson_row, lesson_row],
        "more than one decision": [lesson_row, decision_row, json.dumps(duplicate)],
        "dismissed and made into a lesson": [
            lesson_row,
            json.dumps({"row": "dismissal", "evidence_id": ev, "reason": "x", "at": DURING}),
        ],
        "dismisses the same evidence row twice": [
            json.dumps({"row": "dismissal", "evidence_id": ev, "reason": "x", "at": DURING})
        ]
        * 2,
    }
    for label, lines in cases.items():
        ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(LessonError):
            ledger.lessons()
        assert label


def test_a_malformed_ledger_is_an_error_not_an_empty_list(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    ledger.record(RULE, session_id="s1", step=STEP, at=DURING)
    store.path("session", "lessons.jsonl").write_text('{"row": "lesson"}\n', encoding="utf-8")
    with pytest.raises(LessonError, match="not a ledger row"):
        ledger.untriaged()


def test_a_dismissal_and_a_lesson_are_one_route_each(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    a, b = _correct(store, "one"), _correct(store, "two")
    ledger.dismiss(a, reason="a plain fact", at=DURING)
    with pytest.raises(LessonError, match="dismissed"):
        ledger.record(RULE, session_id="s1", step=STEP, at=DURING, evidence_id=a)
    ledger.record(RULE, session_id="s1", step=STEP, at=DURING, evidence_id=b)
    with pytest.raises(LessonError, match="already has a lesson"):
        ledger.dismiss(b, reason="x", at=DURING)
    with pytest.raises(LessonError, match="already dismissed"):
        ledger.dismiss(a, reason="x", at=DURING)
    with pytest.raises(LessonError, match="says why"):
        ledger.dismiss(_correct(store, "three"), reason="  ", at=DURING)
    with pytest.raises(LessonError, match="no evidence row"):
        ledger.dismiss("ev-999999", reason="x", at=DURING)
    with pytest.raises(LessonError, match="no evidence row"):
        ledger.record(OTHER, session_id="s1", step=STEP, at=DURING, evidence_id="ev-999999")


# -- B2: the seeded task carries the rule and the step, nothing else -------------


def test_the_seeded_task_carries_the_rule_and_the_step_and_nothing_else(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    lesson = ledger.record(RULE, session_id="s1", step=STEP, at=DURING)
    spec = ledger.seed_spec(lesson.id)
    blob = " ".join(spec.command())
    assert RULE in spec.body and STEP in spec.body
    for private in (SAID, store.handle, "Marta", "redundancy", "s1"):
        assert private not in blob


def test_the_printed_seed_command_survives_a_shell(tmp_path: Path) -> None:
    ledger, _ = _setup(tmp_path)
    hostile = "Don't state $(echo PWNED) or `id` in a letter, ever"
    lesson = ledger.record(hostile, session_id="s1", step=STEP, at=DURING)
    spec = ledger.seed_spec(lesson.id)
    assert shlex.split(spec.shell_line()) == spec.command()  # one argument per argument
    assert "\n" in shlex.split(spec.shell_line())[-1]  # newlines are newlines, not "\n"
    assert "'" in spec.shell_line()  # quoted, so the substitution never runs


def test_step_must_be_a_process_step_id(tmp_path: Path) -> None:
    ledger, _ = _setup(tmp_path)
    for bad in ("Marta Quintana depression", "constraint", "step-99-x", ""):
        with pytest.raises(LessonError, match="step id"):
            ledger.record(RULE, session_id="s1", step=bad, at=DURING)
    for good in ("application", "step-02-constraints", "interview-log"):
        ledger.record(OTHER, session_id="s1", step=good, at=DURING)


EVIDENCE_FACT = "I was laid off from Telefónica in Málaga in 2023 because of my depression"


def _jose(tmp_path: Path) -> LessonLedger:
    ledger, store = _setup(tmp_path, name="José Pérez", handle="mq-2026")
    _say(store, EVIDENCE_FACT)
    return ledger


@pytest.mark.parametrize(
    "rule",
    [
        "Pérez, José wants no gap reasons stated",  # the name, any order
        "José wants no gap reasons stated",  # the first name alone
        "Perez wants no gap reasons stated",  # no accents
        "JOSE wants no gap reasons stated",  # case and accents
        "Ｊｏｓé Ｐéｒｅｚ wants no gap reasons",  # fullwidth
        "mq2026 wants gaps worded gently",  # the handle, separators removed
        "mq-2026 wants gaps worded gently",  # the handle as given
        "Never name Telefónica, Málaga or depression in a letter",  # short personal facts
        "laid off from Telefonica never in a letter",  # accents stripped
        "Do not say I was made redundant by my employer in Malaga",  # their city
        "Never mention 2023 in a letter",  # a number from their own text
    ],
)
def test_the_guard_refuses_what_is_the_candidates_not_the_processes(
    tmp_path: Path, rule: str
) -> None:
    ledger = _jose(tmp_path)
    with pytest.raises(LessonError, match="restate it"):
        ledger.record(rule, session_id="s1", step=STEP, at=DURING)
    assert ledger.lessons() == []


def test_the_guard_reads_everything_the_candidate_wrote(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    for parts, word in (
        (("cv", "source", "cv.txt"), "Zaragoza"),
        (("interviews", "off-1", "iv-001", "notes.md"), "Valencia"),
        (("applications", "off-1", "letter.txt"), "Sevilla"),
    ):
        target = store.path(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"Lived in {word} for years", encoding="utf-8")
        with pytest.raises(LessonError, match="restate it"):
            ledger.record(
                f"Never mention {word} in a letter", session_id="s1", step=STEP, at=DURING
            )


def test_a_retracted_row_is_still_the_candidates_and_still_guarded(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    row_id = _say(store, "my landlord evicted me from the flat in Albacete")
    EvidenceLog(store).append(
        recorded_at=BEFORE, step="x", kind="retraction", text="forget that",
        source="conversation", retracts=row_id,
    )  # fmt: skip
    with pytest.raises(LessonError, match="restate it"):
        ledger.record("Never mention Albacete in a letter", session_id="s1", step=STEP, at=DURING)


def test_the_guard_is_rechecked_when_the_task_is_made(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    lesson = ledger.record(RULE, session_id="s1", step=STEP, at=DURING)
    # The candidate later writes the rule's own words; the lesson can no longer leave.
    _say(store, "honestly a cover letter states dates and never the reason a role ended for me")
    with pytest.raises(LessonError, match="cannot leave"):
        ledger.seed_spec(lesson.id)


# The shared-run bound, pinned in both directions with literal inputs. The words are
# all the process's own, so the vocabulary rule cannot be what answers; the test
# asserts that rather than assuming it, and states 4 and 3 as numbers, not as the
# constant under test.
RUN_EVIDENCE = "cover letter states dates never reasons gap period"


def test_a_shared_run_of_exactly_four_words_is_refused_and_three_is_not(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    _say(store, RUN_EVIDENCE)
    vocab = ledger.vocabulary()
    four = "cover letter states dates ranking shortlist"  # shares exactly 4 in a row
    three = "cover letter states shortlist never reasons gap"  # longest shared run is 3
    for sentence in (RUN_EVIDENCE, four, three):
        assert all(word in vocab for word in lesson_triage.tokens(sentence)), sentence
    with pytest.raises(LessonError, match="run of 4 words"):
        ledger.record(four, session_id="s1", step=STEP, at=DURING)
    assert ledger.record(three, session_id="s1", step=STEP, at=DURING).id


def test_a_short_rule_is_compared_whole(tmp_path: Path) -> None:
    ledger, store = _setup(tmp_path)
    _say(store, RUN_EVIDENCE)
    with pytest.raises(LessonError, match="run of 3 words"):
        ledger.record("cover letter states", session_id="s1", step=STEP, at=DURING)
    with pytest.raises(LessonError, match="at least"):
        ledger.record("no dates", session_id="s1", step=STEP, at=DURING)


def test_neutral_rules_in_the_processes_own_words_are_accepted(tmp_path: Path) -> None:
    ledger = _jose(tmp_path)
    for rule in (
        "A cover letter states dates and never the reason a role ended",
        "Offer the shortlist before asking for feedback",
        "A pay floor is a constraint and not a preference",
        "Do not repeat a question the candidate has declined",
    ):
        assert ledger.record(rule, session_id="s1", step=STEP, at=DURING).id


# -- the gate ------------------------------------------------------------------


def test_the_gate_metric_is_measured_over_corrections_and_can_see_them() -> None:
    measured = measure()
    assert measured["candidate_session_corrections_left_untriaged"] == 0
    # one of each kind plus one left over from an earlier session
    assert measured["corrections_in_probe"] == 5
    # the sensitivity witness: before routing, every correction read as open
    assert measured["corrections_open_before_triage"] == 5
    assert measured["second_lesson_on_a_row_refused"] is True
    assert measured["failures"] == []


def test_the_gate_command_exits_zero_and_a_blind_counter_would_not() -> None:
    assert _main(["x", "--check"]) == 0


def test_the_cli_routes_a_correction_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger, store = _setup(tmp_path)
    ev = _correct(store)
    base = ["x", "--root", str(tmp_path), "--handle", store.handle]
    assert _main([*base, "check"]) == 1
    assert _main([*base, "dismiss", ev, "--reason", "a plain fact"]) == 0
    assert _main([*base, "check"]) == 0
    ev2 = _correct(store, "again")
    assert _main([*base, "record", "--session", "s1", "--step", STEP, "--rule", RULE,
                  "--evidence-id", ev2]) == 0  # fmt: skip
    assert _main([*base, "seed", "ls-0001"]) == 0
    assert "create_task.py" in capsys.readouterr().out
    assert _main([*base, "record", "--session", "s1", "--step", "nope", "--rule", RULE]) == 2
    _task(ledger, "t-0123abcd", RULE)
    assert _main([*base, "decide", "ls-0001", "seeded", "--task", "t-0123abcd"]) == 2  # tasks_dir
