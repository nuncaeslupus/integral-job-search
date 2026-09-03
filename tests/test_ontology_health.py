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
    LANGUAGE_GATE,
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


def test_the_per_language_shortfall_is_recorded_rather_than_averaged_away() -> None:
    """ES, EN and CA are one product, so the aggregate may not hide one of them.

    This test asserted `all(rate >= 0.85)` and passed at en 0.8731 — until the
    independent audit of `concept_map.yaml` was applied. Nine of its 41 accepted
    findings fall on English adverts, and correcting them put English at 0.8423:
    **the model does not cover the English corpus to the floor the other two
    clear.** That is a true statement about the model, and the audit's own
    structural finding says why — narrow technical specialisms (PKI, MBSE,
    navigation algorithms, platform engineering, quantum cryptography) have no
    dimension at all, and `domain_knowledge` had been absorbing them.

    Deleting the assertion would leave the aggregate — which the three languages
    carry for each other — as the only number, so the shortfall gets its own
    reported key instead. `languages_below_gate` is pinned here exactly: a
    language falling under the floor, or English recovering, both fail this test
    and force the record to be re-read rather than drifting quietly.

    The remaining hard requirement is that no *further* language falls under.
    Raising English is #321, filed against this measurement.
    """
    measured = measure()
    by_language = measured["ontology_hit_rate_by_language"]

    assert set(by_language) == {"ca", "en", "es"}
    assert measured["languages_below_gate"] == ["en"], by_language
    assert by_language["en"] < LANGUAGE_GATE, "English recovered — retire this test's exception"
    assert by_language["ca"] >= LANGUAGE_GATE, by_language
    assert by_language["es"] >= LANGUAGE_GATE, by_language
    # The aggregate gate is what T57 declares, and it survives the audit.
    assert measured["ontology_hit_rate"] >= LANGUAGE_GATE


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


# --- The independent audit of `concept_map.yaml`, as fixtures -----------------
#
# CLAUDE.md: "Fixtures for a correctness-critical gate are written by a second
# session… Every accepted case is then committed into the gate's own fixtures
# before the PR merges — not merely answered in a comment."
#
# A second session read all 41 dimension `definition:`/`levels:` blocks before
# opening the map, and derived each verdict from that text rather than from
# running this module. It found 41 placements wrong in the **fail-open**
# direction — a concept credited to a dimension whose definition does not reach
# it raises `ontology_hit_rate` without widening anything, which is the one
# failure the metric exists to catch. The report is
# https://github.com/nuncaeslupus/integral-job-search/pull/320#issuecomment-5517619074
#
# Each row is (concept, the dimension the definitions require or None, why).
# `None` means the honest state is unmapped: the concept goes back into the
# staleness signal, where a gap in the model belongs.
_AUDITED: tuple[tuple[str, str | None, str], ...] = (
    # travel_requirement is a `hard` dealbreaker — "travel or relocation the role
    # requires". A benefit scored as a requirement can disqualify on a perk.
    ("internal mobility across countries", None, "offered as a benefit, not required"),
    # wellbeing_benefits: "Non-salary provision aimed at health and life outside work".
    ("flexible remuneration menu", None, "the employee's own gross salary repackaged"),
    ("remote-work expenses reimbursed", None, "work expenses, not life outside work"),
    ("home-office budget", None, "work equipment, not health or life outside work"),
    ("equipment shipped to your home", None, "work equipment, not a wellbeing provision"),
    ("holiday only in low season", None, "a restriction on leave, not provision of it"),
    # variable_pay: "Pay beyond a fixed base: bonuses, commission… profit sharing".
    ("referral programme", "variable_pay", "a bounty paid on top of base pay"),
    # remote_arrangement: "How much of the working week is worked away from a company site".
    ("remote system access", None, "the systems are reached remotely, the worker is not"),
    ("connection quality is a stated condition", None, "not a share of the week off-site"),
    ("distributed team", None, "where colleagues are, not where this post is worked"),
    # role_breadth: "How many distinct jobs the post actually is."
    ("one advert covering many unrelated roles", None, "a scattergun listing, not one post"),
    ("design-system work across three surfaces", None, "one craft applied to three surfaces"),
    # formal_credential: "Whether a documented qualification gates the role."
    ("specialisation desirable not required", "formal_credential", "a qualification preference"),
    # work_eligibility: "Where you must be legally and physically able to work" — spatial.
    (
        "employer in a distant timezone",
        None,
        "no overlap requirement is stated, so it gates nothing",
    ),
    # hiring_process_burden: "What the advert asks of you before it will consider you at all."
    (
        "must be registered unemployed before hiring",
        "hiring_process_burden",
        "a pre-application status the applicant must obtain",
    ),
    (
        "explicit instruction to apply on minimums",
        None,
        "it lowers the barrier rather than adding a cost",
    ),
    ("cap on how often you may apply", None, "names no stage of the process"),
    # domain_knowledge: "tied to one business domain… as against work that transfers
    # between sectors unchanged". Each of these transfers unchanged — the definition's
    # own negative pole — and stretching it here hid a genuinely missing dimension.
    ("platform-engineering background required", None, "a technical field, not a business domain"),
    ("model-based systems engineering desirable", None, "a technical field, not a business domain"),
    ("data governance desirable", None, "a technical field, not a business domain"),
    ("security testing automation", None, "a technical field, not a business domain"),
    ("PKI specialism required", None, "a technical field, not a business domain"),
    ("navigation algorithms desirable", None, "a technical field, not a business domain"),
    ("quantum cryptography specialism", None, "a technical field, not a business domain"),
    ("compliance frameworks required", None, "ISO 27001 / GDPR / NIST name no sector"),
    ("conversion-funnel work", None, "transfers between sectors unchanged"),
    ("named client roster", None, "four unrelated sectors is evidence of the opposite"),
    # ai_in_the_work: "assistants and agent frameworks named in the workflow… or AI
    # fluency stated as a requirement of everyone."
    (
        "harness engineering named as a skill",
        "ai_in_the_work",
        "the quote is 'prompt/context or even harness engineering'",
    ),
    (
        "evaluation practice required",
        "ai_in_the_work",
        "'golden sets, LLM-as-judge, regression detection'",
    ),
    # tool_specificity: "how prescriptive the advert is about tools".
    (
        "niche knowledge desirable",
        "tool_specificity",
        "the quote names a tool family, 'tecnologies GIS'",
    ),
    # contract_stability levels are 0.0 freelance / 0.3 fixed-term / 0.9 open-ended,
    # with no "not stated" rung — so an unplaceable concept scores as freelance.
    ("contract type unstated", None, "no rung means 'not stated'; mapping it scores freelance"),
    (
        "contract type unstated in the fields",
        None,
        "no rung means 'not stated'; mapping it scores freelance",
    ),
    ("four-month probation", None, "probation is not the durability of the engagement"),
    (
        "suits people who reject full-time employment",
        "contract_stability",
        "'full-time' there means permanent",
    ),
    # contracted_hours: "the contract's size, not… when the hours fall".
    (
        "hours change by season",
        "schedule_flexibility",
        "the quote is a timetable, not a contracted quantity",
    ),
    # commute_burden: "providing your own vehicle" — provision is the negation of it.
    ("company vehicle provided", None, "the employer supplies the vehicle"),
    ("company vehicle and tools provided", None, "the employer supplies the vehicle"),
    # company_stage: "Where the employer sits between an early-stage startup and a
    # large established organisation" — employer size, not customer count.
    ("stated user scale", None, "customer count is not employer size"),
    ("stated customer scale", None, "customer count is not employer size"),
    ("family-owned group", None, "ownership is not a stage between startup and large"),
    # learning_support: "What the employer puts behind learning."
    (
        "continuing training expected",
        None,
        "quoted from the candidate profile — a demand, not provision",
    ),
    # stack_modernity: "whether the technology named is current… or legacy".
    ("very large Rails codebase", "technical_depth", "size is not age, and the stack is current"),
)


def _committed_map() -> dict[str, str]:
    from integral.dimensions import load_dimensions
    from integral.ontology_health import (
        DEFAULT_CONCEPT_MAP_PATH,
        DEFAULT_SUGGESTIONS_PATH,
        known_dimension_ids,
        read_concept_map,
    )

    payload = json.loads(DEFAULT_SUGGESTIONS_PATH.read_text(encoding="utf-8"))
    return read_concept_map(
        DEFAULT_CONCEPT_MAP_PATH,
        known_dimension_ids(load_dimensions()),
        set(payload.get("unmapped") or []),
    )


@pytest.mark.parametrize(("concept", "expected", "why"), _AUDITED, ids=[c for c, _, _ in _AUDITED])
def test_the_committed_map_agrees_with_the_independent_audit(
    concept: str, expected: str | None, why: str
) -> None:
    """Each accepted finding, pinned against the map the gate actually reads.

    Answering the audit in a review thread leaves the code exactly as unprotected
    as it was: the next regression re-opens the same hole with nothing to catch
    it. These rows are what make the measured denominator rise.
    """
    assert _committed_map().get(concept) == expected, why


def test_every_audited_concept_is_one_the_read_pass_actually_stated() -> None:
    """A row naming a concept nobody read would pass vacuously.

    The table above is the whole of the audit's protection, and a fixture that
    asserts `None` for a misspelled concept asserts nothing at all — it is green
    for the same reason an empty scan is. So the names are checked against the
    source's own `unmapped` list, which is where every audited concept came from.
    """
    from integral.ontology_health import DEFAULT_SUGGESTIONS_PATH

    payload = json.loads(DEFAULT_SUGGESTIONS_PATH.read_text(encoding="utf-8"))
    declared = set(payload.get("unmapped") or [])
    assert declared, "the read pass declares no unmapped concepts"
    assert not [concept for concept, _, _ in _AUDITED if concept not in declared]
