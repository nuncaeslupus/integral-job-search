"""The named rungs a dimension is labelled in, and the snap that scores against them.

`levels` exists because nobody can answer "is this ad 0.6 or 0.7 on mentoring".
A dimension declares the two-to-five named positions its scale really has; the
labeller clicks a name and never sees the float. The same list doubles as the
class set `extraction_macro_f1` (T15) is computed over — macro-F1 is defined
over classes, and a continuous score has none, so without this the metric would
have to invent a binning rule at measurement time where nobody could review it.

The asymmetry these tests pin down: **gold** values must land exactly on a rung
(gold is a human judgement about a real ad, so it has to be sayable in the
vocabulary a human labels in), while **cue** values need only stay inside the
scale (a cue is the extractor's continuous estimate, snapped at scoring time).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobsearch.dimensions import (
    DEFAULT_DIMENSIONS_DIR,
    GROUPS,
    DimensionError,
    load_dimensions,
)

BODY = """\
id: social_intensity
kind: {kind}
polarity: {polarity}
group: the_work
label:
  en: Social intensity
  es: Intensidad social
  ca: Intensitat social
definition: >
  How much of the working week is spent in unstructured group interaction.
levels:
{levels}
elicitation:
  questions:
    - id: si_q1
      text:
        en: Tell me about a working week you enjoyed.
        es: Cuentame una semana de trabajo que disfrutaste.
        ca: Explica'm una setmana de feina que vas gaudir.
extraction:
  cues:
    en:
      - pattern: "offsites?"
        value: {cue}
        negatable: false
  gold:
{gold}
methods_ref: METHODS.md#21-structured-behavioural-elicitation
"""

NO_GOLD = "    []"


def rung(value: float, name: str = "rung") -> str:
    return (
        f"  - value: {value}\n"
        f"    label: {{en: {name}, es: {name}, ca: {name}}}\n"
        f'    tell: "what this rung looks like in an ad"'
    )


def write(tmp_path: Path, **kwargs: str) -> Path:
    defaults = {"kind": "soft", "polarity": "bipolar", "cue": "0.5", "gold": NO_GOLD}
    body = BODY.format(**{**defaults, **kwargs})
    directory = tmp_path / "dimensions"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "social_intensity.yaml").write_text(body, encoding="utf-8")
    return directory


# --- the scale's own shape ---------------------------------------------------


def test_levels_must_ascend_by_value(tmp_path: Path) -> None:
    """Unordered rungs break the nearest-rung snap, which assumes a sorted scale."""
    directory = write(tmp_path, levels="\n".join([rung(0.7, "high"), rung(0.0, "none")]))
    with pytest.raises(DimensionError, match="levels must ascend"):
        load_dimensions(directory)


def test_two_rungs_at_the_same_value_are_rejected(tmp_path: Path) -> None:
    """Two names for one class record nothing a labeller's choice distinguishes."""
    directory = write(tmp_path, levels="\n".join([rung(0.0, "none"), rung(0.0, "also_none")]))
    with pytest.raises(DimensionError, match="duplicate level value"):
        load_dimensions(directory)


def test_a_single_rung_is_not_a_scale(tmp_path: Path) -> None:
    """One rung offers the labeller no choice, so it records no judgement."""
    directory = write(tmp_path, levels=rung(0.5))
    with pytest.raises(DimensionError, match="levels"):
        load_dimensions(directory)


def test_unipolar_dimension_rejects_a_negative_rung(tmp_path: Path) -> None:
    """The ranker reads a unipolar score as a magnitude, so a sign would be lost."""
    directory = write(
        tmp_path,
        kind="hard",
        polarity="unipolar",
        cue="0.5",
        levels="\n".join([rung(-0.5, "against"), rung(0.5, "for")]),
    )
    with pytest.raises(DimensionError, match="negative level value"):
        load_dimensions(directory)


# --- gold lands on a rung; cues need only stay in range ----------------------


def test_gold_off_a_rung_is_rejected(tmp_path: Path) -> None:
    """Gold is a human judgement, so it must be sayable in the labelling vocabulary."""
    gold = (
        '    - ad_id: fake-1\n      language: en\n      span: "offsites"\n'
        "      value: 0.3\n      derived_from: cue"
    )
    directory = write(tmp_path, levels="\n".join([rung(0.0), rung(0.7)]), gold=gold)
    with pytest.raises(DimensionError, match="not declared levels"):
        load_dimensions(directory)


def test_a_cue_between_two_rungs_is_accepted(tmp_path: Path) -> None:
    """A cue is a continuous estimate — it is snapped at scoring time, not authored on a rung."""
    directory = write(tmp_path, cue="0.42", levels="\n".join([rung(0.0), rung(0.7)]))
    (dimension,) = load_dimensions(directory)
    assert dimension.extraction.cues["en"][0].value == 0.42


def test_a_cue_past_the_end_of_the_scale_is_rejected(tmp_path: Path) -> None:
    """Snapping would silently clamp it into a rung it never meant."""
    directory = write(tmp_path, cue="0.95", levels="\n".join([rung(0.0), rung(0.7)]))
    with pytest.raises(DimensionError, match="outside the level scale"):
        load_dimensions(directory)


# --- the snap itself ---------------------------------------------------------


def test_snap_returns_the_nearest_rung(tmp_path: Path) -> None:
    directory = write(tmp_path, levels="\n".join([rung(0.0, "none"), rung(0.7, "high")]))
    (dimension,) = load_dimensions(directory)
    assert dimension.snap(0.6).label.en == "high"
    assert dimension.snap(0.1).label.en == "none"


def test_snap_breaks_a_tie_towards_zero(tmp_path: Path) -> None:
    """A score exactly between "not stated" and a signal is weaker evidence for the
    signal than for its absence, and an arbitrary tie-break would make macro-F1
    depend on float noise."""
    directory = write(tmp_path, levels="\n".join([rung(0.0, "none"), rung(0.8, "high")]))
    (dimension,) = load_dimensions(directory)
    assert dimension.snap(0.4).label.en == "none"


def test_level_for_does_not_snap(tmp_path: Path) -> None:
    """A label arriving off-rung is a page out of step with the model, not a
    number to round into the nearest acceptable shape."""
    directory = write(tmp_path, levels="\n".join([rung(0.0, "none"), rung(0.7, "high")]))
    (dimension,) = load_dimensions(directory)
    assert dimension.level_for(0.7) is not None
    assert dimension.level_for(0.6) is None


# --- the committed model -----------------------------------------------------


def test_every_committed_dimension_carries_a_usable_scale() -> None:
    for dimension in load_dimensions(DEFAULT_DIMENSIONS_DIR):
        assert 2 <= len(dimension.levels) <= 5, dimension.id
        assert len({level.value for level in dimension.levels}) == len(dimension.levels)
        for level in dimension.levels:
            assert level.tell.strip(), f"{dimension.id}: a rung with no tell"


def test_every_picker_group_is_populated() -> None:
    """An empty section in the labelling picker is a heading that teaches the
    labeller the group exists and then never offers anything under it."""
    used = {dimension.group for dimension in load_dimensions(DEFAULT_DIMENSIONS_DIR)}
    assert used == set(GROUPS), f"unpopulated group(s): {sorted(set(GROUPS) - used)}"


def test_no_group_is_large_enough_to_need_scrolling() -> None:
    """The picker exists so the labeller stops scanning 22 flat options; a group
    holding most of them would rebuild the problem one level down."""
    counts: dict[str, int] = {}
    for dimension in load_dimensions(DEFAULT_DIMENSIONS_DIR):
        counts[dimension.group] = counts.get(dimension.group, 0) + 1
    assert max(counts.values()) <= 8, counts
