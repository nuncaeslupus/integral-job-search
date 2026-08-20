"""Which labels a human actually judged, and the rung vocabulary they judged in.

Pre-marking an ad makes labelling fast and makes one new mistake possible: a
suggestion nobody read can end up in the corpus looking exactly like a decision.
`Label.source` is what stops that being a matter of discipline. There is no
`"suggested"` member — every value means a person made a judgement — so a
suggestion that was never acted on has no shape it could take in the store.

The rung check is the other half. A value that is not one of the dimension's
declared levels has no class for `extraction_macro_f1` to score against, so both
write paths — `import` and `set` — refuse it rather than storing a number that
would have to be silently binned later.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from integral.dimensions import load_dimensions
from integral.harness import (
    Label,
    LabelledAd,
    Span,
    import_labels,
    load_store,
    save_store,
)

DIMENSIONS = {dimension.id: dimension for dimension in load_dimensions()}


def ad(ad_id: str = "test-1", text: str = "Ofrecemos guardias rotativas cada mes.") -> LabelledAd:
    return LabelledAd(
        id=ad_id,
        language="es",
        text=text,
        source_url="https://example.invalid/1",
        split="evaluation",
        labels=[],
    )


def row(**overrides: object) -> dict[str, object]:
    return {
        "ad_id": "test-1",
        "dimension": "on_call_load",
        "value": 0.8,
        "quote": "guardias rotativas",
        **overrides,
    }


# --- provenance --------------------------------------------------------------


def test_a_label_is_human_unless_it_says_otherwise() -> None:
    """The safe default. A caller that forgets to say how a label was reached
    claims the strongest provenance, so an omission cannot quietly downgrade a
    real decision into something the audit would discount."""
    label = Label(dimension="on_call_load", value=0.8, spans=[Span(start=0, end=4)], labeller="o")
    assert label.source == "human"


@pytest.mark.parametrize("source", ["human", "confirmed", "edited"])
def test_import_carries_the_provenance_through(source: str) -> None:
    updated, results = import_labels([ad()], [row(source=source)], DIMENSIONS)

    assert results[0]["status"] == "applied"
    assert updated[0].labels[0].source == source


def test_there_is_no_provenance_for_a_suggestion_nobody_read() -> None:
    """An unconfirmed suggestion is not a label and must have no way to become
    one. If `"suggested"` were a member, an exporter bug would be enough to file
    machine output as corpus ground truth."""
    with pytest.raises(ValidationError):
        Label(
            dimension="on_call_load",
            value=0.8,
            spans=[Span(start=0, end=4)],
            labeller="o",
            # mypy rejecting this line is half the proof: the vocabulary is
            # closed at type-check time as well as at validation time.
            source="suggested",  # type: ignore[arg-type]
        )

    # The runtime half: `import` takes untyped JSON, where mypy cannot reach.
    _updated, results = import_labels([ad()], [row(source="suggested")], DIMENSIONS)
    assert results[0]["status"] == "refused"


def test_provenance_survives_a_write_and_read_cycle(tmp_path: Path) -> None:
    """The audit reads the committed store, not a live object graph."""
    store_path = tmp_path / "store.jsonl"
    updated, _results = import_labels([ad()], [row(source="confirmed")], DIMENSIONS)
    save_store(updated, store_path)

    assert load_store(store_path)[0].labels[0].source == "confirmed"


# --- the rung vocabulary -----------------------------------------------------


def test_import_refuses_a_value_that_is_not_a_declared_rung() -> None:
    """0.65 is a plausible-looking number with no class behind it."""
    updated, results = import_labels([ad()], [row(value=0.65)], DIMENSIONS)

    assert results[0]["status"] == "refused"
    assert "not a declared level" in results[0]["reason"]
    assert updated == [ad()], "nothing must be modified on a refusal"


def test_the_refusal_names_the_rungs_to_pick_from() -> None:
    """A refusal that only says no makes the labeller guess again."""
    _updated, results = import_labels([ad()], [row(value=0.65)], DIMENSIONS)

    reason = results[0]["reason"]
    for level in DIMENSIONS["on_call_load"].levels:
        assert level.label.en in reason, reason


def test_every_declared_rung_is_importable() -> None:
    """The vocabulary the page offers and the vocabulary the importer accepts
    are the same set — otherwise the page can present a rung that is refused on
    submission, after the labelling work is already done."""
    for level in DIMENSIONS["on_call_load"].levels:
        _updated, results = import_labels([ad()], [row(value=level.value)], DIMENSIONS)
        assert results[0]["status"] == "applied", (level.value, results[0])


def test_the_cli_set_path_enforces_the_same_rungs(tmp_path: Path) -> None:
    """`set` must not be a way around the vocabulary `import` enforces."""
    store_path = tmp_path / "store.jsonl"
    save_store([ad()], store_path)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "integral.harness",
            "--store",
            str(store_path),
            "set",
            "test-1",
            "on_call_load",
            "0.65",
            "--quote",
            "guardias rotativas",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2, completed.stdout
    assert "not a declared level" in completed.stderr
    assert not load_store(store_path)[0].labels


def test_committed_store_labels_all_land_on_a_rung() -> None:
    """The corpus itself, not just the write paths. A label that predates the
    levels, or arrived through a path that skipped the check, has no class for
    macro-F1 and would be silently binned at measurement time."""
    offenders = [
        f"{stored.id}:{label.dimension}={label.value}"
        for stored in load_store()
        for label in stored.labels
        if label.dimension in DIMENSIONS
        and DIMENSIONS[label.dimension].level_for(label.value) is None
    ]
    assert not offenders, offenders


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        (["confirmed", "confirmed"], "confirmed"),
        (["human", "human"], "human"),
        (["confirmed", "human"], "edited"),
        (["confirmed", "edited"], "edited"),
        (["human", "edited"], "edited"),
    ],
)
def test_merged_spans_only_stay_confirmed_when_every_span_was(
    sources: list[str], expected: str
) -> None:
    """A confirm rate counts labels a person accepted exactly as proposed.

    When two spans of one dimension merge into one label, that claim has to
    survive the merge honestly: a label built from one confirmed span and one
    the labeller added themselves was not accepted as proposed, and counting it
    as `confirmed` would inflate the very number the blind-control cohort exists
    to make readable. `confirmed` therefore needs unanimity, `human` needs no
    proposal to have been involved at all, and every mix reports as `edited`.
    """
    text = "Guardias rotativas cada mes y guardias localizadas los fines de semana."
    store = [ad(text=text)]
    quotes = ["Guardias rotativas", "guardias localizadas"]

    updated, results = import_labels(
        store,
        [row(quote=quote, source=source) for quote, source in zip(quotes, sources, strict=True)],
        DIMENSIONS,
    )

    assert all(result["status"] == "applied" for result in results)
    assert len(updated[0].labels) == 1
    assert updated[0].labels[0].source == expected
    assert len(updated[0].labels[0].spans) == 2
