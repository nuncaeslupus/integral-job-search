"""T210: a long candidate session is told, once, at a step boundary, what compacting keeps.

The rule's text lives in one place (CLAUDE.md, which a candidate session reads);
every step skill's Boundary points at it by heading. The step list is read off
the filesystem so a thirteenth skill is covered without anyone remembering it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADING = "## Suggest compacting once, at a step boundary"
TITLE = HEADING.removeprefix("## ")
POINTER = f'`CLAUDE.md`, section "{TITLE}"'

# One clause per claim, each quoted from the rule so removing it fails its own test.
WHEN = (
    "only at a step boundary, after the step's checkpoint has run and before the next "
    "step opens, and only when the conversation is already long. Never mid-step"
)
ONCE = (
    "suggest it a single time. If the candidate declines or ignores it, never raise it "
    "again in that session."
)
KEPT = (
    "compacting keeps `session/state.json`, the profile and every step's outputs, "
    "because they live on disk and not in the conversation, so resuming after it is safe"
)
CLAUSES = {"when": WHEN, "once": ONCE, "kept": KEPT}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().replace("**", "")


def _rule_section() -> str:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.count(HEADING) == 1, "the compaction rule must have exactly one heading"
    body = text.split(HEADING, 1)[1]
    return _norm(re.split(r"^## ", body, maxsplit=1, flags=re.M)[0])


def _step_skills() -> list[Path]:
    return sorted((ROOT / ".claude" / "skills").glob("step-*/SKILL.md"))


def _boundary(text: str) -> str:
    m = re.search(r"^## Boundary\s*$(.*?)(?=^#{1,6}\s|\Z)", text, re.M | re.S)
    assert m, "no Boundary section"
    return _norm(m.group(1))


def test_step_list_is_derived_and_not_trivially_small() -> None:
    assert len(_step_skills()) >= 13


def test_each_clause_is_in_the_rule() -> None:
    section = _rule_section()
    for name, clause in CLAUSES.items():
        assert _norm(clause) in section, f"rule lacks its {name} clause"


def test_every_step_boundary_reaches_the_rule() -> None:
    for skill in _step_skills():
        boundary = _boundary(skill.read_text(encoding="utf-8"))
        assert POINTER in boundary, f"{skill.parent.name}: Boundary does not point at the rule"


def test_no_step_restates_the_rule() -> None:
    for skill in _step_skills():
        text = _norm(skill.read_text(encoding="utf-8"))
        assert text.count(TITLE) == 1, f"{skill.parent.name}: pointer missing or duplicated"
        for name, clause in CLAUSES.items():
            assert _norm(clause) not in text, f"{skill.parent.name} restates the {name} clause"


def test_rule_is_not_stated_outside_claude_md() -> None:
    files = sorted((ROOT / "docs").glob("**/*.md")) + sorted(
        (ROOT / ".claude" / "skills").glob("**/SKILL.md")
    )
    for f in files:
        text = _norm(f.read_text(encoding="utf-8"))
        for name, clause in CLAUSES.items():
            assert _norm(clause) not in text, f"{f} restates the {name} clause"
