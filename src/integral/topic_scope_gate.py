"""T227's gate: a topic exclusion reads the employer and the job, not any sentence.

`adverts_excluded_on_a_perk_or_nice_to_have` counts the fixture adverts that only
*mention* the ruled-out topic (a perk, a requirement, a nice-to-have, posting
boilerplate) and are still held. The fail-open mirror,
`adverts_on_the_topic_shown`, counts the adverts that really are on it and are
shown, so loosening the matcher cannot buy the first number down for free.
`held_without_the_words` counts holds the candidate would be told nothing
specific about.

The cases are `tests/fixtures/topic_scope/cases.json`, each with the reason its
verdict is the one it is, written from the task text and not from what the code
returns. The floors are committed instead of the headcounts, so adding a case
does not move the evidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from integral import sourcing_exclusions as se

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_PATH = _REPO_ROOT / "tests" / "fixtures" / "topic_scope" / "cases.json"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T227.json"

#: A zero over a handful of cases is not a pass. The fixture holds 37 adverts the
#: topic is really on today; the floor is deliberately well below that, so cases
#: may be retired without the claim lapsing, but not the whole side.
#: arsenal-floor-margin: FEWEST_HELD_CASES value=10
FEWEST_HELD_CASES = 10

#: The adverts that only mention the topic: 34 today, well above the floor, because
#: the metric counts only over this side and a fixture of mostly on-topic adverts
#: would leave it a clean zero over nothing.
#: arsenal-floor-margin: FEWEST_SHOWN_CASES value=12
FEWEST_SHOWN_CASES = 12


def _parts(case: dict[str, Any]) -> tuple[se.Candidate, se.Exclusion]:
    candidate = se.Candidate(
        offer_id=case["id"],
        title=case["title"],
        text=case["text"],
        employer=case["employer"],
    )
    exclusion = se.Exclusion(
        about=case["about"],
        stated_at_cycle=1,
        words="fixture",
        terms=tuple(case["terms"]),
    )
    return candidate, exclusion


def measure(cases_path: Path = DEFAULT_CASES_PATH) -> dict[str, Any]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    held_cases = [c for c in cases if c["held"]]
    shown_cases = [c for c in cases if not c["held"]]
    wrongly_held = [c["id"] for c in shown_cases if se.matches(*_parts(c))]
    wrongly_shown = [c["id"] for c in held_cases if not se.matches(*_parts(c))]
    unnamed: list[str] = []
    for c in held_cases:
        candidate, exclusion = _parts(c)
        said = se.held_in_words(candidate, [exclusion])
        # Every held topic case must quote the words that held it.
        if se.matches(candidate, exclusion) and "«" not in "".join(said):
            unnamed.append(c["id"])
    populated = len(held_cases) >= FEWEST_HELD_CASES and len(shown_cases) >= FEWEST_SHOWN_CASES
    measured: dict[str, Any] = {
        "status": "measured" if populated else "unmeasured",
        "adverts_excluded_on_a_perk_or_nice_to_have": len(wrongly_held),
        "adverts_on_the_topic_shown": len(wrongly_shown),
        "held_without_the_words": len(unnamed),
        "held_cases_at_least": FEWEST_HELD_CASES,
        "shown_cases_at_least": FEWEST_SHOWN_CASES,
    }
    if not populated:
        for key in (
            "adverts_excluded_on_a_perk_or_nice_to_have",
            "adverts_on_the_topic_shown",
            "held_without_the_words",
        ):
            measured[key] = -1
    return measured


def write_evidence(path: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    recorded = measure()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return recorded


def _main(argv: list[str]) -> int:
    recorded = write_evidence(Path(argv[1]) if len(argv) > 1 else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(recorded, ensure_ascii=False))
    if recorded["status"] != "measured":
        return 3
    bad = (
        recorded["adverts_excluded_on_a_perk_or_nice_to_have"]
        or recorded["adverts_on_the_topic_shown"]
        or recorded["held_without_the_words"]
    )
    return 1 if bad else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
