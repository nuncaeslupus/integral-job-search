"""T43 — what is learned outside the advert, and never quoted as the employer.

Plenty of adverts are four lines and a salary band. Step 8 may look outside when
extraction yields very little — what the company does, how it is spoken about,
what former employees say — and add what it finds.

**The rule that matters.** Nothing sourced outside the advert ever appears as a
verbatim evidence span. `explained_fraction` (T19) means *the employer's own
words*; an explanation citing a review site as though the employer had written
it is a lie about provenance — the kind that stays invisible until the candidate
quotes it back in an interview and the room goes quiet. So
`outside_source_spans_in_explanations` is not a question about labelling on
screen. It asks whether an outside sentence can reach the one place in the
system that means "the advert says this".

**The provenance marker is the type, not a flag.** An `OutsideFinding` is not a
`DimensionScore` and cannot be put where one goes: `Candidate.spans` takes the
advert's words and nothing else, and there is no code path that turns a finding
into a span. A boolean `from_advert` on a shared type would be one forgotten
`if` away from the failure this task exists to prevent; two types are one
`TypeError` away instead. The attribute still exists, as a `ClassVar` that is
always `False`, because a reader holding one should be able to ask.

**A finding with no reference is refused.** "What former employees say", with no
link, is a rumour that becomes checkable-looking purely by being put in a field.
Blank text likewise: there is nothing there to have found.

**The lookup is off when the candidate says so, and is then not performed** —
not performed and filtered, which would already have sent the employer's name to
whatever the finder talks to. The switch is a standing preference in the decline
ledger, the mechanism this codebase already uses for "the candidate would rather
not", and the same one `profile_capture.capture` filters dimensions through.

**Stated ceiling — the refusal is not one of T24's ten pinned fields.** The task
says the preference is recorded in `constraints.json`, and declines surface there
only for the pinned ten. Adding an eleventh is T24's vocabulary to change, not
this task's; the ledger is where a standing refusal lives today and is what
`_resolve_pinned_fields` already reads. Promoting `outside_lookup` to a pinned
field would make it visible in that file and is a small, separate change.

**Stated ceiling — no finder ships here.** `enrich` takes one. What to look up,
where, and under whose robots.txt is a connector question (see `integral.robots`),
and a default finder in this module would be a network call hidden inside a
scoring path.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from integral.decline import DeclineLedger
from integral.explain import explain
from integral.identity import ProfileStore
from integral.offers import Offer, compute_offer_id
from integral.profile import ProfileRevision
from integral.rank import Candidate, rank

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T43.json"

#: The decline-ledger subject that switches outside lookups off.
LOOKUP_KEY = "outside_lookup"

#: Rendered wherever a finding is shown. One phrase, so a candidate learns it
#: once — and so a test can assert it rather than matching a family of wordings.
NOT_FROM_THE_ADVERT = "not from the advert"


class EnrichmentError(Exception):
    """A finding does not carry what a finding has to carry."""


@dataclass(frozen=True)
class OutsideFinding:
    """Something about the employer that the advert does not say.

    Deliberately not a `DimensionScore`: see the module docstring. This type
    cannot be put where a span goes, which is a stronger guarantee than any
    check on a shared type.
    """

    dimension: str
    text: str
    source: str
    source_ref: str
    looked_up_at: str

    #: Always false, and readable. The type is the marker; this is the answer to
    #: a reader who has one in hand and asks.
    from_advert: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise EnrichmentError("an outside finding with no text found nothing")
        if not self.source_ref.strip():
            raise EnrichmentError(
                f"{self.source}: a finding with no reference is a rumour that a field "
                "made look checkable — give the source, or do not record it"
            )

    def label(self) -> str:
        """Standalone form — carries the marker itself, for anywhere this is
        shown without a heading that already says where it came from."""
        return f"{self.text} [{NOT_FROM_THE_ADVERT} — {self.source}: {self.source_ref}]"

    def cite(self) -> str:
        """Form for a block already headed "not from the advert" — the marker
        once, not on every line, and the source still on each."""
        return f"{self.text} [{self.source}: {self.source_ref}]"


Finder = Callable[[Offer, tuple[str, ...]], Sequence["OutsideFinding"]]


def lookups_allowed(store: ProfileStore) -> bool:
    """Whether the candidate has left outside lookups on. Default: yes."""
    return not DeclineLedger(store).declines(LOOKUP_KEY)


def enrich(
    offer: Offer,
    dimensions: Sequence[str],
    *,
    store: ProfileStore,
    finder: Finder,
    at: str,
) -> list[OutsideFinding]:
    """Look outside the advert, unless the candidate has said not to.

    The check is before the call, not after it: filtering the results would
    already have sent the employer's name to whatever the finder talks to.
    """
    if not lookups_allowed(store):
        return []
    return [
        OutsideFinding(
            dimension=finding.dimension,
            text=finding.text,
            source=finding.source,
            source_ref=finding.source_ref,
            looked_up_at=at,
        )
        for finding in finder(offer, tuple(dimensions))
    ]


def outside_source_spans(
    explanations: Mapping[str, Mapping[str, Any]],
    findings: Sequence[OutsideFinding],
) -> list[str]:
    """Every driver citing an outside sentence as the employer's own words."""
    outside = {finding.text.strip(): finding for finding in findings}
    return [
        f"{offer_id}: {driver['dimension']} cites {driver['evidence_span']!r} as the "
        f"advert's words, and it came from {outside[str(driver['evidence_span']).strip()].source}"
        for offer_id, explanation in explanations.items()
        for driver in explanation["drivers"]
        if driver["evidence_span"] and str(driver["evidence_span"]).strip() in outside
    ]


_LEAK = "Antiguos empleados mencionan guardias frecuentes."
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


def _finding() -> OutsideFinding:
    return OutsideFinding(
        dimension="on_call_load",
        text=_LEAK,
        source="review_site",
        source_ref="https://example.invalid/reviews/acme",
        looked_up_at="2026-08-24T00:00:00Z",
    )


def _explanations(spans: Mapping[str, tuple[str, ...]]) -> dict[str, dict[str, Any]]:
    text = "Backend. Barcelona. 40.000€."
    candidate = Candidate(
        offer_id=compute_offer_id(text),
        salary_per_month=3600.0,
        scores={"remote": 1.0, "commute": 0.5},
        spans=spans,
    )
    ranking = rank(
        [candidate],
        dimensions=_FIXTURE_DIMENSIONS,
        revision=ProfileRevision(rows=1, sha256="0" * 64),
        weights=_FIXTURE_WEIGHTS,
        at="2026-08-24T00:00:00Z",
    )
    return explain(ranking, [candidate], _FIXTURE_WEIGHTS)


def measure() -> dict[str, Any]:
    """The gate's number, and proof it can rise."""
    honest = _explanations({"remote": ("100% en remoto",), "commute": ("junto a la estación",)})
    violations = outside_source_spans(honest, [_finding()])

    # Put the review-site sentence where the advert's words go. If the count
    # does not rise, it is not reading the spans and a zero certifies nothing.
    leaked = _explanations({"remote": (_LEAK,), "commute": ("junto a la estación",)})
    planted = outside_source_spans(leaked, [_finding()])

    return {
        "outside_source_spans_in_explanations": len(violations),
        "leak_detected_when_planted": int(bool(planted)),
        "violations": violations,
        "spans_checked": sum(len(e["drivers"]) for e in honest.values()),
        "findings_checked": 1,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Measure T43's provenance separation.")
    parser.add_argument("evidence", nargs="?", default=str(DEFAULT_EVIDENCE_PATH), type=Path)
    args = parser.parse_args(argv)
    measured = write_evidence(args.evidence)

    key = "outside_source_spans_in_explanations"
    print(f"{key}: {measured[key]} (== 0)")
    if measured[key]:
        for problem in measured["violations"]:
            print(problem, file=sys.stderr)
        return 1
    if not measured["leak_detected_when_planted"]:
        print("an outside sentence planted in a span was not detected", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
