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

from integral import eligibility, rank
from integral.eligibility import UNKNOWN_CANDIDATE, CandidateEligibility
from integral.offers import LanguageRequirement, Offer, compute_offer_id, connect_manual


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


def test_negation_in_a_neighbouring_sentence_does_not_cancel_a_bar() -> None:
    """The look-behind used to be a fixed 30 characters, so "not necessary"
    from the sentence *before* the bar negated it and a stated TS/SCI
    requirement returned PASS. That is a fail-open on the exact thing
    `offers_ranked_despite_a_stated_disqualification` counts: the barred offer
    goes on to `rank.py` and the candidate is shown a job they cannot take."""
    reading = eligibility.evaluate_text(
        "offer-1",
        "Experience is not necessary. Must hold an active TS/SCI clearance.",
        CandidateEligibility(clearances=()),
    )

    assert reading.verdict == "FAIL"
    assert reading.reason == "clearance"


def test_soft_language_in_a_neighbouring_sentence_does_not_soften_a_bar() -> None:
    """Same defect in the other window: "a plus" from the preceding sentence
    fell inside the 40-character soft-language window, so a hard citizenship
    bar reported FLAG. Milder than the case above — the offer is marked rather
    than silently permitted — but it still reaches the ranked list."""
    reading = eligibility.evaluate_text(
        "offer-2",
        "Relevant certifications are a plus. Applicants must hold German citizenship.",
        CandidateEligibility(citizenships=()),
    )

    assert reading.verdict == "FAIL"
    assert reading.reason == "citizenship"


def test_the_requirement_noun_is_not_a_target() -> None:
    """"Must hold an active security clearance" names no level, but `_TARGET`
    captured "security" and compared it against the candidate's held
    clearances — so someone holding TS/SCI was excluded by a bar they meet.
    A false FAIL is invisible, so this folds to the generic no-target branch:
    the candidate holds *something*, and a human decides."""
    reading = eligibility.evaluate_text(
        "offer-3",
        "Must hold an active security clearance.",
        CandidateEligibility(clearances=("TS/SCI",)),
    )

    assert reading.verdict == "FLAG"


# ---------------------------------------------------------------------------
# T78 — `offer.language_requirement`, a hard field the ranker never reads
#
# Settled by the owner, 2026-08-25: the language gate reads its own hard
# field rather than `dimensions/english_demand.yaml`'s soft, scored
# preference. Two directions of the same boundary (spec §5.3), because a
# preference weight cancelling a legal or linguistic bar would be invisible
# in any output either layer produces — appended here rather than
# interleaved, per T78's lane.


def _language_offer(
    text: str,
    *,
    requirement_language: str,
    applies_to: str = "role",
    quote: str | None = None,
    offer_language: str | None = None,
) -> Offer:
    return Offer(
        id=compute_offer_id(text),
        source="manual",
        text=text,
        language=offer_language,  # type: ignore[arg-type]
        language_requirement=LanguageRequirement(
            language=requirement_language,
            level_stated=None,
            quote=quote or text,
            applies_to=applies_to,  # type: ignore[arg-type]
        ),
    )


def test_a_hard_gate_field_is_never_read_by_the_ranker() -> None:
    """Direction 1 of spec §5.3's boundary: `rank.py` and `scoring.py` — the
    two modules the boundary table names as "the ranker" — must never access
    `.language_requirement` or `.eligibility` on anything. A hit would mean
    the preference layer can see a field only the hard gate may read."""
    results = [
        r
        for r in eligibility.audit_boundary()
        if r["direction"] == "ranker_never_reads_a_gate_field"
    ]

    assert results, "the ranker modules must actually have been scanned, not skipped"
    assert all(r["match"] for r in results), [r["detail"] for r in results if not r["match"]]


def test_a_dimension_weight_cannot_change_a_gate_verdict() -> None:
    """Direction 2: this gate's verdict for a fixed offer and candidate does
    not move when a dimension weight moves. Two `weights.json`-shaped
    mappings, pricing `english_demand` at opposite extremes to prove the two
    scenarios really do differ, and the gate's verdict is asserted identical
    under both — because `evaluate_offer` takes no `weights` argument at all
    and has no path by which either number could reach it."""
    offer = _language_offer(
        "Backend Engineer, remote. German is required for this role.",
        requirement_language="de",
    )
    candidate = CandidateEligibility(languages=("en",))

    low = rank.priced_dimensions(
        {"part_worths": {"english_demand": {"salary_equivalent_per_month": -5000.0}}}
    )
    high = rank.priced_dimensions(
        {"part_worths": {"english_demand": {"salary_equivalent_per_month": 5000.0}}}
    )
    assert low != high, "the two weight scenarios must genuinely differ, or this proves nothing"

    verdict_under_low_weight = eligibility.evaluate_offer(offer, candidate).verdict
    verdict_under_high_weight = eligibility.evaluate_offer(offer, candidate).verdict

    assert verdict_under_low_weight == verdict_under_high_weight == "FAIL"


def test_the_role_language_is_read_not_the_adverts_own_language() -> None:
    """A Catalan advert for a role needing only Spanish demands Spanish —
    reading `Offer.language` (what the advert is written in) instead of
    `language_requirement.language` (what the role demands) is the exact
    mistake this task exists to prevent."""
    offer = _language_offer(
        "Es requereix castella per a aquest lloc de treball.",
        requirement_language="es",
        offer_language="ca",
    )
    candidate = CandidateEligibility(languages=("ca",))

    reading = eligibility.evaluate_offer(offer, candidate)

    assert reading.verdict == "FAIL"
    assert reading.reason == "language"


def test_the_role_language_is_read_not_the_adverts_own_language_inverse() -> None:
    """The inverse of the case above: an advert written in English for a
    role that explicitly requires Catalan. A gate that read `Offer.language`
    would see "en" and never look for a bar at all."""
    offer = _language_offer(
        "Customer-facing role. Catalan is required for this position.",
        requirement_language="ca",
        offer_language="en",
    )
    candidate = CandidateEligibility(languages=("en",))

    reading = eligibility.evaluate_offer(offer, candidate)

    assert reading.verdict == "FAIL"
    assert reading.reason == "language"


def test_a_language_bar_the_candidate_meets_is_a_pass() -> None:
    offer = _language_offer(
        "Se requiere espanol fluido para el puesto.",
        requirement_language="es",
    )
    candidate = CandidateEligibility(languages=("es", "en"))

    reading = eligibility.evaluate_offer(offer, candidate)

    assert reading.verdict == "PASS"


def test_a_language_bar_with_unclear_candidate_status_is_flagged_not_failed() -> None:
    """The candidate has never stated which languages they work in — FLAG,
    never a confident FAIL over an absence of information, the same rule
    every other requirement kind here follows."""
    offer = _language_offer(
        "Fluent German is required for this role.",
        requirement_language="de",
    )

    reading = eligibility.evaluate_offer(offer, UNKNOWN_CANDIDATE)

    assert reading.verdict == "FLAG"
    assert reading.reason == "language"


def test_a_company_wide_language_statement_does_not_gate_the_role() -> None:
    """`applies_to == "company"` is a blanket statement about the employer,
    not a role-level bar — the same principle `COMPANY_WIDE_WELCOME_RE`
    applies to citizenship and permits, applied here to language. It must
    produce no requirement at all, never a PASS or a FAIL either one."""
    offer = _language_offer(
        "Data Analyst. Our company's internal working language is English.",
        requirement_language="en",
        applies_to="company",
    )

    reading = eligibility.evaluate_offer(offer, CandidateEligibility(languages=()))

    assert reading.verdict == "PASS"
    assert reading.requirements == ()


def test_evaluate_text_never_sees_a_language_requirement() -> None:
    """`evaluate_text` takes raw text, not a structured `Offer` — it has no
    way to see `language_requirement` and must never invent one, even when
    the text itself talks about a language bar in citizenship-style
    wording."""
    reading = eligibility.evaluate_text(
        "offer-lang-text",
        "German is required for this role.",
        CandidateEligibility(languages=()),
    )

    assert reading.verdict == "PASS"
    assert reading.requirements == ()


def test_the_boundary_gate_does_not_pass_on_an_empty_input_set() -> None:
    """A zero violation count over zero audit points is not a pass — the
    same empty-input-set honesty `offers_ranked_despite_a_stated_disqualification`
    already holds, pinned here for T78's own metric."""
    measured = eligibility.measure_boundary([])

    assert measured["gate_status"] == "unmeasured"
    assert measured["gate_fields_read_by_the_ranker"] == -1
    assert measured["ranked_offers_evaluated"] == 0


def test_the_real_boundary_probe_set_has_a_non_zero_denominator() -> None:
    measured = eligibility.measure_boundary()

    assert measured["gate_status"] == "measured"
    assert measured["gate_fields_read_by_the_ranker"] == 0
    assert measured["ranked_offers_evaluated"] > 0


def test_write_boundary_evidence_writes_t78_json(tmp_path: Path) -> None:
    target = tmp_path / "T78.json"

    measured = eligibility.write_boundary_evidence(target)

    written = json.loads(target.read_text(encoding="utf-8"))
    assert written == measured
    assert written["gate_status"] == "measured"
    assert written["gate_fields_read_by_the_ranker"] == 0


def test_main_regenerates_t78_evidence_beside_t76(tmp_path: Path) -> None:
    """`python -m integral.eligibility` writes T78's boundary evidence beside
    T76's, in the same directory, without one gate's exit code masking the
    other."""
    t76_target = tmp_path / "T76.json"

    exit_code = eligibility._main(["eligibility", str(t76_target)])

    assert exit_code == 0
    t78_written = json.loads((tmp_path / "T78.json").read_text(encoding="utf-8"))
    assert t78_written["gate_status"] == "measured"
    assert t78_written["gate_fields_read_by_the_ranker"] == 0
