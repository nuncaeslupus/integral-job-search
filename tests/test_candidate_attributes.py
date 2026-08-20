"""T24 — the candidate attribute schema, and the hard-constraint filter.

The gate is `unsatisfiable_hard_constraint_leaks == 0`: of the offers that
should be removed by a stated hard constraint, none survive the filter, and of
the offers that satisfy every stated constraint, none are wrongly removed. The
rule underneath (`status/spec-v2-process.md` §2.6, §3.1): a hard constraint the
offer cannot satisfy removes the offer, never trades off against a preference;
an attribute the candidate never stated is `unknown`, which neither passes nor
vetoes — and "would move for the right role" is a stated but *conditional*
answer, not a yes, so it must not pass until its condition is checked.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from integral import stated_constraints
from integral.candidate import (
    CONSTRAINT_FIELD_NAMES,
    STATES,
    Availability,
    CandidateConstraints,
    CandidateError,
    EmploymentMode,
    LanguageLevel,
    Languages,
    Location,
    OfferFacts,
    PayCountry,
    Reach,
    Relocation,
    Salary,
    TaxCountry,
    WorkAuthorisation,
    filter_hard_constraints,
    load_constraints,
    probe_hard_filter,
    write_evidence,
)


def _offer(offer_id: str = "offer-1", **overrides: object) -> OfferFacts:
    base: dict[str, object] = {
        "offer_id": offer_id,
        "country": "ES",
        "delivery": "remote",
        "salary_stated": True,
        "salary_min": 45000,
        "salary_max": 55000,
        "salary_currency": "EUR",
        "english_level_required": "conversational",
        "latest_start_required": "2026-10-01",
        "employment_modes_offered": ("employed",),
        "payroll_countries": ("ES",),
        "tax_residency_required": "ES",
    }
    base.update(overrides)
    return OfferFacts.model_validate(base)


def _permissive() -> CandidateConstraints:
    """A candidate stated everywhere, loose enough to admit `_offer()` as-is."""
    return CandidateConstraints(
        languages=Languages(
            state="stated", levels=(LanguageLevel(language="en", level="professional"),)
        ),
        location=Location(state="stated", country="ES", accepts_onsite_in_country=True),
        relocation=Relocation(state="stated", willingness="yes"),
        salary=Salary(state="stated", floor=30000, currency="EUR"),
        availability=Availability(state="stated", earliest_start="2026-08-01"),
        work_authorisation=WorkAuthorisation(state="stated", authorised_countries=("ES",)),
        employment_mode=EmploymentMode(state="stated", accepted=("employed", "contracting")),
        pay_country=PayCountry(state="stated", countries=("ES",)),
        tax_country=TaxCountry(state="stated", country="ES"),
        reach=Reach(
            state="stated",
            modes=("remote", "commute", "relocate", "cross_border_remote_employer"),
        ),
    )


# --- the pinned field set and its three states ------------------------------


def test_the_field_set_has_all_six_v1_attributes_and_all_four_v2_additions() -> None:
    """T24 pins the vocabulary T41's engine will write constraint rows against."""
    assert set(CONSTRAINT_FIELD_NAMES) == {
        "languages",
        "location",
        "relocation",
        "salary",
        "availability",
        "work_authorisation",
        "employment_mode",
        "pay_country",
        "tax_country",
        "reach",
    }


def test_states_match_step_runtime_resolved_states() -> None:
    """`step_runtime._constraints_resolved` already reads this trichotomy.

    A drift here would make T24's schema and the reader that already depends
    on it disagree about what a valid state is, silently.
    """
    from integral.step_runtime import RESOLVED_STATES

    assert STATES == RESOLVED_STATES


@pytest.mark.parametrize("state", ["stated", "declined", "unknown"])
def test_every_state_is_constructible_in_its_own_shape(state: str) -> None:
    if state == "stated":
        Salary(state="stated", floor=10, currency="EUR")
    else:
        Salary(state=state)  # type: ignore[arg-type]


def test_a_field_cannot_carry_a_value_while_declined_or_unknown() -> None:
    """`declined`/`unknown` mean no answer was recorded — never a hidden one."""
    with pytest.raises(ValidationError):
        Salary(state="unknown", floor=10, currency="EUR")
    with pytest.raises(ValidationError):
        WorkAuthorisation(state="declined", authorised_countries=("ES",))


def test_a_field_stated_with_nothing_behind_it_is_rejected() -> None:
    """A `stated` answer has to say something, or the state is a lie."""
    with pytest.raises(ValidationError):
        Salary(state="stated")
    with pytest.raises(ValidationError):
        Languages(state="stated")


def test_an_unknown_extra_key_is_an_error_not_an_ignored_setting() -> None:
    with pytest.raises(ValidationError):
        Salary.model_validate({"state": "stated", "floor": 10, "currency": "EUR", "band": "x"})


# --- loading constraints.json ------------------------------------------------


def test_loading_a_field_outside_the_schema_raises() -> None:
    """A stray dimension id here means T41 tagged a row with the wrong vocabulary."""
    with pytest.raises(CandidateError):
        load_constraints({"fields": {"favourite_colour": {"state": "stated"}}})


def test_a_field_missing_from_the_payload_loads_as_unknown() -> None:
    """Never asked and asked-with-nothing-recorded must be the same shape."""
    constraints = load_constraints({"fields": {}})
    assert constraints.salary.state == "unknown"
    assert set(constraints.outstanding()) == set(CONSTRAINT_FIELD_NAMES)


def test_loading_round_trips_a_stated_field() -> None:
    constraints = load_constraints(
        {"fields": {"salary": {"state": "stated", "floor": 40000, "currency": "EUR"}}}
    )
    assert constraints.salary.state == "stated"
    assert constraints.salary.floor == 40000
    assert constraints.location.state == "unknown"


def test_a_non_dict_payload_raises() -> None:
    with pytest.raises(CandidateError):
        load_constraints([])  # type: ignore[arg-type]


# --- the three named tests ---------------------------------------------------


def test_offer_failing_a_hard_constraint_never_ranks() -> None:
    """An offer that violates one stated hard constraint must be removed
    outright — never scored, never traded against a preference."""
    constraints = _permissive()
    good = _offer("offer-good")
    underpaid = _offer("offer-bad", salary_min=1000, salary_max=2000)

    result = filter_hard_constraints(constraints, [good, underpaid])

    assert result.surviving == ("offer-good",)
    assert underpaid.offer_id not in result.surviving
    assert any(r.offer_id == "offer-bad" and r.field == "salary" for r in result.removed)


def test_missing_attribute_is_unknown_not_satisfied() -> None:
    """An unstated salary floor must not silently admit every offer — it must
    also surface as a question the interview (T27) still owes the candidate."""
    constraints = CandidateConstraints(salary=Salary(state="unknown"))
    starvation_wage = _offer("offer-cheap", salary_min=1, salary_max=1)

    result = filter_hard_constraints(constraints, [starvation_wage])

    # Unknown neither vetoes (the offer is not removed)...
    assert result.surviving == ("offer-cheap",)
    assert result.removed == ()
    # ...nor is it treated as satisfied: it stays outstanding.
    assert "salary" in result.outstanding_fields


def test_a_declined_field_does_not_veto_and_is_not_reported_outstanding() -> None:
    """§5.4 non-insistence: a declined subject is not raised again — reporting
    it as still-owed would be this module inviting the next step to re-ask."""
    constraints = CandidateConstraints(salary=Salary(state="declined"))
    cheap = _offer("offer-cheap", salary_min=1, salary_max=1)
    result = filter_hard_constraints(constraints, [cheap])

    assert result.surviving == ("offer-cheap",)
    assert "salary" not in result.outstanding_fields


def test_conditional_relocation_needs_its_condition_checked() -> None:
    """ "Would move for the right role" is not a yes.

    A `conditional` relocation, by itself, must filter exactly like `no` for
    any offer that needs it — only an explicit per-offer confirmation
    (someone having checked the condition) turns it into a pass, and only for
    that one offer.
    """
    constraints = CandidateConstraints(
        relocation=Relocation(
            state="stated",
            willingness="conditional",
            destinations=("DE",),
            condition="a senior title and a relocation package",
        )
    )
    unchecked = _offer("offer-de", country="DE", delivery="onsite", requires_relocation=True)

    result = filter_hard_constraints(constraints, [unchecked])

    assert unchecked.offer_id not in result.surviving
    assert any(r.offer_id == "offer-de" and r.field == "relocation" for r in result.removed)

    # Confirming the condition for this specific offer, and only this offer,
    # is what makes it count.
    confirmed = constraints.model_copy(
        update={
            "relocation": constraints.relocation.model_copy(
                update={"confirmed_offers": frozenset({"offer-de"})}
            )
        }
    )
    other_unchecked = _offer(
        "offer-de-2", country="DE", delivery="onsite", requires_relocation=True
    )
    confirmed_result = filter_hard_constraints(confirmed, [unchecked, other_unchecked])

    assert "offer-de" in confirmed_result.surviving
    assert "offer-de-2" not in confirmed_result.surviving


def test_relocation_willingness_yes_still_respects_stated_destinations() -> None:
    """ "Yes" is not "yes to anywhere" once destinations are named."""
    constraints = CandidateConstraints(
        relocation=Relocation(state="stated", willingness="yes", destinations=("DE",))
    )
    to_named = _offer("offer-de", country="DE", delivery="onsite", requires_relocation=True)
    to_other = _offer("offer-fr", country="FR", delivery="onsite", requires_relocation=True)

    result = filter_hard_constraints(constraints, [to_named, to_other])

    assert "offer-de" in result.surviving
    assert "offer-fr" not in result.surviving


def test_relocation_willingness_no_removes_every_relocation_offer() -> None:
    constraints = CandidateConstraints(relocation=Relocation(state="stated", willingness="no"))
    offer = _offer("offer-de", country="DE", delivery="onsite", requires_relocation=True)
    result = filter_hard_constraints(constraints, [offer])
    assert result.surviving == ()


def test_a_remote_offer_needs_no_relocation_regardless_of_willingness() -> None:
    constraints = CandidateConstraints(relocation=Relocation(state="stated", willingness="no"))
    remote = _offer("offer-remote", country="DE", delivery="remote")
    result = filter_hard_constraints(constraints, [remote])
    assert result.surviving == ("offer-remote",)


# --- each hard constraint really vetoes, and only when it applies ----------


def test_language_level_below_the_ad_requirement_is_removed() -> None:
    constraints = _permissive()
    result = filter_hard_constraints(
        constraints, [_offer("offer-en", english_level_required="native")]
    )
    assert result.surviving == ()


def test_language_level_at_or_above_the_requirement_survives() -> None:
    constraints = _permissive()
    result = filter_hard_constraints(
        constraints, [_offer("offer-en", english_level_required="basic")]
    )
    assert result.surviving == ("offer-en",)


def test_on_site_in_own_country_is_removed_when_on_site_work_was_declined() -> None:
    constraints = _permissive().model_copy(
        update={"location": Location(state="stated", country="ES", accepts_onsite_in_country=False)}
    )
    offer = _offer("offer-onsite", country="ES", delivery="onsite", requires_relocation=False)
    result = filter_hard_constraints(constraints, [offer])
    assert result.surviving == ()


def test_work_authorisation_is_only_checked_when_presence_is_required() -> None:
    """A remote role asks nothing of local work authorisation in this model."""
    constraints = _permissive().model_copy(
        update={
            "work_authorisation": WorkAuthorisation(state="stated", authorised_countries=("ES",))
        }
    )
    remote_elsewhere = _offer("offer-remote", country="FR", delivery="remote")
    result = filter_hard_constraints(constraints, [remote_elsewhere])
    assert result.surviving == ("offer-remote",)


def test_work_authorisation_is_checked_for_on_site_presence() -> None:
    constraints = _permissive().model_copy(
        update={
            "work_authorisation": WorkAuthorisation(state="stated", authorised_countries=("ES",))
        }
    )
    onsite_elsewhere = _offer(
        "offer-fr", country="FR", delivery="onsite", requires_relocation=False
    )
    result = filter_hard_constraints(constraints, [onsite_elsewhere])
    assert result.surviving == ()


def test_employment_mode_mismatch_is_removed() -> None:
    constraints = _permissive().model_copy(
        update={"employment_mode": EmploymentMode(state="stated", accepted=("employed",))}
    )
    contracting_only = _offer("offer-c", employment_modes_offered=("contracting",))
    result = filter_hard_constraints(constraints, [contracting_only])
    assert result.surviving == ()


def test_pay_country_with_no_overlap_is_removed() -> None:
    constraints = _permissive().model_copy(
        update={"pay_country": PayCountry(state="stated", countries=("ES",))}
    )
    result = filter_hard_constraints(constraints, [_offer("offer-p", payroll_countries=("US",))])
    assert result.surviving == ()


def test_pay_country_is_not_checked_when_the_ad_does_not_say() -> None:
    """An ad-side unknown must not veto either — nothing to compare against."""
    constraints = _permissive().model_copy(
        update={"pay_country": PayCountry(state="stated", countries=("ES",))}
    )
    result = filter_hard_constraints(constraints, [_offer("offer-p", payroll_countries=None)])
    assert result.surviving == ("offer-p",)


def test_tax_country_mismatch_is_removed() -> None:
    constraints = _permissive().model_copy(
        update={"tax_country": TaxCountry(state="stated", country="ES")}
    )
    result = filter_hard_constraints(constraints, [_offer("offer-t", tax_residency_required="PT")])
    assert result.surviving == ()


def test_reach_without_cross_border_remote_removes_a_foreign_employer_offer() -> None:
    constraints = _permissive().model_copy(
        update={"reach": Reach(state="stated", modes=("remote",))}
    )
    foreign = _offer("offer-x", country="US", delivery="remote", foreign_employer=True)
    result = filter_hard_constraints(constraints, [foreign])
    assert result.surviving == ()


def test_reach_with_cross_border_remote_admits_a_foreign_employer_offer() -> None:
    constraints = _permissive().model_copy(
        update={"reach": Reach(state="stated", modes=("cross_border_remote_employer",))}
    )
    foreign = _offer("offer-x", country="US", delivery="remote", foreign_employer=True)
    result = filter_hard_constraints(constraints, [foreign])
    assert result.surviving == ("offer-x",)


def test_availability_after_the_ads_latest_start_is_removed() -> None:
    constraints = _permissive().model_copy(
        update={"availability": Availability(state="stated", earliest_start="2026-12-01")}
    )
    urgent = _offer("offer-urgent", latest_start_required="2026-09-01")
    result = filter_hard_constraints(constraints, [urgent])
    assert result.surviving == ()


def test_salary_is_not_checked_when_the_ad_does_not_state_a_band() -> None:
    """The ad's own unstated salary is a different fact from the candidate's —
    it must not be conflated into a veto either."""
    constraints = _permissive()
    result = filter_hard_constraints(constraints, [_offer("offer-x", salary_stated=False)])
    assert result.surviving == ("offer-x",)


def test_salary_across_mismatched_currencies_is_not_compared() -> None:
    """No conversion rate lives here — a currency mismatch must not fabricate
    a veto out of an incomparable number."""
    constraints = _permissive()
    result = filter_hard_constraints(
        constraints, [_offer("offer-usd", salary_currency="USD", salary_min=1, salary_max=1)]
    )
    assert result.surviving == ("offer-usd",)


def test_salary_with_no_stated_currency_is_not_compared() -> None:
    """An advert quoting a number and no currency is a number of unknown units,
    not an implicit quote in the candidate's own currency.

    The mismatched-currency test above covers an offer that says "USD". This is
    the one that says nothing, which took a different path: the guard only
    returned early when a currency was present *and* different, so an absent
    one fell straight through to the numeric comparison. Both outcomes of that
    are invisible — a veto drops a role that might well clear the floor, and a
    pass admits one that does not — and either way the tool has invented the
    missing half of the comparison.
    """
    constraints = _permissive()
    result = filter_hard_constraints(
        constraints, [_offer("offer-unitless", salary_currency=None, salary_min=1, salary_max=1)]
    )
    assert result.surviving == ("offer-unitless",)


# --- the gate ----------------------------------------------------------------


def test_probe_reports_zero_leaks_and_checks_at_least_ten_cases() -> None:
    measured = probe_hard_filter()
    assert measured["leaks"] == []
    assert measured["unsatisfiable_hard_constraint_leaks"] == 0
    assert measured["cases_checked"] >= 10


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    evidence = tmp_path / "T24.json"
    measured = write_evidence(evidence)
    assert measured["unsatisfiable_hard_constraint_leaks"] == 0
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured


# ---------------------------------------------------------------------------
# D-20 — a stated constraint must reach the filter, not stop at the log


def test_a_stated_commute_radius_reaches_the_hard_constraint_filter() -> None:
    """The sentence D-20 was filed from, end to end.

    > "I can move, but in the province of Barcelona, or maximum to Girona or
    > Tarragona. I want to sleep home each day."

    Not relocation — he is not moving — and not a bare yes to on-site work
    anywhere in Spain, which is what `accepts_onsite_in_country` alone said.
    Before `commutable_regions` existed the Sevilla job survived, so the most
    filtering thing he said changed nothing about what he was shown.
    """
    constraints = CandidateConstraints(
        location=Location(
            state="stated",
            country="ES",
            accepts_onsite_in_country=True,
            commutable_regions=("Barcelona", "Girona", "Tarragona"),
        )
    )
    sevilla = _offer("onsite-sevilla", delivery="onsite", region="Sevilla")
    girona = _offer("onsite-girona", delivery="onsite", region="Girona")

    result = filter_hard_constraints(constraints, [sevilla, girona])

    assert result.surviving == ("onsite-girona",)
    assert [r.field for r in result.removed] == ["location"]
    assert "Sevilla" in result.removed[0].reason

    # The radius narrows on-site work; it says nothing about remote work, which
    # needs no travel at all. A radius that quietly vetoed remote roles would
    # be worse than the absence it replaced.
    remote_sevilla = _offer("remote-sevilla", region="Sevilla")
    assert filter_hard_constraints(constraints, [remote_sevilla]).surviving == ("remote-sevilla",)

    # An ad that does not say where the work is cannot be shown to violate the
    # radius — an ad-side unknown never vetoes, exactly as `payroll_countries`
    # does not.
    unsaid = _offer("onsite-somewhere", delivery="onsite")
    assert filter_hard_constraints(constraints, [unsaid]).surviving == ("onsite-somewhere",)


def test_a_commute_radius_without_accepting_onsite_is_refused() -> None:
    """The contradiction is refused where it is written, not left in the file
    looking answered: a candidate who will not work on site at all has no
    travel radius, and the filter would read the bool first and never reach
    the regions."""
    with pytest.raises(ValidationError, match="commutable_regions"):
        Location(
            state="stated",
            country="ES",
            accepts_onsite_in_country=False,
            commutable_regions=("Barcelona",),
        )


def test_no_stated_constraint_is_recorded_only_as_prose() -> None:
    """D-20's gate. `unfilterable_stated_constraints == 0`.

    The general form of the defect, over all ten pinned fields: for each, a
    real sentence a candidate might say is stated, and the filter must both
    remove an offer that breaks it and keep one that does not. A field that
    stores the answer and changes no offer's fate is prose with extra steps —
    it looks answered from every angle while the candidate sees the same list
    either way.
    """
    measured = stated_constraints.measure()

    assert measured["unfilterable"] == []
    assert measured["unfilterable_stated_constraints"] == 0
    # Not a vacuous zero: every pinned field must have been probed, or the
    # number is a statement about the fields somebody remembered.
    assert measured["fields_probed"] == measured["fields_pinned"] == len(CONSTRAINT_FIELD_NAMES)
    assert all(reading["filters"] for reading in measured["readings"])


def test_a_constraint_that_filters_nothing_is_counted(tmp_path: Path) -> None:
    """The gate confirmed against the state D-20 was filed in.

    With the commute radius dropped — the pre-D-20 `Location`, which could hold
    the country and the bool and nothing else — the Sevilla offer survives and
    the probe is counted. Without this, a zero would only mean the probes ran.
    """
    probe = next(p for p in stated_constraints.PROBES if p.field == "location")
    before = stated_constraints.Probe(
        field=probe.field,
        said=probe.said,
        value=Location(state="stated", country="ES", accepts_onsite_in_country=True),
        removes=probe.removes,
        keeps=probe.keeps,
    )

    reasons = stated_constraints.check(before)

    assert reasons, "the pre-D-20 Location must fail the check it exists to enforce"
    assert "recorded but filters nothing" in reasons[0]


def test_a_pinned_field_with_no_probe_records_minus_one() -> None:
    """`-1`, never `0`. A field nobody probed is an unmeasured field, and a
    clean zero over a partial set is the vacuous pass this project keeps
    finding."""
    original = stated_constraints.PROBES
    stated_constraints.PROBES = tuple(p for p in original if p.field != "salary")
    try:
        measured = stated_constraints.measure()
    finally:
        stated_constraints.PROBES = original

    assert measured["unfilterable_stated_constraints"] == -1
    assert "salary" in measured["unfilterable"][0]
