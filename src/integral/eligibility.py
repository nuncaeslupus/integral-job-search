"""T76 — the eligibility gate: refuse to score an offer the candidate is barred from.

Every hard constraint this tool holds today filters on what the **candidate**
declared (`stated_constraints.py`, `constraints_step.py`). Nothing filters on
what the **advert demands**. So a beautifully ranked list can lead with a role
requiring a work permit, a citizenship or a security clearance the candidate
does not have — useless in the first reply
(`status/spec-v3-silent-success.md` §2).

This module is the hard filter that runs **before** the Pareto frontier
(`rank.py`). Three verdicts, spec §5.4:

- **FAIL** — a stated, role-level bar the candidate cannot meet. Excluded, not
  ranked.
- **FLAG** — stated but ambiguous, or the candidate's status is unclear.
  Ranked, marked, and the human is the tiebreaker.
- **PASS** — nothing stated (or something stated, and the candidate's own
  declared status shows they clear it).

Two rules govern what counts as *stated*, both load-bearing:

- **Silence is not permission.** An advert that says nothing about permits has
  said nothing — not "anyone may apply".
- **A company-wide "we welcome international applicants" is not role-level
  permission.** Spec §5.1's `applies_to` field exists for exactly this: a
  blanket diversity statement never overrides, and never substitutes for, a
  role-level bar found anywhere else in the same advert. `find_requirements`
  never treats boilerplate matched by `COMPANY_WIDE_WELCOME_RE` as a
  requirement of any kind — it grants nothing and cancels nothing.

**Prefer FLAG over a silent PASS, and prefer FLAG over a confident FAIL** — the
single most important constraint here. A false FAIL is invisible: an excluded
job is one the candidate never sees, so this module defaults to FLAG for
anything short of an explicit, role-level, stated bar. Concretely: soft
language ("preferred", "a plus", "may require"), a bar whose target this
module cannot extract *and* whose candidate status is anything but a stated
empty set, and a bar whose kind the candidate has never stated anything about
all resolve to FLAG, never FAIL.

**This gate is not accuracy-tested (D-23).** There are no corpus labels for
permit, citizenship or clearance language, so `measure()` below exercises the
*mechanism* — hand-built adversarial fixtures — never real adverts. Nothing
here, or in its evidence, claims accuracy on real-world text.

Adapted from `MadsLorentzen/ai-job-search` (MIT). Attribution lives in
`README.md` and `docs/METHODS.md` — T83's file, not this one.

Never reads `weights.json` or any `dimensions/*` score (spec §5.3's boundary —
that is `rank.py`/`scoring.py`'s side; T78 tests the boundary directly).
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from integral.offers import Offer

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T76.json"

Verdict = Literal["FAIL", "FLAG", "PASS"]
RequirementKind = Literal["citizenship", "work_permit", "clearance"]

_VERDICT_RANK: dict[Verdict, int] = {"PASS": 0, "FLAG": 1, "FAIL": 2}


@dataclass(frozen=True)
class CandidateEligibility:
    """What the candidate has stated about citizenship, work authorisation and
    clearances — nothing here is this module's own read of the advert, all of
    it is what the candidate themselves told the tool.

    Each field is `None` when the candidate has never stated anything for that
    kind — deliberately distinct from an empty tuple, which means the
    candidate stated they hold *none*. Collapsing the two would turn "nobody
    asked" into "the candidate has none of it", which is exactly the kind of
    invented fact this tool's constraint fields (`candidate.py`) refuse to
    hold. `None` is what keeps a stated hard bar at FLAG rather than a
    confident FAIL when the candidate's status is simply unknown.
    """

    citizenships: tuple[str, ...] | None = None
    work_authorisations: tuple[str, ...] | None = None
    clearances: tuple[str, ...] | None = None


#: The candidate has stated nothing at all. Every hard bar against this
#: profile resolves to FLAG ("the candidate's status is unclear"), never FAIL —
#: there is nothing here to fail them against.
UNKNOWN_CANDIDATE = CandidateEligibility()

_CANDIDATE_FIELD: dict[
    RequirementKind, Callable[[CandidateEligibility], tuple[str, ...] | None]
] = {
    "citizenship": lambda c: c.citizenships,
    "work_permit": lambda c: c.work_authorisations,
    "clearance": lambda c: c.clearances,
}


@dataclass(frozen=True)
class Requirement:
    """One eligibility statement `eligibility.py` found in an advert's text.

    `quote` is a verbatim slice of the advert `text` it was matched against —
    never paraphrased, on the same terms spec §5.1 states for the stored
    field: "nothing sourced outside the advert may appear here." `target` is
    the specific thing named (a country, a clearance level) when the pattern
    could extract one; `None` means the bar names nothing specific ("no
    sponsorship is available", naming no country) and is scored against
    whether the candidate holds *anything at all* of this kind — see
    `_verdict_for_requirement`. `ambiguous` is set only by soft language
    ("preferred", "a plus") — a generic, targetless *hard* bar is not
    ambiguous in this sense; it is simply less specific.
    """

    kind: RequirementKind
    quote: str
    target: str | None
    ambiguous: bool


@dataclass(frozen=True)
class Reading:
    """T76's verdict for one offer, and the single requirement that drove it.

    Spec §5.1 stores at most one `(verdict, reason, quote)` triple per offer —
    not a list — so when more than one requirement is found, the worst verdict
    wins (FAIL over FLAG over PASS) and `reason`/`quote` report the
    requirement that produced it. `requirements` keeps every requirement
    found, for auditability and for T77's follow-on quote assertions.
    """

    offer_id: str
    verdict: Verdict
    reason: RequirementKind | None
    quote: str | None
    requirements: tuple[Requirement, ...]


# ---------------------------------------------------------------------------
# text scanning

# A bar phrased as its own negation ("you do not need to hold X citizenship",
# "no need for a clearance") is good news, not a bar. Checked immediately
# before a match; without it, a naive keyword scan reads exactly the opposite
# of what the advert says.
_NEGATION_RE = re.compile(
    r"\b(?:do(?:es)?\s+not|don't|doesn't|no\s+need\s+for|not\s+necessar(?:y|ily)|"
    r"without\s+needing|need\s+not|is\s+not\s+(?:a\s+)?requirement)\b",
    re.IGNORECASE,
)

# Soft language turns an otherwise hard-looking bar into an ambiguous one:
# "clearance is a plus" is not "clearance required". Stated but ambiguous per
# the spec, so this resolves to FLAG rather than FAIL regardless of what the
# candidate has stated.
_SOFT_RE = re.compile(
    r"\b(?:preferred|nice[\s-]to[\s-]have|a\s+plus|ideally|may\s+require|"
    r"where\s+applicable|in\s+some\s+cases|some\s+roles|desirable|advantageous|"
    r"bonus|not\s+essential|willingness\s+to\s+obtain)\b",
    re.IGNORECASE,
)

# A company-wide welcome is never role-level permission (spec §5.1's
# `applies_to`). Recognised so a naive scan of "international" or
# "nationality" cannot mistake it for a stated permission — `find_requirements`
# never turns a match here into a `Requirement` of any kind, so it can neither
# grant anything nor cancel a bar found elsewhere in the same advert.
COMPANY_WIDE_WELCOME_RE = re.compile(
    r"\bwe\s+welcome\s+(?:international\s+)?applicants\b|"
    r"\bwelcome\s+applications?\s+from\s+(?:all\s+backgrounds|candidates?\s+of\s+all)\b|"
    r"\bequal\s+opportunit(?:y|ies)\s+employer\b|"
    r"\bregardless\s+of\s+nationality\b|"
    r"\bapplicants?\s+of\s+all\s+nationalities\b",
    re.IGNORECASE,
)


def is_company_wide_statement(text: str) -> bool:
    """Does `text` carry the boilerplate spec §5.1 names by example — "we
    welcome international applicants" and its siblings?

    Exposed as its own function (rather than folded silently into the scan)
    so a caller — and `test_a_company_wide_statement_is_not_role_level_permission`
    — can confirm the boilerplate was *recognised*, not merely absent from
    what `find_requirements` happened to match. Recognising it is what proves
    the gate could have been fooled by it and was not, rather than the gate
    simply never looking.
    """
    return bool(COMPANY_WIDE_WELCOME_RE.search(text))


# `target` is the phrase naming what is required — a country, a nationality, a
# clearance level (`TS/SCI`, hence digits/`/`/`-` in the character class). The
# repeat group is reluctant (`{0,3}?`): tried at its shortest first, so a
# trailing optional clause ("... in the EU without sponsorship") is not
# swallowed into the target itself. This gate is not a geography or
# clearance-taxonomy parser — see the module docstring on accuracy.
_TARGET = r"(?P<target>[A-Za-z0-9][A-Za-z0-9./-]*(?:\s+[A-Za-z0-9][A-Za-z0-9./-]*){0,3}?)"

_CITIZENSHIP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"\b(?:must|needs?\s+to)\s+(?:be|hold|possess)\s+(?:a\s+|an\s+)?{_TARGET}\s+citizen(?:ship)?\b",
        re.I,
    ),
    re.compile(rf"\b{_TARGET}\s+citizenship\s+(?:is\s+)?required\b", re.I),
    re.compile(rf"\b{_TARGET}\s+citizens?\s+only\b", re.I),
    # Soft: a target is still named, but the wording is a preference, not a
    # bar — `ambiguous` (via `_SOFT_RE`) is what routes this to FLAG.
    re.compile(
        rf"\b{_TARGET}\s+citizenship\s+(?:is\s+)?(?:preferred|desirable|a\s+plus|advantageous)\b",
        re.I,
    ),
    # No target group: "citizenship is required" alone names no country, so it
    # is scored against whether the candidate has stated *any* citizenship at
    # all — see `_verdict_for_requirement`.
    re.compile(r"\bcitizenship\s+(?:is\s+)?required\b", re.I),
)

_WORK_PERMIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"\bmust\s+(?:already\s+)?(?:have|hold)\s+(?:the\s+)?(?:legal\s+)?right\s+to\s+work\s+in\s+"
        rf"(?:the\s+)?{_TARGET}\b",
        re.I,
    ),
    re.compile(
        rf"\bmust\s+be\s+(?:already\s+)?(?:authoris|authoriz)ed\s+to\s+work\s+in\s+(?:the\s+)?{_TARGET}\b"
        r"(?:\s+without\s+sponsorship)?",
        re.I,
    ),
    re.compile(
        rf"\bmust\s+(?:hold|have)\s+a\s+valid\s+work\s+permit\s+for\s+(?:the\s+)?{_TARGET}\b", re.I
    ),
    # Soft, no target: a preference, not a bar.
    re.compile(
        r"\b(?:existing\s+)?(?:work\s+permit|right\s+to\s+work|visa\s+sponsorship)\s+"
        r"(?:is\s+)?(?:preferred|desirable|a\s+plus|not\s+essential|advantageous)\b",
        re.I,
    ),
    # No target: these name a blanket policy, not a country, so they are
    # scored against whether the candidate has stated *any* authorisation at
    # all — see `_verdict_for_requirement`.
    re.compile(
        r"\bwe\s+(?:are\s+)?(?:unable|not\s+able)\s+to\s+(?:offer|provide)\s+sponsorship\b", re.I
    ),
    re.compile(
        r"\bno\s+(?:visa\s+)?sponsorship\s+(?:is\s+)?(?:available|offered|provided)\b", re.I
    ),
    re.compile(r"\bwill\s+not\s+sponsor\b", re.I),
    re.compile(r"\bsponsorship\s+is\s+not\s+(?:available|offered|provided)\b", re.I),
)

_CLEARANCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"\bmust\s+(?:hold|possess)\s+(?:an?\s+)?(?:active\s+)?{_TARGET}\s+clearance\b", re.I
    ),
    # Soft, with a target: a preference, not a bar.
    re.compile(
        rf"\b(?:an?\s+)?(?:active\s+)?{_TARGET}\s+clearance\s+(?:is\s+)?"
        r"(?:a\s+plus|preferred|desirable|advantageous|nice\s+to\s+have)\b",
        re.I,
    ),
    # No target: names no specific level, scored against whether the
    # candidate has stated holding *any* clearance at all.
    re.compile(r"\b(?:active\s+)?security\s+clearance\s+(?:is\s+)?required\b", re.I),
)

_PATTERNS_BY_KIND: tuple[tuple[RequirementKind, tuple[re.Pattern[str], ...]], ...] = (
    ("citizenship", _CITIZENSHIP_PATTERNS),
    ("work_permit", _WORK_PERMIT_PATTERNS),
    ("clearance", _CLEARANCE_PATTERNS),
)


def _normalize(value: str) -> str:
    """Fold a target phrase to a bare comparison key: lowercase, punctuation
    and whitespace collapsed. This gate compares matched text against what a
    candidate stated in the same vocabulary — it is not a geography or
    clearance-taxonomy database, see the module docstring."""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _scan(
    text: str, kind: RequirementKind, patterns: tuple[re.Pattern[str], ...]
) -> list[Requirement]:
    """Every requirement of `kind` found in `text`. A negated match is
    dropped entirely (it is not a bar, ambiguous or otherwise); everything
    else becomes a `Requirement`, never a silently dropped match, since a
    dropped match cannot be reasoned about or shown to a reviewer."""
    found: list[Requirement] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            preceding = text[max(0, match.start() - 30) : match.start()]
            if _NEGATION_RE.search(preceding):
                continue
            window_start = max(0, match.start() - 40)
            window = text[window_start : match.end() + 20]
            target: str | None = None
            if "target" in pattern.groupindex:
                raw = match.group("target")
                target = _normalize(raw) if raw else None
            ambiguous = bool(_SOFT_RE.search(window))
            found.append(
                Requirement(
                    kind=kind,
                    quote=match.group(0).strip(),
                    target=target,
                    ambiguous=ambiguous,
                )
            )
    return found


def find_requirements(text: str) -> tuple[Requirement, ...]:
    """Every eligibility requirement `text` states, across all three kinds."""
    found: list[Requirement] = []
    for kind, patterns in _PATTERNS_BY_KIND:
        found.extend(_scan(text, kind, patterns))
    return tuple(found)


def _verdict_for_requirement(
    requirement: Requirement, candidate: CandidateEligibility
) -> tuple[Verdict, RequirementKind, str]:
    """One requirement's verdict against what the candidate has stated.

    Soft language is FLAG regardless of the candidate — there is nothing
    concrete enough to check a stated fact against. Otherwise: the
    candidate's status for this `kind` is `None` (never stated) → FLAG,
    "status unclear" — never a confident FAIL over an absence of
    information. A requirement with no extractable `target` (a blanket "no
    sponsorship" or "citizenship is required" naming no country) is scored
    against whether the candidate has stated holding *anything at all* of
    this kind: holding nothing stated (an explicit empty tuple) still fails a
    bar that needs *something*, whatever it is; holding something leaves it
    genuinely unknowable whether it satisfies an unnamed target, so it stays
    FLAG rather than a guessed PASS or FAIL. With a target, the comparison is
    direct.
    """
    if requirement.ambiguous:
        return "FLAG", requirement.kind, requirement.quote
    held = _CANDIDATE_FIELD[requirement.kind](candidate)
    if held is None:
        return "FLAG", requirement.kind, requirement.quote
    if requirement.target is None:
        if not held:
            return "FAIL", requirement.kind, requirement.quote
        return "FLAG", requirement.kind, requirement.quote
    normalized_held = {_normalize(value) for value in held}
    if requirement.target in normalized_held:
        return "PASS", requirement.kind, requirement.quote
    return "FAIL", requirement.kind, requirement.quote


def evaluate_text(
    offer_id: str, text: str, candidate: CandidateEligibility = UNKNOWN_CANDIDATE
) -> Reading:
    """T76's verdict for one advert's text. `offer_id` is carried through
    untouched — this function takes raw text so tests can probe it without
    constructing a full `Offer`."""
    requirements = find_requirements(text)
    if not requirements:
        return Reading(offer_id=offer_id, verdict="PASS", reason=None, quote=None, requirements=())

    worst_verdict: Verdict = "PASS"
    worst_reason: RequirementKind | None = None
    worst_quote: str | None = None
    for requirement in requirements:
        verdict, reason, quote = _verdict_for_requirement(requirement, candidate)
        if _VERDICT_RANK[verdict] > _VERDICT_RANK[worst_verdict]:
            worst_verdict, worst_reason, worst_quote = verdict, reason, quote
    if worst_verdict == "PASS":
        worst_reason = None
        worst_quote = None
    return Reading(
        offer_id=offer_id,
        verdict=worst_verdict,
        reason=worst_reason,
        quote=worst_quote,
        requirements=requirements,
    )


def evaluate_offer(offer: Offer, candidate: CandidateEligibility = UNKNOWN_CANDIDATE) -> Reading:
    """`evaluate_text`, wired to a real `Offer` — the verbatim `text` §5.2
    guarantees every connector emits, so this is what every real caller uses."""
    return evaluate_text(offer.id, offer.text, candidate)


def filter_eligible(
    offers: list[Offer], candidate: CandidateEligibility = UNKNOWN_CANDIDATE
) -> tuple[list[Offer], list[Reading]]:
    """The hard filter itself: every offer paired with its reading, and the
    subset that may reach the Pareto frontier — everything except a FAIL.

    A FLAG offer is **kept**, not excluded: spec §5.4, "ranked, marked, and
    the human is the tiebreaker." Only FAIL removes an offer from what
    `rank.py` ever sees.
    """
    readings = [evaluate_offer(offer, candidate) for offer in offers]
    ranked = [
        offer for offer, reading in zip(offers, readings, strict=True) if reading.verdict != "FAIL"
    ]
    return ranked, readings


# ---------------------------------------------------------------------------
# the gate — measures the mechanism over fixtures, never accuracy (D-23)


@dataclass(frozen=True)
class Probe:
    """One hand-built adversarial case: an advert's text, what the candidate
    has stated, and the verdict a correct implementation must reach.

    `is_disqualification` marks a probe as one where the gate's job is to
    refuse the offer outright — an explicit, role-level bar the stated
    candidate cannot meet. Those are the denominator and numerator of
    `offers_ranked_despite_a_stated_disqualification`: every other probe
    (silence, ambiguity, a bar the candidate clears, a false-FAIL trap) is
    also asserted directly by the unit tests, but is not counted toward this
    specific metric, since it does not describe a stated disqualification.
    """

    name: str
    text: str
    candidate: CandidateEligibility
    expected: Verdict
    is_disqualification: bool = False


PROBES: tuple[Probe, ...] = (
    Probe(
        name="stated-citizenship-bar-candidate-fails-it",
        text="Applicants must hold German citizenship at the time of application.",
        candidate=CandidateEligibility(citizenships=("ES",)),
        expected="FAIL",
        is_disqualification=True,
    ),
    Probe(
        name="stated-clearance-bar-candidate-has-none",
        text="Candidates must hold an active TS/SCI clearance before starting.",
        candidate=CandidateEligibility(clearances=()),
        expected="FAIL",
        is_disqualification=True,
    ),
    Probe(
        name="company-wide-welcome-does-not-cancel-a-bar",
        text=(
            "No visa sponsorship is available for this position. "
            "We are proud to be an equal opportunities employer and welcome "
            "applications from candidates of all backgrounds and nationalities."
        ),
        candidate=CandidateEligibility(work_authorisations=()),
        expected="FAIL",
        is_disqualification=True,
    ),
    Probe(
        name="silence-about-permits",
        text="Backend Engineer wanted. Python, remote, competitive salary.",
        candidate=UNKNOWN_CANDIDATE,
        expected="PASS",
    ),
    Probe(
        name="stated-authorisation-satisfies-the-bar",
        text="Must be authorised to work in the EU without sponsorship.",
        candidate=CandidateEligibility(work_authorisations=("EU",)),
        expected="PASS",
    ),
    Probe(
        name="soft-language-is-not-a-hard-bar",
        text="An active security clearance is a plus, but not required for most roles.",
        candidate=CandidateEligibility(clearances=()),
        expected="FLAG",
    ),
    Probe(
        name="generic-bar-with-no-extractable-target-and-candidate-holds-something",
        text="Citizenship is required for this government contract.",
        candidate=CandidateEligibility(citizenships=("ES",)),
        expected="FLAG",
    ),
    Probe(
        name="hard-bar-candidate-status-unstated",
        text="Must hold an active security clearance.",
        candidate=UNKNOWN_CANDIDATE,
        expected="FLAG",
    ),
    Probe(
        name="negated-requirement-is-not-a-bar",
        text=(
            "You do not need to hold German citizenship to apply for this role "
            "— we provide full visa sponsorship."
        ),
        candidate=UNKNOWN_CANDIDATE,
        expected="PASS",
    ),
    Probe(
        name="company-wide-welcome-alone-is-not-a-stated-permission",
        text=(
            "We welcome international applicants. Equal opportunities employer, "
            "regardless of nationality."
        ),
        candidate=UNKNOWN_CANDIDATE,
        expected="PASS",
    ),
)


def probe() -> list[dict[str, Any]]:
    """Run every `PROBES` case, returning what each produced beside what it
    should have — `measure()`'s only source of truth, since this gate has no
    corpus to run against (D-23)."""
    results = []
    for case in PROBES:
        reading = evaluate_text(case.name, case.text, case.candidate)
        results.append(
            {
                "name": case.name,
                "expected": case.expected,
                "actual": reading.verdict,
                "reason": reading.reason,
                "quote": reading.quote,
                "is_disqualification": case.is_disqualification,
                "match": reading.verdict == case.expected,
            }
        )
    return results


def _unmeasured(reason: str, readings: list[dict[str, Any]]) -> dict[str, Any]:
    """The shape a reading that could not happen takes: `-1`, never `0` — see
    `connector_health.py` for the same rule applied to a different gate."""
    return {
        "offers_ranked_despite_a_stated_disqualification": -1,
        "offers_ranked_despite_a_stated_disqualification_evaluated": 0,
        "probes_run": len(readings),
        "gate_status": "unmeasured",
        "unmeasured_reason": reason,
        "readings": readings,
    }


def measure(readings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """T76's gate reading: `offers_ranked_despite_a_stated_disqualification`.

    `readings=None` (every real caller) draws them from `probe()`; a caller
    may pass its own list to prove the empty-input case cannot pass — see
    `test_the_gate_does_not_pass_on_an_empty_input_set`.

    The denominator is the subset of readings marked `is_disqualification`
    True — an explicit, role-level bar the stated candidate cannot meet. A
    violation is one of those probes whose actual verdict was not FAIL: FLAG
    or PASS both mean the offer would still reach the candidate despite a bar
    it cannot meet, which is exactly the failure this gate exists to catch.

    A zero count over zero disqualification probes is not a pass — see the
    module docstring on the empty-input-set failure — so `gate_status` reads
    `"unmeasured"` whenever that denominator is empty, never a clean `0`.
    """
    if readings is None:
        readings = probe()
    disqualifications = [r for r in readings if r["is_disqualification"]]
    if not disqualifications:
        return _unmeasured(
            "no disqualification probe was run — a zero violation count over "
            "nothing evaluated is not a measurement",
            readings,
        )
    violations = [r for r in disqualifications if r["actual"] != "FAIL"]
    return {
        "offers_ranked_despite_a_stated_disqualification": len(violations),
        "offers_ranked_despite_a_stated_disqualification_evaluated": len(disqualifications),
        "probes_run": len(readings),
        "gate_status": "measured",
        "violations": [
            f"{r['name']}: expected FAIL, got {r['actual']} (quote: {r['quote']!r})"
            for r in violations
        ],
        "readings": readings,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T76.json`. This module owns that
    file outright — nothing else writes it (CA-12: a gate must never name a
    file no module produces)."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.eligibility [path]`.

    The violation count is checked **before** the unmeasured branch: a run
    that found a real, known violation must fail (exit 1), never report
    `unmeasured` — a known bad result outranks "could not be scored yet".
    """
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))

    violations = measured["offers_ranked_despite_a_stated_disqualification"]
    if violations > 0:
        for line in measured.get("violations", []):
            print(line, file=sys.stderr)
        return 1
    if measured["gate_status"] == "unmeasured":
        print(
            f"offers_ranked_despite_a_stated_disqualification: UNMEASURED — "
            f"{measured['unmeasured_reason']}. Not a pass and not a fail.",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
