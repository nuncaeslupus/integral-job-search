"""T31 — a reviewer's note stays bound to the section it was written on.

`create_reader.py` keys a note by a section id derived from its number, and
that id survives a later insertion that renumbers the document — the exact
failure PR #16's review thread found. These tests build tiny fixture git
repositories (the pattern `tests/test_arsenal_subtree.py` already uses) so the
renumbering can actually happen and be caught, rather than only ever running
against a real repository whose committed state already passes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from jobsearch.reader_notes import (
    MINIMUM_PROBES,
    ReaderTarget,
    all_readings,
    classify,
    derive_section_titles,
    discover_reader_targets,
    measure,
    probe_rebinding_detection,
    write_evidence,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

_BEFORE_SPEC = (
    "# Doc\n\n"
    "## 9. Alpha\n\nbody\n\n"
    "## 10. Open, and deliberately so\n\nbody\n"
)
_AFTER_SPEC = (
    "# Doc\n\n"
    "## 8. Inserted\n\nbody\n\n"
    "## 9. Alpha\n\nbody\n\n"
    "## 10. What S2 inherits\n\nbody\n\n"
    "## 11. Open, and deliberately so\n\nbody\n"
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message)


def _makefile_for(spec_name: str, output_dir: str) -> str:
    return (
        "reader:\n"
        "\tuv run --with markdown python3 create_reader.py \\\n"
        f"\t\t--input {spec_name} --output-dir {output_dir} --name X\n"
    )


def _rebinding_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """A repo whose notes.json seeds two keys, then a section is inserted
    ahead of both — renumbering one of the two sections those keys named."""
    repo = tmp_path
    _git(repo, "init", "-q")
    (repo / "Makefile").write_text(_makefile_for("spec.md", "reader"), encoding="utf-8")
    spec = repo / "spec.md"
    outdir = repo / "reader"
    outdir.mkdir()
    spec.write_text(_BEFORE_SPEC, encoding="utf-8")
    notes = outdir / "notes.json"
    notes.write_text(
        json.dumps({"s-spec-10": "closing note", "s-spec-9": "unrelated note"}) + "\n",
        encoding="utf-8",
    )
    _commit(repo, "seed notes before the section insertion")

    spec.write_text(_AFTER_SPEC, encoding="utf-8")
    _commit(repo, "insert a new section ahead of the others")
    return repo, repo / "Makefile"


# --- the two tests the payload names ----------------------------------------


def test_a_note_whose_section_title_changed_is_reported(tmp_path: Path) -> None:
    """`s-spec-10` meant "Open, and deliberately so" when the note was
    written; an earlier insertion renumbered it onto "What S2 inherits" —
    exactly PR #16's silent re-attachment, and it must not stay silent here."""
    repo, makefile = _rebinding_fixture(tmp_path)

    _, readings = all_readings(repo, makefile)

    reading = next(r for r in readings if r.key == "s-spec-10")
    assert reading.classification == "rebound"
    assert reading.historical_title == "§10 Open, and deliberately so"
    assert reading.current_title == "§10 What S2 inherits"


def test_a_note_on_an_unchanged_section_is_not_reported(tmp_path: Path) -> None:
    """`s-spec-9` ("Alpha") kept its number across the same insertion that
    renumbered its neighbour — a warning here would make every note look
    suspect, which is the same as no warning at all."""
    repo, makefile = _rebinding_fixture(tmp_path)

    _, readings = all_readings(repo, makefile)

    reading = next(r for r in readings if r.key == "s-spec-9")
    assert reading.classification == "unchanged"
    assert reading.historical_title == reading.current_title == "§9 Alpha"

    targets = discover_reader_targets(makefile)
    assert targets == [ReaderTarget(input="spec.md", output_dir="reader")]


# --- cannot-tell is not the same as fine ------------------------------------


def test_a_key_with_no_git_history_is_unresolvable_not_unchanged(tmp_path: Path) -> None:
    """A note added to `notes.json` without ever being committed has no
    revision to compare against — reporting it `unchanged` would claim a
    consistency this module never actually checked."""
    repo = tmp_path
    _git(repo, "init", "-q")
    (repo / "Makefile").write_text(_makefile_for("spec.md", "reader"), encoding="utf-8")
    (repo / "spec.md").write_text(_BEFORE_SPEC, encoding="utf-8")
    outdir = repo / "reader"
    outdir.mkdir()
    (outdir / "notes.json").write_text(json.dumps({"s-spec-9": "uncommitted"}), encoding="utf-8")
    _commit(repo, "spec only — notes.json is never committed at this value")
    # Overwrite after the commit so git history never reflects this value.
    (outdir / "notes.json").write_text(
        json.dumps({"s-spec-9": "a different, uncommitted note"}), encoding="utf-8"
    )

    _, readings = all_readings(repo, repo / "Makefile")

    reading = next(r for r in readings if r.key == "s-spec-9")
    assert reading.classification == "unresolvable"


def test_a_key_whose_section_no_longer_exists_is_unresolvable(tmp_path: Path) -> None:
    """A note whose section was deleted outright is not "fine" (nothing to
    differ from) and not a confirmed rebinding (nothing to compare against) —
    it belongs in the third bucket."""
    repo = tmp_path
    _git(repo, "init", "-q")
    (repo / "Makefile").write_text(_makefile_for("spec.md", "reader"), encoding="utf-8")
    spec = repo / "spec.md"
    outdir = repo / "reader"
    outdir.mkdir()
    spec.write_text(_BEFORE_SPEC, encoding="utf-8")
    (outdir / "notes.json").write_text(
        json.dumps({"s-spec-10": "closing note"}) + "\n", encoding="utf-8"
    )
    _commit(repo, "seed the note")
    spec.write_text("# Doc\n\n## 9. Alpha\n\nbody\n", encoding="utf-8")  # §10 removed
    _commit(repo, "remove the section entirely")

    _, readings = all_readings(repo, repo / "Makefile")

    reading = next(r for r in readings if r.key == "s-spec-10")
    assert reading.classification == "unresolvable"
    assert reading.current_title is None


def test_a_broken_note_value_does_not_stop_the_others_being_read(tmp_path: Path) -> None:
    """One note whose value is not text degrades to `unresolvable` on its own;
    it must not raise and take the rest of the reader's notes down with it."""
    repo = tmp_path
    _git(repo, "init", "-q")
    (repo / "Makefile").write_text(_makefile_for("spec.md", "reader"), encoding="utf-8")
    (repo / "spec.md").write_text(_BEFORE_SPEC, encoding="utf-8")
    outdir = repo / "reader"
    outdir.mkdir()
    (outdir / "notes.json").write_text(
        json.dumps({"s-spec-9": "a real note", "s-spec-10": 42}) + "\n", encoding="utf-8"
    )
    _commit(repo, "one broken note alongside a good one")

    _, readings = all_readings(repo, repo / "Makefile")

    by_key = {r.key: r for r in readings}
    assert by_key["s-spec-10"].classification == "unresolvable"
    assert by_key["s-spec-9"].classification == "unchanged"


# --- section id derivation ---------------------------------------------------


def test_derive_section_titles_dedupes_colliding_slugs() -> None:
    """Two unnumbered headings that slug to the same text must still get
    distinct ids — the id-derivation half of the bug this module exists to
    catch could hide inside its own dedupe logic."""
    doc = "# Doc\n\n## Option: A\n\nbody\n\n## Option! A\n\nbody\n"

    titles = derive_section_titles(doc)

    ids = [key for key in titles if key.startswith("s-spec-option-a")]
    assert len(set(ids)) == 2


@pytest.mark.skipif(
    not (_REPO_ROOT / ".claude" / "skills" / "specify" / "scripts" / "create_reader.py").is_file()
    or shutil.which("uv") is None,
    reason="the specify skill is not vendored here, or uv is unavailable",
)
def test_derived_titles_match_the_real_generator(tmp_path: Path) -> None:
    """`derive_section_titles` is a from-scratch reimplementation of half of
    `create_reader.py`'s id/title logic (so this gate does not depend on the
    `markdown` package the real tool needs to even import). Run the real tool
    whenever it is actually available and hold the two to the same answer, so
    a drift between them is caught here instead of only ever in production."""
    script = (
        _REPO_ROOT / ".claude" / "skills" / "specify" / "scripts" / "create_reader.py"
    )
    doc = _REPO_ROOT / "status" / "spec-v2-process.md"
    result = subprocess.run(
        [
            "uv", "run", "--with", "markdown", "python3", str(script),
            "--input", str(doc), "--output-dir", str(tmp_path), "--name", "X",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"create_reader could not run here: {result.stderr.strip()[:160]}")

    html = (tmp_path / "spec-reader.html").read_text(encoding="utf-8")
    real: dict[str, str] = {}
    for match in re.finditer(
        r'<article class="sec" id="([^"]+)">.*?'
        r'<span class="chip">([^<]*)</span><span class="sec-title">(.*?)</span>',
        html,
        re.S,
    ):
        domid, chip, title_html = match.groups()
        title_text = re.sub("<[^>]+>", "", title_html)
        real[domid] = title_text if chip in ("overview", "▸") else f"{chip} {title_text}"

    mine = derive_section_titles(doc.read_text(encoding="utf-8"))
    mine.pop("s-spec-intro", None)
    real.pop("s-spec-intro", None)
    assert mine == real


# --- Makefile discovery is derived, not restated -----------------------------


def test_reader_targets_are_read_from_the_makefile_not_hardcoded() -> None:
    """The Makefile already declares both readers once
    (`reader-process`/`reader-steps`); a second, hand-kept list here would stop
    covering the day a third reader is added and nobody remembers this file."""
    targets = discover_reader_targets(_REPO_ROOT / "Makefile")

    by_output = {t.output_dir: t.input for t in targets}
    assert by_output["docs/spec-v2"] == "status/spec-v2-process.md"
    assert by_output["docs/spec-v2-steps"] == "status/spec-v2-steps.md"


def test_a_makefile_line_missing_a_flag_is_skipped_not_raised(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text(
        "reader:\n\tpython3 create_reader.py --input spec.md\n", encoding="utf-8"
    )
    assert discover_reader_targets(tmp_path / "Makefile") == []


# --- classify, directly -----------------------------------------------------


def test_classify_reports_rebound_only_when_both_titles_are_known_and_differ() -> None:
    assert classify("§10 Alpha", "§10 Beta")[0] == "rebound"
    assert classify("§10 Alpha", "§10 Alpha")[0] == "unchanged"
    assert classify(None, "§10 Alpha")[0] == "unresolvable"
    assert classify("§10 Alpha", None)[0] == "unresolvable"
    assert classify(None, None)[0] == "unresolvable"


# --- the probe floor and the committed repository ----------------------------


def test_the_adversarial_probe_meets_its_own_floor() -> None:
    probe = probe_rebinding_detection()
    assert probe["checks_run"] >= MINIMUM_PROBES
    assert probe["failures"] == []


def test_the_gate_passes_on_the_committed_notes() -> None:
    measured = measure()

    assert measured["reader_note_rebindings"] == 0
    assert measured["readers_declared"] != []
    assert measured["notes_read"] > 0


def test_evidence_records_the_metric_the_gate_reads(tmp_path: Path) -> None:
    evidence = tmp_path / "T31.json"

    measured = write_evidence(evidence=evidence)

    recorded = json.loads(evidence.read_text(encoding="utf-8"))
    assert recorded == measured
    assert "reader_note_rebindings" in recorded


def test_the_gate_module_runs_as_a_script() -> None:
    """`python -m jobsearch.reader_notes --check` is what `make evidence` and
    a reviewer both actually run — exercise the CLI, not just the functions."""
    result = subprocess.run(
        [sys.executable, "-m", "jobsearch.reader_notes", "--check"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT / "src")},
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["reader_note_rebindings"] == 0
