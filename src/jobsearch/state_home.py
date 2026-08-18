"""Where a candidate's state lives, and the one place that decides it (T51).

`docs/distribution.md` §2 settles the rule this module makes mechanical: the
per-user tree of process specification §6 is **not** inside the clone. It
resolves from `$INTEGRAL_HOME`, defaulting to `~/.integral-job-search/`
(respecting `$XDG_DATA_HOME` where it is set), and

> **the resolver refuses to return any path inside a git work tree.**

Not a warning — a refusal, raised as `StateHomeRefused`, with `--dev` (or
`INTEGRAL_DEV=1`) as the single explicit escape for work on the tool itself.

That refusal is the whole point. `profiles/` being gitignored is a convention:
it holds until somebody adds a path, renames a directory, or clones into a
different layout, and nothing tells them it stopped holding. A resolver that
raises turns "the candidate's data never reaches a repository" into a property
of the code — the same difference between a convention and a mechanism that
`ProfileLeak` already buys for cross-profile reads in `jobsearch.identity`.
`.gitignore` keeps ignoring `profiles/` regardless; two mechanisms for one
promise is correct here, and the cheap one sits behind the enforced one.

**Why the containment check walks up rather than comparing against the clone.**
A resolver that only refused paths under *this* repository would wave through a
store inside any other checkout — a second clone, a dotfiles repository, a
work tree the candidate happens to keep their home directory in. The question
worth answering is "is this path in a repository?", not "is this path in mine",
so `enclosing_work_tree` walks the resolved path's own ancestry looking for
`.git` and reports the first one it finds. `.git` is tested with `exists()`
rather than `is_dir()`: in a linked work tree or a submodule it is a *file*
holding a gitdir pointer, and those are exactly the layouts where a store would
otherwise slip through.

**The gate is `state_paths_inside_a_repo == 0`, and it is measured over call
sites, not asserted.** `measure` does two things a review cannot do reliably by
eye: it points the resolver at a temporary git work tree and counts the
resolutions that were *not* refused, and it scans every module that opens a
profile tree for a path built out of the repository root instead of resolved
here. A call site that builds its own path is the failure this task removes, so
it is counted rather than reviewed for — and `paths_checked` is written beside
the count, because a run that measured nothing is a failure and not a pass over
an empty set (the lesson `step_skills` and `step_gates` both carry).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import tokenize
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T51.json"

#: The environment variable that names the store root outright.
HOME_ENV = "INTEGRAL_HOME"
#: Consulted only when `HOME_ENV` is unset — the XDG base directory.
XDG_ENV = "XDG_DATA_HOME"
#: The single escape, and it has to be spelled deliberately (see `dev_mode`).
DEV_ENV = "INTEGRAL_DEV"
#: The directory name appended to `$XDG_DATA_HOME`, and the dotted fallback.
APP_DIR = "integral-job-search"
#: Everything under the store root that belongs to one candidate (spec §6).
PROFILES_DIR = "profiles"

# Values that turn the dev escape on. Anything else — including "0", "false",
# "no" and the empty string — leaves it off. An escape that a stray `export
# INTEGRAL_DEV=0` silently opens is not an escape, it is a hole.
_DEV_TRUE = frozenset({"1", "true", "yes", "on"})

# A candidate-state path built out of the repository root: the exact
# construction this task replaces. Matched on the two spellings that reach it —
# a module-level `_REPO_ROOT` constant, and an inline `parents[N]` walk.
_REPO_RELATIVE_STATE = re.compile(
    rf"""(?:REPO_ROOT|parents\[\d+\])\s*/\s*["']{PROFILES_DIR}["']""",
)


# Token types that say "the next token starts a statement" — so a STRING there
# is a docstring rather than a value. NL/COMMENT are layout between logical
# lines and must not disturb that judgement.
_STATEMENT_BOUNDARY = frozenset({tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT})
_LAYOUT_TOKENS = frozenset({tokenize.NL, tokenize.COMMENT})


class StateHomeError(Exception):
    """The store root could not be resolved."""


class StateHomeRefused(StateHomeError):
    """The resolved store root is inside a git work tree.

    Raised, never returned. A caller that could carry on with a path this class
    describes would put a candidate's history somewhere `git add -A` can reach
    it, which is the one failure `docs/distribution.md` §2 says the project
    cannot retrofit once someone other than the owner has installed the tool.
    """


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SiteCheck(Strict):
    """One call site's answer to "does it resolve through the resolver?"."""

    site: str
    kind: str
    resolves_through_resolver: bool
    builds_a_repo_path: bool
    reasons: tuple[str, ...] = ()

    @property
    def passes(self) -> bool:
        """No recorded reason — including a file the audit could not read.

        Reading `resolves_through_resolver and not builds_a_repo_path` here was
        a hole: a call site that failed to tokenise sets neither flag, so an
        unauditable file passed as a clean one. A check that cannot see a file
        has not cleared it.
        """
        return not self.reasons


class ProbeCheck(Strict):
    """One resolution attempt against a controlled environment."""

    probe: str
    expected: str
    outcome: str
    inside_a_repo: bool
    detail: str = ""

    @property
    def passes(self) -> bool:
        return self.outcome == self.expected


def dev_mode(env: Mapping[str, str] | None = None) -> bool:
    """Whether the explicit dev escape is on.

    Deliberately narrow: only the values in `_DEV_TRUE` count, so an
    `INTEGRAL_DEV=0` left in a shell profile reads as off rather than as set.
    """
    env = os.environ if env is None else env
    return env.get(DEV_ENV, "").strip().lower() in _DEV_TRUE


def enclosing_work_tree(path: Path) -> Path | None:
    """The nearest ancestor of `path` (or `path` itself) holding a `.git`, if any.

    Existence of `path` is irrelevant — the store root is routinely resolved
    before it is created, and a check that only looked at directories already
    on disk would pass on exactly the first run that matters.
    """
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def candidate_root(
    *,
    env: Mapping[str, str] | None = None,
    dev: bool | None = None,
) -> Path:
    """The store root: `$INTEGRAL_HOME`, else `$XDG_DATA_HOME/integral-job-search`,
    else `~/.integral-job-search` — never a path inside a git work tree.

    `dev` overrides `$INTEGRAL_DEV` when given, so `--dev` on a command line is
    the same escape as the environment variable and neither is implicit.
    """
    env = os.environ if env is None else env
    named = env.get(HOME_ENV, "").strip()
    if named:
        root, source = Path(named), HOME_ENV
    else:
        xdg = env.get(XDG_ENV, "").strip()
        if xdg:
            root, source = Path(xdg) / APP_DIR, XDG_ENV
        else:
            home = env.get("HOME", "").strip()
            base = Path(home) if home else Path("~")
            root, source = base / f".{APP_DIR}", "HOME"

    resolved = root.expanduser().resolve()
    if dev if dev is not None else dev_mode(env):
        return resolved

    work_tree = enclosing_work_tree(resolved)
    if work_tree is not None:
        raise StateHomeRefused(
            f"{source} resolves to {resolved}, which is inside the git work tree at "
            f"{work_tree} — candidate state never lives in a repository "
            f"(docs/distribution.md §2). Point {HOME_ENV} outside it, or pass --dev "
            f"({DEV_ENV}=1) if you are working on the tool itself."
        )
    return resolved


def profiles_root(
    *,
    env: Mapping[str, str] | None = None,
    dev: bool | None = None,
) -> Path:
    """`<store root>/profiles` — the roster every `ProfileStore` is built on."""
    return candidate_root(env=env, dev=dev) / PROFILES_DIR


# ---------------------------------------------------------------------------
# the gate


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(  # fixed argv, no shell
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def probe_refusals() -> list[ProbeCheck]:
    """Resolve against a real git work tree and record what the resolver did.

    Every probe names the outcome it expects, and `measure` counts the ones
    that returned a path from inside a repository. Nothing here reads the
    ambient environment: the probes build the environment they resolve
    against, so the number does not change with the machine it runs on.
    """
    checks: list[ProbeCheck] = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        work_tree = base / "clone"
        (work_tree / "deep" / "nested").mkdir(parents=True)
        _git("init", "-q", str(work_tree), cwd=base)
        outside = base / "elsewhere"
        outside.mkdir()

        cases: list[tuple[str, dict[str, str], str]] = [
            (
                f"{HOME_ENV} at the work tree root",
                {HOME_ENV: str(work_tree)},
                "refused",
            ),
            (
                f"{HOME_ENV} deep inside the work tree",
                {HOME_ENV: str(work_tree / "deep" / "nested" / "state")},
                "refused",
            ),
            (
                f"{XDG_ENV} inside the work tree",
                {XDG_ENV: str(work_tree / "share")},
                "refused",
            ),
            (
                "HOME inside the work tree, no variable set",
                {"HOME": str(work_tree)},
                "refused",
            ),
            (
                f"{HOME_ENV} outside any work tree",
                {HOME_ENV: str(outside / "store")},
                "resolved",
            ),
            (
                f"{DEV_ENV}=1 inside the work tree — the documented escape",
                {HOME_ENV: str(work_tree / "state"), DEV_ENV: "1"},
                "resolved",
            ),
            (
                f"{DEV_ENV}=0 inside the work tree — not an escape",
                {HOME_ENV: str(work_tree / "state"), DEV_ENV: "0"},
                "refused",
            ),
            (
                f"{DEV_ENV} empty inside the work tree — not an escape",
                {HOME_ENV: str(work_tree / "state"), DEV_ENV: ""},
                "refused",
            ),
        ]

        for name, env, expected in cases:
            try:
                resolved = profiles_root(env=env)
            except StateHomeRefused as exc:
                checks.append(
                    ProbeCheck(
                        probe=name,
                        expected=expected,
                        outcome="refused",
                        inside_a_repo=False,
                        detail=str(exc).split(" — ")[0],
                    )
                )
                continue
            inside = enclosing_work_tree(resolved) is not None
            checks.append(
                ProbeCheck(
                    probe=name,
                    expected=expected,
                    outcome="resolved",
                    # The dev escape is the one documented way a store may sit
                    # inside a work tree, so it is reported without being
                    # counted against the gate — every other resolution that
                    # lands in a repository is exactly what the gate forbids.
                    inside_a_repo=inside and DEV_ENV not in env,
                    detail=str(resolved),
                )
            )
    return checks


def store_call_sites(repo_root: Path = _REPO_ROOT) -> list[Path]:
    """Every file that opens a candidate's profile tree, in a stable order.

    The thirteen step checkpoints plus `jobsearch.identity`, which is where the
    roster path used to be a module constant. Discovered by glob rather than
    listed, so a fourteenth step's checkpoint is audited the day it is written
    instead of the day somebody remembers to add it here.
    """
    sites = sorted((repo_root / ".claude" / "skills").glob("step-*/scripts/run_checkpoint.py"))
    identity = repo_root / "src" / "jobsearch" / "identity.py"
    if identity.is_file():
        sites.append(identity)
    return sites


def check_call_site(path: Path, repo_root: Path = _REPO_ROOT) -> SiteCheck:
    """Whether this file resolves the store through this module, and builds no repo path."""
    reasons: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return SiteCheck(
            site=_relative(path, repo_root),
            kind=_kind(path),
            resolves_through_resolver=False,
            builds_a_repo_path=False,
            reasons=(f"could not be read: {exc}",),
        )

    resolves = "state_home" in text and ("profiles_root" in text or "candidate_root" in text)
    if not resolves:
        reasons.append(
            "does not resolve its store root through jobsearch.state_home "
            "(profiles_root / candidate_root)"
        )

    try:
        scanned = code_lines(text)
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        return SiteCheck(
            site=_relative(path, repo_root),
            kind=_kind(path),
            resolves_through_resolver=resolves,
            builds_a_repo_path=False,
            reasons=(*reasons, f"could not be tokenised, so its paths were not audited: {exc}"),
        )

    offending = [(n, line.strip()) for n, line in scanned if _REPO_RELATIVE_STATE.search(line)]
    for number, line in offending:
        reasons.append(f"builds a store path from the repository root at line {number}: {line}")

    return SiteCheck(
        site=_relative(path, repo_root),
        kind=_kind(path),
        resolves_through_resolver=resolves,
        builds_a_repo_path=bool(offending),
        reasons=tuple(reasons),
    )


def code_lines(text: str) -> list[tuple[int, str]]:
    """`text`'s lines with comments and docstrings blanked out.

    The audit looks for a *construction*, so it has to read code rather than
    prose. Without this, the paragraph in `jobsearch.identity` explaining which
    construction T51 removed would itself be reported as that construction —
    and the obvious fix, rewording the explanation, would mean the check
    silently decides what the docstrings may say.

    Docstrings, not every string: the construction being looked for *ends* in a
    string literal (`… / "profiles"`), so blanking all of them would blind the
    audit to the one thing it exists to find. A docstring is a string token
    standing alone as a statement, which is what `_opens_a_statement` reads —
    and `tokenize` is what makes that distinction reliable, since implicit
    concatenation, f-strings and triple quotes all defeat a regex over source.

    Blanked rather than dropped, so the line numbers still line up with the
    file a person is about to open.
    """
    lines = text.splitlines()
    grid = [list(line) for line in lines]
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Unparseable input is reported by the caller as a reason, never
        # quietly waved through as "no offending construction found".
        raise
    opens_statement = True
    for token in tokens:
        blanked = token.type == tokenize.COMMENT or (
            token.type == tokenize.STRING and opens_statement
        )
        if token.type not in _LAYOUT_TOKENS:
            opens_statement = token.type in _STATEMENT_BOUNDARY
        if not blanked:
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row, end_row + 1):
            if not 1 <= row <= len(grid):
                continue
            line = grid[row - 1]
            first = start_col if row == start_row else 0
            last = end_col if row == end_row else len(line)
            for col in range(first, min(last, len(line))):
                line[col] = " "
    return [(n, "".join(chars)) for n, chars in enumerate(grid, start=1)]


def _kind(path: Path) -> str:
    return "checkpoint" if path.name == "run_checkpoint.py" else "module"


def _relative(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def measure(repo_root: Path = _REPO_ROOT) -> dict[str, Any]:
    """The T51 gate reading, as it is written to evidence.

    `state_paths_inside_a_repo` sums two counts that fail the same promise in
    two different ways: a resolution that returned a path inside a work tree,
    and a call site that never asked the resolver at all. `paths_checked` is
    written beside it so a run that checked nothing reads as the failure it is
    rather than as a clean sheet.
    """
    probes = probe_refusals()
    sites = [check_call_site(path, repo_root) for path in store_call_sites(repo_root)]

    leaked = [probe for probe in probes if probe.inside_a_repo]
    unexpected = [probe for probe in probes if not probe.passes]
    offending_sites = [site for site in sites if not site.passes]

    shortfalls: list[dict[str, Any]] = []
    for probe in unexpected:
        shortfalls.append(
            {
                "where": probe.probe,
                "reasons": [f"expected {probe.expected}, got {probe.outcome}: {probe.detail}"],
            }
        )
    for site in offending_sites:
        shortfalls.append({"where": site.site, "reasons": list(site.reasons)})

    return {
        "state_paths_inside_a_repo": len(leaked) + len(offending_sites),
        "paths_checked": len(probes) + len(sites),
        "probes_run": len(probes),
        "call_sites_checked": len(sites),
        "shortfalls": shortfalls,
        "probes": [probe.model_dump(mode="json") for probe in probes],
        "call_sites": [site.model_dump(mode="json") for site in sites],
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T51.json`."""
    measured = measure(repo_root)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.state_home [--check] [--write-evidence [PATH]] [--where]`.

    `--where` prints the store root this environment resolves to (or the
    refusal), which is the question a person actually has when a checkpoint
    script says it cannot find a profile.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence file",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/T51.json)",
    )
    parser.add_argument(
        "--where",
        action="store_true",
        help="print the store root this environment resolves to, and exit",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help=f"the explicit escape: allow a store inside a git work tree ({DEV_ENV}=1)",
    )
    args = parser.parse_args(argv[1:])

    if args.where:
        try:
            print(candidate_root(dev=True if args.dev else None))
        except StateHomeRefused as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 1
        return 0

    measured = measure() if args.check else write_evidence(Path(args.write_evidence))

    print(json.dumps(measured, ensure_ascii=False))
    if measured["paths_checked"] == 0:
        print("no paths were checked — nothing was measured", file=sys.stderr)
        return 3
    for shortfall in measured["shortfalls"]:
        print(f"{shortfall['where']}: {'; '.join(shortfall['reasons'])}", file=sys.stderr)
    return 1 if measured["state_paths_inside_a_repo"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
