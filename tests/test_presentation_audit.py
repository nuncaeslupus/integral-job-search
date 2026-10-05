"""T226 — the two records steps 9 and 10 must leave are read against each other.

Cases derive from the task's own text: a ranking with no `present()` row, and an
evidence row quoting a discard no lifecycle record carries. Each gap case has a
twin where the matching call WAS made and the audit must be silent, so a check
that always reports (or never does) fails one of them.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from integral.decline import DeclineLedger
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import purge_offer, save_lifecycle_offer, track_new_offer
from integral.offers import connect_manual
from integral.presentation_audit import unpresented_ranking, unrecorded_discards
from integral.presentation_log import present, rule_out
from integral.profile import EvidenceLog, EvidenceSubject
from integral.profile_capture import capture
from integral.profile_standing import Standing

_RAN = "2026-10-01T09:00:00Z"
_SHOWN = "2026-10-01T09:05:00Z"
_ROOT = Path(__file__).resolve().parents[1]


def _store(tmp_path: Path, handle: str = "candidate") -> ProfileStore:
    identity = create_profile(tmp_path, "Candidate", handle=handle)
    return ProfileStore(tmp_path, identity.handle)


def _offer(store: ProfileStore, title: str = "Backend") -> str:
    offer = connect_manual(f"{title} en Barcelona.", title=title, company="ACME", language="es")
    save_lifecycle_offer(store, offer, track_new_offer(offer, at=_RAN))
    return offer.id


def _rank(store: ProfileStore, ids: list[str], run_id: str = _RAN) -> None:
    store.write_json({"run_id": run_id, "pareto": ids}, "rankings", f"{run_id}.json")


def _say_about(
    store: ProfileStore,
    offer_id: str,
    text: str,
    *,
    step: str = "feedback",
    kind: str = "statement",
) -> None:
    capture(
        EvidenceLog(store),
        DeclineLedger(store),
        step=step,
        kind=kind,  # type: ignore[arg-type]
        text=text,
        source="offer_reaction",
        recorded_at=_SHOWN,
        about=EvidenceSubject(kind="offer", id=offer_id),
    )


def test_a_ranking_with_no_presentation_row_is_reported(tmp_path: Path) -> None:
    store = _store(tmp_path)
    oid = _offer(store)
    _rank(store, [oid])
    gap = unpresented_ranking(store)
    assert [g["problem"] for g in gap] == ["no present() row"]
    assert gap[0]["offers"] == [oid]


def test_a_ranking_that_was_presented_is_not_reported(tmp_path: Path) -> None:
    store = _store(tmp_path)
    oid = _offer(store)
    _rank(store, [oid])
    present(store, [oid], at=_SHOWN)
    assert unpresented_ranking(store) == []


def test_a_presentation_from_before_the_ranking_does_not_count(tmp_path: Path) -> None:
    """The 2026-10-01 shape: an old row exists, today's list has none."""
    store = _store(tmp_path)
    oid = _offer(store)
    present(store, [oid], at="2026-09-30T09:00:00Z")
    _rank(store, [oid])
    assert unpresented_ranking(store)


def test_a_presentation_of_other_offers_does_not_count(tmp_path: Path) -> None:
    store = _store(tmp_path)
    a, b = _offer(store), _offer(store, "Frontend")
    _rank(store, [a])
    present(store, [b], at=_SHOWN)
    assert unpresented_ranking(store)


def test_only_the_latest_ranking_is_asked_about(tmp_path: Path) -> None:
    store = _store(tmp_path)
    oid = _offer(store)
    _rank(store, [oid], "2026-09-29T09:00:00Z")  # superseded, never shown: not a gap
    _rank(store, [oid])
    present(store, [oid], at=_SHOWN)
    assert unpresented_ranking(store) == []


def test_unreadable_or_untimed_rankings_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    oid = _offer(store)
    present(store, [oid], at=_SHOWN)
    store.write_json({"run_id": "not a time", "pareto": [oid]}, "rankings", "x.json")
    assert unpresented_ranking(store), "an untimed ranking cannot be shown to have been presented"
    store.path("rankings", "x.json").write_text("{", encoding="utf-8")
    assert [g["problem"] for g in unpresented_ranking(store)] == ["undatable"]


def test_nothing_ranked_is_no_gap(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert unpresented_ranking(store) == []
    _rank(store, [])
    assert unpresented_ranking(store) == []


def test_a_reaction_with_no_rule_out_is_reported(tmp_path: Path) -> None:
    store = _store(tmp_path)
    oid = _offer(store)
    _say_about(store, oid, "yo no soy applied researcher")
    gaps = unrecorded_discards(store)
    assert [(g["offer"], g["reason"]) for g in gaps] == [(oid, "yo no soy applied researcher")]


def test_a_reaction_recorded_through_rule_out_is_not_reported(tmp_path: Path) -> None:
    store = _store(tmp_path)
    oid = _offer(store)
    rule_out(store, oid, "yo no soy applied researcher", at=_SHOWN)
    assert unrecorded_discards(store) == []


def test_the_same_words_said_twice_need_two_decisions(tmp_path: Path) -> None:
    """Counted, not set-matched: one rule_out cannot cover two rows."""
    store = _store(tmp_path)
    oid = _offer(store)
    rule_out(store, oid, "demasiado junior", at=_SHOWN)
    _say_about(store, oid, "demasiado junior")
    assert len(unrecorded_discards(store)) == 1


_OLDER = "2026-09-30T09:00:00Z"


def _older_ranking_presented(store: ProfileStore) -> str:
    oid = _offer(store, "Older")
    _rank(store, [oid], _OLDER)
    present(store, [oid], at="2026-09-30T09:05:00Z")
    return oid


def test_a_newer_unpresented_ranking_is_reported_beside_an_older_presented_one(
    tmp_path: Path,
) -> None:
    """F2: the newest list is the one asked about, so the second day's gap shows."""
    store = _store(tmp_path)
    _older_ranking_presented(store)
    newer = _offer(store, "Newer")
    _rank(store, [newer])
    gap = unpresented_ranking(store)
    assert [(g["problem"], g["offers"]) for g in gap] == [("no present() row", [newer])]


def test_a_corrupt_newest_ranking_is_a_gap_even_beside_an_older_presented_one(
    tmp_path: Path,
) -> None:
    """F1: a corrupt newest file is dated by its name, and is not passed over."""
    store = _store(tmp_path)
    _older_ranking_presented(store)
    store.path("rankings").joinpath(f"{_RAN}.json").write_text("{", encoding="utf-8")
    assert [g["problem"] for g in unpresented_ranking(store)] == ["unreadable"]


def test_an_untimed_run_id_is_dated_by_the_file_name(tmp_path: Path) -> None:
    """F1: `run_id` that is not a time falls back to the `<run_id>.json` stem."""
    store = _store(tmp_path)
    _older_ranking_presented(store)
    newer = _offer(store, "Newer")
    store.write_json({"run_id": "r2", "pareto": [newer]}, "rankings", f"{_RAN}.json")
    gap = unpresented_ranking(store)
    assert [(g["ranking"], g["problem"]) for g in gap] == [(f"{_RAN}.json", "no present() row")]


def test_a_ranking_that_cannot_be_dated_at_all_is_a_gap(tmp_path: Path) -> None:
    """F1: neither `run_id` nor name dates it, so it may be the newest: reported."""
    store = _store(tmp_path)
    _older_ranking_presented(store)
    store.write_json({"run_id": "r2", "pareto": [_offer(store, "Newer")]}, "rankings", "r2.json")
    assert [(g["ranking"], g["problem"]) for g in unpresented_ranking(store)] == [
        ("r2.json", "undatable")
    ]


def test_a_step_5_stimulus_reaction_owes_no_decision(tmp_path: Path) -> None:
    """F3: step-05 Outputs — reactions tied to a stimulus offer left `new`."""
    store = _store(tmp_path)
    _say_about(
        store, _offer(store), "Massa hores per aquest sou.", step="reactions", kind="reaction"
    )
    assert unrecorded_discards(store) == []


def test_a_step_5_statement_about_a_stimulus_owes_no_decision(tmp_path: Path) -> None:
    """F3: scoped by step as well as kind. A statement in step 5 is not a step-10 decision."""
    store = _store(tmp_path)
    _say_about(store, _offer(store), "no treballaria mai en banca", step="reactions")
    assert unrecorded_discards(store) == []


def test_a_step_10_aside_owes_no_decision(tmp_path: Path) -> None:
    """F3: step-10 Never — no status is inferred from a remark that is not a decision."""
    store = _store(tmp_path)
    _say_about(store, _offer(store), "la oficina parece bonita", kind="reaction")
    assert unrecorded_discards(store) == []


def test_a_ruled_out_offer_purged_later_is_carried_by_its_tombstone(tmp_path: Path) -> None:
    """F3: `purge_offer` drops the lifecycle record and keeps the evidence row."""
    store = _store(tmp_path)
    oid = _offer(store)
    rule_out(store, oid, "nada de banca", at=_SHOWN)
    purge_offer(store, oid, at="2027-01-01T00:00:00Z", now=datetime(2027, 1, 1, tzinfo=UTC))
    assert not store.path("offers", "lifecycle", f"{oid}.json").exists()
    assert unrecorded_discards(store) == []


def test_the_feedback_checkpoint_also_asks_about_a_re_shown_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F4: step 10 re-ranks and re-shows; that list owes a present() row too."""
    module = _script("step-10-feedback")
    gap, ok = _store(tmp_path, "gap"), _store(tmp_path, "ok")
    _rank(gap, [_offer(gap)])
    shown = _offer(ok)
    _rank(ok, [shown])
    present(ok, [shown], at=_SHOWN)
    opened = _checkpoint(module, monkeypatch, tmp_path, "gap")
    closed = _checkpoint(module, monkeypatch, tmp_path, "ok")
    assert opened["unpresented_ranking"] and opened["coverage_met"] is False
    assert closed["unpresented_ranking"] == [] and closed["coverage_met"] is True


def _script(step_dir: str) -> ModuleType:
    path = _ROOT / ".claude" / "skills" / step_dir / "scripts" / "run_checkpoint.py"
    spec = importlib.util.spec_from_file_location(f"_t226_{step_dir.replace('-', '_')}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _checkpoint(
    module: Any, monkeypatch: pytest.MonkeyPatch, root: Path, handle: str
) -> dict[str, Any]:
    monkeypatch.setattr(module, "is_finished", lambda *_a, **_k: True)
    result: dict[str, Any] = module.checkpoint(root, handle)
    return result


def test_the_ranking_checkpoint_refuses_coverage_while_the_list_is_unpresented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wired, not merely available: the step is otherwise finished and still not covered."""
    module = _script("step-09-ranking")
    gap, ok = _store(tmp_path, "gap"), _store(tmp_path, "ok")
    _rank(gap, [_offer(gap)])
    shown = _offer(ok)
    _rank(ok, [shown])
    present(ok, [shown], at=_SHOWN, standing=Standing("strengths", "widen"))
    silent = _store(tmp_path, "silent")  # T209: shown, but the standing lines were never said
    quiet = _offer(silent)
    _rank(silent, [quiet])
    present(silent, [quiet], at=_SHOWN)

    opened = _checkpoint(module, monkeypatch, tmp_path, "gap")
    closed = _checkpoint(module, monkeypatch, tmp_path, "ok")
    mute = _checkpoint(module, monkeypatch, tmp_path, "silent")
    assert opened["unpresented_ranking"] and opened["coverage_met"] is False
    assert closed["unpresented_ranking"] == [] and closed["coverage_met"] is True
    assert closed["unstated_standing"] == []
    assert mute["unstated_standing"] and mute["coverage_met"] is False


def test_the_feedback_checkpoint_refuses_coverage_while_a_reaction_has_no_rule_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _script("step-10-feedback")
    gap, ok = _store(tmp_path, "gap"), _store(tmp_path, "ok")
    _say_about(gap, _offer(gap), "no me interesa la banca")
    rule_out(ok, _offer(ok), "no me interesa la banca", at=_SHOWN)

    opened = _checkpoint(module, monkeypatch, tmp_path, "gap")
    closed = _checkpoint(module, monkeypatch, tmp_path, "ok")
    assert opened["unrecorded_discards"] and opened["coverage_met"] is False
    assert closed["unrecorded_discards"] == [] and closed["coverage_met"] is True
