"""T94 — reduce a few hundred fetched offers to the tens worth reading.

The connector library returns volume now; the pipeline behind it was built for
the handful of adverts a manual round produced, so volume arrives and is triaged
by a person reading it. This is the cheap pass before ranking — **filter, not
rank**. Ranking is step 9 and has an owner.

## Only a hard rule may delete

Every rule here removes a row from what the candidate will ever see, so the
costly direction is the *drop*: a wrong deletion loses a real job and shows
nobody a reason, while a wrong keep costs one row of reading. Every rule is
therefore written to fire only on a fact the advert **states**, and anything
unknown is kept:

- an unstated salary is never below a floor (that is T92's subject — nobody had
  looked for the figure);
- an unstated country is not outside the permitted set;
- a stated remote arrangement keeps an offer whatever its country says;
- a currency or period this module cannot compare against the floor keeps it.

`eligibility.FLAG` is likewise a keep, not a drop — spec §5.4, "ranked, marked,
and the human is the tiebreaker". Only `FAIL` deletes.

## Stated exclusions never reach this module, by construction

T90 defines a sector distaste as **soft**: it shapes the query, and where a
strong match survives it, the survival is named. If this filter also deleted
rows on an exclusion, the two tasks would disagree about the same rule and the
stricter one would win silently — the candidate would lose a strong match with
no reason given, which is the opposite of what T90 asks for.

So `reduce` takes no exclusions argument at all. That is deliberate and is
stronger than a rule saying it must not: a function cannot apply a preference it
is never handed. `HardConstraints` carries only hard facts, and the evidence
counts how many exclusion-matching offers **survived** — an exclusion with no
counter is silence, and the growing excluded set is exactly what a counter is
for.

## Every drop names the rule that made it

A filter that cannot say why is one nobody can trust or debug. `Drop` carries
the rule and the advert's own stated fact, and `drops_with_no_rule` is measured
rather than assumed: it is the key that would catch a row disappearing down a
path nobody declared.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from integral.dedup import (
    Liveness,
    SourceKind,
    _group_duplicate_ids,
    find_duplicates,
    select_survivor,
)
from integral.eligibility import UNKNOWN_CANDIDATE, CandidateEligibility, evaluate_offer
from integral.offers import Offer

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T94.json"


#: The candidate side (`candidate._country_field`) enforces `^[A-Z]{2}$`; the ad
#: side (`offers.Location.country`) enforces nothing. This is the shape a stated
#: country must have before the two can be compared at all — anything else is
#: kept rather than guessed at.
_COMPARABLE_COUNTRY = re.compile(r"[A-Z]{2}")


class BulkFilterError(Exception):
    """A batch or a constraint set this module refuses to act on."""


Rule = Literal[
    "expired",
    "ineligible",
    "below_pay_floor",
    "outside_permitted_countries",
    "duplicate",
]

#: Named, and `len()`-counted in the evidence rather than written as a literal.
#: A denominator written as a literal drifts the moment a rule is added — the
#: `_ESTIMATE_CHECKS = 6 + …` shape that advertised 13 checks over 15 that ran.
RULES: tuple[Rule, ...] = (
    "expired",
    "ineligible",
    "below_pay_floor",
    "outside_permitted_countries",
    "duplicate",
)


@dataclass(frozen=True)
class PayFloor:
    """The least the candidate will consider, with the units to compare it in.

    `currency` and `period` are required, not optional: a bare number is not a
    floor, and comparing 30000 against a monthly figure in another currency is
    the kind of confident wrong answer this module must not produce.
    """

    amount: float
    currency: str
    period: str

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise BulkFilterError("a pay floor must be a positive amount")
        if not self.currency.strip() or not self.period.strip():
            raise BulkFilterError("a pay floor must name its currency and period")


@dataclass(frozen=True)
class HardConstraints:
    """What may delete a row. Hard facts only — see the module docstring.

    An empty `countries` means *no location rule*, not *no country permitted*.
    The distinction matters because the empty case is the default, and a default
    that silently deleted everything would be the worst possible fail-closed.
    """

    countries: frozenset[str] = frozenset()
    pay_floor: PayFloor | None = None
    eligibility: CandidateEligibility = UNKNOWN_CANDIDATE


@dataclass(frozen=True)
class Drop:
    """One removed offer, the rule that removed it, and the advert's own fact."""

    offer_id: str
    rule: Rule
    because: str


@dataclass(frozen=True)
class Reduction:
    """What survived, what did not, and why — computed fresh, never persisted."""

    kept: tuple[Offer, ...]
    dropped: tuple[Drop, ...]

    @property
    def ratio(self) -> float:
        """Share of the batch removed. 0.0 for an empty batch, never a divide."""
        total = len(self.kept) + len(self.dropped)
        return round(len(self.dropped) / total, 4) if total else 0.0


def _parse(stamp: str | None) -> datetime | None:
    """An ISO stamp, or `None` for anything this cannot read.

    Unreadable is `None` and `None` keeps the offer. A date this module cannot
    parse is not evidence that the advert expired.
    """
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _expired(offer: Offer, now: datetime) -> Drop | None:
    expires = _parse(offer.expires_at)
    if expires is None:
        return None
    if len(stamp := (offer.expires_at or "").strip()) == 10 and "T" not in stamp:
        # A date with no time means the whole of that day. Comparing against
        # midnight deleted an advert stating it closes on the 4th from 00:00 on
        # the 4th — a wrong drop, in the costly direction, for its final day.
        # Found by the second reader on #323.
        expires = expires.replace(hour=23, minute=59, second=59)
    if expires >= now:
        return None
    return Drop(offer.id, "expired", f"the advert states it expired at {offer.expires_at}")


def _ineligible(offer: Offer, candidate: CandidateEligibility) -> Drop | None:
    reading = evaluate_offer(offer, candidate)
    if reading.verdict != "FAIL":
        return None  # PASS keeps, and so does FLAG — §5.4 makes a person the tiebreaker
    # `reading.quote`, not the first requirement carrying any quote. `Reading`'s
    # own contract: "when more than one requirement is found, the worst verdict
    # wins and `reason`/`quote` report the requirement that produced it." Taking
    # the first meant an advert reading "Spanish is a plus ... you must have the
    # right to work in Germany" was dropped quoting the Spanish clause — a
    # requirement the candidate meets. The rule was right and the reason wrong,
    # which is the half "a filter that cannot say why" is about.
    # Found by the second reader on #323.
    return Drop(
        offer.id,
        "ineligible",
        reading.quote or "the advert states a requirement the candidate cannot meet",
    )


def _below_pay_floor(offer: Offer, floor: PayFloor | None) -> Drop | None:
    """Only a *stated* figure, in the floor's own currency and period, may drop.

    `salary.stated` is the field §5.2 added to keep "absent" distinct from
    "zero", and this is exactly the decision it exists for: an advert that named
    no pay is not an advert paying too little.
    """
    if floor is None or offer.salary is None or not offer.salary.stated:
        return None
    if offer.salary.currency != floor.currency or offer.salary.period != floor.period:
        return None  # not comparable — a conversion this module will not invent
    # **Only `max`.** An absent `max` on a stated band is an ad-side unknown — the
    # top of the band — not a low figure. `candidate._violates_salary` already
    # says so and returns `None` there: "nothing to compare — an unstated ad
    # band, not a candidate unknown". This read `salary.min` when `max` was
    # absent, so "from EUR 40,000" was deleted against a 50,000 floor, and the
    # two modules answered differently for the same offer — with the stricter one
    # silently winning, which is the failure this task names for exclusions
    # arriving through a different door. Found by the second reader on #323.
    best = offer.salary.max
    if best is None or best >= floor.amount:
        return None
    return Drop(
        offer.id,
        "below_pay_floor",
        f"the advert states {best:g} {floor.currency} per {floor.period}, "
        f"under the floor of {floor.amount:g}",
    )


def _outside_permitted_countries(offer: Offer, countries: frozenset[str]) -> Drop | None:
    """A stated country outside the permitted set, and no stated remote option.

    Any stated remote arrangement keeps the offer. `Location.remote` is free
    text by design — different connectors describe remote work differently — so
    this reads only whether the connector said *something*, never what it means.
    Deciding that a particular phrasing is not remote enough is a ranking
    judgement, and ranking has an owner.
    """
    if not countries or offer.location is None:
        return None
    country = (offer.location.country or "").strip()
    if not country or country in countries:
        return None
    # `Location.country` carries **no pattern** — a connector emitting "Spain",
    # "es" or "Espana" is schema-valid, while `candidate._country_field` enforces
    # `^[A-Z]{2}$` on the candidate's side. Exact membership across those two
    # vocabularies deleted every Spanish row for a candidate who permitted `ES`:
    # a whole-connector-wide deletion, not a row. So a stated country this rule
    # cannot compare is **kept**, the same way an uncomparable currency is.
    # Found by the second reader on #323.
    if not _COMPARABLE_COUNTRY.fullmatch(country):
        return None
    if (offer.location.remote or "").strip():
        return None
    return Drop(
        offer.id,
        "outside_permitted_countries",
        f"the advert states a location in {country}, with no remote arrangement named",
    )


def _duplicates(
    offers: list[Offer],
    source_kind: Mapping[str, SourceKind] | None = None,
    liveness: Mapping[str, Liveness] | None = None,
) -> list[Drop]:
    """Near-duplicates collapsed to one survivor, the earliest in input order.

    Run last, over the offers that already survived every other rule, so the
    survivor is never a row a hard rule was about to delete — which would drop
    a whole cluster instead of keeping its one good member.
    """
    matches = find_duplicates(offers)
    if not matches:
        return []
    position = {offer.id: index for index, offer in enumerate(offers)}
    by_id = {offer.id: offer for offer in offers}
    # Union-find from `dedup`, not a hand-rolled parent chain: given matches
    # (a,c) and (b,c) with no (a,b), the chain overwrote c's parent and left two
    # survivors in one cluster. And the survivor is `dedup.select_survivor`, not
    # the earliest in input order — T75 exists to stop exactly that arbitrary
    # choice, and its rule is that "liveness wins over source rank every time".
    # Keeping the earliest also re-opened T92: if the earlier copy is
    # salary-silent and the later one states the band, the band was deleted with
    # the row and salary recovery lost the donor it is built to find.
    # Found by the second reader on #323.
    groups = _group_duplicate_ids(offers, matches)
    drops: list[Drop] = []
    for group_ids in groups:
        members = sorted((by_id[one] for one in group_ids), key=lambda one: position[one.id])
        kept = select_survivor(members, source_kind=source_kind, liveness=liveness)
        drops.extend(
            Drop(one.id, "duplicate", f"near-duplicate of {kept.id}")
            for one in members
            if one.id != kept.id
        )
    return sorted(drops, key=lambda drop: position[drop.offer_id])


def reduce(
    offers: list[Offer],
    constraints: HardConstraints | None = None,
    *,
    now: datetime | None = None,
    source_kind: Mapping[str, SourceKind] | None = None,
    liveness: Mapping[str, Liveness] | None = None,
) -> Reduction:
    """The bulk pass: hard rules only, every drop naming the rule that made it.

    There is no exclusions parameter, and that is the point — see the module
    docstring. A soft preference cannot be applied by a function that is never
    given one, which is a stronger guarantee than a rule saying it must not be.
    """
    settings = constraints or HardConstraints()
    at = now or datetime.now(UTC)
    kept: list[Offer] = []
    dropped: list[Drop] = []

    for offer in offers:
        drop = (
            _expired(offer, at)
            or _ineligible(offer, settings.eligibility)
            or _below_pay_floor(offer, settings.pay_floor)
            or _outside_permitted_countries(offer, settings.countries)
        )
        if drop is None:
            kept.append(offer)
        else:
            dropped.append(drop)

    duplicate_drops = _duplicates(kept, source_kind, liveness)
    removed = {drop.offer_id for drop in duplicate_drops}
    return Reduction(
        kept=tuple(offer for offer in kept if offer.id not in removed),
        dropped=(*dropped, *duplicate_drops),
    )


# ---------------------------------------------------------------------------
# the gate — measures the mechanism over a built batch, never accuracy (D-23)


#: A sector the candidate has stated they do not want. Soft, by T90 — it shapes
#: the query and never deletes a fetched row, so the probe plants offers that
#: match it and the evidence counts how many **survived**. An exclusion this
#: module honoured by doing nothing is indistinguishable from one it never saw
#: unless the survivors are counted.
PROBE_EXCLUSION = "gambling"

PROBE_BATCH = 320

#: The date the expiry must-keep row states. Read at measure time so the row is
#: always "closing today" — the case that was deleted from 00:00 on its own
#: final day.
_TODAY = "2026-09-03"

#: How many rows `probe_batch` plants that no rule may delete. Named so the
#: denominator of `wrongly_dropped` is a floor rather than a count of the day.
MUST_KEEP_ROWS = 3

#: A floor, not the count of the day. A denominator committed as an exact value
#: drifts on an unrelated change; `>=` is what the key actually asserts.
MINIMUM_BATCH = 300


def _probe_candidate() -> CandidateEligibility:
    return CandidateEligibility(citizenships=("Argentina",), work_authorisations=("Spain",))


def _probe_constraints() -> HardConstraints:
    return HardConstraints(
        countries=frozenset({"ES", "PT"}),
        pay_floor=PayFloor(amount=30000, currency="EUR", period="year"),
        eligibility=_probe_candidate(),
    )


def probe_batch(size: int = PROBE_BATCH) -> list[Offer]:
    """A deterministic batch that exercises every rule, plus rows nothing may drop.

    Built rather than sampled: the corpus is a measurement set for extraction
    (T98) and carries no expiry, salary or citizenship fields to filter on, so a
    batch drawn from it would leave four of the five rules unexercised and the
    evidence would report a reduction nobody had tested.

    **The bodies have to differ from each other**, which is not decoration. The
    first version of this probe varied one sentence over a shared prefix, and
    `find_duplicates` — correctly — collapsed 157 of 322 rows into each other.
    The reduction ratio looked excellent and measured the fixture's own
    repetitiveness rather than the filter. Every advert below therefore draws a
    different role, city and body from rotating vocabularies, so the only
    near-duplicate in the batch is the crosspost pair planted at the end.
    """
    from integral.offers import Location, Salary, compute_offer_id

    # Six clause lists of coprime length. Two adverts repeat only when their
    # indices agree modulo 7·11·13·17·19·23, so within any batch this module
    # will ever measure, the single crosspost pair planted at the end is the
    # only near-duplicate. Two earlier attempts got this wrong in the same way
    # — lists of length 7 rotating against `kind`'s 8, then a shared seed with
    # only the last sentence varying — and both times `find_duplicates`
    # correctly collapsed the fixture, once removing 134 rows of 322. A
    # reduction ratio measured over a repetitive fixture measures the fixture.
    roles = (
        "Backend engineer",
        "Warehouse operative",
        "Geriatric assistant",
        "Site foreman",
        "Data analyst",
        "Sales representative",
        "Chef de partie",
    )
    cities = (
        "Barcelona",
        "Valencia",
        "Porto",
        "Girona",
        "Lisbon",
        "Seville",
        "Bilbao",
        "Zaragoza",
        "Braga",
        "Malaga",
        "Tarragona",
    )
    duties = (
        "You will own a service end to end, from its schema to the dashboards that watch it.",
        "The work is shift based and moves stock between the bays and the loading dock.",
        "Daily personal care for residents, alongside two nurses on each rotation.",
        "Coordinating subcontractors on a residential build and signing off each stage.",
        "Turning telemetry into weekly reports the operations team acts on.",
        "Visiting existing accounts across the region and reporting what they need next.",
        "Running the cold section during service and ordering for it the week after.",
        "Auditing supplier invoices and chasing the discrepancies to a close.",
        "Fitting and commissioning equipment on customer premises across the province.",
        "Preparing the ward for each intake and handing over to the incoming shift.",
        "Drafting the tender responses and holding the client through evaluation.",
        "Maintaining the fleet's telematics and scheduling every service window.",
        "Teaching the induction course and writing the material it runs from.",
    )
    stacks = (
        "Python and Postgres",
        "Java and Oracle",
        "Go and Kafka",
        "Ruby and MySQL",
        "C# and SQL Server",
        "Rust and Redis",
        "PHP and MariaDB",
        "Kotlin and Cassandra",
        "Elixir and Timescale",
        "Scala and Spark",
        "Swift and CoreData",
        "TypeScript and Mongo",
        "Clojure and Datomic",
        "Perl and SQLite",
        "Haskell and CockroachDB",
        "Erlang and Mnesia",
        "Lua and DynamoDB",
    )
    leads = (
        "operations manager",
        "head of engineering",
        "site director",
        "clinical lead",
        "regional supervisor",
        "kitchen manager",
        "commercial director",
        "ward sister",
        "plant foreman",
        "analytics lead",
        "store manager",
        "quality manager",
        "logistics controller",
        "practice principal",
        "depot chief",
        "programme director",
        "workshop supervisor",
        "duty officer",
        "estates lead",
    )
    perks = (
        "The canteen is subsidised and the coffee is not.",
        "Uniform and boots are provided.",
        "A cycle-to-work scheme runs every spring.",
        "The office keeps a small library.",
        "There is a season-ticket loan after probation.",
        "Lunch is covered on site days.",
        "Parking is available for those who need it.",
        "A gym membership is offered.",
        "Language classes run on Thursday evenings.",
        "The team eats together on Fridays.",
        "A hardship fund exists and is used.",
        "Long-service leave accrues from year three.",
        "Childcare vouchers are available.",
        "There is an annual outing to the coast.",
        "Headphones and a chair are yours to choose.",
        "Tea is provided, endlessly.",
        "The dog belongs to nobody in particular.",
        "A quiet room can be booked.",
        "Payday is the twenty-fifth.",
        "The building has showers.",
        "An eye test is offered yearly.",
        "Books are reimbursed without ceremony.",
        "The kitchen has a proper knife block.",
    )
    offers: list[Offer] = []

    def add(text: str, **fields: Any) -> None:
        offers.append(Offer(id=compute_offer_id(text), source="probe", text=text, **fields))

    for index in range(size):
        kind = index % 8
        # Lists of coprime length, plus an index-derived detail sentence: the
        # first attempt rotated three lists of length 7 against `kind`'s 8, so
        # every 56th advert repeated and 134 rows still collapsed as duplicates.
        # A fixture that repeats itself measures its own repetition.
        seed = (
            f"{roles[index % 7]} in {cities[index % 11]}, reference {index}. "
            f"{duties[index % 13]} The stack is {stacks[index % 17]} and the post reports "
            f"to the {leads[index % 19]}. {perks[index % 23]} "
            # Six coprime cycles are not enough on their own: `find_duplicates`
            # subtracts shingles that are boilerplate **across the batch**, so two
            # rows agreeing on a subset of clauses — the duty and the perk, say,
            # which coincide every 13·23 rows — can clear the threshold once the
            # shared scaffolding is discounted. That is why the first version of
            # this docstring was wrong to claim the planted pair was the only
            # near-duplicate, and why the evidence carried five drops nobody had
            # accounted for. This sentence is near-injective on `index`, so every
            # row owns several 8-word windows no other row has.
            f"Internal file {index}-{index * 3}-{index * 7}, desk {index % 97}, "
            f"batch {index // 7}, intake {index % 89}. "
        )
        if kind == 0:
            add(
                seed + "Applications for this posting have closed.",
                expires_at="2020-01-01T00:00:00Z",
            )
        elif kind == 1:
            add(seed + "You must have the right to work in Germany before you apply.")
        elif kind == 2:
            add(
                seed + "The band for this position is stated in the advert.",
                salary=Salary(min=18000, max=21000, currency="EUR", period="year", stated=True),
            )
        elif kind == 3:
            add(
                seed + "Attendance on site every day is required.",
                location=Location(country="DE", raw="Berlin"),
            )
        elif kind == 4:
            # Kept: the same country, but the advert names a remote arrangement.
            add(
                seed + "This role is worked fully remotely from anywhere in the EU.",
                location=Location(country="DE", raw="Berlin", remote="fully remote"),
            )
        elif kind == 5:
            # Kept: no figure stated, so no floor can be breached (T92).
            add(
                seed + "Pay is competitive and discussed at offer stage.",
                salary=Salary(currency="EUR", period="year", stated=False),
            )
        elif kind == 6:
            # Kept, and the point of the whole exclusion counter: this row carries
            # **no hard defect at all**, so anything that removes it removed it on
            # a stated preference. Built that way deliberately — an exclusion row
            # that also expired would make the counter unreadable.
            add(seed + f"The employer's customers are in the {PROBE_EXCLUSION} industry.")
        else:
            add(seed + "A straightforward posting with nothing here to object to.")

    # --- Rows this pass must NOT delete, each one a wrong drop this module has
    # actually made. Until these existed, every recorded key was blind to a wrong
    # drop: nothing counted offers that should have been kept and were not, so
    # `bulk_offers_requiring_manual_triage == 0` was a statement about bookkeeping
    # rather than about the filter. Planted by id and asserted by `wrongly_dropped`.
    # Found by the second reader on #323.
    from integral.offers import Location as _Loc
    from integral.offers import Salary as _Sal

    add(
        "Platform engineer in Sabadell. Owning the ingestion pipeline end to end. "
        "Compensation starts at twenty five thousand euros with no stated ceiling.",
        salary=_Sal(min=25000, max=None, currency="EUR", period="year", stated=True),
    )
    add(
        "Ward assistant in Tarragona for a private clinic, days and alternate weekends. "
        "The employer records its location in full rather than as a code.",
        location=_Loc(country="Spain", raw="Tarragona"),
    )
    add(
        "Kitchen porter in Mataro for a hotel group, split shifts across the season. "
        "Applications close at the end of the stated day, not at its start.",
        expires_at=_TODAY,
    )

    # Two near-duplicate crossposts of one real advert, which collapse to one.
    # `measure` checks this pair by id: "the duplicate rule fired N times" is not
    # evidence that it fired on a real duplicate, and a synthetic batch will
    # always have some incidental near-neighbours. The planted pair is the one
    # the rule is actually asserted against; the rest are counted separately.
    body = (
        "Senior platform engineer wanted for a growing team in Barcelona. "
        "You will own the deployment pipeline, the observability stack and the "
        "on-call rotation, working closely with product on what ships next. "
        "We offer a permanent contract and a hybrid week."
    )
    add(body)
    add(body + " Apply through our careers page.")
    return offers


def must_keep_ids(batch: list[Offer]) -> list[str]:
    """The planted rows no rule may delete, resolved from the batch by their text.

    Each is a wrong drop this module made before the second reader found it: a
    stated band with no `max` under the floor, a country written in full rather
    than as a code, and an advert closing at the end of today. Resolved rather
    than recomputed, so a caller passing its own offers gets an empty list and
    the assertion simply does not apply.
    """
    marks = (
        "no stated ceiling",
        "in full rather than as a code",
        "at the end of the stated day",
    )
    return [offer.id for offer in batch if any(mark in offer.text for mark in marks)]


def PLANTED_DUPLICATE_ID(batch: list[Offer]) -> str | None:
    """The id of the crosspost copy the batch plants, or `None` if absent.

    Resolved from the batch rather than recomputed, so a caller passing its own
    offers gets `None` and the planted-pair assertion simply does not apply.
    """
    tail = " Apply through our careers page."
    return next((offer.id for offer in batch if offer.text.endswith(tail)), None)


def measure(offers: list[Offer] | None = None) -> dict[str, Any]:
    """T94's gate over a built batch."""
    batch = probe_batch() if offers is None else offers
    constraints = _probe_constraints()
    reduction = reduce(batch, constraints, now=datetime(2026, 9, 3, 12, 0, tzinfo=UTC))

    by_rule: dict[str, int] = {rule: 0 for rule in RULES}
    undeclared = 0
    for drop in reduction.dropped:
        if drop.rule in by_rule:
            by_rule[drop.rule] += 1
        else:
            undeclared += 1

    unexplained = sum(1 for drop in reduction.dropped if not drop.because.strip())
    # Every row of the batch must land in exactly one bucket. A filter that
    # silently loses one has reduced nothing — it has hidden a row, and the
    # candidate is back to reading to find out which.
    settled = {offer.id for offer in reduction.kept} | {drop.offer_id for drop in reduction.dropped}
    unaccounted = len({offer.id for offer in batch} - settled)

    exclusion_rows = [offer for offer in batch if PROBE_EXCLUSION in offer.text.lower()]
    exclusion_survivors = {offer.id for offer in reduction.kept}
    planted = PLANTED_DUPLICATE_ID(batch)
    planted_keeps = set(must_keep_ids(batch))
    duplicate_drops = {drop.offer_id for drop in reduction.dropped if drop.rule == "duplicate"}
    return {
        "offers_in": len(batch),
        "offers_in_at_least": MINIMUM_BATCH,
        "offers_kept": len(reduction.kept),
        "offers_dropped": len(reduction.dropped),
        "reduction_ratio": reduction.ratio,
        "drops_by_rule": by_rule,
        "rules_declared": len(RULES),
        # A rule that never fires is a rule nobody measured. Named, so a batch
        # that stopped exercising one is a value in the record, not a silence.
        "rules_never_exercised": sorted(rule for rule, count in by_rule.items() if not count),
        # `status/plan.md`'s declared metric for this task, chosen before the
        # implementation existed. A row "requiring manual triage" is one this
        # pass did not settle: either it reached neither bucket — nobody knows
        # what became of it, the `discarded_concepts` shape — or it was dropped
        # without naming a rule or a reason, which leaves a person to work out
        # why. Both are the same failure to a candidate: volume arrived and was
        # handed back for reading.
        "bulk_offers_requiring_manual_triage": unaccounted + undeclared + unexplained,
        "offers_unaccounted_for": unaccounted,
        "drops_with_no_rule": undeclared + unexplained,
        "soft_preference_drops": sum(
            1 for offer in exclusion_rows if offer.id not in exclusion_survivors
        ),
        # The counter beside the exclusion: an exclusion honoured by doing
        # nothing looks exactly like one that was never presented.
        "soft_preference_rows_presented": len(exclusion_rows),
        # "the duplicate rule fired 6 times" is not evidence it fired on a real
        # duplicate. The planted crosspost is the assertion; a synthetic batch
        # always has some incidental near-neighbours, and they get their own key
        # rather than inflating the ratio unremarked.
        # The key every other number here was blind to: rows planted as
        # must-keeps, and whether the filter deleted any of them. A zero on
        # everything else is consistent with a filter that deletes the wrong
        # rows, because nothing else counts a wrong drop.
        "wrongly_dropped": len(planted_keeps & {drop.offer_id for drop in reduction.dropped}),
        "must_keep_rows_evaluated": len(planted_keeps),
        "must_keep_rows_at_least": MUST_KEEP_ROWS,
        "planted_duplicate_collapsed": planted is not None and planted in duplicate_drops,
        "incidental_duplicate_drops": len(duplicate_drops)
        - (1 if planted in duplicate_drops else 0),
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T94.json`."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.bulk_filter` → T94's gate evidence.

    Exit **1**, never 3, on any breach. `Makefile:58-70` maps exit 3 to
    "unmeasured (recorded)" and *continues*, so a module returning 3 on a floor
    breach does not fail `make evidence` — the fail-open shape this repo has
    found four times.
    """
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))

    failures: list[str] = []
    if measured["offers_in"] < measured["offers_in_at_least"]:
        failures.append(
            f"offers_in {measured['offers_in']} is under the floor "
            f"{measured['offers_in_at_least']} — a clean reduction over a small batch "
            "measures the batch, not the filter"
        )
    if measured["bulk_offers_requiring_manual_triage"]:
        failures.append(
            f"{measured['bulk_offers_requiring_manual_triage']} offer(s) still require "
            f"manual triage — {measured['offers_unaccounted_for']} reached neither bucket "
            f"and {measured['drops_with_no_rule']} were dropped naming no rule or reason. "
            "A filter that cannot say why is one nobody can trust or debug"
        )
    if measured["soft_preference_drops"]:
        failures.append(
            f"{measured['soft_preference_drops']} row(s) were dropped on a stated "
            "exclusion — T90 makes that soft, and it reaches the query, never a "
            "fetched row"
        )
    if measured["wrongly_dropped"]:
        failures.append(
            f"{measured['wrongly_dropped']} row(s) planted as must-keeps were deleted — "
            "the costly error for a filter that removes rows a candidate will never see "
            "is the drop, and every other key here is blind to one"
        )
    if measured["must_keep_rows_evaluated"] < measured["must_keep_rows_at_least"]:
        failures.append(
            f"only {measured['must_keep_rows_evaluated']} must-keep row(s) resolved; the floor "
            f"is {measured['must_keep_rows_at_least']} — `wrongly_dropped` over an empty set "
            "of planted rows is the clean zero an empty scan also reports"
        )
    if measured["incidental_duplicate_drops"]:
        failures.append(
            f"{measured['incidental_duplicate_drops']} row(s) were dropped as duplicates "
            "beyond the planted crosspost pair — the batch is built so no other pair is a "
            "near-duplicate, so this is either that invariant broken or a wrong drop"
        )
    if not measured["planted_duplicate_collapsed"]:
        failures.append(
            "the planted crosspost pair did not collapse — the duplicate rule's count "
            "is then a count of incidental near-neighbours, not evidence the rule works"
        )
    if measured["rules_never_exercised"]:
        failures.append(
            "rules never exercised by the probe batch: "
            f"{', '.join(measured['rules_never_exercised'])} — an unexercised rule is "
            "an unmeasured one"
        )
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
