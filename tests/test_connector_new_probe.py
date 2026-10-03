"""T196 -- the connector-new probe script consults the repo's reader, not its own.

`query_board.py` used to hand the live robots.txt to CPython's `urllib.robotparser`
unconditionally. After T120 the repository's default second reader is a
longest-match one that can refuse where the stdlib cannot, so on any file opening
`Allow: /` the script reported `single_parser` -- an understatement, and a script
whose verdict lags the repo it probes. These tests pin the *property*: the reader
consulted is `connector_policy.DEFAULT_SECOND_READER` read at call time, and the
`standing` it prints is what that reader's behaviour on the file supports.
"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from types import ModuleType

import pytest

from integral import connector_policy, second_reader

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / ".claude" / "skills" / "connector-new" / "scripts" / "query_board.py"

#: Opens `Allow: /` and disallows a longer path: RFC 9309 §2.2.2 (most octets wins)
#: refuses `/search-jobs/python`; a first-match reader meets `Allow: /` first.
LONGER_DISALLOW = "User-agent: *\nAllow: /\nDisallow: /search-jobs\nDisallow: /ajax\n"
#: Disallows only a path nothing we ask about is under: no reader can refuse.
NOTHING_TO_REFUSE = "User-agent: *\nDisallow: /unrelated\n"

URLS = [
    "https://example.test/jobs",
    "https://example.test/search-jobs/python",
    "https://example.test/ajax/x",
]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("query_board_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    return _load()


def _standing(probe: ModuleType, text: str) -> tuple[str, str, str]:
    result: tuple[str, str, str] = probe.second_reader_standing(text, URLS)
    return result


def test_the_probe_uses_the_installed_default_second_reader(
    probe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Resolved at call time: repointing the constant after the script is loaded
    # changes which reader the script hands to the verdict, on the very same bytes.
    # The reader is observed rather than inferred from a verdict, because CPython's
    # own parser changed behaviour between patch releases (3.13.14 is longest-match)
    # and a test resting on "the stdlib cannot refuse" would pass or fail with the
    # interpreter rather than with the script.
    asked: list[str] = []
    real = probe.second_reader_verdict

    def spy(text: str, urls: list[str], reader: str = "", paths: list[str] | None = None) -> str:
        asked.append(reader)
        return str(real(text, urls, reader=reader, paths=paths))

    monkeypatch.setattr(probe, "second_reader_verdict", spy)
    assert connector_policy.DEFAULT_SECOND_READER == second_reader.NAME
    assert _standing(probe, LONGER_DISALLOW)[0] == second_reader.NAME
    monkeypatch.setattr(connector_policy, "DEFAULT_SECOND_READER", "urllib.robotparser")
    assert _standing(probe, LONGER_DISALLOW)[0] == "urllib.robotparser"
    assert asked == [second_reader.NAME, "urllib.robotparser"]


def test_the_probe_reports_two_parsers_agreed_when_the_reader_refuses(
    probe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = LONGER_DISALLOW.encode()

    class _Response(io.BytesIO):
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *a, **k: _Response(served))
    lines = probe.second_reader(URLS)
    assert "  standing: two_parsers_agreed" in lines
    assert not any("single_parser" in line for line in lines)
    assert "refused 2 of 3 path(s)" in lines[0]


def test_the_probe_still_reports_single_parser_when_the_reader_cannot_refuse(
    probe: ModuleType,
) -> None:
    reader, verdict, standing = _standing(probe, NOTHING_TO_REFUSE)
    assert reader == second_reader.NAME
    assert standing == "single_parser"
    assert verdict.startswith("RAN AND COULD NOT REFUSE")


def test_a_reader_that_cannot_be_run_is_single_parser_not_agreement(
    probe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An unknown reader name and an unreadable file are "could not be run".
    monkeypatch.setattr(connector_policy, "DEFAULT_SECOND_READER", "someone.elses")
    _, verdict, standing = _standing(probe, LONGER_DISALLOW)
    assert (standing, verdict.startswith("not run")) == ("single_parser", True)

    def refuse(*_: object, **__: object) -> None:
        raise OSError("no network")

    monkeypatch.setattr(probe.urllib.request, "urlopen", refuse)
    assert probe.second_reader(URLS)[-1] == "  standing: single_parser"


def test_the_reader_is_handed_request_targets_with_their_query(probe: ModuleType) -> None:
    # `allows` refuses a full URL; and a rule naming a query only bites if the
    # query reaches the reader.
    assert probe.request_target("https://h.test/a/b?x=1&y=2") == "/a/b?x=1&y=2"
    assert probe.request_target("https://h.test") == "/"
    text = "User-agent: *\nDisallow: /*?session=\n"
    urls = ["https://h.test/jobs", "https://h.test/jobs?session=9"]
    _, verdict, standing = probe.second_reader_standing(text, urls)
    assert standing == "two_parsers_agreed", verdict


def test_a_target_the_reader_declines_is_no_agreement_and_does_not_crash(
    probe: ModuleType,
) -> None:
    # `//admin` is refused by the reader as ambiguous with a network-path reference.
    # The probe must report "could not be run", never raise and never agree.
    text = "User-agent: *\nDisallow: /admin\n"
    _, verdict, standing = probe.second_reader_standing(
        text, ["https://h.test/jobs", "https://h.test//admin"]
    )
    assert standing == "single_parser"
    assert verdict.startswith("not run")


ROBOTS_API = "User-agent: *\nDisallow: /api\n"
API_URLS = ["https://h.test/jobs", "https://h.test/api/v1"]


def test_a_newly_registered_default_reader_is_the_one_called_and_its_verdict_decides(
    probe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A reader swap is a new name in READERS plus the constant pointing at it. The
    # reader must actually be called, and what it says -- not CPython's parser under
    # its name -- must set the standing.
    calls: list[tuple[str, str]] = []

    def always_allow(text: str, agent: str, target: str) -> bool:
        calls.append((agent, target))
        return True

    monkeypatch.setitem(connector_policy.READERS, "spy.allow", always_allow)
    monkeypatch.setattr(connector_policy, "DEFAULT_SECOND_READER", "spy.allow")
    reader, verdict, standing = probe.second_reader_standing(ROBOTS_API, API_URLS)
    assert reader == "spy.allow"
    assert [target for _, target in calls] == ["/jobs", "/api/v1"]
    # The stdlib would refuse /api/v1 here; the spy does not, so no agreement.
    assert (standing, verdict.startswith("RAN AND COULD NOT REFUSE")) == ("single_parser", True)

    refusing_api: list[str] = []

    def refuses_api(text: str, agent: str, target: str) -> bool:
        refusing_api.append(target)
        return not target.startswith("/api")

    monkeypatch.setitem(connector_policy.READERS, "spy.refuse", refuses_api)
    monkeypatch.setattr(connector_policy, "DEFAULT_SECOND_READER", "spy.refuse")
    # A file the stdlib and the repo reader both allow entirely: only the spy refuses.
    _, _, standing = probe.second_reader_standing("User-agent: *\nDisallow: /zzz\n", API_URLS)
    assert (standing, refusing_api) == ("two_parsers_agreed", ["/jobs", "/api/v1"])


def test_a_default_reader_that_raises_is_single_parser(
    probe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []

    def explodes(text: str, agent: str, target: str) -> bool:
        called.append(target)
        raise RuntimeError("reader broke")

    monkeypatch.setitem(connector_policy.READERS, "spy.raise", explodes)
    monkeypatch.setattr(connector_policy, "DEFAULT_SECOND_READER", "spy.raise")
    _, verdict, standing = probe.second_reader_standing(ROBOTS_API, API_URLS)
    assert called, "the registered reader was never called"
    assert (standing, verdict.startswith("not run")) == ("single_parser", True)
