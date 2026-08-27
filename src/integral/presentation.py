"""T44 — the offer card: a template filled from the normalised offer JSON.

Step 9: *"Presentation is half the specification, not a rendering detail. An
ordering nobody can read is not a result."* Three rules from that section are
what this module is, and each is a distinct way a card can lie.

**A provisional ranking says so, once.** L1 ranks on hard constraints and pay,
with no preference weights behind it. Shown unlabelled it reads as the tool's
considered order of the market, which is a claim nothing has earned yet —
`provisional_rankings_unlabelled` is the count of times that happens. Said once
per page, not per card: a warning repeated on every offer stops being read.

**Unknown is shown as unknown.** *"An advert silent on hours is not an advert
promising good ones."* A blank cell, a dash, or a plausible default all read as
a fact the employer stated. So does an unstated salary shown as a figure: §5.2
gives `salary.stated` precisely so an estimate cannot be laundered into a claim,
and this honours it by showing `unknown` even when `min` carries a number.

**The card is filled, not written.** *"Built once, filled fast, never assembled
a paragraph at a time by a model."* `string.Template` and nothing else, so
rendering the same offer twice is byte-identical — which is the mechanical form
of "no model wrote this", and the only form a test can check.

**The one line includes the bad part.** *"full remote, pay is good, but it is a
gun factory."* It is built from T19's drivers: the dimension that most raised
this offer's salary-equivalent total, then `but` and the one that most lowered
it, each quoting the advert's own words and priced in €/month. A line assembled
from the largest positive driver alone would be the good half of an account the
tool already has both halves of.

**Stated ceiling — `hours` and `contract` can only ever render `unknown`.**
Step 9 lists them among the bullets and §5.2's normalised offer has no field for
either, so no connector can supply one. Rendering them anyway, as `unknown`, is
the honest reading of both documents at once: the bullet the candidate was
promised is there, and it says the only true thing available. Making it say more
is a change to §5.2's offer contract, not to this template.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from string import Template
from typing import Any

from integral.eligibility import Reading
from integral.enrichment import NOT_FROM_THE_ADVERT, OutsideFinding
from integral.explain import explain
from integral.offers import Location, Offer, Salary
from integral.pay import NetEstimate
from integral.profile import ProfileRevision
from integral.rank import Candidate, rank

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T44.json"
DEFAULT_T87_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T87.json"

#: What an advert did not say. One token, so a reader learns it once and a test
#: can count it — "not stated", "n/a" and "—" scattered across four bullets are
#: four things to recognise, and one of them will eventually read as a value.
UNKNOWN = "unknown"

#: Said once per page when the ranking is L1, and never when it is not — the
#: label is a claim about *this* ranking, so it is as wrong when untrue as its
#: absence is when true. Step 9 also asks what would sharpen it, in the same line.
PROVISIONAL_LABEL = (
    "Provisional: ranked on your hard constraints and pay only — no preference "
    "weights yet. Working through step 6's paired choices is what would sharpen it."
)

#: "Show a handful at a time, not forty."
DEFAULT_LIMIT = 5

#: T87. The heading the Excluded section carries, and the marker a FLAG card
#: carries. Both are constants for the same reason `PROVISIONAL_LABEL` is: the
#: gate looks for the exact bytes the page shows, so the check cannot drift
#: from the wording by paraphrasing it.
EXCLUDED_HEADING = "Excluded"
FLAG_MARKER = "[flagged — your call]"

#: What an exclusion renders as when it arrived with no wording behind it.
#: Never silently omitted: an exclusion with no reason is the defect this
#: section's gate counts, and hiding it would make the page look correct.
NO_REASON_GIVEN = "(no reason was recorded — this is a defect, please report it)"

_CARD = Template(
    """$marker$title — $company
  pay:       $pay
  hours:     $hours
  location:  $location
  contract:  $contract
  link:      $link

  $matters
$outside"""
)


def _salary(offer: Offer) -> str:
    """§5.2's salary, or `unknown` — including when a number is present but
    `stated` is false, which is the distinction that field exists to carry."""
    salary = offer.salary
    if salary is None or not salary.stated:
        return UNKNOWN
    low, high = salary.min, salary.max
    if low is None and high is None:
        return UNKNOWN
    currency = salary.currency or ""
    period = f"/{salary.period}" if salary.period else ""
    figures = " to ".join(f"{value:,.0f}" for value in (low, high) if value is not None)
    return f"{figures} {currency}{period}".strip()


def _location(offer: Offer) -> str:
    if offer.location is None:
        return UNKNOWN
    parts = [part for part in (offer.location.raw, offer.location.remote) if part]
    return " · ".join(parts) if parts else UNKNOWN


def _matters(explanation: Mapping[str, Any] | None) -> str:
    """The one plain line, with the bad part in it.

    No drivers means nothing priced moved this offer, and saying so is a
    sentence — inventing a reason from a score would be the model-written
    paragraph the template exists to prevent.
    """
    drivers = list(explanation["drivers"]) if explanation else []
    if not drivers:
        return "Nothing the advert says has been priced yet, so there is no reason to give."

    best = max(drivers, key=lambda d: d["contribution_eur_month"])
    worst = min(drivers, key=lambda d: d["contribution_eur_month"])
    line = _phrase(best)
    if worst is not best and worst["contribution_eur_month"] < 0:
        line += f" — but {_phrase(worst)}"
    return line + "."


def _phrase(driver: Mapping[str, Any]) -> str:
    span = driver["evidence_span"] or f"{driver['dimension']} (the advert's wording was not kept)"
    return f'"{span}" ({driver["contribution_eur_month"]:+,.0f} EUR/mo)'


def card(
    offer: Offer,
    explanation: Mapping[str, Any] | None = None,
    net: NetEstimate | None = None,
    outside: Sequence[OutsideFinding] = (),
    flagged: bool = False,
) -> str:
    """One offer, as the candidate sees it. Pure: same input, same bytes.

    `outside` (T43) is what was learned about the employer that the advert does
    not say. It is a separate block under its own heading, never mixed into the
    bullets or the one line: a fact the employer stated and a fact a review site
    stated are different kinds of claim, and the whole of T43 is that the
    candidate can tell which is which. With nothing found the heading is absent
    rather than empty — "the lookup found nothing" and "no lookup ran" are
    different answers, and an empty heading asserts the first.
    """
    pay = _salary(offer)
    if net is not None:
        pay = f"{pay}\n             {net.label()}"
    return _CARD.substitute(
        # T87/§5.4: a FLAG is "ranked, marked, and the human is the
        # tiebreaker". Ranked was T79's half; marked is this one. The marker
        # sits above the title rather than in a bullet because it qualifies the
        # whole card, and a card that is *not* flagged carries no empty row —
        # "nothing to weigh up" and "this row was left blank" are different
        # claims, the same distinction `_outside_block` draws.
        marker=f"{FLAG_MARKER}\n" if flagged else "",
        title=offer.title or UNKNOWN,
        company=offer.company or UNKNOWN,
        pay=pay,
        # Step 9 asks for these bullets; §5.2's offer has no field for either.
        # See the module docstring — the honest cell is the only one available.
        hours=UNKNOWN,
        contract=UNKNOWN,
        location=_location(offer),
        # D-17: the store had `url` all along and the card dropped it, so seven
        # offers were shown with nothing to click. Absent renders as `unknown`
        # like every other bullet — a row left out reads as "there was nothing
        # to show", which the candidate cannot tell from a card with no link
        # field at all.
        link=offer.url or UNKNOWN,
        matters=_matters(explanation),
        outside=_outside_block(outside),
    )


def _outside_block(findings: Sequence[OutsideFinding]) -> str:
    if not findings:
        return ""
    lines = "\n".join(f"    - {finding.cite()}" for finding in findings)
    # The heading carries the marker once; `cite()` leaves it off each line and
    # keeps the source. `label()` is for anywhere a finding appears alone.
    return f"\n  {NOT_FROM_THE_ADVERT.capitalize()}:\n{lines}\n"


def _excluded_block(excluded: Sequence[Mapping[str, Any]], by_id: Mapping[str, Offer]) -> str:
    """The **Excluded** section: what was removed, and the advert's own sentence
    it was removed for.

    Rendered from the reading, never assembled — D-17's lesson for the card
    applies here too, and the `quote` is a verbatim advert span T77 already
    guarantees. Nothing here recomputes a verdict: the page shows what the gate
    decided, and a page that decided for itself would be a second gate nobody
    gated.

    **Never truncated.** The cards are cut to `limit` because the candidate
    wants the best few; the exclusions are the opposite case — the whole reason
    they are shown is that nothing was dropped quietly, so cutting the list
    would reintroduce exactly what the section exists to close. The count is
    stated in the heading as well, so it is read rather than counted.
    """
    if not excluded:
        return ""
    lines = []
    for entry in excluded:
        offer = by_id.get(str(entry.get("offer_id")))
        name = (offer.title if offer is not None else None) or str(entry.get("offer_id"))
        quote = (entry.get("quote") or "").strip()
        reason = entry.get("reason") or UNKNOWN
        cited = f'"{quote}"' if quote else NO_REASON_GIVEN
        lines.append(f"  - {name} ({reason}): {cited}")
    return "\n".join(
        [
            "",
            f"{EXCLUDED_HEADING} ({len(excluded)}) — you cannot apply for these, "
            "and this is the wording each was removed for:",
            *lines,
        ]
    )


def render(
    ranking: Mapping[str, Any],
    offers: Sequence[Offer],
    *,
    explanations: Mapping[str, Mapping[str, Any]],
    nets: Mapping[str, NetEstimate] | None = None,
    outside: Mapping[str, Sequence[OutsideFinding]] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> str:
    """The page: the provisional line when it is true, then a handful of cards.

    Raises `KeyError` on a frontier offer nobody supplied. Skipping it would
    render a shorter list than the ranking says it ranked, which is the one
    failure a page of offers must not be able to have quietly.
    """
    if limit < 0:
        # `frontier[:-1]` silently drops the last offer and reports "0 more not
        # shown", which is a page that lies about its own completeness.
        raise ValueError(f"limit must not be negative; got {limit}")
    by_id = {offer.id: offer for offer in offers}
    frontier = list(ranking["pareto"])
    # Checked over the whole frontier, not over the page. Validating only the
    # slice makes the check depend on `limit`: a missing offer at position six
    # of five renders "(1 more not shown.)" and nobody ever finds out. The page
    # is a claim about the ranking, so what has to be complete is the ranking.
    missing = [offer_id for offer_id in frontier if offer_id not in by_id]
    if missing:
        raise KeyError(f"{len(missing)} ranked offer(s) were not supplied: {', '.join(missing)}")
    shown = frontier[:limit]
    remaining = len(frontier) - len(shown)
    flagged = set(ranking.get("flagged", ()))

    lines: list[str] = []
    if ranking["level"] == "L1":
        lines += [PROVISIONAL_LABEL, ""]
    lines += [
        card(
            by_id[offer_id],
            explanations.get(offer_id),
            (nets or {}).get(offer_id),
            # Keyed by offer, because a finding is about one employer. Without
            # this the block `card` can render is reachable only by calling
            # `card` directly, and the page — the thing the candidate actually
            # reads — could never show what the lookup found.
            (outside or {}).get(offer_id, ()),
            offer_id in flagged,
        )
        for offer_id in shown
    ]
    if remaining > 0:
        lines.append(f"({remaining} more not shown.)")
    excluded = list(ranking.get("excluded", ()))
    if excluded:
        lines.append(_excluded_block(excluded, by_id))
    return "\n".join(lines)


def provisional_rankings_unlabelled(
    renderings: Sequence[tuple[Mapping[str, Any], str]],
) -> int:
    """How many L1 pages were shown without saying they were provisional.

    `startswith`, not `in`. The label is a header — `render` puts it first and
    nowhere else — and a substring search over the whole page passes as soon as
    any card happens to contain the sentence, in a title, an employer name, or
    an evidence span quoted from an advert. That is not far-fetched for a
    sentence about ranking on pay alone, and it would report an unlabelled
    provisional page as labelled, which is the one thing this number is for.
    """
    return sum(
        1
        for ranking, page in renderings
        if ranking["level"] == "L1" and not page.startswith(PROVISIONAL_LABEL)
    )


_FIXTURE_DIMENSIONS = ("commute", "remote")
_FIXTURE_WEIGHTS: dict[str, Any] = {
    "currency": "EUR",
    "part_worths": {
        "commute": {"utility_per_unit": 0.30, "salary_equivalent_per_month": 200.0},
        "remote": {"utility_per_unit": 0.90, "salary_equivalent_per_month": 600.0},
    },
    "negligible": [],
    "separated": False,
    "salary_utility_per_month": 0.0015,
}
# One advert states its pay and where it is; the other states neither. Both
# shapes have to be in the fixture or the measurement never sees a filled bullet
# next to an empty one, and "unknown is shown as unknown" would be measured on a
# page where everything was unknown anyway.
_FIXTURE_OFFERS: tuple[
    tuple[
        str,
        str,
        str,
        str | None,
        float,
        Salary | None,
        Location | None,
        dict[str, float],
        dict[str, str],
    ],
    ...,
] = (
    (
        "Backend engineer",
        "Remota SL",
        "Backend en Python, 100% en remoto, sin oficina.",
        "https://example.invalid/offers/backend",
        3600.0,
        Salary(min=42000.0, max=48000.0, currency="EUR", period="year", stated=True),
        Location(raw="Barcelona", country="ES", remote="full"),
        {"remote": 1.0, "commute": -0.5},
        {"remote": "100% en remoto, sin oficina", "commute": "un dia al mes a Madrid"},
    ),
    (
        "Platform engineer",
        "Presencial SA",
        "Plataforma, presencial en nuestras oficinas de Barcelona.",
        None,
        4200.0,
        None,
        None,
        {"remote": -1.0, "commute": 0.8},
        {"remote": "presencial en nuestras oficinas", "commute": "junto a la estación"},
    ),
)


def _fixture() -> tuple[list[Offer], list[Candidate]]:
    from integral.offers import compute_offer_id

    offers: list[Offer] = []
    candidates: list[Candidate] = []
    for title, company, text, url, monthly, salary, location, scores, spans in _FIXTURE_OFFERS:
        offer = Offer(
            id=compute_offer_id(text),
            source="fixture",
            title=title,
            company=company,
            text=text,
            language="es",
            url=url,
            salary=salary,
            location=location,
        )
        offers.append(offer)
        candidates.append(
            Candidate(
                offer_id=offer.id,
                salary_per_month=monthly,
                scores=scores,
                unknown=frozenset(n for n in _FIXTURE_DIMENSIONS if n not in scores),
                spans={name: (quote,) for name, quote in spans.items()},
            )
        )
    return offers, candidates


def _page(weights: Mapping[str, Any] | None) -> tuple[dict[str, Any], str]:
    offers, candidates = _fixture()
    ranking = rank(
        candidates,
        dimensions=_FIXTURE_DIMENSIONS,
        revision=ProfileRevision(rows=len(candidates), sha256="0" * 64),
        weights=weights,
        at="2026-08-24T00:00:00Z",
    )
    explanations = explain(ranking, candidates, weights)
    return ranking, render(ranking, offers, explanations=explanations)


def _bullet(page: str, name: str, card_index: int) -> str:
    """The value of one named bullet on the `card_index`-th card of a page."""
    values = [
        line.split(":", 1)[1].strip()
        for line in page.splitlines()
        if line.strip().startswith(f"{name}:")
    ]
    return values[card_index]


def _urls_dropped(limit: int = DEFAULT_LIMIT) -> int:
    """Rendered offers whose stored `url` never reached their own card (D-17).

    Scoped to the offers that actually got a card, and checked against that
    card rather than against the whole page. A dominated or truncated offer has
    no card *by design*, so counting it as a dropped URL would report the
    frontier working as this bug; and a page-wide substring test passes as soon
    as some *other* card carries the same or a longer URL, which is the shape a
    check on a page of near-identical adverts would eventually hit.
    """
    offers, candidates = _fixture()
    ranking, _ = _page(_FIXTURE_WEIGHTS)
    by_id = {offer.id: offer for offer in offers}
    explanations = explain(ranking, candidates, _FIXTURE_WEIGHTS)

    dropped = 0
    for offer_id in ranking["pareto"][:limit]:
        offer = by_id[offer_id]
        if offer.url and offer.url not in card(offer, explanations.get(offer_id)):
            dropped += 1
    return dropped


def measure() -> dict[str, Any]:
    """The gate's number, and proof it can rise."""
    provisional, provisional_page = _page(None)
    weighted, weighted_page = _page(_FIXTURE_WEIGHTS)
    unlabelled = provisional_rankings_unlabelled(
        [(provisional, provisional_page), (weighted, weighted_page)]
    )

    # Strip the label off the L1 page. If the count does not rise, it is not
    # reading the page at all and a zero certifies the fixture, not the code.
    planted = provisional_rankings_unlabelled(
        [(provisional, provisional_page.replace(PROVISIONAL_LABEL, ""))]
    )

    return {
        "provisional_rankings_unlabelled": unlabelled,
        "unlabelled_detected_when_planted": planted,
        "rankings_rendered": 2,
        "provisional_rankings": 1,
        "renders_are_deterministic": int(_page(None)[1] == provisional_page),
        # Named per field, not `UNKNOWN in page`. `hours` and `contract` are
        # unconditionally unknown (§5.2 has no field for either), so a page-wide
        # search for the word is true no matter what the salary and location
        # cells do — and the property would keep passing while exactly the
        # fields it is about stopped rendering. So each bullet is read off its
        # own line, on the advert that states it and the one that does not.
        "stated_bullets_render_their_value": int(
            _bullet(weighted_page, "pay", 0) == "42,000 to 48,000 EUR/year"
            and _bullet(weighted_page, "location", 0) == "Barcelona · full"
        ),
        "unstated_bullets_render_unknown": int(
            _bullet(weighted_page, "pay", 1) == UNKNOWN
            and _bullet(weighted_page, "location", 1) == UNKNOWN
        ),
        # D-17 was invisible because nothing counted it. What is counted is the
        # defect itself — a record that *has* a URL whose card does not show it —
        # not the offers that genuinely have none. An advert with no link is a
        # gap in the source; a link the store held and the card dropped is this
        # bug, and only the second is something this module can commit.
        "ranked_offers_without_a_url": _urls_dropped(),
        "offers_with_no_url_in_the_store": sum(1 for offer in _fixture()[0] if not offer.url),
    }


# ---------------------------------------------------------------------------
# T87 — the Excluded section, measured on the page the candidate reads


#: T87's own fixture, deliberately separate from T44's. Four adverts: two state
#: a hard bar the candidate cannot meet, one states a soft preference, one
#: states nothing. Every `quote` below is a verbatim slice of the `text` beside
#: it, and `measure_exclusions_shown` asserts that rather than trusting it — a
#: section whose whole claim is "these are the advert's own words" cannot be
#: measured against wording invented for the measurement.
_T87_FIXTURE: tuple[tuple[str, str, str, str, str, str | None, str | None], ...] = (
    (
        "Backend engineer",
        "Alemana GmbH",
        "Backend en Python, 100% en remoto. Applicants must hold German citizenship.",
        "https://example.invalid/offers/backend",
        "FAIL",
        "citizenship",
        "must hold German citizenship",
    ),
    (
        "SRE",
        "Clearance Ltd",
        "SRE para infraestructura crítica. Must hold an active TS/SCI clearance.",
        "https://example.invalid/offers/sre",
        "FAIL",
        "clearance",
        "Must hold an active TS/SCI clearance",
    ),
    (
        "Platform engineer",
        "Segura SL",
        "Plataforma en Barcelona. An active security clearance is a plus.",
        "https://example.invalid/offers/platform",
        "FLAG",
        "clearance",
        "An active security clearance is a plus",
    ),
    (
        "Data engineer",
        "Abierta SA",
        "Datos en remoto. Sin requisitos de nacionalidad ni de permiso.",
        "https://example.invalid/offers/data",
        "PASS",
        None,
        None,
    ),
)


def _t87_fixture() -> tuple[list[Offer], list[Candidate], list[Reading]]:
    from integral.offers import compute_offer_id

    offers: list[Offer] = []
    candidates: list[Candidate] = []
    readings: list[Reading] = []
    for index, (title, company, text, url, verdict, reason, quote) in enumerate(_T87_FIXTURE):
        offer_id = compute_offer_id(text)
        offers.append(
            Offer(
                id=offer_id,
                source="fixture",
                url=url,
                title=title,
                company=company,
                text=text,
                language="es",
                salary=Salary(
                    min=36000.0 + 1000 * index, max=None, currency="EUR", period="year", stated=True
                ),
                location=Location(raw="Barcelona", country="ES", remote="full"),
            )
        )
        candidates.append(
            Candidate(
                offer_id=offer_id,
                salary_per_month=3000.0 + 100 * index,
                scores={"remote": 1.0 - 0.2 * index, "commute": -0.1 * index},
            )
        )
        readings.append(
            Reading(
                offer_id=offer_id,
                verdict=verdict,  # type: ignore[arg-type]
                reason=reason,  # type: ignore[arg-type]
                quote=quote,
                requirements=(),
            )
        )
    return offers, candidates, readings


def _t87_page(limit: int = DEFAULT_LIMIT) -> tuple[dict[str, Any], str]:
    offers, candidates, readings = _t87_fixture()
    ranking = rank(
        candidates,
        dimensions=("commute", "remote"),
        revision=ProfileRevision(rows=len(candidates), sha256="0" * 64),
        weights=_FIXTURE_WEIGHTS,
        at="2026-08-27T00:00:00Z",
        readings=readings,
    )
    return ranking, render(
        ranking, offers, explanations=explain(ranking, candidates, _FIXTURE_WEIGHTS), limit=limit
    )


def excluded_offers_missing_from_the_page(
    renderings: Sequence[tuple[Mapping[str, Any], str]],
) -> int:
    """Exclusions the ranking made that the page did not show, with wording.

    An exclusion counts as shown only when its **verbatim quote** appears on the
    page. Checking for the offer id, or for the heading, would pass a section
    that listed what was removed and not why — and the reason a barred offer is
    shown at all is that a false FAIL is invisible by construction. A verdict
    the candidate cannot trace to a sentence in the advert is one they cannot
    dispute.
    """
    return sum(
        1
        for ranking, page in renderings
        for entry in ranking.get("excluded", ())
        if not (entry.get("quote") or "").strip() or str(entry["quote"]).strip() not in page
    )


def _unmeasured_exclusions(reason: str) -> dict[str, Any]:
    return {
        "excluded_offers_missing_from_the_page": -1,
        "excluded_offers_missing_from_the_page_evaluated": 0,
        "gate_status": "unmeasured",
        "reason": reason,
    }


def measure_exclusions_shown() -> dict[str, Any]:
    """T87's numbers: exclusions rendered with their wording, and proof the
    count can rise."""
    offers, _, readings = _t87_fixture()
    text_by_id = {offer.id: offer.text for offer in offers}
    for reading in readings:
        if reading.quote is not None and reading.quote not in text_by_id[reading.offer_id]:
            # The fixture, not the code, would be the thing at fault — and a
            # gate that measured invented wording would certify nothing.
            raise ValueError(f"fixture quote is not a span of its advert: {reading.quote!r}")

    ranking, page = _t87_page()
    excluded = list(ranking["excluded"])
    if not excluded:
        return _unmeasured_exclusions("the ranking excluded nothing, so the section showed nothing")

    missing = excluded_offers_missing_from_the_page([(ranking, page)])
    # Take the section off the page. If the count does not rise, it is not
    # reading the page and a zero certifies the fixture rather than the code.
    stripped = page.split(f"\n{EXCLUDED_HEADING} (")[0]
    planted = excluded_offers_missing_from_the_page([(ranking, stripped)])

    flagged = list(ranking["flagged"])
    carded = [offer_id for offer_id in ranking["pareto"][:DEFAULT_LIMIT]]
    return {
        "excluded_offers_missing_from_the_page": missing,
        "excluded_offers_missing_from_the_page_evaluated": len(excluded),
        "missing_detected_when_the_section_is_removed": int(planted > missing),
        # The heading states the number rather than leaving it to be counted,
        # and the section is never cut to `limit` — D-18's rule is that the
        # withheld count is reported, and a truncated list under a correct
        # count is the same silence with a number on top.
        "excluded_count_stated_on_the_page": int(f"{EXCLUDED_HEADING} ({len(excluded)})" in page),
        "excluded_offers_carded": sum(
            1
            for entry in excluded
            if (url := next((o.url for o in offers if o.id == entry["offer_id"]), None))
            and url in page
        ),
        # §5.4's other half: a FLAG is ranked *and* marked.
        "flagged_offers_marked": sum(
            1 for offer_id in flagged if offer_id in carded and FLAG_MARKER in page
        ),
        "flagged_offers_evaluated": len(flagged),
        "gate_status": "measured",
        "excluded": excluded,
    }


def write_exclusion_evidence(evidence: Path = DEFAULT_T87_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure_exclusions_shown()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Measure T44's ranking presentation.")
    parser.add_argument("evidence", nargs="?", default=str(DEFAULT_EVIDENCE_PATH), type=Path)
    args = parser.parse_args(argv)
    measured = write_evidence(args.evidence)

    print(f"provisional_rankings_unlabelled: {measured['provisional_rankings_unlabelled']} (== 0)")
    if measured["provisional_rankings_unlabelled"] != 0:
        return 1
    if not measured["unlabelled_detected_when_planted"]:
        print("the count did not rise when the label was removed", file=sys.stderr)
        return 1
    if not measured["renders_are_deterministic"]:
        print("rendering the same ranking twice produced different bytes", file=sys.stderr)
        return 1
    if not measured["stated_bullets_render_their_value"]:
        print("a bullet the advert states is no longer showing what it says", file=sys.stderr)
        return 1
    if not measured["unstated_bullets_render_unknown"]:
        print(
            "a bullet the advert does not state is no longer showing `unknown` — "
            "an advert silent on it is not an advert promising anything about it",
            file=sys.stderr,
        )
        return 1

    # T87 rides beside T44 rather than replacing it — one module, two gates,
    # two evidence files.
    shown = write_exclusion_evidence(args.evidence.parent / "T87.json")
    print(
        "excluded_offers_missing_from_the_page: "
        f"{shown['excluded_offers_missing_from_the_page']} (== 0)"
    )
    if shown["gate_status"] != "measured":
        print(f"T87 cannot be scored: {shown['reason']}", file=sys.stderr)
        return 1
    if shown["excluded_offers_missing_from_the_page"] != 0:
        return 1
    if not shown["missing_detected_when_the_section_is_removed"]:
        print("the count did not rise when the Excluded section was removed", file=sys.stderr)
        return 1
    if not shown["excluded_count_stated_on_the_page"]:
        print("the page did not state how many offers were excluded", file=sys.stderr)
        return 1
    if shown["excluded_offers_carded"]:
        print(
            "an excluded offer was rendered as a card the candidate might apply for",
            file=sys.stderr,
        )
        return 1
    if shown["flagged_offers_marked"] != shown["flagged_offers_evaluated"]:
        print("a flagged offer was carded without its marker", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
