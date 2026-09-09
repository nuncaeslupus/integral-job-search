"""Profile revision, and the three classes of staleness (T37).

Process specification §3.4 says going back with new information must *revise*
what later steps produced rather than throw it away, and what happens depends
on which of three classes the downstream artefact belongs to:

* **derived** — recomputed from the log, never edited in place. Recomputation
  is always safe because nothing was hand-authored into them.
* **authored** — marked **stale**, with the reason and the fields that changed,
  and kept exactly as they are. Regeneration is offered, never automatic.
* **historical** — immutable. Never revised, only appended to.

The distinction that matters is **authored**: a CV may already be with an
employer. Silently regenerating it leaves the candidate unable to answer a
question about their own application — so the old version survives, and the
stale marker says what changed and why it might matter.

**Staleness is computed, not tracked.** §3.4: the profile is a pure function of
the append-only log, so the log identifies the profile, and anything whose
recorded revision is behind the current one is stale *by definition*. There is
no staleness flag to set, forget to set, or set wrongly — which is the whole
reason the revision is `{rows, sha256}` of the log rather than a counter
somebody increments.

The gate is `stale_artefact_detection_recall == 1.0`: of the artefacts that
really are behind, the fraction reported. Recall rather than precision, because
the expensive failure is the silent one — an out-of-date CV shown as current is
worse than a current one flagged for a second look.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from integral.identity import ProfileStore
from integral.profile import EvidenceLog, EvidenceRow, ProfileRevision

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T37.json"

ArtefactClass = Literal["derived", "authored", "historical"]

# Where each class lives inside one candidate's tree (§6's artefact tree).
# Matched most-specific-first, because `interviews/<offer>/preparation.md` is
# authored while everything else under `interviews/` is historical — the record
# of what happened, which is not revisable, next to the notes made before it,
# which are.
_CLASSES: tuple[tuple[tuple[str, ...], ArtefactClass], ...] = (
    (("profile", "evidence.jsonl"), "historical"),
    (("offers", "tombstones.jsonl"), "historical"),
    (("applications",), "historical"),
    (("interviews", "*", "preparation"), "authored"),
    (("interviews",), "historical"),
    (("cv", "source"), "historical"),
    (("cv", "generated"), "authored"),
    (("profile",), "derived"),
    (("extractions",), "derived"),
    (("annotations",), "derived"),
    (("rankings",), "derived"),
)

# Derived and authored artefacts record the revision they were computed from;
# historical ones do not, because they are never recomputed against one.
REVISIONED: frozenset[ArtefactClass] = frozenset({"derived", "authored"})


class RevisionError(Exception):
    """An artefact's recorded revision cannot be read."""


def classify(relative: Path | str) -> ArtefactClass:
    """Which of §3.4's three classes an artefact belongs to, by where it lives.

    By location rather than by a field inside the file: a file that has to
    declare its own class can declare the wrong one, and the one that matters —
    a generated CV claiming to be derived — is exactly the file that would then
    be silently regenerated after it had been sent.
    """
    parts = Path(relative).parts
    for pattern, klass in _CLASSES:
        if _matches(parts, pattern):
            return klass
    # Anything unplaced is treated as authored: the safe default is "tell the
    # candidate it may be out of date", never "regenerate it without asking".
    return "authored"


def _matches(parts: Sequence[str], pattern: Sequence[str]) -> bool:
    if len(parts) < len(pattern):
        return False
    for part, expected in zip(parts, pattern, strict=False):
        if expected == "*":
            continue
        if expected.endswith(".jsonl") or expected.endswith(".json"):
            if part != expected:
                return False
        elif not part.startswith(expected):
            return False
    return True


@dataclass(frozen=True)
class Stale:
    """One artefact that is behind the current profile revision.

    `action` is what §3.4 permits for this class, and it is carried out of the
    detection rather than decided by the caller — a caller that chose would
    eventually choose "regenerate" for something authored.
    """

    artefact: str
    artefact_class: ArtefactClass
    recorded: ProfileRevision | None
    current: ProfileRevision
    changed: tuple[str, ...]
    rows_behind: int

    @property
    def action(self) -> str:
        if self.artefact_class == "derived":
            return "recompute"
        return "offer to regenerate"

    def reason(self) -> str:
        """What changed, in the terms §3.4 asks a stale marker to carry."""
        rows = f"{self.rows_behind} new evidence row{'s' if self.rows_behind != 1 else ''}"
        if self.changed:
            return f"{rows} since it was made, touching {', '.join(self.changed)}"
        return f"{rows} since it was made"


def recorded_revision(payload: Any) -> ProfileRevision | None:
    """The revision an artefact says it was computed from, if it says.

    An artefact of a revisioned class that records nothing is treated as behind
    rather than as current — the alternative is that forgetting to stamp a file
    makes it permanently fresh, which is the failure mode with no symptom.
    """
    if not isinstance(payload, dict):
        return None
    stamp = payload.get("profile_revision")
    if not isinstance(stamp, dict):
        return None
    rows, digest = stamp.get("rows"), stamp.get("sha256")
    if not isinstance(rows, int) or not isinstance(digest, str):
        return None
    return ProfileRevision(rows=rows, sha256=digest)


def _read_stamp(store: ProfileStore, relative: Path) -> ProfileRevision | None:
    path = store.path(*relative.parts)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if path.suffix == ".jsonl":
        # A JSONL artefact carries no header, so it has no stamp of its own.
        # The derived set is rebuilt together from one log, so `rebuild` writes
        # one manifest for all of them and that is what says which revision
        # this file is at. Without the fallback a derived JSONL could never be
        # shown to be current, and a rebuild would never clear it.
        return _manifest_revision(store, relative)
    try:
        return recorded_revision(json.loads(text))
    except json.JSONDecodeError:
        return None


def _manifest_revision(store: ProfileStore, relative: Path) -> ProfileRevision | None:
    """The revision recorded by the manifest of this artefact's derived set."""
    from integral.profile import DERIVED_MANIFEST

    manifest = store.path(*relative.parent.parts, DERIVED_MANIFEST)
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if relative.name not in payload.get("files", []):
        return None
    return recorded_revision(payload)


def rows_since(log: EvidenceLog, revision: ProfileRevision | None) -> list[EvidenceRow]:
    """The evidence that has arrived since an artefact was made.

    Indexed by position rather than filtered by timestamp: the revision counts
    rows, the log is append-only, and two rows recorded in the same second are
    still two rows.
    """
    rows = log.rows()
    if revision is None:
        return rows
    return rows[revision.rows :]


def revisioned_artefacts(store: ProfileStore) -> Iterator[tuple[Path, ArtefactClass]]:
    """Every file in the tree whose class records a revision, with its class."""
    home = store.path()
    if not home.is_dir():
        return
    for path in sorted(home.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(home)
        if relative.parts == ("identity.json",) or relative.parts[:1] == ("session",):
            # Identity and session state are neither derived from the log nor
            # authored against it; they are the frame the log sits in.
            continue
        klass = classify(relative)
        if klass in REVISIONED:
            yield relative, klass


def stale_artefacts(store: ProfileStore) -> list[Stale]:
    """Everything behind the current revision, with what changed and what to do.

    Historical artefacts never appear here, and that is the point: "what was
    sent was sent; what happened happened". Listing one as stale would invite
    somebody to bring it up to date, and there is no such operation.
    """
    log = EvidenceLog(store)
    current = log.revision()
    found: list[Stale] = []
    for relative, klass in revisioned_artefacts(store):
        recorded = _read_stamp(store, relative)
        if recorded == current:
            continue
        new_rows = rows_since(log, recorded)
        if not new_rows and recorded is not None:
            # Same row count, different digest: the log was rewritten under it,
            # which is a broken profile rather than a stale artefact — but the
            # artefact is still not the one this log produces.
            pass
        found.append(
            Stale(
                artefact=str(relative),
                artefact_class=klass,
                recorded=recorded,
                current=current,
                changed=tuple(
                    sorted({dimension for row in new_rows for dimension in row.dimensions})
                ),
                rows_behind=len(new_rows),
            )
        )
    return found


def is_immutable(relative: Path | str) -> bool:
    """Whether §3.4 forbids revising this artefact at all."""
    return classify(relative) == "historical"


# ---------------------------------------------------------------------------
# acting on staleness


STALE_SUFFIX = ".stale.json"


def mark_stale(store: ProfileStore, entry: Stale) -> Path:
    """Write the stale marker for an authored artefact, beside it, never in it.

    §3.4: kept exactly as they are. The marker is a sidecar so the artefact's
    own bytes are untouched — a CV that is already with an employer must still
    be the file that was sent, byte for byte, when the candidate opens it to
    answer a question about their own application.
    """
    marker = Path(entry.artefact + STALE_SUFFIX)
    return store.write_json(
        {
            "artefact": entry.artefact,
            "stale_since_revision": entry.current.as_json(),
            "computed_from_revision": entry.recorded.as_json() if entry.recorded else None,
            "reason": entry.reason(),
            "changed": list(entry.changed),
            "action": entry.action,
        },
        *marker.parts,
    )


@dataclass(frozen=True)
class Refreshed:
    """What a refresh actually did, per §3.4's three classes."""

    recomputed: tuple[str, ...]
    marked: tuple[str, ...]
    untouched_historical: tuple[str, ...]


def refresh(store: ProfileStore) -> Refreshed:
    """Recompute what is derived, mark what is authored, touch nothing historical.

    The asymmetry is the whole of §3.4. Recomputation is safe for derived files
    because nothing was hand-authored into them; it is not safe for a generated
    CV, so that gets an offer rather than an action.
    """
    from integral.profile import rebuild

    stale = stale_artefacts(store)
    marked = tuple(
        str(mark_stale(store, entry).relative_to(store.path()))
        for entry in stale
        if entry.artefact_class == "authored"
    )
    recomputed = tuple(sorted(rebuild(store)))
    historical = tuple(
        str(path.relative_to(store.path()))
        for path in sorted(store.path().rglob("*"))
        if path.is_file() and is_immutable(path.relative_to(store.path()))
    )
    return Refreshed(recomputed=recomputed, marked=marked, untouched_historical=historical)


# ---------------------------------------------------------------------------
# the gate


def probe_staleness(root: Path) -> dict[str, Any]:
    """Age a profile deliberately and see how much of what went stale is seen.

    The measurement is **recall**: of the artefacts that really are behind, the
    fraction reported. Precision is not the metric because the expensive
    failure is the silent one — an out-of-date CV shown as current is worse
    than a current one flagged for a second look.
    """
    from integral.identity import create_profile
    from integral.profile import EvidenceLog, rebuild

    identity = create_profile(root, "Probe One", handle="probe-one")
    store = ProfileStore(root, identity.handle)
    log = EvidenceLog(store)

    log.append(
        recorded_at="2026-08-17T10:00:00Z",
        step="history",
        kind="episode",
        dimensions=["team_autonomy"],
        text="They let me pick the stack.",
        source="conversation",
    )
    rebuild(store)
    made_at = log.revision()

    # An authored artefact, stamped with the revision it was generated from…
    store.write_json(
        {"profile_revision": made_at.as_json(), "claims": ["picked the stack"]},
        "cv",
        "generated",
        "offer-1",
        "v1",
        "cv.json",
    )
    # …and two historical ones, which record no revision and never go stale.
    store.write_json({"sent_at": "2026-08-17T12:00:00Z"}, "applications", "offer-1", "sent.json")
    store.write_json({"outcome": "rejected"}, "interviews", "offer-1", "record.json")
    authored = store.path("cv", "generated", "offer-1", "v1", "cv.json")
    authored_before = authored.read_bytes()

    # Now the profile moves on.
    log.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="constraints",
        kind="constraint",
        dimensions=["remote_work"],
        text="Fully remote, or nothing.",
        source="conversation",
    )

    expected = {relative for relative, _ in revisioned_artefacts(store)}
    detected = {Path(entry.artefact) for entry in stale_artefacts(store)}
    failures: list[str] = []
    missed = sorted(str(path) for path in expected - detected)
    if missed:
        failures.append(f"behind the current revision but not reported: {', '.join(missed)}")

    for entry in stale_artefacts(store):
        if entry.artefact_class == "historical":
            failures.append(f"{entry.artefact} is historical and was listed as stale")
        if entry.artefact_class == "authored" and entry.action != "offer to regenerate":
            failures.append(f"{entry.artefact} is authored but its action is {entry.action!r}")
        if not entry.reason().strip():
            failures.append(f"{entry.artefact} went stale without saying why")

    # Snapshotted here, not earlier: appending to the log *is* the legitimate
    # thing to do to a historical artefact ("never revised, only appended to").
    # What must not touch them is the refresh.
    historical_before = {
        str(path.relative_to(store.path())): path.read_bytes()
        for path in sorted(store.path().rglob("*"))
        if path.is_file() and is_immutable(path.relative_to(store.path()))
    }
    result = refresh(store)
    if authored.read_bytes() != authored_before:
        failures.append("an authored artefact was regenerated rather than marked")
    if not result.marked:
        failures.append("an authored artefact went stale and no marker was written")
    for relative, before in historical_before.items():
        if store.path(*Path(relative).parts).read_bytes() != before:
            failures.append(f"the historical artefact {relative} was modified")
    still_stale = [
        entry.artefact for entry in stale_artefacts(store) if entry.artefact_class == "derived"
    ]
    if still_stale:
        failures.append(f"derived artefacts were not recomputed: {', '.join(still_stale)}")

    return {
        "stale_artefact_detection_recall": (
            1.0 if not expected else len(expected & detected) / len(expected)
        ),
        "artefacts_aged": len(expected),
        "failures": failures,
    }


#: A floor, never the count of the day (T100), on `probe_staleness`'s own running
#: tally of aged artefacts rather than a collection this module lists — the
#: scripted scenario run *is* the fixture. Raised to what the probe carries — 6,
#: zero slack — because 4 had drifted two under with no margin argued (T159).
MINIMUM_AGED = 6


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `stale_artefact_detection_recall` in a throwaway tree and record it."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="integral-t37-") as tmp:
        measured = probe_staleness(Path(tmp) / "profiles")
    if measured["failures"]:
        # A failure elsewhere in §3.4 must not be reported behind a clean recall.
        measured["stale_artefact_detection_recall"] = 0.0
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.revision [path]` → T37's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["artefacts_aged"] < MINIMUM_AGED:
        print(
            f"only {measured['artefacts_aged']} artefacts were aged (floor {MINIMUM_AGED}) — "
            "a recall of 1.0 over nothing is not a measurement",
            file=sys.stderr,
        )
        return 3
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
