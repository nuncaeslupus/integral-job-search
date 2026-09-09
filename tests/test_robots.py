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
from pathlib import Path

import pytest

from integral import robots as robots_module
from integral.robots import (
    _RESERVED,
    FIXTURES,
    FIXTURES_AT_LEAST,
    REFUSAL_FIXTURES,
    USER_AGENT,
    Robots,
    RobotsError,
    _allowed,
    _anchored_spelling,
    _canon,
    _canon_region,
    _find_spelling,
    _Fixture,
    _main,
    _match_octets,
    _matches,
    _normalize_rule,
    _product_token,
    _region_of,
    _request_path,
    measure,
    measure_browser_recovery,
)

#: Floors for the two scoring sites `_match_octets` feeds, asserted separately.
#: One number over both would stay green on a population that had drained out of
#: the anchored branch — which is precisely how reverting the anchored count to
#: `run[0][0]` survived the full gate. See
#: `test_a_rule_scores_what_the_same_rule_spelled_explicitly_would_score`.
UNANCHORED_PAIRS_COMPARED_AT_LEAST = 16
ANCHORED_PAIRS_COMPARED_AT_LEAST = 9

#: And for the counts themselves, in
#: `test_the_octets_a_spelling_reports_are_the_octets_that_matched`.
SPELLING_COUNTS_CHECKED_AT_LEAST = 9
ANCHORED_SPELLING_COUNTS_CHECKED_AT_LEAST = 7

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


@pytest.mark.parametrize("failure", [500, 503])
def test_an_unreadable_robots_txt_refuses_rather_than_assumes(failure: int) -> None:
    """An unanswered question is not a yes. Absent rules are not permissive rules.

    403 is excluded here — T71 gives it a browser-agent retry before giving
    up, covered separately below — but 500 and 503 are not the WAF-refusal
    case this module carves an exception for, so they still refuse outright.
    """

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


def test_precedence_is_scored_on_the_spelling_that_matched() -> None:
    """RFC 9309 §2.2.2 weighs "the match that has the most octets".

    A match is an event between a rule and a request, so its octets are the ones
    that were compared. A run whose region the pattern leaves open carries two
    canonical spellings of different lengths — `http%3A//evil` in a path,
    `http%3A%2F%2Fevil` in a query — and only one of them can have matched.

    Scoring the other was a fail-open, and a regression against the behaviour
    that shipped: `Disallow: /*http://evil` matched 19 canonical octets of this
    request and was scored on its 15-octet path spelling, so a strictly shorter
    `Allow` beat it and the request was permitted. The Disallow alone refuses
    it, and so does the same intent written without the `*`.
    """
    path = _request_path("https://x.test/out?url=http://evil.com")
    disallow = _normalize_rule("/*http://evil")
    allow = _normalize_rule("/out?url=http%3A")

    # The count is what changed: the path spelling of that run is 13 octets and
    # the query spelling 17, and it is the query one that met the request.
    assert _match_octets(*disallow, path) == 18  # `/` + `http%3A%2F%2Fevil`
    assert _match_octets(*allow, path) == 18
    # Plus one octet for the `*` that `_normalize_rule` split away, which is
    # what carries the Disallow past the Allow.
    assert _allowed([(False, "/*http://evil"), (True, "/out?url=http%3A")], path) is False


def test_a_wildcard_and_its_wildcard_free_spelling_reach_one_verdict() -> None:
    """§2.2.2 canonicalises prior to comparison, so two spellings of one URI set
    cannot disagree. The `*` form and the fully written form of the same intent
    are checked against the same request and the same competing `Allow`."""
    path = _request_path("https://x.test/out?url=http://evil.com")
    allow = (True, "/out?url=http%3A")

    with_star = _allowed([(False, "/*http://evil"), allow], path)
    without_star = _allowed([(False, "/out?url=http%3A%2F%2Fevil"), allow], path)

    assert with_star == without_star is False


def test_no_shorter_allow_beats_a_wildcard_disallow_that_matched_more() -> None:
    """The finding as a CLASS, not as the one row that exposed it.

    Every `Disallow` whose post-`*` run carries `/` and lands in a query was
    under-scored, so this walks a spread of them against every strictly shorter
    matching `Allow` and requires the longest match to win each time. A single
    triple would pass again the moment a new spelling was mis-scored.
    """
    path = _request_path("https://x.test/out?url=http://evil.com")
    disallows = ["/*http://evil", "/*http://", "/out*http://", "/*%2F/", "/out*//", "/*?"]
    allows = ["/out", "/out?", "/out?url=h", "/out?url=htt", "/out?url=http%3A"]

    def score(pattern: str) -> int | None:
        chunks, anchored = _normalize_rule(pattern)
        octets = _match_octets(chunks, anchored, path)
        return None if octets is None else octets + len(chunks) - 1 + int(anchored)

    compared = 0
    for disallow in disallows:
        refusal = score(disallow)
        assert refusal is not None, f"{disallow} must match the request at all"
        for allow in allows:
            permission = score(allow)
            if permission is None or permission >= refusal:
                continue
            compared += 1
            assert _allowed([(False, disallow), (True, allow)], path) is False, (
                f"{allow!r} scores {permission} and must not beat {disallow!r} at {refusal}"
            )
    assert compared >= 12, f"the class must stay populated; compared {compared}"


def test_a_rule_scores_what_the_same_rule_spelled_explicitly_would_score() -> None:
    """The general form of the precedence finding, in both directions, at BOTH
    scoring sites.

    A run behind a `*` is region-ambiguous, so it carries two canonical
    spellings — and the rule that spells those octets as escapes is not
    ambiguous and carries one. When the ambiguous rule matches through its query
    spelling, it has matched exactly what the explicit rule matches, so the two
    must weigh the same. Scoring the ambiguous rule on its path spelling broke
    that in BOTH directions: a `Disallow` was under-weighed and lost to a
    shorter `Allow` (the fail-open), and an `Allow` was under-weighed and lost
    to a `Disallow` it should have tied or beaten.

    **The octet count is produced in two different places, and the first
    revision of this test reached only one of them.** `_match_octets` scores an
    ordinary run through `_find_spelling` and a `$`-ANCHORED FINAL run through
    `_anchored_spelling`, adding each to the total on its own line. That
    revision carried five unanchored pairs and not one anchored one, so
    reverting the anchored line to `octets + len(run[0][0])` — the identical
    defect this round exists to remove, in the branch the fix forgot — survived
    the whole of `make host-gate` with no evidence drift and permitted 38
    requests the fixed matcher refuses. An invariant whose population never
    reaches the code the invariant is about is not a class-level test.

    So every pair below is weighed TWICE: once as written, where the trailing
    run goes through `_find_spelling`, and once with `$` appended to both sides,
    where it goes through `_anchored_spelling`. A revert at either scoring site
    reddens this.
    """
    pairs = [
        ("/*http://", "/*http%3A%2F%2F"),
        ("/*http://evil", "/*http%3A%2F%2Fevil"),
        ("/*/x", "/*%2Fx"),
        ("/out*//", "/out*%2F%2F"),
        ("/*?y", "/*%3Fy"),
        ("/*://", "/*%3A%2F%2F"),
    ]
    targets = [
        "https://x.test/out?url=http://evil.com",
        "https://x.test/a?b=/x",
        "https://x.test/a/x",
        "https://x.test/q?z=?y",
        "https://x.test/x/http://y",
        # Targets that END on the ambiguous run, so the `$`-anchored form of
        # each pair matches something rather than skipping. Without these the
        # anchored half of the loop is a population of zero.
        "https://x.test/out?url=http://",
        "https://x.test/out?url=http://evil",
        "https://x.test/out?q=//",
        "https://x.test/s?a=?y",
        "https://x.test/p/x",
        "https://x.test/p?q=://",
    ]

    def score(pattern: str, path: str) -> int | None:
        chunks, anchored = _normalize_rule(pattern)
        octets = _match_octets(chunks, anchored, path)
        return None if octets is None else octets + len(chunks) - 1 + int(anchored)

    compared = {"": 0, "$": 0}
    for url in targets:
        path = _request_path(url)
        for ambiguous, explicit in pairs:
            for anchor in ("", "$"):
                weighed = score(ambiguous + anchor, path)
                spelled_out = score(explicit + anchor, path)
                if weighed is None or spelled_out is None:
                    continue
                compared[anchor] += 1
                assert weighed == spelled_out, (
                    f"{ambiguous + anchor!r} scored {weighed} against {path!r} where the "
                    f"same rule written {explicit + anchor!r} scores {spelled_out}"
                )
    # Floored per scoring site, because one number over both would go green on a
    # population that had drained out of the anchored branch entirely — which is
    # the exact shape this test was reworked to close.
    assert compared[""] >= UNANCHORED_PAIRS_COMPARED_AT_LEAST, compared
    assert compared["$"] >= ANCHORED_PAIRS_COMPARED_AT_LEAST, compared


def test_the_octets_a_spelling_reports_are_the_octets_that_matched() -> None:
    """The number itself, not the verdict it feeds.

    `_find_spelling` and `_anchored_spelling` each return how many octets the
    run spent, and `_allowed` scores precedence on it. The test above pins what
    `_allowed` DOES with the number; nothing pinned the number. Returning
    `max(len(text) for text, _ in run)` from `_find_spelling` — the longest
    spelling rather than the one that matched — survives `make host-gate` at
    exit 0 with no evidence drift and permits 26 requests head refuses, because
    the two spellings differ only when the SHORT one matched, and the invariant
    above skips those pairs (the explicit rule spelling the escapes does not
    match a path that carries the octet raw, so there is nothing to compare to).

    So this asserts the contract directly: the count reported is the length of a
    spelling of that run which is literally present in the target at the
    position it was reported for. A count borrowed from the other spelling
    fails, whichever direction it is borrowed in.
    """
    probes = [
        # (pattern, url) — chosen so that between them both spellings of an
        # ambiguous run win: the short path one, and the long query one.
        ("/*/x", "https://x.test/a/x"),
        ("/*/x", "https://x.test/a?b=/x"),
        ("/*?y", "https://x.test/a?b=?y"),
        ("/*?y", "https://x.test/ax?y"),
        ("/*http://", "https://x.test/out?url=http://evil.com"),
        ("/*http://", "https://x.test/x/http://y"),
        ("/*//", "https://x.test/p?q=//"),
        ("/*//", "https://x.test/p//"),
        ("/*://", "https://x.test/p?q=://"),
    ]

    unanchored = anchored = 0
    for pattern, url in probes:
        path = _request_path(url)
        boundary = path.find("?")
        if boundary == -1:
            boundary = len(path)
        chunks, _ = _normalize_rule(pattern)
        for run in chunks[1:]:
            if all(not text for text, _ in run):
                continue
            found = _find_spelling(path, run, 0, boundary)
            if found is not None:
                end, spent = found
                unanchored += 1
                assert any(text == path[end - spent : end] for text, _ in run), (
                    f"{pattern!r} reported {spent} octets ending at {end} of {path!r}, "
                    f"which is {path[end - spent : end]!r} — no spelling of {run}"
                )
            tail = _anchored_spelling(path, run, 0, boundary)
            if tail is not None:
                anchored += 1
                assert any(len(text) == tail and path.endswith(text) for text, _ in run), (
                    f"{pattern!r} reported {tail} anchored octets of {path!r}, "
                    f"which no spelling of {run} ending there has"
                )
    assert unanchored >= SPELLING_COUNTS_CHECKED_AT_LEAST, unanchored
    assert anchored >= ANCHORED_SPELLING_COUNTS_CHECKED_AT_LEAST, anchored


def test_the_query_region_begins_after_the_delimiter_not_at_it() -> None:
    """RFC 3986 §3.4 — the query component is indicated by the first `?` and
    begins AFTER it, so the delimiter is the last octet before the query rather
    than the first octet of it.

    A rule run may therefore end on the delimiter while still being a path
    spelling, which is what `Disallow: /*?$` does. Reading the delimiter's own
    position as query (`>=` rather than `>`) rejects that spelling, the rule
    matches nothing, and the request is permitted — fail-open.
    """
    path = _request_path("https://x.test/x=?")
    assert path == "/x%3D?"
    boundary = path.index("?")

    assert _region_of(boundary - 1, boundary) is False
    assert _region_of(boundary, boundary) is False, "the delimiter is not in the query"
    assert _region_of(boundary + 1, boundary) is True

    chunks, anchored = _normalize_rule("/*?$")
    assert _matches(chunks, anchored, path) is True


def test_a_raw_percent_canonicalises_to_its_escape() -> None:
    """RFC 9309 §2.2.2 compares octets, and a `%` that heads no escape is a
    literal one. Leaving it raw spelled the same octet two ways, so
    `Disallow: /100%25` never matched `/100%` and the fetch was permitted."""
    assert _canon("/100%") == _canon("/100%25") == "/100%25"
    assert _canon("/a%2Ab") == "/a%2Ab"  # a real escape is still not re-encoded


def test_every_reserved_octet_used_as_data_is_encoded_in_both_regions() -> None:
    """RFC 9309 §2.2.2 over RFC 3986 §2.2's whole `reserved` production.

    §2.2.2 requires octets "in the reserved range defined by RFC 3986" to be
    percent-encoded prior to comparison. That is a set, not the two octets its
    example table happens to print, so this walks the set itself rather than a
    list of the cases someone thought of — the exact hole `_CHUNK_SAFE` was: an
    allowlist that left `: & = + , @ ! ; ' ( )` raw in both regions.

    The single exemption is `/` in a PATH, RFC 3986 §3.3's segment separator,
    which is structure and not data. Inside a query it delimits nothing, so
    there it encodes like the rest — which is what makes
    `Disallow: /a?b=https%3A%2F%2Fc` catch `/a?b=https://c`.
    """
    for octet in sorted(_RESERVED):
        in_path = _canon(f"/x{octet}y")
        in_query = _canon(f"/p?q={octet}")
        if octet == "/":
            assert in_path == "/x/y", f"the path separator must not encode: {in_path!r}"
        elif octet == "?":
            # The one raw `?` is the region delimiter itself: it is not an octet
            # in the path, it is the end of the path. A SECOND one is query data
            # and encodes — asserted by the `in_query` check below, which puts
            # this octet after a `?` that has already been consumed.
            assert in_path == "/x?y", f"the query delimiter must survive: {in_path!r}"
        else:
            assert octet not in in_path, f"{octet!r} left raw in a path: {in_path!r}"
        assert in_query.endswith("%3D" + f"%{ord(octet):02X}"), (
            f"{octet!r} left raw in a query: {in_query!r}"
        )


def test_a_rule_and_its_encoded_request_are_one_uri_in_either_region() -> None:
    """The nine T151 cases in miniature, one per region, from the rule's side.

    Both spellings canonicalise to the same octets, which is the only way a
    longest-prefix comparison can see them as one URI. Before the fix each pair
    differed and the rule matched nothing at all — a fail-open, in the matcher
    that decides real fetches.
    """
    assert _canon("/jobs%3Aremote/list") == _canon("/jobs:remote/list")
    assert _canon("/s?q=a%26b") == _canon("/s?q=a&b")
    # And the control that stops this degenerating into "encode everything":
    # a real separator is not the same octet sequence as an encoded one.
    assert _canon("/a/b") != _canon("/a%2Fb")


def test_the_region_flag_threads_across_a_rules_wildcards() -> None:
    """A rule is canonicalised run by run, so the region has to be carried.

    `Disallow: /s?a=1*b=2` splits into `/s?a=1` and `b=2`; the second run lies
    in the query only because the first one opened it. Canonicalising it as a
    path run would leave a `/` in it raw and stop it matching the target's
    encoded one.
    """
    assert _canon_region("/s?a=1", False) == ("/s?a%3D1", True)
    assert _canon_region("u=/x", True) == ("u%3D%2Fx", True)
    assert _canon_region("u=/x", False) == ("u%3D/x", False)


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


# ---------------------------------------------------------------------------
# T102 (issue #236) — does a robots product token match as a prefix of a longer
# crawler token? Case 22 of the round-2 T70 audit, filed rather than committed
# because its citation was a recollection. The verdict below was read off RFC
# 9309 §2.2.1 before the implementation was opened, which is the only order
# that can answer it: deriving it by running the matcher records the matcher's
# behaviour as the specification, and that circularity is what let T70 take ten
# defects across five review rounds.

CASE_22_FIXTURE = "a_file_token_that_is_a_prefix_of_the_crawler_token_does_not_match"


def _fixture(name: str) -> _Fixture:
    return next(f for f in FIXTURES if f.name == name)


def test_a_file_token_shorter_than_the_crawler_token_does_not_match_per_rfc_9309() -> None:
    """RFC 9309 §2.2.1: case is the ONLY relaxation, so `Bot` does not match `Botly`.

    "Crawlers MUST use case-insensitive matching to find the group that matches
    the product token and then obey the rules of the group." No prefix,
    substring or longest-token rule appears anywhere in the document; the one
    substring relation it states runs the other way, between a crawler's
    product token and the identification string it sends. Two of its figures
    say it from the other side as well — one calls the relation "two groups
    that match the same product token exactly", the other declares
    `user-agent: BazBot` a non-match for the crawler `ExampleBot`, two tokens
    that share the suffix `Bot`.

    So the fetch is permitted, by §2.2.1's last clause: no group matches, there
    is no `*` group, and "no rules apply". The name of this test records the
    verdict the spec gave, which is the opposite of the one the audit expected.
    """
    robots_txt = "User-agent: Bot\nDisallow: /private\n"
    robots = _robots({"https://prefix.example/robots.txt": robots_txt}, "Botly/2.0")
    assert robots.allows("https://prefix.example/private")

    # And the direction that matters: reading it as a match would fail OPEN,
    # not closed. An explicitly matched group is used exclusively, so a `Bot`
    # group matched by prefix would displace `*` and permit a path the site
    # disallowed for every crawler.
    with_wildcard = "User-agent: Bot\nDisallow: /other\n\nUser-agent: *\nDisallow: /private\n"
    robots = _robots({"https://prefix2.example/robots.txt": with_wildcard}, "Botly/2.0")
    assert not robots.allows("https://prefix2.example/private")


def test_the_reverse_direction_is_asserted_separately() -> None:
    """File token `Botly`, crawler `Bot` — a different question, same section.

    RFC 9309 §2.2.1 decides it by the same clause and not by the shape of the
    two strings: the crawler's token is `Bot`, the file's group is named
    `Botly`, they are not equal under case folding, so no group matches. With
    no `*` group to fall back to, no rules apply and the fetch is permitted;
    with one, the `*` group applies (the fixture table holds both).

    Asserted separately because the two directions can be got right and wrong
    independently — a matcher doing `file_token in crawler_token` passes the
    first of these and fails nothing here, and a matcher doing the reverse
    fails the first while passing this.
    """
    robots_txt = "User-agent: Botly\nDisallow: /private\n"
    robots = _robots({"https://reverse.example/robots.txt": robots_txt}, "Bot/1.0")
    assert robots.allows("https://reverse.example/private")

    with_wildcard = "User-agent: Botly\nDisallow:\n\nUser-agent: *\nDisallow: /private\n"
    robots = _robots({"https://reverse2.example/robots.txt": with_wildcard}, "Bot/1.0")
    assert not robots.allows("https://reverse2.example/private")


def test_the_case_22_fixture_cites_the_section_it_was_derived_from() -> None:
    """The case is committed as a fixture, with the clause it was read off.

    An audit case answered in a comment and waved through leaves the code
    exactly as unprotected as it was. Being in `FIXTURES` is what makes it
    measured, and the citation is what lets the next reader check the verdict
    against the RFC instead of against the matcher.
    """
    fixture = _fixture(CASE_22_FIXTURE)
    assert "§2.2.1" in fixture.citation
    assert fixture.citation.startswith("RFC 9309")
    assert fixture.agent == "Botly/2.0"
    assert fixture.expected_allowed is True

    # Both companions carry their own citation rather than borrowing this one.
    for name in (
        "a_prefix_file_token_does_not_displace_the_wildcard_group",
        "a_file_token_longer_than_the_crawler_token_does_not_match_with_no_wildcard",
    ):
        assert "§2.2.1" in _fixture(name).citation

    # The measured denominator rose: 56 fixtures before T102, three cases
    # accepted, and the floor moved with them.
    assert FIXTURES_AT_LEAST >= 59
    assert measure()["robots_verdicts_evaluated"] >= FIXTURES_AT_LEAST


def test_a_shrunken_fixture_table_stops_the_build_with_1_not_the_unmeasured_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deleted fixture must be a hard stop, and 3 is not one.

    `make evidence` maps exit 3 to "unmeasured (recorded)" and CONTINUES — the
    right answer for a check that honestly cannot measure yet, and a fail-open
    for this state, where the check ran over fewer cases than it was signed off
    on and still reported a clean zero.
    """
    assert _main(["robots", str(tmp_path / "full.json")]) == 0

    monkeypatch.setattr(robots_module, "FIXTURES", FIXTURES[:2])
    assert _main(["robots", str(tmp_path / "shrunk.json")]) == 1


# ---------------------------------------------------------------------------
# T71 — a browser-agent retry when the honest agent is refused the policy


def test_a_403_on_the_policy_is_retried_with_a_browser_agent() -> None:
    """A WAF refusing the honest identity on `/robots.txt` itself is not an
    answer about what the policy says, so it is not read as one."""
    honest_calls: list[str] = []
    browser_calls: list[str] = []

    def fetch(url: str) -> str:
        honest_calls.append(url)
        raise urllib.error.HTTPError(url, 403, "blocked", {}, None)  # type: ignore[arg-type]

    def browser_fetch(url: str) -> str:
        browser_calls.append(url)
        return "User-agent: *\nDisallow: /internal/\n"

    robots = Robots(fetch=fetch, browser_fetch=browser_fetch)
    assert robots.allows("https://waf.example/ofertas") is True

    assert honest_calls == ["https://waf.example/robots.txt"]
    assert browser_calls == ["https://waf.example/robots.txt"]


def test_only_the_policy_url_is_refetched_never_content() -> None:
    """Exactly one URL per host is eligible for the browser-agent retry: its
    `/robots.txt`. This is not a block-evasion hatch, so nothing else — an
    advert, a listing page — may ever reach `browser_fetch`."""
    browser_calls: list[str] = []

    def fetch(url: str) -> str:
        raise urllib.error.HTTPError(url, 403, "blocked", {}, None)  # type: ignore[arg-type]

    def browser_fetch(url: str) -> str:
        browser_calls.append(url)
        return "User-agent: *\nAllow: /\n"

    robots = Robots(fetch=fetch, browser_fetch=browser_fetch)
    for path in ("ofertas", "profesionales/x", "ofertas/y"):
        robots.allows(f"https://waf.example/{path}")

    # One call total: the retry is cached with the rest of `_groups_for`, and
    # every call it does make names the policy resource, never a content path.
    assert browser_calls == ["https://waf.example/robots.txt"]


def test_a_recovered_policy_is_obeyed_not_ignored() -> None:
    """A policy recovered this way is applied like any other — including when
    it disallows us. Recovering it is not license to read it more loosely."""

    def fetch(url: str) -> str:
        raise urllib.error.HTTPError(url, 403, "blocked", {}, None)  # type: ignore[arg-type]

    def browser_fetch(url: str) -> str:
        return "User-agent: *\nDisallow: /profesionales/\n"

    robots = Robots(fetch=fetch, browser_fetch=browser_fetch)
    assert robots.allows("https://waf.example/ofertas") is True
    assert robots.allows("https://waf.example/profesionales/x") is False


def test_a_403_on_the_policy_and_on_its_retry_still_refuses() -> None:
    """When the browser agent cannot recover the policy either, this is the
    same unanswered question T70 already refuses on — not a new leniency."""

    def fetch(url: str) -> str:
        raise urllib.error.HTTPError(url, 403, "blocked", {}, None)  # type: ignore[arg-type]

    def browser_fetch(url: str) -> str:
        raise urllib.error.HTTPError(url, 403, "still blocked", {}, None)  # type: ignore[arg-type]

    with pytest.raises(RobotsError):
        Robots(fetch=fetch, browser_fetch=browser_fetch).allows("https://waf.example/ofertas")


def test_the_recovery_gate_does_not_pass_on_an_empty_input_set() -> None:
    """A count of zero abandonments over nothing evaluated is not a pass —
    the denominator is asserted, mirroring T70's own gate."""
    measured = measure_browser_recovery()

    assert measured["robots_policies_abandoned_on_refusal_evaluated"] > 0
    assert measured["gate_status"] == "measured"
    assert measured["robots_policies_abandoned_on_refusal"] == 0

    unmeasured = measure_browser_recovery(fixtures=())
    assert unmeasured["robots_policies_abandoned_on_refusal_evaluated"] == 0
    assert unmeasured["gate_status"] == "unmeasured"


def test_the_refusal_fixtures_cover_recovery_and_its_absence() -> None:
    """The table has to exercise both outcomes the mechanism can produce, or
    a gate over only the happy path could not tell a real recovery from one
    that never had to happen."""
    assert any(f.browser_robots_txt is None for f in REFUSAL_FIXTURES)
    assert any(f.browser_robots_txt is not None for f in REFUSAL_FIXTURES)
