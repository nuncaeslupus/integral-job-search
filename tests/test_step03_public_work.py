"""T208 — step 3 follows up on public work where step 1 did not get it.

The bullet is pinned whole, as an exact sentence after whitespace normalisation, and
by position (under Protocol, before the Never: list). For a prose instruction any
wording change is a behaviour change, and an enumeration of forbidden phrases has no
last element. Changing the instruction means changing EXPECTED here, on purpose.
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
    bullets = [b for b in re.split(r"\n(?=- )|\n\n", before_never) if "public" in b.lower()]
    bullets = [b for b in bullets if b.startswith("- ") and "episode" in b]
    assert len(bullets) == 1, "exactly one public-projects bullet, outside the Never list"
    return bullets[0]


EXPECTED = (
    "- **Public projects, only where intake did not get them.** Step 1 already asks "
    "each field for its artefacts, public repositories for software and data. Where "
    "intake recorded none for a role in software or data (declined, or never came "
    "up), follow up when they describe that work: ask whether it left public "
    "repositories or other public projects. Record each as "
    '`EvidenceLog.append(kind="episode", source="conversation", …)` with the link '
    "in `text`, `disclosure` left `private`, and `dimensions` set to what the "
    "project evidences; never edit `profile/stories.jsonl`, which is derived. Never "
    'require one; "I don\'t have any" is a full answer.'
)


def _norm(text: str) -> str:
    return " ".join(text.split())


def test_ask_is_pinned_whole_and_sits_under_protocol_not_never() -> None:
    assert "**Never:**" in _protocol()
    assert _norm(_bullet()) == EXPECTED


def test_step1_still_asks_software_and_data_for_repositories() -> None:
    """The deferral names step 1's table, so that row must still exist there."""
    rows = [
        line.split("|")[1].strip()
        for line in STEP1.read_text().splitlines()
        if line.startswith("|") and "public repositories" in line
    ]
    assert rows == ["software and data"]
