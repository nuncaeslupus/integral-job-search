"""T286: a retraction reaches advice and drafts, not only the send path (spec 4.1)."""

from __future__ import annotations

from pathlib import Path

from integral.approval import PersonalDetails, measure_prepared, prepare
from integral.ats import MISSING_GAP, MISSING_HAVE_IT, classify_keyword, keyword_coverage
from integral.cv_store import ConversationTurn, CVMaster, Episode, Experience, Skill, write_master
from integral.generate import generate, read_manifest
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog

_AT = "2026-08-24T09:00:00Z"
_DETAILS = PersonalDetails(
    full_name="Ada Lovelace",
    email="ada@example.invalid",
    phone="+34 600 111 222",
    postal_address="3 Carrer Nou, 17001 Girona",
)


def _setup(tmp_path: Path) -> tuple[ProfileStore, EvidenceLog]:
    identity = create_profile(tmp_path, "Candidate", handle="candidate")
    store = ProfileStore(tmp_path, identity.handle)
    return store, EvidenceLog(store)


def _say(log: EvidenceLog, text: str, retracts: str | None = None) -> str:
    return log.append(
        recorded_at=_AT,
        step="history" if retracts is None else "any",
        kind="statement" if retracts is None else "retraction",
        text=text,
        source="conversation",
        retracts=retracts,
    ).id


def _skill_master(live: str, wrong: str) -> CVMaster:
    return CVMaster(
        skills=(
            Skill(name="Python", provenance=(ConversationTurn(evidence_id=live),)),
            Skill(name="Salesforce", provenance=(ConversationTurn(evidence_id=wrong),)),
        ),
        experience=(
            Experience(
                title="Dietista",
                organisation="Clinic",
                provenance=(ConversationTurn(evidence_id=wrong),),
            ),
        ),
    )


def test_a_skill_whose_only_turn_is_retracted_is_a_gap_not_a_mirrored_ask(tmp_path: Path) -> None:
    store, log = _setup(tmp_path)
    live = _say(log, "I know Python")
    wrong = _say(log, "I know Salesforce")
    master = _skill_master(live, wrong)
    write_master(store, master)

    before = generate(store, master, offer_id="o-1", advert="x", asks=("Python", "Salesforce"))
    assert before.gaps == ()  # control: held while live

    _say(log, "no", retracts=wrong)
    after = generate(store, master, offer_id="o-2", advert="x", asks=("Python", "Salesforce"))
    assert after.gaps == ("Salesforce",)


def test_ats_calls_a_retracted_skill_a_gap_not_missing_have_it() -> None:
    master = _skill_master("ev-000001", "ev-000002")
    assert classify_keyword("nothing here", master, "Salesforce") == MISSING_HAVE_IT
    withdrawn = frozenset({"ev-000002"})
    assert classify_keyword("nothing here", master, "Salesforce", withdrawn) == MISSING_GAP
    rows = keyword_coverage("nothing here", master, ("Salesforce",), withdrawn)
    assert rows["by_status"][MISSING_GAP] == 1


def test_a_draft_leaves_out_retracted_entries_and_prepare_succeeds(tmp_path: Path) -> None:
    store, log = _setup(tmp_path)
    live = _say(log, "I know Python")
    wrong = _say(log, "I worked at the Clinic")
    master = _skill_master(live, wrong)
    write_master(store, master)
    _say(log, "no", retracts=wrong)

    prepare(
        store,
        master,
        offer_id="o-1",
        advert="Python Salesforce",
        recipient="hr@example.invalid",
        details=_DETAILS,
    )
    where = store.path("cv", "generated", "o-1", "v1")
    for name in ("cv.md", "letter.md"):
        text = (where / name).read_text(encoding="utf-8")
        assert "Salesforce" not in text
        assert "Dietista" not in text
    assert "Python" in (where / "cv.md").read_text(encoding="utf-8")
    manifest = read_manifest(store, "o-1", 1)
    assert {o.section for o in manifest.omissions if "retracted" in o.reason} == {
        "experience",
        "skills",
    }


def test_a_line_retracted_after_drafting_is_refused_with_the_retraction_named(
    tmp_path: Path,
) -> None:
    store, log = _setup(tmp_path)
    live = _say(log, "I know Python")
    wrong = _say(log, "I worked at the Clinic")
    master = _skill_master(live, wrong)
    write_master(store, master)
    manifest = generate(store, master, offer_id="o-1", advert="Salesforce", asks=())
    assert any(claim.section == "experience" for claim in manifest.claims)
    _say(log, "no", retracts=wrong)

    measured = measure_prepared(store, master, "o-1", 1)
    findings = " ".join(measured["unapproved_episodes"])
    assert "the candidate retracted the evidence" in findings
    assert "no per-use approval backs this line" not in findings


def test_ats_calls_a_skill_reached_only_through_a_retracted_synonym_a_gap() -> None:
    """`js` is held, the posting asks for `javascript`: the synonym branch is the only route."""
    master = CVMaster(
        skills=(Skill(name="js", provenance=(ConversationTurn(evidence_id="ev-000009"),)),)
    )
    assert classify_keyword("nothing here", master, "javascript") == MISSING_HAVE_IT
    withdrawn = frozenset({"ev-000009"})
    assert classify_keyword("nothing here", master, "javascript", withdrawn) == MISSING_GAP


def test_an_approved_episode_on_a_retracted_turn_is_left_out_and_named(tmp_path: Path) -> None:
    store, log = _setup(tmp_path)
    wrong = _say(log, "I shipped the migration alone")
    master = CVMaster(
        episodes=(
            Episode(
                kind="achievement",
                text="Shipped the migration alone",
                provenance=(ConversationTurn(evidence_id=wrong),),
            ),
        )
    )
    write_master(store, master)
    before = generate(store, master, offer_id="o-1", advert="x", _approved_episodes=(0,))
    assert "Shipped the migration" in (
        store.path("cv", "generated", "o-1", "v1", "letter.md").read_text(encoding="utf-8")
    )
    assert before.omissions == ()

    _say(log, "no", retracts=wrong)
    after = generate(store, master, offer_id="o-2", advert="x", _approved_episodes=(0,))
    letter = store.path("cv", "generated", "o-2", "v1", "letter.md").read_text(encoding="utf-8")
    assert "Shipped the migration" not in letter
    assert [(o.section, o.reason) for o in after.omissions] == [
        ("episodes", "the candidate retracted the evidence this entry cites")
    ]
    assert not any(c.section == "episodes" for c in after.claims)
