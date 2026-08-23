"""T47 — step 12: the mock interview, and it is a strict role-play.

The gate is `mock_interview_character_breaks == 0`: once the role-play is
announced, the tool is the interviewer and nothing else — no coaching
mid-answer, no encouragement, no breaking character to explain a question. The
discomfort of an unhelped answer is the entire exercise, so a rehearsal
interrupted every third answer to be helpful rehearses nothing.

**The rule is structural, not a blocklist.** The tempting shape is to generate
turns freely and then scan them for coaching phrases, which is a keyword list
and can always be talked around — *"just to help you here"* rephrased is still
coaching, and the scanner is one paraphrase behind for ever. Instead a
`Rehearsal` is a state machine: while it is in character the only turns it can
produce at all are `question`, `follow_up` and `silence` from the interviewer
and `answer` from the candidate. `feedback()` refuses to run until the session
is closed. A coaching turn is not something this code can emit inside the
role-play, so there is no wording to detect.

**The measurement reads the transcripts on disk**, never the `Rehearsal`
objects that wrote them, and it parses the turns as raw JSON rather than
through `Turn` — so a turn planted by a hand edit, a later feature or a second
writer is *seen* rather than rejected at the door by the schema.
`test_the_gate_would_notice_a_coaching_turn_planted_in_a_transcript` puts one
there and requires the count to rise and name it. A gate that cannot fail is
not a gate.

**The questions come from S6's preparation**, not from a generic list: the
dimensions this advert presses on (`likely_presses`) decide what is asked, and
the story bank decides which of those the candidate has an episode for. Hard
cap: ten rehearsed questions.

**Dictation is offered in the announcement**, because speaking an answer aloud
is far closer to the real thing than typing one and the difference shows.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from integral.dimensions import DEFAULT_DIMENSIONS_DIR, Dimension, load_dimensions
from integral.harness import DEFAULT_STORE_PATH, load_store
from integral.identity import ProfileStore, create_profile
from integral.interview_log import (
    Question,
    Strict,
    _write_once,
    likely_presses,
    render_story,
)
from integral.profile import EvidenceLog, EvidenceRow

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T47.json"

SCHEMA_VERSION: Literal[1] = 1

STEP = "mock_interview"

REHEARSAL_ID = re.compile(r"^rh-(\d{3,})$")
_ID_WIDTH = 3

#: Step 12's stop rule. Ten rehearsed questions and the session ends.
MAX_QUESTIONS = 10

Phase = Literal["opening", "in_character", "closed"]
Speaker = Literal["interviewer", "candidate"]
TurnKind = Literal[
    "announcement", "question", "follow_up", "silence", "answer", "closing", "feedback"
]

#: The only turns that may appear between the announcement and the close. This
#: is the gate: `Rehearsal` cannot produce anything else while in character, and
#: the measurement holds every transcript on disk to the same set.
IN_CHARACTER: dict[str, frozenset[str]] = {
    "interviewer": frozenset({"question", "follow_up", "silence"}),
    "candidate": frozenset({"answer"}),
}

_ANNOUNCEMENT = (
    "From here I am the interviewer and nothing else: no coaching, no encouragement, "
    "no stepping out to explain a question. It ends when it ends, and the feedback "
    "comes then. You can dictate your answers out loud instead of typing them — "
    "speaking one is much closer to the real thing."
)
_CLOSING = "That is the end of the interview. Thank you for your time."

_QUESTION = "Walk me through a time {label} was what decided how the work went."
#: Follow-ups that test whether a story is real, rather than inviting more of it.
_PROBES = (
    "When was that, and over how long?",
    "Who else was in the room when that was decided?",
    "What would you do differently now?",
)
_SILENCE = ""


class MockInterviewError(Exception):
    """A turn was asked for in a phase that cannot produce it, or the cap was passed."""


class Turn(Strict):
    """One turn of the transcript. `kind` is what the gate reads."""

    kind: TurnKind
    speaker: Speaker
    text: str = ""


class Transcript(Strict):
    """`interviews/<offer_id>/rehearsals/<rh-id>.json` — written once, never revised."""

    schema_version: Literal[1] = SCHEMA_VERSION
    offer_id: str = Field(min_length=1)
    rehearsal_id: str = Field(pattern=REHEARSAL_ID.pattern)
    dictation_offered: bool
    questions_asked: int = Field(ge=0, le=MAX_QUESTIONS)
    turns: tuple[Turn, ...]


def next_rehearsal_id(store: ProfileStore, offer_id: str) -> str:
    """One past the highest `rh-<N>` already recorded against this offer."""
    root = store.path("interviews", offer_id, "rehearsals")
    if not root.is_dir():
        return f"rh-{1:0{_ID_WIDTH}d}"
    found = [
        int(match.group(1))
        for child in root.iterdir()
        if (match := REHEARSAL_ID.match(child.stem)) and child.suffix == ".json"
    ]
    return f"rh-{max(found, default=0) + 1:0{_ID_WIDTH}d}"


def rehearsal_questions(
    presses: tuple[str, ...], dimensions: list[Dimension], language: str = "en"
) -> tuple[Question, ...]:
    """The questions for one rehearsal, from what this advert presses on.

    Truncated to `MAX_QUESTIONS` here, which is where step 12's stop rule
    actually bites: a candidate who would be asked fifteen is asked ten.
    """
    labels = {dimension.id: dimension.label.get(language) for dimension in dimensions}
    return tuple(
        Question(text=_QUESTION.format(label=labels[press].lower()), dimensions=(press,))
        for press in presses[:MAX_QUESTIONS]
        if press in labels
    )


class Rehearsal:
    """One role-play, as a state machine.

    Three phases. `opening` can only announce; `in_character` can only ask,
    press, wait, take an answer, or close; `closed` can only give feedback.
    Every in-character turn is assembled here from a fixed kind, so the
    interviewer has no way to say anything that is not one of those three
    things — which is what makes "no coaching mid-answer" a property of the
    code rather than a promise about its wording.
    """

    def __init__(
        self,
        offer_id: str,
        questions: tuple[Question, ...],
        *,
        dictation_offered: bool = True,
    ) -> None:
        if len(questions) > MAX_QUESTIONS:
            raise MockInterviewError(
                f"{offer_id}: {len(questions)} questions, and step 12 caps a rehearsal at "
                f"{MAX_QUESTIONS} — truncate with `rehearsal_questions`, do not raise the cap"
            )
        self.offer_id = offer_id
        self.questions = questions
        self.dictation_offered = dictation_offered
        self.phase: Phase = "opening"
        self._turns: list[Turn] = []
        self._asked = 0

    # -- phase guards -------------------------------------------------------

    def _require(self, phase: Phase, doing: str) -> None:
        if self.phase != phase:
            raise MockInterviewError(
                f"{self.offer_id}: cannot {doing} while the rehearsal is {self.phase!r}"
            )

    def _say(self, kind: TurnKind, speaker: Speaker, text: str = "") -> Turn:
        turn = Turn(kind=kind, speaker=speaker, text=text)
        self._turns.append(turn)
        return turn

    # -- opening ------------------------------------------------------------

    def announce(self) -> Turn:
        """Say what is about to happen, then go in character. Offers dictation."""
        self._require("opening", "announce")
        turn = self._say("announcement", "interviewer", _ANNOUNCEMENT)
        self.phase = "in_character"
        return turn

    # -- in character -------------------------------------------------------

    def ask(self) -> Turn | None:
        """The next prepared question, or `None` when the ten are used up."""
        self._require("in_character", "ask")
        if self._asked >= len(self.questions):
            return None
        question = self.questions[self._asked]
        self._asked += 1
        return self._say("question", "interviewer", question.text)

    def press(self) -> Turn:
        """A follow-up that tests whether the story is real."""
        self._require("in_character", "press")
        return self._say("follow_up", "interviewer", _PROBES[len(self._turns) % len(_PROBES)])

    def wait(self) -> Turn:
        """The silence after an answer. A turn, deliberately, and an empty one."""
        self._require("in_character", "wait")
        return self._say("silence", "interviewer", _SILENCE)

    def answer(self, text: str) -> Turn:
        """What the candidate said — typed, or dictated."""
        self._require("in_character", "answer")
        return self._say("answer", "candidate", text)

    def close(self) -> Turn:
        """End the role-play. Only after this does the ordinary voice come back."""
        self._require("in_character", "close")
        turn = self._say("closing", "interviewer", _CLOSING)
        self.phase = "closed"
        return turn

    # -- after ---------------------------------------------------------------

    def feedback(self, lines: tuple[str, ...]) -> tuple[Turn, ...]:
        """The feedback, which exists only once the interview is over."""
        self._require("closed", "give feedback")
        return tuple(self._say("feedback", "interviewer", line) for line in lines)

    # -- the record ----------------------------------------------------------

    def transcript(self, rehearsal_id: str) -> Transcript:
        return Transcript(
            offer_id=self.offer_id,
            rehearsal_id=rehearsal_id,
            dictation_offered=self.dictation_offered,
            questions_asked=self._asked,
            turns=tuple(self._turns),
        )

    def save(self, store: ProfileStore) -> Path:
        """Write the transcript. Historical, like every other interview record."""
        rehearsal_id = next_rehearsal_id(store, self.offer_id)
        where = store.path("interviews", self.offer_id, "rehearsals")
        where.mkdir(parents=True, exist_ok=True)
        # `interview_log._write_once` is the repo's one implementation of "create
        # a historical file, or refuse" (process spec §3.4) — a rehearsal is one.
        return _write_once(where / f"{rehearsal_id}.json", self.transcript(rehearsal_id))


# ---------------------------------------------------------------------------
# the gate — read off the transcripts on disk


def transcript_paths(store: ProfileStore) -> list[Path]:
    """Every rehearsal transcript recorded in this profile, in sorted order."""
    root = store.path("interviews")
    if not root.is_dir():
        return []
    return sorted(
        child
        for offer in root.iterdir()
        if offer.is_dir()
        for child in (offer / "rehearsals").glob("*.json")
        if REHEARSAL_ID.match(child.stem)
    )


def _scan(path: Path) -> tuple[list[str], list[str], list[str], list[str]]:
    """One transcript's defects: breaks, unannounced, unclosed, over the cap.

    Parsed as raw JSON, deliberately. Validating through `Transcript` would make
    an unknown turn kind a *load error* rather than a *finding*, so the one
    thing the gate exists to catch — a turn nothing in this module can produce —
    would be silently unreadable instead of loudly counted.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    turns = data.get("turns") or []
    name = f"{data.get('offer_id', path.parent.parent.name)}/{path.stem}"

    breaks: list[str] = []
    unannounced: list[str] = []
    unclosed: list[str] = []
    over_cap: list[str] = []

    start = 0
    if turns and turns[0].get("kind") == "announcement":
        start = 1
    else:
        unannounced.append(f"{name}: the role-play is not announced before it begins")

    kinds = [turn.get("kind") for turn in turns]
    if "closing" in kinds:
        end = kinds.index("closing")
    else:
        end = len(turns)
        unclosed.append(f"{name}: the role-play never ends, so nothing is ever out of character")

    for index in range(start, end):
        turn = turns[index]
        speaker = str(turn.get("speaker"))
        kind = str(turn.get("kind"))
        if kind not in IN_CHARACTER.get(speaker, frozenset()):
            breaks.append(f"{name}: turn {index} is {kind!r} from the {speaker}")

    asked = sum(1 for kind in kinds[start:end] if kind == "question")
    if asked > MAX_QUESTIONS:
        over_cap.append(f"{name}: {asked} questions rehearsed, and the cap is {MAX_QUESTIONS}")

    return breaks, unannounced, unclosed, over_cap


def character_breaks(store: ProfileStore) -> dict[str, Any]:
    """The gate: turns inside a recorded role-play that are not the interviewer.

    `None`, never a passing `0`, over zero rehearsals (D-2): a profile that
    never rehearsed has not stayed in character, it has nothing to have broken.
    """
    paths = transcript_paths(store)
    breaks: list[str] = []
    unannounced: list[str] = []
    unclosed: list[str] = []
    over_cap: list[str] = []
    for path in paths:
        found = _scan(path)
        breaks += found[0]
        unannounced += found[1]
        unclosed += found[2]
        over_cap += found[3]

    return {
        "mock_interview_character_breaks": None if not paths else len(breaks),
        "sessions_rehearsed": len(paths),
        "character_breaks": sorted(breaks),
        "sessions_not_announced": sorted(unannounced),
        "sessions_never_closed": sorted(unclosed),
        "sessions_over_the_question_cap": sorted(over_cap),
    }


# ---------------------------------------------------------------------------
# measurement — scripted rehearsals against a fixture candidate

_FIXTURE_EPISODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Rebuilt the on-call rota after a quarter of 2am pages", ("on_call_load",)),
    ("Ran the migration end to end with no one reviewing the plan", ("team_autonomy",)),
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


def rehearse(
    store: ProfileStore,
    bank: list[EvidenceRow],
    *,
    offer_id: str,
    questions: tuple[Question, ...],
) -> Path:
    """Run one scripted rehearsal end to end and record it.

    The script is the shape every real session has: announce, then question,
    answer, follow-up, silence — and only once it is closed, the feedback.
    """
    session = Rehearsal(offer_id, questions)
    session.announce()
    covered = 0
    for question in questions:
        if session.ask() is None:  # pragma: no cover - the cap already truncated
            break
        held = next((row for row in bank if set(question.dimensions) & set(row.dimensions)), None)
        session.answer(render_story(held) if held else "(nothing to draw on)")
        session.press()
        session.wait()
        covered += held is not None
    session.close()
    session.feedback(
        (
            f"{len(questions)} questions; {len(questions) - covered} had no episode "
            "in the story bank behind them.",
        )
    )
    return session.save(store)


def measure(
    store_path: Path | None = None,
    dimensions_dir: Path = DEFAULT_DIMENSIONS_DIR,
) -> dict[str, Any]:
    """`mock_interview_character_breaks` over a rehearsal per advert in the corpus.

    Real advert text decides what is pressed on, so the number of questions —
    and whether the cap bites — comes from the committed corpus rather than
    from a fixture written to hit it. The candidate is a fixture, because there
    is no person in this repository and there must not be.
    """
    dimensions = load_dimensions(dimensions_dir)
    ads = load_store(store_path or DEFAULT_STORE_PATH)

    nothing_to_ask: list[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "profiles"
        identity = create_profile(root, "Gate Fixture", handle="fixture", language="en")
        store = ProfileStore(root, identity.handle)
        bank = _seed_bank(EvidenceLog(store))

        for ad in ads:
            questions = rehearsal_questions(likely_presses(ad, dimensions), dimensions)
            if not questions:
                nothing_to_ask.append(ad.id)
                continue
            rehearse(store, bank, offer_id=ad.id, questions=questions)

        measured = character_breaks(store)

    measured["adverts_seen"] = len(ads)
    measured["adverts_with_nothing_to_rehearse"] = sorted(nothing_to_ask)
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T47.json`."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write T47's gate evidence. Exit 1 on any turn the role-play should not hold."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    for key, label in (
        ("character_breaks", "turn inside the role-play that is not the interviewer"),
        ("sessions_not_announced", "rehearsal that was never announced"),
        ("sessions_never_closed", "rehearsal that never ended"),
        ("sessions_over_the_question_cap", "rehearsal past the ten-question cap"),
    ):
        for line in measured[key]:
            print(f"✗ {label}: {line}", file=sys.stderr)
    print(json.dumps(measured, ensure_ascii=False))
    if any(
        measured[key]
        for key in (
            "sessions_not_announced",
            "sessions_never_closed",
            "sessions_over_the_question_cap",
        )
    ):
        return 1
    # `== 0`, not "no breaks found". A run that rehearsed nothing scores `None`
    # with an empty list, and exiting 0 on that would report a gate met by a
    # step that never entered character (D-2).
    if measured["mock_interview_character_breaks"] != 0:
        print(
            f"mock_interview_character_breaks is "
            f"{measured['mock_interview_character_breaks']!r}, not 0",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
