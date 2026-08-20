"""Continuous profile capture across every candidate-facing surface (T28).

**The gap this closes.** T8 (`elicit_extract`) and T41 (`constraints_step`)
already turn a candidate's answer into an evidence row, but only when the
answer arrives through the onboarding interview or the constraints turn. Say
something about yourself anywhere else — why you are ruling an offer out,
what an ad's tone made you think, how a mock interview felt — and, before this
module, it went nowhere: the profile filled at onboarding and stood still
everywhere after. `status/plan.md`'s T28 row and `status/specification.md` §5.4
both say the profile is supposed to be a *pure function of everything the
candidate ever said*, not of everything they said in one particular step.

**`profile_capture_coverage`.** The gate (`arsenal/tasks/_history/lo-62f9.md`) is
the fraction of candidate-facing surfaces that accept free text and append at
least one evidence row when they are actually exercised. "A surface that takes
input and records nothing fails the gate — that is the whole point," and the
corollary the payload also asks for: a surface that takes **no** free text at
all must not be forced into the same denominator, or the gate would go vacuous
the moment enough silent surfaces outnumbered the leaky ones.

## How the surface set is derived, and why

**The set of step ids is read live from `status/spec-v2-steps.json`**
(`integral.process_spec.load_steps`) — the same machine-readable model
`integral.step_runtime` already treats as authoritative for "which artefacts
does the candidate's journey name". A fourteenth step landing in that file
shows up here automatically; nothing in this module holds its own count of
"there are thirteen steps" the way `question_bank.dimension_coverage`'s
docstring warns against ("a checker holding its own copy of *how many* there
are is correct the day it is written and silently wrong on the next one
added"). `_classification_problems` re-asserts this on every measurement,
the same drift guard `step_runtime.unknown_artefacts` runs for its own table:
a step id the JSON names that this module has not classified — or a
classification for an id the JSON no longer has — is a **measured violation**,
not a silent omission.

**Whether a step's protocol puts free text about the candidate in front of a
writer at all is now declared in the model itself (S12).**
`status/spec-v2-steps.json`'s `Step.accepts_candidate_free_text` answers it —
`automatic` does not (only "understanding" is `true`, i.e. has no candidate
present, but says nothing about the twelve conversational steps, several of
which — Ranking: *"No questions; this step presents"*; Identify: *"No evidence
row is written for an unidentified session"* — structurally take no free text
about the candidate despite being ordinary, `automatic: false` conversations).

Before S12 this module carried the judgement itself, as a hand-maintained
`ACCEPTS_CANDIDATE_FREE_TEXT: dict[str, bool]`, one entry per step, each
commented with the sentence of `spec-v2-steps.md` that settled it. That map is
gone: `measure_coverage` and `_classification_problems` below now read
`step.accepts_candidate_free_text` directly off the `StepList` `load_steps()`
returns, and there is no local fallback for a step that leaves it undeclared —
a module that read the model but kept a fallback map would not have moved
anything. The field is optional (`None` = undeclared, never coerced to
`False`) precisely so a new step can land without one: `None` is caught by
name in `unclassified_free_text_steps` (this module's own S12 gate,
`unclassified_free_text_steps == 0`) and in `_classification_problems`, both
in the same "derived, not a silent list" shape `step_runtime.DETECTORS` gives
`unknown_artefacts` for artefact presence — now checked against a schema field
instead of a second Python file a step author had to remember to edit.

**Which `True`-classified steps are actually *measured* is derived a third
way — from what this module can drive, not from a step's own (possibly stale)
`gate.state`.** `gate.state` is recorded per *step*, but this codebase already
has a case where a step's own driver is `not_implemented` while a *different*,
already-shipped task supplies a reachable free-text path underneath it: the
Feedback step's own conversational driver (T21) is `not_implemented`, yet
`integral.lifecycle.transition` (S5, shipped) has taken a free-text `reason`
parameter from day one — exactly the "rejecting an offer with a reason"
surface the payload names, silently going nowhere until this module wraps it
(`capture_offer_decision_reason`, below). Trusting `gate.state` would have
excluded Feedback from the denominator and left that gap unmeasured forever.
So a step counts as *measured* iff this module has actually registered a
driver for it in `SURFACE_DRIVERS` — code that runs the real, unmodified
production function with a scripted free-text answer and reports whether an
evidence row came out — never a claim taken on trust. A `True`-classified step
with no driver yet is reported separately as `pending_implementation`: nothing
has been built for it, so there is nothing to have dropped its input, and
counting it as a failure would conflate "not yet built" with "built and
broken" — the exact conflation item 3 of the payload's "also think about"
warns the denominator must not make.

## Privacy — enforced at the write path, not merely defaulted

`capture()` exposes **no `disclosure` parameter**, mirroring `elicit_extract.
store_answer`'s own discipline exactly: `EvidenceLog.append` already defaults
`disclosure="private"`, and the strength of "the default holds through the
store" is that no caller of this module's primitive has anywhere to pass a
different value even by accident. `test_captured_evidence_defaults_to_private`
proves it by reading a captured row back through a *fresh* `EvidenceLog`, the
same posture T8's own test takes toward `store_answer`.

**Non-insistence (T40) is honoured at incidental capture too — the payload's
own "also think about" item 1.** A subject the candidate declined is at even
more risk here than in an asked answer: nobody is asking, so there is no
question to have skipped, and the temptation is to assume anything volunteered
in passing is fair game. It is not. `capture()` filters every dimension it is
offered through `DeclineLedger.declines` before writing, exactly the guard
`elicit_extract._undeclined` applies to an *asked* reply's incidental hits —
reused here for an unasked one. If every supplied dimension turns out declined,
nothing is written at all, matching `elicit_extract.extract`'s `"declined"`
outcome; a row with a merely-empty `dimensions` tuple would look identical to
one nobody had anything to say about, and that difference matters to a later
reader trying to explain a gap in the record.

## Retraction (T38) — the payload's "also think about" item 2

Every row this module writes goes through `EvidenceLog.append`, T6's own
substrate — the identical call `elicit_extract.store_answer` and
`constraints_step.resolve` already make. Retraction (`integral.retraction.
retract`) suppresses a row by id, over the log itself, with no knowledge of
which step or module wrote it. There is therefore no gap to close here: a row
captured by this module is retractable the moment it exists, by the same
mechanism as any other evidence row, and `test_retraction_reaches_captured_rows`
demonstrates it rather than asserting it by inspection — the same "do not
trust the promise" posture `elicit_extract.probe_linkage_guarantee_is_load_bearing`
takes toward its own guarantee.

## Provenance

Every row carries `step` (which surface), `recorded_at` (when) and `source`
(the four-way `conversation | cv_document | offer_reaction | interview` split
T6 already defines) — the first two of T28's own "which surface, when, in
response to what". The third was unmet, for any capture whose subject is a
specific artefact rather than a question, until **D-8**: `EvidenceRow.about`
(`integral.profile.EvidenceSubject`) now names it, and `capture_offer_decision_
reason` sets it unconditionally. The function already holds the `Offer` it is
transitioning, so building `EvidenceSubject(kind="offer", id=offer.id)` costs
nothing at the call site and — unlike a parameter a caller would have to
remember to pass — cannot be forgotten. `capture()`'s own generic primitive
takes `about` too, for the one caller here that has an artefact to name; a
caller answering a bank question passes nothing, and `captures_without_a_
subject` (below) is built to leave that case alone rather than demand a
subject nothing names — see that function's own docstring for the line it
draws between the two.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from integral.constraints_step import CandidateTurn
from integral.constraints_step import resolve as resolve_constraints
from integral.cv_store import ConversationTurn, CVMaster, add_conversation_entry
from integral.decline import DeclineLedger
from integral.dimensions import (
    Cue,
    Dimension,
    Elicitation,
    Extraction,
    Language,
    LocalisedText,
    Question,
    Side,
    synthetic_levels,
)
from integral.elicit_extract import store_answer
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import LifecycleRecord, save_lifecycle_offer, track_new_offer, transition
from integral.offers import Offer, OfferStatus, connect_manual
from integral.process_spec import StepList, load_steps
from integral.profile import (
    EvidenceLog,
    EvidenceRow,
    EvidenceSubject,
    Kind,
    Precision,
    Source,
    rebuild,
)
from integral.question_bank import build_bank

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T28.json"
# S12's own evidence file — `unclassified_free_text_steps`, over the live
# model rather than T28's adversarial probe, so it can be read (and fails)
# independently of whether the probe's throwaway tree even runs.
DEFAULT_S12_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "S12.json"

SurfaceStatus = Literal["captured", "dropped", "no_free_text", "pending_implementation"]


class ProfileCaptureError(Exception):
    """This module's own classification disagrees with the live step model."""


# ---------------------------------------------------------------------------
# S12: the declaration itself now lives on the model — see the module
# docstring's derivation note. `unclassified_free_text_steps` and
# `_classification_problems` below are the two checks that used to compare
# `ACCEPTS_CANDIDATE_FREE_TEXT`'s key set against the live step list; now that
# there is only one copy of the fact, they read `step.accepts_candidate_
# free_text` straight off `StepList` instead.


def unclassified_free_text_steps(steps: StepList) -> list[str]:
    """Step ids in the live model with no free-text declaration — S12's own
    gate metric (`unclassified_free_text_steps == 0`).

    `None` is "not yet decided", never coerced to "decided no" (that is
    `False`, a real answer this function does not report): a new step landing
    with the field unset must show up here by name, the same way an
    undeclared step used to show up as a missing `ACCEPTS_CANDIDATE_FREE_TEXT`
    entry — the judgement moved into the schema, it did not disappear.
    """
    return sorted(step.id for step in steps.steps if step.accepts_candidate_free_text is None)


def _classification_problems(steps: StepList) -> list[str]:
    """Where the live model's declarations / `SURFACE_DRIVERS` disagree with
    each other — see the module docstring.

    Three checks, the same symmetric-difference shape
    `step_runtime.unknown_artefacts` runs for its own table: a step the JSON
    names with no free-text declaration at all (`unclassified_free_text_
    steps`, folded in here too so T28's own gate — not just S12's — notices
    it), a driver registered for a step declared `False` or left undeclared (a
    driver implies free text is accepted — the declaration would be self-
    contradicting), and a driver for a step id the JSON does not name at all.
    """
    live_ids = {step.id for step in steps.steps}
    declared = {step.id: step.accepts_candidate_free_text for step in steps.steps}
    problems: list[str] = [
        f"{step_id!r} is a step in {steps.source} with no free-text declaration"
        for step_id in unclassified_free_text_steps(steps)
    ]
    for orphan in sorted(set(SURFACE_DRIVERS) - live_ids):
        problems.append(f"{orphan!r} has a driver registered but is not a step in {steps.source}")
    for contradiction in sorted(
        step_id for step_id in SURFACE_DRIVERS if not declared.get(step_id)
    ):
        problems.append(
            f"{contradiction!r} has a driver registered but is not declared "
            "accepts_candidate_free_text=True"
        )
    return problems


# ---------------------------------------------------------------------------
# the generic capture primitive every surface driver below calls through


def capture(
    log: EvidenceLog,
    ledger: DeclineLedger,
    *,
    step: str,
    kind: Kind,
    text: str,
    source: Source,
    dimensions: Sequence[str] = (),
    recorded_at: str,
    occurred_at: str | None = None,
    occurred_precision: Precision | None = None,
    about: EvidenceSubject | None = None,
) -> EvidenceRow | None:
    """Append one row of free text as evidence, or refuse — never widen anything.

    No `disclosure` parameter; refuses a blank `text` (nothing was said); and
    filters `dimensions` through `ledger.declines` before writing — see the
    module docstring's privacy section for why each of the three matters.
    `kind="retraction"` is refused: a retraction names the row it suppresses
    (`integral.profile.EvidenceRow`) and has no business going through a
    generic "the candidate said something" primitive.

    `about` (D-8) names the artefact this capture was in response to, when
    there is one — see the module docstring's Provenance section. It is a
    caller-supplied `EvidenceSubject`, never derived here: this primitive has
    no way to know what a candidate's words were about, only the caller that
    prompted them does (`capture_offer_decision_reason`, below, always
    supplies one because it always holds the `Offer` in question).
    """
    if kind == "retraction":
        raise ProfileCaptureError("capture() does not write retractions — use integral.retraction")
    stripped = text.strip()
    if not stripped:
        return None
    kept = tuple(dimension for dimension in dimensions if not ledger.declines(dimension))
    if dimensions and not kept:
        return None
    return log.append(
        recorded_at=recorded_at,
        step=step,
        kind=kind,
        text=stripped,
        source=source,
        dimensions=kept,
        occurred_at=occurred_at,
        occurred_precision=occurred_precision,
        about=about,
    )


# ---------------------------------------------------------------------------
# the one new integration this task adds: an offer decision's free-text reason
# (payload example: "rejecting an offer with a reason")


def capture_offer_decision_reason(
    store: ProfileStore,
    offer: Offer,
    record: LifecycleRecord,
    to_status: OfferStatus,
    *,
    at: str,
    reason: str | None,
) -> tuple[Offer, LifecycleRecord, EvidenceRow | None]:
    """Transition one offer (S5, unmodified) and capture its free-text reason.

    Composes `integral.lifecycle.transition` rather than editing it: S5's own
    docstring draws the ownership line ("T11 owns the `Offer` schema... this
    module is the 'seam'"), and this task's brief leaves `lifecycle.py`
    untouched — see the report. `reason=None`, or a reason that is only
    whitespace, is not a broken surface: nothing was said, so there is nothing
    to have dropped (the module docstring's `no_free_text` vs. `dropped`
    distinction, applied to one call rather than one step).

    `source="offer_reaction"` — the row is in response to a decision about an
    offer, T6's own vocabulary for exactly this (`integral.profile.Source`).
    `about=EvidenceSubject(kind="offer", id=offer.id)` (D-8) — *which* offer,
    set unconditionally rather than left to a caller, since this function
    already holds the one artefact the reason could possibly be about.
    """
    new_offer, new_record = transition(offer, record, to_status, at=at, reason=reason)
    row: EvidenceRow | None = None
    if reason is not None and reason.strip():
        log = EvidenceLog(store)
        ledger = DeclineLedger(store)
        row = capture(
            log,
            ledger,
            step="feedback",
            kind="statement",
            text=reason,
            source="offer_reaction",
            recorded_at=at,
            about=EvidenceSubject(kind="offer", id=offer.id),
        )
    return new_offer, new_record, row


# ---------------------------------------------------------------------------
# surface drivers — each runs real, unmodified production code with a
# scripted candidate answer and reports the evidence row it produced, or
# `None`. Fixtures built in memory, no YAML, no disk — the same posture
# `elicit_extract._fixture_dimension`/`interview._fixture_dimension` take for
# the same reason: no committed `candidate_trait` dimension exists yet (T26).


def _capture_fixture_dimension(dimension_id: str, *, side: Side) -> Dimension:
    """One minimal, valid `Dimension`, in memory — kept as its own copy rather
    than importing another module's underscore-prefixed helper, the same
    "probes should evolve independently" reasoning `elicit_extract`'s and
    `interview`'s own copies give for not sharing with each other."""
    cues: dict[Language, list[Cue]] = (
        {"en": [Cue(pattern=r"placeholder-never-matches", value=0.1)]} if side == "matched" else {}
    )
    return Dimension(
        id=dimension_id,
        kind="soft",
        polarity="bipolar",
        group="the_work",
        side=side,
        label=LocalisedText(en=dimension_id, es=dimension_id, ca=dimension_id),
        definition="a synthetic dimension used only to probe continuous capture",
        levels=synthetic_levels(),
        elicitation=Elicitation(
            questions=[
                Question(
                    id="q1",
                    text=LocalisedText(en="Tell me about it.", es="Cuéntame.", ca="Explica-m'ho."),
                )
            ]
        ),
        extraction=Extraction(cues=cues),
        methods_ref="METHODS.md#21-structured-behavioural-elicitation",
    )


def _drive_intake(store: ProfileStore) -> EvidenceRow | None:
    """Step 1 — S4's real `cv_store.add_conversation_entry`, over one
    experience entry told by a candidate who arrived with no CV.

    **This driver does not write a row — one already exists by the time it
    runs.** `add_conversation_entry`'s own module docstring settles the
    question this task's payload raised on purpose ("does intake capture
    actually reach the evidence log, or only `master.json`?"): every
    conversation-sourced section entry already appends a row to
    `profile/evidence.jsonl` through `integral.profile.EvidenceLog`
    directly, as an unconditional part of building `cv/master.json` — S4
    shipped that wiring; this task only had to notice it was there. So the
    driver calls the real production function and reads back the row it
    already wrote, via `ConversationTurn.evidence_id` on the entry
    `add_conversation_entry` hands back — the same "run the real function,
    then find the row it produced" shape `_drive_constraints` uses for
    `resolve_constraints`'s own `evidence_id`.

    **Why this does not also call `capture()`.** Every driver that wraps a
    production path with *no* write of its own routes it through `capture()`
    so non-insistence (T40) and the private disclosure default apply — that
    is what `capture_offer_decision_reason` is, the one new integration this
    module's docstring names, for a surface (`lifecycle.transition`) that
    genuinely wrote nothing before T28. Intake is not that case:
    `add_conversation_entry` already appends the row itself. Calling
    `capture()` here too would file the *same* candidate statement twice —
    exactly the "write the row twice just to satisfy a counter" duplication
    the payload says to decide about deliberately rather than default into.
    One utterance, one row; `test_a_conversational_intake_answer_reaches_the_
    evidence_log` pins the count, not just the presence.

    **The real gap this surfaces, reported rather than patched here:**
    `add_conversation_entry`/`set_conversation_scalar` (`integral.cv_store`)
    write straight to `EvidenceLog.append` with no `DeclineLedger` filtering
    at all — unlike `elicit_extract.store_answer` and `constraints_step.
    resolve`, which both filter every dimension through `DeclineLedger`
    before writing (`elicit_extract._undeclined`). So non-insistence is not
    yet honoured on this specific surface: a candidate who has twice declined
    a subject and then, while building their CV from nothing, volunteers
    something touching it anyway, gets it filed regardless. Closing that
    means adding decline-filtering to S4's own write path in `cv_store.py` —
    a change to that module's established contract and beyond a size-S "wire
    a driver into `SURFACE_DRIVERS`" task — so it is named here, in the
    driver that found it, rather than silently absorbed into this change.
    """
    master = add_conversation_entry(
        store,
        CVMaster(),
        "experience",
        {"title": "Warehouse Team Lead", "organisation": "Northgate Logistics"},
        said="I ran the night shift at Northgate Logistics for about two "
        "years, mostly warehouse work, before the site closed down.",
        recorded_at="2026-08-18T09:00:30Z",
    )
    turn = master.experience[-1].provenance[0]
    if not isinstance(turn, ConversationTurn):
        return None
    log = EvidenceLog(store)
    return next((row for row in log.rows() if row.id == turn.evidence_id), None)


def _drive_constraints(store: ProfileStore) -> EvidenceRow | None:
    """Step 2 — T41's real `resolve`, one stated field."""
    result = resolve_constraints(
        store,
        [
            CandidateTurn(
                field="reach",
                action="state",
                value={"modes": ["remote"]},
                text="Remote only, from here on.",
            )
        ],
        now="2026-08-18T09:00:00Z",
    )
    matched = next((r for r in result.resolutions if r.field == "reach"), None)
    if matched is None or matched.evidence_id is None:
        return None
    log = EvidenceLog(store)
    return next((row for row in log.rows() if row.id == matched.evidence_id), None)


def _drive_history(store: ProfileStore) -> EvidenceRow | None:
    """Step 3 — T8's real `store_answer`, over a matched-side dimension."""
    dimension = _capture_fixture_dimension("pc_history_probe", side="matched")
    entry = build_bank([dimension]).by_dimension("pc_history_probe")[0]
    log = EvidenceLog(store)
    ledger = DeclineLedger(store)
    result = store_answer(
        log,
        entry,
        "They let me redesign the whole onboarding flow myself, and nobody "
        "second-guessed the plan once I'd shown my reasoning.",
        [dimension],
        ledger,
        step="history",
        recorded_at="2026-08-18T09:01:00Z",
    )
    return result.row


def _drive_traits(store: ProfileStore) -> EvidenceRow | None:
    """Step 4 — T27's top-up mechanism, driven through T8's `store_answer`
    exactly as `interview.run_interview` does for a trait-side dimension."""
    dimension = _capture_fixture_dimension("pc_trait_probe", side="candidate_trait")
    entry = build_bank([dimension]).by_dimension("pc_trait_probe")[0]
    log = EvidenceLog(store)
    ledger = DeclineLedger(store)
    result = store_answer(
        log,
        entry,
        "Another time this came up was a completely different job, years "
        "later, and I did the same thing again without thinking about it.",
        [dimension],
        ledger,
        step="traits",
        recorded_at="2026-08-18T09:02:00Z",
    )
    return result.row


def _drive_feedback(store: ProfileStore) -> EvidenceRow | None:
    """Step 10 — the new integration, `capture_offer_decision_reason`."""
    offer = connect_manual("Warehouse Operative. Permanent night shifts, on-site only.")
    record = track_new_offer(offer, at="2026-08-18T09:03:00Z")
    save_lifecycle_offer(store, offer, record)
    _, _, row = capture_offer_decision_reason(
        store,
        offer,
        record,
        "screened_out",
        at="2026-08-18T09:03:30Z",
        reason="Permanent nights don't work for me any more — I need to be "
        "home for my kid's bedtime most evenings.",
    )
    return row


# Step id -> driver. Membership here (not `gate.state`) is what makes a
# `True`-classified step "measured" rather than "pending_implementation" —
# see the module docstring.
SURFACE_DRIVERS: dict[str, Callable[[ProfileStore], EvidenceRow | None]] = {
    "intake": _drive_intake,
    "constraints": _drive_constraints,
    "history": _drive_history,
    "traits": _drive_traits,
    "feedback": _drive_feedback,
}


# ---------------------------------------------------------------------------
# the measurement


@dataclass(frozen=True)
class CoverageResult:
    coverage: float
    captured: tuple[str, ...]
    dropped: tuple[str, ...]
    no_free_text: tuple[str, ...]
    pending_implementation: tuple[str, ...]
    problems: tuple[str, ...] = ()

    def as_json(self) -> dict[str, Any]:
        return {
            "profile_capture_coverage": self.coverage,
            "captured_surfaces": list(self.captured),
            "dropped_surfaces": list(self.dropped),
            "no_free_text_surfaces": list(self.no_free_text),
            "pending_implementation_surfaces": list(self.pending_implementation),
            "classification_problems": list(self.problems),
        }


def measure_coverage(
    store: ProfileStore,
    *,
    steps: StepList | None = None,
    drivers: dict[str, Callable[[ProfileStore], EvidenceRow | None]] | None = None,
) -> CoverageResult:
    """`profile_capture_coverage` over one profile — every measured surface
    actually exercised, nothing taken on trust.

    `drivers` defaults to the real `SURFACE_DRIVERS`; a caller may substitute
    a broken one (see `probe_deliberate_break`) to prove the metric notices —
    the same "the measurement is over attempted asks, not the ledger's own
    bookkeeping" posture `decline.count_repeat_asks` takes, applied to a
    caller-supplied driver table instead of a caller-supplied ask list.
    """
    steps = steps or load_steps()
    active_drivers = SURFACE_DRIVERS if drivers is None else drivers
    problems = _classification_problems(steps) if drivers is None else []

    captured: list[str] = []
    dropped: list[str] = []
    no_free_text: list[str] = []
    pending: list[str] = []

    for step in sorted(steps.steps, key=lambda s: s.n):
        accepts = step.accepts_candidate_free_text
        if accepts is None:
            continue  # already reported in `problems` (or by the caller's own drivers)
        if not accepts:
            no_free_text.append(step.id)
            continue
        driver = active_drivers.get(step.id)
        if driver is None:
            pending.append(step.id)
            continue
        row = driver(store)
        (captured if row is not None else dropped).append(step.id)

    denominator = len(captured) + len(dropped)
    coverage = (len(captured) / denominator) if denominator else 0.0
    return CoverageResult(
        coverage=coverage,
        captured=tuple(sorted(captured)),
        dropped=tuple(sorted(dropped)),
        no_free_text=tuple(sorted(no_free_text)),
        pending_implementation=tuple(sorted(pending)),
        problems=tuple(problems),
    )


# ---------------------------------------------------------------------------
# the adversarial probe


def probe_capture(root: Path) -> dict[str, Any]:
    """Run every scenario the module docstring and the payload name.

    One store for the main measurement, fresh stores for every scenario that
    would otherwise contaminate it (a decline, a retraction, a deliberately
    broken driver) — the same isolation `interview.probe_interview` uses for
    the same reason.
    """
    failures: list[str] = []
    checks = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    def fresh_store(handle: str) -> ProfileStore:
        identity = create_profile(root, handle.replace("-", " ").title(), handle=handle)
        return ProfileStore(root, identity.handle)

    steps = load_steps()

    # 1. The classification is complete against the live step model — the
    #    drift guard itself, exercised rather than assumed clean.
    problems = _classification_problems(steps)
    check(not problems, f"classification drifted from the live step model: {problems}")

    # 2. The real measurement: every currently-implemented free-text surface
    #    (intake, constraints, history, traits, feedback) writes evidence
    #    when driven with a real scripted answer through unmodified
    #    production code.
    main_store = fresh_store("probe-capture-main")
    result = measure_coverage(main_store, steps=steps)
    check(
        result.coverage == 1.0,
        f"profile_capture_coverage = {result.coverage}, not 1.0 — dropped: {result.dropped}",
    )
    check(
        set(result.captured) == {"intake", "constraints", "history", "traits", "feedback"},
        f"unexpected captured set: {result.captured}",
    )

    # 3. The three-way split is not vacuous: "no free text" and "not built
    #    yet" are each populated by real steps, distinct from each other and
    #    from "captured" — item 3 of the payload's "also think about".
    check(
        set(result.no_free_text)
        == {"identify", "preferences", "sourcing", "understanding", "ranking"},
        f"unexpected no_free_text set: {result.no_free_text}",
    )
    check(
        set(result.pending_implementation) == {"reactions", "application", "interview_log"},
        f"unexpected pending_implementation set: {result.pending_implementation}",
    )
    check(
        "identify" not in result.captured and "identify" not in result.dropped,
        "a surface with no free text was folded into the measured denominator",
    )
    check(
        "reactions" not in result.captured and "reactions" not in result.dropped,
        "a not-yet-built surface was folded into the measured denominator, "
        "conflating 'not built' with 'built and dropping input'",
    )
    # T50: intake moved from pending_implementation to measured now that S4
    # gives it a real driver — this is the one thing that distinguishes this
    # task from a no-op, per the payload.
    check(
        "intake" in result.captured and "intake" not in result.pending_implementation,
        f"intake is still reported pending_implementation: {result.pending_implementation}",
    )

    # 4. Non-insistence at incidental capture (payload "also think about" #1):
    #    a declined dimension is never filed just because it came up in
    #    passing while talking about something else.
    ni_store = fresh_store("probe-capture-nonins")
    ni_log = EvidenceLog(ni_store)
    ni_ledger = DeclineLedger(ni_store)
    ni_ledger.decline("on_call_load", step="history", at="2026-08-18T09:00:00Z")
    declined_row = capture(
        ni_log,
        ni_ledger,
        step="feedback",
        kind="statement",
        text="On-call again? No thanks.",
        source="offer_reaction",
        dimensions=["on_call_load"],
        recorded_at="2026-08-18T09:00:30Z",
    )
    check(declined_row is None, "an incidentally-mentioned declined dimension was captured anyway")
    mixed_row = capture(
        ni_log,
        ni_ledger,
        step="feedback",
        kind="statement",
        text="On-call again? No thanks, and also the commute is too far.",
        source="offer_reaction",
        dimensions=["on_call_load", "commute_tolerance"],
        recorded_at="2026-08-18T09:00:45Z",
    )
    check(
        mixed_row is not None and mixed_row.dimensions == ("commute_tolerance",),
        f"a mixed declined/undeclined capture did not keep the undeclined dimension: {mixed_row}",
    )

    # 5. Disclosure defaults to private — read back through a *fresh* log, not
    #    the object `capture` handed back (payload's own required test, and
    #    T8's precedent for how to prove it).
    disc_store = fresh_store("probe-capture-disclosure")
    disc_log = EvidenceLog(disc_store)
    disc_ledger = DeclineLedger(disc_store)
    written = capture(
        disc_log,
        disc_ledger,
        step="feedback",
        kind="statement",
        text="Honestly this one made me want to quit looking altogether.",
        source="offer_reaction",
        recorded_at="2026-08-18T09:01:00Z",
    )
    check(written is not None, "capture() wrote nothing for a well-formed call")
    written_id = written.id if written is not None else None
    reread = [row for row in EvidenceLog(disc_store).rows() if row.id == written_id]
    check(bool(reread), "a captured row did not reach disk")
    check(
        all(row.disclosure == "private" for row in reread),
        "a captured row was not private when read back through a fresh log",
    )

    # 6. Retraction (T38) reaches a row this module wrote, with no extra code
    #    — payload's "also think about" #2, demonstrated rather than assumed.
    if written is not None:
        retraction_log = EvidenceLog(disc_store)
        retraction_log.append(
            recorded_at="2026-08-18T09:02:00Z",
            step="feedback",
            kind="retraction",
            text="Forget that.",
            source="conversation",
            retracts=written.id,
        )
        # A *fresh* `EvidenceLog` object, not the one just used to write the
        # retraction — the same "prove it reached disk" posture the
        # disclosure check above takes.
        fresh_log = EvidenceLog(disc_store)
        effective_ids = {row.id for row in fresh_log.effective_rows()}
        check(
            written.id not in effective_ids,
            "a captured row survived retraction — T38 did not reach continuous capture",
        )
        check(
            written.id in {row.id for row in fresh_log.rows()},
            "retraction deleted the captured row instead of suppressing it (append-only, §4.1)",
        )

    # 7. Provenance: every captured row names its surface (`step`) and what
    #    kind of stimulus it was a response to (`source`).
    check(
        written is not None and written.step == "feedback" and written.source == "offer_reaction",
        f"a captured row lost its provenance: {written}",
    )

    # 8. `capture()` refuses to write a retraction — the generic primitive is
    #    not a backdoor around T38's own naming discipline.
    try:
        capture(
            disc_log,
            disc_ledger,
            step="feedback",
            kind="retraction",
            text="Forget that.",
            source="conversation",
            recorded_at="2026-08-18T09:03:00Z",
        )
    except ProfileCaptureError:
        check(True, "")
    else:
        check(False, "capture() accepted kind='retraction'")

    # 9. The required verification: deliberately break a surface, and watch
    #    the metric — and only that surface — fall.
    break_details = probe_deliberate_break(root)
    check(
        break_details["coverage_before_break"] == 1.0,
        f"the break scenario's own baseline was not 1.0: {break_details}",
    )
    check(
        break_details["coverage_after_break"] < 1.0,
        "profile_capture_coverage did not drop when a surface dropped its input",
    )
    check(
        break_details["broken_surface"] in break_details["dropped_after_break"],
        f"the broken surface was not reported dropped: {break_details}",
    )

    return {
        "profile_capture_coverage": result.coverage,
        "captured_surfaces": list(result.captured),
        "dropped_surfaces": list(result.dropped),
        "no_free_text_surfaces": list(result.no_free_text),
        "pending_implementation_surfaces": list(result.pending_implementation),
        "classification_problems": list(result.problems),
        "deliberate_break_demonstration": break_details,
        "checks_run": checks,
        "failures": failures,
    }


def probe_deliberate_break(root: Path) -> dict[str, Any]:
    """The required verification: make a surface drop its input, on purpose.

    Substitutes one driver — `feedback`'s — for one that calls the *real*
    `capture_offer_decision_reason` machinery but discards the row it would
    have produced (mirroring exactly the shape a caller bug would take: the
    text arrived, `transition` ran, and nothing was ever appended to the
    log). `measure_coverage` is handed this broken table explicitly, so it
    skips its own classification-drift check (that check is about this
    module's *classification*, not about a caller-supplied driver override) —
    the coverage arithmetic is exercised for real over a genuinely different
    driver, not stubbed out.
    """

    def _broken_feedback_driver(store: ProfileStore) -> EvidenceRow | None:
        offer = connect_manual("Overnight Stocking Associate. Permanent nights.")
        record = track_new_offer(offer, at="2026-08-18T09:10:00Z")
        save_lifecycle_offer(store, offer, record)
        # The candidate's reason is right here — and this driver, standing in
        # for a hypothetical caller that only ever calls `lifecycle.transition`
        # directly, never routes it through `capture()`. This is the "surface
        # that takes input and records nothing" the payload's gate exists to
        # catch.
        transition(
            offer, record, "screened_out", at="2026-08-18T09:10:30Z", reason="Nights again — no."
        )
        return None

    broken_drivers = dict(SURFACE_DRIVERS)
    broken_drivers["feedback"] = _broken_feedback_driver

    steps = load_steps()
    store = create_profile_store_for_break(root)
    before = measure_coverage(store, steps=steps)  # real drivers, via the default

    broken_store = create_profile_store_for_break(root, suffix="broken")
    after = measure_coverage(broken_store, steps=steps, drivers=broken_drivers)

    return {
        "coverage_before_break": before.coverage,
        "coverage_after_break": after.coverage,
        "broken_surface": "feedback",
        "dropped_after_break": list(after.dropped),
        "captured_after_break": list(after.captured),
    }


def create_profile_store_for_break(root: Path, *, suffix: str = "baseline") -> ProfileStore:
    """A fresh profile for `probe_deliberate_break`'s two runs — never reusing
    one store for both, or the "before" run's evidence would still be on disk
    when the "after" run's broken driver is measured."""
    identity = create_profile(root, f"Probe Break {suffix}", handle=f"probe-capture-break-{suffix}")
    return ProfileStore(root, identity.handle)


# ---------------------------------------------------------------------------
# D-8: a capture whose subject is a specific artefact must name it
#
# `captures_without_a_subject` — a separate, independent gate over the same
# capture surface, the same "second flag, second evidence file, one module"
# shape `integral.profile`'s `--constraint-survival` already uses for D-6.

DEFAULT_D8_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D8.json"

# Which `source` values name a capture "about" one specific external
# artefact, as opposed to an answer to a bank question (whose subject is
# already the question's own dimension — the exclusion the D-8 payload's gate
# names). Only `offer_reaction` qualifies today: every row this codebase
# writes with that source is a reaction to one particular `Offer` — a
# rejection reason via `capture_offer_decision_reason` today, a reactions
# free-text answer (T17) tomorrow. `conversation` (an elicited bank answer,
# or free-standing intake speech), `cv_document` (a parsed CV span — S4
# already names its own document/span provenance) and `interview` (S6's own
# prep/record, not built yet) each already answer "in response to what" a
# different way, none of them needing this field.
_SOURCES_REQUIRING_A_SUBJECT: frozenset[Source] = frozenset({"offer_reaction"})


def captures_without_a_subject(rows: Iterable[EvidenceRow]) -> list[str]:
    """D-8's `captures_without_a_subject` — ids of rows whose capture is about
    one specific artefact and names no way to identify it.

    The line is drawn on `source`, not on `kind` or `step`: `source` already
    answers "was this in response to a question, or to something else"
    (`integral.profile.Source`'s own four-way split), and
    `_SOURCES_REQUIRING_A_SUBJECT` is the one value this codebase can
    currently produce that means "something else, a specific artefact".
    Demanding a subject from every row would make the gate unsatisfiable — a
    bank-question answer has no artefact to name, and
    `test_an_answer_to_a_question_needs_no_subject_field` exercises exactly
    that excluded case; demanding one from none would make the gate vacuous.
    Takes rows as data, not a store, the same posture `trait_evidence_
    sufficiency` takes toward `readings` — a violation produced by a caller
    that bypassed `capture()` entirely must be caught exactly as if the real
    pipeline had produced it.
    """
    return [
        row.id for row in rows if row.source in _SOURCES_REQUIRING_A_SUBJECT and row.about is None
    ]


def probe_deliberate_subject_break(root: Path) -> dict[str, Any]:
    """The required verification: capture a reason about a specific offer
    without recording its subject, on purpose.

    Calls `capture()` directly with `source="offer_reaction"` and no `about`
    — the shape a caller bug would take if it forgot to build the
    `EvidenceSubject` `capture_offer_decision_reason` now always supplies
    (mirroring exactly `probe_deliberate_break`'s own shape for T28's gate,
    over this gate instead).
    """
    store = create_profile_store_for_break(root, suffix="subject")
    log = EvidenceLog(store)
    ledger = DeclineLedger(store)

    offer = connect_manual("Overnight Stocking Associate. Permanent nights.")
    record = track_new_offer(offer, at="2026-08-18T09:10:00Z")
    save_lifecycle_offer(store, offer, record)

    before = captures_without_a_subject(log.effective_rows())

    broken_row = capture(
        log,
        ledger,
        step="feedback",
        kind="statement",
        text="Nights again — no.",
        source="offer_reaction",
        recorded_at="2026-08-18T09:10:30Z",
        # `about` deliberately omitted — the failure this gate exists to catch.
    )

    after = captures_without_a_subject(log.effective_rows())

    return {
        "captures_without_a_subject_before_break": len(before),
        "captures_without_a_subject_after_break": len(after),
        "broken_row_id": broken_row.id if broken_row is not None else None,
        "violation_ids_after_break": after,
    }


def probe_subject_linkage(root: Path) -> dict[str, Any]:
    """D-8's adversarial probe: every scenario the payload and the gate name.

    One fresh store carries scenarios 1-5 in sequence (each building on what
    came before, the way `elicit_extract.probe_extraction` replays declines
    across scenarios); the required-verification break runs against its own
    store, the same isolation `probe_deliberate_break` uses for T28's gate.
    """
    from integral.revision import refresh

    failures: list[str] = []
    checks = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    def fresh_store(handle: str) -> ProfileStore:
        identity = create_profile(root, handle.replace("-", " ").title(), handle=handle)
        return ProfileStore(root, identity.handle)

    # 1. Two rejections of two different offers are distinguishable in the
    #    log — the failure this exists for, invisible while only one offer
    #    has ever been rejected. Identical wording on purpose: only the
    #    subject can tell the two rows apart.
    store = fresh_store("subject-two-offers")
    offer_a = connect_manual("Warehouse Operative. Nights, on-site, permanent.")
    record_a = track_new_offer(offer_a, at="2026-08-18T09:00:00Z")
    save_lifecycle_offer(store, offer_a, record_a)
    offer_b = connect_manual("Data Entry Clerk. Hybrid, three days on-site.")
    record_b = track_new_offer(offer_b, at="2026-08-18T09:00:30Z")
    save_lifecycle_offer(store, offer_b, record_b)

    _, _, row_a = capture_offer_decision_reason(
        store,
        offer_a,
        record_a,
        "screened_out",
        at="2026-08-18T09:01:00Z",
        reason="Too far from home.",
    )
    _, _, row_b = capture_offer_decision_reason(
        store,
        offer_b,
        record_b,
        "screened_out",
        at="2026-08-18T09:01:30Z",
        reason="Too far from home.",
    )
    check(row_a is not None and row_b is not None, "both rejections should have written a row")
    check(
        row_a is not None
        and row_b is not None
        and row_a.about is not None
        and row_b.about is not None
        and row_a.about.id != row_b.about.id,
        "two rejections carrying the identical wording were not distinguishable by subject",
    )
    check(
        row_a is not None and row_a.about == EvidenceSubject(kind="offer", id=offer_a.id),
        f"the first rejection's subject did not name the offer it was about: {row_a}",
    )
    check(
        row_b is not None and row_b.about == EvidenceSubject(kind="offer", id=offer_b.id),
        f"the second rejection's subject did not name the offer it was about: {row_b}",
    )
    check(
        captures_without_a_subject(EvidenceLog(store).effective_rows()) == [],
        "two properly-subjected rejections were flagged by captures_without_a_subject",
    )

    # 2. A captured reason survives rebuild with its subject — provenance that
    #    does not survive T6's rebuild is not provenance.
    rebuild(store)
    reread = [r for r in EvidenceLog(store).rows() if row_a is not None and r.id == row_a.id]
    check(bool(reread), "the captured row did not reach disk")
    check(
        bool(reread) and reread[0].about == EvidenceSubject(kind="offer", id=offer_a.id),
        "a captured reason's subject did not survive a rebuild",
    )

    # 3. An answer to a question needs no subject field — the exclusion,
    #    asserted directly so the gate cannot be satisfied by demanding a
    #    subject everywhere. Driven through the real T8 path (`store_answer`,
    #    via this module's own `history` driver), never asserted by hand.
    question_row = _drive_history(store)
    check(question_row is not None, "the history driver did not write a row to test against")
    check(
        question_row is not None and question_row.about is None,
        "an answer to a bank question carried a subject nobody asked it to",
    )
    check(
        captures_without_a_subject(EvidenceLog(store).effective_rows()) == [],
        "an answer to a question was wrongly counted as a capture with no subject",
    )

    # 4. Retraction (T38) does not strip a captured row's subject: the
    #    suppressed row disappears from what a rebuild uses, but the row
    #    itself, subject included, is still in the append-only log.
    EvidenceLog(store).append(
        recorded_at="2026-08-18T09:02:00Z",
        step="feedback",
        kind="retraction",
        text="Forget that.",
        source="conversation",
        retracts=row_a.id if row_a is not None else "ev-000000",
    )
    after_retraction = [
        r for r in EvidenceLog(store).rows() if row_a is not None and r.id == row_a.id
    ]
    check(
        bool(after_retraction) and after_retraction[0].about is not None,
        "a retraction stripped the subject from the row it suppressed, instead of only "
        "suppressing it",
    )
    check(
        row_a is not None and row_a.id not in {r.id for r in EvidenceLog(store).effective_rows()},
        "test setup: the retraction did not actually suppress the row",
    )

    # 5. Revision (T37) reads the same rows — a subject-carrying row does not
    #    make `refresh` choke, and the subject is still there afterwards.
    refresh(store)
    still_there = [r for r in EvidenceLog(store).rows() if row_b is not None and r.id == row_b.id]
    check(
        bool(still_there) and still_there[0].about == EvidenceSubject(kind="offer", id=offer_b.id),
        "a subject-carrying row lost its subject across T37's refresh",
    )

    # 6. The required verification: capture a reason about a specific offer
    #    without recording its subject, and watch the metric — and only that
    #    row — go non-zero.
    break_details = probe_deliberate_subject_break(root)
    check(
        break_details["captures_without_a_subject_before_break"] == 0,
        f"the break scenario's own baseline was not clean: {break_details}",
    )
    check(
        break_details["captures_without_a_subject_after_break"] > 0,
        "captures_without_a_subject did not rise when a subject was dropped",
    )
    check(
        break_details["broken_row_id"] in break_details["violation_ids_after_break"],
        f"the broken row was not named in the violations: {break_details}",
    )

    all_rows = EvidenceLog(store).effective_rows()
    violations = captures_without_a_subject(all_rows)

    return {
        "captures_without_a_subject": len(violations),
        "violation_ids": violations,
        "deliberate_break_demonstration": break_details,
        "checks_run": checks,
        "failures": failures,
    }


def measure_subject_gate() -> dict[str, Any]:
    """Run D-8's adversarial probe in a throwaway tree and report its gate."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="integral-d8-") as tmp:
        return probe_subject_linkage(Path(tmp) / "profiles")


def write_subject_evidence(evidence: Path = DEFAULT_D8_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure D-8's `captures_without_a_subject` gate and record it."""
    measured = measure_subject_gate()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


MINIMUM_SUBJECT_CHECKS = 12


MINIMUM_CHECKS = 15


def measure() -> dict[str, Any]:
    """Run the adversarial scenario probe in a throwaway tree and report T28's gate."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="integral-t28-") as tmp:
        return probe_capture(Path(tmp) / "profiles")


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure T28's gate and record it."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def measure_step_declarations(steps: StepList | None = None) -> dict[str, Any]:
    """S12's gate reading: every step in the live model must declare whether
    it takes candidate free text, from the model itself rather than a Python
    map that could go stale.

    Reads the already-validated `StepList` directly (never the raw JSON): a
    step whose declaration is present but not a bool would already have
    failed `load_steps()`, so there is nothing left for this function to
    catch beyond "absent" (`None`) — the same load-raises / measure-reports
    split every other gate in this module keeps.
    """
    steps = steps or load_steps()
    unclassified = unclassified_free_text_steps(steps)
    return {
        "unclassified_free_text_steps": len(unclassified),
        "unclassified_step_ids": unclassified,
        "step_count": steps.step_count,
    }


def write_step_declaration_evidence(evidence: Path = DEFAULT_S12_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure S12's gate and record it."""
    measured = measure_step_declarations()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


_WRITE_EVIDENCE_DEFAULT = "__default__"
# Sentinel, not a real path: `--subject-gate` changes which file "the
# default" means (`D8.json` instead of `T28.json`), and a fixed string
# default could not tell "the caller wants that mode's own default" apart
# from "the caller happened to pass that exact path".


def _main(argv: list[str]) -> int:
    """`python -m integral.profile_capture [--check] [--write-evidence [PATH]]`
    -> T28's gate (`profile_capture_coverage`), and — every non `--subject-gate`
    run — S12's gate (`unclassified_free_text_steps`) alongside it.

    `--subject-gate` measures D-8's gate instead (`captures_without_a_
    subject`), and `--write-evidence`'s own default path switches with it —
    the same one-flag-picks-a-second-gate-over-the-same-module shape
    `integral.profile`'s `--constraint-survival` already uses for D-6. S12's
    evidence always goes to its own default path (`status/evidence/S12.json`)
    regardless of `--write-evidence PATH`, the same way D-8's own path is
    fixed under `--subject-gate` — a custom PATH only ever redirects T28's file.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence file",
    )
    parser.add_argument(
        "--subject-gate",
        action="store_true",
        help="measure D-8's captures_without_a_subject gate instead of T28's own",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=_WRITE_EVIDENCE_DEFAULT,
        default=_WRITE_EVIDENCE_DEFAULT,
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/T28.json, "
        "or D8.json with --subject-gate)",
    )
    args = parser.parse_args(argv[1:])

    default_path = DEFAULT_D8_EVIDENCE_PATH if args.subject_gate else DEFAULT_EVIDENCE_PATH
    write_path = (
        default_path
        if args.write_evidence == _WRITE_EVIDENCE_DEFAULT
        else Path(args.write_evidence)
    )

    if args.subject_gate:
        measured = measure_subject_gate() if args.check else write_subject_evidence(write_path)
        print(json.dumps(measured, ensure_ascii=False))

        if measured["checks_run"] < MINIMUM_SUBJECT_CHECKS:
            print(
                f"only {measured['checks_run']} checks ran (floor {MINIMUM_SUBJECT_CHECKS}) — "
                "a clean score without exercising the scenarios is not a measurement",
                file=sys.stderr,
            )
            return 3

        violations = list(measured["failures"])
        if measured["captures_without_a_subject"] != 0:
            violations.append(
                f"captures_without_a_subject = {measured['captures_without_a_subject']} "
                f"(want 0) — {measured['violation_ids']}"
            )
        for violation in violations:
            print(violation, file=sys.stderr)
        return 1 if violations else 0

    measured = measure() if args.check else write_evidence(write_path)
    # S12: the step model's own free-text declarations, measured (and — unless
    # --check — recorded to status/evidence/S12.json) alongside T28's probe on
    # every plain `--write-evidence` run, so one invocation keeps both gates
    # current without a second flag.
    declarations = measure_step_declarations() if args.check else write_step_declaration_evidence()
    print(json.dumps(measured, ensure_ascii=False))
    print(json.dumps(declarations, ensure_ascii=False))

    if measured["checks_run"] < MINIMUM_CHECKS:
        print(
            f"only {measured['checks_run']} checks ran (floor {MINIMUM_CHECKS}) — a clean "
            "score without exercising the scenarios is not a measurement",
            file=sys.stderr,
        )
        return 3

    violations = list(measured["failures"])
    if measured["classification_problems"]:
        violations.extend(measured["classification_problems"])
    if measured["profile_capture_coverage"] != 1.0:
        violations.append(
            f"profile_capture_coverage = {measured['profile_capture_coverage']} (want 1.0) — "
            f"dropped: {measured['dropped_surfaces']}"
        )
    if declarations["unclassified_free_text_steps"] != 0:
        violations.append(
            f"unclassified_free_text_steps = {declarations['unclassified_free_text_steps']} "
            f"(want 0) — {declarations['unclassified_step_ids']}"
        )
    for violation in violations:
        print(violation, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
