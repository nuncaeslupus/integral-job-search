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

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from integral import corpus_scope
from integral.corpus_scope import (
    _REPO_ROOT,
    CATALAN_SCOPE_ANCHOR,
    CORE_SERVING_MODULES,
    CORPUS_MODULES,
    DEFAULT_PLAN,
    DEFAULT_SRC_DIR,
    EXEMPT_CORPUS_READERS,
    MINIMUM_EVALUATION_POOL,
    MINIMUM_SERVING_MODULES,
    MINIMUM_STIMULUS_POOL,
    STIMULUS_STRUCTURAL_DEPENDENCIES,
    TARGET_MIX,
    _corpus_reads,
    exempt_reader_findings,
    measure,
    measure_provenance,
    serving_path_findings,
    serving_path_modules,
    stimulus_split_findings,
    t4b_row,
)
from integral.task_gate import parse_gate_block

#: T98's archived payload — the file whose fenced `gate` block is what
#: `make verify-gates` actually asserts.
T98_PAYLOAD = _REPO_ROOT / "arsenal" / "tasks" / "_history" / "t-617ab974.md"

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
    """A synthetic `src/integral` carrying every serving-path module, all empty.

    Mirrored off the real tree rather than hand-listed. A hand-listed set of eleven sat
    below `MINIMUM_SERVING_MODULES`, so every reading taken over it came back
    `unmeasured` from the floor — which made the missing-module fixture below pass for
    the wrong reason and put `gate_status == "measured"` out of reach of the gate
    fixture. Reading the census keeps the synthetic tree at the real one's size as the
    real one grows.
    """
    src = tmp_path / "integral"
    src.mkdir()
    for name in (*serving_path_modules(), *EXEMPT_CORPUS_READERS):
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
        # The relative spellings. A serving module is a sibling of `corpus`, so these
        # are the shortest thing to type and were the ones the scan missed.
        "from .corpus import load_ads\n",
        "from .harness import load_store\n",
        "from . import corpus\n",
        "from . import harness\n",
        # Deferred, inside a function body. `ast.walk` reaches it and the ceiling
        # docstring says so — but no fixture drove it, so replacing `ast.walk` with
        # a top-level `.body` scan was green (#307 fourth read, F1). A claim whose
        # only evidence is a reader's ad-hoc run is the shape that paragraph now
        # exists to refuse, so it is driven here.
        "def later():\n    from integral.corpus import load_ads\n",
        # This module. The detector was blind to itself: `corpus_scope` reads both
        # stores (`_read_rows`, `provenance_faults`) and exports `DEFAULT_RAW_ADS`,
        # so a serving module could reach the corpus through the very file that
        # measures the ban and the count would stay at zero. Fail-open, and the
        # shortest route of the lot once someone knows the module exists.
        "from integral.corpus_scope import provenance_faults\n",
        "from integral.corpus_scope import DEFAULT_RAW_ADS\n",
        "from integral import corpus_scope\n",
        "import integral.corpus_scope\n",
        "from .corpus_scope import _read_rows\n",
        "from . import corpus_scope\n",
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


def test_the_declared_gate_fails_when_a_serving_module_reads_the_corpus(tmp_path: Path) -> None:
    """The gate T98 declares must fail on either half of what T98 asserts.

    It declared `corpus_rows_without_a_draw_specification` alone, and that key is a count
    of *rows* — so a serving module reading the corpus left it at zero, left `gate_status`
    at `measured`, and T98's own gate passed a serving-cache regression. The key the block
    names is the sum, and this drives the half that used to be outside it.
    """
    src = _serving_tree(tmp_path, {"rank": "from integral.corpus import load_ads\n"})
    measured = measure_provenance(src_dir=src)

    assert measured["corpus_rows_without_a_draw_specification"] == 0
    assert measured["serving_path_corpus_reads"] == 1
    assert measured["corpus_measurement_set_violations"] == 1
    # And it fails as a *measurement*. A synthetic tree below the module floor reports
    # `unmeasured` whatever it finds, which is a different verdict from "one violation
    # here" — the gate is red either way and the fixture stops telling them apart.
    assert measured["gate_status"] == "measured", measured.get("unmeasured_reason")

    fields = parse_gate_block(T98_PAYLOAD.read_text(encoding="utf-8"))
    assert fields is not None
    assert fields["key"] == "corpus_measurement_set_violations", fields
    assert fields["key"] in measured


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
    # It has to be unmeasured *because of `rank`*. The synthetic tree used to sit below
    # the module floor, so the verdict arrived from the floor and this fixture passed
    # without the absent-module detection existing at all — a gate testing something
    # other than what it claims.
    assert measured["unmeasured_reason"] == "serving-path modules not found: rank"


# --------------------------------------------------------------------------------
# T98 — the one exemption to that ban, and the three things that bound it.
#
# Step 5 (`integral.reaction_elicit`) draws corpus adverts as **stimuli**. The owner
# ruled on 2026-09-04 that this is exempt — "reacting to an advert can never contaminate
# the labels it is scored against" — *provided* the stimuli come from a split disjoint
# from the evaluation set. An exemption with no boundary is a hole with a comment next
# to it, so what follows drives each boundary until it trips.


def _labelled(tmp_path: Path, rows: list[dict[str, str]], name: str = "labelled.jsonl") -> Path:
    """A synthetic labelled store: id, text, split, and nothing else this reads."""
    path = tmp_path / name
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    return path


def _pool(prefix: str, split: str, count: int) -> list[dict[str, str]]:
    """`count` distinct adverts in one split, none of them sharing text."""
    return [
        {"id": f"{prefix}{i}", "text": f"{prefix} advert {i}", "split": split}
        for i in range(count)
    ]


def _clean_store(tmp_path: Path, name: str = "labelled.jsonl") -> list[dict[str, str]]:
    """Both halves, comfortably clear of both floors, and disjoint."""
    del tmp_path, name
    return _pool("e", "elicitation", MINIMUM_STIMULUS_POOL + 5) + _pool(
        "v", "evaluation", MINIMUM_EVALUATION_POOL + 5
    )


def test_the_exemption_is_a_named_module_that_is_exempt_for_itself_alone() -> None:
    """Deliverable 1, asserted structurally before it is asserted as prose.

    Two memberships carry the whole ruling. `reaction_elicit` is **not** in
    `CORE_SERVING_MODULES`, which is the exemption: showing an advert to capture a
    reaction is measurement, not a search result. And it **is** in `CORPUS_MODULES`,
    which is the exemption's second bound: a serving module importing it reaches the
    corpus through it, and that is a corpus read like any other. Exempt for itself,
    never for anyone who imports it.
    """
    for name in EXEMPT_CORPUS_READERS:
        assert name not in CORE_SERVING_MODULES, name
        assert f"integral.{name}" in CORPUS_MODULES, name


def test_the_owners_reason_is_recorded_beside_the_serving_ban() -> None:
    """The rest of deliverable 1: a reader of `CORE_SERVING_MODULES` finds *why* one
    module is missing from it, so the next session does not re-litigate the ruling from
    scratch or, worse, close the "hole" by adding it.

    This is a prose check and is named as one — it asserts a sentence is present, not
    that anything behaves. The behaviour is the test above and the four below.
    """
    source = (DEFAULT_SRC_DIR / "corpus_scope.py").read_text(encoding="utf-8")
    ruling = "reacting to an advert can never contaminate the labels it is scored against"
    assert ruling in source
    # And beside the list, not in some appendix: between the serving-path census and the
    # corpus-module set is where somebody reading the ban is standing.
    assert source.index("CORE_SERVING_MODULES: tuple") < source.index(ruling)
    assert source.index(ruling) < source.index("CORPUS_MODULES = frozenset")


def test_the_exemption_covers_something_real() -> None:
    """An exemption for a module that does not read the corpus is a dead entry that
    nothing would notice going stale. `reaction_elicit` must actually be a corpus
    reader, or the entry — and the laundering bound built on it — protects nothing."""
    for name in EXEMPT_CORPUS_READERS:
        source = (DEFAULT_SRC_DIR / f"{name}.py").read_text(encoding="utf-8")
        assert _corpus_reads(source), name


@pytest.mark.parametrize(
    "body",
    [
        "from integral.reaction_elicit import corpus_stimuli\n",
        "from integral import reaction_elicit\n",
        "import integral.reaction_elicit\n",
        "from .reaction_elicit import corpus_stimuli\n",
        "from . import reaction_elicit\n",
        # Deferred, as above — the laundering route is the one that matters most
        # here, because it is the two-line edit the exemption invites.
        "def later():\n    from integral.reaction_elicit import corpus_stimuli\n",
    ],
)
def test_a_serving_module_reaching_the_corpus_through_the_exemption_is_caught(
    tmp_path: Path, body: str
) -> None:
    """Bound 2, the laundering route, and the one that made the exemption dangerous.

    `reaction_elicit` is not scanned by `serving_path_findings` — that is what being
    exempt means — so before this, `rank` importing it read the corpus with the ban's
    own count still at zero. One import is a shorter detour than any of the direct
    spellings above, and it arrives looking like reuse.
    """
    src = _serving_tree(tmp_path, {"rank": body})
    findings, absent = serving_path_findings(src)
    assert absent == []
    assert [f["module"] for f in findings] == ["rank"]


def test_the_exempt_reader_may_not_import_the_serving_path(tmp_path: Path) -> None:
    """Bound 1, driven the other way: the exemption widened from inside.

    A stimulus and a served offer differ in what happens to the advert next. Importing
    `integral.rank` into the exempt module is that difference as a two-line edit — "while
    we have these adverts, show them as matches" — and nothing else in this file would
    see it, because the exempt module is deliberately outside the serving-path scan.
    """
    src = _serving_tree(tmp_path, {"reaction_elicit": "from integral.rank import rank_offers\n"})
    findings, absent = exempt_reader_findings(src)
    assert absent == []
    assert [f["module"] for f in findings] == ["reaction_elicit"]
    assert "integral.rank" in findings[0]["reason"]


@pytest.mark.parametrize(
    "body",
    [
        "from integral.presentation import render\n",
        "from integral.explain import explain\n",
        "from integral.feedback import record\n",
        "from integral.freshness import age\n",
        "from integral.dedup import dedupe\n",
        "from integral import rank\n",
        "import integral.presentation\n",
        "from .rank import rank_offers\n",
        "from . import presentation\n",
    ],
)
def test_every_spelling_of_widening_the_exemption_trips_it(tmp_path: Path, body: str) -> None:
    """Catching one route and missing eight is a fail-open check. The relative forms are
    here for the reason they are in the serving-ban fixtures above: a sibling import is
    the shortest thing to type, and it was the spelling that scan originally missed."""
    src = _serving_tree(tmp_path, {"reaction_elicit": body})
    findings, _ = exempt_reader_findings(src)
    assert [f["module"] for f in findings] == ["reaction_elicit"], body


def test_the_permitted_dependencies_are_pinned_by_name(tmp_path: Path) -> None:
    """The allowlist's *contents*, written out, so widening it is a failing test.

    Before this the positive fixture was `@parametrize`d over
    `STIMULUS_STRUCTURAL_DEPENDENCIES` itself, so adding `sourcing_market` and
    `sourcing_strategy` to the tuple left the suite green and *added two passing
    tests* — the widening manufacturing its own certificate. A fixture parametrised
    over the thing it pins asserts nothing about that thing (#307 second-reader F2).
    """
    assert STIMULUS_STRUCTURAL_DEPENDENCIES == ("offers", "lifecycle")


def test_every_serving_module_outside_the_allowlist_trips_the_exemption(
    tmp_path: Path,
) -> None:
    """The negative half, derived from the census rather than from a hand-written
    list — so a serving module that exists today and was never fixtured is inside
    this test the day it appears.

    `sourcing_*` is the half that matters and the half the old fixtures missed
    entirely: they drove six `CORE_SERVING_MODULES` and no module that issues a
    search. An import of one of those from `reaction_elicit` is the exemption
    widening until step 5 is sourcing in all but name.
    """
    outside = sorted(set(serving_path_modules()) - set(STIMULUS_STRUCTURAL_DEPENDENCIES))
    assert len(outside) >= 6, outside
    assert any(name.startswith("sourcing_") for name in outside), outside
    for name in outside:
        # One tree per module: `_serving_tree` creates `integral/` and would collide.
        root = tmp_path / name
        root.mkdir()
        src = _serving_tree(root, {"reaction_elicit": f"from integral.{name} import thing\n"})
        findings, _ = exempt_reader_findings(src)
        assert [f["module"] for f in findings] == ["reaction_elicit"], name


@pytest.mark.parametrize("name", ("offers", "lifecycle"))
def test_the_structural_dependencies_of_a_stimulus_are_permitted(
    tmp_path: Path, name: str
) -> None:
    """The boundary has to be narrow *and* usable, or it is not a boundary — it is a ban
    the real module already violates, which gets deleted the first time it is red.

    `integral.offers` is the record a stimulus is (and `compute_offer_id`, which is what
    makes provenance checkable at all); `integral.lifecycle` is the single transition
    that admits one to the candidate's store. Neither orders, filters or presents
    anything, which is why these two and no others.
    """
    src = _serving_tree(tmp_path, {"reaction_elicit": f"from integral.{name} import thing\n"})
    findings, _ = exempt_reader_findings(src)
    assert findings == [], findings


def test_the_real_exempt_reader_stays_inside_its_bounds() -> None:
    """The tree that ships."""
    findings, absent = exempt_reader_findings()
    assert findings == [], findings
    assert absent == [], absent


def test_a_missing_exempt_reader_makes_the_reading_unmeasured_not_zero(tmp_path: Path) -> None:
    """Renaming the exempt module must not read as one fewer place a violation could be.
    Same verdict as a missing serving module, for the same reason: the scan shrinking is
    a reason to distrust the number rather than a number."""
    src = _serving_tree(tmp_path)
    (src / "reaction_elicit.py").unlink()

    findings, absent = exempt_reader_findings(src)
    assert findings == []
    assert absent == ["reaction_elicit"]

    measured = measure_provenance(src_dir=src)
    assert measured["exempt_reader_serving_imports"] == 0
    assert measured["gate_status"] == "unmeasured"
    assert measured["unmeasured_reason"] == "exempt corpus readers not found: reaction_elicit"


def test_no_advert_reachable_as_a_stimulus_is_in_the_evaluation_split() -> None:
    """Bound 3 on the tree that ships — the owner's condition on the exemption.

    An advert a candidate has reacted to is no longer clean held-out data, so a metric
    computed over the evaluation split and quoted as held-out would be contaminated by
    the very act the exemption permits.
    """
    overlaps, collisions, stimulus_pool, evaluation_pool = stimulus_split_findings()
    assert overlaps == [], overlaps
    assert collisions == [], collisions
    assert stimulus_pool >= MINIMUM_STIMULUS_POOL
    assert evaluation_pool >= MINIMUM_EVALUATION_POOL


def test_an_advert_in_both_the_stimulus_pool_and_the_evaluation_split_is_named(
    tmp_path: Path,
) -> None:
    """The planted advert. Without it the committed zero is equally consistent with a
    check that cannot return anything else.

    It is planted under a *different corpus id* and identical text, which is the shape
    that matters: `corpus_stimuli` selects on the `split` field, but an offer is
    addressed by its text, so a row marked `elicitation` can carry an evaluation
    advert's content and every split-field check in the system reads clean. That is the
    fail-open direction — the contamination is silent and the metric is still quoted as
    held-out.
    """
    rows = _clean_store(tmp_path)
    rows.append({"id": "planted", "text": "v advert 0", "split": "elicitation"})
    overlaps, _, _, _ = stimulus_split_findings(_labelled(tmp_path, rows))

    assert [f["row"] for f in overlaps] == ["planted"]
    assert "v0" in overlaps[0]["reason"]


def test_removing_the_planted_advert_returns_the_pool_to_zero(tmp_path: Path) -> None:
    """The other half of the mutation: the check is not simply always red."""
    overlaps, _, _, _ = stimulus_split_findings(_labelled(tmp_path, _clean_store(tmp_path)))
    assert overlaps == []


def test_the_split_field_alone_is_not_what_is_compared(tmp_path: Path) -> None:
    """The same planted row, kept honest about *why* it is a finding.

    Marked `elicitation`, it satisfies every `split == "elicitation"` filter in the
    repository. It is a finding because its **text** is an evaluation advert's, and the
    bridge is `compute_offer_id` — the same function `reaction_elicit` addresses offers
    with, deliberately not a second implementation of the same hash.
    """
    rows = _clean_store(tmp_path)
    rows.append({"id": "planted", "text": "v advert 0", "split": "elicitation"})
    overlaps, _, stimulus_pool, _ = stimulus_split_findings(_labelled(tmp_path, rows))

    # The planted row is inside the reach, so the denominator moves with it: reach is
    # counted in distinct adverts (by text), which is what "reachable as a stimulus"
    # means once two ids can carry one advert.
    assert stimulus_pool == MINIMUM_STIMULUS_POOL + 6
    assert len(overlaps) == 1


def test_two_rows_carrying_identical_text_are_a_collision(tmp_path: Path) -> None:
    """The same defect one step earlier, and reported under its own name.

    Two ids on one text is the mechanism by which a re-split puts one copy in each half.
    Inside a single split it is not yet a contamination, which is exactly why it is a
    separate key: folding it into `stimulus_pool_evaluation_overlaps` would report a
    contamination that has not happened, and omitting it would let one arrive later with
    nothing watching.
    """
    rows = _clean_store(tmp_path)
    rows.append({"id": "twin", "text": "e advert 0", "split": "elicitation"})
    overlaps, collisions, _, _ = stimulus_split_findings(_labelled(tmp_path, rows))

    assert overlaps == []
    assert [f["row"] for f in collisions] == ["e0, twin"]


def test_a_repeated_row_id_is_not_counted_as_a_collision_with_itself(tmp_path: Path) -> None:
    """A duplicated *line* is `provenance_faults`' finding, not this one. Counting it
    here would put one defect in two keys and make the sum wrong in the direction that
    looks like diligence."""
    rows = _clean_store(tmp_path)
    rows.append({"id": "e0", "text": "e advert 0", "split": "elicitation"})
    _, collisions, _, _ = stimulus_split_findings(_labelled(tmp_path, rows))
    assert collisions == []


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        # An empty stimulus pool overlaps nothing …
        (_pool("v", "evaluation", MINIMUM_EVALUATION_POOL + 5), "reachable as stimuli"),
        # … and an empty evaluation split is overlapped by nothing. Two vacuous passes,
        # two floors: a floor on one side alone leaves the other reading a clean zero.
        (_pool("e", "elicitation", MINIMUM_STIMULUS_POOL + 5), "evaluation-split adverts"),
    ],
)
def test_a_disjointness_zero_over_an_empty_side_is_unmeasured(
    tmp_path: Path, rows: list[dict[str, str]], expected: str
) -> None:
    """The vacuous pass this pair of floors exists to refuse.

    Both readings return zero overlaps, and neither is evidence that the stimulus pool
    is disjoint from the evaluation split. The reading is checked for the *specific*
    floor rather than merely for `unmeasured`: a synthetic store also sits below
    `MINIMUM_CORPUS_ROWS`, so asserting the verdict alone would pass with these two
    floors deleted entirely.
    """
    measured = measure_provenance(labelled_path=_labelled(tmp_path, rows))

    assert measured["stimulus_pool_evaluation_overlaps"] == 0
    assert measured["gate_status"] == "unmeasured"
    assert expected in measured["unmeasured_reason"], measured["unmeasured_reason"]
    assert measured["floor_breaches"] >= 1


def test_the_declared_gate_fails_on_a_contaminated_stimulus_pool(tmp_path: Path) -> None:
    """The sum T98's gate block names has to move on the half added for the exemption.

    It was `corpus_rows_without_a_draw_specification + serving_path_corpus_reads`, and
    both stay at zero over a pool contaminated by text: the planted row names a declared
    draw and no serving module imports anything. So the gate T98 declares would have
    passed the regression the exemption's own condition exists to prevent.
    """
    rows = _clean_store(tmp_path)
    rows.append({"id": "planted", "text": "v advert 0", "split": "elicitation"})
    labelled = _labelled(tmp_path, rows)
    measured = measure_provenance(labelled_path=labelled)

    assert measured["stimulus_pool_evaluation_overlaps"] == 1
    assert measured["corpus_measurement_set_violations"] >= 1

    fields = parse_gate_block(T98_PAYLOAD.read_text(encoding="utf-8"))
    assert fields is not None
    assert fields["key"] == "corpus_measurement_set_violations", fields


def test_the_declared_gate_fails_when_the_exemption_is_widened(tmp_path: Path) -> None:
    """And on the other new half. A synthetic tree keeps every other component at zero,
    so the sum moving is this component moving and not something else."""
    src = _serving_tree(tmp_path, {"reaction_elicit": "from integral.rank import rank_offers\n"})
    measured = measure_provenance(src_dir=src)

    assert measured["serving_path_corpus_reads"] == 0
    assert measured["stimulus_pool_evaluation_overlaps"] == 0
    assert measured["exempt_reader_serving_imports"] == 1
    assert measured["corpus_measurement_set_violations"] == 1
    assert measured["gate_status"] == "measured", measured.get("unmeasured_reason")



SUM_COMPONENTS = (
    "corpus_rows_without_a_draw_specification",
    "serving_path_corpus_reads",
    "exempt_reader_serving_imports",
    "stimulus_pool_evaluation_overlaps",
    "corpus_text_collisions",
)


def _sum_row(row_id: str, text: str, **overrides: Any) -> dict[str, Any]:
    """A well-formed corpus row, varied only where a component needs it."""
    row: dict[str, Any] = {
        "id": row_id,
        "source": "exampleboard",
        "source_url": f"https://example.invalid/{row_id}",
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "language": "es",
        "title": "Programador/a backend",
        "company": "Example S.L.",
        "job_family": "programming",
        "draw": "es-programming",
        "text": text,
    }
    row.update(overrides)
    return row


def _store(directory: Path, name: str, rows: list[dict[str, Any]]) -> Path:
    path = directory / name
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )
    return path


def _draws_file(directory: Path) -> Path:
    path = directory / "draws.yaml"
    path.write_text(
        "draws:\n"
        "  - id: es-programming\n"
        '    drawn_at: "2026-01-01"\n'
        "    purpose: Spanish-language programming adverts, for extraction scoring.\n"
        "    languages: [es]\n"
        "    job_families: [programming]\n"
        "    sources: [exampleboard]\n",
        encoding="utf-8",
    )
    return path


def test_the_component_list_is_the_sum_expression_itself() -> None:
    """`SUM_COMPONENTS` is a hand-written mirror, so something has to hold it against
    the expression it mirrors.

    Adding a sixth `len(...)` term to `corpus_measurement_set_violations`, plus its own
    key, left the whole suite green when that term was zero across every fixture — so
    the module's claim that "naming the sum means a sixth component cannot be forgotten"
    was true of `_main`'s exit code and false of everything that checks the sum
    (#307 third read, N5). Read out of the source rather than re-encoded here: a test
    that restates the expression is a second copy to drift.

    **The shape it recognises is `len(<Name>)`, and that is the ceiling.** A term
    spelled `sum(1 for _ in x)`, `len(obj.attr)`, or a bare literal is not counted,
    so a sixth component written that way walks through (#307 fourth read, F3).
    Hoisting the sum into a local, or renaming the key, is caught — by the
    `assert terms` tripwire, fail-closed. Stated rather than left to be found.
    """
    module = ast.parse(Path(corpus_scope.__file__).read_text(encoding="utf-8"))
    matches: list[list[str]] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            named = isinstance(key, ast.Constant) and (
                key.value == "corpus_measurement_set_violations"
            )
            if not named:
                continue
            matches.append([
                call.args[0].id
                for call in ast.walk(value)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "len"
                and call.args
                and isinstance(call.args[0], ast.Name)
            ])
    # Accumulated and required to be unique. Assigning inside the loop measured
    # only the LAST matching dict, so a decoy literal carrying the same key later
    # in the file masked a sixth term in the real sum (#307 fourth read, F2).
    assert len(matches) == 1, matches
    terms = matches[0]
    assert terms, "the sum expression was not found — this test has stopped reading it"
    assert len(terms) == len(SUM_COMPONENTS), (terms, SUM_COMPONENTS)


@pytest.mark.parametrize("component", SUM_COMPONENTS)
def test_each_component_of_the_sum_is_individually_load_bearing(
    tmp_path: Path, component: str
) -> None:
    """The arithmetic, over readings where the component is NOT zero.

    `test_every_component_of_the_sum_is_reported_beside_it` runs over the real corpus,
    where all five components are zero — and `0 == 0` holds for any subset of them, so
    dropping `len(overlaps)`, `len(collisions)` or `len(faults)` from the sum left the
    whole suite green (#307 delta re-read, N1). That matters more since `_main` now
    derives its exit code from the sum alone: a component missing from the arithmetic is
    a violation that neither fails the gate nor prints.

    So each component is driven to a non-zero value on its own and the equality is
    asserted there. A subset sum cannot survive its own component's case.
    """
    root = tmp_path / component
    root.mkdir()
    text = "Buscamos una persona para trabajar en Python. " * 20
    other = "Otra oferta distinta, tambien en Python. " * 20
    src_extra: dict[str, str] = {}
    raw_rows = [_sum_row("a", text, split="elicitation")]
    labelled_rows = [_sum_row("a", text, split="elicitation")]

    if component == "corpus_rows_without_a_draw_specification":
        # A labelled row with no raw row behind it: nothing produced it.
        labelled_rows.append(_sum_row("orphan", other, split="elicitation"))
    elif component == "serving_path_corpus_reads":
        src_extra["rank"] = "from integral.corpus import load_ads\n"
    elif component == "exempt_reader_serving_imports":
        src_extra["reaction_elicit"] = "from integral.rank import rank_offers\n"
    elif component == "stimulus_pool_evaluation_overlaps":
        # One id, one text, both splits. `seen_ids` dedupes, so `by_text` records the
        # id once and there is NO collision — the overlap is isolated, which is what
        # lets this case fail when `len(overlaps)` alone is dropped.
        raw_rows.append(_sum_row("a", text, split="evaluation"))
        labelled_rows.append(_sum_row("a", text, split="evaluation"))
    elif component == "corpus_text_collisions":
        # Two ids, one text, the SAME split: a collision with no overlap.
        raw_rows.append(_sum_row("b", text, split="elicitation"))
        labelled_rows.append(_sum_row("b", text, split="elicitation"))

    measured = measure_provenance(
        raw_path=_store(root, "ads.jsonl", raw_rows),
        labelled_path=_store(root, "labelled.jsonl", labelled_rows),
        draws_path=_draws_file(root),
        src_dir=_serving_tree(root, src_extra),
    )
    assert measured[component] >= 1, measured
    assert sum(measured[key] for key in SUM_COMPONENTS) == (
        measured["corpus_measurement_set_violations"]
    ), measured

def test_every_component_of_the_sum_is_reported_beside_it() -> None:
    """A metric named for more than it counts is the defect this repository has caught
    four times (`status_is_asserted`, `incidental_duplicate_drops`,
    `negation_recall_hits_by_mechanism`, `robots_adjudications_without_a_competent_second_reader`).
    `corpus_measurement_set_violations` is a sum of five, so all five are named keys and
    the arithmetic is asserted rather than described.
    """
    measured = measure_provenance()
    assert sum(measured[key] for key in SUM_COMPONENTS) == (
        measured["corpus_measurement_set_violations"]
    )
    # And the exemption's reach is a number in the record, not a claim in a comment.
    assert measured["stimulus_reachable_adverts_at_least"] == MINIMUM_STIMULUS_POOL
    assert measured["evaluation_adverts_compared_at_least"] == MINIMUM_EVALUATION_POOL
    assert measured["exempt_corpus_readers"] == list(EXEMPT_CORPUS_READERS)
