"""The onboarding interview protocol: sequencing, manner, and the trait floor (T27).

T7 (`jobsearch.question_bank`) generates questions from the dimension model. T8
(`jobsearch.elicit_extract`) turns one answer into evidence. Neither is an
*interview* — T7's own docstring says so explicitly: "It does not decide *when*
a question is asked, does not sequence an interview... Wiring belongs to
whichever step actually puts questions in front of a candidate — T27." This
module is that wiring: which question comes next, what a negative answer is
followed by, when a personality question presumes a job that may not exist, and
when a trait has been asked about enough to be worth scoring.

**Two decisions this task's payload (`arsenal/tasks/_history/lo-609f.md`) left
open are settled by work that landed after it was written, not by this
module's own judgement**: T35 (`jobsearch.session`) already builds the whole
runtime around a session that is interrupted and resumed, and `spec-v2-steps.md`
step 3 already says scoring is idempotent across an interruption — so this is
built as several sittings with resumable state, never one long call. And the
two-episode/two-occasion floor (below) settles the second question by what the
floor's own wording means: "recorded on >= 2 separate occasions" cannot be true
of one sitting, so holding evidence across sittings is not a design choice here,
it is what the floor *is*.

**The measurable half of manner.** Empathy is mostly unmeasurable, but one part
of it is not: `run_interview` never lets the turn immediately following a
stored negative episode be an ordinary further question about the same subject.
It is always the fixed lesson-extraction turn (`LESSON_FOLLOWUP_TEXT`) —
"what did you take from that, and what would you do differently" — never
"tell me more about what went wrong". `negative_episode_followup_rate` re-walks
the transcript sequentially and checks exactly that adjacency, over the
transcript rather than trusting the driver's own bookkeeping, the same
posture `elicit_extract.story_dimension_linkage` takes toward `store_answer`.

**Valence is supplied, never guessed.** Nothing in this codebase calls a model,
so "was that episode a success or a failure" cannot be inferred from free text
by a regex the way a dimension cue is. `InterviewAnswer.valence` is a structured
field the caller sets — a human running the real conversation would know
whether the story it just heard was a failure, the same way `elicit_extract`
exposes `needs_review` instead of guessing at an answer it cannot classify.
Point 6 of the payload asks for exactly this: "expose a structured outcome
rather than guessing."

**The floor asks, it does not refuse, and the quota is never voiced.** Below
`MINIMUM_TRAIT_EPISODES`/`MINIMUM_TRAIT_OCCASIONS` for a trait dimension, the
driver looks for one more episode "the ordinary way" — `EXTRA_EPISODE_TEXT` asks
about "another time... a different job, or a different moment", never a count.
`test_quota_language_never_appears_in_generated_question_text` scans every
turn's text in all three corpus languages for the words that would leak it.
Only one extra ask is issued per trait per call to `run_interview`, and only for
a dimension that did **not** just receive its first episode in *this* call
(`newly_touched`) — which is the mechanical form of "several sittings, not one
long session": nothing in this module can chase a trait's second episode inside
the same sitting its first one arrived in, so the floor cannot be satisfied
except across a resumption.

**Non-insistence (T40) gates the floor, not just the first ask.** A declined
trait is `insufficient` forever, and the top-up loop below checks
`DeclineLedger.declines` before ever generating an extra-episode turn — a
subject the candidate opted out of is never chased for a second episode just
because a floor wants one. `TraitFloorState.declined` is what lets
`profile_coverage` count a declined trait as *resolved* rather than *owed*,
mirroring `candidate.CandidateConstraints.outstanding()`'s declined/unknown
split exactly.

**`trait_evidence_sufficiency` belongs to T49, not here.** `status/plan.md`'s
reconciliation table is explicit: T27 "carries" the floor, but the step 4
metric that scores a trait against it is T49's (D-4 records the contradiction
in the process specification this created; it is not resolved by this module
reassigning the metric to itself). What this module owns is `TraitFloorState` —
whether a trait's evidence clears the floor — which T49 can read once it
exists; it does not compute or gate on any number named `trait_evidence_sufficiency`.

**Coverage must not be satisfiable by asking nothing.** `profile_coverage`'s
denominator is T24's ten pinned constraint fields plus every dimension the
interview can reach — never fewer than ten, because `CandidateConstraints`
always carries all ten keys (`candidate.py`) — so a transcript that fills two
fields cannot report anything close to `1.0`; `probe_interview`'s
`"coverage does not reward a mostly-empty transcript"` check proves it with a
fixture that deliberately answers almost nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jobsearch.candidate import CandidateConstraints
from jobsearch.decline import DeclineLedger
from jobsearch.dimensions import (
    Cue,
    Dimension,
    Elicitation,
    Extraction,
    LocalisedText,
    Question,
    synthetic_levels,
)
from jobsearch.elicit_extract import ExtractionResult, store_answer
from jobsearch.profile import EvidenceLog, EvidenceRow
from jobsearch.question_bank import BankEntry, QuestionBank, build_bank

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T27.json"

# The two-episode/two-occasion floor (`status/plan.md` scope extension §3).
# "Occasion" is the calendar date an episode was *recorded* — not when the
# story happened (`occurred_at`) — because the property the floor protects is
# that the evidence itself was gathered across more than one sitting; two
# episodes about jobs five years apart, told in the same ten-minute call, are
# not two occasions of *interviewing*.
MINIMUM_TRAIT_EPISODES = 2
MINIMUM_TRAIT_OCCASIONS = 2
# Bounded, and one per call to `run_interview` (see the module docstring) —
# an unbounded chase would turn "asks, does not refuse" into a different kind
# of insistence, and a single call issuing several in a row would let one
# sitting satisfy the two-occasion half of the floor on its own.
MAX_EXTRA_EPISODE_ATTEMPTS = 3

TurnKind = Literal["retrospective", "trait", "lesson_followup", "extra_episode"]
Valence = Literal["positive", "negative", "mixed"]

# The two synthetic turns this module authors itself, never drawn from the
# dimension model's own bank (T7 owns that vocabulary; these are additions T27
# makes on top of it). Every language is checked for quota language by
# `probe_interview` — see `_QUOTA_MARKERS`.
LESSON_FOLLOWUP_TEXT = LocalisedText(
    en="What did you take from that, and what would you do differently next time?",
    es="¿Qué aprendiste de eso, y qué harías diferente la próxima vez?",
    ca="Què en vas treure, d'això, i què faries diferent la propera vegada?",
)
EXTRA_EPISODE_TEXT = LocalisedText(
    en="Can you think of another time — a different job, or a different moment — "
    "that shows the same thing?",
    es="¿Se te ocurre otro momento — otro trabajo, u otra ocasión distinta — que muestre lo mismo?",
    ca="Se t'acut un altre moment — una altra feina, o una altra ocasió diferent — "
    "que mostri el mateix?",
)


class InterviewError(Exception):
    """A caller asked this module to run an interview it cannot make sense of."""


# ---------------------------------------------------------------------------
# turns, answers, the transcript


@dataclass(frozen=True)
class InterviewTurn:
    """One question the interview puts to the candidate.

    `entry` is a real `BankEntry` in every case — for `"retrospective"`/`"trait"`
    turns it is one T7 generated from the dimension model; for
    `"lesson_followup"`/`"extra_episode"` turns it is synthesised by
    `_synthetic_entry` so `store_answer` (T8) has something to file the reply
    against, unconditionally requiring `dimension_id` the same way every real
    bank entry does — a follow-up this module cannot trace to a dimension is
    exactly the "story bank as a pile of prose" failure `elicit_extract`'s
    docstring names, just one layer up.
    """

    entry: BankEntry
    kind: TurnKind
    follow_up_to: str | None = None

    @property
    def turn_id(self) -> str:
        return self.entry.bank_id

    @property
    def dimension_id(self) -> str:
        return self.entry.dimension_id

    @property
    def text(self) -> LocalisedText:
        return self.entry.text


@dataclass(frozen=True)
class InterviewAnswer:
    """What the respondent said, plus the two structured signals this module
    cannot derive from the text itself — see the module docstring's "Valence
    is supplied, never guessed"."""

    text: str = ""
    valence: Valence | None = None
    declines: bool = False


@dataclass(frozen=True)
class InterviewStep:
    """One posed-and-answered turn, and what extraction did with it.

    `extraction` is `None` exactly when `answer.declines` — a declined turn is
    never handed to `store_answer` at all, which is what keeps a declined
    subject from being "stored anyway, just tagged declined": T40's ledger
    records the decline, T8 never sees the answer.
    """

    turn: InterviewTurn
    answer: InterviewAnswer
    extraction: ExtractionResult | None


Respondent = Callable[[InterviewTurn], InterviewAnswer]


# ---------------------------------------------------------------------------
# the first-job branch


def reachable_entries(
    bank: QuestionBank, dimensions: Sequence[Dimension], *, first_job: bool
) -> tuple[BankEntry, ...]:
    """Bank entries a candidate on this branch can actually be asked.

    `side == "matched"` is the structural signal, not a name or a keyword
    scan of the question text: every matched-side elicitation question in the
    committed model is phrased as "tell me about a time at work..." (they
    exist so a candidate's own words can later be compared to an ad's), which
    is exactly what makes them unaskable of someone who has never had a job.
    `candidate_trait` entries (personality, spare time) carry no such
    presupposition and are always reachable. This is what makes the branch
    "genuinely unreachable" rather than a text the driver merely chooses not
    to say: a bank entry filtered out here is filtered out for every caller of
    `run_interview`, not skipped by one code path that another could still
    reach it through.
    """
    by_id = {dimension.id: dimension for dimension in dimensions}

    def _reachable(entry: BankEntry) -> bool:
        dimension = by_id.get(entry.dimension_id)
        return not (first_job and dimension is not None and dimension.side == "matched")

    return tuple(entry for entry in bank.entries if _reachable(entry))


def _kind_for(dimension: Dimension | None) -> TurnKind:
    if dimension is not None and dimension.side == "candidate_trait":
        return "trait"
    return "retrospective"


def _synthetic_entry(dimension_id: str, prefix: str, n: int, text: LocalisedText) -> BankEntry:
    """A `BankEntry` this module authors itself — see `InterviewTurn`'s docstring."""
    return BankEntry(
        bank_id=f"{dimension_id}:{prefix}{n}",
        dimension_id=dimension_id,
        question_id=f"{prefix}{n}",
        order=0,
        text=text,
    )


def _next_n(asked: set[str], dimension_id: str, prefix: str) -> int:
    n = 1
    while f"{dimension_id}:{prefix}{n}" in asked:
        n += 1
    return n


# ---------------------------------------------------------------------------
# the trait floor


@dataclass(frozen=True)
class TraitFloorState:
    """One trait dimension's standing against the two-episode/two-occasion floor.

    `status` is always one of exactly two values — never a third, unresolved
    one — which is the property `test_every_trait_is_scored_or_explicitly_insufficient`
    holds this to. `reason` is for logs, tests, and T49 once it exists; it is
    never the text of a question put to the candidate (see `EXTRA_EPISODE_TEXT`,
    which says none of this).
    """

    dimension_id: str
    episodes: int
    occasions: int
    declined: bool
    status: Literal["sufficient", "insufficient"]
    reason: str


def _occasion(row: EvidenceRow) -> str:
    """The calendar date an episode was *recorded* — see the module docstring."""
    return row.recorded_at[:10]


def trait_floor_state(
    log: EvidenceLog, ledger: DeclineLedger, dimension_id: str
) -> TraitFloorState:
    """Where one trait dimension stands, read from the log and the ledger.

    Read from the log rather than from this module's own running count, the
    same discipline `story_dimension_linkage` applies to `store_answer`: a
    second writer that filed an episode against this dimension some other way
    still counts here, because the floor is a property of what is on disk, not
    of this driver's bookkeeping.
    """
    episodes = [
        row
        for row in log.effective_rows()
        if row.kind == "episode" and dimension_id in row.dimensions
    ]
    occasions = {_occasion(row) for row in episodes}
    declined = bool(ledger.declines(dimension_id))
    if declined:
        return TraitFloorState(
            dimension_id=dimension_id,
            episodes=len(episodes),
            occasions=len(occasions),
            declined=True,
            status="insufficient",
            reason="the candidate declined this subject; not raised again to fill the floor",
        )
    sufficient = (
        len(episodes) >= MINIMUM_TRAIT_EPISODES and len(occasions) >= MINIMUM_TRAIT_OCCASIONS
    )
    if sufficient:
        return TraitFloorState(
            dimension_id=dimension_id,
            episodes=len(episodes),
            occasions=len(occasions),
            declined=False,
            status="sufficient",
            reason=f"{len(episodes)} episodes across {len(occasions)} occasions clears the floor",
        )
    missing = []
    if len(episodes) < MINIMUM_TRAIT_EPISODES:
        missing.append("episodes")
    if len(occasions) < MINIMUM_TRAIT_OCCASIONS:
        missing.append("occasions")
    return TraitFloorState(
        dimension_id=dimension_id,
        episodes=len(episodes),
        occasions=len(occasions),
        declined=False,
        status="insufficient",
        reason=f"below the floor on {', '.join(missing)} ({len(episodes)} episode(s), "
        f"{len(occasions)} occasion(s) so far)",
    )


# ---------------------------------------------------------------------------
# the driver


def run_interview(
    dimensions: Sequence[Dimension],
    bank: QuestionBank,
    log: EvidenceLog,
    ledger: DeclineLedger,
    respondent: Respondent,
    *,
    first_job: bool,
    step: str = "history",
    now: str,
    asked: frozenset[str] = frozenset(),
) -> tuple[list[InterviewStep], frozenset[str]]:
    """One sitting: every reachable bank entry not yet asked, then one
    floor-driven top-up per trait dimension still short.

    Resumable by construction, not by a special mode: `asked` is the whole of
    what a caller needs to persist between sittings (via
    `jobsearch.session.SessionStore`, in `Position.covered`) and pass back in.
    Nothing here reads a clock beyond `now`, which the caller supplies for the
    same reason `jobsearch.profile` never stamps a derived file from the wall
    clock — a resumed sitting has its own `now`, not this module's opinion of
    the current time.

    `dimensions` is read twice over: `reachable_entries` for the first-job
    filter, and `_kind_for`/the top-up loop for which dimensions are traits.
    Passed in rather than loaded from disk, the same posture T7 and T8 take —
    there is no committed `candidate_trait` dimension yet (T26 is unbuilt), so
    every caller, this module's own probe included, supplies its own model.
    """
    by_id = {dimension.id: dimension for dimension in dimensions}
    transcript: list[InterviewStep] = []
    asked_now = set(asked)
    newly_touched: set[str] = set()

    def _pose(turn: InterviewTurn) -> InterviewStep:
        answer = respondent(turn)
        asked_now.add(turn.turn_id)
        if answer.declines:
            ledger.decline(turn.dimension_id, step=step, at=now)
            return InterviewStep(turn=turn, answer=answer, extraction=None)
        result = store_answer(
            log, turn.entry, answer.text, dimensions, ledger, step=step, recorded_at=now
        )
        return InterviewStep(turn=turn, answer=answer, extraction=result)

    def _maybe_lesson_followup(step_result: InterviewStep) -> None:
        if step_result.extraction is None or step_result.extraction.outcome != "stored":
            return
        newly_touched.update(step_result.extraction.dimensions)
        if step_result.answer.valence != "negative":
            return
        dimension_id = step_result.turn.dimension_id
        n = _next_n(asked_now, dimension_id, "lesson")
        entry = _synthetic_entry(dimension_id, "lesson", n, LESSON_FOLLOWUP_TEXT)
        if entry.bank_id in asked_now:
            return
        lesson_turn = InterviewTurn(
            entry=entry, kind="lesson_followup", follow_up_to=step_result.turn.turn_id
        )
        transcript.append(_pose(lesson_turn))

    for entry in reachable_entries(bank, dimensions, first_job=first_job):
        if entry.bank_id in asked_now:
            continue
        if not ledger.may_ask(entry.dimension_id, step=step):
            continue
        turn = InterviewTurn(entry=entry, kind=_kind_for(by_id.get(entry.dimension_id)))
        step_result = _pose(turn)
        transcript.append(step_result)
        _maybe_lesson_followup(step_result)

    for dimension in dimensions:
        if dimension.side != "candidate_trait":
            continue
        if dimension.id in newly_touched:
            # This sitting is what just gave it a first episode — the floor's
            # second occasion is next sitting's business, never this one's.
            continue
        state = trait_floor_state(log, ledger, dimension.id)
        if state.status == "sufficient" or state.declined:
            continue
        if not ledger.may_ask(dimension.id, step=step):
            continue
        n = _next_n(asked_now, dimension.id, "extra")
        if n > MAX_EXTRA_EPISODE_ATTEMPTS:
            continue
        entry = _synthetic_entry(dimension.id, "extra", n, EXTRA_EPISODE_TEXT)
        turn = InterviewTurn(entry=entry, kind="extra_episode")
        step_result = _pose(turn)
        transcript.append(step_result)
        _maybe_lesson_followup(step_result)

    return transcript, frozenset(asked_now)


# ---------------------------------------------------------------------------
# the measurable half of manner


def negative_episode_followup_rate(
    transcript: Sequence[InterviewStep],
) -> tuple[float, list[str]]:
    """Fraction of stored negative episodes immediately followed by the lesson turn.

    Walked over the transcript's own sequence, not over this module's
    bookkeeping — a driver that queued the right thing but somehow asked it
    later, or asked something else first, must be caught here exactly as if
    `run_interview` had never queued a follow-up at all. An empty transcript
    (no negative episode ever recorded) reports `(0.0, [...])`, matching
    `elicit_extract.story_dimension_linkage`'s refusal to call nothing-to-measure
    a pass — `probe_interview` supplies its own floor on how many negative
    episodes a run must contain before this number is trusted.
    """
    negative_indices = [
        index
        for index, step in enumerate(transcript)
        if step.extraction is not None
        and step.extraction.outcome == "stored"
        and step.answer.valence == "negative"
    ]
    if not negative_indices:
        return 0.0, ["no negative episode was recorded — nothing to measure"]
    violations: list[str] = []
    honoured = 0
    for index in negative_indices:
        turn_id = transcript[index].turn.turn_id
        following = transcript[index + 1] if index + 1 < len(transcript) else None
        if (
            following is not None
            and following.turn.kind == "lesson_followup"
            and following.turn.follow_up_to == turn_id
        ):
            honoured += 1
        else:
            got = following.turn.kind if following is not None else "nothing"
            violations.append(
                f"{turn_id}: the next turn was {got!r}, not a lesson-extraction follow-up — "
                "an interrogation, not an interview"
            )
    return honoured / len(negative_indices), violations


_QUOTA_MARKERS: tuple[str, ...] = (
    "two",
    "second occasion",
    "2 episodes",
    "2 occasions",
    "dos episodios",
    "dos ocasiones",
    "dues ocasions",
    "dos ocasions",
    "floor",
    "quota",
    "sufficient",
    "insufficient",
)

# A word list alone missed the phrasing most likely to leak the quota, because
# the leak is usually a *number*, not the word "two": "you have given me 1 of 2
# required examples" contains no marker above and states the quota outright.
# Any small integer sitting next to a counting word is treated as a leak — a
# turn that needs to say "3 things" can say "a few".
_QUOTA_COUNT_RE = re.compile(
    r"\b\d+\s*(?:of|/|de)\s*\d+\b"
    r"|\b\d+\s+(?:more\s+)?"
    r"(?:example|episode|story|stories|occasion|time|moment|ejemplo|episodio|ocasi[oó]n|"
    r"exemple|episodi|ocasi[oó])",
    re.IGNORECASE,
)


def leaks_quota_language(text: LocalisedText) -> list[str]:
    """Which corpus languages of `text` leak the floor — by word or by number.

    Checked against every generated turn's text by `probe_interview` — the
    payload's item 2 asks for a way to test this rather than trust the wording
    by inspection; this is that way, and it is a real check because
    `EXTRA_EPISODE_TEXT` and `LESSON_FOLLOWUP_TEXT` are read through it exactly
    like any other turn's text, not exempted as "the ones we wrote carefully".
    """
    hits = []
    for language in ("en", "es", "ca"):
        lowered = text.get(language).lower()
        if any(marker in lowered for marker in _QUOTA_MARKERS) or _QUOTA_COUNT_RE.search(lowered):
            hits.append(language)
    return hits


# ---------------------------------------------------------------------------
# coverage


@dataclass(frozen=True)
class ProfileCoverage:
    fraction: float
    filled: tuple[str, ...]
    missing: tuple[str, ...]


def profile_coverage(
    constraints: CandidateConstraints,
    dimensions: Sequence[Dimension],
    bank: QuestionBank,
    log: EvidenceLog,
    ledger: DeclineLedger,
    *,
    first_job: bool,
) -> ProfileCoverage:
    """`interview_profile_coverage` — T24's fields, plus every reachable dimension.

    T24's ten constraint fields are never asked by this module (that is T41,
    step 2 — T27 depends on T24's *schema*, not on T41's engine); they are read
    as given, because a real candidate reaches Constraints before or alongside
    History in the process graph, and the coverage this gate reports is of the
    *profile*, not of this module's own questions alone. A field counts filled
    when its state is not `"unknown"` — `"declined"` is a resolved answer under
    non-insistence, exactly as `CandidateConstraints.outstanding()` already
    treats it.

    A `candidate_trait` dimension counts filled only once `trait_floor_state`
    reports `"sufficient"` or `"declined"` — never merely "asked once" — which
    is the mechanical form of item 4's "must not be satisfiable by asking
    nothing": one episode on one occasion is real progress but is not yet a
    filled field. A `matched`/reachable dimension counts filled once it has
    >=1 episode (no floor — the floor is a trait-only property, `status/plan.md`
    scope extension §3 says "every trait", not every dimension).
    """
    filled: list[str] = []
    missing: list[str] = []

    for name, value in constraints.as_dict().items():
        (filled if value.state != "unknown" else missing).append(f"constraint:{name}")

    reachable = reachable_entries(bank, dimensions, first_job=first_job)
    reachable_dimension_ids = sorted({entry.dimension_id for entry in reachable})
    by_id = {dimension.id: dimension for dimension in dimensions}

    episode_counts: dict[str, int] = {}
    for row in log.effective_rows():
        if row.kind != "episode":
            continue
        for dimension_id in row.dimensions:
            episode_counts[dimension_id] = episode_counts.get(dimension_id, 0) + 1

    for dimension_id in reachable_dimension_ids:
        dimension = by_id.get(dimension_id)
        if dimension is not None and dimension.side == "candidate_trait":
            state = trait_floor_state(log, ledger, dimension_id)
            label = f"trait:{dimension_id}"
            if state.status == "sufficient" or state.declined:
                filled.append(label)
            else:
                missing.append(label)
        else:
            label = f"dimension:{dimension_id}"
            if episode_counts.get(dimension_id, 0) >= 1 or bool(ledger.declines(dimension_id)):
                filled.append(label)
            else:
                missing.append(label)

    total = len(filled) + len(missing)
    fraction = (len(filled) / total) if total else 0.0
    return ProfileCoverage(
        fraction=fraction, filled=tuple(sorted(filled)), missing=tuple(sorted(missing))
    )


@dataclass(frozen=True)
class InterviewStatus:
    coverage: ProfileCoverage
    trait_states: tuple[TraitFloorState, ...]
    negative_episode_followup_rate: float
    negative_episode_followup_violations: tuple[str, ...]


def interview_status(
    constraints: CandidateConstraints,
    dimensions: Sequence[Dimension],
    bank: QuestionBank,
    log: EvidenceLog,
    ledger: DeclineLedger,
    transcript: Sequence[InterviewStep],
    *,
    first_job: bool,
) -> InterviewStatus:
    """Everything this task's gate and its required tests read, in one answer —
    the same "one object, not several call sites" shape `step_runtime.Situation`
    already uses for the same reason."""
    coverage = profile_coverage(constraints, dimensions, bank, log, ledger, first_job=first_job)
    trait_states = tuple(
        trait_floor_state(log, ledger, dimension.id)
        for dimension in dimensions
        if dimension.side == "candidate_trait"
    )
    rate, violations = negative_episode_followup_rate(transcript)
    return InterviewStatus(
        coverage=coverage,
        trait_states=trait_states,
        negative_episode_followup_rate=rate,
        negative_episode_followup_violations=tuple(violations),
    )


# ---------------------------------------------------------------------------
# fixtures for the adversarial probe — no committed transcript corpus exists,
# and no committed `candidate_trait` dimension exists either (T26 is unbuilt),
# so (like T7's and T8's own probes) the measurement *is* a scripted scenario
# run over an in-memory model, never a scan over checked-in data.


def _fixture_dimension(
    dimension_id: str, *, side: Literal["matched", "candidate_trait"]
) -> Dimension:
    """One minimal, valid `Dimension`, in memory — mirrors `question_bank._synthetic_dimension`
    and `elicit_extract._fixture_dimension`, kept as its own copy for the same
    reason those two are not shared with each other: importing an underscore
    helper across modules couples probes that should evolve independently."""
    cues: dict[str, list[Cue]] = (
        {"en": [Cue(pattern=r"placeholder-never-matches", value=0.1)]} if side == "matched" else {}
    )
    return Dimension(
        id=dimension_id,
        kind="soft",
        polarity="bipolar",
        group="the_work",
        side=side,
        label=LocalisedText(en=dimension_id, es=dimension_id, ca=dimension_id),
        definition="a synthetic dimension used only to probe the interview driver",
        levels=synthetic_levels(),
        elicitation=Elicitation(
            questions=[
                Question(
                    id="q1",
                    text=LocalisedText(en="Tell me about it.", es="Cuéntame.", ca="Explica'm-ho."),
                )
            ]
        ),
        extraction=Extraction(cues=cues),  # type: ignore[arg-type]
        methods_ref="METHODS.md#21-structured-behavioural-elicitation",
    )


def _generous_answer(text: str = "", *, valence: Valence | None = "positive") -> InterviewAnswer:
    body = text or (
        "Here is a full, concrete account of something specific that happened, with "
        "enough detail that it is clearly about a real situation and not a placeholder."
    )
    return InterviewAnswer(text=body, valence=valence)


def _scripted_respondent(overrides: dict[str, InterviewAnswer]) -> Respondent:
    def respond(turn: InterviewTurn) -> InterviewAnswer:
        return overrides.get(turn.turn_id, _generous_answer())

    return respond


def probe_interview(root: Path) -> dict[str, Any]:
    """Run every scenario the module docstring and the payload name, and check them.

    One store per scenario (unlike `elicit_extract.probe_extraction`'s shared
    replay) because several scenarios here deliberately interrupt and resume a
    session, and mixing that with a shared decline history across scenarios
    would make one scenario's declines bleed into another's floor.
    """
    from jobsearch.identity import ProfileStore as _ProfileStore
    from jobsearch.identity import create_profile

    failures: list[str] = []
    checks = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    def fresh_store(handle: str) -> _ProfileStore:
        identity = create_profile(root, handle.replace("-", " ").title(), handle=handle)
        return _ProfileStore(root, identity.handle)

    matched = [_fixture_dimension("last_role_autonomy", side="matched")]
    traits = [
        _fixture_dimension("trait_creativity", side="candidate_trait"),
        _fixture_dimension("trait_ambition", side="candidate_trait"),
        _fixture_dimension("trait_curiosity", side="candidate_trait"),
    ]
    model = matched + traits
    bank = build_bank(model)

    def full_constraints() -> CandidateConstraints:
        # All ten pinned fields resolved — nine stated with a minimal valid
        # shape, one declined — never `unknown`, matching what a candidate who
        # reached Constraints (T41) before or alongside History would
        # actually have. Built from the concrete field classes directly
        # rather than guessed generically from each one's defaults, the same
        # way `candidate._baseline_constraints` builds its own fixture.
        from jobsearch.candidate import (
            Availability,
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

    # 1. A fully cooperative respondent, over two sittings, reaches full
    #    coverage — `test_scripted_respondent_yields_full_profile_coverage`'s
    #    own scenario, replayed here so the gate measures the same thing the
    #    test asserts.
    store = fresh_store("probe-full")
    log = EvidenceLog(store)
    ledger = DeclineLedger(store)
    overrides = {
        "last_role_autonomy:q1": _generous_answer(
            "A detailed story about a role that went badly, with clear reasons why.",
            valence="negative",
        )
    }
    respondent = _scripted_respondent(overrides)
    day1, asked = run_interview(
        model,
        bank,
        log,
        ledger,
        respondent,
        first_job=False,
        now="2026-08-10T09:00:00Z",
        asked=frozenset(),
    )
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
    transcript = day1 + day2
    status = interview_status(
        full_constraints(), model, bank, log, ledger, transcript, first_job=False
    )
    check(
        status.coverage.fraction >= 0.90,
        f"a cooperative two-sitting run only reached {status.coverage.fraction}",
    )
    check(
        status.negative_episode_followup_rate == 1.0,
        f"the negative episode in the cooperative run was not followed by a lesson turn: "
        f"{status.negative_episode_followup_violations}",
    )
    check(
        all(state.status == "sufficient" for state in status.trait_states),
        f"a cooperative two-sitting run left a trait short of the floor: {status.trait_states}",
    )
    check(
        len(day1) > 0 and len(day2) > 0,
        "the floor was met without needing a second sitting — it should be structurally impossible",
    )

    # 2. First-job branch: no retrospective (matched-dimension) turn is ever
    #    posed, checked from the transcript the driver actually produced.
    store = fresh_store("probe-firstjob")
    log = EvidenceLog(store)
    ledger = DeclineLedger(store)
    first_job_transcript, _ = run_interview(
        model,
        bank,
        log,
        ledger,
        _scripted_respondent({}),
        first_job=True,
        now="2026-08-10T09:00:00Z",
    )
    check(
        all(step.turn.kind != "retrospective" for step in first_job_transcript),
        "a first-job candidate was asked a retrospective (matched-dimension) question",
    )
    check(
        any(step.turn.kind == "trait" for step in first_job_transcript),
        "a first-job candidate was asked no personality questions at all",
    )

    # 3. A declined trait is never chased for a second episode.
    store = fresh_store("probe-declined")
    log = EvidenceLog(store)
    ledger = DeclineLedger(store)
    declining = _scripted_respondent({"trait_ambition:q1": InterviewAnswer(declines=True)})
    d1, asked_d = run_interview(
        model, bank, log, ledger, declining, first_job=True, now="2026-08-10T09:00:00Z"
    )
    d2, asked_d = run_interview(
        model,
        bank,
        log,
        ledger,
        declining,
        first_job=True,
        now="2026-08-11T09:00:00Z",
        asked=asked_d,
    )
    ambition_turns = [step for step in d1 + d2 if step.turn.dimension_id == "trait_ambition"]
    check(len(ambition_turns) == 1, f"a declined trait was asked about again: {ambition_turns}")
    ambition_state = trait_floor_state(log, ledger, "trait_ambition")
    check(
        ambition_state.declined and ambition_state.status == "insufficient",
        "a declined trait was not reported declined/insufficient",
    )

    # 4. Quota language never appears in a generated turn's text.
    leaks = [
        f"{step.turn.turn_id} ({language})"
        for step in transcript + first_job_transcript + d1 + d2
        for language in leaks_quota_language(step.turn.text)
    ]
    check(not leaks, f"quota language leaked into generated question text: {leaks}")

    # 5. Coverage does not reward a mostly-empty transcript — item 4's own
    #    demand, proven with a candidate who answered almost nothing.
    store = fresh_store("probe-sparse")
    log = EvidenceLog(store)
    ledger = DeclineLedger(store)
    sparse_constraints = CandidateConstraints()  # every field its default: unknown
    sparse_status = interview_status(
        sparse_constraints, model, bank, log, ledger, [], first_job=False
    )
    check(
        sparse_status.coverage.fraction < 0.3,
        f"an almost-empty profile reported {sparse_status.coverage.fraction} coverage",
    )

    # 6. `sufficient` never certifies fewer than the floor — the anti-vacuous
    #    check the payload's required verification exercises by breaking it.
    for state in status.trait_states:
        if state.status == "sufficient":
            checks += 1
            if state.episodes < MINIMUM_TRAIT_EPISODES or state.occasions < MINIMUM_TRAIT_OCCASIONS:
                failures.append(
                    f"{state.dimension_id} was reported sufficient with {state.episodes} "
                    f"episode(s) on {state.occasions} occasion(s)"
                )

    return {
        "interview_profile_coverage": round(status.coverage.fraction, 4),
        "negative_episode_followup_rate": status.negative_episode_followup_rate,
        "trait_states": [
            {
                "dimension_id": s.dimension_id,
                "episodes": s.episodes,
                "occasions": s.occasions,
                "declined": s.declined,
                "status": s.status,
            }
            for s in status.trait_states
        ],
        "checks_run": checks,
        "failures": failures,
    }


MINIMUM_CHECKS = 12


def measure() -> dict[str, Any]:
    """Run the adversarial scenario probe in a throwaway tree and report T27's gate."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="jobsearch-t27-") as tmp:
        return probe_interview(Path(tmp) / "profiles")


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure T27's gate and record it."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.interview [--check] [--write-evidence [PATH]]` -> T27's gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence file",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/T27.json)",
    )
    args = parser.parse_args(argv[1:])

    measured = measure() if args.check else write_evidence(Path(args.write_evidence))
    print(json.dumps(measured, ensure_ascii=False))

    if measured["checks_run"] < MINIMUM_CHECKS:
        print(
            f"only {measured['checks_run']} checks ran (floor {MINIMUM_CHECKS}) — a clean "
            "score without exercising the scenarios is not a measurement",
            file=sys.stderr,
        )
        return 3

    violations = list(measured["failures"])
    if measured["interview_profile_coverage"] < 0.90:
        violations.append(
            f"interview_profile_coverage = {measured['interview_profile_coverage']} (want >= 0.90)"
        )
    for violation in violations:
        print(violation, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
