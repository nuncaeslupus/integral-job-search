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

from integral.gate_exit import worst

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T70.json"
DEFAULT_T71_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T71.json"

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


# T71: some sites put a WAF in front of everything, so the honest agent above
# gets a 403 on `/robots.txt` itself — the one document that names the rules
# it would otherwise be refused for. A generic browser string, not our own,
# because this is a one-time exception for the policy resource and must not
# read as a second identity to fetch anything else with.
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _browser_read(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": _BROWSER_USER_AGENT})
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

    The token comparison is **equality**, case-folded, and nothing else (T102,
    issue #236). §2.2.1 grants exactly one relaxation — "Crawlers MUST use
    case-insensitive matching to find the group that matches the product token"
    — and the only substring relation the RFC states runs the other way, between
    a crawler's product token and the identification string it sends. So
    `User-agent: Bot` does not govern a crawler whose token is `Botly`, and that
    is not a fail-open: it is what the file said. Two of the RFC's own figures
    say the same thing from the other side — one calls the relation "two groups
    that match the same product token exactly", the other declares
    `user-agent: BazBot` a non-match for the crawler `ExampleBot`, two tokens
    sharing the suffix `Bot`.

    Reading it as a prefix match is not a merely-conservative deviation, either.
    An explicitly matched group is used EXCLUSIVELY, so a prefix match can
    suppress the `*` group and *unblock* a path the site disallowed for
    everyone — the `a_prefix_file_token_does_not_displace_the_wildcard_group`
    fixture is exactly that document, permitted under the prefix reading and
    blocked under this one. A `googlebot` group governing `Googlebot-Image` is
    Google's crawler handing the matcher several of its own names, not a rule in
    the RFC; the reference implementation compares each of them with
    `EqualsIgnoreCase`.
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
# RFC 3986 §2.2's `reserved` production, written out in full so the rule below
# is derived from the spec rather than from a list somebody typed. RFC 9309
# §2.2.2 canonicalises over exactly this *set*: octets outside US-ASCII, and
# those in the reserved range defined by RFC 3986, MUST be percent-encoded
# prior to comparison. So the default is ENCODE, and every exemption has to be
# argued — which is the whole of the fix below.
#
# The previous revision instead carried one hand-written allowlist,
# `_CHUNK_SAFE = "/:@!&'()+,;=?~-._"`, and consulted it for the path and the
# query alike. It left `: & = + , @ ! ; ' ( )` standing as raw octets in both
# regions, so a rule and a request target that were two spellings of one URI
# never compared equal and the rule matched nothing: `Disallow: /s?q=a%26b` did
# not catch `/s?q=a&b`, and `Disallow: /jobs%3Aremote/list` did not catch
# `/jobs:remote/list`. Nine spec-derived paths RFC 9309 refuses came back ALLOW,
# in the matcher that decides real fetches. One allowlist, two regions.
_GEN_DELIMS = ":/?#[]@"
_SUB_DELIMS = "!$&'()*+,;="
_RESERVED = frozenset(_GEN_DELIMS + _SUB_DELIMS)

_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")

# The held-out octets, reasoned PER REGION — because the same octet is structure
# in one region and data in the other, and that is precisely what a single
# allowlist cannot express.
#
# `/` — RFC 3986 §3.3 makes it the path's segment separator. Inside a path it is
#   structure, never data, so it must NOT encode there even though every other
#   reserved octet must: `Disallow: /a%2Fb` and the request `/a/b` are different
#   octet sequences and must not match. Inside a *query* it delimits nothing
#   (§3.4 admits `/` and `?` as ordinary query octets), so there it is data and
#   encodes like the rest — which is what makes
#   `Disallow: /foo/bar?baz=https%3A%2F%2Ffoo.bar` catch
#   `/foo/bar?baz=https://foo.bar`, §2.2.2's own example.
_PATH_SAFE = "/"
#
# Nothing at all is held out inside the query: once the opening `?` has been
# consumed as the region delimiter, no reserved octet after it delimits anything
# this matcher can see. `&` and `=` separate parameters for the *server*, not for
# a prefix comparison over octets, so treating them as structure would be reading
# a form-encoding convention into §2.2.2's set.
_QUERY_SAFE = ""
#
# Held out by construction rather than by these sets, because they are syntax and
# never reach a literal run at all:
#
# `?` — the FIRST raw one is the path/query delimiter, and it is what makes "in
#   the query" a decidable question in the first place; `_canon_region` splits on
#   it and re-emits it literally, on both sides, so `Disallow: /search?` still
#   catches `/search?q=x`. A `?` *after* that one delimits nothing and is query
#   data, so it encodes.
# `*` and `$` — RFC 9309 §2.2.3's two pattern metacharacters. In a rule they are
#   removed before canonicalisation (`_normalize_rule` splits on `*` and strips a
#   trailing `$`), so they never appear in a run. Everywhere else — anywhere in a
#   request target, and a `$` that is not the rule's final octet — they are
#   ordinary data and encode to `%2A` / `%24`, which is how a rule spelling
#   either literally as an escape meets the target that carries it raw. An
#   earlier revision reasoned this out for `*` and left `$` unencoded — half the
#   symmetry, so `Disallow: /report%24` never matched `/report$`.
# `%` — NOT held out. It is only ever legitimate as the head of an escape, and
#   `_canon_run` quotes the runs *between* escapes, where any `%` left standing
#   is a literal one. Leaving it safe meant `/100%` canonicalised to itself while
#   `Disallow: /100%25` canonicalised to `/100%25` — the same octet spelled two
#   ways, so the rule never matched.

#: The one octet that separates the two regions, in a rule and in a target
#: alike. It is re-emitted literally rather than encoded, which is what makes
#: "in the query" a decidable question at all.
_QUERY_DELIMITER = "?"

_ESCAPE_RE = re.compile(r"%([0-9A-Fa-f]{2})")


def _canon_run(run: str, safe: str) -> str:
    """One canonical octet form for a literal run lying wholly in one region.

    Escapes encoding an *unreserved* character are decoded, because `%62` and
    `b` denote the same octet and a `Disallow: /foo/%62ar` that fails to match
    `/foo/bar` is a fail-open. Every other escape is kept and upper-cased, so
    `%2A` survives as `%2A` rather than becoming a wildcard — which is how a
    rule spells a literal asterisk.

    `safe` is the region's held-out set; everything else outside `_UNRESERVED`
    is percent-encoded, which is §2.2.2's requirement applied to the whole of
    RFC 3986's reserved range instead of to a sample of it.
    """

    out: list[str] = []
    pos = 0
    for match in _ESCAPE_RE.finditer(run):
        out.append(quote(run[pos : match.start()], safe=safe))
        char = chr(int(match.group(1), 16))
        out.append(char if char in _UNRESERVED else "%" + match.group(1).upper())
        pos = match.end()
    out.append(quote(run[pos:], safe=safe))
    return "".join(out)


def _canon_region(run: str, in_query: bool) -> tuple[str, bool]:
    """Canonicalise one run, and report which region it ends in.

    The region is decided by the first raw `?`: everything before it is path,
    everything after is query. A rule is canonicalised run by run (the runs
    between its wildcards), so the flag has to be carried across them — a `?`
    in an earlier run puts every later run in the query.

    A `*` may itself span the delimiter, and then the rule carries no raw `?`
    of its own and every run is read as path. `/` is the only octet whose
    canonical form differs between the two regions, so that is the only case
    the ambiguity can reach: `Disallow: /*/x` denotes a literal separator and
    does not match `/s?q=/x`, whose canonical query is `q%3D%2Fx`. That is a
    consequence of comparing canonical forms, not a special case — the rule
    that reaches it is `Disallow: /*%2Fx`.
    """
    if in_query:
        return _canon_run(run, _QUERY_SAFE), True
    head, delimiter, tail = run.partition(_QUERY_DELIMITER)
    if not delimiter:
        return _canon_run(head, _PATH_SAFE), False
    return _canon_run(head, _PATH_SAFE) + _QUERY_DELIMITER + _canon_run(tail, _QUERY_SAFE), True


def _canon(target: str) -> str:
    """The canonical octet form of a whole request target — path, then query."""
    canonical, _ = _canon_region(target, in_query=False)
    return canonical


#: One admissible spelling of a rule run: its canonical octets, and the region
#: its FIRST octet has to lie in for that spelling to be the right one — `True`
#: query, `False` path, and `None` for a run that canonicalises identically in
#: both and is therefore admissible in either. See `_normalize_rule`.
_Spelling = tuple[str, bool | None]


def _normalize_rule(pattern: str) -> tuple[list[tuple[_Spelling, ...]], bool]:
    """A rule as canonical literal runs plus its end-anchor flag.

    Splitting on `*` before canonicalising is what keeps the wildcard as
    syntax: only the runs between wildcards are percent-normalised. The region
    flag threads through those runs, so a rule's query octets are canonicalised
    as query octets even when a wildcard sits between them and the `?`.

    **A `*` can itself span the delimiter, and then the pattern does not say
    which region its later runs are in.** §2.2.3 makes `*` "any sequence of
    characters", `?` included, so `Disallow: /*http://` is a rule about a query
    as readily as one about a path — the pattern carries no `?` of its own to
    decide it. Reading such a run as path octets is a FAIL-OPEN: `http://`
    canonicalises to `http%3A//` there, the request `/out?url=http://evil.com`
    canonicalises to `/out?url=http%3A%2F%2Fevil.com`, and the rule matches
    nothing at all. So a run whose region the pattern leaves open is emitted in
    BOTH spellings, and `_matches` accepts whichever suits the region of the
    position it is testing. The two differ only where the run carries `/` or a
    `?` of its own — the octets this matcher reads as structure in one region
    and as data in the other — so every other run has nothing to get wrong and
    collapses back to a single spelling admissible in either region.
    """
    body, anchored = (pattern[:-1], True) if pattern.endswith("$") else (pattern, False)
    chunks: list[tuple[_Spelling, ...]] = []
    in_query = False
    # The first run starts at the first octet of the path, so its region is
    # never in doubt. Every later run sits behind a `*`.
    undetermined = False
    for run in body.split("*"):
        canonical, ends_in_query = _canon_region(run, in_query)
        if in_query or not undetermined:
            chunks.append(((canonical, in_query),))
        else:
            as_query, _ = _canon_region(run, True)
            # Equal spellings are not one path spelling: they are a run with no
            # region to get wrong, admissible on either side. Collapsing them to
            # `(canonical, False)` instead re-opened a fail-open — `/*a$b` was
            # confined to the path and stopped matching `/x?q=a%24b`.
            chunks.append(
                ((canonical, None),)
                if as_query == canonical
                else ((canonical, False), (as_query, True))
            )
        in_query = ends_in_query
        undetermined = True
    return chunks, anchored


def _region_of(position: int, boundary: int) -> bool:
    """Whether `position` in a canonical target lies in the query region.

    `boundary` is the index of the target's own `?`, or its length when it has
    none. The delimiter itself belongs to the path side: a rule run may start at
    it and run across it, which is exactly what `Disallow: /search?` does.
    """
    return position > boundary


def _spelling_at(path: str, run: tuple[_Spelling, ...], at: int, boundary: int) -> int | None:
    """The end of whichever spelling of `run` sits at exactly `at`, or `None`.

    At most one can: two spellings of the same run differ only where it carries
    `/`, so one demands a literal `/` at a position where the other demands
    `%2F`, and no string satisfies both.
    """
    for text, in_query in run:
        if in_query is not None and in_query != _region_of(at, boundary):
            continue
        if path.startswith(text, at):
            return at + len(text)
    return None


def _find_spelling(
    path: str, run: tuple[_Spelling, ...], start: int, boundary: int
) -> tuple[int, int] | None:
    """Where `run` first ends at or after `start`, and how many octets it spent.

    Earliest END rather than earliest start, because two spellings of one run
    have different lengths: taking the one that finishes soonest leaves the most
    room for the runs after it, which is what keeps the greedy scan complete.
    The winning spelling's octet count is returned alongside its end position,
    because that count — and not the other spelling's — is what `_allowed` has
    to score. Nothing else knows which spelling matched.

    Each spelling is searched only in its own region — a path spelling must
    START at or before the delimiter, a query spelling after it. A run carrying
    no `?` cannot cover the delimiter octet, so bounding the start is enough to
    keep it on one side; a run carrying its own `?` is meant to cross.
    """
    best: tuple[int, int] | None = None
    for text, in_query in run:
        if in_query is None:
            lower, upper = start, len(path)
        elif in_query:
            lower, upper = max(start, boundary + 1), len(path)
        else:
            lower, upper = start, min(len(path), boundary + len(text))
        if lower > len(path):
            continue
        found = path.find(text, lower, upper)
        if found == -1:
            continue
        if best is None or found + len(text) < best[0]:
            best = (found + len(text), len(text))
    return best


def _anchored_spelling(
    path: str, run: tuple[_Spelling, ...], floor: int, boundary: int
) -> int | None:
    """The octets a `$`-anchored final run spends flush against the end, or `None`.

    At most one spelling can satisfy this. Two spellings of a run differ in
    length, so ending together means starting apart, and the shorter — always
    the path one, since `/` costs one octet and `%2F` three — would have to
    start LATER, past the delimiter, where a path spelling is not admissible.
    The `max` is therefore a formality; it is written as one rather than as a
    first-hit so that a case this argument has not foreseen scores the spelling
    that consumed the most octets rather than whichever the tuple listed first.
    """
    best: int | None = None
    for text, in_query in run:
        at = len(path) - len(text)
        if at < floor:
            continue
        if in_query is not None and in_query != _region_of(at, boundary):
            continue
        if not path.endswith(text):
            continue
        if best is None or len(text) > best:
            best = len(text)
    return best


def _match_octets(chunks: list[tuple[_Spelling, ...]], anchored: bool, path: str) -> int | None:
    """The literal octets the rule consumed, or `None` when it does not match.

    Greedy wildcard match, iterative and bounded — never exponential. The
    previous revision compiled each rule to a regex with `.*` per wildcard.
    Correct, but it backtracks catastrophically: a remote robots.txt could ship
    `/*a*a*a...b$` and hang the crawler on any path lacking the final `b`,
    turning a politeness check into a denial of service against ourselves. Any
    site can serve a robots.txt, so the matcher must be bounded by construction
    rather than by trusting the input.

    Each run is found once, left to right, never reconsidered: O(len(path) x
    len(rule)), and the at-most-two spellings a run can carry double that work
    rather than branching it.

    **The count is the point of this function, not a by-product.** RFC 9309
    §2.2.2 decides precedence by "the match that has the most octets", and a run
    whose region the pattern leaves open has TWO canonical spellings of
    different lengths — `/` in a path against `%2F` in a query. Exactly one of
    them is the one that matched, and this walk is the only place that knows
    which. Returning a bare `True` threw that away and left `_allowed` to guess
    from the tuple's first entry; see the fail-open recorded there.
    """
    if not chunks:
        return 0
    boundary = path.find(_QUERY_DELIMITER)
    if boundary == -1:
        boundary = len(path)
    first, *rest = chunks
    prefix = _spelling_at(path, first, 0, boundary)
    if prefix is None:
        return None
    # The first run starts at octet 0, so where it ends IS what it spent.
    octets = prefix
    if not rest:
        if anchored and len(path) != prefix:
            return None
        return octets
    position = prefix
    for index, run in enumerate(rest):
        if index == len(rest) - 1 and anchored:
            # The final run must sit flush against the end of the path.
            tail = _anchored_spelling(path, run, position, boundary)
            return None if tail is None else octets + tail
        if all(not text for text, _ in run):
            continue
        found = _find_spelling(path, run, position, boundary)
        if found is None:
            return None
        position, spent = found
        octets += spent
    return octets


def _matches(chunks: list[tuple[_Spelling, ...]], anchored: bool, path: str) -> bool:
    """Whether the rule applies to `path` at all — `_match_octets`, thresholded."""
    return _match_octets(chunks, anchored, path) is not None


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
        matched = _match_octets(chunks, anchored, path)
        if matched is None:
            continue
        # Specificity is the octet count OF THE MATCH, metacharacters included:
        # `len(chunks) - 1` restores the `*` octets that splitting removed, and
        # `int(anchored)` the trailing `$` that `_normalize_rule` stripped.
        # Restoring only the wildcards is how `Disallow: /foo/*$` scored 6
        # against `Allow: /foo/x`, tied, and lost to the allow rule — which
        # permits a path the site anchored a rule to exclude.
        #
        # **`matched` comes from the walk, not from the pattern, and that is the
        # fix for a fail-open this module shipped.** Summing `run[0][0]` — each
        # run's FIRST spelling, the path one — scored an undetermined run on a
        # spelling that had not matched anything. Since the query spelling is
        # never the shorter (`/`->`%2F`, `?`->`%3F`), a `Disallow` reaching the
        # query through a `*` matched on the long spelling and was scored on the
        # short one, and lost to an `Allow` it should have beaten:
        #
        #     Disallow: /*http://evil     matched 19 octets, scored 15
        #     Allow:    /out?url=http%3A  scored 18
        #     /out?url=http://evil.com -> ALLOW, where the Disallow alone refuses
        #
        # Twelve such triples exist, including this module's own showcase rule.
        # The defence for `run[0][0]` was that precedence should depend "on the
        # pattern rather than the request" — but §2.2.2 weighs "the match that
        # has the most octets", and a match is an event between a rule and a
        # request, so its octets are the ones that were actually compared. The
        # code had already accepted that much by counting CANONICAL octets
        # rather than raw pattern text (`specificity_must_be_computed_on_
        # decoded_octets_not_raw_text` pins it); having two canonical forms for
        # one run, it then chose the one that lost. The test of the rule is that
        # the wildcard and non-wildcard spellings of one intent must agree, and
        # under this count they do.
        length = matched + len(chunks) - 1 + int(anchored)
        if length > best_len or (length == best_len and is_allow):
            best_len, best_allow = length, is_allow
    return best_allow


def allows_text(text: str, agent: str, target: str) -> bool:
    """The RFC 9309 verdict for `target` under a robots.txt already in hand.

    `Robots.allows` fetches; this is the same decision over text, so a caller
    adjudicating a *recorded* file — or a constructed one — gets the module's
    real answer rather than a re-implementation of it. `target` may be a full
    URL or a bare request target (`/jobs?page=2`).
    """
    rules, _ = _select_rules(_parse_groups(text), agent)
    return _allowed(rules, _request_path(target))


def disallow_patterns(text: str, agent: str) -> tuple[str, ...]:
    """The `Disallow` patterns of the group that binds `agent`, in file order.

    §2.2.1 selection is applied first, so a `Disallow: /` written for another
    crawler is not returned here: it is not a restriction on this agent, and a
    caller looking for a path this file refuses *us* would otherwise be handed
    one it does not.
    """
    rules, _ = _select_rules(_parse_groups(text), agent)
    return tuple(pattern for is_allow, pattern in rules if not is_allow)


#: The octet a `*` is expanded into, and the alternate `sample_paths` falls
#: back to. Neither is special: they are two octets that differ.
_WITNESS_OCTET = "x"
_ALTERNATE_OCTET = "y"


def _witness(pattern: str, expansion: str) -> str | None:
    """`pattern` with `$` dropped and every `*` expanded to `expansion`."""
    body = pattern[:-1] if pattern.endswith("$") else pattern
    if not body.startswith("/"):
        # RFC 9309 §2.2.2: matching starts at the first octet of the path, so a
        # pattern that does not is not a path rule this module can witness.
        return None
    return body.replace("*", expansion)


def sample_path(pattern: str) -> str | None:
    """One concrete request target that `pattern` matches, or `None`.

    A rule is a pattern, and a parser is asked about paths — so a file's own
    `Disallow` lines only become negative controls once each is turned back
    into something fetchable. §2.2.3's two metacharacters are the whole of the
    translation: `$` anchors the end and is dropped, and `*` stands for any
    sequence, for which one literal octet is the shortest witness.

    `x` rather than the empty string, because a pattern is allowed to end in
    `*` and an empty expansion would silently shorten the sample below the
    rule that produced it.

    **One witness is not enough to decide whether a file refuses anything** —
    see `sample_paths`, which is what a caller looking for a negative control
    should ask for. This returns the first of that family and is kept because
    "one path this pattern covers" is its own question.
    """
    return _witness(pattern, _WITNESS_OCTET)


def sample_paths(pattern: str) -> tuple[str, ...]:
    """Every request target this module offers as a witness for `pattern`.

    The reason there is more than one is §2.2.2 rather than §2.2.3: a witness
    only becomes a *negative control* when the whole group refuses it, and a
    competing `Allow` in the same group can capture the single witness a
    pattern produces while leaving the rest of what that pattern covers
    refused.

        User-agent: *
        Disallow: /a*
        Allow: /ax

    `/ax` — the one witness `sample_path` yields — matches both rules at three
    octets each, and §2.2.2 gives an equal-length tie to the allow. So a caller
    with that witness alone concludes the file refuses nothing, when `/ay` is
    refused by it: §2.2.3 makes `*` "any sequence of characters", so
    `Disallow: /a*` covers `/ay` while `Allow: /ax` does not. Reporting "no
    negative control is possible" for a file that plainly refuses a path is the
    fail-open direction of the error this sampling exists to prevent.

    The family, in order, each still matched by `pattern` itself:

    1. the `x` expansion — `sample_path`'s answer;
    2. that witness with one octet appended, for an **unanchored** pattern
       only: §2.2.2 matches against the beginning of the path, so the pattern
       still matches the longer string, while a competing `Allow` anchored with
       `$` no longer does. An anchored pattern matches nothing longer than its
       own body, so it is never extended;
    3. a different expansion octet, when the pattern carries `*` — this is what
       separates `/ay` from a literal, unanchored `Allow: /ax`;
    4. the empty expansion, when the pattern carries `*` — §2.2.3's "any
       sequence" includes the empty one, so it is the shortest witness the
       pattern admits, and it escapes an `Allow` whose literal body is longer.

    Order is for reporting only: a caller takes the first witness the group
    actually refuses, and each is a genuine consequence of `pattern`, so none
    of them can manufacture a refusal the file does not contain.
    """
    first = _witness(pattern, _WITNESS_OCTET)
    if first is None:
        return ()
    found = [first]
    if not pattern.endswith("$"):
        found.append(first + _WITNESS_OCTET)
    if "*" in pattern:
        for expansion in (_ALTERNATE_OCTET, ""):
            other = _witness(pattern, expansion)
            if other is not None:
                found.append(other)
    # `dict.fromkeys` rather than a set: the order above is the report order,
    # and `/a*` with an empty expansion can collide with a literal `/a`.
    return tuple(dict.fromkeys(found))


class Robots:
    """One robots.txt per host, fetched once and remembered."""

    def __init__(
        self,
        user_agent: str = USER_AGENT,
        fetch: Fetch = _read,
        browser_fetch: Fetch = _browser_read,
    ) -> None:
        self.user_agent = user_agent
        self._fetch = fetch
        self._browser_fetch = browser_fetch
        self._groups: dict[str, list[_Group]] = {}

    def _groups_for(self, url: str) -> list[_Group]:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._groups:
            robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
            try:
                text = self._fetch(robots_url)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    # The site saying "no rules", which permits everything.
                    text = ""
                elif exc.code == 403:
                    # T71: a WAF refusing the honest agent on the policy
                    # resource itself is not an answer about what the policy
                    # says, so it is not treated as one. Exactly one URL is
                    # eligible for this retry — the one already being fetched
                    # here, `/robots.txt` — and content is never refetched
                    # this way; a 403 on an advert stays unverified (T74's
                    # concern). What comes back is then obeyed like any other
                    # fetched policy, through the same `_parse_groups` and
                    # `_select_rules` this method already uses for `text` —
                    # recovering it is not license to read it more loosely.
                    try:
                        text = self._browser_fetch(robots_url)
                    except (urllib.error.HTTPError, OSError) as retry_exc:
                        raise RobotsError(
                            f"{origin}/robots.txt returned 403, and the browser-agent "
                            f"retry could not read it either: {retry_exc}"
                        ) from retry_exc
                else:
                    # 500, a redirect loop, anything else — an unanswered
                    # question, and an unanswered question is not a yes.
                    raise RobotsError(f"{origin}/robots.txt returned {exc.code}") from exc
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
    # The clause the expected verdict was READ OFF — not the clause the code
    # happens to agree with. A contested case is only worth committing if the
    # next reader can check the citation without re-deriving it, which is the
    # whole point of T102: case 22 of the round-2 audit was filed rather than
    # committed because its citation was a recollection. Empty on the fixtures
    # that predate this field; retrofitting the rest is its own pass.
    citation: str = ""


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
        robots_txt="User-agent: *\nDisallow: /%7Euser\n",
        agent="TestBot/1.0",
        url="https://example.com/~user",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 / RFC 3986 SS2.3 -- normalization is symmetric: an
        # unencoded '~' in the rule must still match a request path that spells the
        # same character as '%7E'.
        name="literal_rule_vs_percent_encoded_unreserved_request",
        robots_txt="User-agent: *\nDisallow: /~user\n",
        agent="TestBot/1.0",
        url="https://example.com/%7Euser",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 / RFC 3986 SS2.3 -- '/' is a reserved character, not
        # unreserved, so '%2F' is never decode-normalized. An identically-encoded
        # rule and request path are the same octet sequence and must match.
        name="percent_encoded_reserved_slash_exact_match",
        robots_txt="User-agent: *\nDisallow: /a%2Fb\n",
        agent="TestBot/1.0",
        url="https://example.com/a%2Fb",
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
        robots_txt="User-agent: *\nDisallow: /a%2Fb\n",
        agent="TestBot/1.0",
        url="https://example.com/a/b",
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2, incorporating RFC 3986 SS2.1 -- the hex digits of a
        # percent-encoded triplet are case-insensitive; '%C3%A9' and '%c3%a9' denote
        # the same two octets and must compare equal.
        name="percent_encoding_hex_digit_case_insensitivity",
        robots_txt="User-agent: *\nDisallow: /caf%C3%A9\n",
        agent="TestBot/1.0",
        url="https://example.com/caf%c3%a9",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 -- '%' is not itself an unreserved character, so a
        # literal '%' octet in a path is represented as '%25'. An identically
        # written rule and request path match.
        name="percent_25_literal_percent_sign_exact_match",
        robots_txt="User-agent: *\nDisallow: /100%25\n",
        agent="TestBot/1.0",
        url="https://example.com/100%25",
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
        robots_txt="User-agent: *\nDisallow: /100%25$\n",
        agent="TestBot/1.0",
        url="https://example.com/100%2525",
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 / RFC 3986 SS2.3 -- ALPHA characters are unreserved, so
        # '%41' (encoding 'A') normalizes to 'A', making the rule equivalent to
        # 'Disallow: /Admin'.
        name="percent_encoded_unreserved_letters_spelling_a_word",
        robots_txt="User-agent: *\nDisallow: /%41dmin\n",
        agent="TestBot/1.0",
        url="https://example.com/Admin",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 -- an empty value on a Disallow line imposes no
        # restriction at all; a group whose only rule is an empty Disallow permits
        # every path.
        name="empty_disallow_value_permits_everything",
        robots_txt="User-agent: *\nDisallow:\n",
        agent="TestBot/1.0",
        url="https://example.com/anything/at/all",
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 -- an empty Allow value matches a zero-length path and
        # therefore has no specificity; it must not out-rank or otherwise suppress a
        # non-empty Disallow rule that actually matches the request path.
        name="empty_allow_value_does_not_suppress_real_disallow",
        robots_txt="User-agent: *\nAllow:\nDisallow: /private\n",
        agent="TestBot/1.0",
        url="https://example.com/private",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 / SS2.2.3 -- outside of the '*' and '$' special
        # characters, a rule's octets (including '?') are matched literally as a
        # prefix of the path-plus-query string; '/path?' is a prefix of
        # '/path?query=1'.
        name="literal_question_mark_blocks_matching_query_string",
        robots_txt="User-agent: *\nDisallow: /path?\n",
        agent="TestBot/1.0",
        url="https://example.com/path?query=1",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 -- '/path?' is not a prefix of '/path' because the
        # literal '?' octet the rule requires is absent from the request; the rule
        # does not apply.
        name="literal_question_mark_does_not_block_bare_path",
        robots_txt="User-agent: *\nDisallow: /path?\n",
        agent="TestBot/1.0",
        url="https://example.com/path",
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '*' matches zero or more of any character, so '/*?'
        # matches any path that contains a literal '?' anywhere after the root,
        # including '/page?x=1'.
        name="wildcard_then_literal_question_mark_blocks_any_query",
        robots_txt="User-agent: *\nDisallow: /*?\n",
        agent="TestBot/1.0",
        url="https://example.com/page?x=1",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '/*?' requires a literal '?' to occur somewhere in the
        # path; a request with no '?' cannot satisfy the pattern no matter how '*'
        # expands.
        name="wildcard_then_literal_question_mark_does_not_block_no_query",
        robots_txt="User-agent: *\nDisallow: /*?\n",
        agent="TestBot/1.0",
        url="https://example.com/page",
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '$' designates the end of the match pattern; '/path$'
        # matches only a request path that is exactly '/path'.
        name="dollar_anchor_exact_match",
        robots_txt="User-agent: *\nDisallow: /path$\n",
        agent="TestBot/1.0",
        url="https://example.com/path",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- because '$' anchors the pattern to end exactly after
        # 'path', a request path with trailing characters ('pathxyz') does not
        # match.
        name="dollar_anchor_rejects_longer_suffix",
        robots_txt="User-agent: *\nDisallow: /path$\n",
        agent="TestBot/1.0",
        url="https://example.com/pathxyz",
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '$' requires the string to end exactly at that point;
        # '/path/' has an extra '/' octet after 'path' and therefore does not
        # satisfy '/path$'.
        name="dollar_anchor_rejects_trailing_slash",
        robots_txt="User-agent: *\nDisallow: /path$\n",
        agent="TestBot/1.0",
        url="https://example.com/path/",
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '*' matches any sequence of characters, including
        # none; '/*.php' matches any path that ends in the literal suffix '.php'
        # reached after zero or more characters, including '/index.php'.
        name="wildcard_basic_suffix_match",
        robots_txt="User-agent: *\nDisallow: /*.php\n",
        agent="TestBot/1.0",
        url="https://example.com/index.php",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '$' anchors the end of the pattern immediately after
        # '.php'; the request continues with '?x=1' after '.php', so the string does
        # not end where the pattern requires.
        name="wildcard_dollar_anchor_excludes_query_suffix",
        robots_txt="User-agent: *\nDisallow: /*.php$\n",
        agent="TestBot/1.0",
        url="https://example.com/index.php?x=1",
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '*' matches zero or more characters; two adjacent '*'
        # tokens are semantically equivalent to one and together still match any run
        # of characters between 'a' and 'b', including 'xyz'.
        name="consecutive_wildcards_collapse_to_one",
        robots_txt="User-agent: *\nDisallow: /a**b\n",
        agent="TestBot/1.0",
        url="https://example.com/axyzb",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.3 -- '*' may expand to zero characters, so '/a*$' matches a
        # path that is exactly '/a' as well as any longer path beginning with '/a'.
        name="trailing_wildcard_before_dollar_matches_zero_expansion",
        robots_txt="User-agent: *\nDisallow: /a*$\n",
        agent="TestBot/1.0",
        url="https://example.com/a",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.1 -- the crawler token 'Botly' matches the 'Botly' group
        # and only that one, so its Disallow applies. The comment here used to
        # read "the crawler MUST use the most specific (longest) matching token";
        # no such rule exists in the RFC, which says only to combine every group
        # whose token matches. The verdict is unchanged and the reason is not:
        # under equality the 'Bot' group is not a match to rank, it is a
        # non-match (T102).
        name="an_exactly_matching_group_applies_where_a_shorter_token_does_not",
        robots_txt="User-agent: Bot\nDisallow:\n\nUser-agent: Botly\nDisallow: /private\n",
        agent="Botly/2.0",
        url="https://example.com/private",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.1 -- 'Botly' is not the crawler's token 'Bot', so that
        # group does not apply and the crawler falls back to the wildcard '*'
        # group. The comment here used to justify that by a substring rule ("the
        # rule's product token must be a substring of the crawler's token"),
        # which the RFC does not state in either direction; T102 read the section
        # and replaced the reason. The verdict is unchanged.
        name="agent_token_longer_than_crawler_token_does_not_match",
        robots_txt="User-agent: Botly\nDisallow:\n\nUser-agent: *\nDisallow: /private\n",
        agent="Bot/1.0",
        url="https://example.com/private",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.1 -- matching of the User-agent product token against the
        # crawler's own token MUST be case-insensitive; 'GoogleBot' matches the
        # crawler's self-identification as 'googlebot'.
        name="agent_match_is_case_insensitive",
        robots_txt="User-agent: GoogleBot\nDisallow: /private\n",
        agent="googlebot/2.1",
        url="https://example.com/private",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 -- unlike the User-agent match, Allow/Disallow path
        # values are compared octet-for-octet, case-sensitively; '/Secret' does not
        # match the differently-cased path '/secret'.
        name="path_match_is_case_sensitive",
        robots_txt="User-agent: *\nDisallow: /Secret\n",
        agent="TestBot/1.0",
        url="https://example.com/secret",
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS2.2.1 -- consecutive User-agent lines with no intervening rule
        # lines form a single group whose rules bind every listed token; a crawler
        # matching the second-listed token 'B' is bound exactly as one matching 'A'
        # would be.
        name="shared_group_applies_to_every_listed_agent_token",
        robots_txt="User-agent: A\nUser-agent: B\nDisallow: /secret\n",
        agent="B/1.0",
        url="https://example.com/secret",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.2 -- a group that declares no Allow or Disallow lines
        # contains no restrictions, so every path is permitted for a crawler
        # matching it.
        name="group_with_no_rules_permits_everything",
        robots_txt="User-agent: *\n",
        agent="TestBot/1.0",
        url="https://example.com/anything",
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS5.1 -- when an Allow and a Disallow rule match a path with
        # equal specificity (equal matched octet length), the Allow rule takes
        # precedence.
        name="equal_length_tie_allow_wins_subpath",
        robots_txt="User-agent: *\nAllow: /page\nDisallow: /page\n",
        agent="TestBot/1.0",
        url="https://example.com/page",
        expected_allowed=True,
    ),
    _Fixture(
        # RFC 9309 SS5.1 -- the Allow-wins tie-break applies regardless of path
        # depth; equal-length root rules still resolve to Allow.
        name="equal_length_tie_allow_wins_root",
        robots_txt="User-agent: *\nAllow: /\nDisallow: /\n",
        agent="TestBot/1.0",
        url="https://example.com/",
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
        robots_txt="User-agent: *\nAllow: /%61/%62\nDisallow: /a/bcdef\n",
        agent="TestBot/1.0",
        url="https://example.com/a/bcdef",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.1 -- when the same product token reappears in more than one
        # group, the crawler MUST combine the rules of all such groups; the first
        # group's Disallow must still apply even though a later group for the same
        # token exists.
        name="duplicate_agent_groups_combine_first_groups_rule_survives",
        robots_txt="User-agent: Bot\nDisallow: /a\n\nUser-agent: Bot\nDisallow: /b\n",
        agent="Bot/1.0",
        url="https://example.com/a",
        expected_allowed=False,
    ),
    _Fixture(
        # RFC 9309 SS2.2.1 -- combining duplicate groups means the second group's
        # Disallow must also apply; a matcher that keeps only the first group it
        # encounters for a token would incorrectly allow this path.
        name="duplicate_agent_groups_combine_second_groups_rule_survives",
        robots_txt="User-agent: Bot\nDisallow: /a\n\nUser-agent: Bot\nDisallow: /b\n",
        agent="Bot/1.0",
        url="https://example.com/b",
        expected_allowed=False,
    ),
    # T102 (issue #236) -- case 22 of the round-2 T70 audit, the one case of 33
    # that was filed rather than committed because the auditor could not reach
    # the RFC and recorded a recollection ("a file token matches as a prefix of
    # a longer crawler token") instead of a citation. Read from the text, it
    # does not. The three below settle the question in both directions and in
    # the configuration where getting it wrong would fail OPEN.
    _Fixture(
        # The filed case, unchanged: file token 'Bot', crawler token 'Botly'.
        # SS2.2.1 relaxes case and nothing else, so 'Bot' does not match; there
        # is no '*' group; and the section's last clause -- "If no group matches
        # the product token and there is no group with a user-agent line with
        # the '*' value ... no rules apply" -- permits the fetch. Recording this
        # as ALLOWED is not a fail-open being blessed: the site named a crawler
        # that is not us.
        name="a_file_token_that_is_a_prefix_of_the_crawler_token_does_not_match",
        robots_txt="User-agent: Bot\nDisallow: /private\n",
        agent="Botly/2.0",
        url="https://example.com/private",
        expected_allowed=True,
        citation=(
            "RFC 9309 §2.2.1 — case-insensitive matching of the product token is the only "
            "relaxation granted; with no matching group and no `*` group, no rules apply"
        ),
    ),
    _Fixture(
        # The same non-match, in the configuration where the prefix reading
        # fails OPEN instead of closed. An explicitly matched group is used
        # exclusively, so under that reading the 'Bot' group would displace '*'
        # and permit '/private' -- a path this site disallowed for every
        # crawler. Under SS2.2.1 as written there is no match to displace it
        # with, '*' applies, and the path stays blocked. This is the fixture
        # that makes "the prefix reading is merely more conservative" false.
        name="a_prefix_file_token_does_not_displace_the_wildcard_group",
        robots_txt="User-agent: Bot\nDisallow: /other\n\nUser-agent: *\nDisallow: /private\n",
        agent="Botly/2.0",
        url="https://example.com/private",
        expected_allowed=False,
        citation=(
            "RFC 9309 §2.2.1 — a group whose token does not match is not selected, so the "
            "`*` group is still the one that applies"
        ),
    ),
    _Fixture(
        # The reverse direction, with its own citation, and deliberately with no
        # '*' group: `agent_token_longer_than_crawler_token_does_not_match` above
        # covers the same direction where a wildcard absorbs the non-match, so
        # its verdict would hold even if the non-match were wrong. Here nothing
        # absorbs it, and the verdict is the RFC's own last clause.
        name="a_file_token_longer_than_the_crawler_token_does_not_match_with_no_wildcard",
        robots_txt="User-agent: Botly\nDisallow: /private\n",
        agent="Bot/1.0",
        url="https://example.com/private",
        expected_allowed=True,
        citation=(
            "RFC 9309 §2.2.1 — the crawler's token `Bot` is not the file's token `Botly`; "
            "no group matches and there is no `*` group, so no rules apply"
        ),
    ),
    # ---------------------------------------------------------------
    # T151, 2026-09-08. §2.2.2 canonicalisation over the WHOLE of RFC 3986's
    # reserved range, in the path as well as the query. The nine cases that
    # named the defect live in the independent table (`second_reader_cases`)
    # and are re-run against this module from `test_second_reader.py`; what is
    # committed here is one per region, so the primary matcher's own gate is
    # not silent about the rule it now implements, plus the three controls that
    # stop the fix degenerating into "encode every reserved octet everywhere".
    _Fixture(
        name="a_reserved_octet_used_as_path_data_is_encoded_before_comparison",
        robots_txt="User-agent: *\nDisallow: /jobs%3Aremote/list\n",
        agent="TestBot/1.0",
        url="https://example.com/jobs:remote/list",
        expected_allowed=False,
        citation=(
            "RFC 9309 §2.2.2 — `:` is in RFC 3986 §2.2's reserved range, so both "
            "spellings canonicalise to `/jobs%3Aremote/list` and the rule applies; "
            "RFC 3986 §3.3 admits `:` inside a path segment as data"
        ),
    ),
    _Fixture(
        name="a_reserved_octet_used_as_query_data_is_encoded_before_comparison",
        robots_txt="User-agent: *\nDisallow: /s?q=a%26b\n",
        agent="TestBot/1.0",
        url="https://example.com/s?q=a&b",
        expected_allowed=False,
        citation=(
            "RFC 9309 §2.2.2 — `&` is a sub-delim in RFC 3986 §2.2's reserved "
            "range; it separates parameters for the server, not for an octet "
            "comparison, so it is data here and both sides encode it"
        ),
    ),
    _Fixture(
        # The control for the region split: `/` is the one reserved octet that
        # must NOT encode in a path, so an encoded one is data and a raw one is
        # structure and the two are different octet sequences.
        name="a_path_separator_is_not_the_same_octet_as_an_encoded_one",
        robots_txt="User-agent: *\nDisallow: /a:b/c:d\n",
        agent="TestBot/1.0",
        url="https://example.com/a%3Ab%2Fc%3Ad",
        expected_allowed=True,
        citation=(
            "RFC 3986 §3.3 — `/` delimits path segments, so RFC 9309 §2.2.2 "
            "leaves it unencoded there while `:` encodes; the rule denotes two "
            "segments and the request one, and they do not match"
        ),
    ),
    _Fixture(
        # A `*` is "any sequence of characters" (§2.2.3), the delimiter
        # included, so a pattern with no `?` of its own does not say which
        # region its later runs are in. Reading them as path octets leaves
        # `http://` spelled `http%3A//` against a target spelled
        # `http%3A%2F%2F`, and the rule matches nothing: fail-open, on the
        # shorter and more natural of the two ways to write the rule.
        name="a_rule_reaching_the_query_through_a_wildcard_still_matches",
        robots_txt="User-agent: *\nDisallow: /*http://\n",
        agent="TestBot/1.0",
        url="https://example.com/out?url=http://evil.com",
        expected_allowed=False,
        citation=(
            "RFC 9309 §2.2.3 — `*` matches any sequence of characters, `?` "
            "included, so the run behind it is admissible as query octets; "
            "§2.2.2 then encodes the `/` in that region and both sides meet"
        ),
    ),
    _Fixture(
        # And the other direction of the same rule, so accepting a query
        # spelling cannot become "accept either spelling anywhere": `%2F` in a
        # PATH is data, and a rule whose run denotes a separator must not
        # capture it. Without the region tag this over-blocks.
        name="a_wildcard_rule_denoting_a_separator_does_not_capture_encoded_data",
        robots_txt="User-agent: *\nDisallow: /*/x\n",
        agent="TestBot/1.0",
        url="https://example.com/a%2Fx",
        expected_allowed=True,
        citation=(
            "RFC 9309 §2.2.2 with RFC 3986 §3.3 — the rule's `/` is a segment "
            "separator and the request's `%2F` is an encoded data octet; they "
            "are different octet sequences and the rule does not apply"
        ),
    ),
    # ---------------------------------------------------------------
    # T151 round 2, 2026-09-08. The second reader's BLOCK on #422 and the
    # cases it named. The fix above gave an undetermined run TWO canonical
    # spellings, and `_allowed` was scoring the one that had not matched: a
    # fail-open, and a regression against `main`. These commit the class.
    _Fixture(
        # THE blocking case. `Disallow: /*http://evil` alone refuses this
        # request; adding a strictly shorter `Allow` used to let it through,
        # because the Disallow matched 19 canonical octets and was scored on
        # its 15-octet path spelling against the Allow's 18.
        name="a_wildcard_disallow_is_scored_on_the_octets_it_actually_matched",
        robots_txt="User-agent: *\nDisallow: /*http://evil\nAllow: /out?url=http%3A\n",
        agent="TestBot/1.0",
        url="https://example.com/out?url=http://evil.com",
        expected_allowed=False,
        citation=(
            'RFC 9309 §2.2.2 — the most specific match is "the match that has the '
            'most octets", and a match is between a rule and a request, so the '
            "octets counted are the ones compared: the Disallow meets 19 canonical "
            "octets (`/` + `*` + `http%3A%2F%2Fevil`) against the Allow's 18"
        ),
    ),
    _Fixture(
        # The control the reader required beside it: the SAME intent written
        # without a metacharacter. §2.2.2 canonicalises prior to comparison, so
        # two spellings of one URI set cannot reach opposite verdicts. This
        # already passed; it is committed so that a future scoring change
        # cannot fix one spelling and break the other unobserved.
        name="the_same_intent_without_a_wildcard_reaches_the_same_verdict",
        robots_txt=(
            "User-agent: *\nDisallow: /out?url=http%3A%2F%2Fevil\nAllow: /out?url=http%3A\n"
        ),
        agent="TestBot/1.0",
        url="https://example.com/out?url=http://evil.com",
        expected_allowed=False,
        citation=(
            "RFC 9309 §2.2.2 — canonicalisation happens prior to comparison, so the "
            "wildcard and non-wildcard spellings of one rule denote one URI set and "
            "must produce one verdict; here the Disallow is the longer match either way"
        ),
    ),
    _Fixture(
        # The M9 differential: nothing observed `_region_of`'s comparison, and
        # relaxing it to `>=` moves this row to ALLOW.
        name="an_anchored_rule_may_end_on_the_query_delimiter",
        robots_txt="User-agent: *\nDisallow: /*?$\n",
        agent="TestBot/1.0",
        url="https://example.com/x=?",
        expected_allowed=False,
        citation=(
            "RFC 3986 §3.4 — the query component BEGINS AFTER the first `?`, so the "
            "delimiter is the last octet of the target before the query and not the "
            "first octet of it; RFC 9309 §2.2.3 — `*` is any sequence and `$` anchors "
            "the end, so a rule ending at that delimiter matches a target ending there"
        ),
    ),
    _Fixture(
        name="a_raw_non_ascii_rule_matches_its_percent_encoded_request",
        robots_txt="User-agent: *\nDisallow: /caf\u00e9\n",
        agent="TestBot/1.0",
        url="https://example.com/caf%C3%A9",
        expected_allowed=False,
        citation=(
            "RFC 9309 §2.2.2 — octets outside the US-ASCII range are percent-encoded "
            "per RFC 3986 before comparison, so the rule's UTF-8 `é` and the "
            "request's `%C3%A9` are one octet sequence"
        ),
    ),
    _Fixture(
        # And the other direction, which nothing covered: the escape is in the
        # RULE and the raw octets are in the REQUEST.
        name="a_percent_encoded_non_ascii_rule_matches_its_raw_request",
        robots_txt="User-agent: *\nDisallow: /caf%C3%A9\n",
        agent="TestBot/1.0",
        url="https://example.com/caf\u00e9",
        expected_allowed=False,
        citation=(
            "RFC 9309 §2.2.2 — the same encoding requirement read from the request's "
            "side; canonicalisation is applied to both, so which side carries the "
            "escape cannot change the verdict"
        ),
    ),
    _Fixture(
        # The second direction of the hex-digit case, which
        # `percent_encoding_hex_digit_case_insensitivity` only covered one way
        # round (uppercase rule, lowercase request).
        name="percent_encoding_hex_digit_case_insensitivity_from_the_rules_side",
        robots_txt="User-agent: *\nDisallow: /caf%c3%a9\n",
        agent="TestBot/1.0",
        url="https://example.com/caf%C3%A9",
        expected_allowed=False,
        citation=(
            "RFC 3986 §6.2.2.1 — the hexadecimal digits of a percent-encoding triplet "
            "are case-insensitive and normalise to uppercase, so `%c3%a9` in the rule "
            "and `%C3%A9` in the request are the same octets"
        ),
    ),
    _Fixture(
        # A `?`-bearing run behind a `*`, landing in a PATH: the rule's own `?`
        # opens its query, so the run reads as `x` + delimiter + `y`, and it
        # meets a request whose `?` is in the same place.
        name="a_wildcard_run_carrying_its_own_delimiter_lands_in_a_path",
        robots_txt="User-agent: *\nDisallow: /*x?y\n",
        agent="TestBot/1.0",
        url="https://example.com/ax?y",
        expected_allowed=False,
        citation=(
            "RFC 9309 §2.2.3 — `*` matches any sequence, so `/*x?y` denotes `/` then "
            "anything then `x?y`; RFC 3986 §3.4 — the request's single `?` is its own "
            "region delimiter, matching the rule's"
        ),
    ),
    _Fixture(
        # The same run landing in a QUERY, where its `?` is data on both sides.
        # This is the case the two-spelling emission exists for: the rule's `?`
        # must spell as `%3F` to meet a second `?` in the request, which §3.4
        # makes ordinary query data.
        name="a_wildcard_run_carrying_its_own_delimiter_lands_in_a_query",
        robots_txt="User-agent: *\nDisallow: /*x?y\n",
        agent="TestBot/1.0",
        url="https://example.com/a?bx?y",
        expected_allowed=False,
        citation=(
            "RFC 9309 §2.2.3 with RFC 3986 §3.4 — the request's FIRST `?` opens its "
            "query and the second is query data, encoded `%3F`; the `*` may span the "
            "first, so the run behind it is admissible as query octets and spells its "
            "own `?` the same way"
        ),
    ),
)

# The denominator of `robots_verdicts_misread`, asserted as a FLOOR and never as
# the count of the day. Adding fixtures is what the audits are for and must
# never turn this red; removing them must, because a clean zero over a shrunken
# table is the failure this module keeps finding one level up. Raise it
# deliberately when a round of cases lands -- T102 raised it from the 56 the
# round-2 audit left to the 59 it measured, T151 raised it to 64 with the five
# §2.2.2 region cases above, and T151's second-reader round raised it to 72
# with the eight the BLOCK on #422 named.
FIXTURES_AT_LEAST = 72


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
            "citation": fixture.citation,
        }
        for fixture in fixtures
        if (actual := _verdict(fixture)) != fixture.expected_allowed
    ]
    evaluated = len(fixtures)
    return {
        "robots_verdicts_misread": len(misread),
        "robots_verdicts_evaluated": evaluated,
        "robots_verdicts_evaluated_at_least": FIXTURES_AT_LEAST,
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


@dataclass(frozen=True)
class _RefusalFixture:
    """A 403 on `/robots.txt` and the policy a browser-agent retry recovers.

    `browser_robots_txt` is `None` for the one fixture where the retry fails
    too — the honest failure this mechanism must still produce when there is
    nothing to recover, kept beside the recoverable cases so both outcomes
    are exercised by the same table.
    """

    name: str
    origin: str
    browser_robots_txt: str | None
    agent: str
    path: str
    expected_allowed: bool | None


REFUSAL_FIXTURES: tuple[_RefusalFixture, ...] = (
    _RefusalFixture(
        name="a_waf_blocks_the_honest_agent_but_the_recovered_policy_still_bars_the_path",
        origin="https://waf-protected.example",
        browser_robots_txt="User-agent: *\nDisallow: /internal/\n",
        agent=USER_AGENT,
        path="/internal/secret",
        expected_allowed=False,
    ),
    _RefusalFixture(
        name="the_recovered_policy_permits_the_path_it_says_nothing_about",
        origin="https://waf-protected.example",
        browser_robots_txt="User-agent: *\nDisallow: /internal/\n",
        agent=USER_AGENT,
        path="/ofertas",
        expected_allowed=True,
    ),
    _RefusalFixture(
        name="the_recovered_policy_names_our_own_product_token_and_bars_it",
        origin="https://tightly-waffed.example",
        browser_robots_txt="User-agent: integral-job-search\nDisallow: /\n",
        agent=USER_AGENT,
        path="/ofertas",
        expected_allowed=False,
    ),
    _RefusalFixture(
        name="the_waf_blocks_the_browser_retry_too_so_nothing_is_recoverable",
        origin="https://fully-blocked.example",
        browser_robots_txt=None,
        agent=USER_AGENT,
        path="/ofertas",
        expected_allowed=None,
    ),
)


def _recovered_verdict(fixture: _RefusalFixture) -> bool | None:
    """`allows()` after the honest agent is refused, or `None` if the retry
    could not recover a policy at all — abandonment, not a verdict, and
    distinct from a recovered `False`."""

    def fetch(url: str) -> str:
        raise urllib.error.HTTPError(url, 403, "blocked", {}, None)  # type: ignore[arg-type]

    def browser_fetch(url: str) -> str:
        if fixture.browser_robots_txt is None:
            raise urllib.error.HTTPError(url, 403, "blocked", {}, None)  # type: ignore[arg-type]
        return fixture.browser_robots_txt

    robots = Robots(user_agent=fixture.agent, fetch=fetch, browser_fetch=browser_fetch)
    try:
        return robots.allows(f"{fixture.origin}{fixture.path}")
    except RobotsError:
        return None


def measure_browser_recovery(
    fixtures: tuple[_RefusalFixture, ...] = REFUSAL_FIXTURES,
) -> dict[str, Any]:
    """T71's gate: refusals where a browser-agent retry should have recovered
    the policy (or, for the one unrecoverable fixture, correctly did not) but
    the code produced some other verdict instead.

    `robots_policies_abandoned_on_refusal_evaluated` is the denominator this
    measurement is hollow without: a zero abandonment count over zero
    evaluated refusals is not a pass, it is a check that never ran.
    """
    abandoned = [
        {
            "name": fixture.name,
            "origin": fixture.origin,
            "path": fixture.path,
            "expected_allowed": fixture.expected_allowed,
            "actual_allowed": actual,
        }
        for fixture in fixtures
        if (actual := _recovered_verdict(fixture)) != fixture.expected_allowed
    ]
    evaluated = len(fixtures)
    return {
        "robots_policies_abandoned_on_refusal": len(abandoned),
        "robots_policies_abandoned_on_refusal_evaluated": evaluated,
        "gate_status": "measured" if evaluated else "unmeasured",
        "abandoned_cases": abandoned,
    }


def write_browser_recovery_evidence(
    evidence: Path = DEFAULT_T71_EVIDENCE_PATH,
    fixtures: tuple[_RefusalFixture, ...] = REFUSAL_FIXTURES,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T71.json`."""
    measured = measure_browser_recovery(fixtures)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


_KNOWN_OPTIONS = frozenset({"--browser-recovery"})


def _main(argv: list[str]) -> int:
    """`python -m integral.robots [--browser-recovery] [path]`.

    Bare invocation writes **both** evidence files, T70's and T71's — the
    same reason `liveness.py` writes D-18 and T74 on a bare run: `make
    evidence` derives its module list from `^def _main` and runs each module
    once, with no way to know a module owns more than one gate. Naming
    `--browser-recovery` still writes T71 alone, so that gate block's own
    invocation stays precise.
    """
    options = [arg for arg in argv[1:] if arg.startswith("--")]
    unknown = [arg for arg in options if arg not in _KNOWN_OPTIONS]
    if unknown:
        print(
            f"robots: unknown option(s) {' '.join(unknown)} — "
            f"expected any of {' '.join(sorted(_KNOWN_OPTIONS))}",
            file=sys.stderr,
        )
        return 2

    positional = [arg for arg in argv[1:] if not arg.startswith("-")]
    if len(positional) > 1:
        print(
            f"robots: expected at most one path, got {len(positional)}: {' '.join(positional)}",
            file=sys.stderr,
        )
        return 2

    browser_recovery = "--browser-recovery" in options

    if not browser_recovery and not positional:
        # Each recursive call carries a positional path (or
        # `--browser-recovery`) so it lands past this branch rather than
        # back in it — otherwise a bare `python -m integral.robots` would
        # recurse into itself forever.
        recovery_rc = _main([argv[0], "--browser-recovery"])
        verdicts_rc = _main([argv[0], str(DEFAULT_EVIDENCE_PATH)])
        # `worst`, never `max`: `max(1, 3) == 3` reported a failed T70 as
        # T71's `unmeasured`, which `make evidence` records and continues
        # past. Numeric order is not severity order (`integral.gate_exit`).
        return worst(recovery_rc, verdicts_rc)

    if browser_recovery:
        target = Path(positional[0]) if positional else DEFAULT_T71_EVIDENCE_PATH
        measured = write_browser_recovery_evidence(target)
        if measured["robots_policies_abandoned_on_refusal"]:
            print(
                f"robots_policies_abandoned_on_refusal: "
                f"{measured['robots_policies_abandoned_on_refusal']} of "
                f"{measured['robots_policies_abandoned_on_refusal_evaluated']}: "
                f"{measured['abandoned_cases']}",
                file=sys.stderr,
            )
        print(json.dumps(measured, ensure_ascii=False))
        if measured["gate_status"] == "unmeasured":
            return 3
        return 1 if measured["robots_policies_abandoned_on_refusal"] else 0

    # T70's gate evidence. The `robots_verdicts_misread == 0` threshold is
    # asserted by `gate_evidence.py` against the committed file, not by this
    # exit code — the same split `integral.extraction` and
    # `integral.ontology_health` use, so a misread fixture is reported here
    # (loudly, on stderr) without halting every other module's `make
    # evidence` regeneration.
    # `FIXTURES` is passed rather than defaulted so the table is read at call
    # time: the floor below is only a guard if a test can shrink it.
    measured = write_evidence(
        Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH, FIXTURES
    )
    if measured["robots_verdicts_misread"]:
        print(
            f"robots_verdicts_misread: {measured['robots_verdicts_misread']} of "
            f"{measured['robots_verdicts_evaluated']} fixture verdicts disagree with RFC 9309: "
            f"{measured['misread_cases']}",
            file=sys.stderr,
        )
    print(json.dumps(measured, ensure_ascii=False))
    # A table that has shrunk below the floor is a hard stop, and the exit code
    # says so: `make evidence` maps 3 to "unmeasured (recorded)" and CONTINUES,
    # which would let a deleted fixture pass as an honest "cannot measure yet".
    # This is the opposite state -- the check ran, over fewer cases than it was
    # signed off on -- so it exits 1, the code that stops the build.
    if measured["robots_verdicts_evaluated"] < FIXTURES_AT_LEAST:
        print(
            f"robots_verdicts_evaluated: {measured['robots_verdicts_evaluated']} is below the "
            f"floor of {FIXTURES_AT_LEAST}: fixtures have been removed, so the misread count "
            "above is measured over a smaller table than this gate was signed off on",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
