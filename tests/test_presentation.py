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

import pytest

from integral import presentation
from integral.explain import explain
from integral.offers import Location, Offer, Salary, compute_offer_id
from integral.presentation import _FIXTURE_WEIGHTS as _FIXTURE_WEIGHTS_FOR_TEST
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


def test_a_missing_offer_beyond_the_page_limit_is_still_refused() -> None:
    """Validating only the slice would make the check depend on `limit`: an
    offer missing at position six of five renders "(1 more not shown.)" and the
    page reads as complete."""
    offers = [_offer(f"Oferta {n}, remoto.") for n in range(8)]
    candidates = [_candidate(offer, 3000.0 + n, {"remote": 1.0}) for n, offer in enumerate(offers)]
    ranking, explanations = _ranked(candidates, None)

    beyond = ranking["pareto"][-1]
    supplied = [offer for offer in offers if offer.id != beyond]
    try:
        render(ranking, supplied, explanations=explanations, limit=3)
    except KeyError as exc:
        assert beyond in str(exc)
        return
    raise AssertionError("a frontier offer nobody supplied should not vanish behind the limit")


def test_the_cli_fails_when_a_stated_bullet_stops_showing_its_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A recorded number nothing asserts is a gate that measures nothing."""
    from integral import presentation

    measured = presentation.measure()
    assert measured["stated_bullets_render_their_value"] == 1
    assert measured["unstated_bullets_render_unknown"] == 1

    monkeypatch.setattr(
        presentation, "measure", lambda: {**measured, "unstated_bullets_render_unknown": 0}
    )
    assert presentation._main([str(tmp_path / "T44.json")]) == 1


def test_the_unknown_property_is_read_per_field_not_page_wide() -> None:
    """`hours` and `contract` are unconditionally unknown, so a page-wide search
    for the word is true whatever the salary and location cells do."""
    from integral.presentation import _bullet, _page

    _, page = _page(_FIXTURE_WEIGHTS_FOR_TEST)
    assert _bullet(page, "hours", 0) == UNKNOWN
    assert _bullet(page, "pay", 0) != UNKNOWN
    assert _bullet(page, "pay", 1) == UNKNOWN


def test_a_label_appearing_inside_a_card_does_not_count_as_the_header() -> None:
    """A page whose header is missing but whose card text happens to contain the
    sentence would otherwise report as labelled."""
    offer = _offer()
    ranking, _ = _ranked([_candidate(offer, 3600.0, {"remote": 1.0})], None)
    smuggled = f"Backend engineer — ACME\n  note: {PROVISIONAL_LABEL}\n"

    assert provisional_rankings_unlabelled([(ranking, smuggled)]) == 1


def test_a_negative_limit_is_refused() -> None:
    """`frontier[:-1]` drops the last offer and reports "0 more not shown"."""
    offer = _offer()
    ranking, explanations = _ranked([_candidate(offer, 3600.0, {"remote": 1.0})], None)
    with pytest.raises(ValueError):
        render(ranking, [offer], explanations=explanations, limit=-1)


# ---------------------------------------------------------------------------
# D-17 — a ranked offer carries its link
#
# Captured at step `ranking` in test session `test-2026-08-20-a`: *"you didn't
# give links to real offers, so it is not clear what to do with that info."*
# Seven offers were shown with title, employer, pay and a verbatim citation and
# no link, while every stored record already carried `url` and `source_ref`.
# The card dropped a field the store had — so the rule is the same one the other
# bullets follow: render it, and when it is absent say so.


def test_every_ranked_offer_renders_its_url() -> None:
    offer = _offer(url="https://example.invalid/offers/1")
    assert "https://example.invalid/offers/1" in _card(offer)


def test_an_offer_with_no_url_shows_the_absence() -> None:
    """A missing row reads as "there was nothing to show"; the candidate cannot
    tell it apart from a card that has no link field at all."""
    text = _card(Offer(id=compute_offer_id("sin enlace"), source="fixture", text="sin enlace"))
    assert "link:" in text
    assert UNKNOWN in text.split("link:")[1].split("\n")[0]


def test_the_url_row_is_present_on_every_card_in_a_page() -> None:
    offers = [_offer("Uno, remoto.", url="https://example.invalid/1"), _offer("Dos, presencial.")]
    candidates = [
        _candidate(offers[0], 3600.0, {"remote": 1.0}),
        _candidate(offers[1], 3100.0, {"remote": -1.0}),
    ]
    ranking, explanations = _ranked(candidates, None)
    page = render(ranking, offers, explanations=explanations)

    assert page.count("link:") == 2
    assert "https://example.invalid/1" in page


def test_a_dropped_url_is_counted_in_the_evidence() -> None:
    """D-17 is a presentation defect that was invisible because nothing counted
    it. The number goes in the gate evidence so a regression is visible."""
    assert measure()["ranked_offers_without_a_url"] == 0
    assert measure()["offers_with_no_url_in_the_store"] == 1


def test_a_dominated_offer_is_not_counted_as_a_dropped_url() -> None:
    """It has no card by design. Counting it would report the frontier working
    as if it were this bug."""
    from integral.presentation import _fixture, _urls_dropped

    offers, _ = _fixture()
    assert any(offer.url for offer in offers)
    assert _urls_dropped(limit=1) == 0


# ---------------------------------------------------------------------------
# T87 — the Excluded section on the page


def _t87() -> tuple[dict[str, Any], str]:
    return presentation._t87_page()


def test_an_excluded_offer_appears_on_the_page_with_its_quote() -> None:
    """Shown, never silently dropped — and shown with the advert's own sentence.

    T79 removed the offer and recorded the wording; until this section existed
    the candidate saw neither, so a barred offer and an offer that was never
    found looked identical from where they sit.
    """
    ranking, page = _t87()

    assert f"{presentation.EXCLUDED_HEADING} (2)" in page
    for entry in ranking["excluded"]:
        assert entry["quote"] in page, f"{entry['quote']!r} was excluded for but never shown"
        assert str(entry["reason"]) in page


def test_an_excluded_offer_gets_no_card() -> None:
    """Listed as excluded, not rendered as an offer the candidate might take.
    The link is the test: a card carries it and the Excluded line does not."""
    ranking, page = _t87()
    offers, _, _ = presentation._t87_fixture()
    by_id = {offer.id: offer for offer in offers}

    for entry in ranking["excluded"]:
        offer = by_id[entry["offer_id"]]
        assert offer.url is not None
        assert offer.url not in page, "an excluded offer was rendered as an applyable card"


def test_a_flagged_offer_is_carded_with_its_marker() -> None:
    """Spec §5.4: ranked, marked, and the human is the tiebreaker. T79 did the
    ranking; the marking is the card's."""
    ranking, page = _t87()

    assert len(ranking["flagged"]) == 1
    assert presentation.FLAG_MARKER in page
    # The marker qualifies one card, not the page: the offer that states
    # nothing must not inherit it.
    assert page.count(presentation.FLAG_MARKER) == 1


def test_the_page_reports_the_excluded_count_even_when_the_list_is_long() -> None:
    """The count is stated, not implied by the length of a list that `limit`
    may have cut. Cards are truncated because the candidate wants the best few;
    exclusions are the opposite case, and cutting them would reintroduce the
    silence the section exists to close."""
    ranking, page = presentation._t87_page(limit=1)

    assert "(1 more not shown.)" in page, "the fixture must actually truncate the cards"
    assert f"{presentation.EXCLUDED_HEADING} (2)" in page
    for entry in ranking["excluded"]:
        assert entry["quote"] in page, "an exclusion was cut by the card limit"


def test_an_exclusion_with_no_reason_is_shown_as_a_defect_not_omitted() -> None:
    """The one case the gate counts. Dropping the line would make the page look
    correct while the candidate lost an offer for wording nobody recorded."""
    offers, _, _ = presentation._t87_fixture()
    block = presentation._excluded_block(
        [{"offer_id": offers[0].id, "reason": "citizenship", "quote": None}],
        {offer.id: offer for offer in offers},
    )

    assert presentation.NO_REASON_GIVEN in block
    assert offers[0].title is not None
    assert offers[0].title in block


def test_the_gate_does_not_pass_on_an_empty_input_set() -> None:
    """A count of zero over nothing excluded is not a pass. The denominator is
    asserted, and the negative control proves the count rises when the section
    is taken off the page."""
    measured = presentation.measure_exclusions_shown()

    assert measured["excluded_offers_missing_from_the_page_evaluated"] > 0
    assert measured["gate_status"] == "measured"
    assert measured["excluded_offers_missing_from_the_page"] == 0
    assert measured["missing_detected_when_the_section_is_removed"] == 1
    assert measured["flagged_offers_marked"] == measured["flagged_offers_evaluated"] > 0


def test_the_stated_excluded_count_is_the_number_actually_on_the_page() -> None:
    """`excluded_count_stated_on_the_page` is read off the heading, not a
    boolean flag in disguise — a `1` next to two exclusions would look like a
    passing check while stating the wrong number."""
    ranking, _ = _t87()
    measured = presentation.measure_exclusions_shown()

    assert measured["excluded_count_stated_on_the_page"] == len(ranking["excluded"]) == 2


def test_a_page_wide_quote_search_misses_a_dropped_exclusion_line() -> None:
    """Two exclusions sharing a quote must each be checked against its own
    rendered line. A page-wide search for the quote alone is satisfied by
    either line and would report zero missing while one entry was never
    shown."""
    offers, _, _ = presentation._t87_fixture()
    by_id = {offer.id: offer for offer in offers}
    shared_quote = "must hold German citizenship"
    entries = [
        {"offer_id": offers[0].id, "reason": "citizenship", "quote": shared_quote},
        {"offer_id": offers[1].id, "reason": "citizenship", "quote": shared_quote},
    ]
    ranking = {"excluded": entries}
    # Only the first entry's line is on the page; the second was dropped. The
    # shared quote text is still present, which is exactly what would fool a
    # substring-only check.
    page = presentation._excluded_line(entries[0], by_id)
    assert shared_quote in page

    assert presentation.excluded_offers_missing_from_the_page([(ranking, page, by_id)]) == 1


def test_two_exclusions_with_the_byte_identical_line_are_each_counted() -> None:
    """Two entries can render the *exact same* line — same name, same reason,
    same quote, from two different offers whose titles happen to coincide.
    `in` only asks whether the line appears at all: one rendered copy would
    satisfy both entries and a dropped second exclusion would go uncounted.
    `page.count(line)` against how many entries expect it is what catches a
    second copy that never made it onto the page."""
    offers, _, _ = presentation._t87_fixture()
    same_titled = offers[1].model_copy(update={"title": offers[0].title})
    by_id = {offers[0].id: offers[0], offers[1].id: same_titled}
    quote = "must hold German citizenship"
    entries = [
        {"offer_id": offers[0].id, "reason": "citizenship", "quote": quote},
        {"offer_id": offers[1].id, "reason": "citizenship", "quote": quote},
    ]
    ranking = {"excluded": entries}
    line = presentation._excluded_line(entries[0], by_id)
    assert presentation._excluded_line(entries[1], by_id) == line, "the two lines must be identical"

    # Only one copy of the (identical) line is on the page — the second
    # exclusion was dropped, and a bare `in` check would miss that.
    page = line
    assert presentation.excluded_offers_missing_from_the_page([(ranking, page, by_id)]) == 1

    # Both copies present: nothing missing.
    page_with_both = f"{line}\n{line}"
    missing_with_both = presentation.excluded_offers_missing_from_the_page(
        [(ranking, page_with_both, by_id)]
    )
    assert missing_with_both == 0


def test_a_page_wide_marker_search_misses_an_unmarked_flagged_card() -> None:
    """Two flagged offers must each be checked against its own rendered card.
    A page-wide search for the marker text is satisfied by either card and
    would report both marked while one carries no marker at all."""
    offers, _, _ = presentation._t87_fixture()
    marked_card = card(offers[0], flagged=True)
    unmarked_card = card(offers[1], flagged=False)
    page = f"{marked_card}\n{unmarked_card}"

    # The bug this guards against: the marker appears once, so a page-wide
    # `FLAG_MARKER in page` check reads as "marked" for every flagged offer.
    assert presentation.FLAG_MARKER in page

    # The fix: check containment of each offer's own re-rendered card.
    assert card(offers[0], flagged=True) in page
    assert card(offers[1], flagged=True) not in page
