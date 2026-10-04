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
    "keys or tells it to work in the repo, or is told to work in the repo after its "
    "first response, in which case it is a repo session for the rest of the session. "
    "Default candidate; repo when asked for."
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


def test_rule_sits_under_its_heading_and_gates_the_board_protocol() -> None:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.count(HEADING) == 1
    section = text.split(HEADING, 1)[1].split("\n## ", 1)[0]
    assert RULE in _norm(section)
    assert "board protocol applies only in a repo session" in _norm(section)


def test_step_0_and_test_mode_point_at_the_rule_without_restating_it() -> None:
    for rel in POINTERS:
        text = _norm((ROOT / rel).read_text(encoding="utf-8"))
        assert POINTER in text, rel
        assert "`CLAUDE.md`" in text, rel
        assert "Default candidate" not in text, rel
        assert RULE not in text, rel
