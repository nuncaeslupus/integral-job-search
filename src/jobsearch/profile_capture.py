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

**`profile_capture_coverage`.** The gate (`claude-arsenal/queue/lo-62f9.md`) is
the fraction of candidate-facing surfaces that accept free text and append at
least one evidence row when they are actually exercised. "A surface that takes
input and records nothing fails the gate — that is the whole point," and the
corollary the payload also asks for: a surface that takes **no** free text at
all must not be forced into the same denominator, or the gate would go vacuous
the moment enough silent surfaces outnumbered the leaky ones.

## How the surface set is derived, and why

**The set of step ids is read live from `status/spec-v2-steps.json`**
(`jobsearch.process_spec.load_steps`) — the same machine-readable model
`jobsearch.step_runtime` already treats as authoritative for "which artefacts
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

**What is *not* mechanically derivable is whether a step's protocol puts free
text about the candidate in front of a writer at all.** `status/spec-v2-steps.json`
has no such field — `automatic` comes close (only "understanding" is `true`,
i.e. has no candidate present) but says nothing about the twelve conversational
steps, several of which (Ranking: *"No questions; this step presents"*;
Identify: *"No evidence row is written for an unidentified session"*)
structurally take no free text about the candidate despite being ordinary,
`automatic: false` conversations. That distinction lives only in
`status/spec-v2-steps.md`'s prose Protocol/Outputs sections, which are not
machine-readable at this granularity. So `ACCEPTS_CANDIDATE_FREE_TEXT` below is
the one hand-made judgement call in this module — exactly one boolean per step,
each commented with the sentence of `spec-v2-steps.md` that settles it — and it
is guarded, not trusted: `_classification_problems` fails loudly the moment its
key set stops matching the live step list, which is the same "derived, not a
silent list" guarantee `step_runtime.DETECTORS` gives `unknown_artefacts` for
artefact presence rather than for text-acceptance. This is named here rather
than hidden, per the payload: a checker that could not derive one part of its
own denominator says so, instead of quietly pretending the whole thing came
from the model.

**Which `True`-classified steps are actually *measured* is derived a third
way — from what this module can drive, not from a step's own (possibly stale)
`gate.state`.** `gate.state` is recorded per *step*, but this codebase already
has a case where a step's own driver is `not_implemented` while a *different*,
already-shipped task supplies a reachable free-text path underneath it: the
Feedback step's own conversational driver (T21) is `not_implemented`, yet
`jobsearch.lifecycle.transition` (S5, shipped) has taken a free-text `reason`
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
`constraints_step.resolve` already make. Retraction (`jobsearch.retraction.
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
T6 already defines) — "in response to what", to the resolution the existing
schema affords. `EvidenceRow` is `extra="forbid"` (T6) and this task's brief is
explicit that `profile.py` needs no change, so a finer-grained "which specific
offer/ad this was about" field is out of scope here; it would be a schema
widening (§5.7), not a capture-path fix, and is named as a limitation in this
task's report rather than smuggled in as a silent addition to a file another
task owns.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jobsearch.constraints_step import CandidateTurn
from jobsearch.constraints_step import resolve as resolve_constraints
from jobsearch.decline import DeclineLedger
from jobsearch.dimensions import (
    Cue,
    Dimension,
    Elicitation,
    Extraction,
    Language,
    LocalisedText,
    Question,
    Side,
)
from jobsearch.elicit_extract import store_answer
from jobsearch.identity import ProfileStore, create_profile
from jobsearch.lifecycle import LifecycleRecord, save_lifecycle_offer, track_new_offer, transition
from jobsearch.offers import Offer, OfferStatus, connect_manual
from jobsearch.process_spec import StepList, load_steps
from jobsearch.profile import EvidenceLog, EvidenceRow, Kind, Precision, Source
from jobsearch.question_bank import build_bank

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T28.json"

SurfaceStatus = Literal["captured", "dropped", "no_free_text", "pending_implementation"]


class ProfileCaptureError(Exception):
    """This module's own classification disagrees with the live step model."""


# ---------------------------------------------------------------------------
# the one hand-made judgement call — see the module docstring's derivation note
#
# Every entry is commented with the `status/spec-v2-steps.md` sentence that
# settles it; `_classification_problems` fails loudly if this dict's key set
# ever stops matching `load_steps()`'s, so it cannot silently go stale.

ACCEPTS_CANDIDATE_FREE_TEXT: dict[str, bool] = {
    # Step 0: "No evidence row is written for an unidentified session." — the
    # candidate's name is identity, never evidence.
    "identify": False,
    # Step 1: "`profile/evidence.jsonl` rows for everything said."
    "intake": True,
    # Step 2: CandidateTurn(action="state"/"confirm", text=...) — T41, shipped.
    "constraints": True,
    # Step 3: "A story bank of episodes" — T8/T27, shipped.
    "history": True,
    # Step 4: "ask... about the traits still below the floor... by asking for
    # another situation" — T27's top-up loop, shipped.
    "traits": True,
    # Step 5: "Capture their words verbatim and extract afterwards."
    "reactions": True,
    # Step 6: "Forced pairwise choices... never sliders" — a structured pick
    # between two packages, not free text.
    "preferences": False,
    # Step 7: automated fetch, plus a manual paste of an *advert's* text — not
    # a claim about the candidate (see `jobsearch.offers`'s own docstring).
    "sourcing": False,
    # Step 8: `automatic: true` in the live step model — no candidate present.
    "understanding": False,
    # Step 9: "No questions; this step presents."
    "ranking": False,
    # Step 10: "Capture their words... a rejection reason recorded here
    # triggers a weight refit." Reachable today via `lifecycle.transition`'s
    # `reason` (S5, shipped) — see `capture_offer_decision_reason`.
    "feedback": True,
    # Step 11: "show the candidate what was chosen and what was left out" /
    # personal details collected here, by the candidate's own words.
    "application": True,
    # Step 12: "record what actually happened... what they wish they had
    # said" — "Evidence rows linking each lesson to a dimension or episode."
    "interview_log": True,
}


def _classification_problems(steps: StepList) -> list[str]:
    """Where `ACCEPTS_CANDIDATE_FREE_TEXT`/`SURFACE_DRIVERS` disagree with the
    live step model or with each other — see the module docstring.

    Four checks, all symmetric-difference comparisons the same shape
    `step_runtime.unknown_artefacts` runs for its own table: a step the JSON
    names with no classification here, a classification for a step the JSON no
    longer has, a driver registered for a step classified `False` (a driver
    implies free text is accepted — the classification would be self-
    contradicting), and a driver for a step id the JSON does not name at all.
    """
    live_ids = {step.id for step in steps.steps}
    classified_ids = set(ACCEPTS_CANDIDATE_FREE_TEXT)
    problems: list[str] = []
    for missing in sorted(live_ids - classified_ids):
        problems.append(
            f"{missing!r} is a step in {steps.source} with no ACCEPTS_CANDIDATE_FREE_TEXT entry"
        )
    for stale in sorted(classified_ids - live_ids):
        problems.append(f"{stale!r} is classified here but is no longer a step in {steps.source}")
    for orphan in sorted(set(SURFACE_DRIVERS) - live_ids):
        problems.append(f"{orphan!r} has a driver registered but is not a step in {steps.source}")
    for contradiction in sorted(
        step_id for step_id in SURFACE_DRIVERS if not ACCEPTS_CANDIDATE_FREE_TEXT.get(step_id)
    ):
        problems.append(
            f"{contradiction!r} has a driver registered but is classified accepts_free_text=False"
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
) -> EvidenceRow | None:
    """Append one row of free text as evidence, or refuse — never widen anything.

    No `disclosure` parameter; refuses a blank `text` (nothing was said); and
    filters `dimensions` through `ledger.declines` before writing — see the
    module docstring's privacy section for why each of the three matters.
    `kind="retraction"` is refused: a retraction names the row it suppresses
    (`jobsearch.profile.EvidenceRow`) and has no business going through a
    generic "the candidate said something" primitive.
    """
    if kind == "retraction":
        raise ProfileCaptureError("capture() does not write retractions — use jobsearch.retraction")
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

    Composes `jobsearch.lifecycle.transition` rather than editing it: S5's own
    docstring draws the ownership line ("T11 owns the `Offer` schema... this
    module is the 'seam'"), and this task's brief leaves `lifecycle.py`
    untouched — see the report. `reason=None`, or a reason that is only
    whitespace, is not a broken surface: nothing was said, so there is nothing
    to have dropped (the module docstring's `no_free_text` vs. `dropped`
    distinction, applied to one call rather than one step).

    `source="offer_reaction"` — the row is in response to a decision about an
    offer, T6's own vocabulary for exactly this (`jobsearch.profile.Source`).
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
        side=side,
        label=LocalisedText(en=dimension_id, es=dimension_id, ca=dimension_id),
        definition="a synthetic dimension used only to probe continuous capture",
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
        accepts = ACCEPTS_CANDIDATE_FREE_TEXT.get(step.id)
        if accepts is None:
            continue  # already reported in `problems`
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
    #    (constraints, history, traits, feedback) writes evidence when driven
    #    with a real scripted answer through unmodified production code.
    main_store = fresh_store("probe-capture-main")
    result = measure_coverage(main_store, steps=steps)
    check(
        result.coverage == 1.0,
        f"profile_capture_coverage = {result.coverage}, not 1.0 — dropped: {result.dropped}",
    )
    check(
        set(result.captured) == {"constraints", "history", "traits", "feedback"},
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
        set(result.pending_implementation)
        == {"intake", "reactions", "application", "interview_log"},
        f"unexpected pending_implementation set: {result.pending_implementation}",
    )
    check(
        "identify" not in result.captured and "identify" not in result.dropped,
        "a surface with no free text was folded into the measured denominator",
    )
    check(
        "intake" not in result.captured and "intake" not in result.dropped,
        "a not-yet-built surface was folded into the measured denominator, "
        "conflating 'not built' with 'built and dropping input'",
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


MINIMUM_CHECKS = 15


def measure() -> dict[str, Any]:
    """Run the adversarial scenario probe in a throwaway tree and report T28's gate."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="jobsearch-t28-") as tmp:
        return probe_capture(Path(tmp) / "profiles")


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure T28's gate and record it."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.profile_capture [--check] [--write-evidence [PATH]]` -> T28's gate."""
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
        help="write evidence JSON to PATH (default: status/evidence/T28.json)",
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
    if measured["classification_problems"]:
        violations.extend(measured["classification_problems"])
    if measured["profile_capture_coverage"] != 1.0:
        violations.append(
            f"profile_capture_coverage = {measured['profile_capture_coverage']} (want 1.0) — "
            f"dropped: {measured['dropped_surfaces']}"
        )
    for violation in violations:
        print(violation, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
