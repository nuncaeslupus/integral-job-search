#!/usr/bin/env python3
"""Assert the assembled `claude-arsenal/` bundle still matches its subtree source.

`claude-arsenal/` is not upstream content. It is *assembled* from
`vendor/claude-arsenal/plugins/core/skills/init/assets/`, which is a real git
subtree of the marketplace repository. That split exists because neither half
of the obvious arrangement works:

- **A subtree at `claude-arsenal/` cannot work.** `git subtree` maps a prefix
  onto the upstream repository *root*, and the bundle lives several directories
  down. A subtree there would import the whole marketplace — `plugins/`,
  `docs/`, its own `Makefile` and `pyproject.toml` — and not one path the
  session protocol calls (`claude-arsenal/bin/queue_branch.sh`) would exist.
- **Host state lives inside the same directory.** `claude-arsenal/queue/` is
  the task ledger and every task payload — dozens of files upstream has never
  heard of. A subtree prefix must hold only upstream content, or every
  `git subtree pull` fights them.

So upstream is vendored at its own prefix and the bundle is copied out of it.
That copy is what this checks: a hand-edit to `claude-arsenal/bin/*.sh` would
work perfectly until the next upgrade silently reverted it, which is the
failure mode a vendored copy has and a subtree is supposed to remove. Here it
is caught instead.

**`session/handover.md` is deliberately excluded.** Upstream ships a template;
this repository's copy is live session state, rewritten every session. It is
the one asset that is *meant* to diverge, and comparing it would make the check
permanently red — which costs more than it protects, because a check that is
always failing is one nobody reads.

**Host-owned paths must stay outside any subtree prefix**, and that is checked
too rather than assumed: if `claude-arsenal/queue/` ever ended up inside one,
an upgrade would take the ledger with it.

Exit: 0 the bundle matches and nothing host-owned is inside a subtree prefix;
1 a divergence; 2 the subtree or the assets directory is missing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
SUBTREE_PREFIX = Path("vendor/claude-arsenal")
ASSETS_SUBPATH = Path("plugins/core/skills/init/assets")
BUNDLE = Path("claude-arsenal")
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "S9.json"

# Live host state, not a vendored asset — see the module docstring.
EXCLUDED_FROM_COMPARISON = frozenset({Path("session/handover.md")})

# Directories under `claude-arsenal/` that belong to this repository and must
# never sit inside a subtree prefix.
HOST_OWNED = ("queue", "session", "project")

# A bundle of one file is not a bundle. Guards against the assets directory
# being empty or mis-pathed and the check passing over nothing.
MINIMUM_ASSETS = 20


class SubtreeError(Exception):
    """The layout itself is wrong — distinct from a file having diverged."""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assets_dir(root: Path = _REPO_ROOT) -> Path:
    path = root / SUBTREE_PREFIX / ASSETS_SUBPATH
    if not path.is_dir():
        raise SubtreeError(
            f"no subtree assets at {path.relative_to(root)} — "
            "run `git subtree add --prefix=vendor/claude-arsenal arsenal <tag> --squash`"
        )
    return path


def subtree_is_real(root: Path = _REPO_ROOT) -> bool | None:
    """Whether git history actually records a *real* subtree merge at the prefix.

    A directory that merely *looks* like the subtree — copied in by hand, say —
    used to satisfy this check: the old implementation accepted any commit that
    merely touched the prefix path, and an ordinary `git add && git commit` of a
    copied directory touches the path just as much as a real subtree merge
    does. `tests/test_arsenal_subtree.py`'s own `_fixture_repo` — a plain
    `git init` plus one commit, no subtree anywhere — proved it: the old check
    read it as real.

    A real `git subtree add`/`pull --squash` writes a distinct marker. Reading
    this repository's own history (`git log --format=%B -- vendor/claude-arsenal`)
    shows the merge commit itself carries only `Merge commit '<sha>' as
    '<prefix>'` — but that squash commit it merges in (`git cat-file -p <sha>`)
    carries the metadata:

        Squashed 'vendor/claude-arsenal/' content from commit f84b4ef

        git-subtree-dir: vendor/claude-arsenal
        git-subtree-split: f84b4eff13a87c29023931147877bc55085466f8

    That squash commit's own tree is the *unprefixed* subtree content, so it
    never shows up in a path-filtered `git log -- <prefix>` walk — only the
    merge commit that brings it in under the prefix does, and that commit's
    message has no trailer. So the check must search commit messages directly
    (`git log --grep`) rather than filtering by path, or it would never find
    the one commit that actually proves anything.

    Three outcomes:

    - True  — a commit whose message carries `git-subtree-dir: <prefix>` is
      reachable from HEAD. A real subtree merge happened.
    - False — history is present and searchable, but no such commit exists.
      The prefix was populated by an ordinary commit: a hand-copy wearing the
      subtree's directory structure. This is the failure the whole function
      exists to catch.
    - None  — "cannot tell": the repository's history does not reach back far
      enough to contain the subtree commit even if it is real — a shallow
      clone (`git rev-parse --is-shallow-repository` reports true), or history
      that has been squashed/rewritten since. This is deliberately NOT folded
      into False. The house rule is that a check must never pass vacuously —
      but a check that is unconditionally red in every shallow CI checkout,
      for a reason that has nothing to do with the repository's actual state,
      is a check nobody reads either. `_main` treats None as "skip this
      sub-check" rather than as a pass or a fail: it neither blocks the run
      nor claims to have confirmed anything.
    """
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        capture_output=True,
        text=True,
        cwd=root,
    )
    is_shallow = shallow.returncode == 0 and shallow.stdout.strip() == "true"

    result = subprocess.run(
        ["git", "log", "-F", "--grep", f"git-subtree-dir: {SUBTREE_PREFIX}", "--format=%H"],
        capture_output=True,
        text=True,
        cwd=root,
    )
    if result.returncode != 0:
        # No searchable history at all (e.g. not a git repository). Distinct
        # from "shallow": there is nothing to blame on truncated history, so
        # this is a real failure, not a "cannot tell".
        return False
    if result.stdout.strip():
        return True
    return None if is_shallow else False


def compare(root: Path = _REPO_ROOT) -> dict[str, object]:
    """Every asset, compared against its assembled copy — in both directions.

    The forward walk (source -> bundle, below) catches a bundled file that
    drifted from or is missing relative to its subtree source. It cannot catch
    the opposite: a file present in `claude-arsenal/` that upstream's asset
    tree has no opinion on at all. That happens two ways — (a) upstream
    deleted a script the bundle still carries, so a removed tool keeps running
    here forever, or (b) someone hand-added a file straight into
    `claude-arsenal/bin/`, which is the single most dangerous case this
    checker exists for: a hand-edit that silently vanishes at the next
    upgrade, because upstream never knew to preserve it. Both look identical
    from the bundle side — "this file exists here and not in the source" — so
    one reverse walk (bundle -> source) below catches both.
    """
    source = assets_dir(root)
    compared = 0
    diverging: list[str] = []
    missing: list[str] = []

    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if relative in EXCLUDED_FROM_COMPARISON:
            continue
        compared += 1
        assembled = root / BUNDLE / relative
        if not assembled.is_file():
            missing.append(str(relative))
        elif _digest(assembled) != _digest(path):
            diverging.append(str(relative))

    # Reverse walk: bundle -> source. `HOST_OWNED` names the exact directories
    # under `claude-arsenal/` that this repository owns rather than upstream —
    # the queue ledger, session state, workspace plans — so a path whose first
    # component is one of them is expected to exist only here and is skipped.
    # Everything else under claude-arsenal/ is asserted to be upstream's asset
    # tree reassembled verbatim: if the source doesn't have it, either upstream
    # deleted it (stale leftover) or nobody but this repository ever added it
    # (undocumented hand-edit) — both are the same signal from this side.
    extra_in_bundle: list[str] = []
    bundle_root = root / BUNDLE
    if bundle_root.is_dir():
        for path in sorted(bundle_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(bundle_root)
            # Compiled bytecode is not a bundle file. Importing any vendored
            # script — which the migration path and several tests do — leaves a
            # `__pycache__/` behind, and reporting it as an undocumented
            # hand-edit turns a required gate red for a file git already
            # ignores.
            if "__pycache__" in relative.parts:
                continue
            if relative.parts and relative.parts[0] in HOST_OWNED:
                continue
            if relative in EXCLUDED_FROM_COMPARISON:
                continue
            if not (source / relative).is_file():
                extra_in_bundle.append(str(relative))

    host_inside: list[str] = []
    for name in HOST_OWNED:
        if (root / SUBTREE_PREFIX / name).exists():
            host_inside.append(f"{SUBTREE_PREFIX}/{name}")

    return {
        "vendored_files_diverging_from_subtree": (
            len(diverging) + len(missing) + len(host_inside) + len(extra_in_bundle)
        ),
        "assets_compared": compared,
        "diverging": diverging,
        "missing_from_bundle": missing,
        "extra_in_bundle": extra_in_bundle,
        "host_owned_inside_subtree": host_inside,
        "subtree_recorded_in_history": subtree_is_real(root),
        "excluded": sorted(str(p) for p in EXCLUDED_FROM_COMPARISON),
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, object]:
    measured = compare()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_EVIDENCE_PATH)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write-evidence", action="store_true")
    # `--root` exists so the checker can be driven against a fixture tree. A
    # verifier whose only input is the real repository can only ever be tested
    # on a state that already passes, which proves nothing about its refusals.
    parser.add_argument("--root", type=Path, default=_REPO_ROOT)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        measured = compare(args.root)
        if args.root == _REPO_ROOT:
            args.path.parent.mkdir(parents=True, exist_ok=True)
            args.path.write_text(
                json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
    except SubtreeError as exc:
        print(f"verify-arsenal-subtree: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(measured, ensure_ascii=False))

    compared = int(measured["assets_compared"])  # type: ignore[call-overload]
    if compared < MINIMUM_ASSETS:
        print(
            f"only {compared} asset(s) compared (floor {MINIMUM_ASSETS}) — "
            "a clean result over nothing is not a measurement",
            file=sys.stderr,
        )
        return 3
    recorded = measured["subtree_recorded_in_history"]
    if recorded is False:
        print(
            f"{SUBTREE_PREFIX} has no history — it is a copy, not a subtree, "
            "so `git subtree pull` has nothing to pull",
            file=sys.stderr,
        )
        return 1
    if recorded is None:
        # "Cannot tell" (shallow clone / squashed history) — see
        # subtree_is_real's docstring. Neither a pass nor a fail: warn and let
        # the rest of the checks (which do not depend on history depth) still
        # run and still gate the exit code.
        print(
            f"{SUBTREE_PREFIX}: cannot confirm subtree history from this checkout "
            "(shallow clone or squashed history?) — skipping the real-subtree check",
            file=sys.stderr,
        )
    for kind in (
        "diverging",
        "missing_from_bundle",
        "extra_in_bundle",
        "host_owned_inside_subtree",
    ):
        for item in measured[kind]:  # type: ignore[attr-defined]
            print(f"{kind}: {item}", file=sys.stderr)
    return 1 if measured["vendored_files_diverging_from_subtree"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
