"""T171: a steerable connector's query must sit where a capture recorded one."""

from __future__ import annotations

import ast
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote, urlsplit

import pytest

from integral import query_capture as qc
from integral.connectors import (
    DEFAULT_CONNECTORS_DIR,
    accepts_query,
    build_list_urls,
    load_connector,
)

_STEERABLE = tuple(
    package.name
    for package in sorted(DEFAULT_CONNECTORS_DIR.iterdir())
    if (package / "connector.yaml").is_file() and accepts_query(load_connector(package))
)


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "connectors"
    shutil.copytree(DEFAULT_CONNECTORS_DIR, root)
    return root


def _swap_query_key(package: Path) -> str:
    """Move `{query}` to a URL position no capture carried; return the new pattern.

    A query-string key gets a suffix. A path segment gets a prefix. Either way
    the connector still loads and sends the terms, only somewhere else.
    """
    yaml_path = package / "connector.yaml"
    text = yaml_path.read_text(encoding="utf-8")
    pattern = load_connector(package).list.url_pattern
    swapped, keys = re.subn(r"([?&][^=&?#]+)=\{query\}", r"\1_swapped={query}", pattern)
    if not keys:
        swapped = pattern.replace("{query}", "swapped-{query}")
    assert swapped != pattern
    assert text.count(pattern) == 1
    yaml_path.write_text(text.replace(pattern, swapped), encoding="utf-8")
    assert load_connector(package).list.url_pattern == swapped
    return swapped


def test_the_library_is_clean_and_meets_the_floor() -> None:
    measured = qc.measure()
    assert measured["findings"] == []
    assert measured["gate_status"] == "measured"
    assert measured["steerable_packages_checked"] == len(_STEERABLE)
    assert len(_STEERABLE) >= qc.MINIMUM_STEERABLE_PACKAGES_CHECKED


@pytest.mark.parametrize("name", _STEERABLE)
def test_swapping_a_steerable_packages_query_key_fails_it_by_name(library: Path, name: str) -> None:
    """The second reader's mutation on #447, derived from the library, not listed."""
    _swap_query_key(library / name)
    measured = qc.measure(library)
    assert [row["package"] for row in measured["findings"]] == [name]
    assert "did not load" not in measured["findings"][0]["reason"]


def test_jobfluents_pre_fix_probe_is_named(library: Path) -> None:
    """The live instance on `main` before T171: a probe that never carried `q`."""
    capture = library / "jobfluent_es" / "probe" / "captured.json"
    record = json.loads(capture.read_text(encoding="utf-8"))
    record["url"] = "https://www.jobfluent.com/es/empleos-barcelona?page=2"
    capture.write_text(json.dumps(record), encoding="utf-8")
    assert [row["package"] for row in qc.measure(library)["findings"]] == ["jobfluent_es"]


def test_a_steerable_package_with_no_capture_is_named(library: Path) -> None:
    name = _STEERABLE[0]
    (library / name / "probe" / "captured.json").unlink()
    assert [row["package"] for row in qc.measure(library)["findings"]] == [name]


def test_an_unreadable_package_is_named_not_skipped(library: Path) -> None:
    """Whether it is steerable is unknown, so it cannot be scored as clean."""
    name = _STEERABLE[0]
    (library / name / "connector.yaml").write_text("list: [", encoding="utf-8")
    measured = qc.measure(library)
    assert [row["package"] for row in measured["findings"]] == [name]
    assert "did not load" in measured["findings"][0]["reason"]


@pytest.mark.parametrize(
    ("pattern", "captured", "measured"),
    [
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=python&page=2", True),
        ("https://b.test/jobs?q={query}", "https://b.test/jobs?q=product+manager", True),
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?page=2", False),
        # Empty asks for nothing, so the board's answer is its whole list.
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=&page=2", False),
        # `url_pattern` copied into the capture with the placeholder unfilled.
        ("https://b.test/jobs?q={query}", "https://b.test/jobs?q={query}", False),
        # A fixed duplicate of the key: the capture must carry both.
        ("https://b.test/jobs?q=all&q={query}", "https://b.test/jobs?q=python", False),
        ("https://b.test/jobs/{query}/", "https://b.test/jobs/python/", True),
        ("https://b.test/jobs/{query}/", "https://b.test/jobs//", False),
        ("https://b.test/jobs/{query}/", "https://b.test/jobs/python/extra/", False),
        ("https://b.test/jobs/{query}/", "https://b.test/other/python/", False),
        ("https://b.test/jobs?q={query}", None, False),
        # Second read on #461, F1: blank once decoded, so `build_list_urls`
        # would have refused to send it.
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=+&page=2", False),
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=%20&page=2", False),
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=%09&page=2", False),
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q= &page=2", False),
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=\t&page=2", False),
        ("https://b.test/trabajo-de-{query}", "https://b.test/trabajo-de-+", False),
        ("https://b.test/trabajo-de-{query}", "https://b.test/trabajo-de-%20", False),
        # F2: each delimiter ends the position, leaving the query empty.
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=&x=1&page=2", False),
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=#x&page=2", False),
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=;x&page=2", False),
        ("https://b.test/jobs/{query}/", "https://b.test/jobs/?x/", False),
        ("https://b.test/jobs/{query}/", "https://b.test/jobs/#x/", False),
        (
            "https://b.test/jobs?q={query}&page={page}",
            "https://b.test/jobs?q=python&page=two",
            False,
        ),
        # F3: a dot-segment is removed from the path, and the query with it.
        ("https://b.test/jobs/{query}/", "https://b.test/jobs/../", False),
        ("https://b.test/jobs/{query}/", "https://b.test/jobs/./", False),
        ("https://b.test/jobs/{query}/", "https://b.test/jobs/%2E%2E/", False),
        # ...but in the query component `..` is a literal search.
        ("https://b.test/jobs?q={query}", "https://b.test/jobs?q=..", True),
        # F4: the placeholder, escaped as a browser would copy it.
        ("https://b.test/jobs?q={query}", "https://b.test/jobs?q=%7Bquery%7D", False),
        ("https://b.test/jobs/{query}/", "https://b.test/jobs/%7Bquery%7D/", False),
        # Filled, in the spellings the connector and a browser really send.
        ("https://b.test/jobs?q={query}", "https://b.test/jobs?q=t%C3%A9cnico%20farmacia", True),
        ("https://b.test/jobs?q={query}", "https://b.test/jobs?q=t%C3%A9cnico+farmacia", True),
        ("https://b.test/jobs/{query}/", "https://b.test/jobs/data-scientist/", True),
        # Round 2, R2-1 / O1: every slot, and the same query in each.
        ("https://b.test/{query}/x?q={query}", "https://b.test/python/x?q=python", True),
        ("https://b.test/{query}/x?q={query}", "https://b.test/python/x?q=+", False),
        ("https://b.test/{query}/x?q={query}", "https://b.test/+/x?q=python", False),
        ("https://b.test/{query}/x?q={query}", "https://b.test/python/x?q=java", False),
        # R2-2: a `%` must be an escape the encoder writes.
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=%#x&page=2", False),
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=%&x&page=2", False),
        ("https://b.test/jobs/{query}/", "https://b.test/jobs/%/./", False),
        ("https://b.test/jobs?q={query}", "https://b.test/jobs?q=%2", False),
        ("https://b.test/jobs?q={query}", "https://b.test/jobs?q=%FF", False),
        # Lower-case hex is not how `quote` spells it (fail-closed, and visible).
        ("https://b.test/jobs?q={query}", "https://b.test/jobs?q=t%c3%a9cnico", False),
        # R2-3: the page is ASCII digits and at least one of them.
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=python&page=", False),
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=python&page=٢", False),
        # R2-4: a fragment is never sent (RFC 3986 §3.5), so it measures nothing.
        ("https://b.test/jobs?page={page}#q={query}", "https://b.test/jobs?page=2#q=python", False),
        ("https://{query}.b.test/jobs", "https://python.b.test/jobs", False),
        # R2-5: the component is RFC 3986's, not "after a `?` or a `=`".
        ("https://b.test/s=1/{query}/", "https://b.test/s=1/../", False),
        ("https://b.test/s=1/{query}/", "https://b.test/s=1/a+b/", False),
        ("https://b.test/s=1/{query}/", "https://b.test/s=1/a%20b/", True),
    ],
)
def test_query_measured(pattern: str, captured: str | None, measured: bool) -> None:
    assert qc.query_measured(pattern, captured) is measured


@pytest.mark.parametrize("in_query_component", [True, False])
@pytest.mark.parametrize("char", [chr(code) for code in range(0x20, 0x7F)])
def test_the_raw_alphabet_is_the_one_the_connector_encodes_in(
    char: str, in_query_component: bool
) -> None:
    """Derived from `quote`, not listed: a raw character is accepted exactly when
    `build_list_urls`' encoder would leave it as it is, plus `+` in the query
    component. An enumeration of delimiters has no last element (F2)."""
    pattern = "https://b.test/jobs?q={query}" if in_query_component else "https://b.test/j/{query}/"
    captured = pattern.replace("{query}", f"x{char}x")
    expected = quote(char, safe="") == char or (char == "+" and in_query_component)
    assert qc.query_measured(pattern, captured) is expected


#: RFC 3986 §2.3, written out from the RFC rather than read off `quote`.
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


@pytest.mark.parametrize("in_query_component", [True, False])
@pytest.mark.parametrize("octet", range(256))
def test_an_escape_is_accepted_only_where_an_encoder_writes_one(
    octet: int, in_query_component: bool
) -> None:
    """Round 2, R2-2: the shape of a `%` escape was a regex nobody tested.

    The expectation comes from the RFC, not from the code. An encoder escapes
    exactly the octets that are not unreserved, in upper case (§2.1). A lone
    octet at or above 0x80 is not UTF-8, so no query string encodes to it.
    """
    pattern = "https://b.test/jobs?q={query}" if in_query_component else "https://b.test/j/{query}/"
    for escape in {f"%{octet:02X}", f"%{octet:02x}"}:
        captured = pattern.replace("{query}", f"x{escape}x")
        expected = octet < 0x80 and chr(octet) not in _UNRESERVED and escape == escape.upper()
        assert qc.query_measured(pattern, captured) is expected, escape


_AWKWARD_QUERIES = ("python", "técnico farmacia", "c++", "a/b", "x&y=z", "50%", "{x}", " a ")


@pytest.mark.parametrize("name", _STEERABLE)
@pytest.mark.parametrize("query", _AWKWARD_QUERIES)
def test_every_url_the_connector_sends_is_accepted(name: str, query: str) -> None:
    """The fail-closed mirror: nothing `build_list_urls` sends reads as unmeasured."""
    connector = load_connector(DEFAULT_CONNECTORS_DIR / name)
    for url in build_list_urls(connector, query=query):
        assert qc.query_measured(connector.list.url_pattern, url), url


@pytest.mark.parametrize("query", _AWKWARD_QUERIES)
def test_every_url_a_path_slot_connector_sends_is_accepted(library: Path, query: str) -> None:
    """The mirror for a path slot, which no package on `main` has yet (O2).

    `..` is left out on purpose. `build_list_urls` sending it into a path is a
    defect of its own, filed separately, and this rule is right to refuse it.
    """
    package = next(
        library / name
        for name in _STEERABLE
        if load_connector(library / name).list.pagination.mode == "none"
    )
    parts = urlsplit(load_connector(package).list.url_pattern)
    moved = f"{parts.scheme}://{parts.netloc}/search/{{query}}/"
    yaml_path = package / "connector.yaml"
    old = load_connector(package).list.url_pattern
    yaml_path.write_text(yaml_path.read_text(encoding="utf-8").replace(old, moved), "utf-8")
    connector = load_connector(package)
    assert connector.list.url_pattern == moved
    for url in build_list_urls(connector, query=query):
        assert qc.query_measured(moved, url), url


def test_jobfluents_committed_bytes_carry_no_session_token_or_client_ip() -> None:
    """What `jobfluent_es/meta.yaml` says the build asserts, and the live probe
    relies on. Until the second read on #461 nothing asserted either. Every
    `value`/`content` on a tag naming either token, in any attribute order and
    any quoting, must read `REDACTED` (O4)."""
    package = DEFAULT_CONNECTORS_DIR / "jobfluent_es"
    files = [*package.glob("fixture/*.html"), *package.glob("probe/*.html")]
    assert len(files) >= 3
    # A tag whose `name` is a token field. `<meta name="csrf-param"
    # content="authenticity_token">` names the parameter and holds no token.
    tag = re.compile(
        r"""<[^>]*\bname\s*=\s*["']?(?:authenticity_token|csrf-token)\b[^>]*>""", re.IGNORECASE
    )
    attribute = re.compile(
        r"""\b(?:value|content)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE
    )
    ipv4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    tags_read = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        for found in tag.findall(text):
            tags_read += 1
            values = {"".join(groups) for groups in attribute.findall(found)}
            assert values <= {"REDACTED"}, (path, found)
        assert not ipv4.search(text), path
    # The live probe carries both fields, so a pattern that reads nothing fails.
    assert tags_read >= 2


def test_below_the_floor_reads_unmeasured_writes_nothing_and_exits_1(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in _STEERABLE[: len(_STEERABLE) - qc.MINIMUM_STEERABLE_PACKAGES_CHECKED + 1]:
        shutil.rmtree(library / name)
    evidence = tmp_path / "T171.json"
    assert qc.write_evidence(evidence, library)["gate_status"] == "unmeasured"
    assert not evidence.exists()
    monkeypatch.setattr(qc, "DEFAULT_CONNECTORS_DIR", library)
    assert qc._main(["query_capture", str(evidence)]) == 1


def test_a_finding_exits_1(library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _swap_query_key(library / _STEERABLE[0])
    monkeypatch.setattr(qc, "DEFAULT_CONNECTORS_DIR", library)
    assert qc._main(["query_capture", str(tmp_path / "T171.json")]) == 1


def test_the_floor_is_a_literal_and_is_what_the_evidence_commits() -> None:
    """T122's pin, read over every assignment (`ast.walk`, per T160)."""
    tree = ast.parse(Path(qc.__file__).read_text(encoding="utf-8"))
    bound = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "MINIMUM_STEERABLE_PACKAGES_CHECKED"
            for t in node.targets
        )
    ]
    assert len(bound) == 1
    assert isinstance(bound[0], ast.Constant)
    assert isinstance(bound[0].value, int)
    committed = json.loads(qc.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert committed["steerable_packages_checked_at_least"] == bound[0].value
    assert "steerable_packages_checked" not in committed
