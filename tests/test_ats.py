"""T80 — the ATS text-layer contract, asserted over the document text.

Each test drives a real `generate()` call rather than hand-writing a fixture
document: the gate is about what a machine parsing the actual generated CV
would see, and a synthetic string could pass a check that a real document
built the same way it always is would fail. `test_a_document_missing_a_required_field_fails`
and `test_a_replacement_character_in_the_text_layer_fails` are the D-21 guard
— a check that only ever sees a complete document is not a check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.ats import (
    COVERED,
    KEYWORD_STATUSES,
    SYNONYM_ONLY,
    _application_text,
    audit_documents,
    check_document,
    classify_keyword,
    keyword_coverage,
)
from integral.cv_store import CVMaster, Experience, Skill, SourcedText, write_master
from integral.generate import generate
from integral.identity import ProfileStore, create_profile

ADVERT = "We are hiring a data engineer in Girona to own a PostgreSQL estate."


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


def _experience() -> Experience:
    return Experience(
        title="Data engineer",
        organisation="Cintra Logistics",
        start="2021",
        end="2025",
        description="Moved the billing system onto PostgreSQL.",
    )


def test_a_generated_cv_carries_contact_email_as_literal_text(store: ProfileStore) -> None:
    master = CVMaster(
        headline=SourcedText(text="Data engineer — ada.lovelace@example.invalid"),
        experience=(_experience(),),
    )
    write_master(store, master)
    generate(store, master, offer_id="girona-1", advert=ADVERT)

    cv = store.path("cv", "generated", "girona-1", "v1", "cv.md")
    result = check_document(cv)

    assert result["missing_fields"] == []
    assert result["violations"] == []
    assert "ada.lovelace@example.invalid" in cv.read_text(encoding="utf-8")


def test_a_document_missing_a_required_field_fails(store: ProfileStore) -> None:
    master = CVMaster(
        headline=SourcedText(text="Data engineer — no way to reach me here"),
        experience=(_experience(),),
    )
    write_master(store, master)
    generate(store, master, offer_id="girona-1", advert=ADVERT)

    cv = store.path("cv", "generated", "girona-1", "v1", "cv.md")
    result = check_document(cv)

    assert result["missing_fields"] == ["contact_email"]
    assert "missing required field: contact_email" in result["violations"]

    audited = audit_documents([cv])
    assert audited["documents_missing_a_required_text_layer_field"] == 1
    assert audited["documents_missing_a_required_text_layer_field_evaluated"] == 1
    assert audited["gate_status"] == "measured"


def test_a_replacement_character_in_the_text_layer_fails(store: ProfileStore) -> None:
    master = CVMaster(
        headline=SourcedText(text="Data engineer — ada.lovelace@example.invalid"),
        experience=(_experience(),),
    )
    write_master(store, master)
    generate(store, master, offer_id="girona-1", advert=ADVERT)

    cv = store.path("cv", "generated", "girona-1", "v1", "cv.md")
    intact = cv.read_text(encoding="utf-8")

    corrupted_replacement = cv.with_name("cv-replacement.md")
    corrupted_replacement.write_text(intact + "Experience � Cintra Logistics\n", encoding="utf-8")
    replacement_result = check_document(corrupted_replacement)
    assert "�" in replacement_result["corruption_markers"]
    assert any("corrupted text layer" in v for v in replacement_result["violations"])

    corrupted_cid = cv.with_name("cv-cid.md")
    corrupted_cid.write_text(intact + "Experience (cid:14) Cintra Logistics\n", encoding="utf-8")
    cid_result = check_document(corrupted_cid)
    assert "(cid:14)" in cid_result["corruption_markers"]
    assert any("corrupted text layer" in v for v in cid_result["violations"])


def test_corruption_alone_is_not_counted_as_a_missing_field(store: ProfileStore) -> None:
    """The gate's key names one breach; it must count only that one.

    A document carrying every required field but a mojibake text layer is a
    real failure under a different name. Counting it as a missing field made
    `documents_missing_a_required_text_layer_field` a number that could not be
    read literally. It still fails the gate — through the CLI exit code in the
    task's own ```bash``` block, which reads the all-violations total.
    """
    master = CVMaster(
        headline=SourcedText(text="Data engineer — ada.lovelace@example.invalid"),
        experience=(_experience(),),
    )
    write_master(store, master)
    generate(store, master, offer_id="girona-1", advert=ADVERT)

    cv = store.path("cv", "generated", "girona-1", "v1", "cv.md")
    intact = cv.read_text(encoding="utf-8")
    corrupted = cv.with_name("cv-corrupt-only.md")
    corrupted.write_text(intact + "Experience \ufffd Cintra Logistics\n", encoding="utf-8")

    audited = audit_documents([corrupted])

    assert audited["documents_missing_a_required_text_layer_field"] == 0
    assert audited["documents_with_text_layer_violations"] == 1
    assert check_document(corrupted)["missing_fields"] == []


def test_the_gate_does_not_pass_on_an_empty_input_set(store: ProfileStore) -> None:
    empty = audit_documents([])
    assert empty["documents_missing_a_required_text_layer_field_evaluated"] == 0
    assert empty["documents_missing_a_required_text_layer_field"] == 0
    assert empty["gate_status"] == "unmeasured", (
        "a zero violation count over zero documents checked is not a pass — "
        "the gate must be able to tell the two apart"
    )

    master = CVMaster(
        headline=SourcedText(text="Data engineer — ada.lovelace@example.invalid"),
        experience=(_experience(),),
    )
    write_master(store, master)
    generate(store, master, offer_id="girona-1", advert=ADVERT)
    cv = store.path("cv", "generated", "girona-1", "v1", "cv.md")

    real = audit_documents([cv])
    assert real["documents_missing_a_required_text_layer_field_evaluated"] > 0
    assert real["gate_status"] == "measured"


# ---------------------------------------------------------------------------
# T81 — keyword coverage against the posting, in four statuses


def _master_with_an_omittable_skill() -> CVMaster:
    """A store built so all four keyword statuses are reachable off one document.

    `PostgreSQL` is in `_experience()`'s description, an `_ALWAYS` section, so
    it is always rendered — the `covered` case, and (under the spelling
    `Postgres`) the `synonym-only` case. `Salesforce` is a `_SELECTED`-section
    skill that `ADVERT` never mentions and generation is called with no
    `asks`, so `_select` omits it — the store holds it, the document does not
    — `missing (have it)`. `Kubernetes` is nowhere in the store at all —
    `missing (gap)`.
    """
    return CVMaster(
        headline=SourcedText(text="Data engineer — ada.lovelace@example.invalid"),
        experience=(_experience(),),
        skills=(Skill(name="Salesforce", level="working"),),
    )


def test_every_posting_keyword_receives_exactly_one_status(store: ProfileStore) -> None:
    master = _master_with_an_omittable_skill()
    write_master(store, master)
    manifest = generate(store, master, offer_id="girona-1", advert=ADVERT)
    document_text = _application_text(store, "girona-1", manifest.version)

    keywords = ("PostgreSQL", "Postgres", "Salesforce", "Kubernetes")
    result = keyword_coverage(document_text, master, keywords)

    assert result["posting_keywords_left_unclassified"] == 0
    assert result["posting_keywords_left_unclassified_evaluated"] == len(keywords)
    statuses = {row["keyword"]: row["status"] for row in result["rows"]}
    assert statuses == {
        "PostgreSQL": "covered",
        "Postgres": "synonym-only",
        "Salesforce": "missing (have it)",
        "Kubernetes": "missing (gap)",
    }
    # Every one of the four declared statuses is actually reachable, not just
    # named — the D-21 guard for this gate.
    assert set(statuses.values()) == set(KEYWORD_STATUSES)


def test_a_keyword_the_store_holds_but_the_document_omits_is_missing_have_it(
    store: ProfileStore,
) -> None:
    master = _master_with_an_omittable_skill()
    write_master(store, master)
    manifest = generate(store, master, offer_id="girona-1", advert=ADVERT)
    document_text = _application_text(store, "girona-1", manifest.version)
    assert "Salesforce" not in document_text  # the omission this test relies on

    result = keyword_coverage(document_text, master, ("Salesforce",))
    assert result["rows"] == [{"keyword": "Salesforce", "status": "missing (have it)"}]


def test_a_keyword_the_candidate_lacks_is_missing_gap(store: ProfileStore) -> None:
    master = _master_with_an_omittable_skill()
    write_master(store, master)
    manifest = generate(store, master, offer_id="girona-1", advert=ADVERT)
    document_text = _application_text(store, "girona-1", manifest.version)

    result = keyword_coverage(document_text, master, ("Kubernetes",))
    assert result["rows"] == [{"keyword": "Kubernetes", "status": "missing (gap)"}]


def test_the_keyword_coverage_gate_does_not_pass_on_an_empty_input_set(
    store: ProfileStore,
) -> None:
    master = _master_with_an_omittable_skill()
    write_master(store, master)
    manifest = generate(store, master, offer_id="girona-1", advert=ADVERT)
    document_text = _application_text(store, "girona-1", manifest.version)

    empty = keyword_coverage(document_text, master, ())
    assert empty["posting_keywords_left_unclassified_evaluated"] == 0
    assert empty["posting_keywords_left_unclassified"] == 0
    assert empty["gate_status"] == "unmeasured", (
        "a zero violation count over zero keywords checked is not a pass — "
        "the gate must be able to tell the two apart"
    )

    real = keyword_coverage(document_text, master, ("PostgreSQL",))
    assert real["posting_keywords_left_unclassified_evaluated"] > 0
    assert real["gate_status"] == "measured"


def test_a_longer_declared_spelling_is_synonym_only_not_covered() -> None:
    """`_SYNONYMS` declares `node.js` an alternate spelling of `node`, so a
    document that only ever wrote `Node.js` said it differently — it did not
    say `node`. `_mentions` treats `.` as a term boundary, so a plain literal
    check reported `covered` and contradicted the table.

    The distinction is the point of the status: the candidate is told to add
    the posting's own wording, which an ATS may match literally.
    """

    master = CVMaster()

    assert classify_keyword("We use Node.js daily", master, "node") == SYNONYM_ONLY
    # Unchanged: the standalone spelling, and a document carrying both.
    assert classify_keyword("We use node daily", master, "node") == COVERED
    assert classify_keyword("node and Node.js", master, "node") == COVERED
    # Unchanged for the pair that has no substring relationship.
    assert classify_keyword("We use PostgreSQL", master, "postgres") == SYNONYM_ONLY
    assert classify_keyword("We use Postgres", master, "postgres") == COVERED
