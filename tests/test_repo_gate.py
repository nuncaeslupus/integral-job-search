"""T85 — does the evidence run reach every module that writes evidence?

`make evidence` regenerates every module's committed number and fails on any
drift, but its own module list used to be derived by grepping
`src/integral/*.py` for `^def _main` — a naming convention on the
entry-point function, not on what the module actually does. Three modules
(`plan_v2`, `process_spec`, `step_specs`) write evidence through a function
named `main` instead, and were invisible to that loop: `T85: The evidence run
reaches every module that writes evidence` (arsenal task `t-cd8dcc16`) found
`S8.json`'s committed `plan_rows` reading 81 against 107 actually measured,
while `make evidence` exited 0 printing "no drift".

`repo_gate.evidence_writing_modules` is the fix, and these tests hold it to
what the task requires: it must find every module that writes evidence (not
just the three the bug report named), it must not depend on any naming
convention to do it, and its own gate must not pass on an empty input set.
"""

from __future__ import annotations

from pathlib import Path

from integral import repo_gate

REPO_ROOT = Path(__file__).resolve().parents[1]

# The selection `make evidence` used before T85: `grep -l '^def _main'`,
# which finds a module by the name of its entry-point function rather than by
# what it writes. Frozen here as a fixture so the regression it caused stays
# provable even after the real Makefile no longer reads this way.
_OLD_MAIN_NAMING_TARGET = """\
.PHONY: evidence

evidence:  ## regenerate every module's gate evidence and fail on any drift
\t@for m in $$(grep -l '^def _main' src/integral/*.py \\
\t\t| xargs -n1 basename | sed 's/\\.py$$//'); do \\
\t\tprintf '  %-18s ' "$$m"; \\
\t\tuv run python -m integral.$$m >/dev/null || { echo "GATE FAILED"; exit 1; }; \\
\t\techo ok; \\
\tdone
\t@git diff --exit-code --stat status/evidence/ \\
\t\t|| { echo "evidence: drift" >&2; exit 1; }
\t@echo "evidence: no drift"
"""


def test_every_module_writing_evidence_is_reached_by_the_evidence_run() -> None:
    """Against the real repo, `make evidence`'s own module list is complete."""
    measured = repo_gate.measure_evidence_reach()

    assert measured["gate_status"] == "measured"
    assert measured["modules_missing"] == []
    assert measured["gate_modules_outside_the_evidence_run"] == 0


def test_a_module_that_writes_evidence_and_is_missed_fails_the_check(tmp_path: Path) -> None:
    """The pre-T85 selection misses exactly the three modules the bug report named.

    `plan_v2`, `process_spec` and `step_specs` write evidence through a
    function named `main`, not `_main`, so `grep -l '^def _main'` never found
    them. Every other evidence-writing module in the real tree does define
    `_main` (or, like `plan_v2`'s own siblings before this task, would have
    been caught the same way), so this fixture's violation set is exactly
    those three — not a superset padded by unrelated modules.
    """
    old_makefile = tmp_path / "Makefile"
    old_makefile.write_text(_OLD_MAIN_NAMING_TARGET, encoding="utf-8")

    measured = repo_gate.measure_evidence_reach(makefile=old_makefile, repo_root=REPO_ROOT)

    assert measured["gate_status"] == "measured"
    assert measured["modules_missing"] == ["plan_v2", "process_spec", "step_specs"]
    assert measured["gate_modules_outside_the_evidence_run"] == 3


def test_the_selection_does_not_depend_on_a_private_name_convention() -> None:
    """Discovery reads the evidence path a module actually constructs, never
    the name of the function or constant that holds it.

    A module whose entry point is named `main`, `_main`, or something else
    again — `write_cycle_evidence`, `probe_suggestions` — is not what
    `_writes_evidence` looks at; a synthetic source snippet with a
    deliberately arbitrary function name proves the point without needing
    three more real modules to make it.
    """
    writes_evidence_source = (
        "from pathlib import Path\n\n"
        "SOME_OBSCURELY_NAMED_CONSTANT = Path('status') / 'evidence' / 'made-up.json'\n\n"
        "def some_arbitrarily_named_entry_point():\n"
        "    return SOME_OBSCURELY_NAMED_CONSTANT\n"
    )
    assert repo_gate._writes_evidence(writes_evidence_source) is True

    does_not_write_evidence_source = (
        "from pathlib import Path\n\n"
        "SOME_OTHER_PATH = Path('status') / 'not-evidence' / 'made-up.json'\n\n"
        "def main():\n"
        "    return SOME_OTHER_PATH\n"
    )
    assert repo_gate._writes_evidence(does_not_write_evidence_source) is False


def test_the_gate_does_not_pass_on_an_empty_input_set(tmp_path: Path) -> None:
    """A zero violation count over zero modules checked is not a pass."""
    empty_src_dir = tmp_path / "no_evidence_writing_modules_here"
    empty_src_dir.mkdir()

    empty = repo_gate.measure_evidence_reach(src_dir=empty_src_dir)
    assert empty["gate_modules_outside_the_evidence_run_evaluated"] == 0
    assert empty["gate_modules_discovered"] == 0
    assert empty["gate_status"] == "unmeasured", (
        "a zero violation count over zero modules checked is not a pass — "
        "the gate must be able to tell the two apart"
    )

    real = repo_gate.measure_evidence_reach()
    assert real["gate_modules_outside_the_evidence_run_evaluated"] > 0
    assert real["gate_modules_discovered"] > 0
    assert real["gate_status"] == "measured"
