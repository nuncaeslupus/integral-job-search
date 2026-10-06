"""T247 — a job-alert pointer is usable only with a permission recorded for that read."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from integral import alert_mailbox as am
from integral.alert_mailbox import Reason
from integral.identity import ProfileStore, create_profile

KELVIN = chr(0x212A)  # Kelvin sign: casefolds to ASCII k
_GRANT = "2026-10-05T09:00:00+00:00"
_READ = "2026-10-05T09:30:00+00:00"


def _perm(**kw: str) -> am.MailboxPermission:
    base = {
        "permission_id": "p1",
        "read_id": "r1",
        "mailbox": "a@x.org",
        "session": "s1",
        "granted_at": _GRANT,
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
        "read_at": _READ,
    }
    return am.AlertPointer(**{**base, **kw})  # type: ignore[arg-type]


def test_a_pointer_citing_a_permission_for_this_read_and_mailbox_holds() -> None:
    assert am.refusal(_pointer(mailbox=" A@X.org "), [_perm()]) is None


@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({"permission_id": None}, Reason.NO_CITE),
        ({"permission_id": " "}, Reason.NO_CITE),
        ({"permission_id": "p9"}, Reason.UNKNOWN),
        ({"read_id": ""}, Reason.BLANK_ID),
        ({"session": " "}, Reason.BLANK_ID),
        ({"read_id": "r2"}, Reason.OTHER_READ),
        ({"session": "s2"}, Reason.OTHER_SESSION),
        ({"mailbox": "other@x.org"}, Reason.OTHER_MAILBOX),
        ({"mailbox": "a person"}, Reason.MAILBOX_UNRESOLVABLE),
        ({"mailbox": KELVIN + "@x.org"}, Reason.MAILBOX_UNRESOLVABLE),  # Kelvin sign
        ({"mailbox": "straße@x.org"}, Reason.MAILBOX_UNRESOLVABLE),
        ({"read_at": "yesterday"}, Reason.READ_TIME_BAD),
        ({"read_at": "2026-10-05T09:30:00"}, Reason.READ_TIME_BAD),  # naive
        ({"read_at": "2026-10-05T08:59:59+00:00"}, Reason.PERMISSION_AFTER_READ),
    ],
)
def test_each_refusal_is_for_its_own_reason(kw: dict[str, object], reason: Reason) -> None:
    assert am.refusal(_pointer(**kw), [_perm()]) is reason


def test_a_permission_recorded_at_the_moment_of_the_read_holds() -> None:
    assert am.refusal(_pointer(read_at=_GRANT), [_perm()]) is None


def test_the_offset_is_honoured_when_ordering() -> None:
    # 09:30+02:00 is 07:30 UTC, before a 09:00 UTC grant.
    why = am.refusal(_pointer(read_at="2026-10-05T09:30:00+02:00"), [_perm()])
    assert why is Reason.PERMISSION_AFTER_READ


def test_a_trailing_junk_address_is_not_an_address() -> None:
    # fullmatch, not match: a valid prefix with junk after it resolves to nothing.
    assert am.resolve_mailbox("a@x.org <b>") is None
    assert am.resolve_mailbox("a@x.org\nb") is None
    assert am.resolve_mailbox("a@x.org") == "a@x.org"


def test_non_ascii_addresses_resolve_to_nothing_and_are_never_merged() -> None:
    assert am.resolve_mailbox(KELVIN + "@x.org") is None  # casefolds to 'k@x.org'
    assert am.resolve_mailbox("k@x.org") == "k@x.org"
    assert am.resolve_mailbox("straße@x.org") is None


@pytest.mark.parametrize("shown", ["", "  ", "a person", "me@", "a@x"])
def test_an_unresolvable_mailbox_resolves_to_none(shown: str) -> None:
    assert am.resolve_mailbox(shown) is None


@pytest.mark.parametrize(
    "kw",
    [
        {"mailbox": "me"},
        {"read_id": " "},
        {"session": ""},
        {"permission_id": ""},
        {"granted_at": "yesterday"},
        {"granted_at": "2026-10-05T09:00:00"},  # naive
    ],
)
def test_a_permission_that_identifies_no_read_cannot_be_recorded(kw: dict[str, str]) -> None:
    with pytest.raises(am.MailboxPermissionError):
        _perm(**kw)


def test_record_applies_the_same_validator_as_grant(tmp_path: Path) -> None:
    bad = replace(_perm(), read_id="")
    with pytest.raises(am.MailboxPermissionError):
        am.record(ProfileStore(tmp_path, "ada"), bad)


def test_record_refuses_a_duplicate_permission_id(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, "ada")
    am.record(store, _perm())
    with pytest.raises(am.MailboxPermissionError):
        am.record(store, _perm(read_id="r2"))
    assert len(am.load(store)) == 1


@pytest.mark.parametrize(
    "kw",
    [
        {"read_id": ""},
        {"session": " "},
        {"permission_id": " "},
        {"mailbox": "a person"},
        {"granted_at": "never"},
        {"granted_at": "2026-10-05T09:00:00"},
    ],
)
def test_a_loaded_row_grant_would_refuse_licenses_nothing(
    tmp_path: Path, kw: dict[str, str]
) -> None:
    # Written to the ledger by hand, bypassing `record`: the pointer matches it exactly.
    row = {**asdict(_perm()), **kw}
    store = ProfileStore(tmp_path, "ada")
    store.append_jsonl(row, *am.LEDGER_PARTS)
    pointer = _pointer(
        permission_id=row["permission_id"],
        read_id=row["read_id"],
        session=row["session"],
        mailbox=row["mailbox"],
    )
    assert am.refusal(pointer, am.load(store)) is not None


def test_a_loaded_invalid_row_is_refused_as_an_invalid_record(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, "ada")
    store.append_jsonl({**asdict(_perm()), "granted_at": "never"}, *am.LEDGER_PARTS)
    assert am.refusal(_pointer(), am.load(store)) is Reason.INVALID_RECORD


def test_a_duplicated_id_in_the_ledger_licenses_nothing(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, "ada")
    store.append_jsonl(asdict(_perm()), *am.LEDGER_PARTS)
    store.append_jsonl(asdict(_perm()), *am.LEDGER_PARTS)
    assert am.refusal(_pointer(), am.load(store)) is Reason.DUPLICATE


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
    assert measured["refusal_reasons_without_a_case"] == 0
    assert measured["gate_status"] == "measured"


def test_every_refusing_case_differs_from_a_permitted_twin_in_one_dimension() -> None:
    twin = am._ptr()
    permissions = am._permissions()
    for pointer, why in am._CASES:
        if why is None:
            continue
        differing = [k for k in asdict(twin) if asdict(twin)[k] != asdict(pointer)[k]]
        # permission_id may name a different (broken) record; that is still one dimension.
        assert len(differing) == 1, (why, differing)
        assert am.refusal(pointer, permissions) is why


def test_a_population_too_small_is_unmeasured_not_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(am, "_CASES", am._CASES[:3])
    measured = am.measure()
    assert measured["job_alert_emails_read_without_a_recorded_permission"] == -1
    assert measured["gate_status"] == "unmeasured"


def test_a_rule_that_lets_everything_through_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(am, "refusal", lambda pointer, permissions: None)
    measured = am.measure()
    assert measured["job_alert_emails_read_without_a_recorded_permission"] == (
        am.MINIMUM_REFUSING_CASES
    )


def test_a_rule_that_refuses_for_the_wrong_reason_is_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(am, "refusal", lambda pointer, permissions: Reason.UNKNOWN)
    measured = am.measure()
    assert measured["job_alert_emails_read_without_a_recorded_permission"] > 0
    assert measured["permitted_pointers_refused"] > 0


def test_a_reason_no_case_reaches_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    kept = tuple(c for c in am._CASES if c[1] is not Reason.OTHER_READ)
    monkeypatch.setattr(am, "_CASES", kept)
    monkeypatch.setattr(am, "MINIMUM_REFUSING_CASES", len(kept) - 2)
    assert am.measure()["refusal_reasons_without_a_case"] == 1


# --- the recorder CLI ---------------------------------------------------------


def _profile(tmp_path: Path) -> list[str]:
    create_profile(tmp_path, "Ada Test", handle="ada")
    return ["--root", str(tmp_path), "--handle", "ada"]


def test_the_cli_mints_the_ids_and_the_time(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _profile(tmp_path)
    assert am._main(["x", *base, "grant", "--mailbox", "A@X.org", "--session", "s1"]) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["permission_id"].startswith("perm-") and row["read_id"].startswith("read-")
    assert am._moment(row["granted_at"]) is not None
    assert am.load(ProfileStore(tmp_path, "ada")) == [am.MailboxPermission(**row)]


def test_the_cli_refuses_a_mailbox_that_is_not_an_address(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _profile(tmp_path)
    assert am._main(["x", *base, "grant", "--mailbox", "me", "--session", "s1"]) == 2
    assert am.load(ProfileStore(tmp_path, "ada")) == []


_CHECK_TAIL = ["--read-id", "r", "--mailbox", "a@x.org", "--read-at", "2999-01-01T00:00:00+00:00"]


@pytest.mark.parametrize(
    "spelling",
    [
        lambda b: ["check", *b, *_CHECK_TAIL],  # subcommand first
        lambda b: [f"--root={b[1]}", "--handle=ada", "check", *_CHECK_TAIL],  # `=` form
        lambda b: ["--roo", b[1], "--handle", "ada", "check", *_CHECK_TAIL],  # abbreviation
        lambda b: ["grant", *b, "--mailbox", "a@x.org"],
        lambda b: ["--bogus"],
        lambda b: ["check"],  # a bare subcommand name is not a path
        lambda b: ["out.json", "extra"],  # more than one argument is never evidence mode
    ],
)
def test_anything_but_no_argument_or_one_path_never_runs_evidence_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spelling: object
) -> None:
    base = _profile(tmp_path)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    try:
        code = am._main(["x", *spelling(base)])  # type: ignore[operator]
    except SystemExit as exc:
        code = int(exc.code or 0)
    assert code != 0
    assert list(cwd.iterdir()) == []


def test_the_cli_exits_2_for_an_unknown_profile(tmp_path: Path) -> None:
    argv = ["x", "--root", str(tmp_path), "--handle", "nobody", "grant", "--mailbox", "a@x.org"]
    assert am._main(argv) == 2


def test_the_cli_check_accepts_a_granted_read_and_refuses_another(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _profile(tmp_path)
    am._main(["x", *base, "grant", "--mailbox", "a@x.org", "--session", "s1"])
    row = json.loads(capsys.readouterr().out)
    later = "2999-01-01T00:00:00+00:00"
    ok = ["x", *base, "check", "--read-id", row["read_id"], "--session", "s1"]
    ok += ["--mailbox", "a@x.org", "--permission-id", row["permission_id"], "--read-at", later]
    assert am._main(ok) == 0
    assert capsys.readouterr().out.strip() == "ok"
    other = [*ok]
    other[other.index(row["read_id"])] = "read-other"
    assert am._main(other) == 1
    assert capsys.readouterr().out.strip() == Reason.OTHER_READ.value
