"""Step 2 — Constraints: confirm-and-fill from claims, or ask from scratch (T41).

Process specification §2.1 says why this step exists apart from Intake, and
what makes it short when Intake ran: "Constraints promotes claims to confirmed
facts by asking, and anything the candidate does not confirm stays `unknown`
— which, per the inherited rule, neither passes nor vetoes." §2.5 requires the
step; §3.1 names the three states a field may end in (`stated`, `declined`,
`unknown`) and the sufficiency level (`L1`) that resolving all of them unlocks.
This module is the engine that gets a field from "unaddressed" to one of the
three — the confirm-and-fill half of the step, not the conversation around it.

**Two openings, and both have to work.** With claims available (Intake ran,
found a CV) the step "opens by showing what Intake inferred and asks the
candidate to correct it in place" (§2.1) — short, because most fields already
have a starting point. With no claims (Intake was declined, or found nothing)
the step "asks from scratch" (§3.1) — longer, never harder: every field still
resolves to one of the three states, from a `CandidateTurn` sequence with no
claim behind any of them. `test_step_runs_with_no_claims_present` is this
path, and it is the one that broke once already (PR #16): a candidate with no
CV must still reach a fully resolved constraint set, because Constraints is
**required** (§2.5) while Intake is **offered**, and "any offered step may be
declined" has to hold in the graph, not only in prose.

**The rule that carries the task: a claim is not a fact.** "Barcelona" pulled
from a CV header (`read_claims`, kind `statement`, source `cv_document`, step
`intake`) is a claim the *document* makes. Nothing here ever reads that claim
as an answer. Only an explicit `CandidateTurn` — `confirm` (there was a claim,
the candidate accepted or corrected it) or `state` (there was none, they
answered from scratch) — writes a `stated` fact, and `confirm` on a field with
no claim to confirm is refused rather than silently treated as `state`: the
distinction between the two openings is enforced, not decorative.

**`declined` and `unknown` are different answers, kept different end to end.**
Both fail to veto an offer (T24's `filter_hard_constraints` skips both), but
only `unknown` is still owed (`CandidateConstraints.outstanding`) — a
`declined` field is a resolved non-answer, and re-raising it breaks §5.4's
non-insistence rule (`jobsearch.decline`). `resolve` consults `DeclineLedger`
before recording a new decline (so a field already silenced by two declines is
never piled on a third time) and calls `may_ask`/`open_fields` the same way any
other step would, so the property is exercised through this module's own API,
not merely inherited by import.

**Why this module writes `profile/constraints.json` itself, rather than
through `jobsearch.profile.rebuild`.** T6's `_build_constraints` folds any
`constraint`-kind evidence row into `state: "stated"` and leaves every other
field **absent** — deliberately, per its own docstring: "unknown" and "stated
as nothing" are different answers "and only T24 gets to name the difference".
T24 names the difference; this module is where that naming becomes a write.
The file stays *derived* in the sense §3.4 means — recomputed from what the
evidence log and the decline ledger currently say, in the same stable field
order every time, never hand-edited — it is just derived by a richer function
than T6's generic fold, one that knows the ten pinned fields and their three
states.

**A stated value survives a call that says nothing about it.** A step run
again later (§3.5's re-entries; a session picked back up) must not forget what
an earlier run settled. Because the file is fully recomputed each time, the
stated value has to be reconstructible from the log alone — so a `stated`
`CandidateTurn` is recorded as one `constraint`-kind evidence row whose `text`
carries both the human quote and the structured value, JSON-encoded together.
`_last_stated_value` replays the log for the most recent one; a decline for
the same field recorded *after* that row wins instead, by timestamp — the
ordinary "the candidate changed their mind more recently" case.

**Open hazard, not this module's file to close.** `jobsearch.revision.refresh`
calls `jobsearch.profile.rebuild` for every derived artefact whenever an
upstream change goes stale — and `rebuild` still writes `constraints.json`
through T6's generic, `stated`-only fold. Calling `rebuild`/`refresh` after
this module has written a richer file would silently overwrite it back down to
a stated-only sliver, dropping every `declined` and `unknown` entry — the
exact collapse this module exists to prevent, reintroduced one layer up.
Closing that requires either teaching `rebuild` to special-case
`constraints.json` or excluding it from the generic derived set, and both
touch `profile.py`, which this task does not own. Flagged here, and in the
handback report, for whoever picks it up next.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from jobsearch.candidate import (
    CONSTRAINT_FIELD_NAMES,
    FIELD_MODELS,
    CandidateConstraints,
    CandidateError,
    ConstraintField,
    ConstraintState,
    load_constraints,
)
from jobsearch.decline import DeclineLedger
from jobsearch.identity import ProfileStore
from jobsearch.profile import DERIVED_DIR, EvidenceLog, EvidenceRow

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T41.json"

# Where the derived file lives — alongside `traits.json`, `weights.json` and
# `stories.jsonl` (T6), so `revision.classify` keeps treating it as `derived`
# without this module needing to know anything about that classification.
CONSTRAINTS_PARTS: tuple[str, ...] = (DERIVED_DIR, "constraints.json")

# §2 names this step "Constraints"; `jobsearch.decline`'s subjects are
# free-form strings, and this is the one every turn in this module is filed
# under unless a caller passes something else (re-entry from a later step,
# e.g. "ranking" asking a field the interview turned out to need).
STEP_ID = "constraints"

Action = Literal["confirm", "state", "decline"]


class ConstraintsStepError(Exception):
    """A turn does not resolve cleanly — an unpinned field, a shape T24 refuses,
    or a `confirm` with no claim behind it to confirm."""


# ---------------------------------------------------------------------------
# claims — what Intake left behind, not yet a fact


@dataclass(frozen=True)
class Claim:
    """One thing Intake inferred about a pinned field, before anyone asked.

    `evidence_id` names the `statement` row this rests on, so a caller showing
    the claim to the candidate can trace it back to where it came from — the
    same provenance discipline §2.1 asks of Intake itself.
    """

    field: str
    text: str
    evidence_id: str


def read_claims(log: EvidenceLog) -> dict[str, Claim]:
    """Every unconfirmed claim Intake left for a pinned field.

    A claim is Intake's own evidence about what a CV says: `kind="statement"`,
    `source="cv_document"`, `step="intake"` (§2.1), tagged with one of T24's
    ten pinned field names. Reading it here is what lets the "claims
    available" opening show what Intake inferred — it must never be read as an
    answer. Only a `CandidateTurn` does that, and only this function's caller
    decides whether one arrives.
    """
    claims: dict[str, Claim] = {}
    for row in log.effective_rows():
        if row.step != "intake" or row.kind != "statement" or row.source != "cv_document":
            continue
        for dimension in row.dimensions:
            if dimension in FIELD_MODELS:
                claims[dimension] = Claim(field=dimension, text=row.text, evidence_id=row.id)
    return claims


# ---------------------------------------------------------------------------
# turns — what the candidate actually said, this call


@dataclass(frozen=True)
class CandidateTurn:
    """One exchange about one pinned field, offered to `resolve` this call.

    `confirm` requires a claim to exist for `field` — it is "correct this
    claim in place", and a `confirm` with nothing to confirm is a caller bug,
    refused rather than quietly treated as `state`. `state` answers from
    scratch, claim or no claim. `decline` needs neither `value` nor `text`:
    §5.4's non-insistence rule is filed in the decline ledger, never as
    evidence about the candidate (`jobsearch.decline`'s module docstring).

    `value` is the payload `FIELD_MODELS[field]` expects when `state="stated"`
    — e.g. `{"country": "ES", "accepts_onsite_in_country": True}` for
    `location`. `text` is the human quote recorded alongside it; a caller that
    leaves it blank still gets a evidence row, just a less legible one.
    """

    field: str
    action: Action
    value: dict[str, Any] | None = None
    text: str = ""


@dataclass(frozen=True)
class FieldResolution:
    """What one field resolved to, and the evidence row behind a `stated` one."""

    field: str
    state: ConstraintState
    evidence_id: str | None = None


@dataclass(frozen=True)
class StepResult:
    """Everything one `resolve` call produced: the typed constraints, the
    per-field trace, and where the derived file landed."""

    constraints: CandidateConstraints
    resolutions: tuple[FieldResolution, ...]
    path: Path


def open_fields(store: ProfileStore, *, step: str = STEP_ID) -> tuple[str, ...]:
    """Pinned fields still worth asking about in `step` — never a silenced one.

    Not "still `unknown`": a field with an unconfirmed claim is open too, since
    nobody has answered it yet either. What must never appear here is a field
    §5.4 has closed — declined twice, and the candidate has not reopened it.
    """
    ledger = DeclineLedger(store)
    return tuple(field for field in CONSTRAINT_FIELD_NAMES if ledger.may_ask(field, step=step))


def _encode_stated(quote: str, value: dict[str, Any]) -> str:
    """A `stated` evidence row's `text`: the quote a human reads, and the
    value this module needs back to reconstruct the field without a new turn."""
    return json.dumps({"quote": quote, "value": value}, ensure_ascii=False, sort_keys=True)


def _last_stated_value(log: EvidenceLog, field: str) -> tuple[EvidenceRow, dict[str, Any]] | None:
    """The most recent row this module wrote that states `field`, decoded.

    Walked newest-first so a later correction always wins over an earlier one.
    A `constraint` row tagged with `field` that this module did not write —
    T6's own fixture uses the kind for free-form facts, and nothing stops
    another step from doing the same — carries no `{"value": ...}` payload and
    is skipped rather than misread: a row this function cannot interpret is
    not a fact it can replay, which is the same "unknown means unknown"
    discipline applied to malformed history instead of a missing answer.
    """
    for row in reversed(log.effective_rows()):
        if row.kind != "constraint" or field not in row.dimensions:
            continue
        try:
            payload = json.loads(row.text)
            value = payload["value"]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        if isinstance(value, dict):
            return row, value
    return None


def _resolve_without_turn(
    log: EvidenceLog, ledger: DeclineLedger, field: str
) -> tuple[ConstraintState, EvidenceRow | None, dict[str, Any] | None]:
    """What `field` already is, when this call offers no turn for it.

    The two histories that can each name an answer — a prior `stated` row and
    a decline in the ledger — are reconciled by timestamp: whichever happened
    more recently wins, the same "the candidate changed their mind" rule a
    fresh turn would apply if one had arrived this call.
    """
    stated = _last_stated_value(log, field)
    declines = ledger.declines(field)
    if stated is not None:
        row, value = stated
        last_decline_at = declines[-1].at if declines else None
        if last_decline_at is None or row.recorded_at >= last_decline_at:
            return "stated", row, value
    if declines:
        return "declined", None, None
    return "unknown", None, None


def resolve(
    store: ProfileStore,
    turns: Sequence[CandidateTurn],
    *,
    step: str = STEP_ID,
    now: str,
) -> StepResult:
    """Resolve every one of T24's ten pinned fields, and write the file.

    Every field ends in exactly one of `stated`, `declined`, `unknown` — the
    loop below never leaves one out, which is what makes
    `constraint_field_resolution` countable rather than aspirational. A field
    a `CandidateTurn` addresses this call is settled by it; anything else
    falls back to `_resolve_without_turn`, so a step run twice does not forget
    what the first run settled.
    """
    log = EvidenceLog(store)
    ledger = DeclineLedger(store)
    claims = read_claims(log)

    turns_by_field: dict[str, CandidateTurn] = {}
    for turn in turns:
        if turn.field not in FIELD_MODELS:
            raise ConstraintsStepError(
                f"{turn.field!r} is not one of T24's ten pinned constraint fields"
            )
        if turn.field in turns_by_field:
            raise ConstraintsStepError(f"{turn.field}: two turns for one field in one call")
        turns_by_field[turn.field] = turn

    resolutions: list[FieldResolution] = []
    fields: dict[str, ConstraintField] = {}

    for field in CONSTRAINT_FIELD_NAMES:
        matched: CandidateTurn | None = turns_by_field.get(field)

        if matched is not None and matched.action == "decline":
            if ledger.may_ask(field, step=step):
                ledger.decline(field, step=step, at=now)
            # else: already silenced (§5.4) — resolve as declined without
            # piling a redundant row onto the ledger.
            fields[field] = FIELD_MODELS[field](state="declined")
            resolutions.append(FieldResolution(field, "declined"))
            continue

        if matched is not None:  # "confirm" or "state"
            if matched.action == "confirm" and field not in claims:
                raise ConstraintsStepError(
                    f"{field}: nothing to confirm — Intake left no claim; use action='state'"
                )
            if matched.value is None:
                raise ConstraintsStepError(f"{field}: {matched.action} needs a value")
            try:
                FIELD_MODELS[field](state="stated", **matched.value)
            except ValidationError as exc:
                raise ConstraintsStepError(f"{field}: {exc}") from exc
            if ledger.declines(field):
                # The candidate raised it themselves by answering — §5.4's
                # only route back in.
                ledger.reopen(field, at=now)
            row = log.append(
                recorded_at=now,
                step=step,
                kind="constraint",
                dimensions=[field],
                source="conversation",
                text=_encode_stated(matched.text, matched.value),
            )
            fields[field] = FIELD_MODELS[field](state="stated", **matched.value)
            resolutions.append(FieldResolution(field, "stated", row.id))
            continue

        state, evidence_row, value = _resolve_without_turn(log, ledger, field)
        if state == "stated":
            # `_resolve_without_turn` only returns "stated" together with both
            # of these — the assert is a type narrowing for mypy, not a
            # runtime check of something that could actually be missing.
            if evidence_row is None or value is None:  # pragma: no cover - contract, not a path
                raise ConstraintsStepError(f"{field}: a stated resolution carried no evidence")
            fields[field] = FIELD_MODELS[field](state="stated", **value)
            resolutions.append(FieldResolution(field, "stated", evidence_row.id))
        else:
            fields[field] = FIELD_MODELS[field](state=state)
            resolutions.append(FieldResolution(field, state))

    # `fields` is built through `FIELD_MODELS[field](...)` — a dispatch table
    # keyed by name, so each value's precise subtype (`Languages`, `Salary`,
    # …) is only known at runtime; mypy sees the table's declared value type,
    # `ConstraintField`, for all ten. `CandidateConstraints` re-validates every
    # one against its own typed attribute on construction, so a mismatch here
    # still fails loudly — just at runtime rather than at the type checker.
    constraints = CandidateConstraints(**fields)  # type: ignore[arg-type]
    path = write_constraints(store, log, constraints)
    return StepResult(constraints, tuple(resolutions), path)


def write_constraints(
    store: ProfileStore, log: EvidenceLog, constraints: CandidateConstraints
) -> Path:
    """Regenerate `profile/constraints.json` in full — never edited in place.

    The header matches T6's shape (`profile_revision`, `scored_at`) so
    `jobsearch.revision`'s staleness detection keeps working over this file
    exactly as it does over any other derived one; only the `fields` body is
    this module's own, carrying all ten pinned names every time regardless of
    which ones this call's turns touched.
    """
    rows = log.effective_rows()
    stamps = [row.recorded_at for row in rows]
    payload: dict[str, Any] = {
        "profile_revision": log.revision().as_json(),
        "scored_at": max(stamps) if stamps else None,
        "fields": {
            # `mode="json"` — `Relocation.confirmed_offers` is a `frozenset`,
            # which the default dump mode hands back unconverted and
            # `json.dumps` (S3's `ProfileStore.write_json`) cannot serialise.
            name: constraints.as_dict()[name].model_dump(mode="json")
            for name in CONSTRAINT_FIELD_NAMES
        },
    }
    return store.write_json(payload, *CONSTRAINTS_PARTS)


# ---------------------------------------------------------------------------
# the gate


def probe_resolution(root: Path) -> dict[str, Any]:
    """Run both openings against a real tree, adversarially.

    Not "does a full resolution round-trip" — it is "does every place the
    trichotomy could quietly collapse actually hold": an unconfirmed claim
    read as a fact, a declined field read as unknown (or the reverse), the
    required-only path stalling at L0, and a field declined twice getting
    asked a third time anyway. `checks_run` counts assertions actually made,
    the same discipline `candidate.probe_hard_filter` uses for the same
    reason — a probe that claims coverage it did not run is its own leak.
    """
    from jobsearch.identity import create_profile
    from jobsearch.step_runtime import ProfileView, sufficiency

    failures: list[str] = []
    checks = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    # --- opening one: claims available, and the confirm-and-fill shortcut --
    with_claims = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    store = ProfileStore(root, with_claims.handle)
    log = EvidenceLog(store)
    log.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="intake",
        kind="statement",
        dimensions=["location"],
        text="Barcelona (CV header)",
        source="cv_document",
    )
    log.append(
        recorded_at="2026-08-18T09:00:01Z",
        step="intake",
        kind="statement",
        dimensions=["salary"],
        text="around 40k EUR, inferred from a past role's listed band",
        source="cv_document",
    )
    claims = read_claims(log)
    check(
        set(claims) == {"location", "salary"},
        f"intake claims were not read back intact: {sorted(claims)}",
    )

    with_claims_missing_claim = False
    try:
        resolve(
            store,
            [CandidateTurn(field="reach", action="confirm", value={"modes": ["remote"]})],
            now="2026-08-18T09:04:00Z",
        )
    except ConstraintsStepError:
        with_claims_missing_claim = True
    check(
        with_claims_missing_claim,
        "confirm on a field with no claim to confirm was accepted instead of refused",
    )

    result = resolve(
        store,
        [
            CandidateTurn(
                field="salary",
                action="confirm",
                value={"floor": 40000, "currency": "EUR"},
                text="40k EUR floor, confirmed",
            ),
            CandidateTurn(field="reach", action="decline"),
        ],
        now="2026-08-18T09:05:00Z",
    )
    written = json.loads(store.path(*CONSTRAINTS_PARTS).read_text(encoding="utf-8"))
    fields = written["fields"]

    check(
        set(fields) == set(CONSTRAINT_FIELD_NAMES),
        f"constraints.json is missing pinned fields: {set(CONSTRAINT_FIELD_NAMES) - set(fields)}",
    )
    check(
        fields["location"]["state"] == "unknown",
        "an intake claim was promoted to a fact without being confirmed",
    )
    check(fields["salary"]["state"] == "stated", "a confirmed field did not resolve to stated")
    check(fields["reach"]["state"] == "declined", "a declined field did not resolve to declined")
    check(
        fields["languages"]["state"] == "unknown",
        "a field with no claim and no turn resolved to something other than unknown",
    )
    check(fields["reach"]["state"] != "unknown", "a declined field collapsed into unknown")
    check(fields["location"]["state"] != "declined", "an unconfirmed claim was read as a decline")
    check(
        result.constraints.salary.floor == 40000,
        "the resolved typed constraints do not carry the confirmed value",
    )

    resolved_count = sum(
        1
        for name in CONSTRAINT_FIELD_NAMES
        if isinstance(fields.get(name), dict)
        and fields[name].get("state") in {"stated", "declined", "unknown"}
    )
    field_resolution = resolved_count / len(CONSTRAINT_FIELD_NAMES)
    check(
        field_resolution == 1.0,
        f"only {resolved_count}/{len(CONSTRAINT_FIELD_NAMES)} pinned fields resolved — "
        "the fraction is over the pinned set, not over what happened to be written",
    )

    try:
        loaded = load_constraints(written)
    except CandidateError as exc:
        checks += 1
        failures.append(f"T24's own loader rejected what this module wrote: {exc}")
    else:
        check(loaded.location.state == "unknown", "T24's loader disagrees about location")
        check("salary" not in loaded.outstanding(), "a stated field was reported outstanding")
        check("location" in loaded.outstanding(), "an unknown field was not reported outstanding")

    # --- opening two: required-only, no CV at all ---------------------------
    no_cv = create_profile(root, "Grace Hopper", handle="grace", language="en")
    store2 = ProfileStore(root, no_cv.handle)
    log2 = EvidenceLog(store2)
    check(read_claims(log2) == {}, "a profile with no intake activity produced a claim")

    resolve(
        store2,
        [
            CandidateTurn(
                field="location",
                action="state",
                value={"country": "PT", "accepts_onsite_in_country": True},
            ),
            CandidateTurn(field="salary", action="decline"),
        ],
        now="2026-08-18T10:00:00Z",
    )
    view = ProfileView(store2)
    check(
        sufficiency(view) == "L1",
        "a fully resolved constraint set with no CV at all did not reach L1 — "
        "the required-only path breaking again (PR #16)",
    )

    # --- non-insistence, exercised through this module's own API -----------
    resolve(
        store2, [CandidateTurn(field="employment_mode", action="decline")],
        now="2026-08-18T10:05:00Z",
    )
    resolve(
        store2, [CandidateTurn(field="employment_mode", action="decline")],
        now="2026-08-18T10:10:00Z", step="ranking",
    )
    ledger = DeclineLedger(store2)
    check(
        "employment_mode" not in open_fields(store2, step="constraints"),
        "a field declined twice is still offered to ask",
    )
    check(
        len(ledger.declines("employment_mode")) == 2,
        "the ledger does not show two declines after two decline turns",
    )
    resolve(
        store2, [CandidateTurn(field="employment_mode", action="decline")],
        now="2026-08-18T10:15:00Z",
    )
    check(
        len(ledger.declines("employment_mode")) == 2,
        "a silenced field was asked again and the ledger grew a third decline",
    )

    return {
        "constraint_field_resolution": field_resolution if not failures else 0.0,
        "fields_pinned": len(CONSTRAINT_FIELD_NAMES),
        "checks_run": checks,
        "failures": failures,
    }


MINIMUM_CHECKS = 10


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `constraint_field_resolution` in a throwaway tree and record it."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="jobsearch-t41-") as tmp:
        measured = probe_resolution(Path(tmp) / "profiles")
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.constraints_step [path]` → T41's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["checks_run"] < MINIMUM_CHECKS:
        print(
            f"only {measured['checks_run']} checks ran (floor {MINIMUM_CHECKS}) — "
            "a resolution of 1.0 over nothing is not a measurement",
            file=sys.stderr,
        )
        return 3
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
