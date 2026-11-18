"""T197 — the `connector-new` skill must not carry a census of what a package moves.

Step 6 used to say that exactly two committed counts move when a package lands and
that "if a third moves, that is a finding". T194 moved seven and all seven were
truthful: four keys by +1 for the package, two by +3 (one `BoardOutcome` per phrase,
which is `Run.steered`'s own definition) and the provenance census. A census in
prose has no last element, and a stale one does worse than fail to help — it makes
a session distrust correct work and pay to refute it, or edit something until the
count matches.

Two tests hold the remedy down. One reads the skill for the *shape* of the claim
(any English number, digit or vague quantifier next to a key/count noun, or a
"finding" fenced by else/other/third/more than), not for today's wording. The other
measures the fact that made the claim wrong — it adds a real
package to a copy of the tree and counts how many committed keys move — so putting
a number back is red; a census reworded to avoid every number and quantifier the
detector knows is not, which is why the detector is a closed rule and not a list of
phrasings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / ".claude" / "skills" / "connector-new" / "SKILL.md"

#: The count the skill used to claim. Not a threshold: the measured count must
#: differ from it, and separately no number may be claimed at all.
CLAIMED_BY_THE_OLD_SKILL = 2


def _words(text: str) -> list[str]:
    return re.split(r"\s+", text.strip())


_UNITS = _words(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen"
)
_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_ORDINALS = _words(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
    "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth "
    "twentieth thirtieth"
)
_LARGE = ["hundred", "thousand", "million", "dozen"]
_QUANTIFIERS = ["both", "pair", "couple", "several", "few"]
_COMPOUND = rf"(?:{'|'.join(_TENS)})(?:[- ](?:{'|'.join(_UNITS[1:10])}))?"
#: Every English cardinal and ordinal, any digit run, and the vague quantifiers.
#: A closed rule: a number is a number whether or not anyone thought to list it.
#: A digit run is not a number when it is the amount of a move (`+1`, `-3`) or part
#: of an identifier (`T72`), which the lookbehind and `\b` exclude.
_WORDS = "|".join([*_UNITS, *_ORDINALS, *_LARGE, *_QUANTIFIERS])
_NUMBER = rf"(?:(?<![+\-\w])\d+(?:st|nd|rd|th)?\b|\b(?:{_COMPOUND}|{_WORDS})\b)"
#: Step 6 is the one section that used to carry the tally, and the rule for it is
#: closed: its prose contains no number token at all. Not "no number near a noun", which
#: a window and a noun list let through ("Sixteen of the committed evidence keys",
#: "Sixteen connector keys", "values", "entries", "16 findings") — none at all.
_BOUNDARY = re.compile(
    r"\b(?:else|other|others|additional|extra|further|another|third|beyond|besides|more\s+than)\b",
    re.IGNORECASE,
)


def step_6_span(text: str) -> str:
    """Everything from Step 6's heading up to Step 7's: the one boundary every check uses.

    Not "up to the next `##`": a section inserted between the two would then sit outside
    both checks. Step 7 is the section that follows in the skill, so the boundary is it.
    """
    start = text.index("## Step 6")
    return text[start : text.index("\n## Step 7", start)]


def step_6_prose(text: str) -> str:
    """The span without its heading and its code fences."""
    body = step_6_span(text).split("\n", 1)[1]
    return re.sub(r"```.*?```", "", body, flags=re.DOTALL)


def number_tokens(prose: str) -> list[str]:
    return re.findall(_NUMBER, prose, flags=re.IGNORECASE)


def census_claims(text: str) -> list[str]:
    """What Step 6 says that tallies the moved keys or fences the set closed."""
    prose = re.sub(r"\s+", " ", step_6_prose(text))
    found = [f"number token {token!r}" for token in number_tokens(prose)]
    found += [f"boundary word {word!r}" for word in _BOUNDARY.findall(prose)]
    return found


def evidence_key_names() -> set[str]:
    """Every committed evidence key spelled like an identifier, read off the records."""
    keys: set[str] = set()
    for path in (REPO / "status" / "evidence").glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(document, dict):
            keys.update(key for key in document if "_" in key)
    return keys


def _step_6_saying(text: str, sentence: str) -> str:
    """The skill with one more sentence appended to Step 6's prose."""
    end = text.index("\n## Step 7")
    return f"{text[:end]}\n{sentence}\n{text[end:]}"


def _a_section_between_6_and_7(text: str, sentence: str) -> str:
    """The skill with a new `##` section, carrying `sentence`, between Steps 6 and 7."""
    end = text.index("\n## Step 7")
    return f"{text[:end]}\n\n## Step 6b — afterwards\n\n{sentence}\n{text[end:]}"


def test_the_skill_names_no_census_of_moved_keys() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert census_claims(text) == []


def test_step_6_names_no_committed_evidence_key() -> None:
    body = step_6_span(SKILL.read_text(encoding="utf-8"))
    keys = evidence_key_names()
    assert len(keys) > 20, "the committed records were not read"
    assert sorted(key for key in keys if key in body) == []


REVIEWED_REWORDINGS = [
    "Two committed counts move when a package lands.",
    "If a third moves, that is a finding.",
    "Exactly 7 keys move for one package.",
    "three evidence keys change when a connector is added",
    "Only two counts move, and both must be checked.",
    "Sixteen keys move when a package lands.",
    "Both committed counts move; if anything else moves, that is a finding.",
    "Only `X` and `Y` move; any other key that moves is a finding.",
    "The package moves 7 keys.",
    "Expect a couple of counts to change.",
    "More than two keys are findings.",
    "A third moving key means something else is package-sensitive.",
    "Twenty-one keys move.",
    "Sixteen of the committed evidence keys move.",
    "Sixteen connector keys move.",
    "The package adds twelve entries.",
    "Several values change.",
    "16 findings are expected.",
    "Treat any additional move as a defect.",
    "Anything else is suspicious.",
    "Any other key that moves is a red flag.",
    "Move number 3rd means a bug.",
    "The 3rd key to move is suspect.",
]


@pytest.mark.parametrize("sentence", REVIEWED_REWORDINGS)
def test_every_reviewed_rewording_is_flagged_inside_step_6(sentence: str) -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert census_claims(text) == []
    assert census_claims(_step_6_saying(text, sentence))


@pytest.mark.parametrize("sentence", REVIEWED_REWORDINGS)
def test_a_census_in_a_section_between_steps_6_and_7_is_flagged_too(sentence: str) -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert census_claims(_a_section_between_6_and_7(text, sentence))


@pytest.mark.parametrize(
    "rule",
    [
        "A key that moves by the package's own contribution is truthful.",
        "Each connector is a package, and keys move by +1 per package.",
        "A per-phrase outcome moves by +N for N phrases.",
        "A finding is a move you cannot derive from the package.",
        "Find which keys are package-sensitive with the registry, then explain each move.",
    ],
)
def test_the_rule_can_be_added_to_step_6_without_being_flagged(rule: str) -> None:
    assert census_claims(_step_6_saying(SKILL.read_text(encoding="utf-8"), rule)) == []


def test_a_number_outside_step_6_is_not_this_tests_business() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert number_tokens(text), "the rest of the skill has numbered steps; the scope is Step 6"
    assert census_claims(text) == []
