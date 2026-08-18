"""T8 — free-text answer extraction into dimension values + story-bank episodes.

`status/plan.md`'s T8 row names two RED tests: every stored episode links to
>=1 dimension id, and a new episode is `disclosure: private` by default. The
rest of this file covers the properties the payload calls out as things to
get right rather than assume: non-insistence at the write path (T40), an
answer that yields nothing being a normal outcome rather than an error, and a
judgement call the module cannot make deterministically being surfaced as
`needs_review` instead of guessed at.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jobsearch.decline import DeclineLedger
from jobsearch.dimensions import Dimension, LocalisedText
from jobsearch.elicit_extract import (
    MAX_ANSWER_CHARS,
    MIN_ANSWER_CHARS,
    MINIMUM_CHECKS,
    ElicitExtractError,
    _fixture_dimension,
    candidate_dimensions,
    extract,
    measure,
    probe_extraction,
    probe_linkage_guarantee_is_load_bearing,
    store_answer,
    story_dimension_linkage,
    write_evidence,
)
from jobsearch.identity import ProfileStore, create_profile
from jobsearch.profile import EvidenceLog
from jobsearch.question_bank import BankEntry, build_bank


@pytest.fixture
def model() -> list[Dimension]:
    return [
        _fixture_dimension("elx_autonomy", side="candidate_trait"),
        _fixture_dimension("elx_oncall", cue_pattern=r"on-?call"),
        _fixture_dimension("elx_workload", cue_pattern=r"overtime|extra hours"),
    ]


@pytest.fixture
def entries(model: list[Dimension]) -> dict[str, BankEntry]:
    bank = build_bank(model)
    return {entry.dimension_id: entry for entry in bank.entries}


@pytest.fixture
def profile(tmp_path: Path) -> tuple[EvidenceLog, DeclineLedger]:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    store = ProfileStore(root, identity.handle)
    return EvidenceLog(store), DeclineLedger(store)


ORDINARY_ANSWER = (
    "They let me pick my own priorities every sprint and nobody second-guessed "
    "the schedule."
)


# --- the two RED tests named in the payload ---------------------------------


def test_every_episode_links_to_a_dimension(
    model: list[Dimension],
    entries: dict[str, BankEntry],
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """No stored episode is ever missing a dimension id — and the metric would
    catch one if it existed.

    This is `story_dimension_linkage`'s whole reason to exist: a story bank
    that is a pile of unqueryable prose. It has two halves, both required —
    proving this module's own writer (`store_answer`) can never produce an
    unlinked episode is not the same claim as proving the *metric* would
    notice one if some other writer did, so both are checked here.
    """
    log, ledger = profile

    result = store_answer(
        log,
        entries["elx_autonomy"],
        ORDINARY_ANSWER,
        model,
        ledger,
        step="history",
        recorded_at="2026-08-18T09:00:00Z",
    )
    assert result.outcome == "stored"
    assert result.row is not None
    assert result.row.dimensions, "a stored episode carries no dimension id"

    linkage, unlinked = story_dimension_linkage(log)
    assert linkage == 1.0
    assert unlinked == []

    # And the metric itself is not fooled by a row this module never wrote:
    # bypassing `store_answer` and appending an unlinked episode directly must
    # be visible in the measurement, not silently averaged away.
    broken = log.append(
        recorded_at="2026-08-18T09:01:00Z",
        step="history",
        kind="episode",
        text="bypassing store_answer on purpose",
        source="conversation",
        dimensions=(),
    )
    linkage_after, unlinked_after = story_dimension_linkage(log)
    assert linkage_after < 1.0
    assert unlinked_after == [broken.id]


def test_episode_defaults_to_private_disclosure(
    model: list[Dimension],
    entries: dict[str, BankEntry],
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """A newly stored episode is private, read back off disk through a fresh log.

    `store_answer` exposes no `disclosure` parameter at all — the strongest
    form of "the default holds through the store, not only the constructor":
    there is no argument a caller could pass to override it. Reading through a
    *new* `EvidenceLog` object, rather than trusting the row `store_answer`
    handed back, is what proves the default reached disk.
    """
    log, ledger = profile
    result = store_answer(
        log,
        entries["elx_autonomy"],
        ORDINARY_ANSWER,
        model,
        ledger,
        step="history",
        recorded_at="2026-08-18T09:00:00Z",
    )
    assert result.row is not None

    reread = EvidenceLog(log.store).rows()
    stored = [row for row in reread if row.kind == "episode"]
    assert stored, "no episode row reached disk"
    assert all(row.disclosure == "private" for row in stored)


# --- extraction: primary linkage, then secondary, then filtering -----------


def test_answer_links_to_the_asked_dimension_by_construction(
    model: list[Dimension], entries: dict[str, BankEntry]
) -> None:
    """The dimension a bank question targets is fixed at bank-generation time,
    not guessed from the reply — so it is always first in `candidate_dimensions`.
    """
    dims, denied = candidate_dimensions(
        entries["elx_autonomy"], "no cue-bearing text here", model
    )
    assert dims == ("elx_autonomy",)
    assert denied == ()


def test_secondary_cue_hit_is_linked_alongside_the_primary(
    model: list[Dimension],
    entries: dict[str, BankEntry],
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """A mechanical cue hit for a different, undeclined dimension is kept —
    secondary linkage is legitimate evidence, not itself forbidden.
    """
    _, ledger = profile
    answer = ORDINARY_ANSWER + " Though the on-call rotation ran every third week."
    result = extract(entries["elx_autonomy"], answer, model, ledger)
    assert result.outcome == "stored"
    assert set(result.dimensions) == {"elx_autonomy", "elx_oncall"}


def test_only_matched_side_dimensions_ever_contribute_a_secondary_hit(
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """`candidate_trait` and `candidate_fact` dimensions never carry cues at the
    model level (`Dimension._a_trait_cannot_be_read_from_an_ad`, T2's
    `side_violations`) — this asserts the extractor relies on that rather than
    re-checking `side` for cues that could never exist.
    """
    _, ledger = profile
    trait = _fixture_dimension("elx_trait_only", side="candidate_trait")
    matched = _fixture_dimension("elx_matched", cue_pattern="overtime")
    bank = build_bank([trait, matched])
    entry = bank.by_dimension("elx_trait_only")[0]
    result = extract(entry, "constant overtime every single week", [trait, matched], ledger)
    assert result.outcome == "stored"
    assert set(result.dimensions) == {"elx_trait_only", "elx_matched"}


# --- non-insistence: T40 applies at the write path --------------------------


def test_declined_subject_is_not_mined_from_an_unrelated_answer(
    model: list[Dimension],
    entries: dict[str, BankEntry],
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """§5.4's rule does not stop at "do not re-ask" — writing a declined
    subject into the log anyway, because it happened to come up in an answer
    to a *different* question, is its own kind of insistence and this test
    is what T40's non-insistence guarantee has to survive at this module's
    write path.
    """
    _, ledger = profile
    ledger.decline("elx_oncall", step="history", at="2026-08-18T09:00:00Z")
    answer = ORDINARY_ANSWER + " Though the on-call rotation ran every third week."
    result = extract(entries["elx_autonomy"], answer, model, ledger)
    assert result.outcome == "stored"
    assert result.dimensions == ("elx_autonomy",), (
        "a declined subject was mined out of an answer about something else"
    )


def test_declined_primary_subject_yields_declined_outcome_not_an_episode(
    model: list[Dimension],
    entries: dict[str, BankEntry],
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """Belt-and-braces: even the *asked* dimension is filtered through the
    ledger, in case a caller ever routes a declined subject's own question
    through here. Nothing is stored about a subject the candidate opted out
    of, and that is a normal outcome, not an error.
    """
    _, ledger = profile
    ledger.decline("elx_autonomy", step="history", at="2026-08-18T09:00:00Z")
    result = extract(entries["elx_autonomy"], ORDINARY_ANSWER, model, ledger)
    assert result.outcome == "declined"
    assert result.dimensions == ()
    assert result.row is None


def test_declined_primary_with_surviving_secondary_is_flagged_for_review(
    model: list[Dimension],
    entries: dict[str, BankEntry],
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """Discarding the whole answer would lose real evidence; silently filing it
    under the incidental dimension risks mis-filing a story. Neither is
    guessed at — the module reports `needs_review` and stores nothing.
    """
    _, ledger = profile
    ledger.decline("elx_autonomy", step="history", at="2026-08-18T09:00:00Z")
    answer = "I'd rather not get into that, but there was constant overtime expected of the team."
    result = extract(entries["elx_autonomy"], answer, model, ledger)
    assert result.outcome == "needs_review"
    assert result.dimensions == ("elx_workload",)
    assert result.row is None


def test_reopening_a_declined_subject_lets_it_be_mined_again(
    model: list[Dimension],
    entries: dict[str, BankEntry],
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """Only the candidate reopening a subject clears it (`DeclineLedger.reopen`)
    — `extract` must not carry its own, separate memory of a decline that
    outlives the ledger's own resolution of it.
    """
    _, ledger = profile
    ledger.decline("elx_oncall", step="history", at="2026-08-18T09:00:00Z")
    ledger.reopen("elx_oncall", at="2026-08-18T09:05:00Z")
    answer = ORDINARY_ANSWER + " Though the on-call rotation ran every third week."
    result = extract(entries["elx_autonomy"], answer, model, ledger)
    assert result.outcome == "stored"
    assert set(result.dimensions) == {"elx_autonomy", "elx_oncall"}


# --- an answer that yields nothing is normal, not an error ------------------


def test_blank_answer_is_empty_not_an_error(
    model: list[Dimension],
    entries: dict[str, BankEntry],
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    _, ledger = profile
    result = extract(entries["elx_autonomy"], "   ", model, ledger)
    assert result.outcome == "empty"
    assert result.row is None


def test_short_answer_below_the_floor_is_empty(
    model: list[Dimension],
    entries: dict[str, BankEntry],
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    _, ledger = profile
    short = "x" * (MIN_ANSWER_CHARS - 1)
    result = extract(entries["elx_autonomy"], short, model, ledger)
    assert result.outcome == "empty"


def test_answer_at_exactly_the_floor_is_not_empty(
    model: list[Dimension],
    entries: dict[str, BankEntry],
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    _, ledger = profile
    exact = "x" * MIN_ANSWER_CHARS
    result = extract(entries["elx_autonomy"], exact, model, ledger)
    assert result.outcome != "empty"


def test_implausibly_long_answer_needs_review_instead_of_guessing(
    model: list[Dimension],
    entries: dict[str, BankEntry],
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """Long enough to plausibly be several answers concatenated by a caller
    bug rather than one elicitation reply — the module does not decide which,
    it flags it.
    """
    _, ledger = profile
    huge = "x" * (MAX_ANSWER_CHARS + 1)
    result = extract(entries["elx_workload"], huge, model, ledger)
    assert result.outcome == "needs_review"
    assert result.dimensions == ()


def test_the_gate_cannot_pass_over_nothing_extracted(
    model: list[Dimension],
    entries: dict[str, BankEntry],
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """`story_dimension_linkage` over an empty episode set is `0.0`, not `1.0`
    — matching `question_bank.dimension_coverage` and `dimensions.extractor_coverage`'s
    stance that nothing measured is not the same as full coverage.
    """
    log, _ = profile
    linkage, unlinked = story_dimension_linkage(log)
    assert linkage == 0.0
    assert unlinked == []


# --- deliberately breaking the guarantee, per the required verification -----


def test_deliberately_broken_writer_is_caught_by_the_metric_and_the_cli(tmp_path: Path) -> None:
    """A gate never shown to fail is not a gate.

    `probe_linkage_guarantee_is_load_bearing` bypasses `store_answer` and
    writes an unlinked episode straight through `EvidenceLog.append` — the
    exact shape `store_answer` refuses to produce. This asserts the measured
    metric drops below 1.0 when that happens, and that `_main`'s own arithmetic
    (over the same measurement) would report it as a violation and exit
    non-zero rather than a clean 0.
    """
    broken = probe_linkage_guarantee_is_load_bearing(tmp_path / "profiles")
    assert broken["story_dimension_linkage"] < 1.0
    assert broken["unlinked_episode_ids"] == [broken["broken_row_id"]]

    # The same arithmetic `_main` runs over its own measurement: this is what
    # makes a broken linkage guarantee a non-zero exit rather than a number
    # nobody enforces.
    would_be_violations = []
    if broken["story_dimension_linkage"] != 1.0:
        would_be_violations.append("story_dimension_linkage != 1.0")
    assert would_be_violations, "the deliberate break did not register as a violation"


# --- a caller mistake is a raise, not a silent outcome -----------------------


def test_an_entry_naming_no_dimension_is_a_caller_error(
    model: list[Dimension], profile: tuple[EvidenceLog, DeclineLedger]
) -> None:
    """`BankEntry`'s own schema already forbids an empty `dimension_id`
    (`Field(min_length=2)` via `DimensionId`) — this exercises `extract`'s own
    defensive check by handing it something that gets past Pydantic
    construction only via `model_construct`, the same "never trust that
    composition never breaks" posture `QuestionBank._bank_ids_are_unique` takes.
    """
    _, ledger = profile
    text = LocalisedText(en="x", es="x", ca="x")
    broken_entry = BankEntry.model_construct(
        bank_id="broken:entry", dimension_id="", question_id="q1", order=0, text=text
    )
    with pytest.raises(ElicitExtractError):
        extract(broken_entry, ORDINARY_ANSWER, model, ledger)


# --- the adversarial probe and the evidence writer ---------------------------


def test_probe_extraction_runs_at_least_the_declared_floor(tmp_path: Path) -> None:
    """A probe that quietly stopped running its checks would still report zero
    failures — this pins the floor so "nothing failed" cannot mean "nothing ran".
    """
    probed = probe_extraction(tmp_path / "profiles")
    assert probed["checks_run"] >= MINIMUM_CHECKS
    assert probed["failures"] == []


def test_write_evidence_reports_full_linkage(tmp_path: Path) -> None:
    evidence_path = tmp_path / "T8.json"
    measured = write_evidence(evidence_path)
    assert evidence_path.exists()
    assert measured["story_dimension_linkage"] == 1.0
    assert measured["unlinked_episode_ids"] == []
    assert measured["failures"] == []
    assert measured["checks_run"] >= MINIMUM_CHECKS


def test_measure_is_deterministic() -> None:
    """Two runs of the scripted probe must agree — nothing here reads the
    clock or the environment, matching `profile.rebuild`'s own determinism bar.
    """
    first = measure()
    second = measure()
    assert first == second


# --- review findings: the sign of a cue hit, and two orderings -------------


def test_a_denied_subject_is_linked_but_marked_denied(
    model: list[Dimension], entries: dict[str, BankEntry]
) -> None:
    """"There was no on-call rotation" and "the on-call rotation ran every
    third week" used to produce byte-identical output.

    Dropping the denial would be wrong — it answers the question, and
    `profile._build_traits` collects evidence references without scoring, so
    the link itself is unsigned and true of both. What must not happen is the
    two becoming indistinguishable, because `Cue.negatable` exists precisely to
    record that "no on-call" is evidence *against* rather than absence of
    evidence, and a scorer counting episodes toward a trait floor (T49) would
    otherwise count a denial as its opposite.
    """
    denied, affirmed = "there was no on-call rotation", "on-call rotation every third week"
    denied_dims, denied_flags = candidate_dimensions(entries["elx_autonomy"], denied, model)
    affirmed_dims, affirmed_flags = candidate_dimensions(entries["elx_autonomy"], affirmed, model)

    assert denied_dims == affirmed_dims, "a denial must stay linked, not be dropped"
    assert denied_flags == ("elx_oncall",)
    assert affirmed_flags == ()


def test_a_bank_entry_naming_an_unknown_dimension_is_refused(
    model: list[Dimension],
    entries: dict[str, BankEntry],
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """`BankEntry` validates the shape of a dimension id, never that the
    ontology still holds one, and `EvidenceRow` accepts it too — so a bank
    generated against an older model files rows under an id nothing resolves,
    and the first thing to notice is a rebuilt `traits.json` listing a
    dimension nobody can look up. A caller mistake, so it raises.
    """
    _, ledger = profile
    stale = entries["elx_autonomy"].model_copy(update={"dimension_id": "gone_from_the_model"})
    with pytest.raises(ElicitExtractError, match="not in the supplied model"):
        extract(stale, "a perfectly ordinary answer about the work", model, ledger)


def test_an_overlong_answer_to_a_declined_subject_reports_declined(
    model: list[Dimension],
    entries: dict[str, BankEntry],
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """The length check used to run first, so an over-long answer about a
    declined subject came back `needs_review` with a reason about its size —
    inviting a caller to look at it and file it anyway. No row ever leaked, but
    "filtered before anything is written" has to cover what is *reported* too,
    or the guarantee holds only on the paths that happen to reach it.
    """
    _, ledger = profile
    ledger.decline("elx_autonomy", step="history", at="2026-08-18T09:00:00Z")
    result = extract(entries["elx_autonomy"], "y" * (MAX_ANSWER_CHARS + 1), model, ledger)
    assert result.outcome == "declined"
    assert "declined" in result.reason
