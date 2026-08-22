"""T42 — the annotation is local, and the profile never rides along with an advert.

Extraction answers "what does this advert say"; annotation answers "what does it
say *to this candidate*". Keeping them apart is not a layering preference: it is
what keeps `extractions/<offer_id>.json` candidate-independent — cacheable,
shareable, leaking nothing — and it is the one privacy failure that cannot be
undone once it happens.

So the gate is measured over the **actual outbound payload**. A test asserting
that the code does not intend to send the profile proves nothing; these scan the
bytes `model_request` would put on the wire for the candidate's own strings.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from integral.annotation import (
    EGRESS_SAMPLE,
    annotate,
    egress_leaks,
    fixture_constraints,
    measure,
    outbound_payloads,
    stated_strings,
    write_annotation,
)
from integral.candidate import OfferFacts
from integral.dimensions import load_dimensions
from integral.extraction import OfferExtraction
from integral.identity import ProfileStore, create_profile
from integral.offers import Offer, compute_offer_id
from integral.profile import EvidenceLog, ProfileRevision, rebuild
from integral.revision import stale_artefacts

_DIMENSIONS = load_dimensions()
_TEXT = "Buscamos backend. Presencial a Sabadell. Banda 30.000-36.000€."


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", language="en")
    store = ProfileStore(root, identity.handle)
    EvidenceLog(store).append(
        recorded_at="2026-08-22T10:00:00Z",
        step="constraints",
        kind="constraint",
        dimensions=["pay_transparency"],
        text="Floor is firm.",
        source="conversation",
    )
    rebuild(store)
    return store


def _offer() -> Offer:
    return Offer(id=compute_offer_id(_TEXT), source="fixture", text=_TEXT, language="es")


def _facts(offer_id: str) -> OfferFacts:
    return OfferFacts(
        offer_id=offer_id,
        country="ES",
        delivery="onsite",
        region="Vallès Occidental",
        salary_stated=True,
        salary_min=30000,
        salary_max=36000,
        salary_currency="EUR",
    )


def test_no_profile_bytes_appear_in_an_extraction_payload() -> None:
    """The named test: nothing the candidate said reaches an outbound request."""
    constraints = fixture_constraints()
    markers = stated_strings(constraints)
    assert markers, "a fixture with no distinctive strings would prove nothing"

    offer = _offer()
    annotation = annotate(_facts(offer.id), constraints, ProfileRevision(rows=1, sha256="a" * 64))
    assert annotation.readings, "the annotation must actually read the profile"

    payloads = outbound_payloads([offer], _DIMENSIONS)
    assert payloads, "no payload scanned means no measurement"
    assert egress_leaks(payloads, markers) == []


def test_the_egress_check_would_notice_a_planted_leak() -> None:
    """The gate metric cannot pass by having no teeth."""
    markers = stated_strings(fixture_constraints())
    leaked = json.dumps({"text": _TEXT, "candidate_condition": markers[0]})
    assert egress_leaks([leaked], markers) != []


def test_a_marker_json_escaping_would_hide_is_still_found() -> None:
    """JSON escapes quotes, backslashes and newlines; a raw substring scan does not.

    A candidate whose stated condition contains a quote is not exotic — "only for
    a 'staff' role" is an ordinary sentence — and the escaped form of it never
    appears verbatim in the serialised payload.
    """
    marker = 'only for a "staff" role\nnot otherwise'
    payload = json.dumps({"text": _TEXT, "candidate_condition": marker})
    assert marker not in payload, "the fixture must actually be escaped, or it proves nothing"
    assert egress_leaks([payload], [marker]) != []


def test_a_payload_that_does_not_parse_is_still_scanned() -> None:
    """Unparseable is not a reason to stop looking."""
    markers = stated_strings(fixture_constraints())
    assert egress_leaks([f"not json at all {markers[0]}"], markers) != []


def test_annotation_is_recomputed_when_constraints_change(store: ProfileStore) -> None:
    """An annotation is derived: it stamps the revision it was read against."""
    offer = _offer()
    revision = EvidenceLog(store).revision()
    write_annotation(store, annotate(_facts(offer.id), fixture_constraints(), revision))
    assert [entry.artefact for entry in stale_artefacts(store)] == []

    EvidenceLog(store).append(
        recorded_at="2026-08-22T11:00:00Z",
        step="constraints",
        kind="constraint",
        dimensions=["pay_transparency"],
        text="Actually the floor moved.",
        source="conversation",
    )
    stale = [entry.artefact for entry in stale_artefacts(store)]
    assert f"annotations/{offer.id}.json" in stale


def test_extraction_schema_stays_candidate_independent() -> None:
    """An annotation field added to the extraction schema fails validation."""
    with pytest.raises(ValidationError):
        OfferExtraction(
            offer_id="sha256:" + "a" * 64,
            language="es",
            fits_candidate_salary_band=True,  # type: ignore[call-arg]
        )


def test_the_gate_measures_real_adverts() -> None:
    measured = measure()
    assert measured["annotation_profile_egress"] == 0
    # The full sample, not "some": a scan that quietly got smaller still reports
    # zero leaks, and the denominator is half of what this number means.
    assert measured["outbound_payloads_scanned"] == EGRESS_SAMPLE
    assert measured["profile_strings_planted"] > 0
