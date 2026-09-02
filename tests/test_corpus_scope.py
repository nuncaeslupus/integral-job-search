"""D-1 — the Catalan slice's declared scope must not silently drift between
`status/plan.md`, `corpus/raw/README.md`, and `tests/test_corpus_raw.py`.

`test_the_committed_documents_agree` is the real-tree check: it must fail on
the pre-D-1 documents (which said "remote programming" everywhere) and pass
once `status/plan.md`'s T4b row and `corpus/raw/README.md`'s "Known
divergence" section both carry the agreed scope. The rest drive
`integral.corpus_scope.measure` against synthetic documents so the mechanism
is shown to fail for the right reason — a missing anchor phrase, a missing
section, a missing row — not just to happen to pass on the two real files
today.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.corpus_scope import (
    CATALAN_SCOPE_ANCHOR,
    CORE_SERVING_MODULES,
    DEFAULT_PLAN,
    MINIMUM_SERVING_MODULES,
    TARGET_MIX,
    measure,
    measure_provenance,
    serving_path_findings,
    serving_path_modules,
    t4b_row,
)

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


def test_a_negated_declaration_does_not_satisfy_the_anchor(tmp_path: Path) -> None:
    """The anchors match on content words alone, so "the slice is **not**
    Catalan IT ads" satisfied them while stating the opposite of what they
    exist to assert — a drift detector passing on a document that contradicts
    the thing it checks.

    The realistic drift is a reversion to the old wording, which the anchors
    already caught. This is the other direction, and it is the one that would
    have gone unnoticed: the metric stays at 0 and nobody re-reads a green check.
    """
    row = t4b_row()
    plan = DEFAULT_PLAN.read_text(encoding="utf-8").replace(
        row, row.replace("Catalan IT ads at large", "not Catalan IT ads at large")
    )
    negated = tmp_path / "plan.md"
    negated.write_text(plan, encoding="utf-8")

    measured = measure(plan_path=negated)

    assert measured["corpus_language_slice_mismatch"] == 1
    assert "status/plan.md" in measured["mismatches"][0]["document"]


# --------------------------------------------------------------------------------
# T98 — the serving ban, asserted over the code rather than promised in a document.
#
# "No candidate is ever served from the corpus" is a sentence a document can hold while
# the code does the opposite. What makes it enforceable is that the modules putting an
# advert in front of a candidate as an *offer* — sourcing, the offer store, ranking,
# presentation — do not reach the corpus at all, so "just read the corpus when the
# connectors return nothing" is not a two-line change anybody can make quietly.


def _serving_tree(tmp_path: Path, extra: dict[str, str] | None = None) -> Path:
    """A synthetic `src/integral` carrying every serving-path module, all empty."""
    src = tmp_path / "integral"
    src.mkdir()
    for name in (*CORE_SERVING_MODULES, "sourcing_market", "sourcing_strategy", "sourcing_cycles"):
        (src / f"{name}.py").write_text("", encoding="utf-8")
    for name, body in (extra or {}).items():
        (src / f"{name}.py").write_text(body, encoding="utf-8")
    return src


def test_no_ranking_path_reads_the_corpus_as_an_offer_source() -> None:
    """The real tree. An advert is perishable and a stored one is stale by definition;
    serving from the corpus is what let one live session return three adverts and call
    the market exhausted."""
    findings, absent = serving_path_findings()
    assert findings == [], findings
    assert absent == [], absent
    assert len(serving_path_modules()) >= MINIMUM_SERVING_MODULES


def test_the_serving_ban_is_measured_over_a_scan_that_covered_something() -> None:
    """A clean zero is only worth reading over a real denominator, so the floor and the
    module census are inside the evidence rather than beside it."""
    measured = measure_provenance()
    assert measured["serving_path_corpus_reads"] == 0, measured["serving_path_findings"]
    assert measured["gate_status"] == "measured", measured.get("unmeasured_reason")
    assert measured["serving_path_modules_scanned_at_least"] == MINIMUM_SERVING_MODULES


@pytest.mark.parametrize(
    "body",
    [
        "from integral.corpus import load_ads\n",
        "from integral.harness import load_store\n",
        "from integral import corpus\n",
        "import integral.corpus\n",
        'ADS = "corpus/raw/ads.jsonl"\n',
        'ADS = "corpus/labelled/ads.jsonl"\n',
    ],
)
def test_a_serving_module_reaching_the_corpus_is_caught(tmp_path: Path, body: str) -> None:
    """Shown to fail for the right reason, not merely to pass on today's tree.

    Every spelling is here because catching one and missing five is a fail-open check,
    and the shortest route to a serving cache is whichever import the author reached for.
    """
    src = _serving_tree(tmp_path, {"rank": body})
    findings, absent = serving_path_findings(src)
    assert absent == []
    assert [f["module"] for f in findings] == ["rank"]


def test_a_new_sourcing_module_is_inside_the_scan_the_day_it_lands(tmp_path: Path) -> None:
    """The set is not a frozen list: `sourcing_*` is discovered, so a module added next
    week is covered without anyone remembering to add it here."""
    src = _serving_tree(tmp_path, {"sourcing_brand_new": "from integral.corpus import load_ads\n"})
    assert "sourcing_brand_new" in serving_path_modules(src)
    findings, _ = serving_path_findings(src)
    assert [f["module"] for f in findings] == ["sourcing_brand_new"]


def test_a_missing_serving_module_makes_the_reading_unmeasured_not_zero(tmp_path: Path) -> None:
    """A renamed or deleted module dropping out of the scan must not read as one fewer
    place the violation could be. The scan shrinking is a reason to distrust the number,
    which is a verdict of its own."""
    src = _serving_tree(tmp_path)
    (src / "rank.py").unlink()

    findings, absent = serving_path_findings(src)
    assert findings == []
    assert absent == ["rank"]

    measured = measure_provenance(src_dir=src)
    assert measured["serving_path_corpus_reads"] == 0
    assert measured["gate_status"] == "unmeasured"
    assert "rank" in measured["unmeasured_reason"]
