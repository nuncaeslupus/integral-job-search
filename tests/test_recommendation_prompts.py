"""T209 — the steps recommend instead of listing a menu, and ranking says what is strong.

Half 1 is read from the step skills themselves: every step skill that offers the
candidate a choice (the `OFFERS_A_CHOICE` pattern) must carry a "Lead with the
recommendation" section whose example prompt opens with a recommendation, and the
line that offers the choice must itself say which option is recommended. The set of
skills found is compared to a floor so a pattern that matches nothing cannot pass.

Half 2 runs `integral.profile_standing` over stack fits built by the real
`stack_fit.fit`, so the expected lines are derived from the spec of the buckets
(match -> strength; missing/weak -> widen; averse -> neither), not from the code.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from integral import profile_standing, stack_fit
from integral.stack_fit import Held

SKILLS = Path(__file__).resolve().parents[1] / ".claude" / "skills"
OFFERS_A_CHOICE = re.compile(
    r"offer [Rr]eactions instead|recommend Reactions first|offer the options|"
    r"ask whether that is of interest",
)
SECTION = "## Lead with the recommendation"
MINIMUM_CHOICE_SKILLS = 3  # steps 6, 9 and 11 offered a choice when this landed


def _skills() -> dict[str, str]:
    return {
        p.parent.name: p.read_text(encoding="utf-8") for p in sorted(SKILLS.glob("step-*/SKILL.md"))
    }


def _section(text: str) -> str:
    start = text.find(SECTION)
    if start < 0:
        return ""
    rest = text[start + len(SECTION) :]
    end = re.search(r"^## ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def _prompt_leads_with_a_recommendation(section: str) -> bool:
    block = re.search(r"```text\n\"?(.*?)\"?\n```", section, re.DOTALL)
    return block is not None and block.group(1).lstrip().startswith(
        ("I'd recommend", "I recommend")
    )


def _choice_lines_naming_no_recommendation(text: str) -> list[str]:
    return [
        line
        for line in text.splitlines()
        if OFFERS_A_CHOICE.search(line) and "recommend" not in line.lower()
    ]


def choice_prompts_without_a_recommendation() -> tuple[list[str], int]:
    bad, found = [], 0
    for name, text in _skills().items():
        if not OFFERS_A_CHOICE.search(text):
            continue
        found += 1
        if not _prompt_leads_with_a_recommendation(_section(text)):
            bad.append(f"{name}: no recommending example in {SECTION!r}")
        bad += [f"{name}: {ln.strip()[:60]}" for ln in _choice_lines_naming_no_recommendation(text)]
    return bad, found


def test_every_choice_prompt_leads_with_a_recommendation() -> None:
    bad, found = choice_prompts_without_a_recommendation()
    assert found >= MINIMUM_CHOICE_SKILLS
    assert bad == []


def test_the_check_refuses_a_menu() -> None:
    menu = "- the gap: offer the options honestly, apply anyway or leave\n"
    assert _choice_lines_naming_no_recommendation(menu) == [menu.rstrip("\n")]
    neutral = f'{SECTION}\n\n```text\n"Which would you like?"\n```\n'
    assert not _prompt_leads_with_a_recommendation(_section(neutral))


# ---------------------------------------------------------------------------
# half 2: step 9 says what is working and what would widen the fit


def _fit(title: str, held: dict[str, Held]) -> dict[str, Any]:
    return stack_fit.fit(title, "", held)


HELD = {
    "python": Held("strong", False, "cv:skills[0]"),
    "java": Held("working", True, "row1"),  # known, but averse
    "kubernetes": Held("basic", False, "cv:skills[1]"),  # weak
}


def _stack() -> dict[str, dict[str, Any]]:
    return {
        "a": _fit("Python engineer", HELD),
        "b": _fit("Python and Kubernetes engineer", HELD),
        "c": _fit("Python, Java and Go engineer", HELD),
    }


def test_strengths_and_widen_come_from_the_fits_with_counts() -> None:
    stack = _stack()
    lines = profile_standing.standing(stack, language="en")
    assert lines.strengths == "What is working for you: Python (in 3 of the 3 shown)."
    assert "Kubernetes (in 1 of the 3 shown)" in lines.widen
    assert "Go (in 1 of the 3 shown)" in lines.widen  # not in the CV at all


def test_an_aversion_is_never_something_to_improve() -> None:
    lines = profile_standing.standing(_stack(), language="en")
    assert "Java" not in lines.widen
    assert "Java" not in lines.strengths


def test_no_strength_is_said_as_none_not_invented() -> None:
    stack = {"a": _fit("Go engineer", HELD)}
    lines = profile_standing.standing(stack, language="en")
    assert lines.strengths.startswith("None of the technologies")
    assert "Go (in 1 of the 1 shown)" in lines.widen


def test_adverts_naming_nothing_say_so_on_both_lines() -> None:
    lines = profile_standing.standing({"a": _fit("Office manager", HELD)}, language="en")
    assert lines.strengths == lines.widen
    assert "name no technology" in lines.strengths


def test_both_lines_exist_in_every_catalogue_language() -> None:
    for language in ("en", "es", "ca"):
        lines = profile_standing.standing(_stack(), language=language)
        assert lines.strengths and lines.widen and "{" not in lines.strengths + lines.widen


def test_step_nine_skill_calls_it() -> None:
    text = _skills()["step-09-ranking"]
    assert "from integral.profile_standing import standing" in text
    assert "what would widen the fit" in text.lower()
