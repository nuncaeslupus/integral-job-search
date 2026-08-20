"""Pre-marked spans, and the instruments that keep them from poisoning the gold.

The suggestions exist to remove work from the labeller. The risk they carry is
that the corpus becomes a transcript of whatever proposed them — and if that is
`Dimension.extraction.cues`, `extraction_macro_f1` (T15) ends up measuring the
extractor against its own output and passes regardless of merit. That is D-2.

Two instruments are tested here. `validate_suggestions` refuses the arrangement
outright where it is provable (a cue-derived set covering an evaluation ad; a
control ad that was given suggestions after all). `cue_agreement` measures the
part that cannot be refused, because a set that merely *happens* to agree with
the cues looks identical to one derived from them until you count.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral.dimensions import DimensionError, load_dimensions
from integral.harness import LabelledAd, load_store
from integral.suggestions import (
    SuggestionError,
    SuggestionSet,
    blind_control,
    cue_agreement,
    validate_suggestions,
    write_proposals,
)
from integral.suggestions import _main as suggestions_main

DIMENSIONS = load_dimensions()
TEXT = "Ofrecemos guardias rotativas cada mes y dos horas cada viernes para estudiar."


def ad(ad_id: str = "a-1", split: str = "evaluation", text: str = TEXT) -> LabelledAd:
    return LabelledAd(
        id=ad_id,
        language="es",
        text=text,
        source_url="https://example.invalid/1",
        split=split,  # type: ignore[arg-type]
        labels=[],
    )


def store(split: str = "evaluation", text: str = TEXT) -> list[LabelledAd]:
    """Eight ads, so the blind-control cohort is a real subset rather than everything.

    `validate_suggestions` now requires the declared control set to *be* the
    computed cohort, so a one-ad fixture cannot express "this ad carries
    suggestions and is not a control" — at that size the cohort is the only ad
    there is.
    """
    return [ad(f"a-{n}", split, text) for n in range(1, 9)]


def target_id(ads: list[LabelledAd]) -> str:
    """An ad outside the cohort — the one a suggestion may legitimately land on."""
    controls = set(blind_control(ads))
    return next(a.id for a in ads if a.id not in controls)


def suggestion_set(
    method: str = "llm_read",
    ads: list[LabelledAd] | None = None,
    **overrides: object,
) -> SuggestionSet:
    ads = ads if ads is not None else store()
    payload: dict[str, object] = {
        "method": method,
        "generated_at": "2026-08-19",
        "blind_control": blind_control(ads),
        "by_ad": {
            target_id(ads): [
                {"dimension": "on_call_load", "value": 0.8, "quote": "guardias rotativas"}
            ]
        },
        **overrides,
    }
    return SuggestionSet.model_validate(payload)


# --- the control set ---------------------------------------------------------


def test_blind_control_carries_every_language() -> None:
    """A control set holding no Catalan ad says nothing about labelling Catalan
    cold, which is exactly the slice most likely to be rubber-stamped."""
    store = load_store()
    chosen = set(blind_control(store))
    languages = {ad.language for ad in store if ad.id in chosen}

    assert languages == {ad.language for ad in store}


def test_blind_control_is_stable_across_regeneration() -> None:
    """An ad labelled blind that later receives a suggestion has already given up
    the only thing it was for, so the set must not move when it is recomputed."""
    store = load_store()
    assert blind_control(store) == blind_control(store)
    assert blind_control(list(reversed(store))) == blind_control(store)


def test_a_control_ad_carrying_suggestions_is_refused() -> None:
    ads = store()
    control = blind_control(ads)[0]
    marked = suggestion_set(
        ads=ads,
        by_ad={control: [{"dimension": "on_call_load", "value": 0.8, "quote": "guardias"}]},
    )

    problems = validate_suggestions(marked, ads, DIMENSIONS)

    assert any("no longer a baseline" in problem for problem in problems)


def test_an_undeclared_cohort_is_refused_rather_than_passing_over_nothing() -> None:
    """An empty control list used to pass with zero violations — a clean result
    over nothing, which is the one outcome a gate here may never produce. Without
    the cohort there is no baseline, so a confirm rate cannot be told apart from
    rubber-stamping while the probe still reports success."""
    ads = store()

    problems = validate_suggestions(suggestion_set(ads=ads, blind_control=[]), ads, DIMENSIONS)

    assert problems, "an absent cohort must not validate"
    assert all("belongs to the blind-control cohort" in problem for problem in problems)


def test_an_invented_control_ad_is_refused() -> None:
    """The cohort is derived from the ad id so it stays stable; a hand-picked one
    would drift on every regeneration."""
    ads = store()
    outsider = target_id(ads)

    problems = validate_suggestions(
        suggestion_set(ads=ads, blind_control=[*blind_control(ads), outsider], by_ad={}),
        ads,
        DIMENSIONS,
    )

    assert any("not in the computed cohort" in problem for problem in problems)


# --- what a suggestion has to satisfy ----------------------------------------


def test_a_quote_absent_from_the_ad_is_refused() -> None:
    ads = store()
    absent = {
        target_id(ads): [{"dimension": "on_call_load", "value": 0.8, "quote": "nada de esto"}]
    }
    problems = validate_suggestions(suggestion_set(ads=ads, by_ad=absent), ads, DIMENSIONS)
    assert any("does not appear" in problem for problem in problems)


def test_an_ambiguous_quote_is_refused() -> None:
    """The page turns a quote into offsets by searching for it; two hits means
    the span silently lands on whichever came first."""
    ads = store(text="guardias por la tarde y guardias de noche")
    twice = {target_id(ads): [{"dimension": "on_call_load", "value": 0.8, "quote": "guardias"}]}
    problems = validate_suggestions(suggestion_set(ads=ads, by_ad=twice), ads, DIMENSIONS)
    assert any("appears 2 times" in problem for problem in problems)


def test_a_value_off_the_rungs_is_refused() -> None:
    ads = store()
    off = {
        target_id(ads): [
            {"dimension": "on_call_load", "value": 0.65, "quote": "guardias rotativas"}
        ]
    }
    problems = validate_suggestions(suggestion_set(ads=ads, by_ad=off), ads, DIMENSIONS)
    assert any("is not a rung" in problem for problem in problems)


def test_an_unknown_dimension_is_refused() -> None:
    ads = store()
    unknown = {
        target_id(ads): [{"dimension": "vibes", "value": 0.8, "quote": "guardias rotativas"}]
    }
    problems = validate_suggestions(suggestion_set(ads=ads, by_ad=unknown), ads, DIMENSIONS)
    assert any("unknown dimension" in problem for problem in problems)


# --- D-2: cue-derived suggestions and the evaluation split -------------------


def test_cue_derived_suggestions_are_refused_on_an_evaluation_ad() -> None:
    """The half `extraction_macro_f1` is measured on. Confirming a cue here makes
    the gate score the extractor against its own output."""
    ads = store(split="evaluation")
    problems = validate_suggestions(suggestion_set(method="cue", ads=ads), ads, DIMENSIONS)
    assert any("D-2" in problem for problem in problems)


def test_cue_derived_suggestions_are_allowed_on_an_elicitation_ad() -> None:
    """The elicitation half feeds reaction elicitation (T9), not the extraction
    gate, so there is nothing there for a cue to contaminate."""
    ads = store(split="elicitation")
    problems = validate_suggestions(suggestion_set(method="cue", ads=ads), ads, DIMENSIONS)
    assert problems == []


def test_cue_agreement_is_total_when_every_quote_is_a_cue_hit() -> None:
    """What a cue-derived set looks like from the outside, whatever it calls
    itself — the number that makes `method` checkable rather than trusted."""
    ads = store()
    measured = cue_agreement(suggestion_set(ads=ads), ads, DIMENSIONS)

    assert measured["suggestion_count"] == 1
    assert measured["suggestion_cue_agreement"] == 1.0
    assert measured["cue_unreachable"] == 0


def test_cue_agreement_counts_a_span_the_extractor_could_not_reach() -> None:
    """The interesting half: suggestions carrying information the cues do not
    already hold are the ones that make the gold worth measuring against.

    "two hours every Friday to study" is learning support by the dimension's own
    definition — time the employer puts behind learning — and no `learning_support`
    cue reaches it: they all key on the words *presupuesto/plan de formación*,
    *formación continua*, or paid certifications. Precisely the phrasing a
    regex-derived gold set would never contain, and so precisely what makes the
    gold worth measuring the extractor against."""
    ads = store()
    target = target_id(ads)
    beyond = {
        target: [
            {
                "dimension": "learning_support",
                "value": 0.8,
                "quote": "dos horas cada viernes para estudiar",
            }
        ]
    }
    measured = cue_agreement(suggestion_set(ads=ads, by_ad=beyond), ads, DIMENSIONS)

    assert measured["cue_unreachable"] == 1
    assert measured["suggestion_cue_agreement"] == 0.0
    assert measured["cue_unreachable_examples"] == [f"{target}:learning_support"]


@pytest.mark.parametrize("method", ["llm_read", "cue"])
def test_the_method_is_recorded_verbatim(method: str) -> None:
    """Nameable either way. A cue set is a legitimate thing to build for
    debugging the extractor; what it is not is a source of gold, and that is
    enforced by where it may be used, not by refusing to name it."""
    assert suggestion_set(method=method).method == method


# --- coining a dimension has to terminate somewhere ------------------------


def test_propose_writes_a_stub_that_will_not_load_until_a_person_finishes_it(
    tmp_path: Path,
) -> None:
    """The page runs over `file://` and cannot write to the repository, so a
    coined dimension travels in the export and is materialised here.

    Deliberately as a stub that `load_dimensions` *refuses*. Coining changes the
    model's spine and every gate that counts dimensions reads it; a stub that
    loaded cleanly would let an idea had while reading one ad become part of the
    measured model without anyone deciding it should.
    """
    export = {
        "labels": [],
        "proposed_dimensions": [
            {
                "id": "childcare_support",
                "label": "Childcare support",
                "definition": "what the employer puts behind childcare",
                "group": "terms",
                "polarity": "unipolar",
                "coined_at_ad": "manfred-8360",
                "levels": [
                    {"value": 0.0, "label": "Nothing"},
                    {"value": 1.0, "label": "Concrete"},
                ],
            }
        ],
    }

    (written,) = write_proposals(export, tmp_path)

    assert written.name == "childcare_support.yaml"
    body = written.read_text(encoding="utf-8")
    assert "TODO" in body
    assert "manfred-8360" in body, "the stub must record where it was coined"
    with pytest.raises(DimensionError, match="methods_ref"):
        load_dimensions(tmp_path)


def test_propose_refuses_to_overwrite_an_existing_dimension(tmp_path: Path) -> None:
    (tmp_path / "on_call_load.yaml").write_text("id: on_call_load\n", encoding="utf-8")
    export = {
        "proposed_dimensions": [
            {
                "id": "on_call_load",
                "label": "x",
                "levels": [{"value": 0.0, "label": "a"}, {"value": 1.0, "label": "b"}],
            }
        ]
    }

    with pytest.raises(SuggestionError, match="already exists"):
        write_proposals(export, tmp_path)


def test_propose_refuses_an_id_the_model_could_never_accept(tmp_path: Path) -> None:
    export = {"proposed_dimensions": [{"id": "Not Snake Case", "label": "x", "levels": []}]}

    with pytest.raises(SuggestionError, match="snake_case"):
        write_proposals(export, tmp_path)


# --- the CLI itself, not just the functions behind it ----------------------


def test_propose_is_reachable_from_the_command_line(tmp_path: Path) -> None:
    """`argv or ["check"]` discarded `sys.argv` whenever argv was None — which is
    every real invocation — so `propose` was unreachable from the command line
    while its unit tests, which call `write_proposals` directly, stayed green.

    The importer prints this command as the way out of a coined-dimension
    import, so a version of it that cannot be run leaves that workflow with no
    terminating step at all. This test drives `main` the way a shell does.
    """
    export = tmp_path / "export.json"
    export.write_text(
        json.dumps(
            {
                "labels": [],
                "proposed_dimensions": [
                    {
                        "id": "childcare_support",
                        "label": "Childcare support",
                        "definition": "d",
                        "group": "terms",
                        "coined_at_ad": "manfred-8360",
                        "levels": [
                            {"value": 0.0, "label": "Nothing"},
                            {"value": 1.0, "label": "Concrete"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    code = suggestions_main(["propose", str(export), "--dimensions", str(tmp_path)])

    assert code == 0
    assert (tmp_path / "childcare_support.yaml").exists()


def test_the_check_form_without_a_subcommand_still_works(tmp_path: Path) -> None:
    """The original `… --suggestions X <evidence>` form predates subcommands and
    is what the docs and Makefile call; adding `propose` must not break it."""
    suggestions = tmp_path / "s.json"
    ads = load_store()
    suggestions.write_text(
        json.dumps(
            {
                "method": "llm_read",
                "generated_at": "2026-08-19",
                "blind_control": blind_control(ads),
                "by_ad": {},
            }
        ),
        encoding="utf-8",
    )
    evidence = tmp_path / "e.json"

    code = suggestions_main(["--suggestions", str(suggestions), str(evidence)])

    assert code == 0
    assert json.loads(evidence.read_text(encoding="utf-8"))["suggestion_violations"] == 0


def test_propose_reports_an_export_carrying_no_proposals(tmp_path: Path) -> None:
    export = tmp_path / "export.json"
    export.write_text(json.dumps({"labels": []}), encoding="utf-8")

    assert suggestions_main(["propose", str(export), "--dimensions", str(tmp_path)]) == 1
