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

**A stored correction that cannot be read is shown, never dropped.** Any
non-`reaction` row under `step: "preferences"` that is not in voice-preference form
(the shape a prose backfill leaves) is listed by id in the notice and in the
manifest as *unreadable*: "N stored, M applied, K unreadable". It is not guessed
at or migrated from its phrasing, because a rule inferred from a sentence that
was meant as something else is the wrong preference silently governing every
document. Re-record it with `python -m integral.voice record`, or retract it to
dismiss it. Step 6's forced choices are `reaction` rows, so they never count.

**A line with an invisible character is not trusted.** Whether a zero-width
space stands for a space or for nothing is the matcher's guess, and a mix of
both in one line defeats any fixed pair of readings. So under any enforceable
preference an entry holding a `Default_Ignorable_Code_Point` or `Cf` character
is left out and recorded as an omission ("contains invisible characters"), so
the candidate can clean the source. Nothing is repaired.

**`forbid` is a floor on what is caught, not a definition of the preference.**
A paraphrase the patterns do not name gets through; the statement the candidate
reads is the definition, and the patterns are only what can be checked.

**The rule `generate` enforces is closed, not enumerated.** Every rendered
line, scaffold and section headings included, is matched against every live
preference's `forbid`.
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

import argparse
import datetime
import functools
import json
import re
import sys
import tempfile
import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from integral.identity import IdentityError, ProfileStore
from integral.profile import EvidenceLog, EvidenceRow, ProfileError
from integral.state_home import StateHomeRefused, ensure_outside_a_work_tree, profiles_root

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
        (r"\bwhether\s+(?:they|it|these)\s*(?:are|is|'re|'s)\s+perfectly\s+structured\b",),
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
        "This field is where I have spent my working life.",
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


@functools.lru_cache(maxsize=1)
def _quote_folds() -> dict[int, str]:
    """Every code point Unicode itself names an apostrophe or a quotation mark.

    Derived from the character database rather than listed: a word processor's
    U+2019, a keyboard's modifier apostrophe U+02BC, a prime U+2032 and a
    fullwidth U+FF07 are all "apostrophe" by name, and the next variant added to
    Unicode is covered without anyone remembering it. Single marks fold to `'`,
    double ones to `"`.
    """
    folds: dict[int, str] = {0x60: "'", 0xB4: "'"}  # grave and acute accents, typed as apostrophes
    for code in range(0x110000):
        name = unicodedata.name(chr(code), "")
        if not name:
            continue
        if unicodedata.category(chr(code)) in {"Ll", "Lu", "Lt", "Lo"}:
            continue  # a letter that merely contains an apostrophe (U+0149) is not a mark
        words = name.split()
        if "APOSTROPHE" in name or ("SINGLE" in words and "QUOTATION" in words):
            folds[code] = "'"
        elif "QUOTATION" in words and "MARK" in words:
            folds[code] = '"'
        elif "PRIME" in words and not {"DOUBLE", "TRIPLE", "QUADRUPLE", "REVERSED"} & set(words):
            folds[code] = "'"
    return folds


# `Default_Ignorable_Code_Point`, Unicode 15.0 DerivedCoreProperties.txt: the
# closed set the standard names as "renders as nothing". `unicodedata` has no
# accessor for it, so the ranges are vendored (inclusive). It is not a subset of
# `Cf` (variation selectors and the Hangul fillers are `Mn` and `Lo`), and `Cf`
# is not a subset of it (U+0600 ARABIC NUMBER SIGN is visible), so the rule uses
# the union: anything either definition says may vanish.
_DEFAULT_IGNORABLE: tuple[tuple[int, int], ...] = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)


def is_invisible(ch: str) -> bool:
    """Whether `ch` may render as nothing: `Default_Ignorable_Code_Point` or `Cf`."""
    code = ord(ch)
    return unicodedata.category(ch) == "Cf" or any(
        lo <= code <= hi for lo, hi in _DEFAULT_IGNORABLE
    )


def contains_invisible(text: str) -> bool:
    """Whether `text` holds an invisible character, raw or once NFKC has folded it."""
    return any(is_invisible(ch) for ch in text) or any(
        is_invisible(ch) for ch in unicodedata.normalize("NFKC", text)
    )


def _view(text: str) -> str:
    """The form of `text` a rule is matched against: NFKC, quotes folded, spaces collapsed."""
    # Fold before NFKC as well as after: NFKC turns U+00B4 into a space plus a
    # combining accent, which would leave nothing for the second fold to see.
    folded = unicodedata.normalize("NFKC", text.translate(_quote_folds())).translate(_quote_folds())
    return re.sub(r"\s+", " ", folded)


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


class VoiceUnreadable(Strict):
    """A stored correction in the preferences step that is not in voice-preference form."""

    row_id: str = Field(min_length=1)
    text: str


def unreadable_preferences(log: EvidenceLog) -> tuple[VoiceUnreadable, ...]:
    """Live rows under the preferences step, other than `reaction`, that did not decode.

    The discriminator is stated rather than inferred: step 6 records its forced
    choices as `reaction` rows, and nothing else belongs in this step but a
    correction in the candidate's own words, which may have been backfilled as
    any kind (a `constraint` is as plausible as a `statement`). One that is not
    in voice-preference form is one nothing applies. A retracted row is not live
    and is not listed, which is how a candidate dismisses one.
    """
    return tuple(
        VoiceUnreadable(row_id=row.id, text=row.text)
        for row in log.effective_rows()
        if row.step == VOICE_STEP and row.kind != "reaction" and decode_preference(row) is None
    )


def violations(text: str, preferences: Iterable[VoicePreference]) -> list[VoicePreference]:
    """Which preferences `text` breaks. Advisory preferences never appear.

    A line holding an invisible character breaks **every** enforceable
    preference. Hiding a phrase takes a per-character choice (delete this one
    inside a word, make that one a space between words), and no fixed set of
    views covers every mix, so rather than guess which reading the candidate
    would give it the line is not trusted. Fail-closed by construction: the
    cost is a withheld entry, recorded as an omission, not a phrase let through.
    """
    invisible = contains_invisible(text)
    view = _view(text)
    return [
        pref
        for pref in preferences
        if pref.forbid
        and (invisible or any(_compile(pattern).search(view) for pattern in pref.forbid))
    ]


def applied(preferences: Iterable[VoicePreference]) -> tuple[VoiceApplied, ...]:
    return tuple(
        VoiceApplied(row_id=p.row_id, statement=p.statement, enforced=p.enforced)
        for p in preferences
    )


_EXCERPT = 100


def notice(
    preferences: Sequence[VoiceApplied | VoicePreference],
    unreadable: Sequence[VoiceUnreadable] = (),
) -> str:
    """What the candidate sees with every package: counts, then every row by name.

    `N stored, M applied, K unreadable` — stored is the sum, so a correction the
    candidate gave can never be missing from the count. Each unreadable row is
    listed with its id so it can be re-recorded or retracted.
    """
    head = (
        f"{len(preferences) + len(unreadable)} stored, "
        f"{len(preferences)} applied, {len(unreadable)} unreadable"
    )
    lines = [
        f"  - applied: {p.statement}" + ("" if p.enforced else " (advisory, not checked)")
        for p in preferences
    ]
    lines += [
        f"  - unreadable {u.row_id}, not applied: {u.text[:_EXCERPT]!r} "
        "(re-record it with `python -m integral.voice record`, or retract it)"
        for u in unreadable
    ]
    return "\n".join([head + ":", *lines]) if lines else head


# ---------------------------------------------------------------------------
# the gate


def _fixture_master(drafts: Sequence[str], log: EvidenceLog) -> Any:
    from integral.cv_store import ConversationTurn, CVMaster, Experience

    # Lettered, never numbered: a digit in a title is a count (T146), and a count with no
    # source is withheld, which this gate would then read as a voice defect.
    def tag(i: int) -> str:
        return "".join(chr(ord("A") + int(d)) for d in str(i))

    def said(text: str) -> tuple[Any, ...]:
        """The candidate's own words for a draft, so a figure in it has a source (T146)."""
        row = log.append(
            recorded_at="2026-01-01T00:00:00Z", step="history", kind="statement", text=text,
            source="conversation",
        )  # fmt: skip
        return (ConversationTurn(evidence_id=row.id),)

    return CVMaster(
        experience=tuple(
            Experience(
                title=f"Role {tag(i)}",
                organisation=f"Org {tag(i)}",
                description=text,
                provenance=said(text),
            )
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
            [seed[2] for seed in enforceable] + [seed[3] for seed in enforceable], log
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


def _store_for(handle: str, input_dir: str | None, dev: bool) -> ProfileStore:
    """The candidate's store, resolved through the same containment rule as every step."""
    flag = True if dev else None
    root = (
        ensure_outside_a_work_tree(input_dir, source="--input-dir", dev=flag)
        if input_dir
        else profiles_root(dev=flag)
    )
    return ProfileStore(root, handle)


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m integral.voice")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("record", "notice"):
        command = sub.add_parser(name)
        command.add_argument("--id", required=True, dest="handle")
        command.add_argument("--input-dir", default=None)
        command.add_argument("--dev", action="store_true")
        if name == "record":
            command.add_argument("--statement", required=True)
            command.add_argument("--forbid", action="append", default=[])
            command.add_argument("--at", default=None, help="ISO date; default today")
    args = parser.parse_args(argv)
    try:
        store = _store_for(args.handle, args.input_dir, args.dev)
        store.identity()  # a handle nobody identified is refused before anything is written
        log = EvidenceLog(store)
        if args.command == "record":
            at = args.at or datetime.date.today().isoformat()
            pref = record(log, args.statement, args.forbid, at=at)
            print(json.dumps({"recorded": pref.row_id, "enforced": pref.enforced}))
        print(notice(applied(stored_preferences(log)), unreadable_preferences(log)))
    except (VoiceError, StateHomeRefused, IdentityError, ProfileError) as exc:
        print(f"voice: {exc}", file=sys.stderr)
        return 2
    return 0


def _main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] in ("record", "notice"):
        return _cli(argv[1:])
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
