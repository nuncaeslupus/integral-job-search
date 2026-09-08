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

import importlib.machinery
import inspect
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from integral import arsenal_source, repo_gate

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


def _tiny_repo(tmp_path: Path) -> Path:
    """A git repository the tree mutations can actually be applied to.

    Real, because the added-file mutation writes a real file and hands its path
    to every source: `git ls-files` cannot see an untracked file and `ruff`
    cannot see one that is not there, so a fake tree tests neither half.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text("lint:\n\truff format --check .\n", encoding="utf-8")
    for relative in ("arsenal/tasks/t-aaaa1111.md", "docs/guide.md", "claude-arsenal/AGENTS.md"):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# a file\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    return repo


def _population(repo_root: Path, added: frozenset[str], archived: frozenset[str]) -> set[str]:
    """Every Markdown path in the tree, as the mutations leave it."""
    live = {path.relative_to(repo_root).as_posix() for path in repo_root.rglob("*.md")}
    return (live | set(added)) - set(archived)


def _census_source(name: str = "census") -> repo_gate.EvidenceSource:
    """A source that commits its file population exactly — T125 before this task."""

    def measure(
        repo_root: Path,
        *,
        added: frozenset[str] = frozenset(),
        archived: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        return {"findings": 0, "files": len(_population(repo_root, added, archived))}

    return repo_gate.EvidenceSource(name=name, measure=measure, record=dict)


def _floored(source: repo_gate.EvidenceSource) -> repo_gate.EvidenceSource:
    """The same source, recorded T100's way: the live count out, the floor in."""
    return repo_gate.EvidenceSource(
        name=source.name,
        measure=source.measure,
        record=lambda measured: {
            **{key: value for key, value in measured.items() if key != "files"},
            "files_at_least": 2,
        },
    )


def test_a_key_that_moves_when_a_file_is_added_is_named(tmp_path: Path) -> None:
    """The control. T100 compared its record across an archive only, and
    archiving moves a task file *inside* the tree — ruff formats it either way
    — so the key that drifts on every added file survived it."""
    repo = _tiny_repo(tmp_path)
    measured = repo_gate.measure_evidence_stability(
        repo, sources=[_census_source()], minimum_keys=1, minimum_sources=1
    )

    assert measured["gate_status"] == "measured", measured
    assert "census.files moves when a Markdown file is added" in measured["unstable"]
    assert "census.files moves when a task file is archived" in measured["unstable"]


def test_a_floor_in_place_of_the_census_is_what_makes_it_stable(tmp_path: Path) -> None:
    repo = _tiny_repo(tmp_path)
    measured = repo_gate.measure_evidence_stability(
        repo, sources=[_floored(_census_source())], minimum_keys=1, minimum_sources=1
    )

    assert measured["unstable_evidence_keys"] == 0, measured
    assert measured["evidence_keys_compared"] == 4, measured
    assert measured["mutations_compared"] == [
        repo_gate.A_FILE_IS_ADDED,
        repo_gate.A_TASK_FILE_IS_ARCHIVED,
    ]


def test_a_second_census_key_the_registry_never_named_is_still_caught(tmp_path: Path) -> None:
    """F1, the second reader's own experiment, and the reason this gate was
    blocked. The first version mutated the *measurement* — `{**measured, key:
    population + 1}` for a hand-written key — and the two keys ever written were
    the two already known to be broken, so a record carrying a *second* exact
    census reported `stable, compared=17, unstable=0`. Nothing about the second
    key was different in kind; it simply had not been named.

    The mutation is now applied to the tree, so every population derived from it
    moves at once and a key nobody thought of moves with the rest."""
    repo = _tiny_repo(tmp_path)

    def measure(
        repo_root: Path,
        *,
        added: frozenset[str] = frozenset(),
        archived: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        population = _population(repo_root, added, archived)
        return {
            "findings": 0,
            "files": len(population),
            # The second census. The registry names neither key, and must not
            # have to.
            "markdown_files": sum(1 for path in population if path.endswith(".md")),
        }

    two_censuses = repo_gate.EvidenceSource(
        name="census",
        measure=measure,
        record=lambda m: {
            **{key: value for key, value in m.items() if key != "files"},
            "files_at_least": 2,
        },
    )
    measured = repo_gate.measure_evidence_stability(
        repo, sources=[two_censuses], minimum_keys=1, minimum_sources=1
    )

    assert measured["gate_status"] == "measured", measured
    assert "census.markdown_files moves when a Markdown file is added" in measured["unstable"]


def test_a_source_no_mutation_moves_is_unmeasured_not_a_pass(tmp_path: Path) -> None:
    """F3a. A record compared with itself agrees with itself — the shape
    `naming.first_task_file` was rewritten to avoid. Pooled across the registry
    it hid: with one source carrying both mutations, another source's coverage
    could degrade to identity and the run still read `measured` with both
    mutations advertised. Coverage is now required **per source**."""
    repo = _tiny_repo(tmp_path)
    inert = repo_gate.EvidenceSource(
        name="inert",
        measure=lambda repo_root, **_: {"findings": 0, "files": 400},
        record=dict,
    )
    measured = repo_gate.measure_evidence_stability(
        repo, sources=[_floored(_census_source()), inert], minimum_keys=1, minimum_sources=1
    )

    assert measured["unstable_evidence_keys"] == 0
    assert measured["gate_status"] == "unmeasured", measured
    assert measured["sources_compared"] == ["census"]
    assert any("inert was moved by no mutation" in reason for reason in measured["reasons"]), (
        measured["reasons"]
    )


def test_stability_reached_by_committing_nothing_is_unmeasured(tmp_path: Path) -> None:
    """F3b. `record` could satisfy "the mutation changes nothing" by dropping
    every key. Zero over zero is not a pass, and — the half that was missing —
    the *other* source staying healthy does not make up for it."""
    repo = _tiny_repo(tmp_path)
    empty = repo_gate.EvidenceSource(
        name="empty",
        measure=_census_source().measure,
        record=lambda measured: {},
    )
    measured = repo_gate.measure_evidence_stability(
        repo, sources=[_floored(_census_source()), empty], minimum_keys=1, minimum_sources=1
    )

    assert measured["gate_status"] == "unmeasured", measured
    assert measured["sources_compared"] == ["census"]
    assert any("empty was moved by no mutation" in reason for reason in measured["reasons"])


def test_a_source_missing_from_the_registry_trips_the_denominator() -> None:
    """F3c. A source deleted outright left no trace but `evidence_keys_compared`
    moving 16 -> 12, and nothing read that number: the record still said
    `measured`, `unstable_evidence_keys: 0`, both mutations compared. The only
    catch was `make evidence` byte-drift, defeated by regenerating and
    committing the new value. Both denominators are now asserted."""
    registry = repo_gate.evidence_sources()
    assert len(registry) >= repo_gate.MINIMUM_EVIDENCE_SOURCES_COMPARED

    thinned = repo_gate.measure_evidence_stability(
        sources=[source for source in registry if source.name != "T125"]
    )
    assert thinned["gate_status"] == "unmeasured", thinned
    assert thinned["unstable_evidence_keys"] == 0, "the finding count says nothing is wrong"
    assert thinned["evidence_keys_compared"] < repo_gate.MINIMUM_EVIDENCE_KEYS_COMPARED
    assert any("a source has left the registry" in reason for reason in thinned["reasons"])
    assert any("source(s) compared" in reason for reason in thinned["reasons"])


def test_the_registry_is_discovered_from_the_modules_that_write_evidence() -> None:
    """F2, the structural half. `evidence_sources()` was a literal 2-tuple
    naming T55 and T125 — the two records already caught committing a census —
    so it could not cover a third even in principle, and its own docstring
    asserted "the two that do today". `T58.bundle_files` was the third, sitting
    committed on `main`, and this gate reported a clean zero over it.

    A module now joins by declaring `EVIDENCE_SOURCES` beside the code that does
    the counting, and the gate asks every module that writes evidence."""
    discovered = {source.name for source in repo_gate.evidence_sources()}

    assert {"T55", "T125", "T58"} <= discovered, discovered
    declaring = repo_gate.modules_declaring_evidence_sources()
    assert {"naming", "arsenal_source", "repo_gate"} <= set(declaring), declaring
    assert repo_gate.evidence_sources_not_imported() == (), (
        "a module declares a source the registry cannot reach"
    )


def test_t58_commits_floors_and_not_the_bundle_census() -> None:
    """F2, the instance. `bundle_files` is `len(tracked files under
    claude-arsenal/)` — 47, of which 14 are Markdown — committed exactly, so a
    bundle refresh that adds one `references/*.md` turned `make evidence` red
    about vendoring it has no finding on."""
    small = arsenal_source.record(
        {"upstream_subtree_files": 0, "vendored_skills": 18, "bundle_files": 47}
    )
    grown = arsenal_source.record(
        {"upstream_subtree_files": 0, "vendored_skills": 19, "bundle_files": 48}
    )

    assert "bundle_files" not in small and "vendored_skills" not in small
    assert small["bundle_files_at_least"] == arsenal_source.MINIMUM_BUNDLE_FILES
    assert small["vendored_skills_at_least"] == arsenal_source.MINIMUM_VENDORED_SKILLS
    assert small == grown, "a bundle refresh must not change what is committed"
    assert small["upstream_subtree_files"] == 0, "the finding itself is untouched"


def test_the_bundle_census_would_be_caught_if_it_were_still_committed() -> None:
    """The same finding, made by the gate rather than asserted about it: T58
    recorded the way `main` records it is named unstable. This is what the
    hand-enumerated mutation could not do, because nothing had told it the key
    existed."""
    registry = repo_gate.evidence_sources()
    unfloored = repo_gate.EvidenceSource("T58", arsenal_source.measure, dict)
    measured = repo_gate.measure_evidence_stability(
        sources=[unfloored, *(source for source in registry if source.name != "T58")]
    )

    assert "T58.bundle_files moves when a Markdown file is added" in measured["unstable"], measured


def test_the_added_file_mutation_probes_every_place_markdown_lives() -> None:
    """A census over a path **prefix** only moves when the added file lands
    under that prefix, and `T58.bundle_files` counts `claude-arsenal/` alone. A
    probe in one directory would have re-created F1 one level up: a check that
    can only find the prefixes somebody thought of."""
    roots = {path.split("/")[0] if "/" in path else "" for path in repo_gate.probe_paths()}

    assert "claude-arsenal" in roots, "the prefix T58 counts"
    assert "arsenal" in roots, "where a task-seeding pull request adds files"
    assert all(path.endswith(repo_gate.PROBE_BASENAME) for path in repo_gate.probe_paths())


def test_the_probe_file_is_removed_again(tmp_path: Path) -> None:
    """It is a real file in the working tree for the length of one measurement.
    A probe left behind would be committed by the next `git add -A`."""
    repo = _tiny_repo(tmp_path)
    paths = repo_gate.probe_paths(repo)
    assert paths

    with repo_gate._a_markdown_file_is_added(repo) as population:
        assert population is not None
        assert all((repo / path).is_file() for path in paths)
    assert not any((repo / path).exists() for path in paths)


def test_this_repository_commits_nothing_that_moves_under_either_mutation() -> None:
    """T150's gate, over the real tree: both mutations exercised, every
    registered source moved by one of them, no committed key moves."""
    measured = repo_gate.measure_evidence_stability()

    assert measured["gate_status"] == "measured", measured
    assert measured["unstable_evidence_keys"] == 0, measured["unstable"]
    assert measured["mutations_compared"] == [
        repo_gate.A_FILE_IS_ADDED,
        repo_gate.A_TASK_FILE_IS_ARCHIVED,
    ]
    assert measured["evidence_keys_compared"] >= repo_gate.MINIMUM_EVIDENCE_KEYS_COMPARED
    assert measured["evidence_sources_compared"] >= repo_gate.MINIMUM_EVIDENCE_SOURCES_COMPARED


def test_the_floors_are_below_what_this_tree_actually_holds() -> None:
    """A floor is only a floor while the population clears it. Raised above what
    the tree holds it stops being a denominator and becomes an assertion the
    repository cannot satisfy."""
    measured = repo_gate.measure_formatting()

    assert measured["gate_status"] == "measured", measured
    assert measured["files_checked"] > repo_gate.MINIMUM_FILES_FORMATTED, measured
    assert measured["python_files_checked"] > repo_gate.MINIMUM_PYTHON_FILES_FORMATTED, measured


def test_a_scan_that_read_no_python_is_not_a_pass(tmp_path: Path) -> None:
    """F5. The total floor of 300 sat above both halves — Markdown 242, Python
    227 — which caught losing either, but by accident of today's counts and not
    by anything asserted. `arsenal/tasks/` grows about nine Markdown files per
    task-seeding pull request, so in six or seven of them Markdown alone clears
    300 and a run that read **zero Python** scores a clean pass. The Python
    floor says the thing the conflated total cannot, and does not expire."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Makefile").write_text("lint:\n\truff format --check .\n", encoding="utf-8")
    for index in range(repo_gate.MINIMUM_FILES_FORMATTED + 5):
        (repo / f"doc{index}.md").write_text("# a document\n", encoding="utf-8")

    measured = repo_gate.measure_formatting(repo)

    assert measured["files_checked"] > repo_gate.MINIMUM_FILES_FORMATTED, measured
    assert measured["python_files_checked"] == 0
    assert measured["gate_status"] == "unmeasured", "an all-Markdown scan is not a formatted repo"
    assert any("Python file(s) checked" in reason for reason in measured["reasons"])


def test_the_python_floor_catches_losing_the_package() -> None:
    """The case the total floor misses even today: `src/` is 104 of 469 files,
    and 469 - 104 = 365 clears 300, so the entire production package could go
    unscanned and the gate would report a clean pass. Against the Python
    population it cannot: 227 - 104 = 123, under the floor."""
    live = repo_gate.measure_formatting()
    src_files = len(
        subprocess.run(
            ["git", "-C", str(repo_gate._REPO_ROOT), "ls-files", "src/*.py", "src/**/*.py"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    )

    assert src_files > 0
    assert live["files_checked"] - src_files > repo_gate.MINIMUM_FILES_FORMATTED, (
        "the total floor does not catch losing src/ — that is why there is a second one"
    )
    assert live["python_files_checked"] - src_files < repo_gate.MINIMUM_PYTHON_FILES_FORMATTED


def test_the_stability_record_commits_floors_and_not_its_own_denominators() -> None:
    """The gate that exists to stop exact denominators being committed does not
    get to commit two of its own: `evidence_keys_compared` moves whenever any
    registered record gains a field, and `evidence_sources_compared` whenever a
    module joins."""
    small = repo_gate.record_evidence_stability(
        {"unstable_evidence_keys": 0, "evidence_keys_compared": 22, "evidence_sources_compared": 3}
    )
    grown = repo_gate.record_evidence_stability(
        {"unstable_evidence_keys": 0, "evidence_keys_compared": 27, "evidence_sources_compared": 4}
    )

    assert "evidence_keys_compared" not in small
    assert small["evidence_keys_compared_at_least"] == repo_gate.MINIMUM_EVIDENCE_KEYS_COMPARED
    assert small == grown


def test_the_gate_asserts_the_committed_floors() -> None:
    """The floors are arguments so a three-file fixture repository can be
    measured at all. Nothing on the run path passes them, and what is committed
    is the module constant — a floor that a caller can lower is a floor that
    could be lowered where it matters."""
    signature = inspect.signature(repo_gate.measure_evidence_stability)

    assert signature.parameters["minimum_keys"].default == repo_gate.MINIMUM_EVIDENCE_KEYS_COMPARED
    assert (
        signature.parameters["minimum_sources"].default
        == repo_gate.MINIMUM_EVIDENCE_SOURCES_COMPARED
    )
    committed = json.loads(
        (REPO_ROOT / "status" / "evidence" / "T150.json").read_text(encoding="utf-8")
    )
    assert committed["evidence_keys_compared_at_least"] == repo_gate.MINIMUM_EVIDENCE_KEYS_COMPARED
    assert (
        committed["evidence_sources_compared_at_least"]
        == repo_gate.MINIMUM_EVIDENCE_SOURCES_COMPARED
    )
    assert "evidence_keys_compared" not in committed


def test_a_declared_source_the_registry_cannot_reach_is_reported(tmp_path: Path) -> None:
    """Discovery reads the declarations rather than importing them, because
    `src/integral/` may not call `importlib` at all — the connector contract's
    safety story is that this package loads no code it did not ship. The cost is
    that a declaration is only reachable once something imports the module, and
    a fourth census module added tomorrow would be found by the scan and missing
    from the registry: F2 a second time. So it is a finding, not a shrug."""
    src = tmp_path / "integral"
    src.mkdir()
    (src / "later.py").write_text('EVIDENCE_SOURCES = (("T999", None, None),)\n', encoding="utf-8")

    assert repo_gate.modules_declaring_evidence_sources(src) == ("later",)
    assert repo_gate.evidence_sources_not_imported(src) == ("later",)
    assert repo_gate.evidence_sources(src) == ()
    assert repo_gate.evidence_sources_not_imported() == (), "the live tree reaches all of its own"


def test_a_source_declared_by_the_module_run_as_main_still_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`make evidence` runs `python -m integral.repo_gate`, which puts that file
    in `sys.modules` as `__main__`. Resolving a declaration by dotted key alone
    found T55 and T58, missed T125, and left the gate `unmeasured` under `make
    evidence` with the whole suite green. It is resolved by `__spec__`."""
    pretend = types.ModuleType("__main__")
    pretend.__spec__ = importlib.machinery.ModuleSpec("integral.ran_as_main", None)
    pretend.EVIDENCE_SOURCES = (("TX", None, None),)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "__main__", pretend)

    assert sys.modules.get("integral.ran_as_main") is None
    assert repo_gate._declared_module("ran_as_main") is pretend
