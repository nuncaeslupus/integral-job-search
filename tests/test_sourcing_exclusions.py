"""T90 — a constraint the candidate stated is not applied to the next search.

Written RED before `integral.sourcing_exclusions` existed, per the task
payload. The case is the live session of 2026-08-30: fintech, e-commerce,
frontend and cloud were each ruled out in words, twice, and each kept
arriving. The candidate's own diagnosis was the right question —

    Did you search for the ads all together at the beginning or are you
    adding filters with everything I'm telling you?

— and from the outside those two designs are indistinguishable until
something ruled out comes back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral import sourcing_exclusions as se
from integral.sourcing_exclusions import (
    Exclusion,
    Override,
    Presentation,
    SearchQuery,
    excluded_terms,
    matches,
    next_query,
    resurfaced,
)


def _offer(text: str, offer_id: str = "a") -> se.Candidate:
    return se.Candidate(offer_id=offer_id, title=text, text=text)


_FINTECH = Exclusion(about="sector:fintech", stated_at_cycle=2, words="fintech no me interesa")
_FRONTEND = Exclusion(about="role:frontend", stated_at_cycle=3, words="frontend tampoco")


def test_an_exclusion_stated_at_cycle_n_shapes_the_query_at_cycle_n_plus_1() -> None:
    """The whole task. A rank penalty is applied after offers are fetched; an
    exclusion has to reach the request, and those are different code paths."""
    cycle_two = SearchQuery(cycle=2, terms=("data engineer",), excluded=())

    cycle_three = next_query(cycle_two, [_FINTECH])

    assert cycle_three.cycle == 3
    assert "sector:fintech" in cycle_three.excluded
    assert cycle_three.terms == cycle_two.terms
    # And it is in the request the connector is handed, not only in a field
    # some later ranking step might read.
    assert "fintech" in excluded_terms(cycle_three)


def test_an_exclusion_survives_every_later_cycle_until_it_is_lifted() -> None:
    """Twice more, frontend and cloud. An exclusion that has to be restated
    every cycle is the bug wearing the fix's clothes."""
    query = SearchQuery(cycle=1, terms=("data engineer",), excluded=())
    for exclusion in (_FINTECH, _FRONTEND):
        query = next_query(query, [exclusion])
    query = next_query(query, [])

    assert set(query.excluded) == {"sector:fintech", "role:frontend"}


def test_a_penalised_offer_still_counts_as_resurfaced() -> None:
    """`weights.py` can push a fintech advert down and it still appears, which
    is the observed behaviour and reads as not listening. A demotion is not an
    exclusion — the candidate still saw it."""
    demoted = Presentation(
        candidate=_offer("Senior Data Engineer, fintech scale-up"),
        rank=97,
        penalty_applied=True,
    )

    found = resurfaced([demoted], [_FINTECH], cycle=4)

    assert [r.about for r in found] == ["sector:fintech"]
    assert found[0].penalty_applied is True


def test_an_exclusion_overridden_by_a_strong_match_is_named_not_silent() -> None:
    """A sector distaste is soft: it must not silently delete a role that is
    otherwise a strong match. So the escape hatch exists — and it is always
    visible, which is the half that makes it an escape rather than a leak."""
    shown = Presentation(
        candidate=_offer("Staff Data Engineer, fintech", offer_id="b"),
        rank=1,
        override=Override(
            about="sector:fintech",
            reason="salario un 40% por encima de tu suelo y 100% remoto",
        ),
    )

    assert resurfaced([shown], [_FINTECH], cycle=4) == []
    assert "fintech" in shown.say()
    assert "40%" in shown.say()


def test_an_override_with_no_reason_is_not_an_override() -> None:
    """An override the candidate cannot read is the silent resurfacing with
    an extra field attached."""
    with pytest.raises(ValueError):
        Override(about="sector:fintech", reason="   ")


def test_an_override_for_a_different_exclusion_does_not_cover_this_one() -> None:
    """Naming the cloud override does not license the fintech advert."""
    shown = Presentation(
        candidate=_offer("Cloud Platform Engineer at a fintech", offer_id="c"),
        rank=2,
        override=Override(about="stack:cloud", reason="es el único rol senior de la semana"),
    )

    assert [r.about for r in resurfaced([shown], [_FINTECH], cycle=4)] == ["sector:fintech"]


def test_an_exclusion_is_not_resurfaced_by_the_cycle_it_was_stated_in() -> None:
    """The offers already fetched when the candidate spoke are not evidence of
    not listening — the next search is."""
    shown = Presentation(candidate=_offer("Data Engineer, fintech"), rank=5)

    assert resurfaced([shown], [_FINTECH], cycle=2) == []
    assert resurfaced([shown], [_FINTECH], cycle=3) != []


def test_e_commerce_is_matched_however_the_advert_spells_it() -> None:
    """The candidate said "e-commerce"; adverts say "ecommerce" and
    "E-Commerce". A matcher that only catches the candidate's spelling is a
    filter that reads as not listening in exactly the same way."""
    ecommerce = Exclusion(about="sector:e-commerce", stated_at_cycle=1, words="e-commerce tampoco")

    assert matches(_offer("Backend Engineer, ecommerce marketplace"), ecommerce)
    assert matches(_offer("Data Engineer — E-Commerce"), ecommerce)
    assert not matches(_offer("Data Engineer, banca comercial"), ecommerce)


def test_a_value_inside_a_longer_word_is_not_a_match() -> None:
    """Word boundaries, or `cloud` matches `cloudflare` and the exclusion
    starts deleting roles the candidate never ruled out."""
    cloud = Exclusion(about="stack:cloud", stated_at_cycle=1, words="cloud no")

    assert not matches(_offer("Backend Engineer at Cloudflare"), cloud)
    assert matches(_offer("Cloud Engineer"), cloud)


def test_the_probe_reports_no_resurfaced_exclusions() -> None:
    measured = se.probe_exclusions()

    assert measured["restated_exclusions_resurfaced"] == 0
    assert measured["restated_exclusions_resurfaced_evaluated"] >= se.MINIMUM_PRESENTATIONS
    assert measured["gate_status"] == "measured"
    assert measured["failures"] == []


def test_the_probe_counts_a_query_that_only_ranks() -> None:
    """The negative control that matters: a "fix" that penalises instead of
    excluding must be counted, or the gate passes over the observed bug."""
    assert "penalty" in " ".join(se.NEGATIVE_CONTROLS).lower()


def test_the_gate_does_not_pass_on_an_empty_presentation_set() -> None:
    """Nothing shown, nothing resurfaced, nothing proved."""
    measured = se.measure(presentations=(), exclusions=(), cycle=4)

    assert measured["restated_exclusions_resurfaced"] == 0
    assert measured["restated_exclusions_resurfaced_evaluated"] == 0
    assert measured["gate_status"] == "unmeasured"


def test_the_module_writes_its_evidence(tmp_path: Path) -> None:
    target = tmp_path / "T90.json"

    assert se._main(["sourcing_exclusions", str(target)]) == 0
    assert target.is_file()


def test_a_hyphen_joined_compound_is_still_a_match() -> None:
    """Found by review on #285, and a fail-open in the one direction that
    matters. `_fold` deleted separators, so "fintech-focused scale-up" became
    "fintechfocused" and the word-boundary lookahead rejected "fintech" — the
    gate recording a pass over an advert the candidate ruled out."""
    for advert in (
        "Data Engineer at a fintech-focused scale-up",
        "Senior Engineer, fintech / payments",
        "Ingeniero de datos — fintech_ops",
    ):
        assert matches(_offer(advert), _FINTECH), advert


def test_a_compound_does_not_make_a_longer_word_match() -> None:
    """The fix widens the matcher, so the over-reach guard is re-asserted:
    `cloud` must still not find `Cloudflare`, either folding."""
    cloud = Exclusion(about="stack:cloud", stated_at_cycle=1, words="cloud no")

    assert not matches(_offer("Backend Engineer at Cloudflare"), cloud)
    assert not matches(_offer("Engineer, soundcloud-adjacent"), cloud)
    assert matches(_offer("Cloud-native Platform Engineer"), cloud)


def test_the_probe_counts_each_presentation_once() -> None:
    """Found by review on #285. `named` was in both the shown set and the
    controls, so the denominator reported 8 where 7 had been checked and the
    floor was cleared by a duplicate — the padded denominator this module's
    own comment rules out."""
    measured = se.probe_exclusions()

    assert measured["presentations_checked"] == measured[
        "restated_exclusions_resurfaced_evaluated"
    ]
    assert measured["presentations_checked"] >= se.MINIMUM_PRESENTATIONS
