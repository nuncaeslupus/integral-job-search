"""T231: the candidate-vs-repo session rule is stated in exactly one place.

Metric: ``session_kind_rule_stated_in_one_place`` is 1 when the rule's sentence
appears in exactly one prose file, that file is CLAUDE.md, and step 0 and the
test-mode skill each point at it without restating it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RULE = (
    "A session is a candidate session unless the conversation opens with `[[…]]` "
    "keys (keys as `integral.test_mode.parse_turn` reads them: outside a paste, since "
    "the paste guard declines `[[…]]` inside a pasted advert or CV, so keys inside a "
    "paste never count, while a short non-paste turn's `[[…]]` does) or tells it to "
    "work in the repo, or "
    "is told to work in the repo after its first response, in which case it is a "
    "repo session for the rest of the session. Default candidate; repo when asked for."
)
# The clauses that give the rule its effect, not only its wording.
OPERATIVE = (
    'Neither the "Automatic session protocol" above nor the "Session-start protocol" of '
    '`claude-arsenal/AGENTS.md` ("At the start of every session") is run in a '
    "candidate session",
    "Decide this before running anything in either protocol above or in `claude-arsenal/AGENTS.md`",
    "The board protocol applies only in a repo session.",
    "A session spawned with a task assigned is a repo session",
)
# Any sentence that classifies a session is the rule restated, in whatever words.
# `[[…]]`, `[[a note]]`, `[[! act]]`; not a TOML table (`[[tool.mypy]]`, no space)
# or shell's `[[ -f x ]]` (leading space).
KEY_MARKER = re.compile(r"\[\[(?:…|!|\S[^\[\]]*\s[^\[\]]*)\]\]")
CLASSIFYING = re.compile(
    r"(?:\b(?:is|becomes?|counts as|makes? it|opens?) an? (?:repo|candidate) session"
    r"|default(?:s| to)? candidate|repo when asked)",
    re.IGNORECASE,
)
HEADING = "## Which kind of session this is"
POINTER = 'section "Which kind of session this is"'
POINTERS = (
    ".claude/skills/step-00-identify/SKILL.md",
    ".claude/skills/test-mode/SKILL.md",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _prose_files() -> list[Path]:
    files = [ROOT / "CLAUDE.md"]
    files += sorted((ROOT / ".claude" / "skills").glob("**/SKILL.md"))
    files += sorted((ROOT / "docs").glob("**/*.md"))
    return [p for p in files if p.is_file()]


def _holders() -> list[str]:
    return [
        str(p.relative_to(ROOT))
        for p in _prose_files()
        if _norm(p.read_text(encoding="utf-8")).count(RULE)
    ]


def test_rule_is_stated_in_exactly_one_file_and_once() -> None:
    assert _holders() == ["CLAUDE.md"]
    claude = _norm((ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
    assert claude.count(RULE) == 1


def test_rule_sits_under_its_heading_and_names_both_protocols() -> None:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.count(HEADING) == 1
    section = _norm(text.split(HEADING, 1)[1].split("\n## ", 1)[0])
    assert RULE in section
    for clause in OPERATIVE:
        assert _norm(clause) in section, clause
    assert section.index(_norm(OPERATIVE[1])) < section.index(RULE)


def test_step_0_and_test_mode_point_at_the_rule_without_restating_it() -> None:
    for rel in POINTERS:
        text = _norm((ROOT / rel).read_text(encoding="utf-8"))
        assert POINTER in text, rel
        assert "`CLAUDE.md`" in text, rel
        assert RULE not in text, rel
        assert not CLASSIFYING.search(text), rel


def test_any_other_prose_that_ties_repo_sessions_to_keys_points_and_never_classifies() -> None:
    for path in _prose_files():
        if path == ROOT / "CLAUDE.md":
            continue
        text = _norm(path.read_text(encoding="utf-8"))
        if KEY_MARKER.search(text) and ("repo" in text.lower() or "candidate" in text.lower()):
            assert POINTER in text, path
        assert not CLASSIFYING.search(text), path
