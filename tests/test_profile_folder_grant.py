"""The profile folder is granted when the profile resolves (step 0), not at step 11's end."""

from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / ".claude" / "skills"
GRANT = "mcp__ccd_directory__request_directory"


def _text(step: str) -> str:
    return (SKILLS / step / "SKILL.md").read_text(encoding="utf-8")


def test_step_0_grants_the_profile_folder_before_any_link() -> None:
    text = _text("step-00-identify")
    assert GRANT in text
    line = next(ln for ln in text.splitlines() if GRANT in ln)
    assert "once per session" in line
    assert "before any link" in line


def test_step_11_relies_on_the_step_0_grant() -> None:
    line = next(ln for ln in _text("step-11-application").splitlines() if GRANT in ln)
    assert "granted at step 0" in line
    assert "only if this session never passed step 0" in line
