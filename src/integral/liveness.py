"""D-18 — an advert is verified at its source before it is offered.

Of the seven offers the test session of 2026-08-20 produced, **not one was a
live vacancy**. The two `jobtoday.com` listings answered 403; every
`tablondeanuncios.com` listing read *"Puesto ocupado"*. They had been surfaced
by a generic `WebSearch` over indexed pages, which is the whole failure in one
line: **a search index outlives the advert**. The index is a memory of a page,
and the page had moved on.

So the rule the owner set, encoded here: real searches are run *inside* the
portals, a generic web search is for discovering new portals rather than for
collecting adverts, and nothing reaches the candidate until the advert itself
has been fetched and found alive.

**Three verdicts, not two.** `live`, `dead`, and `unverified` — and the third
is the one that makes this honest. A 403 is not proof an advert is gone; it is
proof we could not look. Recording that as `dead` would tombstone a vacancy
that may be perfectly open and merely defended against robots, and a tombstone
is what stops it ever being offered again (§7.4). Both verdicts keep the offer
away from the candidate, which is what D-18 requires; only one of them claims
to know why.

**What may be presented is what was checked and found alive.** Not "what was
not found dead" — an offer nobody managed to verify is exactly the seven from
that session, and `offers_presented_without_a_liveness_check` counts them.

This module is *not* `integral.freshness`. That one is T36 — proactive
re-entry, whether to ask a returning candidate what has changed since — and its
`Offer` is a question the tool would like to ask, not a job advert. The task
that opened D-18 proposed wiring it into the sourcing path; the two share a
word and nothing else. Liveness of an advert lives here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from integral.connectors import SEARCH_SOURCE
from integral.offers import Offer

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-18.json"

Liveness = Literal["live", "dead", "unverified"]

#: Statuses that say the advert is gone, from the server itself. `410 Gone` is
#: explicit; `404` is the ordinary way a board retires a listing.
GONE_STATUSES = frozenset({404, 410})

#: Statuses that say we could not look. `403` is the one the session hit, and
#: it is deliberately *not* `dead`: an anti-bot rule and a filled vacancy are
#: indistinguishable from here, and only one of them deserves a tombstone.
BLOCKED_STATUSES = frozenset({401, 403, 429})

#: What a filled or withdrawn advert says in its own body, on the boards this
#: candidate's market actually uses. Matched on normalised text, so casing and
#: runs of whitespace do not decide whether a vacancy is open.
DEAD_PHRASES: tuple[str, ...] = (
    "puesto ocupado",
    "oferta cerrada",
    "oferta no disponible",
    "esta oferta ya no está disponible",
    "vacante cubierta",
    "position filled",
    "no longer accepting applications",
    "this job is no longer available",
    "this vacancy has closed",
)

_WHITESPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Lowercase, collapse whitespace — enough for phrase matching, no more."""
    return _WHITESPACE.sub(" ", text).strip().lower()


def dead_phrase_in(text: str) -> str | None:
    """The closure phrase the body carries, if it carries one."""
    haystack = normalise(text)
    return next((phrase for phrase in DEAD_PHRASES if phrase in haystack), None)


@dataclass(frozen=True)
class SourceCheck:
    """What fetching one advert's own page established."""

    offer_id: str
    liveness: Liveness
    reason: str

    @property
    def presentable(self) -> bool:
        """Only a checked-and-alive advert may reach the candidate."""
        return self.liveness == "live"


def read_response(offer_id: str, status: int | None, body: str | None) -> SourceCheck:
    """Turn one fetch of the advert's own URL into a verdict.

    `status is None` means the fetch never happened or never returned — which
    is `unverified`, not `live`. Nothing here defaults to alive: that default
    is precisely how seven dead adverts were presented as vacancies.
    """
    if status is None:
        return SourceCheck(offer_id, "unverified", "the advert's own page was never fetched")
    if status in GONE_STATUSES:
        return SourceCheck(offer_id, "dead", f"the source returned {status} — the advert is gone")
    if status in BLOCKED_STATUSES:
        return SourceCheck(
            offer_id,
            "unverified",
            f"the source returned {status} — we were blocked, which is not evidence the "
            "advert is gone, only that it could not be read",
        )
    if status >= 400:
        return SourceCheck(
            offer_id, "unverified", f"the source returned {status} — the page could not be read"
        )
    if body is None:
        return SourceCheck(
            offer_id, "unverified", f"the source returned {status} but no body was captured"
        )
    phrase = dead_phrase_in(body)
    if phrase is not None:
        return SourceCheck(offer_id, "dead", f"the advert's own page says {phrase!r}")
    return SourceCheck(offer_id, "live", f"fetched from source, {status}, no closure notice")


def expire(offer: Offer, check: SourceCheck) -> Offer:
    """Mark a dead advert `expired`, leaving anything else alone.

    `unverified` is not expiry — see the module docstring. It keeps the offer
    out of the candidate's list without asserting the vacancy is closed, so a
    later run that manages to read the page can still find it open.
    """
    if check.liveness == "dead" and offer.status != "expired":
        return offer.model_copy(update={"status": "expired"})
    return offer


def presentable(
    offers: Iterable[Offer], checks: Mapping[str, SourceCheck]
) -> tuple[list[Offer], list[SourceCheck]]:
    """Split offers into what may be shown and why the rest may not.

    An offer with no check at all is withheld and reported as `unverified`:
    absence of a check is the defect, so it cannot be the thing that lets an
    offer through.
    """
    shown: list[Offer] = []
    withheld: list[SourceCheck] = []
    for offer in offers:
        check = checks.get(offer.id) or SourceCheck(
            offer.id, "unverified", "no liveness check was run against the advert's own page"
        )
        if check.presentable:
            shown.append(offer)
        else:
            withheld.append(check)
    return shown, withheld


def needs_source_check(offer: Offer) -> bool:
    """Does this offer have to be verified at source before it is presented?

    Every offer does. The function exists to name *why* it is unconditional:
    the tempting exception is "a connector fetched it, so it was live" — but a
    connector reads a listing page, and a listing page is an index too, just a
    smaller one. `web_search` (D-16) is the loudest case, not the only one.
    """
    return True


def index_sourced(offer: Offer) -> bool:
    """Did a general web search produce this, rather than a board?

    D-16 gave that its own reserved `source`, which is what makes this
    answerable from the record rather than guessed from the URL.
    """
    return offer.source == SEARCH_SOURCE


# ---------------------------------------------------------------------------
# the gate


@dataclass(frozen=True)
class Scenario:
    """One way an advert can arrive, and what must happen to it."""

    name: str
    source: str
    status: int | None
    body: str | None
    expect: Liveness


#: The seven offers of 2026-08-20, generalised. Every arrival shape the session
#: produced, plus the one it never managed: an advert actually read and open.
SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "a search hit nobody fetched",
        SEARCH_SOURCE,
        None,
        None,
        "unverified",
    ),
    Scenario(
        "jobtoday, 403",
        SEARCH_SOURCE,
        403,
        None,
        "unverified",
    ),
    Scenario(
        "tablondeanuncios, puesto ocupado",
        SEARCH_SOURCE,
        200,
        "<h1>Albañil</h1><p>PUESTO OCUPADO</p>",
        "dead",
    ),
    Scenario(
        "a board listing retired at source",
        "examplejobs",
        404,
        None,
        "dead",
    ),
    Scenario(
        "a connector listing, fetched and open",
        "examplejobs",
        200,
        "<h1>Albañil</h1><p>Se busca. Jornada completa.</p>",
        "live",
    ),
)


def _offer_for(scenario: Scenario) -> Offer:
    # `hashlib`, not `hash()`: the built-in is salted per process, and an id
    # that changes between runs is drift `make evidence` would report as a
    # finding — or worse, would not, because it never reaches the file.
    digest = hashlib.sha256(scenario.name.encode("utf-8")).hexdigest()
    return Offer(
        id=f"sha256:{digest}",
        source=scenario.source,
        text=scenario.body or f"An advert that arrived as: {scenario.name}.",
    )


def probe() -> list[dict[str, Any]]:
    """Every arrival scenario, and whether it is handled as D-18 requires."""
    readings = []
    for scenario in SCENARIOS:
        offer = _offer_for(scenario)
        check = read_response(offer.id, scenario.status, scenario.body)
        shown, _ = presentable([offer], {offer.id: check})
        expired = expire(offer, check).status == "expired"
        reasons = []
        if check.liveness != scenario.expect:
            reasons.append(
                f"{scenario.name}: read as {check.liveness!r}, expected {scenario.expect!r}"
            )
        if scenario.expect != "live" and shown:
            reasons.append(f"{scenario.name}: was presentable despite being {scenario.expect}")
        if scenario.expect == "live" and not shown:
            reasons.append(f"{scenario.name}: a verified-live advert was withheld")
        if (scenario.expect == "dead") != expired:
            reasons.append(
                f"{scenario.name}: expiry was {expired}, which does not match a "
                f"{scenario.expect!r} verdict"
            )
        readings.append(
            {
                "scenario": scenario.name,
                "source": scenario.source,
                "index_sourced": index_sourced(offer),
                "liveness": check.liveness,
                "expected": scenario.expect,
                "presented": bool(shown),
                "expired": expired,
                "reason": check.reason,
                "reasons": reasons,
            }
        )
    return readings


def _unmeasured(reason: str, readings: list[dict[str, Any]]) -> dict[str, Any]:
    """The shape a reading that could not happen takes: `-1`, never `0`."""
    return {
        "offers_presented_without_a_liveness_check": -1,
        "scenarios_probed": len(readings),
        "dead_phrases_known": len(DEAD_PHRASES),
        "violations": [reason],
        "readings": readings,
    }


def measure() -> dict[str, Any]:
    """D-18's gate reading: `offers_presented_without_a_liveness_check`."""
    try:
        readings = probe()
    except Exception as exc:  # a probe that cannot run is evidence, not a crash
        return _unmeasured(f"a scenario could not be probed: {exc}", [])
    if not any(r["expected"] == "live" for r in readings):
        # Without a live scenario the check could pass by withholding
        # everything, which would be as useless to the candidate as showing
        # them seven dead adverts.
        return _unmeasured("no live scenario was probed — withholding everything would pass", [])
    violations = [reason for r in readings for reason in r["reasons"]]
    return {
        "offers_presented_without_a_liveness_check": len(violations),
        "scenarios_probed": len(readings),
        "dead_phrases_known": len(DEAD_PHRASES),
        "violations": violations,
        "readings": readings,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/D-18.json`."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.liveness [--check]`.

    Without arguments it writes the evidence file, so `make evidence` — whose
    module list is derived from `^def _main` — regenerates D-18's number with
    no flag to remember.
    """
    parser = argparse.ArgumentParser(
        description="D-18's gate: an advert is verified at source before it is offered"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence file",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/D-18.json)",
    )
    args = parser.parse_args(argv[1:])

    measured = measure() if args.check else write_evidence(Path(args.write_evidence))
    print(json.dumps(measured, ensure_ascii=False))
    for violation in measured["violations"]:
        print(violation, file=sys.stderr)
    if measured["offers_presented_without_a_liveness_check"] == -1:
        return 3
    return 1 if measured["offers_presented_without_a_liveness_check"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
