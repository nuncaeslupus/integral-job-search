"""T17 — `ontology_hit_rate` counts what the ontology does not cover.

The metric is `mapped ÷ (mapped + unmapped)` over the concepts an advert-reading
pass actually stated (`docs/METHODS.md`). Its whole value is the numerator's
complement: an extractor that silently discards what it cannot classify destroys
the project's only automatic warning that the market moved
(`status/specification.md` §5.3).

So the property under test is not the ratio — it is that nothing vanishes on the
way to the ratio. `concepts_read` is counted from the source's own entries; the
buckets are counted from the classifier. A reader that filters out what it cannot
name makes the two disagree, and `discarded_concepts` goes non-zero.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from integral.ontology_health import (
    OntologyHealthError,
    measure,
    read_suggestions,
    tally,
)

_KNOWN = {"pay_transparency", "team_autonomy"}


def _suggestions(entries: dict[str, list[dict[str, Any]]], **extra: Any) -> dict[str, Any]:
    return {"method": "llm_read", "by_ad": entries, **extra}


def _write(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "suggestions.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _map(tmp_path: Path, body: str = "") -> Path:
    """A concept map beside the fixture, so the committed one is never read here."""
    path = tmp_path / "concept_map.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_unmapped_concepts_are_counted_not_discarded(tmp_path: Path) -> None:
    """A concept outside the model raises `unmapped` and lowers the hit rate."""
    source = read_suggestions(
        _write(
            tmp_path,
            _suggestions(
                {
                    "ad-1": [
                        {"dimension": "pay_transparency", "quote": "22.000€ bruts"},
                        {"dimension": "team_autonomy", "quote": "you own the roadmap"},
                        # Named, but no dimension covers it.
                        {"dimension": "four_day_week", "quote": "jornada de 4 dies"},
                        # Found and unnameable — the reader had nowhere to put it.
                        {"quote": "equity refresh"},
                    ]
                },
                unmapped=[],
            ),
        ),
        _KNOWN,
        _map(tmp_path),
    )

    assert source.concepts_read == 4
    assert source.mapped == ["pay_transparency", "team_autonomy"]
    assert source.unmapped == ["equity refresh", "four_day_week"]

    counted = tally([source])
    assert counted["discarded_concepts"] == 0
    assert counted["ontology_hit_rate"] == 0.5
    assert counted["ontology_status"] == "measured"


def test_a_source_that_cannot_report_unmapped_concepts_leaves_the_rate_unmeasured(
    tmp_path: Path,
) -> None:
    """1.0 out of a pass handed the dimension list measures the pass, not the market."""
    source = read_suggestions(
        _write(tmp_path, _suggestions({"ad-1": [{"dimension": "team_autonomy", "quote": "x"}]})),
        _KNOWN,
        _map(tmp_path),
    )

    assert source.unmapped_capable is False
    counted = tally([source])
    assert counted["ontology_hit_rate"] is None
    assert counted["ontology_status"] == "unmeasured"
    assert counted["mapped_concepts"] == 1


def _mapped_source(tmp_path: Path, concept_map: str) -> Any:
    """One advert, one concept the read pass could not place, one map to try on it."""
    return read_suggestions(
        _write(
            tmp_path,
            _suggestions(
                {
                    "ad-1": [
                        {
                            "quote": "Imprescindible carnet de conducir",
                            "note": "driving licence required — a condition on the person",
                        }
                    ]
                },
                unmapped=["driving licence required"],
            ),
        ),
        _KNOWN | {"commute_burden"},
        _map(tmp_path, concept_map),
    )


def test_a_concept_the_map_places_on_a_real_dimension_counts_as_mapped(tmp_path: Path) -> None:
    """Widening the model is the only thing that may move a concept between buckets.

    The read pass left this entry unmapped because nothing in the model could hold
    it. A dimension now exists, so the concept is covered — and the count of what
    was read is untouched, which is what separates widening from discarding.
    """
    source = _mapped_source(
        tmp_path,
        'concepts:\n  commute_burden:\n    - "driving licence required"\n',
    )

    assert source.concepts_read == 1
    assert source.mapped == ["commute_burden"]
    assert source.unmapped == []
    assert tally([source])["discarded_concepts"] == 0


def test_a_map_naming_a_dimension_the_model_lacks_is_refused(tmp_path: Path) -> None:
    """Otherwise the rate rises by inventing a question the model never asks."""
    with pytest.raises(OntologyHealthError, match="not a dimension the model declares"):
        _mapped_source(
            tmp_path,
            'concepts:\n  four_day_week:\n    - "driving licence required"\n',
        )


def test_a_map_naming_a_concept_the_source_never_stated_is_refused(tmp_path: Path) -> None:
    """The other half of the same guard: coverage of something nobody read.

    A map free to invent concept names could pad the numerator with entries no
    advert produced. Every name must be one the source itself declares under its
    top-level `unmapped` key.
    """
    with pytest.raises(OntologyHealthError, match="not a concept the source declares"):
        _mapped_source(
            tmp_path,
            'concepts:\n  commute_burden:\n    - "free artisanal coffee"\n',
        )


def test_no_language_falls_below_the_gate() -> None:
    """ES, EN and CA are one product, so the aggregate may not hide one of them.

    A model widened only where the English adverts complain would clear 0.85 on
    the total while covering a Catalan care advert no better than before. The
    per-language split is recorded in the evidence for that reason, and this is
    what makes it a requirement rather than a note.
    """
    by_language = measure()["ontology_hit_rate_by_language"]

    assert set(by_language) == {"ca", "en", "es"}
    assert all(rate >= 0.85 for rate in by_language.values()), by_language


def test_the_committed_corpus_is_read_and_nothing_is_dropped() -> None:
    """The gate's own number, over the real files rather than a fixture.

    The corpus read pass now declares the `unmapped` capability, so the rate is
    **measured** rather than refused (T57). What this test still owns is the
    invariant underneath it: `discarded_concepts == 0`, meaning every concept the
    pass stated ended up in exactly one bucket. A reader that quietly filtered out
    what it could not name would raise the rate while breaking this line, which is
    why the drop is the gate and the ratio is only the reading.
    """
    measured = measure()
    assert measured["concepts_read"] > 0
    assert measured["discarded_concepts"] == 0
    assert measured["ontology_status"] == "measured"
    assert 0.0 < measured["ontology_hit_rate"] < 1.0
    # Not 1.0 by construction, which is the whole of T57: a pass briefed from the
    # dimension list alone reports every concept mapped, and that number measures
    # the briefing. A non-zero unmapped count is what makes the rate a reading of
    # the market rather than of how the reader was asked to look.
    assert measured["unmapped_concepts"] > 0
