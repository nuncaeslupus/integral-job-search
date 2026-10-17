"""T345 - an offer already applied to, rejected or expired is not shown again.

Verdicts come from the task text: the offer's own lifecycle status (section 7.1)
decides, whether current or reached earlier, and an offer shown before is marked
as seen, not new. Controls must stay shown.
"""

from __future__ import annotations

import pytest

from integral import offers_seen_again as gate
from integral.presentation_log import REASON_APPLIED, REASON_EXPIRED, partition


def _held(build) -> str | None:  # type: ignore[no-untyped-def]
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        store = gate._store(Path(tmp))
        offer_id = build(store)
        show, held = partition(store, [offer_id])
        assert (offer_id in show) != bool(held)
        return held[0].reason if held else None


def test_gate_is_zero_with_a_nonzero_denominator() -> None:
    measured = gate.measure()
    assert measured["gate_status"] == "measured"
    assert measured["offers_presented_again_after_applied_or_rejected"] == 0
    assert len(gate.RULED_CASES) + len(gate.RECORD_ONLY_CASES) >= 9
    assert measured["controls_withheld"] == 0
    assert measured["offers_seen_not_marked"] == 0


@pytest.mark.parametrize(("name", "path"), gate.RULED_CASES)
def test_each_ruled_offer_is_withheld(name: str, path: tuple[str, ...]) -> None:
    assert _held(gate._built(name, path)) is not None  # type: ignore[arg-type]


@pytest.mark.parametrize(("name", "path"), gate.CONTROLS)
def test_each_control_is_shown(name: str, path: tuple[str, ...]) -> None:
    assert _held(gate._built(name, path)) is None  # type: ignore[arg-type]


def test_reasons_name_the_cause() -> None:
    assert _held(gate._built("a", ("shortlisted", "applied", "archived"))) == REASON_APPLIED
    assert _held(gate._built("e", ("expired", "archived"))) == REASON_EXPIRED
    assert _held(gate._record_only("applied")) == REASON_APPLIED


def test_a_draft_is_not_an_application() -> None:
    assert _held(gate._record_only("drafted")) is None


def test_seen_note_names_only_the_repeat_in_the_documented_order() -> None:
    import tempfile
    from pathlib import Path

    from integral.presentation_log import present, shown_notes

    with tempfile.TemporaryDirectory() as tmp:
        store = gate._store(Path(tmp))
        seen = gate._save(store, "seen", ())
        fresh = gate._save(store, "fresh", ())
        present(store, [seen], at=gate._AT)
        show, _ = partition(store, [seen, fresh])
        present(store, show, at=gate._AT)
        text = "\n".join(shown_notes(store, show))
        assert "Role seen" in text
        assert "Role fresh" not in text
    assert gate._repeat_unmarked() == 0
