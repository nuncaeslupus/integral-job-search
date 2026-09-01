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

from pathlib import Path

import pytest

from integral import connector_policy as cp
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
