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
DEFAULT_IDENTITY_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T74.json"

Liveness = Literal["live", "dead", "unverified"]

#: Statuses that say the advert is gone, from the server itself. `410 Gone` is
#: explicit; `404` is the ordinary way a board retires a listing.
GONE_STATUSES = frozenset({404, 410})

#: Statuses that say we could not look. `403` is the one the session hit, and
#: it is deliberately *not* `dead`: an anti-bot rule and a filled vacancy are
#: indistinguishable from here, and only one of them deserves a tombstone.
BLOCKED_STATUSES = frozenset({401, 403, 429})

#: Statuses that answer about some *other* page, or about the past. A board
#: retiring an advert commonly 301s it to a generic listings page, which
#: renders perfectly and says nothing about the vacancy; `304 Not Modified` is
#: a statement about a cache, not about today. Neither is evidence of life, so
#: the caller must follow the redirect and hand back the final response.
INDIRECT_STATUSES = frozenset({301, 302, 303, 304, 307, 308})

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


def title_in_body(title: str, body: str) -> bool:
    """Does the fetched page mention the offer's own title, tolerantly?

    Casefold and collapse whitespace, then a plain substring test — no more.
    A listing page that renders unrelated roles will not carry this vacancy's
    title anywhere in it, which is what tells the fragment-anchor case (T74)
    apart from the advert itself: the URL never changed, so `same_page`
    passes, and only the content says this is a different page. Strict would
    be worse than useless here — a title match that trips on markup or
    punctuation turns live adverts into `unverified`, and the candidate sees
    nothing, which is the failure this exists to fix, reproduced.
    """
    return normalise(title) in normalise(body)


#: Statuses that mean the record is retired. Liveness answers "is the advert
#: still there", never "should this candidate see it" — so a `live` verdict on
#: a retired record must not put it back in the list. Showing one would also
#: contradict the record itself, which still reads `expired`.
RETIRED_STATUSES: frozenset[str] = frozenset({"expired", "archived"})


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


def same_page(a: str | None, b: str | None) -> bool:
    """Do two URLs name the same page, ignoring a fragment or trailing slash?"""
    if a is None or b is None:
        return True  # nothing to compare — `read_response` decides what that means
    return a.split("#", 1)[0].rstrip("/") == b.split("#", 1)[0].rstrip("/")


def read_response(
    offer_id: str,
    status: int | None,
    body: str | None,
    *,
    advert_url: str | None = None,
    final_url: str | None = None,
    title: str | None = None,
) -> SourceCheck:
    """Turn one fetch of the advert's own URL into a verdict.

    `status is None` means the fetch never happened or never returned — which
    is `unverified`, not `live`. Nothing here defaults to alive: that default
    is precisely how seven dead adverts were presented as vacancies.

    `final_url` is where the fetch actually landed after redirects. A board
    retiring an advert commonly sends it to a generic listings page, which
    answers 200, carries no closure phrase, and is not the advert: following
    the redirect fixes the status code and not the problem. When the landing
    page is a different page from the one asked for, the verdict is
    `unverified` — we read something, but not this vacancy.

    `title` is the offer's own title, and it is checked even when the URL
    never moved (T74): a stored URL can fetch 200 at the address it always
    had and still render a listings page rather than the advert — a fragment
    anchor (`#ikerian`) is never sent to the server, so the redirect check
    above sees nothing wrong. Only the content says otherwise. `title=None`
    skips the check rather than failing it: an offer this module cannot name
    a title for gives the identity check nothing to compare, and refusing to
    guess is safer than manufacturing a mismatch.
    """
    if advert_url is not None and final_url is not None and not same_page(advert_url, final_url):
        return SourceCheck(
            offer_id,
            "unverified",
            f"the fetch landed on {final_url} rather than the advert at {advert_url} — "
            "that is some other page, not this vacancy",
        )
    if status is None:
        return SourceCheck(offer_id, "unverified", "the advert's own page was never fetched")
    if status in GONE_STATUSES:
        return SourceCheck(offer_id, "dead", f"the source returned {status} — the advert is gone")
    if status in INDIRECT_STATUSES:
        return SourceCheck(
            offer_id,
            "unverified",
            f"the source returned {status} — that describes another page or a cache, not this "
            "advert; follow it and check the final response",
        )
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
    if title is not None and not title_in_body(title, body):
        return SourceCheck(
            offer_id,
            "unverified",
            f"the page does not mention {title!r} — the URL checks out but this reads as "
            "some other page, not the advert",
        )
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
        if offer.status in RETIRED_STATUSES:
            withheld.append(
                SourceCheck(
                    offer.id,
                    check.liveness,
                    f"the record is {offer.status} — liveness does not un-retire an offer, "
                    "whatever the source now says",
                )
            )
        elif check.presentable:
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
    advert_url: str | None = None
    final_url: str | None = None
    #: The offer's own title, when this scenario is meant to exercise T74's
    #: page-identity check. `None` for every arrival shape that predates it —
    #: those keep testing D-18 alone, exactly as before.
    title: str | None = None


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
        "a retired advert redirected to the listings page",
        SEARCH_SOURCE,
        302,
        "<h1>Ofertas de empleo</h1><p>Encuentra tu próximo trabajo</p>",
        "unverified",
    ),
    Scenario(
        "a retired advert whose redirect lands on the listings page",
        SEARCH_SOURCE,
        200,
        "<h1>Ofertas de empleo</h1><p>Encuentra tu próximo trabajo</p>",
        "unverified",
        advert_url="https://board.example.com/oferta/12345",
        final_url="https://board.example.com/ofertas",
    ),
    Scenario(
        "a connector listing, fetched and open",
        "examplejobs",
        200,
        "<h1>Albañil</h1><p>Se busca. Jornada completa.</p>",
        "live",
        title="Albañil",
    ),
    # T74 — page identity, not only the URL. The two below are the
    # fragment-anchor and generic-mismatch shapes; the "connector listing"
    # scenario above now doubles as their live counterpart, so the identity
    # check has both a violation shape and a still-live shape to prove
    # against, the same as every other verdict here.
    Scenario(
        "a fragment anchor lands on the listings page",
        SEARCH_SOURCE,
        200,
        "<h1>Ofertas de empleo</h1><p>Explora nuestras vacantes en el sector servicios</p>",
        "unverified",
        advert_url="https://board.example.com/jobs/ciso/#ikerian",
        final_url="https://board.example.com/jobs/ciso/#ikerian",
        title="CISO",
    ),
    Scenario(
        "a page whose title does not match the offer",
        "examplejobs",
        200,
        "<h1>Recepcionista</h1><p>Media jornada, turno de tarde.</p>",
        "unverified",
        title="Ingeniero de Datos",
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
        title=scenario.title,
        text=scenario.body or f"An advert that arrived as: {scenario.name}.",
    )


def probe() -> list[dict[str, Any]]:
    """Every arrival scenario, and whether it is handled as D-18 requires."""
    readings = []
    for scenario in SCENARIOS:
        offer = _offer_for(scenario)
        check = read_response(
            offer.id,
            scenario.status,
            scenario.body,
            advert_url=scenario.advert_url,
            final_url=scenario.final_url,
            title=offer.title,
        )
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
                "title": offer.title,
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


def _identity_unmeasured(reason: str, readings: list[dict[str, Any]]) -> dict[str, Any]:
    """The shape a reading that could not happen takes: `-1`, never `0`."""
    return {
        "offers_presented_from_a_page_that_is_not_the_advert": -1,
        "offers_presented_from_a_page_that_is_not_the_advert_evaluated": 0,
        "pages_checked": 0,
        "gate_status": "unmeasured",
        "violations": [reason],
        "readings": readings,
    }


def measure_page_identity(readings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """T74's gate reading: `offers_presented_from_a_page_that_is_not_the_advert`.

    Reads off the same scenarios `measure()` probes rather than running a
    second fetch cycle — a scenario either carries a `title` to check page
    identity against or it does not, and only the ones that do count toward
    this gate's denominator. `readings=None` (every real caller) draws them
    from `probe()`; a caller may pass its own list to prove the empty-input
    case cannot pass — see `test_the_gate_does_not_pass_on_an_empty_input_set`.

    A zero-violation count over zero evaluated pages is indistinguishable
    from a genuine pass unless something separates them: `gate_status` is
    that something, `"unmeasured"` whenever nothing was evaluated and
    `"measured"` otherwise, so the gate block's `status-key` can refuse to
    score a run that checked nothing rather than reading it as a clean one.
    """
    if readings is None:
        try:
            readings = probe()
        except Exception as exc:  # a probe that cannot run is evidence, not a crash
            return _identity_unmeasured(f"a scenario could not be probed: {exc}", [])
    evaluated = [r for r in readings if r.get("title") is not None]
    if not evaluated:
        return _identity_unmeasured(
            "no scenario carried a title to check page identity against — nothing was evaluated",
            list(readings),
        )
    violations = [
        f"{r['scenario']}: presented although the page read as {r['liveness']!r}, not the advert"
        for r in evaluated
        if r["presented"] and r["liveness"] != "live"
    ]
    return {
        "offers_presented_from_a_page_that_is_not_the_advert": len(violations),
        "offers_presented_from_a_page_that_is_not_the_advert_evaluated": len(evaluated),
        "pages_checked": len(evaluated),
        "gate_status": "measured",
        "violations": violations,
        "readings": evaluated,
    }


def write_page_identity_evidence(evidence: Path = DEFAULT_IDENTITY_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T74.json`, beside D-18's own file.

    A separate file, not a key folded into D-18.json: the gate block names
    `status/evidence/T74.json` directly, and CA-12's rule is that a gate must
    never name a file no module produces.
    """
    measured = measure_page_identity()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.liveness [--check] [--identity] [path]`.

    Bare invocation writes **both** evidence files, D-18's and T74's — the
    same reason `dimensions.py` writes T2, T3 and T23 on a bare run: `make
    evidence` derives its module list from `^def _main` and runs each module
    once, with no way to know a module owns more than one gate. Naming
    `--identity` still writes T74 alone, so that gate block's own invocation
    stays precise.
    """
    identity = "--identity" in argv[1:]
    check = "--check" in argv[1:]
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]

    if not identity and not positional:
        # Each recursive call carries a positional path (or `--identity`) so
        # it lands past this branch rather than back in it — otherwise a bare
        # `python -m integral.liveness` would recurse into itself forever.
        identity_rc = _main([argv[0], "--identity", *(["--check"] if check else [])])
        liveness_rc = _main(
            [argv[0], str(DEFAULT_EVIDENCE_PATH), *(["--check"] if check else [])]
        )
        return max(identity_rc, liveness_rc)

    if identity:
        target = Path(positional[0]) if positional else DEFAULT_IDENTITY_EVIDENCE_PATH
        measured_identity = (
            measure_page_identity() if check else write_page_identity_evidence(target)
        )
        print(json.dumps(measured_identity, ensure_ascii=False))
        for violation in measured_identity["violations"]:
            print(violation, file=sys.stderr)
        if measured_identity["gate_status"] == "unmeasured":
            return 3
        return 1 if measured_identity["offers_presented_from_a_page_that_is_not_the_advert"] else 0

    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = measure() if check else write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    for violation in measured["violations"]:
        print(violation, file=sys.stderr)
    if measured["offers_presented_without_a_liveness_check"] == -1:
        return 3
    return 1 if measured["offers_presented_without_a_liveness_check"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
