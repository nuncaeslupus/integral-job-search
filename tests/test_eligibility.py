"""T76 — the eligibility gate: a stated, role-level bar the candidate cannot
meet excludes the offer before scoring; a false FAIL is the failure that
matters most here, because an excluded job is one the candidate never sees.

These fixtures are hand-built, not drawn from the corpus (D-23): there are no
labels for permit, citizenship or clearance language, so this suite exercises
the mechanism — the three-verdict shape, the negation and soft-language
handling, the empty-input-set honesty — never accuracy on a real advert.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral import eligibility
from integral.eligibility import UNKNOWN_CANDIDATE, CandidateEligibility
from integral.offers import connect_manual


def test_a_stated_citizenship_requirement_excludes_the_offer() -> None:
    """An explicit, role-level citizenship bar the candidate does not meet is
    the clearest case this gate exists for: FAIL, not ranked."""
    reading = eligibility.evaluate_text(
        "off-1",
        "Applicants must hold German citizenship at the time of application.",
        CandidateEligibility(citizenships=("ES",)),
    )

    assert reading.verdict == "FAIL"
    assert reading.reason == "citizenship"
    assert reading.quote is not None
    assert reading.quote in "Applicants must hold German citizenship at the time of application."


def test_silence_about_permits_is_not_a_disqualification() -> None:
    """An advert that says nothing about permits has said nothing — not
    'anyone may apply'. Silence must read as PASS, never as an invented
    permission and never as an invented bar."""
    reading = eligibility.evaluate_text(
        "off-2",
        "Backend Engineer wanted. Python, remote, competitive salary.",
        UNKNOWN_CANDIDATE,
    )

    assert reading.verdict == "PASS"
    assert reading.reason is None
    assert reading.quote is None
    assert reading.requirements == ()


def test_a_company_wide_statement_is_not_role_level_permission() -> None:
    """A blanket 'we welcome applicants of all nationalities' sitting right
    beside a real bar must not cancel it. A naive implementation that treats
    any mention of nationality/international as a granted permission would
    read this as PASS; the correct verdict is still FAIL."""
    text = (
        "No visa sponsorship is available for this position. "
        "We are proud to be an equal opportunities employer and welcome "
        "applications from candidates of all backgrounds and nationalities."
    )
    assert eligibility.is_company_wide_statement(text), (
        "the boilerplate must be recognised, not merely fail to match anything"
    )

    reading = eligibility.evaluate_text("off-3", text, CandidateEligibility(work_authorisations=()))

    assert reading.verdict == "FAIL"
    assert reading.reason == "work_permit"


def test_a_company_wide_welcome_with_nothing_else_stated_is_still_pass() -> None:
    """The welcome boilerplate on its own — no bar anywhere else in the
    advert — must not itself read as a stated requirement of any kind. A scan
    that treats 'nationality' or 'international' as bar-shaped text would
    wrongly FLAG or FAIL this."""
    text = (
        "We welcome international applicants. Equal opportunities employer, "
        "regardless of nationality."
    )

    assert eligibility.is_company_wide_statement(text)
    reading = eligibility.evaluate_text("off-4", text, UNKNOWN_CANDIDATE)

    assert reading.verdict == "PASS"
    assert reading.requirements == ()


def test_the_gate_does_not_pass_on_an_empty_input_set() -> None:
    """A zero-violation count over zero disqualification probes evaluated is
    not a pass — it is what a check that ran over nothing also reports."""
    measured = eligibility.measure(readings=[])

    assert measured["gate_status"] == "unmeasured"
    assert measured["offers_ranked_despite_a_stated_disqualification_evaluated"] == 0
    assert measured["offers_ranked_despite_a_stated_disqualification"] == -1


def test_the_real_probe_set_has_a_non_zero_disqualification_denominator() -> None:
    """The task's own gate: over the module's built-in adversarial fixtures,
    `..._evaluated` must be written and non-zero, and the violation count
    must be zero — the mechanism this increment is about, measured."""
    measured = eligibility.measure()

    assert measured["gate_status"] == "measured"
    assert measured["offers_ranked_despite_a_stated_disqualification_evaluated"] > 0
    assert measured["offers_ranked_despite_a_stated_disqualification"] == 0


def test_a_stated_authorisation_that_satisfies_the_bar_is_not_a_false_fail() -> None:
    """The other direction of the citizenship test above: a role-level bar IS
    stated, and the candidate's own declared status shows they clear it. A
    naive implementation that FAILs on any matched bar keyword — regardless of
    whether the candidate meets it — would wrongly exclude this offer."""
    reading = eligibility.evaluate_text(
        "off-5",
        "Must be authorised to work in the EU without sponsorship.",
        CandidateEligibility(work_authorisations=("EU",)),
    )

    assert reading.verdict == "PASS"


def test_soft_language_is_flagged_not_failed() -> None:
    """'A plus' is a preference, not a bar. Failing on it would exclude an
    offer that never actually barred the candidate — the false-FAIL direction
    this gate must never take."""
    reading = eligibility.evaluate_text(
        "off-6",
        "An active security clearance is a plus, but not required for most roles.",
        CandidateEligibility(clearances=()),
    )

    assert reading.verdict == "FLAG"
    assert reading.reason == "clearance"


def test_a_hard_bar_with_unclear_candidate_status_is_flagged_not_failed() -> None:
    """The single most important false-FAIL trap here: the bar is explicit
    and hard, but the candidate has never said anything about clearances. A
    plausible-but-wrong implementation treats 'no information' as 'candidate
    does not have it' and FAILs. The correct verdict is FLAG — the human is
    the tiebreaker, not a guess dressed up as a fact."""
    reading = eligibility.evaluate_text(
        "off-7", "Must hold an active security clearance.", UNKNOWN_CANDIDATE
    )

    assert reading.verdict == "FLAG"
    assert reading.reason == "clearance"


def test_a_generic_bar_naming_no_target_does_not_fail_a_candidate_who_holds_something() -> None:
    """'Citizenship is required' names no country. A candidate who has stated
    *some* citizenship might well hold the one that satisfies it — this
    module cannot tell, and guessing FAIL would be the false-FAIL direction;
    guessing PASS would silently rank a possible disqualification. FLAG is
    the only honest answer."""
    reading = eligibility.evaluate_text(
        "off-8",
        "Citizenship is required for this government contract.",
        CandidateEligibility(citizenships=("ES",)),
    )

    assert reading.verdict == "FLAG"


def test_a_generic_bar_naming_no_target_fails_a_candidate_who_holds_none_at_all() -> None:
    """The other side of the case above: the candidate has stated they hold
    *no* citizenship at all. Whatever citizenship the advert has in mind,
    they do not have it, so this is a genuine disqualification even without
    an extracted target."""
    reading = eligibility.evaluate_text(
        "off-9",
        "Citizenship is required for this government contract.",
        CandidateEligibility(citizenships=()),
    )

    assert reading.verdict == "FAIL"


def test_a_negated_statement_is_not_a_requirement_at_all() -> None:
    """'You do not need to hold German citizenship' contains every keyword a
    naive scanner would key on, and states the opposite of a bar. A
    false-FAIL trap: treating this as a stated disqualification would exclude
    an offer that explicitly told the candidate they qualify."""
    text = (
        "You do not need to hold German citizenship to apply for this role "
        "— we provide full visa sponsorship."
    )

    assert eligibility.find_requirements(text) == ()
    reading = eligibility.evaluate_text("off-10", text, UNKNOWN_CANDIDATE)
    assert reading.verdict == "PASS"


def test_multiple_requirements_the_worst_verdict_wins() -> None:
    """An advert stating both a bar the candidate clears and one it does not
    must report the disqualifying one — a average or first-match strategy
    would silently rank a job the candidate cannot take."""
    text = (
        "Must be authorised to work in the EU without sponsorship. "
        "Applicants must hold German citizenship at the time of application."
    )
    candidate = CandidateEligibility(work_authorisations=("EU",), citizenships=("ES",))

    reading = eligibility.evaluate_text("off-11", text, candidate)

    assert reading.verdict == "FAIL"
    assert reading.reason == "citizenship"
    assert len(reading.requirements) == 2


def test_filter_eligible_excludes_only_fail_verdicts() -> None:
    """The hard filter itself: a FAIL offer never reaches the frontier; a
    FLAG offer is kept, marked, ranked — spec §5.4, 'the human is the
    tiebreaker'. Only FAIL removes an offer."""
    fail_offer = connect_manual(
        "Applicants must hold German citizenship at the time of application."
    )
    flag_offer = connect_manual("Must hold an active security clearance.")
    pass_offer = connect_manual("Backend Engineer wanted. Python, remote.")
    candidate = CandidateEligibility(citizenships=("ES",))

    ranked, readings = eligibility.filter_eligible([fail_offer, flag_offer, pass_offer], candidate)

    assert [r.verdict for r in readings] == ["FAIL", "FLAG", "PASS"]
    assert ranked == [flag_offer, pass_offer]


def test_the_gate_does_not_pass_when_a_known_violation_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The task's exit-code contract: a run with a known violation must exit
    1, and must never report `unmeasured` even if the status key would
    otherwise read that way — a known bad result outranks 'could not be
    scored yet'. `_main` is exercised directly (not re-derived here) so this
    pins the module's real branch order, not a restatement of it."""
    contrived = {
        "offers_ranked_despite_a_stated_disqualification": 2,
        "offers_ranked_despite_a_stated_disqualification_evaluated": 3,
        "gate_status": "unmeasured",
        "violations": ["contrived violation for this test"],
    }
    monkeypatch.setattr(eligibility, "write_evidence", lambda evidence: contrived)

    exit_code = eligibility._main(["eligibility", str(tmp_path / "T76.json")])

    assert exit_code == 1


def test_main_writes_evidence_and_exits_zero_on_the_real_probe_set(tmp_path: Path) -> None:
    target = tmp_path / "T76.json"
    exit_code = eligibility._main(["eligibility", str(target)])

    assert exit_code == 0
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["gate_status"] == "measured"
    assert written["offers_ranked_despite_a_stated_disqualification"] == 0
    assert written["offers_ranked_despite_a_stated_disqualification_evaluated"] > 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("We welcome international applicants.", True),
        ("Equal opportunities employer.", True),
        ("We consider applicants regardless of nationality.", True),
        ("Backend Engineer wanted. Python, remote.", False),
    ],
)
def test_is_company_wide_statement_recognises_common_boilerplate(text: str, expected: bool) -> None:
    assert eligibility.is_company_wide_statement(text) is expected
