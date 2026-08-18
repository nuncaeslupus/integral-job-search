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

from jobsearch.identity import ProfileStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T6.json"

# Where the log and the derived files live inside one profile's tree (§6).
EVIDENCE_PARTS = ("profile", "evidence.jsonl")
DERIVED_DIR = "profile"

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


class EvidenceRow(Strict):
    """One row of `profile/evidence.jsonl` — process specification §4.1.

    `occurred_at` is separate from `recorded_at` on purpose: it is what makes
    "two years have passed since that job ended" computable, and the freshness
    triggers of §5.2 depend on it. It is optional because most of what a
    candidate says has no date attached, and inventing one would make an
    elapsed-time trigger fire on a number nobody stated.
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


def _build_constraints(log: EvidenceLog, rows: Sequence[EvidenceRow]) -> dict[str, Any]:
    """Constraint rows folded into fields, each in one of three states.

    T24 pins the field set and T41 owns the confirm-and-fill engine; what T6
    owns is that the file is *derived* — regenerated from the log, in a stable
    order, and never edited in place. A field nobody stated is absent here
    rather than present-and-empty, because "unknown" and "stated as nothing"
    are different answers and only T24 gets to name the difference.
    """
    stated: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.kind != "constraint":
            continue
        for dimension in row.dimensions or ("unattributed",):
            stated.setdefault(dimension, {"state": "stated", "evidence": []})
            stated[dimension]["evidence"].append(row.id)
    return {**_header(log, rows), "fields": dict(sorted(stated.items()))}


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


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.profile [path]` → T6's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    for failure in measured["failures"]:
        print(f"rebuild is not deterministic: {failure}", file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
