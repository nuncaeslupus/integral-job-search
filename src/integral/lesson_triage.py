"""A route from one candidate's correction to the process every candidate gets (T239).

A correction a candidate makes — how a gap is worded, what a letter must not
say, a screening rule — lands in that candidate's `profile/evidence.jsonl` and
stays there. Whether it ever became a task depended on the session remembering
to offer it, and `test-mode`'s end-of-session pass only covers `[[…]]` notes in
test sessions.

This module is the route. Each correction a session notices is **recorded as a
lesson** (a rule, in neutral words) in `session/lessons.jsonl`; at the end of
the session every lesson recorded during it is listed, and each one gets exactly
one **decision** — seeded as a task, or kept as candidate-specific with a
reason. The decision is kept in the same ledger, so "was this offered?" is
answerable afterwards from a file rather than from anyone's memory.

**Nothing personal leaves the profile.** A task is a public artefact; a lesson
is useful to everyone only as a rule. So the task carries the rule and the step
and nothing else, and `rule` is refused — at recording, and again at seeding —
when it reproduces the candidate's own words: a run of `SHINGLE` consecutive
words shared with any row of that profile's evidence log (retracted rows
included; a retraction hides a row from the profile, not from the file), or the
candidate's name or handle. The check is on the property — "does this text
contain what the candidate said" — by comparing against the candidate's actual
rows, rather than on a proxy such as the rule's length or shape.

A lesson already decided cannot be decided again: the decision is the record
that the question was put, and a ledger that let it be overwritten would not be
one.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from integral.identity import ProfileStore
from integral.profile import EvidenceLog

LEDGER_PARTS = ("session", "lessons.jsonl")

# How many consecutive words a rule may share with the candidate's own rows.
# Three words is a phrase a rule can legitimately reuse ("cover letter", "never
# say"); four is a sentence fragment someone said. Short rules compare whole.
SHINGLE = 4
MIN_RULE_WORDS = 3

LESSON_ID = re.compile(r"^ls-\d{4,}$")
SESSION_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
TASK_ID = re.compile(r"^t-[0-9a-f]{8}$")
_WORD = re.compile(r"\w+", re.UNICODE)

Decision = Literal["seeded", "candidate_specific"]


class LessonError(Exception):
    """A lesson or decision the ledger refuses."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Lesson(Strict):
    row: Literal["lesson"] = "lesson"
    id: str = Field(pattern=LESSON_ID.pattern)
    session_id: str = Field(pattern=SESSION_ID.pattern)
    step: str = Field(min_length=1, max_length=64)
    rule: str = Field(min_length=1)
    at: str
    # A pointer to the evidence row that prompted it. Never a copy of its text.
    evidence_id: str | None = None


class Decided(Strict):
    row: Literal["decision"] = "decision"
    lesson: str = Field(pattern=LESSON_ID.pattern)
    decision: Decision
    at: str
    task_id: str | None = None
    reason: str | None = None


def _words(text: str) -> list[str]:
    return [word.casefold() for word in _WORD.findall(text)]


def _shingles(words: list[str], size: int) -> set[tuple[str, ...]]:
    if len(words) < size:
        return set()
    return {tuple(words[i : i + size]) for i in range(len(words) - size + 1)}


def _contains(haystack: list[str], needle: list[str]) -> bool:
    if not needle:
        return False
    return any(haystack[i : i + len(needle)] == needle for i in range(len(haystack)))


def personal_span(rule: str, store: ProfileStore) -> str | None:
    """The first thing in `rule` that is the candidate's own, or None.

    Compared against every row of the profile's evidence log, retracted or not,
    and against the display name and handle. Returns a description of the
    overlap (for the error message), never more of the candidate's text than the
    rule already contained.
    """
    rule_words = _words(rule)
    own: list[list[str]] = []
    if EvidenceLog(store).exists():
        own = [_words(row.text) for row in EvidenceLog(store).rows()]
    size = min(SHINGLE, len(rule_words))
    if size >= MIN_RULE_WORDS:
        mine = _shingles(rule_words, size)
        for words in own:
            if mine & _shingles(words, size):
                return f"a run of {size} words that the candidate's evidence also contains"
    names = [store.handle]
    with contextlib.suppress(Exception):  # no readable roster: no name to compare
        names.append(store.identity().display_name)
    for name in names:
        name_words = _words(name)
        if name_words and _contains(rule_words, name_words):
            return "the candidate's name or handle"
    return None


@dataclass(frozen=True)
class TaskSpec:
    """The task a seeded lesson becomes — arguments, not an action."""

    title: str
    lesson_id: str
    body: str

    def command(self) -> list[str]:
        return [
            "python3",
            ".claude/skills/queue-add/scripts/create_task.py",
            "--title",
            self.title,
            "--body",
            self.body,
        ]


def _one_line(text: str, limit: int = 72) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


class LessonLedger:
    """Append-only record of the lessons a session noticed and what was decided."""

    def __init__(self, store: ProfileStore) -> None:
        self.store = store

    @property
    def path(self) -> Path:
        return self.store.path(*LEDGER_PARTS)

    def _rows(self) -> list[Lesson | Decided]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        rows: list[Lesson | Decided] = []
        for number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                if payload.get("row") == "decision":
                    rows.append(Decided.model_validate(payload))
                else:
                    rows.append(Lesson.model_validate(payload))
            except (json.JSONDecodeError, ValidationError, AttributeError) as exc:
                raise LessonError(f"lessons.jsonl:{number} is not a ledger row: {exc}") from exc
        return rows

    def lessons(self, session_id: str | None = None) -> list[Lesson]:
        return [
            row
            for row in self._rows()
            if isinstance(row, Lesson) and (session_id is None or row.session_id == session_id)
        ]

    def decisions(self) -> dict[str, Decided]:
        return {row.lesson: row for row in self._rows() if isinstance(row, Decided)}

    def untriaged(self, session_id: str) -> list[Lesson]:
        decided = self.decisions()
        return [lesson for lesson in self.lessons(session_id) if lesson.id not in decided]

    def _get(self, lesson_id: str) -> Lesson:
        for lesson in self.lessons():
            if lesson.id == lesson_id:
                return lesson
        raise LessonError(f"no lesson {lesson_id!r} in this profile's ledger")

    def _next_id(self) -> str:
        highest = max((int(row.id.removeprefix("ls-")) for row in self.lessons()), default=0)
        return f"ls-{highest + 1:04d}"

    def record(
        self,
        rule: str,
        *,
        session_id: str,
        step: str,
        at: str,
        evidence_id: str | None = None,
    ) -> Lesson:
        """Note one correction, as a rule. Refused when it carries the candidate's words."""
        if not SESSION_ID.match(session_id):
            raise LessonError(f"{session_id!r} is not a session id")
        rule = " ".join(rule.split())
        if len(_words(rule)) < MIN_RULE_WORDS:
            raise LessonError(
                f"a rule is at least {MIN_RULE_WORDS} words; "
                "a fragment cannot be acted on by someone who was not there"
            )
        found = personal_span(rule, self.store)
        if found:
            raise LessonError(
                f"the rule contains {found}; restate it as a rule that holds for any candidate"
            )
        lesson = Lesson(
            id=self._next_id(),
            session_id=session_id,
            step=step,
            rule=rule,
            at=at,
            evidence_id=evidence_id,
        )
        self.store.append_jsonl(lesson.model_dump(exclude_none=True), *LEDGER_PARTS)
        return lesson

    def seed_spec(self, lesson_id: str) -> TaskSpec:
        """The task for one lesson: its rule and its step, and nothing of the candidate."""
        lesson = self._get(lesson_id)
        previous = self.decisions().get(lesson_id)
        if previous is not None and previous.decision != "seeded":
            raise LessonError(f"{lesson_id} was decided {previous.decision}; it is not re-opened")
        # Re-checked: evidence may have been added since the rule was recorded.
        found = personal_span(lesson.rule, self.store)
        if found:
            raise LessonError(f"{lesson_id}'s rule now contains {found}; it cannot leave")
        return TaskSpec(
            title=f"Candidate lesson: {_one_line(lesson.rule)}",
            lesson_id=lesson_id,
            body=(
                f"Learned in a candidate session at step `{lesson.step}`.\n\n"
                f"Rule: {lesson.rule}\n\n"
                "Generalise it if it holds for every candidate; if it does not, close this "
                "task and say why.\n"
            ),
        )

    def decide(
        self,
        lesson_id: str,
        decision: Decision,
        *,
        at: str,
        task_id: str | None = None,
        reason: str | None = None,
    ) -> Decided:
        """Keep the decision. Exactly one per lesson, and not overwritable."""
        self._get(lesson_id)
        if lesson_id in self.decisions():
            raise LessonError(f"{lesson_id} already has a decision on record")
        if decision == "seeded":
            if not task_id or not TASK_ID.match(task_id):
                raise LessonError("a seeded lesson names the task it became (t-xxxxxxxx)")
            reason = None
        else:
            if not reason or not reason.strip():
                raise LessonError("a candidate-specific lesson says why it is")
            task_id = None
        row = Decided(lesson=lesson_id, decision=decision, at=at, task_id=task_id, reason=reason)
        self.store.append_jsonl(row.model_dump(exclude_none=True), *LEDGER_PARTS)
        return row


def render_session(ledger: LessonLedger, session_id: str) -> str:
    """The end-of-session list: every lesson, with what has been decided about it."""
    decided = ledger.decisions()
    lessons = ledger.lessons(session_id)
    lines = [f"lessons — {len(lessons)} recorded in session {session_id}"]
    for lesson in lessons:
        row = decided.get(lesson.id)
        if row is None:
            state = "UNDECIDED"
        elif row.decision == "seeded":
            state = f"seeded as {row.task_id}"
        else:
            state = f"candidate-specific ({row.reason})"
        lines.append(f"  {lesson.id} [{lesson.step}] {lesson.rule} — {state}")
    if not lessons:
        lines.append("  (none)")
    left = ledger.untriaged(session_id)
    if left:
        lines.append(f"{len(left)} lesson(s) still need a decision: seed or candidate-specific.")
    return "\n".join(lines)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _main(argv: list[str]) -> int:
    """`python -m integral.lesson_triage <record|list|seed|decide|check> …`

    `check` is the end-of-session gate: exit 1 while any lesson recorded in the
    session has no decision.
    """
    parser = argparse.ArgumentParser(description="Candidate lessons → the process (T239).")
    parser.add_argument("--root", required=True, help="the profiles root")
    parser.add_argument("--handle", required=True)
    sub = parser.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--session", required=True)
    rec.add_argument("--step", required=True)
    rec.add_argument("--rule", required=True)
    rec.add_argument("--evidence-id", default=None)
    for name in ("list", "check"):
        sub.add_parser(name).add_argument("--session", required=True)
    seed = sub.add_parser("seed")
    seed.add_argument("lesson")
    dec = sub.add_parser("decide")
    dec.add_argument("lesson")
    dec.add_argument("decision", choices=["seeded", "candidate_specific"])
    dec.add_argument("--task", default=None)
    dec.add_argument("--reason", default=None)
    args = parser.parse_args(argv[1:])

    ledger = LessonLedger(ProfileStore(Path(args.root), args.handle))
    try:
        if args.cmd == "record":
            lesson = ledger.record(
                args.rule,
                session_id=args.session,
                step=args.step,
                at=_now(),
                evidence_id=args.evidence_id,
            )
            print(lesson.id)
        elif args.cmd == "list":
            print(render_session(ledger, args.session))
        elif args.cmd == "check":
            print(render_session(ledger, args.session))
            return 1 if ledger.untriaged(args.session) else 0
        elif args.cmd == "seed":
            spec = ledger.seed_spec(args.lesson)
            print(" ".join(repr(part) if " " in part else part for part in spec.command()))
        else:
            ledger.decide(
                args.lesson, args.decision, at=_now(), task_id=args.task, reason=args.reason
            )
    except LessonError as exc:
        print(f"lesson_triage: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
