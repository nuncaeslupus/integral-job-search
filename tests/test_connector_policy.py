"""T99 — a refusal that is ours, not the board's, needs an owner's decision.

`connectors/ruled-out.yaml` grew a `policy_refused` section holding
remoteok.com: robots.txt **allows** the endpoint under RFC 9309 group
semantics, and the implementing session refused anyway, because the board
restates those `Disallow` lines verbatim for eleven named AI crawlers.

The owner had already stated a different position:

    It is the user who will use the scraper, not you, and most of them did
    not allow massive scraping for AI, but they allow it for making some
    searches.

That is a real disagreement and it turns on *who is fetching*. The file's own
header already says the same thing — "those bans target bulk training crawls;
a connector is one candidate's search" — so the ledger contradicts its own
rule two hundred lines apart.

**The defect is the same whichever way it resolves.** A policy that silently
removes boards from a candidate's reach needs a decision recorded next to it,
and it was never put to the owner. These tests are about that record, not
about remoteok.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from integral import connector_policy as cp
from integral import robots
from integral.connector_policy import (
    DEFAULT_LEDGER_PATH,
    PolicyRefusal,
    measure,
    refusals,
)


def test_every_policy_refusal_cites_an_owner_decision_with_a_date() -> None:
    """Who decided, and when. Without both, a judgement made in one session
    reads a month later exactly like a settled position."""
    for refusal in refusals(DEFAULT_LEDGER_PATH):
        assert refusal.decided_by == "owner", refusal.site
        assert refusal.decided_on is not None, refusal.site
        assert refusal.decision.strip(), refusal.site


def test_a_refusal_distinguishes_volume_from_access() -> None:
    """The owner's position is about volume; the entry was written as access.
    Those are different refusals with different consequences — one throttles a
    connector, the other deletes a board from the candidate's reach — and a
    section that does not say which cannot be argued with."""
    for refusal in refusals(DEFAULT_LEDGER_PATH):
        assert refusal.refuses in {"volume", "access"}, refusal.site


def test_a_board_allowed_by_robots_is_never_refused_without_a_cited_rule() -> None:
    """`policy_refused` is by definition the mechanically-allowed set, so the
    citation is the whole of the argument. An entry without one is a board
    removed on nobody's stated grounds."""
    for refusal in refusals(DEFAULT_LEDGER_PATH):
        if refusal.robots_verdict == "allowed":
            assert refusal.rule_cited.strip(), refusal.site


def test_an_entry_with_no_decision_is_counted(tmp_path: Path) -> None:
    """The gate, shown failing — the state the ledger was actually in."""
    ledger = tmp_path / "ruled-out.yaml"
    ledger.write_text(
        "policy_refused:\n"
        "  - site: example.test\n"
        "    checked: 2026-08-31\n"
        "    refuses: access\n"
        "    robots_verdict: allowed\n"
        "    rule_cited: 'something'\n",
        encoding="utf-8",
    )

    measured = measure(ledger)

    assert measured["policy_refusals_without_an_owner_decision"] == 1
    assert measured["gate_status"] == "measured"


def test_a_decision_by_the_implementing_session_is_not_an_owner_decision(
    tmp_path: Path,
) -> None:
    """The exact defect. A session recording its own judgement as the decision
    would satisfy a check that only asked whether the field was filled in."""
    ledger = tmp_path / "ruled-out.yaml"
    ledger.write_text(
        "policy_refused:\n"
        "  - site: example.test\n"
        "    checked: 2026-08-31\n"
        "    refuses: access\n"
        "    robots_verdict: allowed\n"
        "    rule_cited: 'something'\n"
        "    decided_by: implementing session\n"
        "    decided_on: 2026-08-31\n"
        "    decision: 'the intent is legible'\n",
        encoding="utf-8",
    )

    measured = measure(ledger)

    assert measured["policy_refusals_without_an_owner_decision"] == 1
    assert "decided_by" in " ".join(measured["violations"])


def test_the_ledger_as_committed_passes() -> None:
    measured = measure()

    assert measured["policy_refusals_without_an_owner_decision"] == 0
    assert measured["violations"] == []
    assert measured["gate_status"] == "measured"


def test_the_gate_counts_what_it_checked() -> None:
    """One live entry is a thin denominator, so the constructed malformed
    entries are put through the same reader and counted with it. A rule true
    of one row is nearly a rule true of nothing."""
    measured = measure()

    assert measured["policy_refusals_without_an_owner_decision_evaluated"] >= len(
        cp.MALFORMED_CONTROLS
    )
    assert measured["policy_refusals_checked"] == measured[
        "policy_refusals_without_an_owner_decision_evaluated"
    ]
    assert measured["live_refusals"] >= 1


def test_the_gate_does_not_pass_on_an_empty_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "ruled-out.yaml"
    ledger.write_text("policy_refused: []\n", encoding="utf-8")

    measured = measure(ledger, controls=())

    assert measured["policy_refusals_without_an_owner_decision"] == 0
    assert measured["policy_refusals_without_an_owner_decision_evaluated"] == 0
    assert measured["gate_status"] == "unmeasured"


def test_every_malformed_control_is_caught() -> None:
    """Each control is malformed by construction, so a run that accepts one
    has lost the check rather than found a clean ledger."""
    for name, payload in cp.MALFORMED_CONTROLS:
        assert PolicyRefusal.from_mapping(payload).problems(), name


def test_a_yaml_timestamp_is_not_a_decided_on_date() -> None:
    """`datetime` is a `date` subtype, so a YAML timestamp passes an
    `isinstance` check written for a day. The ledger records the day a call
    was made, not the minute a file was written."""
    assert cp._as_date(datetime(2026, 8, 31, 14, 30)) is None


def test_an_unpadded_date_is_not_a_decided_on_date() -> None:
    """`strptime` accepts `2026-8-1`. A ledger read years later holds one
    spelling of a day, not two."""
    assert cp._as_date("2026-8-1") is None


def test_a_canonical_date_is_read() -> None:
    """Both spellings the ledger actually uses — PyYAML's parsed `date`, and
    a quoted ISO string — are the record."""
    assert cp._as_date(date(2026, 8, 31)) == date(2026, 8, 31)
    assert cp._as_date(" 2026-08-31 ") == date(2026, 8, 31)


def test_the_module_writes_its_evidence(tmp_path: Path) -> None:
    target = tmp_path / "T99.json"

    assert cp._main(["connector_policy", str(target)]) == 0
    assert target.is_file()


def test_a_refusal_that_names_no_site_is_not_silently_skipped(tmp_path: Path) -> None:
    """A row with no site cannot be argued with, retested or overturned."""
    ledger = tmp_path / "ruled-out.yaml"
    ledger.write_text("policy_refused:\n  - checked: 2026-08-31\n", encoding="utf-8")

    measured = measure(ledger)

    assert measured["policy_refusals_without_an_owner_decision"] >= 1


def test_an_unreadable_ledger_is_not_a_clean_run(tmp_path: Path) -> None:
    """Nothing read is not nothing to find."""
    ledger = tmp_path / "ruled-out.yaml"
    ledger.write_text("policy_refused: [\n", encoding="utf-8")

    with pytest.raises(cp.PolicyLedgerError):
        measure(ledger)


# ---------------------------------------------------------------------------
# T116 — the second reader in "two matchers must agree" could not say no.
#
# Every expected verdict below was derived from RFC 9309's text and written
# into `COMPETENCE_FIXTURES[...].why` BEFORE either parser was run over the
# document beside it. Deciding correctness by execution is the circularity
# that let T70 take ten defects across five review rounds, eight of them
# introduced by the session fixing the previous one.
#
# Egress to rfc-editor.org is blocked in the session that wrote these, so the
# citations are RECOLLECTED rather than fetched. Each names its section, so a
# reader with the text in front of them checks the derivation and not the code.
# ---------------------------------------------------------------------------

FIXTURES_BY_NAME = {fixture.name: fixture for fixture in cp.COMPETENCE_FIXTURES}


def _fixture(name: str) -> cp._CompetenceFixture:
    return FIXTURES_BY_NAME[name]


def test_a_first_match_parser_on_a_permissively_opening_file_is_not_competent() -> None:
    """RFC 9309 §2.2.2: "The most specific match found MUST be used. The most
    specific match is the match that has the most octets."

        User-agent: *
        Allow: /
        Disallow: /apply

    `/apply` matches both rules; the disallow is six octets against the
    allow's one, so the RFC refuses it. CPython's `Entry.allowance` returns on
    the FIRST `applies_to` hit, which here is `Allow: /` — so the second reader
    returns True for `/apply` and for every other path in the file. It cannot
    refuse, so its agreement carries no information at all.

    Fail-open, in the exact component that exists as the independent check.
    Measured on himalayas.app and nofluffjobs.com, both of which open this way.
    """
    fixture = _fixture("a_permissive_opener_hides_every_longer_disallow")
    found = cp._classify(fixture.robots_txt, fixture.agent)

    assert found.verdict == cp.INCOMPETENT
    # The two halves of the finding, asserted rather than assumed.
    assert "/apply" in found.rfc_refused
    assert found.second_reader_refused == ()
    assert cp.second_reader_allows(fixture.robots_txt, fixture.agent, "/apply") is True
    assert robots.allows_text(fixture.robots_txt, fixture.agent, "/apply") is False


def test_an_agreement_counts_only_when_the_second_parser_refuses_one_path_on_the_same_file() -> (
    None
):
    """The rule, from both sides.

    A recorded `two_parsers_agreed` that names no refused path is counted —
    that is the state every agreement over a permissively-opening file was
    silently in. The same row with a refusal named is not.

    "On the same file" is load-bearing: a refusal demonstrated somewhere else
    says nothing about whether this reader can refuse here, which is what
    `test_the_same_rules_in_the_other_order...` shows on one rule set.
    """
    without = cp.RobotsAdjudication.from_mapping(
        {
            "site": "a.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": cp.TWO_PARSERS_AGREED,
            "second_reader": "urllib.robotparser",
            "source": "connectors/robots-adjudications.yaml",
            "allowed": ["/jobs"],
        }
    )
    problems = without.problems()
    assert problems
    assert any("cannot say no" in problem for problem in problems)

    with_refusal = cp.RobotsAdjudication.from_mapping(
        {
            "site": "a.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": cp.TWO_PARSERS_AGREED,
            "second_reader": "urllib.robotparser",
            "source": "connectors/robots-adjudications.yaml",
            "allowed": ["/jobs"],
            "second_reader_refused": ["/admin/"],
        }
    )
    assert with_refusal.problems() == []


def test_a_file_admitting_no_negative_control_carries_its_own_verdict() -> None:
    """RFC 9309 §2.2.2 admits an empty pattern, which has no octets to match,
    so the group carries no restriction; with no match found in the group the
    URI is allowed. `www.workingnomads.com`'s entire robots.txt is that
    document, and no correct parser can produce a False on it.

    That is a third state, not a missing one. Before this, "no control is
    possible here" and "nobody ran a control" were the same silence.
    """
    fixture = _fixture("a_bare_disallow_admits_no_negative_control")
    found = cp._classify(fixture.robots_txt, fixture.agent)

    assert found.verdict == cp.NO_CONTROL_POSSIBLE
    assert found.rfc_refused == ()
    assert cp.NO_NEGATIVE_CONTROL_POSSIBLE in cp.STANDINGS

    live = {row.site: row for row in cp.adjudications()}
    assert live["workingnomads.com"].standing == cp.NO_NEGATIVE_CONTROL_POSSIBLE
    assert live["workingnomads.com"].reason


def test_the_same_rules_in_the_other_order_change_the_second_readers_competence() -> None:
    """The argument for measuring competence rather than assuming it.

    `Disallow: /apply` and `Allow: /` are one rule set, and §2.2.2 gives
    `/apply` the same verdict whichever order they are written in — precedence
    is by octets, not by position. A first-match reader's answer flips. So
    competence is a property of the FILE, never of the reader, and cannot be
    established once and carried to the next board.
    """
    permissive_first = _fixture("a_permissive_opener_hides_every_longer_disallow")
    disallow_first = _fixture("the_same_rules_in_the_other_order_let_the_second_reader_refuse")

    assert robots.allows_text(permissive_first.robots_txt, permissive_first.agent, "/apply") is (
        robots.allows_text(disallow_first.robots_txt, disallow_first.agent, "/apply")
    )
    assert cp._classify(permissive_first.robots_txt, permissive_first.agent).verdict == (
        cp.INCOMPETENT
    )
    assert cp._classify(disallow_first.robots_txt, disallow_first.agent).verdict == cp.COMPETENT


def test_refusing_a_path_the_rfc_allows_is_not_counted_as_competence() -> None:
    """RFC 9309 §2.2.2: "If an allow rule and a disallow rule are equivalent,
    then the allow rule SHOULD be used."

        User-agent: *
        Disallow: /jobs
        Allow: /jobs

    So `/jobs` is ALLOWED and this file refuses nothing — no control exists.
    A first-match reader returns the disallow it meets first and says False.
    A competence check that only asked "did some False come back" would score
    this file as the second reader's best showing, on the one path where the
    reader is wrong. Fail-closed for that path, and fail-open for every other
    path on the file, because it manufactures a competence finding.
    """
    fixture = _fixture("refusing_a_path_the_rfc_allows_is_not_competence")
    found = cp._classify(fixture.robots_txt, fixture.agent)

    assert found.verdict == cp.NO_CONTROL_POSSIBLE
    assert "/jobs" in found.second_reader_false_refusals
    assert found.second_reader_refused == ()


def test_a_disallow_written_for_another_agent_is_not_our_negative_control() -> None:
    """RFC 9309 §2.2.1: a crawler obeys the one group its product token
    selects, falling back to `*`. `OtherBot`'s `Disallow: /` is not a
    restriction on us, so offering it as our negative control would
    manufacture a refusal out of a group we are not in — a control that
    "passes" while proving nothing about the rules binding this fetch.
    """
    fixture = _fixture("a_disallow_for_another_agent_is_not_our_negative_control")
    found = cp._classify(fixture.robots_txt, fixture.agent)

    assert found.verdict == cp.NO_CONTROL_POSSIBLE
    assert found.controls_tried == ()
    # And the same file DOES yield a control for the agent it names.
    assert cp._classify(fixture.robots_txt, "OtherBot/1.0").verdict == cp.COMPETENT


def test_a_wildcard_and_anchored_rule_still_yields_a_negative_control() -> None:
    """RFC 9309 §2.2.3 gives `*` "any sequence of characters" and `$` "end of
    URL". A sampler that could not turn `/*.pdf$` back into a path would find
    no controls on this file and report `no_control_possible` — which reads as
    good news and is the fail-open answer.
    """
    fixture = _fixture("an_end_anchored_wildcard_rule_still_yields_a_control")
    found = cp._classify(fixture.robots_txt, fixture.agent)

    assert found.controls_tried == ("/x.pdf",)
    assert found.rfc_refused == ("/x.pdf",)
    assert found.verdict == cp.INCOMPETENT


def test_every_competence_fixture_classifies_as_the_rfc_requires() -> None:
    """The whole table, in one assertion, so a new fixture is measured by
    being added rather than by also being wired up."""
    for fixture in cp.COMPETENCE_FIXTURES:
        found = cp._classify(fixture.robots_txt, fixture.agent)
        assert found.verdict == fixture.expected, f"{fixture.name}: {fixture.section}"


def test_every_competence_fixture_cites_the_section_it_was_derived_from() -> None:
    """A verdict argued from what the code does is the circularity this exists
    to break, so every case names the RFC section it was read off — and all
    three verdicts are exercised, since a table that only ever expects one is
    satisfied by a classifier that only ever returns it."""
    for fixture in cp.COMPETENCE_FIXTURES:
        assert fixture.section.startswith("RFC 9309 §"), fixture.name
        assert fixture.why.strip(), fixture.name
    assert {fixture.expected for fixture in cp.COMPETENCE_FIXTURES} == {
        cp.COMPETENT,
        cp.INCOMPETENT,
        cp.NO_CONTROL_POSSIBLE,
    }


def test_the_stdlib_second_reader_returns_the_first_matching_rule() -> None:
    """The defect stated directly against the dependency, so a CPython release
    that fixed `Entry.allowance` shows up here as a failure to read rather than
    as silence. Both files carry the same rules; only the order differs.
    """
    permissive_first = "User-agent: *\nAllow: /\nDisallow: /apply\n"
    disallow_first = "User-agent: *\nDisallow: /apply\nAllow: /\n"
    agent = "integral-job-search/0.1"

    assert cp.second_reader_allows(permissive_first, agent, "/apply") is True
    assert cp.second_reader_allows(disallow_first, agent, "/apply") is False
    # RFC 9309 §2.2.2 gives one answer for both.
    assert robots.allows_text(permissive_first, agent, "/apply") is False
    assert robots.allows_text(disallow_first, agent, "/apply") is False


def test_the_committed_adjudication_record_passes() -> None:
    measured = cp.measure_second_readers()

    assert measured["robots_adjudications_without_a_competent_second_reader"] == 0
    assert measured["violations"] == []
    assert measured["gate_status"] == "measured"


def test_every_shipped_package_has_an_adjudication_record() -> None:
    """A package with no record is a fetch admitted with no second reader at
    all. Excluding it would make the metric reachable by deleting rows, which
    is the direction this repository keeps finding."""
    measured = cp.measure_second_readers()

    assert measured["packages_without_an_adjudication_record"] == 0
    assert measured["shipped_packages"] >= cp.PACKAGES_AT_LEAST


def test_a_shipped_package_with_no_record_is_counted(tmp_path: Path) -> None:
    """The coverage half, shown failing."""
    record = tmp_path / "robots-adjudications.yaml"
    record.write_text("adjudications: []\n", encoding="utf-8")
    packages = tmp_path / "connectors"
    (packages / "somewhere_en").mkdir(parents=True)

    measured = cp.measure_second_readers(
        record, packages_dir=packages, controls=(), fixtures=(), repo_root=tmp_path
    )

    assert measured["packages_without_an_adjudication_record"] == 1
    assert measured["robots_adjudications_without_a_competent_second_reader"] == 1


def test_every_malformed_adjudication_control_is_caught() -> None:
    """Each control is malformed by construction, so a run that accepts one
    has lost the check rather than found a clean record."""
    for name, payload in cp.MALFORMED_ADJUDICATIONS:
        assert cp.RobotsAdjudication.from_mapping(payload).problems(), name


def test_an_honest_single_parser_row_is_not_counted() -> None:
    """The task's own scope: "where it cannot, the adjudication is
    single-parser and must be recorded as such rather than counted as
    agreement". A metric that counted the honest record could only reach zero
    by deleting it — and the two boards measured in #310 are exactly these."""
    live = {row.site: row for row in cp.adjudications()}

    for site in ("himalayas.app", "nofluffjobs.com"):
        assert live[site].standing == cp.SINGLE_PARSER
        assert live[site].problems() == []
        assert live[site].reason


def test_the_one_agreement_names_the_path_its_second_reader_refused() -> None:
    """usajobs.gov is the only `two_parsers_agreed` standing in the record, and
    it earns it: that file has no `Allow` line at all, so first-match order and
    longest-match precedence cannot diverge on it, and `/Content/foo.css` came
    back False from both readers."""
    agreements = [row for row in cp.adjudications() if row.standing == cp.TWO_PARSERS_AGREED]

    assert agreements
    for row in agreements:
        assert row.second_reader_refused, row.site
        assert row.allowed, row.site
        assert (cp._REPO_ROOT / row.source).is_file(), row.site


def test_the_gate_does_not_pass_on_a_scan_under_its_floor(tmp_path: Path) -> None:
    """A clean zero over an empty scan is what a check that never ran also
    reports, so the denominator is floored and the honest answer below it is
    `unmeasured` — not a pass and not a fail."""
    record = tmp_path / "robots-adjudications.yaml"
    record.write_text("adjudications: []\n", encoding="utf-8")
    packages = tmp_path / "connectors"
    packages.mkdir()

    measured = cp.measure_second_readers(
        record, packages_dir=packages, controls=(), fixtures=(), repo_root=tmp_path
    )

    assert measured["robots_adjudications_without_a_competent_second_reader"] == 0
    assert measured["robots_adjudications_checked"] == 0
    assert measured["gate_status"] == "unmeasured"


def test_the_committed_evidence_holds_the_floor_not_the_count_of_the_day() -> None:
    """T100's family. Adding a connector moves the denominator, and a committed
    exact value would make that an evidence drift on every such PR. The floor
    says what the scan guaranteed, without moving."""
    measured = cp.measure_second_readers()
    committed = cp.record_second_readers(measured)

    assert committed["robots_adjudications_at_least"] == cp.ADJUDICATIONS_AT_LEAST
    assert committed["shipped_packages_at_least"] == cp.PACKAGES_AT_LEAST
    for moving in (
        "robots_adjudications_without_a_competent_second_reader_evaluated",
        "robots_adjudications_checked",
        "live_adjudications",
        "shipped_packages",
    ):
        assert moving not in committed, moving
    # A floor nothing clears is a decoration.
    assert measured["robots_adjudications_checked"] >= cp.ADJUDICATIONS_AT_LEAST
    assert measured["shipped_packages"] >= cp.PACKAGES_AT_LEAST


def test_an_unreadable_adjudication_record_is_not_a_clean_run(tmp_path: Path) -> None:
    """Nothing read is not nothing to find."""
    record = tmp_path / "robots-adjudications.yaml"
    record.write_text("adjudications: [\n", encoding="utf-8")

    with pytest.raises(cp.AdjudicationLedgerError):
        cp.measure_second_readers(record)


def test_the_module_writes_its_second_reader_evidence(tmp_path: Path) -> None:
    target = tmp_path / "T116.json"

    assert cp._main(["connector_policy", "--second-readers", str(target)]) == 0
    committed = json.loads(target.read_text(encoding="utf-8"))
    assert committed["robots_adjudications_without_a_competent_second_reader"] == 0
    assert committed["gate_status"] == "measured"


def test_a_bare_invocation_writes_both_gates(tmp_path: Path) -> None:
    """`make evidence` runs each module once and cannot know a module owns two
    gates, so a bare run must write both or T116's record silently stops being
    regenerated."""
    for name, writer in (
        ("T99.json", cp.write_evidence),
        ("T116.json", cp.write_second_reader_evidence),
    ):
        target = tmp_path / name
        writer(target)
        assert target.is_file(), name

    assert "--second-readers" in cp._KNOWN_OPTIONS
    assert cp._main(["connector_policy", "--nope"]) == 2
