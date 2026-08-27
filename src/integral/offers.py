"""Normalised offer schema, and the manual-paste connector (T11).

Specification §5.2 fixes one shape every connector must emit "regardless of
source" — a portal scraper and a candidate pasting an advert both produce the
same `Offer`. This module is that shape, plus the one connector that needs no
network and no ToS to operate: the candidate pastes an advert's text and it
becomes a schema-valid offer. §6's risk table calls it out explicitly — "One
connector in v1 plus a manual-paste path that is always available" — because a
cloud session cannot reach any job board (403 at the egress proxy, confirmed
2026-08-15) and a live connector's ToS can change or block at any time; the
manual path is the one thing that keeps working regardless.

Four decisions drawn straight from the spec, each protecting something a later
stage depends on:

* **`text` is verbatim, byte-for-byte.** §5.2: "extraction evidence spans are
  offsets into it, and a summary would invalidate every span." The same reason
  `harness.py` guards offsets with `roundtrip_loss` — a connector that trims
  trailing whitespace or collapses blank lines is indistinguishable, later, from
  one that silently shifted every span T15 will ever compute against this ad.
  So `connect_manual` never touches the string it is given except to check it
  is not blank.

* **A connector may not invent fields (§5.2).** The manual-paste connector has
  no structured `location`, `salary`, `title` or `company` unless the candidate
  supplies them alongside the paste — there is no HTML to parse and no API
  response to read. Every one of those stays `None` (absent) rather than being
  guessed from the ad text; that guessing is extraction's job (T15, over the
  committed dimension model), not a connector's.

* **`id` is content-derived, not random or clock-based.** Dedup (T13) and
  tombstones (S5, §7.4) both key on offer identity across sources, and neither
  works if two connections of the same paste mint two different ids. The id is
  `sha256:<hex of the verbatim text>` — deliberately *not* the same computation
  as §7.4's tombstone `text_sha256`, which hashes *normalised* text (chrome and
  volatile stamps stripped, whitespace collapsed, lowercased) so that
  differently-formatted re-scrapes of the same listing still tombstone
  together. This module does none of that normalisation — S5 owns it, and
  layering it in here would mean two hashing rules disagreeing about what
  "the same ad" means. What this id buys is narrower and unconditional: paste
  the identical text twice, byte for byte, and it is unconditionally the same
  offer, from any source, forever. Near-duplicate text across differently
  formatted re-postings is T13's `dedup_precision` problem, not this one's.

* **Unknown is a value, not a shrug.** `language` is only ever set to what the
  candidate (or a future connector) states explicitly; nothing here guesses it
  from the pasted words. A guess that turns out wrong is worse than an honest
  `None`, because a wrong `es` looks exactly as confident as a correct one to
  every downstream reader.

`status` is shaped but not driven: spec-v2-process §7.1 defines seven statuses
and the transitions between them, and that state machine belongs to S5, not
here. A connector only ever produces a freshly-seen offer, so the only value
this module ever assigns is `"new"`; the field exists so S5 does not have to
widen this schema (a breaking migration, §5.7) to add what §7.1 already
specifies.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from integral.dimensions import Language
from integral.identity import IdentityError, ProfileStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T11.json"

# spec-v2-process §7.1. Only "new" is ever assigned by a connector; the other
# six exist so the field does not need widening when S5 lands the transitions.
OfferStatus = Literal[
    "new", "screened_out", "shortlisted", "applied", "rejected", "expired", "archived"
]

# The id format is asserted, not just documented — a malformed id passing
# `Offer.model_validate` silently is exactly the kind of schema hole
# `offer_schema_violations` exists to catch.
_OFFER_ID_PATTERN = r"^sha256:[0-9a-f]{64}$"


class OfferError(Exception):
    """A paste, or a stored record, does not fit the offer contract."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Location(Strict):
    """§5.2's `location` object. All fields optional — a connector with no
    structured location data leaves the whole thing `None` rather than filling
    this in with guesses (see the module docstring's second point)."""

    raw: str | None = None
    country: str | None = None
    # Free text, not a Literal: different connectors will describe remote work
    # in different vocabularies (T32's declarative format may standardise one),
    # and constraining it here would mean a future connector's honest value
    # gets coerced into the nearest guess or refused outright.
    remote: str | None = None


class Salary(Strict):
    """§5.2's `salary` object.

    `stated` has no default on purpose. §5.2: "`salary.stated` distinguishes
    absent from zero — a distinction the whole 'best salary' facet depends on
    in markets where ads routinely omit pay." A default would let a caller
    populate `min`/`max` without ever deciding whether the ad actually said so
    — silently turning "we estimated this" into "the employer stated this".
    Forcing the caller to write `stated=` every time is what keeps that
    decision visible at every call site instead of buried in a default.
    """

    min: float | None = None
    max: float | None = None
    currency: str | None = None
    period: str | None = None
    stated: bool


#: `language_requirement.applies_to` — spec §5.1. `"role"` is a bar stated for
#: *this* position; `"company"` is a blanket statement about the employer
#: ("our working language is English") that says nothing about whether this
#: particular role needs it. Only `"role"` may ever gate a candidate — the
#: same distinction `eligibility.py`'s `COMPANY_WIDE_WELCOME_RE` draws for
#: citizenship and permits, applied here to language.
LanguageApplication = Literal["role", "company"]


class LanguageRequirement(Strict):
    """spec §5.1's `language_requirement` — a hard field the eligibility gate
    (`eligibility.py`) reads, and `rank.py`/`scoring.py` must never see (§5.3):
    a preference weight cancelling a legal or linguistic bar would be
    invisible in any output either layer produces, which is why the boundary
    is a test rather than a comment (T78).

    `language` is the language **the role** demands — deliberately not the
    same thing as `Offer.language`, which only records what the advert
    happens to be written in. A Catalan advert for a role that needs only
    Spanish still requires Spanish; reading `Offer.language` here would be
    exactly that mistake.

    `quote` is a verbatim span of `Offer.text`, on the same terms as
    `Candidate.spans` and `eligibility.Requirement.quote`: nothing sourced
    outside the advert may appear here.
    """

    language: str = Field(min_length=1)
    level_stated: str | None = None
    quote: str = Field(min_length=1)
    applies_to: LanguageApplication


class Offer(Strict):
    """§5.2's normalised offer — the shape every connector emits.

    `extra="forbid"` is the mechanical form of "a connector may not invent
    fields": a connector that tries to smuggle an extra key past this model —
    a scraped `recruiter_note`, a portal's internal `ad_score` — gets a
    `ValidationError`, not a silently-accepted extra field nobody downstream
    was told to expect.
    """

    id: str = Field(pattern=_OFFER_ID_PATTERN)
    source: str = Field(min_length=1)
    source_ref: str | None = None
    url: str | None = None
    fetched_at: str | None = None
    title: str | None = None
    company: str | None = None
    location: Location | None = None
    salary: Salary | None = None
    language: Language | None = None
    text: str
    expires_at: str | None = None
    # Additive, optional, never backfilled (§5.1) — T78's hard field. Absent
    # means the advert stated no role-level language requirement, not that
    # one was checked for and cleared; see `LanguageRequirement`'s docstring
    # for why this is never `Offer.language`.
    language_requirement: LanguageRequirement | None = None
    # T13 fills this in; a freshly connected offer is never a duplicate of
    # anything until dedup has looked at it.
    duplicate_of: str | None = None
    status: OfferStatus = "new"

    @field_validator("text")
    @classmethod
    def _text_is_not_blank(cls, value: str) -> str:
        # `Field(min_length=1)` would accept "   " — three characters, zero
        # content. A whitespace-only paste is refused for the same reason an
        # empty one is: there is nothing here for extraction to find evidence
        # spans in, so storing it would produce an offer nothing downstream
        # can do anything with.
        if not value.strip():
            raise ValueError("offer text must not be blank")
        return value


def compute_offer_id(text: str) -> str:
    """Content-address an offer by its verbatim text alone.

    Deliberately *only* the text — not source, not title, not url. Two
    connectors that both see the exact same wording are seeing the same ad,
    and giving them the same id is what lets T13/S5 recognise that without
    either one knowing the other exists. Hashing in anything connector-specific
    would mean the same paste, re-submitted through a different path, mints a
    second offer — precisely the duplication tombstones (§7.4) exist to
    prevent.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def connect_manual(
    text: str,
    *,
    source_ref: str | None = None,
    url: str | None = None,
    fetched_at: str | None = None,
    title: str | None = None,
    company: str | None = None,
    language: Language | None = None,
    location: Location | None = None,
    salary: Salary | None = None,
    expires_at: str | None = None,
) -> Offer:
    """Turn a candidate's pasted advert into a schema-valid `Offer`.

    `text` is stored exactly as given — see the module docstring's first
    point. Every other parameter defaults to `None` and stays `None` unless the
    caller supplies it explicitly: this function has no way to see a job
    board's structured fields, so it never invents them (§5.2). Raises
    `OfferError` on a blank paste, because storing an empty offer would hand
    every later stage a record with nothing to extract from — a loader raises
    when what it's given cannot become the thing it promises.
    """
    if not text.strip():
        raise OfferError("pasted text is empty or whitespace-only — nothing to connect")
    try:
        return Offer(
            id=compute_offer_id(text),
            source="manual",
            source_ref=source_ref,
            url=url,
            fetched_at=fetched_at,
            title=title,
            company=company,
            location=location,
            salary=salary,
            language=language,
            text=text,
            expires_at=expires_at,
        )
    except ValidationError as exc:  # pragma: no cover - defensive; see tests
        raise OfferError(f"pasted text did not produce a valid offer: {exc}") from exc


def save_offer(store: ProfileStore, offer: Offer) -> Path:
    """Write `offer` at `offers/<id>.json`, where `step_runtime`'s `offers`
    detector (`has_any_under("offers")`) looks for it."""
    return store.write_json(offer.model_dump(mode="json"), "offers", f"{offer.id}.json")


def load_offer(store: ProfileStore, offer_id: str) -> Offer:
    """Read one offer back from a candidate's tree, raising `OfferError` on
    anything that does not fit — a missing file, a hand-edited record that no
    longer validates."""
    try:
        raw = store.read_json("offers", f"{offer_id}.json")
    except IdentityError as exc:
        raise OfferError(str(exc)) from exc
    try:
        return Offer.model_validate(raw)
    except ValidationError as exc:
        raise OfferError(f"offers/{offer_id}.json is not a valid offer: {exc}") from exc


# ---------------------------------------------------------------------------
# the gate


def _expect_rejected(label: str, attempt: Callable[[], Any]) -> str | None:
    """Run an adversarial construction; report a violation if it was NOT
    refused. Used by `probe_offers` for every case that must fail."""
    try:
        attempt()
    except (OfferError, ValidationError):
        return None
    return f"{label}: wrongly accepted"


def probe_offers() -> dict[str, Any]:
    """Adversarial checks against the offer schema and the manual connector.

    `offer_schema_violations` is the count of cases that should have been
    refused — an invented field, a malformed id, a blank paste, a guessed
    language — but were accepted anyway. This is the gate's measurement, not
    a summary of the happy path: a run that only exercised valid input would
    report zero violations having tested nothing.
    """
    violations: list[str] = []
    checked = 0

    ad_text = "Backend Engineer wanted. Python, remote.\nSalary DOE."

    # A well-formed paste is accepted, and the text it carries is exactly what
    # was given — no trimming, no collapsing.
    checked += 1
    offer = connect_manual(ad_text)
    if offer.text != ad_text:
        violations.append("verbatim text was altered by a well-formed paste")

    # An invented field must be refused by the schema, not silently dropped or
    # silently accepted — either would defeat `extra="forbid"`'s whole point.
    checked += 1
    with_extra_field = offer.model_dump(mode="json")
    with_extra_field["recruiter_note"] = "fabricated by a connector"
    result = _expect_rejected(
        "invented field 'recruiter_note'", lambda: Offer.model_validate(with_extra_field)
    )
    if result:
        violations.append(result)

    # Blank and whitespace-only pastes must be refused, not stored as empty
    # offers.
    checked += 1
    result = _expect_rejected("blank paste via connect_manual", lambda: connect_manual(""))
    if result:
        violations.append(result)

    checked += 1
    result = _expect_rejected(
        "whitespace-only paste via connect_manual", lambda: connect_manual("   \n\t  ")
    )
    if result:
        violations.append(result)

    # A malformed id (not this module's `sha256:<hex>` shape) must be refused.
    checked += 1
    bad_id = offer.model_dump(mode="json")
    bad_id["id"] = "not-a-hash"
    result = _expect_rejected("malformed id", lambda: Offer.model_validate(bad_id))
    if result:
        violations.append(result)

    # A status outside spec-v2-process §7.1's seven must be refused.
    checked += 1
    bad_status = offer.model_dump(mode="json")
    bad_status["status"] = "ghosted"
    result = _expect_rejected(
        "status outside §7.1's seven", lambda: Offer.model_validate(bad_status)
    )
    if result:
        violations.append(result)

    # `salary.stated` has no default (see `Salary`'s docstring) — omitting it
    # must be refused, not silently defaulted to False.
    checked += 1
    result = _expect_rejected(
        "salary without 'stated'", lambda: Salary.model_validate({"min": 40000})
    )
    if result:
        violations.append(result)

    # Identity: the same paste always yields the same id; a different paste
    # never collides with it.
    checked += 1
    repeated = connect_manual(ad_text)
    if repeated.id != offer.id:
        violations.append("identical paste produced a different offer_id")

    checked += 1
    other = connect_manual("Frontend Engineer wanted. React, hybrid, Barcelona.")
    if other.id == offer.id:
        violations.append("two different pastes collided on the same offer_id")

    # Language is never guessed. A paste with no language given must come back
    # `None`, not a plausible-looking default.
    checked += 1
    if offer.language is not None:
        violations.append("language was invented for a paste that stated none")

    return {
        "offer_schema_violations": len(violations),
        "checks_run": checked,
        "violations": violations,
    }


MINIMUM_CHECKS = 8


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `offer_schema_violations` and record it."""
    measured = probe_offers()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.offers [path]` → T11's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["checks_run"] < MINIMUM_CHECKS:
        print(
            f"only {measured['checks_run']} check(s) were run (floor {MINIMUM_CHECKS}) — "
            "zero violations over nothing is not a measurement",
            file=sys.stderr,
        )
        return 3
    for violation in measured["violations"]:
        print(violation, file=sys.stderr)
    return 1 if measured["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
