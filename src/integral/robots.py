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
def _product_token(agent: str) -> str:
    """The robots product token inside an identification string.

    `integral-job-search/0.1 (+https://...)` -> `integral-job-search`. A bare
    token (`ClaudeBot`) is returned unchanged, which is what a robots.txt
    actually writes and what the fixtures below use."""
    return agent.split("/", 1)[0].strip()

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
                rules.append((field_name == "allow", value))
                started = True
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

# `%` stays safe so an escape already present is not re-encoded. `*` is absent
# on purpose: a target's literal `*` becomes `%2A`, which is exactly how a rule
# must spell a literal asterisk, so the two sides meet.
_CHUNK_SAFE = "/%:@!$&'()+,;=?~-._"

_ESCAPE_RE = re.compile(r"%([0-9A-Fa-f]{2})")


def _canon(chunk: str) -> str:
    """One canonical octet form for a literal run of a path.

    Escapes encoding an *unreserved* character are decoded, because `%62` and
    `b` denote the same octet and a `Disallow: /foo/%62ar` that fails to match
    `/foo/bar` is a fail-open. Every other escape is kept and upper-cased, so
    `%2A` survives as `%2A` rather than becoming a wildcard — which is how a
    rule spells a literal asterisk.
    """

    def _decode(match: re.Match[str]) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else "%" + match.group(1).upper()

    return quote(_ESCAPE_RE.sub(_decode, chunk), safe=_CHUNK_SAFE)


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
    if parts.query:
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
        length = sum(len(chunk) for chunk in chunks)
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
