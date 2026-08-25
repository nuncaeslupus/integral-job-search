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

from integral.ats import audit_documents, check_document
from integral.cv_store import CVMaster, Experience, SourcedText, write_master
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
