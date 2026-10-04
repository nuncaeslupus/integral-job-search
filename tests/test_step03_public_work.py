"""T208 — step 3 follows up on public work where step 1 did not get it.

The ask is pinned by its position, polarity, condition and recording instruction,
not by keywords: a negated, inverted, misplaced or mis-recorded bullet must fail.
"""

from __future__ import annotations

import re
from pathlib import Path

STEP3 = Path(".claude/skills/step-03-history/SKILL.md")
STEP1 = Path(".claude/skills/step-01-intake/SKILL.md")


def _protocol() -> str:
    text = STEP3.read_text()
    return text.split("## Protocol", 1)[1].split("\n## ", 1)[0]


def _bullet() -> str:
    """The one Protocol bullet about public projects, from before the Never: list."""
    before_never = _protocol().split("**Never:**", 1)[0]
    bullets = [b for b in re.split(r"\n(?=- )", before_never) if "public" in b.lower()]
    bullets = [b for b in bullets if b.startswith("- ") and "episode" in b]
    assert len(bullets) == 1, "exactly one public-projects bullet, outside the Never list"
    return bullets[0]


def _step1_software_row() -> str:
    """The field label step 1's artefact table uses for repositories, read from step 1."""
    for line in STEP1.read_text().splitlines():
        if line.startswith("|") and "public repositories" in line:
            return line.split("|")[1].strip()
    raise AssertionError("step 1 has no repositories row")


def test_ask_sits_under_protocol_not_never() -> None:
    assert "**Never:**" in _protocol()
    assert _bullet().startswith("- **Public projects")


def test_ask_polarity_condition_and_defers_to_step1() -> None:
    text = _bullet()
    low = text.lower()
    assert "ask whether it left public repositories or other public projects" in low
    for refusal in ("never ask", "do not ask", "don't ask", "skip it", "except", "every"):
        assert refusal not in low, refusal
    # the condition: software/data fields, taken from step 1's own table, only where
    # intake recorded nothing for the role
    assert _step1_software_row() == "software and data"
    assert "in software or data" in low
    assert "where intake recorded none" in low
    assert "follow up when they describe that work" in low


def test_recording_is_an_episode_evidence_row_not_the_derived_file() -> None:
    text = _bullet()
    assert "`episode` evidence row" in text
    assert "`source: conversation`" in text
    assert "the link in `text`" in text
    assert "`disclosure` left `private`" in text
    assert "never by editing `profile/stories.jsonl`, which is derived" in text
    assert "overwrit" not in text.lower()


def test_no_unbacked_step11_claim() -> None:
    assert "step 11" not in _bullet().lower()
