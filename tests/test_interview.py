"""T27 — the onboarding interview protocol: sequencing, manner, and the floor.

`status/plan.md`'s T27 row names three RED tests, all below:
`test_every_trait_is_scored_or_explicitly_insufficient`,
`test_scripted_respondent_yields_full_profile_coverage`, and
`test_every_negative_episode_gets_a_lesson_followup`. The payload
(`arsenal/tasks/_history/lo-609f.md`) adds a fourth,
`test_first_job_branch_skips_retrospective_questions`. The rest of this file
holds the two properties the "Required verification" section of the task asks
to see fail on purpose: a further probing question instead of a lesson
follow-up, and a trait scored sufficient from a single episode.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.candidate import (
    Availability,
    CandidateConstraints,
    EmploymentMode,
    LanguageLevel,
    Languages,
    Location,
    PayCountry,
    Reach,
    Relocation,
    Salary,
    TaxCountry,
    WorkAuthorisation,
)
from integral.decline import DeclineLedger
from integral.dimensions import Dimension, LocalisedText
from integral.elicit_extract import MIN_ANSWER_CHARS
from integral.identity import ProfileStore, create_profile
from integral.interview import (
    EXTRA_EPISODE_TEXT,
    LESSON_FOLLOWUP_TEXT,
    MAX_EXTRA_EPISODE_ATTEMPTS,
    MINIMUM_TRAIT_EPISODES,
    MINIMUM_TRAIT_OCCASIONS,
    InterviewAnswer,
    InterviewStep,
    InterviewTurn,
    _fixture_dimension,
    _synthetic_entry,
    interview_status,
    leaks_quota_language,
    negative_episode_followup_rate,
    profile_coverage,
    reachable_entries,
    run_interview,
    trait_floor_state,
)
from integral.profile import EvidenceLog
from integral.question_bank import build_bank

LONG_POSITIVE = (
    "We shipped a whole redesign in six weeks and I owned the rollout plan end "
    "to end, including the rollback we ended up not needing."
)
LONG_NEGATIVE = (
    "That role fell apart within four months — the team was reorganised twice "
    "and I ended up reporting to someone who had never done the job."
)
LONG_NEUTRAL = (
    "Outside work I've been teaching myself woodworking, mostly small furniture "
    "repairs, and I read the changelog of every library I depend on."
)


@pytest.fixture
def model() -> list[Dimension]:
    return [
        _fixture_dimension("last_role_autonomy", side="matched"),
        _fixture_dimension("last_role_pace", side="matched"),
        _fixture_dimension("trait_creativity", side="candidate_trait"),
        _fixture_dimension("trait_ambition", side="candidate_trait"),
    ]


@pytest.fixture
def profile(tmp_path: Path) -> tuple[EvidenceLog, DeclineLedger]:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    store = ProfileStore(root, identity.handle)
    return EvidenceLog(store), DeclineLedger(store)


def _full_constraints() -> CandidateConstraints:
    """All ten T24 fields resolved — none `unknown` — the state a candidate who
    reached Constraints (T41) before or alongside History would actually have."""
    return CandidateConstraints(
        languages=Languages(
            state="stated", levels=(LanguageLevel(language="en", level="professional"),)
        ),
        location=Location(state="stated", country="ES", accepts_onsite_in_country=True),
        relocation=Relocation(state="stated", willingness="no"),
        salary=Salary(state="stated", floor=40000, currency="EUR"),
        availability=Availability(state="stated", earliest_start="2026-09-01"),
        work_authorisation=WorkAuthorisation(state="stated", authorised_countries=("ES",)),
        employment_mode=EmploymentMode(state="stated", accepted=("employed",)),
        pay_country=PayCountry(state="stated", countries=("ES",)),
        tax_country=TaxCountry(state="stated", country="ES"),
        reach=Reach(state="declined"),
    )


# --- the RED tests named in the payload and the plan row --------------------


def test_scripted_respondent_yields_full_profile_coverage(
    model: list[Dimension], profile: tuple[EvidenceLog, DeclineLedger]
) -> None:
    """A fully cooperative respondent, over two sittings, clears the >= 0.90 gate.

    Two sittings, not one: the floor cannot be met inside a single call to
    `run_interview` (see the module docstring's "several sittings" reasoning),
    so this is also the test that proves the floor is not accidentally
    satisfiable in one long session.
    """
    log, ledger = profile
    bank = build_bank(model)

    def respondent(turn: InterviewTurn) -> InterviewAnswer:
        return InterviewAnswer(text=LONG_POSITIVE, valence="positive")

    day1, asked = run_interview(
        model, bank, log, ledger, respondent, first_job=False, now="2026-08-10T09:00:00Z"
    )
    assert day1, "the first sitting produced no turns at all"
    day2, asked = run_interview(
        model,
        bank,
        log,
        ledger,
        respondent,
        first_job=False,
        now="2026-08-11T09:00:00Z",
        asked=asked,
    )
    assert day2, "coverage was reached without a second sitting — the floor should forbid that"

    status = interview_status(
        _full_constraints(), model, bank, log, ledger, day1 + day2, first_job=False
    )
    assert status.coverage.fraction >= 0.90, status.coverage
    assert status.coverage.missing == (), status.coverage.missing


def test_every_negative_episode_gets_a_lesson_followup(
    model: list[Dimension], profile: tuple[EvidenceLog, DeclineLedger]
) -> None:
    """A question that follows a stored negative episode is always the lesson
    turn, never a further question about the failure itself — the "difference
    between an interview and an interrogation" the payload names."""
    log, ledger = profile
    bank = build_bank(model)

    overrides = {
        "last_role_autonomy:q1": InterviewAnswer(text=LONG_NEGATIVE, valence="negative"),
        "last_role_pace:q1": InterviewAnswer(text=LONG_NEGATIVE, valence="negative"),
    }

    def respondent(turn: InterviewTurn) -> InterviewAnswer:
        return overrides.get(turn.turn_id, InterviewAnswer(text=LONG_POSITIVE, valence="positive"))

    transcript, _ = run_interview(
        model, bank, log, ledger, respondent, first_job=False, now="2026-08-10T09:00:00Z"
    )

    negative_steps = [
        step
        for step in transcript
        if step.extraction is not None
        and step.extraction.outcome == "stored"
        and step.answer.valence == "negative"
    ]
    assert len(negative_steps) == 2, (
        "the fixture did not record the two negative episodes it set up"
    )

    rate, violations = negative_episode_followup_rate(transcript)
    assert violations == [], violations
    assert rate == 1.0

    # And each lesson turn is visibly the lesson turn, not merely counted as
    # one by the metric's own bookkeeping — checked against the transcript
    # directly, the way the metric itself is checked against it above.
    lesson_turns = [step.turn for step in transcript if step.turn.kind == "lesson_followup"]
    assert len(lesson_turns) == 2
    assert {turn.follow_up_to for turn in lesson_turns} == {
        step.turn.turn_id for step in negative_steps
    }
    for turn in lesson_turns:
        assert turn.text == LESSON_FOLLOWUP_TEXT


def test_first_job_branch_skips_retrospective_questions(
    model: list[Dimension], profile: tuple[EvidenceLog, DeclineLedger]
) -> None:
    """A candidate with no work history is never asked what their last role
    was like — checked from the transcript the driver actually produced, not
    from the filtering logic in isolation."""
    log, ledger = profile
    bank = build_bank(model)

    def respondent(turn: InterviewTurn) -> InterviewAnswer:
        return InterviewAnswer(text=LONG_NEUTRAL, valence="positive")

    transcript, _ = run_interview(
        model, bank, log, ledger, respondent, first_job=True, now="2026-08-10T09:00:00Z"
    )

    assert transcript, "a first-job candidate was asked nothing at all"
    assert all(step.turn.kind != "retrospective" for step in transcript), [
        step.turn.turn_id for step in transcript if step.turn.kind == "retrospective"
    ]
    assert all(step.turn.dimension_id != "last_role_autonomy" for step in transcript)
    assert all(step.turn.dimension_id != "last_role_pace" for step in transcript)
    # Personality questions are unaffected by the branch.
    assert any(step.turn.kind == "trait" for step in transcript)

    # And the same property holds for the reachability function directly —
    # belt-and-braces over the same guarantee `run_interview` relies on.
    reachable = reachable_entries(bank, model, first_job=True)
    assert all(
        entry.dimension_id not in {"last_role_autonomy", "last_role_pace"} for entry in reachable
    )
    not_first_job = reachable_entries(bank, model, first_job=False)
    assert any(entry.dimension_id == "last_role_autonomy" for entry in not_first_job), (
        "the same entries must be reachable for a candidate who has worked before"
    )


def test_every_trait_is_scored_or_explicitly_insufficient(
    model: list[Dimension], profile: tuple[EvidenceLog, DeclineLedger]
) -> None:
    """Every `candidate_trait` dimension ends the run in exactly one of two
    states — never left unclassified — and a declined trait is `insufficient`
    with a reason that says so, not silently dropped from the report."""
    log, ledger = profile
    bank = build_bank(model)

    # trait_creativity: cooperates fully across two sittings -> sufficient.
    # trait_ambition: declines outright -> insufficient, declined.
    overrides_day1 = {"trait_ambition:q1": InterviewAnswer(declines=True)}

    def respondent(turn: InterviewTurn) -> InterviewAnswer:
        return overrides_day1.get(
            turn.turn_id, InterviewAnswer(text=LONG_POSITIVE, valence="positive")
        )

    day1, asked = run_interview(
        model, bank, log, ledger, respondent, first_job=True, now="2026-08-10T09:00:00Z"
    )
    day2, asked = run_interview(
        model,
        bank,
        log,
        ledger,
        respondent,
        first_job=True,
        now="2026-08-11T09:00:00Z",
        asked=asked,
    )

    states = {
        dimension.id: trait_floor_state(log, ledger, dimension.id)
        for dimension in model
        if dimension.side == "candidate_trait"
    }
    assert set(states) == {"trait_creativity", "trait_ambition"}

    creativity = states["trait_creativity"]
    assert creativity.status == "sufficient", creativity
    assert creativity.episodes >= MINIMUM_TRAIT_EPISODES
    assert creativity.occasions >= MINIMUM_TRAIT_OCCASIONS
    assert creativity.reason.strip()

    ambition = states["trait_ambition"]
    assert ambition.status == "insufficient", ambition
    assert ambition.declined is True
    assert ambition.reason.strip()

    # Completeness: no state is missing, and every one lands in exactly one
    # of the two buckets `TraitFloorState.status` allows.
    assert {state.status for state in states.values()} <= {"sufficient", "insufficient"}

    # And non-insistence held: the declined trait was asked about exactly
    # once across both sittings, never chased for a second episode.
    ambition_turns = [step for step in day1 + day2 if step.turn.dimension_id == "trait_ambition"]
    assert len(ambition_turns) == 1, ambition_turns


# --- things the payload calls out as worth getting right --------------------


def test_quota_language_never_appears_in_generated_question_text(
    model: list[Dimension], profile: tuple[EvidenceLog, DeclineLedger]
) -> None:
    """No generated turn's text — in any corpus language — ever names the
    floor, the count, or the word "quota". A candidate must never be told
    they owe two episodes."""
    log, ledger = profile
    bank = build_bank(model)

    def respondent(turn: InterviewTurn) -> InterviewAnswer:
        return InterviewAnswer(text=LONG_POSITIVE, valence="positive")

    day1, asked = run_interview(
        model, bank, log, ledger, respondent, first_job=False, now="2026-08-10T09:00:00Z"
    )
    day2, _ = run_interview(
        model,
        bank,
        log,
        ledger,
        respondent,
        first_job=False,
        now="2026-08-11T09:00:00Z",
        asked=asked,
    )

    leaks = {step.turn.turn_id: leaks_quota_language(step.turn.text) for step in day1 + day2}
    leaks = {turn_id: langs for turn_id, langs in leaks.items() if langs}
    assert leaks == {}

    # And the two canned turns this module authors are clean on their own,
    # independent of whether the fixture above ever happened to trigger them.
    assert leaks_quota_language(LESSON_FOLLOWUP_TEXT) == []
    assert leaks_quota_language(EXTRA_EPISODE_TEXT) == []


def test_declined_trait_is_not_revisited_to_satisfy_its_episode_count(
    model: list[Dimension], profile: tuple[EvidenceLog, DeclineLedger]
) -> None:
    """T40's non-insistence applies to the floor, not only to the first ask —
    a declined subject is never chased for a second episode just because a
    trait floor wants one."""
    log, ledger = profile
    bank = build_bank(model)

    def respondent(turn: InterviewTurn) -> InterviewAnswer:
        if turn.dimension_id == "trait_ambition":
            return InterviewAnswer(declines=True)
        return InterviewAnswer(text=LONG_POSITIVE, valence="positive")

    asked: frozenset[str] = frozenset()
    all_steps: list[InterviewStep] = []
    for now in ("2026-08-10T09:00:00Z", "2026-08-11T09:00:00Z", "2026-08-12T09:00:00Z"):
        steps, asked = run_interview(
            model, bank, log, ledger, respondent, first_job=True, now=now, asked=asked
        )
        all_steps.extend(steps)

    ambition_steps = [step for step in all_steps if step.turn.dimension_id == "trait_ambition"]
    assert len(ambition_steps) == 1, "a declined trait was asked about more than once"
    assert ambition_steps[0].answer.declines is True

    state = trait_floor_state(log, ledger, "trait_ambition")
    assert state.declined is True
    assert state.status == "insufficient"


# --- required verification: deliberately break both guarantees --------------


def test_a_further_probe_instead_of_a_lesson_followup_is_detected() -> None:
    """Breaking the manner guarantee by hand: a transcript where the turn
    after a negative episode is an ordinary further question, not the lesson
    turn, must drop `negative_episode_followup_rate` below 1.0 and name the
    offending turn."""
    from integral.dimensions import LocalisedText
    from integral.elicit_extract import ExtractionResult
    from integral.question_bank import BankEntry

    negative_entry = BankEntry(
        bank_id="last_role_pace:q1",
        dimension_id="last_role_pace",
        question_id="q1",
        order=0,
        text=LocalisedText(en="x", es="x", ca="x"),
    )
    probe_entry = BankEntry(
        bank_id="last_role_pace:probe_deeper",
        dimension_id="last_role_pace",
        question_id="probe_deeper",
        order=1,
        text=LocalisedText(
            en="Tell me more about what went wrong.",
            es="Cuéntame más sobre qué salió mal.",
            ca="Explica'm més sobre què va anar malament.",
        ),
    )
    negative_turn = InterviewTurn(entry=negative_entry, kind="retrospective")
    # This is the break: a further probe into the failure, not the lesson
    # turn — exactly the interrogation the module docstring says never happens.
    interrogating_turn = InterviewTurn(entry=probe_entry, kind="retrospective")

    transcript = [
        InterviewStep(
            turn=negative_turn,
            answer=InterviewAnswer(text=LONG_NEGATIVE, valence="negative"),
            extraction=ExtractionResult("stored", ("last_role_pace",), "stored"),
        ),
        InterviewStep(
            turn=interrogating_turn,
            answer=InterviewAnswer(text=LONG_NEGATIVE, valence="negative"),
            extraction=ExtractionResult("stored", ("last_role_pace",), "stored"),
        ),
    ]

    rate, violations = negative_episode_followup_rate(transcript)
    assert rate < 1.0, "a further probe after a negative episode was not detected"
    assert violations != []
    assert "last_role_pace:q1" in violations[0]


def test_a_trait_cannot_be_reported_sufficient_from_a_single_episode(
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """Breaking the floor guarantee by hand: one episode on one occasion must
    report `insufficient`, and the two floor constants are what stand between
    that and a false `sufficient` — moving either one down to 1 (simulating a
    regression) is exactly what would let a single episode pass, which is why
    both are asserted here rather than trusted from the constant's name."""
    log, ledger = profile

    log.append(
        recorded_at="2026-08-10T09:00:00Z",
        step="history",
        kind="episode",
        text=LONG_POSITIVE,
        source="conversation",
        dimensions=("trait_creativity",),
    )

    state = trait_floor_state(log, ledger, "trait_creativity")
    assert state.episodes == 1
    assert state.occasions == 1
    assert state.status == "insufficient", (
        "a single episode on a single occasion was reported sufficient — "
        f"the floor did not hold: {state}"
    )
    assert MINIMUM_TRAIT_EPISODES >= 2, "the episode floor was weakened below the specification"
    assert MINIMUM_TRAIT_OCCASIONS >= 2, "the occasion floor was weakened below the specification"


# --- coverage must not be satisfiable by asking nothing ---------------------


def test_coverage_over_an_unanswered_transcript_is_far_from_full(
    model: list[Dimension], profile: tuple[EvidenceLog, DeclineLedger]
) -> None:
    """A candidate who has resolved none of T24's fields and answered no
    interview question at all must not read as anywhere close to covered —
    the anti-vacuous-gate property this repository has been bitten by before."""
    log, ledger = profile
    bank = build_bank(model)

    empty_constraints = CandidateConstraints()  # every field defaults to unknown
    coverage = profile_coverage(empty_constraints, model, bank, log, ledger, first_job=False)
    assert coverage.fraction < 0.2, coverage
    assert coverage.filled == ()


def test_extra_episode_attempts_are_bounded(
    model: list[Dimension], profile: tuple[EvidenceLog, DeclineLedger]
) -> None:
    """A respondent who never gives a usable second episode does not get
    chased forever — `MAX_EXTRA_EPISODE_ATTEMPTS` bounds the top-up loop, and
    the trait ends `insufficient` rather than stalling the interview."""
    log, ledger = profile
    bank = build_bank(model)

    too_short = "short"
    assert len(too_short) < MIN_ANSWER_CHARS

    def respondent(turn: InterviewTurn) -> InterviewAnswer:
        if turn.dimension_id == "trait_ambition" and turn.kind != "trait":
            return InterviewAnswer(text=too_short)
        return InterviewAnswer(text=LONG_POSITIVE, valence="positive")

    asked: frozenset[str] = frozenset()
    for n in range(MAX_EXTRA_EPISODE_ATTEMPTS + 3):
        _, asked = run_interview(
            model,
            bank,
            log,
            ledger,
            respondent,
            first_job=True,
            now=f"2026-08-{10 + n:02d}T09:00:00Z",
            asked=asked,
        )

    extra_turn_ids = [turn_id for turn_id in asked if turn_id.startswith("trait_ambition:extra")]
    assert 0 < len(extra_turn_ids) <= MAX_EXTRA_EPISODE_ATTEMPTS, extra_turn_ids

    state = trait_floor_state(log, ledger, "trait_ambition")
    assert state.status == "insufficient"
    assert state.declined is False


def test_synthetic_entry_ids_are_traceable_to_a_dimension() -> None:
    """`_synthetic_entry` never produces a follow-up unlinked to a dimension —
    the same "story bank as a pile of prose" guarantee T8 enforces at the
    write path, held here at the point this module authors its own entries."""
    entry = _synthetic_entry("trait_creativity", "extra", 1, EXTRA_EPISODE_TEXT)
    assert entry.dimension_id == "trait_creativity"
    assert entry.bank_id == "trait_creativity:extra1"


def _localised(text: str) -> LocalisedText:
    """One string in all three corpus languages — the leak wording is what is
    under test here, not the translation."""
    return LocalisedText(en=text, es=text, ca=text)


def test_a_numeric_quota_leak_is_detected_not_just_the_word_two() -> None:
    """The floor is never voiced, and the check for that was a word list — but
    the phrasing most likely to leak a quota is a *number*, not the word "two".
    "You have given me 1 of 2 required examples" contains no listed marker and
    states the quota outright, so the guarantee held only against the wordings
    somebody had already thought of.

    Asserted alongside two ordinary turns, because a detector that fires on
    everything would satisfy the leak cases on its own and would make every
    real turn unusable.
    """
    leak = _localised("You have given me 1 of 2 required examples.")
    spanish_leak = _localised("Necesito 2 ejemplos más para esto.")
    ordinary = _localised("Tell me about another time that mattered to you.")

    assert leaks_quota_language(leak)
    assert leaks_quota_language(spanish_leak)
    assert not leaks_quota_language(ordinary)
    assert not leaks_quota_language(EXTRA_EPISODE_TEXT)
    assert not leaks_quota_language(LESSON_FOLLOWUP_TEXT)
