"""T51 — candidate state resolves from `$INTEGRAL_HOME`, never from inside a clone.

`docs/distribution.md` §2 is the design; `jobsearch.state_home` is the
mechanism. What these tests hold to is the sentence that makes it a mechanism
rather than a convention: **the resolver refuses to return any path inside a
git work tree**, and `--dev` is the single, explicit way past it.

The refusal is proved against a real temporary git work tree rather than a
mocked one — `.git` in a linked work tree is a *file*, not a directory, and a
containment check written against a mock is exactly the kind that passes in the
suite and waves a real store through on disk.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from jobsearch.state_home import (
    APP_DIR,
    DEV_ENV,
    HOME_ENV,
    XDG_ENV,
    StateHomeRefused,
    candidate_root,
    check_call_site,
    code_lines,
    dev_mode,
    enclosing_work_tree,
    measure,
    probe_refusals,
    profiles_root,
    store_call_sites,
    write_evidence,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def work_tree(tmp_path: Path) -> Path:
    """A real git work tree, because `.git` is not always a directory."""
    tree = tmp_path / "clone"
    tree.mkdir()
    subprocess.run(["git", "init", "-q", str(tree)], check=True, capture_output=True)
    return tree


# ---------------------------------------------------------------------------
# the refusal


def test_a_home_inside_a_git_work_tree_is_refused(work_tree: Path) -> None:
    with pytest.raises(StateHomeRefused) as refusal:
        candidate_root(env={HOME_ENV: str(work_tree / "state")})
    assert str(work_tree) in str(refusal.value)
    assert HOME_ENV in str(refusal.value)


def test_the_refusal_reaches_arbitrarily_deep_paths(work_tree: Path) -> None:
    """Containment walks up; it does not compare against the work tree root."""
    deep = work_tree / "a" / "b" / "c" / "profiles"
    with pytest.raises(StateHomeRefused):
        candidate_root(env={HOME_ENV: str(deep)})


def test_the_refusal_does_not_require_the_path_to_exist(work_tree: Path) -> None:
    """The store root is resolved before it is created — the first run is the one that matters."""
    missing = work_tree / "never" / "created"
    assert not missing.exists()
    with pytest.raises(StateHomeRefused):
        candidate_root(env={HOME_ENV: str(missing)})


def test_a_git_file_counts_as_a_work_tree(tmp_path: Path) -> None:
    """A linked work tree and a submodule both carry `.git` as a file, not a directory."""
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / ".git").write_text("gitdir: /somewhere/else/.git/worktrees/linked\n")
    assert enclosing_work_tree(linked / "store") == linked
    with pytest.raises(StateHomeRefused):
        candidate_root(env={HOME_ENV: str(linked / "store")})


def test_the_xdg_and_default_paths_are_refused_inside_a_repo_too(work_tree: Path) -> None:
    """Every resolution branch goes through the same check, not just the named one."""
    with pytest.raises(StateHomeRefused):
        candidate_root(env={XDG_ENV: str(work_tree / "share")})
    with pytest.raises(StateHomeRefused):
        candidate_root(env={"HOME": str(work_tree)})


def test_a_symlink_into_a_repo_is_refused(tmp_path: Path, work_tree: Path) -> None:
    """Resolution follows links, so a link is not a way around the containment check."""
    link = tmp_path / "store"
    link.symlink_to(work_tree / "inside", target_is_directory=True)
    with pytest.raises(StateHomeRefused):
        candidate_root(env={HOME_ENV: str(link)})


# ---------------------------------------------------------------------------
# where it resolves when it does not refuse


def test_the_default_home_is_outside_the_clone(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    resolved = candidate_root(env={"HOME": str(home)})
    assert resolved == home / f".{APP_DIR}"
    assert enclosing_work_tree(resolved) is None
    assert _REPO_ROOT not in resolved.parents
    assert resolved != _REPO_ROOT


def test_xdg_data_home_is_respected_where_it_is_set(tmp_path: Path) -> None:
    xdg = tmp_path / "xdg"
    home = tmp_path / "home"
    assert candidate_root(env={XDG_ENV: str(xdg), "HOME": str(home)}) == xdg / APP_DIR


def test_integral_home_wins_over_xdg(tmp_path: Path) -> None:
    named = tmp_path / "named"
    assert candidate_root(env={HOME_ENV: str(named), XDG_ENV: str(tmp_path / "xdg")}) == named


def test_an_empty_variable_is_not_a_setting(tmp_path: Path) -> None:
    """`INTEGRAL_HOME=` in a shell profile must not resolve the store to the cwd."""
    home = tmp_path / "home"
    assert candidate_root(env={HOME_ENV: "  ", "HOME": str(home)}) == home / f".{APP_DIR}"


def test_the_profiles_root_sits_under_the_store_root(tmp_path: Path) -> None:
    named = tmp_path / "named"
    assert profiles_root(env={HOME_ENV: str(named)}) == named / "profiles"


# ---------------------------------------------------------------------------
# the escape


def test_dev_mode_is_the_only_way_in_and_is_explicit(work_tree: Path) -> None:
    inside = work_tree / "state"

    # The escape, spelled deliberately, in either of its two forms.
    assert candidate_root(env={HOME_ENV: str(inside), DEV_ENV: "1"}) == inside
    assert candidate_root(env={HOME_ENV: str(inside)}, dev=True) == inside

    # Everything else leaves it shut — an `INTEGRAL_DEV=0` left in a profile
    # reads as off, which is the difference between an escape and a hole.
    for value in ("0", "false", "no", "", "off", "maybe"):
        assert not dev_mode({DEV_ENV: value})
        with pytest.raises(StateHomeRefused):
            candidate_root(env={HOME_ENV: str(inside), DEV_ENV: value})


def test_dev_mode_accepts_only_the_documented_spellings() -> None:
    for value in ("1", "true", "TRUE", "yes", "on"):
        assert dev_mode({DEV_ENV: value})


def test_an_explicit_dev_false_overrides_the_environment(work_tree: Path) -> None:
    """`dev=False` from a caller beats `INTEGRAL_DEV=1` — the argument is the last word."""
    with pytest.raises(StateHomeRefused):
        candidate_root(env={HOME_ENV: str(work_tree / "state"), DEV_ENV: "1"}, dev=False)


# ---------------------------------------------------------------------------
# every call site


def test_every_store_path_resolves_through_the_resolver() -> None:
    """A module that builds its own profile path fails, rather than being reviewed for."""
    sites = store_call_sites(_REPO_ROOT)
    assert sites, "no store call sites were discovered — the audit measured nothing"
    failing = [check_call_site(path, _REPO_ROOT) for path in sites]
    offenders = [site for site in failing if not site.passes]
    assert not offenders, "\n".join(f"{s.site}: {'; '.join(s.reasons)}" for s in offenders)


def test_every_step_checkpoint_is_audited() -> None:
    """The divisor is the checkpoints on disk, not a number this test carries."""
    checkpoints = sorted((_REPO_ROOT / ".claude" / "skills").glob("step-*/scripts/*.py"))
    audited = {p for p in store_call_sites(_REPO_ROOT) if p.name == "run_checkpoint.py"}
    assert audited == {p for p in checkpoints if p.name == "run_checkpoint.py"}


def test_a_call_site_that_builds_a_repo_path_is_caught(tmp_path: Path) -> None:
    """The audit's own detector, proved against a file that commits the sin."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "from pathlib import Path\n"
        "_REPO_ROOT = Path(__file__).resolve().parents[2]\n"
        'ROOT = _REPO_ROOT / "profiles"\n'
    )
    check = check_call_site(offender, tmp_path)
    assert check.builds_a_repo_path
    assert not check.resolves_through_resolver
    assert not check.passes


def test_a_docstring_naming_the_construction_is_not_an_offender(tmp_path: Path) -> None:
    """The audit reads code. Prose explaining what T51 removed is not a call site."""
    explainer = tmp_path / "explainer.py"
    explainer.write_text(
        "from jobsearch.state_home import profiles_root\n"
        '"""The constant this replaced was `_REPO_ROOT / \'profiles\'`."""\n'
        "ROOT = profiles_root()\n"
    )
    check = check_call_site(explainer, tmp_path)
    assert not check.builds_a_repo_path
    assert check.passes


def test_blanking_keeps_line_numbers(tmp_path: Path) -> None:
    numbered = code_lines('x = 1\n"""two\nthree"""\ny = 2\n')
    assert [n for n, _ in numbered] == [1, 2, 3, 4]
    assert numbered[0][1].strip() == "x = 1"
    assert numbered[1][1].strip() == ""
    assert numbered[3][1].strip() == "y = 2"


def test_an_unparseable_call_site_is_reported_not_waved_through(tmp_path: Path) -> None:
    """A file the audit cannot read is a finding, never a silent pass."""
    broken = tmp_path / "broken.py"
    broken.write_text("from jobsearch.state_home import profiles_root\ndef (:\n")
    check = check_call_site(broken, tmp_path)
    assert not check.passes
    assert any("could not be tokenised" in reason for reason in check.reasons)


# ---------------------------------------------------------------------------
# the gate


def test_the_probe_measures_something_and_expects_each_outcome() -> None:
    probes = probe_refusals()
    assert len(probes) >= 8, "the probe set shrank — a gate that checks less is not the same gate"
    unexpected = [p for p in probes if not p.passes]
    assert not unexpected, [f"{p.probe}: expected {p.expected}, got {p.outcome}" for p in probes]


def test_the_gate_is_met_and_was_measured_over_a_non_empty_set() -> None:
    measured = measure(_REPO_ROOT)
    assert measured["paths_checked"] > 0
    assert measured["probes_run"] > 0
    assert measured["call_sites_checked"] > 0
    assert measured["state_paths_inside_a_repo"] == 0, measured["shortfalls"]


def test_the_evidence_file_records_what_was_measured(tmp_path: Path) -> None:
    target = tmp_path / "T51.json"
    measured = write_evidence(target, _REPO_ROOT)
    written = json.loads(target.read_text())
    assert written == measured
    assert written["paths_checked"] == written["probes_run"] + written["call_sites_checked"]
