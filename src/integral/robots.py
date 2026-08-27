"""Whether a URL may be fetched, according to the site's own robots.txt.

Stdlib only, for the same reason `corpus.py` is: the decision belongs to
`tools/collect_ads.py`, which needs the scraping stack, but the *rule* must be
testable without it.

**The matching is our own, not `urllib.robotparser`'s.** Measured 2026-08-25,
`RobotFileParser` is wrong in both directions: it treats a blank line as the
end of a record, so a real-world file with a blank line inside a group loses
that group's rules — and when that group was a `Disallow: /` for a crawler
naming itself honestly, the loss reads as *permission*. Failing closed on an
ambiguous file is acceptable; failing open on an explicit refusal is not. RFC
9309 does not terminate a group on a blank line — only a new `User-agent`
line, once the current group has started reading directives, does that — so
this module parses groups itself: §2.1 grouping (blank lines are whitespace),
§2.2.1 duplicate-group merging (a token repeated across the file is one
group, not "first one wins"), §2.2.1 most-specific-token selection (an exact
token match is used exclusively; `*` applies only when nothing else does),
and §2.2.2 longest-match precedence with `Allow` winning an equal-length tie.

**The user agent is the whole point.** robots.txt is addressed to whoever the
client says it is, so a client that lies about its identity is not complying
with the file, it is evading it. Both boards this repository has collected from
say so explicitly: `tecnoempleo.com` allows `User-agent: *` on its listings and
`Disallow: /` for nine named AI crawlers, and `remoteok.com` does the same in a
Cloudflare-managed block. An honest name is what makes the `*` rules the ones
that apply.
"""

from __future__ import annotations

import contextlib
import json
import re
import string
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T70.json"

# Who we say we are. A contact URL, because a board that wants this to stop
# needs somewhere to say so — that is the half of politeness a delay cannot do.
USER_AGENT = "integral-job-search/0.1 (+https://github.com/nuncaeslupus/integral-job-search)"

# RFC 9309 §2.2.1: a group is selected by the *product token*, which is a
# substring of the identification string — not the whole `User-Agent` header.
# Matching on the header meant a site's own `User-agent: integral-job-search`
# group never matched us, so we silently fell through to `*` and obeyed the
# wrong rules. On a module named "cannot fail open", that is the failure.
_TOKEN_RE = re.compile(r"[A-Za-z_-]+")
# A *product* is a token followed by a version: `Mozilla/5`, `integral-job-search/0`.
# Requiring the digit is what keeps `(+https://...)` from reading as a second
# product — `https` is followed by `:`, and `//` by no digit.
_PRODUCT_RE = re.compile(r"([A-Za-z_-]+)/\d")


def _product_token(agent: str) -> str:
    """The robots product token inside an identification string.

    `integral-job-search/0.1 (+https://...)` -> `integral-job-search`. A bare
    token (`ClaudeBot`) is returned unchanged, which is what a robots.txt
    actually writes and what the fixtures below use.

    A browser-style string names *several* products —
    `Mozilla/5.0 (compatible; integral-job-search/0.1; +https://...)` names
    `Mozilla` and `integral-job-search` — and RFC 9309 §2.2.1 gives a crawler
    one token, not a list, so there is no correct answer to pick. Splitting on
    the first `/` silently answered `Mozilla`, which reads whichever group the
    site wrote for browsers (usually none) and ignores the group written for
    us by name. That is a fail-open, and it is the one T71 walks into by
    design, since presenting a browser agent is the whole of that task.

    So refuse instead of guessing. `RobotsError` is what the rest of this
    module raises when the rules cannot be established, and an agent whose
    governing group is undecidable is exactly that case.
    """
    products: list[str] = [m.group(1) for m in _PRODUCT_RE.finditer(agent)]
    if len(products) > 1:
        raise RobotsError(
            f"the identification string {agent!r} names more than one product "
            f"({', '.join(products)}), so which robots group governs this crawler is "
            "undecidable; identify with a single product token"
        )
    if products:
        return products[0]
    bare = agent.strip()
    if _TOKEN_RE.fullmatch(bare):
        return bare
    raise RobotsError(
        f"the identification string {agent!r} names no product token, "
        "so no robots group can be matched to this crawler"
    )

Fetch = Callable[[str], str]


class RobotsError(RuntimeError):
    """The site's rules could not be established, so nothing may be fetched."""


def _read(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        return str(response.read().decode("utf-8", errors="replace"))


@dataclass(frozen=True)
class _Group:
    """One `User-agent:` record — the tokens it names and the rules it carries."""

    agents: tuple[str, ...]
    rules: tuple[tuple[bool, str], ...] = field(default_factory=tuple)
    crawl_delay: float | None = None


def _parse_groups(text: str) -> list[_Group]:
    """RFC 9309 §2.1 grouping. A blank line is whitespace, not a terminator.

    A group ends only when a `User-agent` line arrives after the current group
    has already read at least one directive (`Allow`, `Disallow` or
    `Crawl-delay`) — that is what tells consecutive `User-agent` lines ("this
    group has two names") apart from a new group starting.
    """
    groups: list[_Group] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    crawl_delay: float | None = None
    started = False

    def flush() -> None:
        nonlocal agents, rules, crawl_delay, started
        if agents:
            groups.append(_Group(tuple(agents), tuple(rules), crawl_delay))
        agents, rules, crawl_delay, started = [], [], None, False

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field_name, _, value = line.partition(":")
        field_name, value = field_name.strip().lower(), value.strip()

        if field_name == "user-agent":
            if not value:
                continue
            if started:
                flush()
            agents.append(value)
        elif field_name in ("allow", "disallow"):
            if agents:
                # An EMPTY value is a no-op rule, not a rule matching everything.
                # `Disallow:` with nothing after it is the standard idiom for
                # "allow all", and storing it as the pattern `""` made it match
                # every path — so a site using that idiom had its ENTIRE tree
                # read as disallowed and nothing was ever fetched from it. Fail
                # closed, but the candidate sees nothing, which this project
                # counts as the worse failure. `urllib.robotparser` allows these
                # and so must we.
                #
                # It still counts as a directive for grouping: the line is
                # present, so it closes the run of `User-agent` lines above it.
                started = True
                if value:
                    rules.append((field_name == "allow", value))
        elif field_name == "crawl-delay":
            if agents:
                with contextlib.suppress(ValueError):
                    crawl_delay = float(value)
                started = True
        # Any other field (Sitemap, Host, ...) is neither a group boundary nor
        # a rule, so it is read and dropped.
    flush()
    return groups


def _select_rules(groups: list[_Group], agent: str) -> tuple[list[tuple[bool, str]], float | None]:
    """RFC 9309 §2.2.1: the most specific token, with its duplicates merged.

    An explicit token equal to `agent` is used exclusively when one exists —
    a crawler named in its own group is never also governed by `*`. Every
    group carrying that token is combined, because the file may declare it
    more than once (`Disallow` and `Crawl-delay` split across two blocks is
    still one set of rules for one crawler). Only when no explicit token
    matches does the wildcard group apply.
    """
    agent_lower = _product_token(agent).lower()
    explicit = [group for group in groups if any(a.lower() == agent_lower for a in group.agents)]
    matched = explicit or [group for group in groups if "*" in group.agents]
    rules = [rule for group in matched for rule in group.rules]
    delay = next((group.crawl_delay for group in matched if group.crawl_delay is not None), None)
    return rules, delay


# RFC 9309 §2.2.2 comparison rules. A rule and a request target are NOT
# normalised the same way, and conflating them let two excluded paths through:
# `*` is pattern syntax in a rule but an ordinary octet in a target, and `?`
# must survive on both sides or a query rule can never match anything.
_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")

# `%` stays safe so an escape already present is not re-encoded. `*` and `$` are
# both absent on purpose, for one reason: they are the two pattern metacharacters,
# so a rule can only spell either literally as an escape (`%2A`, `%24`). Encoding
# them in the target too is what makes the two sides meet. An earlier revision
# reasoned this out for `*` and then left `$` safe — half the symmetry, so
# `Disallow: /report%24` never matched `/report$` and the target was permitted.
# A raw `%` is NOT safe: it is only ever legitimate as the head of an escape,
# and `_canon` quotes the runs *between* escapes, where any `%` left standing is
# a literal one. Leaving it safe meant `/100%` canonicalised to itself while the
# rule `Disallow: /100%25` canonicalised to `/100%25` — the same octet spelled
# two ways, so the rule never matched and the target was permitted.
_CHUNK_SAFE = "/:@!&'()+,;=?~-._"

_ESCAPE_RE = re.compile(r"%([0-9A-Fa-f]{2})")


def _canon(chunk: str) -> str:
    """One canonical octet form for a literal run of a path.

    Escapes encoding an *unreserved* character are decoded, because `%62` and
    `b` denote the same octet and a `Disallow: /foo/%62ar` that fails to match
    `/foo/bar` is a fail-open. Every other escape is kept and upper-cased, so
    `%2A` survives as `%2A` rather than becoming a wildcard — which is how a
    rule spells a literal asterisk.
    """

    out: list[str] = []
    pos = 0
    for match in _ESCAPE_RE.finditer(chunk):
        out.append(quote(chunk[pos : match.start()], safe=_CHUNK_SAFE))
        char = chr(int(match.group(1), 16))
        out.append(char if char in _UNRESERVED else "%" + match.group(1).upper())
        pos = match.end()
    out.append(quote(chunk[pos:], safe=_CHUNK_SAFE))
    return "".join(out)


def _normalize_rule(pattern: str) -> tuple[list[str], bool]:
    """A rule as canonical literal runs plus its end-anchor flag.

    Splitting on `*` before canonicalising is what keeps the wildcard as
    syntax: only the runs between wildcards are percent-normalised.
    """
    body, anchored = (pattern[:-1], True) if pattern.endswith("$") else (pattern, False)
    return [_canon(chunk) for chunk in body.split("*")], anchored


def _matches(chunks: list[str], anchored: bool, path: str) -> bool:
    """Greedy wildcard match, iterative and bounded — never exponential.

    The previous revision compiled each rule to a regex with `.*` per wildcard.
    Correct, but it backtracks catastrophically: a remote robots.txt could ship
    `/*a*a*a...b$` and hang the crawler on any path lacking the final `b`,
    turning a politeness check into a denial of service against ourselves. Any
    site can serve a robots.txt, so the matcher must be bounded by construction
    rather than by trusting the input.

    Each run is found once, left to right, never reconsidered: O(len(path) x
    len(rule)).
    """
    if not chunks:
        return True
    first, *rest = chunks
    if not path.startswith(first):
        return False
    if not rest:
        return len(path) == len(first) if anchored else True
    position = len(first)
    for index, chunk in enumerate(rest):
        if index == len(rest) - 1 and anchored:
            # The final run must sit flush against the end of the path.
            return len(path) - position >= len(chunk) and path.endswith(chunk)
        if not chunk:
            continue
        found = path.find(chunk, position)
        if found == -1:
            return False
        position = found + len(chunk)
    return True


def _request_path(url: str) -> str:
    """The request target — path and query together — in canonical form."""
    parts = urlsplit(url)
    target = parts.path or "/"
    # `urlsplit` reports an empty query for both `/foo` and `/foo?`, and those
    # are different request targets: `Disallow: /foo?` must catch the second.
    # Testing `parts.query` alone dropped the delimiter and let it through, so
    # look for the delimiter itself, in the URL with any fragment removed.
    if parts.query or "?" in url.split("#", 1)[0]:
        target = f"{target}?{parts.query}"
    return _canon(target)


def _allowed(rules: list[tuple[bool, str]], path: str) -> bool:
    """RFC 9309 §2.2.2: longest match wins; `Allow` wins an equal-length tie.

    No matching rule at all is an implicit allow — the file simply said
    nothing about this path, which is not the same as forbidding it.

    Rule patterns and the request path go through the same canonical percent
    form: comparing a raw pattern against an encoded path is how an excluded
    path slips through.
    """
    best_len, best_allow = -1, True
    for is_allow, pattern in rules:
        chunks, anchored = _normalize_rule(pattern)
        if not _matches(chunks, anchored, path):
            continue
        # Specificity is the length of the PATTERN, metacharacters included:
        # `len(chunks) - 1` restores the `*` octets that splitting removed, and
        # `int(anchored)` the trailing `$` that `_normalize_rule` stripped.
        # Restoring only the wildcards is how `Disallow: /foo/*$` scored 6
        # against `Allow: /foo/x`, tied, and lost to the allow rule — which
        # permits a path the site anchored a rule to exclude.
        length = sum(len(chunk) for chunk in chunks) + len(chunks) - 1 + int(anchored)
        if length > best_len or (length == best_len and is_allow):
            best_len, best_allow = length, is_allow
    return best_allow


class Robots:
    """One robots.txt per host, fetched once and remembered."""

    def __init__(self, user_agent: str = USER_AGENT, fetch: Fetch = _read) -> None:
        self.user_agent = user_agent
        self._fetch = fetch
        self._groups: dict[str, list[_Group]] = {}

    def _groups_for(self, url: str) -> list[_Group]:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._groups:
            try:
                text = self._fetch(
                    urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
                )
            except urllib.error.HTTPError as exc:
                # 404 is the site saying "no rules", which permits everything.
                # Anything else — 403, 500, a redirect loop — is an unanswered
                # question, and an unanswered question is not a yes.
                if exc.code != 404:
                    raise RobotsError(f"{origin}/robots.txt returned {exc.code}") from exc
                text = ""
            except OSError as exc:
                raise RobotsError(f"{origin}/robots.txt could not be read: {exc}") from exc
            self._groups[origin] = _parse_groups(text)
        return self._groups[origin]

    def allows(self, url: str) -> bool:
        rules, _ = _select_rules(self._groups_for(url), self.user_agent)
        return _allowed(rules, _request_path(url))

    def delay(self, url: str, floor: float) -> float:
        """The site's crawl-delay, or `floor` — whichever asks us to wait longer."""
        _, stated = _select_rules(self._groups_for(url), self.user_agent)
        return max(floor, stated) if stated is not None else floor


@dataclass(frozen=True)
class _Fixture:
    """One robots.txt document, paired with the RFC 9309 verdict it must produce."""

    name: str
    robots_txt: str
    agent: str
    url: str
    expected_allowed: bool


# A fixture table of robots.txt documents paired with their RFC 9309 verdict
# per (agent, path) — the measurement `robots_verdicts_misread` is taken over.
# Two entries reproduce the failures measured against `urllib.robotparser` on
# 2026-08-25: `blank_line_inside_a_disallow_all_record` (fails open — the
# dangerous direction, see the module docstring) and
# `allow_beats_a_shorter_disallow` (fails closed). The rest cover the other
# RFC 9309 requirements this module claims to implement, so a regression in
# any of them shows up here rather than only in the unit tests.
FIXTURES: tuple[_Fixture, ...] = (
    _Fixture(
        name="no_matching_rule_is_allowed",
        robots_txt="""
User-agent: *
Disallow: /admin/
""",
        agent="SomeBot",
        url="https://f1.example/jobs/x",
        expected_allowed=True,
    ),
    _Fixture(
        name="explicit_disallow_all",
        robots_txt="""
User-agent: ClaudeBot
Disallow: /
""",
        agent="ClaudeBot",
        url="https://f2.example/jobs/x",
        expected_allowed=False,
    ),
    _Fixture(
        name="blank_line_inside_a_disallow_all_record",
        robots_txt="""
User-agent: ClaudeBot

Disallow: /
""",
        agent="ClaudeBot",
        url="https://f3.example/anything",
        expected_allowed=False,
    ),
    _Fixture(
        name="allow_beats_a_shorter_disallow",
        robots_txt="""
User-agent: *
Disallow: /jobs/
Allow: /jobs/public/
""",
        agent="SomeBot",
        url="https://f4.example/jobs/public/x",
        expected_allowed=True,
    ),
    _Fixture(
        name="disallow_still_applies_outside_the_longer_allow",
        robots_txt="""
User-agent: *
Disallow: /jobs/
Allow: /jobs/public/
""",
        agent="SomeBot",
        url="https://f4.example/jobs/private",
        expected_allowed=False,
    ),
    _Fixture(
        name="allow_wins_an_equal_length_tie",
        robots_txt="""
User-agent: *
Disallow: /x
Allow: /x
""",
        agent="SomeBot",
        url="https://f5.example/x",
        expected_allowed=True,
    ),
    _Fixture(
        name="duplicate_groups_for_one_token_are_merged",
        robots_txt="""
User-agent: ClaudeBot
Disallow: /a

User-agent: Other
Disallow: /b

User-agent: ClaudeBot
Disallow: /c
""",
        agent="ClaudeBot",
        url="https://f6.example/c",
        expected_allowed=False,
    ),
    _Fixture(
        name="a_merged_group_does_not_leak_another_agents_rules",
        robots_txt="""
User-agent: ClaudeBot
Disallow: /a

User-agent: Other
Disallow: /b

User-agent: ClaudeBot
Disallow: /c
""",
        agent="ClaudeBot",
        url="https://f6.example/b",
        expected_allowed=True,
    ),
    _Fixture(
        name="an_explicit_token_is_used_exclusively_not_merged_with_the_wildcard",
        robots_txt="""
User-agent: *
Allow: /

User-agent: ClaudeBot
Disallow: /
""",
        agent="ClaudeBot",
        url="https://f7.example/jobs",
        expected_allowed=False,
    ),
    _Fixture(
        name="an_unmatched_agent_falls_back_to_the_wildcard",
        robots_txt="""
User-agent: ClaudeBot
Disallow: /

User-agent: *
Allow: /
""",
        agent="SomeOtherBot",
        url="https://f8.example/jobs",
        expected_allowed=True,
    ),
    _Fixture(
        name="the_agent_token_match_is_case_insensitive",
        robots_txt="""
User-agent: ClaudeBot
Disallow: /private/
""",
        agent="claudebot",
        url="https://f9.example/private/x",
        expected_allowed=False,
    ),
    # The four below were added after review found the matcher failing open on
    # each of them while this gate still read `robots_verdicts_misread: 0`.
    # A fixture table that cannot express the failure is the same defect the
    # module is about, one level up — so they live here, in the measurement,
    # rather than only in the unit tests.
    _Fixture(
        name="our_own_product_token_beats_the_wildcard_group",
        robots_txt="""
User-agent: integral-job-search
Disallow: /private

User-agent: *
Allow: /
""",
        agent=USER_AGENT,
        url="https://f10.example/private",
        expected_allowed=False,
    ),
    _Fixture(
        name="an_already_percent_encoded_path_still_matches_its_rule",
        robots_txt="""
User-agent: *
Disallow: /private%20jobs
""",
        agent="SomeBot",
        url="https://f11.example/private%20jobs",
        expected_allowed=False,
    ),
    _Fixture(
        name="a_wildcard_and_end_anchor_exclude_the_path",
        robots_txt="""
User-agent: *
Disallow: /*.pdf$
""",
        agent="SomeBot",
        url="https://f12.example/docs/file.pdf",
        expected_allowed=False,
    ),
    _Fixture(
        name="an_end_anchor_does_not_over_block_a_near_miss",
        robots_txt="""
User-agent: *
Disallow: /*.pdf$
""",
        agent="SomeBot",
        url="https://f13.example/docs/file.pdf.txt",
        expected_allowed=True,
    ),
    # A second review round found the first fix had itself opened two more
    # holes, both in normalisation. Same lesson as the round before: the
    # fixture table is where a normalisation bug becomes visible.
    _Fixture(
        name="a_rule_carrying_a_query_string_still_matches",
        robots_txt="""
User-agent: *
Disallow: /search?q=x
""",
        agent="SomeBot",
        url="https://f14.example/search?q=x",
        expected_allowed=False,
    ),
    _Fixture(
        name="an_escape_for_an_unreserved_octet_is_the_same_path",
        robots_txt="""
User-agent: *
Disallow: /foo/%62ar
""",
        agent="SomeBot",
        url="https://f15.example/foo/bar",
        expected_allowed=False,
    ),
    _Fixture(
        name="a_percent_encoded_asterisk_is_a_literal_not_a_wildcard",
        robots_txt="""
User-agent: *
Disallow: /a%2Ab
""",
        agent="SomeBot",
        url="https://f16.example/axb",
        expected_allowed=True,
    ),
    # `$` is the other metacharacter, and it needed both of `*`'s treatments.
    _Fixture(
        name="a_percent_encoded_dollar_matches_a_literal_dollar_target",
        robots_txt="""
User-agent: *
Disallow: /report%24
""",
        agent="SomeBot",
        url="https://f17.example/report$",
        expected_allowed=False,
    ),
    _Fixture(
        name="an_anchored_rule_outranks_a_shorter_allow",
        robots_txt="""
User-agent: *
Disallow: /foo/*$
Allow: /foo/x
""",
        agent="SomeBot",
        url="https://f18.example/foo/x",
        expected_allowed=False,
    ),
    # Both of these fail OPEN before the fix: the target and the rule spell the
    # same octet two different ways, so the rule never matches and the fetch is
    # permitted. That is the direction that actually hurts a site.
    _Fixture(
        name="a_raw_percent_in_the_target_matches_a_percent_encoded_rule",
        robots_txt="""
User-agent: ClaudeBot
Disallow: /100%25
""",
        agent="ClaudeBot",
        url="https://f21.example/100%",
        expected_allowed=False,
    ),
    # From the independent RFC 9309 audit (session_014PVqB2HnzAsTQhTm3sktHs):
    # 19 spec-derived cases, 17 passing, these two failing. Both are fail-CLOSED
    # — the whole site became unfetchable — which is why they went unnoticed:
    # nothing was ever wrongly fetched, there was simply nothing at all.
    _Fixture(
        name="an_empty_disallow_is_a_no_op_not_a_rule_matching_everything",
        robots_txt="""
User-agent: ClaudeBot
Disallow:
""",
        agent="ClaudeBot",
        url="https://f23.example/anything",
        expected_allowed=True,
    ),
    _Fixture(
        name="an_empty_disallow_does_not_swallow_the_rules_beside_it",
        robots_txt="""
User-agent: ClaudeBot
Disallow:
Disallow: /private
""",
        agent="ClaudeBot",
        url="https://f24.example/public",
        expected_allowed=True,
    ),
    _Fixture(
        name="a_bare_query_delimiter_still_matches_a_rule_that_ends_in_one",
        robots_txt="""
User-agent: ClaudeBot
Disallow: /search?
""",
        agent="ClaudeBot",
        url="https://f22.example/search?",
        expected_allowed=False,
    ),
    # ---------------------------------------------------------------
    # Round-2 independent audit, 2026-08-26. Derived from RFC 9309 by a
    # session that had not read this module, and committed to the audit
    # branch BEFORE the implementation was opened, so these expectations
    # are not a description of what the code already did. Each carries
    # the section it is citing. Report: arsenal/audits/t70-robots-round2.md
    # ---------------------------------------------------------------
    _Fixture(
        # RFC 9309 SS2.2.2, incorporating RFC 3986 SS2.3 -- percent-encoded octets
        # for unreserved characters (which includes '~') must be normalized to the
        # unencoded character before path comparison, so '%7E' in a rule matches a
        # literal '~' in the request path.
        name="percent_encoded_unreserved_rule_vs_literal_request",
        robots_txt='User-agent: *\nDisallow: /%7Euser\n',
        agent='TestBot/1.0',
        url='https://example.com/~user',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 / RFC 3986 SS2.3 -- normalization is symmetric: an
        # unencoded '~' in the rule must still match a request path that spells the
        # same character as '%7E'.
        name="literal_rule_vs_percent_encoded_unreserved_request",
        robots_txt='User-agent: *\nDisallow: /~user\n',
        agent='TestBot/1.0',
        url='https://example.com/%7Euser',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 / RFC 3986 SS2.3 -- '/' is a reserved character, not
        # unreserved, so '%2F' is never decode-normalized. An identically-encoded
        # rule and request path are the same octet sequence and must match.
        name="percent_encoded_reserved_slash_exact_match",
        robots_txt='User-agent: *\nDisallow: /a%2Fb\n',
        agent='TestBot/1.0',
        url='https://example.com/a%2Fb',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 / RFC 3986 SS2.3 -- because '/' is reserved, '%2F' must
        # NOT be treated as equivalent to an unencoded '/'. 'Disallow: /a%2Fb' and
        # the request path '/a/b' denote different octet sequences, so they do not
        # match. A matcher that folds %2F into / here fails open in reverse (over-
        # blocks) on the companion case above and under-blocks nothing here, but the
        # two cases together catch either direction of that bug.
        name="percent_encoded_reserved_slash_must_not_equal_literal_slash",
        robots_txt='User-agent: *\nDisallow: /a%2Fb\n',
        agent='TestBot/1.0',
        url='https://example.com/a/b',
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2, incorporating RFC 3986 SS2.1 -- the hex digits of a
        # percent-encoded triplet are case-insensitive; '%C3%A9' and '%c3%a9' denote
        # the same two octets and must compare equal.
        name="percent_encoding_hex_digit_case_insensitivity",
        robots_txt='User-agent: *\nDisallow: /caf%C3%A9\n',
        agent='TestBot/1.0',
        url='https://example.com/caf%c3%a9',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 -- '%' is not itself an unreserved character, so a
        # literal '%' octet in a path is represented as '%25'. An identically
        # written rule and request path match.
        name="percent_25_literal_percent_sign_exact_match",
        robots_txt='User-agent: *\nDisallow: /100%25\n',
        agent='TestBot/1.0',
        url='https://example.com/100%25',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2/SS2.2.3 -- '$' anchors the pattern to the exact end of
        # the path. Percent-decoding is applied one level only: '%2525' decodes to
        # the literal string '%25' (a '%' followed by '2' and '5'), which is a
        # longer, different octet sequence than the single '%'-octet the anchored
        # rule '/100%25$' denotes. The anchored pattern therefore cannot match the
        # full request path, and the rule does not apply.
        name="double_encoded_percent_sign_does_not_match_single_encoded",
        robots_txt='User-agent: *\nDisallow: /100%25$\n',
        agent='TestBot/1.0',
        url='https://example.com/100%2525',
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 / RFC 3986 SS2.3 -- ALPHA characters are unreserved, so
        # '%41' (encoding 'A') normalizes to 'A', making the rule equivalent to
        # 'Disallow: /Admin'.
        name="percent_encoded_unreserved_letters_spelling_a_word",
        robots_txt='User-agent: *\nDisallow: /%41dmin\n',
        agent='TestBot/1.0',
        url='https://example.com/Admin',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 -- an empty value on a Disallow line imposes no
        # restriction at all; a group whose only rule is an empty Disallow permits
        # every path.
        name="empty_disallow_value_permits_everything",
        robots_txt='User-agent: *\nDisallow:\n',
        agent='TestBot/1.0',
        url='https://example.com/anything/at/all',
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 -- an empty Allow value matches a zero-length path and
        # therefore has no specificity; it must not out-rank or otherwise suppress a
        # non-empty Disallow rule that actually matches the request path.
        name="empty_allow_value_does_not_suppress_real_disallow",
        robots_txt='User-agent: *\nAllow:\nDisallow: /private\n',
        agent='TestBot/1.0',
        url='https://example.com/private',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 / SS2.2.3 -- outside of the '*' and '$' special
        # characters, a rule's octets (including '?') are matched literally as a
        # prefix of the path-plus-query string; '/path?' is a prefix of
        # '/path?query=1'.
        name="literal_question_mark_blocks_matching_query_string",
        robots_txt='User-agent: *\nDisallow: /path?\n',
        agent='TestBot/1.0',
        url='https://example.com/path?query=1',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 -- '/path?' is not a prefix of '/path' because the
        # literal '?' octet the rule requires is absent from the request; the rule
        # does not apply.
        name="literal_question_mark_does_not_block_bare_path",
        robots_txt='User-agent: *\nDisallow: /path?\n',
        agent='TestBot/1.0',
        url='https://example.com/path',
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '*' matches zero or more of any character, so '/*?'
        # matches any path that contains a literal '?' anywhere after the root,
        # including '/page?x=1'.
        name="wildcard_then_literal_question_mark_blocks_any_query",
        robots_txt='User-agent: *\nDisallow: /*?\n',
        agent='TestBot/1.0',
        url='https://example.com/page?x=1',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '/*?' requires a literal '?' to occur somewhere in the
        # path; a request with no '?' cannot satisfy the pattern no matter how '*'
        # expands.
        name="wildcard_then_literal_question_mark_does_not_block_no_query",
        robots_txt='User-agent: *\nDisallow: /*?\n',
        agent='TestBot/1.0',
        url='https://example.com/page',
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '$' designates the end of the match pattern; '/path$'
        # matches only a request path that is exactly '/path'.
        name="dollar_anchor_exact_match",
        robots_txt='User-agent: *\nDisallow: /path$\n',
        agent='TestBot/1.0',
        url='https://example.com/path',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- because '$' anchors the pattern to end exactly after
        # 'path', a request path with trailing characters ('pathxyz') does not
        # match.
        name="dollar_anchor_rejects_longer_suffix",
        robots_txt='User-agent: *\nDisallow: /path$\n',
        agent='TestBot/1.0',
        url='https://example.com/pathxyz',
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '$' requires the string to end exactly at that point;
        # '/path/' has an extra '/' octet after 'path' and therefore does not
        # satisfy '/path$'.
        name="dollar_anchor_rejects_trailing_slash",
        robots_txt='User-agent: *\nDisallow: /path$\n',
        agent='TestBot/1.0',
        url='https://example.com/path/',
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '*' matches any sequence of characters, including
        # none; '/*.php' matches any path that ends in the literal suffix '.php'
        # reached after zero or more characters, including '/index.php'.
        name="wildcard_basic_suffix_match",
        robots_txt='User-agent: *\nDisallow: /*.php\n',
        agent='TestBot/1.0',
        url='https://example.com/index.php',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '$' anchors the end of the pattern immediately after
        # '.php'; the request continues with '?x=1' after '.php', so the string does
        # not end where the pattern requires.
        name="wildcard_dollar_anchor_excludes_query_suffix",
        robots_txt='User-agent: *\nDisallow: /*.php$\n',
        agent='TestBot/1.0',
        url='https://example.com/index.php?x=1',
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '*' matches zero or more characters; two adjacent '*'
        # tokens are semantically equivalent to one and together still match any run
        # of characters between 'a' and 'b', including 'xyz'.
        name="consecutive_wildcards_collapse_to_one",
        robots_txt='User-agent: *\nDisallow: /a**b\n',
        agent='TestBot/1.0',
        url='https://example.com/axyzb',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '*' may expand to zero characters, so '/a*$' matches a
        # path that is exactly '/a' as well as any longer path beginning with '/a'.
        name="trailing_wildcard_before_dollar_matches_zero_expansion",
        robots_txt='User-agent: *\nDisallow: /a*$\n',
        agent='TestBot/1.0',
        url='https://example.com/a',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.1 -- when a crawler token matches more than one group's
        # product token, the crawler MUST use the most specific (longest) matching
        # token. 'Botly' is more specific than 'Bot' for the crawler token
        # 'Botly/2.0', so the Botly group's Disallow applies even though the Bot
        # group alone would permit everything.
        name="most_specific_agent_group_wins_over_shorter_token",
        robots_txt='User-agent: Bot\nDisallow:\n\nUser-agent: Botly\nDisallow: /private\n',
        agent='Botly/2.0',
        url='https://example.com/private',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.1 -- the match direction is one-way: the rule's product
        # token must be a substring of the crawler's token, not the reverse. 'Botly'
        # is not a substring of the crawler token 'Bot', so that group does not
        # apply and the crawler falls back to the wildcard '*' group.
        name="agent_token_longer_than_crawler_token_does_not_match",
        robots_txt='User-agent: Botly\nDisallow:\n\nUser-agent: *\nDisallow: /private\n',
        agent='Bot/1.0',
        url='https://example.com/private',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.1 -- matching of the User-agent product token against the
        # crawler's own token MUST be case-insensitive; 'GoogleBot' matches the
        # crawler's self-identification as 'googlebot'.
        name="agent_match_is_case_insensitive",
        robots_txt='User-agent: GoogleBot\nDisallow: /private\n',
        agent='googlebot/2.1',
        url='https://example.com/private',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 -- unlike the User-agent match, Allow/Disallow path
        # values are compared octet-for-octet, case-sensitively; '/Secret' does not
        # match the differently-cased path '/secret'.
        name="path_match_is_case_sensitive",
        robots_txt='User-agent: *\nDisallow: /Secret\n',
        agent='TestBot/1.0',
        url='https://example.com/secret',
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.1 -- consecutive User-agent lines with no intervening rule
        # lines form a single group whose rules bind every listed token; a crawler
        # matching the second-listed token 'B' is bound exactly as one matching 'A'
        # would be.
        name="shared_group_applies_to_every_listed_agent_token",
        robots_txt='User-agent: A\nUser-agent: B\nDisallow: /secret\n',
        agent='B/1.0',
        url='https://example.com/secret',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 -- a group that declares no Allow or Disallow lines
        # contains no restrictions, so every path is permitted for a crawler
        # matching it.
        name="group_with_no_rules_permits_everything",
        robots_txt='User-agent: *\n',
        agent='TestBot/1.0',
        url='https://example.com/anything',
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS5.1 -- when an Allow and a Disallow rule match a path with
        # equal specificity (equal matched octet length), the Allow rule takes
        # precedence.
        name="equal_length_tie_allow_wins_subpath",
        robots_txt='User-agent: *\nAllow: /page\nDisallow: /page\n',
        agent='TestBot/1.0',
        url='https://example.com/page',
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS5.1 -- the Allow-wins tie-break applies regardless of path
        # depth; equal-length root rules still resolve to Allow.
        name="equal_length_tie_allow_wins_root",
        robots_txt='User-agent: *\nAllow: /\nDisallow: /\n',
        agent='TestBot/1.0',
        url='https://example.com/',
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS5.1 combined with SS2.2.2 -- specificity is the length of the
        # matched octet sequence AFTER percent-decoding unreserved characters, not
        # the raw rule-line character count. Decoded, 'Allow: /%61/%62' is '/a/b' (4
        # octets) and 'Disallow: /a/bcdef' is 8 octets, so Disallow is strictly more
        # specific and wins -- even though the two raw rule lines happen to be the
        # same length (8 characters each), which would wrongly read as a tie (and
        # therefore wrongly resolve to Allow, fail-open) under a matcher that
        # compares raw text length instead of decoded octet length.
        name="specificity_must_be_computed_on_decoded_octets_not_raw_text",
        robots_txt='User-agent: *\nAllow: /%61/%62\nDisallow: /a/bcdef\n',
        agent='TestBot/1.0',
        url='https://example.com/a/bcdef',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.1 -- when the same product token reappears in more than one
        # group, the crawler MUST combine the rules of all such groups; the first
        # group's Disallow must still apply even though a later group for the same
        # token exists.
        name="duplicate_agent_groups_combine_first_groups_rule_survives",
        robots_txt='User-agent: Bot\nDisallow: /a\n\nUser-agent: Bot\nDisallow: /b\n',
        agent='Bot/1.0',
        url='https://example.com/a',
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.1 -- combining duplicate groups means the second group's
        # Disallow must also apply; a matcher that keeps only the first group it
        # encounters for a token would incorrectly allow this path.
        name="duplicate_agent_groups_combine_second_groups_rule_survives",
        robots_txt='User-agent: Bot\nDisallow: /a\n\nUser-agent: Bot\nDisallow: /b\n',
        agent='Bot/1.0',
        url='https://example.com/b',
        expected_allowed=False,
    ),
)


def _verdict(fixture: _Fixture) -> bool:
    rules, _ = _select_rules(_parse_groups(fixture.robots_txt), fixture.agent)
    return _allowed(rules, _request_path(fixture.url))


def measure(fixtures: tuple[_Fixture, ...] = FIXTURES) -> dict[str, Any]:
    """T70's gate: how many fixture verdicts disagree with RFC 9309.

    `robots_verdicts_evaluated` is the denominator this measurement is
    hollow without — a zero misread count over zero evaluated fixtures is not
    a pass, it is a check that never ran. `gate_status` names that state
    explicitly so `gate_evidence.py` can refuse to score it (exit 3,
    "unmeasured") rather than reading the vacuous zero as green.
    """
    misread = [
        {
            "name": fixture.name,
            "agent": fixture.agent,
            "url": fixture.url,
            "expected_allowed": fixture.expected_allowed,
            "actual_allowed": actual,
        }
        for fixture in fixtures
        if (actual := _verdict(fixture)) != fixture.expected_allowed
    ]
    evaluated = len(fixtures)
    return {
        "robots_verdicts_misread": len(misread),
        "robots_verdicts_evaluated": evaluated,
        "gate_status": "measured" if evaluated else "unmeasured",
        "misread_cases": misread,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH, fixtures: tuple[_Fixture, ...] = FIXTURES
) -> dict[str, Any]:
    """Measure and record `status/evidence/T70.json`."""
    measured = measure(fixtures)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write T70's gate evidence.

    The `robots_verdicts_misread == 0` threshold is asserted by
    `gate_evidence.py` against the committed file, not by this exit code —
    the same split `integral.extraction` and `integral.ontology_health` use,
    so a misread fixture is reported here (loudly, on stderr) without halting
    every other module's `make evidence` regeneration.
    """
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)

    if measured["robots_verdicts_misread"]:
        print(
            f"robots_verdicts_misread: {measured['robots_verdicts_misread']} of "
            f"{measured['robots_verdicts_evaluated']} fixture verdicts disagree with RFC 9309: "
            f"{measured['misread_cases']}",
            file=sys.stderr,
        )
    print(json.dumps(measured, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
