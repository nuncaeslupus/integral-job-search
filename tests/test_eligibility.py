"""T76 — the eligibility gate: a stated, role-level bar the candidate cannot
meet excludes the offer before scoring; a false FAIL is the failure that
matters most here, because an excluded job is one the candidate never sees.

These fixtures are hand-built, not drawn from the corpus (D-23): there are no
labels for permit, citizenship or clearance language, so this suite exercises
the mechanism — the three-verdict shape, the negation and soft-language
handling, the empty-input-set honesty — never accuracy on a real advert.
"""

from __future__ import annotations

import ast
import inspect
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


_RANKING_MODULES = frozenset({"rank", "scoring", "weights"})


def _imported_names(source: str) -> frozenset[str]:
    """Every module name `source` imports, by any form.

    `from integral import rank` puts `integral` in `ImportFrom.module` and
    `rank` in its `names` — so collecting only `.module` sees the package and
    misses the module, which is the one that matters here. Both are collected,
    for both statement forms.
    """
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[-1])
            names.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name.split(".")[-1] for alias in node.names)
    return frozenset(names)


def test_the_import_audit_catches_every_form_a_ranking_module_could_arrive_by() -> None:
    """The negative control for the assertion above.

    An audit that cannot see the import it is looking for would pass silently
    forever. `from integral import rank` is the form that slipped through a
    first version of this check, so each form is pinned here.
    """
    assert "rank" in _imported_names("from integral import rank\n")
    assert "rank" in _imported_names("from integral.rank import priced_dimensions\n")
    assert "rank" in _imported_names("import integral.rank\n")
    assert "rank" in _imported_names("from integral import rank as r\n")
    assert "rank" not in _imported_names("from integral.offers import Offer\n")


def test_a_dimension_weight_cannot_change_a_gate_verdict() -> None:
    """Direction 2: no dimension weight can reach this gate's verdict.

    The guarantee is structural — `evaluate_offer` takes no weights argument,
    so there is no path by which one could arrive — and that is what this test
    pins. Calling `evaluate_offer(offer, candidate)` twice and comparing the
    two results cannot establish it: both calls pass identical arguments, so
    the comparison holds for any deterministic function and would keep holding
    if someone added a `weights=` parameter with a default. Asserting the
    signature is what actually fails when the boundary is breached.
    """
    parameters = inspect.signature(eligibility.evaluate_offer).parameters
    assert list(parameters) == ["offer", "candidate"], (
        "evaluate_offer grew a parameter: if a weight can be passed in, the gate "
        "and the ranker share a channel neither output layer would ever show"
    )
    assert list(inspect.signature(eligibility.evaluate_text).parameters) == [
        "offer_id",
        "text",
        "candidate",
    ]

    imported = _imported_names(Path(eligibility.__file__).read_text(encoding="utf-8"))
    assert not imported & _RANKING_MODULES, (
        "eligibility imported a ranking module — the weight could reach the gate "
        f"through it: {sorted(imported & _RANKING_MODULES)}"
    )

    # With the structure pinned above, the behavioural half is worth stating:
    # two genuinely different weight scenarios, and a verdict that is the
    # offer's alone under both.
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

    assert eligibility.evaluate_offer(offer, candidate).verdict == "FAIL"


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
    """`> 0` is too weak to catch the failure that matters here.

    The audit mixes two kinds of point — module scans and offer cases — and
    reporting the combined length as `ranked_offers_evaluated` claimed five
    offers where three were seen. An inflated denominator makes a zero look
    better supported than it is, so both counts are asserted exactly: a case
    added or dropped has to be acknowledged here rather than sliding under a
    `> 0`.
    """
    measured = eligibility.measure_boundary()

    assert measured["gate_status"] == "measured"
    assert measured["gate_fields_read_by_the_ranker"] == 0
    assert measured["ranked_offers_evaluated"] == len(eligibility.WEIGHT_INVARIANCE_CASES) == 3
    assert measured["ranker_modules_scanned"] == len(eligibility.RANKER_MODULES) == 2
    assert measured["audit_points_evaluated"] == 5
    assert measured["gate_verdicts_mismatching_expectation"] == 0


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
# T77 — every FAIL and every FLAG carries the advert's own sentence


def test_every_fail_verdict_carries_the_adverts_own_sentence() -> None:
    """A FAIL excludes the offer outright — spec's own objection to an
    unexplained veto applies with full force here. If this module cannot show
    the sentence that disqualified the offer, it has no business removing it
    from the candidate's list."""
    text = "Applicants must hold German citizenship at the time of application."
    reading = eligibility.evaluate_text(
        "t77-fail", text, CandidateEligibility(citizenships=("ES",))
    )

    assert reading.verdict == "FAIL"
    assert reading.quote
    assert reading.quote in text


def test_a_flag_verdict_quotes_too() -> None:
    """FLAG is a claim about the advert as much as FAIL is — "this is
    ambiguous" or "your status here is unclear" still has to point at real
    wording, not an implementation's own paraphrase of what it saw."""
    text = "An active security clearance is a plus, but not required for most roles."
    reading = eligibility.evaluate_text("t77-flag", text, CandidateEligibility(clearances=()))

    assert reading.verdict == "FLAG"
    assert reading.quote
    assert reading.quote in text


def test_a_verdict_quote_is_a_span_of_the_advert_text() -> None:
    """`is_advert_span` is the exact bar a quote must clear: found, byte for
    byte, somewhere in the text it is attributed to."""
    text = "Must hold an active TS/SCI clearance before starting."

    assert eligibility.is_advert_span("Must hold an active TS/SCI clearance", text)
    assert not eligibility.is_advert_span("Must hold an active TS/SCI clearance!", text)


def test_a_near_miss_quote_with_collapsed_whitespace_is_not_a_span() -> None:
    """A plausible-but-wrong implementation normalises whitespace before
    comparing, so a quote that collapses the advert's double space to one
    would read as found when it was never actually written that way. No
    normalisation: the check compares raw text."""
    text = "Must hold an active TS/SCI  clearance before starting."
    quote = "Must hold an active TS/SCI clearance before starting."

    assert quote not in text, "the fixture must be a genuine near miss, not an accidental match"
    assert not eligibility.is_advert_span(quote, text)


def test_a_near_miss_quote_with_a_stripped_accent_is_not_a_span() -> None:
    """Same failure mode, the accent-folding direction: 'España' and 'Espana'
    are not the same bytes, and a quote is not entitled to the difference."""
    text = "Debe tener residencia legal en España para este puesto."
    quote = "residencia legal en Espana"

    assert quote not in text
    assert not eligibility.is_advert_span(quote, text)


def test_a_near_miss_quote_with_an_inserted_ellipsis_is_not_a_span() -> None:
    """A quote spliced from two non-adjacent parts of the advert and joined
    with an ellipsis is not a span of the text, even though both halves,
    read separately, are genuine."""
    text = "Must hold an active TS/SCI clearance. Remote-first team, competitive salary."
    quote = "Must hold an active TS/SCI clearance ... competitive salary."

    assert quote not in text
    assert not eligibility.is_advert_span(quote, text)


def test_a_fabricated_quote_is_a_schema_violation_not_a_warning() -> None:
    """The module's own rule, exercised directly: a quote not found in the
    advert text must fail loudly, never pass through as a warning."""
    with pytest.raises(eligibility.QuoteProvenanceError):
        eligibility._require_advert_span(
            "a sentence the advert never wrote", "the advert's actual text", context="test"
        )


def test_a_missing_quote_on_a_non_pass_verdict_is_also_a_schema_violation() -> None:
    """No quote at all is refused exactly like a fabricated one — 'FAIL, no
    quote given' is still an unfalsifiable veto."""
    with pytest.raises(eligibility.QuoteProvenanceError):
        eligibility._require_advert_span(None, "the advert's actual text", context="test")


def test_the_quote_provenance_gate_does_not_pass_on_an_empty_input_set() -> None:
    """The same failure this whole increment is about, turned on T77's own
    gate: a zero-violation count over zero disqualification verdicts
    evaluated is not a pass."""
    measured = eligibility.measure_quote_provenance(readings=[])

    assert measured["gate_status"] == "unmeasured"
    assert measured["disqualification_verdicts_evaluated"] == 0
    assert measured["disqualification_verdicts_without_quoted_wording_evaluated"] == 0
    assert measured["disqualification_verdicts_without_quoted_wording"] == -1


def test_the_real_probe_set_has_a_non_zero_quote_provenance_denominator() -> None:
    """The task's own gate: over the module's built-in adversarial fixtures,
    `disqualification_verdicts_evaluated` must be written and non-zero, and
    the violation count must be zero."""
    measured = eligibility.measure_quote_provenance()

    assert measured["gate_status"] == "measured"
    assert measured["disqualification_verdicts_evaluated"] > 0
    assert measured["disqualification_verdicts_without_quoted_wording"] == 0


def test_main_writes_t77_evidence_beside_t76(tmp_path: Path) -> None:
    """`_main` regenerates both gates in one run — both task payloads name the
    same `python -m integral.eligibility` command, so the module must produce
    both evidence files from it. Pointing the T76 path at a temp directory
    must not write the T77 file over the committed one."""
    t76_target = tmp_path / "T76.json"
    exit_code = eligibility._main(["eligibility", str(t76_target)])

    assert exit_code == 0
    t77_written = json.loads((tmp_path / "T77.json").read_text(encoding="utf-8"))
    assert t77_written["gate_status"] == "measured"
    assert t77_written["disqualification_verdicts_without_quoted_wording"] == 0
    assert t77_written["disqualification_verdicts_evaluated"] > 0


def test_a_language_quote_the_advert_never_contained_is_a_schema_violation() -> None:
    """T78 introduced a second source of requirements, and it is the one most
    able to carry text the advert never held.

    The other three kinds are found by a regex *over* the advert, so their
    quote is a span by construction. A language bar instead comes from the
    structured `offer.language_requirement`, whose `quote` is whatever the
    connector put there — so nothing about how it was produced guarantees it
    appears in `offer.text`. Without a check, T78 would have opened a path
    around T77's whole guarantee: a candidate shown a sentence, attributed to
    the advert, that the advert never contained.

    `evaluate_offer` holds both sources to the same bar, so this raises.
    """
    offer = _language_offer(
        "Backend Engineer, remote. German is required for this role.",
        requirement_language="de",
        quote="Fluent Klingon is required for this role.",
    )

    with pytest.raises(eligibility.QuoteProvenanceError):
        eligibility.evaluate_offer(offer, CandidateEligibility(languages=("en",)))


def test_a_language_quote_that_is_a_real_span_is_accepted() -> None:
    """The other half of the case above: the check rejects fabrication, not
    structured language requirements as such."""
    offer = _language_offer(
        "Backend Engineer, remote. German is required for this role.",
        requirement_language="de",
        quote="German is required for this role.",
    )

    reading = eligibility.evaluate_offer(offer, CandidateEligibility(languages=("en",)))

    assert reading.verdict == "FAIL"


def test_a_verdict_mismatch_is_not_reported_as_the_ranker_reading_a_gate_field() -> None:
    """The two directions fail for different reasons and must count separately.

    Folding both into `gate_fields_read_by_the_ranker` meant a regression in
    *this* gate — a verdict no longer matching its expectation — was reported
    as `rank.py` having read a gate-only field. The reader would go and inspect
    a module that did nothing wrong. A metric that misnames its own failure
    costs more than no metric, because disproving it takes longer than reading
    it.
    """
    results = [
        {
            "direction": "ranker_never_reads_a_gate_field",
            "name": "rank.py",
            "match": True,
            "detail": None,
        },
        {
            "direction": "gate_verdict_matches_expectation",
            "name": "a-language-bar",
            "match": False,
            "detail": "expected FAIL, got PASS",
        },
    ]

    measured = eligibility.measure_boundary(results)

    assert measured["gate_fields_read_by_the_ranker"] == 0
    assert measured["gate_verdicts_mismatching_expectation"] == 1


def test_the_cli_fails_when_a_verdict_mismatches_even_with_a_clean_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A count that is reported but never gates is decoration.

    `_score` folds in the metric it is handed, so the second count has to be
    checked explicitly or a verdict regression would be written to the evidence
    file and exit 0 anyway.
    """
    clean_scan = {
        "direction": "ranker_never_reads_a_gate_field",
        "name": "rank.py",
        "match": True,
        "detail": None,
    }
    bad_verdict = {
        "direction": "gate_verdict_matches_expectation",
        "name": "a-language-bar",
        "match": False,
        "detail": "expected FAIL, got PASS",
    }
    monkeypatch.setattr(eligibility, "audit_boundary", lambda: [clean_scan, bad_verdict])

    exit_code = eligibility._main(["eligibility", str(tmp_path / "T76.json")])

    assert exit_code == 1


def test_the_boundary_scan_catches_every_form_a_gate_field_could_be_read_by() -> None:
    """A ranker does not have to write `offer.language_requirement` to read
    it. `getattr(offer, "language_requirement")` is an `ast.Call` carrying
    the name in a `Constant` argument, and a scan that walks only
    `ast.Attribute` nodes reports a clean boundary over it — a zero the gate
    did not earn, in the one direction it exists to close.

    Each form is pinned separately so a regression names which route
    reopened, and the last two pin the false positives that made an AST walk
    the right choice in the first place.
    """
    reads = {
        "attribute": "def f(o):\n    return o.language_requirement\n",
        "getattr": 'def f(o):\n    return getattr(o, "language_requirement")\n',
        "hasattr": 'def f(o):\n    return hasattr(o, "language_requirement")\n',
        "setattr": 'def f(o, v):\n    setattr(o, "eligibility", v)\n',
    }
    for form, source in reads.items():
        names = eligibility._field_access(source).names
        hit = next((f for f in eligibility.GATE_ONLY_OFFER_FIELDS if f in names), None)
        assert hit is not None, f"a {form} read of a gate-only field went unseen"

    ignored = {
        "docstring": '"""Never reads language_requirement."""\ndef f(o):\n    return o.salary\n',
        "unrelated field": "def f(o):\n    return o.salary + o.seniority\n",
    }
    for form, source in ignored.items():
        names = eligibility._field_access(source).names
        hit = next((f for f in eligibility.GATE_ONLY_OFFER_FIELDS if f in names), None)
        assert hit is None, f"a {form} must not be reported as a gate-field read"


def test_an_access_the_scan_cannot_resolve_is_unmeasured_not_a_clean_zero(
    tmp_path: Path,
) -> None:
    """`getattr(offer, key)` names its field at runtime. The scan cannot say
    whether that field is a gate-only one, and the honest reading of a
    question never answered is `unmeasured` — not the `0` that means "looked
    and found none".

    This is the empty-input failure with a full denominator: a count of zero
    obtained by not looking. `-1`, never `0`, for the same reason
    `_unmeasured_boundary` uses it everywhere else.
    """
    for opaque in (
        "def score(o, key):\n    return getattr(o, key)\n",
        'def score(o):\n    return o.__dict__["language_requirement"]\n',
        "def score(o):\n    return vars(o)\n",
    ):
        module = tmp_path / "rank.py"
        module.write_text(opaque, encoding="utf-8")

        measured = eligibility.measure_boundary(eligibility.audit_boundary(modules=(module,)))

        assert measured["gate_status"] == "unmeasured", opaque
        assert measured["gate_fields_read_by_the_ranker"] == -1
        assert "cannot resolve" in measured["unmeasured_reason"]


def test_a_resolvable_ranker_module_still_measures_clean(tmp_path: Path) -> None:
    """The counterpart to the case above, and the reason it is not enough to
    make every scan unmeasured: a module whose accesses all resolve, and
    which reads no gate-only field, must still produce a measured zero."""
    module = tmp_path / "rank.py"
    module.write_text("def score(o):\n    return o.salary + o.seniority\n", encoding="utf-8")

    measured = eligibility.measure_boundary(eligibility.audit_boundary(modules=(module,)))

    assert measured["gate_status"] == "measured"
    assert measured["gate_fields_read_by_the_ranker"] == 0
    assert measured["ranker_modules_scanned"] == 1
