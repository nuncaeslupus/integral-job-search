"""The profile store: an append-only evidence log, and rebuild (T6).

Process specification §4.1 fixes the shape of an evidence row and §3.4 fixes
what the profile *is*: a pure function of that log. Everything derived —
`constraints.json`, `traits.json`, `weights.json`, `stories.jsonl` — is
recomputed from it and never edited in place, "because an edit that is not an
evidence row is lost at the next rebuild and produces a profile that cannot be
explained" (§6).

Three properties carry this module, and each is a test rather than a comment.

**The log only grows.** `append` is the only writer, it assigns the next id in
sequence, and there is no update or delete. "Forget that" is a `retraction` row
naming the row it suppresses (§4.1) — the original survives, so a rebuild stays
deterministic and an accidental retraction can itself be undone.

**Rebuild is deterministic to the byte.** Two rebuilds of one log produce
identical files. That is `profile_rebuild_deterministic == 1`, and it is the
cheap check that keeps "derived" honest: the moment a rebuild depends on
anything outside the log, the property fails and says so.

This is why `scored_at` in a derived file is **the newest `recorded_at` the
rebuild incorporated, not the wall clock**. Stamping the derived files with the
time the command ran would make two rebuilds of the same log differ, which
destroys the only mechanical check that the rebuild is a function of the log at
all — and it would buy nothing, because §3.4 computes staleness from the
revision rather than from a timestamp: "anything whose recorded revision is
behind the current one is stale, by definition". `scored_at` therefore answers
*as of which evidence*, which is the question a stale marker actually asks.

**One profile cannot reach another.** Every path goes through `ProfileStore`
(S3), so this module never names a directory. Writing profile B leaves profile
A byte-identical, and that is measured too.

**D-6: `constraints.json` is derived from two files of one profile, not one.**
T24 pins ten fields and their three states (`stated`, `declined`, `unknown`);
T41 is the engine that first resolves them, and a `declined` state lives in
`session/declines.jsonl` (T40's ledger), never in `evidence.jsonl` — filing a
refusal as evidence would make "what do you know about me?" answer partly with
what someone declined to discuss. So for those ten names `_build_constraints`
reads the ledger too, through `log.store` — still this one profile's own tree,
so "one profile cannot reach another" is unaffected — and still nothing but
what is on disk for this profile, so `profile_rebuild_deterministic` holds:
two rebuilds of one unchanged tree still produce identical bytes, only "the
log" now means the evidence log *and* the decline ledger together for this one
derived file.

**D-8: a capture can name the artefact it was about.** T28's own brief asks
continuous capture to record provenance as "which surface, when, in response
to what" — `step` and `recorded_at` give the first two, but nothing on this
row named the third for a capture whose subject is a specific artefact rather
than a question. Concretely: a rejection reason recorded at `step="feedback"`,
`source="offer_reaction"` was true of *every* offer decision ever captured, so
two rejections of two different jobs produced two rows a reader could not
tell apart — and a reason read back without its subject keeps the words and
loses the meaning ("too far from home" says nothing without the posting it
was about). `EvidenceRow.about` (`EvidenceSubject`, below) closes that gap.

It is `Optional`, defaulting to `None`, because the alternative — required —
would break every row already on disk. `extra="forbid"` (`Strict`, below)
polices keys *present* in the data; it says nothing about a key the schema
merely allows that a line happens not to carry. A row minted before this
field existed has no `about` key at all, and it parses exactly the way this
row's other optional fields (`occurred_at`, `retracts`) already parse a
missing key — as `None`, not as a validation error. `probe_legacy_rows_
load_without_a_subject` proves this over a hand-written pre-D-8 line rather
than arguing it from the schema, and its result feeds `profile_rebuild_
deterministic` (`probe_rebuild`, below): a rebuild over a log mixing an
old-shaped row and a subject-carrying new one must still be byte-identical
across two runs, or the backward-compatibility claim this paragraph makes is
false. The alternative the D-8 payload also weighed — a companion file keyed
by row id, the shape S5 uses for lifecycle state (`offers/lifecycle/<id>
.json`) — was rejected once this property held: a companion file buys nothing
here that an optional field does not already buy more simply, and it would be
a second thing to keep in step with the log, which is exactly the drift this
module's derived files are built to avoid.

The one option ruled out on inspection, not merely by preference: reusing
`dimensions` with a namespaced id (`"offer:sha256:…"`) needs no schema change
at all, but `dimensions` already means "which dimension this bears on" to two
shipped gates that count it — `elicit_extract.story_dimension_linkage` and
`trait_sufficiency`'s own floor — and folding a subject reference into the
same tuple would corrupt both without either gate's code changing a line.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from jobsearch.candidate import FIELD_MODELS, ConstraintState
from jobsearch.decline import DeclineLedger
from jobsearch.identity import ProfileStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T6.json"

# Where the log and the derived files live inside one profile's tree (§6).
EVIDENCE_PARTS = ("profile", "evidence.jsonl")
DERIVED_DIR = "profile"
# One stamp for the whole derived set. `stories.jsonl` is JSONL and so carries
# no header of its own; without this it could never be shown to be current, and
# a rebuild would never clear it from the stale list (T37). The manifest is
# honest about what the derived files actually are — one set, rebuilt together
# from one log, at one revision.
DERIVED_MANIFEST = ".derived.json"

# §4.1's row kinds. `retraction` is one of them rather than a separate mechanism,
# which is what makes "forget that" survive a rebuild.
Kind = Literal["episode", "statement", "reaction", "constraint", "outcome", "retraction"]
Source = Literal["conversation", "cv_document", "offer_reaction", "interview"]
# Private by default, and it stays private without a per-use approval (§6.2).
Disclosure = Literal["private", "approved_for_use"]
Precision = Literal["day", "month", "year"]

EVIDENCE_ID = re.compile(r"^ev-\d{6,}$")
DIMENSION_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_ID_WIDTH = 6


class ProfileError(Exception):
    """The evidence log does not satisfy the §4.1 contract."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# D-8. Which kind of artefact `EvidenceRow.about` names. `offer` is the only
# value today: the only capture surface shipped so far that ties a row to one
# specific external artefact, rather than to a bank question, is
# `profile_capture.capture_offer_decision_reason` (T28), reacting to one
# `Offer` (T11). A reaction (T17) or an interview record (S6) will each add
# their own kind when they land — additive to this `Literal` and to nothing
# else, since `EvidenceRow.about` is already `Optional[EvidenceSubject]`.
SubjectKind = Literal["offer"]

# T11's own offer-id shape (`jobsearch.offers._OFFER_ID_PATTERN`), duplicated
# rather than imported. `profile.py` is imported by nearly every other module
# in this codebase (`retraction`, `revision`, `elicit_extract`,
# `trait_sufficiency`, `profile_capture`, `cv_store`) and depends on none of
# them; reaching into `offers.py` for one regex would be a new edge in that
# graph for no real gain, the same reasoning `_last_pinned_value` gives for
# keeping its own copy of a T41 encoding rather than importing it back.
_OFFER_SUBJECT_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


class EvidenceSubject(Strict):
    """D-8: the artefact one capture was in response to.

    "In response to what" — the third element of T28's own provenance brief
    that no field on `EvidenceRow` previously carried. `kind` names what sort
    of artefact; `id` names which one. Deliberately not free text: a label a
    human can read but nothing downstream can look up would not let T21 trace
    a rejection reason back to the offer it changed a ranking about, which is
    the whole reason this field exists (`status/plan.md`'s T21 row,
    `feedback_traceability == 1.0`).

    Only `kind="offer"` is validated against a real id shape today — see
    `_OFFER_SUBJECT_ID` — because it is the only kind any writer produces yet.
    A future kind defines its own id shape when it lands, not this one.
    """

    kind: SubjectKind
    id: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> EvidenceSubject:
        if self.kind == "offer" and not _OFFER_SUBJECT_ID.match(self.id):
            raise ValueError(f"{self.id!r} is not a T11 offer id (sha256:<64 lowercase hex>)")
        return self


class EvidenceRow(Strict):
    """One row of `profile/evidence.jsonl` — process specification §4.1.

    `occurred_at` is separate from `recorded_at` on purpose: it is what makes
    "two years have passed since that job ended" computable, and the freshness
    triggers of §5.2 depend on it. It is optional because most of what a
    candidate says has no date attached, and inventing one would make an
    elapsed-time trigger fire on a number nobody stated.

    `about` (D-8) is the artefact this row was in response to — the third
    element of "which surface, when, in response to what" that `step` and
    `recorded_at` alone could not answer for a capture whose subject is a
    specific artefact rather than a question. It is optional for the same
    reason `occurred_at` and `retracts` already are: most rows (an answer to
    a bank question, a CV import, a constraint statement) have their subject
    named some other way already, and a row written before this field existed
    has no `about` key on disk at all — see the module docstring's D-8
    paragraph for why that must, and does, still load.
    """

    id: str = Field(pattern=EVIDENCE_ID.pattern)
    recorded_at: str
    occurred_at: str | None = None
    occurred_precision: Precision | None = None
    step: str = Field(min_length=1, max_length=64)
    kind: Kind
    dimensions: tuple[str, ...] = ()
    text: str
    source: Source
    disclosure: Disclosure = "private"
    # Set only on a `retraction` row: the id of the row it suppresses (§4.1).
    retracts: str | None = None
    about: EvidenceSubject | None = None

    @model_validator(mode="after")
    def _check(self) -> EvidenceRow:
        for dimension in self.dimensions:
            if not DIMENSION_ID.match(dimension):
                # Not checked against `dimensions/*.yaml`: the log is written by
                # every step and must not fail because the ontology moved under
                # it. `ontology_hit_rate` (T17) is where unmapped concepts get
                # counted; here the shape is all that is enforced.
                raise ValueError(f"{dimension!r} is not a dimension id")
        if self.kind == "retraction":
            if not self.retracts:
                raise ValueError("a retraction row must name the row it suppresses")
        elif self.retracts is not None:
            raise ValueError(f"only a retraction row may set `retracts` (kind={self.kind})")
        if self.occurred_precision is not None and self.occurred_at is None:
            raise ValueError("occurred_precision without occurred_at says nothing")
        return self

    def canonical(self) -> str:
        """The row as one line of JSONL — sorted keys, no spare whitespace.

        Sorted so a diff of the log is readable and so two writers of the same
        row produce the same bytes; `exclude_none` so an absent `occurred_at`
        does not fill the log with nulls nobody reads.
        """
        payload = self.model_dump(exclude_none=True)
        payload["dimensions"] = list(self.dimensions)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class ProfileRevision:
    """`{rows, sha256}` — process specification §3.4.

    The profile is a pure function of the log, so the log identifies the
    profile and no separate revision file is needed. Everything derived records
    the revision it was computed from; anything behind the current one is stale
    by definition.
    """

    rows: int
    sha256: str

    def as_json(self) -> dict[str, Any]:
        return {"rows": self.rows, "sha256": self.sha256}

    @classmethod
    def of_nothing(cls) -> ProfileRevision:
        """The revision of a profile whose log does not exist yet.

        The sha256 of the empty byte string, not a sentinel: a profile with no
        evidence and a profile whose log was emptied are the same profile, and
        a special-case marker here would make the first rebuild look like a
        different kind of event from every later one.
        """
        return cls(rows=0, sha256=hashlib.sha256(b"").hexdigest())


class EvidenceLog:
    """Append-only access to one profile's `profile/evidence.jsonl`.

    Constructed from a `ProfileStore`, so it inherits S3's guarantee: this class
    never names a directory and cannot be pointed at another candidate's tree.
    """

    def __init__(self, store: ProfileStore) -> None:
        self.store = store

    @property
    def handle(self) -> str:
        return self.store.handle

    def exists(self) -> bool:
        return self.store.exists(*EVIDENCE_PARTS)

    def raw_bytes(self) -> bytes:
        path = self.store.path(*EVIDENCE_PARTS)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return b""

    def rows(self) -> list[EvidenceRow]:
        """Every row ever appended, in order, including retracted ones.

        Retracted rows are *here* and suppressed in `effective_rows`. Dropping
        them at read time would make a retraction indistinguishable from a
        deletion, and §4.1 is explicit that it is not one.
        """
        parsed: list[EvidenceRow] = []
        for number, line in enumerate(self.raw_bytes().decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                parsed.append(EvidenceRow.model_validate_json(line))
            except ValidationError as exc:
                raise ProfileError(f"evidence.jsonl:{number} is not a valid row: {exc}") from exc
        return parsed

    def revision(self) -> ProfileRevision:
        raw = self.raw_bytes()
        if not raw:
            return ProfileRevision.of_nothing()
        rows = sum(1 for line in raw.decode("utf-8").splitlines() if line.strip())
        return ProfileRevision(rows=rows, sha256=hashlib.sha256(raw).hexdigest())

    def next_id(self) -> str:
        """`ev-000001`, `ev-000002`, … — the next id in sequence.

        Derived from the highest id present rather than from the row count, so
        a log that was concatenated or hand-repaired cannot mint an id that
        already exists — and a duplicate id is what would let a retraction
        suppress the wrong row.
        """
        highest = 0
        for row in self.rows():
            highest = max(highest, int(row.id.removeprefix("ev-")))
        return f"ev-{highest + 1:0{_ID_WIDTH}d}"

    def append(
        self,
        *,
        recorded_at: str,
        step: str,
        kind: Kind,
        text: str,
        source: Source,
        dimensions: Sequence[str] = (),
        occurred_at: str | None = None,
        occurred_precision: Precision | None = None,
        disclosure: Disclosure = "private",
        retracts: str | None = None,
        about: EvidenceSubject | None = None,
    ) -> EvidenceRow:
        """Add one row. The only writer, and it never rewrites what is there."""
        if retracts is not None and not self._has(retracts):
            raise ProfileError(f"cannot retract {retracts!r}: no such row in this profile's log")
        row = EvidenceRow(
            id=self.next_id(),
            recorded_at=recorded_at,
            occurred_at=occurred_at,
            occurred_precision=occurred_precision,
            step=step,
            kind=kind,
            dimensions=tuple(dimensions),
            text=text,
            source=source,
            disclosure=disclosure,
            retracts=retracts,
            about=about,
        )
        path = self.store.path(*EVIDENCE_PARTS)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(row.canonical() + "\n")
        return row

    def _has(self, row_id: str) -> bool:
        return any(row.id == row_id for row in self.rows())

    def suppressed_ids(self) -> frozenset[str]:
        """Which rows a retraction currently suppresses.

        A retraction can itself be retracted, and then the row it suppressed is
        live again — which is how "an accidental retraction can itself be
        undone" (§4.1) works without anything being deleted. That undoing
        nests: retracting the retraction of a retraction puts the original back
        under suppression, and a single pass over the log gets the second level
        right and the third wrong.

        So it is a fixpoint instead. A retraction bites only while it is itself
        unsuppressed; recompute until the set stops moving. The iteration is
        bounded because a log that somehow encodes a cycle must fail loudly
        rather than spin — a rebuild that never returns is worse than one that
        reports a broken log.
        """
        retractions = [
            row for row in self.rows() if row.kind == "retraction" and row.retracts is not None
        ]
        suppressed: frozenset[str] = frozenset()
        for _ in range(len(retractions) + 2):
            following = frozenset(
                row.retracts
                for row in retractions
                if row.id not in suppressed and row.retracts is not None
            )
            if following == suppressed:
                return suppressed
            suppressed = following
        raise ProfileError(
            "the retraction chain in evidence.jsonl does not settle — "
            "a row retracts something that retracts it back"
        )

    def effective_rows(self) -> list[EvidenceRow]:
        """The rows a rebuild may use: everything live, retractions excluded.

        The retraction rows themselves are excluded too. They are bookkeeping
        about the log, not evidence about the candidate, and a derived file
        that listed them would be answering "what has been forgotten" to a
        question that asked what is known.
        """
        suppressed = self.suppressed_ids()
        return [
            row for row in self.rows() if row.kind != "retraction" and row.id not in suppressed
        ]


# ---------------------------------------------------------------------------
# rebuild


def _scored_at(rows: Iterable[EvidenceRow]) -> str | None:
    """The newest `recorded_at` a rebuild incorporated — see the module docstring."""
    stamps = [row.recorded_at for row in rows]
    return max(stamps) if stamps else None


def _header(log: EvidenceLog, rows: Sequence[EvidenceRow]) -> dict[str, Any]:
    return {
        "profile_revision": log.revision().as_json(),
        "scored_at": _scored_at(rows),
    }


def _last_pinned_value(
    rows: Sequence[EvidenceRow], field: str
) -> tuple[EvidenceRow, dict[str, Any]] | None:
    """The most recent T41-encoded `stated` value for one of T24's ten fields.

    Mirrors `constraints_step._last_stated_value` exactly: same encoding
    (`{"quote": ..., "value": ...}`, T41's `_encode_stated`), same
    newest-first replay, same "cannot interpret it, cannot replay it" skip on
    a row this cannot decode. Kept as its own copy rather than an import of
    T41's function — `jobsearch.constraints_step` imports this module at load
    time, so importing back would cycle, and T24/T41 own naming the
    vocabulary; T6 only replays what they wrote.
    """
    for row in reversed(rows):
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


def _resolve_pinned_field(
    rows: Sequence[EvidenceRow], declines: Sequence[Any], field: str
) -> tuple[ConstraintState, dict[str, Any] | None, bool]:
    """One pinned field's `(state, value, touched)`.

    The same reconciliation T41 applies when a call offers it no new turn for
    a field (`constraints_step._resolve_without_turn`): whichever of a prior
    stated row or a decline happened more recently wins. `touched` says
    whether either history has anything to say about this field at all — see
    `_resolve_pinned_fields` for why that decides whether the field is written
    at all.
    """
    stated = _last_pinned_value(rows, field)
    touched = stated is not None or bool(declines)
    if stated is not None:
        row, value = stated
        last_decline_at = declines[-1].at if declines else None
        if last_decline_at is None or row.recorded_at >= last_decline_at:
            return "stated", value, touched
    if declines:
        return "declined", None, touched
    return "unknown", None, touched


def _resolve_pinned_fields(
    log: EvidenceLog, rows: Sequence[EvidenceRow]
) -> dict[str, dict[str, Any]]:
    """T24's ten pinned fields, in T41's own shape — present only if touched.

    "Touched" means a stated value or a decline has ever been recorded against
    one of the ten names, by either history. A profile that has never reached
    Constraints must not read as ten resolved `unknown`s just because a
    rebuild ran: `step_runtime._constraints_resolved` counts `unknown` as
    resolved, so writing it unconditionally would tell sufficiency a step ran
    that never did. The moment one field is touched, all ten are written —
    exactly `constraints_step.write_constraints`'s own behaviour, which this
    reproduces so a rebuild after Constraints is a no-op rather than a
    regression.
    """
    ledger = DeclineLedger(log.store)
    resolved: dict[str, dict[str, Any]] = {}
    any_touched = False
    for field, model in FIELD_MODELS.items():
        declines = ledger.declines(field)
        state, value, touched = _resolve_pinned_field(rows, declines, field)
        any_touched = any_touched or touched
        try:
            instance = (
                model(state="stated", **value)
                if state == "stated" and value is not None
                else model(state=state)
            )
        except ValidationError:
            # A row this shape check refuses is not a fact to carry forward —
            # the same "cannot interpret it, cannot replay it" discipline as
            # `_last_pinned_value`'s decode skip, just caught one step later.
            instance = model(state="unknown")
        resolved[field] = instance.model_dump(mode="json")
    return resolved if any_touched else {}


def _build_constraints(log: EvidenceLog, rows: Sequence[EvidenceRow]) -> dict[str, Any]:
    """Constraint rows folded into fields, each in one of three states.

    T24 pins ten field names and T41 owns the confirm-and-fill engine that
    first resolves them; what T6 owns is that the file stays *derived* — a
    rebuild must reproduce it, not merely reproduce whatever part happens to
    live in `evidence.jsonl`. For those ten names this function replays T41's
    own resolution (`_resolve_pinned_fields`, module docstring) rather than
    the plain evidence-id fold below, because a `declined` or `unknown` state
    the plain fold cannot see (it lives in the decline ledger, or nowhere at
    all) must survive a rebuild exactly as a `stated` one already did — a
    field the candidate explicitly refused must not revert to
    indistinguishable-from-never-asked just because something upstream
    changed and `revision.refresh` recomputed this file (D-6).

    A dimension outside the pinned ten is folded the old way, unchanged:
    whatever `dimensions` a constraint row carries, however a step tagged it,
    with the evidence ids that stated it. A field nobody stated is absent
    here rather than present-and-empty, because "unknown" and "stated as
    nothing" are different answers and only T24 gets to name the difference.
    """
    generic: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.kind != "constraint":
            continue
        for dimension in row.dimensions or ("unattributed",):
            if dimension in FIELD_MODELS:
                continue  # T24's pinned fields are resolved below, trichotomy and all
            generic.setdefault(dimension, {"state": "stated", "evidence": []})
            generic[dimension]["evidence"].append(row.id)

    fields: dict[str, dict[str, Any]] = {**generic, **_resolve_pinned_fields(log, rows)}
    return {**_header(log, rows), "fields": dict(sorted(fields.items()))}


def _build_traits(log: EvidenceLog, rows: Sequence[EvidenceRow]) -> dict[str, Any]:
    """Per-dimension evidence references — §6: "derived, with evidence row references".

    No scoring happens here. T27 and T28 own the trait scores and the
    two-episode floor; T6 owns the fact that whatever they compute is rebuilt
    from the log and traces back to row ids.
    """
    by_dimension: dict[str, list[str]] = {}
    for row in rows:
        for dimension in row.dimensions:
            by_dimension.setdefault(dimension, []).append(row.id)
    return {
        **_header(log, rows),
        "dimensions": {
            dimension: {"evidence": ids, "evidence_count": len(ids)}
            for dimension, ids in sorted(by_dimension.items())
        },
    }


def _build_weights(log: EvidenceLog, rows: Sequence[EvidenceRow]) -> dict[str, Any]:
    """The salary-equivalent weights file — shaped now, computed by T10.

    It is written even while empty so that "no weights yet" is a file saying so
    at a known revision, rather than a missing file every later reader has to
    guess about. That distinction is what lets T34 call a ranking L1.
    """
    reactions = [row.id for row in rows if row.kind == "reaction"]
    return {
        **_header(log, rows),
        "part_worths": {},
        "reaction_evidence": reactions,
    }


def _build_stories(log: EvidenceLog, rows: Sequence[EvidenceRow]) -> list[dict[str, Any]]:
    """Episodes, linked to dimensions, in log order — §6's `stories.jsonl`.

    Log order rather than any scoring order: the episodes are the candidate's
    own words in the order they said them, and T8 links each to a dimension.
    Disclosure is carried through unchanged, because an episode reaches an
    employer-bound document only with per-use approval (§6.2) and the derived
    file must not be where that fact gets lost.
    """
    return [
        {
            "id": row.id,
            "dimensions": list(row.dimensions),
            "disclosure": row.disclosure,
            "occurred_at": row.occurred_at,
            "occurred_precision": row.occurred_precision,
            "recorded_at": row.recorded_at,
            "step": row.step,
            "text": row.text,
        }
        for row in rows
        if row.kind == "episode"
    ]


def _as_json_bytes(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _as_jsonl_bytes(payload: Sequence[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in payload)


@dataclass(frozen=True)
class Derived:
    """One derived file: its name, and the pure function that produces it."""

    filename: str
    build: Callable[[EvidenceLog, Sequence[EvidenceRow]], Any]
    render: Callable[[Any], str]


DERIVED: tuple[Derived, ...] = (
    Derived("constraints.json", _build_constraints, _as_json_bytes),
    Derived("stories.jsonl", _build_stories, _as_jsonl_bytes),
    Derived("traits.json", _build_traits, _as_json_bytes),
    Derived("weights.json", _build_weights, _as_json_bytes),
)


def rebuild(store: ProfileStore) -> dict[str, str]:
    """Recompute every derived file from the log. Returns `{filename: content}`.

    Pure in everything but the write: the same log yields the same bytes, on
    any machine, at any time. Nothing here reads the clock, the environment or
    another profile — which is exactly what `profile_rebuild_deterministic`
    measures, and why the measurement is worth anything.
    """
    log = EvidenceLog(store)
    rows = log.effective_rows()
    written: dict[str, str] = {}
    for artefact in DERIVED:
        content = artefact.render(artefact.build(log, rows))
        store.write_text(content, DERIVED_DIR, artefact.filename)
        written[artefact.filename] = content
    store.write_json(
        {
            "profile_revision": log.revision().as_json(),
            "scored_at": _scored_at(rows),
            "files": sorted(written),
        },
        DERIVED_DIR,
        DERIVED_MANIFEST,
    )
    return written


def derived_bytes(store: ProfileStore) -> dict[str, bytes]:
    """What is currently on disk for each derived file, for comparison."""
    snapshot: dict[str, bytes] = {}
    for artefact in DERIVED:
        path = store.path(DERIVED_DIR, artefact.filename)
        snapshot[artefact.filename] = path.read_bytes() if path.exists() else b""
    return snapshot


def tree_bytes(store: ProfileStore) -> dict[str, bytes]:
    """Every file in one profile's tree, keyed by its path relative to the tree.

    Used to prove that writing profile B changed nothing in profile A — a
    property that is easy to state, easy to believe, and only true if somebody
    compares the bytes.
    """
    home = store.path()
    if not home.is_dir():
        return {}
    return {
        str(path.relative_to(home)): path.read_bytes()
        for path in sorted(home.rglob("*"))
        if path.is_file()
    }


# ---------------------------------------------------------------------------
# the gate


_FIXTURE = (
    {
        "recorded_at": "2026-08-17T10:04:11Z",
        "occurred_at": "2026-03-01",
        "occurred_precision": "month",
        "step": "history",
        "kind": "episode",
        "dimensions": ["team_autonomy"],
        "text": "They let me pick the stack and nobody second-guessed it.",
        "source": "conversation",
    },
    {
        "recorded_at": "2026-08-17T10:06:02Z",
        "step": "constraints",
        "kind": "constraint",
        "dimensions": ["remote_work"],
        "text": "Fully remote, or nothing.",
        "source": "conversation",
    },
    {
        "recorded_at": "2026-08-17T10:09:40Z",
        "step": "reactions",
        "kind": "reaction",
        "dimensions": ["on_call"],
        "text": "On-call every third week? No.",
        "source": "offer_reaction",
    },
)


def probe_rebuild(root: Path) -> list[str]:
    """Build the two-profile fixture and check the two properties that matter.

    Adversarial in the same spirit as S3's probes: the checks are the ways a
    rebuild stops being a function of the log — a stamp from the clock, a
    derived file that accumulates instead of being replaced, a write to one
    profile that touches another. Each failure is named in the returned list.
    """
    from jobsearch.identity import create_profile

    failures: list[str] = []
    first = EvidenceLog(
        ProfileStore(root, create_profile(root, "Probe One", handle="probe-one").handle)
    )
    second = EvidenceLog(
        ProfileStore(root, create_profile(root, "Probe Two", handle="probe-two").handle)
    )
    for payload in _FIXTURE:
        first.append(**payload)  # type: ignore[arg-type]

    once = rebuild(first.store)
    twice = rebuild(first.store)
    for filename in sorted(set(once) | set(twice)):
        if once.get(filename) != twice.get(filename):
            failures.append(f"{filename} differs between two rebuilds of one log")

    on_disk = derived_bytes(first.store)
    if on_disk != {name: content.encode("utf-8") for name, content in twice.items()}:
        failures.append("what was written to disk is not what rebuild returned")

    # A retracted row must be gone from everything derived, and still in the log.
    episode = first.rows()[0]
    first.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="history",
        kind="retraction",
        text="Forget that.",
        source="conversation",
        retracts=episode.id,
    )
    after = rebuild(first.store)
    if episode.text in "".join(after.values()):
        failures.append("a retracted row survived into a derived file")
    if episode.text not in first.raw_bytes().decode("utf-8"):
        failures.append("a retraction removed the row from the log, which is not append-only")

    # And the neighbouring profile is untouched by all of it.
    before = tree_bytes(first.store)
    for payload in _FIXTURE:
        second.append(**payload)  # type: ignore[arg-type]
    rebuild(second.store)
    if tree_bytes(first.store) != before:
        failures.append("writing the second profile changed the first")

    failures.extend(probe_legacy_rows_load_without_a_subject(root))

    return failures


def probe_legacy_rows_load_without_a_subject(root: Path) -> list[str]:
    """D-8: a row minted before `EvidenceSubject` existed has no `about` key.

    `EvidenceRow` is `extra="forbid"` and frozen, which polices keys *present*
    in the data — never keys the schema merely allows a line not to carry. A
    JSONL line written before this field existed simply lacks the key, and
    `about: EvidenceSubject | None = None` parses a missing key exactly the
    way `occurred_at` or `retracts` already do. This is the check the D-8
    payload asks for before choosing the optional field over a companion
    file: a hand-written pre-D-8 line is written straight to a fresh log's
    file — bypassing `EvidenceLog.append`, which would always write the
    current shape — and a rebuild over a log mixing that legacy row with a
    subject-carrying new one must still be deterministic, the same property
    `profile_rebuild_deterministic` already guards, now exercised over
    exactly the row shape that motivated D-8.
    """
    from jobsearch.identity import create_profile

    failures: list[str] = []
    identity = create_profile(root, "Probe Legacy", handle="probe-legacy")
    store = ProfileStore(root, identity.handle)
    log = EvidenceLog(store)

    legacy_line = json.dumps(
        {
            "dimensions": [],
            "id": "ev-000001",
            "kind": "statement",
            "recorded_at": "2026-08-01T09:00:00Z",
            "source": "offer_reaction",
            "step": "feedback",
            "text": "Too far from home.",
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    path = store.path(*EVIDENCE_PARTS)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(legacy_line + "\n", encoding="utf-8")

    try:
        legacy_rows = log.rows()
    except ProfileError as exc:
        failures.append(f"a pre-D-8 row with no 'about' key failed to load: {exc}")
        return failures
    if legacy_rows[0].about is not None:
        failures.append("a row with no 'about' key on disk read back with a non-None subject")

    log.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="feedback",
        kind="statement",
        text="Too far from the new one, too.",
        source="offer_reaction",
        about=EvidenceSubject(kind="offer", id=f"sha256:{'0' * 64}"),
    )
    once = rebuild(store)
    twice = rebuild(store)
    if once != twice:
        failures.append(
            "a log mixing a pre-D-8 row and a subject-carrying row did not rebuild "
            "deterministically"
        )
    return failures


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `profile_rebuild_deterministic` in a throwaway tree and record it."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="jobsearch-t6-") as tmp:
        failures = probe_rebuild(Path(tmp) / "profiles")
    measured: dict[str, Any] = {
        "profile_rebuild_deterministic": 0 if failures else 1,
        "derived_files": [artefact.filename for artefact in DERIVED],
        "failures": failures,
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


# ---------------------------------------------------------------------------
# D-6's gate — a resolved constraint state must survive a refresh

DEFAULT_D6_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D6.json"

# One target state per pinned field, cycling through all three so the gate
# exercises `stated`, `declined` and `unknown` rather than just one of them —
# 4 stated, 3 declined, 3 unknown across T24's ten names. `None` is the value
# payload for a field this fixture declines or leaves untouched; a `state`
# turn always carries one.
_D6_FIXTURE: tuple[tuple[str, ConstraintState, dict[str, Any] | None], ...] = (
    ("languages", "stated", {"levels": [{"language": "en", "level": "professional"}]}),
    ("location", "declined", None),
    ("relocation", "unknown", None),
    ("salary", "stated", {"floor": 40000, "currency": "EUR"}),
    ("availability", "declined", None),
    ("work_authorisation", "unknown", None),
    ("employment_mode", "stated", {"accepted": ["employed"]}),
    ("pay_country", "declined", None),
    ("tax_country", "unknown", None),
    ("reach", "stated", {"modes": ["remote"]}),
)
MINIMUM_FIELDS_CHECKED = len(_D6_FIXTURE)


def probe_constraint_survival(root: Path) -> dict[str, Any]:
    """Resolve all ten of T24's pinned fields, refresh, and see what survives.

    D-6: before the fix, `revision.refresh` called this module's `rebuild`,
    whose generic fold only ever produced `stated` from an evidence-log row —
    a `declined` field (recorded in T40's ledger, not the log) or an
    unaddressed `unknown` one disappeared from `constraints.json` the moment
    anything upstream refreshed it. This drives a genuine
    resolve-then-refresh cycle over every one of the ten fields, each in one
    of the three states, and counts how many come out of the refresh
    byte-for-byte unchanged.
    """
    from jobsearch.constraints_step import CandidateTurn, resolve
    from jobsearch.identity import create_profile
    from jobsearch.revision import refresh

    identity = create_profile(root, "Probe D6", handle="probe-d6")
    store = ProfileStore(root, identity.handle)

    turns = [
        CandidateTurn(field=field, action="state", value=value)
        for field, state, value in _D6_FIXTURE
        if state == "stated"
    ] + [
        CandidateTurn(field=field, action="decline")
        for field, state, _ in _D6_FIXTURE
        if state == "declined"
    ]
    # The remaining fixture fields (`state == "unknown"`) get no turn at all —
    # that is what makes them unknown: nobody has addressed them yet.
    resolve(store, turns, now="2026-08-18T09:00:00Z")

    constraints_path = store.path("profile", "constraints.json")
    before = json.loads(constraints_path.read_text(encoding="utf-8"))["fields"]

    refresh(store)

    after = json.loads(constraints_path.read_text(encoding="utf-8"))["fields"]

    survived: list[str] = []
    lost: list[str] = []
    for field, expected_state, _ in _D6_FIXTURE:
        entry = after.get(field)
        if (
            isinstance(entry, dict)
            and entry.get("state") == expected_state
            and entry == before.get(field)
        ):
            survived.append(field)
        else:
            lost.append(
                f"{field}: expected {expected_state!r} to survive the refresh — "
                f"before={before.get(field)!r} after={entry!r}"
            )

    return {
        "constraint_states_survive_rebuild": len(survived) / len(_D6_FIXTURE),
        "fields_checked": len(_D6_FIXTURE),
        "states_covered": sorted({state for _, state, _ in _D6_FIXTURE}),
        "survived": survived,
        "lost": lost,
    }


def write_constraint_survival_evidence(
    evidence: Path = DEFAULT_D6_EVIDENCE_PATH,
) -> dict[str, Any]:
    """Measure `constraint_states_survive_rebuild` (D-6) in a throwaway tree."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="jobsearch-d6-") as tmp:
        measured = probe_constraint_survival(Path(tmp) / "profiles")
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.profile [path]` → T6's gate evidence.

    `python -m jobsearch.profile --constraint-survival [path]` → D-6's gate
    evidence instead — a second, independent measurement over the same
    module, kept as a flag rather than a new file because the property it
    checks (a resolved state surviving *this* module's own `rebuild`) belongs
    to `rebuild`, not to a module of its own.
    """
    if "--constraint-survival" in argv[1:]:
        positional = [arg for arg in argv[1:] if not arg.startswith("--")]
        target = Path(positional[0]) if positional else DEFAULT_D6_EVIDENCE_PATH
        measured = write_constraint_survival_evidence(target)
        print(json.dumps(measured, ensure_ascii=False))
        if measured["fields_checked"] < MINIMUM_FIELDS_CHECKED:
            print(
                f"only {measured['fields_checked']} fields were checked "
                f"(floor {MINIMUM_FIELDS_CHECKED}) — full survival over nothing is not "
                "a measurement",
                file=sys.stderr,
            )
            return 3
        for loss in measured["lost"]:
            print(loss, file=sys.stderr)
        return 1 if measured["lost"] else 0

    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    for failure in measured["failures"]:
        print(f"rebuild is not deterministic: {failure}", file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
