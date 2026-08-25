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

from integral.ontology_health import measure, read_suggestions, tally

_KNOWN = {"pay_transparency", "team_autonomy"}


def _suggestions(entries: dict[str, list[dict[str, Any]]], **extra: Any) -> dict[str, Any]:
    return {"method": "llm_read", "by_ad": entries, **extra}


def _write(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "suggestions.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
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
    )

    assert source.unmapped_capable is False
    counted = tally([source])
    assert counted["ontology_hit_rate"] is None
    assert counted["ontology_status"] == "unmeasured"
    assert counted["mapped_concepts"] == 1


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
