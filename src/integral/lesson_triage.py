"""A route from one candidate's correction to the process every candidate gets (T239).

A correction a candidate makes — how a gap is worded, what a letter must not
say, a screening rule — lands in that candidate's `profile/evidence.jsonl` and
stays there. Whether it ever became a task depended on the session remembering
to offer it, and `test-mode`'s end-of-session pass only covers `[[…]]` notes in
test sessions.

**The population is the evidence log, not the lessons somebody chose to
record.** A route that only audits what a session volunteered still depends on
the session remembering, one step later. So the session's *corrections* are
read from `profile/evidence.jsonl`: every row of a correction-shaped kind
(`CORRECTION_KINDS`) appended since the session identified the candidate
(`identified_at` in the active-session record `identity.py` writes). Each such
row must end the session with exactly one outcome:

* a **lesson** whose `evidence_id` points at it, and that lesson is decided —
  seeded as a task, or kept as candidate-specific with a reason; or
* a **dismissal** (`not_a_lesson`) with a reason.

`check` exits 1 while any is open, and 2 when the session id is not the one the
active-session record names — an unknown session has no window, and "no window"
must never read as "nothing to triage". The kinds are the ones in which a
candidate states or amends something about themselves or their own draft:
`statement` (what they said, including amending an earlier answer),
`constraint` (a restated residence, pay floor, permit), `retraction` ("forget
that") and `candidate_statement` (an edit to their own application draft).
`episode` (intake history), `reaction` (a view on one advert) and `outcome` are
not corrections. A row of an in-scope kind that merely states a fact is
dismissed, which is a recorded decision rather than silence.

**Nothing personal leaves the profile.** A seeded task carries the rule and the
step id and nothing else, and the rule is checked against the property — "does
this text carry what the candidate said" — rather than a proxy for it. One
normaliser (NFKC, casefold, strip combining marks) is applied to the rule and to
everything it is compared with, then a rule is refused when

1. it contains any token of the candidate's display name or handle, in any
   order, with or without separators (`mq-2026`, `mq2026`), fullwidth included;
2. it contains a word that appears in the candidate's own text — evidence rows
   (retracted included), `cv/source`, `interviews/`, `applications/` — and not
   in the process's own vocabulary (`process_vocabulary`: the skills and the
   spec). Employers, cities and diagnoses are refused without anyone listing
   them, however short; or
3. it shares `SHINGLE` consecutive words with any one of those texts, which
   catches a run made entirely of common words.

`step` is not guarded but validated: it must be a process step id.

A lesson already decided cannot be decided again, and the ledger reader refuses
a file that says otherwise (a duplicate lesson id, a second decision), so the
guarantee holds for the file and not only for this module's writer.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import shlex
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from integral.identity import ACTIVE_FILE, ProfileStore, create_profile, write_active_handle
from integral.profile import EvidenceLog, EvidenceRow

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T239.json"
DEFAULT_TASKS_DIR = _REPO_ROOT / "arsenal" / "tasks"
DEFAULT_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"
DEFAULT_STATUS_DIR = _REPO_ROOT / "status"

LEDGER_PARTS = ("session", "lessons.jsonl")
# Where the candidate's text lives besides the evidence log.
CANDIDATE_TEXT_DIRS = (("cv", "source"), ("interviews",), ("applications",))
MAX_TEXT_BYTES = 5_000_000

# The evidence kinds in which the candidate states or amends something.
CORRECTION_KINDS = frozenset({"statement", "constraint", "retraction", "candidate_statement"})

# How many consecutive words a rule may share with one of the candidate's texts.
# Three is a phrase a rule can legitimately reuse ("cover letter", "never say");
# four is a sentence fragment someone said. Rules shorter than this compare whole.
SHINGLE = 4
MIN_RULE_WORDS = 3

LESSON_ID = re.compile(r"^ls-\d{4,}$")
SESSION_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
TASK_ID = re.compile(r"^t-[0-9a-f]{8}$")
EVIDENCE_ID = re.compile(r"^ev-\d{6,}$")
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_STEP_DIR = re.compile(r"^step-(\d\d)-(.+)$")

Decision = Literal["seeded", "candidate_specific"]


class LessonError(Exception):
    """A lesson, decision or session the ledger refuses."""


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
    evidence_id: str | None = Field(default=None, pattern=EVIDENCE_ID.pattern)


class Decided(Strict):
    row: Literal["decision"] = "decision"
    lesson: str = Field(pattern=LESSON_ID.pattern)
    decision: Decision
    at: str
    task_id: str | None = None
    reason: str | None = None


class Dismissed(Strict):
    row: Literal["dismissal"] = "dismissal"
    evidence_id: str = Field(pattern=EVIDENCE_ID.pattern)
    reason: str = Field(min_length=1)
    at: str


# ---------------------------------------------------------------------------
# the one normaliser, and what it is compared with


def normalise(text: str) -> str:
    """NFKC, casefold, then strip combining marks — applied to both sides, always."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    decomposed = unicodedata.normalize("NFD", folded)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(normalise(text))


def _shingles(words: list[str], size: int) -> set[tuple[str, ...]]:
    if len(words) < size:
        return set()
    return {tuple(words[i : i + size]) for i in range(len(words) - size + 1)}


def process_steps(skills_dir: Path = DEFAULT_SKILLS_DIR) -> frozenset[str]:
    """Every id a step can be named by: `step-11-application` and `application`."""
    found: set[str] = set()
    if skills_dir.is_dir():
        for entry in skills_dir.iterdir():
            match = _STEP_DIR.match(entry.name)
            if entry.is_dir() and match:
                found.add(entry.name)
                found.add(match.group(2))
    return frozenset(found)


def process_vocabulary(
    skills_dir: Path = DEFAULT_SKILLS_DIR, status_dir: Path = DEFAULT_STATUS_DIR
) -> frozenset[str]:
    """The process's own words: every skill's text and the spec's."""
    paths = sorted(skills_dir.glob("*/SKILL.md")) + sorted(status_dir.glob("spec*.md"))
    words: set[str] = set()
    for path in paths:
        words.update(tokens(path.read_text(encoding="utf-8")))
    return frozenset(words)


def candidate_texts(store: ProfileStore) -> list[list[str]]:
    """Every text of the candidate's as token lists: evidence rows, CV, interviews, drafts."""
    texts: list[list[str]] = []
    log = EvidenceLog(store)
    if log.exists():
        texts.extend(tokens(row.text) for row in log.rows())
    for parts in CANDIDATE_TEXT_DIRS:
        base = store.path(*parts)
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_TEXT_BYTES:
                continue
            texts.append(tokens(path.read_text(encoding="utf-8", errors="ignore")))
    return texts


def _name_tokens(store: ProfileStore) -> set[str]:
    names = [store.handle]
    with contextlib.suppress(Exception):  # no readable roster: no display name to compare
        names.append(store.identity().display_name)
    found: set[str] = set()
    for name in names:
        parts = tokens(name)
        found.update(part for part in parts if len(part) >= 2)
        joined = "".join(parts)
        if len(joined) >= 2:
            found.add(joined)
    return found


def personal_span(
    rule: str, store: ProfileStore, *, vocabulary: frozenset[str] | None = None
) -> str | None:
    """What in `rule` is the candidate's own, or None; never more of their text than the rule."""
    words = tokens(rule)
    names = _name_tokens(store)
    if any(word in names for word in words):
        return "a token of the candidate's name or handle"
    texts = candidate_texts(store)
    known = vocabulary if vocabulary is not None else process_vocabulary()
    mine = set().union(*texts) if texts else set()
    foreign = sorted({word for word in words if word in mine and word not in known})
    if foreign:
        return f"{len(foreign)} word(s) that are the candidate's and not the process's"
    size = min(SHINGLE, len(words))
    if size >= MIN_RULE_WORDS:
        wanted = _shingles(words, size)
        if any(wanted & _shingles(text, size) for text in texts):
            return f"a run of {size} words that the candidate's own text also contains"
    return None


# ---------------------------------------------------------------------------
# the session window


def _parse(stamp: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def session_start(store: ProfileStore, session_id: str) -> datetime:
    """When this session identified the candidate, or refuse: the id must be the live one."""
    if not SESSION_ID.match(session_id):
        raise LessonError(f"{session_id!r} is not a session id")
    marker = Path(store.root) / ACTIVE_FILE
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise LessonError("no active-session record: the session has no window") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("session_id") != session_id
        or payload.get("handle") != store.handle
    ):
        raise LessonError(f"{session_id!r} is not the session that identified {store.handle!r}")
    started = _parse(str(payload.get("identified_at", "")))
    if started is None:
        raise LessonError("the active-session record has no readable identified_at")
    return started


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

    def shell_line(self) -> str:
        return shlex.join(self.command())


def _one_line(text: str, limit: int = 72) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


@dataclass(frozen=True)
class Open:
    """One thing still needing a decision: a correction row, or a lesson with no row."""

    kind: Literal["correction", "lesson"]
    ref: str
    text: str


class LessonLedger:
    """Append-only record of the lessons a session noticed and what was decided."""

    def __init__(
        self,
        store: ProfileStore,
        *,
        tasks_dir: Path = DEFAULT_TASKS_DIR,
        vocabulary: frozenset[str] | None = None,
        steps: frozenset[str] | None = None,
    ) -> None:
        self.store = store
        self.tasks_dir = tasks_dir
        self._vocabulary = vocabulary
        self._steps = steps

    @property
    def path(self) -> Path:
        return self.store.path(*LEDGER_PARTS)

    def vocabulary(self) -> frozenset[str]:
        return self._vocabulary if self._vocabulary is not None else process_vocabulary()

    def steps(self) -> frozenset[str]:
        return self._steps if self._steps is not None else process_steps()

    # -- reading ----------------------------------------------------------

    def _rows(self) -> list[Lesson | Decided | Dismissed]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        rows: list[Lesson | Decided | Dismissed] = []
        for number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                kind = payload.get("row")
                if kind == "decision":
                    rows.append(Decided.model_validate(payload))
                elif kind == "dismissal":
                    rows.append(Dismissed.model_validate(payload))
                else:
                    rows.append(Lesson.model_validate(payload))
            except (json.JSONDecodeError, ValidationError, AttributeError) as exc:
                raise LessonError(f"lessons.jsonl:{number} is not a ledger row: {exc}") from exc
        self._refuse_contradictions(rows)
        return rows

    @staticmethod
    def _refuse_contradictions(rows: list[Lesson | Decided | Dismissed]) -> None:
        lessons = [row for row in rows if isinstance(row, Lesson)]
        ids = [row.id for row in lessons]
        if len(ids) != len(set(ids)):
            raise LessonError("lessons.jsonl names the same lesson id twice")
        decided = [row.lesson for row in rows if isinstance(row, Decided)]
        if len(decided) != len(set(decided)):
            raise LessonError("lessons.jsonl holds more than one decision for a lesson")
        dismissed = [row.evidence_id for row in rows if isinstance(row, Dismissed)]
        if len(dismissed) != len(set(dismissed)):
            raise LessonError("lessons.jsonl dismisses the same evidence row twice")
        if set(dismissed) & {row.evidence_id for row in lessons if row.evidence_id}:
            raise LessonError("an evidence row is both dismissed and made into a lesson")

    def lessons(self, session_id: str | None = None) -> list[Lesson]:
        return [
            row
            for row in self._rows()
            if isinstance(row, Lesson) and (session_id is None or row.session_id == session_id)
        ]

    def decisions(self) -> dict[str, Decided]:
        return {row.lesson: row for row in self._rows() if isinstance(row, Decided)}

    def dismissals(self) -> dict[str, Dismissed]:
        return {row.evidence_id: row for row in self._rows() if isinstance(row, Dismissed)}

    def corrections(self, session_id: str) -> list[EvidenceRow]:
        """The correction-shaped evidence rows appended since this session identified."""
        started = session_start(self.store, session_id)
        log = EvidenceLog(self.store)
        found = []
        for row in log.rows():
            if row.kind not in CORRECTION_KINDS:
                continue
            at = _parse(row.recorded_at)
            if at is None or at >= started:  # an unreadable stamp is kept in: fail-closed
                found.append(row)
        return found

    def untriaged(self, session_id: str) -> list[Open]:
        """Everything the session still owes a decision on."""
        rows = self.corrections(session_id)
        decided = self.decisions()
        dismissed = self.dismissals()
        by_evidence = {row.evidence_id: row for row in self.lessons() if row.evidence_id}
        covered = {row.id for row in rows}
        left: list[Open] = []
        for row in rows:
            lesson = by_evidence.get(row.id)
            if row.id in dismissed or (lesson is not None and lesson.id in decided):
                continue
            ref = lesson.id if lesson is not None else row.id
            left.append(Open("correction", ref, f"{row.kind} {row.id}"))
        for lesson in self.lessons(session_id):
            if lesson.evidence_id in covered or lesson.id in decided:
                continue
            left.append(Open("lesson", lesson.id, lesson.rule))
        return left

    def _get(self, lesson_id: str) -> Lesson:
        for lesson in self.lessons():
            if lesson.id == lesson_id:
                return lesson
        raise LessonError(f"no lesson {lesson_id!r} in this profile's ledger")

    def _next_id(self) -> str:
        highest = max((int(row.id.removeprefix("ls-")) for row in self.lessons()), default=0)
        return f"ls-{highest + 1:04d}"

    def _evidence_ids(self) -> set[str]:
        return {row.id for row in EvidenceLog(self.store).rows()}

    # -- writing ----------------------------------------------------------

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
        session_start(self.store, session_id)
        if step not in self.steps():
            raise LessonError(f"{step!r} is not a process step id")
        rule = " ".join(rule.split())
        if len(tokens(rule)) < MIN_RULE_WORDS:
            raise LessonError(
                f"a rule is at least {MIN_RULE_WORDS} words; "
                "a fragment cannot be acted on by someone who was not there"
            )
        if evidence_id is not None:
            if evidence_id not in self._evidence_ids():
                raise LessonError(f"no evidence row {evidence_id!r} in this profile")
            if evidence_id in self.dismissals():
                raise LessonError(f"{evidence_id} was dismissed; it is not a lesson")
        found = personal_span(rule, self.store, vocabulary=self.vocabulary())
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

    def dismiss(self, evidence_id: str, *, reason: str, at: str) -> Dismissed:
        """`not_a_lesson`: this correction says nothing a second candidate could use."""
        if evidence_id not in self._evidence_ids():
            raise LessonError(f"no evidence row {evidence_id!r} in this profile")
        if evidence_id in self.dismissals():
            raise LessonError(f"{evidence_id} is already dismissed")
        if any(lesson.evidence_id == evidence_id for lesson in self.lessons()):
            raise LessonError(f"{evidence_id} already has a lesson")
        if not reason.strip():
            raise LessonError("a dismissal says why")
        row = Dismissed(evidence_id=evidence_id, reason=reason.strip(), at=at)
        self.store.append_jsonl(row.model_dump(exclude_none=True), *LEDGER_PARTS)
        return row

    def seed_spec(self, lesson_id: str) -> TaskSpec:
        """The task for one lesson: its rule and its step, and nothing of the candidate."""
        lesson = self._get(lesson_id)
        previous = self.decisions().get(lesson_id)
        if previous is not None and previous.decision != "seeded":
            raise LessonError(f"{lesson_id} was decided {previous.decision}; it is not re-opened")
        # Re-checked: evidence may have been added since the rule was recorded.
        found = personal_span(lesson.rule, self.store, vocabulary=self.vocabulary())
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

    def _task_carries(self, task_id: str, rule: str) -> bool:
        wanted = " ".join(rule.split())
        for folder in (self.tasks_dir, self.tasks_dir / "_history"):
            path = folder / f"{task_id}.md"
            if path.is_file():
                return wanted in " ".join(path.read_text(encoding="utf-8").split())
        return False

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
        lesson = self._get(lesson_id)
        if lesson_id in self.decisions():
            raise LessonError(f"{lesson_id} already has a decision on record")
        if decision == "seeded":
            if not task_id or not TASK_ID.match(task_id):
                raise LessonError("a seeded lesson names the task it became (t-xxxxxxxx)")
            if not self._task_carries(task_id, lesson.rule):
                raise LessonError(
                    f"{task_id} is not a task under arsenal/tasks/ that carries this rule"
                )
            reason = None
        else:
            if not reason or not reason.strip():
                raise LessonError("a candidate-specific lesson says why it is")
            task_id = None
        row = Decided(lesson=lesson_id, decision=decision, at=at, task_id=task_id, reason=reason)
        self.store.append_jsonl(row.model_dump(exclude_none=True), *LEDGER_PARTS)
        return row


def render_session(ledger: LessonLedger, session_id: str) -> str:
    """The end-of-session list: every correction and lesson, with what was decided."""
    decided = ledger.decisions()
    dismissed = ledger.dismissals()
    by_evidence = {row.evidence_id: row for row in ledger.lessons() if row.evidence_id}
    lines = []
    corrections = ledger.corrections(session_id)
    lines.append(f"corrections — {len(corrections)} in session {session_id}")
    for row in corrections:
        lesson = by_evidence.get(row.id)
        if row.id in dismissed:
            state = f"not a lesson ({dismissed[row.id].reason})"
        elif lesson is None:
            state = "NO LESSON AND NOT DISMISSED"
        else:
            state = _lesson_state(lesson, decided)
        lines.append(f"  {row.id} [{row.kind}] {state}")
    if not corrections:
        lines.append("  (none)")
    unlinked = [
        lesson
        for lesson in ledger.lessons(session_id)
        if lesson.evidence_id not in {row.id for row in corrections}
    ]
    for lesson in unlinked:
        lines.append(
            f"  {lesson.id} [{lesson.step}] {lesson.rule} — {_lesson_state(lesson, decided)}"
        )
    left = ledger.untriaged(session_id)
    if left:
        lines.append(f"{len(left)} item(s) still need a decision.")
    return "\n".join(lines)


def _lesson_state(lesson: Lesson, decided: dict[str, Decided]) -> str:
    row = decided.get(lesson.id)
    if row is None:
        return f"{lesson.id} UNDECIDED: {lesson.rule}"
    if row.decision == "seeded":
        return f"{lesson.id} seeded as {row.task_id}: {lesson.rule}"
    return f"{lesson.id} candidate-specific ({row.reason}): {lesson.rule}"


# ---------------------------------------------------------------------------
# the gate: candidate_session_corrections_left_untriaged


def probe(root: Path) -> dict[str, Any]:
    """One constructed session, triaged by the same API a real session uses.

    Four in-window corrections of four kinds, one earlier statement and one
    in-window `episode` that are not corrections. Before anything is done all
    four must read as open (the sensitivity witness: a counter that cannot see
    them would read 0 here too); after each is routed, none may.
    """
    identity = create_profile(root, "Probe Candidate", handle="probe-candidate")
    store = ProfileStore(root, identity.handle)
    started = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    write_active_handle(root, identity.handle, session_id="probe", now=started)
    log = EvidenceLog(store)

    def add(kind: Any, text: str, when: str, retracts: str | None = None) -> str:
        return log.append(
            recorded_at=when,
            step="constraints",
            kind=kind,
            text=text,
            source="conversation",
            retracts=retracts,
        ).id

    earlier = add("statement", "before the session", "2026-10-04T09:00:00+00:00")
    add("episode", "history captured at intake", "2026-10-05T09:30:00+00:00")
    during = "2026-10-05T10:00:00+00:00"
    ids = [
        add(kind, f"probe {kind}", during, earlier if kind == "retraction" else None)
        for kind in sorted(CORRECTION_KINDS)
    ]
    tasks = root / "probe-tasks"
    tasks.mkdir()
    ledger = LessonLedger(store, tasks_dir=tasks)
    before = len(ledger.untriaged("probe"))
    rule = "A letter states dates and never the reason a role ended"
    one = ledger.record(
        rule, session_id="probe", step="step-11-application", at=during, evidence_id=ids[0]
    )
    (tasks / "t-00000001.md").write_text(f"Rule: {rule}\n", encoding="utf-8")
    ledger.decide(one.id, "seeded", at=during, task_id="t-00000001")
    two = ledger.record(
        "A pay floor is a constraint and not a preference",
        session_id="probe", step="step-02-constraints", at=during, evidence_id=ids[1],
    )  # fmt: skip
    ledger.decide(two.id, "candidate_specific", at=during, reason="turned on one permit")
    ledger.dismiss(ids[2], reason="a plain fact", at=during)
    ledger.dismiss(ids[3], reason="a plain fact", at=during)
    return {
        "corrections": len(ids),
        "open_before": before,
        "open_after": len(ledger.untriaged("probe")),
    }


def measure() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="integral-lessons-") as tmp:
        result = probe(Path(tmp))
    failures = []
    if result["open_before"] != result["corrections"]:
        failures.append(
            f"{result['open_before']} of {result['corrections']} corrections read as open "
            "before any was routed"
        )
    return {
        "candidate_session_corrections_left_untriaged": result["open_after"],
        "corrections_in_probe": result["corrections"],
        "corrections_open_before_triage": result["open_before"],
        "failures": failures,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


# ---------------------------------------------------------------------------
# the command line


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _main(argv: list[str]) -> int:
    """`python -m integral.lesson_triage [--root R --handle H <subcommand>]`

    With no subcommand it is T239's gate (exit 3 when nothing was measured).
    `check` is the end-of-session gate: 1 while anything is open, 2 for an
    unknown session or a refused write.
    """
    parser = argparse.ArgumentParser(description="Candidate lessons → the process (T239).")
    parser.add_argument("--root")
    parser.add_argument("--handle")
    parser.add_argument("--check", action="store_true", help="measure without writing evidence")
    sub = parser.add_subparsers(dest="cmd")
    rec = sub.add_parser("record")
    rec.add_argument("--session", required=True)
    rec.add_argument("--step", required=True)
    rec.add_argument("--rule", required=True)
    rec.add_argument("--evidence-id", default=None)
    dis = sub.add_parser("dismiss")
    dis.add_argument("evidence_id")
    dis.add_argument("--reason", required=True)
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

    if args.cmd is None:
        measured = measure() if args.check else write_evidence()
        print(json.dumps(measured, ensure_ascii=False))
        for failure in measured["failures"]:
            print(f"lesson_triage: {failure}", file=sys.stderr)
        if measured["corrections_in_probe"] <= 0:
            print("lesson_triage: the probe had no corrections: nothing measured", file=sys.stderr)
            return 3
        bad = measured["candidate_session_corrections_left_untriaged"] or measured["failures"]
        return 1 if bad else 0

    if not args.root or not args.handle:
        print("lesson_triage: --root and --handle are required", file=sys.stderr)
        return 2
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
        elif args.cmd == "dismiss":
            ledger.dismiss(args.evidence_id, reason=args.reason, at=_now())
        elif args.cmd == "list":
            print(render_session(ledger, args.session))
        elif args.cmd == "check":
            print(render_session(ledger, args.session))
            return 1 if ledger.untriaged(args.session) else 0
        elif args.cmd == "seed":
            print(ledger.seed_spec(args.lesson).shell_line())
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
