"""T121: the local substitute for CI must still be a substitute.

This file no longer has a text half. Three rounds of matching the script's text
were defeated — the third by putting all twelve patterns in one unused
single-quoted string, and again in trailing `#` comments, both scoring
`verified_gate_defects: 0` over a script that resolved nothing, fetched nothing,
created no worktree and ran no gate. `integral.verified_gate`'s docstring carries
the history; the design that replaced it is that the measurement RUNS the script.

So every case here is one of two shapes:

- **the mutation table** — break the script, assert `measure()` names the
  contract that broke, assert the unbroken script passes that same contract.
  The table is the committed form of the mutate-verify-restore cycle
  `CLAUDE.md` requires, and it runs on every `make test` rather than once in the
  session that wrote it. Nothing on disk is ever mutated: the mutated body is a
  string handed to a temp path, so there is no restore step to get wrong and no
  bytecode to go stale.
- **the checker's own machinery** — the floor, the missing-script verdict, the
  documentation cross-check, and the command line, which are the parts a
  contract cannot reach because they are about the measurement rather than the
  script.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from integral import verified_gate as vg

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "tools" / "verified_gate.sh"


def _mutate(find: str, replace: str) -> str:
    """The committed script with one substring replaced.

    Derived from the real file rather than written out, so a case cannot quietly
    stop describing the thing it is about: a `find` the script no longer
    contains fails loudly instead of testing a body nobody ships.
    """
    script = _SCRIPT.read_text(encoding="utf-8")
    assert find in script, f"the script no longer contains {find!r}; this case is stale"
    mutated = script.replace(find, replace, 1)
    assert mutated != script, f"replacing {find!r} changed nothing"
    return mutated


def _measure_text(
    tmp_path: Path,
    script_text: str,
    *,
    only: str | None = None,
    documented: bool = True,
) -> dict[str, Any]:
    """Measure a script body as if it were the committed one.

    `only` narrows the run to one contract by name. Cases in the mutation table
    use it because the mutation they carry is aimed at exactly one contract, and
    the assertion is that *that* contract is the one that speaks — a mutation
    detected only by some other contract is a hole, not a pass.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "verified_gate.sh"
    script.write_text(script_text, encoding="utf-8")
    script.chmod(0o755)
    instructions = tmp_path / "CLAUDE.md"
    instructions.write_text(
        "Run `verified_gate.sh` before merging.\n" if documented else "Merge carefully.\n",
        encoding="utf-8",
    )
    contracts = vg.CONTRACTS
    if only is not None:
        contracts = tuple(c for c in vg.CONTRACTS if c.name == only)
        assert contracts, f"no contract named {only!r}"
    return vg.measure(script_path=script, instructions=instructions, contracts=contracts)


def _failed_names(measured: dict[str, Any]) -> list[str]:
    return [entry.split(" — ", 1)[0] for entry in measured["failed_contracts"]]


# --------------------------------------------------------------------------
# The committed script, measured for real.
# --------------------------------------------------------------------------


def test_the_script_exists_and_is_executable() -> None:
    assert _SCRIPT.exists()
    assert _SCRIPT.stat().st_mode & 0o111, "a script nobody can run is not a substitute"


def test_the_committed_script_honours_every_contract() -> None:
    measured = vg.measure()
    assert measured["failed_contracts"] == []
    assert measured["undocumented"] == []
    assert measured["verified_gate_defects"] == 0
    assert measured["gate_status"] == "measured"
    assert measured["verified_gate_contracts_checked"] == len(vg.CONTRACTS)
    # The zero must hide nothing: a reader has to be able to see WHICH claims ran.
    assert measured["contracts_checked_by_name"] == [c.name for c in vg.CONTRACTS]


def test_every_contract_has_a_reason_it_exists() -> None:
    # A contract with no stated mutation is decoration, and decoration is what
    # the property table became by round 2.
    for contract in vg.CONTRACTS:
        assert len(contract.why) > 40, f"{contract.name} does not say what it kills"
    assert len({c.name for c in vg.CONTRACTS}) == len(vg.CONTRACTS)


# --------------------------------------------------------------------------
# The mutation table. `(id, find, replace, the contract that must object)`.
#
# Every row was measured against the committed script: red with the mutation,
# green without. That pairing is asserted below rather than described, because
# a mutation nothing catches and a mutation everything catches are both useless
# and only the first looks like a failure.
# --------------------------------------------------------------------------

_MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        # B1. The mutation that survived every text property: the gate runs, it
        # genuinely fails, and the block prints PASS with exit 0. Nothing in
        # round 2's twelve patterns touched `status` or the verdict.
        "status_forced_to_zero",
        "status=$?",
        "status=$?\nstatus=0",
        "a_failing_gate_is_reported_as_FAIL",
    ),
    (
        # The property the script exists for, inverted.
        "the_gate_runs_where_the_caller_stands",
        '( cd "${tree}" && ${gate_command} )',
        '( cd "${repo_root}" && ${gate_command} )',
        "the_commit_is_measured_not_the_callers_tree",
    ),
    (
        "the_block_prints_prose_where_the_sha_goes",
        'echo "commit    ${sha}"',
        'echo "commit    (a clean detached checkout)"',
        "the_verdict_names_the_commit_it_measured",
    ),
    (
        # B2. Round 2's property 12 matched `worktree prune` inside `cleanup()`
        # and was satisfied while nothing ever called it.
        "the_cleanup_trap_is_removed",
        "trap cleanup EXIT",
        "# trap cleanup EXIT",
        "nothing_survives_the_run_pass_or_fail",
    ),
    (
        # B5. `resolved` was an echo of a variable nothing constrained.
        "resolved_from_is_hard_coded",
        'resolved_from="local ref"',
        'resolved_from="origin, fetched just now"',
        "the_resolution_line_is_true",
    ),
    (
        "on_origin_is_hard_coded",
        'pushed="NO — not reachable from any origin/* ref this clone knows"',
        'pushed="yes — reachable from origin/main"',
        "the_origin_reachability_line_is_true",
    ),
    (
        # C. The exact guard that shipped at 316cd6c, restored. `@` is git's
        # synonym for HEAD, is not the string "HEAD", and `git fetch origin -- @`
        # answers with origin's default branch.
        "the_head_guard_is_a_blacklist_of_one_string",
        '[ "${fetchable}" = "yes" ]',
        '[ "${ref}" != "HEAD" ]',
        "caller_relative_refs_measure_the_caller",
    ),
    (
        # The fail-open direction for a ref that resolves to nothing: measure
        # whatever tree the script happens to be standing in and call it a pass.
        "an_unresolvable_ref_falls_through_to_head",
        "  echo \"verified-gate: cannot resolve '${ref}' to a commit\" >&2\n  exit 2",
        '  sha="$(git -C "${repo_root}" rev-parse HEAD)"',
        "an_unmeasurable_ref_refuses_with_2",
    ),
    (
        # D-22's drift, in the form that actually type-checks as a gate: four
        # real targets in place of the aggregate. It passes today and falls
        # behind the Makefile on the next target anyone adds.
        "the_targets_are_enumerated_instead_of_delegated",
        '( cd "${tree}" && ${gate_command} )',
        '( cd "${tree}" && make lint && make test && make evidence && make verify-gates )',
        "the_aggregate_target_is_what_runs",
    ),
    (
        # Round 1's compounding half: declare the aggregate, run something else,
        # and paste a block claiming the aggregate onto the pull request.
        "the_block_claims_the_aggregate_while_lint_runs",
        '( cd "${tree}" && ${gate_command} )',
        '( cd "${tree}" && make lint )',
        "the_verdict_reports_the_command_that_ran",
    ),
    (
        # `open_task_pr.sh` v3.2.0 ran the host gate on both sides of the archive
        # and the committed evidence would have had to hold two values at once
        # (`CLAUDE.md`: 615 pre-archive against 614 post). Running the gate twice
        # is a real defect that a set-valued probe would call clean, so the probe
        # keeps repeats and this row is what proves it.
        "the_gate_is_run_twice",
        '( cd "${tree}" && ${gate_command} )',
        '( cd "${tree}" && ${gate_command} && ${gate_command} )',
        "the_aggregate_target_is_what_runs",
    ),
)


@pytest.mark.parametrize(
    ("find", "replace", "contract"),
    [(f, r, c) for _id, f, r, c in _MUTATIONS],
    ids=[i for i, _f, _r, _c in _MUTATIONS],
)
def test_each_mutation_is_reported_by_the_contract_it_breaks(
    tmp_path: Path, find: str, replace: str, contract: str
) -> None:
    broken = _measure_text(tmp_path / "broken", _mutate(find, replace), only=contract)
    assert _failed_names(broken) == [contract], broken["failed_contracts"]
    assert broken["verified_gate_defects"] == 1


@pytest.mark.parametrize(
    "contract", [c for _id, _f, _r, c in _MUTATIONS], ids=[i for i, *_ in _MUTATIONS]
)
def test_the_committed_script_passes_the_contract_each_mutation_breaks(
    tmp_path: Path, contract: str
) -> None:
    """The other half of mutate-verify-restore.

    Without it, a contract that fails for every script — a broken harness, a
    stale scenario — would read as a table of ten successful mutation kills.
    """
    intact = _measure_text(tmp_path, _SCRIPT.read_text(encoding="utf-8"), only=contract)
    assert intact["failed_contracts"] == []


def test_every_contract_is_covered_by_the_mutation_table() -> None:
    """A contract nobody can break is decoration, and this is the check that
    says so out loud rather than leaving a reader to compare two lists."""
    covered = {c for _id, _f, _r, c in _MUTATIONS}
    assert covered == {c.name for c in vg.CONTRACTS}


# --------------------------------------------------------------------------
# A1 and A2 — the round-3 defeats. Both scored `verified_gate_defects: 0`,
# `properties_checked: 12`, `missing_properties: []` against 316cd6c.
# --------------------------------------------------------------------------

_A1 = """#!/usr/bin/env bash
set -uo pipefail
dead_string_never_executed='
rev-parse --verify
worktree add --detach
__pycache__
commit ${sha}
gate_command="make host-gate"
cd "${tree}" && ${gate_command}
command ${gate_command}
[ "${ref}" != "HEAD" ]
resolved ${resolved_from}
on origin ${pushed}
fetch --quiet origin --
worktree prune
'
sha=0000000000000000000000000000000000000000
ref="${1:-HEAD}"
resolved_from="origin, fetched just now"
pushed="yes - reachable from origin/main"
echo '## Verified gate'
echo '```'
echo "commit    ${sha}"
echo "ref       ${ref}"
echo "resolved  ${resolved_from}"
echo "on origin ${pushed}"
echo "command   make host-gate   (delegated, never a listed subset)"
echo "verdict   PASS"
echo '```'
exit 0
"""

_A2_PATTERNS = (
    "rev-parse --verify",
    "worktree add --detach",
    "__pycache__",
    "commit ${sha}",
    'gate_command="make host-gate"',
    'cd "${tree}" && ${gate_command}',
    "command ${gate_command}",
    '[ "${ref}" != "HEAD" ]',
    "resolved ${resolved_from}",
    "on origin ${pushed}",
    "fetch --quiet origin -- x",
    "worktree prune",
)

# A line carrying code AND a trailing comment is not comment-only, so round 2's
# `#`-line filter kept every one of these.
_A2 = (
    "#!/usr/bin/env bash\nset -uo pipefail\n"
    + "".join(f"true  # {pattern}\n" for pattern in _A2_PATTERNS)
    + "sha=0000000000000000000000000000000000000000\n"
    + "echo '## Verified gate'\necho \"commit    ${sha}\"\necho 'verdict   PASS'\nexit 0\n"
)


@pytest.mark.parametrize(
    ("label", "body"), [("A1_dead_string", _A1), ("A2_trailing_comments", _A2)]
)
def test_a_script_that_only_contains_the_patterns_fails_almost_every_contract(
    tmp_path: Path, label: str, body: str
) -> None:
    """The acceptance case for the redesign.

    Both bodies satisfy all twelve of round 2's text properties and do nothing
    at all. Eight of ten contracts object; the two that do not are
    `the_commit_is_measured_not_the_callers_tree` (satisfied by an
    unconditional PASS) and `nothing_survives_the_run_pass_or_fail` (satisfied
    by creating nothing) — named here rather than rounded up, because a claim of
    ten that measured eight is the shape of defect this task is about.
    """
    measured = _measure_text(tmp_path, body)
    failed = set(_failed_names(measured))
    assert failed == {c.name for c in vg.CONTRACTS} - {
        "the_commit_is_measured_not_the_callers_tree",
        "nothing_survives_the_run_pass_or_fail",
    }
    # Derived rather than the literal 8, so adding an eleventh contract that A1
    # also fails does not require editing this line. It cannot silently shrink:
    # `test_the_floor_is_a_literal_the_table_cannot_drag` pins the table at ten
    # or more. Eight as of this commit.
    assert measured["verified_gate_defects"] == len(vg.CONTRACTS) - 2
    assert measured["verified_gate_defects"] == 8, "the recorded measurement moved"


# --------------------------------------------------------------------------
# The floor. #333, F3 — it was `x < x`, so it could never fire.
# --------------------------------------------------------------------------


def test_the_floor_is_a_literal_the_table_cannot_drag() -> None:
    source = Path(vg.__file__).read_text(encoding="utf-8")
    assert "MINIMUM_CONTRACTS = 10" in source, (
        "the floor must be a literal; written as `len(CONTRACTS)` it is compared "
        "against a count derived from CONTRACTS and can never fire"
    )
    assert len(vg.CONTRACTS) >= vg.MINIMUM_CONTRACTS


def test_a_shrunken_table_trips_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Truncating the table to three contracts must exit 3, not 0.

    Zero defects over three contracts is the vacuous pass the floor exists to
    refuse, and `return 3` has to be reachable for that to be true.
    """
    monkeypatch.setattr(vg, "CONTRACTS", vg.CONTRACTS[:3])
    target = tmp_path / "T121.json"
    assert vg._main(["prog", str(target)]) == 3
    assert "below the floor of 10" in capsys.readouterr().err
    assert json.loads(target.read_text(encoding="utf-8"))["verified_gate_contracts_checked"] == 3


def test_a_real_defect_outranks_a_thin_denominator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`naming`'s precedence: exit 1 for a finding, 3 only for a thin scan."""
    monkeypatch.setattr(vg, "CONTRACTS", vg.CONTRACTS[:1])
    script = tmp_path / "verified_gate.sh"
    script.write_text(_A1, encoding="utf-8")
    instructions = tmp_path / "CLAUDE.md"
    instructions.write_text("Run `verified_gate.sh`.\n", encoding="utf-8")
    assert (
        vg._main(
            [
                "prog",
                str(tmp_path / "out.json"),
                "--script",
                str(script),
                "--instructions",
                str(instructions),
            ]
        )
        == 1
    )


# --------------------------------------------------------------------------
# A missing script, and the prose half of D-22.
# --------------------------------------------------------------------------


def test_a_missing_script_is_a_defect_and_not_an_honest_unmeasured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#333, F5. `unmeasured` is this repo's word for "cannot be scored yet",
    `make evidence` records it and CONTINUES, and `_main` returns 1 — so writing
    it here said the opposite of what the code decided."""
    instructions = tmp_path / "CLAUDE.md"
    instructions.write_text("Run `verified_gate.sh`.\n", encoding="utf-8")
    measured = vg.measure(script_path=tmp_path / "gone.sh", instructions=instructions)
    assert measured["verified_gate_defects"] == -1
    assert measured["gate_status"] == "measured"

    assert (
        vg._main(["prog", str(tmp_path / "out.json"), "--script", str(tmp_path / "gone.sh")]) == 1
    )
    assert "does not exist" in capsys.readouterr().err


def test_prose_that_names_no_script_is_reported(tmp_path: Path) -> None:
    measured = _measure_text(
        tmp_path, _SCRIPT.read_text(encoding="utf-8"), only=None, documented=False
    )
    assert measured["undocumented"] == ["CLAUDE.md does not name verified_gate.sh"]
    assert measured["verified_gate_defects"] == 1


def test_this_repositorys_own_instructions_name_the_script() -> None:
    assert vg.is_documented((_ROOT / "CLAUDE.md").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# The command line. #333's F4 was fixed; two residues of it were not.
# --------------------------------------------------------------------------


def test_a_repeated_flag_is_refused_rather_than_half_honoured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D residue 1. `args.index(name)` removed only the FIRST occurrence, so
    `--script A --script B` left `B` standing as the positional — the evidence
    path — and the run overwrote B with JSON: 4189 bytes to 232, exit 0, no
    warning. F4 again, in miniature."""
    victim = tmp_path / "b.sh"
    victim.write_text(_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    before = victim.read_bytes()

    assert vg._main(["prog", "--script", str(tmp_path / "a.sh"), "--script", str(victim)]) == 2
    assert "given twice" in capsys.readouterr().err
    assert victim.read_bytes() == before, "the second --script value was overwritten"


@pytest.mark.parametrize(
    "flag", ["--script=/tmp/x.sh", "--instructions=/tmp/x.md", "--repo", "-s", "--verbose"]
)
def test_an_unknown_option_is_refused_rather_than_dropped(
    flag: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """D residue 2. Anything starting with `-` was stripped from the positionals
    and never recognised as a flag, so `own_tree` stayed True and the run
    measured THIS repository and wrote the real `status/evidence/T121.json` — a
    caller who mistypes got a green answer about a file they never named."""
    assert vg._main(["prog", flag]) == 2
    assert "unknown option" in capsys.readouterr().err


def test_a_second_positional_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    # The old code took `positional[0]` and dropped the rest in silence.
    assert vg._main(["prog", "one.json", "two.json"]) == 2
    assert "one evidence path at most" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--script", "--instructions"])
def test_a_trailing_flag_with_no_value_exits_2(
    flag: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert vg._main(["prog", flag]) == 2
    assert "needs a path" in capsys.readouterr().err


def test_naming_a_script_does_not_overwrite_it(tmp_path: Path) -> None:
    """#333, F4 itself: the documented invocation wrote the evidence JSON over
    the script it was pointed at."""
    named = tmp_path / "verified_gate.sh"
    named.write_text(_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    before = named.read_bytes()
    # 0, not an error: the file is intact and honours every contract. The point
    # is the bytes below, not the exit code.
    assert vg._main(["prog", "--script", str(named)]) == 0
    assert named.read_bytes() == before


def test_measuring_another_tree_records_nothing_about_this_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A measurement of some other tree is not evidence about this repository.

    `DEFAULT_EVIDENCE_PATH` is monkeypatched to a file that does not exist, so
    the assertion is that nothing was written there — a `tmp_path`-only check
    could not see the gap it is about.
    """
    decoy = tmp_path / "T121.json"
    monkeypatch.setattr(vg, "DEFAULT_EVIDENCE_PATH", decoy)
    named = tmp_path / "verified_gate.sh"
    named.write_text(_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    vg._main(["prog", "--script", str(named)])
    assert not decoy.exists()


def test_an_explicit_target_still_records_when_a_script_is_named(tmp_path: Path) -> None:
    named = tmp_path / "verified_gate.sh"
    named.write_text(_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    instructions = tmp_path / "CLAUDE.md"
    instructions.write_text("Run `verified_gate.sh`.\n", encoding="utf-8")
    target = tmp_path / "out.json"
    assert (
        vg._main(["prog", str(target), "--script", str(named), "--instructions", str(instructions)])
        == 0
    )
    assert json.loads(target.read_text(encoding="utf-8"))["verified_gate_defects"] == 0


def test_the_module_runs_as_a_module(tmp_path: Path) -> None:
    # `python -m integral.verified_gate` is what the task's gate block runs and
    # what `make evidence` calls; an import-time error there is invisible to
    # every test that imports the module directly.
    done = subprocess.run(
        [sys.executable, "-m", "integral.verified_gate", str(tmp_path / "out.json")],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["verified_gate_defects"] == 0


# --------------------------------------------------------------------------
# One direct functional regression, kept outside the contract table.
#
# `@` is the finding that broke round 2, and reading it here as a plain script
# run — no checker in the middle — is what makes the contract above legible to
# someone auditing this file rather than the module.
# --------------------------------------------------------------------------


def test_an_at_sign_measures_the_caller_not_origins_default_branch(tmp_path: Path) -> None:
    """Measured at 316cd6c, standing on a branch whose committed gate genuinely
    fails: `bash tools/verified_gate.sh @` printed origin/main's SHA and
    `verdict PASS`, exit 0."""
    harness = vg.Harness(_SCRIPT, tmp_path)
    clone, upstream, local = harness.clone_with_an_origin()
    ran = harness.run(clone, "@")
    assert ran.fields["commit"] == local
    assert ran.fields["commit"] != upstream
    assert ran.fields["verdict"] == "FAIL"
    assert ran.returncode == 1
