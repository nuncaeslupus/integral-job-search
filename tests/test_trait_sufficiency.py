"""T49 — trait evidence sufficiency: the step 4 gate.

`status/plan.md`'s T49 row names three RED tests, all below:
`test_a_trait_below_the_floor_is_insufficient_not_scored`,
`test_insufficient_does_not_stop_the_step`, and
`test_the_floor_counts_occasions_not_repetitions`. The payload
(`claude-arsenal/queue/lo-455d.md`) adds two more,
`test_evidence_from_any_surface_counts` and
`test_the_floor_is_never_in_candidate_facing_text`. The rest of this file holds
the properties `trait_sufficiency.py`'s own module docstring commits to: a
denial counting toward the floor like an affirmation, and the "required
verification" section's two deliberate breaks — a trait scored from a single
episode, and a trait left with no reading at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobsearch.decline import DeclineLedger
from jobsearch.identity import ProfileStore, create_profile
from jobsearch.interview import (
    MINIMUM_TRAIT_EPISODES,
    MINIMUM_TRAIT_OCCASIONS,
    leaks_quota_language,
)
from jobsearch.profile import EvidenceLog
from jobsearch.trait_sufficiency import (
    MINIMUM_TRAITS,
    TraitSufficiencyReading,
    _fixture_dimension,
    _localised,
    trait_dimension_ids,
    trait_evidence_sufficiency,
    trait_sufficiency_reading,
    trait_sufficiency_readings,
)

LONG_A = "Redesigned the onboarding flow from scratch — nobody asked me to."
LONG_B = "Built a working prototype over a weekend just to see if an idea held up."
LONG_C = "Pushed back on the plan in the room, even though it was not my call to make."


@pytest.fixture
def profile(tmp_path: Path) -> tuple[EvidenceLog, DeclineLedger]:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    store = ProfileStore(root, identity.handle)
    return EvidenceLog(store), DeclineLedger(store)


# --- the RED tests named in the payload and the plan row --------------------


def test_a_trait_below_the_floor_is_insufficient_not_scored(
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """A scored trait below the floor is a stereotype presented as a finding
    (the module docstring's own words for the harm the gate exists for) — one
    episode on one occasion must read `insufficient`, never `scored`."""
    log, ledger = profile
    log.append(
        recorded_at="2026-08-10T09:00:00Z",
        step="history",
        kind="episode",
        text=LONG_A,
        source="conversation",
        dimensions=("trait_single",),
    )

    reading = trait_sufficiency_reading(log, ledger, "trait_single")

    assert reading.episodes == 1
    assert reading.occasions == 1
    assert reading.status == "insufficient", reading
    assert reading.evidence == (), "an insufficient reading carried evidence ids anyway"
    assert reading.reason.strip()
    assert MINIMUM_TRAIT_EPISODES >= 2, "the episode floor this module reads was weakened"
    assert MINIMUM_TRAIT_OCCASIONS >= 2, "the occasion floor this module reads was weakened"


def test_insufficient_does_not_stop_the_step(
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """Refusing to produce a profile because one trait is thin is the behaviour
    spec-v2-steps.md step 4 rules out — an `insufficient` trait sits alongside a
    scored one in the same measurement, and the step still reads as complete
    (`trait_evidence_sufficiency == 1.0`) rather than blocked."""
    log, ledger = profile
    dims = [_fixture_dimension("trait_thin"), _fixture_dimension("trait_full")]

    log.append(
        recorded_at="2026-08-10T09:00:00Z",
        step="history",
        kind="episode",
        text=LONG_A,
        source="conversation",
        dimensions=("trait_thin",),
    )
    log.append(
        recorded_at="2026-08-10T09:00:00Z",
        step="history",
        kind="episode",
        text=LONG_A,
        source="conversation",
        dimensions=("trait_full",),
    )
    log.append(
        recorded_at="2026-08-11T09:00:00Z",
        step="history",
        kind="episode",
        text=LONG_B,
        source="conversation",
        dimensions=("trait_full",),
    )

    ids = trait_dimension_ids(dims)
    readings = trait_sufficiency_readings(log, ledger, dims)
    fraction, violations = trait_evidence_sufficiency(ids, readings)

    assert violations == [], violations
    assert fraction == 1.0, (
        "a step with one thin trait and one full trait did not read as complete — "
        "insufficient must not block the step"
    )
    by_id = {r.dimension_id: r for r in readings}
    assert by_id["trait_thin"].status == "insufficient"
    assert by_id["trait_full"].status == "scored"


def test_the_floor_counts_occasions_not_repetitions(
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """Two mentions in one sitting are one occasion — exactly what "two
    occasions" is guarding against (the module docstring's own framing) — so
    two same-day episodes must still read `insufficient`."""
    log, ledger = profile
    log.append(
        recorded_at="2026-08-12T09:00:00Z",
        step="history",
        kind="episode",
        text=LONG_A,
        source="conversation",
        dimensions=("trait_sameday",),
    )
    log.append(
        recorded_at="2026-08-12T15:00:00Z",
        step="history",
        kind="episode",
        text=LONG_B,
        source="conversation",
        dimensions=("trait_sameday",),
    )

    reading = trait_sufficiency_reading(log, ledger, "trait_sameday")

    assert reading.episodes == 2, "the fixture did not record two episodes"
    assert reading.occasions == 1, "two same-day episodes were counted as two occasions"
    assert reading.status == "insufficient", reading


def test_evidence_from_any_surface_counts(
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """The floor reads the evidence log, not only onboarding — a row written by
    a step other than History (continuous capture, T28) still counts, feeding
    the same floor an onboarding sitting would."""
    log, ledger = profile
    log.append(
        recorded_at="2026-08-10T09:00:00Z",
        step="history",
        kind="episode",
        text=LONG_A,
        source="conversation",
        dimensions=("trait_anysurface",),
    )
    # Recorded from a wholly different step — reactions, not history — and
    # written straight through `EvidenceLog.append`, not through the interview
    # driver at all: the mechanical form of "any surface".
    log.append(
        recorded_at="2026-08-13T09:00:00Z",
        step="reactions",
        kind="episode",
        text=LONG_C,
        source="offer_reaction",
        dimensions=("trait_anysurface",),
    )

    reading = trait_sufficiency_reading(log, ledger, "trait_anysurface")

    assert reading.episodes == 2
    assert reading.occasions == 2
    assert reading.status == "scored", reading
    assert len(reading.evidence) == 2


def test_the_floor_is_never_in_candidate_facing_text(
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """`TraitSufficiencyReading` carries no field meant for display, and the
    quota-language tripwire (`interview.leaks_quota_language`) still fires on
    an insufficient reading's raw `reason` — which is exactly why nothing in
    this module ever forwards `reason` to a candidate-facing surface."""
    log, ledger = profile
    log.append(
        recorded_at="2026-08-10T09:00:00Z",
        step="history",
        kind="episode",
        text=LONG_A,
        source="conversation",
        dimensions=("trait_quota",),
    )

    reading = trait_sufficiency_reading(log, ledger, "trait_quota")
    assert reading.status == "insufficient"

    assert leaks_quota_language(_localised(reading.reason)), (
        "the reason text for an insufficient trait no longer trips the quota-language "
        "detector — if a caller ever showed it raw, the leak would go unnoticed"
    )
    assert not hasattr(TraitSufficiencyReading, "text")
    assert not hasattr(TraitSufficiencyReading, "question")
    assert set(TraitSufficiencyReading.__dataclass_fields__) == {
        "dimension_id",
        "status",
        "episodes",
        "occasions",
        "declined",
        "reason",
        "evidence",
    }


# --- things the payload calls out as worth getting right --------------------


def test_declined_trait_is_insufficient_and_not_chased(
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """Non-insistence (T40) applies to the floor: a declined trait reaches a
    terminal `insufficient` state with `declined=True`, and nothing about that
    verdict depends on — or invites — asking again."""
    log, ledger = profile
    ledger.decline("trait_declined", step="history", at="2026-08-10T09:00:00Z")

    reading = trait_sufficiency_reading(log, ledger, "trait_declined")

    assert reading.status == "insufficient"
    assert reading.declined is True
    assert reading.episodes == 0
    assert reading.reason.strip()

    # And the completeness contract holds over it: a declined trait is not a
    # violation, it is a resolved reading like any other insufficient one.
    fraction, violations = trait_evidence_sufficiency(
        ("trait_declined", "trait_other"),
        (
            reading,
            trait_sufficiency_reading(log, ledger, "trait_other"),
        ),
    )
    assert violations == [], violations
    assert fraction == 1.0


def test_a_denial_counts_toward_the_floor_same_as_an_affirmation(
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """A deliberate design decision (see the module docstring): an episode
    counts toward a trait's floor because the candidate's answer was evidence
    *about* that trait, not because of which way it pointed. Two occasions of
    evidence phrased as a denial clear the floor exactly as two affirming ones
    would — the floor protects evidentiary density, not direction."""
    log, ledger = profile
    log.append(
        recorded_at="2026-08-15T09:00:00Z",
        step="history",
        kind="episode",
        text="I have never really pushed to reopen a decision once it was made.",
        source="conversation",
        dimensions=("trait_deference",),
    )
    log.append(
        recorded_at="2026-08-16T09:00:00Z",
        step="history",
        kind="episode",
        text="Even when I disagreed strongly, I let the original call stand.",
        source="conversation",
        dimensions=("trait_deference",),
    )

    reading = trait_sufficiency_reading(log, ledger, "trait_deference")

    assert reading.episodes == 2
    assert reading.occasions == 2
    assert reading.status == "scored", (
        f"two occasions of evidence denying a trait did not clear the floor — {reading}"
    )


# --- required verification: deliberately break the contract two ways --------


def test_a_trait_scored_from_a_single_episode_is_rejected() -> None:
    """Breaking the contract by hand: a reading claiming `"scored"` from one
    episode on one occasion — built directly, bypassing `trait_sufficiency_reading`
    — must drop `trait_evidence_sufficiency` below 1.0 and name the offending
    dimension, exactly as if the real pipeline had produced it."""
    broken = TraitSufficiencyReading(
        dimension_id="trait_broken",
        status="scored",
        episodes=1,
        occasions=1,
        declined=False,
        reason="hand-built violation",
        evidence=("ev-000099",),
    )

    fraction, violations = trait_evidence_sufficiency(
        ("trait_broken", "trait_second"),
        (
            broken,
            TraitSufficiencyReading(
                dimension_id="trait_second",
                status="insufficient",
                episodes=0,
                occasions=0,
                declined=False,
                reason="no evidence yet",
            ),
        ),
    )

    assert fraction < 1.0, "a trait scored from a single episode was not rejected"
    assert violations != []
    assert "trait_broken" in violations[0]


def test_a_trait_left_neither_scored_nor_insufficient_is_rejected() -> None:
    """Breaking the contract by hand: a trait dimension the model names but no
    reading covers at all must be rejected — never silently dropped from the
    denominator, and never counted as satisfied."""
    only_reading = TraitSufficiencyReading(
        dimension_id="trait_covered",
        status="scored",
        episodes=3,
        occasions=3,
        declined=False,
        reason="clears the floor",
        evidence=("ev-000001", "ev-000002", "ev-000003"),
    )

    fraction, violations = trait_evidence_sufficiency(
        ("trait_covered", "trait_missing"), (only_reading,)
    )

    assert fraction < 1.0, "a trait left with no reading at all was not rejected"
    assert any("trait_missing" in v for v in violations), violations


# --- the metric must not pass vacuously --------------------------------------


def test_zero_trait_dimensions_does_not_report_full_sufficiency() -> None:
    """A run over zero trait dimensions must not report 1.0 — nothing to
    measure is not the same as full sufficiency, the same posture
    `elicit_extract.story_dimension_linkage` takes over an empty episode set."""
    fraction, violations = trait_evidence_sufficiency((), ())
    assert fraction != 1.0
    assert violations != []


def test_a_single_trait_dimension_does_not_report_full_sufficiency(
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """ "1.0 over one trait is not a measurement" (the payload's own words) —
    `MINIMUM_TRAITS` refuses a full mark over too small a denominator, even
    when the one trait present is genuinely, honestly scored."""
    log, ledger = profile
    log.append(
        recorded_at="2026-08-10T09:00:00Z",
        step="history",
        kind="episode",
        text=LONG_A,
        source="conversation",
        dimensions=("trait_lonely",),
    )
    log.append(
        recorded_at="2026-08-11T09:00:00Z",
        step="history",
        kind="episode",
        text=LONG_B,
        source="conversation",
        dimensions=("trait_lonely",),
    )
    reading = trait_sufficiency_reading(log, ledger, "trait_lonely")
    assert reading.status == "scored", reading

    fraction, violations = trait_evidence_sufficiency(("trait_lonely",), (reading,))

    assert fraction != 1.0
    assert violations != []
    assert MINIMUM_TRAITS >= 2


def test_trait_dimension_ids_excludes_non_trait_sides() -> None:
    """Only `candidate_trait` dimensions are ever measured — a `matched`
    dimension is not a trait, and must never inflate or deflate the
    denominator this metric divides by."""
    from jobsearch.dimensions import Cue, Dimension, Elicitation, LocalisedText, Question
    from jobsearch.dimensions import Extraction as _Extraction

    matched = Dimension(
        id="last_role_autonomy",
        kind="soft",
        polarity="bipolar",
        side="matched",
        label=LocalisedText(en="x", es="x", ca="x"),
        definition="a matched dimension, not a trait",
        elicitation=Elicitation(
            questions=[Question(id="q1", text=LocalisedText(en="x", es="x", ca="x"))]
        ),
        extraction=_Extraction(cues={"en": [Cue(pattern=r"placeholder", value=0.2)]}),
        methods_ref="METHODS.md#21-structured-behavioural-elicitation",
    )
    trait = _fixture_dimension("trait_only")

    ids = trait_dimension_ids([matched, trait])

    assert ids == ("trait_only",)


# --- the module's own writer, exercised end to end ---------------------------


def test_probe_trait_sufficiency_is_clean(tmp_path: Path) -> None:
    """The adversarial probe this module ships (`probe_trait_sufficiency`) runs
    clean over its own scripted scenarios — the same end-to-end check every
    other gated module's test suite runs over its own probe."""
    from jobsearch.trait_sufficiency import MINIMUM_CHECKS, probe_trait_sufficiency

    result = probe_trait_sufficiency(tmp_path / "profiles")

    assert result["checks_run"] >= MINIMUM_CHECKS
    assert result["failures"] == [], result["failures"]
    assert result["trait_evidence_sufficiency"] == 1.0
