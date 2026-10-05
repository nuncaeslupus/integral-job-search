"""T209 — the steps recommend instead of listing a menu, and ranking says what is strong.

Half 1 is a closed rule over the population, not a search for today's nouns: every
`step-*/SKILL.md` either carries a "Lead with the recommendation" section whose example
opens with a recommendation, or is named in `NO_BETTER_OPTION` with the reason no option
is better there. The two sets must cover the glob exactly, so a new step (or a new
phrasing of an offer inside an old one) cannot escape without someone writing down why.
The regex over offer phrasings stays as a cross-check only.

Half 2 runs `integral.profile_standing` over stack fits built by the real
`stack_fit.fit`, so the expected lines are derived from the bucket rules
(match -> strength; missing/weak -> widen; averse, excluded, constrained -> neither).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from integral import profile_standing, stack_fit, strings
from integral.identity import ProfileStore, create_profile
from integral.presentation_audit import unstated_standing
from integral.presentation_log import present
from integral.profile import EvidenceLog
from integral.sourcing_exclusions import Exclusion, record_exclusion
from integral.stack_fit import Held

SKILLS = Path(__file__).resolve().parents[1] / ".claude" / "skills"
SECTION = "## Lead with the recommendation"

#: Steps with no choice where one option is better for the search — each with why.
NO_BETTER_OPTION: dict[str, str] = {
    "step-00-identify": (
        "resolves who the candidate is; the only choice is which profile, theirs to name"
    ),
    "step-01-intake": "captures what the candidate hands over; nothing is offered in its place",
    "step-02-constraints": (
        "records the candidate's own limits; a recommendation would be pressure on them"
    ),
    "step-03-history": "elicits stories one at a time; there is no menu, only the next question",
    "step-05-reactions": (
        "learns preferences from reactions; steering the reaction would corrupt it"
    ),
    "step-08-understanding": "runs extraction unattended; the candidate is offered nothing",
    "step-10-feedback": (
        "captures the candidate's opinion of the list; recommending one would bias it"
    ),
    "step-12-interview-log": (
        "records an interview; the only choice is which half runs, and the date decides"
    ),
}

#: Cross-check only: phrasings that offer a choice. A skill matching one must carry the section.
OFFERS_A_CHOICE = re.compile(
    r"\boffer\b[^.\n]{0,60}\binstead\b|offer the options|ask whether that is of interest|"
    r"offer to run|recommend \w+ first|Two things I can do"
)
#: Offer lines that must themselves name the recommendation (the section's example is not enough).
OFFER_LINE = re.compile(r"\boffer\b[^.\n]{0,60}\binstead\b|offer the options|offer to run")


def _skills() -> dict[str, str]:
    return {
        p.parent.name: p.read_text(encoding="utf-8") for p in sorted(SKILLS.glob("step-*/SKILL.md"))
    }


def _prose(text: str) -> str:
    """Without the runtime-deferral boilerplate every step carries."""
    return "\n".join(ln for ln in text.splitlines() if "step_runtime.offered" not in ln)


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


def _unclassified_or_unrecommending(skills: dict[str, str], allowed: dict[str, str]) -> list[str]:
    bad = []
    with_section = {n for n, t in skills.items() if SECTION in t}
    for name in sorted(set(skills) - with_section - set(allowed)):
        bad.append(f"{name}: neither carries the section nor is allowlisted")
    for name in sorted(set(allowed) - set(skills)):
        bad.append(f"{name}: allowlisted but not a step skill")
    for name in sorted(set(allowed) & with_section):
        bad.append(f"{name}: allowlisted yet carries the section")
    for name, reason in allowed.items():
        if not reason.strip():
            bad.append(f"{name}: allowlisted with no reason")
    for name in sorted(with_section):
        if not _prompt_leads_with_a_recommendation(_section(skills[name])):
            bad.append(f"{name}: example does not open with a recommendation")
    for name, text in skills.items():
        if OFFERS_A_CHOICE.search(_prose(text)) and name not in with_section:
            bad.append(f"{name}: offers a choice without the section")
        bad += [
            f"{name}: {ln.strip()[:60]}"
            for ln in _prose(text).splitlines()
            if OFFER_LINE.search(ln) and "recommend" not in ln.lower()
        ]
    return bad


def test_every_step_skill_recommends_or_says_why_not() -> None:
    skills = _skills()
    assert len(skills) >= 13
    assert _unclassified_or_unrecommending(skills, NO_BETTER_OPTION) == []


def test_the_sections_are_where_the_choices_are() -> None:
    carried = {n for n, t in _skills().items() if SECTION in t}
    assert {"step-04-traits", "step-06-preferences", "step-07-sourcing"} <= carried
    assert {"step-09-ranking", "step-11-application"} <= carried


def test_the_closed_rule_refuses_an_unlisted_new_step_and_a_menu() -> None:
    skills = {"step-99-new": "# new\n", "step-04-traits": f'{SECTION}\n\n```text\n"Which?"\n```\n'}
    found = _unclassified_or_unrecommending(skills, {})
    assert "step-99-new: neither carries the section nor is allowlisted" in found
    assert "step-04-traits: example does not open with a recommendation" in found
    menu = {"step-98-x": "- offer the options honestly\n"}
    assert any("offer" in f for f in _unclassified_or_unrecommending(menu, {"step-98-x": "r"}))


# ---------------------------------------------------------------------------
# half 2: step 9 says what is working and what would widen the fit


def _fit(title: str, held: dict[str, Held]) -> dict[str, Any]:
    return stack_fit.fit(title, "", held)


HELD = {
    "python": Held("strong", False, "cv:skills[0]"),
    "java": Held("working", True, "row1"),  # known, but averse
    "kubernetes": Held("basic", False, "cv:skills[1]"),  # weak
    "rust": Held(None, False, "cv:experience[0]"),  # used, level unstated
}


def _stack() -> dict[str, dict[str, Any]]:
    return {
        "a": _fit("Python engineer", HELD),
        "b": _fit("Python and Kubernetes engineer", HELD),
        "c": _fit("Python, Java and Go engineer", HELD),
    }


def test_strengths_and_widen_come_from_the_fits_with_counts() -> None:
    lines = profile_standing.standing(_stack(), ["a", "b", "c"], language="en")
    assert lines.strengths == "What is working for you: Python (in 3 of the 3 shown)."
    assert "Kubernetes (in 1 of the 3 shown)" in lines.widen
    assert "Go (in 1 of the 3 shown)" in lines.widen  # not in the CV at all


def test_the_denominator_is_the_offers_on_the_page_including_those_naming_nothing() -> None:
    stack = {
        "p1": _fit("Python engineer", HELD),
        "p2": _fit("Python engineer", HELD),
        "p3": _fit("Python engineer", HELD),
        "n1": _fit("Office manager", HELD),
        "n2": _fit("Receptionist", HELD),
    }
    lines = profile_standing.standing(stack, list(stack), language="en")
    assert lines.strengths == "What is working for you: Python (in 3 of the 5 shown)."


def test_only_the_page_is_counted_not_the_whole_ranking() -> None:
    stack = {f"o{i}": _fit("Python engineer", HELD) for i in range(40)}
    page = [f"o{i}" for i in range(5)]
    lines = profile_standing.standing(stack, page, language="en")
    assert lines.strengths == "What is working for you: Python (in 5 of the 5 shown)."


def test_a_shown_offer_with_no_fit_still_counts_in_the_denominator() -> None:
    stack = {"a": _fit("Python engineer", HELD)}
    lines = profile_standing.standing(stack, ["a", "b"], language="en")
    assert "Python (in 1 of the 2 shown)" in lines.strengths


def test_an_aversion_stance_is_never_something_to_improve() -> None:
    lines = profile_standing.standing(_stack(), ["a", "b", "c"], language="en")
    assert "Java" not in lines.widen
    assert "Java" not in lines.strengths


def test_used_at_an_unstated_level_is_neither_a_strength_nor_a_gap() -> None:
    stack = {"a": _fit("Rust and Python engineer", HELD)}
    lines = profile_standing.standing(stack, ["a"], language="en")
    assert "Rust" not in lines.strengths
    assert "Rust" not in lines.widen


def test_a_ruled_out_technology_is_never_in_widen() -> None:
    stack = _stack()
    lines = profile_standing.standing(
        stack, ["a", "b", "c"], ruled_out=frozenset({"go"}), language="en"
    )
    assert "Go" not in lines.widen
    assert "Kubernetes" in lines.widen


def _store(tmp_path: Path) -> ProfileStore:
    identity = create_profile(tmp_path, "Standing probe", handle="standing-probe")
    return ProfileStore(tmp_path, identity.handle)


def test_an_exclusion_or_a_constraint_row_reaches_the_ruled_out_set(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record_exclusion(
        store,
        Exclusion(about="skill:go", stated_at_cycle=1, words="Nunca he usado Go, así que fuera"),
    )
    EvidenceLog(store).append(
        recorded_at="2026-10-05T10:00:00Z",
        step="constraints",
        kind="constraint",
        text="no PHP shops",
        source="conversation",
    )
    assert {"go", "php"} <= profile_standing.ruled_out(store)
    lines = profile_standing.standing_for_store(store, _stack(), ["a", "b", "c"], language="en")
    assert "Go" not in lines.widen


def test_nothing_ruled_out_reads_as_the_empty_set(tmp_path: Path) -> None:
    assert profile_standing.ruled_out(_store(tmp_path)) == frozenset()


def test_no_strength_is_said_as_none_not_invented() -> None:
    lines = profile_standing.standing({"a": _fit("Go engineer", HELD)}, ["a"], language="en")
    assert lines.strengths == (
        "None of the technologies the shown adverts name is one your CV or your words "
        "put at working level."
    )
    assert "Go (in 1 of the 1 shown)" in lines.widen


def test_the_widen_line_asks_and_never_assigns() -> None:
    lines = profile_standing.standing(_stack(), ["a", "b", "c"], language="en")
    assert lines.widen.endswith("Is any of that of interest to you?")
    clean = profile_standing.standing({"a": _fit("Python engineer", HELD)}, ["a"], language="en")
    assert "interest" not in clean.widen  # nothing to ask about


def test_a_truncated_list_says_how_many_more() -> None:
    held: dict[str, Held] = {}
    title = "Go Rust Java Kotlin Swift Ruby PHP Scala engineer"
    lines = profile_standing.standing({"a": _fit(title, held)}, ["a"], language="en")
    named = len(_fit(title, held)["spans"])
    assert named > profile_standing.MAX_ITEMS
    assert f"and {named - profile_standing.MAX_ITEMS} more" in lines.widen


def test_adverts_naming_nothing_say_so_on_both_lines() -> None:
    lines = profile_standing.standing({"a": _fit("Office manager", HELD)}, ["a"], language="en")
    assert lines.strengths == lines.widen
    assert "name no technology" in lines.strengths


def test_nothing_assessed_is_not_assessed_not_named_nothing() -> None:
    expected = strings.text(strings.load(), "stack_not_assessed", "en")
    for stack, shown in (({}, ["a"]), (None, ["a"]), (_stack(), [])):
        lines = profile_standing.standing(stack, shown, language="en")
        assert lines.strengths == lines.widen == expected


def test_both_lines_exist_in_every_catalogue_language() -> None:
    for language in ("en", "es", "ca"):
        lines = profile_standing.standing(_stack(), ["a", "b", "c"], language=language)
        assert lines.strengths and lines.widen and "{" not in lines.strengths + lines.widen


def test_step_nine_skill_passes_the_page_and_records_the_lines() -> None:
    text = _skills()["step-09-ranking"]
    assert "standing_for_store(store, stack, show)" in text
    assert "standing=lines" in text


def test_the_checkpoint_reads_whether_the_lines_were_said(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert unstated_standing(store) == []  # nothing presented: unpresented_ranking's finding
    present(store, ["a"], at="2026-10-05T10:00:00Z")
    assert unstated_standing(store)[0]["problem"].startswith("no standing lines")
    lines = profile_standing.standing(_stack(), ["a", "b", "c"], language="en")
    present(store, ["a"], at="2026-10-05T11:00:00Z", standing=lines)
    assert unstated_standing(store) == []
    present(store, ["b"], at="2026-10-05T12:00:00Z")  # a later batch said nothing
    assert unstated_standing(store)
