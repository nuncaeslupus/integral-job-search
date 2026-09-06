"""T128 — a board that does not serve UTF-8 must decode correctly or refuse.

The cases below were derived from the WHATWG Encoding Standard and WHATWG HTML
**before** the decoder was written, and each cites the clause its verdict comes
from. CLAUDE.md requires a session other than the implementer to write a
correctness-critical gate's fixtures, precisely so the cases are not a
description of what the code already does. No second session was available;
writing the table from the standard first is the nearest substitute, it is
weaker, and the pull request says so rather than claiming the rule was met.

The behavioural contracts live in `connectors.CHARSET_CONTRACTS` so `make
evidence` measures them. These tests cover what a contract table cannot: that
the table itself has teeth.
"""

from __future__ import annotations

import pytest

from integral.connectors import (
    CHARSET_CONTRACTS,
    DEFAULT_CONNECTORS_DIR,
    MINIMUM_CHARSET_CONTRACTS,
    ConnectorError,
    connector_packages,
    decode_body,
    encoding_for,
    load_connector,
    measure_charset,
    parse_connector,
)

_MINIMAL = (
    "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
    "{extra}list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
    "  fields:\n    text: {{css: '.x'}}\n"
)


def test_every_contract_holds() -> None:
    measured = measure_charset()
    assert measured["charset_contracts_failing"] == 0, measured["failed_contracts"]
    assert measured["charset_contracts_checked"] >= MINIMUM_CHARSET_CONTRACTS
    assert measured["gate_status"] == "measured"


def test_the_contract_names_are_unique() -> None:
    """Two contracts sharing a name means one silently replaced the other."""
    names = [name for name, _, _ in CHARSET_CONTRACTS]
    assert len(names) == len(set(names))


def test_every_contract_names_its_source() -> None:
    """A verdict argued from what the decoder does is the circularity this
    table exists to break, so each has to say where it comes from.

    Two kinds are allowed and the distinction is the point. A contract citing
    `Encoding §` or `HTML` is derived from the standard and is not negotiable.
    One prefixed `repo policy:` is this library's own choice — refusing rather
    than replacing, refusing at load rather than at fetch — and a reader is
    entitled to know which they are looking at. Written broader first, and this
    test failed over five contracts that had no citation because four of them
    genuinely are not in the standard.
    """
    for name, clause, _ in CHARSET_CONTRACTS:
        assert any(source in clause for source in ("Encoding §", "HTML ", "repo policy:")), (
            f"{name} cites no standard clause and is not marked as repo policy"
        )


def test_most_contracts_are_derived_from_the_standard() -> None:
    """A table that drifted to all-policy would be this library agreeing with
    itself about encodings, which is what reading the spec first prevents."""
    from_standard = [
        name for name, clause, _ in CHARSET_CONTRACTS if "Encoding §" in clause or "HTML " in clause
    ]
    assert len(from_standard) >= 8, from_standard


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("ISO-8859-1", "cp1252"),
        ("iso_8859-1", "cp1252"),
        ("  latin1  ", "cp1252"),
        ("us-ascii", "cp1252"),
        ("UTF8", "utf-8"),
    ],
)
def test_labels_resolve_per_the_standard(label: str, expected: str) -> None:
    assert encoding_for(label) == expected


def test_iso_8859_1_is_windows_1252_and_not_the_stdlib_reading() -> None:
    """The trap the stdlib walks into.

    `codecs.lookup("iso-8859-1")` is true Latin-1, where 0x92 is an undefined
    C1 control. Encoding §4.2 puts that label in the windows-1252 index, where
    it is a right single quotation mark — and boards are authored against what
    browsers do.
    """
    assert decode_body(b"don\x92t", "iso-8859-1") == "don\u2019t"
    assert b"don\x92t".decode("latin-1") != "don\u2019t", "the premise: the stdlib differs"


def test_an_undecodable_body_refuses_rather_than_replacing() -> None:
    """The fail-open this task exists to close: `errors="replace"` gives
    `T�cnico`, which downstream is indistinguishable from an
    advert that really said that."""
    with pytest.raises(ConnectorError, match="does not decode"):
        decode_body("Técnico".encode("cp1252"), "utf-8")


def test_a_bom_wins_over_the_declared_charset_and_is_removed() -> None:
    assert decode_body(b"\xef\xbb\xbfHola", "iso-8859-1") == "Hola"
    assert "﻿" not in decode_body(b"\xef\xbb\xbfHola", "utf-8")


def test_an_unknown_charset_will_not_load() -> None:
    with pytest.raises(ConnectorError, match="unknown charset label"):
        parse_connector(_MINIMAL.format(extra="charset: banana\n"))


def test_a_replacement_decoder_label_will_not_load() -> None:
    with pytest.raises(ConnectorError, match="replacement decoder"):
        parse_connector(_MINIMAL.format(extra="charset: iso-2022-cn\n"))


def test_the_default_is_utf8_so_every_existing_package_is_unchanged() -> None:
    """The default is the measured status quo, not a guess: all 18 packages
    committed before this existed were serving UTF-8."""
    assert parse_connector(_MINIMAL.format(extra="")).charset == "utf-8"
    for package in connector_packages(DEFAULT_CONNECTORS_DIR):
        assert load_connector(package / "connector.yaml").charset == "utf-8"


def test_no_committed_capture_falls_outside_its_declared_charset() -> None:
    assert measure_charset()["captures_outside_their_charset"] == []
