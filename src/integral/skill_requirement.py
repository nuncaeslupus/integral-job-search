"""T229 — does this advert *require* a skill, or only mention it?

The candidate said "Nunca he usado Go, así que fuera." A text exclusion on
`golang` matched 128 stored adverts, many listing it as one option among several
(one employer alone: 32), and 299 more say bare `Go`, which no word match can
tell from the verb. So the statement was stored as evidence and applied by hand.

`skill:<technology>` is the facet that answers it, and it asks a different
question from a topic: not "is the word in the advert" but "does the advert
**hold the candidate to it**". Text cannot answer that. Two earlier versions of
this module tried a reader built from headings and cue words, and a second
reader found a new fail-open case in every round — "Required skills", "What
you'll need", "About you", "Backend Developer (Java/Go)", "Python Engineer (Go a
plus)", a "must" bound to another skill. An enumeration of the ways English and
Spanish soften a requirement has no last element, so it was **removed**.

What replaces it is the task's own wording — "read required-versus-optional
skills in extraction (step 8)": the step-8 model reads each advert and records,
per skill it names, a role (`extraction.SkillReading`: `required`, `optional`,
`alternative` or `plus`) beside the advert's own words for it, and
`extraction.OfferExtraction.skills` keeps them. This module only **consumes**
that reading:

* a `skill:<tech>` exclusion holds an advert **only** when its extraction lists
  `<tech>` as `required`;
* an advert with **no extraction yet**, or one stored before the field existed
  (`skills` is `None`), is *pending*: it is shown, and `pending_skill_checks`
  says which exclusions could not be applied to it. It is never held on a guess;
* a reading of `[]` is a finding — the model read the advert and it names no
  skill — and is shown without being pending.

Nothing here decides a hold from the advert's text. The ceiling is the model's
reading, which no test in this repository can measure (`status/evidence/T229.json`
says so as `stored_corpus_status: unmeasured` until a stored corpus carries
readings). What *is* pinned is the consuming path, over the reviewer's 105 cases
read as extractions (`tests/fixtures/skill_requirement/cases.json`).

What the technology *is* comes from `stack_fit.VOCABULARY` (R1-R4), so an
extraction naming `Golang` and an exclusion on `go` agree; a value outside that
vocabulary falls back to a case- and accent-folded comparison of the value and
its recorded terms.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from integral import stack_fit

FACET = "skill"

#: The one role that holds an advert; every other is shown.
REQUIRED = "required"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T229.json"
DEFAULT_CASES_PATH = _REPO_ROOT / "tests" / "fixtures" / "skill_requirement" / "cases.json"

#: The fewest adverts whose extraction lists the skill as required that the
#: fixture may hold before the clean zeros below stop meaning anything. The
#: population is `cases.json`, which this repository does not enumerate, so the
#: margin is stated here: the fixture holds 18 such cases today, a margin of 8, so
#: a handful may be retired before the claim lapses and not the whole side.
#: arsenal-floor-margin: FEWEST_REQUIRING_CASES value=10
FEWEST_REQUIRING_CASES = 10

#: The same floor for the adverts that are not required (alternative, plus,
#: optional, or no reading at all): 115 today, a margin of 65, because the
#: fail-closed twin counts only over this side and a fixture of mostly-required
#: adverts would leave it a clean zero over nothing.
#: arsenal-floor-margin: FEWEST_NOT_REQUIRING_CASES value=50
FEWEST_NOT_REQUIRING_CASES = 50


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


@dataclass(frozen=True)
class Target:
    """The technologies (and any literal words) one exclusion names."""

    technologies: frozenset[str]
    literals: frozenset[str] = frozenset()


def target_of(value: str, terms: Iterable[str] = ()) -> Target:
    """`value` and `terms` as vocabulary technologies where they resolve."""
    technologies: set[str] = set()
    literals: set[str] = set()
    for word in (value, *terms):
        word = word.strip()
        if not word:
            continue
        try:
            technologies.add(stack_fit.resolve_technology(word))
        except stack_fit.StackFitError:
            literals.add(_fold(word))
    return Target(frozenset(technologies), frozenset(literals))


def names(skill: str, target: Target) -> bool:
    """Does the extraction's `skill` name what the exclusion rules out?"""
    try:
        if stack_fit.resolve_technology(skill.strip()) in target.technologies:
            return True
    except stack_fit.StackFitError:
        pass
    return _fold(skill) in target.literals


def required_skills(payload: Any) -> tuple[str, ...] | None:
    """The skills an extraction's JSON lists as `required`; `None` when unread.

    `None` is *pending*: no `skills` key, a `null` one, or anything that is not
    a list of readings. A malformed payload is pending, not required — it is
    shown, never held, on a record nothing could validate.
    """
    if not isinstance(payload, dict):
        return None
    readings = payload.get("skills")
    if not isinstance(readings, list):
        return None
    found: list[str] = []
    for reading in readings:
        if (
            isinstance(reading, dict)
            and reading.get("role") == REQUIRED
            and isinstance(reading.get("skill"), str)
        ):
            found.append(reading["skill"])
    return tuple(found)


def required_skills_in(store: Any, offer_id: str) -> tuple[str, ...] | None:
    """`required_skills` of `extractions/<offer_id>.json`; `None` when absent or unreadable."""
    path = Path(store.path("extractions", f"{offer_id}.json"))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return required_skills(payload)


def holds(required: Sequence[str] | None, target: Target) -> bool:
    """True only when the extraction lists the target as required. Pending never holds."""
    if required is None:
        return False
    return any(names(skill, target) for skill in required)


# ---------------------------------------------------------------------------
# T229's measurement — the consuming path, over the reviewer's cases


def _verdicts(cases: Sequence[dict[str, Any]]) -> dict[str, int]:
    from integral.sourcing_exclusions import Candidate, Exclusion, matches

    exclusion = Exclusion(about="skill:go", stated_at_cycle=1, words="w", terms=("golang",))

    def held(case: dict[str, Any], *, extracted: bool) -> bool:
        readings = case["extracted"] if extracted else None
        skills = None if readings is None else required_skills({"skills": readings})
        return matches(
            Candidate(
                offer_id=str(case["id"]),
                title=case.get("title"),
                text=str(case["text"]),
                required_skills=skills,
            ),
            exclusion,
        )

    requiring = [c for c in cases if c["requires"]]
    not_requiring = [c for c in cases if not c["requires"]]
    return {
        "cases": len(cases),
        "requiring_cases": len(requiring),
        "not_requiring_cases": len(not_requiring),
        # The plan's metric: an advert whose extraction lists the skill as
        # required, let through the exclusion.
        "adverts_requiring_a_ruled_out_skill_presented": sum(
            1 for c in requiring if not held(c, extracted=True)
        ),
        # Its fail-closed twin: an advert whose extraction does not list the
        # skill as required, held anyway.
        "adverts_not_requiring_a_ruled_out_skill_held": sum(
            1 for c in not_requiring if held(c, extracted=True)
        ),
        # Pending must show, whatever the advert says: a hold with no reading
        # is the text decision this module no longer makes.
        "pending_adverts_held": sum(1 for c in cases if held(c, extracted=False)),
    }


def measure(cases_path: Path = DEFAULT_CASES_PATH) -> dict[str, Any]:
    """T229's gate reading. `-1` and `unmeasured` over an empty population, never a clean 0."""
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    verdicts = _verdicts(cases)
    populated = (
        verdicts["requiring_cases"] >= FEWEST_REQUIRING_CASES
        and verdicts["not_requiring_cases"] >= FEWEST_NOT_REQUIRING_CASES
    )
    measured: dict[str, Any] = {
        "status": "measured" if populated else "unmeasured",
        **verdicts,
    }
    if not populated:
        for key in (
            "adverts_requiring_a_ruled_out_skill_presented",
            "adverts_not_requiring_a_ruled_out_skill_held",
            "pending_adverts_held",
        ):
            measured[key] = -1
    # The stored corpus carries no model reading of skills yet, so the metric
    # over it has no population. Said as unmeasured, not as a zero.
    measured["stored_corpus_status"] = "unmeasured"
    measured["stored_corpus_adverts_requiring_a_ruled_out_skill_presented"] = -1
    measured["stored_corpus_note"] = (
        "no stored extraction carries `skills` yet; the model's reading of an "
        "advert is the one thing this repository cannot measure"
    )
    return measured


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """The committed form: the verdicts and the floors, never the fixture's headcount.

    The three headcounts move whenever a case is added; the floors are the claim.
    """
    kept = {
        k: v
        for k, v in measured.items()
        if k not in {"cases", "requiring_cases", "not_requiring_cases"}
    }
    return kept | {
        "requiring_cases_at_least": FEWEST_REQUIRING_CASES,
        "not_requiring_cases_at_least": FEWEST_NOT_REQUIRING_CASES,
    }


def write_evidence(path: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    recorded = record(measure())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return recorded


def _main(argv: list[str]) -> int:
    recorded = write_evidence(Path(argv[1]) if len(argv) > 1 else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(recorded, ensure_ascii=False))
    if recorded["status"] != "measured":
        return 3
    bad = (
        recorded["adverts_requiring_a_ruled_out_skill_presented"]
        or recorded["adverts_not_requiring_a_ruled_out_skill_held"]
        or recorded["pending_adverts_held"]
    )
    return 1 if bad else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
