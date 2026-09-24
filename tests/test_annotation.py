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

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast, get_args, get_type_hints

import pytest
from pydantic import ValidationError

import integral.annotation as annotation_module
from integral.annotation import (
    EGRESS_SAMPLE,
    Annotation,
    annotate,
    egress_leaks,
    fixture_constraints,
    measure,
    outbound_payloads,
    stated_strings,
    write_annotation,
)
from integral.candidate import CandidateConstraints, HardFilterResult, OfferFacts
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


@pytest.mark.parametrize(
    "marker",
    [
        pytest.param('only for a "staff" role\nnot otherwise', id="quote-and-newline"),
        pytest.param(r"C:\Users\ada\constraints", id="backslash"),
    ],
)
@pytest.mark.parametrize("position", ["value", "key"])
def test_a_marker_json_escaping_would_hide_is_still_found(marker: str, position: str) -> None:
    """JSON escapes quotes, backslashes and newlines; a raw substring scan does not.

    A candidate whose stated condition contains a quote is not exotic — "only for
    a 'staff' role" is an ordinary sentence — and the escaped form of it never
    appears verbatim in the serialised payload. Keys are scanned as well as
    values, because a payload that carried the candidate's own words as a field
    name would leak them just as completely.
    """
    body = {marker: True} if position == "key" else {"candidate_condition": marker}
    payload = json.dumps({"text": _TEXT, **body})
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


# ---------------------------------------------------------------------------
# `kept` and the readings are one statement about an offer, not two
#
# `annotate()` derives `kept` from `HardFilterResult.surviving` and the
# per-field readings from `HardFilterResult.removed`. Those are two different
# buckets, so an offer that is in neither leaves the two halves describing
# different offers: `kept=False` beside a full set of readings that all say
# "satisfied". Nothing pinned that agreement until these two tests.


def _kept_facts(offer_id: str) -> OfferFacts:
    """An offer `fixture_constraints()` keeps.

    Remote, so the stated location has nothing to compare against, and paying
    over the stated floor of 42000 EUR.
    """
    return OfferFacts(
        offer_id=offer_id,
        country="ES",
        delivery="remote",
        salary_stated=True,
        salary_min=50000,
        salary_max=60000,
        salary_currency="EUR",
    )


def _unsatisfied_stated(annotation: Annotation, constraints: CandidateConstraints) -> list[str]:
    """The **stated** fields this annotation does not report as satisfied.

    Restricted to stated fields on purpose. `unknown` is what a field the
    candidate never answered reads, and `filter_hard_constraints` skips those
    entirely — so an `unknown` reading can never be the reason an offer was
    dropped, and counting it as one would let a contradiction hide behind the
    six fields `fixture_constraints()` leaves unanswered. That is not
    hypothetical: it is what this helper was written to fix, after the twin
    below reported green over a deliberately added fourth bucket.

    Any verdict but `satisfied` counts, rather than `violated` alone, so a
    literal added later (T201's `unplaced`) explains a drop without this test
    having to learn its name.

    A **missing** reading fails outright rather than counting as unsatisfied.
    Filtering `reading.field in stated` judges the readings that happen to
    exist, which is a proxy for the property and not the property: a field
    `annotate()` stopped emitting would pass every check below by not being
    there, and the dropped case would pass for the wrong reason. Raised as a
    finding by CodeRabbit on this PR, and it is the same shape as the defect
    these tests exist to catch — a check defeated by the absence of the thing
    it reads, one level up.
    """
    stated = {name for name, value in constraints.as_dict().items() if value.state == "stated"}
    read = {reading.field: reading.verdict for reading in annotation.readings}
    missing = sorted(stated - set(read))
    assert not missing, f"the annotation carries no reading at all for stated field(s): {missing}"
    return [field for field in sorted(stated) if read[field] != "satisfied"]


@pytest.mark.parametrize(
    ("facts", "expect_kept"),
    [(_kept_facts("kept-offer"), True), (_facts("dropped-offer"), False)],
    ids=["kept", "dropped"],
)
def test_kept_and_the_readings_never_disagree(
    store: ProfileStore, facts: OfferFacts, expect_kept: bool
) -> None:
    """A dropped offer must name a field that dropped it, and a kept one none."""
    constraints = fixture_constraints()
    annotation = annotate(facts, constraints, EvidenceLog(store).revision())
    unsatisfied = _unsatisfied_stated(annotation, constraints)

    assert annotation.kept is expect_kept
    if expect_kept:
        assert unsatisfied == [], f"kept, yet these stated fields did not pass: {unsatisfied}"
    else:
        assert unsatisfied != [], "not kept, yet every stated field reads satisfied"


# `outstanding_fields` names constraint fields the candidate has not answered,
# never offers, so it is the one bucket the twin below leaves alone. It is
# excluded **by name** rather than by type — `surviving` is a `tuple[str, ...]`
# too, so a type test could not tell them apart — which means any bucket added
# later is treated as offer-bearing by default. That is the fail-safe
# direction, and the whole point of deriving the list instead of writing it:
# a new bucket is varied without anyone remembering to come back here.
_NOT_A_BUCKET_OF_OFFERS = frozenset({"outstanding_fields"})


def _bucket_holding(name: str, offer_id: str, violated_field: str) -> tuple[Any, ...]:
    """One bucket's value, carrying `offer_id` and nothing else.

    Handles the two element shapes `HardFilterResult` uses — a bare offer id,
    and a dataclass carrying one — so a future bucket of either shape needs no
    change here.
    """
    element = get_args(get_type_hints(HardFilterResult)[name])[0]
    if element is str:
        return (offer_id,)
    if dataclasses.is_dataclass(element):
        # `is_dataclass` narrows to `DataclassInstance`, which mypy will not
        # call; the twin is constructing the type, not copying an instance.
        build = cast("Callable[..., Any]", element)
        return (
            build(
                **{
                    member.name: offer_id
                    if member.name == "offer_id"
                    # A real bucket entry names a real constraint field; a
                    # placeholder here would produce no reading and make the
                    # assertion below fail for the wrong reason.
                    else violated_field
                    if member.name == "field"
                    else f"a synthetic {member.name}"
                    for member in dataclasses.fields(element)
                }
            ),
        )
    raise AssertionError(f"`{name}` holds {element!r}, which this twin cannot build")


def test_every_bucket_of_the_filter_reaches_the_annotation(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An offer in a bucket `annotate()` does not read makes it contradict itself.

    Derived from `dataclasses.fields(HardFilterResult)` rather than from the
    buckets that exist today, so T201's proposed `unplaced` — an offer whose
    location cannot be compared because the advert states no region — is varied
    here the day it lands. `annotate()` reads `surviving` and `removed` only,
    so such an offer would fall out `kept=False` with every field still reading
    "satisfied": exactly what the test above forbids, and invisible without
    this one, because a bucket nothing constructs is a bucket nothing tests.
    """
    constraints = fixture_constraints()
    stated = [name for name, value in constraints.as_dict().items() if value.state == "stated"]
    assert stated, "the twin needs a stated field for a bucket entry to name"
    facts = _kept_facts("bucketed-offer")

    buckets = [
        field.name
        for field in dataclasses.fields(HardFilterResult)
        if field.name not in _NOT_A_BUCKET_OF_OFFERS
    ]
    assert len(buckets) >= 2, f"the twin is varying almost nothing: {buckets}"

    for bucket in buckets:
        result = HardFilterResult(
            **{
                **{field.name: () for field in dataclasses.fields(HardFilterResult)},
                bucket: _bucket_holding(bucket, facts.offer_id, stated[0]),
            }
        )
        monkeypatch.setattr(annotation_module, "filter_hard_constraints", lambda *_, _r=result: _r)
        produced = annotate(facts, constraints, EvidenceLog(store).revision())

        if bucket == "surviving":
            assert produced.kept is True, "an offer in `surviving` is not kept"
            continue

        assert produced.kept is False, f"an offer only in `{bucket}` was kept"
        assert _unsatisfied_stated(produced, constraints) != [], (
            f"an offer in `{bucket}` is not kept, yet every stated field still "
            f'reads "satisfied" — `annotate()` does not consult that bucket'
        )


def test_an_unplaceable_offer_reads_unplaced_rather_than_satisfied(store: ProfileStore) -> None:
    """The reading says the advert did not say, not that it said nothing wrong.

    `kept=False` beside a `"satisfied"` location reading is the contradiction
    the invariant above forbids, and `"satisfied"` is also the wrong sentence
    on its own terms: the filter did not clear this advert, it failed to place
    it. The verdict is a fourth literal rather than `"unknown"` because the
    two name different silent parties and owe different next steps — `unknown`
    is a question for the candidate, `unplaced` is a gap in the advert.
    """
    facts = _kept_facts("unplaceable").model_copy(update={"delivery": "onsite", "region": None})
    constraints = fixture_constraints()
    assert constraints.location.commutable_regions, "the fixture must state a radius to compare"

    annotation = annotate(facts, constraints, EvidenceLog(store).revision())
    location = next(r for r in annotation.readings if r.field == "location")

    assert annotation.kept is False
    assert location.verdict == "unplaced"
    assert "states no region" in location.because
    # Not a violation: the advert broke nothing, and reporting it as a breach
    # would be the over-rejection #547 measured, moved one layer up.
    assert [r.field for r in annotation.readings if r.verdict == "violated"] == []


def test_unplaced_is_not_spent_on_an_advert_that_states_its_region(store: ProfileStore) -> None:
    """The control: the new verdict must not have swallowed the comparison.

    A `_read_field` that returned `"unplaced"` for every on-site advert would
    pass the test above and mean nothing.
    """
    region = fixture_constraints().location.commutable_regions[0]
    facts = _kept_facts("placed").model_copy(update={"delivery": "onsite", "region": region})

    annotation = annotate(facts, fixture_constraints(), EvidenceLog(store).revision())
    location = next(r for r in annotation.readings if r.field == "location")

    assert annotation.kept is True
    assert location.verdict == "satisfied"
