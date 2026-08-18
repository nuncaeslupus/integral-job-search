"""D-1 — the Catalan slice's declared scope must not silently drift between
`status/plan.md`, `corpus/raw/README.md`, and `tests/test_corpus_raw.py`.

`test_the_committed_documents_agree` is the real-tree check: it must fail on
the pre-D-1 documents (which said "remote programming" everywhere) and pass
once `status/plan.md`'s T4b row and `corpus/raw/README.md`'s "Known
divergence" section both carry the agreed scope. The rest drive
`jobsearch.corpus_scope.measure` against synthetic documents so the mechanism
is shown to fail for the right reason — a missing anchor phrase, a missing
section, a missing row — not just to happen to pass on the two real files
today.
"""

from __future__ import annotations

from pathlib import Path

from jobsearch.corpus_scope import CATALAN_SCOPE_ANCHOR, TARGET_MIX, measure

_GOOD_PLAN = (
    "| T# | Description | ... |\n"
    "|----|-------------|-----|\n"
    "| T4b | Collect ads: ES/EN remote programming, plus CA Catalan IT ads "
    "at large | ... |\n"
)
_GOOD_README = (
    "# Raw ad corpus\n\n"
    "## Known divergence — the Catalan slice\n\n"
    "The Catalan 15 are Catalan IT ads at large, with the remote dimension "
    "mixed in rather than filtered for.\n\n"
    "## Reproducing\n\nSome other section.\n"
)


def test_the_committed_documents_agree() -> None:
    """The real `status/plan.md` and `corpus/raw/README.md`, as they stand
    after D-1's fix, must show zero mismatches — this is the check the D-1
    payload's acceptance gate asks for, run against the real tree."""
    measured = measure()
    assert measured["corpus_language_slice_mismatch"] == 0, measured["mismatches"]
    assert measured["target_mix"] == TARGET_MIX


def test_agreeing_documents_produce_no_mismatch(tmp_path: Path) -> None:
    """The positive case, proven first: two documents that both carry the
    anchor phrases must report zero mismatches, not just "no exception"."""
    plan = tmp_path / "plan.md"
    plan.write_text(_GOOD_PLAN, encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(_GOOD_README, encoding="utf-8")

    measured = measure(plan_path=plan, readme_path=readme)
    assert measured["corpus_language_slice_mismatch"] == 0
    assert measured["mismatches"] == []


def test_a_plan_row_reverted_to_remote_programming_is_caught(tmp_path: Path) -> None:
    """The exact regression D-1 was filed over: a future edit to `status/plan.md`
    that drops the Catalan-IT-ads wording and reverts to "remote programming"
    for all three languages must be caught, even though the README still
    states the agreed scope correctly."""
    plan = tmp_path / "plan.md"
    plan.write_text(
        "| T4b | Collect >=100 raw ads (~60 ES, 25 EN, 15 CA) for remote "
        "programming roles | ... |\n",
        encoding="utf-8",
    )
    readme = tmp_path / "README.md"
    readme.write_text(_GOOD_README, encoding="utf-8")

    measured = measure(plan_path=plan, readme_path=readme)
    assert measured["corpus_language_slice_mismatch"] == 1
    assert measured["mismatches"][0]["document"] == "status/plan.md"
    assert CATALAN_SCOPE_ANCHOR in measured["mismatches"][0]["reason"].lower()


def test_a_readme_that_drops_the_remote_mixed_note_is_caught(tmp_path: Path) -> None:
    """The README can restate "Catalan IT ads" and still fail to say *why* that
    matters for labelling — that the remote dimension is mixed in, not
    filtered for. Dropping that sentence is its own mismatch, separate from
    dropping the scope label itself."""
    plan = tmp_path / "plan.md"
    plan.write_text(_GOOD_PLAN, encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(
        "## Known divergence — the Catalan slice\n\n"
        "The Catalan 15 are Catalan IT ads at large.\n\n"
        "## Reproducing\n\nSome other section.\n",
        encoding="utf-8",
    )

    measured = measure(plan_path=plan, readme_path=readme)
    assert measured["corpus_language_slice_mismatch"] == 1
    assert "remote" in measured["mismatches"][0]["reason"]


def test_a_missing_known_divergence_section_is_a_mismatch_not_a_skip(tmp_path: Path) -> None:
    """A README rewritten without its "Known divergence" heading at all must
    not read as "nothing to disagree with, therefore fine" — that vacuous-pass
    shape is exactly what let three documents drift apart before D-1 was
    filed."""
    plan = tmp_path / "plan.md"
    plan.write_text(_GOOD_PLAN, encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text("# Raw ad corpus\n\nNothing about Catalan here.\n", encoding="utf-8")

    measured = measure(plan_path=plan, readme_path=readme)
    assert measured["corpus_language_slice_mismatch"] == 1
    assert measured["mismatches"][0]["document"] == "corpus/raw/README.md"


def test_a_missing_t4b_row_is_a_mismatch_not_a_skip(tmp_path: Path) -> None:
    """Same guard, the other direction: a plan with no T4b row at all must
    count as disagreement, not as nothing to check."""
    plan = tmp_path / "plan.md"
    plan.write_text("| T1 | Scaffold | ... |\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(_GOOD_README, encoding="utf-8")

    measured = measure(plan_path=plan, readme_path=readme)
    assert measured["corpus_language_slice_mismatch"] == 1
    assert measured["mismatches"][0]["document"] == "status/plan.md"
