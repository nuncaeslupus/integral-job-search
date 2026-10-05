"""T247 — a job-alert pointer is usable only with a permission recorded for that read."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from integral import alert_mailbox as am
from integral.identity import ProfileStore


def _perm(**kw: str) -> am.MailboxPermission:
    base = {
        "permission_id": "p1",
        "read_id": "r1",
        "mailbox": "a@x.org",
        "session": "s1",
        "granted_at": "2026-10-05T09:00:00+00:00",
    }
    return am.grant(**{**base, **kw})


def _pointer(**kw: object) -> am.AlertPointer:
    base: dict[str, object] = {
        "title": "Role",
        "employer": "Acme",
        "read_id": "r1",
        "session": "s1",
        "mailbox": "a@x.org",
        "permission_id": "p1",
    }
    return am.AlertPointer(**{**base, **kw})  # type: ignore[arg-type]


def test_a_pointer_citing_a_permission_for_this_read_and_mailbox_holds() -> None:
    assert am.refusal(_pointer(mailbox=" A@X.org "), [_perm()]) is None


def test_no_cited_permission_is_refused() -> None:
    # The message, not just a refusal: "not on record" would answer a mutant too.
    assert "never asked" in (am.refusal(_pointer(permission_id=None), [_perm()]) or "")


def test_an_unrecorded_permission_is_refused() -> None:
    assert am.refusal(_pointer(permission_id="p9"), [_perm()])


def test_a_different_mailbox_is_refused() -> None:
    assert am.refusal(_pointer(mailbox="other@x.org"), [_perm()])


def test_a_permission_for_another_read_is_not_standing() -> None:
    assert am.refusal(_pointer(read_id="r2"), [_perm()])


def test_a_permission_from_another_session_is_refused() -> None:
    assert am.refusal(_pointer(session="s2"), [_perm()])


@pytest.mark.parametrize("shown", ["", "  ", "a person", "me@", "a@x"])
def test_an_unresolvable_mailbox_is_refused_at_the_pointer(shown: str) -> None:
    assert am.refusal(_pointer(mailbox=shown), [_perm()])


def test_an_unresolvable_recorded_mailbox_is_refused_on_the_record_too() -> None:
    bad = replace(_perm(), mailbox="a person")
    assert am.refusal(_pointer(mailbox="a person"), [bad])


@pytest.mark.parametrize(
    "kw",
    [{"mailbox": "me"}, {"read_id": " "}, {"session": ""}, {"granted_at": "yesterday"}],
)
def test_a_permission_that_identifies_no_read_cannot_be_recorded(kw: dict[str, str]) -> None:
    with pytest.raises(am.MailboxPermissionError):
        _perm(**kw)


def test_the_record_keeps_only_what_it_needs(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, "ada")
    am.record(store, _perm())
    assert am.load(store) == [_perm()]
    keys = set(next(iter(store.read_jsonl(*am.LEDGER_PARTS))))
    assert keys == {"permission_id", "read_id", "mailbox", "session", "granted_at"}


def test_an_empty_ledger_loads_as_no_permissions(tmp_path: Path) -> None:
    assert am.load(ProfileStore(tmp_path, "ada")) == []


def test_the_gate_measures_zero_over_enough_cases() -> None:
    measured = am.measure()
    assert measured["job_alert_emails_read_without_a_recorded_permission"] == 0
    assert measured["permitted_pointers_refused"] == 0
    assert measured["gate_status"] == "measured"


def test_a_population_too_small_is_unmeasured_not_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(am, "_CASES", am._CASES[:3])
    measured = am.measure()
    assert measured["job_alert_emails_read_without_a_recorded_permission"] == -1
    assert measured["gate_status"] == "unmeasured"


def test_a_rule_that_lets_everything_through_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(am, "refusal", lambda pointer, permissions: None)
    measured = am.measure()
    assert measured["job_alert_emails_read_without_a_recorded_permission"] >= 7
