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

import ast
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


# --------------------------------------------------------------------------
# T161 — the block must not assert what it did not measure about CI.
#
# `tools/verified_gate.sh:143` used to print, in every verdict block, the
# hardcoded sentence "CI is unavailable; this is the substitute CLAUDE.md
# names" — true during the 2026-09-04 outage, false from 2026-09-07. Measured
# against the unfixed script (before this task's edit) `measure_ci_claims()`
# reported `verdict_block_claims_about_ci_that_are_not_measured == 3` — one
# per scenario, since the sentence is unconditional — confirming the check is
# not vacuously zero before a single line of the fix was written.
#
# ROUND 2, after a second-reader BLOCK on #472: round 1's enumeration (a
# verb-of-being list plus a 19-word state-word list) scored a clean 0 against
# four re-shippings of the removed defect, one of them with only the subject
# noun swapped from "CI" to "GitHub Actions" — `CLAUDE.md`'s own other name
# for the identical referent — and the round-1 detector's own doc comment
# turned out to have been fitted to the exact scope sentence this diff shipped
# (F3). The fix taken here is the report's own remedy: the block's prose now
# says nothing about CI at all, and the check is the closed two-name
# membership test `ci_state_assertions` now performs — see its doc comment in
# `integral.verified_gate` for why two names, not a shaped sentence. The
# mutation table below is rewritten to the second reader's own four
# re-shippings plus their control, so this file carries the adversarial cases
# that found the round-1 defect rather than a table this session invented.
# --------------------------------------------------------------------------


def _measure_ci_claims_text(tmp_path: Path, script_text: str) -> dict[str, Any]:
    """`measure_ci_claims` against a script body as if it were the committed
    one, the same shape `_measure_text` gives the contract table above."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "verified_gate.sh"
    script.write_text(script_text, encoding="utf-8")
    script.chmod(0o755)
    return vg.measure_ci_claims(script_path=script)


def test_the_committed_script_makes_no_ci_claim() -> None:
    measured = vg.measure_ci_claims()
    assert measured["ci_claims_found"] == []
    assert measured["verdict_block_claims_about_ci_that_are_not_measured"] == 0
    assert measured["gate_status"] == "measured"
    assert measured["ci_claim_scenarios_checked"] == len(vg.CI_CLAIM_SCENARIOS)
    assert measured["ci_claim_scenarios_checked_by_name"] == [s.name for s in vg.CI_CLAIM_SCENARIOS]


def test_every_ci_claim_scenario_has_a_reason_it_exists() -> None:
    for scenario in vg.CI_CLAIM_SCENARIOS:
        assert len(scenario.why) > 30, f"{scenario.name} does not say what it is for"
    assert len({s.name for s in vg.CI_CLAIM_SCENARIOS}) == len(vg.CI_CLAIM_SCENARIOS)


# `(id, find, replace)` — each reintroduces a CI-state assertion into the
# COMMITTED (fixed) script. `find` is a substring of the real, current file,
# so a rewrite of the surrounding prose that leaves this substring behind
# does not silently stop testing anything (the same discipline `_mutate`
# documents above). Every row was measured against the committed script:
# green without the mutation, red with it.
#
# These four are not this session's invention — they are the second reader's
# own adversarial findings on #472 (F1), the exact re-shippings that scored a
# clean 0 against round 1's enumeration. Row 1 is the one that matters most:
# round 1 matched only the literal token "ci", and this row reintroduces the
# identical defect with nothing changed but the subject noun, to `CLAUDE.md`'s
# own other name for the same referent ("GitHub Actions has runner minutes
# again"). A check that only forbade "ci" would repeat round 1's mistake on
# this exact row, which is why `ci_state_assertions` now checks both names.
_CI_CLAIM_MUTATIONS: tuple[tuple[str, str, str], ...] = (
    (
        # #472, F1, row 1 — the removed defect with only its subject noun
        # swapped to `CLAUDE.md`'s other name for CI. This is the row that
        # actually caught round 1's enumeration; keep it first.
        "the_subject_noun_swapped_to_github_actions",
        'echo "was measured. This block is scoped to that commit only."',
        'echo "was measured. This block is scoped to that commit only. '
        'GitHub Actions is unavailable; this is the substitute."',
    ),
    (
        # #472, F1, row 2.
        "reworded_as_a_block_substitute_for_ci",
        'echo "was measured. This block is scoped to that commit only."',
        'echo "was measured. This block is scoped to that commit only. '
        'This block substitutes for the unavailable CI."',
    ),
    (
        # #472, F1, row 3 — negated past tense, no verb-of-being at all.
        "reworded_as_ci_did_not_run",
        'echo "was measured. This block is scoped to that commit only."',
        'echo "was measured. This block is scoped to that commit only. '
        'CI did not run for this commit."',
    ),
    (
        # #472, F1, row 4 — the fail-open PASS direction: an ungrounded claim
        # that CI already succeeded is exactly as unmeasured as an ungrounded
        # claim that it failed or is unavailable.
        "reworded_as_a_green_ci_check_already_covered",
        'echo "was measured. This block is scoped to that commit only."',
        'echo "was measured. This block is scoped to that commit only. '
        'A green CI check already covered this head."',
    ),
)


@pytest.mark.parametrize(
    ("find", "replace"),
    [(f, r) for _id, f, r in _CI_CLAIM_MUTATIONS],
    ids=[i for i, _f, _r in _CI_CLAIM_MUTATIONS],
)
def test_each_ci_claim_mutation_is_detected(tmp_path: Path, find: str, replace: str) -> None:
    """Revert the fix (in miniature) and watch the metric go red."""
    broken = _measure_ci_claims_text(tmp_path / "broken", _mutate(find, replace))
    assert broken["verdict_block_claims_about_ci_that_are_not_measured"] > 0, broken
    # Found on every scenario, since the mutated line is unconditional — the
    # metric must not undercount by de-duplicating identical assertions
    # across runs, which would hide exactly the "prints it every time"
    # property that made the original sentence a defect on every PR.
    assert broken["verdict_block_claims_about_ci_that_are_not_measured"] == len(
        vg.CI_CLAIM_SCENARIOS
    )


@pytest.mark.parametrize(
    "find_replace_id",
    [i for i, _f, _r in _CI_CLAIM_MUTATIONS],
    ids=[i for i, _f, _r in _CI_CLAIM_MUTATIONS],
)
def test_the_committed_script_passes_every_ci_claim_mutations_baseline(
    tmp_path: Path, find_replace_id: str
) -> None:
    """The other half of mutate-verify-restore: the UNMUTATED script must be
    clean, or a mutation that "breaks" a perpetually-red check proves nothing."""
    intact = _measure_ci_claims_text(tmp_path, _SCRIPT.read_text(encoding="utf-8"))
    assert intact["verdict_block_claims_about_ci_that_are_not_measured"] == 0


@pytest.mark.parametrize(
    ("text", "expect_assertion"),
    [
        # Positive: either of the two names this repository uses for CI,
        # in any grammatical shape at all — there is no verb or state-word
        # list left to satisfy, so an ungrounded claim cannot dodge this by
        # choosing an unlisted adjective the way round 1 could be dodged.
        ("CI is unavailable; this is the substitute CLAUDE.md names.", True),
        ("CI has failed on this commit.", True),
        ("CI was green on the last run.", True),
        ("As of this run, CI is currently down for maintenance.", True),
        ("CI: unavailable.", True),
        ("CI — down for maintenance.", True),
        ("(CI unavailable)", True),
        ("ci is green", True),  # case-insensitive
        ("Everything is fine, CI.", True),  # bare mention, no verb at all
        # Positive — the other name, #472 F1's own finding: round 1's
        # enumeration matched only the literal token "ci" and missed every
        # one of these because the subject noun was never "CI".
        ("GitHub Actions is unavailable; this is the substitute.", True),
        ("github   actions\nhas failed on this commit.", True),  # whitespace/case
        # Negative: no mention of either name at all.
        ("Merge only while the head is still the SHA the block names.", False),
        ("on origin yes — reachable from origin/main.", False),
        ("verdict   PASS", False),
        # Negative: "ci" appears as a substring inside a longer word, which
        # must not match — the word-boundary is what keeps this rule from
        # flagging ordinary English.
        ("Traci reviewed the science and found it reciprocal and explicit.", False),
        # Negative: "actions" alone, with no "GitHub" attached, must not
        # match — the phrase is two words together, not either word alone.
        ("User actions are logged for audit.", False),
        # Negative: this IS the exact scope sentence round 1's enumeration
        # was built to exempt (F3's finding) — under the closed rule there is
        # no exemption to encode, so a sentence like this is simply never
        # written; it is included here as documentation of what changed, not
        # because the rule special-cases it.
        (
            "it and CI are complementary (this over the committed head, CI over the "
            "pull request's separate merge ref), and it makes no claim about CI's "
            "own state here.",
            True,
        ),
    ],
)
def test_ci_state_assertions_is_the_closed_two_name_rule(text: str, expect_assertion: bool) -> None:
    found = vg.ci_state_assertions(text)
    assert bool(found) is expect_assertion, (text, found)


def test_the_committed_scripts_own_preamble_mentions_neither_name() -> None:
    """Behavioural mirror of the rule above, run against the REAL block.

    This is `ci_state_assertions`'s own cheap check, and #472's round-3 report
    (F4) showed it is exactly that and no more: eleven further re-shippings of
    the same claim, none using either watched name, all scored `[]` here too.
    That is why this function is no longer what the property depends on — see
    `test_the_emitted_prose_is_pinned_verbatim_on_a_pass` below, which does not
    care what words a re-shipped claim uses. This test stays as the documented
    floor of the two-name rule: the committed script clears even the narrow
    check, which is necessary and, per F4, not sufficient on its own.
    """
    measured = vg.measure_ci_claims()
    assert measured["ci_claims_found"] == []


def _non_fenced_prose(stdout: str, *, sha: str) -> str:
    """Every line the script printed OUTSIDE a fenced ``` region, masked and
    rejoined — the property F5 found the old pin did not cover.

    #472, round 3, F5: the pin this replaces looked only at
    `lines[2:fence_index]` — the three preamble lines between the heading and
    the FIRST fence — so a claim placed in the trailer (`tools/verified_gate.sh`
    :171-172) or inside the FAIL `<details>` wrapper sat outside its reach,
    guarded only by F4's two-name enumeration. Measured: the same sentence
    ("Actions is free and unmetered on public repositories" — `CLAUDE.md`:641
    verbatim, round 3's probe P1) scored `ci_claims_found == []` AND left the
    old preamble-only pin matching (pytest green, 83 passed) when placed in
    the trailer, while the identical sentence placed in the preamble was
    already caught by the old pin (pytest red) — see
    `test_a_claim_anywhere_in_non_fenced_prose_is_caught` for both, run for
    real against the committed script rather than asserted from this
    docstring.

    So this walks the WHOLE block rather than only the span before the first
    fence: it toggles on lines that are exactly a bare fence delimiter, and
    keeps every line printed while NOT inside one of the two data fences (the
    commit-info table, and the log excerpt) — the heading, the blank
    separators, the three preamble lines, the `<details>`/`</details>`
    wrapper on a FAIL block, and the two-line trailer. A pin over that whole
    span is fail-closed against any new sentence dropped anywhere in the
    non-fenced prose, independent of the word it uses for CI (or anything
    else) — which is what lets `_CI_REFERENT_RE` stop being load-bearing.

    The one value that legitimately varies run to run is `${sha}`, embedded
    mid-sentence in the trailer — never keyed like `commit` inside the fence,
    so `_read_block` cannot factor it out the way
    `_c_verdict_names_the_commit` already does for THAT field. It is masked
    the same way in spirit: not guessed by a pattern that could also eat a
    sentence a future editor writes, but replaced by the caller's own known
    SHA — the harness always knows which commit it asked the script to
    measure — so a real 40-hex value can only ever be removed if it is
    exactly the one this run produced. No timestamp appears outside a fence
    today (`measured  $(date …)` sits inside the commit-info fence), so there
    is nothing to mask for it here; if one ever migrated into prose this
    function would need to mask that too, the same way.
    """
    out: list[str] = []
    in_fence = False
    for line in stdout.splitlines():
        if line == "```":
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out).strip("\n").replace(sha, "<SHA>")


_GOLDEN_PROSE_PASS = (
    "## Verified gate\n"
    "\n"
    "Run by `tools/verified_gate.sh` against a clean detached checkout of the\n"
    "commit named below — not a working tree — and that SHA is the one that\n"
    "was measured. This block is scoped to that commit only.\n"
    "\n"
    "\n"
    "\n"
    "Merge only while the pull request head is still `<SHA>`. A push after this\n"
    "block was produced makes it evidence about a commit nobody is merging."
)

_GOLDEN_PROSE_FAIL = (
    "## Verified gate\n"
    "\n"
    "Run by `tools/verified_gate.sh` against a clean detached checkout of the\n"
    "commit named below — not a working tree — and that SHA is the one that\n"
    "was measured. This block is scoped to that commit only.\n"
    "\n"
    "\n"
    "\n"
    "<details><summary>failing output</summary>\n"
    "\n"
    "\n"
    "</details>\n"
    "\n"
    "Merge only while the pull request head is still `<SHA>`. A push after this\n"
    "block was produced makes it evidence about a commit nobody is merging."
)


#: Literals, on purpose — `MINIMUM_CONTRACTS`'s form and reason repeated: the
#: committed script always prints exactly two data fences on a PASS run (the
#: commit-info table, the log excerpt) and three on a FAIL run (those two
#: plus the `<details>` tail), so four and six bare ``` delimiter lines is a
#: fact about the script today, not a count derived from `stdout` itself —
#: see `test_a_claim_smuggled_inside_a_forged_fence_pair_is_caught_by_the_
#: fence_count` for why a fourth constant here would be self-defeating.
_EXPECTED_FENCE_DELIMITERS_PASS = 4
_EXPECTED_FENCE_DELIMITERS_FAIL = 6


def test_the_emitted_prose_is_pinned_verbatim_on_a_pass(tmp_path: Path) -> None:
    """The token rule above is deliberately loose about everything except the
    two names — it says nothing if a future edit adds some OTHER unmeasured
    claim ("this commit was authored by a trustworthy contributor", say), and
    F4 showed it is loose about the two names too. The second reader's report
    offered a golden-text pin as the complement, "in addition to the token
    rule, not instead" — a golden text pins the exact wording, the token rule
    pins the property it names. This is that pin, widened past F5's gap: the
    ENTIRE non-fenced prose of a PASS block is a fixed generated string with
    one masked input (the SHA), so it can be compared for byte-exact equality
    rather than merely scanned.

    Any change anywhere in this prose — CI-related or not, preamble or
    trailer — now has to touch this fixture deliberately, which is what makes
    it a pin rather than a filter.
    """
    h = vg.Harness(_SCRIPT, tmp_path)
    root = h.repo("repo", vg._plain_makefile(vg._PASSING))
    sha = h.git("rev-parse", "HEAD", cwd=root)
    stdout = h.run(root, "HEAD").stdout
    # Belt alongside the pin below, not a replacement for it — see
    # `test_a_claim_smuggled_inside_a_forged_fence_pair_is_caught_by_the_
    # fence_count` for the gap this closes on its own.
    assert stdout.count("```") == _EXPECTED_FENCE_DELIMITERS_PASS
    assert _non_fenced_prose(stdout, sha=sha) == _GOLDEN_PROSE_PASS


def test_the_emitted_prose_is_pinned_verbatim_on_a_fail(tmp_path: Path) -> None:
    """The FAIL shape's own `<details>` wrapper is prose too, and sat outside
    even the property this pin describes until this row was added — a FAIL
    block is what a genuinely broken gate pastes, so it is exactly the case a
    fail-open claim would be most valuable stapled to."""
    h = vg.Harness(_SCRIPT, tmp_path)
    root = h.repo("repo", vg._plain_makefile(vg._FAILING))
    sha = h.git("rev-parse", "HEAD", cwd=root)
    stdout = h.run(root, "HEAD").stdout
    assert stdout.count("```") == _EXPECTED_FENCE_DELIMITERS_FAIL
    assert _non_fenced_prose(stdout, sha=sha) == _GOLDEN_PROSE_FAIL


def test_a_claim_smuggled_inside_a_forged_fence_pair_is_caught_by_the_fence_count(
    tmp_path: Path,
) -> None:
    """Self-scan finding on this round's OWN diff, not a re-shipping of #472's:
    `_non_fenced_prose` toggles on any line that is exactly a bare ``` — that
    is what lets it skip the two real data fences without reading their
    contents, and it is exactly what lets a mutation that adds a THIRD,
    forged fence pair smuggle a claim inside it. Measured, wrapping round 3's
    own P1 sentence in a forged fence pair:

    - `ci_state_assertions` still scores it `[]` (F4's gap, unchanged: P1
      names neither watched word).
    - `_non_fenced_prose(...) == _GOLDEN_PROSE_PASS` STILL HOLDS — the
      smuggled line sits inside what the toggle treats as fence content, so
      the pin above does not move either. The prose-equality pin alone does
      not close this path.

    What does move: the committed script always prints exactly two data
    fences on a PASS run, so a forged third pair changes the number of bare
    ``` lines from four to six even though it changes nothing the prose
    extraction can see. `_EXPECTED_FENCE_DELIMITERS_PASS` is checked in the
    happy-path test above for exactly this reason, not only here — this test
    is the adversarial proof that the guard is load-bearing, not decorative.

    This does not reopen F4/F5: every row in `_TRAILER_CLAIM_MUTATIONS`
    forges no fence, and the prose pin alone catches all of them. This is a
    narrower, second path that needed its own guard, found by going looking
    rather than by another round.
    """
    mutated = _mutate(
        'echo "block was produced makes it evidence about a commit nobody is merging."',
        'echo "block was produced makes it evidence about a commit nobody is merging."\n'
        "echo '```'\n"
        'echo "Actions is free and unmetered on public repositories."\n'
        "echo '```'\n",
    )
    script = tmp_path / "verified_gate.sh"
    script.write_text(mutated, encoding="utf-8")
    script.chmod(0o755)
    h = vg.Harness(script, tmp_path / "work")
    root = h.repo("repo", vg._plain_makefile(vg._PASSING))
    sha = h.git("rev-parse", "HEAD", cwd=root)
    stdout = h.run(root, "HEAD").stdout
    assert vg.ci_state_assertions(stdout) == ()
    assert _non_fenced_prose(stdout, sha=sha) == _GOLDEN_PROSE_PASS
    assert stdout.count("```") != _EXPECTED_FENCE_DELIMITERS_PASS


# `(id, find, replace)` — F5's own reproduction: `find` sits in the TRAILER,
# outside the span the pin covered before this round, so before the fix each
# row here left `ci_state_assertions` at `[]` (F4: none uses either watched
# name) AND the old preamble-only pin matching (F5: the trailer is outside
# `lines[2:fence_index]`) — measured, not asserted, in this session's own
# report. `find` is a substring of the real, current file, so a rewrite of
# the surrounding prose that leaves this substring behind does not silently
# stop testing anything (`_mutate`'s own discipline).
_TRAILER_CLAIM_MUTATIONS: tuple[tuple[str, str, str], ...] = (
    (
        # Round 3's own probe P1 — `CLAUDE.md`:641, verbatim, the sentence
        # named as "the one a future editor is most likely to restore".
        "p1_line_641_verbatim_in_the_trailer",
        'echo "block was produced makes it evidence about a commit nobody is merging."',
        'echo "block was produced makes it evidence about a commit nobody is merging. '
        'Actions is free and unmetered on public repositories."',
    ),
    (
        # F4's other two named gaps in the same sentence shape, together —
        # "workflow" and "runner" are `CLAUDE.md`:647/649-650/671's words for
        # the identical referent, and neither is "ci" or "github actions".
        "workflow_and_runner_named_instead_of_ci",
        'echo "block was produced makes it evidence about a commit nobody is merging."',
        'echo "block was produced makes it evidence about a commit nobody is merging. '
        'The workflow runner has minutes again."',
    ),
)


@pytest.mark.parametrize(
    ("find", "replace"),
    [(f, r) for _id, f, r in _TRAILER_CLAIM_MUTATIONS],
    ids=[i for i, _f, _r in _TRAILER_CLAIM_MUTATIONS],
)
def test_a_claim_anywhere_in_non_fenced_prose_is_caught(
    tmp_path: Path, find: str, replace: str
) -> None:
    """F4 and F5, closed together: neither row here uses "ci" or "github
    actions", so `ci_state_assertions` still scores it `[]` — F4 is not
    fixed by this pin, it is made non-load-bearing by it. What catches both
    rows is that the trailer is no longer outside the pinned span."""
    mutated = _mutate(find, replace)
    script = tmp_path / "verified_gate.sh"
    script.write_text(mutated, encoding="utf-8")
    script.chmod(0o755)
    h = vg.Harness(script, tmp_path / "work")
    root = h.repo("repo", vg._plain_makefile(vg._PASSING))
    sha = h.git("rev-parse", "HEAD", cwd=root)
    stdout = h.run(root, "HEAD").stdout
    # F4, reconfirmed on this exact row: the two-name rule alone is blind to it.
    assert vg.ci_state_assertions(stdout) == ()
    # F5, closed: the widened pin is not blind to it.
    assert _non_fenced_prose(stdout, sha=sha) != _GOLDEN_PROSE_PASS


@pytest.mark.parametrize(
    "find_replace_id",
    [i for i, _f, _r in _TRAILER_CLAIM_MUTATIONS],
    ids=[i for i, _f, _r in _TRAILER_CLAIM_MUTATIONS],
)
def test_the_committed_script_passes_every_trailer_claim_mutations_baseline(
    tmp_path: Path, find_replace_id: str
) -> None:
    """The other half of mutate-verify-restore: the UNMUTATED script's
    trailer must still match the pin, or a mutation that "breaks" a
    perpetually-red check proves nothing."""
    h = vg.Harness(_SCRIPT, tmp_path)
    root = h.repo("repo", vg._plain_makefile(vg._PASSING))
    sha = h.git("rev-parse", "HEAD", cwd=root)
    stdout = h.run(root, "HEAD").stdout
    assert _non_fenced_prose(stdout, sha=sha) == _GOLDEN_PROSE_PASS


def test_the_ci_claim_scenario_floor_is_a_literal() -> None:
    """AST fact, not a substring — the same idiom
    `tests/test_gate_reader_agreement.py::test_the_floor_is_a_literal_the_population_cannot_drag`
    uses for the identical shape, and the one this test used to be missing:
    #472's F2 mutated `MINIMUM_CI_CLAIM_SCENARIOS = 3` to
    `len(CI_CLAIM_SCENARIOS)` and the OLD substring-grep version of this test
    still passed 72 green, because the decoy literal `3` still sat in a
    trailing comment. A comment cannot satisfy an AST check."""
    source = Path(vg.__file__).read_text(encoding="utf-8")
    assigned = [
        node.value
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "MINIMUM_CI_CLAIM_SCENARIOS"
    ]
    assert len(assigned) == 1, "the floor is assigned once, at module level"
    assert isinstance(assigned[0], ast.Constant) and isinstance(assigned[0].value, int), (
        "the floor must be an integer literal; written as `len(CI_CLAIM_SCENARIOS)` "
        "it is compared against a count derived from the table itself and can "
        "never fire — and that construction is exactly what #472's F2 mutated it "
        "to, surviving the old substring-grep form of this test at 72 passed"
    )
    assert len(vg.CI_CLAIM_SCENARIOS) == assigned[0].value, (
        "the literal must equal the population it is sized to — an added "
        "scenario should raise the floor rather than widen the slack"
    )
    assert len(vg.CI_CLAIM_SCENARIOS) >= vg.MINIMUM_CI_CLAIM_SCENARIOS


def test_a_shrunken_ci_claim_table_is_unmeasured_not_silently_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vg, "CI_CLAIM_SCENARIOS", vg.CI_CLAIM_SCENARIOS[:1])
    measured = vg.measure_ci_claims()
    assert measured["ci_claim_scenarios_checked"] == 1
    assert measured["ci_claim_scenarios_checked"] < vg.MINIMUM_CI_CLAIM_SCENARIOS


def test_a_missing_script_is_the_maximal_ci_claim_defect() -> None:
    measured = vg.measure_ci_claims(script_path=Path("/nonexistent/verified_gate.sh"))
    assert measured["verdict_block_claims_about_ci_that_are_not_measured"] == -1
    assert measured["gate_status"] == "measured"


# --------------------------------------------------------------------------
# `_main` writes both T121's and T161's evidence from the one bare
# invocation `make evidence` actually makes, and a live CI-claim regression
# fails it — end to end, not just `measure_ci_claims()` in isolation.
# --------------------------------------------------------------------------


def _patch_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, script: Path) -> None:
    instructions = tmp_path / "CLAUDE.md"
    instructions.write_text(f"Run `{script.name}`.\n", encoding="utf-8")
    monkeypatch.setattr(vg, "DEFAULT_SCRIPT_PATH", script)
    monkeypatch.setattr(vg, "DEFAULT_INSTRUCTIONS", instructions)
    monkeypatch.setattr(vg, "DEFAULT_EVIDENCE_PATH", tmp_path / "T121.json")
    monkeypatch.setattr(vg, "DEFAULT_T161_EVIDENCE_PATH", tmp_path / "T161.json")


def test_a_bare_invocation_writes_both_evidence_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "verified_gate.sh"
    script.write_text(_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    script.chmod(0o755)
    _patch_defaults(monkeypatch, tmp_path, script)

    assert vg._main(["prog"]) == 0
    t121 = json.loads((tmp_path / "T121.json").read_text(encoding="utf-8"))
    t161 = json.loads((tmp_path / "T161.json").read_text(encoding="utf-8"))
    assert t121["verified_gate_defects"] == 0
    assert t161["verdict_block_claims_about_ci_that_are_not_measured"] == 0


def test_a_live_ci_claim_regression_fails_the_bare_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wiring, not just the metric: a script that reintroduces the
    hardcoded sentence must fail `_main`'s bare invocation — the one
    `make evidence` runs — even though T121's own ten contracts do not
    mention CI at all and would otherwise pass it clean."""
    script = tmp_path / "verified_gate.sh"
    script.write_text(
        _mutate(
            'echo "was measured. This block is scoped to that commit only."',
            'echo "was measured. This block is scoped to that commit only. CI is unavailable."',
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    _patch_defaults(monkeypatch, tmp_path, script)

    assert vg._main(["prog"]) == 1
    t161 = json.loads((tmp_path / "T161.json").read_text(encoding="utf-8"))
    assert t161["verdict_block_claims_about_ci_that_are_not_measured"] > 0


def test_an_explicit_target_does_not_trigger_the_ci_claim_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`options.target == DEFAULT_EVIDENCE_PATH` is the whole gate for writing
    T161 alongside T121; an explicit, non-default target must not write it —
    mirroring `test_measuring_another_tree_records_nothing_about_this_one`."""
    script = tmp_path / "verified_gate.sh"
    script.write_text(_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    script.chmod(0o755)
    _patch_defaults(monkeypatch, tmp_path, script)
    decoy = tmp_path / "T161.json"

    assert vg._main(["prog", str(tmp_path / "out.json")]) == 0
    assert not decoy.exists()
