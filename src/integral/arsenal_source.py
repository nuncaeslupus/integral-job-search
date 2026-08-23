"""T58 — no subtree; the skills are vendored, and that is the point.

Two things that sound alike are held apart here, and getting them the wrong way
round is what this module exists to prevent.

**The subtree is gone.** `vendor/claude-arsenal` was a copy of upstream's whole
repository, maintained by `git subtree pull`. A squash merge drops the
`git-subtree-split:` trailer, so the next pull replays from a stale base and
conflicts on files that carry no local edits by construction; the standing
resolution was "take upstream's tree verbatim", a ceremony performed every
upgrade to reconcile a copy nobody edits. `/init` writes what this repo needs
now, so there is nothing to pull and nothing to reconcile.

**The skills are vendored on purpose, and must stay that way.** `/init` at
v2.0.0 copies upstream's skills into `.claude/skills/` and marks each with
`.arsenal-vendored`. That is not the old duplication: it is the only thing that
works on every surface. A cloud session — Claude Code on the web, `claude
--cloud`, the apps, routines — runs on a fresh clone on another machine, never
sees `~/.claude/`, and **does not install plugins the repo asks for**. Upstream
verified that against a live session rather than inferring it from docs
(`claude-arsenal#200`): with a correct declaration committed and the tag
reachable from inside the sandbox, `known_marketplaces.json` was absent and
`installed_plugins.json` empty. What a cloud session loads is what was
committed.

So the count that must be zero is the **subtree**, and the count that must be
non-zero is the **vendored skills**. Both are reported, because "we removed the
tree" and "we removed the skills" would otherwise be the same clean zero.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T58.json"

#: Where a vendored upstream tree would sit. Named rather than inferred: the
#: check is "no copy of upstream is tracked here", and a prefix it has to guess
#: is a prefix it can guess wrong.
VENDOR_PREFIX = "vendor/"

#: The machinery a subtree would need. Reported beside the count so a reviewer
#: can see the removal is complete rather than take the zero on trust.
SUBTREE_MARKERS = ("git subtree", "verify-subtree", "arsenal-upgrade", "update-skills")

#: `/init` stamps this into every skill folder it owns. It is what lets the
#: vendoring be counted without guessing which skills are upstream's — and what
#: lets `/init` leave a skill this repo authored alone.
VENDOR_MARKER = ".arsenal-vendored"


class ArsenalSourceError(Exception):
    """The working tree cannot be read."""


def tracked_files(root: Path = _REPO_ROOT) -> list[str]:
    """Every path git tracks, from git rather than from a filesystem walk.

    An untracked stray copy is somebody's scratch directory; a *tracked* one is
    the repo carrying upstream again, which is the thing being ruled out.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ArsenalSourceError(f"cannot list tracked files: {exc}") from exc
    return [line for line in out.stdout.splitlines() if line]


def vendored_files(files: list[str], prefix: str = VENDOR_PREFIX) -> list[str]:
    return sorted(path for path in files if path.startswith(prefix))


def subtree_machinery(makefile: Path | None = None) -> list[str]:
    """Which subtree markers still appear in the Makefile, if any."""
    path = makefile or _REPO_ROOT / "Makefile"
    text = path.read_text(encoding="utf-8")
    return [marker for marker in SUBTREE_MARKERS if marker in text]


def vendored_skills(root: Path = _REPO_ROOT) -> list[str]:
    """The skill folders `/init` owns, by their marker rather than by a name list."""
    skills = root / ".claude" / "skills"
    if not skills.is_dir():
        return []
    return sorted(d.name for d in skills.iterdir() if (d / VENDOR_MARKER).is_file())


def measure(root: Path = _REPO_ROOT) -> dict[str, Any]:
    """T58's gate."""
    files = tracked_files(root)
    vendored = vendored_files(files)
    machinery = subtree_machinery()
    skills = vendored_skills(root)
    return {
        "upstream_subtree_files": len(vendored),
        "subtree_paths": vendored[:20],
        # Non-zero on purpose. A cloud session installs no plugins, so skills
        # that are not committed do not exist there at all.
        "vendored_skills": len(skills),
        "subtree_machinery_in_makefile": machinery,
        # The bundle is generated, not vendored, and it must survive: every
        # protocol step calls into it. Counted so "we removed the tree" cannot
        # be confused with "we removed the bundle".
        "bundle_files": len([path for path in files if path.startswith("claude-arsenal/")]),
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T58.json`."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write T58's gate evidence. Exit 1 on a subtree, or on skills that are not committed."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    if measured["upstream_subtree_files"]:
        print(
            f"upstream_subtree_files: {measured['upstream_subtree_files']} tracked file(s) "
            f"under {VENDOR_PREFIX!r} — `/init` writes what this repo needs; there is no "
            "subtree to maintain.",
            file=sys.stderr,
        )
        return 1
    if not measured["vendored_skills"]:
        print(
            "vendored_skills: 0 — `.claude/skills/` carries no `/init`-owned skill. A cloud "
            "session installs no plugins, so uncommitted skills do not exist there. "
            "Run `/init`.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
