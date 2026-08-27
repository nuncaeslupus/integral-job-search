"""The fetch rule the collector is bound by, checked without a network.

The interesting cases are the ones where a wrong answer is silent. A client
that names itself honestly is governed by a site's `User-agent: *` block; a
client that calls itself Claude is governed by the `Disallow: /` block both of
these boards keep for AI crawlers. Same file, same path, opposite answers — so
the identity is not a detail of the request, it is the input to the decision.
"""

from __future__ import annotations

import time
import urllib.error

import pytest

from integral.robots import (
    USER_AGENT,
    Robots,
    RobotsError,
    _allowed,
    _canon,
    _matches,
    _normalize_rule,
    _product_token,
    _request_path,
    measure,
)

# Trimmed from the live files on 2026-08-24, keeping the groups that decide the
# cases below. Frozen on purpose: a test that re-fetches measures the boards'
# mood today, not this code.
TECNOEMPLEO = """
User-agent: *
Disallow: /profesionales/
Disallow: /_ajax/select_ajax.php
Disallow: /accesoempresa.php

User-agent: ClaudeBot
Disallow: /

User-agent: anthropic-ai
Disallow: /

User-agent: Bingbot
Crawl-delay: 5
"""

REMOTEOK = """
User-agent: *
Crawl-delay: 1
Allow: /
Disallow: /track-ad
"""


def _robots(files: dict[str, str], user_agent: str = USER_AGENT) -> Robots:
    def fetch(url: str) -> str:
        if url not in files:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        return files[url]

    return Robots(user_agent=user_agent, fetch=fetch)


TECNO_ROBOTS = "https://www.tecnoempleo.com/robots.txt"
TECNO_LISTING = "https://www.tecnoempleo.com/ofertas-trabajo/?te=teletrabajo"


def test_an_honestly_named_client_may_read_the_listings() -> None:
    """The `*` block does not disallow them, and `*` is the block that applies."""
    assert _robots({TECNO_ROBOTS: TECNOEMPLEO}).allows(TECNO_LISTING)


def test_the_same_path_is_refused_to_a_client_calling_itself_claude() -> None:
    """The identity decides it. This is why the user agent may not be invented."""
    assert not _robots({TECNO_ROBOTS: TECNOEMPLEO}, "ClaudeBot").allows(TECNO_LISTING)
    assert not _robots({TECNO_ROBOTS: TECNOEMPLEO}, "anthropic-ai").allows(TECNO_LISTING)


def test_a_disallowed_path_is_refused_to_everyone() -> None:
    robots = _robots({TECNO_ROBOTS: TECNOEMPLEO})
    assert not robots.allows("https://www.tecnoempleo.com/profesionales/alguien")
    assert not robots.allows("https://www.tecnoempleo.com/accesoempresa.php")


def test_a_missing_robots_txt_permits_everything() -> None:
    """404 is the site saying it has no rules — the one absence that is a yes."""
    assert _robots({}).allows("https://nowhere.example/ofertas")


@pytest.mark.parametrize("failure", [500, 403, 503])
def test_an_unreadable_robots_txt_refuses_rather_than_assumes(failure: int) -> None:
    """An unanswered question is not a yes. Absent rules are not permissive rules."""

    def fetch(url: str) -> str:
        raise urllib.error.HTTPError(url, failure, "nope", {}, None)  # type: ignore[arg-type]

    with pytest.raises(RobotsError):
        Robots(fetch=fetch).allows("https://example.test/ofertas")


def test_a_network_failure_refuses_too() -> None:
    def fetch(url: str) -> str:
        raise OSError("connection reset")

    with pytest.raises(RobotsError):
        Robots(fetch=fetch).allows("https://example.test/ofertas")


def test_the_sites_crawl_delay_wins_when_it_is_slower_than_ours() -> None:
    robots = _robots({"https://remoteok.com/robots.txt": REMOTEOK})
    assert robots.delay("https://remoteok.com/remote-jobs", floor=0.4) == 1.0


def test_our_floor_wins_when_the_site_asks_for_nothing() -> None:
    robots = _robots({TECNO_ROBOTS: TECNOEMPLEO})
    assert robots.delay(TECNO_LISTING, floor=0.4) == 0.4


def test_robots_txt_is_read_once_per_host() -> None:
    """A fetch per advert would be its own politeness problem."""
    reads: list[str] = []

    def fetch(url: str) -> str:
        reads.append(url)
        return TECNOEMPLEO

    robots = Robots(fetch=fetch)
    for path in ("uno", "dos", "tres"):
        robots.allows(f"https://www.tecnoempleo.com/{path}")
    assert reads == [TECNO_ROBOTS]


def test_each_host_is_asked_separately() -> None:
    robots = _robots({TECNO_ROBOTS: TECNOEMPLEO, "https://remoteok.com/robots.txt": REMOTEOK})
    assert not robots.allows("https://www.tecnoempleo.com/profesionales/x")
    assert robots.allows("https://remoteok.com/profesionales/x")


def test_the_declared_user_agent_names_the_tool_and_carries_a_contact() -> None:
    """Not a browser string. A board that wants this to stop needs somewhere to say so."""
    assert "Mozilla" not in USER_AGENT
    assert "integral-job-search" in USER_AGENT
    assert "https://" in USER_AGENT


def test_a_blank_line_inside_a_record_does_not_end_it() -> None:
    """A `Disallow: /` after a blank line still binds its agent group.

    `urllib.robotparser` reads the blank line as the record's end, so the
    `Disallow: /` that follows binds nothing — a board that disallowed
    ClaudeBot outright then reads as *permitting* it. That is the fail-open
    direction, and it is the dangerous one (see the module docstring).
    """
    robots_txt = """
User-agent: ClaudeBot

Disallow: /
"""
    robots = _robots({"https://blanks.example/robots.txt": robots_txt}, "ClaudeBot")
    assert not robots.allows("https://blanks.example/anything")


def test_longest_match_wins_over_file_order() -> None:
    """`Allow: /jobs/public/` beats an earlier, shorter `Disallow: /jobs/` (RFC 9309 §2.2.2)."""
    robots_txt = """
User-agent: *
Disallow: /jobs/
Allow: /jobs/public/
"""
    robots = _robots({"https://longest.example/robots.txt": robots_txt})
    assert robots.allows("https://longest.example/jobs/public/x")
    assert not robots.allows("https://longest.example/jobs/private")


def test_allow_beats_disallow_on_an_equal_length_tie() -> None:
    robots_txt = """
User-agent: *
Disallow: /x
Allow: /x
"""
    robots = _robots({"https://tie.example/robots.txt": robots_txt})
    assert robots.allows("https://tie.example/x")


def test_duplicate_groups_for_one_token_are_combined_not_first_wins() -> None:
    """RFC 9309 §2.2.1: repeated groups for the same token are merged."""
    robots_txt = """
User-agent: ClaudeBot
Disallow: /a

User-agent: Other
Disallow: /b

User-agent: ClaudeBot
Disallow: /c
"""
    robots = _robots({"https://dup.example/robots.txt": robots_txt}, "ClaudeBot")
    assert not robots.allows("https://dup.example/a")
    assert not robots.allows("https://dup.example/c")
    assert robots.allows("https://dup.example/b")


def test_an_explicit_token_group_is_not_merged_with_the_wildcard() -> None:
    """The most specific token applies exclusively; `*` is a fallback, not an addition."""
    robots_txt = """
User-agent: *
Allow: /

User-agent: ClaudeBot
Disallow: /
"""
    robots = _robots({"https://specific.example/robots.txt": robots_txt}, "ClaudeBot")
    assert not robots.allows("https://specific.example/jobs")


def test_the_gate_does_not_pass_on_an_empty_input_set() -> None:
    """A zero-violation count over zero evaluated fixtures is not a pass."""
    measured = measure(())
    assert measured["robots_verdicts_evaluated"] == 0
    assert measured["gate_status"] == "unmeasured"


def test_the_fixture_table_itself_evaluates_clean() -> None:
    measured = measure()
    assert measured["robots_verdicts_evaluated"] > 0
    assert measured["robots_verdicts_misread"] == 0, measured["misread_cases"]


def test_an_adversarial_wildcard_rule_matches_in_bounded_time() -> None:
    """A remote robots.txt is attacker-controlled input: any site can serve one.

    The regex matcher this replaced expanded each `*` to a greedy `.*`, so
    `/*a*a*a...b` against a long path with no final `b` backtracked
    catastrophically — measured hanging past 60s, which turns a politeness
    check into a denial of service against ourselves. The linear matcher must
    answer immediately.
    """
    rule = "/" + "a" * 1 + "".join("*a" for _ in range(30)) + "b"
    chunks, anchored = _normalize_rule(rule)
    started = time.monotonic()
    assert _matches(chunks, anchored, "/" + "a" * 5000) is False
    assert time.monotonic() - started < 1.0


def test_a_percent_encoded_asterisk_is_not_a_wildcard() -> None:
    """`%2A` is how a rule spells a literal asterisk. Decoding it into the
    pattern character would silently widen every rule that contains one."""
    chunks, anchored = _normalize_rule("/a%2Ab")

    assert _matches(chunks, anchored, _request_path("https://x.test/a*b")) is True
    assert _matches(chunks, anchored, _request_path("https://x.test/axb")) is False


def test_specificity_counts_the_wildcard_octets() -> None:
    """RFC 9309 §2.2.2 picks the longest matching *pattern*. Splitting a rule
    on `*` drops those octets, so the length has to add them back — otherwise
    a wildcard rule silently loses precedence contests it should win."""
    rules = [(False, "/a/b/c"), (True, "/a*b*c")]  # disallow 6, allow 6 -> allow wins the tie

    assert _allowed(rules, "/a/b/c") is True


def test_a_raw_percent_canonicalises_to_its_escape() -> None:
    """RFC 9309 §2.2.2 compares octets, and a `%` that heads no escape is a
    literal one. Leaving it raw spelled the same octet two ways, so
    `Disallow: /100%25` never matched `/100%` and the fetch was permitted."""
    assert _canon("/100%") == _canon("/100%25") == "/100%25"
    assert _canon("/a%2Ab") == "/a%2Ab"  # a real escape is still not re-encoded


def test_an_empty_query_keeps_its_delimiter() -> None:
    """`urlsplit` reports an empty query for both `/foo` and `/foo?`, but they
    are different request targets and only the second is caught by
    `Disallow: /foo?`. Testing the query alone dropped the delimiter."""
    assert _request_path("https://x.test/search?") == "/search?"
    assert _request_path("https://x.test/search") == "/search"
    assert _request_path("https://x.test/search?#frag") == "/search?"


def test_a_single_product_identification_string_yields_its_token() -> None:
    """The ordinary case, including the `(+url)` comment we actually send."""
    assert _product_token("integral-job-search/0.1 (+https://x.test)") == "integral-job-search"
    assert _product_token("ClaudeBot") == "ClaudeBot"


def test_a_browser_style_agent_naming_two_products_is_refused() -> None:
    """RFC 9309 §2.2.1 gives a crawler one product token, so a string naming
    two has no correct answer. Splitting on the first `/` answered `Mozilla`,
    which reads the group written for browsers and ignores the one written for
    us by name — a fail-open, and exactly what T71's browser agent produces."""
    with pytest.raises(RobotsError, match="more than one product"):
        _product_token("Mozilla/5.0 (compatible; integral-job-search/0.1; +https://x.test)")

    with pytest.raises(RobotsError, match="no product token"):
        _product_token("   ")
