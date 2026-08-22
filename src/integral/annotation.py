"""T42 — the local annotation pass: this advert, read against *this* candidate.

An extraction that records `salary: 48000` leaves ranking to work out what that
means. An annotation recording that it sits inside the candidate's stated band,
that the commute is one they said they would make, that the relocation condition
has not been checked — turns ranking into comparison rather than computation.

So it is a second pass over the offer, **on this machine**, writing
`annotations/<offer_id>.json`: derived, stamped with the profile revision it was
read against, and never a field inside the extraction.

**The separation matters more than the convenience.** The model sees the advert
and nothing else; the profile is never sent one advert at a time. That is what
keeps `extractions/<offer_id>.json` candidate-independent — cacheable, shareable,
leaking nothing — and it is the single privacy failure that cannot be undone once
it happens.

The gate is therefore measured over the **actual outbound payload**, not over
intent: `outbound_payloads` serialises exactly what `model_request` would send
for real corpus adverts, and `egress_leaks` scans those bytes for the strings a
fixture candidate stated. A test asserting that this module does not *intend* to
send the profile would prove nothing; adding a constraints field to
`ModelRequest` makes this number go non-zero on the next `make evidence`.

Recomputation is not this module's own machinery. An annotation records its
`profile_revision` in the shape `revision.recorded_revision` reads, so
`revision.stale_artefacts` — which already classifies `annotations/` as derived
— names it the moment the constraints move. A second staleness rule here would
be a second thing to keep in step with §3.4.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from integral.candidate import (
    FIELD_MODELS,
    CandidateConstraints,
    LanguageLevel,
    Languages,
    Location,
    OfferFacts,
    Relocation,
    Salary,
    filter_hard_constraints,
)
from integral.dimensions import Dimension, load_dimensions
from integral.extraction import (
    OfferExtraction,
    model_request,
    normalise,
    rules_stage,
    unsettled_dimensions,
)
from integral.harness import load_store
from integral.identity import ProfileStore
from integral.offers import Offer, compute_offer_id
from integral.profile import ProfileRevision

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T42.json"

#: Adverts the egress scan runs over. Real ones, from the corpus — a fabricated
#: advert would let a leak hide in text nobody ever sends.
EGRESS_SAMPLE = 12

#: Strings shorter than this are not scanned for. A country, currency or
#: language code ("ES", "EUR", "ca") identifies nobody and occurs constantly in
#: advert text, so counting it would drown the real signal in false positives.
#: Every string that *does* carry the candidate is longer than this.
MIN_IDENTIFYING_LENGTH = 4


class AnnotationError(Exception):
    """The annotation pass cannot read what it was given."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Reading(Strict):
    """One constraint field, and what this offer does about it."""

    field: str = Field(min_length=1)
    # `unknown` is a first-class outcome, never folded into `satisfied`: a field
    # the candidate has not answered has made no claim for the offer to meet,
    # and reading that as a pass is how an unanswered question becomes a
    # silent yes downstream.
    verdict: Literal["satisfied", "violated", "unknown"]
    because: str = Field(min_length=1)


class Annotation(Strict):
    """`annotations/<offer_id>.json` — derived, local, and never sent."""

    offer_id: str = Field(min_length=1)
    profile_revision: dict[str, Any]
    kept: bool
    readings: list[Reading] = Field(default_factory=list)


def annotate(
    facts: OfferFacts,
    constraints: CandidateConstraints,
    revision: ProfileRevision,
) -> Annotation:
    """Read one offer against the candidate's stated constraints.

    The hard-constraint verdicts come from `filter_hard_constraints` (T24)
    rather than from a second set of checks here: two implementations of "does
    this offer break a constraint" would drift, and the one that drifted would
    be this one, because it is the one nothing else is gated on.
    """
    result = filter_hard_constraints(constraints, [facts])
    violated = {removal.field: removal.reason for removal in result.removed}
    readings = [
        Reading(
            field=name,
            verdict="unknown"
            if value.state != "stated"
            else ("violated" if name in violated else "satisfied"),
            because=violated.get(name)
            or (
                f"the candidate has not stated {name}"
                if value.state == "unknown"
                else f"the candidate declined to state {name}"
                if value.state == "declined"
                else f"nothing in this advert conflicts with the stated {name}"
            ),
        )
        for name, value in constraints.as_dict().items()
    ]
    return Annotation(
        offer_id=facts.offer_id,
        profile_revision=revision.as_json(),
        kept=facts.offer_id in result.surviving,
        readings=readings,
    )


def write_annotation(store: ProfileStore, annotation: Annotation) -> Path:
    """Record it under the candidate's own tree, and nowhere else."""
    return store.write_json(annotation.model_dump(), "annotations", f"{annotation.offer_id}.json")


# ---------------------------------------------------------------------------
# the gate: what actually goes out


def _schema_vocabulary() -> frozenset[str]:
    """Every value the constraints schema itself permits — `stated`, `professional`, `remote`.

    Read out of the JSON schema rather than listed, for the same reason
    `stated_strings` walks the dump: a `Literal` gaining a member must not
    quietly become a false positive that somebody then "fixes" by loosening the
    scan. These words are the model's vocabulary, not the candidate's — an
    advert saying "professional" says nothing about who is reading it.
    """
    words: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            words.add(node)

    models: list[type[BaseModel]] = [CandidateConstraints, *FIELD_MODELS.values()]
    for model in models:
        schema = model.model_json_schema()
        for definition in [*schema.get("$defs", {}).values(), schema]:
            for prop in definition.get("properties", {}).values():
                walk({k: v for k, v in prop.items() if k in {"enum", "const", "anyOf"}})
    return frozenset(words)


def stated_strings(constraints: CandidateConstraints) -> list[str]:
    """Every identifying string the candidate stated — the bytes that must not leave.

    Walked from the model dump rather than listed field by field, so a
    constraint field added later is scanned for without anyone remembering to
    add it here. A hardcoded list is a check that silently stops covering the
    thing it was written for.
    """
    found: set[str] = set()
    vocabulary = _schema_vocabulary()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            if len(value) >= MIN_IDENTIFYING_LENGTH and value not in vocabulary:
                found.add(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list | tuple | set | frozenset):
            for item in value:
                walk(item)

    walk(constraints.model_dump(mode="json"))
    return sorted(found)


def outbound_payloads(offers: list[Offer], dimensions: list[Dimension]) -> list[str]:
    """Exactly what stage 3 would put on the wire, serialised.

    `model_request` is the whole of this system's egress towards a model in
    step 8. Scanning its output is what makes the gate a measurement of the
    payload rather than of the intention behind it.
    """
    payloads: list[str] = []
    for offer in offers:
        ad = normalise(offer)
        unsettled = unsettled_dimensions(dimensions, rules_stage(ad, dimensions))
        payloads.append(model_request(ad, unsettled).model_dump_json())
    return payloads


def _searchable(payload: str) -> list[str]:
    """The payload as raw bytes *and* as its decoded strings.

    Raw alone is not enough: JSON escapes quotes, backslashes and newlines, so a
    stated string containing any of them would sail past a substring scan — a
    false negative in the one check that cannot be wrong. Decoded alone is not
    enough either: a payload that does not parse must still be scanned rather
    than silently skipped.
    """
    haystacks = [payload]

    def walk(node: Any) -> None:
        if isinstance(node, str):
            haystacks.append(node)
        elif isinstance(node, dict):
            for key, value in node.items():
                haystacks.append(key)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    with contextlib.suppress(json.JSONDecodeError):
        walk(json.loads(payload))
    return haystacks


def egress_leaks(payloads: list[str], markers: list[str]) -> list[str]:
    """Every candidate string that appears in an outbound payload."""
    return sorted(
        f"payload {index}: carries {marker!r}"
        for index, payload in enumerate(payloads)
        for marker in markers
        if any(marker in haystack for haystack in _searchable(payload))
    )


def fixture_constraints() -> CandidateConstraints:
    """A candidate whose every stated string is unmistakable in a payload.

    Distinctive by construction: the check is only as good as its markers, and
    a realistic-looking fixture would leave a leak indistinguishable from an
    advert that happens to mention Barcelona.
    """
    return CandidateConstraints(
        languages=Languages(
            state="stated",
            levels=(LanguageLevel(language="en", level="professional", working_language=True),),
        ),
        location=Location(
            state="stated",
            country="ES",
            accepts_onsite_in_country=True,
            commutable_regions=("EGRESSCANARY-REGION-Q7",),
        ),
        relocation=Relocation(
            state="stated",
            willingness="conditional",
            condition="EGRESSCANARY-CONDITION-Q7",
            destinations=("PT",),
        ),
        salary=Salary(state="stated", floor=42000, currency="EUR"),
    )


def _sample_offers(limit: int = EGRESS_SAMPLE) -> list[Offer]:
    """Real corpus adverts as offers, so the scan runs over text that is sent.

    Refuses a short corpus rather than scanning whatever is there. A slice that
    quietly returns four adverts still reports `annotation_profile_egress: 0`,
    and a gate that got smaller without saying so is the one failure a privacy
    number must not have.
    """
    ads = load_store()
    if len(ads) < limit:
        raise AnnotationError(
            f"the egress scan needs {limit} corpus adverts to run over, and the corpus "
            f"holds {len(ads)}"
        )
    return [
        Offer(
            id=compute_offer_id(ad.text),
            source="corpus",
            text=ad.text,
            language=ad.language,
            title=ad.title or None,
            company=ad.company or None,
        )
        for ad in ads[:limit]
    ]


def _extraction_schema_refuses() -> bool:
    """Does `OfferExtraction` still refuse a candidate-dependent field?

    Tried, not asserted. The failure this guards is somebody adding an
    annotation field to the extraction — at which point the extraction stops
    being shareable and this must stop reading true.
    """
    try:
        OfferExtraction(
            offer_id="sha256:" + "0" * 64,
            language="es",
            fits_candidate_salary_band=True,  # type: ignore[call-arg]
        )
    except ValidationError:
        return True
    return False


def measure(dimensions_dir: Path | None = None) -> dict[str, Any]:
    """T42's gate: candidate strings found in what would actually be sent."""
    dimensions = load_dimensions(dimensions_dir) if dimensions_dir else load_dimensions()
    constraints = fixture_constraints()
    markers = stated_strings(constraints)
    offers = _sample_offers()
    payloads = outbound_payloads(offers, dimensions)
    leaks = egress_leaks(payloads, markers)

    # The annotation is computed for every sampled offer, so the number is
    # measured with the pass actually running rather than over a pipeline that
    # never annotated anything.
    revision = ProfileRevision.of_nothing()
    annotations = [
        annotate(
            OfferFacts(offer_id=offer.id, country="ES", delivery="remote"), constraints, revision
        )
        for offer in offers
    ]

    return {
        "annotation_profile_egress": len(leaks),
        "leaks": leaks,
        "profile_strings_planted": len(markers),
        "outbound_payloads_scanned": len(payloads),
        "outbound_bytes_scanned": sum(len(payload) for payload in payloads),
        "annotations_computed": len(annotations),
        # The other half of "candidate-independent", and attempted rather than
        # asserted: a hardcoded `true` here would keep reading true on the day
        # somebody relaxes the extraction schema.
        "extraction_schema_forbids_a_candidate_field": _extraction_schema_refuses(),
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T42.json`."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write T42's gate evidence. Exit 1 on any leak — this one has no third outcome."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    if measured["annotation_profile_egress"]:
        for leak in measured["leaks"]:
            print(f"annotation_profile_egress: {leak}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
