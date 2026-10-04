"""T208 — step 3 asks portfolio-role candidates for their public work."""

from __future__ import annotations

from pathlib import Path

from integral.corpus import FAMILY_TITLE_RE

SKILL = Path(".claude/skills/step-03-history/SKILL.md")


def _public_work_bullet() -> str:
    bullets = [b for b in SKILL.read_text().split("\n- ") if "GitHub" in b]
    assert len(bullets) == 1, "step 3 must carry exactly one public-work instruction"
    return bullets[0]


def test_step3_asks_for_github_and_public_projects() -> None:
    text = _public_work_bullet().lower()
    assert "github" in text and "public projects" in text
    assert "software" in text and "developer" in text


def test_step3_says_how_the_answer_is_recorded_and_used() -> None:
    text = _public_work_bullet()
    assert "profile/stories.jsonl" in text
    assert "step 11" in text.lower()


def test_step3_skips_every_corpus_family_without_a_public_trail() -> None:
    """Each family the corpus knows is a trail-less one, so each is named as skipped."""
    text = _public_work_bullet()
    skip = text.split("Skip it for", 1)[1].split(".", 1)[0].lower()
    for family in FAMILY_TITLE_RE:
        assert family in skip, family
