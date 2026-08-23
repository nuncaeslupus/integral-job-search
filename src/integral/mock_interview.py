"""T47 — step 12: the mock interview, and it is a strict role-play.

The gate is `mock_interview_character_breaks == 0`: once the role-play is
announced, the tool is the interviewer and nothing else — no coaching
mid-answer, no encouragement, no breaking character to explain a question. The
discomfort of an unhelped answer is the entire exercise, so a rehearsal
interrupted every third answer to be helpful rehearses nothing.

**The rule is structural, not a blocklist over free text.** Scanning generated
prose for coaching phrases is a keyword list and can always be talked around —
*"just to help you here"* rephrased is still coaching, and the scanner is one
paraphrase behind for ever. So the interviewer is given no free text to write
in. While in character its entire vocabulary is `VOCABULARY`: the announcement,
one question frame with a **dimension id** substituted into it, three
follow-ups, silence, and the closing. That is five sentences and a frame, and
nothing else exists to say.

Constraining the turn *kind* alone would not do it, and the first version of
this module made exactly that mistake: `ask()` emitted caller-supplied text, so
a `Question` whose wording was a STAR tip scored `kind="question"` and zero
breaks. The subject is now a dimension id — `SNAKE_CASE`, so prose cannot be
smuggled through it — and the wording is rendered here, by `render`.

**The measurement reads the transcripts on disk** and re-renders every
interviewer turn from the `(kind, form)` it recorded, then requires the text to
match. A turn nothing in this module could have said — a hand edit, a later
feature, a second writer — therefore *moves the number* rather than being
rejected at the door by the schema, which is why the turns are parsed as raw
JSON rather than through `Turn`.

**And the scan is total.** Every turn is examined: the span before the closing
against the in-character vocabulary, and everything after it against "the
feedback, and nothing else". An earlier version took `kinds.index("closing")`
and iterated up to it, so one planted `closing` at index 1 left the rest of the
transcript unread — a blind spot exactly where a smuggler would aim.

`VOCABULARY` is pinned literally by `test_the_interviewer_vocabulary_is_closed`,
because the one thing a re-render cannot catch is the vocabulary itself being
rewritten: change `_PROBES[0]` to a tip and writer and reader agree again. That
test is what makes such an edit a decision somebody has to take deliberately,
and it is decidable only because the set is finite.

**The questions come from S6's preparation**, not from a generic list: the
dimensions this advert presses on (`likely_presses`) decide what is asked, and
the story bank decides which of those the candidate has an episode for. Hard
cap: ten rehearsed questions.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from integral.dimensions import DEFAULT_DIMENSIONS_DIR, Dimension, load_dimensions
from integral.harness import DEFAULT_STORE_PATH, load_store
from integral.identity import ProfileStore, create_profile
from integral.interview_log import Strict, _write_once, likely_presses, render_story
from integral.profile import EvidenceLog, EvidenceRow

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T47.json"

SCHEMA_VERSION: Literal[1] = 1

REHEARSAL_ID = re.compile(r"^rh-(\d{3,})$")
#: No separator, and no leading dot. A transcript filed under an id containing
#: one lands outside `interviews/<offer_id>/rehearsals/`, where
#: `transcript_paths` never looks — three defective rehearsals would then
#: measure as one clean session. Refusing the id is cheaper than making the
#: walk clever, and every advert id in the corpus already satisfies it.
OFFER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ID_WIDTH = 3

#: Step 12's stop rule. Ten rehearsed questions and the session ends.
MAX_QUESTIONS = 10

Phase = Literal["opening", "in_character", "closed"]
Speaker = Literal["interviewer", "candidate"]
TurnKind = Literal[
    "announcement", "question", "follow_up", "silence", "answer", "closing", "feedback"
]

#: The only turns that may appear up to and including the closing. `Rehearsal`
#: cannot produce anything else while in character, and the measurement holds
#: every transcript on disk to the same set.
IN_CHARACTER: dict[str, frozenset[str]] = {
    "interviewer": frozenset({"question", "follow_up", "silence", "closing"}),
    "candidate": frozenset({"answer"}),
}

ANNOUNCEMENT = (
    "From here I am the interviewer and nothing else: no coaching, no encouragement, "
    "no stepping out to explain a question. It ends when it ends, and the feedback "
    "comes then. You can dictate your answers out loud instead of typing them — "
    "speaking one is much closer to the real thing."
)
CLOSING = "That is the end of the interview. Thank you for your time."
QUESTION = "Walk me through a time {label} was what decided how the work went."
#: Follow-ups that test whether a story is real, rather than inviting more of it.
PROBES = (
    "When was that, and over how long?",
    "Who else was in the room when that was decided?",
    "What would you do differently now?",
)

#: Everything the interviewer can say in character. Pinned by a test.
VOCABULARY: tuple[str, ...] = (ANNOUNCEMENT, CLOSING, QUESTION, *PROBES, "")


class MockInterviewError(Exception):
    """A turn was asked for in a phase that cannot produce it, or a value was refused."""


class Turn(Strict):
    """One turn. `form` is what the interviewer's words are re-rendered from.

    For a `question` it is the dimension id being asked about; for a
    `follow_up`, the index of the probe. Fixed-wording turns carry `""`. The
    candidate's `answer` and the after-the-end `feedback` are free prose and are
    stored as written — the first is theirs, and the second is the ordinary
    voice, which by then is allowed back.
    """

    kind: TurnKind
    speaker: Speaker
    form: str = ""
    text: str = ""


class Transcript(Strict):
    """`interviews/<offer_id>/rehearsals/<rh-id>.json` — written once, never revised.

    Carries no summary of itself. An earlier version recorded
    `questions_asked` and `dictation_offered`, and both could be set to
    anything without a test noticing: a count is derivable from the turns, and
    whether dictation was offered is a property of the announcement's wording,
    which the scan now re-renders. A field that can lie freely is worse than
    no field.
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    offer_id: str = Field(pattern=OFFER_ID.pattern)
    rehearsal_id: str = Field(pattern=REHEARSAL_ID.pattern)
    turns: tuple[Turn, ...]


def render(kind: str, form: str, labels: Mapping[str, str]) -> str | None:
    """The one wording this module produces for `(kind, form)`, or `None`.

    `None` means "there is no such interviewer turn" — an unknown kind, a
    question about a dimension the model does not have, a probe index out of
    range. Both the writer and the gate call this, which is what makes "the
    interviewer said only what this module can say" checkable rather than
    asserted.
    """
    match kind:
        case "announcement":
            return ANNOUNCEMENT
        case "closing":
            return CLOSING
        case "silence":
            # Literal, not a constant. The silence after an answer is the
            # exercise; a constant here could be edited into encouragement and
            # writer and reader would agree about it.
            return ""
        case "question":
            label = labels.get(form)
            return None if label is None else QUESTION.format(label=label)
        case "follow_up":
            return PROBES[int(form)] if form.isdigit() and int(form) < len(PROBES) else None
        case _:
            return None


def dimension_labels(dimensions: list[Dimension], language: str = "en") -> dict[str, str]:
    """`{dimension id: the label a question is asked about}`."""
    return {dimension.id: dimension.label.get(language).lower() for dimension in dimensions}


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


def rehearsal_subjects(presses: tuple[str, ...], labels: Mapping[str, str]) -> tuple[str, ...]:
    """The dimensions one rehearsal asks about, from what this advert presses on.

    Truncated to `MAX_QUESTIONS` here, which is where step 12's stop rule
    actually bites: a candidate who would be asked fifteen is asked ten.
    """
    return tuple(press for press in presses if press in labels)[:MAX_QUESTIONS]


class Rehearsal:
    """One role-play, as a state machine.

    Three phases. `opening` can only announce; `in_character` can only ask,
    press, wait, take an answer, or close; `closed` can only give feedback.
    Every interviewer turn is rendered here by `render`, from a subject that is
    a dimension id — so there is no argument through which a caller can put
    words in the interviewer's mouth.
    """

    def __init__(
        self,
        offer_id: str,
        subjects: tuple[str, ...],
        labels: Mapping[str, str],
    ) -> None:
        if not OFFER_ID.match(offer_id):
            raise MockInterviewError(
                f"{offer_id!r} is not a usable offer id — a separator or a leading dot files "
                "the transcript where the gate does not look, and an unread rehearsal is a "
                "rehearsal that cannot fail"
            )
        if len(subjects) > MAX_QUESTIONS:
            raise MockInterviewError(
                f"{offer_id}: {len(subjects)} questions, and step 12 caps a rehearsal at "
                f"{MAX_QUESTIONS} — truncate with `rehearsal_subjects`, do not raise the cap"
            )
        unknown = sorted(set(subjects) - set(labels))
        if unknown:
            raise MockInterviewError(
                f"{offer_id}: cannot ask about {', '.join(unknown)} — a subject is a dimension "
                "id, which is what keeps free prose out of the interviewer's questions"
            )
        self.offer_id = offer_id
        self.subjects = subjects
        self.labels = dict(labels)
        self.phase: Phase = "opening"
        self._turns: list[Turn] = []
        self._asked = 0

    # -- phase guards -------------------------------------------------------

    def _require(self, phase: Phase, doing: str) -> None:
        if self.phase != phase:
            raise MockInterviewError(
                f"{self.offer_id}: cannot {doing} while the rehearsal is {self.phase!r}"
            )

    def _say(self, kind: TurnKind, form: str = "") -> Turn:
        """The only way an interviewer turn is made: rendered, never passed in."""
        text = render(kind, form, self.labels)
        if text is None:  # pragma: no cover - unreachable; the callers pass fixed kinds
            raise MockInterviewError(f"{self.offer_id}: no interviewer wording for {kind}/{form}")
        turn = Turn(kind=kind, speaker="interviewer", form=form, text=text)
        self._turns.append(turn)
        return turn

    # -- opening ------------------------------------------------------------

    def announce(self) -> Turn:
        """Say what is about to happen, then go in character. Offers dictation."""
        self._require("opening", "announce")
        turn = self._say("announcement")
        self.phase = "in_character"
        return turn

    # -- in character -------------------------------------------------------

    def ask(self) -> Turn | None:
        """The next prepared question, or `None` when the ten are used up."""
        self._require("in_character", "ask")
        if self._asked >= len(self.subjects):
            return None
        subject = self.subjects[self._asked]
        self._asked += 1
        return self._say("question", subject)

    def press(self) -> Turn:
        """A follow-up that tests whether the story is real."""
        self._require("in_character", "press")
        return self._say("follow_up", str(len(self._turns) % len(PROBES)))

    def wait(self) -> Turn:
        """The silence after an answer. A turn, deliberately, and an empty one."""
        self._require("in_character", "wait")
        return self._say("silence")

    def answer(self, text: str) -> Turn:
        """What the candidate said — typed, or dictated. Theirs, so free prose."""
        self._require("in_character", "answer")
        turn = Turn(kind="answer", speaker="candidate", text=text)
        self._turns.append(turn)
        return turn

    def close(self) -> Turn:
        """End the role-play. Only after this does the ordinary voice come back."""
        self._require("in_character", "close")
        turn = self._say("closing")
        self.phase = "closed"
        return turn

    # -- after ---------------------------------------------------------------

    def feedback(self, lines: tuple[str, ...]) -> tuple[Turn, ...]:
        """The feedback, which exists only once the interview is over."""
        self._require("closed", "give feedback")
        out = tuple(Turn(kind="feedback", speaker="interviewer", text=line) for line in lines)
        self._turns += out
        return out

    # -- the record ----------------------------------------------------------

    def transcript(self, rehearsal_id: str) -> Transcript:
        return Transcript(
            offer_id=self.offer_id, rehearsal_id=rehearsal_id, turns=tuple(self._turns)
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


class _Defects(dict[str, list[str]]):
    """The named findings from one scan or many, keyed by the list they belong in."""

    def add(self, key: str, entry: str) -> None:
        self.setdefault(key, []).append(entry)


def _scan(path: Path, labels: Mapping[str, str], found: _Defects) -> None:
    """One transcript's defects, named. Every turn is examined.

    Parsed as raw JSON, deliberately. Validating through `Transcript` would make
    a planted turn a *load error* rather than a *finding*, so the one thing the
    gate exists to catch would be silently unreadable instead of loudly counted.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    turns = data.get("turns") or []
    name = f"{data.get('offer_id', path.parent.parent.name)}/{path.stem}"

    def says(index: int) -> str:
        turn = turns[index]
        return f"{name}: turn {index} is {turn.get('kind')!r} from the {turn.get('speaker')}"

    start = 1
    opening = turns[0] if turns else {}
    # The speaker is checked, not just the kind. This turn decides how much of
    # the transcript is scanned, and a boundary turn that is itself unscanned is
    # exactly the hole a planted `closing` opened: a forged first turn reading
    # `announcement` from the *candidate* would advance `start` past itself and
    # never be held to `IN_CHARACTER`, so a role-play the interviewer never
    # announced would measure clean. Treated as no announcement at all, which
    # leaves `start` at 0 and puts the forged turn back inside the scan.
    if opening.get("kind") != "announcement" or opening.get("speaker") != "interviewer":
        found.add(
            "sessions_not_announced", f"{name}: the role-play is not announced before it begins"
        )
        start = 0
    elif opening.get("text") != ANNOUNCEMENT:
        # The announcement is the promise the whole role-play is held to — that
        # there will be no coaching, and that dictation is on offer. A rewritten
        # one is not an announcement, so it is reported the same way a missing
        # one is. This is also why no `dictation_offered` flag is recorded: the
        # offer is in these words, and these words are re-rendered.
        found.add(
            "sessions_not_announced",
            f"{name}: the announcement is not the one this module makes",
        )

    kinds = [turn.get("kind") for turn in turns]
    if "closing" in kinds:
        end = kinds.index("closing")
    else:
        end = len(turns) - 1
        found.add(
            "sessions_never_closed",
            f"{name}: the role-play never ends, so nothing is ever out of character",
        )

    # Up to and including the closing: only the in-character kinds, and the
    # interviewer's words must be exactly what this module renders for them.
    for index in range(start, min(end + 1, len(turns))):
        turn = turns[index]
        speaker, kind = str(turn.get("speaker")), str(turn.get("kind"))
        if kind not in IN_CHARACTER.get(speaker, frozenset()):
            found.add("character_breaks", says(index))
        elif speaker == "interviewer" and turn.get("text") != render(
            kind, str(turn.get("form", "")), labels
        ):
            found.add("character_breaks", f"{says(index)}, and not in the interviewer's words")

    # After it: the ordinary voice, and only that. A second `closing`, a
    # question, an answer — anything here is a turn nobody was still in the
    # role-play for, and leaving the span unread is what let one planted
    # `closing` hide a whole transcript.
    for index in range(end + 1, len(turns)):
        if kinds[index] != "feedback":
            found.add("turns_after_the_end_that_are_not_feedback", says(index))

    asked = kinds.count("question")
    if asked > MAX_QUESTIONS:
        found.add(
            "sessions_over_the_question_cap",
            f"{name}: {asked} questions rehearsed, and the cap is {MAX_QUESTIONS}",
        )


DEFECT_KEYS = (
    "character_breaks",
    "sessions_not_announced",
    "sessions_never_closed",
    "turns_after_the_end_that_are_not_feedback",
    "sessions_over_the_question_cap",
)


def character_breaks(
    store: ProfileStore, dimensions: list[Dimension] | None = None
) -> dict[str, Any]:
    """The gate: turns inside a recorded role-play that are not the interviewer.

    `None`, never a passing `0`, over zero rehearsals (D-2): a profile that
    never rehearsed has not stayed in character, it has nothing to have broken.
    """
    labels = dimension_labels(dimensions if dimensions is not None else load_dimensions())
    paths = transcript_paths(store)
    found = _Defects()
    for path in paths:
        _scan(path, labels, found)

    measured: dict[str, Any] = {
        "mock_interview_character_breaks": (
            None if not paths else len(found.get("character_breaks", []))
        ),
        "sessions_rehearsed": len(paths),
    }
    measured.update({key: sorted(found.get(key, [])) for key in DEFECT_KEYS})
    return measured


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
    subjects: tuple[str, ...],
    labels: Mapping[str, str],
) -> Path:
    """Run one scripted rehearsal end to end and record it.

    The script is the shape every real session has: announce, then question,
    answer, follow-up, silence — and only once it is closed, the feedback.
    """
    session = Rehearsal(offer_id, subjects, labels)
    session.announce()
    covered = 0
    for subject in subjects:
        if session.ask() is None:  # pragma: no cover - the cap already truncated
            break
        held = next((row for row in bank if subject in row.dimensions), None)
        session.answer(render_story(held) if held else "(nothing to draw on)")
        session.press()
        session.wait()
        covered += held is not None
    session.close()
    session.feedback(
        (
            f"{len(subjects)} questions; {len(subjects) - covered} had no episode "
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
    labels = dimension_labels(dimensions)
    ads = load_store(store_path or DEFAULT_STORE_PATH)

    nothing_to_ask: list[str] = []
    at_the_cap = 0
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "profiles"
        identity = create_profile(root, "Gate Fixture", handle="fixture", language="en")
        store = ProfileStore(root, identity.handle)
        bank = _seed_bank(EvidenceLog(store))

        for ad in ads:
            subjects = rehearsal_subjects(likely_presses(ad, dimensions), labels)
            if not subjects:
                nothing_to_ask.append(ad.id)
                continue
            at_the_cap += len(subjects) == MAX_QUESTIONS
            rehearse(store, bank, offer_id=ad.id, subjects=subjects, labels=labels)

        measured = character_breaks(store, dimensions)

    measured["adverts_seen"] = len(ads)
    measured["adverts_with_nothing_to_rehearse"] = sorted(nothing_to_ask)
    # Recorded because it is the honest state of the cap: no advert in this
    # corpus presses on more than ten dimensions, so `rehearsal_subjects` never
    # truncates here and `sessions_over_the_question_cap` could not have been
    # non-empty from this run. The cap's check is exercised by a planted
    # transcript in the tests instead of being reported as a passing zero.
    measured["adverts_at_the_question_cap"] = at_the_cap
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T47.json`."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


_LABELS = {
    "character_breaks": "turn inside the role-play that is not the interviewer",
    "sessions_not_announced": "rehearsal that was never announced",
    "sessions_never_closed": "rehearsal that never ended",
    "turns_after_the_end_that_are_not_feedback": "turn after the end that is not the feedback",
    "sessions_over_the_question_cap": "rehearsal past the ten-question cap",
}


def _main(argv: list[str]) -> int:
    """Write T47's gate evidence. Exit 1 on any turn the role-play should not hold."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    for key, label in _LABELS.items():
        for line in measured[key]:
            print(f"✗ {label}: {line}", file=sys.stderr)
    print(json.dumps(measured, ensure_ascii=False))
    if any(measured[key] for key in DEFECT_KEYS if key != "character_breaks"):
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
