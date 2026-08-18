"""Retraction of a fact, and deletion of a person (T38).

Process specification §4.1 and §4.3 describe two operations that sound alike
and are nothing like each other.

**Retraction** — "forget that" — suppresses one fact everywhere derived while
the row itself survives. The log is append-only, so a retraction is a row
naming the row it suppresses, never a deletion. Two consequences follow, and
both are the point: a rebuild stays deterministic, and an accidental retraction
can itself be undone. T6 owns resolving the chain; what lands here is the
candidate-facing pair of operations and the gate that
`retracted_rows_surviving_rebuild == 0` across *every* derived file, not just
the ones one module happens to write.

**Deletion of a person** — "delete everything you have about me" — removes
`profiles/<handle>/` entirely: log, stories, CV store, offers, rankings,
applications, interviews, tombstones. It is confirmed once by naming what goes,
and it is not reversible. That is the point of it.

§4.3 also settles the awkward case: deleting *another* profile is permitted
after confirming the target by name, because anyone who can run the tool can
delete the directory with a file manager, so a refusal would protect nothing
and would merely make the tool useless to a household that shares a laptop.
What the tool adds is that the target is stated before it happens.

**An instruction that does not name a profile deletes nothing.** Not "delete
the current one", not "delete the only one" — nothing. A deletion that can be
triggered without a name is a deletion that happens by accident, and there is
no undo behind it.
"""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jobsearch.identity import Identity, ProfileStore
from jobsearch.profile import DERIVED_DIR, EvidenceLog, EvidenceRow, rebuild

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T38.json"


class DeletionRefused(Exception):
    """A deletion was not confirmed by name, so nothing was deleted."""


# ---------------------------------------------------------------------------
# retraction — one fact


def retract(
    log: EvidenceLog,
    row_id: str,
    *,
    at: str,
    text: str = "Forget that.",
    step: str = "any",
) -> EvidenceRow:
    """Suppress one row everywhere derived, keeping the row.

    "A candidate asking for something to be forgotten gets it suppressed
    everywhere derived, in the same turn" (§4.1) — so this rebuilds rather than
    leaving the derived files to catch up at the next step boundary. Forgetting
    is the one operation whose effect the candidate must be able to see now.
    """
    row = log.append(
        recorded_at=at,
        step=step,
        kind="retraction",
        text=text,
        source="conversation",
        retracts=row_id,
    )
    rebuild(log.store)
    purge_derived_citations(log.store)
    return row


def purge_derived_citations(store: ProfileStore) -> list[str]:
    """Delete derived artefacts that still cite a retracted row.

    `rebuild` recomputes the four files `jobsearch.profile` owns. Rankings and
    extractions are derived too — §3.4 lists them — but nothing recomputes them
    yet (T18 and T15 own that), so after a retraction they are stale files
    quoting a fact the candidate asked to have forgotten.

    Deleting them is the honest move, and it is safe precisely because they are
    derived: a derived artefact is regenerable by definition, so removing one
    loses nothing that the log cannot produce again. Keeping it would leave the
    retracted words on disk and readable, which is the one outcome "forget
    that" must not have. Returns what was removed, so the caller can say a
    ranking has gone rather than let it vanish silently.
    """
    removed: list[str] = []
    for message in survivors(store):
        relative = message.split(" ", 1)[0]
        path = store.path(*Path(relative).parts)
        if path.exists():
            path.unlink()
            removed.append(relative)
    return sorted(set(removed))


def unretract(log: EvidenceLog, retraction_id: str, *, at: str) -> EvidenceRow:
    """Undo a retraction by retracting it — nothing is ever deleted.

    This is why a retraction is a row rather than a flag: an accidental "forget
    that" is a mistake somebody makes in the middle of a sentence, and the
    only reason it can be taken back is that the original row never left.
    """
    return retract(log, retraction_id, at=at, text="No, keep that after all.")


# The areas §3.4 calls derived. `profile/` is what `rebuild` owns; the rest are
# derived too and are recomputed by tasks that do not exist yet, which is why
# `purge_derived_citations` has anything to do.
_DERIVED_AREAS = frozenset({DERIVED_DIR, "rankings", "extractions", "annotations"})


def derived_files(store: ProfileStore) -> list[Path]:
    """Every file a rebuild produces or that is computed from the profile.

    The gate scans all of them rather than the four `jobsearch.profile` writes:
    a retracted row surviving in `rankings/` is exactly as bad as one surviving
    in `traits.json`, and a check that only knew about one module would not see
    it.
    """
    home = store.path()
    if not home.is_dir():
        return []
    return [
        path
        for path in sorted(home.rglob("*"))
        if path.is_file()
        and path.relative_to(home).parts[0] in _DERIVED_AREAS
        and path.name != "evidence.jsonl"
    ]


def survivors(store: ProfileStore) -> list[str]:
    """Retracted rows still visible in something derived, after a rebuild.

    Matched on both the row id and its verbatim text: a derived file that cited
    the id would leak the reference, and one that quoted the words would leak
    the fact itself. Either is the failure this gate is named for.
    """
    log = EvidenceLog(store)
    suppressed = log.suppressed_ids()
    if not suppressed:
        return []
    by_id = {row.id: row for row in log.rows()}
    found: list[str] = []
    for path in derived_files(store):
        content = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(store.path())
        for row_id in sorted(suppressed):
            row = by_id.get(row_id)
            if row_id in content:
                found.append(f"{relative} still cites {row_id}")
            if row is not None and row.text and row.text in content:
                found.append(f"{relative} still quotes the words of {row_id}")
    return found


# ---------------------------------------------------------------------------
# deletion — a person


@dataclass(frozen=True)
class DeletionPlan:
    """What a deletion would remove, stated before it happens (§4.3)."""

    handle: str
    display_name: str
    files: int
    areas: tuple[str, ...]

    def sentence(self) -> str:
        """The confirmation §4.3 asks for, in the words it asks for them in."""
        return (
            f"This will permanently delete everything for {self.display_name}: "
            f"{', '.join(self.areas)} — {self.files} files. "
            f"Confirm by typing their name."
        )


# The candidate-facing names for what lives under a profile, in the order §4.3
# lists them. A plan naming directories would be a plan nobody can check.
_AREAS: tuple[tuple[str, str], ...] = (
    ("profile", "profile"),
    ("profile/stories.jsonl", "stories"),
    ("cv", "CV store"),
    ("offers", "offers"),
    ("rankings", "rankings"),
    ("applications", "applications"),
    ("interviews", "interviews"),
)


def plan_deletion(root: Path, handle: str) -> DeletionPlan:
    """What would go, so the candidate is told before being asked to confirm."""
    store = ProfileStore(root, handle)
    identity = store.identity()
    home = store.path()
    files = [path for path in home.rglob("*") if path.is_file()]
    areas = tuple(
        label
        for relative, label in _AREAS
        if any(str(path.relative_to(home)).startswith(relative) for path in files)
    )
    return DeletionPlan(
        handle=handle,
        display_name=identity.display_name,
        files=len(files),
        areas=areas or ("profile",),
    )


def _names_the_target(confirmation: str | None, identity: Identity) -> bool:
    if not confirmation:
        return False
    said = confirmation.strip().casefold()
    return said in {identity.handle.casefold(), identity.display_name.casefold()}


def delete_profile(root: Path, handle: str, *, confirmation: str | None) -> DeletionPlan:
    """Remove one profile's tree entirely. Named once, and not reversible.

    `confirmation` must name the target — its handle or its display name.
    Anything else, including `None` and including the name of a *different*
    profile, deletes nothing and raises. There is no "the current one" and no
    "the only one": a deletion that can be triggered without a name is one that
    happens by accident, and nothing stands behind it.
    """
    store = ProfileStore(root, handle)
    identity = store.identity()
    if not _names_the_target(confirmation, identity):
        raise DeletionRefused(
            f"deletion of {identity.summary()} was not confirmed by name — nothing was deleted"
        )
    plan = plan_deletion(root, handle)
    home = store.path()
    shutil.rmtree(home)
    return plan


# ---------------------------------------------------------------------------
# the gate


def probe_retraction(root: Path) -> dict[str, Any]:
    """Retract, rebuild, look everywhere; then try to delete without a name."""
    from jobsearch.identity import create_profile

    failures: list[str] = []
    first = create_profile(root, "Probe One", handle="probe-one")
    second = create_profile(root, "Probe Two", handle="probe-two")
    store = ProfileStore(root, first.handle)
    neighbour = ProfileStore(root, second.handle)
    log = EvidenceLog(store)

    episode = log.append(
        recorded_at="2026-08-17T10:00:00Z",
        step="history",
        kind="episode",
        dimensions=["team_autonomy"],
        text="A thing said once and regretted afterwards.",
        source="conversation",
    )
    log.append(
        recorded_at="2026-08-17T10:01:00Z",
        step="constraints",
        kind="constraint",
        dimensions=["remote_work"],
        text="Fully remote, or nothing.",
        source="conversation",
    )
    rebuild(store)
    # A derived artefact outside `profile/`, so the scan is not one module deep.
    store.write_json(
        {"level": "L1", "cites": [episode.id], "quote": episode.text},
        "rankings",
        "2026-08-17T10-02-00.json",
    )

    undo = retract(log, episode.id, at="2026-08-18T09:00:00Z")

    # Nothing is cleaned up by hand here: whatever `retract` did not clear is
    # a survivor, which is the only way this number means anything.
    leaked = survivors(store)
    failures.extend(leaked)

    if episode.text not in log.raw_bytes().decode("utf-8"):
        failures.append("the retracted row left the log, which is not append-only")
    if episode.id not in {row.id for row in log.rows()}:
        failures.append("the retracted row is no longer in the log")

    unretract(log, undo.id, at="2026-08-18T09:05:00Z")
    if episode.id in log.suppressed_ids():
        failures.append("a retraction could not itself be retracted")
    if episode.id not in {row.id for row in log.effective_rows()}:
        failures.append("undoing a retraction did not bring the row back")

    # And deletion: nothing without a name, nothing with the wrong name.
    refusals = ((None, "no name"), ("", "an empty name"), ("somebody else", "a wrong name"))
    for confirmation, label in refusals:
        try:
            delete_profile(root, second.handle, confirmation=confirmation)
        except DeletionRefused:
            pass
        else:
            failures.append(f"a profile was deleted with {label}")
    if not neighbour.path().is_dir():
        failures.append("the neighbouring profile was removed by a refused deletion")

    plan = plan_deletion(root, second.handle)
    if second.display_name not in plan.sentence():
        failures.append("the deletion confirmation does not name who it is about")
    delete_profile(root, second.handle, confirmation=second.display_name)
    if (Path(root) / second.handle).exists():
        failures.append("a confirmed deletion left the tree behind")
    if not store.path().is_dir():
        failures.append("deleting one profile removed another")

    return {
        "retracted_rows_surviving_rebuild": len(leaked),
        "derived_files_scanned": len(derived_files(store)),
        "failures": failures,
    }


MINIMUM_SCANNED = 4


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `retracted_rows_surviving_rebuild` in a throwaway tree."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="jobsearch-t38-") as tmp:
        measured = probe_retraction(Path(tmp) / "profiles")
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.retraction [path]` → T38's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["derived_files_scanned"] < MINIMUM_SCANNED:
        print(
            f"only {measured['derived_files_scanned']} derived files were scanned "
            f"(floor {MINIMUM_SCANNED}) — zero survivors over nothing is not a measurement",
            file=sys.stderr,
        )
        return 3
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
