"""`make evidence` runs its modules concurrently without changing what it reports.

No real evidence module runs here: `_run` is replaced by a stub.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from integral import evidence_runner

_ROOT = Path(__file__).resolve().parent.parent

# The Makefile's former serial loop selected modules with exactly this pipeline.
_OLD_PIPELINE = (
    "grep -l '__main__' src/integral/*.py"
    " | xargs grep -lE 'status/evidence|\"evidence\"|EVIDENCE'"
    " | sed 's|.*/||; s|\\.py$||'"
)


def test_discovery_equals_the_old_shell_pipeline() -> None:
    out = subprocess.run(
        _OLD_PIPELINE, shell=True, cwd=_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    found = evidence_runner.discover()
    # The driver itself mentions evidence and has a `__main__`; it must not run itself.
    assert set(found) == set(out) - {"evidence_runner"}
    assert "evidence_runner" not in found
    assert found == sorted(found)
    assert len(found) > 50


@pytest.mark.parametrize(
    ("code", "line"),
    [
        (0, "ok"),
        (3, "unmeasured (recorded)"),
        (1, "GATE FAILED"),
        (2, "GATE FAILED"),
        (-9, "GATE FAILED"),
        (127, "GATE FAILED"),
    ],
)
def test_status_mapping(code: int, line: str) -> None:
    assert evidence_runner.status_line(code) == line


def _stub(
    codes: dict[str, int], delays: dict[str, float] | None = None
) -> Callable[[str], tuple[str, int, str]]:
    def run(module: str) -> tuple[str, int, str]:
        time.sleep((delays or {}).get(module, 0))
        return module, codes[module], f"stderr of {module}\n"

    return run


def test_results_are_sorted_whatever_order_they_finish_in(monkeypatch: pytest.MonkeyPatch) -> None:
    codes = {"c": 0, "a": 0, "b": 0}
    monkeypatch.setattr(evidence_runner, "_run", _stub(codes, {"a": 0.15, "b": 0.05}))
    results = evidence_runner.run_all(["c", "a", "b"], 3)
    assert [r[0] for r in results] == ["a", "b", "c"]


def test_modules_really_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    barrier = threading.Barrier(3, timeout=5)

    def run(module: str) -> tuple[str, int, str]:
        barrier.wait()  # only passes if three run at once
        return module, 0, ""

    monkeypatch.setattr(evidence_runner, "_run", run)
    assert [r[1] for r in evidence_runner.run_all(["a", "b", "c"], 3)] == [0, 0, 0]


def test_main_reports_every_failure_not_the_first(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    codes = {"alpha": 0, "beta": 1, "gamma": 3, "delta": 2}
    monkeypatch.setattr(evidence_runner, "discover", lambda: sorted(codes, reverse=True))
    monkeypatch.setattr(evidence_runner, "_run", _stub(codes))
    assert evidence_runner.main() == 1
    cap = capsys.readouterr()
    lines = [ln.split() for ln in cap.out.splitlines()]
    assert [ln[0] for ln in lines] == ["alpha", "beta", "delta", "gamma"]
    assert cap.out.count("GATE FAILED") == 2
    assert "unmeasured (recorded)" in cap.out
    assert "stderr of beta" in cap.err and "stderr of delta" in cap.err
    assert "stderr of alpha" not in cap.err and "stderr of gamma" not in cap.err


def test_unmeasured_alone_is_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    codes = {"a": 0, "b": 3}
    monkeypatch.setattr(evidence_runner, "discover", lambda: ["a", "b"])
    monkeypatch.setattr(evidence_runner, "_run", _stub(codes))
    assert evidence_runner.main() == 0


def test_jobs_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVIDENCE_JOBS", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 6)
    assert evidence_runner.jobs() == 6
    monkeypatch.setenv("EVIDENCE_JOBS", "2")
    assert evidence_runner.jobs() == 2
    for bad in ("0", "-1", "many", ""):
        monkeypatch.setenv("EVIDENCE_JOBS", bad)
        assert evidence_runner.jobs() == 6
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    assert evidence_runner.jobs() == 1


def test_the_makefile_calls_the_driver_once_and_keeps_the_drift_check() -> None:
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("\nevidence:", 1)[1].split("\n\n", 1)[0]
    assert target.count("integral.evidence_runner") == 1
    assert "git diff --exit-code --stat status/evidence/" in target
    assert "integral.$$m" not in target


def test_a_real_module_failure_fails_main(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The real `_run`, no stub: a module that cannot be imported exits non-zero.
    monkeypatch.setattr(evidence_runner, "discover", lambda: ["no_such_evidence_module"])
    assert evidence_runner.main() == 1
    assert "GATE FAILED" in capsys.readouterr().out


def test_the_makefile_does_not_swallow_the_drivers_exit_code() -> None:
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("\nevidence:", 1)[1].split("\n\n", 1)[0]
    runner = [ln for ln in target.splitlines() if "integral.evidence_runner" in ln]
    assert runner == ["\t@uv run python -m integral.evidence_runner"]
