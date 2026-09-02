"""What is left of the old name after the rename to `integral-job-search` (T55).

The name was settled on 2026-08-18 (`docs/product-shape.md`, question 5). The
rename that followed is mechanical — nothing in the design was ever named after
the project — but it is wide: the package, the distribution, the repository, and
every document that spells one of them out.

Wide and mechanical is exactly the shape of change that finishes at 95%. A
surviving *import* fails loudly the first time that module is loaded, so it gets
found. A surviving *document* fails silently and much later: it sends the next
reader to a repository that no longer answers, and nothing in the test suite has
an opinion about prose. Counting is the only way to know the sweep finished, so
this module counts, and T55's gate is the count.

**Two names, counted separately, because they are swept by different rules.**

- The *package* was `jobsearch` and is now `integral`. Any surviving occurrence
  of that token is a defect: it is not a word, and nothing else in this
  repository is called it.
- The *repository* was `job-search` and is now `integral-job-search`. That one
  cannot be swept by substring, because three other things spell it the same
  way and none of them is this project:

  - `ai-job-search`, the external precedent `status/specification.md` compares
    against — a different project, whose name renaming ours must not touch;
  - the **`job-search process`**, the thirteen-step process the step skills are
    named after (`status/spec-v2-steps.json`). The process is not the project;
    renaming the repository does not rename it, and the task that ordered this
    rename says so in as many words;
  - `job-search-spec-v1:`, the `localStorage` namespace the generated spec
    readers key annotations under. Rewriting it would not update a name, it
    would orphan every annotation a reader has already saved.

  So the repository name is matched on its own, with no letter, digit,
  underscore or hyphen on either side, and not where the word `process` or
  `session` follows it. That admits `# job-search` and `cd job-search`, and
  refuses all three of the above.

**What the allowlist holds, and why each entry is in it.** Everything here is a
place where the old name is *correct* and sweeping it would destroy something:

- `arsenal/tasks/_history/` — the archived rows of the queue ledger. They
  record what a past task said at the time, and the whole point of a ledger is
  that it is not edited afterwards. **Only the archive**: the first version of
  this list held `arsenal/`, which also covered the *live* task files and
  `arsenal/config.toml`, and those are not history — a live task's fenced gate
  block is a command that still runs. Eight of them named `jobsearch.*` after
  T55 swept everything else, two inside gate blocks, and this counter reported
  zero. That is the dishonest-zero this docstring warns about, found in its own
  allowlist.
- `arsenal/tasks/_migrated-history.md` — the same ledger's pre-migration rows,
  archived in one file rather than one per task.
- `claude-arsenal/` and `vendor/` — upstream's code, reverted at the next
  upgrade; not ours to rename.
- this module and `tests/test_naming.py` — a counter has to name the thing it
  counts, and its test has to be able to construct a violation.
- `status/evidence/T55.json` — the payload this writes, which quotes what it
  found.

The list is small and each line is justified above, which is the property that
matters: an allowlist is how a reference counter reaches zero dishonestly, so it
stays short enough to read in one sitting and every entry names its reason.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T55.json"

#: The names this rename replaced, and what replaced them.
OLD_PACKAGE = "jobsearch"
NEW_PACKAGE = "integral"
OLD_REPOSITORY = "job-search"
NEW_REPOSITORY = "integral-job-search"

#: The distribution, and the one package the wheel ships.
DISTRIBUTION_NAME = NEW_REPOSITORY
WHEEL_PACKAGE = f"src/{NEW_PACKAGE}"

# The package token. It is not a word, so a bare match is already unambiguous.
_PACKAGE_REFERENCE = re.compile(rf"(?<![\w-]){OLD_PACKAGE}(?![\w-])")

# The repository name — see the module docstring for each thing this refuses.
# `\s+` rather than a literal space so a line break between the two words of
# "job-search process" does not turn a process reference into a false positive.
_REPOSITORY_REFERENCE = re.compile(
    rf"(?<![\w-]){OLD_REPOSITORY}(?![\w-])(?!\s+(?:process|session))"
)

#: Paths where the old name is correct. Prefix-matched, repo-relative.
ALLOWLIST: tuple[str, ...] = (
    "arsenal/tasks/_history/",
    "arsenal/tasks/_migrated-history.md",
    "claude-arsenal/",
    "vendor/",
    "src/integral/naming.py",
    "tests/test_naming.py",
    "status/evidence/T55.json",
)


class NamingError(Exception):
    """The sweep could not be measured — never silently a count of zero."""


def _tracked_files(repo_root: Path) -> tuple[Path, ...]:
    """Every file the repository ships, from git itself.

    Tracked files, not a directory walk: a rename is about what this repository
    publishes, and a walk would also count build output, virtualenvs and
    whatever else happens to be sitting in the tree. When git cannot answer,
    this raises rather than returning an empty list — a measurement that could
    not run must not read as a clean sweep.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise NamingError(f"{repo_root}: could not list tracked files: {exc}") from exc
    names = [name for name in completed.stdout.decode("utf-8").split("\0") if name]
    if not names:
        raise NamingError(f"{repo_root}: git lists no tracked files")
    return tuple(repo_root / name for name in names)


#: A connector's recorded capture of somebody else's page. Exempt for a reason
#: the allowlist above does not cover: these are **evidence**, not documents
#: this repository authors. Remotive serves a stylesheet called
#: `job-search.css` and a blog tag `/job-search-tips/`; editing a capture so it
#: stops saying so would falsify the very thing the fixture exists to prove,
#: and the rename this gate polices has nothing to do with what a third party
#: names its own URLs. Matched on the path segment rather than by directory
#: prefix so it covers every package without listing them.
_CAPTURE_SEGMENTS = ("/fixture/", "/probe/")


def _is_a_recorded_capture(relative: str) -> bool:
    return relative.startswith("connectors/") and any(
        segment in f"/{relative}" for segment in _CAPTURE_SEGMENTS
    )


def _is_allowlisted(relative: str) -> bool:
    if _is_a_recorded_capture(relative):
        return True
    return any(relative == entry or relative.startswith(entry) for entry in ALLOWLIST)


def measure(
    repo_root: Path = _REPO_ROOT, *, archived: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """T55's gate: surviving references to the old package and repository names.

    `archived` names repo-relative paths to measure as though they had already
    been moved into `arsenal/tasks/_history/`. That directory is allowlisted,
    so archiving a file *is* "this path stops being scanned" and nothing else
    — which is what lets `measure_archive_sensitivity` answer T100's question
    without moving anybody's task file on disk to find out.
    """
    package: list[str] = []
    repository: list[str] = []
    scanned = 0

    for path in _tracked_files(repo_root):
        relative = path.relative_to(repo_root).as_posix()
        if relative in archived or _is_allowlisted(relative):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Binary, or gone since git listed it. Neither can hold a name a
            # reader would follow, and neither is a measurement failure.
            continue
        scanned += 1
        for line_number, line in enumerate(text.splitlines(), start=1):
            if _PACKAGE_REFERENCE.search(line):
                package.append(f"{relative}:{line_number}")
        # Matched over the whole text, not line by line, so the lookahead can
        # see a `process` that the line break put on the following line.
        for match in _REPOSITORY_REFERENCE.finditer(text):
            line_number = text.count("\n", 0, match.start()) + 1
            repository.append(f"{relative}:{line_number}")

    return {
        "old_name_references": len(package) + len(repository),
        "old_package_references": len(package),
        "old_repository_references": len(repository),
        "files_scanned": scanned,
        "package_reference_sites": package,
        "repository_reference_sites": repository,
    }


#: The floor `files_scanned` is asserted against, and what the record carries
#: in its place. Today's sweep sees a little over six hundred files; this sits
#: well below that so the repository can lose a directory without the gate
#: turning red for a reason that is not a finding.
#:
#: A floor rather than a census because `files_scanned` is a **denominator**.
#: It measures nothing about the code — it exists to stop a clean zero resting
#: on an empty scan — and committing it as an exact value made every added
#: file a drift, `open_task_pr.sh`'s archive included. That is T100: the
#: script archives the task file and then runs the host gate, so the committed
#: number had to be the pre-archive value and the post-archive value at once.
MINIMUM_SCANNED = 500

#: T100's own record, beside T55's. Two questions of one sweep: what the
#: rename left behind, and whether what we commit about it can survive a task
#: file moving into `_history/`.
DEFAULT_ARCHIVE_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T100.json"


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed, out of what was measured.

    The one difference is the denominator: the live count goes out and the
    floor it was checked against goes in. The number is not dropped — a reader
    comparing two evidence files still sees what the sweep guaranteed — it
    just stops being a value that moves when a file is added.
    """
    committed = {key: value for key, value in measured.items() if key != "files_scanned"}
    committed["files_scanned_at_least"] = MINIMUM_SCANNED
    return committed


def first_task_file(repo_root: Path = _REPO_ROOT) -> str | None:
    """The repo-relative path of one live task file, or `None` if there is none.

    Deterministic — sorted, first — because a gate that picks a different
    input each run reports a different thing each run.

    It must be a file the sweep currently *scans*. `arsenal/tasks/` also holds
    `_migrated-history.md`, which is allowlisted already, and archiving that
    moves nothing: the first version of this picked it, compared a tree with
    itself, and reported `measured` over a no-op — the same self-comparison
    that made `connector_health`'s probe worthless before T72 was rewritten.
    """
    try:
        tracked = _tracked_files(repo_root)
    except NamingError:
        return None
    live = sorted(
        relative
        for relative in (path.relative_to(repo_root).as_posix() for path in tracked)
        if relative.startswith("arsenal/tasks/")
        and relative.endswith(".md")
        and "/" not in relative[len("arsenal/tasks/") :]
        and not _is_allowlisted(relative)
    )
    return live[0] if live else None


def sensitive_keys(live: dict[str, Any], archived: dict[str, Any]) -> list[str]:
    """Which committed keys disagree across the archive. Empty is the goal."""
    return sorted(key for key in live | archived if live.get(key) != archived.get(key))


def measure_archive_sensitivity(repo_root: Path = _REPO_ROOT) -> dict[str, Any]:
    """T100's gate: `archive_sensitive_evidence_keys`.

    Not a test of the fix's shape but of its effect. `record` could satisfy
    "the archive changes nothing" by dropping the sensitive key entirely, so
    the metric compares the two records key by key and the denominator —
    `evidence_keys_compared` — is what says the comparison happened at all.
    With no task file to archive there is nothing to move and nothing proved,
    which is `unmeasured` rather than a pass.
    """
    candidate = first_task_file(repo_root)
    if candidate is None:
        return {
            "archive_sensitive_evidence_keys": 0,
            "evidence_keys_compared": 0,
            "gate_status": "unmeasured",
            "archived_for_the_comparison": None,
            "sensitive": [],
        }
    live = record(measure(repo_root))
    archived = record(measure(repo_root, archived=frozenset({candidate})))
    sensitive = sensitive_keys(live, archived)
    return {
        "archive_sensitive_evidence_keys": len(sensitive),
        "evidence_keys_compared": len(live | archived),
        "gate_status": "measured",
        "archived_for_the_comparison": candidate,
        "sensitive": sensitive,
    }


def write_archive_sensitivity_evidence(
    evidence: Path = DEFAULT_ARCHIVE_EVIDENCE_PATH,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T100.json`.

    Returns the whole reading; commits all of it but
    `archived_for_the_comparison`. *Which* file `first_task_file` picks is the
    sorted-first **live** task, so it changes the moment that task merges —
    committing it made T100's own record go stale on somebody else's merge,
    which is the defect T100 measures, in the file that measures it. The
    caller still gets the name for its stderr message.
    """
    measured = measure_archive_sensitivity(repo_root)
    committed = {k: v for k, v in measured.items() if k != "archived_for_the_comparison"}
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(committed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T55.json`.

    Returns what was *measured*; writes what is *recorded*. The caller still
    needs the live count for the floor check, and the file must not carry it.
    """
    measured = measure(repo_root)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str]) -> int:
    """Write T55's gate evidence. Exit 1 when any reference to the old name survives.

        python -m integral.naming [evidence-path] [--repo PATH]

    `--repo` measures a checkout other than this one, and then writes nothing
    unless the caller also said where — the same rule `connector_shape` (D-10)
    and `connector_contract` (D-11) follow, for the same reason: a measurement
    of some other tree is not evidence about this repository, and recording it
    unconditionally is how a committed number gets replaced by the answer to a
    different question.
    """
    args = list(argv[1:])
    repo_root = _REPO_ROOT
    own_repo = True
    if "--repo" in args:
        index = args.index("--repo")
        if index + 1 >= len(args):
            print("naming: --repo needs a path", file=sys.stderr)
            return 2
        repo_root = Path(args[index + 1])
        own_repo = False
        args = args[:index] + args[index + 2 :]
    positional = [arg for arg in args if not arg.startswith("--")]
    default_target = DEFAULT_EVIDENCE_PATH if own_repo else None
    target: Path | None = Path(positional[0]) if positional else default_target
    try:
        measured = measure(repo_root) if target is None else write_evidence(target, repo_root)
    except NamingError as exc:
        # Exit 3, not 1: nothing was counted, so nothing passed and nothing failed.
        print(f"naming: {exc}", file=sys.stderr)
        return 3

    for site in measured["package_reference_sites"]:
        print(
            f"✗ {site} still names the old package `{OLD_PACKAGE}` — "
            f"the package is `{NEW_PACKAGE}` (T55)",
            file=sys.stderr,
        )
    for site in measured["repository_reference_sites"]:
        print(
            f"✗ {site} still names the old repository `{OLD_REPOSITORY}` — "
            f"the repository is `{NEW_REPOSITORY}` (T55)",
            file=sys.stderr,
        )
    print(json.dumps(measured, ensure_ascii=False))
    if measured["old_name_references"]:
        return 1

    sensitivity: dict[str, Any] | None = None
    # T100, beside T55 — one sweep, two questions, two files. Written exactly
    # when T55's own record is: `--repo` supplies no default target, so a
    # measurement of another tree lands nowhere unless the caller said where.
    # Gating this on `own_repo` as well made the T100 half unreachable for an
    # explicit `--repo <tree> <target>`, which is the one shape a test of a
    # repository with no live task file can take.
    if target is not None:
        sensitivity = write_archive_sensitivity_evidence(target.parent / "T100.json", repo_root)
        for key in sensitivity["sensitive"]:
            print(
                f"✗ `{key}` changes when {sensitivity['archived_for_the_comparison']} is "
                "archived — a committed value that moves on the archive is what stops "
                "`open_task_pr.sh` opening a PR (T100)",
                file=sys.stderr,
            )
        if sensitivity["archive_sensitive_evidence_keys"]:
            return 1

    # The floor, last: a surviving reference is a finding and outranks a thin
    # denominator, the same precedence `connector_health` applies between a
    # real violation and a missing probe. Exit 3 is "nothing was counted, so
    # nothing passed and nothing failed".
    if measured["files_scanned"] < MINIMUM_SCANNED:
        print(
            f"only {measured['files_scanned']} file(s) were scanned (floor "
            f"{MINIMUM_SCANNED}) — zero surviving references over nothing is not a "
            "measurement",
            file=sys.stderr,
        )
        return 3
    # T100's own denominator, after T55's. Zero sensitive keys over no
    # comparison is zero, and this task exists because a denominator nobody
    # asserted let a check report success over work it did not do — so a
    # checkout that has archived its only task file must not read as a pass
    # here either. Found by review on #284: the fix reproducing the failure it
    # fixes, one exit code down.
    if sensitivity is not None and sensitivity["gate_status"] != "measured":
        print(
            "archive_sensitive_evidence_keys: UNMEASURED — no live task file to "
            "archive, so nothing was compared. Not a pass and not a fail.",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
