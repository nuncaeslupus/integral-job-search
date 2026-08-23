"""The candidate attribute schema, and the hard-constraint filter (T24).

`constraints.json` (`status/spec-v2-process.md` §2.6, `status/specification.md`
§5) is where the candidate-side facts that *veto* offers live — as opposed to
`weights.json`, which is where preferences that merely *rank* offers live.
Nothing named the field set before this module; `_build_constraints` in
`integral.profile` folds whatever `dimensions` a constraint evidence row
carries into the file, and folds them under whatever name the writer chose.
That is correct for T6 (a derived file that has to accept an evidence log
however a step happened to tag it), but it is not a contract on its own — two
future writers could tag the same fact two different ways and nothing would
notice. This module is that contract: the fixed vocabulary T41's engine writes
constraint rows against, and the shape each field's value takes once it does.

**Three states, and only three** (§3.1): `stated`, `declined`, `unknown`.
`step_runtime._constraints_resolved` already reads this trichotomy off
whatever is in `constraints.json`'s `fields` dict; this module is what fixes
what a valid value under each state looks like, so that reader's assumption is
backed by something rather than by convention. `unknown` is the load-bearing
one: an attribute nobody has answered is unknown, never satisfied, and unknown
is not neutral — it must never quietly stand in for "no constraint" *or* for
"constraint violated". A candidate who has not stated a salary floor gets
every offer through the salary check, and a `NotStated` field name comes back
out of the filter to say a floor is still owed to T27's interview. `declined`
is different from `unknown` in exactly one way that matters here: both fail to
veto, but a `declined` field is not reported as outstanding, because §5.4's
non-insistence rule says a declined subject is not raised again — reporting it
as still-owed would be this module inviting the next step to ask anyway.

**The rule that carries the task** (§2.6, restated in the payload): a hard
constraint the offer cannot satisfy *removes* the offer. It is never weighed
against a preference, never averaged in, never partially satisfied. Every
field this module defines is a hard constraint for exactly that reason — the
six the v1 table names (languages, location, relocation, salary, availability,
work authorisation) plus the four v2 adds because they determine which offers
are *legal*, not merely welcome: employment mode (employed or contracting),
where the candidate may be paid, where they are taxed, and how far the search
may travel (remote, commuting distance, relocation, or working for a foreign
employer while living here).

**Conditional relocation is not a yes.** "Would move for the right role" is a
real, stated answer — it is not `unknown` — but it is not `willingness: "yes"`
either, and a filter that treated it as one would let every relocation-needing
offer through on the strength of a maybe. `Relocation.confirmed_offers` is the
only thing that turns a `conditional` willingness into a pass for one specific
offer, and nothing in this module sets it automatically: the condition has to
be checked — by a human, in T41's engine, or by T27's interview — before it
counts. Until it is confirmed for a given offer, `conditional` behaves like
`no` for that offer, never like `yes`.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T24.json"

# The three states §3.1 names. Kept as a plain tuple/frozenset rather than
# imported from `integral.step_runtime.RESOLVED_STATES`: that module reads
# constraints.json, this module defines what is valid to put in it, and a
# schema module importing its own reader would invert the dependency for no
# gain. `test_states_match_step_runtime_resolved_states` holds the two in step
# instead, the same way T2 holds `Language` against the corpus with a test
# rather than a shared import across an unrelated boundary.
ConstraintState = Literal["stated", "declined", "unknown"]
STATES: frozenset[str] = frozenset(get_args(ConstraintState))

Level = Literal["none", "basic", "conversational", "professional", "native"]
LEVEL_ORDER: dict[str, int] = {level: rank for rank, level in enumerate(get_args(Level))}

EmploymentModeName = Literal["employed", "contracting"]
ReachMode = Literal[
    "remote",
    "commute",
    "relocate",
    "cross_border_remote_employer",
]

COUNTRY_PATTERN = r"^[A-Z]{2}$"
CURRENCY_PATTERN = r"^[A-Z]{3}$"
LANGUAGE_PATTERN = r"^[a-z]{2}$"


def _country_field(*, required: bool) -> Any:
    """A fresh `FieldInfo` per attribute — `Field(...)` objects are not meant
    to be shared across class attributes, so each caller gets its own."""
    if required:
        return Field(pattern=COUNTRY_PATTERN)
    return Field(default=None, pattern=COUNTRY_PATTERN)


class CandidateError(Exception):
    """A `constraints.json` payload, or a field within it, breaks the schema."""


class Strict(BaseModel):
    """Unknown keys are an error everywhere in this schema — see `dimensions.Strict`.

    A typo'd field name inside a candidate's stated constraint must fail loudly:
    silently ignoring it is silently ignoring the fact the candidate stated.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# constraint fields


class ConstraintField(Strict):
    """One `constraints.json` field: a state, and the value that state permits.

    The shape rule is the same for every field and is enforced once, here:
    `stated` requires the fields named in `_required_when_stated` to be set to
    something other than their default; `declined` and `unknown` require every
    value field to be at its default. The second half is what makes "unknown
    means unknown" mechanical rather than a naming convention — a subclass
    cannot carry a hidden opinion under a state that says it has none.
    """

    state: ConstraintState
    # The evidence rows that stated this field (T21). Provenance, not a value,
    # which is why `_shape_matches_state` below skips it: a `stated` field
    # still has to say something other than who said it, and a `declined` one
    # still carries no answer even though a decline of its own is on record.
    # Empty is the honest default — a field resolved from a decline or never
    # touched has no row behind it, and step 10's `feedback_traceability`
    # measures how often a *stated* one does not.
    evidence: tuple[str, ...] = ()
    # Field names (on the subclass) that must be non-default when `state` is
    # `stated`. Empty by default; a subclass with no sub-fields at all (none
    # exist here, but the base stays honest) would otherwise accept a
    # `stated` with nothing behind it.
    _required_when_stated: ClassVar[tuple[str, ...]] = ()

    def _is_default(self, name: str) -> bool:
        info = type(self).model_fields[name]
        return bool(getattr(self, name) == info.get_default(call_default_factory=True))

    @model_validator(mode="after")
    def _shape_matches_state(self) -> ConstraintField:
        names = [
            name for name in type(self).model_fields if name not in ("state", "evidence")
        ]
        set_names = [name for name in names if not self._is_default(name)]
        if self.state == "stated":
            missing = [name for name in self._required_when_stated if self._is_default(name)]
            if not set_names:
                raise ValueError(
                    f"{type(self).__name__}: state is 'stated' but every value is at its "
                    "default — a stated fact has to say something"
                )
            if missing:
                raise ValueError(
                    f"{type(self).__name__}: state 'stated' requires {', '.join(missing)} to be set"
                )
        elif set_names:
            raise ValueError(
                f"{type(self).__name__}: state {self.state!r} carries a value in "
                f"{', '.join(set_names)} — {self.state} means no answer was recorded, "
                "not a hidden one"
            )
        return self


class LanguageLevel(Strict):
    """One language the candidate speaks, and whether they'd work in it."""

    language: str = Field(pattern=LANGUAGE_PATTERN)
    level: Level
    working_language: bool = False


class Languages(ConstraintField):
    """Compares against `english_demand` and its siblings (payload table).

    A level per language rather than one flag, because the ad-side dimensions
    this is filtered against are graded (`english_demand` runs none → native),
    and a boolean "speaks English" would collapse B1 and native into the same
    fact where the filter needs the gap between them.
    """

    levels: tuple[LanguageLevel, ...] = ()
    _required_when_stated = ("levels",)

    def level_of(self, language: str) -> Level:
        return next((entry.level for entry in self.levels if entry.language == language), "none")


class Location(ConstraintField):
    """Where the candidate is, and the on-site work they'll do without moving.

    Deliberately scoped to *within* the candidate's own country — a job in a
    different country is `Relocation`'s question, not this one, so the two
    fields do not both have an opinion about the same offer.
    """

    country: str | None = _country_field(required=False)
    accepts_onsite_in_country: bool = False
    #: The subdivisions — provinces, regions, whatever the country calls them —
    #: the candidate will travel to and back from within a day. Empty means the
    #: reach is not narrowed, and `accepts_onsite_in_country` governs alone.
    #:
    #: This exists because `accepts_onsite_in_country` is a single bool over a
    #: whole country, and "I can move, but in the province of Barcelona, or at
    #: most Girona or Tarragona — I want to sleep at home each day" is neither
    #: relocation (he is not moving) nor a bare yes to on-site anywhere in
    #: Spain. Without somewhere to put it the most filtering thing the
    #: candidate said survived only as quote text on an evidence row (D-20).
    commutable_regions: tuple[str, ...] = ()
    _required_when_stated = ("country",)

    @model_validator(mode="after")
    def _a_commute_radius_implies_accepting_onsite(self) -> Location:
        # A candidate who will not work on site at all has no commute radius:
        # the pair would be contradictory, and the filter would read the bool
        # first and never reach the regions. Refuse it at construction rather
        # than let the contradiction sit in `constraints.json` looking answered.
        if self.commutable_regions and not self.accepts_onsite_in_country:
            raise ValueError(
                "Location: commutable_regions given while on-site work in the country is "
                "declined — a travel radius for work the candidate will not do says nothing"
            )
        return self


class Relocation(ConstraintField):
    """Willing / not / conditional, and where — payload's third named test.

    `confirmed_offers` is not something a candidate "states" in the ordinary
    sense; it is written once someone has checked a `conditional` candidate's
    condition against one specific offer and found it satisfied. Until an
    offer's id is in this set, `conditional` filters exactly like `no` for
    that offer — seeing "the right role" and rubber-stamping every relocation
    offer is the failure this field exists to prevent.
    """

    willingness: Literal["yes", "no", "conditional"] | None = None
    destinations: tuple[str, ...] = ()
    condition: str | None = None
    confirmed_offers: frozenset[str] = frozenset()
    _required_when_stated = ("willingness",)

    @model_validator(mode="after")
    def _conditional_names_its_condition(self) -> Relocation:
        if self.willingness == "conditional" and not self.condition:
            raise ValueError(
                "Relocation: willingness 'conditional' without a condition is not "
                "checkable — record what the 'right role' would have to offer"
            )
        if self.willingness != "conditional" and (self.condition or self.confirmed_offers):
            raise ValueError(
                "Relocation: condition/confirmed_offers only apply to willingness 'conditional'"
            )
        if self.willingness == "no" and self.destinations:
            raise ValueError("Relocation: willingness 'no' but destinations are listed")
        return self


class Salary(ConstraintField):
    """Floor and target, gross annual by default — compares against the ad's band."""

    floor: float | None = None
    target: float | None = None
    currency: str | None = Field(default=None, pattern=CURRENCY_PATTERN)
    period: Literal["year", "month"] = "year"
    _required_when_stated = ("floor", "currency")

    @model_validator(mode="after")
    def _target_is_not_below_floor(self) -> Salary:
        if self.floor is not None and self.target is not None and self.target < self.floor:
            raise ValueError("Salary: target is below floor")
        return self


class Availability(ConstraintField):
    """Notice period and earliest start — compares against the ad's urgency."""

    notice_period_days: int | None = Field(default=None, ge=0)
    earliest_start: str | None = None
    _required_when_stated = ("earliest_start",)


class WorkAuthorisation(ConstraintField):
    """Countries the candidate may legally work in without sponsorship."""

    authorised_countries: tuple[str, ...] = ()
    _required_when_stated = ("authorised_countries",)


class EmploymentMode(ConstraintField):
    """Employed, contracting, or both — the v2 reach-and-legality addition."""

    accepted: tuple[EmploymentModeName, ...] = ()
    _required_when_stated = ("accepted",)


class PayCountry(ConstraintField):
    """Countries the candidate can legally be paid in."""

    countries: tuple[str, ...] = ()
    _required_when_stated = ("countries",)


class TaxCountry(ConstraintField):
    """The single country the candidate is tax-resident in.

    Singular, unlike `PayCountry`: an employer can often route payroll through
    more than one jurisdiction, but a person is tax-resident in one place (or
    is a dual-resident case rare enough that it is recorded as free text and
    handled by hand, not modelled here).
    """

    country: str | None = None
    _required_when_stated = ("country",)


class Reach(ConstraintField):
    """How far the search may travel — §2.6's four modes, named once here.

    Coarser than `Location`/`Relocation`: those carry the destination-level
    detail a specific offer is checked against, this carries which *kinds* of
    arrangement are in scope at all (so Sourcing knows whether to look for
    cross-border-remote roles before a single offer exists to check). A stated
    `Reach` still gates individual offers in the filter below — it is a second,
    coarser hard constraint, not a replacement for the finer-grained ones.
    """

    modes: tuple[ReachMode, ...] = ()
    _required_when_stated = ("modes",)


# The pinned field set — the whole point of this module. Order matches the
# payload's table, v1 six then v2 four, so a diff against the payload is easy
# to eyeball.
FIELD_MODELS: dict[str, type[ConstraintField]] = {
    "languages": Languages,
    "location": Location,
    "relocation": Relocation,
    "salary": Salary,
    "availability": Availability,
    "work_authorisation": WorkAuthorisation,
    "employment_mode": EmploymentMode,
    "pay_country": PayCountry,
    "tax_country": TaxCountry,
    "reach": Reach,
}
CONSTRAINT_FIELD_NAMES: tuple[str, ...] = tuple(FIELD_MODELS)


def _unknown[F: ConstraintField](model: type[F]) -> F:
    return model(state="unknown")


class CandidateConstraints(Strict):
    """`constraints.json`'s `fields` object, typed — one attribute per pinned field.

    A field absent from a raw payload is loaded as `unknown`, not omitted: the
    candidate not having reached that question yet and the candidate having
    been asked and having no answer recorded are the same fact from the
    filter's point of view, and giving the absent case a different shape would
    make every consumer handle it twice.
    """

    languages: Languages = Field(default_factory=lambda: _unknown(Languages))
    location: Location = Field(default_factory=lambda: _unknown(Location))
    relocation: Relocation = Field(default_factory=lambda: _unknown(Relocation))
    salary: Salary = Field(default_factory=lambda: _unknown(Salary))
    availability: Availability = Field(default_factory=lambda: _unknown(Availability))
    work_authorisation: WorkAuthorisation = Field(
        default_factory=lambda: _unknown(WorkAuthorisation)
    )
    employment_mode: EmploymentMode = Field(default_factory=lambda: _unknown(EmploymentMode))
    pay_country: PayCountry = Field(default_factory=lambda: _unknown(PayCountry))
    tax_country: TaxCountry = Field(default_factory=lambda: _unknown(TaxCountry))
    reach: Reach = Field(default_factory=lambda: _unknown(Reach))

    def as_dict(self) -> dict[str, ConstraintField]:
        return {name: getattr(self, name) for name in CONSTRAINT_FIELD_NAMES}

    def outstanding(self) -> tuple[str, ...]:
        """Fields still owed to T27's interview — `unknown`, never `declined`.

        `declined` is a resolved non-answer (§5.4): the candidate was asked and
        said no, and raising it again is exactly what non-insistence forbids.
        Only `unknown` — never asked, or asked and lost to a session that never
        recorded it — is still owed.
        """
        return tuple(name for name, value in self.as_dict().items() if value.state == "unknown")


def load_constraints(payload: dict[str, Any]) -> CandidateConstraints:
    """Parse a `constraints.json` payload's `fields` object.

    Raises `CandidateError` — this is a loader, and a caller that receives a
    `CandidateConstraints` back is entitled to assume every field satisfies its
    state's shape rule, not to re-check it. A field this schema does not name
    is refused rather than dropped: `_build_constraints` (T6) folds in whatever
    a constraint row is tagged with, so a stray dimension id reaching this
    loader is a real signal that T41 tagged a row with something outside the
    pinned vocabulary, not something to shrug past.
    """
    if not isinstance(payload, dict):
        raise CandidateError(f"constraints.json must be an object, got {type(payload).__name__}")
    fields = payload.get("fields", {})
    if not isinstance(fields, dict):
        raise CandidateError("constraints.json 'fields' must be an object")
    unknown_keys = sorted(set(fields) - set(FIELD_MODELS))
    if unknown_keys:
        raise CandidateError(
            f"constraints.json names field(s) outside the T24 schema: {', '.join(unknown_keys)}"
        )
    parsed: dict[str, Any] = {}
    for name, model in FIELD_MODELS.items():
        raw = fields.get(name)
        try:
            parsed[name] = model.model_validate(raw) if raw is not None else _unknown(model)
        except ValidationError as exc:
            raise CandidateError(f"constraints.json field {name!r}: {exc}") from exc
    return CandidateConstraints.model_validate(parsed)


# ---------------------------------------------------------------------------
# the offer side — just enough to check a hard constraint against


class OfferFacts(Strict):
    """The offer-side facts a hard-constraint check needs.

    Not the full §5.2 normalised offer, and not the extraction output either —
    both belong to Sourcing (T-whatever) and Understanding (T8), which this
    task does not own. This is the narrow slice the filter reads: the location
    triple already in §5.2's `offers/*.json`, plus the handful of legality
    facts §2.6 adds and the graded requirement `english_demand` extraction
    would otherwise supply. A future integration passes the real values in;
    tests here construct them directly, the same way `test_dimensions.py`
    constructs `Dimension` instances without going through a YAML file.
    """

    offer_id: str = Field(min_length=1)
    country: str = _country_field(required=True)
    delivery: Literal["remote", "hybrid", "onsite"]
    # True when physical presence in `country` is required to do the job at
    # all — distinct from `delivery != "remote"`, because a hybrid role next
    # door to the candidate needs no relocation even though it needs presence.
    requires_relocation: bool = False
    # True when the legal employer sits in a different country from the one
    # the candidate lives in, independent of `delivery` — the "foreign
    # employer while living here" case §2.6 names explicitly.
    foreign_employer: bool = False
    salary_stated: bool = False
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    english_level_required: Level | None = None
    latest_start_required: str | None = None
    employment_modes_offered: tuple[EmploymentModeName, ...] = ("employed",)
    # `None` means the ad does not say — an ad-side unknown, which (like a
    # candidate-side one) must not veto: nothing here to compare against.
    payroll_countries: tuple[str, ...] | None = None
    tax_residency_required: str | None = None
    # The subdivision the job sits in, for `Location.commutable_regions`.
    # `None` means the ad does not say — an ad-side unknown which, like
    # `payroll_countries` above, must not veto: there is nothing to compare.
    region: str | None = None


# ---------------------------------------------------------------------------
# the filter


@dataclass(frozen=True)
class Removal:
    """One offer, one field, and why the field removed it."""

    offer_id: str
    field: str
    reason: str


@dataclass(frozen=True)
class HardFilterResult:
    surviving: tuple[str, ...]
    removed: tuple[Removal, ...]
    outstanding_fields: tuple[str, ...]


def _violates_languages(field_value: Languages, offer: OfferFacts) -> str | None:
    if offer.english_level_required is None:
        return None
    have = field_value.level_of("en")
    if LEVEL_ORDER[have] < LEVEL_ORDER[offer.english_level_required]:
        return f"needs English at {offer.english_level_required!r}, candidate has {have!r}"
    return None


def _violates_location(field_value: Location, offer: OfferFacts) -> str | None:
    if offer.delivery == "remote" or offer.requires_relocation:
        return None  # remote needs no presence; a real relocation is Relocation's check
    if offer.country != field_value.country:
        return None  # a different country without relocation is not this field's job
    if not field_value.accepts_onsite_in_country:
        return "requires on-site presence in the candidate's own country, which was declined"
    if (
        field_value.commutable_regions
        and offer.region is not None
        and offer.region not in field_value.commutable_regions
    ):
        return (
            f"is on site in {offer.region}, outside the area the candidate can travel "
            f"to and from in a day ({', '.join(field_value.commutable_regions)})"
        )
    return None


def _violates_relocation(field_value: Relocation, offer: OfferFacts) -> str | None:
    if offer.delivery == "remote" or not offer.requires_relocation:
        return None
    if field_value.willingness == "no":
        return f"requires relocation to {offer.country}, candidate will not relocate"
    if field_value.willingness == "yes":
        if field_value.destinations and offer.country not in field_value.destinations:
            return (
                f"requires relocation to {offer.country}, outside the candidate's stated "
                f"destinations ({', '.join(field_value.destinations)})"
            )
        return None
    # conditional: only a per-offer confirmation turns it into a pass — see the
    # module docstring. Absent that, it filters exactly like "no".
    if offer.offer_id in field_value.confirmed_offers:
        if field_value.destinations and offer.country not in field_value.destinations:
            return (
                f"relocation condition was confirmed, but {offer.country} is outside the "
                f"candidate's stated destinations ({', '.join(field_value.destinations)})"
            )
        return None
    return (
        "requires relocation, and the candidate's willingness is conditional "
        f"({field_value.condition!r}) but that condition has not been checked against "
        "this offer"
    )


def _violates_salary(field_value: Salary, offer: OfferFacts) -> str | None:
    if not offer.salary_stated or offer.salary_max is None:
        return None  # nothing to compare — an unstated ad band, not a candidate unknown
    # The offer must say which currency its band is in. An advert that names a
    # number and no currency is not implicitly quoting the candidate's own: it
    # is a number of unknown units, and comparing it to a floor invents the
    # missing half. Both outcomes of that invention are wrong in a way nobody
    # sees — a veto silently drops a role that may well clear the floor, and a
    # pass admits one that does not. Unknown must not fabricate a hard
    # constraint result; that is the rule this whole module is built on.
    if offer.salary_currency is None or offer.salary_currency != field_value.currency:
        return None  # cannot compare across currencies without a conversion rate
    if offer.salary_max < (field_value.floor or 0):
        return (
            f"pays up to {offer.salary_max} {offer.salary_currency}, below the candidate's "
            f"floor of {field_value.floor} {field_value.currency}"
        )
    return None


def _violates_availability(field_value: Availability, offer: OfferFacts) -> str | None:
    if offer.latest_start_required is None or field_value.earliest_start is None:
        return None
    if field_value.earliest_start > offer.latest_start_required:
        return (
            f"needs someone by {offer.latest_start_required}, candidate's earliest start is "
            f"{field_value.earliest_start}"
        )
    return None


def _violates_work_authorisation(field_value: WorkAuthorisation, offer: OfferFacts) -> str | None:
    if offer.delivery == "remote" and not offer.requires_relocation:
        return None  # no physical presence, so no local work-authorisation question
    if offer.country not in field_value.authorised_countries:
        return f"requires the right to work in {offer.country}, which the candidate lacks"
    return None


def _violates_employment_mode(field_value: EmploymentMode, offer: OfferFacts) -> str | None:
    if not set(field_value.accepted) & set(offer.employment_modes_offered):
        offered = ", ".join(offer.employment_modes_offered)
        accepted = ", ".join(field_value.accepted)
        return f"offers only {offered}, candidate accepts only {accepted}"
    return None


def _violates_pay_country(field_value: PayCountry, offer: OfferFacts) -> str | None:
    if offer.payroll_countries is None:
        return None
    if not set(field_value.countries) & set(offer.payroll_countries):
        return (
            f"can only pay into {', '.join(offer.payroll_countries)}, candidate can only be "
            f"paid in {', '.join(field_value.countries)}"
        )
    return None


def _violates_tax_country(field_value: TaxCountry, offer: OfferFacts) -> str | None:
    if offer.tax_residency_required is None:
        return None
    if offer.tax_residency_required != field_value.country:
        return (
            f"requires tax residency in {offer.tax_residency_required}, candidate is tax-"
            f"resident in {field_value.country}"
        )
    return None


def _required_reach_mode(offer: OfferFacts) -> ReachMode:
    if offer.delivery == "remote" and not offer.requires_relocation:
        return "cross_border_remote_employer" if offer.foreign_employer else "remote"
    if offer.requires_relocation:
        return "relocate"
    return "commute"


def _violates_reach(field_value: Reach, offer: OfferFacts) -> str | None:
    needed = _required_reach_mode(offer)
    if needed not in field_value.modes:
        return f"needs {needed!r} in scope, candidate's search does not reach that far"
    return None


# One checker per pinned field, in the same order as `FIELD_MODELS`. A checker
# is only ever called with a field whose `state` is `stated` — see
# `filter_hard_constraints` — so none of them branch on `state` themselves.
_CHECKS: dict[str, Callable[[Any, OfferFacts], str | None]] = {
    "languages": _violates_languages,
    "location": _violates_location,
    "relocation": _violates_relocation,
    "salary": _violates_salary,
    "availability": _violates_availability,
    "work_authorisation": _violates_work_authorisation,
    "employment_mode": _violates_employment_mode,
    "pay_country": _violates_pay_country,
    "tax_country": _violates_tax_country,
    "reach": _violates_reach,
}
if set(_CHECKS) != set(FIELD_MODELS):
    # A missing checker is a schema defect, not a runtime condition to handle —
    # fail at import time rather than let a field silently never veto anything.
    raise CandidateError(
        f"a checker is missing for: {', '.join(sorted(set(FIELD_MODELS) - set(_CHECKS)))}"
    )


def filter_hard_constraints(
    constraints: CandidateConstraints, offers: Sequence[OfferFacts]
) -> HardFilterResult:
    """Remove every offer a *stated* hard constraint rules out.

    `declined` and `unknown` fields are skipped entirely — the rule this
    function exists to obey (§2.6, §3.1) is that a hard constraint the offer
    cannot satisfy removes it, and a field with no stated answer has made no
    claim to check the offer against. Skipping is not the same as passing
    silently: `outstanding_fields` names what T27 still owes, separately from
    which offers survived, so "unknown" never gets read downstream as "fine".
    """
    stated = {
        name: value for name, value in constraints.as_dict().items() if value.state == "stated"
    }
    removed: list[Removal] = []
    surviving: list[str] = []
    for offer in offers:
        reasons = [
            Removal(offer.offer_id, name, reason)
            for name, value in stated.items()
            if (reason := _CHECKS[name](value, offer)) is not None
        ]
        if reasons:
            removed.extend(reasons)
        else:
            surviving.append(offer.offer_id)
    return HardFilterResult(
        surviving=tuple(surviving),
        removed=tuple(removed),
        outstanding_fields=constraints.outstanding(),
    )


# ---------------------------------------------------------------------------
# the gate


@dataclass(frozen=True)
class _Case:
    """One adversarial check: an offer, and whether the filter must remove it."""

    name: str
    offer: OfferFacts
    must_be_removed: bool


def _baseline_constraints() -> CandidateConstraints:
    """A candidate stated on every field, permissive enough that a matching
    offer passes every check — the control every adversarial offer is a
    single-field mutation of."""
    return CandidateConstraints(
        languages=Languages(
            state="stated", levels=(LanguageLevel(language="en", level="professional"),)
        ),
        location=Location(state="stated", country="ES", accepts_onsite_in_country=True),
        relocation=Relocation(
            state="stated",
            willingness="conditional",
            destinations=("DE",),
            condition="a fully-funded relocation package and a senior title",
        ),
        salary=Salary(state="stated", floor=40000, currency="EUR"),
        availability=Availability(state="stated", earliest_start="2026-09-01"),
        work_authorisation=WorkAuthorisation(state="stated", authorised_countries=("ES", "DE")),
        employment_mode=EmploymentMode(state="stated", accepted=("employed", "contracting")),
        pay_country=PayCountry(state="stated", countries=("ES",)),
        tax_country=TaxCountry(state="stated", country="ES"),
        reach=Reach(
            state="stated",
            modes=("remote", "commute", "relocate", "cross_border_remote_employer"),
        ),
    )


def _good_offer(offer_id: str = "offer-good") -> OfferFacts:
    return OfferFacts(
        offer_id=offer_id,
        country="ES",
        delivery="remote",
        salary_stated=True,
        salary_min=45000,
        salary_max=55000,
        salary_currency="EUR",
        english_level_required="conversational",
        latest_start_required="2026-10-01",
        employment_modes_offered=("employed",),
        payroll_countries=("ES",),
        tax_residency_required="ES",
    )


def _adversarial_cases() -> list[_Case]:
    """One offer per pinned field that violates exactly that field, plus the
    two properties named in the payload's tests: an unstated field must not
    veto, and `conditional` relocation must not pass without confirmation."""
    good = _good_offer
    cases = [
        _Case(
            "languages",
            good("offer-language").model_copy(update={"english_level_required": "native"}),
            True,
        ),
        _Case(
            "location",
            good("offer-location").model_copy(
                update={"delivery": "onsite", "country": "ES", "requires_relocation": False}
            ),
            # baseline accepts_onsite_in_country=True, so a same-country onsite
            # offer should pass — this case is the mirror check, see below.
            False,
        ),
        _Case(
            "salary",
            good("offer-salary").model_copy(update={"salary_max": 30000, "salary_min": 25000}),
            True,
        ),
        _Case(
            "availability",
            good("offer-availability").model_copy(update={"latest_start_required": "2026-08-20"}),
            True,
        ),
        _Case(
            "work_authorisation",
            # `requires_relocation=False` keeps this isolated from the
            # relocation check below — a border-commute case, not a move.
            good("offer-auth").model_copy(
                update={"delivery": "onsite", "country": "FR", "requires_relocation": False}
            ),
            True,
        ),
        _Case(
            "employment_mode",
            good("offer-mode").model_copy(update={"employment_modes_offered": ("contracting",)}),
            # baseline accepts both, so this must survive — the mirror check.
            False,
        ),
        _Case(
            "pay_country",
            good("offer-pay").model_copy(update={"payroll_countries": ("US",)}),
            True,
        ),
        _Case(
            "tax_country",
            good("offer-tax").model_copy(update={"tax_residency_required": "PT"}),
            True,
        ),
        _Case(
            "reach",
            good("offer-reach").model_copy(
                update={"delivery": "remote", "foreign_employer": True, "country": "US"}
            ),
            # baseline's reach includes cross_border_remote_employer, so this
            # must survive — the mirror check.
            False,
        ),
        # The relocation field itself, unconfirmed: baseline's willingness is
        # "conditional" with DE in destinations and no confirmed offers, so a
        # relocation-requiring offer to DE must still be removed.
        _Case(
            "relocation",
            good("offer-relocate").model_copy(
                update={"delivery": "onsite", "country": "DE", "requires_relocation": True}
            ),
            True,
        ),
    ]
    return cases


def probe_hard_filter() -> dict[str, Any]:
    """Build the adversarial fixture and run it through the filter.

    Adversarial in the same spirit as `revision.probe_staleness`: this is not
    "does a happy-path offer survive", it is "does every single hard
    constraint, mutated one at a time, actually remove the offer it should —
    and does the filter refrain from removing offers it should not". A filter
    that always says "removed" would show zero leaks and prove nothing, so the
    survival-expected cases are exactly as load-bearing as the removal-expected
    ones: `unsatisfiable_hard_constraint_leaks` counts a false pass on either
    side. `cases_checked` counts real assertions made, not a guessed constant —
    a probe that claimed more coverage than it ran would be its own leak.
    """
    checks = 0
    leaks: list[str] = []

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            leaks.append(message)

    constraints = _baseline_constraints()
    cases = _adversarial_cases()
    result = filter_hard_constraints(constraints, [case.offer for case in cases])
    removed_by_offer = {removal.offer_id: removal for removal in result.removed}

    for case in cases:
        was_removed = case.offer.offer_id in removed_by_offer
        if case.must_be_removed:
            check(
                was_removed,
                f"{case.name}: an offer violating this hard constraint was not removed "
                f"({case.offer.offer_id})",
            )
        else:
            reason = removed_by_offer.get(case.offer.offer_id)
            check(
                not was_removed,
                f"{case.name}: an offer that satisfies this constraint was removed anyway "
                f"({reason.field if reason else ''}: {reason.reason if reason else ''})",
            )

    # Three fields (location, employment_mode, reach) only get a "must
    # survive" mirror case above, because the baseline is permissive on all
    # three — a genuine violation needs a *stricter* candidate, checked here
    # against its own batch rather than mixed into the shared baseline run.
    strict_location = _baseline_constraints().model_copy(
        update={"location": Location(state="stated", country="ES", accepts_onsite_in_country=False)}
    )
    onsite_home = _good_offer("offer-location-violates").model_copy(
        update={"delivery": "onsite", "country": "ES", "requires_relocation": False}
    )
    location_result = filter_hard_constraints(strict_location, [onsite_home])
    check(
        onsite_home.offer_id not in location_result.surviving,
        "location: an on-site offer in the candidate's own country was not removed despite "
        "on-site work being declined",
    )

    employed_only = _baseline_constraints().model_copy(
        update={"employment_mode": EmploymentMode(state="stated", accepted=("employed",))}
    )
    contract_only = _good_offer("offer-mode-violates").model_copy(
        update={"employment_modes_offered": ("contracting",)}
    )
    mode_result = filter_hard_constraints(employed_only, [contract_only])
    check(
        contract_only.offer_id not in mode_result.surviving,
        "employment_mode: a contracting-only offer was not removed for a candidate who "
        "accepts only employment",
    )

    no_remote = _baseline_constraints().model_copy(
        update={"reach": Reach(state="stated", modes=("commute", "relocate"))}
    )
    remote_offer = _good_offer("offer-reach-violates").model_copy(
        update={"delivery": "remote", "foreign_employer": False, "country": "ES"}
    )
    reach_result = filter_hard_constraints(no_remote, [remote_offer])
    check(
        remote_offer.offer_id not in reach_result.surviving,
        "reach: a remote offer was not removed for a candidate whose search does not "
        "reach remote work",
    )

    # The named test: an unstated attribute must neither pass nor veto. A
    # candidate with an unknown salary floor must let a starvation-wage offer
    # through (nothing to check it against) *and* must report salary as owed.
    partial = CandidateConstraints(salary=Salary(state="unknown"))
    cheap_offer = _good_offer("offer-unstated").model_copy(
        update={"salary_stated": True, "salary_min": 1, "salary_max": 1, "salary_currency": "EUR"}
    )
    unstated_result = filter_hard_constraints(partial, [cheap_offer])
    check(
        cheap_offer.offer_id in unstated_result.surviving,
        "an unstated salary floor vetoed an offer instead of admitting it",
    )
    check(
        "salary" in unstated_result.outstanding_fields,
        "an unknown salary was not reported as outstanding",
    )

    # `declined` must behave like `unknown` for filtering (no veto) but must
    # NOT be reported outstanding — re-asking a declined subject breaks §5.4.
    declined = CandidateConstraints(salary=Salary(state="declined"))
    declined_result = filter_hard_constraints(declined, [cheap_offer])
    check(
        cheap_offer.offer_id in declined_result.surviving,
        "a declined salary floor vetoed an offer instead of admitting it",
    )
    check(
        "salary" not in declined_result.outstanding_fields,
        "a declined field was reported outstanding — non-insistence broken",
    )

    # Confirming the relocation condition for one specific offer must turn a
    # removal into a survival for that offer, and only that offer.
    confirmed = _baseline_constraints().model_copy(
        update={
            "relocation": Relocation(
                state="stated",
                willingness="conditional",
                destinations=("DE",),
                condition="a fully-funded relocation package and a senior title",
                confirmed_offers=frozenset({"offer-relocate-confirmed"}),
            )
        }
    )
    confirmable = _good_offer("offer-relocate-confirmed").model_copy(
        update={"delivery": "onsite", "country": "DE", "requires_relocation": True}
    )
    still_unconfirmed = _good_offer("offer-relocate-still-open").model_copy(
        update={"delivery": "onsite", "country": "DE", "requires_relocation": True}
    )
    confirmed_result = filter_hard_constraints(confirmed, [confirmable, still_unconfirmed])
    check(
        confirmable.offer_id in confirmed_result.surviving,
        "confirming the relocation condition for one offer did not admit it",
    )
    check(
        still_unconfirmed.offer_id not in confirmed_result.surviving,
        "confirming one offer's condition leaked through to an unconfirmed offer",
    )

    return {
        "unsatisfiable_hard_constraint_leaks": len(leaks),
        "cases_checked": checks,
        "leaks": leaks,
    }


MINIMUM_CASES = 10


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `unsatisfiable_hard_constraint_leaks` and record it."""
    measured = probe_hard_filter()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.candidate [path]` → T24's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["cases_checked"] < MINIMUM_CASES:
        # A pass over nothing is not a pass — see every other T2x gate module.
        print(
            f"only {measured['cases_checked']} cases were checked (floor {MINIMUM_CASES})",
            file=sys.stderr,
        )
        return 3
    for leak in measured["leaks"]:
        print(leak, file=sys.stderr)
    return 1 if measured["leaks"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
