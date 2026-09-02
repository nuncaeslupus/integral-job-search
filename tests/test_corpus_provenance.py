"""T98 — a corpus row must be traceable to a draw, and a draw is a specification.

The owner's ruling has two halves. No candidate is ever served from stored adverts,
which `tests/test_corpus_scope.py` asserts over the serving-path code. And the corpus
must not be *built* from one candidate's harvest either: ~2,755 rows drawn against one
person's profile are the shape of that person's queries and exclusions, and an accuracy
measured on them would be quoted as accuracy for everyone.

The second half is what this file measures. It is only enforceable if a row can prove
where it came from, so every row names a draw declared in `corpus/draws.yaml`, and the
draw's stated query shape has to actually account for the row. The last part is the one
with teeth: a harvested row can be relabelled `draw: t4b-programming` in a second, but
it cannot as easily come from a source, language and job family that draw asked for.

Every fixture below is constructed. No advert a candidate was reading enters this
repository — the set of ads a person opens carries their field, level, city and the fact
that they are looking, and a fixture in a public repository carries that forever.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from integral.corpus import load_ads
from integral.corpus_scope import (
    DEFAULT_DRAWS,
    MINIMUM_CORPUS_ROWS,
    draw_queries,
    draw_selects,
    load_draws,
    measure_provenance,
    provenance_faults,
)

# A registry with the same shape as the committed one, small enough to reason about.
_DRAWS = """
draws:
  - id: es-programming
    drawn_at: "2026-01-01"
    purpose: Spanish-language programming adverts, for extraction scoring.
    languages: [es]
    job_families: [programming]
    sources: [exampleboard]
  - id: ca-trades
    drawn_at: "2026-01-02"
    purpose: Catalan trades adverts, for vocabulary breadth.
    languages: [ca]
    job_families: [trades]
    sources: [exampleboard]
"""


def _row(row_id: str, **overrides: Any) -> dict[str, Any]:
    """A well-formed corpus row. Invented wholesale — no real advert, no real person."""
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
        "text": "Buscamos una persona para trabajar en Python. " * 20,
    }
    row.update(overrides)
    return row


def _corpus(tmp_path: Path, rows: list[dict[str, Any]], name: str = "ads.jsonl") -> Path:
    path = tmp_path / name
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )
    return path


def _registry(tmp_path: Path, document: str = _DRAWS) -> Path:
    path = tmp_path / "draws.yaml"
    path.write_text(document, encoding="utf-8")
    return path


def _faults(tmp_path: Path, rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Faults over a raw corpus whose labelled store mirrors it exactly, so anything
    reported is a fault of the raw rows and not of the pairing."""
    raw = _corpus(tmp_path, rows)
    labelled = _corpus(tmp_path, rows, "labelled.jsonl")
    found, _ = provenance_faults(raw, labelled, _registry(tmp_path))
    return found


# --------------------------------------------------------------------------------
# test_every_corpus_row_records_the_draw_that_produced_it


def test_every_corpus_row_records_the_draw_that_produced_it() -> None:
    """The committed corpus, as it stands: every row names a declared draw whose
    specification still asks for it, and every labelled row has a raw row behind it."""
    faults, examined = provenance_faults()
    assert faults == []
    assert examined >= MINIMUM_CORPUS_ROWS, examined


def test_the_committed_gate_is_measured_not_vacuous() -> None:
    """`corpus_rows_without_a_draw_specification == 0` is only worth reading if the scan
    that produced it covered something. The floors are inside the evidence for exactly
    that reason."""
    measured = measure_provenance()
    assert measured["gate_status"] == "measured", measured.get("unmeasured_reason")
    assert measured["corpus_rows_without_a_draw_specification"] == 0, measured["faults"]
    assert measured["declared_draws"]


def test_a_row_naming_no_draw_is_a_fault(tmp_path: Path) -> None:
    """The base case, and the one a session harvest produces by default: adverts saved
    from a search have nothing to name."""
    rows = [_row("good"), _row("orphan", draw="")]
    faults = _faults(tmp_path, rows)
    assert [f["row"] for f in faults] == ["orphan"]
    assert "names no draw" in faults[0]["reason"]


def test_a_row_naming_an_undeclared_draw_is_a_fault(tmp_path: Path) -> None:
    """A `draw:` value is not provenance unless something declares it. An id invented at
    write time reads exactly like a real one until the registry is consulted."""
    faults = _faults(tmp_path, [_row("invented", draw="live-session-2026-09")])
    assert [f["row"] for f in faults] == ["invented"]
    assert "does not declare" in faults[0]["reason"]


def test_an_empty_corpus_reports_unmeasured_rather_than_a_clean_zero(tmp_path: Path) -> None:
    """Zero faults over zero rows is the failure mode the floor exists for: the number
    the gate reads would be perfect and would mean nothing."""
    measured = measure_provenance(
        raw_path=_corpus(tmp_path, [_row("only")]),
        labelled_path=_corpus(tmp_path, [_row("only")], "labelled.jsonl"),
        draws_path=_registry(tmp_path),
    )
    assert measured["corpus_rows_without_a_draw_specification"] == 0
    assert measured["gate_status"] == "unmeasured"
    assert "below the" in measured["unmeasured_reason"]


def test_a_labelled_row_with_no_raw_row_behind_it_is_a_fault(tmp_path: Path) -> None:
    """The labelled store carries no draw of its own because it is seeded from the raw
    corpus. That makes it the back door: a row dropped straight into it would otherwise
    be provenance-free and unexamined."""
    raw = _corpus(tmp_path, [_row("known")])
    labelled = _corpus(tmp_path, [_row("known"), _row("smuggled")], "labelled.jsonl")
    faults, _ = provenance_faults(raw, labelled, _registry(tmp_path))
    assert [(f["where"], f["row"]) for f in faults] == [("labelled", "smuggled")]


# --------------------------------------------------------------------------------
# test_a_row_harvested_for_one_candidate_is_refused


def test_a_row_harvested_for_one_candidate_is_refused(tmp_path: Path) -> None:
    """Provenance is a filter, not a comment.

    A harvest row written down honestly says who it was fetched for, and that is exactly
    why it is refused — the sample is one person's queries. `load_ads` raises rather than
    skipping: a filter that silently drops a row is indistinguishable from one that
    stopped running.
    """
    path = _corpus(tmp_path, [_row("harvested", candidate_id="cand-0001")])
    with pytest.raises(ValueError, match="bound to a candidate"):
        load_ads(path)


@pytest.mark.parametrize(
    "key", ["candidate", "drawn_for", "for_candidate", "profile_id", "search_id", "session_id"]
)
def test_every_candidate_bound_key_is_refused_at_load(tmp_path: Path, key: str) -> None:
    """One spelling caught and five waved through is a fail-open filter. A harvest names
    its person under whichever of these the writing code happened to use."""
    path = _corpus(tmp_path, [_row("harvested", **{key: "whoever"})])
    with pytest.raises(ValueError, match="bound to a candidate"):
        load_ads(path)


def test_a_row_with_no_draw_is_refused_at_load_too(tmp_path: Path) -> None:
    """The unadorned harvest: adverts saved from a session, carrying no claim at all."""
    row = _row("harvested")
    del row["draw"]
    with pytest.raises(ValueError, match="names no draw"):
        load_ads(_corpus(tmp_path, [row]))


def test_a_harvested_row_is_not_laundered_by_copying_a_real_draws_label(tmp_path: Path) -> None:
    """The one that matters, because it is the one a filter checking only the *presence*
    of a draw would pass.

    Relabelling a harvested row costs nothing. Coming from a source, language and job
    family the draw actually asked for does not: a person's search returns whatever the
    market had for that person. Here the label is real and the row is a Catalan trades
    advert, which `es-programming` never asked for.
    """
    laundered = _row("laundered", language="ca", job_family="trades", draw="es-programming")
    faults = _faults(tmp_path, [_row("genuine"), laundered])
    assert [f["row"] for f in faults] == ["laundered"]
    assert "does not ask for" in faults[0]["reason"]


def test_a_draw_specification_may_not_name_a_candidate(tmp_path: Path) -> None:
    """The registry is subject to its own rule. A draw that can only be stated by naming
    a person is a search with a specification's filename."""
    registry = _registry(
        tmp_path,
        "draws:\n"
        "  - id: whoever-2026\n"
        '    drawn_at: "2026-01-01"\n'
        "    purpose: What one person was looking for.\n"
        "    languages: [es]\n"
        "    job_families: [programming]\n"
        "    sources: [exampleboard]\n"
        "    drawn_for: cand-0001\n",
    )
    with pytest.raises(ValueError, match="bound to a candidate"):
        load_draws(registry)


@pytest.mark.parametrize("field", ["drawn_at", "purpose", "languages", "job_families", "sources"])
def test_a_draw_missing_any_axis_is_refused(tmp_path: Path, field: str) -> None:
    """An incomplete specification cannot be re-issued, so it accounts for nothing — and
    a row naming it would otherwise read as accounted for."""
    document = {
        "id": "partial",
        "drawn_at": "2026-01-01",
        "purpose": "Something.",
        "languages": "[es]",
        "job_families": "[programming]",
        "sources": "[exampleboard]",
    }
    del document[field]
    body = "".join(f"    {key}: {value}\n" for key, value in document.items() if key != "id")
    with pytest.raises(ValueError, match=f"declares no {field}"):
        load_draws(_registry(tmp_path, f"draws:\n  - id: partial\n{body}"))


# --------------------------------------------------------------------------------
# test_a_draw_is_reproducible_from_its_specification


def test_a_draw_is_reproducible_from_its_specification() -> None:
    """A draw is a stated query shape, and that is what separates it from a harvest.

    Two things are asserted. The specification expands to the same work every time —
    otherwise "redraw it" means nothing. And applying that expansion to the committed
    corpus recovers *exactly* the rows claiming the draw, which is what makes the
    specification the account of the corpus rather than a caption beside it.
    """
    draws = load_draws()
    assert draws, DEFAULT_DRAWS

    rows = [json.loads(line) for line in _committed_raw_lines()]
    for identifier, spec in draws.items():
        assert draw_queries(spec) == draw_queries(spec)
        assert draw_queries(spec), identifier

        claimed = {str(row["id"]) for row in rows if row.get("draw") == identifier}
        selected = {str(row["id"]) for row in rows if draw_selects(spec, row)}
        assert claimed == selected, identifier
        assert claimed, identifier


def test_a_specification_expands_to_every_axis_combination(tmp_path: Path) -> None:
    """The expansion is the cross product of the three axes, sorted — derived from the
    specification alone, with nothing carried over from the run that produced it."""
    spec = load_draws(_registry(tmp_path))["es-programming"]
    assert draw_queries(spec) == [("exampleboard", "es", "programming")]

    wider = dict(spec, languages=["es", "ca"], sources=["b", "a"])
    assert draw_queries(wider) == [
        ("a", "ca", "programming"),
        ("a", "es", "programming"),
        ("b", "ca", "programming"),
        ("b", "es", "programming"),
    ]


def _committed_raw_lines() -> list[str]:
    from integral.corpus_scope import DEFAULT_RAW_ADS

    return [line for line in DEFAULT_RAW_ADS.read_text(encoding="utf-8").splitlines() if line]
