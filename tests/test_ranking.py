"""T78's boundary, from the ranker's side of spec §5.3.

`rank.py`/`scoring.py` may read `dimensions/*` scores and `weights.json`; they
must never read `offer.language_requirement` or `offer.eligibility` — the
eligibility/language gate's own hard fields (`eligibility.py`). This file
pins the same invariant `eligibility.py`'s own boundary tests pin, from the
ranker module's side, so a reader of `test_rank.py`'s sibling does not have
to already know `eligibility.py` exists to find it.

T79's presentation tests — the Excluded section, and a FLAG offer that stays
ranked with its marker — live here too.
"""

from __future__ import annotations

from typing import Any

from integral import eligibility
from integral.eligibility import Reading
from integral.profile import ProfileRevision
from integral.rank import Candidate, measure_exclusions, rank


def test_a_hard_gate_field_is_never_read_by_the_ranker() -> None:
    """`rank.py` and `scoring.py` — the two modules spec §5.3's boundary
    table names as "the ranker" — must never access `.language_requirement`
    or `.eligibility` on anything. A hit would mean the preference layer can
    see a field only the hard gate may read, which is exactly the failure
    that would let a dimension weight cancel a legal or linguistic bar."""
    results = [
        r
        for r in eligibility.audit_boundary()
        if r["direction"] == "ranker_never_reads_a_gate_field"
    ]

    assert results, "the ranker modules must actually have been scanned, not skipped"
    assert {r["name"] for r in results} == {"rank.py", "scoring.py"}
    assert all(r["match"] for r in results), [r["detail"] for r in results if not r["match"]]


# ---------------------------------------------------------------------------
# T79 — the Excluded section


_BARRED = "sha256:" + "a" * 64
_FLAGGED = "sha256:" + "b" * 64
_CLEAR = "sha256:" + "c" * 64

_READINGS = (
    Reading(
        offer_id=_BARRED,
        verdict="FAIL",
        reason="citizenship",
        quote="must hold German citizenship",
        requirements=(),
    ),
    Reading(
        offer_id=_FLAGGED,
        verdict="FLAG",
        reason="clearance",
        quote="An active security clearance is a plus",
        requirements=(),
    ),
    Reading(offer_id=_CLEAR, verdict="PASS", reason=None, quote=None, requirements=()),
)


def _ranking() -> dict[str, Any]:
    """Three offers, one of each verdict. The barred one pays the most, so a
    frontier that merely sorted it last would still put it first."""
    candidates = [
        Candidate(offer_id=_BARRED, salary_per_month=9000.0, scores={"remote": 1.0}),
        Candidate(offer_id=_FLAGGED, salary_per_month=3000.0, scores={"remote": 0.5}),
        Candidate(offer_id=_CLEAR, salary_per_month=2000.0, scores={"remote": -1.0}),
    ]
    return rank(
        candidates,
        dimensions=("remote",),
        revision=ProfileRevision(rows=3, sha256="0" * 64),
        weights=None,
        at="2026-08-27T00:00:00Z",
        readings=_READINGS,
    )


def test_an_excluded_offer_appears_with_its_quoted_reason() -> None:
    """Shown, never silently dropped — and shown with the advert's own
    sentence, because a verdict the candidate cannot trace to wording is one
    they cannot dispute."""
    excluded = _ranking()["excluded"]

    assert excluded == [
        {
            "offer_id": _BARRED,
            "reason": "citizenship",
            "quote": "must hold German citizenship",
        }
    ]


def test_an_excluded_offer_is_not_on_the_frontier() -> None:
    """Excluded means excluded from the dominance comparison, not sorted last:
    dominance over a barred offer is meaningless, and a very low score is still
    a place on the list."""
    ranking = _ranking()

    assert _BARRED not in ranking["pareto"]
    assert _BARRED not in ranking["dominated"]
    assert _BARRED not in ranking["salary_equivalent_total"]


def test_a_flagged_offer_is_ranked_with_its_marker() -> None:
    """Spec §5.4: ranked, marked, and the human is the tiebreaker."""
    ranking = _ranking()

    assert _FLAGGED in ranking["pareto"]
    assert ranking["flagged"] == [_FLAGGED]
    assert _CLEAR not in ranking["flagged"]


def test_the_gate_does_not_pass_on_an_empty_input_set() -> None:
    """A violation count of zero over nothing excluded is not a pass. The
    denominator is asserted, and the negative control proves the count rises
    when a reason goes missing."""
    measured = measure_exclusions()

    assert measured["excluded_offers_shown_without_a_reason_evaluated"] > 0
    assert measured["gate_status"] == "measured"
    assert measured["excluded_offers_shown_without_a_reason"] == 0
    assert measured["violation_detected_when_planted"] == 1
