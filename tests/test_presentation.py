"""T44 — the offer card: a template filled from JSON, never written per offer.

Step 9: *"Presentation is half the specification, not a rendering detail."* Three
rules carry the gate, and each is a way the card can lie:

* **A provisional ranking says so.** L1 ranks on constraints and pay with no
  preference weights. Shown unlabelled it reads as the tool's considered order,
  and `provisional_rankings_unlabelled` is the count of times that happens.
* **Unknown is shown as unknown.** *"An advert silent on hours is not an advert
  promising good ones."* A blank, a dash or a plausible default all read as a
  fact the advert never stated.
* **The card is filled, not generated.** *"Built once, filled fast, never
  assembled a paragraph at a time by a model."* Rendering the same offer twice
  is byte-identical — which is the mechanical form of "no model wrote this".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from integral.explain import explain
from integral.offers import Location, Offer, Salary, compute_offer_id
from integral.presentation import (
    PROVISIONAL_LABEL,
    UNKNOWN,
    card,
    measure,
    provisional_rankings_unlabelled,
    render,
    write_evidence,
)
from integral.profile import ProfileRevision
from integral.rank import Candidate, rank

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


def _offer(text: str = "Desarrollador backend, 100% en remoto.", **kwargs: Any) -> Offer:
    fields: dict[str, Any] = {
        "id": compute_offer_id(text),
        "source": "fixture",
        "title": "Backend engineer",
        "company": "ACME",
        "text": text,
        "language": "es",
    }
    fields.update(kwargs)
    return Offer(**fields)


def _candidate(offer: Offer, salary: float | None, scores: dict[str, float]) -> Candidate:
    return Candidate(
        offer_id=offer.id,
        salary_per_month=salary,
        scores=scores,
        unknown=frozenset(name for name in _DIMENSIONS if name not in scores),
        spans={name: (f"the advert's words for {name}",) for name in scores},
    )


def _ranked(
    candidates: list[Candidate], weights: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    ranking = rank(
        candidates,
        dimensions=_DIMENSIONS,
        revision=ProfileRevision(rows=len(candidates), sha256="0" * 64),
        weights=weights,
        at="2026-08-24T00:00:00Z",
    )
    return ranking, explain(ranking, candidates, weights)


def test_l1_ranking_is_labelled_provisional() -> None:
    offer = _offer()
    ranking, explanations = _ranked([_candidate(offer, 3600.0, {"remote": 1.0})], None)
    page = render(ranking, [offer], explanations=explanations)

    assert ranking["level"] == "L1"
    assert PROVISIONAL_LABEL in page
    assert provisional_rankings_unlabelled([(ranking, page)]) == 0


def test_an_l2_ranking_carries_no_provisional_label() -> None:
    """The label is a claim about this ranking, so it is wrong when untrue."""
    offer = _offer()
    ranking, explanations = _ranked(
        [_candidate(offer, 3600.0, {"remote": 1.0, "commute": -0.5})], _WEIGHTS
    )
    page = render(ranking, [offer], explanations=explanations)

    assert ranking["level"] == "L2"
    assert PROVISIONAL_LABEL not in page


def test_the_label_is_said_once_not_per_card() -> None:
    """Step 9: "in one line, once"."""
    offers = [_offer("Uno, remoto."), _offer("Dos, presencial.")]
    candidates = [
        _candidate(offers[0], 3600.0, {"remote": 1.0}),
        _candidate(offers[1], 3100.0, {"remote": -1.0}),
    ]
    ranking, explanations = _ranked(candidates, None)
    page = render(ranking, offers, explanations=explanations)

    assert page.count(PROVISIONAL_LABEL) == 1


def test_an_unlabelled_provisional_rendering_is_counted() -> None:
    """The measurement has to be able to rise, or it certifies nothing."""
    offer = _offer()
    ranking, _ = _ranked([_candidate(offer, 3600.0, {"remote": 1.0})], None)
    assert provisional_rankings_unlabelled([(ranking, "a page that forgot to say so")]) == 1


def test_unknown_field_renders_as_unknown_not_neutral() -> None:
    """An advert silent on hours is not an advert promising good ones."""
    text = _card(_offer())

    for bullet in ("pay", "hours", "location", "contract"):
        assert bullet in text
    assert text.count(UNKNOWN) >= 3
    assert "0" not in text.split("what matters")[0].replace("100%", "")


def test_a_stated_salary_is_not_shown_as_unknown() -> None:
    offer = _offer(
        salary=Salary(min=42000.0, max=52000.0, currency="EUR", period="year", stated=True)
    )
    assert "42,000 to 52,000" in _card(offer)


def test_an_unstated_salary_is_unknown_even_when_a_number_is_present() -> None:
    """§5.2: `stated` distinguishes absent from zero. An estimate is not a claim
    the employer made, and a card that shows it as one launders a guess."""
    offer = _offer(salary=Salary(min=42000.0, currency="EUR", period="year", stated=False))
    assert "42,000" not in _card(offer)
    assert UNKNOWN in _card(offer)


def test_card_is_filled_from_json_not_generated_per_offer() -> None:
    """Rendering the same offer twice is byte-identical."""
    offer = _offer(location=Location(raw="Barcelona", country="ES", remote="full"))
    assert _card(offer) == _card(offer)


def test_the_whole_page_is_byte_identical_across_renderings() -> None:
    offers = [_offer("Uno, remoto."), _offer("Dos, presencial.")]
    candidates = [
        _candidate(offers[0], 3600.0, {"remote": 1.0, "commute": 0.5}),
        _candidate(offers[1], 4200.0, {"remote": -1.0, "commute": -0.5}),
    ]
    ranking, explanations = _ranked(candidates, _WEIGHTS)
    assert render(ranking, offers, explanations=explanations) == render(
        ranking, offers, explanations=explanations
    )


def test_the_one_line_includes_the_bad_part() -> None:
    """ "full remote, pay is good, but it is a gun factory." The line a candidate
    reads is not allowed to be the good half of the account."""
    offer = _offer()
    ranking, explanations = _ranked(
        [_candidate(offer, 3600.0, {"remote": 1.0, "commute": -0.8})], _WEIGHTS
    )
    page = render(ranking, [offer], explanations=explanations)

    assert "but" in page
    assert "the advert's words for commute" in page
    assert "the advert's words for remote" in page


def test_the_line_leads_with_the_offer_not_a_score() -> None:
    """Step 9: "Lead with the offer and the one thing that most moved it, never
    with a score"."""
    offer = _offer()
    ranking, explanations = _ranked([_candidate(offer, 3600.0, {"remote": 1.0})], _WEIGHTS)
    page = render(ranking, [offer], explanations=explanations)

    first = next(
        line for line in page.splitlines() if line.strip() and PROVISIONAL_LABEL not in line
    )
    assert first.startswith("Backend engineer")


def test_a_handful_at_a_time_not_forty() -> None:
    offers = [_offer(f"Oferta {n}, remoto.") for n in range(12)]
    candidates = [_candidate(offer, 3000.0 + n, {"remote": 1.0}) for n, offer in enumerate(offers)]
    ranking, explanations = _ranked(candidates, None)
    page = render(ranking, offers, explanations=explanations, limit=5)

    assert page.count("Backend engineer") == 5
    assert "7 more" in page


def test_an_offer_on_the_frontier_with_no_record_is_refused() -> None:
    offer = _offer()
    ranking, explanations = _ranked([_candidate(offer, 3600.0, {"remote": 1.0})], None)
    try:
        render(ranking, [], explanations=explanations)
    except KeyError:
        return
    raise AssertionError("rendering a frontier offer nobody supplied should not quietly succeed")


def test_measure_proves_the_count_can_rise() -> None:
    measured = measure()
    assert measured["provisional_rankings_unlabelled"] == 0
    assert measured["unlabelled_detected_when_planted"] == 1


def test_write_evidence_records_the_gate_key(tmp_path: Path) -> None:
    evidence = tmp_path / "T44.json"
    write_evidence(evidence)
    assert json.loads(evidence.read_text(encoding="utf-8"))["provisional_rankings_unlabelled"] == 0


def _card(offer: Offer) -> str:
    return card(offer, explanation=None, net=None)
