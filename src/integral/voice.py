"""Stored voice preferences, and generation that honours them (T147).

A candidate reading a draft says "that sounds like bad work" and the sentence
is fixed. The next application starts from the same defaults and earns the same
correction from a person who has already given it. A *voice preference* is that
correction kept: stated once, applicable to every later document, checkable
after the fact.

**It is not a dimension score.** Scoring a rule about prose against an advert
means nothing. It is a constraint on the text, so its shape is a statement the
candidate can read plus the phrasings it forbids (`forbid`, case-insensitive
regular expressions). A preference with no `forbid` is *advisory*: it is listed
when applied but nothing can check it mechanically (a rule about type size or
a paragraph's last line is layout, which T143 measures, not prose).

**It lives in the evidence log**, as a `statement` row under `step:
"preferences"` whose text is JSON carrying a `voice_preference` key (T41's
convention for a structured capture, as `integral.weights` uses). So a
retraction is `integral.retraction.retract` on that row and nothing here
reimplements suppression: `stored_preferences` reads `effective_rows()`, the
same reader every other derived view cites through.

**It is visible when applied.** `generate` records every preference it applied
in the manifest, with whether it could enforce it, and `notice` renders the
sentence the candidate sees ("applied 6 of your stored preferences", then the
list). A preference inferred from one irritated sentence can be wrong, and a
wrong one that silently governs every document is worse than the correction it
saved.

**The rule `generate` enforces is closed, not enumerated.** Every rendered
line, scaffold included, is matched against every live preference's `forbid`.
An entry that violates is left out of both documents and recorded as an
`Omission` naming the preference, so the candidate can say it was the wrong
call; a scaffold line that violates refuses the generation outright, because
there is no entry to leave out. Nothing is rewritten: a generator that
paraphrased the candidate's own words to satisfy a rule would be inventing
claims, which T45 exists to prevent.

The gate is `voice_preference_defects == 0`, measured by `measure` over one
fixture per preference: a draft that violates it must not be emitted, its
compliant twin must be (or banning every sentence would score zero), a
retracted preference must stop applying, and a retraction that is itself
retracted must restore it.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from integral.profile import EvidenceLog, EvidenceRow

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T147.json"

VOICE_STEP = "preferences"
VOICE_KEY = "voice_preference"

# The seven corrections of the first document round, as (statement, forbid,
# violating draft, compliant twin). A twin says the same thing the permitted
# way; the gate requires it through, so it cannot be met by refusing prose.
# An empty `forbid` is advisory. These are the fixtures, and `record` is how a
# real candidate's preferences are written: nothing here is applied unless a
# row in that candidate's own log says so.
_NUMBER_WORDS = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"twenty|thirty|forty|fifty|hundred|thousand)"
)
_COUNTED = (
    r"(?:commits|repositories|repos|stars|downloads|users|contributors|"
    r"failure\s+families|customers|clients)"
)
SEEDS: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    (
        "Do not sound as though I am asking to be quizzed on the employer's most basic course.",
        (
            r"\bask(?:ed)?\s+(?:me\s+)?(?:about|on)\s+(?:your|the)\s+(?:most\s+)?"
            r"(?:basic|introductory|beginner)\b",
            r"\bquiz(?:zed)?\s+me\b",
        ),
        "I would be happy if you asked me about your most basic course.",
        "I have read your course outline and have a concrete question about its project.",
    ),
    (
        "Say 'without worrying too much about their structure', never 'perfectly structured'.",
        (r"\bwhether\s+(?:they|it|these)\s+(?:are|is)\s+perfectly\s+structured\b",),
        "I share notes without worrying whether they are perfectly structured.",
        "I share notes without worrying too much about their structure.",
    ),
    (
        "Claim authorship explicitly: 'I was the one who', not a bare 'I automated'.",
        (r"\bI\s+automated\b",),
        "I automated a good deal of my team's tasks with AI.",
        "I was the one who automated a good deal of my team's tasks with AI.",
    ),
    (
        "No sentimental register.",
        (
            r"\bit(?:'s|\s+is)\s+also\s+personal\b",
            r"\bclose\s+to\s+my\s+heart\b",
            r"\bpassion(?:ate)?\b",
        ),
        "It is also personal: this field is close to my heart.",
        "This field is where I have spent the last six years.",
    ),
    (
        "Nothing unintelligible in the CV, even when true.",
        (r"\bdrawspec\b", r"\bfailure\s+famil(?:y|ies)\b"),
        "Built drawspec, with its failure families.",
        "Built a diagramming tool for specifications.",
    ),
    (
        "No figures that go stale.",
        (rf"~?\s*\b(?:\d[\d,.]*\+?|{_NUMBER_WORDS})\s+(?:\w+\s+)?{_COUNTED}\b",),
        "About 1,600 commits across seven repositories.",
        "Maintains several repositories of his own.",
    ),
    (
        "Less text and larger type over more content; no paragraph ending on a nearly empty line.",
        (),
        "",
        "",
    ),
)


class VoiceError(Exception):
    """A preference could not be stored, or a generation could not honour one."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VoicePreference(Strict):
    """One stored preference: the log row it came from, what it says, what it forbids."""

    row_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    forbid: tuple[str, ...] = ()

    @property
    def enforced(self) -> bool:
        return bool(self.forbid)


class VoiceApplied(Strict):
    """What the manifest records for one preference a generation applied."""

    row_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    enforced: bool


def _normalise(text: str) -> str:
    """NFKC plus collapsed whitespace: a width variant or double space cannot dodge a rule."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text))


def _compile(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise VoiceError(f"{pattern!r} is not a regular expression: {exc}") from exc


def encode_preference(statement: str, forbid: Sequence[str] = ()) -> str:
    """The row text. Validates every pattern, so a stored rule always compiles."""
    if not statement.strip():
        raise VoiceError("a voice preference needs a statement the candidate can read")
    for pattern in forbid:
        if _compile(pattern).search(""):
            # Matches the empty string, hence every line: it would silently
            # empty every document.
            raise VoiceError(f"{pattern!r} matches the empty string, so it forbids everything")
    return json.dumps(
        {VOICE_KEY: {"statement": statement, "forbid": list(forbid)}}, ensure_ascii=False
    )


def decode_preference(row: EvidenceRow) -> VoicePreference | None:
    """The preference a row carries, or `None` for any row that is not one.

    A row that merely resembles one (right step, wrong text) is `None`, never an
    error: the `preferences` step also holds step 6's forced choices.
    """
    if row.kind != "statement" or row.step != VOICE_STEP:
        return None
    try:
        payload = json.loads(row.text)
    except ValueError:
        return None
    body = payload.get(VOICE_KEY) if isinstance(payload, dict) else None
    if not isinstance(body, dict):
        return None
    statement, forbid = body.get("statement"), body.get("forbid", [])
    if not isinstance(statement, str) or not statement.strip():
        return None
    if not isinstance(forbid, list) or not all(isinstance(item, str) for item in forbid):
        return None
    try:
        for pattern in forbid:
            _compile(pattern)
    except VoiceError:
        return None
    return VoicePreference(row_id=row.id, statement=statement, forbid=tuple(forbid))


def record(
    log: EvidenceLog, statement: str, forbid: Sequence[str] = (), *, at: str
) -> VoicePreference:
    """Store one preference. Retract the returned `row_id` to stop it applying."""
    row = log.append(
        recorded_at=at,
        step=VOICE_STEP,
        kind="statement",
        text=encode_preference(statement, forbid),
        source="conversation",
    )
    decoded = decode_preference(row)
    if decoded is None:  # pragma: no cover - encode_preference just validated it
        raise VoiceError("the preference just written does not read back")
    return decoded


def stored_preferences(log: EvidenceLog) -> tuple[VoicePreference, ...]:
    """The live preferences, oldest first. A retracted one is not here."""
    found = (decode_preference(row) for row in log.effective_rows())
    return tuple(pref for pref in found if pref is not None)


def violations(text: str, preferences: Iterable[VoicePreference]) -> list[VoicePreference]:
    """Which preferences `text` breaks. Advisory preferences never appear."""
    flat = _normalise(text)
    return [
        pref
        for pref in preferences
        if any(_compile(pattern).search(flat) for pattern in pref.forbid)
    ]


def applied(preferences: Iterable[VoicePreference]) -> tuple[VoiceApplied, ...]:
    return tuple(
        VoiceApplied(row_id=p.row_id, statement=p.statement, enforced=p.enforced)
        for p in preferences
    )


def notice(preferences: Sequence[VoiceApplied | VoicePreference]) -> str:
    """The sentence the candidate sees, and the list behind it."""
    if not preferences:
        return "applied 0 of your stored preferences"
    head = f"applied {len(preferences)} of your stored preferences"
    lines = [
        f"  - {p.statement}" + ("" if p.enforced else " (advisory, not checked)")
        for p in preferences
    ]
    return "\n".join([head + ":", *lines])


# ---------------------------------------------------------------------------
# the gate


def _fixture_master(drafts: Sequence[str]) -> Any:
    from integral.cv_store import CVMaster, Experience

    return CVMaster(
        experience=tuple(
            Experience(title=f"Role {i}", organisation=f"Org {i}", description=text)
            for i, text in enumerate(drafts)
        )
    )


def _emitted(store: Any, master: Any, offer: str) -> tuple[str, Any]:
    from integral.generate import generate

    manifest = generate(store, master, offer_id=offer, advert="advert")
    root = store.path("cv", "generated", offer, f"v{manifest.version}")
    text = (root / "cv.md").read_text(encoding="utf-8") + (root / "letter.md").read_text(
        encoding="utf-8"
    )
    return text, manifest


def measure() -> dict[str, Any]:
    """`voice_preference_defects` over one fixture per enforceable seed."""
    from integral.identity import ProfileStore, create_profile
    from integral.retraction import retract, unretract

    enforceable = [seed for seed in SEEDS if seed[1]]
    defects: list[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "profiles"
        identity = create_profile(root, "Gate Fixture", handle="fixture", language="en")
        store = ProfileStore(root, identity.handle)
        log = EvidenceLog(store)
        master = _fixture_master(
            [seed[2] for seed in enforceable] + [seed[3] for seed in enforceable]
        )
        stored = [record(log, s[0], s[1], at="2026-01-01") for s in SEEDS]

        text, manifest = _emitted(store, master, "all-live")
        if len(manifest.voice_applied) != len(SEEDS):
            defects.append(f"applied {len(manifest.voice_applied)} of {len(SEEDS)}")
        for seed in enforceable:
            if seed[2] in text:
                defects.append(f"emitted the violating draft: {seed[2]}")
            if seed[3] not in text:
                defects.append(f"withheld the compliant twin: {seed[3]}")

        for seed, pref in zip(SEEDS, stored, strict=True):
            if not seed[1]:
                continue
            retract(log, pref.row_id, at="2026-01-02")
            text, manifest = _emitted(store, master, f"without-{pref.row_id}")
            if seed[2] not in text:
                defects.append(f"a retracted preference still applies: {seed[0]}")
            if pref.row_id in {a.row_id for a in manifest.voice_applied}:
                defects.append(f"a retracted preference is still listed: {seed[0]}")
            others = [s for s in enforceable if s is not seed]
            if any(s[2] in text for s in others):
                defects.append(f"retracting one preference released another: {seed[0]}")
            rows = log.rows()
            unretract(log, rows[-1].id, at="2026-01-03")
            text, _ = _emitted(store, master, f"restored-{pref.row_id}")
            if seed[2] in text:
                defects.append(f"a restored preference does not apply: {seed[0]}")

    return {
        "voice_preference_defects": len(defects),
        "defects": defects,
        "preferences_checked": len(enforceable),
        "preferences_stored": len(SEEDS),
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["voice_preference_defects"] != 0:
        return 1
    if measured["preferences_checked"] == 0:
        print("the gate checked no preferences, so a zero proves nothing", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
