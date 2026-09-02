"""T103: the configured merge policy makes a red CI blocking.

The named gate test is `test_the_configured_merge_policy_requires_ci`; the rest
guard the two preconditions and the fail directions. Every case builds its own
config, D-22 record and capture on disk — nothing here reaches the network, so
the suite says the same thing offline as it does on a laptop with `gh` logged
in, which is the point of the capture being committed at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral import merge_policy

GREEN_CAPTURE = {
    "workflow": "CI",
    "branch": "main",
    "conclusion": "success",
    "run_id": 1,
    "run_created_at": "2026-09-02T09:52:47Z",
    "captured_at": "2026-09-02",
}


def _tree(
    tmp_path: Path,
    *,
    policy: str | None = "after-ci-and-review",
    d22: dict[str, object] | None = None,
    capture: dict[str, object] | None = None,
) -> tuple[Path, Path, Path]:
    config = tmp_path / "config.toml"
    config.write_text("" if policy is None else f'merge-policy = "{policy}"\n', encoding="utf-8")
    d22_path = tmp_path / "D-22.json"
    d22_path.write_text(
        json.dumps({"ci_targets_missing_from_makefile": 0} if d22 is None else d22),
        encoding="utf-8",
    )
    capture_path = tmp_path / "ci-conclusion.json"
    if capture is not None:
        capture_path.write_text(json.dumps(capture), encoding="utf-8")
    return config, d22_path, capture_path


def _measure(tmp_path: Path, **kwargs: object) -> dict[str, object]:
    return merge_policy.measure(*_tree(tmp_path, **kwargs))  # type: ignore[arg-type]


def test_the_configured_merge_policy_requires_ci() -> None:
    """The gate itself, read off the repository's own files."""
    measured = merge_policy.measure()
    assert measured["gate_status"] == "measured", measured.get("unmeasured_reason")
    assert measured["merge_policy"] == "after-ci-and-review"
    assert measured["merge_policy_ignores_ci"] == 0, measured[
        "readings_that_say_ci_does_not_block"
    ]
    assert measured["merge_policy_ignores_ci_evaluated"] == 8


def test_the_committed_evidence_matches_what_the_code_measures() -> None:
    assert json.loads(merge_policy.DEFAULT_EVIDENCE_PATH.read_text()) == merge_policy.measure()


@pytest.mark.parametrize(
    ("policy", "blocks"),
    [("always", False), ("after-review", False), ("after-ci", True), ("never", True)],
)
def test_each_documented_policy_is_classified(policy: str, blocks: bool) -> None:
    assert merge_policy.a_red_check_blocks(policy) is blocks


def test_an_unrecognised_policy_reads_as_not_blocking() -> None:
    """Fail-closed: a typo in the setting fails the gate rather than passing it."""
    assert merge_policy.a_red_check_blocks("after-ci-and-reviwe") is False


def test_a_policy_that_ignores_ci_is_counted(tmp_path: Path) -> None:
    measured = _measure(tmp_path, policy="after-review", capture=GREEN_CAPTURE)
    assert measured["merge_policy_ignores_ci"] == 1
    assert measured["gate_status"] == "measured"


def test_d22_without_t101s_key_is_unmeasured_not_a_pass(tmp_path: Path) -> None:
    """The dependency fails legibly instead of as a `KeyError`."""
    measured = _measure(tmp_path, d22={"gates_required": 5}, capture=GREEN_CAPTURE)
    assert measured["gate_status"] == "unmeasured"
    assert "T101" in str(measured["unmeasured_reason"])
    assert measured[merge_policy.CI_TARGETS_KEY] is None


def test_a_ci_job_naming_a_missing_target_is_counted(tmp_path: Path) -> None:
    measured = _measure(
        tmp_path, d22={"ci_targets_missing_from_makefile": 2}, capture=GREEN_CAPTURE
    )
    assert measured["merge_policy_ignores_ci"] == 1
    assert measured["gate_status"] == "measured"


def test_a_missing_capture_is_unmeasured_not_a_pass(tmp_path: Path) -> None:
    measured = _measure(tmp_path, capture=None)
    assert measured["gate_status"] == "unmeasured"
    assert measured["merge_policy_ignores_ci"] == 0
    assert "--refresh-ci" in str(measured["unmeasured_reason"])


def test_a_capture_of_another_branch_does_not_answer_this_question(tmp_path: Path) -> None:
    measured = _measure(tmp_path, capture={**GREEN_CAPTURE, "branch": "release"})
    assert measured["gate_status"] == "unmeasured"


def test_a_red_latest_ci_run_is_counted(tmp_path: Path) -> None:
    measured = _measure(tmp_path, capture={**GREEN_CAPTURE, "conclusion": "failure"})
    assert measured["merge_policy_ignores_ci"] == 1
    assert "failure" in measured["readings_that_say_ci_does_not_block"][0]  # type: ignore[index]


def test_an_unreadable_config_is_unmeasured_not_a_pass(tmp_path: Path) -> None:
    measured = _measure(tmp_path, policy=None, capture=GREEN_CAPTURE)
    assert measured["gate_status"] == "unmeasured"


def test_a_reader_control_the_module_gets_wrong_is_counted_as_a_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The number has to move when the classifier breaks, not only the config."""
    monkeypatch.setattr(merge_policy, "a_red_check_blocks", lambda policy: True)
    measured = _measure(tmp_path, capture=GREEN_CAPTURE)
    assert measured["policy_reader_control_failures"] == ["always", "after-review"]
    assert measured["merge_policy_ignores_ci"] == 2


@pytest.mark.parametrize(
    ("reader", "name"),
    [
        (merge_policy.configured_policy, "config.toml"),
        (merge_policy.ci_targets_missing, "D-22.json"),
        (merge_policy.read_capture, "ci-conclusion.json"),
    ],
)
def test_a_file_that_is_not_utf8_reads_as_unreadable(
    tmp_path: Path, reader: object, name: str
) -> None:
    """#304 review. `read_text(encoding="utf-8")` raises `UnicodeDecodeError`
    on a file that is not valid UTF-8, and that is neither an `OSError` nor a
    parse error — so it escaped all three readers and took the command down
    instead of reporting `unmeasured`. Every reader answers `None`.
    """
    corrupt = tmp_path / name
    corrupt.write_bytes(b"\xff\xfe\x00not utf-8 at all")
    assert reader(corrupt) is None  # type: ignore[operator]


def test_a_gate_run_over_undecodable_files_is_unmeasured_not_a_pass(tmp_path: Path) -> None:
    """The three readers together: an undecodable tree measures nothing."""
    for name in ("config.toml", "D-22.json", "ci-conclusion.json"):
        (tmp_path / name).write_bytes(b"\xff\xfe\x00")
    measured = merge_policy.measure(
        config=tmp_path / "config.toml",
        d22=tmp_path / "D-22.json",
        capture=tmp_path / "ci-conclusion.json",
    )
    assert measured["gate_status"] == "unmeasured"
