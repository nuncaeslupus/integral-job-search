"""S6 — step 12: prepare for the interview, then record what actually happened.

The gate is `interview_lesson_linkage == 1.0`: every logged interview produces
at least one evidence row linked to a dimension or to a story-bank episode. An
interview that produces only prose is a diary entry. The point of logging it is
that the profile learns something and the next interview goes better — *"they
pushed hard on on-call and I had no answer"* is evidence about `on_call_load`,
and it has to land in `evidence.jsonl` as such or the feedback loop is
decorative.

**Linkage is structural, the way T45's traceability is.** `log_interview`
refuses a set of lessons that names nothing — no dimension, no episode — so a
linkless interview cannot be written in the first place. The measurement then
reads the **records on disk** against the **log on disk**, never the objects
that wrote them, so it still sees an interview however it got there: a hand
edit, a later feature, a second writer. A check that trusted the writer would
be measuring its own intention.

**A cited episode contributes its dimensions.** A lesson may link either way —
*"they asked about autonomy"* names a dimension directly, *"that Zylo story
landed badly"* names an episode — and the second is resolved through the log to
the dimensions T8 linked that episode to. So one rule covers both, and the row
in the log carries real dimension ids either way rather than a story id nothing
downstream can score.

**The record is historical; only the preparation is authored** (process spec
§3.4, and `revision.py`'s `_CLASSES` already keys it that way). Nothing under
`interviews/<offer_id>/<iv-id>/` is ever rewritten — `held.json` and, when it
arrives, `outcome.json` are both created exclusively. That is what makes "the
outcome came four days later" an append rather than a revision: a reply that
lands after the fact adds a file, and what was recorded on the day stays what
was recorded on the day.

**Preparation draws only from the story bank** — the same invent-nothing rule
the generated CV is held to (S4/T45). `render_story` is the single source of a
rehearsal line's wording, so a line the candidate is told to rehearse cannot be
a story they never told us.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from integral.dimensions import DEFAULT_DIMENSIONS_DIR, Dimension, ad_side, load_dimensions
from integral.extraction import _normalise_labelled, cue_findings
from integral.harness import DEFAULT_STORE_PATH, LabelledAd, load_store
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog, EvidenceRow, EvidenceSubject, SubjectKind

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "S6.json"

SCHEMA_VERSION: Literal[1] = 1

STEP = "interview_log"
SUBJECT_KIND: SubjectKind = "interview"

INTERVIEW_ID = re.compile(r"^iv-(\d{3,})$")
_ID_WIDTH = 3

OutcomeResult = Literal["advanced", "rejected", "offer", "withdrew", "silence"]

_REHEARSE_HEADING = "## What to rehearse"
_PRESS_HEADING = "## What they are likely to press on"
_ASKED_HEADING = "## What they asked last time"


class InterviewLogError(Exception):
    """A record was refused: linkless lessons, a rewrite, or an unknown episode."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Question(Strict):
    """One question the candidate was asked, and what it was about."""

    text: str = Field(min_length=1)
    dimensions: tuple[str, ...] = ()


class Lesson(Strict):
    """One thing the interview taught, and what it attaches to.

    `stories` are ids of `episode` rows in this profile's log. Either link is
    enough on its own; a lesson with neither is what `log_interview` refuses.
    """

    text: str = Field(min_length=1)
    dimensions: tuple[str, ...] = ()
    stories: tuple[str, ...] = ()

    @property
    def links_to_something(self) -> bool:
        return bool(self.dimensions or self.stories)


class Held(Strict):
    """`interviews/<offer_id>/<iv-id>/held.json` — written once, never revised."""

    schema_version: Literal[1] = SCHEMA_VERSION
    offer_id: str = Field(min_length=1)
    interview_id: str = Field(pattern=INTERVIEW_ID.pattern)
    held_on: str = Field(min_length=1)
    questions: tuple[Question, ...] = ()
    lessons: tuple[Lesson, ...]
    # The rows this record produced, so a reader of the file can find them
    # without scanning the log. The gate does the scan anyway — this is the
    # convenience, not the link.
    evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> Held:
        if not any(lesson.links_to_something for lesson in self.lessons):
            raise ValueError("an interview record must carry at least one linked lesson")
        return self


class Outcome(Strict):
    """`interviews/<offer_id>/<iv-id>/outcome.json` — the reply, whenever it came."""

    schema_version: Literal[1] = SCHEMA_VERSION
    offer_id: str = Field(min_length=1)
    interview_id: str = Field(pattern=INTERVIEW_ID.pattern)
    recorded_at: str = Field(min_length=1)
    result: OutcomeResult
    note: str = ""
    evidence_id: str = Field(min_length=1)


def subject(offer_id: str, interview_id: str) -> EvidenceSubject:
    """The `about` value every row this module writes carries."""
    return EvidenceSubject(kind=SUBJECT_KIND, id=f"{offer_id}/{interview_id}")


def _interview_dir(store: ProfileStore, offer_id: str, interview_id: str) -> Path:
    return store.path("interviews", offer_id, interview_id)


def next_interview_id(store: ProfileStore, offer_id: str) -> str:
    """One past the highest `iv-<N>` already recorded against this offer."""
    root = store.path("interviews", offer_id)
    if not root.is_dir():
        return f"iv-{1:0{_ID_WIDTH}d}"
    found = [
        int(match.group(1))
        for child in root.iterdir()
        if child.is_dir() and (match := INTERVIEW_ID.match(child.name))
    ]
    return f"iv-{max(found, default=0) + 1:0{_ID_WIDTH}d}"


def _episodes(log: EvidenceLog) -> dict[str, EvidenceRow]:
    return {row.id: row for row in log.effective_rows() if row.kind == "episode"}


def _linked_dimensions(lesson: Lesson, episodes: dict[str, EvidenceRow]) -> tuple[str, ...]:
    """Every dimension one lesson reaches — its own, plus each cited episode's.

    Resolving the citation here rather than storing a story id is what lets the
    gate ask one question of the log. A row naming `ev-000412` would need the
    reader to walk to that row and back before it knew whether anything was
    learned; a row naming `team_autonomy` says so on its face.
    """
    reached = set(lesson.dimensions)
    for story in lesson.stories:
        episode = episodes.get(story)
        if episode is None:
            raise InterviewLogError(
                f"lesson cites {story!r}, which is not an episode in this profile's log"
            )
        reached.update(episode.dimensions)
    return tuple(sorted(reached))


def log_interview(
    store: ProfileStore,
    log: EvidenceLog,
    *,
    offer_id: str,
    held_on: str,
    lessons: tuple[Lesson, ...],
    questions: tuple[Question, ...] = (),
    recorded_at: str | None = None,
) -> Held:
    """Write one interview record and the evidence rows it produced.

    Refuses before writing anything if the lessons link to nothing. That refusal
    is the gate's teeth: `interview_lesson_linkage` cannot be met by a writer
    that quietly drops the unlinkable ones, because there is no path that writes
    a record without at least one row behind it.
    """
    episodes = _episodes(log)
    reach = [(lesson, _linked_dimensions(lesson, episodes)) for lesson in lessons]
    # Tested on the **resolved** reach, not on `links_to_something`. A lesson
    # citing an episode that T8 never linked to a dimension has a non-empty
    # `stories` and resolves to nothing, so the shape check would have let it
    # through and `lesson_linkage` would then have reported the record
    # unlinked — the gate failing through a path nothing refused. The guard and
    # the measurement have to agree about what counts as a link.
    if not any(dimensions for _, dimensions in reach):
        raise InterviewLogError(
            f"{offer_id}: nothing to log — an interview that taught us nothing about a "
            "dimension or a story is a diary entry, and the profile learns nothing from it"
        )

    interview_id = next_interview_id(store, offer_id)
    # Reserve the directory before writing a row. Two callers can read the same
    # answer from `next_interview_id`, and an exclusive mkdir is what makes the
    # allocation a compare-and-swap rather than a hope — the loser is refused
    # with nothing written, instead of appending evidence for a record that
    # ends up interleaved with somebody else's.
    where = _interview_dir(store, offer_id, interview_id)
    try:
        where.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise InterviewLogError(
            f"{offer_id} {interview_id} already exists — another writer took this id; "
            "nothing was written, and a fresh call will take the next one"
        ) from exc

    at = recorded_at or held_on
    rows = [
        log.append(
            recorded_at=at,
            occurred_at=held_on,
            occurred_precision="day",
            step=STEP,
            kind="outcome",
            dimensions=dimensions,
            text=lesson.text,
            source="interview",
            about=subject(offer_id, interview_id),
        )
        for lesson, dimensions in reach
    ]
    held = Held(
        offer_id=offer_id,
        interview_id=interview_id,
        held_on=held_on,
        questions=questions,
        lessons=lessons,
        evidence_ids=tuple(row.id for row in rows),
    )
    _write_once(where / "held.json", held)
    return held


def record_outcome(
    store: ProfileStore,
    log: EvidenceLog,
    *,
    offer_id: str,
    interview_id: str,
    recorded_at: str,
    result: OutcomeResult,
    note: str = "",
) -> Outcome:
    """Append the employer's reply to an interview already recorded.

    A separate file rather than a field on `held.json`, because §3.4 makes the
    record historical: what was recorded on the day stays what was recorded on
    the day, and a reply that lands four days later adds to the record without
    revising it.
    """
    where = _interview_dir(store, offer_id, interview_id)
    if not (where / "held.json").exists():
        raise InterviewLogError(f"{offer_id} {interview_id} has no record to attach an outcome to")
    # Checked before the append, not left to `_write_once`. The log is
    # append-only, so a row written for an outcome that is then refused cannot
    # be taken back — it would sit there for good, about an interview whose
    # reply was already recorded. `_write_once` is still the authority that
    # creates the file; this only keeps the ordinary case from leaving a row
    # behind.
    if (where / "outcome.json").exists():
        raise InterviewLogError(
            f"{offer_id} {interview_id} already has an outcome — the record is historical "
            "and is never revised, only appended to (process spec §3.4)"
        )
    row = log.append(
        recorded_at=recorded_at,
        step=STEP,
        kind="outcome",
        dimensions=(),
        text=note or f"the employer's answer was: {result}",
        source="interview",
        about=subject(offer_id, interview_id),
    )
    outcome = Outcome(
        offer_id=offer_id,
        interview_id=interview_id,
        recorded_at=recorded_at,
        result=result,
        note=note,
        evidence_id=row.id,
    )
    _write_once(where / "outcome.json", outcome)
    return outcome


def _write_once(path: Path, payload: Strict) -> Path:
    """Create a historical file, or refuse. `"x"` is the whole of immutability."""
    body = json.dumps(payload.model_dump(mode="json"), indent=2, ensure_ascii=False, sort_keys=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(body + "\n")
    except FileExistsError as exc:
        raise InterviewLogError(
            f"{path.name} is already written — an interview record is historical and is "
            "never revised, only appended to (process spec §3.4)"
        ) from exc
    return path


def read_held(store: ProfileStore, offer_id: str, interview_id: str) -> Held:
    path = _interview_dir(store, offer_id, interview_id) / "held.json"
    return Held.model_validate_json(path.read_text(encoding="utf-8"))


def read_outcome(store: ProfileStore, offer_id: str, interview_id: str) -> Outcome | None:
    path = _interview_dir(store, offer_id, interview_id) / "outcome.json"
    if not path.exists():
        return None
    return Outcome.model_validate_json(path.read_text(encoding="utf-8"))


def logged_interviews(store: ProfileStore) -> list[tuple[str, str]]:
    """Every `(offer_id, interview_id)` with a record on disk, in sorted order."""
    root = store.path("interviews")
    if not root.is_dir():
        return []
    return sorted(
        (offer.name, child.name)
        for offer in root.iterdir()
        if offer.is_dir()
        for child in offer.iterdir()
        if child.is_dir() and INTERVIEW_ID.match(child.name) and (child / "held.json").exists()
    )


def lesson_linkage(store: ProfileStore, log: EvidenceLog) -> dict[str, Any]:
    """The gate: the fraction of logged interviews the log actually learned from.

    Reads the records on disk and the log on disk. A record counts as linked
    only when a row in the log is `about` it *and* names at least one dimension
    — an unlinked row would be prose in a different file.
    """
    reached: dict[str, set[str]] = {}
    for row in log.effective_rows():
        if row.about is None or row.about.kind != SUBJECT_KIND:
            continue
        reached.setdefault(row.about.id, set()).update(row.dimensions)

    logged = logged_interviews(store)
    keys = {f"{offer_id}/{interview_id}" for offer_id, interview_id in logged}
    unlinked = sorted(key for key in keys if not reached.get(key))

    # Rows about an interview with no record on disk. `interview_lesson_linkage`
    # cannot see this and should not — every record that exists still traces, so
    # the fraction is honestly what it says. It is a different property: the log
    # and the records have to agree about which interviews happened. A row
    # claiming a lesson from an interview nobody logged would feed a weight
    # (step 10) from an event with no record behind it.
    orphans = sorted(key for key in reached if key not in keys)

    # And the reverse: a record naming rows that are not in the log, or are not
    # about it. `evidence_ids` is the convenience copy, and a convenience that
    # can disagree with the thing it copies is worse than not having it.
    by_id = {row.id: row for row in log.effective_rows()}
    mismatched = sorted(
        f"{offer_id}/{interview_id}: {row_id}"
        for offer_id, interview_id in logged
        for row_id in read_held(store, offer_id, interview_id).evidence_ids
        if (named := by_id.get(row_id)) is None
        or named.about is None
        or named.about.id != f"{offer_id}/{interview_id}"
    )

    return {
        # `None`, never 1.0, over zero interviews: a profile that logged nothing
        # has not met a gate about what logging teaches (D-2's third outcome).
        "interview_lesson_linkage": (
            None if not logged else (len(logged) - len(unlinked)) / len(logged)
        ),
        "interviews_logged": len(logged),
        "interviews_unlinked": unlinked,
        "rows_about_an_interview_with_no_record": orphans,
        "records_naming_a_row_that_is_not_theirs": mismatched,
    }


# ---------------------------------------------------------------------------
# preparation — authored, and drawn only from the story bank


def render_story(episode: EvidenceRow) -> str:
    """The one line an episode becomes. The single source of a rehearsal line.

    Both the writer and `test_preparation_draws_only_from_the_story_bank` call
    this, which is what makes "only from the story bank" checkable rather than
    asserted: a line that is not this function's output for some episode in the
    bank did not come from the bank.
    """
    where = f" ({episode.occurred_at})" if episode.occurred_at else ""
    return f"- {episode.text}{where}"


def rehearsal_lines(text: str) -> list[str]:
    """The lines of a preparation note that quote the story bank."""
    out: list[str] = []
    inside = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            inside = line == _REHEARSE_HEADING
        elif inside and line.strip():
            out.append(line)
    return out


def likely_presses(ad: LabelledAd, dimensions: list[Dimension]) -> tuple[str, ...]:
    """The dimensions this advert's own wording emphasises, in id order.

    The advert is the employer's text, so this is a claim about *them*, not
    about the candidate — which is why it may be derived from cue matches while
    nothing on the rehearsal side may be derived from anything but the bank.
    """
    normalised = _normalise_labelled(ad)
    return tuple(
        sorted(
            dimension.id
            for dimension in ad_side(dimensions)
            if cue_findings(normalised, dimension) is not None
        )
    )


def prepare(
    store: ProfileStore,
    log: EvidenceLog,
    *,
    offer_id: str,
    presses: tuple[str, ...],
) -> Path:
    """Write `interviews/<offer_id>/preparation/<iv-id>.md` for the next round.

    Authored, not historical (`revision.py`'s `_CLASSES`): if the profile moves
    under it, it is marked stale and regeneration is offered, never automatic.
    """
    interview_id = next_interview_id(store, offer_id)
    bank = [row for row in log.effective_rows() if row.kind == "episode"]
    by_dimension = {
        dimension: [row for row in bank if dimension in row.dimensions] for dimension in presses
    }

    lines = [f"# Preparation — {offer_id} ({interview_id})", "", _PRESS_HEADING, ""]
    for dimension in presses:
        held = len(by_dimension[dimension])
        lines.append(
            f"- `{dimension}` — {held} episode(s) in the story bank"
            if held
            else f"- `{dimension}` — nothing in the story bank yet; worth an answer before the day"
        )
    lines += ["", _REHEARSE_HEADING, ""]
    # Sorted by id and de-duplicated: one episode may answer two of the presses,
    # and rehearsing it twice would read as two different stories.
    rehearse = {row.id: row for rows in by_dimension.values() for row in rows}
    lines += [render_story(episode) for _, episode in sorted(rehearse.items())]

    asked = [
        question.text
        for logged_offer, interview in logged_interviews(store)
        if logged_offer == offer_id
        for question in read_held(store, offer_id, interview).questions
    ]
    if asked:
        lines += ["", _ASKED_HEADING, "", *(f"- {question}" for question in sorted(set(asked)))]

    return store.write_text(
        "\n".join(lines).rstrip("\n") + "\n",
        "interviews",
        offer_id,
        "preparation",
        f"{interview_id}.md",
    )


# ---------------------------------------------------------------------------
# the gate — measured over every advert in the labelled corpus

_FIXTURE_EPISODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Rebuilt the on-call rota after a quarter of 2am pages", ("on_call_load",)),
    ("Ran the migration end to end with no one reviewing the plan", ("team_autonomy",)),
    ("Took over the client calls when the account manager left", ("team_autonomy",)),
)


def _seed_bank(log: EvidenceLog) -> list[EvidenceRow]:
    return [
        log.append(
            recorded_at="2026-01-04T09:00:00Z",
            occurred_at="2025-11",
            occurred_precision="month",
            step="history",
            kind="episode",
            dimensions=dimensions,
            text=text,
            source="conversation",
        )
        for text, dimensions in _FIXTURE_EPISODES
    ]


def measure(
    store_path: Path | None = None,
    dimensions_dir: Path = DEFAULT_DIMENSIONS_DIR,
) -> dict[str, Any]:
    """`interview_lesson_linkage` over an interview per advert in the corpus.

    Real advert text drives what the employer presses on, so the branch that
    matters is exercised by the corpus rather than by a fixture written to hit
    it: an advert whose wording fires no cue produces no linked lesson, and
    `log_interview` refuses it. Those refusals are counted, not hidden — a gate
    reported over only the interviews that happened to link would be a gate met
    by dropping the awkward ones.

    The candidate is a fixture, because there is no person in this repository
    and there must not be; the adverts are the committed corpus.
    """
    dimensions = load_dimensions(dimensions_dir)
    ads = load_store(store_path or DEFAULT_STORE_PATH)

    refused = 0
    rehearsal_untraced: list[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "profiles"
        identity = create_profile(root, "Gate Fixture", handle="fixture", language="en")
        store = ProfileStore(root, identity.handle)
        log = EvidenceLog(store)
        bank = {render_story(row) for row in _seed_bank(log)}

        for ad in ads:
            presses = likely_presses(ad, dimensions)
            note = prepare(store, log, offer_id=ad.id, presses=presses)
            rehearsal_untraced += [
                f"{ad.id}: {line}"
                for line in rehearsal_lines(note.read_text(encoding="utf-8"))
                if line not in bank
            ]
            lessons = tuple(
                Lesson(text=f"they pressed on {dimension}", dimensions=(dimension,))
                for dimension in presses
            )
            try:
                held = log_interview(
                    store, log, offer_id=ad.id, held_on="2026-02-10", lessons=lessons
                )
            except InterviewLogError:
                refused += 1
                continue
            record_outcome(
                store,
                log,
                offer_id=ad.id,
                interview_id=held.interview_id,
                recorded_at="2026-02-14",
                result="advanced",
            )

        measured = lesson_linkage(store, log)

    measured["adverts_seen"] = len(ads)
    measured["interviews_refused_for_teaching_nothing"] = refused
    measured["rehearsal_lines_not_in_the_story_bank"] = sorted(rehearsal_untraced)
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/S6.json`."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write S6's gate evidence. Exit 1 on any interview the profile learned nothing from."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    for line in measured["interviews_unlinked"]:
        print(f"✗ logged interview with no linked evidence row: {line}", file=sys.stderr)
    for line in measured["rehearsal_lines_not_in_the_story_bank"]:
        print(f"✗ rehearsal line the story bank does not hold: {line}", file=sys.stderr)
    for line in measured["rows_about_an_interview_with_no_record"]:
        print(f"✗ evidence row about an interview nobody logged: {line}", file=sys.stderr)
    for line in measured["records_naming_a_row_that_is_not_theirs"]:
        print(f"✗ record names a row that is not about it: {line}", file=sys.stderr)
    print(json.dumps(measured, ensure_ascii=False))
    if (
        measured["rehearsal_lines_not_in_the_story_bank"]
        or measured["rows_about_an_interview_with_no_record"]
        or measured["records_naming_a_row_that_is_not_theirs"]
    ):
        return 1
    # `== 1.0`, not "nothing unlinked". A run that logged no interview at all
    # scores `None` with an empty unlinked list, and exiting 0 on that would
    # report a gate met by a step that recorded nothing.
    if measured["interview_lesson_linkage"] != 1.0:
        print(
            f"interview_lesson_linkage is {measured['interview_lesson_linkage']!r}, not 1.0",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
