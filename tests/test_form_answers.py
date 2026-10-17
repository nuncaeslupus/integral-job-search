"""T339 — application-form answers are a step-11 output, drafted from the store and staged.

Every claim here is pinned by reverting the one line that makes it true.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from integral import form_answers
from integral.approval import (
    ApprovalError,
    PersonalDetails,
    payload_digest,
    prepare,
    read_payload,
    stage_send,
    verify_send,
)
from integral.cv_store import CVMaster, Episode, Experience, Skill, write_master
from integral.form_answers import (
    FormAnswer,
    FormAnswerError,
    answer_defects,
    backed_lines,
    measure,
    read_answers,
    shorten,
    write_answers,
)
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog

OFFER = "girona-1"
ADVERT = "We are hiring a data engineer in Girona. You will own a PostgreSQL estate."
WIN = "Cut the nightly billing run from six hours to forty minutes by rewriting reconciliation."
FAILURE = (
    "Shipped a schema change without a backfill and left invoicing wrong for two days "
    "before anyone noticed."
)
DETAILS = PersonalDetails(full_name="Ada Lovelace", email="ada@example.invalid")
NOTICE_TEXT = "My notice period is two months at my current employer."


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


@pytest.fixture
def master(store: ProfileStore) -> CVMaster:
    built = CVMaster(
        experience=(
            Experience(
                title="Data migration lead",
                organisation="Cintra Logistics",
                start="2021",
                end="2025",
                description="Moved the billing system off the mainframe.",
            ),
        ),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(Episode(kind="achievement", text=WIN), Episode(kind="failure", text=FAILURE)),
    )
    write_master(store, built)
    return built


def _row(store: ProfileStore, kind: Any, text: str) -> str:
    return (
        EvidenceLog(store)
        .append(
            recorded_at="2026-10-17T09:00:00Z",
            step="history",
            kind=kind,
            text=text,
            source="conversation",
        )
        .id
    )


@pytest.fixture
def notice(store: ProfileStore) -> str:
    return _row(store, "constraint", NOTICE_TEXT)


def _answer(notice_id: str, text: str = "My notice period is two months.", **kw: Any) -> FormAnswer:
    return FormAnswer(question="Notice period?", text=text, evidence_ids=(notice_id,), **kw)


def _prepare(
    store: ProfileStore,
    master: CVMaster,
    answers: tuple[FormAnswer, ...],
    approved: tuple[int, ...] = (),
) -> int:
    return prepare(
        store,
        master,
        offer_id=OFFER,
        advert=ADVERT,
        recipient="hiring team, Girona",
        details=DETAILS,
        asks=("PostgreSQL",),
        approved_episodes=approved,
        form_answers=answers,
    ).version


def _vdir(store: ProfileStore, version: int) -> Path:
    return store.path("cv", "generated", OFFER, f"v{version}")


def _confirm(store: ProfileStore, version: int) -> str:
    return payload_digest(read_payload(store, OFFER, version))


# --- shortened to a stated character limit -------------------------------------------------


def test_shorten_keeps_whole_leading_sentences_within_the_limit() -> None:
    text = "I start in two months. I can relocate to Girona. I have a permit."
    out = shorten(text, 50)
    assert out == "I start in two months. I can relocate to Girona."
    assert len(out) <= 50
    assert text.startswith(out)
    assert shorten(text, 22) == "I start in two months."
    assert shorten(text, 1000) == text


def test_shorten_stops_at_a_sentence_too_long_and_does_not_skip_it() -> None:
    # M11: `break` -> `continue` kept a later short sentence after dropping a long middle one,
    # so the result was no longer the leading sentences of the text.
    text = "I start soon. I can relocate to Girona with my whole family next spring. I agree."
    out = shorten(text, 30)
    assert out == "I start soon."
    assert text.startswith(out)


def test_shorten_refuses_rather_than_cut_the_first_sentence() -> None:
    with pytest.raises(FormAnswerError, match="shorter one"):
        shorten("I start in two months.", 10)


def test_an_answer_over_its_stated_limit_is_a_defect_and_is_not_recorded(
    store: ProfileStore, master: CVMaster, notice: str
) -> None:
    long_one = _answer(notice, char_limit=10)
    assert any(d.startswith("limit:") for d in answer_defects(long_one, {}, ()))
    with pytest.raises(FormAnswerError, match="limit"):
        _prepare_dir(store, master, notice, (long_one,))
    ok = _answer(notice, char_limit=len("My notice period is two months."))
    assert not [d for d in answer_defects(ok, _live(store), ()) if d.startswith("limit")]


def _live(store: ProfileStore) -> dict[str, Any]:
    return {r.id: r for r in EvidenceLog(store).effective_rows()}


def _prepare_dir(
    store: ProfileStore, master: CVMaster, notice_id: str, answers: tuple[FormAnswer, ...]
) -> None:
    version = _prepare(store, master, ())
    write_answers(store, OFFER, version, answers)


# --- store entries only ---------------------------------------------------------------------


def test_an_answer_citing_nothing_is_refused_and_writes_nothing(
    store: ProfileStore, master: CVMaster
) -> None:
    bare = FormAnswer(question="Why us?", text="I like the product.")
    with pytest.raises(ApprovalError, match="not backed by the store"):
        _prepare(store, master, (bare,))
    assert not list(store.path("cv", "generated", OFFER).glob("v*/payload.json"))


@pytest.mark.parametrize("hole", ["unknown", "retracted", "reaction", "unrelated"])
def test_an_answer_whose_citation_backs_nothing_is_refused(
    store: ProfileStore, master: CVMaster, notice: str, hole: str
) -> None:
    other = _row(store, "statement", "I would expect around sixty thousand euros a year.")
    reaction = _row(store, "reaction", "My notice period worries me about this advert.")
    gone = _row(store, "statement", "My notice period is flexible with this employer.")
    EvidenceLog(store).append(
        recorded_at="2026-10-17T10:00:00Z",
        step="history",
        kind="retraction",
        text="Forget that.",
        source="conversation",
        retracts=gone,
    )
    cited = {"unknown": "ev-999999", "retracted": gone, "reaction": reaction, "unrelated": other}
    bad = FormAnswer(
        question="Notice?", text="My notice period is two months.", evidence_ids=(cited[hole],)
    )
    with pytest.raises(ApprovalError, match="source:"):
        _prepare(store, master, (bad,))


def test_a_denial_or_a_number_the_cited_words_do_not_hold_is_refused(
    store: ProfileStore, master: CVMaster, notice: str
) -> None:
    for text in ("I have never used a notice period.", "My notice period is 3 months."):
        with pytest.raises(ApprovalError):
            _prepare(store, master, (_answer(notice, text),))


def test_two_answers_to_the_same_question_are_refused(
    store: ProfileStore, master: CVMaster, notice: str
) -> None:
    with pytest.raises(ApprovalError, match="answered twice"):
        _prepare(store, master, (_answer(notice), _answer(notice)))


# --- story-bank episodes under per-use approval ---------------------------------------------


def test_a_story_row_may_be_cited_only_under_a_per_use_approval(
    store: ProfileStore, master: CVMaster
) -> None:
    story = _row(store, "episode", WIN)
    why = FormAnswer(question="Why us?", text=WIN, evidence_ids=(story,))
    with pytest.raises(ApprovalError, match="no per-use approval"):
        _prepare(store, master, (why,))
    version = _prepare(store, master, (why,), approved=(0,))
    assert WIN in (_vdir(store, version) / "form_answers.md").read_text(encoding="utf-8")


def test_an_episode_carried_by_an_answer_that_cites_something_else_is_refused(
    store: ProfileStore, master: CVMaster
) -> None:
    said = _row(
        store, "statement", "I enjoy migrations and reconciliation work at logistics firms."
    )
    smuggled = FormAnswer(question="Why us?", text=FAILURE, evidence_ids=(said,))
    # the cited row shares no episode flag, so only the document sweep can see the story
    with pytest.raises(ApprovalError):
        _prepare(store, master, (smuggled,))


# --- staged in send/ with the rest of the payload ------------------------------------------


def test_the_answers_are_a_payload_document_and_are_staged_byte_for_byte(
    store: ProfileStore, master: CVMaster, notice: str
) -> None:
    version = _prepare(store, master, (_answer(notice),))
    payload = read_payload(store, OFFER, version)
    assert "form_answers.md" in payload.documents
    assert any(c.startswith("form_answers.md: Notice period?") for c in payload.claims)
    folder = stage_send(store, master, OFFER, version, confirms=_confirm(store, version))
    assert sorted(p.name for p in folder.iterdir()) == ["cv.md", "form_answers.md", "letter.md"]
    assert (folder / "form_answers.md").read_bytes() == (
        _vdir(store, version) / "form_answers.md"
    ).read_bytes()
    assert not (folder / "form_answers.json").exists()  # the record is not sent
    assert verify_send(store, OFFER, version) == []


def test_changing_the_answers_changes_the_payload_the_candidate_confirms(
    store: ProfileStore, master: CVMaster, notice: str
) -> None:
    first = _prepare(store, master, (_answer(notice),))
    second = _prepare(
        store, master, (_answer(notice, "My notice period is two months at my current employer."),)
    )
    assert _confirm(store, first) != _confirm(store, second)


def test_an_answer_line_edited_after_drafting_stops_staging(
    store: ProfileStore, master: CVMaster, notice: str
) -> None:
    version = _prepare(store, master, (_answer(notice),))
    confirm = _confirm(store, version)
    doc = _vdir(store, version) / "form_answers.md"
    doc.write_text(doc.read_text(encoding="utf-8") + "\nI can start tomorrow.\n", encoding="utf-8")
    with pytest.raises(ApprovalError, match="nothing here is sendable"):
        stage_send(store, master, OFFER, version, confirms=confirm)
    assert not (_vdir(store, version) / "send").exists()


def test_a_cited_row_retracted_after_drafting_stops_staging(
    store: ProfileStore, master: CVMaster, notice: str
) -> None:
    version = _prepare(store, master, (_answer(notice),))
    confirm = _confirm(store, version)
    EvidenceLog(store).append(
        recorded_at="2026-10-17T11:00:00Z",
        step="application",
        kind="retraction",
        text="Forget that.",
        source="conversation",
        retracts=notice,
    )
    assert not backed_lines(store, OFFER, version, ())
    with pytest.raises(ApprovalError, match="nothing here is sendable"):
        stage_send(store, master, OFFER, version, confirms=confirm)


def test_a_missing_record_backs_no_line(store: ProfileStore, master: CVMaster, notice: str) -> None:
    version = _prepare(store, master, (_answer(notice),))
    confirm = _confirm(store, version)
    (_vdir(store, version) / "form_answers.json").unlink()
    with pytest.raises(ApprovalError, match="nothing here is sendable"):
        stage_send(store, master, OFFER, version, confirms=confirm)


def test_a_staged_version_is_not_rewritten(
    store: ProfileStore, master: CVMaster, notice: str
) -> None:
    version = _prepare(store, master, (_answer(notice),))
    stage_send(store, master, OFFER, version, confirms=_confirm(store, version))
    with pytest.raises(FormAnswerError, match="already staged"):
        write_answers(store, OFFER, version, (_answer(notice),))


def test_a_prepare_without_answers_is_unchanged(store: ProfileStore, master: CVMaster) -> None:
    version = _prepare(store, master, ())
    assert "form_answers.md" not in read_payload(store, OFFER, version).documents
    assert not (_vdir(store, version) / "form_answers.json").exists()


# --- the gate ------------------------------------------------------------------------------


def test_the_gate_reads_zero_and_every_probe_is_judged_as_required() -> None:
    measured = measure()
    assert measured["form_answers_without_a_store_source"] == 0
    assert measured["answers_checked"] >= 5
    assert measured["probe_cases"] >= 18
    assert measured["probe_cases_misjudged"] == 0


def test_the_committed_evidence_matches_what_is_measured() -> None:
    committed = json.loads(form_answers.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert committed == measure()


def test_step_11_names_the_form_answers_output() -> None:
    skill = (
        Path(__file__).resolve().parents[1] / ".claude/skills/step-11-application/SKILL.md"
    ).read_text(encoding="utf-8")
    for needle in ("form_answers=", "form_answers.md", "shorten", "per-use"):
        assert needle in skill


# --- the second reader's cases on #822 (report 6232424809), kept as fixtures -------------------


def _refused(store: ProfileStore, answer: FormAnswer) -> list[str]:
    return answer_defects(answer, _live(store), ())


def _ans(text: str, *ids: str, q: str = "Question?") -> FormAnswer:
    return FormAnswer(question=q, text=text, evidence_ids=ids)


def test_f1_an_outcome_row_is_never_a_source(store: ProfileStore, master: CVMaster) -> None:
    # step 10: a rejection reason "is never quoted to any employer"; interview outcomes stay local
    rejection = _row(store, "outcome", "The manager was dismissive, I would not go back.")
    lesson = _row(store, "outcome", "I lost the thread in the interview when asked about pricing.")
    cases = (
        (rejection, "The manager was dismissive, I would not go back."),
        (lesson, "I lost the thread in the interview when asked about pricing."),
    )
    for ev, text in cases:
        assert any("outcome row" in d for d in _refused(store, _ans(text, ev)))
        with pytest.raises(ApprovalError, match="outcome row"):
            _prepare(store, master, (_ans(text, ev),))
    assert not list(store.path("cv", "generated", OFFER).glob("v*/send"))


def test_f2_a_denial_dropped_from_the_cited_row_is_refused(
    store: ProfileStore, master: CVMaster
) -> None:
    row = _row(store, "statement", "I do not hold a work permit for the United Kingdom.")
    flipped = _ans("I hold a work permit for the United Kingdom.", row)
    assert any("is dropped" in d for d in _refused(store, flipped))
    with pytest.raises(ApprovalError, match="dropped"):
        _prepare(store, master, (flipped,))
    # the unrelated denial in another sentence does not stand in for the dropped one
    other = _row(store, "constraint", "I do not need visa sponsorship.")
    both = _ans(
        "I hold a work permit for the United Kingdom. I do not need visa sponsorship.", row, other
    )
    assert any("is dropped" in d for d in _refused(store, both))


@pytest.mark.parametrize(
    ("row", "answer"),
    [
        (
            "I want to work on logistics software at a company this size.",
            "I have a valid work permit for the United States.",
        ),
        (
            "I want to work on logistics software at a company this size.",
            "I am a certified AWS architect and want to work remotely.",
        ),
        (
            "I used Kubernetes at Acme for two years.",
            "I am a certified Kubernetes administrator.",
        ),
        # closed rule: any word the row lacks, however ordinary the words around it
        ("I want to work on logistics software.", "I want to work on logistics software daily."),
    ],
)
def test_f3_a_common_shared_word_does_not_back_an_invented_claim(
    store: ProfileStore, master: CVMaster, row: str, answer: str
) -> None:
    cited = _row(store, "statement", row)
    assert any("come from no cited row" in d for d in _refused(store, _ans(answer, cited)))
    with pytest.raises(ApprovalError, match="come from no cited row"):
        _prepare(store, master, (_ans(answer, cited),))


def test_f3_words_may_be_drawn_from_two_cited_rows(store: ProfileStore) -> None:
    one = _row(store, "statement", "I want to work on logistics software.")
    two = _row(store, "statement", "I used Kubernetes at Acme for two years.")
    assert not _refused(store, _ans("I used Kubernetes on logistics software.", one, two))


def test_f4_a_claim_in_the_question_is_refused(
    store: ProfileStore, master: CVMaster, notice: str
) -> None:
    claims = (
        "I am a certified Kubernetes administrator with a UK work permit",
        "Certified Kubernetes administrator with a UK work permit",
        "Notice period? I hold a UK work permit.",
        "Do you need sponsorship? I do not.",
        "Notice period of 3 months?",
    )
    for q in claims:
        bad = _answer(notice).model_copy(update={"question": q})
        assert any(d.startswith("question:") for d in answer_defects(bad, _live(store), ())), q
        with pytest.raises(ApprovalError, match="question:"):
            _prepare(store, master, (bad,))
    ok = _answer(notice).model_copy(update={"question": "How long is your notice period?"})
    assert not answer_defects(ok, _live(store), ())


def test_f5_a_denial_cited_word_for_word_is_accepted_and_staged(
    store: ProfileStore, master: CVMaster
) -> None:
    row = _row(store, "constraint", "I do not need visa sponsorship.")
    said = FormAnswer(
        question="Do you require sponsorship?",
        text="I do not need visa sponsorship.",
        evidence_ids=(row,),
    )
    assert not answer_defects(said, _live(store), ())
    version = _prepare(store, master, (said,))
    stage_send(store, master, OFFER, version, confirms=_confirm(store, version))
    assert verify_send(store, OFFER, version) == []
    # a paraphrase of the denial is not word for word
    loose = said.model_copy(update={"text": "I don't need visa sponsorship."})
    assert any(d.startswith("denial:") for d in answer_defects(loose, _live(store), ()))


# --- reverts the first round left unpinned (M14, M15, M16) -----------------------------------


def test_m14_a_record_for_another_offer_or_version_is_not_read(
    store: ProfileStore, master: CVMaster, notice: str
) -> None:
    version = _prepare(store, master, (_answer(notice),))
    assert read_answers(store, OFFER, version) is not None
    record = _vdir(store, version) / "form_answers.json"
    for field, value in (("version", version + 1), ("offer_id", "other-offer")):
        data = json.loads(record.read_text(encoding="utf-8"))
        data[field] = value
        record.write_text(json.dumps(data), encoding="utf-8")
        assert read_answers(store, OFFER, version) is None
        assert not backed_lines(store, OFFER, version, ())
        data[field] = {"version": version, "offer_id": OFFER}[field]
        record.write_text(json.dumps(data), encoding="utf-8")
    assert read_answers(store, OFFER, version) is not None


def test_m15_a_heading_line_or_a_multi_line_question_is_a_shape_defect(
    store: ProfileStore, notice: str
) -> None:
    live = _live(store)
    smuggled = _answer(notice, "My notice period is two months.\n# Another question\nmonths.")
    assert any(d.startswith("shape:") for d in answer_defects(smuggled, live, ()))
    broken = _answer(notice).model_copy(update={"question": "Notice\nperiod?"})
    assert any(d.startswith("shape:") for d in answer_defects(broken, live, ()))
    assert not any(d.startswith("shape:") for d in answer_defects(_answer(notice), live, ()))


def test_m16_an_empty_answer_set_is_refused(store: ProfileStore, master: CVMaster) -> None:
    version = _prepare(store, master, ())
    with pytest.raises(FormAnswerError, match="no form answers"):
        write_answers(store, OFFER, version, ())
    assert not (_vdir(store, version) / "form_answers.md").exists()
    assert not (_vdir(store, version) / "form_answers.json").exists()
