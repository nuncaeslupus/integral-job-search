"""t-c088d832 — step 11 applies from the employer's own careers page, not an aggregator's copy."""

from pathlib import Path

SKILL = Path(".claude/skills/step-11-application/SKILL.md")
RULE = (
    "Before giving the candidate an application link, find the advert on the employer's own "
    "careers site and read it whole there.\n"
    "An aggregator's copy is a pointer, never the advert: its work mode, its open or closed "
    "status and its closing asks can be stale or missing.\n"
    "The link the candidate gets, and the URL the package records, is the employer's own; an "
    "aggregator's is given only when the employer publishes none, and then said so."
)


def test_rule_is_stated_once_verbatim() -> None:
    assert SKILL.read_text().count(RULE) == 1
