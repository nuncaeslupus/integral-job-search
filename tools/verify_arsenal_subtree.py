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


def subtree_is_real(root: Path = _REPO_ROOT) -> bool:
    """Whether git history actually records a subtree at the prefix.

    A directory that merely *looks* like the subtree — copied in by hand, say —
    would satisfy every file comparison while `git subtree pull` had nothing to
    pull. The point of the conversion is the history, so the history is what is
    checked.
    """
    result = subprocess.run(
        ["git", "log", "--oneline", "--", str(SUBTREE_PREFIX)],
        capture_output=True,
        text=True,
        cwd=root,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def compare(root: Path = _REPO_ROOT) -> dict[str, object]:
    """Every asset, compared against its assembled copy."""
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

    host_inside: list[str] = []
    for name in HOST_OWNED:
        if (root / SUBTREE_PREFIX / name).exists():
            host_inside.append(f"{SUBTREE_PREFIX}/{name}")

    return {
        "vendored_files_diverging_from_subtree": len(diverging) + len(missing) + len(host_inside),
        "assets_compared": compared,
        "diverging": diverging,
        "missing_from_bundle": missing,
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
    if not measured["subtree_recorded_in_history"]:
        print(
            f"{SUBTREE_PREFIX} has no history — it is a copy, not a subtree, "
            "so `git subtree pull` has nothing to pull",
            file=sys.stderr,
        )
        return 1
    for kind in ("diverging", "missing_from_bundle", "host_owned_inside_subtree"):
        for item in measured[kind]:  # type: ignore[attr-defined]
            print(f"{kind}: {item}", file=sys.stderr)
    return 1 if measured["vendored_files_diverging_from_subtree"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
