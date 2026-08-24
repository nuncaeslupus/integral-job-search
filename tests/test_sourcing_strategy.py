"""T62 — exhaustion as a measurement: a cycle that keeps finding the same jobs.

`status/specs/iterative-sourcing.md` §5.2. Two things are checked here that a
reading of the code would otherwise have to be trusted on: that a cycle which
returned *nothing* is exhausted for its own stated reason rather than for a
repeat share of zero, and that an exhaustion carrying no reason cannot be
constructed at all — it is a violation, not a trigger.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from integral.sourcing_strategy import (
    EXHAUSTION_REPEAT_SHARE,
    Exhaustion,
    judge_cycle,
    probe_exhaustion,
    write_evidence,
)


def test_a_cycle_repeating_known_offers_is_exhausted() -> None:
    judged = judge_cycle(cycle=2, offers_returned=10, offers_already_seen=9)
    assert judged.repeat_share > EXHAUSTION_REPEAT_SHARE
    assert judged.exhausted
    assert judged.reason.strip()


def test_a_cycle_finding_new_work_is_not_exhausted() -> None:
    judged = judge_cycle(cycle=1, offers_returned=10, offers_already_seen=1)
    assert not judged.exhausted
    assert judged.reason == ""


def test_the_threshold_is_the_boundary_and_not_beyond_it() -> None:
    judged = judge_cycle(cycle=3, offers_returned=10, offers_already_seen=8)
    assert judged.repeat_share == pytest.approx(EXHAUSTION_REPEAT_SHARE)
    assert judged.exhausted


def test_a_cycle_that_returned_nothing_is_exhausted_for_its_own_reason() -> None:
    judged = judge_cycle(cycle=4, offers_returned=0, offers_already_seen=0)
    assert judged.repeat_share == 0.0
    assert judged.exhausted
    # A zero share must not read as "nothing was repeated, so all is well": the
    # reason has to name the empty return, not the repetition that did not happen.
    assert "repeat" not in judged.reason.lower()
    assert "no offers" in judged.reason.lower()


def test_no_exhaustion_is_recorded_without_a_reason() -> None:
    with pytest.raises(ValidationError):
        Exhaustion(
            cycle=1,
            offers_returned=10,
            offers_already_seen=10,
            repeat_share=1.0,
            exhausted=True,
            reason="   ",
        )


def test_a_repeat_share_that_contradicts_the_counts_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Exhaustion(
            cycle=1,
            offers_returned=10,
            offers_already_seen=2,
            repeat_share=0.9,
            exhausted=True,
            reason="claims a repeat share the counts do not support",
        )


def test_more_seen_than_returned_is_rejected() -> None:
    with pytest.raises(ValidationError):
        judge_cycle(cycle=1, offers_returned=2, offers_already_seen=3)


def test_the_probe_finds_no_reasonless_trigger_and_is_not_vacuous() -> None:
    measured = probe_exhaustion()
    assert measured["exhaustion_triggers_without_a_reason"] == 0
    assert measured["failures"] == []
    # A probe that never triggered would pass by not measuring anything.
    assert measured["exhaustion_triggers"] >= 2
    assert measured["reasonless_construction_rejected"] is True


def test_the_evidence_file_carries_the_gate_key(tmp_path: Path) -> None:
    target = tmp_path / "T62.json"
    measured = write_evidence(target)
    assert json.loads(target.read_text(encoding="utf-8")) == measured
    assert measured["exhaustion_triggers_without_a_reason"] == 0
