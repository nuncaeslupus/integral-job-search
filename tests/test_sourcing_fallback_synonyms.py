"""T187 - the web-search fallback in step-07-sourcing expands, parallelises, unions, then filters.

The section is located by heading and the test fails if it is missing, so a
removed section cannot pass vacuously.  Each clause is read from the numbered
step that carries it, and there must be exactly four steps in that order:
filtering before the union exists is the defect this task is about.
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / ".claude/skills/step-07-sourcing/SKILL.md"
HEADING = re.compile(r"^### Fallback search\b.*$", re.M)


def _section() -> str:
    text = SKILL.read_text(encoding="utf-8")
    match = HEADING.search(text)
    assert match, "step-07-sourcing has no '### Fallback search' section"
    rest = text[match.end() :]
    end = re.search(r"^#{1,3} ", rest, re.M)
    return rest[: end.start()] if end else rest


def _flat() -> str:
    return " ".join(_section().split())


def _steps() -> list[str]:
    parts = re.split(r"^(?=\d+\. )", _section(), flags=re.M)
    steps = [p for p in parts if re.match(r"\d+\. ", p)]
    assert len(steps) == 4, f"expected 4 numbered steps, found {len(steps)}"
    return steps


def test_step_one_expands_synonyms() -> None:
    assert re.search(r"synonym", _steps()[0], re.I)


def test_step_two_runs_queries_in_parallel() -> None:
    assert "Run the queries in parallel**, one per expanded term, not one after another." in _flat()


def test_expansion_is_done_by_the_session_not_the_candidate() -> None:
    assert "do it yourself rather than asking the candidate for synonyms" in _flat()


def test_step_three_unions_and_dedupes_before_judging() -> None:
    step = " ".join(_steps()[2].split())
    assert "**Union the results** and dedupe by advert before anything is judged." in step


def test_step_four_filters_the_whole_union_after_it_exists() -> None:
    step = _steps()[3]
    assert re.search(r"only then", step, re.I)
    assert "`## Liveness`" in step
    assert (
        "the candidate's eligibility constraints (residence, pay floor, mobility, permits)"
        in " ".join(step.split())
    )
    assert re.search(r"whole union", step, re.I)
    assert re.search(r"never to one query", step, re.I)


def test_disclosure_and_label_apply_to_the_union() -> None:
    sentence = (
        "The disclosure above and the `source: web_search` label apply to every result "
        "in the union."
    )
    assert sentence in _flat()
