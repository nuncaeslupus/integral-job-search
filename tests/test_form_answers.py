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
    second = _prepare(store, master, (_answer(notice, "My notice period is two months at most."),))
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
    assert measured["probe_cases"] >= 9
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
