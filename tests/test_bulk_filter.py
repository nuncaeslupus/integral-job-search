"""T94 — the bulk pass reduces volume without a person, and says why.

Three properties the task names, and the adversarial half underneath them.

This filter **deletes rows the candidate will never see**, so the costly
direction is the drop, not the keep: a wrong deletion loses a real job and shows
nobody a reason, while a wrong keep costs one row of reading. Most of what is
below is therefore about what must *survive* — an unstated salary, an unstated
country, a stated remote arrangement, a `FLAG`, a stated sector distaste —
because those are the cases where a filter written to look decisive quietly
stops being honest.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from integral import bulk_filter
from integral.bulk_filter import (
    RULES,
    BulkFilterError,
    HardConstraints,
    PayFloor,
    measure,
    probe_batch,
    reduce,
)
from integral.eligibility import CandidateEligibility
from integral.offers import Location, Offer, Salary, compute_offer_id

_NOW = datetime(2026, 9, 3, tzinfo=UTC)


def _offer(text: str, **fields: object) -> Offer:
    return Offer(id=compute_offer_id(text), source="test", text=text, **fields)  # type: ignore[arg-type]


def _rules(reduction: bulk_filter.Reduction) -> set[str]:
    return {drop.rule for drop in reduction.dropped}


# --- the three the task names -------------------------------------------------


def test_a_few_hundred_offers_reduce_without_a_human_decision() -> None:
    """The whole point: volume in, tens out, nobody consulted.

    `reduce` takes no callback, prompts nothing and returns a finished answer,
    so "without a human decision" is a property of the signature as much as of
    the numbers. The numbers are here because a filter that returns its input
    unchanged also consults nobody.
    """
    batch = probe_batch()
    assert len(batch) >= 300

    reduction = reduce(batch, bulk_filter._probe_constraints(), now=_NOW)

    assert len(reduction.kept) < len(batch) / 2
    assert len(reduction.kept) + len(reduction.dropped) == len(batch)
    # Nothing invented and nothing lost: every survivor came from the batch.
    assert {offer.id for offer in reduction.kept} <= {offer.id for offer in batch}


def test_every_rejection_records_which_rule_dropped_it() -> None:
    """A filter that cannot say why is one nobody can trust or debug."""
    reduction = reduce(probe_batch(), bulk_filter._probe_constraints(), now=_NOW)

    assert reduction.dropped
    for drop in reduction.dropped:
        assert drop.rule in RULES, drop
        assert drop.because.strip(), f"{drop.offer_id} dropped by {drop.rule} with no reason"
    # And every declared rule is exercised. A rule nobody fired is a rule nobody
    # measured, and it would sit here green for as long as the batch avoided it.
    assert _rules(reduction) == set(RULES)


def test_the_filter_never_drops_on_a_soft_preference() -> None:
    """Soft goes to ranking. Only hard rules delete — T90.

    Asserted twice, and the structural half is the one that holds. A behavioural
    test can only show that today's rules ignore an exclusion; `reduce` having
    no parameter to receive one is what stops a later rule from applying it.
    """
    parameters = set(inspect.signature(reduce).parameters)
    assert not parameters & {"exclusions", "preferences", "soft", "distastes"}
    assert not {field for field in HardConstraints.__dataclass_fields__} & {
        "exclusions",
        "preferences",
        "soft",
    }

    disliked = _offer(
        "Backend engineer in Girona. We build wagering software for the gambling "
        "industry, and you would own the settlement service end to end."
    )
    reduction = reduce([disliked], bulk_filter._probe_constraints(), now=_NOW)

    assert [offer.id for offer in reduction.kept] == [disliked.id]
    assert not reduction.dropped


# --- the drop side: only a stated fact may delete -----------------------------


def test_an_expired_advert_is_dropped_and_an_unreadable_date_is_not() -> None:
    """A date this module cannot parse is not evidence that the advert expired."""
    expired = _offer("Closed posting for a site foreman.", expires_at="2020-01-01T00:00:00Z")
    unreadable = _offer("Open posting for a site foreman.", expires_at="soon")
    absent = _offer("Another posting for a site foreman.")

    reduction = reduce([expired, unreadable, absent], now=_NOW)

    assert [drop.offer_id for drop in reduction.dropped] == [expired.id]
    assert {offer.id for offer in reduction.kept} == {unreadable.id, absent.id}


def test_a_stated_figure_under_the_floor_drops_and_an_unstated_one_never_does() -> None:
    """`salary.stated` is the field §5.2 added to keep absent distinct from zero.

    An advert that named no pay is not an advert paying too little — that is
    T92's whole subject, "an advert with no salary is dropped, and nobody looked
    for the figure". This is the rule that would recreate it.
    """
    floor = HardConstraints(pay_floor=PayFloor(amount=30000, currency="EUR", period="year"))
    under = _offer(
        "Data analyst, band stated.",
        salary=Salary(min=18000, max=21000, currency="EUR", period="year", stated=True),
    )
    unstated = _offer(
        "Data analyst, competitive.",
        salary=Salary(currency="EUR", period="year", stated=False),
    )
    other_currency = _offer(
        "Data analyst, band stated in dollars.",
        salary=Salary(min=18000, max=21000, currency="USD", period="year", stated=True),
    )
    no_salary = _offer("Data analyst, no salary object at all.")

    reduction = reduce([under, unstated, other_currency, no_salary], floor, now=_NOW)

    assert [drop.offer_id for drop in reduction.dropped] == [under.id]
    assert _rules(reduction) == {"below_pay_floor"}
    # The reason quotes the advert's own figure, not the rule's name twice over.
    assert "18000" in reduction.dropped[0].because or "21000" in reduction.dropped[0].because


def test_a_stated_country_outside_the_set_drops_unless_remote_is_named() -> None:
    outside = _offer("On site in Berlin.", location=Location(country="DE", raw="Berlin"))
    remote = _offer(
        "Worked remotely.", location=Location(country="DE", raw="Berlin", remote="fully remote")
    )
    inside = _offer("On site in Girona.", location=Location(country="ES", raw="Girona"))
    unstated = _offer("Location not given.", location=Location(raw="somewhere"))
    no_location = _offer("No location object at all.")

    constraints = HardConstraints(countries=frozenset({"ES", "PT"}))
    reduction = reduce([outside, remote, inside, unstated, no_location], constraints, now=_NOW)

    assert [drop.offer_id for drop in reduction.dropped] == [outside.id]
    assert {offer.id for offer in reduction.kept} == {
        remote.id,
        inside.id,
        unstated.id,
        no_location.id,
    }


def test_an_empty_country_set_is_no_rule_rather_than_nothing_permitted() -> None:
    """The default must not delete the batch.

    `frozenset()` is `HardConstraints`'s default, so reading it as "no country is
    permitted" would make an unconfigured filter remove every located offer —
    the worst available fail-closed, and reachable by forgetting an argument.
    """
    located = _offer("On site in Berlin.", location=Location(country="DE"))

    assert [offer.id for offer in reduce([located], HardConstraints(), now=_NOW).kept] == [
        located.id
    ]


def test_only_a_fail_deletes_and_a_flag_survives() -> None:
    """§5.4: ranked, marked, and the human is the tiebreaker."""
    candidate = CandidateEligibility(citizenships=("Argentina",), work_authorisations=("Spain",))
    fails = _offer("You must have the right to work in Germany before you apply.")
    flagged = _offer("EU citizenship required for this position.")

    reduction = reduce([fails, flagged], HardConstraints(eligibility=candidate), now=_NOW)

    assert [drop.offer_id for drop in reduction.dropped] == [fails.id]
    assert [offer.id for offer in reduction.kept] == [flagged.id]


def test_an_unknown_candidate_fails_nobody() -> None:
    """Nothing stated about the candidate cannot resolve to a confident FAIL."""
    hard = _offer("You must have the right to work in Germany before you apply.")

    assert not reduce([hard], HardConstraints(), now=_NOW).dropped


# --- duplicates ----------------------------------------------------------------


def test_a_crosspost_collapses_to_one_and_the_survivor_is_named() -> None:
    body = (
        "Senior platform engineer wanted for a growing team in Barcelona. You will own "
        "the deployment pipeline, the observability stack and the on-call rotation, "
        "working closely with product on what ships next. A permanent contract."
    )
    first = _offer(body)
    second = _offer(body + " Apply through our careers page.")

    reduction = reduce([first, second], now=_NOW)

    assert [offer.id for offer in reduction.kept] == [first.id]
    assert [drop.offer_id for drop in reduction.dropped] == [second.id]
    assert first.id in reduction.dropped[0].because


def test_a_duplicate_of_a_row_a_hard_rule_removed_still_survives() -> None:
    """Duplicates are collapsed last, over what already passed.

    Run first, the surviving copy could be one an expiry or a pay floor was
    about to delete — and the whole cluster would go with it, losing a live
    advert because its dead twin was earlier in the list. This is the ordering
    bug the rule sequence exists to prevent, and nothing else would catch it.
    """
    body = (
        "Warehouse operative in Valencia for a national distributor. The work is shift "
        "based and moves stock between the bays and the loading dock, with a forklift "
        "licence provided during the first month."
    )
    dead = Offer(
        id=compute_offer_id(body),
        source="test",
        text=body,
        expires_at="2020-01-01T00:00:00Z",
    )
    live = _offer(body + " Apply on our careers page.")

    reduction = reduce([dead, live], now=_NOW)

    assert [offer.id for offer in reduction.kept] == [live.id]
    assert [(d.offer_id, d.rule) for d in reduction.dropped] == [(dead.id, "expired")]


# --- the recorded measurement --------------------------------------------------


def test_the_recorded_measurement_holds_its_own_invariants() -> None:
    measured = measure()

    assert measured["offers_in"] >= measured["offers_in_at_least"]
    assert measured["bulk_offers_requiring_manual_triage"] == 0
    assert measured["offers_unaccounted_for"] == 0
    assert measured["drops_with_no_rule"] == 0
    assert measured["soft_preference_drops"] == 0
    assert measured["soft_preference_rows_presented"] > 0
    assert measured["rules_never_exercised"] == []
    assert measured["rules_declared"] == len(RULES)
    assert measured["planted_duplicate_collapsed"] is True
    assert 0.0 < measured["reduction_ratio"] < 1.0


def test_the_rule_vocabulary_is_counted_rather_than_written_as_a_literal() -> None:
    """A denominator written as a literal drifts the moment a rule is added.

    `rules_declared` is `len(RULES)`, and every drop's rule is drawn from the
    same tuple, so a sixth rule cannot be added without both the record and the
    exercised-rules check noticing it.
    """
    measured = measure()

    assert measured["rules_declared"] == len(RULES)
    assert set(measured["drops_by_rule"]) == set(RULES)


@pytest.mark.parametrize(
    ("amount", "currency", "period"),
    [(0, "EUR", "year"), (-1, "EUR", "year"), (30000, " ", "year"), (30000, "EUR", "")],
)
def test_a_floor_that_cannot_be_compared_is_refused_at_construction(
    amount: float, currency: str, period: str
) -> None:
    """A bare number is not a floor.

    Comparing 30000 against a monthly figure in another currency is the kind of
    confident wrong answer a deleting filter must not be able to produce, so the
    units are required where the floor is built rather than checked where it is
    used.
    """
    with pytest.raises(BulkFilterError):
        PayFloor(amount=amount, currency=currency, period=period)


def test_an_empty_batch_reduces_to_nothing_without_dividing_by_zero() -> None:
    reduction = reduce([], bulk_filter._probe_constraints(), now=_NOW)

    assert reduction.kept == ()
    assert reduction.dropped == ()
    assert reduction.ratio == 0.0
