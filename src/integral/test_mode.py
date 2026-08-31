"""Test mode — a second channel for notes about the tool, open during a live session (S11).

Once the tool runs end to end, the way to improve the thirteen step skills is to
run a real session and notice, *in the moment*, where the protocol was wrong: a
question that should have been asked, a follow-up that was missed, a tone that
landed badly. Those observations are worth most while the conversation is live
and worth nothing if writing them down derails it.

So there are two channels. The first carries the session as a candidate would
experience it. The second carries notes about the tool.

**The requirement that drives every decision here: the session must proceed
exactly as a real one.** The moment the tool acknowledges a note, adjusts its
next question, or apologises, the run stops being a test of the skill and
becomes a test of the skill plus a correction. A note is captured silently and
changes nothing until the person says otherwise.

That is also what makes silent capture dangerous — **a note that is mis-parsed
or missed is invisible by design** — and it is why almost everything below is
about making the silence auditable rather than about the capture itself:

* `ParsedTurn` reports the `guard` that was in force and how many markers it
  declined to parse (`unparsed_markers`), so a note swallowed by the paste
  guard is a number somebody can see rather than a note that never existed;
* `unclosed_markers` counts a `[[` that never closed — the typo that would
  otherwise lose a note in the most invisible way available;
* the ledger is a file, appended on capture, so the notes survive the session
  that made them and `review()` reads them back from disk rather than from
  memory a crash would take with it.

## The marker (owner, 2026-08-20): `[[…]]`, with a paste guard

The owner's original proposal was that everything in `[...]` is meta. The
collision is not hypothetical: this tool's main input is **pasted job adverts**,
which are full of brackets — `[Remote]`, `[Barcelona]`, `[sic]`, bracketed
section headers — and T11 keeps an advert's `text` byte-for-byte verbatim
because extraction evidence spans are offsets into it. Under silent capture the
candidate would not be told that part of their advert had been eaten.

So, option 3 of the payload:

* `[[note]]` — a silent observation;
* `[[! note]]` — an observation the person wants acted on now. The *instruction
  to act* is separated from the *observation* so the end-of-session pass can
  treat every silent note uniformly;
* **no meta parsing inside a paste** — neither an explicit `/paste` turn nor a
  turn long enough to be one (`PASTE_CHARS`). Adverts are pasted; nothing in a
  paste is ever read as meta.

## Where notes live, and why it is not the candidate's tree

**A test note is never candidate evidence.** It is a fact about the tool, not
about the person, and it must not reach `profile/evidence.jsonl` or any derived
file. That is the reasoning that put the decline ledger in `session/` rather
than in the evidence log (T40) — but this goes one step further and puts the
note ledger **outside every profile tree**:

    <profiles root>/.test-mode/<session id>.jsonl

Three things follow from that placement, and each closes a hole that a
`session/`-level ledger would leave open. It cannot reach a candidate's derived
files, because it is not inside a candidate. It exists before identification
does, so a note made during step 0 — the step most worth criticising, since it
is where a session's tone is set — has somewhere real to go instead of an
in-memory buffer a crash would empty. And the leading dot means
`identity.list_identities` already skips it, so it never reads as a profile.

## Simulated candidates are fiction, and the reader is what enforces it

Inventing answers is often the only way to exercise a step at all — waiting for
a real run to reach step 9 makes step 9 untestable. So a simulated session is
allowed, and the profile it produces carries `fiction: true` in its
`identity.json`.

The mark is enforced **from the reader's side**: `list_identities` excludes
fiction profiles unless a caller explicitly asks for them. A mark that nothing
checks is decoration, and the same discipline is what `verified` versus
`generated` already enforces for the shipped tax rules — a value not obtained
the way its label implies must say which way it was obtained.

## Notes become tasks, but only ones the owner confirmed

Their whole value is improving the skills, and this repository's way of turning
a finding into work is a task with a gate. The session ends by printing every
note with its step and its skill named, asks which to address, and seeds only
those. `seed_specs` takes the confirmed set and returns nothing for a note that
is not in it — seeding all of them silently would fill the board with
observations that were wrong or already known.

The gate is `test_notes_reaching_candidate_evidence == 0`, measured by
`probe_notes_reaching_evidence`, which runs a whole simulated session and then
greps **every byte of every profile tree** for the note texts. Asserting the
writer never calls the evidence log would be a gate that restates a rule; this
one reads the bytes the rule is about (D-11).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from integral.identity import (
    Identity,
    Language,
    ProfileStore,
    create_profile,
    list_identities,
)
from integral.process_spec import load_steps
from integral.profile import EvidenceLog, tree_bytes
from integral.step_skills import skill_dir_name

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "S11.json"

# The ledger's home, relative to the profiles root. Dot-prefixed on purpose:
# `list_identities` skips a child whose name starts with `.`, so this directory
# is invisible to the roster without the roster needing to know it exists.
LEDGER_DIR = ".test-mode"

# `[[note]]` and `[[! note]]`. Deliberately not DOTALL — a note is one line.
# A `[[` whose `]]` is on another line is a typo, and `unclosed_markers` counts
# it rather than swallowing the rest of the turn into a note nobody meant.
_NOTE = re.compile(r"\[\[(?P<body>[^\]\n]*(?:\](?!\])[^\]\n]*)*)\]\]")
_OPEN_MARKER = "[["
_ACT_NOW = "!"

# A turn at least this long is treated as a paste whether or not it was
# announced as one. Adverts and pasted CV text run to thousands of characters;
# a typed conversational turn carrying a note is far shorter. The threshold is
# a guard, not a classifier — which is why a marker it declines to parse is
# reported instead of dropped.
PASTE_CHARS = 400

PASTE_COMMAND = "/paste"

Guard = Literal["none", "explicit-paste", "long-turn"]


class MetaNoteError(Exception):
    """A note, a ledger, or a session could not be read or written."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# parsing a turn


@dataclass(frozen=True)
class MetaNote:
    """One note found in a turn, before it is attributed to a step."""

    text: str
    act_now: bool


@dataclass(frozen=True)
class ParsedTurn:
    """A turn split into what the candidate said and what the tester noted.

    `visible` is what the session sees. It is the *whole* turn whenever no note
    was found, byte for byte — see `strip_notes` for why that is a code path
    rather than a claim.
    """

    visible: str
    notes: tuple[MetaNote, ...]
    guard: Guard
    unparsed_markers: int
    unclosed_markers: int

    @property
    def carries_a_note(self) -> bool:
        return bool(self.notes)

    @property
    def wants_action_now(self) -> bool:
        return any(note.act_now for note in self.notes)


def _horizontal_run_at_end(text: str) -> int:
    """How many trailing spaces/tabs `text` ends with."""
    n = 0
    while n < len(text) and text[len(text) - 1 - n] in " \t":
        n += 1
    return n


def _horizontal_run_at_start(text: str) -> int:
    n = 0
    while n < len(text) and text[n] in " \t":
        n += 1
    return n


def _repair_seam(before: str, after: str) -> tuple[str, str]:
    """Close the hole a removed note left, so the rest reads as if untyped.

    Two shapes, because people write notes in two shapes.

    **A note on a line of its own** — everything from the last newline to the
    note is whitespace, and the note is the last thing on its line. The line
    goes with it, indent and newline included, or the transcript grows a blank
    line the person never typed.

    **An aside inside a line** — the person typed *one* space to set the note
    off from what they were saying, so exactly **one character** of adjacent
    horizontal whitespace comes back out with it. One character, never the run:
    the two spaces somebody put after a full stop are their spacing, not the
    note's separator, and normalising them would edit a turn this function
    exists to leave alone.
    """
    lead = _horizontal_run_at_end(before)
    line_start = before[: len(before) - lead]
    trail = _horizontal_run_at_start(after)
    rest = after[trail:]

    own_line = (not line_start or line_start.endswith("\n")) and (not rest or rest.startswith("\n"))
    if own_line:
        return line_start, rest[1:] if rest.startswith("\n") else rest

    if lead:
        return before[:-1], after
    if trail:
        return before, after[1:]
    return before, after


def strip_notes(text: str) -> tuple[str, tuple[MetaNote, ...], int]:
    """Split a turn into its visible text, its notes, and its unclosed markers.

    **A turn with no note is returned unchanged, by construction.** The early
    return is not an optimisation: `test_the_visible_conversation_is_byte_
    identical_with_and_without_notes` is the property this whole feature rests
    on, and a code path that reassembles a note-free turn out of pieces is one
    that can normalise a newline, drop a trailing space, or otherwise edit an
    advert that must stay byte-for-byte verbatim (T11). Nothing touches text
    that carries no marker.
    """
    matches = list(_NOTE.finditer(text))
    unclosed = text.count(_OPEN_MARKER) - len(matches)
    if not matches:
        return text, (), max(0, unclosed)

    notes: list[MetaNote] = []
    before = ""
    cursor = 0
    pieces: list[str] = []
    for match in matches:
        body = match.group("body").strip()
        act_now = body.startswith(_ACT_NOW)
        if act_now:
            body = body[len(_ACT_NOW) :].strip()
        notes.append(MetaNote(text=body, act_now=act_now))
        before = "".join(pieces) + text[cursor : match.start()]
        head, tail = _repair_seam(before, text[match.end() :])
        pieces = [head]
        cursor = len(text) - len(tail)
    visible = "".join(pieces) + text[cursor:]
    return visible, tuple(notes), max(0, unclosed)


def detect_guard(text: str) -> Guard:
    """Whether this turn is a paste, and so not to be read for meta at all.

    Two ways to be one, and the explicit form wins because it is the one a
    person can rely on: a turn whose first line is `/paste` is a paste however
    short it is, which is what makes "paste this three-line advert with
    brackets in it" safe.
    """
    first, _, _ = text.partition("\n")
    if first.strip() == PASTE_COMMAND:
        return "explicit-paste"
    if len(text) >= PASTE_CHARS:
        return "long-turn"
    return "none"


def parse_turn(text: str, *, guard: Guard | None = None) -> ParsedTurn:
    """Read one turn: what the candidate said, and what the tester noted.

    Under a guard nothing is parsed and the text is returned untouched — but
    the markers that *would* have been notes are counted. A guard that silently
    ate three observations and a guard that saw none are otherwise the same
    event from the outside, and the second channel's whole risk is that its
    failures look like nothing happening.
    """
    in_force = guard if guard is not None else detect_guard(text)
    if in_force != "none":
        visible = text
        if in_force == "explicit-paste":
            # The command is addressed to the tool, not part of the advert. What
            # follows the first newline is kept exactly as it arrived.
            _, sep, rest = text.partition("\n")
            visible = rest if sep else ""
        return ParsedTurn(
            visible=visible,
            notes=(),
            guard=in_force,
            unparsed_markers=visible.count(_OPEN_MARKER),
            unclosed_markers=0,
        )

    visible, notes, unclosed = strip_notes(text)
    return ParsedTurn(
        visible=visible,
        notes=notes,
        guard="none",
        unparsed_markers=0,
        unclosed_markers=unclosed,
    )


# ---------------------------------------------------------------------------
# the ledger


class NoteRow(Strict):
    """One captured note, as it is written to the ledger."""

    n: int = Field(ge=1)
    text: str = Field(min_length=1)
    act_now: bool = False
    # The step that was live when the note was made. `None` only before
    # identification has settled one — a note reading "should have asked about
    # qualifications" is actionable attached to step 3 and needs somebody to
    # reconstruct the conversation without it.
    step: str | None = None
    at: str


class TallyRow(Strict):
    """Markers a turn declined to capture — written, because they are the audit.

    The counters used to live on the live `MetaChannel` and were handed to
    `build_review` directly. That worked for exactly as long as the process
    did: `query_notes.py` — the documented end-of-session command — reopens the
    ledger in a *new* process, so it rebuilt a review that reported zero lost
    markers however many had been eaten, and exited 0.

    Which is the failure this feature exists to prevent, reproduced inside the
    mechanism meant to expose it. A count that does not survive the session is
    not an audit trail; it is a log line. So a turn that loses a marker appends
    a row, and every reader gets the same answer from the same file.
    """

    kind: Literal["tally"] = "tally"
    unparsed_markers: int = 0
    unclosed_markers: int = 0
    step: str | None = None
    at: str


class SessionRow(Strict):
    """The ledger's opening line — entering test mode, in the record.

    Written before any note, so nobody later mistakes a test session's
    artefacts for a real candidate's: the file says what it is, when it began,
    and whether the candidate in it was invented.
    """

    kind: Literal["session"] = "session"
    session_id: str
    simulated: bool
    at: str
    handle: str | None = None


def ledger_path(profiles_root: Path, session_id: str) -> Path:
    """Where this session's notes live. One file per session, named by it.

    The readable part is the id with anything unsafe replaced, which is lossy —
    `a/b` and `a?b` both slug to `a-b`. Two sessions sharing one file would mix
    their notes and show one session's observations during another's review, so
    the digest of the **raw** id is appended and it is what actually
    distinguishes them. The slug is there to make the directory legible; the
    digest is there to make it correct.
    """
    slug = re.sub(r"[^A-Za-z0-9_.-]", "-", session_id).strip("-") or "unnamed"
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:8]
    return Path(profiles_root) / LEDGER_DIR / f"{slug}-{digest}.jsonl"


class NoteLedger:
    """Append-only notes for one session, outside every profile tree.

    Appended on capture rather than flushed at the end, for the reason the
    session store gives for the same choice: the files are the memory, and a
    memory written only at the end is not one. A crashed test session still has
    its notes.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def open_session(self, row: SessionRow) -> None:
        self._append(row.model_dump(mode="json"))

    def append(self, row: NoteRow) -> NoteRow:
        self._append(row.model_dump(mode="json"))
        return row

    def append_tally(self, row: TallyRow) -> TallyRow:
        self._append(row.model_dump(mode="json"))
        return row

    def _append(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def raw_rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MetaNoteError(f"{self.path}:{number} is not JSON: {exc}") from exc
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows

    def notes(self) -> list[NoteRow]:
        """Every note in the ledger, read back from disk."""
        return [
            NoteRow.model_validate(row)
            for row in self.raw_rows()
            if row.get("kind") not in {"session", "tally"}
        ]

    def losses(self) -> tuple[int, int]:
        """Markers this session declined or could not close, summed from disk."""
        unparsed = 0
        unclosed = 0
        for row in self.raw_rows():
            if row.get("kind") != "tally":
                continue
            tally = TallyRow.model_validate(row)
            unparsed += tally.unparsed_markers
            unclosed += tally.unclosed_markers
        return unparsed, unclosed

    def header(self) -> SessionRow | None:
        """The session's metadata — the **last** row, not the first.

        A session that is reopened after its handle is known writes a second
        header, and the newer one is the true one. Returning the first would
        mean a run that identified its candidate mid-session still reported
        `handle: null` at triage.
        """
        found: SessionRow | None = None
        for row in self.raw_rows():
            if row.get("kind") == "session":
                found = SessionRow.model_validate(row)
        return found

    def highest_note_number(self) -> int:
        """The largest `n` on disk — where a reopened session resumes from."""
        return max((note.n for note in self.notes()), default=0)


# ---------------------------------------------------------------------------
# the review, and what it seeds


class ReviewRow(Strict):
    """One note as the end-of-session pass shows it.

    `skill` is named rather than left to the reader to work out: a note is
    addressed by editing a skill, and the point of attributing it to a step was
    always to say which one.
    """

    n: int
    text: str
    act_now: bool
    step: str | None
    skill: str | None
    at: str


class Review(Strict):
    """Everything captured this session, for the owner to triage.

    `captured` and `rows` are both present so the one failure silent capture
    makes invisible — a note parsed and then dropped before it was shown — is a
    comparison rather than an inspection.
    """

    session_id: str
    simulated: bool
    handle: str | None
    captured: int
    rows: tuple[ReviewRow, ...]
    unparsed_markers: int = 0
    unclosed_markers: int = 0

    @property
    def is_complete(self) -> bool:
        return self.captured == len(self.rows)


def _skill_for_step(step: str | None) -> str | None:
    if step is None:
        return None
    try:
        steps = load_steps()
    except Exception:  # a spec that will not load must not take the review with it
        return None
    for candidate in steps.steps:
        if candidate.id == step:
            return skill_dir_name(candidate)
    return None


def build_review(ledger: NoteLedger) -> Review:
    """Every captured note, with its step and its skill named.

    **Every field comes from the ledger file, including the loss counters.**
    Read from a caller's list — or worse, from a caller's memory — and the
    review is only as good as the process that happens to be running it, which
    is exactly how the standalone triage command came to report zero losses
    however many markers had been eaten.
    """
    header = ledger.header()
    notes = ledger.notes()
    unparsed_markers, unclosed_markers = ledger.losses()
    return Review(
        session_id=header.session_id if header else "",
        simulated=header.simulated if header else False,
        handle=header.handle if header else None,
        captured=len(notes),
        rows=tuple(
            ReviewRow(
                n=note.n,
                text=note.text,
                act_now=note.act_now,
                step=note.step,
                skill=_skill_for_step(note.step),
                at=note.at,
            )
            for note in notes
        ),
        unparsed_markers=unparsed_markers,
        unclosed_markers=unclosed_markers,
    )


@dataclass(frozen=True)
class TaskSpec:
    """A queue task a confirmed note would become — arguments, not an action.

    Returned rather than executed on purpose. "Seed only what the owner
    confirmed" is a property of what this function returns for a given
    confirmed set, which is testable; a function that shells out to
    `create_task.py` can only be tested by watching what it did.
    """

    title: str
    note_n: int
    step: str | None
    skill: str | None
    body: str

    def command(self) -> list[str]:
        """The invocation, with the body — `create_task.py --body` defaults empty.

        Printing only `--title` would seed a task carrying a truncated one-line
        summary and nothing else, losing the note's full text and the step it
        was made at: the actionable context the whole triage pass exists to
        carry into the queue.
        """
        return [
            "python3",
            ".claude/skills/queue-add/scripts/create_task.py",
            "--title",
            self.title,
            "--body",
            self.body,
        ]


def seed_specs(review: Review, confirmed: Iterable[int]) -> list[TaskSpec]:
    """The tasks to seed — only for notes whose number the owner confirmed.

    An empty confirmed set returns an empty list, and that is the whole of
    `test_nothing_is_seeded_until_the_owner_confirms`. A number that matches no
    note is ignored rather than raising: the owner typing `4` for a session
    with three notes should not lose the two they did confirm.
    """
    wanted = set(confirmed)
    specs: list[TaskSpec] = []
    for row in review.rows:
        if row.n not in wanted:
            continue
        where = row.skill or row.step or "the session protocol"
        specs.append(
            TaskSpec(
                title=f"Test-mode note {row.n}: {_one_line(row.text)}",
                note_n=row.n,
                step=row.step,
                skill=row.skill,
                body=(
                    f"Captured during a test session at step `{row.step or 'unknown'}`.\n\n"
                    f"> {row.text}\n\n"
                    f"Addressed in: `{where}`.\n"
                ),
            )
        )
    return specs


def _one_line(text: str, limit: int = 72) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# the session


class MetaChannel:
    """A session running with the meta channel open.

    Entering test mode is an explicit act and it is in the record: `begin`
    writes the session row before any note can be captured. Nothing here ever
    returns a note to the conversation — `feed` hands back only the visible
    text, which is the mechanical form of "the session proceeds exactly as a
    real one".
    """

    def __init__(
        self,
        profiles_root: Path,
        *,
        session_id: str,
        simulated: bool = False,
        handle: str | None = None,
        now: datetime | None = None,
    ) -> None:
        self.profiles_root = Path(profiles_root)
        self.session_id = session_id
        self.simulated = simulated
        self.handle = handle
        self.ledger = NoteLedger(ledger_path(self.profiles_root, session_id))
        self._clock = now
        # A test session spans many turns and may outlive the process running
        # it. Resuming from the ledger's own highest number, rather than from
        # zero, is what stops a restart minting a second note 1 — which would
        # make triage ambiguous, because `seed_specs` selects every row whose
        # number the owner confirmed.
        self._n = self.ledger.highest_note_number()
        self._acting_now: tuple[MetaNote, ...] = ()

        entering = SessionRow(
            session_id=session_id,
            simulated=simulated,
            handle=handle,
            at=self._stamp(),
        )
        current = self.ledger.header()
        if current is None or (current.simulated, current.handle) != (simulated, handle):
            # Written once on entry, and again only when the metadata actually
            # changed — a session that identifies its candidate part-way
            # through. Re-announcing identical metadata on every reopen would
            # bury the moment test mode was entered under copies of itself.
            self.ledger.open_session(entering)

    def _stamp(self) -> str:
        return (self._clock or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")

    def feed(self, text: str, *, step: str | None = None, guard: Guard | None = None) -> str:
        """Take one turn; return what the session sees, and only that.

        The notes go to the ledger. The return type is `str` rather than the
        `ParsedTurn` deliberately: a caller that cannot get at the notes cannot
        accidentally let one change the next question, which is the failure the
        payload says turns a test of the skill into a test of the skill plus a
        correction.
        """
        parsed = parse_turn(text, guard=guard)
        unclosed = parsed.unclosed_markers
        captured: list[MetaNote] = []
        for note in parsed.notes:
            if not note.text:
                # An empty `[[]]` is a slip, not an observation. Counted as
                # unclosed so it shows up in the review rather than becoming a
                # blank row nobody can act on.
                unclosed += 1
                continue
            self._n += 1
            self.ledger.append(
                NoteRow(
                    n=self._n,
                    text=note.text,
                    act_now=note.act_now,
                    step=step,
                    at=self._stamp(),
                )
            )
            captured.append(note)

        if parsed.unparsed_markers or unclosed:
            # To the ledger, not to an attribute: the triage command runs in
            # another process and must see the same losses this one did.
            self.ledger.append_tally(
                TallyRow(
                    unparsed_markers=parsed.unparsed_markers,
                    unclosed_markers=unclosed,
                    step=step,
                    at=self._stamp(),
                )
            )

        self._acting_now = tuple(note for note in captured if note.act_now)
        return parsed.visible

    def pending_actions(self) -> tuple[str, ...]:
        """What `[[! …]]` in the **last** turn asked for, and nothing else.

        `feed` returns only the visible text so a silent note cannot reach the
        conversation. But `[[! …]]` is the one marker documented as an
        exception — the owner explicitly asking for something to be acted on
        now — and a distinction the parser records, the ledger stores, and no
        caller can ever read is a feature that does not exist at runtime.

        So the exception gets its own door, and a narrow one: only the last
        turn's act-now notes, never the silent ones, and it must be opened
        deliberately. Reading it is the caller saying "I am about to break the
        silence, as instructed"; ignoring it leaves every note silent, which is
        the safe default.
        """
        return tuple(note.text for note in self._acting_now)

    def review(self) -> Review:
        """What to show at the end, before anything is seeded."""
        return build_review(self.ledger)


def create_simulated_profile(
    profiles_root: Path,
    display_name: str,
    *,
    language: Language = "es",
    handle: str | None = None,
    now: datetime | None = None,
) -> Identity:
    """Create a profile for an invented candidate, marked as fiction.

    A thin wrapper on `identity.create_profile` so a simulated run cannot
    forget the flag: the one call a test session makes sets it, rather than
    every caller remembering to.
    """
    return create_profile(
        profiles_root,
        display_name,
        language=language,
        handle=handle,
        now=now,
        fiction=True,
    )


# ---------------------------------------------------------------------------
# the gate


_SCRIPT: tuple[tuple[str, str | None], ...] = (
    # (turn, live step) — a session that reaches four steps and criticises each.
    ("Me llamo Marta Ruiz [[should have offered to continue in Catalan]]", "identify"),
    (
        "Trabajé seis años en Seat, en Martorell. [[! ask which plant, it changes the commute]]",
        "intake",
    ),
    (
        "Vivo en Sabadell y no me puedo mudar. [[the pay floor question came too early]]",
        "constraints",
    ),
    (
        "Llevé el turno de noche cuando se fue el encargado.\n"
        "[[no follow-up on what happened afterwards]]",
        "history",
    ),
)

# A real advert, brackets and all, pasted the way step 7 receives one. Long
# enough to trip the length guard on its own; announced as a paste as well, so
# the probe exercises both halves.
_PASTED_ADVERT = (
    "/paste\n"
    "[Barcelona] [Híbrido] Técnico/a de mantenimiento [sic]\n"
    "Buscamos un/a técnico/a para nuestra planta. [[Turnos rotativos]] "
    "Se valorará experiencia en automoción. Ofrecemos contrato indefinido, "
    "salario según convenio y formación continua. Imprescindible carné B y "
    "residencia en el área metropolitana. Incorporación inmediata. "
    "Enviar CV a rrhh@example.invalid indicando la referencia [REF-2026-114]."
)


def probe_notes_reaching_evidence(root: Path) -> tuple[int, list[str], int]:
    """Run a whole simulated test session, then read every profile byte back.

    The measurement is deliberately not "the writer never called the evidence
    log". That would be a gate restating a rule, and a rule the code has
    stopped following still agrees with its own restatement (D-11). This writes
    real evidence rows through `EvidenceLog.append` alongside the notes — so
    the profile tree genuinely contains the conversation — and then sweeps
    **every file under every profile** for each note's text.

    Returns the number of leaked notes, a line per leak, and how many notes
    the run actually captured — the third value is what keeps a zero from
    being a pass a dead parser could also produce.
    """
    root = Path(root)
    stamp = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    identity = create_simulated_profile(root, "Marta Ruiz", handle="marta-probe", now=stamp)
    store = ProfileStore(root, identity.handle)
    log = EvidenceLog(store)

    session = MetaChannel(
        root,
        session_id="probe-session",
        simulated=True,
        handle=identity.handle,
        now=stamp,
    )

    for turn, step in _SCRIPT:
        visible = session.feed(turn, step=step)
        if visible.strip():
            log.append(
                recorded_at=stamp.isoformat(timespec="seconds"),
                step=step or "identify",
                kind="statement",
                text=visible,
                source="conversation",
            )
    advert_visible = session.feed(_PASTED_ADVERT, step="sourcing")
    log.append(
        recorded_at=stamp.isoformat(timespec="seconds"),
        step="sourcing",
        kind="statement",
        text=advert_visible,
        source="conversation",
    )

    review = session.review()
    failures: list[str] = []

    # 1. The bytes. Every file in every profile tree, against every note.
    for candidate in list_identities(root, include_fiction=True):
        blob = b"\n".join(tree_bytes(ProfileStore(root, candidate.handle)).values())
        for row in review.rows:
            if row.text.encode("utf-8") in blob:
                failures.append(
                    f"note {row.n} ({row.text!r}) is in {candidate.handle}'s profile tree"
                )

    # 2. The advert survived verbatim. The paste guard's whole job.
    body = _PASTED_ADVERT.partition("\n")[2]
    if advert_visible != body:
        failures.append("the pasted advert was not returned byte-for-byte")

    # 3. Every captured note reached the review — the drop silent capture hides.
    if not review.is_complete:
        failures.append(f"{review.captured} notes captured but {len(review.rows)} shown")

    # 4. The fiction mark is enforced where it is read, not where it is written.
    if any(candidate.handle == identity.handle for candidate in list_identities(root)):
        failures.append(f"the simulated profile {identity.handle!r} is listed as a real profile")

    return len(failures), failures, review.captured


def measure(root: Path | None = None) -> dict[str, Any]:
    """S11's gate reading, as it is written to evidence.

    `notes_captured_in_probe` is reported next to the zero, and it is what
    stops the gate passing vacuously. A probe that parsed nothing leaks
    nothing, so "0 notes reached the evidence log" is a clean pass and a dead
    feature at the same time — the shape of vacuous pass this repository's
    evidence rules exist to refuse. `_main` treats a probe that captured no
    notes as "nothing was measured" (exit 3), never as a pass.
    """
    if root is not None:
        leaked, failures, captured = probe_notes_reaching_evidence(root)
    else:
        with tempfile.TemporaryDirectory(prefix="integral-test-mode-") as tmp:
            leaked, failures, captured = probe_notes_reaching_evidence(Path(tmp) / "profiles")

    # The script's own marker count, so "the probe captured what the script
    # contains" is itself checked rather than assumed.
    expected = sum(len(_NOTE.findall(turn)) for turn, _ in _SCRIPT)
    if captured != expected:
        failures.append(f"the probe captured {captured} of the script's {expected} notes")

    return {
        "test_notes_reaching_candidate_evidence": leaked + (0 if captured == expected else 1),
        "notes_captured_in_probe": captured,
        "notes_in_probe_script": expected,
        "failures": failures,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/S11.json`."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def render_review(review: Review) -> str:
    """The end-of-session list, as the owner reads it before confirming.

    Printed even when it is empty, and the counts are printed with it. "No
    notes were captured" and "notes were captured and then lost" have to look
    different, and under silent capture the only thing that can tell them apart
    is a number the session kept.
    """
    lines = [
        f"test mode — {review.captured} note(s) captured"
        + (" · simulated candidate (fiction)" if review.simulated else "")
    ]
    for row in review.rows:
        where = row.skill or row.step or "step unknown"
        mark = " [act now]" if row.act_now else ""
        lines.append(f"  {row.n}. [{where}]{mark} {row.text}")
    if not review.rows:
        lines.append("  (none)")
    if review.unparsed_markers:
        lines.append(
            f"  ⚠ {review.unparsed_markers} marker(s) inside a paste were not read as notes"
        )
    if review.unclosed_markers:
        lines.append(f"  ⚠ {review.unclosed_markers} unclosed or empty marker(s) were not captured")
    lines.append("Which of these should be addressed? Nothing is seeded until you say.")
    return "\n".join(lines)


def _main(argv: list[str]) -> int:
    """`python -m integral.test_mode [--check]` → S11's gate.

    `--check` measures without writing, matching every other gate module here.
    """
    parser = argparse.ArgumentParser(description="Test mode — the meta note channel (S11).")
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
        help="write evidence JSON to PATH (default: status/evidence/S11.json)",
    )
    args = parser.parse_args(argv[1:])

    measured = measure() if args.check else write_evidence(Path(args.write_evidence))
    print(json.dumps(measured, ensure_ascii=False))
    for failure in measured["failures"]:
        print(f"test_mode: {failure}", file=sys.stderr)
    if measured["notes_captured_in_probe"] <= 0:
        print("test_mode: the probe captured no notes — nothing was measured", file=sys.stderr)
        return 3
    return 1 if measured["test_notes_reaching_candidate_evidence"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
