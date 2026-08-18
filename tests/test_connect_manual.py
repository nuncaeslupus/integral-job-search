"""T11 — the normalised offer schema, and the manual-paste connector.

The gate is `offer_schema_violations == 0`. Two properties carry the task, and
each maps straight to a §5.2 sentence:

* **`text` is verbatim.** Every later stage — extraction, evidence spans,
  explanations quoting the ad's own words — computes offsets into whatever is
  stored here. A connector that "tidies" the text (trims trailing whitespace,
  collapses blank lines, re-encodes an accent) invalidates every span computed
  against it without anything downstream being able to tell.
* **A connector may not invent fields.** The manual-paste connector has no
  structured data beyond what the candidate typed alongside the paste, so
  every field it cannot see stays `None` — never a guess dressed up as a
  default.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jobsearch.identity import ProfileStore, create_profile
from jobsearch.offers import (
    MINIMUM_CHECKS,
    Location,
    Offer,
    OfferError,
    Salary,
    compute_offer_id,
    connect_manual,
    load_offer,
    probe_offers,
    save_offer,
    write_evidence,
)

AD_TEXT_EN = "Backend Engineer wanted. Python, remote.\nSalary DOE.\nApply within."
AD_TEXT_ES = "Se busca Ingeniera Backend. Python, remoto.\nSalario a convenir."
AD_TEXT_ACCENTED = (
    "Cerca de Enginyer/a Backend a Barcelona — condicions flexibles, salari competitiu."
)


def test_pasted_text_produces_valid_offer() -> None:
    """A pasted ad must yield a schema-valid offer with verbatim `text` — the
    property every downstream stage (extraction, evidence spans) depends on."""
    offer = connect_manual(AD_TEXT_EN)
    assert isinstance(offer, Offer)
    assert offer.text == AD_TEXT_EN
    assert offer.source == "manual"


def test_text_preserved_byte_for_byte_with_whitespace_and_accents() -> None:
    """Internal blank lines, trailing whitespace and accented characters must
    survive unchanged. A normalisation pass that looks harmless here is exactly
    the kind of change that shifts an offset computed against this text later."""
    raw = "  Enginyer/a de dades — 100% remot.\n\n\tCondicions: flexibles.  \n"
    offer = connect_manual(raw)
    assert offer.text == raw
    assert offer.text[0] == " "  # leading whitespace not stripped
    assert offer.text.endswith("  \n")  # trailing whitespace not stripped
    assert "—" in offer.text
    assert "Enginyer/a" in offer.text


def test_no_invented_fields_when_only_text_is_given() -> None:
    """A connector may not invent fields (§5.2): with no structured data
    supplied, every optional field must come back absent, not defaulted to
    something plausible-looking."""
    offer = connect_manual(AD_TEXT_EN)
    assert offer.source_ref is None
    assert offer.url is None
    assert offer.fetched_at is None
    assert offer.title is None
    assert offer.company is None
    assert offer.location is None
    assert offer.salary is None
    assert offer.language is None
    assert offer.expires_at is None
    assert offer.duplicate_of is None


def test_explicit_metadata_alongside_a_paste_is_recorded() -> None:
    """When the candidate *does* supply metadata alongside the paste (copied
    from the browser, say), it is recorded — absence is the default, not a
    ceiling on what the connector can carry."""
    offer = connect_manual(
        AD_TEXT_EN,
        title="Backend Engineer",
        company="Acme SL",
        url="https://example.test/jobs/123",
        source_ref="123",
        language="en",
        location=Location(raw="Barcelona", country="ES", remote="hybrid"),
        salary=Salary(min=45000, max=55000, currency="EUR", period="year", stated=True),
    )
    assert offer.title == "Backend Engineer"
    assert offer.company == "Acme SL"
    assert offer.url == "https://example.test/jobs/123"
    assert offer.language == "en"
    assert offer.location is not None and offer.location.remote == "hybrid"
    assert offer.salary is not None and offer.salary.stated is True


def test_same_paste_produces_the_same_offer_id() -> None:
    """Dedup (T13) and tombstones (S5) key on offer identity across sources —
    two connections of the identical text must mint the identical id."""
    first = connect_manual(AD_TEXT_EN)
    second = connect_manual(AD_TEXT_EN)
    assert first.id == second.id


def test_different_paste_produces_a_different_offer_id() -> None:
    """Two genuinely different ads must not collide on the same id — that
    would mean one silently overwrote the other at `offers/<id>.json`."""
    first = connect_manual(AD_TEXT_EN)
    second = connect_manual(AD_TEXT_ES)
    assert first.id != second.id


def test_offer_id_does_not_depend_on_metadata() -> None:
    """The id is content-derived from `text` alone (module docstring): the same
    ad pasted with and without a title must still be recognised as one offer."""
    bare = connect_manual(AD_TEXT_EN)
    annotated = connect_manual(AD_TEXT_EN, title="Backend Engineer", company="Acme SL")
    assert bare.id == annotated.id


def test_offer_id_is_not_a_random_or_time_based_value() -> None:
    """`compute_offer_id` must be a pure function of the text — never a UUID4
    or a clock read, which would break every re-connection of the same ad."""
    assert compute_offer_id(AD_TEXT_EN) == compute_offer_id(AD_TEXT_EN)
    assert compute_offer_id(AD_TEXT_EN).startswith("sha256:")
    digest_part = compute_offer_id(AD_TEXT_EN).removeprefix("sha256:")
    assert len(digest_part) == 64
    assert all(c in "0123456789abcdef" for c in digest_part)


@pytest.mark.parametrize("blank", ["", "   ", "\n\n\t  \n"])
def test_blank_paste_is_refused_not_stored(blank: str) -> None:
    """An empty or whitespace-only paste must be refused rather than stored as
    an empty offer — there would be nothing for extraction to find evidence
    spans in."""
    with pytest.raises(OfferError):
        connect_manual(blank)


def test_unknown_language_is_recorded_as_unknown() -> None:
    """§5.2: language is ES/EN/CA. When the connector cannot tell, that must be
    `None` (unknown) — never a guess dressed up as a plausible default."""
    offer = connect_manual(AD_TEXT_ACCENTED)
    assert offer.language is None


def test_explicit_language_is_recorded_verbatim() -> None:
    offer = connect_manual(AD_TEXT_ACCENTED, language="ca")
    assert offer.language == "ca"


def test_offer_schema_forbids_unknown_fields() -> None:
    """`extra="forbid"` is what makes 'a connector may not invent fields'
    mechanical rather than a convention a reviewer has to remember to check."""
    payload = connect_manual(AD_TEXT_EN).model_dump(mode="json")
    payload["recruiter_note"] = "not part of the schema"
    with pytest.raises(ValidationError):
        Offer.model_validate(payload)


def test_offer_schema_rejects_a_malformed_id() -> None:
    payload = connect_manual(AD_TEXT_EN).model_dump(mode="json")
    payload["id"] = "just-some-string"
    with pytest.raises(ValidationError):
        Offer.model_validate(payload)


def test_offer_schema_rejects_an_unrecognised_status() -> None:
    """Only spec-v2-process §7.1's seven statuses are valid; anything else is
    a defect, per that section's own wording."""
    payload = connect_manual(AD_TEXT_EN).model_dump(mode="json")
    payload["status"] = "ghosted"
    with pytest.raises(ValidationError):
        Offer.model_validate(payload)


def test_a_freshly_connected_offer_has_status_new() -> None:
    """S5 owns the transitions between statuses; a connector only ever
    produces a freshly-seen offer."""
    assert connect_manual(AD_TEXT_EN).status == "new"


def test_salary_stated_has_no_default() -> None:
    """§5.2: `salary.stated` distinguishes an employer-stated figure from an
    absent one. Letting it default would silently turn 'we don't know whether
    this was stated' into 'it was not' for every caller that forgets the flag."""
    with pytest.raises(ValidationError):
        Salary.model_validate({"min": 40000, "max": 50000, "currency": "EUR", "period": "year"})


def test_offer_and_offer_fields_are_frozen() -> None:
    """`frozen=True` — a typo'd mutation must be an error, not a silent
    in-place edit of a record other stages assume is immutable once written."""
    offer = connect_manual(AD_TEXT_EN)
    with pytest.raises(ValidationError):
        offer.text = "something else"


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    identity = create_profile(tmp_path / "profiles", "Probe Candidate", language="en")
    return ProfileStore(tmp_path / "profiles", identity.handle)


def test_save_offer_writes_where_step_runtime_expects_it(store: ProfileStore) -> None:
    """`step_runtime`'s `offers` detector looks for anything under `offers/` in
    the candidate's tree; the filename must be `<id>.json`."""
    offer = connect_manual(AD_TEXT_EN)
    written = save_offer(store, offer)
    assert written == store.path("offers", f"{offer.id}.json")
    assert written.exists()
    on_disk = json.loads(written.read_text(encoding="utf-8"))
    assert on_disk["text"] == AD_TEXT_EN
    assert on_disk["id"] == offer.id


def test_save_and_load_offer_roundtrips(store: ProfileStore) -> None:
    offer = connect_manual(AD_TEXT_ACCENTED, title="Enginyer/a de dades", language="ca")
    save_offer(store, offer)
    reloaded = load_offer(store, offer.id)
    assert reloaded == offer


def test_load_offer_raises_on_missing_record(store: ProfileStore) -> None:
    with pytest.raises(OfferError):
        load_offer(store, "sha256:" + "0" * 64)


def test_load_offer_raises_on_a_hand_edited_record_with_an_invented_field(
    store: ProfileStore,
) -> None:
    """A record that reached disk some other way — a hand edit, a future
    connector with a bug — must still be refused on read, not just on write."""
    offer = connect_manual(AD_TEXT_EN)
    save_offer(store, offer)
    corrupted = offer.model_dump(mode="json")
    corrupted["ad_score"] = 0.91
    store.write_json(corrupted, "offers", f"{offer.id}.json")
    with pytest.raises(OfferError):
        load_offer(store, offer.id)


def test_probe_offers_measures_something(tmp_path: Path) -> None:
    """The gate must not pass by measuring nothing — a floor on checks run,
    mirroring `decline.py`'s `MINIMUM_ASKS` and `revision.py`'s
    `MINIMUM_AGED`."""
    measured = probe_offers()
    assert measured["checks_run"] >= MINIMUM_CHECKS
    assert measured["offer_schema_violations"] == len(measured["violations"])


def test_write_evidence_records_zero_violations(tmp_path: Path) -> None:
    evidence_path = tmp_path / "T11.json"
    measured = write_evidence(evidence_path)
    assert measured["offer_schema_violations"] == 0
    on_disk = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert on_disk["offer_schema_violations"] == 0
