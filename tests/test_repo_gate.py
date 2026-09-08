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

**T101 is here too**, because it is the same module's second half: every
`make` target a CI job names must be a rule the Makefile defines.
`verify-subtree` lost its rule in #123 and its job kept calling it, failing on
every run until 2026-09-01 and invisible while the runner outage failed every
job anyway. The check must read the workflows as parsed YAML — the comment
that named `verify-subtree` outlived the job by six weeks, so a regex over the
file text reports a violation that is not there.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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


def test_an_unreadable_evidence_target_is_unmeasured_not_a_traceback(tmp_path: Path) -> None:
    """A rewritten `evidence` recipe this cannot parse must report that the
    reach is unscoreable, not abort the run. Merging two branches that both
    edit that recipe is the realistic way to produce one."""
    makefile = tmp_path / "Makefile"
    makefile.write_text("evidence:\n\t@echo nothing here\n", encoding="utf-8")

    measured = repo_gate.measure_evidence_reach(makefile=makefile)

    assert measured["gate_status"] == "unmeasured"
    assert "cannot read the evidence target" in measured["unmeasured_reason"]


def test_a_failing_module_list_command_is_unmeasured_not_a_traceback(tmp_path: Path) -> None:
    """Same rule for the module-list command itself exiting non-zero."""
    makefile = tmp_path / "Makefile"
    makefile.write_text(
        "evidence:\n\t@for m in $$(exit 7); do \\\n\t\techo $$m; \\\n\tdone\n", encoding="utf-8"
    )

    measured = repo_gate.measure_evidence_reach(makefile=makefile)

    assert measured["gate_status"] == "unmeasured"
    assert "module list failed to evaluate" in measured["unmeasured_reason"]


# ---------------------------------------------------------------------------
# T101 — a CI job may not name a Makefile target that does not exist


def _repo(tmp_path: Path, makefile: str, workflow: str) -> Path:
    """A throwaway repository root: one Makefile, one workflow."""
    (tmp_path / "Makefile").write_text(makefile, encoding="utf-8")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(workflow, encoding="utf-8")
    return tmp_path


def test_every_target_this_repositorys_ci_runs_exists() -> None:
    """Against the real tree — the assertion the task is for."""
    measured = repo_gate.measure()

    assert measured["ci_targets_missing"] == []
    assert measured["ci_targets_missing_from_makefile"] == 0
    # Not a vacuous zero: CI really does run `make`, and what it runs includes
    # the four `CLAUDE.md` requires before a merge.
    assert measured["ci_targets_missing_from_makefile_evaluated"] >= 4
    assert set(repo_gate.ci_make_targets()) >= {"lint", "test", "evidence", "verify-gates"}
    # The constructed controls go through the same reader and are counted, so
    # the denominator moves when the reader regresses and not only when a
    # workflow does.
    assert measured["ci_reader_control_failures"] == []
    assert len(measured["ci_reader_controls"]) == len(repo_gate.CI_READER_CONTROLS)
    assert measured["ci_targets_missing_from_makefile_evaluated"] == len(
        repo_gate.ci_make_targets()
    ) + sum(len(expected) for _, _, expected in repo_gate.CI_READER_CONTROLS)


def test_a_delimiter_glued_to_the_target_name_does_not_hide_it(tmp_path: Path) -> None:
    """Fail-open, and the worse direction. `shlex.split` keeps `ghost;` as one
    token, `_TARGET_TOKEN_RE` rejects it, and the missing target is never
    reported — the gate goes green over a broken workflow. Review on #291."""
    root = _repo(
        tmp_path,
        "lint:\n\ttrue\n",
        "jobs:\n"
        "  everything:\n"
        "    steps:\n"
        "      - run: |\n"
        "          make ghost; make phantom && make lint\n"
        "          make spectre | tee log\n"
        "          (make wraith)\n",
    )

    assert repo_gate.ci_make_targets_missing(root) == ["ghost", "phantom", "spectre", "wraith"]


def test_run_outside_a_step_is_data_and_not_a_shell_command(tmp_path: Path) -> None:
    """`run` is a shell command in exactly one place in the Actions schema:
    `jobs.<job_id>.steps[*].run`. An environment variable called `run` is
    someone's data, and reading it invents a violation that is not there —
    `--check` then exits 1 over a valid workflow. Review on #291."""
    root = _repo(
        tmp_path,
        "lint:\n\ttrue\n",
        "env:\n"
        "  run: make ghost\n"
        "jobs:\n"
        "  build:\n"
        "    env:\n"
        "      run: make phantom\n"
        "    steps:\n"
        "      - with:\n"
        "          run: make spectre\n"
        "      - run: make lint\n",
    )

    assert repo_gate.ci_make_targets(root / ".github" / "workflows") == ["lint"]
    assert repo_gate.ci_make_targets_missing(root) == []


def test_a_reader_control_the_module_gets_wrong_is_counted_as_a_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The controls are not decoration: a reader that misreads one has to make
    the number this gate asserts is zero move."""
    monkeypatch.setattr(
        repo_gate,
        "CI_READER_CONTROLS",
        (("a control nothing can satisfy", "jobs:\n  a:\n    steps: []\n", ("ghost",)),),
    )
    measured = repo_gate.measure_ci_targets()

    assert measured["ci_targets_missing_from_makefile"] == 1
    assert "a control nothing can satisfy" in measured["ci_reader_control_failures"][0]


def test_a_workflow_naming_an_absent_target_is_reported(tmp_path: Path) -> None:
    """The fault this task came from: `verify-subtree` lost its rule in #123
    and its job kept calling it, red on every run for six weeks."""
    root = _repo(
        tmp_path,
        "lint:\n\truff check .\n",
        "jobs:\n  lint:\n    steps:\n      - run: make lint\n"
        "  dead:\n    steps:\n      - run: make verify-subtree\n",
    )

    assert repo_gate.ci_make_targets_missing(root) == ["verify-subtree"]


def test_a_target_named_only_in_a_comment_is_not_read_as_a_step(tmp_path: Path) -> None:
    """The regex trap. This repository's workflow comments discuss Make
    targets at length, and the comment naming `verify-subtree` outlived the
    job that ran it — a check reading the file text would report a violation
    that is not there, from a YAML comment, a step name or a shell comment."""
    root = _repo(
        tmp_path,
        "lint:\n\truff check .\n",
        "# make verify-subtree once ran here\n"
        "jobs:\n"
        "  lint:\n"
        "    steps:\n"
        "      # nor here: make verify-subtree\n"
        "      - name: make verify-subtree is only prose in a name\n"
        "        run: |\n"
        "          # and not here either: make verify-subtree\n"
        "          make lint\n",
    )

    assert repo_gate.ci_make_targets(root / ".github" / "workflows") == ["lint"]
    assert repo_gate.ci_make_targets_missing(root) == []


def test_a_multi_line_run_block_is_read(tmp_path: Path) -> None:
    """A `run: |` block is a shell script, and every `make` on any of its
    lines is a step that has to work — including a second one on the same
    line, which a per-line first-match read would miss."""
    root = _repo(
        tmp_path,
        "lint:\n\ttrue\n",
        "jobs:\n"
        "  everything:\n"
        "    steps:\n"
        "      - run: |\n"
        "          uv sync\n"
        "          make lint && make ghost\n"
        "          make phantom\n",
    )

    assert repo_gate.ci_make_targets_missing(root) == ["ghost", "phantom"]


def test_a_target_the_makefile_defines_but_ci_never_runs_is_not_a_violation(
    tmp_path: Path,
) -> None:
    """The direction this check deliberately does not assert. `format`,
    `clean`, `build`, `publish`, `sync`, `help`, `reader` and
    `labelling-round` are all deliberately not CI steps, so the converse would
    be false on a correct repository from its first run and the repair would
    be an allowlist edited every time a target is added."""
    root = _repo(
        tmp_path,
        "lint:\n\ttrue\nformat:\n\ttrue\nclean:\n\ttrue\npublish:\n\ttrue\n",
        "jobs:\n  lint:\n    steps:\n      - run: make lint\n",
    )

    assert repo_gate.ci_make_targets_missing(root) == []


def test_the_ci_reading_does_not_pass_over_a_workflow_tree_that_runs_no_make(
    tmp_path: Path,
) -> None:
    """A zero count over nothing scanned is not a pass, and neither is a
    workflow this cannot parse. Both record `-1` — and neither erases D-22's
    own answer about `CLAUDE.md`, which is a different question."""
    empty = tmp_path / "no-workflows-here"
    empty.mkdir()

    silent = repo_gate.measure_ci_targets(workflows=empty)
    assert silent["ci_targets_missing_from_makefile"] == -1
    assert silent["ci_targets_missing_from_makefile_evaluated"] == 0
    assert "scanned nothing" in silent["ci_unmeasured_reason"]

    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "ci.yml").write_text("jobs:\n  - [unbalanced\n", encoding="utf-8")
    unparseable = repo_gate.measure_ci_targets(workflows=broken)
    assert unparseable["ci_targets_missing_from_makefile"] == -1
    assert "could not be parsed" in unparseable["ci_unmeasured_reason"]

    # D-22's own reading survives both, because it does not depend on them.
    assert repo_gate.measure(workflows=empty)["required_gates_with_no_enforcement_point"] == 0


# ---------------------------------------------------------------------------
# T125 — the formatting metric, and the control that proves it is not vacuous.


def test_the_formatting_metric_moves_when_a_file_is_unformatted(tmp_path: Path) -> None:
    """The first version of this metric counted `^Would reformat: ` lines, which
    `ruff format --check` never emits — it prints a diff and one summary line. It
    reported `unformatted_files: 0` with a genuinely unformatted file in the
    tree, and only a negative control caught it. This is that control, kept."""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "Makefile").write_text("lint:\n\truff format --check .\n", encoding="utf-8")
    for name in ("a", "b", "c"):
        (repo / "src" / f"{name}.py").write_text("x = 1\n", encoding="utf-8")

    clean = repo_gate.measure_formatting(repo)
    assert clean["unformatted_files"] == 0
    assert clean["files_checked"] == 3

    (repo / "src" / "b.py").write_text("def f( a,b ):\n    return   a+b\n", encoding="utf-8")
    dirty = repo_gate.measure_formatting(repo)
    assert dirty["unformatted_files"] == 1, dirty
    assert dirty["files_checked"] == 3, dirty


def test_a_formatted_tree_with_no_check_in_lint_is_still_a_finding(tmp_path: Path) -> None:
    """`unformatted_files == 0` is satisfiable by a tree nobody will check again.
    The formatting is the state; the check in `make lint` is what keeps it."""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "Makefile").write_text("lint:\n\truff check .\n", encoding="utf-8")
    (repo / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

    measured = repo_gate.measure_formatting(repo)
    assert measured["unformatted_files"] == 0
    assert measured["lint_runs_the_check"] is False


def test_a_scan_that_found_almost_nothing_is_unmeasured(tmp_path: Path) -> None:
    """A zero over three files is what a broken invocation also reports."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text("lint:\n\truff format --check .\n", encoding="utf-8")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    measured = repo_gate.measure_formatting(repo)
    assert measured["gate_status"] == "unmeasured"
    assert measured["files_checked"] < repo_gate.MINIMUM_FILES_FORMATTED


# ---------------------------------------------------------------------------
# T150 — a committed evidence key must not move when the tree gains a file.


def test_the_formatting_record_commits_a_floor_and_not_the_count_of_the_day() -> None:
    """T125 committed `files_checked` exactly, and ruff 0.16 reads Markdown, so
    a pull request of nine task files and no Python moved it 453 -> 462 and
    `make evidence` went red about formatting it had no finding on. The floor
    is the denominator's whole job — `unformatted_files == 0` must not rest on
    an empty scan — and it does not move."""
    small = repo_gate.record_formatting(
        {"unformatted_files": 0, "files_checked": 465, "gate_status": "measured"}
    )
    grown = repo_gate.record_formatting(
        {"unformatted_files": 0, "files_checked": 474, "gate_status": "measured"}
    )

    assert "files_checked" not in small
    assert small["files_checked_at_least"] == repo_gate.MINIMUM_FILES_FORMATTED
    assert small == grown, "nine added task files must not change what is committed"
    assert small["unformatted_files"] == 0, "the finding itself is untouched"


def test_adding_a_markdown_file_adds_one_to_the_formatter_population(tmp_path: Path) -> None:
    """The fact `_one_more_file` encodes, measured rather than assumed: since
    ruff 0.16 the formatter reads Markdown, so `arsenal/tasks/` is inside
    `files_checked` and every task file lands in it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text("lint:\n\truff format --check .\n", encoding="utf-8")
    for name in ("a", "b", "c"):
        (repo / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")
    before = repo_gate.measure_formatting(repo)
    assert before["files_checked"] == 3

    (repo / "d.md").write_text("# d\n", encoding="utf-8")
    after = repo_gate.measure_formatting(repo)
    assert after["files_checked"] == before["files_checked"] + 1
    assert after["unformatted_files"] == 0


def _census_source(name: str = "census") -> repo_gate.EvidenceSource:
    """A source that commits its population exactly — T125 before this task."""
    return repo_gate.EvidenceSource(
        name=name,
        measure=lambda repo_root: {"findings": 0, "files": 400},
        record=dict,
        mutations={
            repo_gate.A_FILE_IS_ADDED: repo_gate._one_more_file("files"),
            repo_gate.A_TASK_FILE_IS_ARCHIVED: lambda repo_root, measured: {
                **measured,
                "files": measured["files"] - 1,
            },
        },
    )


def test_a_key_that_moves_when_a_file_is_added_is_named(tmp_path: Path) -> None:
    """The control. T100 compared its record across an archive only, and
    archiving moves a task file *inside* the tree — ruff formats it either way
    — so the key that drifts on every added file survived it."""
    measured = repo_gate.measure_evidence_stability(tmp_path, sources=[_census_source()])

    assert measured["gate_status"] == "measured"
    assert measured["unstable_evidence_keys"] == 2, measured
    assert "census.files moves when a Markdown file is added" in measured["unstable"]
    assert "census.files moves when a task file is archived" in measured["unstable"]


def test_a_floor_in_place_of_the_census_is_what_makes_it_stable(tmp_path: Path) -> None:
    """The same source, recorded T100's way: the live count out, the floor in."""
    census = _census_source()
    floored = repo_gate.EvidenceSource(
        name=census.name,
        measure=census.measure,
        record=lambda measured: {
            **{key: value for key, value in measured.items() if key != "files"},
            "files_at_least": 300,
        },
        mutations=census.mutations,
    )

    measured = repo_gate.measure_evidence_stability(tmp_path, sources=[floored])
    assert measured["unstable_evidence_keys"] == 0, measured
    assert measured["evidence_keys_compared"] == 4, measured
    assert measured["gate_status"] == "measured"


def test_a_mutation_that_moves_nothing_is_not_a_comparison(tmp_path: Path) -> None:
    """A record compared with itself agrees with itself. That is the shape
    `naming.first_task_file` was rewritten to avoid, and a registry made of it
    must report `unmeasured` rather than a clean zero."""
    inert = repo_gate.EvidenceSource(
        name="inert",
        measure=lambda repo_root: {"findings": 0, "files": 400},
        record=dict,
        mutations={
            repo_gate.A_FILE_IS_ADDED: lambda repo_root, measured: dict(measured),
            repo_gate.A_TASK_FILE_IS_ARCHIVED: lambda repo_root, measured: dict(measured),
        },
    )

    measured = repo_gate.measure_evidence_stability(tmp_path, sources=[inert])
    assert measured["unstable_evidence_keys"] == 0
    assert measured["evidence_keys_compared"] == 0
    assert measured["gate_status"] == "unmeasured"
    assert any("moved nothing" in reason for reason in measured["reasons"])


def test_stability_reached_by_committing_nothing_is_unmeasured(tmp_path: Path) -> None:
    """`record` could satisfy "the mutation changes nothing" by dropping every
    key. The denominator is what refuses that: zero over zero is not a pass."""
    empty = repo_gate.EvidenceSource(
        name="empty",
        measure=lambda repo_root: {"files": 400},
        record=lambda measured: {},
        mutations={
            repo_gate.A_FILE_IS_ADDED: repo_gate._one_more_file("files"),
            repo_gate.A_TASK_FILE_IS_ARCHIVED: lambda repo_root, measured: {"files": 399},
        },
    )

    measured = repo_gate.measure_evidence_stability(tmp_path, sources=[empty])
    assert measured["evidence_keys_compared"] == 0
    assert measured["gate_status"] == "unmeasured"


def test_losing_the_added_file_half_is_unmeasured_not_a_pass(tmp_path: Path) -> None:
    """T100 was green while blind to one of the two mutations. A registry that
    exercises only the archive again must say so out loud."""
    census = _census_source()
    archive_only = repo_gate.EvidenceSource(
        name=census.name,
        measure=census.measure,
        record=lambda measured: {"findings": measured["findings"]},
        mutations={
            repo_gate.A_TASK_FILE_IS_ARCHIVED: census.mutations[repo_gate.A_TASK_FILE_IS_ARCHIVED]
        },
    )

    measured = repo_gate.measure_evidence_stability(tmp_path, sources=[archive_only])
    assert measured["unstable_evidence_keys"] == 0
    assert measured["gate_status"] == "unmeasured"
    assert measured["mutations_compared"] == ["a task file is archived"]
    assert any("a Markdown file is added" in reason for reason in measured["reasons"])


def test_this_repository_commits_nothing_that_moves_under_either_mutation() -> None:
    """T150's gate, over the real tree: both mutations exercised, no key moves."""
    measured = repo_gate.measure_evidence_stability()

    assert measured["gate_status"] == "measured", measured
    assert measured["unstable_evidence_keys"] == 0, measured["unstable"]
    assert measured["mutations_compared"] == [
        repo_gate.A_FILE_IS_ADDED,
        repo_gate.A_TASK_FILE_IS_ARCHIVED,
    ]
    assert measured["evidence_keys_compared"] >= 12, measured


def test_the_floor_is_below_what_this_tree_actually_holds() -> None:
    """A floor is only a floor while the population clears it. Raised above
    what the tree holds it stops being a denominator and becomes an assertion
    the repository cannot satisfy — `gate_status` goes `unmeasured` and nothing
    in the suite would otherwise notice, because every other test names the
    constant rather than a number."""
    measured = repo_gate.measure_formatting()

    assert measured["gate_status"] == "measured", measured
    assert measured["files_checked"] > repo_gate.MINIMUM_FILES_FORMATTED, measured
