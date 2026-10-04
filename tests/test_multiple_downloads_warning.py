"""T232 — a step that saves several pages through the candidate's browser says so up front.

Chrome asks once whether a site may download multiple files. A capture that
stalls on a prompt the candidate was not told to expect looks like a hang.

The population is derived from the step SKILL files, never listed by hand: any
step whose skill drives the browser to save a page (it builds an `a.download`
link) must mention the multiple-downloads prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "skills"
SAVES_THROUGH_BROWSER = re.compile(r"\.download\s*=")
WARNING = re.compile(r"download\s+multiple\s+files", re.IGNORECASE)


def _step_skills() -> list[Path]:
    return sorted(SKILLS_DIR.glob("step-*/SKILL.md"))


def _capturing_skills() -> list[Path]:
    return [p for p in _step_skills() if SAVES_THROUGH_BROWSER.search(p.read_text("utf-8"))]


def test_population_is_not_empty() -> None:
    assert len(_step_skills()) >= 13
    assert any(p.parent.name == "step-07-sourcing" for p in _capturing_skills())


def test_every_browser_saving_step_warns_about_the_multiple_downloads_prompt() -> None:
    missing = [
        p.parent.name for p in _capturing_skills() if not WARNING.search(p.read_text("utf-8"))
    ]
    assert missing == []
