"""T58 — upstream is installed, not vendored.

`claude-arsenal` v1.0.0 is a Claude Code marketplace. Its two plugins live in
`~/.claude/plugins/cache/`, installed once per machine, so this repository
carries no copy of upstream's tree and has nothing to pull, re-vendor or verify.

What it does still carry is the assembled bundle under `claude-arsenal/` — every
protocol step calls into it, and upstream's own session protocol prescribes it.
That is not a vendored tree: it is generated, and `init.py` out of the installed
`core` plugin refreshes it on turn one of every session. The distinction this
module measures is exactly that one.

The failure it guards is re-vendoring by reflex. A subtree pull whose squash
merge drops the `git-subtree-split:` trailer replays from a stale base and
conflicts on files that carry no local edits by construction; the standing
resolution was "take upstream's tree verbatim", a ceremony performed every
upgrade to reconcile a copy nobody edits. Removing the tree removed the class,
and this keeps it removed.
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

#: The machinery a re-vendoring would need. Reported beside the count so a
#: reviewer can see the removal is complete rather than take the zero on trust.
SUBTREE_MARKERS = ("git subtree", "verify-subtree", "arsenal-upgrade", "update-skills")


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


def measure(root: Path = _REPO_ROOT) -> dict[str, Any]:
    """T58's gate."""
    files = tracked_files(root)
    vendored = vendored_files(files)
    machinery = subtree_machinery()
    return {
        "vendored_upstream_files": len(vendored),
        "vendored": vendored[:20],
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
    """Write T58's gate evidence. Exit 1 if upstream is vendored here again."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    if measured["vendored_upstream_files"]:
        print(
            f"vendored_upstream_files: {measured['vendored_upstream_files']} tracked file(s) "
            f"under {VENDOR_PREFIX!r} — upstream is installed from the marketplace here, "
            "not vendored.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
