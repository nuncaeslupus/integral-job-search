"""T146 — a denial and a count are claims; the manifest must be able to refuse both.

Cases are derived from the task text, not from the code: the live letter said
"I have not used observability tools" (false, Honeycomb at Flanks) and
"~1,600 commits across seven repositories, six published" (stale within the
session). The family that keeps the check honest is the third: a denial WITH a
backing row must PASS, or banning the word "not" would satisfy the gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral import claim_trace
from integral.application_authorship import check_authorship
from integral.claim_trace import (
    check_version,
    entry_denials,
    is_denial,
    paragraph_defects,
    quantities,
)
from integral.cv_store import (
    ConversationTurn,
    CVMaster,
    DocumentSpan,
    Episode,
    Experience,
    Skill,
    SourcedText,
    write_master,
)
from integral.generate import Claim, Manifest, generate, read_manifest, traceability
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog

DENIAL = "I have not used observability tools in production."
COUNT = "About 1,600 commits across seven repositories, six published."
ADVERT = "A data engineer in Girona. PostgreSQL and migrations."


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


def say(
    store: ProfileStore, text: str, kind: str = "statement", source: str = "conversation"
) -> str:
    return (
        EvidenceLog(store)
        .append(
            recorded_at="2026-10-06T10:00:00Z",
            step="history",
            kind=kind,  # type: ignore[arg-type]
            text=text,
            source=source,  # type: ignore[arg-type]
        )
        .id
    )


def cited(*ids: str) -> tuple[ConversationTurn, ...]:
    return tuple(ConversationTurn(evidence_id=i) for i in ids)


def kinds(store: ProfileStore, entry: SourcedText | Skill) -> list[str]:
    return [d.kind for d in entry_denials(store, entry)]


# --- the classifier --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "I have not used observability tools.",
        "I haven't used Kubernetes",
        "I haven" + chr(0x2019) + "t used Kubernetes",
        "Never touched Kafka.",
        "No experience with Terraform.",
        "No he usado herramientas de observabilidad.",
        "Nunca he trabajado con Kafka.",
        "Sense experiència amb Terraform. Mai he fet servir Kafka.",
    ],
)
def test_denials_are_recognised_in_three_languages(text: str) -> None:
    assert is_denial(text)


@pytest.mark.parametrize(
    "text",
    [
        "Used Honeycomb at Flanks.",
        "Built the NoSQL layer.",
        "No-code automation lead.",
        "Migrated billing without downtime.",
    ],
)
def test_an_assertion_is_not_a_denial(text: str) -> None:
    assert not is_denial(text)


def test_quantities_are_read_from_digits_and_words_and_years_are_not_counts() -> None:
    assert quantities(COUNT) == [1600, 7, 6]
    assert quantities("Seven repositories, siete repos, set repos.") == [7, 7]
    assert quantities("A zero-downtime cutover, once.") == []
    assert quantities("Since 2019, until 1998.") == []
    assert quantities("Cut cost by 2.5 percent") == [None]
    assert quantities("30% faster, 12 services") == [30, 12]
    assert quantities("Web3 and S3 on 3D scenes") == [3]  # only the free-standing 3


# --- a stored denial needs a backing row exactly as an assertion does --------


def test_a_denial_with_no_backing_row_is_refused(store: ProfileStore) -> None:
    assert kinds(store, SourcedText(text=DENIAL)) == ["denial_without_backing_row"]


def test_a_denial_the_candidate_made_passes(store: ProfileStore) -> None:
    """The case that keeps the check honest: not satisfiable by banning 'not'."""
    row = say(store, "I have not used observability tools in production, only logs.")
    assert kinds(store, SourcedText(text=DENIAL, provenance=cited(row))) == []


def test_the_live_incident_is_refused_the_candidate_used_honeycomb(store: ProfileStore) -> None:
    said = say(store, "I used Honeycomb at Flanks for years and I understand queries and traces.")
    assert kinds(store, SourcedText(text=DENIAL, provenance=cited(said))) == [
        "denial_without_backing_row"
    ]


def test_an_affirmation_sharing_the_topic_does_not_back_a_denial(store: ProfileStore) -> None:
    """Same words, opposite sense: overlap alone would let the contradiction back the lie."""
    said = say(store, "I used observability tools in production for years.")
    assert kinds(store, SourcedText(text=DENIAL, provenance=cited(said))) == [
        "denial_without_backing_row"
    ]


def test_a_denial_about_something_else_does_not_back_this_one(store: ProfileStore) -> None:
    other = say(store, "I have never written any Haskell.")
    assert kinds(store, SourcedText(text=DENIAL, provenance=cited(other))) == [
        "denial_without_backing_row"
    ]


def test_a_withdrawn_row_no_longer_backs_a_denial(store: ProfileStore) -> None:
    row = say(store, DENIAL)
    entry = SourcedText(text=DENIAL, provenance=cited(row))
    assert kinds(store, entry) == []
    EvidenceLog(store).append(
        recorded_at="2026-10-06T11:00:00Z",
        step="history",
        kind="retraction",
        text="that was wrong",
        source="conversation",
        retracts=row,
    )
    assert kinds(store, entry) == ["denial_without_backing_row"]


def test_a_reaction_row_is_not_the_candidate_denying(store: ProfileStore) -> None:
    row = say(store, DENIAL, kind="reaction")
    assert kinds(store, SourcedText(text=DENIAL, provenance=cited(row))) == [
        "denial_without_backing_row"
    ]


def test_a_cited_row_that_does_not_exist_backs_nothing(store: ProfileStore) -> None:
    entry = SourcedText(text=DENIAL, provenance=cited("ev-999999"))
    assert kinds(store, entry) == ["denial_without_backing_row"]


def test_a_document_span_can_back_a_denial(store: ProfileStore) -> None:
    source = "Observability: I have not used observability tools in production."
    store.path("cv", "source").mkdir(parents=True)
    store.path("cv", "source", "doc-000001.txt").write_text(source, encoding="utf-8")
    whole = DocumentSpan(source_file="doc-000001", start=0, end=len(source))
    assert kinds(store, SourcedText(text=DENIAL, provenance=(whole,))) == []
    heading = DocumentSpan(source_file="doc-000001", start=0, end=14)  # "Observability:"
    assert kinds(store, SourcedText(text=DENIAL, provenance=(heading,))) == [
        "denial_without_backing_row"
    ]


def test_a_denial_in_a_name_field_is_read_too(store: ProfileStore) -> None:
    assert kinds(store, Skill(name="Never used Kafka")) == ["denial_without_backing_row"]


# --- the generator withholds an unbacked denial, keeps a backed one ----------


def test_the_generator_omits_an_unbacked_denial_and_says_why(store: ProfileStore) -> None:
    master = CVMaster(
        headline=SourcedText(text=DENIAL),
        experience=(Experience(title="Dev", organisation="Cintra", description="Moved billing."),),
    )
    write_master(store, master)
    manifest = generate(store, master, offer_id="o1", advert=ADVERT)
    written = {c.text for c in manifest.claims}
    assert DENIAL not in written
    assert any("Moved billing" in t for t in written)
    assert [o.section for o in manifest.omissions] == ["headline"]
    assert "no backing row" in manifest.omissions[0].reason
    assert check_version(store, master, "o1", 1)["untraced_claim_defects"] == 0


def test_the_generator_keeps_a_denial_the_candidate_made(store: ProfileStore) -> None:
    row = say(store, "I have not used observability tools in production.")
    master = CVMaster(headline=SourcedText(text=DENIAL, provenance=cited(row)))
    write_master(store, master)
    manifest = generate(store, master, offer_id="o1", advert=ADVERT)
    assert DENIAL in {c.text for c in manifest.claims}
    assert not manifest.omissions
    assert check_version(store, master, "o1", 1)["untraced_claim_defects"] == 0


def test_an_approved_episode_that_is_an_unbacked_denial_is_left_out(store: ProfileStore) -> None:
    """The episode path is filtered separately from the CV path and has its own pin."""
    master = CVMaster(
        headline=SourcedText(text="Backend engineer"),
        episodes=(Episode(kind="lesson", text="I have never used observability tools."),),
    )
    write_master(store, master)
    manifest = generate(store, master, offer_id="o1", advert=ADVERT, _approved_episodes=(0,))
    assert "I have never used observability tools." not in {c.text for c in manifest.claims}
    assert [o.section for o in manifest.omissions] == ["episodes"]


def test_check_version_refuses_a_backed_line_whose_entry_is_a_bare_denial(
    store: ProfileStore,
) -> None:
    """Manifest and document agree and T45 is green - only the claim check sees it."""
    master = CVMaster(headline=SourcedText(text=DENIAL))
    write_master(store, CVMaster())
    generate(store, CVMaster(), offer_id="o1", advert=ADVERT)
    where = store.path("cv", "generated", "o1", "v1")
    cv = where / "cv.md"
    cv.write_text(cv.read_text(encoding="utf-8") + DENIAL + "\n", encoding="utf-8")
    manifest = read_manifest(store, "o1", 1)
    row = Claim(document="cv.md", text=DENIAL, section="headline", entry_index=0)
    (where / "manifest.json").write_text(
        Manifest(**{**manifest.model_dump(), "claims": (*manifest.claims, row)}).model_dump_json(),
        encoding="utf-8",
    )
    assert traceability(store, master, "o1", 1)["claims_untraced"] == []
    checked = check_version(store, master, "o1", 1)
    assert [d.kind for d in checked["defects"]] == ["denial_without_backing_row"]
    assert checked["untraced_claim_defects"] == 1


# --- the letter: what a paragraph the candidate did not write may assert -----


def test_an_assistant_denial_is_refused() -> None:
    assert [d.kind for d in paragraph_defects("assistant", DENIAL, [])] == [
        "denial_without_backing_row"
    ]


def test_an_edited_denial_needs_the_candidates_own_denial_cited() -> None:
    assert paragraph_defects("edited", DENIAL, ["I have not used observability tools."]) == []
    assert paragraph_defects("edited", DENIAL, ["I used observability tools daily."])  # opposite
    assert paragraph_defects("edited", DENIAL, ["I have never written Haskell."])  # unrelated


def test_an_assistant_hand_typed_count_is_refused_per_number() -> None:
    assert [d.kind for d in paragraph_defects("assistant", COUNT, [])] == ["hand_typed_count"] * 3


def test_an_edited_paragraph_may_keep_the_candidates_number_but_not_add_one() -> None:
    assert paragraph_defects("edited", "I run 3 services.", ["I run 3 services daily."]) == []
    added = paragraph_defects("edited", "I run 4 services.", ["I run 3 services daily."])
    assert [d.kind for d in added] == ["hand_typed_count"]


def test_a_number_is_spent_once() -> None:
    twice = paragraph_defects("edited", "3 teams, 3 services.", ["I run 3 services."])
    assert [d.kind for d in twice] == ["hand_typed_count"]


def test_years_and_the_candidates_own_paragraph_are_never_counts() -> None:
    assert paragraph_defects("assistant", "Since 2019 at Flanks.", []) == []
    assert paragraph_defects("candidate", COUNT + " " + DENIAL, []) == []


def _letter(store: ProfileStore, author: str, body: str, *sources: str) -> list[str]:
    ids = [
        say(store, text, kind="candidate_statement", source="application_draft") for text in sources
    ]
    cell = "" if author == "assistant" else " ".join(ids)
    table = (
        "## Authorship\n| n | a | e | c |\n|---|---|---|---|\n"
        f"| 1 | {author} | {cell} | reworded |\n"
    )
    return list(check_authorship(body, table, EvidenceLog(store)).defects)


def test_check_authorship_refuses_an_assistant_paragraph_carrying_the_live_incident(
    store: ProfileStore,
) -> None:
    """Both live defects, through the real gate: each in a paragraph that cites nothing."""
    for body, kind in ((DENIAL, "denial_without_backing_row"), (COUNT, "hand_typed_count")):
        found = _letter(store, "assistant", body)
        assert any(kind in d for d in found), found


def test_check_authorship_passes_the_honest_gap_paragraph(store: ProfileStore) -> None:
    """The counter-case through the real gate: the candidate said it, the paragraph keeps it."""
    assert _letter(store, "edited", DENIAL, DENIAL) == []
    assert _letter(store, "candidate", DENIAL, DENIAL) == []


# --- the gate ---------------------------------------------------------------


def test_the_probes_judge_every_hole_and_every_counter_case() -> None:
    verdicts = claim_trace.probe_cases()
    labels = {v["case"] for v in verdicts}
    assert {
        "stored denial with no backing row",
        "stored denial the candidate made",
        "assistant denial",
        "edited denial the candidate cited",
        "assistant hand-typed count",
        "edited count the candidate wrote",
    } <= labels
    assert all(v["expected"] == v["found"] for v in verdicts), verdicts
    assert any(v["expected"] == 0 and "denial" in v["case"] for v in verdicts)


def test_the_measurement_over_the_corpus_is_clean() -> None:
    measured = claim_trace.measure()
    assert measured["untraced_claim_defects"] == 0
    assert measured["claims_checked"] > 0 and measured["adverts_generated"] > 0
    assert measured["probe_cases_misjudged"] == 0


def test_main_exits_zero_and_writes_the_record(tmp_path: Path) -> None:
    out = tmp_path / "T146.json"
    assert claim_trace._main(["claim_trace", str(out)]) == 0
    assert json.loads(out.read_text())["untraced_claim_defects"] == 0
