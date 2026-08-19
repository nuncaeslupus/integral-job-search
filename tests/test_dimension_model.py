"""T2 — the dimension schema, its loader, and `methods_ref` anchor resolution.

Written RED before `jobsearch.dimensions` existed, per the task payload.

The two tests the plan names are `test_dimension_missing_methods_ref_is_rejected`
and `test_dimension_duplicate_id_is_rejected`; the rest guard the parts of the
§5.1 contract that would otherwise be enforced by review alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobsearch.dimensions import (
    DEFAULT_DIMENSIONS_DIR,
    DEFAULT_METHODS_PATH,
    DimensionError,
    Language,
    collect_violations,
    load_dimensions,
    methods_anchors,
)

VALID = """\
id: social_intensity
kind: soft
polarity: bipolar
group: the_work
label:
  en: Social intensity
  es: Intensidad social
  ca: Intensitat social
definition: >
  How much of the working week is spent in unstructured group interaction.
levels:
  - value: 0.0
    label: {en: Absent, es: Ausente, ca: Absent}
    tell: the ad says nothing about it
  - value: 1.0
    label: {en: Present, es: Presente, ca: Present}
    tell: the ad says so plainly
elicitation:
  questions:
    - id: si_q1
      text:
        en: Tell me about a working week you enjoyed.
        es: Cuentame una semana de trabajo que disfrutaste.
        ca: Explica'm una setmana de feina que vas gaudir.
  reaction_probes:
    - excerpt_kind: perks
extraction:
  cues:
    en:
      - pattern: "(team\\\\s+)?offsites?"
        value: 0.6
        negatable: true
methods_ref: METHODS.md#21-structured-behavioural-elicitation
"""


def write_dimension(directory: Path, stem: str, body: str, suffix: str = ".yaml") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}{suffix}"
    path.write_text(body, encoding="utf-8")
    return path


def test_dimension_missing_methods_ref_is_rejected(tmp_path: Path) -> None:
    """A dimension without `methods_ref` fails validation.

    §5.1: `methods_ref` is required on every dimension. It is the whole basis of
    the `undocumented_methods == 0` criterion, so a dimension that omits it must
    not load at all.
    """
    body = "\n".join(line for line in VALID.splitlines() if not line.startswith("methods_ref:"))
    write_dimension(tmp_path, "social_intensity", body + "\n")

    with pytest.raises(DimensionError, match="methods_ref"):
        load_dimensions(tmp_path)


def test_dimension_duplicate_id_is_rejected(tmp_path: Path) -> None:
    """Two files sharing an `id` fail to load.

    A duplicate id silently shadows one of the two files, and every downstream
    component keys on the id — so this is a load-time error, not a warning.
    Both extensions are read, which is exactly how two files come to share an id
    once the filename must match it.
    """
    write_dimension(tmp_path, "social_intensity", VALID, ".yaml")
    write_dimension(tmp_path, "social_intensity", VALID, ".yml")

    with pytest.raises(DimensionError, match="duplicate"):
        load_dimensions(tmp_path)


def test_dimension_id_must_match_its_filename(tmp_path: Path) -> None:
    """`dimensions/<id>.yaml` — the filename is part of the contract.

    Without this a file can be renamed while the id stays put, and the two drift
    apart with nothing to catch it.
    """
    write_dimension(tmp_path, "not_the_id", VALID)

    with pytest.raises(DimensionError, match="filename"):
        load_dimensions(tmp_path)


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    """Extra keys are refused, the same discipline connectors are held to."""
    write_dimension(tmp_path, "social_intensity", VALID + "weight: 0.4\n")

    with pytest.raises(DimensionError, match="weight"):
        load_dimensions(tmp_path)


def test_label_missing_a_language_is_rejected(tmp_path: Path) -> None:
    """All three corpus languages are required on every label."""
    body = VALID.replace("  ca: Intensitat social\n", "")
    write_dimension(tmp_path, "social_intensity", body)

    with pytest.raises(DimensionError, match="ca"):
        load_dimensions(tmp_path)


def test_unipolar_dimension_rejects_a_negative_cue_value(tmp_path: Path) -> None:
    """Polarity bounds the cue values it admits: unipolar is 0..1, bipolar -1..1.

    A negative value on a unipolar dimension is not a small inconsistency — it
    inverts a score that the ranker reads as a magnitude.
    """
    body = VALID.replace("polarity: bipolar", "polarity: unipolar").replace(
        "value: 0.6", "value: -0.6"
    )
    write_dimension(tmp_path, "social_intensity", body)

    with pytest.raises(DimensionError, match="unipolar"):
        load_dimensions(tmp_path)


def test_uncompilable_cue_pattern_is_rejected(tmp_path: Path) -> None:
    """Cues are regexes; one that cannot compile fails at load, not at extraction."""
    body = VALID.replace('pattern: "(team\\\\s+)?offsites?"', 'pattern: "(unclosed"')
    write_dimension(tmp_path, "social_intensity", body)

    with pytest.raises(DimensionError, match="pattern"):
        load_dimensions(tmp_path)


def test_methods_anchors_are_github_style_slugs() -> None:
    """Anchor resolution reads the real headings out of `docs/METHODS.md`."""
    anchors = methods_anchors(DEFAULT_METHODS_PATH)

    assert "21-structured-behavioural-elicitation" in anchors
    assert "41-dimension-score--weighted-mean" in anchors


def test_unresolvable_methods_ref_is_a_violation(tmp_path: Path) -> None:
    """A `methods_ref` pointing at no heading is counted, not ignored."""
    body = VALID.replace(
        "methods_ref: METHODS.md#21-structured-behavioural-elicitation",
        "methods_ref: METHODS.md#99-a-section-that-does-not-exist",
    )
    write_dimension(tmp_path, "social_intensity", body)

    violations = collect_violations(tmp_path, DEFAULT_METHODS_PATH)

    assert len(violations) == 1
    assert "99-a-section-that-does-not-exist" in violations[0]


def test_collect_violations_reports_instead_of_raising(tmp_path: Path) -> None:
    """The gate needs a count, so the audit path never raises on a bad file.

    `load_dimensions` raises because callers cannot proceed on a broken model;
    `collect_violations` reports because a gate that crashes records no number.
    """
    write_dimension(tmp_path, "social_intensity", VALID + "weight: 0.4\n")

    violations = collect_violations(tmp_path, DEFAULT_METHODS_PATH)

    assert len(violations) == 1
    assert "social_intensity.yaml" in violations[0]


def test_unresolvable_methods_ref_is_rejected_by_the_default_load(tmp_path: Path) -> None:
    """Anchor resolution is part of loading, not an opt-in extra.

    §5.1 requires every `methods_ref` to resolve; a loader that only checked
    when asked would accept, on its ordinary path, exactly the models the spec
    forbids.
    """
    body = VALID.replace(
        "methods_ref: METHODS.md#21-structured-behavioural-elicitation",
        "methods_ref: METHODS.md#99-a-section-that-does-not-exist",
    )
    write_dimension(tmp_path, "social_intensity", body)

    with pytest.raises(DimensionError, match="resolves to no heading"):
        load_dimensions(tmp_path)

    # …and opting out is explicit, for a model detached from a methods register.
    assert load_dimensions(tmp_path, methods_path=None)


def test_collect_violations_reports_an_unreadable_file(tmp_path: Path) -> None:
    """A mis-encoded dimension is a counted violation, not a traceback.

    The gate path has to yield a number for every failure mode it can meet, or
    `dimension_schema_violations` goes unrecorded exactly when it matters.
    """
    (tmp_path / "social_intensity.yaml").write_bytes(b"id: social\xff_intensity\n")

    violations = collect_violations(tmp_path, DEFAULT_METHODS_PATH)

    assert len(violations) == 1
    assert "UTF-8" in violations[0]


def test_collect_violations_reports_a_missing_methods_register(tmp_path: Path) -> None:
    """No `METHODS.md` is a violation of the whole model, reported once."""
    write_dimension(tmp_path, "social_intensity", VALID)

    violations = collect_violations(tmp_path, tmp_path / "nonexistent" / "METHODS.md")

    assert len(violations) == 1
    assert "methods register not found" in violations[0]


def test_schema_languages_match_the_corpus_languages() -> None:
    """The schema's language keys and the corpus's language list stay in step.

    Pydantic needs the languages spelled out statically, so they appear twice —
    once as `Language`, once as `jobsearch.corpus.LANGUAGES`. This is what stops
    the second copy drifting from the first.
    """
    from typing import get_args

    from jobsearch.corpus import LANGUAGES

    assert set(get_args(Language)) == set(LANGUAGES)


def test_committed_dimension_model_has_no_violations() -> None:
    """The model in the repo satisfies its own schema and resolves its anchors.

    This is what makes the T2 gate measure something: without a committed
    dimension, `dimension_schema_violations == 0` would pass over an empty
    directory.
    """
    dimensions = load_dimensions(DEFAULT_DIMENSIONS_DIR)

    assert dimensions, "no dimensions committed — the gate would pass vacuously"
    assert collect_violations(DEFAULT_DIMENSIONS_DIR, DEFAULT_METHODS_PATH) == []
