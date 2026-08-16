"""T23 — a dimension's `side`, and a coverage metric that respects it.

Written RED before `side` existed. Until now every dimension was implicitly
*matched*: an ad describes an environment, a candidate holds a preference, and
ranking compares the two. A candidate **trait** (creativity, ambition) has no ad
cue that could ever exist, and a candidate **fact** (languages, location) is
compared against an ad *requirement* rather than a preference. Both would sit in
the model as permanently broken matched dimensions, penalised by
`dimension_extractor_coverage` for being what they are.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobsearch.dimensions import (
    DEFAULT_DIMENSIONS_DIR,
    DEFAULT_METHODS_PATH,
    DimensionError,
    ad_side,
    collect_violations,
    extractor_coverage,
    load_dimensions,
    side_violations,
)

TRAIT = """\
id: ambition
kind: soft
polarity: unipolar
side: candidate_trait
label:
  en: Ambition
  es: Ambición
  ca: Ambició
definition: >
  How strongly the candidate pursues advancement, scope and responsibility.
elicitation:
  questions:
    - id: amb_q1
      text:
        en: Tell me about something you went after at work that nobody asked you to.
        es: Cuéntame algo que buscaste en el trabajo que nadie te pidió.
        ca: Explica'm alguna cosa que vas buscar a la feina que ningú et va demanar.
methods_ref: METHODS.md#21-structured-behavioural-elicitation
"""

FACT = """\
id: languages_spoken
kind: hard
polarity: unipolar
side: candidate_fact
compares_against: english_demand
label:
  en: Languages spoken
  es: Idiomas hablados
  ca: Idiomes parlats
definition: >
  The languages the candidate can work in, and at what level.
elicitation:
  questions:
    - id: lang_q1
      text:
        en: Which languages have you actually worked in, as opposed to studied?
        es: ¿En qué idiomas has trabajado realmente, en lugar de estudiado?
        ca: En quins idiomes has treballat realment, en comptes d'estudiar?
methods_ref: METHODS.md#21-structured-behavioural-elicitation
"""


def write(directory: Path, stem: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_a_trait_dimension_without_cues_is_valid(tmp_path: Path) -> None:
    """A `candidate_trait` needs no cues and no gold.

    There is no ad text that evidences ambition. Requiring cues of a trait would
    make the model unable to hold the thing the interview exists to elicit.
    """
    write(tmp_path, "ambition", TRAIT)

    dimensions = load_dimensions(tmp_path)

    assert [d.id for d in dimensions] == ["ambition"]
    assert dimensions[0].side == "candidate_trait"
    assert collect_violations(tmp_path, DEFAULT_METHODS_PATH) == []


def test_a_trait_dimension_carrying_cues_is_rejected(tmp_path: Path) -> None:
    """Claiming ad-extractability for a trait is a contradiction, not a warning.

    A cue on `ambition` asserts that an ad's wording evidences the candidate's
    ambition. It evidences the employer's prose. Left permitted, the extractor
    would score a personality trait from marketing copy.
    """
    cues = (
        "extraction:\n"
        "  cues:\n"
        "    en:\n"
        '      - pattern: "ambitious"\n'
        "        value: 0.6\n"
    )
    body = TRAIT.replace("methods_ref:", cues + "methods_ref:")
    write(tmp_path, "ambition", body)

    with pytest.raises(DimensionError, match="candidate_trait"):
        load_dimensions(tmp_path)


def test_a_matched_dimension_without_cues_is_a_violation(tmp_path: Path) -> None:
    """The rule still binds where it always did.

    `side` must not become a way to opt out of cues: a matched dimension with
    none is exactly what `dimension_extractor_coverage` was built to catch.
    """
    body = TRAIT.replace("side: candidate_trait\n", "")
    write(tmp_path, "ambition", body)

    violations = side_violations(load_dimensions(tmp_path))

    assert len(violations) == 1
    assert "no cues" in violations[0]


def test_a_candidate_fact_must_name_what_it_compares_against(tmp_path: Path) -> None:
    """A fact with no comparison target cannot filter anything.

    `languages_spoken` is only meaningful opposite an ad-side requirement. A
    fact that names none is a value collected and never used — which reads, from
    every metric's point of view, exactly like a fact that matched everything.
    """
    body = FACT.replace("compares_against: english_demand\n", "")
    write(tmp_path, "languages_spoken", body)

    violations = side_violations(load_dimensions(tmp_path))

    assert len(violations) == 1
    assert "compares_against" in violations[0]


def test_a_candidate_fact_comparing_against_an_unknown_dimension_is_a_violation(
    tmp_path: Path,
) -> None:
    """The target must resolve, or the filter silently never fires."""
    write(tmp_path, "languages_spoken", FACT.replace("english_demand", "no_such_dimension"))

    violations = side_violations(load_dimensions(tmp_path))

    assert len(violations) == 1
    assert "no_such_dimension" in violations[0]


def test_extractor_coverage_counts_only_ad_side_dimensions(tmp_path: Path) -> None:
    """Adding traits must not depress `dimension_extractor_coverage`.

    The metric asks "can this be extracted from an ad". Asking it of a trait
    scores the model down for holding the very thing the scope extension added,
    and would push a future author to delete traits to keep a gate green.
    """
    for stem, body in (("ambition", TRAIT), ("languages_spoken", FACT)):
        write(tmp_path, stem, body)
    committed = load_dimensions(DEFAULT_DIMENSIONS_DIR)
    candidate_side = load_dimensions(tmp_path)

    assert extractor_coverage(committed) == 1.0
    assert extractor_coverage([*committed, *candidate_side]) == 1.0
    # …and with nothing ad-side at all there is nothing to report, which is not
    # the same as full coverage.
    assert extractor_coverage(candidate_side) == 0.0
    assert ad_side(candidate_side) == []


def test_the_committed_model_is_all_matched_and_unchanged() -> None:
    """`side` is additive: the 22 v0 dimensions default to `matched`."""
    dimensions = load_dimensions(DEFAULT_DIMENSIONS_DIR)

    assert {d.side for d in dimensions} == {"matched"}
    assert side_violations(dimensions) == []
