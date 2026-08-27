"""T78's boundary, from the ranker's side of spec §5.3.

`rank.py`/`scoring.py` may read `dimensions/*` scores and `weights.json`; they
must never read `offer.language_requirement` or `offer.eligibility` — the
eligibility/language gate's own hard fields (`eligibility.py`). This file
pins the same invariant `eligibility.py`'s own boundary tests pin, from the
ranker module's side, so a reader of `test_rank.py`'s sibling does not have
to already know `eligibility.py` exists to find it.

T79's presentation tests (the Excluded section, a FLAG marker) live here too,
once T79 lands; this file exists ahead of that only for T78's boundary.
"""

from __future__ import annotations

from integral import eligibility


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
