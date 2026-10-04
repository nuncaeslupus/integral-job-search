"""T232 — a step that saves several pages through the candidate's browser warns first.

Chrome asks once whether a site may download multiple files. A capture that
stalls on a prompt the candidate was not told to expect looks like a hang, so
the warning belongs in what the step *says to the candidate before capturing*:
the quoted ```text ask block that precedes the first download trigger. A
mention elsewhere (after the capture, or in a sentence that denies the prompt)
does not warn anyone in time.

The population is derived from the step SKILL files, never listed by hand: any
step whose skill triggers a browser download (`.download =` or
`setAttribute('download'`) must carry the warning in a ```text block before
that first trigger.
"""

from __future__ import annotations

import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "skills"
TRIGGER = re.compile(r"""\.download\s*=|setAttribute\(\s*['"]download['"]""")
TEXT_BLOCK = re.compile(r"```text\n(.*?)```", re.DOTALL)
WARNING = re.compile(r"\bmay\s+ask\b[^.:]*\bdownload\s+multiple\s+files\b", re.IGNORECASE)


def _step_skills() -> list[Path]:
    return sorted(SKILLS_DIR.glob("step-*/SKILL.md"))


def _capturing_skills() -> list[Path]:
    return [p for p in _step_skills() if TRIGGER.search(p.read_text("utf-8"))]


def _warned_before_capture(text: str) -> bool:
    trigger = TRIGGER.search(text)
    assert trigger is not None
    for block in TEXT_BLOCK.finditer(text[: trigger.start()]):
        body = " ".join(block.group(1).split())
        if body.startswith('"') and WARNING.search(body):
            return True
    return False


def test_population_is_not_empty() -> None:
    assert len(_step_skills()) >= 13
    assert any(p.parent.name == "step-07-sourcing" for p in _capturing_skills())


def test_every_browser_saving_step_warns_in_its_ask_before_capturing() -> None:
    missing = [
        p.parent.name
        for p in _capturing_skills()
        if not _warned_before_capture(p.read_text("utf-8"))
    ]
    assert missing == []
