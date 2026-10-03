"""T186: a retraction chain resolves to a current value, at any depth."""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.feedback import traceability
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog, EvidenceRow, rebuild

_AT = "2026-08-24T09:00:00Z"


def _log(tmp_path: Path) -> tuple[ProfileStore, EvidenceLog]:
    identity = create_profile(tmp_path, "Candidate", handle="candidate")
    store = ProfileStore(tmp_path, identity.handle)
    return store, EvidenceLog(store)


def _add(
    log: EvidenceLog, text: str, *, retracts: str | None = None, kind: str | None = None
) -> EvidenceRow:
    return log.append(
        recorded_at=_AT,
        step="history",
        kind="retraction" if retracts else (kind or "statement"),  # type: ignore[arg-type]
        text=text,
        source="conversation",
        retracts=retracts,
        dimensions=() if retracts else ("learning_support",),
    )


def _chain(log: EvidenceLog, depth: int) -> list[str]:
    """A row followed by `depth` retractions, each retracting the previous one."""
    ids = [_add(log, "Dietètica").id]
    for _ in range(depth):
        ids.append(_add(log, "retracts the previous", retracts=ids[-1]).id)
    return ids


def test_a_retracted_row_is_not_effective(tmp_path: Path) -> None:
    _, log = _log(tmp_path)
    wrong = _add(log, "Nutrició")
    right = _add(log, "Dietètica")
    retraction = _add(log, "no", retracts=wrong.id)

    live = {row.id for row in log.effective()}
    assert wrong.id not in live
    assert retraction.id not in live
    assert live == {right.id}
    assert len(log.rows()) == 3  # still append-only


def test_retracting_a_retraction_restores_the_original_row(tmp_path: Path) -> None:
    """ev-48 -> ev-60 retracts it -> ev-66 retracts ev-60: ev-48 is live again."""
    _, log = _log(tmp_path)
    original = _add(log, "Dietètica")
    wrong = _add(log, "Nutrició", retracts=original.id, kind="statement")
    assert wrong.kind == "retraction"  # a retraction row carries the wrong value
    undo = _add(log, "no", retracts=wrong.id)

    live = [row.id for row in log.effective()]
    assert live == [original.id]
    assert undo.id not in live


@pytest.mark.parametrize("depth", range(0, 14))
def test_a_chain_of_any_depth_resolves_by_parity(tmp_path: Path, depth: int) -> None:
    """The rule, not the enumeration: the row is live iff an even number of
    retractions stack on it. Both parities, every depth, must agree."""
    _, log = _log(tmp_path)
    ids = _chain(log, depth)
    live = {row.id for row in log.effective()}
    assert (ids[0] in live) is (depth % 2 == 0)
    assert not set(ids[1:]) & live  # retraction rows are never evidence


def test_a_withdrawn_value_never_reads_as_current_beside_a_restored_one(tmp_path: Path) -> None:
    _, log = _log(tmp_path)
    kept = _chain(log, 2)[0]  # restored
    gone = _chain(log, 3)[0]  # withdrawn
    live = {row.id for row in log.effective()}
    assert kept in live
    assert gone not in live


def test_a_claim_tracing_to_a_retracted_row_is_refused(tmp_path: Path) -> None:
    store, log = _log(tmp_path)
    row = _add(log, "Aprendí Rust por mi cuenta.", kind="episode")
    rebuild(store)
    assert traceability(store)["untraced"] == []

    _add(log, "no", retracts=row.id)
    # Derived files are stale on purpose: they still cite the withdrawn row.
    measured = traceability(store)
    assert measured["feedback_traceability"] < 1.0
    assert any(row.id in problem for problem in measured["untraced"])

    # Withdraw the withdrawal: the same citation traces again, no restatement.
    _add(log, "oops", retracts=log.rows()[-1].id)
    assert traceability(store)["untraced"] == []
