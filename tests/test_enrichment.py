"""T43 — what is learned outside the advert, and never quoted as the employer.

Plenty of adverts are four lines and a salary band. When extraction yields very
little, step 8 may look outside — what the company does, how it is spoken about,
what former employees say — and add what it finds.

**The rule that matters**: nothing sourced outside the advert ever appears as a
verbatim evidence span. `explained_fraction` means the employer's own words, and
an explanation citing a review site as though the employer had written it is a
lie about provenance — the kind that is invisible until the candidate quotes it
back in an interview and the room goes quiet.

So the gate, `outside_source_spans_in_explanations == 0`, is not about whether
enrichment is labelled on screen. It is about whether an outside sentence can
reach the one place in the system that means "the advert says this".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from integral.decline import DeclineLedger
from integral.enrichment import (
    LOOKUP_KEY,
    NOT_FROM_THE_ADVERT,
    EnrichmentError,
    OutsideFinding,
    enrich,
    lookups_allowed,
    measure,
    outside_source_spans,
    write_evidence,
)
from integral.explain import explain
from integral.identity import ProfileStore, create_profile
from integral.offers import Offer, compute_offer_id
from integral.presentation import card, render
from integral.profile import ProfileRevision
from integral.rank import Candidate, rank

_AT = "2026-08-24T10:00:00Z"
_DIMENSIONS = ("commute", "remote")
_WEIGHTS: dict[str, Any] = {
    "currency": "EUR",
    "part_worths": {
        "commute": {"utility_per_unit": 0.30, "salary_equivalent_per_month": 200.0},
        "remote": {"utility_per_unit": 0.90, "salary_equivalent_per_month": 600.0},
    },
    "negligible": [],
    "separated": False,
    "salary_utility_per_month": 0.0015,
}


def _store(tmp_path: Path) -> ProfileStore:
    identity = create_profile(tmp_path, "Candidate", handle="candidate")
    return ProfileStore(tmp_path, identity.handle)


def _thin_offer() -> Offer:
    text = "Backend. Barcelona. 40.000€."
    return Offer(id=compute_offer_id(text), source="fixture", title="Backend", text=text)


def _finding(text: str = "Antiguos empleados mencionan guardias frecuentes.") -> OutsideFinding:
    return OutsideFinding(
        dimension="on_call_load",
        text=text,
        source="review_site",
        source_ref="https://example.invalid/reviews/acme",
        looked_up_at=_AT,
    )


def _finder(offer: Offer, dimensions: tuple[str, ...]) -> list[OutsideFinding]:
    return [_finding()]


def test_outside_information_is_marked_not_from_the_advert(tmp_path: Path) -> None:
    """The named test. A finding is a different type from a `DimensionScore`,
    and it says so wherever it is rendered."""
    store = _store(tmp_path)
    findings = enrich(_thin_offer(), _DIMENSIONS, store=store, finder=_finder, at=_AT)

    assert findings
    for finding in findings:
        assert finding.from_advert is False
        assert NOT_FROM_THE_ADVERT in finding.label()
        assert finding.source_ref in finding.label()


def test_an_explanation_never_cites_an_outside_source_as_the_employer() -> None:
    """The gate. An outside sentence reaching `evidence_span` is the failure."""
    quote = "Antiguos empleados mencionan guardias frecuentes."
    honest = Candidate(
        offer_id="sha256:" + "1" * 64,
        salary_per_month=3600.0,
        scores={"remote": 1.0, "commute": 0.5},
        spans={"remote": ("100% en remoto",), "commute": ("junto a la estación",)},
    )
    ranking = rank(
        [honest],
        dimensions=_DIMENSIONS,
        revision=ProfileRevision(rows=1, sha256="0" * 64),
        weights=_WEIGHTS,
        at=_AT,
    )
    explanations = explain(ranking, [honest], _WEIGHTS)

    assert outside_source_spans(explanations, [_finding(quote)]) == []


def test_an_outside_sentence_reaching_a_span_is_counted() -> None:
    """The measurement has to be able to rise, or it certifies nothing."""
    quote = "Antiguos empleados mencionan guardias frecuentes."
    leaked = Candidate(
        offer_id="sha256:" + "2" * 64,
        salary_per_month=3600.0,
        scores={"remote": 1.0, "commute": 0.5},
        spans={"remote": (quote,), "commute": ("junto a la estación",)},
    )
    ranking = rank(
        [leaked],
        dimensions=_DIMENSIONS,
        revision=ProfileRevision(rows=1, sha256="0" * 64),
        weights=_WEIGHTS,
        at=_AT,
    )
    explanations = explain(ranking, [leaked], _WEIGHTS)

    violations = outside_source_spans(explanations, [_finding(quote)])
    assert len(violations) == 1
    assert "review_site" in violations[0]


def test_lookup_is_skipped_when_the_candidate_declined_it(tmp_path: Path) -> None:
    """A standing preference, not a per-offer prompt."""
    store = _store(tmp_path)
    DeclineLedger(store).decline(LOOKUP_KEY, step="understanding", at=_AT)

    assert lookups_allowed(store) is False
    assert enrich(_thin_offer(), _DIMENSIONS, store=store, finder=_finder, at=_AT) == []


def test_a_declined_lookup_calls_no_finder(tmp_path: Path) -> None:
    """Skipped means not performed. Filtering afterwards would still have sent
    the employer's name to whatever the finder talks to."""
    store = _store(tmp_path)
    DeclineLedger(store).decline(LOOKUP_KEY, step="understanding", at=_AT)
    called: list[str] = []

    def spy(offer: Offer, dimensions: tuple[str, ...]) -> list[OutsideFinding]:
        called.append(offer.id)
        return [_finding()]

    enrich(_thin_offer(), _DIMENSIONS, store=store, finder=spy, at=_AT)
    assert called == []


def test_lookups_are_allowed_by_default(tmp_path: Path) -> None:
    assert lookups_allowed(_store(tmp_path)) is True


def test_a_finding_with_no_source_reference_is_refused() -> None:
    """ "What former employees say" with no link is a rumour the tool made
    checkable-looking by putting it in a field."""
    with pytest.raises(EnrichmentError):
        OutsideFinding(
            dimension="on_call_load",
            text="Se dice que hay guardias.",
            source="review_site",
            source_ref="  ",
            looked_up_at=_AT,
        )


def test_a_finding_with_blank_text_is_refused() -> None:
    with pytest.raises(EnrichmentError):
        OutsideFinding(
            dimension="on_call_load",
            text="   ",
            source="review_site",
            source_ref="https://example.invalid/x",
            looked_up_at=_AT,
        )


def test_a_finding_with_a_blank_source_is_refused() -> None:
    """A reference nobody is answerable for. `source_ref` was already refused
    for the same reason; the source is the other half of the attribution, and
    without it `cite()` renders "[: https://...]"."""
    with pytest.raises(EnrichmentError):
        OutsideFinding(
            dimension="on_call_load",
            text="Antiguos empleados mencionan guardias frecuentes.",
            source="   ",
            source_ref="https://example.invalid/x",
            looked_up_at=_AT,
        )


def test_the_page_shows_what_was_learned_outside_the_advert() -> None:
    """The candidate reads the page, not a bare card. Before this, `card` could
    render the block and `render` could not pass one, so the only way to see a
    finding was to call `card` yourself."""
    offer = _thin_offer()
    ranking = {"level": "L2", "pareto": [offer.id]}

    page = render(ranking, [offer], explanations={}, outside={offer.id: [_finding()]})

    assert NOT_FROM_THE_ADVERT.capitalize() in page
    assert "guardias frecuentes" in page
    # A finding is about one employer: another offer's card must not carry it.
    assert NOT_FROM_THE_ADVERT.capitalize() not in render(
        ranking, [offer], explanations={}, outside={"some-other-offer": [_finding()]}
    )


def test_the_card_shows_which_is_which() -> None:
    """The candidate sees the difference, not just the schema."""
    rendered = card(_thin_offer(), explanation=None, outside=[_finding()])

    assert NOT_FROM_THE_ADVERT.capitalize() in rendered
    assert "review_site" in rendered
    assert "guardias frecuentes" in rendered


def test_a_card_with_no_outside_findings_says_nothing_about_them() -> None:
    """An empty "not from the advert" heading reads as a lookup that found
    nothing, which is a different claim from one that never ran."""
    assert NOT_FROM_THE_ADVERT.capitalize() not in card(_thin_offer(), explanation=None)


def test_measure_proves_the_count_can_rise() -> None:
    measured = measure()
    assert measured["outside_source_spans_in_explanations"] == 0
    assert measured["leak_detected_when_planted"] == 1


def test_write_evidence_records_the_gate_key(tmp_path: Path) -> None:
    evidence = tmp_path / "T43.json"
    write_evidence(evidence)
    key = "outside_source_spans_in_explanations"
    assert json.loads(evidence.read_text(encoding="utf-8"))[key] == 0
