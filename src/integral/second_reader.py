"""A second robots.txt reader, written from RFC 9309 rather than from `robots.py`.

The connector ledger admits a fetch only when the repository's own matcher and
an **independent** parser agree, plus a negative control so a `True` is
distinguishable from a matcher that says yes to everything. Until T120 that
second parser was CPython's `urllib.robotparser`, and T116 measured what it is
worth: `Entry.allowance` iterates the rule list and returns on the **first**
`applies_to` hit, so on any file opening with `Allow: /` it answers `True` for
every path in the document. It implements none of §2.2.3's metacharacters
either, matching `Disallow: /a*` as the literal prefix `/a*`.

A reader that cannot refuse cannot disagree, and an agreement with a parser that
cannot disagree carries no information. This module is the replacement: a
longest-match matcher implementing §2.2.1's group selection, §2.2.2's
most-octets precedence and §2.2.3's `*`/`$`, with percent-encoding
canonicalisation derived from §2.2.3's text.

**Two things it deliberately is not.**

* It is not a copy of `integral.robots`. It was written by a session that had
  not read that module, from the RFC's text alone — a second reader derived
  from the same reading as the first is one matcher with two names, and the
  agreement between them is a tautology.
* It is not trusted for having been written here. `connector_policy._classify`
  measures **this** reader on **each file** it is asked about, exactly as it
  measured the stdlib, and a reader believed competent because of who wrote it
  is the assumption T116 removed.

The fixture table in `second_reader_cases.py` is not this session's either:
every `expected` was derived from RFC 9309 by a separate session that was
instructed not to read `src/` and never to settle a verdict by running code,
before this parser existed. `status/evidence/T120.json` counts the cases where
this reader's verdict differs from the one that session read off the RFC.

RFC citations here are marked RECOLLECTED, as everywhere else in this
repository: egress is blocked and `https://www.rfc-editor.org/rfc/rfc9309.txt`
answers 403, so the text is quoted from recollection rather than re-fetched.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from integral.second_reader_cases import (
    ALLOW_VERDICT,
    CASES,
    DISALLOW_VERDICT,
    FAIL_CLOSED_RISK,
    FAIL_OPEN_RISK,
    Case,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T120.json"

#: How this reader names itself in `connectors/robots-adjudications.yaml`.
NAME = "integral.second_reader"

#: §2.2.1's fallback group. A crawler obeys the group matching its own product
#: token and, only when no group names it, this one.
WILDCARD = "*"

ALLOW = "allow"
DISALLOW = "disallow"

#: RFC 3986's unreserved set, quoted by §2.2.3 when it says which octets a
#: percent-escape may be resolved back to. An escape encoding one of these is
#: equivalent to the character itself; an escape encoding anything else is NOT
#: resolvable — `%2F` is not a path separator, and decoding it would make a rule
#: about `/a%2Fb` silently cover `/a/b`.
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")

_HEX = "0123456789ABCDEFabcdef"


class SecondReaderError(Exception):
    """The document could not be read — never silently an allow."""


#: RFC 3986's reserved set — gen-delims `:/?#[]@` and sub-delims `!$&\'()*+,;=`.
#: §2.2.2's requirement is stated over this set, not over an example: octets
#: "outside the range of the US-ASCII coded character set, and those in the
#: reserved range defined by RFC3986, MUST be percent-encoded ... prior to
#: comparison". The section's example table then *exercises* two of them —
#: `/foo/bar?baz=https://foo.bar` has "path to match"
#: `/foo/bar?baz=https%3A%2F%2Ffoo.bar`, showing the `:` and the two `/` encoded
#: as data inside the value of `baz` — and that is an illustration of the rule,
#: never its extent.
_RESERVED = ":/?#[]@!$&'()*+,;="

#: The two reserved octets §2.2.3 gives a meaning to **inside a pattern**: `*`
#: "designates 0 or more instances of any character" and `$` "designates the end
#: of the match pattern". Encoding them in a rule would delete that rule's own
#: metacharacters, and `Disallow: /s?q=*` would stop matching anything.
#: Case 22's `confidence_note` already records that whether a literal `$` in a
#: pattern should be encoded before comparison is unsettled by the RFC; this is
#: where that reading is taken, once, rather than in each caller.
#:
#: **The hold-out is a property of patterns, and of nothing else.** A request
#: target is a sequence of octets: there is no pattern in it for `*` to
#: designate 0 or more of, or for `$` to anchor the end of. So §2.2.2's
#: requirement over RFC 3986's reserved range reaches a target's `*` and `$`
#: like every other reserved octet, and `_encode_set` is what says so — see its
#: docstring for the fail-open that reading the hold-out as two-sided produced.
_PATTERN_METACHARACTERS = "*$"

#: Reserved octets percent-encoded when they appear as **data** in a query.
#:
#: This used to be the literal string `":/"` — the two octets the example table
#: happens to exercise — which made the equivalence a description of one row
#: rather than of the rule. Every other reserved octet then escaped it in the
#: fail-open direction: `Disallow: /s?q=a%26b` did not match `/s?q=a&b`, and
#: `%3D` did not match `=`, so a rule an operator wrote in plain sight covered
#: nothing. Deriving the set from `_RESERVED` is what closes that class; adding
#: `&` and `=` to a list would have left `#`, `[`, `]`, `@`, `!`, `'`, `(`, `)`,
#: `+`, `,` and `;` still outside it.
#:
#: The query's opening `?` is not excluded here but positionally, in
#: `canonical`: it is the octet that makes "in the query" decidable at all, so
#: encoding it would leave nothing to be in. A *later* `?` is data and is
#: encoded, on both sides, like any other reserved octet.
_QUERY_DATA_OCTETS = "".join(octet for octet in _RESERVED if octet not in _PATTERN_METACHARACTERS)


def _encode_set(*, as_pattern: bool) -> str:
    """The reserved octets encoded as query data on one side of the comparison.

    §2.2.2 states its requirement over RFC 3986's whole reserved range, and that
    is what a **request target** gets: `_RESERVED`, entire. The two hold-outs
    above are §2.2.3 pattern semantics, and §2.2.3 is a section about the
    `Allow`/`Disallow` *value* — a target has no pattern in it for `*` to
    designate 0 or more of, or for `$` to end.

    Reading the hold-out as two-sided is a **fail-open**, and it was measured on
    this module: `Disallow: /s?q=a%2Ab` against `/s?q=a*b` returned ALLOW where
    §2.2.2 requires DISALLOW, because the rule's `%2A` stayed encoded while the
    target's `*` was held out of the encode pass and stayed literal, so the two
    could never compare equal. The `%24`/`$` twin returned ALLOW for the same
    reason. `integral.robots` — the matcher this reader exists to audit —
    refuses both, so on those two octets the second reader was the more
    permissive of the two, which is T116's failure mode inside its replacement.

    The fix is this function rather than a list of exceptions-to-the-exception.
    A literal list is what `_QUERY_DATA_OCTETS` used to be (`":/"`), and the
    lesson of that round is that the rule has to be made right: pattern
    semantics apply to patterns.
    """
    return _QUERY_DATA_OCTETS if as_pattern else _RESERVED


def _percent(octet: str) -> str:
    """One character as its UTF-8 percent-encoding, upper-cased."""
    return "".join(f"%{byte:02X}" for byte in octet.encode("utf-8"))


def canonical(text: str, *, encode_query_data: bool = True, as_pattern: bool = True) -> str:
    """One spelling for octet sequences §2.2.2 and §2.2.3 call equivalent.

    Comparison is octet against octet, so a rule and a request path have to be
    written the same way before they can be compared at all. §2.2.2's example
    table is the specification of what "the same way" means, and it settles
    four things, each of which this function does:

    * **An escape of an unreserved octet resolves to the octet.** `%7E` and `~`
      are the same path (RFC 3986's unreserved set is what may be resolved).
    * **Every other escape is kept, hex upper-cased.** `%2f` and `%2F` are the
      same path — and neither is `/`. Resolving an encoded slash would let a
      rule about `/a%2Fb` quietly cover `/a/b`, which is a rule matching more
      than it says.
    * **Octets outside US-ASCII are percent-encoded.** The table gives both
      `/foo/bar/☃` and `/foo/bar/%E2%98%83` the same "path to match", so a rule
      written in literal UTF-8 and a request that arrives encoded are one
      string. Encoding both sides rather than decoding both is the direction the
      table shows.
    * **Reserved octets used as data in a query are percent-encoded** — every
      octet in RFC 3986's reserved set, which is what §2.2.2 states the
      requirement over, and not only the `:` and `/` its example table happens
      to exercise. `?baz=https://foo.bar` becomes `?baz=https%3A%2F%2Ffoo.bar`,
      and by the same rule `?q=a&b` becomes `?q=a%26b`, so a rule written
      `/s?q=a%26b` matches a request written `/s?q=a&b`. The `/` inside a
      *path* is structure and stays, which is why this applies only after the
      first `?`. The first `?` is held out on both sides, positionally; the two
      pattern metacharacters `*` and `$` are held out **when canonicalising a
      pattern and only then** (`as_pattern`, the default), because §2.2.3 gives
      them a meaning in a rule and gives them none in a request target. Holding
      them out of a target too is a fail-open, and `_encode_set` records the two
      cases that measured it.

      This produces a canonical string that is not, octet for octet, the
      example table's printed "path to match" column — `?baz=` there keeps its
      `=`. It does not need to be. What §2.2.2 requires is that two spellings
      of one URI compare equal, and the transform runs over the rule and the
      target alike, so encoding a delimiter on both sides leaves every verdict
      the table states unchanged while merging the spellings it does not
      mention. Encoding one side only is what breaks, and that is the mistake
      the paragraph below is about.

    A `%` that begins no valid escape is a literal `%`, kept as one: a decoder
    that raised on `/sale/100%discount` would have to answer somehow, and the
    answer such an error path reaches for is "allow" — fail-open on a rule the
    operator wrote in plain sight.

    The transform is applied to rules and to request targets alike. Applying it
    to one side only is how an encoded and a literal spelling of the same path
    come to disagree, and the disagreement is always the fail-open way round:
    the rule stops matching.
    """
    encode_set = _encode_set(as_pattern=as_pattern)
    out: list[str] = []
    index = 0
    length = len(text)
    in_query = False
    while index < length:
        char = text[index]
        if char == "%":
            escape = text[index + 1 : index + 3]
            if len(escape) == 2 and escape[0] in _HEX and escape[1] in _HEX:
                octet = chr(int(escape, 16))
                out.append(octet if octet in _UNRESERVED else "%" + escape.upper())
                index += 3
                continue
            out.append("%")
            index += 1
            continue
        if char == "?" and not in_query:
            # The first `?` is the query delimiter, and it is the only octet
            # this function reads positionally: without one literal `?` there
            # is no query for anything to be "in". A LATER `?` is data, and
            # falls through to the reserved-octet branch below like any other.
            in_query = True
            out.append(char)
        elif ord(char) > 127 or (encode_query_data and in_query and char in encode_set):
            out.append(_percent(char))
        else:
            out.append(char)
        index += 1
    return "".join(out)


@dataclass(frozen=True)
class Rule:
    """One `Allow:` or `Disallow:` line, with the pattern it matches."""

    kind: str
    pattern: str

    @property
    def octets(self) -> int:
        """§2.2.2's specificity: 'the match that has the most octets'.

        Measured on the canonicalised pattern as written. `*` and `$` are one
        octet each and are counted, which is the reading this module takes and
        records: the alternative — measuring the span of the path the pattern
        consumed — makes specificity depend on the request rather than on the
        rule, so two paths could order the same two rules differently.
        """
        return len(self.pattern)


@dataclass(frozen=True)
class Group:
    """One §2.2 group: the product tokens it names, and the rules it carries."""

    agents: tuple[str, ...]
    rules: tuple[Rule, ...]


def _strip_comment(line: str) -> str:
    """`#` begins a comment §2.2 says runs to end of line."""
    return line.split("#", 1)[0]


def parse(text: str) -> tuple[Group, ...]:
    """Read a robots.txt into §2.2's groups.

    A group opens on a `user-agent` line and stays open across every following
    `user-agent` line, so consecutive tokens name one group. The first rule line
    closes the token list; the next `user-agent` line after a rule starts a NEW
    group. Rule lines appearing before any `user-agent` line belong to no group
    and are dropped — there is no group for them to be obeyed under, and
    attaching them to the first group that happens to follow would apply another
    crawler's restrictions to us, or ours to it.

    Unknown fields (`sitemap`, `crawl-delay`, anything else) are ignored rather
    than rejected: §2.2 requires a parser to tolerate them, and refusing the
    file over one would turn an unreadable directive into a permissive result.
    """
    # A UTF-8 BOM on the first line makes `\ufeffuser-agent` not the
    # `user-agent` field, so no group opens, every rule is dropped and every
    # path is allowed — a whole robots.txt disabled by three invisible octets,
    # in the fail-open direction. Stripped rather than tolerated: a file this
    # reader cannot open must not read as a file that permits everything.
    text = text.lstrip("\ufeff")

    groups: list[Group] = []
    agents: list[str] = []
    rules: list[Rule] = []
    seen_rule = False

    def close() -> None:
        if agents:
            groups.append(Group(agents=tuple(agents), rules=tuple(rules)))

    for raw in text.splitlines():
        line = _strip_comment(raw).strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            if seen_rule:
                close()
                agents = []
                rules = []
                seen_rule = False
            # A `User-agent:` line with no value names no product token, and the
            # rules under it would otherwise fall through to the "no group above
            # me" branch below and be dropped — silently, and fail-open, because
            # what gets dropped is usually a `Disallow`. The line is malformed
            # under §2.2's ABNF so any handling is defensible; this module takes
            # the fail-closed one and reads it as the wildcard group, exactly as
            # it strips a BOM rather than letting three invisible octets disable
            # a whole file. A rule the operator wrote is obeyed by somebody.
            agents.append(value.lower() if value else WILDCARD)
            continue
        if field in (ALLOW, DISALLOW):
            if not agents:
                # A rule with no group above it. Dropped, per the docstring.
                continue
            seen_rule = True
            rules.append(Rule(kind=field, pattern=canonical(value)))
            continue
        # Any other field: ignored, and it does not close the token list.
    close()
    return tuple(groups)


def _tokens(agent: str) -> tuple[str, ...]:
    """The product tokens one crawler answers to.

    §2.2.1 (RECOLLECTED) matches a crawler to a group by product token,
    case-insensitively. Our user agent is `integral-job-search/0.1`; the
    `User-agent:` line carries a product token without a version, so both the
    full string and the part before the `/` are offered.

    Matching is case-folded **equality** and nothing else — no prefix rule and
    no most-specific-token rule (T102 settled that, and it must not come back).
    A prefix rule would let a group named `integral` bind a crawler called
    `integral-job-search`, which is a restriction read out of a name that was
    never written.
    """
    folded = agent.strip().lower()
    head = folded.split("/", 1)[0].strip()
    return (folded, head) if head and head != folded else (folded,)


def select(groups: tuple[Group, ...], agent: str) -> tuple[Rule, ...]:
    """§2.2.1's group selection, returning the rules the crawler must obey.

    Every group naming this crawler's token is combined — a token written twice
    in one file is one group's worth of rules, and obeying only the first would
    drop restrictions the file plainly states. The `*` group is the fallback and
    is used only when **no** group names the crawler: a file that writes rules
    for us has said what it wants from us, and reading the wildcard group as
    well would apply rules it excluded us from.
    """
    wanted = set(_tokens(agent))
    named = [rule for group in groups if wanted & set(group.agents) for rule in group.rules]
    if named:
        return tuple(named)
    # A group naming us with NO rules is still a match: it says "nothing is
    # restricted for you", which is not the same as never having been named.
    if any(wanted & set(group.agents) for group in groups):
        return ()
    return tuple(rule for group in groups if WILDCARD in group.agents for rule in group.rules)


def _segments(pattern: str) -> tuple[tuple[str, ...], bool]:
    r"""§2.2.3's pattern, split into the literal runs `*` separates.

    Returns the runs and whether the pattern is end-anchored. `$` 'designates
    the end of the match pattern', so a **trailing** `$` anchors; a `$` anywhere
    else is an ordinary octet and stays in the literal run around it.

    §2.2.3's sentence describes a character at the end of a pattern and says
    nothing about one in the middle, so two readings survive it: that `$` is
    special only in final position, or that it always anchors. The second makes
    `Disallow: /a$b` describe a path that ends and then continues — which no
    path does — so the rule would match nothing and `/a$b` would be **allowed**,
    in a file that plainly disallows it. The first is the reading under which
    the operator gets what they wrote, and it is the fail-closed one of the two;
    that decides it. (This module took the anchoring reading first, and the
    independent case table caught it: `dollar_in_middle_of_pattern`, marked LOW
    confidence and fail-open.)
    """
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    return tuple(body.split("*")), anchored


def matches(pattern: str, target: str) -> bool:
    r"""Does one rule pattern cover this request target?

    §2.2.3 gives `*` 'any sequence of characters', **including the empty
    sequence** — so `/a*b` covers `/ab`, and a matcher reading `*` as 'one or
    more' silently drops the rule, which is usually a `Disallow`. The match is
    anchored at the start of the target and is otherwise a prefix match, which
    is what makes `Disallow: /admin` cover `/admin/users`.

    An **empty** pattern matches nothing. §2.2.2's `Disallow:` with no value is
    the documented way to restrict nothing at all, and reading it as the
    zero-length prefix every path starts with would invert the one line meaning
    'everything is open' into a rule covering every path in the file.

    **Why this is not a regular expression.** The obvious implementation
    compiles `*` to `.*` and calls `re.match`, and it is correct — it passes
    every case in the table. It is also a denial of service: `re` backtracks, so
    a pattern with a run of wildcards costs exponential time in the number of
    them. Measured on this module's own regex version, `Disallow: /a*a*a*…z`
    with fourteen wildcards against a sixty-character path did not finish in
    **two minutes**. robots.txt is a document fetched from a third party, so
    that is a stranger deciding how long our permission check takes, and a
    permission check that never returns is one that never says no.

    So the pattern is matched by consuming its literal runs left to right:
    the first must sit at the start, each middle run is found at the earliest
    position at or after the last one ended, and the final run is pinned to the
    end when the pattern is anchored and found anywhere otherwise. Taking each
    run as early as possible always leaves the most target for the runs after
    it, so nothing is given back and nothing is retried — the cost is linear in
    the target for each run, with no backtracking to exploit.
    """
    if not pattern:
        return False
    segments, anchored = _segments(pattern)
    first, *rest = segments
    if not target.startswith(first):
        return False
    index = len(first)
    if not rest:
        # No wildcard at all: a plain prefix, or an exact path when anchored.
        return index == len(target) if anchored else True

    last = rest[-1]
    for segment in rest[:-1]:
        if not segment:
            # Two adjacent `*`, which together still mean 'any sequence'.
            continue
        found = target.find(segment, index)
        if found < 0:
            return False
        index = found + len(segment)

    if not last:
        # The pattern ends in `*`, so whatever remains of the target matches —
        # including nothing, since `*` covers the empty sequence.
        return True
    if anchored:
        return len(target) - len(last) >= index and target.endswith(last)
    return target.find(last, index) >= 0


def _decode_query_data(text: str) -> str:
    """The query's reserved-as-data escapes resolved back to their octets.

    The mirror of the encoding pass. A request may arrive with `://` written
    out or with `%3A%2F%2F` in its place — §2.2.2's example table says those are
    one URI — and a rule reaching the query through a wildcard carries whichever
    of the two its author typed. Encoding the target is not enough on its own:
    it maps `://` onto the encoded form, but leaves an already-encoded request
    unmatched by a rule written literally, which is the same fail-open one step
    along. So the decoded form is offered as well.

    Only octets after the first `?` are touched, and only `_QUERY_DATA_OCTETS`.
    A `%2F` in a **path** stays encoded in every spelling: resolving it would
    make a rule about `/a%2Fb` cover `/a/b`, which is the fail-open the case
    table's `pct_encoded_slash_is_not_a_separator` exists to refuse.
    """
    head, delimiter, query = text.partition("?")
    if not delimiter:
        return text
    for octet in _QUERY_DATA_OCTETS:
        query = query.replace(_percent(octet), octet)
    return head + delimiter + query


def spellings(target: str) -> tuple[str, ...]:
    """Every canonical spelling a rule may legitimately be written against.

    §2.2.2's example table encodes reserved octets that appear as **data**
    inside a query value, and leaves the query's own delimiters alone. Deciding
    which octets are "in the query" needs a literal `?`, and a rule does not
    always have one: `Disallow: /*http://` reaches the query through a wildcard,
    so its `:` and `//` are canonicalised as path octets and stay literal, while
    the target's are encoded. The two then cannot match, and the rule silently
    covers nothing.

    That asymmetry is **fail-open** and it is decided by how the operator
    happened to spell a rule rather than by what they asked for:
    `Disallow: /*http://` and `Disallow: /*?*http://` are the same intent, and
    only the second one worked. So the target is offered in every spelling its
    query admits — encoded, as written, and decoded.

    **The extra spellings are offered to `Disallow` rules only**, and that
    restriction is the whole of the safety argument rather than a detail of it.
    An earlier version of this function let every rule match every spelling,
    with the justification that "comparing against more spellings can only make
    more rules apply — it never makes a `Disallow` stop matching". That was
    false, and the pre-PR review produced the witness:

        User-agent: *
        Disallow: /jobs
        Allow: /*/apply

    against `/jobs?next=%2Fapply`. The canonical path to match is
    `/jobs?next=%2Fapply`, which `Allow: /*/apply` does not match, so §2.2.2
    leaves `Disallow: /jobs` as the only matching rule and refuses. Under the
    decoded spelling the allow matches, and being eight octets to the disallow's
    five it wins — ALLOW, on a path the file refuses. Making an `Allow` apply is
    exactly how a `Disallow` stops deciding.

    So the ambiguity these spellings exist to absorb is resolved one way only:
    toward refusing. A rule whose reach into the query is uncertain can gain
    coverage when it is a `Disallow` and never when it is an `Allow`.

    The second spelling is the target read **as a target**: `canonical` holds
    `*` and `$` out of the encode pass when it is canonicalising a pattern,
    because §2.2.3 gives them a meaning there, and a request target has no
    pattern semantics for them to carry. Running the pattern's hold-out over the
    target as well left `Disallow: /s?q=a%2Ab` unable to reach `/s?q=a*b` — the
    rule's `%2A` encoded, the target's `*` literal — and the `%24`/`$` twin the
    same, both ALLOW where §2.2.2 requires DISALLOW, and both refused correctly
    by `integral.robots`. It is offered to `Disallow` rules under the same
    one-directional rule as the others: it can make a refusal reach, never an
    allow.

    Found by the independent pre-PR review, not by the case table: no case in
    the table has a wildcard spanning the `?`, so the gate was green over it.
    The `*`/`$` pair was found by the second round of the same review, in the
    exemption the first round introduced.
    """
    written = canonical(target, encode_query_data=False)
    found: list[str] = []
    candidates = (
        canonical(target),
        canonical(target, as_pattern=False),
        written,
        _decode_query_data(written),
    )
    for spelling in candidates:
        if spelling not in found:
            found.append(spelling)
    return tuple(found)


def allows(text: str, agent: str, target: str) -> bool:
    """RFC 9309's verdict for `target`, for `agent`, over the document in hand.

    §2.2.2 (RECOLLECTED): 'The most specific match found MUST be used. The most
    specific match is the match that has the most octets. If an allow rule and a
    disallow rule are equivalent, then the allow rule SHOULD be used.' And a
    path no rule matches is allowed — the protocol is an exclusion protocol, so
    silence is permission.

    The target is compared as given, path **and** query: a rule may name a query
    string (`Disallow: /*?session=`), and matching only up to the `?` would
    admit exactly the endpoints such a rule exists to exclude. Paths are
    compared case-sensitively — only product tokens are not.
    """
    if not isinstance(text, str):  # pragma: no cover - defensive
        raise SecondReaderError(f"robots.txt must be text, not {type(text).__name__}")
    rules = select(parse(text), agent)
    wanted = spellings(target)
    # An `Allow` is matched against the canonical spelling alone; a `Disallow`
    # against every spelling the query admits. See `spellings` for why the
    # widening is one-directional — it was not, and that was a fail-open.
    canonical_only = wanted[:1]
    best: Rule | None = None
    for rule in rules:
        offered = wanted if rule.kind == DISALLOW else canonical_only
        if not any(matches(rule.pattern, spelling) for spelling in offered):
            continue
        if best is None or rule.octets > best.octets:
            best = rule
        elif rule.octets == best.octets and rule.kind == ALLOW:
            # The equal-length tie §2.2.2 gives to the allow. Written as a
            # replacement rather than a `continue` so the tie is decided by the
            # rule's kind and never by which one the file happened to list
            # first — file order is exactly what the stdlib reader mistook for
            # precedence.
            best = rule
    if best is None:
        return True
    return best.kind == ALLOW


# ---------------------------------------------------------------------------
# T120's gate: `second_reader_verdicts_misread`.
# ---------------------------------------------------------------------------

#: The floor the case table is committed against. A count of the day would make
#: every added case an evidence drift (T100); a floor says what the scan
#: guaranteed without moving, and it is deliberately under what the table
#: carries. Its job is to stop a clean zero resting on an empty table — a
#: reader that reads nothing misreads nothing.
FIXTURES_AT_LEAST = 34

#: Of those, how many must be cases a weak matcher would wrongly ALLOW. A table
#: made only of paths a broken reader would wrongly refuse would score a clean
#: zero while saying nothing about the direction that matters: a fail-closed
#: bug costs one skipped fetch, a fail-open bug means the check said yes to
#: something it exists to refuse.
FAIL_OPEN_CASES_AT_LEAST = 19

#: And how many paths this reader must refuse where `urllib.robotparser` does
#: not. A "longest-match" reader that happens to agree with the stdlib on every
#: committed case has demonstrated nothing at all — the stdlib's inability to
#: refuse is the whole reason this module exists, so the table has to contain
#: the disagreement rather than assert it in prose.
STDLIB_DISAGREEMENTS_AT_LEAST = 8

#: The floor on cases derived here rather than by the independent session. It is
#: a floor for T100's reason, and it is small on purpose: this tuple exists to
#: cover branches the spec table does not reach, and if it ever grows large the
#: honest reading is that the independent table needs extending, not this one.
REGRESSION_CASES_AT_LEAST = 4


#: Cases where `integral.robots` — the repository's PRIMARY matcher, the one
#: CLAUDE.md tells every session to adjudicate a board with — answers something
#: other than what RFC 9309 requires, as measured by this table.
#:
#: There are three, and all three are **fail-open**, and all three are one bug.
#: On `Disallow: /foo/bar?baz=https%3A%2F%2Ffoo.bar` against the request
#: `/foo/bar?baz=https://foo.bar`, §2.2.2's own example table (row two) gives
#: the "path to match" as the percent-encoded form and therefore requires
#: DISALLOW. `robots.allows_text` returns True: its `_CHUNK_SAFE` allowlist
#: leaves `:` and `/` unencoded everywhere, including as data inside a query
#: value, so the rule and the request never compare equal. `_CHUNK_SAFE` also
#: carries `&` and `=`, so cases 50 and 51 fail there for the same reason and
#: by the same mechanism.
#:
#: **That defect is pre-existing and fixing it is not this task's job** — T120
#: replaces the SECOND reader. What would not be acceptable is shipping the
#: artefact that proves it and recording the proof nowhere, which is what this
#: constant and the measurement below exist to prevent: the disagreements the
#: independent table bought are the most valuable thing in it, and they were
#: invisible until the pre-PR review ran the table against both readers.
#:
#: It is pinned rather than merely counted, so a NEW disagreement appearing is a
#: test failure naming it rather than a number quietly going up. It went from
#: one to three on the review of this reader's own pull request, which is the
#: pin doing its job: the two cases the review added are the general rule that
#: the first case was one instance of, and the follow-up is scoped to the rule
#: rather than to the instance. Fixing `robots.py` is that follow-up (T151);
#: when it lands this tuple empties and the evidence drifts, which is the change
#: being visible rather than a nuisance.
REPO_MATCHER_DISAGREEMENTS = (
    "reserved_octets_stay_encoded_in_query",
    "ampersand_as_query_data_is_encoded",
    "equals_as_query_data_is_encoded",
)

#: Cases the deriving session marked LOW confidence: RFC 9309's text admits more
#: than one reading and the document says which it took and why. They gate like
#: any other case, and that is a decision rather than an oversight — each is the
#: **fail-closed** reading of its ambiguity, so a reader failing one is refusing
#: less than this repository intends to refuse. Recorded by name so that a future
#: session whose correct reader fails exactly these knows immediately it has met
#: a reading disagreement to settle in writing, not a defect to fix blind.
#:
#: The two readings this module committed to, both recorded here because nothing
#: else in the repository states them:
#:
#: * **Specificity is counted on the pattern as written** (`*` and `$` included),
#:   not on the span of the request a wildcard consumed. Otherwise a rule's
#:   precedence depends on the request, and two paths could order the same two
#:   rules differently.
#: * **`$` anchors only in final position.** A mid-pattern `$` is an ordinary
#:   octet, so `Disallow: /a$b` refuses `/a$b` rather than matching nothing.
CONTESTED_CASES = tuple(case.id for case in CASES if case.confidence == "LOW")


#: Cases derived **here**, by the session that wrote this reader, for branches
#: the independent table does not reach.
#:
#: They are kept in a separate tuple, in this module rather than in
#: `second_reader_cases`, because that module's whole value is that its author
#: never saw this code — mixing these in would spend exactly what it is for. But
#: they are counted in `second_reader_verdicts_misread` alongside it, and that
#: is the pre-PR review's finding: the gate number is what
#: `status/evidence/T120.json` commits and what `verify-gates` adjudicates
#: forever after, so a branch no committed case reaches is a branch that number
#: silently passes. Two mutation rounds found three such branches.
#:
#: Every `expected` below is still read off RFC 9309's text and cites its
#: section. What they cannot claim is independence, and they say so rather than
#: borrowing it.
REGRESSION_CASES: tuple[Case, ...] = (
    Case(
        id="interior_wildcard_matches_the_empty_sequence",
        robots_txt="User-agent: *\nDisallow: /a*b*c\n",
        agent="integral-job-search/0.1",
        path="/abc",
        expected=DISALLOW_VERDICT,
        section="RFC 9309 §2.2.3 (implementer-derived)",
        why=(
            "§2.2.3's `*` is 'any sequence of characters', the empty sequence included, "
            "and that holds for EVERY wildcard in a pattern rather than for the first "
            "one. Every pattern in the spec-derived table has at most one significant "
            "wildcard, so the matcher's interior-run branch was unreached: a mutation "
            "making an interior `*` require one character survived all 49 cases."
        ),
        direction=FAIL_OPEN_RISK,
    ),
    Case(
        id="interior_wildcard_spans_real_content",
        robots_txt="User-agent: *\nDisallow: /a*b*c\n",
        agent="integral-job-search/0.1",
        path="/axxbyyc",
        expected=DISALLOW_VERDICT,
        section="RFC 9309 §2.2.3 (implementer-derived)",
        why="The same rule with both wildcards consuming content — the ordinary reading.",
        direction=FAIL_OPEN_RISK,
    ),
    Case(
        id="interior_wildcard_does_not_reorder_the_literals",
        robots_txt="User-agent: *\nDisallow: /a*b*c\n",
        agent="integral-job-search/0.1",
        path="/acb",
        expected=ALLOW_VERDICT,
        section="RFC 9309 §2.2.3 (implementer-derived)",
        why=(
            "The literal runs must appear in the order the pattern writes them, so a "
            "path carrying the same octets in another order is not matched. The "
            "fail-closed mirror of the two above: without it a matcher could pass them "
            "by ignoring order entirely."
        ),
        direction=FAIL_CLOSED_RISK,
    ),
    Case(
        id="a_rule_reaching_the_query_through_a_wildcard",
        robots_txt="User-agent: *\nDisallow: /*http://\n",
        agent="integral-job-search/0.1",
        path="/out?url=http://evil.com",
        expected=DISALLOW_VERDICT,
        section="RFC 9309 §2.2.2 (implementer-derived)",
        why=(
            "§2.2.2's example table encodes reserved octets appearing as data in a "
            "query, and deciding what is 'in the query' needs a literal `?` — which a "
            "rule reaching the query through a wildcard does not have. So this rule was "
            "canonicalised as path octets and matched nothing, while `/*?*http://` — "
            "the same intent, differently spelled — worked. Found by the independent "
            "pre-PR review; no case in the spec table has a wildcard spanning the `?`."
        ),
        direction=FAIL_OPEN_RISK,
    ),
    Case(
        id="the_same_rule_against_an_already_encoded_request",
        robots_txt="User-agent: *\nDisallow: /*http://\n",
        agent="integral-job-search/0.1",
        path="/out?url=http%3A%2F%2Fevil.com",
        expected=DISALLOW_VERDICT,
        section="RFC 9309 §2.2.2 (implementer-derived)",
        why=(
            "The same URI arriving in its encoded spelling. Encoding the target is not "
            "enough on its own — it leaves an already-encoded request unmatched by a "
            "rule written literally, which is the same fail-open one step along — so "
            "every spelling the query admits is offered."
        ),
        direction=FAIL_OPEN_RISK,
    ),
    Case(
        id="a_wildcard_allow_does_not_outrank_a_matching_disallow",
        robots_txt="User-agent: *\nDisallow: /jobs\nAllow: /*/apply\n",
        agent="integral-job-search/0.1",
        path="/jobs?next=%2Fapply",
        expected=DISALLOW_VERDICT,
        section="RFC 9309 §2.2.2 (implementer-derived)",
        why=(
            "The canonical path to match is `/jobs?next=%2Fapply` — `%2F` is a reserved "
            "octet and is not resolved — which `Allow: /*/apply` does not match. So "
            "§2.2.2 leaves `Disallow: /jobs` as the only matching rule and refuses. "
            "This reader answered ALLOW for one round: offering every query spelling to "
            "every rule let the decoded spelling match the 8-octet allow, which then "
            "outranked the 5-octet disallow. The fix that closed one fail-open opened "
            "another on the other side, and this case is the witness the pre-PR review "
            "produced for it."
        ),
        direction=FAIL_OPEN_RISK,
    ),
    Case(
        id="a_wildcard_allow_reaching_an_encoded_query_does_not_rescue_a_refusal",
        robots_txt="User-agent: *\nDisallow: /x\nAllow: /*http://\n",
        agent="integral-job-search/0.1",
        path="/x?u=http%3A%2F%2Fy",
        expected=DISALLOW_VERDICT,
        section="RFC 9309 §2.2.2 (implementer-derived)",
        why=(
            "The second witness of the same shape, kept because the two differ in which "
            "spelling does the damage. `Disallow: /x` matches the canonical path; the "
            "allow reaches the query only through a spelling offered to resolve an "
            "ambiguity, and an ambiguity must not be resolved into a permission."
        ),
        direction=FAIL_OPEN_RISK,
    ),
    Case(
        id="an_uppercase_rule_still_refuses_an_uppercase_path",
        robots_txt="User-agent: *\nDisallow: /Private/\n",
        agent="integral-job-search/0.1",
        path="/Private/notes",
        expected=DISALLOW_VERDICT,
        section="RFC 9309 §2.2.2 (implementer-derived)",
        why=(
            "The fail-open mirror of the table's `path_matching_is_case_sensitive`, "
            "which carries only the fail-closed half (`/Private/` must not refuse "
            "`/private/notes`). Without this half, a matcher that case-folds ONE side "
            "of the comparison scores a clean zero over all 55 cases while allowing "
            "`/Private/notes` on a file that plainly refuses it. The table applies the "
            "paired-mirror discipline elsewhere (4/5, 6/7, 17/18, 29/30); this is the "
            "pair it did not make, and the pre-PR review produced the surviving mutant."
        ),
        direction=FAIL_OPEN_RISK,
    ),
    Case(
        id="an_escape_of_a_reserved_octet_compares_case_insensitively",
        robots_txt="User-agent: *\nDisallow: /a%2fb\n",
        agent="integral-job-search/0.1",
        path="/a%2Fb",
        expected=DISALLOW_VERDICT,
        section="RFC 9309 §2.2.3 (implementer-derived)",
        why=(
            "A percent-escape's hex digits are case-insensitive, so `%2f` and `%2F` are "
            "the same octet and the rule covers the path. Neither is `/`: the escape is "
            "of a RESERVED octet and stays encoded, which is what keeps a rule about "
            "`/a%2Fb` from covering `/a/b`. Dropping the `.upper()` in `canonical` was "
            "caught by a unit test but not by the committed gate number, and that "
            "number is what `verify-gates` adjudicates from here on."
        ),
        direction=FAIL_OPEN_RISK,
    ),
    Case(
        id="rules_under_an_empty_user_agent_line_are_not_dropped",
        robots_txt="User-agent: foo\nDisallow: /a\nUser-agent:\nDisallow: /b\n",
        agent="integral-job-search/0.1",
        path="/b",
        expected=DISALLOW_VERDICT,
        section="RFC 9309 §2.2 (implementer-derived)",
        why=(
            "A `User-agent:` line with an empty value names no product token. Its rules "
            "used to reach the 'no group above me' branch and be dropped, so `/b` was "
            "allowed for every crawler including us — a `Disallow` the operator wrote, "
            "discarded in silence. The line is malformed under §2.2's ABNF so any "
            "handling is defensible; the fail-closed one is to read it as the wildcard "
            "group, and this case pins that choice so it cannot revert unnoticed."
        ),
        direction=FAIL_OPEN_RISK,
    ),
    Case(
        id="a_byte_order_mark_does_not_disable_the_file",
        robots_txt="\ufeffUser-agent: *\nDisallow: /admin\n",
        agent="integral-job-search/0.1",
        path="/admin",
        expected=DISALLOW_VERDICT,
        section="RFC 9309 §2.2 (implementer-derived)",
        why=(
            "A UTF-8 BOM makes the first line's field `\ufeffuser-agent` rather than "
            "`user-agent`, so no group opens, every rule is dropped, and every path in "
            "the file is allowed — a whole robots.txt disabled by three invisible "
            "octets. §2.2's grammar describes the fields; a file that cannot be opened "
            "must not read as one that permits everything. Reported by the independent "
            "pre-PR review."
        ),
        direction=FAIL_OPEN_RISK,
    ),
    # The three below pin the two decisions that generalising
    # `_QUERY_DATA_OCTETS` from `":/"` to RFC 3986's reserved set forced, and
    # they are here because a mutation round found both unreached: with the
    # 51-case spec table green, removing the first-`?` guard survived, and so
    # did emptying `_PATTERN_METACHARACTERS`. Both surviving mutants are
    # fail-open. A generalised rule needs its exemptions pinned octet by octet
    # or the exemption list becomes the new `":/"`.
    Case(
        id="a_later_question_mark_is_query_data",
        robots_txt="User-agent: *\nDisallow: /s?q=a%3Fb\n",
        agent="integral-job-search/0.1",
        path="/s?q=a?b",
        expected=DISALLOW_VERDICT,
        section="RFC 9309 §2.2.2 (implementer-derived)",
        why=(
            "`?` is a gen-delim, so it is in RFC 3986's reserved range and §2.2.2 "
            "requires it percent-encoded before comparison like any other reserved "
            "octet. Only the FIRST `?` is exempt, and positionally rather than by "
            "class: it is the delimiter that makes 'in the query' decidable at all. A "
            "canonicaliser that treats EVERY `?` as that delimiter leaves a later one "
            "literal on the request while the rule's `%3F` stays encoded, so the two "
            "never compare equal and the rule matches nothing."
        ),
        direction=FAIL_OPEN_RISK,
    ),
    Case(
        id="a_wildcard_in_the_query_is_still_a_wildcard",
        robots_txt="User-agent: *\nDisallow: /s?q=*\n",
        agent="integral-job-search/0.1",
        path="/s?q=secret",
        expected=DISALLOW_VERDICT,
        section="RFC 9309 §2.2.3 (implementer-derived)",
        why=(
            "§2.2.3 gives `*` its pattern meaning wherever it appears in a rule, and "
            "being also an RFC 3986 sub-delim does not turn it into data. Encoding "
            "every reserved octet in the query without holding the pattern "
            "metacharacters out rewrites this rule's `*` to `%2A` — a literal run no "
            "request path carries — so the rule silently covers nothing."
        ),
        direction=FAIL_OPEN_RISK,
    ),
    Case(
        id="a_dollar_anchor_in_the_query_still_anchors",
        robots_txt="User-agent: *\nDisallow: /s?q=x$\n",
        agent="integral-job-search/0.1",
        path="/s?q=x",
        expected=DISALLOW_VERDICT,
        section="RFC 9309 §2.2.3 (implementer-derived)",
        why=(
            "The `$` half of the case above, and it needs its own row: a holdout list "
            "carrying `*` alone passes that one while rewriting this rule's `$` to "
            "`%24`, leaving an anchor no path can satisfy. §2.2.3 designates `$` 'the "
            "end of the match pattern', and a sub-delim in RFC 3986 is not that."
        ),
        direction=FAIL_OPEN_RISK,
    ),
)


def _repo_matcher_allows(text: str, agent: str, target: str) -> bool:
    """`integral.robots`' verdict, for the comparison only.

    Imported inside the function, like the stdlib reader below and for the same
    reason: this module's verdicts are derived from RFC 9309, and a second
    reader that consults the first is not a second opinion. Nothing above this
    line can reach it.
    """
    from integral import robots

    return bool(robots.allows_text(text, agent, target))


def _stdlib_allows(text: str, agent: str, target: str) -> bool:
    """`urllib.robotparser`'s verdict, for the comparison only.

    Imported here rather than at module scope so nothing in the matcher above
    can reach it: this module's verdicts are derived from RFC 9309, and a
    reader that consults the parser it replaces is not a second opinion.
    """
    import urllib.robotparser

    parser = urllib.robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch(agent, target)


def measure(cases: tuple[Case, ...] | None = None) -> dict[str, Any]:
    """Read every spec-derived case, and report where this reader disagrees.

    `second_reader_verdicts_misread` counts the cases where this module's
    verdict differs from the one RFC 9309's text requires — T70's
    `robots_verdicts_misread` one module over, and for the same reason: a
    reader is trusted for exactly the cases somebody wrote down, and those
    cases were written down by a session that had not seen this code.

    Each misread is recorded with its direction, because the two are not the
    same finding. `fail_open` means the RFC refuses a path and this reader
    allowed it: the check said yes to something it exists to refuse.
    """
    table = (CASES + REGRESSION_CASES) if cases is None else cases
    misread: list[dict[str, Any]] = []
    stdlib_disagreements: list[dict[str, str]] = []
    for case in table:
        verdict = (
            ALLOW_VERDICT if allows(case.robots_txt, case.agent, case.path) else DISALLOW_VERDICT
        )
        if verdict != case.expected:
            misread.append(
                {
                    "id": case.id,
                    "path": case.path,
                    "section": case.section,
                    "expected": case.expected,
                    "actual": verdict,
                    "direction": ("fail_open" if verdict == ALLOW_VERDICT else "fail_closed"),
                    "why": case.why,
                }
            )
        if verdict == DISALLOW_VERDICT and _stdlib_allows(case.robots_txt, case.agent, case.path):
            stdlib_disagreements.append({"id": case.id, "path": case.path})

    # The comparison the table was bought for and this module did not originally
    # make: the same 49 cases through the matcher that decides real fetches.
    spec_derived = [case for case in table if case in CASES]
    repo_disagreements = [
        {
            "id": case.id,
            "section": case.section,
            "expected": case.expected,
            "repo_matcher": (
                ALLOW_VERDICT
                if _repo_matcher_allows(case.robots_txt, case.agent, case.path)
                else DISALLOW_VERDICT
            ),
        }
        for case in spec_derived
        if (
            ALLOW_VERDICT
            if _repo_matcher_allows(case.robots_txt, case.agent, case.path)
            else DISALLOW_VERDICT
        )
        != case.expected
    ]

    regression = [case for case in table if case not in CASES]
    fail_open_cases = [case for case in table if case.direction == FAIL_OPEN_RISK]
    floored = (
        len(spec_derived) >= FIXTURES_AT_LEAST
        and len(regression) >= REGRESSION_CASES_AT_LEAST
        and len(fail_open_cases) >= FAIL_OPEN_CASES_AT_LEAST
        and len(stdlib_disagreements) >= STDLIB_DISAGREEMENTS_AT_LEAST
    )
    return {
        "second_reader_verdicts_misread": len(misread),
        "second_reader_fixtures_checked": len(table),
        "second_reader_fixtures_at_least": FIXTURES_AT_LEAST,
        # Kept apart in the record, because where a case came from is the whole
        # argument for trusting it. The gate counts both; only the first is
        # independent of the session that wrote the reader.
        "spec_derived_cases_checked": len(spec_derived),
        "implementer_regression_cases_checked": len(regression),
        "implementer_regression_cases_at_least": REGRESSION_CASES_AT_LEAST,
        "fail_open_cases_checked": len(fail_open_cases),
        "fail_open_cases_at_least": FAIL_OPEN_CASES_AT_LEAST,
        # The demonstration the gate block asks for, counted rather than
        # claimed: paths this reader refuses and `urllib.robotparser` allows.
        "paths_refused_that_the_stdlib_allows": len(stdlib_disagreements),
        "stdlib_disagreements_at_least": STDLIB_DISAGREEMENTS_AT_LEAST,
        "misread_cases": misread,
        # Not this gate's number — `second_reader_verdicts_misread` is about the
        # reader T120 adds. This is what the same table says about the matcher
        # that was already here, recorded so it cannot be shipped and forgotten.
        "repo_matcher_verdicts_against_the_rfc": len(repo_disagreements),
        "repo_matcher_disagreement_cases": repo_disagreements,
        "contested_readings_gating": list(CONTESTED_CASES),
        # `unmeasured` is the honest reading of a table too small, too
        # one-directional, or too agreeable with the stdlib to mean anything.
        # Not a pass, and not a fail.
        "gate_status": "measured" if floored else "unmeasured",
    }


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed, out of what was measured.

    The counts of the day go out and the floors they were checked against stay
    in — T100's finding, applied here before it can bite: a table that grows by
    one case would otherwise turn every future PR into an evidence drift.
    """
    moving = (
        "second_reader_fixtures_checked",
        "spec_derived_cases_checked",
        "implementer_regression_cases_checked",
        "fail_open_cases_checked",
        "paths_refused_that_the_stdlib_allows",
    )
    return {key: value for key, value in measured.items() if key not in moving}


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH, cases: tuple[Case, ...] | None = None
) -> dict[str, Any]:
    """Measure and record `status/evidence/T120.json`."""
    measured = measure(cases)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str] | None = None) -> int:
    """`python -m integral.second_reader`.

    Exit 1 on any misread case, 3 when the table is under one of its floors,
    0 otherwise. The 3 is not a pass: `make evidence` records it and continues,
    and `verify-gates` is what adjudicates the number — a zero over an empty
    table must never be reachable through this exit.
    """
    target = DEFAULT_EVIDENCE_PATH if not argv else Path(argv[0])
    measured = write_evidence(target)
    print(json.dumps(record(measured), ensure_ascii=False))
    for case in measured["misread_cases"]:
        print(
            f"{case['id']}: {case['section']} requires {case['expected']} for "
            f"{case['path']!r}, this reader says {case['actual']} ({case['direction']})",
            file=sys.stderr,
        )
    if measured["second_reader_verdicts_misread"]:
        return 1
    if measured["gate_status"] == "unmeasured":
        print(
            "second_reader_verdicts_misread: UNMEASURED — the case table is under "
            "its floor. Not a pass and not a fail.",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(_main(sys.argv[1:]))
