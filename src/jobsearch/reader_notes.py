"""Reviewer notes stay bound to the section they were written on (T31).

`.claude/skills/specify/scripts/create_reader.py` generates an annotatable
reader from a spec document (`status/spec-v2-process.md`,
`status/spec-v2-steps.md`) and keys each section's note slot by a stable id
derived from the section's *number* — `s-spec-10` for the section currently
numbered `10`. A reviewer's exported notes (`docs/spec-v2/notes.json`,
`docs/spec-v2-steps/notes.json`) are seeded back in by that same id the next
time the reader is regenerated.

That id is stable only as long as the numbering is. Insert a section earlier
in the document and every id after it now names a *different* section than it
did when the note was written — the generator has no way to notice, because
the id still resolves to something. This is exactly what PR #16's review
thread found: a new §8 pushed "Open, and deliberately so" from §10 to §11, so
the owner's closing note — keyed `s-spec-10` — silently re-attached to "What S2
inherits", a section the owner had never commented on. Nothing failed; the
regenerated reader just showed the wrong person's words under the wrong
heading, and a human reviewer had to notice by reading it.

**What this module checks, and how.** For every reader the project's own
`Makefile` declares (parsed from its `create_reader.py` invocations, never a
list kept here — the Makefile already carries that list once, and a second
copy would stop covering the next reader the day one is added), and for every
note key currently seeded for that reader: find the commit that last set the
note's text to what it is now (`git log` over the notes file, walked forward),
re-derive what section that key resolved to *in the spec document as it stood
at that commit*, and compare it against what the key resolves to in the spec
document now. A changed title is a rebinding — `reader_note_rebindings`, this
module's gate metric, counts exactly that.

**A note that cannot be tied to history is not a note that is fine.** No git
history for the notes file, a source document unreadable at the historical
commit, a key that resolves to nothing in the current document, a non-string
note value — none of these say "the section did not move"; they say "this
could not be checked". Folding them into the same bucket as a clean pass would
make a check that has never looked hard enough for something it cannot see —
so `unresolvable` is counted and reported separately from both `rebound` and
`unchanged`, matching `jobsearch.step_gates`' distinction between "not
implemented" and "the register cannot say".

**The section-id algorithm is re-derived here, not imported.**
`create_reader.py` needs the `markdown` package to run at all (its own
`import markdown` exits the whole script if the dependency is not installed —
see `tests/test_step_specs.py`'s `test_regenerating_the_reader_produces_no_diff`,
which skips for exactly this reason). A gate that only runs where an optional
third-party package happens to be present is not a gate this repository's `make
ci` can rely on, so `derive_section_titles` reimplements just the id/title
half of `create_reader.py`'s `build_part` — the half that needs only `re`, not
`markdown`. `tests/test_reader_notes.py`'s
`test_derived_titles_match_the_real_generator` holds the two in lockstep
against the real tool whenever it *is* available, so a drift between them does
not go unnoticed merely because most runs cannot exercise it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAKEFILE_PATH = _REPO_ROOT / "Makefile"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T31.json"

Classification = Literal["unchanged", "rebound", "unresolvable"]


class Strict(BaseModel):
    """Unknown keys are an error everywhere in this module's schema.

    Matches `jobsearch.question_bank.Strict`: a reader target is parsed from
    the Makefile, which is content this module does not own, and a typo in a
    future recipe line should surface as a parse problem rather than silently
    grow a field nothing reads.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReaderTarget(Strict):
    """One `create_reader.py` invocation, as the Makefile declares it.

    `input` is the spec Markdown source; `output_dir` is where its `notes.json`
    and generated reader live. Both are repo-root-relative, exactly as written
    in the Makefile recipe — resolving them against a repo root is the
    caller's job, so this model stays a faithful parse of the text and nothing
    more.
    """

    input: str = Field(min_length=1)
    output_dir: str = Field(min_length=1)


@dataclass(frozen=True)
class NoteReading:
    """What one note key resolved to when written, and what it resolves to now."""

    reader: str
    key: str
    historical_commit: str | None
    historical_title: str | None
    current_title: str | None
    classification: Classification
    why: str


class ReaderNotesError(Exception):
    """A reader target or its notes file could not be parsed at all."""


# ---------------------------------------------------------------------------
# Makefile parsing — the list of readers is derived, never restated here.

_CREATE_READER_RE = re.compile(r"create_reader\.py\b")
_INPUT_RE = re.compile(r"--input\s+(\S+)")
_OUTPUT_DIR_RE = re.compile(r"--output-dir\s+(\S+)")


def _join_line_continuations(text: str) -> list[str]:
    """Collapse `\\`-continued Makefile recipe lines into single logical lines.

    `reader-process`'s recipe splits `create_reader.py \\` from its
    `--input ... --output-dir ...` line for readability; a regex over the raw
    text would never see `--input` and `create_reader.py` on the same line.
    """
    joined: list[str] = []
    buffer = ""
    for line in text.split("\n"):
        current = buffer + line.lstrip() if buffer else line
        if current.rstrip().endswith("\\"):
            buffer = current.rstrip()[:-1] + " "
        else:
            joined.append(current)
            buffer = ""
    if buffer:
        joined.append(buffer)
    return joined


def discover_reader_targets(makefile: Path = DEFAULT_MAKEFILE_PATH) -> list[ReaderTarget]:
    """Every `create_reader.py --input X --output-dir Y` the Makefile runs.

    Reads the Makefile's own recipes rather than hardcoding `reader-process`
    and `reader-steps` here: a third reader added to the Makefile is covered
    the next time this runs, with no matching edit required in this module —
    the same reasoning `make evidence`'s module list already applies to itself.
    A line naming `create_reader.py` that is missing either flag is skipped,
    not raised on — a Makefile in flux mid-edit should not crash the checker
    for readers it can still describe.
    """
    text = makefile.read_text(encoding="utf-8")
    targets: list[ReaderTarget] = []
    for line in _join_line_continuations(text):
        if not _CREATE_READER_RE.search(line):
            continue
        input_match = _INPUT_RE.search(line)
        output_match = _OUTPUT_DIR_RE.search(line)
        if input_match is None or output_match is None:
            continue
        targets.append(ReaderTarget(input=input_match.group(1), output_dir=output_match.group(1)))
    return targets


# ---------------------------------------------------------------------------
# Section id/title derivation — the id half of create_reader.py's build_part,
# reimplemented without a dependency on the `markdown` package.

_HEADING_RE = re.compile(r"^(#{2,3})\s+(.*)$")
_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+(.*)$")


def _strip_inline_md(text: str) -> str:
    text = re.sub(r"`(.*?)`", r"\1", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"_(.*?)_", r"\1", text)
    return text.strip()


def _slug(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _split_sections(raw: str) -> tuple[str, list[tuple[int, str]]]:
    """(intro_text, [(heading_level, heading_text), ...]) — code fences excluded.

    Mirrors `create_reader.py`'s `parse_doc`: skip past the first `# ` title
    line and the intro paragraph, then split the rest on `##`/`###` headings.
    A heading spelled inside a fenced code block does not count, matched by
    toggling `in_code_block` on every ` ``` ` line exactly as the source
    generator does.
    """
    lines = raw.split("\n")
    i = 0
    in_code_block = False
    h1_found = False
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
        if not in_code_block and re.match(r"^#\s+(.*)$", line):
            i += 1
            h1_found = True
            break
        i += 1
    if not h1_found:
        i = 0
    intro_lines: list[str] = []
    in_code_block = False
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
        if not in_code_block and _HEADING_RE.match(line):
            break
        intro_lines.append(line)
        i += 1
    sections: list[tuple[int, str]] = []
    in_code_block = False
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
        match = _HEADING_RE.match(line) if not in_code_block else None
        if match:
            sections.append((len(match.group(1)), match.group(2).strip()))
        i += 1
    return "\n".join(intro_lines), sections


def derive_section_titles(raw: str, code: str = "SPEC") -> dict[str, str]:
    """domid -> human title, for every section `create_reader.py` would emit.

    `code` defaults to `"SPEC"` because every reader this project's Makefile
    declares runs `create_reader.py --input FILE` — single-file mode, where
    `create_reader.py` hardcodes `code = "SPEC"` regardless of the input
    file's name (`collect_parts_single`). The title is the same `label` text
    the generated reader shows next to the note field — `"§10 What S2
    inherits"` for a numbered section, the bare heading text otherwise — so a
    changed title here is a change a reviewer would actually see.
    """
    intro, sections = _split_sections(raw)
    used: set[str] = set()

    def mk(base: str) -> str:
        domid = "s-" + _slug(base)
        candidate = domid
        suffix = 1
        while candidate in used:
            suffix += 1
            candidate = f"{domid}-{suffix}"
        used.add(candidate)
        return candidate

    titles: dict[str, str] = {}
    if intro.strip():
        titles[mk(f"{code}-intro")] = "Preamble & scope"
    for _level, heading in sections:
        match = _NUM_RE.match(heading)
        if match:
            num, rest = match.group(1), match.group(2)
            titles[mk(f"{code}-{num}")] = f"§{num} {_strip_inline_md(rest)}"
        else:
            plain = _strip_inline_md(heading)
            titles[mk(f"{code}-{_slug(plain)[:32]}")] = plain
    return titles


# ---------------------------------------------------------------------------
# Git plumbing — the note's own history is the only record of what it was
# written against; nothing about that is restated anywhere in this repo.


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _commits_touching(repo_root: Path, relpath: str) -> list[str]:
    """Commits that changed `relpath`, oldest first. Empty if git cannot say."""
    result = _git(repo_root, "log", "--format=%H", "--", relpath)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return list(reversed(result.stdout.strip().split("\n")))


def _blob_at(repo_root: Path, commit: str, relpath: str) -> str | None:
    """`relpath`'s content at `commit`, or `None` if git cannot produce it."""
    result = _git(repo_root, "show", f"{commit}:{relpath}")
    if result.returncode != 0:
        return None
    return result.stdout


@dataclass(frozen=True)
class NotesHistory:
    """Parsed snapshots of one notes file, oldest first, one per commit that

    could actually be read as a JSON object — a commit whose blob was missing,
    unreadable, or not a JSON object is skipped rather than raising, so one bad
    revision in old history does not block reading the rest of it.
    """

    commits: tuple[str, ...]
    snapshots: tuple[dict[str, str], ...]


def load_notes_history(repo_root: Path, relpath: str) -> NotesHistory:
    commits: list[str] = []
    snapshots: list[dict[str, str]] = []
    for commit in _commits_touching(repo_root, relpath):
        blob = _blob_at(repo_root, commit, relpath)
        if blob is None:
            continue
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        commits.append(commit)
        snapshots.append({k: v for k, v in data.items() if isinstance(v, str)})
    return NotesHistory(tuple(commits), tuple(snapshots))


def last_changed_commit(history: NotesHistory, key: str, current_value: str) -> str | None:
    """The most recent commit that set `key` to `current_value`, walked forward.

    Returns `None` when history does not end at `current_value` — most often
    an uncommitted local edit to the notes file, which git history cannot yet
    explain. A note whose value git cannot account for is not one this module
    can say was "written against" any particular commit.
    """
    previous: str | None = None
    last: str | None = None
    for commit, snapshot in zip(history.commits, history.snapshots, strict=True):
        value = snapshot.get(key)
        if value != previous:
            last = commit
        previous = value
    if previous != current_value:
        return None
    return last


# ---------------------------------------------------------------------------
# Classification


def classify(historical_title: str | None, current_title: str | None) -> tuple[Classification, str]:
    """Whether a note's key still means what it meant when the note was written.

    `unresolvable` is returned whenever either title is unknown — a section
    that no longer exists is not the same claim as "the note is fine", and
    folding the two together is exactly the bug T48's `not_implemented` state
    already refuses to make for gate states.
    """
    if historical_title is None and current_title is None:
        return "unresolvable", "no title could be resolved for this key, then or now"
    if historical_title is None:
        return "unresolvable", "the title this note was written against could not be determined"
    if current_title is None:
        return (
            "unresolvable",
            f"was written against {historical_title!r}; its key no longer resolves",
        )
    if historical_title != current_title:
        return (
            "rebound",
            f"was written against {historical_title!r}; now resolves to {current_title!r}",
        )
    return "unchanged", f"still resolves to {current_title!r}"


# ---------------------------------------------------------------------------
# Measurement


def _relpath(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _readings_for_target(target: ReaderTarget, repo_root: Path) -> list[NoteReading]:
    """Every note key currently seeded for one reader target, with its reading.

    Kept separate from `all_readings` so a test can call it directly against a
    fixture `ReaderTarget` without going through Makefile discovery at all.
    """
    notes_path = repo_root / target.output_dir / "notes.json"
    source_path = repo_root / target.input
    if not notes_path.is_file():
        return []

    try:
        raw_notes = json.loads(notes_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [
            NoteReading(
                reader=target.output_dir,
                key="<file>",
                historical_commit=None,
                historical_title=None,
                current_title=None,
                classification="unresolvable",
                why=f"{notes_path} could not be read: {exc}",
            )
        ]
    if not isinstance(raw_notes, dict):
        return [
            NoteReading(
                reader=target.output_dir,
                key="<file>",
                historical_commit=None,
                historical_title=None,
                current_title=None,
                classification="unresolvable",
                why=f"{notes_path} does not contain a JSON object",
            )
        ]

    try:
        current_text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            NoteReading(
                reader=target.output_dir,
                key=str(key),
                historical_commit=None,
                historical_title=None,
                current_title=None,
                classification="unresolvable",
                why=f"{source_path} could not be read: {exc}",
            )
            for key in raw_notes
        ]

    current_titles = derive_section_titles(current_text)
    history = load_notes_history(repo_root, _relpath(notes_path, repo_root))
    source_relpath = _relpath(source_path, repo_root)

    readings: list[NoteReading] = []
    for key, value in raw_notes.items():
        if not isinstance(value, str):
            readings.append(
                NoteReading(
                    reader=target.output_dir,
                    key=str(key),
                    historical_commit=None,
                    historical_title=None,
                    current_title=current_titles.get(str(key)),
                    classification="unresolvable",
                    why=f"note value is {value!r}, not text",
                )
            )
            continue
        commit = last_changed_commit(history, key, value)
        if commit is None:
            readings.append(
                NoteReading(
                    reader=target.output_dir,
                    key=key,
                    historical_commit=None,
                    historical_title=None,
                    current_title=current_titles.get(key),
                    classification="unresolvable",
                    why="no commit in git history ties this note to a source revision",
                )
            )
            continue
        current_title = current_titles.get(key)
        historical_text = _blob_at(repo_root, commit, source_relpath)
        if historical_text is None:
            historical_title = None
            classification: Classification = "unresolvable"
            why = f"{source_path} could not be read at {commit}"
        else:
            historical_title = derive_section_titles(historical_text).get(key)
            classification, why = classify(historical_title, current_title)
        readings.append(
            NoteReading(
                reader=target.output_dir,
                key=key,
                historical_commit=commit,
                historical_title=historical_title,
                current_title=current_title,
                classification=classification,
                why=why,
            )
        )
    return readings


def all_readings(
    repo_root: Path = _REPO_ROOT, makefile: Path = DEFAULT_MAKEFILE_PATH
) -> tuple[list[ReaderTarget], list[NoteReading]]:
    """Every reader target the Makefile declares, and every note's reading."""
    targets = discover_reader_targets(makefile)
    readings: list[NoteReading] = []
    for target in targets:
        readings.extend(_readings_for_target(target, repo_root))
    return targets, readings


# ---------------------------------------------------------------------------
# Adversarial probes — exercised in-memory, no git or filesystem involved, so
# they run identically offline and in CI regardless of what history exists.

MINIMUM_PROBES = 5


def probe_rebinding_detection() -> dict[str, Any]:
    """Try to fool the classifier and the id-derivation with the exact shapes

    the real bug (and its near-misses) take:

    1. a section renumbered by an earlier insertion must classify as `rebound`;
    2. a section whose number and title are both untouched must classify as
       `unchanged`, even while sections around it move;
    3. a key naming a section that no longer exists must classify as
       `unresolvable`, not `rebound` — there is no current title to differ from;
    4. a key with no resolvable history must classify as `unresolvable`, not
       silently pass as `unchanged`;
    5. two distinct unnumbered headings that slug to the same text must still
       get distinct ids — `derive_section_titles`' own dedupe, without which a
       genuine rebinding could hide as "same key, always meant this section".
    """
    failures: list[str] = []
    checks = 0

    before = "# Doc\n\n## 9. Alpha\n\nbody\n\n## 10. Open, and deliberately so\n\nbody\n"
    after = (
        "# Doc\n\n## 8. Inserted\n\nbody\n\n## 9. Alpha\n\nbody\n\n"
        "## 10. What S2 inherits\n\nbody\n\n## 11. Open, and deliberately so\n\nbody\n"
    )
    before_titles = derive_section_titles(before)
    after_titles = derive_section_titles(after)

    # 1. s-spec-10 meant "Open, and deliberately so" before the insertion, and
    #    means "What S2 inherits" after it — a rebinding.
    checks += 1
    classification, _ = classify(before_titles.get("s-spec-10"), after_titles.get("s-spec-10"))
    if classification != "rebound":
        failures.append("a renumbered section was not classified as a rebinding")

    # 2. s-spec-9 ("Alpha") kept its number both times, even though a section
    #    was inserted ahead of it.
    checks += 1
    classification, _ = classify(before_titles.get("s-spec-9"), after_titles.get("s-spec-9"))
    if classification != "unchanged":
        failures.append("an untouched section's number was reported as a rebinding")

    # 3. A key naming a section removed entirely must not be treated as
    #    resolving consistently, and must not be treated as a title mismatch
    #    either — there is nothing on the other side of the comparison.
    checks += 1
    classification, _ = classify("§12 Deleted section", None)
    if classification != "unresolvable":
        failures.append("a key with no current section was not reported unresolvable")

    # 4. No historical title at all (git history could not be resolved).
    checks += 1
    classification, _ = classify(None, after_titles.get("s-spec-9"))
    if classification != "unresolvable":
        failures.append("a key with no resolvable history passed as unchanged")

    # 5. Two unnumbered headings that would slug to the same base text.
    checks += 1
    doc = "# Doc\n\n## Option: A\n\nbody\n\n## Option! A\n\nbody\n"
    titles = derive_section_titles(doc)
    ids = [k for k in titles if k.startswith("s-spec-option-a")]
    if len(set(ids)) != 2:
        failures.append("two distinct headings collapsed onto the same section id")

    return {"checks_run": checks, "failures": failures}


# ---------------------------------------------------------------------------
# The gate


def measure(
    repo_root: Path = _REPO_ROOT, makefile: Path = DEFAULT_MAKEFILE_PATH
) -> dict[str, Any]:
    targets, readings = all_readings(repo_root, makefile)
    probe = probe_rebinding_detection()
    rebound = [r for r in readings if r.classification == "rebound"]
    unresolvable = [r for r in readings if r.classification == "unresolvable"]
    unchanged = [r for r in readings if r.classification == "unchanged"]
    return {
        "reader_note_rebindings": len(rebound),
        "readers_declared": [t.output_dir for t in targets],
        "readers_with_notes": sorted({r.reader for r in readings}),
        "notes_read": len(readings),
        "notes_unchanged": len(unchanged),
        "notes_unresolvable": len(unresolvable),
        "rebindings": [
            {
                "reader": r.reader,
                "key": r.key,
                "historical_commit": r.historical_commit,
                "why": r.why,
            }
            for r in rebound
        ],
        "unresolvable_notes": [
            {"reader": r.reader, "key": r.key, "why": r.why} for r in unresolvable
        ],
        "adversarial_checks_run": probe["checks_run"],
        "adversarial_failures": probe["failures"],
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    repo_root: Path = _REPO_ROOT,
    makefile: Path = DEFAULT_MAKEFILE_PATH,
) -> dict[str, Any]:
    measured = measure(repo_root, makefile)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.reader_notes [--check] [--write-evidence [PATH]]` → T31's gate.

    `--check` measures and reports without writing a file. Without it (the
    default, matching `question_bank` and every other gate module), the
    evidence file is written to `status/evidence/T31.json` unless
    `--write-evidence PATH` overrides the target. `--repo-root`/`--makefile`
    default to this repository and exist so the tool can be pointed at a
    fixture repo — the same reason `question_bank` takes `--dimensions-dir`.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="measure and report only; do not write evidence"
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/T31.json)",
    )
    parser.add_argument(
        "--repo-root",
        default=str(_REPO_ROOT),
        metavar="DIR",
        help="repository root to measure (default: this repository)",
    )
    parser.add_argument(
        "--makefile",
        default=None,
        metavar="PATH",
        help="Makefile to read reader targets from (default: <repo-root>/Makefile)",
    )
    args = parser.parse_args(argv[1:])
    repo_root = Path(args.repo_root)
    makefile = Path(args.makefile) if args.makefile else repo_root / "Makefile"

    measured = (
        measure(repo_root, makefile)
        if args.check
        else write_evidence(Path(args.write_evidence), repo_root, makefile)
    )

    print(json.dumps(measured, ensure_ascii=False))

    if not measured["readers_declared"]:
        print(
            "no create_reader.py targets found in the Makefile — nothing measured",
            file=sys.stderr,
        )
        return 3
    if measured["adversarial_checks_run"] < MINIMUM_PROBES:
        print(
            f"only {measured['adversarial_checks_run']} adversarial checks ran "
            f"(floor {MINIMUM_PROBES}) — a clean score without exercising the edge "
            "cases is not a measurement",
            file=sys.stderr,
        )
        return 3

    violations: list[str] = []
    if measured["reader_note_rebindings"] != 0:
        violations.append(f"reader_note_rebindings = {measured['reader_note_rebindings']} (want 0)")
    for entry in measured["rebindings"]:
        violations.append(f"{entry['reader']}:{entry['key']} {entry['why']}")
    violations.extend(measured["adversarial_failures"])

    for violation in violations:
        print(violation, file=sys.stderr)
    for entry in measured["unresolvable_notes"]:
        print(f"cannot tell — {entry['reader']}:{entry['key']}: {entry['why']}", file=sys.stderr)

    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
