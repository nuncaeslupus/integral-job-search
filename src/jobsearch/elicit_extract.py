"""Free-text answer extraction -> dimension values + story-bank episodes (T8).

`docs/METHODS.md` §2.1 states the mechanism this module implements: "Questions
are generated from the dimension model so every question maps to at least one
dimension ID (gate: `question_dimension_coverage == 1.0`). Free-text answers
are extracted against those same IDs." T7 (`jobsearch.question_bank`) built
the bank half of that sentence; this module is the other half — turning one
candidate answer, given in reply to one `BankEntry`, into evidence rows the
rest of the system can use. `status/specification.md` §5.4 fixes what those
rows become: `stories.jsonl` (episodes, for reuse in a cover letter or
interview prep) and the dimension-evidence side of `traits.json` are both
**derived** from `profiles/<handle>/profile/evidence.jsonl`, never written
directly (`jobsearch.profile`, T6). So this module owns exactly one thing —
deciding what belongs in one more line of that log — and nothing that
recomputes anything downstream of it.

**The concrete failure this module exists to prevent** is a story bank that is
a pile of prose: an episode with no dimension id is not wrong, it is
unqueryable — nothing can ever select it for a cover letter about a specific
trait, and `status/plan.md`'s T8 gate, `story_dimension_linkage == 1.0`, is
named after exactly that property. `store_answer` therefore has no code path
that appends a `kind="episode"` row with an empty `dimensions` tuple; the two
places that would otherwise produce one (`extract`'s `"empty"` and
`"declined"` outcomes, and `"needs_review"`) return without writing anything.
`story_dimension_linkage` re-measures the log itself rather than trusting that
guarantee — see its docstring for why, and `probe_linkage_guarantee_is_load_bearing`
for a demonstration that bypasses the guarantee on purpose.

**A second failure this module exists to prevent** is an episode that leaks
into a document the candidate never approved of. §5.4: "`disclosure` defaults
to `private`. Promotion to `approved_for_use` requires an explicit per-offer
act by the candidate and is itself recorded in `evidence.jsonl`." Promotion is
not this module's job — nothing here ever runs after an offer exists — so
`store_answer` does not expose a `disclosure` parameter at all: closing the
leak at the call signature is stronger than defaulting a parameter nobody
passes today but somebody could tomorrow. `test_episode_defaults_to_private_disclosure`
proves the default by reading the row back off disk through a fresh
`EvidenceLog`, not by inspecting the object `store_answer` happened to return.

**Why extraction here is one dimension id, unconditionally, plus whatever a
mechanical scan finds — never a model call.** Every check this repository runs
in CI runs without network (the `run` skill, `make ci`), so extraction cannot
be "ask an LLM what this answer means." What *is* available, deterministically,
is which dimension the question was written to elicit — `BankEntry.dimension_id`,
fixed at bank-generation time (T7), not guessed from the reply — plus the same
regex `extraction.cues` machinery `dimensions/*.yaml` already carries for
matched-side dimensions (§5.1), reapplied here to the candidate's own words
instead of an ad's. A cue hit is a mechanical fact about the text, not an
interpretation of it, which is what keeps this deterministic and testable
(`tests/test_elicit_extract.py` runs it with no model in the loop).

**Where the code cannot make the call, it says so instead of guessing.**
`extract` returns a `needs_review` outcome, and stores nothing, in the two
places a human judgement is genuinely required: an answer implausibly long for
one elicitation question (more likely several answers concatenated by a
caller bug than one very long story), and an answer whose *asked* dimension
was declined but whose text also, incidentally, touches an undeclined one — a
case where discarding the whole answer loses real evidence and keeping it
under the incidental dimension alone risks mis-filing a story under the wrong
heading. Neither is resolved by inventing a heuristic; both come back as a
structured outcome with a reason a human (or T27, the interview protocol that
will call this module) can act on.

**Non-insistence (T40) is honoured at the write path, not assumed.**
`jobsearch.decline.DeclineLedger` guarantees "a subject declined once is not
raised again in that step" — that is T27's job, sequencing *questions*, and
outside this module's scope (`question_bank`'s own docstring makes the same
carve-out for the same reason). What this module owns is narrower and
different: an answer to an *undeclined* question can still mention a
*declined* subject in passing, because a mechanical cue scan does not know
what the candidate would rather not discuss. `extract` filters every
candidate dimension id — the asked one included, belt-and-braces, in case a
caller ever routes a declined subject's own question through here — through
`DeclineLedger.declines` before anything is written, so a subject the
candidate opted out of is never mined out of an answer about something else.

**One store, not two.** The payload title ("dimension values + story-bank
episodes") describes two downstream *views*, not two things this module
writes. `jobsearch.profile._build_stories` projects `kind="episode"` rows into
`stories.jsonl`; `jobsearch.profile._build_traits` projects every row's
`dimensions` into `traits.json`'s evidence-id lists, `kind="episode"` rows
included. One `EvidenceRow`, appended once, is both — inventing a second
store here would be the exact drift T6's module docstring warns against
("Everything derived… is recomputed from it and never edited in place").
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jobsearch.decline import DeclineLedger
from jobsearch.dimensions import (
    SCHEMA_LANGUAGES,
    Cue,
    Dimension,
    Elicitation,
    Extraction,
    Language,
    LocalisedText,
    Question,
    Side,
)
from jobsearch.profile import EvidenceLog, EvidenceRow
from jobsearch.question_bank import BankEntry, build_bank

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T8.json"

# Below this many non-whitespace characters, an answer carries too little to be
# evidence of anything — "fine", "ok", a stray keystroke. Not a claim about
# *content* (that would be guessing at meaning); a length floor is the one
# thing that can be asserted about an answer without interpreting it. Item 4
# of the payload: "an answer that yields nothing is a normal outcome, not an
# error" — this is the mechanical form of "yields nothing".
MIN_ANSWER_CHARS = 12

# Above this many characters, one elicitation answer is implausible — this
# repository's real bank questions ask for one behavioural anecdote, not an
# essay. More likely several answers concatenated by a caller bug than a
# single very long story; deciding which is exactly the judgement call the
# module docstring says gets surfaced rather than guessed at.
MAX_ANSWER_CHARS = 4000

Outcome = Literal["stored", "empty", "declined", "needs_review"]


class ElicitExtractError(Exception):
    """A caller asked this module to extract against something it cannot use."""


@dataclass(frozen=True)
class ExtractionResult:
    """What happened to one answer, and — only for `"stored"` — the row it became.

    `outcome` is never inferred by a caller from `row is None`: a caller that
    wants to know *why* nothing was written reads `reason`, which is why every
    non-storing outcome still carries one instead of an empty string.
    """

    outcome: Outcome
    dimensions: tuple[str, ...]
    reason: str
    row: EvidenceRow | None = None
    denied: tuple[str, ...] = ()
    """Of `dimensions`, the ones the answer *denies* rather than affirms.

    Linkage itself is unsigned and stays that way — `profile._build_traits`
    collects evidence row references per dimension and scores nothing, so
    "this episode bears on `on_call_load`" is true of "we were on call every
    third week" and of "there was no on-call rotation" alike, and dropping the
    second would throw away a real answer to a real question.

    What must not happen is the two becoming *indistinguishable*. `Cue.value`
    and `Cue.negatable` exist precisely because "no on-call" is evidence
    against rather than absence of evidence (T16), and reusing the patterns
    while discarding the sign leaves a later scorer — T49, counting episodes
    towards a trait floor — unable to tell an affirmation from its opposite.
    So the sign is carried here, beside the link, rather than folded into it.
    """


# ---------------------------------------------------------------------------
# which dimensions an answer touches


# Words that flip a cue in the three corpus languages, and how far ahead of the
# match they are allowed to sit. A window, not a sentence parse: this module is
# deterministic and does no linguistics, so it claims only what a window can
# honestly support — `NEGATION_WINDOW_CHARS` is deliberately short, because a
# negation five words back usually belongs to a different clause.
NEGATION_WORDS: tuple[str, ...] = (
    # en
    "no", "not", "never", "without", "zero",
    # es
    "sin", "nunca", "ninguna", "ningun", "ningún", "tampoco",
    # ca
    "sense", "cap", "mai",
)
NEGATION_WINDOW_CHARS = 24


def _is_negated(text: str, match_start: int) -> bool:
    """Whether a negation word sits just before `match_start`.

    The ad-side pipeline (T16) owns real negation scoring against a measured
    `extraction_negation_recall`. This is the candidate-side echo of it, and it
    is deliberately weaker and says so: it decides only whether to mark a link
    as denied, never a numeric value, so a miss costs a lost sign rather than a
    wrong score.
    """
    window = text[max(0, match_start - NEGATION_WINDOW_CHARS) : match_start].lower()
    return any(re.search(rf"\b{re.escape(word)}\b", window) for word in NEGATION_WORDS)


def _matched_cue_hits(
    answer: str,
    dimensions: Sequence[Dimension],
    *,
    language: Language | None,
) -> tuple[tuple[str, bool], ...]:
    """`(dimension_id, negated)` for every dimension whose cues fire on this text.

    Reuses `Dimension.extraction.cues` exactly as written for ad text (§5.1) —
    no separate pattern set invented for candidate speech. Only `matched`-side
    dimensions ever carry cues at all: `candidate_trait` is refused one at load
    (`Dimension._a_trait_cannot_be_read_from_an_ad`) and `candidate_fact`'s own
    cues are a schema violation (`dimensions.side_violations`), so this
    function does not need to special-case either — a trait or a fact dimension
    simply never contributes a secondary hit, by construction of the model it
    reads.

    `language=None` (the default) tries every corpus language's cues, because
    nothing at this layer tracks which language the candidate is answering in
    — a deliberate simplification named in the module docstring's limits, not
    a silent guess: a caller who *does* know the answer's language can pass it
    to narrow the scan.
    """
    languages = (language,) if language is not None else SCHEMA_LANGUAGES
    hits: list[tuple[str, bool]] = []
    for dimension in dimensions:
        if dimension.side != "matched":
            continue
        fired = [
            (cue, match)
            for lang in languages
            for cue in dimension.extraction.cues.get(lang, ())
            if (match := re.search(cue.pattern, answer, re.IGNORECASE)) is not None
        ]
        if not fired:
            continue
        # Negated only when *every* cue that fired is either a negatable one
        # reading under a negation, or a cue the model itself scores at zero
        # (`no\s+on-?call`). One plain affirmative hit is enough to call the
        # whole answer an affirmation — "we had on-call shifts, though no
        # on-call rotation as such" fires both an affirmed and a zero-valued
        # cue, and the subject is plainly present.
        hits.append(
            (
                dimension.id,
                all(
                    cue.value == 0.0 or (cue.negatable and _is_negated(answer, match.start()))
                    for cue, match in fired
                ),
            )
        )
    return tuple(hits)


def candidate_dimensions(
    entry: BankEntry,
    answer: str,
    dimensions: Sequence[Dimension],
    *,
    language: Language | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """`(every dimension this answer bears on, those it denies)`, before declines.

    `entry.dimension_id` — what the question was built to elicit — is always
    first, unconditionally: which dimension a bank question targets is fixed
    at bank-generation time (T7), not guessed from what the candidate happened
    to say back. Anything after it is a mechanical cue hit for a *different*
    dimension (`_matched_cue_hits`, deduplicated against the primary), in bank
    order.

    The second tuple is the subset of those secondary hits the answer *denies*
    — see `ExtractionResult.denied` for why a denial is linked rather than
    dropped. The primary is never in it: which dimension a question targets is
    a fact about the question, not a claim the answer makes.
    """
    primary = entry.dimension_id
    hits = [(did, negated) for did, negated in _matched_cue_hits(
        answer, dimensions, language=language
    ) if did != primary]
    return (primary, *(did for did, _ in hits)), tuple(did for did, negated in hits if negated)


def _undeclined(ledger: DeclineLedger, dimension_ids: Sequence[str]) -> tuple[str, ...]:
    """`dimension_ids`, minus any the candidate has an unreopened decline against.

    `DeclineLedger.declines` already resolves reopening (`since_last_reopening`)
    and does not require the two-decline `silenced` threshold — a single,
    unreopened decline is enough to keep a subject out of a *different*
    question's answer, which is a stricter bar than §5.4's "not raised again in
    that step": nobody is being asked here, but writing it down anyway is its
    own kind of insistence.
    """
    return tuple(
        dimension_id for dimension_id in dimension_ids if not ledger.declines(dimension_id)
    )


# ---------------------------------------------------------------------------
# classify + extract


def extract(
    entry: BankEntry,
    answer: str,
    dimensions: Sequence[Dimension],
    ledger: DeclineLedger,
    *,
    language: Language | None = None,
) -> ExtractionResult:
    """Decide what one answer to one bank entry is evidence for, without writing it.

    Every branch is a `dataclass`, never an exception, because none of these
    are errors — `ElicitExtractError` is reserved for a caller mistake (an
    entry that names no dimension at all), and every outcome below is a normal
    thing for a candidate's answer to be.
    """
    if not entry.dimension_id:  # pragma: no cover - BankEntry's own schema forbids this
        raise ElicitExtractError(f"bank entry {entry.bank_id} names no dimension")
    # `BankEntry` validates the *shape* of a dimension id, never that the
    # ontology still contains one. A bank generated against an older model —
    # or hand-built in a test — therefore carries ids that resolve to nothing,
    # and `EvidenceRow` accepts them too, so the first thing that notices is a
    # rebuilt `traits.json` listing a dimension nobody can look up. Caller
    # mistake, not a candidate outcome, so it raises like the check above.
    if entry.dimension_id not in {dimension.id for dimension in dimensions}:
        raise ElicitExtractError(
            f"bank entry {entry.bank_id} names dimension {entry.dimension_id!r}, "
            "which is not in the supplied model — regenerate the bank (T7) before extracting"
        )

    stripped = answer.strip()
    if len(stripped) < MIN_ANSWER_CHARS:
        return ExtractionResult(
            "empty",
            (),
            f"answer is {len(stripped)} character(s), below the {MIN_ANSWER_CHARS}-character "
            "floor for evidence — too little to be about anything",
        )

    # Declines are resolved before the length check, not after. Nothing is
    # written either way, so no row ever leaked — but an over-long answer to a
    # declined subject used to come back `needs_review` with a reason about its
    # length, which invites a caller to look at it and file it. "Filtered
    # before anything is written" has to mean before anything is *reported*
    # too, or the guarantee holds only for the paths that happened to reach it.
    candidates, denied = candidate_dimensions(entry, stripped, dimensions, language=language)
    kept = _undeclined(ledger, candidates)

    if not kept:
        return ExtractionResult(
            "declined",
            (),
            f"every candidate dimension ({', '.join(candidates)}) has been declined — "
            "nothing is filed about a subject the candidate opted out of",
        )

    kept_denied = tuple(dimension_id for dimension_id in denied if dimension_id in kept)

    if len(stripped) > MAX_ANSWER_CHARS:
        return ExtractionResult(
            "needs_review",
            (),
            f"answer is {len(stripped)} characters, above {MAX_ANSWER_CHARS} — implausible for "
            "one elicitation answer; check it is really one answer before extracting",
            denied=kept_denied,
        )

    if entry.dimension_id not in kept:
        return ExtractionResult(
            "needs_review",
            kept,
            f"{entry.dimension_id} was declined, but the answer also touches "
            f"{', '.join(kept)} — decide whether to file it under that instead of discarding it",
            denied=kept_denied,
        )

    reason = f"answer is evidence for {', '.join(kept)}"
    if kept_denied:
        reason += f" (denying {', '.join(kept_denied)})"
    return ExtractionResult("stored", kept, reason, denied=kept_denied)


def store_answer(
    log: EvidenceLog,
    entry: BankEntry,
    answer: str,
    dimensions: Sequence[Dimension],
    ledger: DeclineLedger,
    *,
    step: str,
    recorded_at: str,
    language: Language | None = None,
) -> ExtractionResult:
    """`extract`, then — only on `"stored"` — append one episode row.

    No `disclosure` parameter: `EvidenceLog.append` defaults `disclosure` to
    `"private"` and this call never overrides it, which is what makes the
    default hold *through the store*, not merely in `EvidenceRow`'s own
    field default — see the module docstring.
    """
    result = extract(entry, answer, dimensions, ledger, language=language)
    if result.outcome != "stored":
        return result
    row = log.append(
        recorded_at=recorded_at,
        step=step,
        kind="episode",
        text=answer.strip(),
        source="conversation",
        dimensions=result.dimensions,
    )
    return ExtractionResult(
        result.outcome, result.dimensions, result.reason, row, denied=result.denied
    )


# ---------------------------------------------------------------------------
# the gate metric


def story_dimension_linkage(log: EvidenceLog) -> tuple[float, list[str]]:
    """`story_dimension_linkage` — fraction of stored episodes carrying >=1 dimension id.

    Measured from the log itself (`EvidenceLog.effective_rows`, so a retracted
    episode counts neither way), never from this module's own bookkeeping — a
    violation written some other way must be caught exactly as if `store_answer`
    had produced it. `probe_linkage_guarantee_is_load_bearing` proves this by
    bypassing `store_answer` on purpose.

    An empty episode set reports `(0.0, [])`, matching every other measure in
    this codebase (`question_bank.dimension_coverage`, `dimensions.extractor_coverage`):
    nothing to measure is not the same as full linkage.
    """
    episodes = [row for row in log.effective_rows() if row.kind == "episode"]
    if not episodes:
        return 0.0, []
    unlinked = [row.id for row in episodes if not row.dimensions]
    linked = len(episodes) - len(unlinked)
    return linked / len(episodes), unlinked


# ---------------------------------------------------------------------------
# fixtures for the adversarial probe — no committed transcript corpus exists,
# so (like T40's `probe_declines` and T6's `probe_rebuild`) the measurement
# *is* a scripted scenario run, not a scan over checked-in data.


def _fixture_dimension(
    dimension_id: str,
    *,
    side: Side = "matched",
    cue_pattern: str | None = None,
) -> Dimension:
    """One minimal, valid `Dimension` built in memory — no YAML, no disk.

    Mirrors `question_bank._synthetic_dimension`'s posture (kept as a private
    copy here rather than imported, since importing another module's
    underscore-prefixed helper would couple two probes that should be able to
    evolve independently): a synthetic model exercising scenarios the
    committed 22-dimension model does not (and should not) carry, such as a
    cue engineered to fire on a specific probe answer.
    """
    cues: dict[Language, list[Cue]] = (
        {"en": [Cue(pattern=cue_pattern, value=0.5, negatable=True)]} if cue_pattern else {}
    )
    return Dimension(
        id=dimension_id,
        kind="soft",
        polarity="bipolar",
        side=side,
        label=LocalisedText(en=dimension_id, es=dimension_id, ca=dimension_id),
        definition="a synthetic dimension used only to probe answer extraction",
        elicitation=Elicitation(
            questions=[
                Question(
                    id=f"{dimension_id}_q1",
                    text=LocalisedText(
                        en="Tell me about it.", es="Cuéntame.", ca="Explica-m'ho."
                    ),
                )
            ]
        ),
        extraction=Extraction(cues=cues),
        methods_ref="METHODS.md#21-structured-behavioural-elicitation",
    )


def probe_extraction(root: Path) -> dict[str, Any]:
    """Run every scenario the module docstring names, and check what came out.

    One shared profile and ledger across scenarios, in the order below —
    declines applied by a later scenario deliberately affect only the
    scenarios that follow it, the same replay discipline `decline.probe_declines`
    uses.
    """
    from jobsearch.identity import ProfileStore as _ProfileStore
    from jobsearch.identity import create_profile

    autonomy = _fixture_dimension("elx_autonomy", side="candidate_trait")
    oncall = _fixture_dimension("elx_oncall", cue_pattern=r"on-?call")
    workload = _fixture_dimension("elx_workload", cue_pattern=r"overtime|extra hours")
    model = [autonomy, oncall, workload]
    bank = build_bank(model)
    entry_autonomy = bank.by_dimension("elx_autonomy")[0]
    entry_workload = bank.by_dimension("elx_workload")[0]

    identity = create_profile(root, "Probe Elicit", handle="probe-elicit")
    store = _ProfileStore(root, identity.handle)
    log = EvidenceLog(store)
    ledger = DeclineLedger(store)

    failures: list[str] = []
    checks = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    # 1. An ordinary substantive answer is stored under the question's own
    #    dimension, and only that one.
    ordinary = (
        "They let me pick my own priorities every sprint and nobody "
        "second-guessed the schedule."
    )
    result = store_answer(
        log,
        entry_autonomy,
        ordinary,
        model,
        ledger,
        step="history",
        recorded_at="2026-08-18T09:00:00Z",
    )
    check(result.outcome == "stored", "an ordinary answer was not stored")
    check(result.dimensions == ("elx_autonomy",), "an ordinary answer linked the wrong dimension")
    check(result.row is not None and bool(result.row.dimensions), "a stored row has no dimensions")

    # 2. A blank answer is `"empty"`, not an error, and nothing is written.
    blank_result = extract(entry_autonomy, "   ", model, ledger)
    check(blank_result.outcome == "empty", "a blank answer was not reported empty")
    check(blank_result.row is None, "a blank answer produced a row")

    # 3. A too-short answer is also `"empty"` — a length floor, not a content guess.
    short_result = extract(entry_autonomy, "fine", model, ledger)
    check(short_result.outcome == "empty", "a too-short answer was not reported empty")

    # 4. A mechanical cue hit for a *different*, undeclined dimension is kept
    #    alongside the primary one — secondary linkage is not itself forbidden.
    secondary_answer = (
        "They let me pick my own priorities, though the on-call rotation ran "
        "every third week."
    )
    secondary_result = extract(entry_autonomy, secondary_answer, model, ledger)
    check(secondary_result.outcome == "stored", "a legitimate secondary hit was not stored")
    check(
        set(secondary_result.dimensions) == {"elx_autonomy", "elx_oncall"},
        "a legitimate secondary hit did not carry both dimensions",
    )

    # 5. Decline the secondary subject, then answer the *unrelated* primary
    #    question with text that still mentions it — non-insistence at the
    #    write path: the declined subject must not be mined out of an answer
    #    about something else.
    ledger.decline("elx_oncall", step="history", at="2026-08-18T09:05:00Z")
    mined_result = extract(entry_autonomy, secondary_answer, model, ledger)
    check(mined_result.outcome == "stored", "a declined secondary mention blocked the whole answer")
    check(
        mined_result.dimensions == ("elx_autonomy",),
        "a declined subject was mined out of an answer about something else",
    )

    # 6. Decline the *primary* subject itself (belt-and-braces: T27 should
    #    never route a declined subject's own question here, but this module
    #    does not trust that it never will). No secondary hit survives either
    #    -> `"declined"`, nothing written.
    ledger.decline("elx_autonomy", step="history", at="2026-08-18T09:10:00Z")
    declined_primary = extract(entry_autonomy, ordinary, model, ledger)
    check(declined_primary.outcome == "declined", "a declined primary subject was not refused")
    check(declined_primary.row is None, "a declined primary subject still produced a row")

    # 7. Same declined primary, but the answer also touches an undeclined
    #    dimension in passing -> `"needs_review"`, not a silent choice either way.
    review_answer = (
        "I'd rather not get into that, but there was constant overtime "
        "expected of the whole team."
    )
    review_result = extract(entry_autonomy, review_answer, model, ledger)
    check(
        review_result.outcome == "needs_review",
        "a declined-primary+secondary case was not flagged",
    )
    check(
        review_result.dimensions == ("elx_workload",),
        "the needs_review case did not carry the surviving secondary dimension",
    )

    # 8. An implausibly long single answer -> `"needs_review"`, on length alone.
    huge_result = extract(entry_workload, "x" * (MAX_ANSWER_CHARS + 1), model, ledger)
    check(huge_result.outcome == "needs_review", "an implausibly long answer was not flagged")
    check(huge_result.dimensions == (), "an oversized answer carried dimensions anyway")

    # 9. Disclosure is `"private"` as read back from a *fresh* read of the log
    #    on disk — proving the default holds through the store, not only in
    #    the object `store_answer` handed back.
    reread = EvidenceLog(store).rows()
    stored_rows = [row for row in reread if row.kind == "episode"]
    check(bool(stored_rows), "no episode rows were persisted to disk at all")
    check(
        all(row.disclosure == "private" for row in stored_rows),
        "a stored episode was not private on disk",
    )

    # 10. A denial and an affirmation of the same subject must not be
    #     indistinguishable. Both stay linked — a denial answers the question
    #     — but the sign has to survive, or a scorer counting episodes towards
    #     a trait floor cannot tell "we were on call constantly" from "there
    #     was no on-call at all".
    denied_hits = _matched_cue_hits("there was no on-call rotation", model, language=None)
    affirmed_hits = _matched_cue_hits(
        "the on-call rotation ran every third week", model, language=None
    )
    check(
        denied_hits == (("elx_oncall", True),),
        f"a denied subject did not read as denied: {denied_hits}",
    )
    check(
        affirmed_hits == (("elx_oncall", False),),
        f"an affirmed subject did not read as affirmed: {affirmed_hits}",
    )
    check(
        [d for d, _ in denied_hits] == [d for d, _ in affirmed_hits],
        "a denial was dropped rather than linked — it answers the question too",
    )

    # 11. A bank entry naming a dimension the model no longer has is a caller
    #     mistake, not a candidate outcome: it must raise rather than file a
    #     row under an id nothing can resolve.
    stale = BankEntry(
        bank_id="gone:q1",
        dimension_id="gone",
        question_id="q1",
        text=entry_autonomy.text,
        order=entry_autonomy.order,
    )
    try:
        extract(stale, "a perfectly ordinary answer about work", model, ledger)
    except ElicitExtractError:
        check(True, "")
    else:
        check(False, "a bank entry naming an unknown dimension was accepted")

    # 12. Declines are resolved before the length check: an over-long answer to
    #     a wholly declined subject reports `declined`, not a reason about its
    #     length that invites someone to file it anyway.
    # `elx_autonomy` was declined in scenario 6 above, so this reuses the
    # shared ledger's accumulated state rather than inventing a second one.
    long_declined = extract(entry_autonomy, "y" * (MAX_ANSWER_CHARS + 1), model, ledger)
    check(
        long_declined.outcome == "declined",
        f"an over-long answer to a declined subject reported {long_declined.outcome!r}",
    )

    linkage, unlinked = story_dimension_linkage(log)
    check(
        linkage == 1.0,
        f"story_dimension_linkage was {linkage}, not 1.0, over this module's own writer",
    )
    check(unlinked == [], "this module's own writer produced an unlinked episode")

    return {
        "story_dimension_linkage": linkage,
        "unlinked_episode_ids": unlinked,
        "stored_episode_count": len(stored_rows),
        "denied_link_examples": [
            {"text": "there was no on-call rotation", "hits": [list(h) for h in denied_hits]},
            {
                "text": "the on-call rotation ran every third week",
                "hits": [list(h) for h in affirmed_hits],
            },
        ],
        "checks_run": checks,
        "failures": failures,
    }


def probe_linkage_guarantee_is_load_bearing(root: Path) -> dict[str, Any]:
    """Prove `story_dimension_linkage` measures the log, not this module's bookkeeping.

    Writes one episode straight through `EvidenceLog.append` — bypassing
    `store_answer` entirely — with `dimensions=()`: the exact shape
    `store_answer` itself refuses to produce. If a second writer, somewhere
    else in the codebase, shipped without this module's guarantee, this is
    what the gate has to catch; a metric that could not see it would be
    trusting a promise instead of measuring one.
    """
    from jobsearch.identity import ProfileStore as _ProfileStore
    from jobsearch.identity import create_profile

    identity = create_profile(root, "Probe Break", handle="probe-break")
    store = _ProfileStore(root, identity.handle)
    log = EvidenceLog(store)
    broken = log.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="history",
        kind="episode",
        text="An episode written straight to the log, bypassing this module's guarantee.",
        source="conversation",
        dimensions=(),
    )
    linkage, unlinked = story_dimension_linkage(log)
    return {
        "story_dimension_linkage": linkage,
        "unlinked_episode_ids": unlinked,
        "broken_row_id": broken.id,
    }


MINIMUM_CHECKS = 22


def measure() -> dict[str, Any]:
    """Run the adversarial scenario probe in a throwaway tree and report T8's gate.

    There is no committed interview transcript to measure against (unlike
    T7's dimension model) — the measurement *is* the scripted scenario run,
    the same posture `decline.write_evidence` and `profile.write_evidence`
    already take for T40 and T6.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="jobsearch-t8-") as tmp:
        return probe_extraction(Path(tmp) / "profiles")


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure T8's gate and record it."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.elicit_extract [--check] [--write-evidence [PATH]]` -> T8's gate.

    `--check` measures and reports without writing a file; without it (the
    default, matching `question_bank._main`) the evidence file is written.
    """
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
        help="write evidence JSON to PATH (default: status/evidence/T8.json)",
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
    if measured["story_dimension_linkage"] != 1.0:
        violations.append(
            f"story_dimension_linkage = {measured['story_dimension_linkage']} (want 1.0)"
        )
    for violation in violations:
        print(violation, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
