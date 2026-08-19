"""T5's labelling aid — the generated page and `harness import`.

T5 (`claude-arsenal/queue/lo-d2b2.md`) is `[HUMAN]`: nothing here tests the
labels themselves, because no labels are placed by code. What is tested is the
tooling that makes the person's 300+ label-and-quote decisions fast and
mechanically safe:

* `tools/labelling_page.py` renders every ad and every matched dimension into
  one `file://`-openable page, with the corpus's own text as the only source
  of a "quote" a selection can ever produce.
* `jobsearch.harness.import_labels` (and its CLI shell, `harness import`)
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

from jobsearch.dimensions import Dimension, load_dimensions
from jobsearch.harness import (
    DEFAULT_STORE_PATH,
    Label,
    LabelledAd,
    build_store,
    import_labels,
    load_store,
    locate_quote,
    main,
    save_store,
)


def _load_labelling_page() -> object:
    """Import `tools/labelling_page.py` without `tools/` being on `sys.path`.

    `tools/` is repo automation, not a package under `src/` — `pyproject.toml`
    only puts `src` on `pythonpath` (`[tool.pytest.ini_options]`), and adding
    `tools` there is out of scope for this task's file list. Loading the
    module by its file path keeps the test self-sufficient instead of
    depending on a config change shipped elsewhere.
    """
    path = Path(__file__).resolve().parents[1] / "tools" / "labelling_page.py"
    spec = importlib.util.spec_from_file_location("labelling_page", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build_page = _load_labelling_page().build_page  # type: ignore[attr-defined]

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
        assert dimension.label.es in page, f"{dimension.id}'s Spanish label missing"
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


def test_generated_page_carries_the_cue_contamination_warning() -> None:
    """The page must say, in its own UI, that highlights are not labels.

    `corpus/labelled/README.md` and D-2 explain why in prose a labeller never
    reads; the page's own notice is what actually reaches them.
    """
    page = build_page(STORE[:3], DIMENSIONS)

    assert "navigation" in page.lower()
    assert "D-2" in page or "cue-derived" in page.lower() or "independent" in page.lower()


def test_ambiguous_quote_selection_is_detected_client_side() -> None:
    """The page must warn about a repeated selection before it is ever exported.

    `set` and `import` both refuse an ambiguous quote server-side; the page's
    own `countOccurrences` logic is what lets the person catch it while
    looking at the ad, instead of on the next `harness import` run. This test
    reads the *shipped* JS text — not a reimplementation of it — so a change
    that silently deletes the check would fail here.
    """
    page = build_page(STORE[:1], DIMENSIONS[:1])

    assert "extend the selection" in page
    assert "countOccurrences" in page


def test_negated_toggle_is_present_per_dimension() -> None:
    """`negated` records a denial ("sense guàrdies"), not an absence — README.

    The page must offer this as a real per-label choice, not only accept it
    from `harness import`.
    """
    page = build_page(STORE[:1], DIMENSIONS[:1])

    assert 'class="negated-input"' in page
    assert "denies" in page.lower()


def test_cue_highlight_never_prefills_a_value() -> None:
    """D-2: cue-derived gold is not independent of the model it checks.

    `extraction_macro_f1` (T15) is measured against this corpus's labels, so
    a page that let a cue hit set a value, pick a dimension, or fill a quote
    would let the labeller rubber-stamp the extractor's own regex as ground
    truth — the gate would then check the model against itself. This is
    verified two ways, both mechanical rather than a reading of intent:

    1. the JSON payload the page embeds carries a cue's `pattern` and
       `negatable` only — never its `value` (`Cue.value` exists in the
       dimension schema and is deliberately dropped when building the page);
       there is no number in the page's data for a prefill to come from.
    2. the only call site of the highlighting function (`cueMatches`) is
       inside `renderAdText`, and nothing in that function's body calls
       `touch(` — the one function that writes into the labeller's saved
       state. A cue match therefore cannot reach `localStorage` no matter
       what the labeller does.
    """
    page = build_page(STORE[:5], DIMENSIONS)
    embedded = _embedded_data(page)

    for dimension in embedded["dimensions"]:
        for cues in dimension["cues"].values():
            for cue in cues:
                assert set(cue.keys()) == {"pattern", "negatable"}, (
                    f"{dimension['id']}: cue payload carries {sorted(cue.keys())}, "
                    "which includes something beyond pattern/negatable a prefill could use"
                )

    start = page.index("function renderAdText")
    end = page.index("\n  function ", start + 1)
    render_ad_text_body = page[start:end]
    assert "cueMatches(ad)" in render_ad_text_body, (
        "renderAdText must be the one caller of cueMatches"
    )
    # Exactly two mentions of the identifier: its own `function cueMatches(ad) {`
    # definition, and the single call inside renderAdText asserted above — so
    # nothing else in the page can be a second call site.
    assert page.count("cueMatches") == 2, "cueMatches must be defined once and called once"
    assert "touch(" not in render_ad_text_body, (
        "cue highlighting must never write into the labeller's saved state"
    )


def test_value_input_carries_no_static_default() -> None:
    """The value `<input>` template must ship with no `value="…"` attribute.

    Belt-and-braces alongside `test_cue_highlight_never_prefills_a_value`: even
    a page with an empty `DATA.ads`/`DATA.dimensions` payload must not bake a
    number into the control itself.
    """
    page = build_page([], [])

    assert re.search(r'class="val-input"[^>]*\bvalue=', page) is None


def test_emitted_quote_is_a_real_substring_of_the_ad_text() -> None:
    """The page's data contract: `text` reaches the browser unmodified.

    The page can only ever emit a quote by reading `window.getSelection()`
    inside the rendered ad text; that guarantee is worth nothing if the text
    the page embeds is not byte-for-byte what `harness` will later search
    against. Driven with a real, accented Catalan ad — the case most likely
    to be mangled by an encoding step the page's data pipeline might add.
    """
    catalan_ads = [a for a in STORE if a.language == "ca"]
    assert catalan_ads, "fixture assumption: the committed corpus has Catalan ads"
    target = next(a for a in catalan_ads if any(ch in a.text for ch in "àèéíòóúïüç"))

    page = build_page([target], DIMENSIONS)
    embedded = _embedded_data(page)
    embedded_ad = next(a for a in embedded["ads"] if a["id"] == target.id)

    assert embedded_ad["text"] == target.text, "ad text must reach the page unmodified"

    # Simulate what a real selection would hand back: a literal slice of the
    # embedded text, taken across an accented word.
    accent_index = next(i for i, ch in enumerate(target.text) if ch in "àèéíòóúïüç")
    quote = target.text[max(0, accent_index - 3) : accent_index + 4]
    assert quote in embedded_ad["text"]

    located = locate_quote(target, quote)
    assert not isinstance(located, str), f"a real substring must locate cleanly: {located}"


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
    rows_path.write_text(
        json.dumps([row(ad_id="a", quote="guardias rotativas")]), encoding="utf-8"
    )

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


def test_import_last_row_wins_within_one_batch() -> None:
    """Two rows targeting the same (ad, dimension, round) — the later one applies.

    Matches `set`'s overwrite-in-place semantics, so importing a corrected
    export twice in a row (an earlier draft, then a fixed one, pasted as one
    file) behaves the same as running `set` twice would.
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

    assert all(r["status"] == "applied" for r in results)
    assert len(updated[0].labels) == 1
    assert updated[0].labels[0].value == 0.0


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
            {"id": f"x-{i}", "language": "en", "text": f"role {i}", "source_url": "https://e.invalid"}
            for i in range(4)
        ]
    )

    page = build_page(seeded, DIMENSIONS[:1])
    embedded = _embedded_data(page)

    assert {a["split"] for a in embedded["ads"]} <= {"elicitation", "evaluation"}


# ── helpers ──────────────────────────────────────────────────────────────


def _embedded_data(page: str) -> dict[str, list[dict[str, Any]]]:
    match = re.search(
        r'<script type="application/json" id="jobsearch-data">(.*?)</script>', page, re.S
    )
    assert match, "page must embed its data as a json script block"
    # build_page escapes "</" to "<\/" so the JSON block cannot terminate early;
    # undo that before parsing, matching what the page's own JS does.
    parsed: dict[str, list[dict[str, Any]]] = json.loads(match.group(1).replace("<\\/", "</"))
    return parsed
