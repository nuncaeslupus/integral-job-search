"""T5's labelling aid — the generated page and `harness import`.

T5 (`arsenal/tasks/_history/lo-d2b2.md`) is `[HUMAN]`: nothing here tests the
labels themselves, because no labels are placed by code. What is tested is the
tooling that makes the person's 300+ label-and-quote decisions fast and
mechanically safe:

* `tools/labelling_page.py` renders every ad and every matched dimension into
  one `file://`-openable page, with the corpus's own text as the only source
  of a "quote" a selection can ever produce.
* `integral.harness.import_labels` (and its CLI shell, `harness import`)
  applies the JSON batch that page emits with the same verbatim-quote
  strictness as `set`, atomically.
* the D-2 property (`status/plan.md`): cue highlighting is navigation, never
  a label default. `test_cue_highlight_never_prefills_a_value` is the test
  named for it.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from integral.dimensions import DEFAULT_DIMENSIONS_DIR, Dimension, load_dimensions
from integral.harness import (
    DEFAULT_STORE_PATH,
    Label,
    LabelledAd,
    Span,
    build_store,
    import_labels,
    load_store,
    locate_quote,
    save_store,
)
from integral.harness import _main as main
from integral.suggestions import SuggestionSet


def _load_labelling_page() -> Any:
    """Import `tools/labelling_page.py` without `tools/` being on `sys.path`.

    `tools/` is repo automation, not a package under `src/` — `pyproject.toml`
    only puts `src` on `pythonpath` (`[tool.pytest.ini_options]`), and adding
    `tools` there is out of scope for this task's file list. Loading the
    module by its file path keeps the test self-sufficient instead of
    depending on a config change shipped elsewhere.

    Returned as `Any`, which is what it honestly is: a module resolved at run
    time whose attributes no stub describes. The alternative — annotating it
    `object` and then silencing `attr-defined` at every use — buys no type
    safety and leaves suppression comments standing where a reader has to judge
    each one. One accurate annotation replaces all three.
    """
    path = Path(__file__).resolve().parents[1] / "tools" / "labelling_page.py"
    spec = importlib.util.spec_from_file_location("labelling_page", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_PAGE = _load_labelling_page()
build_page = _PAGE.build_page
page_main = _PAGE.main
banked_payload = _PAGE._banked_payload

# The real, committed store and model — the fixture every "does the real
# corpus work" test in this file exercises.
STORE = load_store(DEFAULT_STORE_PATH)
DIMENSIONS = [d for d in load_dimensions() if d.side == "matched"]


def ad(
    ad_id: str = "test-1",
    text: str = "Se busca ingeniero con guardias y disponibilidad para viajar.",
    language: str = "es",
    labels: list[Label] | None = None,
) -> LabelledAd:
    return LabelledAd(
        id=ad_id,
        language=language,  # type: ignore[arg-type]
        text=text,
        source_url="https://example.invalid/1",
        split="evaluation",
        labels=labels or [],
    )


def known(*ids: str) -> dict[str, Dimension]:
    """The real committed dimensions, by id — what `import_labels` validates against.

    Real ones rather than stubs, because the import path now also checks that a
    value lands on one of the dimension's declared rungs. A stub scale would let
    a test pass a value the committed model would refuse, which is the direction
    that hides a regression rather than causing one.
    """
    by_id = {dimension.id: dimension for dimension in load_dimensions()}
    return {dimension_id: by_id[dimension_id] for dimension_id in ids}


def row(
    ad_id: str = "test-1",
    dimension: str = "on_call_load",
    value: float = 0.8,
    quote: str = "guardias",
    negated: bool = False,
    labeller: str = "owner",
    round_: int = 1,
) -> dict[str, object]:
    return {
        "ad_id": ad_id,
        "dimension": dimension,
        "value": value,
        "quote": quote,
        "negated": negated,
        "labeller": labeller,
        "round": round_,
    }


# ── the generated page ──────────────────────────────────────────────────────


def test_generated_page_contains_every_matched_dimension_and_every_ad() -> None:
    """A labeller working from the page must never need to open the catalogue.

    Every ad the harness knows about, and every one of the 22 `matched`
    dimensions, has to be reachable from the single generated file — a page
    missing even one of either silently narrows what the person can label.
    """
    page = build_page(STORE, DIMENSIONS)

    for dimension in DIMENSIONS:
        assert f'"{dimension.id}"' in page, f"dimension {dimension.id} missing from the page"
        assert dimension.label.en in page, f"{dimension.id}'s label missing"
    for ad_record in STORE:
        assert f'"{ad_record.id}"' in page, f"ad {ad_record.id} missing from the page"

    embedded = _embedded_data(page)
    assert len(embedded["ads"]) == len(STORE)
    assert len(embedded["dimensions"]) == len(DIMENSIONS)


def test_generated_page_is_self_contained() -> None:
    """No network, no CDN — the page must open cold from `file://`.

    A `<script src=…>` or `<link href=…>` pointing off the page is exactly
    what a strict, offline `file://` open cannot fetch: the labeller would
    see a broken page with no way to tell why.
    """
    page = build_page(STORE[:3], DIMENSIONS[:2])

    assert page.lstrip().startswith("<!doctype html>")
    assert re.search(r"<script[^>]*\bsrc=", page) is None
    assert re.search(r"<link[^>]*>", page) is None


def test_the_page_carries_no_cue_data_at_all() -> None:
    """D-2, closed by construction rather than by rule.

    `extraction_macro_f1` (T15) is measured against this corpus's labels, so a
    page that let a cue hit propose a dimension, a rung or a span would let the
    labeller rubber-stamp the extractor's own regexes as ground truth — the gate
    would then score the extractor against itself and pass regardless of merit.

    Earlier versions guarded this by keeping cue *values* out of an embedded cue
    list, which left the guard one careless edit from being undone. There is now
    no cue list: the payload carries no patterns, no values and no negatable
    flags, so no rendering path and no future change to the page can derive a
    mark from the extractor. The marks come from `suggestions.json`, whose
    provenance is recorded and whose overlap with the cues is measured.
    """
    page = build_page(STORE[:5], DIMENSIONS)
    embedded = _embedded_data(page)

    for dimension in embedded["dimensions"]:
        assert set(dimension) == {
            "id",
            "group",
            "label",
            "definition",
            "polarity",
            "kind",
            "levels",
        }, f"{dimension['id']} carries {sorted(dimension)}"

    blob = json.dumps(embedded)
    for leaked in ("cues", "negatable", "extraction"):
        assert leaked not in blob, f"the page payload carries {leaked!r}"

    # And no committed cue pattern appears verbatim. Restricted to patterns
    # carrying regex metacharacters: a bare-word cue like `promotion` occurs
    # naturally in a definition, so its absence would prove nothing and its
    # presence is not evidence of a leak. A pattern with `\\s+` or an
    # alternation in it cannot arrive by any route but a cue list.
    regexish = [
        (dimension.id, cue.pattern)
        for dimension in DIMENSIONS
        for cues in dimension.extraction.cues.values()
        for cue in cues
        if any(token in cue.pattern for token in ("\\\\", "|", "[", "?", "+", "("))
    ]
    assert regexish, "no regex-shaped cue to check against — this assertion has gone inert"
    for dimension_id, pattern in regexish:
        assert pattern not in page, f"{dimension_id}: cue pattern reached the page"


def test_the_page_explains_where_its_marks_come_from() -> None:
    """The reasoning has to reach the labeller, not just the commit log.

    A person confirming pre-marked spans needs to know the marks are not the
    extractor's own output, and that some ads are deliberately bare — otherwise
    an unmarked control ad reads as a bug and gets skipped.
    """
    page = build_page(STORE[:3], DIMENSIONS)

    assert "D-2" in page
    assert "suggestions.json" in page
    assert "control" in page.lower()
    assert "rubber-stamping" in page.lower()


def test_a_proposal_is_visibly_not_a_decision() -> None:
    """The whole speed-up rests on the labeller being able to tell at a glance
    what they decided from what was proposed to them, without reading a legend.
    """
    page = build_page(STORE[:1], DIMENSIONS[:1])

    assert "mark.ann.confirmed" in page, "confirmed marks must be styled apart from proposals"
    assert "dashed" in page
    assert "status: 'pending'" in page
    assert "a.status !== 'confirmed'" in page


def test_only_a_resolved_annotation_is_exported() -> None:
    """A proposal nobody acted on is not a label. The export path is where that
    is enforced, so it is read out of the shipped JS rather than restated here.
    """
    page = build_page(STORE[:1], DIMENSIONS[:1])

    body = page[page.index("function buildExport") : page.index("function note")]
    assert "if (a.status !== 'confirmed') { skipped++; continue; }" in body
    assert "const derived = sourceOf(a);" in body
    assert "source: derived," in body


def test_provenance_is_derived_from_the_proposal_not_stored_as_a_flag() -> None:
    """A stored flag is one the UI can set wrongly and nothing can catch. Deriving
    `confirmed` vs `edited` by comparing against the original proposal means the
    audit cannot be fooled by a page bug — only by editing the saved state by
    hand.
    """
    page = build_page(STORE[:1], DIMENSIONS[:1])

    body = page[page.index("function sourceOf") : page.index("function rungOf")]
    assert "if (!o) return 'human';" in body
    assert "unchanged ? 'confirmed' : 'edited'" in body


def test_the_page_widens_an_ambiguous_quote_instead_of_asking() -> None:
    """`import` refuses a quote appearing twice. The old page made the labeller
    "extend it until it is unique", which is work the text itself determines —
    so the page now widens the exported quote until it pins down, leaving the
    stored offsets alone.
    """
    page = build_page(STORE[:1], DIMENSIONS[:1])

    assert "function uniqueQuote" in page
    assert "quote: uniqueQuote(ad.text, a.start, a.end)" in page


def test_negation_stays_a_per_annotation_choice() -> None:
    """`negated` records a denial ("sense guàrdies"), not an absence — README."""
    page = build_page(STORE[:1], DIMENSIONS[:1])

    assert "a.negated = !a.negated" in page
    assert "'un-negate' : 'negate'" in page


def test_no_rung_is_offered_that_the_importer_would_refuse() -> None:
    """The page offers rungs; `import_labels` refuses anything that is not one.
    If the two ever disagree the labeller loses work already done, at submission
    time, with no way to recover the intended value.
    """
    embedded = _embedded_data(build_page(STORE[:1], DIMENSIONS))
    by_id = {dimension.id: dimension for dimension in DIMENSIONS}

    for payload in embedded["dimensions"]:
        for level in payload["levels"]:
            assert by_id[payload["id"]].level_for(level["value"]) is not None, (
                f"{payload['id']} offers rung {level['value']}, which import would refuse"
            )


def test_every_dimension_is_reachable_through_a_titled_section() -> None:
    """The picker exists so a labeller can find a dimension without already
    knowing its name. A dimension in no rendered section is unreachable except
    by search, which requires the name they do not have.
    """
    embedded = _embedded_data(build_page(STORE[:1], DIMENSIONS))
    sections = {group["id"] for group in embedded["groups"]}

    for dimension in embedded["dimensions"]:
        assert dimension["group"] in sections, f"{dimension['id']} is in no rendered section"
    for group in embedded["groups"]:
        assert group["title"], f"{group['id']} has no heading to render"


def test_a_mark_crosses_to_the_browser_as_a_quote_not_an_offset() -> None:
    """A Python offset counts code points; a JavaScript one counts UTF-16 units.

    The corpus is full of emoji outside the BMP — the Manfred ads open with 📢,
    and 🫵🏾 is two surrogate pairs on its own. Each one makes the JS index one
    unit larger than the Python index, so an offset computed here and used there
    slides every later span leftwards, citing words next to the evidence rather
    than the evidence. It looks plausible in the panel and is wrong in the
    corpus — the same failure `corpus/labelled/README.md` rules out for byte
    offsets, one encoding layer up.

    Observed before this was fixed: a `technical_depth` span on `manfred-8360`
    rendered as "so. Manejarás **cientos de miles de eventos por segun" instead
    of "Manejarás **cientos de miles de eventos por segundo**" — four units
    adrift by 2,300 characters in.
    """
    ad_record = next(a for a in STORE if a.id == "manfred-8360")
    quote = "Docker y Kubernetes"
    assert ad_record.text.count(quote) == 1

    suggestions = SuggestionSet.model_validate(
        {
            "method": "llm_read",
            "generated_at": "2026-08-19",
            "by_ad": {
                ad_record.id: [{"dimension": "stack_modernity", "value": 0.6, "quote": quote}]
            },
        }
    )
    embedded = _embedded_data(build_page([ad_record], DIMENSIONS, suggestions))
    (mark,) = embedded["suggestions"]["marks"][ad_record.id]

    assert mark["quote"] == quote
    assert "start" not in mark and "end" not in mark, (
        "a mark must not carry offsets across the language boundary"
    )

    # The hazard is real for this ad, not hypothetical — so the test cannot go
    # quietly inert if the corpus is ever re-fetched without emoji.
    before = ad_record.text[: ad_record.text.index(quote)]
    assert any(ord(ch) > 0xFFFF for ch in before), (
        "no astral character before the span — this regression test proves nothing here"
    )


def test_the_page_resolves_a_mark_in_its_own_index_space() -> None:
    """The other half of the fix, read out of the shipped JS: the browser locates
    the quote itself rather than trusting a number computed in Python."""
    page = build_page(STORE[:1], DIMENSIONS[:1])

    assert "const start = ad.text.indexOf(m.quote);" in page
    assert "if (start < 0) return [];" in page, "an unlocatable mark must be dropped, not placed"


def test_a_coined_dimension_records_the_ad_it_was_coined_at() -> None:
    """A dimension invented at ad 60 means ads 1-59 were read without it. Recording
    where it was coined is what lets those be swept for it, rather than assumed
    clean or re-read in full.
    """
    page = build_page(STORE[:1], DIMENSIONS[:1])

    assert "coined_at_ad: ADS[current].id" in page
    assert "proposed_dimensions" in page


# ── `harness import` ────────────────────────────────────────────────────────


def test_import_refuses_an_absent_quote(tmp_path: Path) -> None:
    """A quote not present verbatim in the ad is refused, exactly like `set`."""
    store_path = tmp_path / "store.jsonl"
    save_store([ad()], store_path)
    store = load_store(store_path)

    updated, results = import_labels(
        store, [row(quote="not in this ad anywhere")], known("on_call_load")
    )

    assert results[0]["status"] == "refused"
    assert "does not appear" in results[0]["reason"]
    assert updated == store, "nothing must be modified on a refusal"


def test_import_refuses_an_ambiguous_quote(tmp_path: Path) -> None:
    """A quote appearing more than once is refused, not silently placed on the first hit."""
    store = [ad(text="guardias, guardias, y mas guardias por la tarde")]

    updated, results = import_labels(store, [row(quote="guardias")], known("on_call_load"))

    assert results[0]["status"] == "refused"
    assert "more than once" in results[0]["reason"]
    assert updated == store


def test_import_applies_a_valid_batch(tmp_path: Path) -> None:
    """A clean batch is applied and reported per row."""
    store = [ad(ad_id="a", text="Ofrecemos guardias rotativas y viajes frecuentes.")]

    updated, results = import_labels(
        store,
        [
            row(ad_id="a", dimension="on_call_load", value=0.8, quote="guardias rotativas"),
            row(ad_id="a", dimension="travel_requirement", value=0.9, quote="viajes frecuentes"),
        ],
        known("on_call_load", "travel_requirement"),
    )

    assert all(r["status"] == "applied" for r in results)
    labels = {label.dimension: label for label in updated[0].labels}
    assert labels["on_call_load"].value == 0.8
    assert labels["travel_requirement"].spans[0].extract(updated[0].text) == "viajes frecuentes"


def test_import_is_idempotent(tmp_path: Path) -> None:
    """Re-importing the same batch must not duplicate labels."""
    store_path = tmp_path / "store.jsonl"
    save_store([ad(ad_id="a", text="Ofrecemos guardias rotativas cada mes.")], store_path)
    rows_path = tmp_path / "rows.json"
    rows_path.write_text(json.dumps([row(ad_id="a", quote="guardias rotativas")]), encoding="utf-8")

    assert main(["--store", str(store_path), "import", str(rows_path)]) == 0
    once = load_store(store_path)
    assert main(["--store", str(store_path), "import", str(rows_path)]) == 0
    twice = load_store(store_path)

    assert len(once[0].labels) == 1
    assert len(twice[0].labels) == 1
    assert once[0].labels[0] == twice[0].labels[0]


def test_import_writes_nothing_when_any_row_is_bad(tmp_path: Path) -> None:
    """Validate everything, then write, or write nothing — never half-apply.

    The batch here has one good row and one bad row; the good one must not
    land just because it happened to validate first.
    """
    store_path = tmp_path / "store.jsonl"
    save_store(
        [ad(ad_id="a", text="Ofrecemos guardias rotativas y viajes frecuentes por Europa.")],
        store_path,
    )
    rows_path = tmp_path / "rows.json"
    rows_path.write_text(
        json.dumps(
            [
                row(ad_id="a", dimension="on_call_load", quote="guardias rotativas"),
                row(ad_id="a", dimension="travel_requirement", quote="not present at all"),
            ]
        ),
        encoding="utf-8",
    )
    before = store_path.read_text(encoding="utf-8")

    code = main(["--store", str(store_path), "import", str(rows_path)])

    assert code == 2
    after = store_path.read_text(encoding="utf-8")
    assert after == before, "the file on disk must be byte-identical to before the attempt"


def test_import_refuses_an_unknown_dimension() -> None:
    """A misspelled dimension is refused, not silently accepted and dropped later."""
    store = [ad()]

    updated, results = import_labels(
        store, [row(dimension="sallary_transparency")], known("on_call_load")
    )

    assert results[0]["status"] == "refused"
    assert "unknown dimension" in results[0]["reason"]
    assert updated == store


def test_import_refuses_malformed_rows_without_a_traceback() -> None:
    """A row missing a required field, or an out-of-range value, is reported per row."""
    store = [ad()]

    updated, results = import_labels(
        store,
        [{"ad_id": "test-1", "dimension": "on_call_load", "value": 5.0, "quote": "guardias"}],
        known("on_call_load"),
    )

    assert results[0]["status"] == "refused"
    assert updated == store


def test_import_keeps_every_span_of_a_dimension_stated_twice() -> None:
    """One dimension evidenced in two places keeps both spans, not just the last.

    The first real export hit this: an ad that stated its pay twice, its English
    requirement twice and its experience floor twice. Each pair shares an
    (ad, dimension, round) key, and the apply pass used to rebuild the label
    from whichever row it saw last — so three of eleven hand-placed spans went
    into the store's bin while every row was still reported `applied`. Losing
    human labelling work silently is the one outcome this importer exists to
    prevent, so agreeing rows now merge into one label with both spans.
    """
    text = "Retribucion 3.085 euros al mes. Salario bruto anual 43.200 euros."
    store = [ad(ad_id="a", text=text)]

    updated, results = import_labels(
        store,
        [
            row(ad_id="a", dimension="compensation_transparency", value=0.9, quote="Retribucion"),
            row(
                ad_id="a",
                dimension="compensation_transparency",
                value=0.9,
                quote="Salario bruto anual",
            ),
        ],
        known("compensation_transparency"),
    )

    assert all(r["status"] == "applied" for r in results)
    assert len(updated[0].labels) == 1
    label = updated[0].labels[0]
    assert [span.extract(text) for span in label.spans] == ["Retribucion", "Salario bruto anual"]


def test_import_refuses_one_dimension_carrying_two_values_on_one_ad() -> None:
    """Rows that disagree on the value are two judgements, and neither is picked.

    Merging agreeing spans is safe because they argue the same thing. Rows that
    agree on the dimension and disagree on the rung do not: an ad naming an
    office and two days at home has one `remote_arrangement`, and choosing
    between them is the labeller's call, not the importer's. An earlier version
    let the last row win — the same silent discard of a human judgement as the
    dropped-span bug above, wearing a different hat — so the batch is refused
    with both rows named instead.
    """
    store = [ad(ad_id="a", text="Guardias rotativas los martes; sin guardias los jueves.")]

    updated, results = import_labels(
        store,
        [
            row(ad_id="a", value=0.8, quote="Guardias rotativas"),
            row(ad_id="a", value=0.0, quote="sin guardias"),
        ],
        known("on_call_load"),
    )

    assert all(r["status"] == "refused" for r in results)
    assert "disagree on value" in results[0]["reason"]
    assert updated == store


def test_import_merges_the_spans_of_the_first_real_export() -> None:
    """The export that exposed the bug, replayed: eleven spans in, eleven out."""
    text = (
        "Experiencia de 3 a 5 anys en el sector bancari. Angles (B2). "
        "Retribucio 3.085 euros. Experiencia 60 mesos. Salari mensual brut 3085 euros."
    )
    store = [ad(ad_id="a", text=text)]
    batch = [
        row(ad_id="a", dimension="seniority_expectation", value=0.5, quote="Experiencia de 3 a 5"),
        row(ad_id="a", dimension="english_demand", value=0.6, quote="Angles (B2)"),
        row(ad_id="a", dimension="compensation_transparency", value=0.9, quote="Retribucio 3.085"),
        row(ad_id="a", dimension="seniority_expectation", value=0.5, quote="Experiencia 60 mesos"),
        row(
            ad_id="a",
            dimension="compensation_transparency",
            value=0.9,
            quote="Salari mensual brut",
        ),
    ]

    updated, results = import_labels(
        store,
        batch,
        known("seniority_expectation", "english_demand", "compensation_transparency"),
    )

    assert all(r["status"] == "applied" for r in results)
    spans = sum(len(label.spans) for label in updated[0].labels)
    assert spans == len(batch), "every imported span must survive into the store"


def test_import_cli_refusal_reports_every_bad_row_and_exits_nonzero(tmp_path: Path) -> None:
    """The CLI shell surfaces `import_labels`'s per-row reasons, not a stack trace."""
    store_path = tmp_path / "store.jsonl"
    save_store([ad(ad_id="a")], store_path)
    rows_path = tmp_path / "rows.json"
    rows_path.write_text(json.dumps([row(ad_id="a", quote="absent text")]), encoding="utf-8")

    code = main(["--store", str(store_path), "import", str(rows_path)])

    assert code == 2


def test_import_cli_rejects_non_json_input(tmp_path: Path) -> None:
    """Malformed JSON is reported cleanly, not as a Python traceback."""
    store_path = tmp_path / "store.jsonl"
    save_store([ad(ad_id="a")], store_path)
    rows_path = tmp_path / "rows.json"
    rows_path.write_text("not json at all", encoding="utf-8")

    assert main(["--store", str(store_path), "import", str(rows_path)]) == 2


def test_import_cli_rejects_a_json_object_instead_of_an_array(tmp_path: Path) -> None:
    """The batch must be a JSON array of rows — a bare object is not one row."""
    store_path = tmp_path / "store.jsonl"
    save_store([ad(ad_id="a")], store_path)
    rows_path = tmp_path / "rows.json"
    rows_path.write_text(json.dumps(row(ad_id="a")), encoding="utf-8")

    assert main(["--store", str(store_path), "import", str(rows_path)]) == 2


def test_import_against_the_real_committed_corpus() -> None:
    """The batch path works over the real store and model, not only fixtures.

    Picks one real ad's real cue-matched gold span (the same mechanism
    `probe_labels` uses for T4's roundtrip gate) and imports it as a batch,
    proving `import_labels` and the real corpus agree on what a verbatim
    quote is.
    """
    dimension_with_gold = next(d for d in DIMENSIONS if d.extraction.gold)
    gold = dimension_with_gold.extraction.gold[0]
    by_id = {d.id: d for d in DIMENSIONS}

    updated, results = import_labels(
        list(STORE),
        [
            row(
                ad_id=gold.ad_id,
                dimension=dimension_with_gold.id,
                value=gold.value,
                quote=gold.span,
            )
        ],
        by_id,
    )

    assert results[0]["status"] == "applied", results[0]
    applied_ad = next(a for a in updated if a.id == gold.ad_id)
    label = next(
        label_ for label_ in applied_ad.labels if label_.dimension == dimension_with_gold.id
    )
    assert label.spans[0].extract(applied_ad.text) == gold.span


# ── shared plumbing between `set` and `import` ─────────────────────────────


def test_locate_quote_matches_sets_own_search_exactly() -> None:
    """`import` cannot drift from `set`'s notion of a valid quote — same function."""
    an_ad = ad(text="Trabajo remoto al 100% con guardias los fines de semana.")

    absent = locate_quote(an_ad, "not present")
    assert isinstance(absent, str) and "does not appear" in absent

    ambiguous = ad(text="hola hola hola")
    result = locate_quote(ambiguous, "hola")
    assert isinstance(result, str) and "more than once" in result

    clean = locate_quote(an_ad, "guardias")
    assert clean == (an_ad.text.index("guardias"), an_ad.text.index("guardias") + len("guardias"))


def test_split_shares_are_stable_input_for_the_page(tmp_path: Path) -> None:
    """A page built from a freshly-seeded store still carries a real split per ad.

    Guards against `build_page` silently depending on a field `build_store`
    does not actually populate.
    """
    seeded = build_store(
        [
            {
                "id": f"x-{i}",
                "language": "en",
                "text": f"role {i}",
                "source_url": "https://e.invalid",
            }
            for i in range(4)
        ]
    )

    page = build_page(seeded, DIMENSIONS[:1])
    embedded = _embedded_data(page)

    assert {a["split"] for a in embedded["ads"]} <= {"elicitation", "evaluation"}


# ── helpers ──────────────────────────────────────────────────────────────


def _embedded_data(page: str) -> dict[str, Any]:
    match = re.search(
        r'<script type="application/json" id="integral-data">(.*?)</script>', page, re.S
    )
    assert match, "page must embed its data as a json script block"
    # build_page escapes "</" to "<\/" so the JSON block cannot terminate early;
    # undo that before parsing, matching what the page's own JS does.
    parsed: dict[str, Any] = json.loads(match.group(1).replace("<\\/", "</"))
    return parsed


def test_import_accepts_the_pages_export_object(tmp_path: Path) -> None:
    """The page emits `{labels: [...]}` so it can also carry proposed dimensions.
    A bare array stays valid — that is a hand-written batch, and the older page.
    """
    store_path = tmp_path / "store.jsonl"
    save_store([ad(text="Ofrecemos guardias rotativas cada mes.")], store_path)
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"labels": [row(quote="guardias rotativas")]}), encoding="utf-8")

    code = main(["--store", str(store_path), "import", str(batch)])

    assert code == 0
    assert load_store(store_path)[0].labels[0].dimension == "on_call_load"


def test_import_does_not_write_a_coined_dimension_into_the_model(tmp_path: Path) -> None:
    """A dimension coined mid-read changes the model's spine, and every gate that
    counts dimensions reads it. That belongs in a reviewed diff, not in an import
    that is also writing to the corpus — so the labels apply and the proposal is
    reported for a separate, deliberate step.
    """
    store_path = tmp_path / "store.jsonl"
    save_store([ad(text="Ofrecemos guardias rotativas cada mes.")], store_path)
    batch = tmp_path / "batch.json"
    batch.write_text(
        json.dumps(
            {
                "labels": [row(quote="guardias rotativas")],
                "proposed_dimensions": [
                    {
                        "id": "childcare_support",
                        "label": "Childcare support",
                        "coined_at_ad": "test-1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    before = sorted(p.name for p in DEFAULT_DIMENSIONS_DIR.iterdir())

    code = main(["--store", str(store_path), "import", str(batch)])

    assert code == 0
    assert sorted(p.name for p in DEFAULT_DIMENSIONS_DIR.iterdir()) == before


def test_import_rejects_an_object_that_carries_no_labels(tmp_path: Path) -> None:
    store_path = tmp_path / "store.jsonl"
    save_store([ad()], store_path)
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"proposed_dimensions": []}), encoding="utf-8")

    assert main(["--store", str(store_path), "import", str(batch)]) == 2


def test_page_build_refuses_an_invalid_suggestion_set(tmp_path: Path) -> None:
    """The validator is the only thing checking a suggestion set means what it
    says. Building without it would let a contaminated set reach the labeller
    looking perfectly ordinary — and a labeller confirming a contaminated mark
    is the exact failure the suggestion design exists to prevent.
    """
    bad = tmp_path / "suggestions.json"
    bad.write_text(
        json.dumps(
            {
                "method": "llm_read",
                "generated_at": "2026-08-19",
                "blind_control": [],
                "by_ad": {
                    STORE[0].id: [
                        {"dimension": "on_call_load", "value": 0.65, "quote": "no such words"}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "label.html"

    code = page_main(["--out", str(out), "--suggestions", str(bad)])

    assert code == 2
    assert not out.exists(), "no page may be written from a set that failed validation"


def test_page_build_errors_on_a_suggestions_path_that_was_asked_for(tmp_path: Path) -> None:
    """A path the operator typed and that is not there is a mistake, not a
    request for blind mode — blind mode has its own flag."""
    out = tmp_path / "label.html"

    code = page_main(["--out", str(out), "--suggestions", str(tmp_path / "absent.json")])

    assert code == 2
    assert not out.exists()


def test_page_build_without_suggestions_still_works_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Blind mode is a real mode — the control ads use it, and it is the whole
    corpus until the suggestions exist. It must not be silent, though."""
    out = tmp_path / "label.html"

    code = page_main(["--out", str(out), "--no-suggestions"])

    assert code == 0
    assert out.exists()
    assert "blind" in capsys.readouterr().out.lower()


def test_an_annotation_carries_the_text_it_was_placed_on() -> None:
    """Offsets only mean something against the text they were taken from, and the
    saved state is keyed by ad id alone — so a page regenerated over a re-fetched
    corpus could mark and export whatever now sits at those positions, turning
    confirmed work into confidently wrong labels.
    """
    page = build_page(STORE[:1], DIMENSIONS[:1])

    body = page[page.index("function reconcile") : page.index("function sourceOf")]
    assert "ad.text.slice(a.start, a.end) === a.quote" in body, "drift must be detected"
    assert "const at = ad.text.indexOf(a.quote);" in body, "a moved span must be relocated"
    assert "drift[adId] = { relocated, lost };" in body, "the labeller must be told"


def test_work_from_the_previous_page_is_carried_over_not_stranded() -> None:
    """The old page saved under its own key. Reading only the new one would leave
    that work in the browser while the page looked empty, and the labeller could
    export a replacement corpus missing everything they had already done.
    """
    page = build_page(STORE[:1], DIMENSIONS[:1])

    assert "integral-t5-labels-v1" in page
    body = page[page.index("function migrateV1") : page.index("function save")]
    assert "status: 'pending'" in body, (
        "a migrated value may sit between two rungs, so it must be re-confirmed, "
        "not silently placed on the labeller's behalf"
    )


def test_reconcile_returns_the_live_array_when_nothing_drifted() -> None:
    """Caught in the browser: returning the rebuilt copy unconditionally handed
    every caller a detached array, so an annotation pushed onto it — every one
    the labeller creates — vanished on the next render. Only real drift may
    replace the stored array.
    """
    page = build_page(STORE[:1], DIMENSIONS[:1])

    body = page[page.index("function reconcile") : page.index("function sourceOf")]
    assert "if (!relocated && !lost) return anns;" in body


# ── banked labels: the corpus is the page's memory ───────────────────────────


def test_a_banked_label_reaches_the_page_as_a_confirmed_annotation() -> None:
    """A label already in the store arrives placed, not offered again.

    Without this the page is amnesiac. Every rebuild — a new suggestion set, a
    coined dimension, a fix to the page — handed back a corpus the labeller had
    already worked through, with their decisions surviving only in whatever
    `localStorage` the browser still held. The first real session ended exactly
    there: the page gone, the work in an export file the page could not read.
    """
    text = "Contracte laboral indefinit. Anglès B2 necessari."
    store = [
        ad(
            ad_id="a",
            text=text,
            labels=[
                Label(
                    dimension="contract_stability",
                    value=0.9,
                    spans=[Span(start=0, end=27)],
                    labeller="owner",
                    source="human",
                )
            ],
        )
    ]

    banked = banked_payload(store[0])

    assert banked == [
        {
            "dimension": "contract_stability",
            "value": 0.9,
            "quote": "Contracte laboral indefinit",
            "nth": 0,
            "negated": False,
            "source": "human",
            "labeller": "owner",
            "round": 1,
        }
    ]
    assert "Contracte laboral indefinit" in build_page(store, DIMENSIONS)


def test_a_banked_span_of_a_repeated_phrase_keeps_its_own_position() -> None:
    """`nth` is what stops a repeated quote collapsing onto the first match.

    Offsets cannot cross into the browser — a Python index counts code points
    and a JavaScript one counts UTF-16 units — so the span travels as a quote.
    A quote alone is ambiguous whenever the ad says the same thing twice, and
    resolving it by `indexOf` would silently re-point the label at a sentence
    the labeller never marked.
    """
    text = "Se ofrecen guardias. El equipo comparte guardias cada mes."
    second = text.index("guardias", text.index("guardias") + 1)
    store = [
        ad(
            ad_id="a",
            text=text,
            labels=[
                Label(
                    dimension="on_call_load",
                    value=0.8,
                    spans=[Span(start=second, end=second + len("guardias"))],
                    labeller="owner",
                )
            ],
        )
    ]

    banked = banked_payload(store[0])

    assert banked[0]["nth"] == 1
    # What the page's `nthIndexOf` does, in Python: the (nth+1)th occurrence.
    at = -1
    for _ in range(banked[0]["nth"] + 1):
        at = text.index(banked[0]["quote"], at + 1)
    assert at == second


def test_every_banked_span_in_the_committed_corpus_resolves_to_itself() -> None:
    """The round trip, over the real store: quote plus `nth` lands back exactly.

    The corpus is the durable memory now, so a span that resolves anywhere but
    where it was placed is a label pointing at words nobody judged.
    """
    checked = 0
    for stored in STORE:
        for entry in banked_payload(stored):
            at = -1
            for _ in range(entry["nth"] + 1):
                at = stored.text.index(entry["quote"], at + 1)
            assert stored.text[at : at + len(entry["quote"])] == entry["quote"]
            checked += 1
    assert checked, "no labels banked yet — this test would pass over nothing"


def test_a_banked_span_keeps_the_round_it_was_labelled_in() -> None:
    """`labeller` and `round` ride along, because the export rebuilds every row.

    The page stamps its two header inputs onto every exported label. A banked
    round-1 label re-exported from a page set to round 2 would come back as a
    round-2 row — and `import_labels` replaces by `(ad, dimension, round)`, so
    it would land as a *duplicate* in round 2 while round 1 sat untouched. That
    silently corrupts `harness agreement`, which is a comparison between rounds
    and means nothing once one round holds the other's labels.
    """
    text = "Contracte laboral indefinit. Anglès B2 necessari."
    store = [
        ad(
            ad_id="a",
            text=text,
            labels=[
                Label(
                    dimension="contract_stability",
                    value=0.9,
                    spans=[Span(start=0, end=27)],
                    labeller="someone-else",
                    round=2,
                    source="confirmed",
                )
            ],
        )
    ]

    banked = banked_payload(store[0])

    assert banked[0]["labeller"] == "someone-else"
    assert banked[0]["round"] == 2
    assert banked[0]["source"] == "confirmed"
