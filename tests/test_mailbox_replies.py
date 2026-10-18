"""T341 — mailbox replies propose a status change; a yes is per read; nothing applies unasked."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from integral import alert_mailbox as am
from integral import mailbox_replies as mr
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import load_lifecycle_offer, read_application_status
from integral.mailbox_replies import Outcome, ProposalError, ReplyKind


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    create_profile(root, "Fixture", handle="fixture", language="en", fiction=True)
    return ProfileStore(root, "fixture")


@pytest.fixture
def ids(store: ProfileStore) -> dict[str, str]:
    found = mr._seed(store)
    for permission in mr._permissions():
        am.record(store, permission)
    return found


def _state(store: ProfileStore, offer_id: str) -> tuple[str, str | None]:
    offer, _record = load_lifecycle_offer(store, offer_id)
    return offer.status, read_application_status(store, offer_id)


def test_the_gate_reads_clean_and_its_controls_read_above_zero() -> None:
    measured = mr.measure()
    assert mr.gate_passes(measured), measured
    assert measured["mailbox_reads_without_a_per_read_permission"] == 0
    assert measured["control_unpermitted_reads_that_got_through"] > 0
    assert measured["control_digest_moves_when_a_change_is_applied"] > 0
    assert measured["cases_measured"] >= mr.MINIMUM_CASES_MEASURED
    assert measured["reasons_recorded_without_the_candidates_yes"] == 0
    assert measured["control_reason_rows_counted_when_the_candidate_says_yes"] == 1
    assert measured["outcomes_without_a_case"] == 0


def test_the_headline_counter_reads_above_zero_on_a_permission_blind_control() -> None:
    blind = [mr.Verdict(mr.Outcome.PROPOSED) for _ in mr._CASES]
    assert mr._unpermitted_that_got_through(blind) == mr.measure()["refusing_cases"]
    honest = [mr.Verdict(o) for _r, o, _w, _f in mr._CASES]
    assert mr._unpermitted_that_got_through(honest) == 0


def test_every_outcome_is_expected_by_some_case() -> None:
    assert {o for _r, o, _w, _f in mr._CASES} == set(mr.Outcome)


def test_a_yes_for_read_one_does_not_authorise_read_two(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    first = mr._reply()  # read r1 under p1
    second = mr._reply(read_id="r2")  # a later read citing the same permission
    verdict, proposal = mr.propose(store, first)
    assert verdict.outcome is Outcome.PROPOSED and proposal
    verdict, proposal = mr.propose(store, second)
    assert verdict.outcome is Outcome.REFUSED
    assert verdict.refusal is am.Reason.OTHER_READ
    assert proposal is None
    assert len(mr._rows(store)) == 1


def test_a_refused_reply_is_never_matched_against_the_applications(
    store: ProfileStore, ids: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> list[str]:
        raise AssertionError("an unpermitted read reached the applications")

    monkeypatch.setattr(mr, "_matches", boom)
    for kind in ReplyKind:
        verdict, _ = mr.propose(store, mr._reply(kind, permission_id=None))
        assert verdict.outcome is Outcome.REFUSED


@pytest.mark.parametrize(
    ("title", "employer"),
    [
        ("Backend Engineer", "Nobody Inc"),  # no such employer
        ("Never Applied", "Zeta"),  # an offer on record, but never applied to
        ("Backend Engineer (senior)", "Acme"),  # a different posting
        ("", "Acme"),  # a blank title matches nothing
    ],
)
def test_a_reply_for_an_application_not_on_record_proposes_nothing(
    store: ProfileStore, ids: dict[str, str], title: str, employer: str
) -> None:
    verdict, proposal = mr.propose(store, mr._reply(title=title, employer=employer))
    assert verdict.outcome is Outcome.UNMATCHED
    assert proposal is None and mr._rows(store) == []


def test_two_applications_for_one_posting_propose_nothing(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    verdict, proposal = mr.propose(store, mr._reply(title="Ops Lead", employer="Delta"))
    assert verdict.outcome is Outcome.AMBIGUOUS and proposal is None


def test_a_proposal_changes_no_file_until_it_is_confirmed(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    before = mr._digest(store)
    _verdict, proposal = mr.propose(store, mr._reply())
    assert proposal and mr._digest(store) == before
    assert _state(store, ids["acme"]) == ("applied", "applied")
    mr.confirm(store, proposal)
    assert _state(store, ids["acme"]) == ("rejected", "rejected")
    with pytest.raises(ProposalError, match="already decided"):
        mr.confirm(store, proposal)


def test_a_declined_proposal_stays_unapplied_and_cannot_be_confirmed_later(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    _verdict, proposal = mr.propose(store, mr._reply())
    assert proposal
    before = mr._digest(store)
    mr.decline(store, proposal)
    assert mr._digest(store) == before
    with pytest.raises(ProposalError):
        mr.confirm(store, proposal)
    assert _state(store, ids["acme"]) == ("applied", "applied")


def test_confirming_an_unknown_proposal_is_refused(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    with pytest.raises(ProposalError, match="not a proposal on record"):
        mr.confirm(store, "reply-nope")


def test_a_rejection_confirmed_without_a_reason_records_no_statement(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    _v, plain = mr.propose(store, mr._reply())
    assert plain
    mr.confirm(store, plain)
    assert not store.exists("profile", "evidence.jsonl")


def test_an_informative_rejection_reason_becomes_a_statement(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    _v, proposal = mr.propose(store, mr._reply())
    assert proposal
    mr.confirm(store, proposal, informative_reason="they wanted people-management experience")
    rows = list(store.read_jsonl("profile", "evidence.jsonl"))
    assert [r["kind"] for r in rows] == ["statement"]
    assert "people-management" in rows[0]["text"]


@pytest.mark.parametrize(
    ("kind", "outcome"),
    [
        (ReplyKind.ACKNOWLEDGEMENT, Outcome.NO_CHANGE),
        (ReplyKind.INTERVIEW_INVITATION, Outcome.NO_MARK),
    ],
)
def test_acknowledgements_and_invitations_change_nothing(
    store: ProfileStore, ids: dict[str, str], kind: ReplyKind, outcome: Outcome
) -> None:
    verdict, proposal = mr.propose(store, mr._reply(kind, "Data Analyst", "Beta"))
    assert verdict.outcome is outcome and proposal is None


def test_offer_terms_are_routed_to_t334_even_for_an_unknown_employer(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    for employer in ("Beta", "Unknown Ltd"):
        verdict, proposal = mr.propose(store, mr._reply(ReplyKind.OFFER_TERMS, "X", employer))
        assert verdict.outcome is Outcome.ROUTED_TO_T334 and proposal is None
    assert mr._rows(store) == []


def test_a_rejection_the_lifecycle_forbids_is_not_proposed(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    for title, employer in (("Designer", "Gamma"), ("QA Lead", "Epsilon")):
        verdict, proposal = mr.propose(store, mr._reply(title=title, employer=employer))
        assert verdict.outcome is Outcome.TRANSITION_REFUSED and proposal is None


def test_the_command_line_reads_the_recorded_permission_and_confirms_on_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "profiles"
    create_profile(root, "Fixture", handle="fixture", language="en", fiction=True)
    store = ProfileStore(root, "fixture")
    ids = mr._seed(store)
    base = ["--root", str(root), "--handle", "fixture"]
    assert am._cli([*base, "grant", "--mailbox", "me@example.org", "--session", "s9"]) == 0
    granted = json.loads(capsys.readouterr().out)
    args = [
        *base,
        "propose",
        "--kind",
        "rejection",
        "--title",
        "Backend Engineer",
        "--employer",
        "Acme",
        "--received-at",
        "2026-10-05T08:00:00+00:00",
        "--read-id",
        granted["read_id"],
        "--session",
        "s9",
        "--mailbox",
        "me@example.org",
        "--read-at",
        granted["granted_at"],  # a read at the moment of the yes: never later than now
    ]
    # no permission cited: refused, exit 1, nothing written
    assert mr._cli(args) == 1
    assert json.loads(capsys.readouterr().out)["outcome"] == "REFUSED"
    assert mr._rows(store) == []
    assert mr._cli([*args, "--permission-id", granted["permission_id"]]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] == "PROPOSED" and out["ask_whether_the_reason_is_informative"]
    assert _state(store, ids["acme"]) == ("applied", "applied")
    assert mr._cli([*base, "confirm", out["proposal_id"]]) == 0
    assert _state(store, ids["acme"]) == ("rejected", "rejected")
    assert mr._cli([*base, "confirm", out["proposal_id"]]) == 2


_NOW = datetime(2026, 12, 31, tzinfo=UTC)


def _later(reply: mr.Reply, **changes: str) -> mr.Reply:
    return mr.Reply(
        reply.kind,
        reply.title,
        reply.employer,
        changes.get("received_at", reply.received_at),
        am.AlertPointer(
            reply.pointer.title,
            reply.pointer.employer,
            reply.pointer.read_id,
            reply.pointer.session,
            reply.pointer.mailbox,
            reply.pointer.permission_id,
            changes.get("read_at", reply.pointer.read_at),
        ),
    )


def test_a_reply_that_arrived_a_week_after_the_read_is_not_credited_to_it(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    verdict, proposal = mr.propose(
        store, mr._reply(received_at="2026-10-12T09:00:00+00:00"), now=_NOW
    )
    assert verdict.outcome is Outcome.REPLY_AFTER_READ and proposal is None
    assert _state(store, ids["acme"]) == ("applied", "applied")


def test_a_read_time_in_the_future_is_refused_and_the_clock_is_injected(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    for read_at in ("2099-01-01T00:00:00+00:00", "2026-12-31T00:00:00+00:00"):
        reply = mr._reply(read_id="r3", permission_id="p3", read_at=read_at)
        verdict, proposal = mr.propose(store, reply, now=datetime(2026, 10, 17, tzinfo=UTC))
        assert verdict.outcome is Outcome.READ_IN_FUTURE and proposal is None
    # the same read time is fine once the clock has passed it
    reply = mr._reply(read_id="r3", permission_id="p3", read_at="2026-12-31T00:00:00+00:00")
    assert mr.propose(store, reply, now=_NOW)[0].outcome is Outcome.PROPOSED


@pytest.mark.parametrize("received", ["yesterday", "", "2026-10-05T08:00:00", "05/10/2026"])
def test_a_reply_date_that_does_not_parse_or_has_no_zone_is_refused(
    store: ProfileStore, ids: dict[str, str], received: str
) -> None:
    verdict, proposal = mr.propose(store, mr._reply(received_at=received), now=_NOW)
    assert verdict.outcome is Outcome.REPLY_DATE_BAD and proposal is None


def test_a_read_id_reused_three_weeks_later_is_not_a_new_read(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    ack = mr._reply(ReplyKind.ACKNOWLEDGEMENT, "Data Analyst", "Beta")
    assert mr.propose(store, ack, now=_NOW)[0].outcome is Outcome.NO_CHANGE
    three_weeks = "2026-10-26T09:30:00+00:00"
    late = mr._reply(received_at=three_weeks, read_at=three_weeks)
    verdict, proposal = mr.propose(store, late, now=_NOW)
    assert verdict.outcome is Outcome.READ_TIME_REBOUND and proposal is None
    # the same instant spelled another way is the same read
    same = mr._reply(read_at="2026-10-05T11:30:00+02:00")
    assert mr.propose(store, same, now=_NOW)[0].outcome is Outcome.PROPOSED


def test_a_refused_reply_does_not_bind_its_read_id(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    refused = mr._reply(permission_id=None, read_at="2026-10-05T10:00:00+00:00")
    assert mr.propose(store, refused, now=_NOW)[0].outcome is Outcome.REFUSED
    assert mr.propose(store, mr._reply(), now=_NOW)[0].outcome is Outcome.PROPOSED


def test_a_proposal_is_refused_when_confirming_it_would_be(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    for kwargs, outcome in (
        ({"title": "Chief Analyst", "employer": "Iota"}, Outcome.CONFIRMED_BY_CANDIDATE),
        ({"received_at": "2026-09-01T00:00:00+00:00"}, Outcome.BEFORE_LAST_TRANSITION),
        ({"received_at": "yesterday"}, Outcome.REPLY_DATE_BAD),
    ):
        verdict, proposal = mr.propose(store, mr._reply(**kwargs), now=_NOW)  # type: ignore[arg-type]
        assert verdict.outcome is outcome and proposal is None
    assert mr._rows(store) == []


def test_a_second_pending_proposal_for_one_application_is_refused_until_decided(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    _v, first = mr.propose(store, mr._reply(), now=_NOW)
    assert first
    verdict, second = mr.propose(store, mr._reply(), now=_NOW)
    assert verdict.outcome is Outcome.ALREADY_PENDING and second is None
    mr.decline(store, first)
    assert mr.propose(store, mr._reply(), now=_NOW)[0].outcome is Outcome.PROPOSED


def test_confirm_judges_the_permission_again(store: ProfileStore, ids: dict[str, str]) -> None:
    store.append_jsonl(
        {
            "proposal_id": "reply-handwritten",
            "state": "proposed",
            "offer_id": ids["acme"],
            "to_status": "rejected",
            "received_at": mr._RECEIVED,
            "permission_id": None,
            "read_id": "r1",
        },
        *mr.LEDGER_PARTS,
    )
    with pytest.raises(ProposalError, match="no longer has a yes"):
        mr.confirm(store, "reply-handwritten")
    assert _state(store, ids["acme"]) == ("applied", "applied")


def test_confirm_refuses_a_row_whose_permission_names_another_read(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    _v, proposal = mr.propose(store, mr._reply(), now=_NOW)
    assert proposal
    rows = [{**r, "read_id": "r2"} if r.get("state") == "proposed" else r for r in mr._rows(store)]
    path = store.path(*mr.LEDGER_PARTS)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(ProposalError, match="no longer has a yes"):
        mr.confirm(store, proposal)


def test_a_read_with_no_proposal_still_binds_its_read_id(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    late = mr._reply(received_at="2026-10-12T09:00:00+00:00")  # arrived after the read
    assert mr.propose(store, late, now=_NOW)[0].outcome is Outcome.REPLY_AFTER_READ
    reused = mr._reply(read_at=mr._LATER_READ)  # the same id claimed for a later read
    verdict, proposal = mr.propose(store, reused, now=_NOW)
    assert verdict.outcome is Outcome.READ_TIME_REBOUND and proposal is None


def test_confirm_judges_visibility_and_the_read_binding_again(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    _v, proposal = mr.propose(store, mr._reply(), now=_NOW)
    assert proposal
    path = store.path(*mr.LEDGER_PARTS)
    original = path.read_text(encoding="utf-8")
    for change in ({"received_at": "2026-10-12T09:00:00+00:00"}, {"read_at": mr._LATER_READ}):
        rows = [{**r, **change} if r.get("state") == "proposed" else r for r in mr._rows(store)]
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        with pytest.raises(ProposalError, match="no longer visible"):
            mr.confirm(store, proposal, now=_NOW)
        assert _state(store, ids["acme"]) == ("applied", "applied")
        path.write_text(original, encoding="utf-8")


def test_a_refused_confirm_does_not_block_the_next_reply(
    store: ProfileStore, ids: dict[str, str]
) -> None:
    _v, proposal = mr.propose(store, mr._reply(), now=_NOW)
    assert proposal
    rows = [
        {**r, "permission_id": None} if r.get("state") == "proposed" else r for r in mr._rows(store)
    ]
    store.path(*mr.LEDGER_PARTS).write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    with pytest.raises(ProposalError, match="no longer has a yes"):
        mr.confirm(store, proposal, now=_NOW)
    verdict = mr.propose(store, mr._reply(), now=_NOW)[0]
    assert verdict.outcome is Outcome.PROPOSED
