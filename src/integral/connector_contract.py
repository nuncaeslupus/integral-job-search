"""What a connector must satisfy to be *shared* — the conformance check (T53).

T32 settled the connector **format**: declarative, data not code, no stored
credential. This settles the **package**, which is a different question. A
selector file is enough to run a connector on the machine that wrote it; it is
not enough to borrow one. Borrowing needs to know who maintains it, when it
last worked, and — above all — whether it does what it claims *without asking
the network*, because the only honest way to review a scraper somebody else
wrote is to run it against a response they recorded.

So a shared connector is a directory (`docs/distribution.md` §5):

    connectors/<site-id>/
      connector.yaml     what to fetch, and the mapping to the offer schema
      parse.py           optional, only where the declarative form cannot express it
      fixture/           one recorded response, saved verbatim
        list.html          required — the listing page rule 2 is checked against
        detail.html        optional — recorded when the connector has a `detail`
      meta.yaml          site, country, language, maintainer handle, last_verified

The two fixture filenames are fixed rather than discovered. Rule 2 has to know
which recorded file is the listing in order to check anything against it, and
"whichever file sorts first" is the kind of rule that works until somebody adds
`README.html`. A contributor is told the name by the violation message rather
than having to find it here.

and six rules, in **one command** that a contributor's agent and CI both run,
so a green local check and a green CI are the same judgement rather than two
that drift:

1. one connector, one directory, exactly those files;
2. a fixture is present, and the connector's output over it satisfies the
   offer schema **offline** — no fixture, no merge;
3. no network of its own: only the runner's HTTP client, which owns rate
   limiting, robots.txt, timeouts and the user agent (checked statically);
4. no filesystem writes, no subprocess, no environment or credential reads;
5. `meta.yaml` complete, including `last_verified`;
6. policy: public listings only, robots.txt respected, no authentication,
   paywall or captcha bypass.

## Why rules 3 and 4 are static — and exactly how far that goes

They are checked by reading `parse.py` as an **AST**, never by running it.
Running it to see what it does is the thing the rules exist to prevent: by the
time an import has executed, a module-level `socket.connect` has already
happened. So the check parses, walks, and refuses — and it refuses against an
**allowlist** of imports rather than a blocklist of bad ones. A blocklist is a
list of the attacks somebody thought of; `importlib`, `ctypes`, `os.system`
via a re-export, and `builtins.__import__` are all things a blocklist misses on
the day it is written. The allowlist is short because the job is small: a
`parse.py` turns text into text.

**This is admission lint, not a sandbox, and the difference matters.** A static
allowlist cannot bound what Python *would* do if it ran: an attribute chain off
a literal reaches `object.__subclasses__`, a name can be assembled from strings,
and neither is an import or a call this walker can name. Anyone reading these
rules as "contributed code is safe to execute" would be wrong, and would be
wrong in the direction that matters.

What actually holds the line is one property, and it is stronger than the lint:
**nothing in this repository ever executes a connector's `parse.py`.** The
interpreter in `connectors.py` reads `connector.yaml` and matches selectors; it
has no import machinery, and `test_nothing_in_the_codebase_executes_a_contributed_parse_module`
asserts that rather than trusting it. So today `parse.py` is a file the contract
*admits* and nothing *runs*.

The day a runner does want to execute one, this check is not what makes that
safe — process-level isolation is, or dropping `parse.py` in favour of widening
the declarative grammar. Raised by review on #77 and recorded here rather than
in a thread, because the person who needs it is whoever writes that runner.

This is the same argument `connectors.py` makes for its selector grammar, and
it is deliberately the same shape: match against a closed vocabulary, never
evaluate.

## Why the fixture's provenance is a rule and not a convention

Job adverts are public. The **set** of adverts a person reads is not — it
carries their field, their level, their city, and the fact that they are
looking at all. A fixture committed to a public repository carries whatever it
was made from, permanently, and no later deletion reaches a clone. So the
recorded response must declare itself a *sampled* fetch made for this purpose,
and a package whose fixture declares anything else — or declares nothing — is
refused rather than reviewed by hand.

## What this does not do

It does not create the sources repository or move connectors into it; that is
a follow-up, once there is more than one connector to move. It defines and
enforces the contract those connectors will have to satisfy, here, where there
is already one to check it against.

Exit: 0 every package conforms; 1 at least one violation; 3 nothing was
checked (no package at all is not a pass — see `MINIMUM_PACKAGES`).
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from integral.connectors import (
    CONNECTOR_FILENAME,
    DEFAULT_CONNECTORS_DIR,
    FIXTURE_DIRNAME,
    META_FILENAME,
    PROBE_DIRNAME,
    ConnectorError,
    build_offer,
    connector_packages,
    load_connector,
    parse_detail_page,
    parse_list_page,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T53.json"

PARSE_FILENAME = "parse.py"

# Rule 1. Exactly these, and nothing else. An unexpected file is a violation
# rather than a warning: "one connector, one directory" is what lets a reviewer
# know that everything in the directory is the connector, and a stray
# `notes.txt` today is a stray `credentials.env` tomorrow.
REQUIRED_ENTRIES = frozenset({CONNECTOR_FILENAME, META_FILENAME, FIXTURE_DIRNAME})

# Empty since D-10 (#78). `parse.py` used to be here, and `docs/distribution.md`
# §5 advertised it as the escape hatch for sites the declarative form cannot
# express — but nothing in this repository has ever executed one, so such a
# connector passed the whole check and could not work. The promise is withdrawn
# rather than implemented: executing contributed code needs process-level
# isolation, and the allowlist below is admission lint, not a sandbox.
# `probe/` is the connector's second capture of the same query, taken on a
# later day and read by `connector_health` to tell a rotted parser from a
# healthy one. Optional rather than required: a connector is reviewable
# without one — that check simply reports `unmeasured` until somebody on a
# permitted surface captures it.
OPTIONAL_ENTRIES: frozenset[str] = frozenset({PROBE_DIRNAME})

# Named so the refusal can say *why* rather than "unexpected file". A
# contributor who wrote a `parse.py` did what §5 told them to; they are owed the
# reason it is no longer true, not a lint message.
WITHDRAWN_ENTRIES = frozenset({PARSE_FILENAME})

# Rules 3 and 4, as an allowlist. A `parse.py` turns text into text; nothing
# here reaches a socket, a file, the environment or another process. See the
# module docstring for why this is not a blocklist.
ALLOWED_IMPORTS = frozenset({"re", "json", "datetime", "typing", "collections", "unicodedata"})

# Names that reach outside the process no matter how they are imported, so
# they are refused as calls even if some allowed module were to re-export one.
FORBIDDEN_CALLS = frozenset(
    {
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "input",
        "breakpoint",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "memoryview",
    }
)

# Rule 5. `last_verified` is the one that decays, and the one a borrower most
# needs: a connector is a claim about markup somebody else controls.
REQUIRED_META = ("site", "country", "language", "maintainer", "last_verified")

# Rule 6, as the only accepted answers. There is deliberately no vocabulary for
# "authenticated" or "paywalled" — a connector needing either could not be
# shared, so the schema cannot express it rather than the policy forbidding it.
REQUIRED_POLICY = {
    "listings": "public",
    "robots_txt": "respected",
    "authentication": "none",
}

# The fixture must say it was sampled for this purpose. See the docstring.
ACCEPTED_FIXTURE_PROVENANCE = "sampled"

# Rule 7 — a capture carries the requester's own location, and it must not ship.
#
# A board personalises what it serves: talent.com writes the requesting address,
# the city it geolocates it to, that city's postcode *and its coordinates* into
# every response. The first redaction of `talent_es` scanned for "an IPv4 and an
# IPv6 literal", found two of each, replaced them, said so in `meta.yaml` — and
# left `lat` and `lon` untouched two keys away, because a scan for the fields
# somebody remembered cannot reach the one they did not. An enumeration has no
# last element.
#
# So the rule is structural, and closed over the capture's own text. The
# requester's data is not "the fields listed below"; it is whatever the board
# put in the object it also put the address in:
#
#   1. every flat JSON object — scalar members only, so the *innermost* one —
#      is a requester block if it carries an address-bearing key or if the key
#      introducing it names the requester, and then every value in it must be a
#      placeholder. A field the board starts sending tomorrow is inside that
#      object and is covered without anyone editing a list;
#   2. an `"<address-bearing key>": <value>` pair is redacted wherever it
#      appears, block or no block;
#   3. the run of scalar pairs the board wrote *immediately before* that
#      object's key belongs to it — talent.com repeats `prefilledLocation`
#      there, and the run ends at the first character that is not another pair,
#      which on these captures is two pairs later;
#   4. an HTML attribute whose *whole* value is one the clauses above removed is
#      removed too — the board renders the location it geolocated into the
#      search box as `value="<city>, <country>"`.
#
# **Two of the four are seeds, and only the sweep is closed.** Clauses 1 and 2
# start from key names, and a name nobody thought of starts nothing — that much
# is a vocabulary and is admitted here rather than dressed up. What the rule
# buys is that one seed covers *everything around it*: the address key reached
# the coordinates, the postcode and the timezone without any of them being
# named, which is precisely what the first redaction of this package could not
# do. Adding a seed is one word and inherits the whole sweep.
#
# Clauses 1-3 are checkable over a committed capture, which is the point:
# `client_ip: redacted` in `meta.yaml` was prose, and the only code that read it
# printed it in a table row. **Clause 4 is not checkable afterwards** and is not
# claimed to be: it compares against the values the scrub removed, and once they
# are placeholders there is nothing left to compare. `scrub_requester_location`
# enforces it; `check_capture_redaction` cannot see it.
#
# What this deliberately does not do is sweep by key name, by value, or by
# key-and-value across the whole file. All three were measured against these
# captures and all three destroy advert data, because the board's own rows carry
# the same words: `city` occurs seven times, `state` three — `Catalonia` in an
# advert's address and `Catalonia` in the requester's block are the same bytes —
# `lat` three, and exactly one of each is the requester's. The object boundary
# is the only thing in the text that tells them apart, which is why the rule is
# structural and why clause 3 is bounded by adjacency rather than by matching.
ADDRESS_BEARING_KEYS = frozenset(
    {"ip", "ipLocation", "clientIp", "client_ip", "ipAddress", "remoteAddr", "remote_addr"}
)


def _key_spelling(key: str) -> str:
    """One spelling per key, so casing and separators stop being a vocabulary.

    `clientIp`, `client_ip`, `client-ip` and `Client.IP` are one key written
    four ways, and listing spellings is the enumeration that has no last
    element. Normalising closes that axis; the *vocabulary* below stays an
    explicit list and is honestly an enumeration, because the alternative —
    matching keys that merely contain `ip` — takes `zip` with it, and `zip` is
    a postcode on the requester and a field on an advert.

    This is a deletion filter over an allowlist, which is the shape CLAUDE.md
    records as fail-open for resolving an identity — there it welds decoration
    onto a login and reads as somebody else. The direction is what differs.
    Normalisation here only ever **merges** spellings into the address-bearing
    set, and a member of that set is a key this gate demands be redacted, so a
    collision asks for more redaction, never less. A key whose true spelling is
    address-bearing normalises onto its member every time; nothing leaves the
    set. Fail-closed, and named because the shape invites the other reading.
    """
    return re.sub(r"[^a-z0-9]", "", key.lower())


_ADDRESS_BEARING_SPELLINGS = frozenset(_key_spelling(k) for k in ADDRESS_BEARING_KEYS)


def _is_address_bearing(key: str) -> bool:
    return _key_spelling(key) in _ADDRESS_BEARING_SPELLINGS


# Clause 1's second seed. An address is not the only thing a board records about
# whoever fetched: talent.com also ships a Statsig `user` payload carrying a
# device hash and a stable UUID that are the *same* across two of these three
# captures, in an object with no address key in it at all.
#
# It is short because a plausible seed was measured and thrown out. `location`
# was the obvious first entry and it is **wrong**: on `greenhouse_en` the object
# introduced by `location` is the *advert's* — `{"name": "Remote"}` — so seeding
# on it redacted two job locations out of a fixture, which is the board's data
# and not the requester's. talent.com's own `location` object is reached by
# clause 1 anyway, because the address key is inside it. A seed is only worth
# adding once some capture shows a requester record that nothing else reaches.
REQUESTER_OBJECT_KEYS = frozenset({"custom", "customIDs"})

# Both halves of clause 1's vocabulary normalise, because one of them did not.
# `_key_spelling`'s own docstring argues that normalising only ever *merges*
# spellings into a set whose members must be redacted, so a collision asks for
# more redaction and never less — an argument that was true of the address half
# and simply not applied here. `Custom`, `customids` and `custom_ids` are the
# same key as `custom`, and until round 8 each of them seeded nothing: the
# object went unblocked, and reading 2 is gated on this same predicate, so the
# miss was silent rather than merely wrong.
_REQUESTER_OBJECT_SPELLINGS = frozenset(_key_spelling(k) for k in REQUESTER_OBJECT_KEYS)


def _seeds_a_block(key: str) -> bool:
    """Clause 1's seeding vocabulary, in one place because it was in two.

    Clause 1 reads *"a block seeds if the key introducing it names the
    requester"*, and an address-bearing key names the requester — that is what
    `ADDRESS_BEARING_KEYS` is for. `requester_location_blocks` consulted only
    `REQUESTER_OBJECT_KEYS` as an introducing key, so
    `{"ipLocation":{"city":"Barcelona","zip_code":"08001","lat":41.3874}}`
    scrubbed to itself: no block, no audit site, no census site, no violation,
    and the object carrying the city, the postcode and the coordinates was
    invisible to every clause and every reading at once. The block needs no
    object boundary to find — the introducing key is already in hand.

    Both seeds run through here, so the vocabulary cannot widen in one caller
    and not the other, which is how it came apart the first time.
    """
    return _key_spelling(key) in _REQUESTER_OBJECT_SPELLINGS or _is_address_bearing(key)


# The address placeholder is a real one — RFC 5737 TEST-NET-1, not globally
# routable — so a capture that is parsed still yields something address-shaped
# where the board expects an address. Everything else becomes the word or zero.
REDACTED_IP = "192.0.2.1"
REDACTED_STRING = "redacted"
REDACTED_NUMBER = "0"

# Captures are served as escaped JSON inside a script literal (`\"lat\":41.4`)
# as often as plain, so every quote below is optionally backslashed. Matching
# the text rather than parsing it is not a shortcut: a capture is evidence, and
# parse-and-reserialise would commit a file the board never sent.
# A JSON string body, escapes included. Possessive throughout, so it is
# deterministic: each alternative consumes bytes only it can consume, and the
# pattern never backtracks. That is not a micro-optimisation — a lazy body
# inside `_FLAT_JSON_OBJECT`'s repeated group backtracks exponentially and did
# not finish at all over a 546 KB capture.
#
#   [^"\\]++   ordinary bytes
#   \\\\.       two backslashes and a byte — an escape in the doubled form
#   \\(?!")    one backslash not opening a terminator — an escape when plain
#
# so it halts at `"` or at `\\"`, whichever form the capture is written in.
# What it cannot represent is an escaped quote inside a *plain* string, where
# `\\"` is both an escape and a terminator and nothing local decides which.
# Resolving that needs the enclosing structure, and these captures put 547
# braces inside string values, so the tokeniser it would take is not writable
# here. Named rather than hidden; no capture in this library contains one.
_STRING_BODY = r'(?:[^"\\]++|\\\\.|\\(?!"))*+'
_KEY = r'\\?"(' + _STRING_BODY + r')\\?"\s*:\s*'
# Every scalar a value can be, paired with the shortest prefix that identifies
# it. `_VALUE` and `_SCALAR_KEY_SITE` are both built from this one table, so a
# value shape dropped from one cannot survive in the other. That is not
# tidiness: the locator's lookahead was written out by hand for one round, and
# removing `true|false|null` from it alone left the audited domain 9.3% smaller
# with the whole suite green — a locator quietly narrower than the grammar it
# audits, which is the deletion-filter defect one level up, again.
_SCALAR_VALUES: tuple[tuple[str, str], ...] = (
    (r'\\?"' + _STRING_BODY + r'\\?"', r'\\?"'),
    (r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", r"-?\d"),
    ("true", "true"),
    ("false", "false"),
    ("null", "null"),
)
_VALUE = "(" + "|".join(whole for whole, _ in _SCALAR_VALUES) + ")"
_PAIR = re.compile(_KEY + _VALUE)
# The audit on all of the above, and the reason it is not a second opinion from
# the same regex: `_PAIR` has to match a whole value and this needs only a
# lookahead at the value's first character. Every hole in the *value* grammar —
# the documented escaped quote, and the next one — is a hole in `_PAIR`, and a
# `_PAIR` that matches nothing reads exactly like a capture with nothing to
# redact. That asymmetry is where the independence lives, and it is the whole
# of it: disagreement between the two is reported rather than resolved.
#
# The **key** is where the two must not differ, and it differed twice. The
# domain is the grammar's own, not an identifier class: `[A-Za-z_][A-Za-z0-9_.-]*`
# stood for one round on the argument that a JSON key is an identifier — true
# of the keys a board happens to serve, and not of the keys `_key_spelling`
# normalises over, which is the population this rule is about. `"client ip"`,
# `"client:ip"`, `" ip"` are all address-bearing by that function's own
# definition and none of them is an identifier: 31 of 31 separators tested gave
# a key `_PAIR` reaches and the identifier class could not see.
#
# `[^"\\]*` replaced it and was narrower again, one notch along the same axis:
# it can represent no escape at all. So `"ip\/"` seeds a block this reading
# cannot see, and one nested member inserted to cost that block left
# `Barcelona` and `41.3874` in the scrubbed output with the census reading 0,
# the audit silent and the gate green. Not hypothetical — `_PAIR` reached **4**
# key sites this locator could not on committed bytes: `campaign_objective\t`
# and `paced\t`, in both list captures. Two key classes that agree today are
# the enumeration again, so there is one: `_STRING_BODY` itself, and
# `unaudited_requester_sites` reading 3 asserts the containment in the
# direction nothing ever computed.
_SCALAR_KEY_SITE = re.compile(
    r'\\?"('
    + _STRING_BODY
    + r')\\?"\s*:\s*(?='
    + "|".join(head for _, head in _SCALAR_VALUES)
    + ")"
)
# Clause 1's seeds, located independently of the object grammar so that a block
# the grammar fails to span is reported instead of passing. Every key that
# introduces an object, filtered by `_seeds_a_block` in Python rather than
# spelled into the pattern: an alternation of literals cannot express the
# spellings `_key_spelling` normalises over, so listing them here would audit a
# narrower vocabulary than the one that seeds — which is the defect this round
# closed one level up.
_OBJECT_SEED = re.compile(_KEY + r"\{")
_FLAT_JSON_OBJECT = re.compile(
    r"\{\s*" + _KEY + _VALUE + r"(?:\s*,\s*" + _KEY + _VALUE + r")*\s*\}"
)
# Clause 3's left edge: the object's own key, preceded by however many scalar
# pairs run up to it. `\Z` anchors it to the object, so `search` over the text
# before one returns the leftmost start of that run. Bounded to a window
# because it is applied to a slice of a capture, not to a parsed document.
_LEADING_RUN = re.compile(r"(?:" + _KEY + _VALUE + r"\s*,\s*)*" + _KEY + r"\Z")
# Clause 3's right edge — and it applies to **one** of the two seeds, which is
# the whole of the distinction. An object introduced by a requester key
# (`custom`, `customIDs`) sits inside a requester record, so the scalars either
# side of it are the requester's: on this board that is `userID`, `country`,
# `locale`, and without a right edge they are covered only by the order the
# board happened to write them in. A reordering it is free to make at any time
# would leak them with nothing observable moving — the pair count does not even
# fall.
#
# An object that merely *carries* an address is embedded wherever the page put
# it, and its siblings are not the requester's. Measured here: extending right
# from `location` reaches `protocol`, `host` and `children` — the page's own
# metadata and an RSC stream reference — and redacting those corrupts the
# capture rather than protecting anybody. So the right edge is not symmetric,
# because the two seeds are not.
_TRAILING_RUN = re.compile(r"(?:\s*,\s*" + _KEY + _VALUE + r")*")
# 4,000 characters, which is the run and not the object: the widest block this
# finds across the three committed captures is 306, so the window is thirteen
# times what it has to reach — and `test_the_run_window_clears_the_widest_block`
# re-measures that rather than leaving the ratio in this comment, because a
# figure a comment states is the one thing in this file nothing checks. It is a
# bound on work rather
# than on correctness — a run longer than this is left partly unredacted and
# the capture fails the gate loudly, which is the fail-closed direction.
_RUN_WINDOW = 4000
# The ceiling on that window — here, beside what it bounds, rather than in the
# test that held it for one round. A test cannot be this guard, and the reason
# is ordering rather than taste: the run scan is quadratic in this number, so
# the guard has to fire before anything walks the library, and pytest runs a
# module's tests in definition order. Measured at `_RUN_WINDOW = 10_000_000`:
# the test holding the ceiling failed in 0.61 s, and the library walk defined
# 23 lines above it was killed at 300 s against a 22 s baseline — `make test`,
# `make host-gate` and `verified_gate.sh` all hung exactly as they did before
# the ceiling existed. An import-time refusal has no ordering to lose: nothing
# in this module runs, so no test can be the one that runs first.
#
# Eight times the present window, so ordinary growth never reaches it. Raising
# *both* numbers together is still a silent edit, and no constant can catch
# that — `test_the_library_walk_stays_inside_its_time_budget` is what does,
# because it measures the wall clock the ceiling exists to protect.
_RUN_WINDOW_CEILING = 32_000
if _RUN_WINDOW >= _RUN_WINDOW_CEILING:
    raise ValueError(
        f"_RUN_WINDOW is {_RUN_WINDOW}, at or above the {_RUN_WINDOW_CEILING}-character "
        "ceiling: the run scan is quadratic in it, and the gate does not finish"
    )
# Clause 4. A whole attribute value, never a substring: the board's own advert
# rows read `Barcelona, Barcelona, ES`, so a substring sweep for the requester's
# `Barcelona, ES` would cut an advert's location in half.
_HTML_ATTRIBUTE = re.compile(r'([A-Za-z_:][-A-Za-z0-9_:.]*)="([^"]*)"')

# A clean result over no packages is not a clean result. `verify_gates` and CI
# both read the number this module writes, and "0 violations" from an empty
# directory reads identically to "0 violations" from a directory that was
# checked — which is the failure mode every gate in this repository is built to
# refuse.
#
# T159 (F4/F5) looked at this floor against this repository's own 21-package
# `connectors/` directory and, on that comparison alone, called it the
# strongest instance of a silent gap in the repository — 1 against 21, twenty
# deletions tolerated. Raising it to 21 broke three tests
# (`test_the_contributors_command_leaves_our_committed_evidence_alone`,
# `test_meta_that_is_not_valid_utf8_leaves_the_command_with_a_documented_
# status`, `test_the_command_exits_non_zero_when_a_package_violates`), and the
# reason is real, not a fixture that needs updating: `evidence_target`'s own
# docstring says this command is *the contributor's*, run over *their own*
# directory (`docs/distribution.md` §5), and a conforming third-party library
# can legitimately be one package. So this floor's true population is not
# "this repository's own library" — it is "whatever directory this particular
# invocation was given", which varies by caller the same way
# `corpus.MIN_ADS_PER_FAMILY` and `salary_recovery.HOUSE_ESTIMATE_MINIMUM`
# (both named in `floor_sweep`'s own docstring) compare against a per-group
# count that is never the length of a fixed collection. `1` stays a floor in
# the sense this task cares about (a run over zero packages is refused, at
# `evidence_target(positional, own_library) is not None`'s own check above),
# not an accidentally-shrunk one. Left at `1`, deliberately, and out of T159's
# scope for the reason `_population_for`'s own docstring gives for those two:
# never itself the length of one fixed collection.
MINIMUM_PACKAGES = 1


@dataclass(frozen=True)
class PackageReport:
    """One package's verdict. `violations` is empty exactly when it conforms."""

    name: str
    violations: tuple[str, ...] = ()


@dataclass
class ContractReport:
    """Every package's verdict, and the total the gate reads."""

    packages: list[PackageReport] = field(default_factory=list)

    @property
    def violations(self) -> list[str]:
        return [f"{p.name}: {v}" for p in self.packages for v in p.violations]


def _load_yaml(path: Path) -> Any:
    """`safe_load`, and only ever `safe_load`.

    The same reason `connectors.py` gives: a `!!python/object/apply:` tag in a
    contributed file constructs whatever it names, at load time, before any
    rule below has had a chance to look at it.
    """
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ConnectorError(f"{path.name} could not be read: {exc}") from exc


def _as_date(raw: object) -> date | None:
    """An ISO date, or None. Never raises — the caller reports, it does not die."""
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def check_layout(package: Path) -> list[str]:
    """Rule 1 — one connector, one directory, exactly those files."""
    violations: list[str] = []
    try:
        # Dotfiles are NOT excused. Review on #77: filtering them before the
        # comparison let a committed `.env` through the one rule written to
        # keep credentials out of a shared package — the check said "exactly
        # these files" and meant "exactly these files, plus anything hidden".
        present = {p.name for p in package.iterdir()}
    except OSError as exc:
        return [f"rule 1: the package could not be listed: {exc}"]
    for required in sorted(REQUIRED_ENTRIES):
        if required not in present:
            violations.append(f"rule 1: {required} is missing")
    unexpected = sorted(present - REQUIRED_ENTRIES - OPTIONAL_ENTRIES)
    for name in unexpected:
        if name in WITHDRAWN_ENTRIES:
            violations.append(
                f"rule 1: {name} is no longer part of a connector package — nothing "
                "executes it, so a connector needing one cannot work (D-10). Sites the "
                "declarative form cannot express are met by growing connector.yaml."
            )
        else:
            violations.append(f"rule 1: {name} is not part of a connector package")
    # Both, not just the required one. `probe` became an OPTIONAL_ENTRIES member
    # and inherited the exemption from "unexpected entry" without inheriting the
    # type check — so a regular *file* named `probe` passed rule 1 while
    # `connector_health` expects a directory to read `list.html` out of.
    for dirname in (FIXTURE_DIRNAME, PROBE_DIRNAME):
        if (package / dirname).exists() and not (package / dirname).is_dir():
            violations.append(f"rule 1: {dirname} must be a directory")
    return violations


def check_meta(package: Path) -> list[str]:
    """Rules 5 and 6, plus the fixture's provenance."""
    meta_path = package / META_FILENAME
    if not meta_path.is_file():
        return [f"rule 5: {META_FILENAME} is missing"]
    try:
        meta = _load_yaml(meta_path)
    except ConnectorError as exc:
        return [f"rule 5: {exc}"]
    if not isinstance(meta, dict):
        return [f"rule 5: {META_FILENAME} is not a mapping"]

    violations: list[str] = []
    for key in REQUIRED_META:
        value = meta.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            violations.append(f"rule 5: {META_FILENAME} has no {key}")
    if meta.get("last_verified") is not None:
        raw = meta["last_verified"]
        if not isinstance(raw, date) and _as_date(raw) is None:
            violations.append(
                f"rule 5: last_verified {raw!r} is not an ISO date — a date nobody "
                "can parse is the same as no date"
            )

    policy = meta.get("policy")
    if not isinstance(policy, dict):
        violations.append("rule 6: no policy block — public listings must be declared, not assumed")
    else:
        for key, expected in REQUIRED_POLICY.items():
            actual = policy.get(key)
            if actual != expected:
                violations.append(f"rule 6: policy.{key} is {actual!r}, must be {expected!r}")

    # One verification fact, two files, and `assess_staleness` reads the
    # connector's copy — so a package could advertise a fresh date to a
    # borrower while the runtime trusted an older one (review, #77). They must
    # agree; the borrower-facing number is not allowed to be the flattering one.
    declared = meta.get("last_verified")
    if declared is not None:
        try:
            connector = load_connector(package)
        except ConnectorError:
            connector = None  # rule 2 reports an unloadable connector already
        if connector is not None:
            stated = declared if isinstance(declared, date) else _as_date(declared)
            if stated is not None and stated != connector.last_verified:
                violations.append(
                    f"rule 5: {META_FILENAME} says last_verified {stated.isoformat()} but "
                    f"{CONNECTOR_FILENAME} says {connector.last_verified.isoformat()} — "
                    "staleness is judged on the connector's copy, so the two cannot differ"
                )

    fixture_meta = meta.get("fixture")
    if not isinstance(fixture_meta, dict):
        violations.append(
            "rule 2: no fixture block — a recorded response must declare where it came from"
        )
    else:
        provenance = fixture_meta.get("provenance")
        if provenance != ACCEPTED_FIXTURE_PROVENANCE:
            violations.append(
                f"rule 2: fixture.provenance is {provenance!r}, must be "
                f"{ACCEPTED_FIXTURE_PROVENANCE!r} — a fixture is a listing sampled for this "
                "purpose, never an advert the candidate was reading"
            )
    return violations


def check_code(package: Path) -> list[str]:
    """Rules 3 and 4 — statically, by reading `parse.py`, never running it.

    No `parse.py` is the normal case and passes: the declarative form covers
    most sites, and this file exists for the ones it cannot express.
    """
    source_path = package / PARSE_FILENAME
    if not source_path.is_file():
        return []
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError) as exc:
        # A file the checker cannot read is a violation, never an exception the
        # command dies on: contributor-controlled bytes must not be able to
        # stop the gate from writing its evidence (review, #77).
        return [f"rule 3/4: {PARSE_FILENAME} could not be parsed: {exc}"]

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    violations.append(
                        f"rule 3/4: {PARSE_FILENAME} imports {alias.name!r}, which is not in "
                        f"the allowlist ({', '.join(sorted(ALLOWED_IMPORTS))})"
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            # `from . import x` has no module; a relative import inside a
            # connector package can only reach the package itself, which has no
            # other python in it, so it is refused rather than reasoned about.
            if node.level or root not in ALLOWED_IMPORTS:
                name = node.module or "." * node.level
                violations.append(
                    f"rule 3/4: {PARSE_FILENAME} imports from {name!r}, which is not in "
                    f"the allowlist ({', '.join(sorted(ALLOWED_IMPORTS))})"
                )
        # Any *mention* in a load position, not only a direct call. Review on
        # #77: matching the call target alone let `reader = open` then
        # `reader(path, "w")` straight through, and `loader = __import__` with
        # it. Naming one of these at all is the violation; there is no use for
        # `open` in a file that turns text into text.
        elif (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in FORBIDDEN_CALLS
        ):
            violations.append(f"rule 3/4: {PARSE_FILENAME} names {node.id}")
    return violations


def check_fixture(package: Path) -> list[str]:
    """Rule 2 — the connector's output over its own fixture is a valid offer.

    Offline by construction: this reads files and calls the interpreter. There
    is no HTTP client in this module to reach for, which is the point — CI
    running this over a contributed package must never become a scraping proxy
    for whatever URL that package names.
    """
    fixture_dir = package / FIXTURE_DIRNAME
    if not fixture_dir.is_dir():
        return ["rule 2: no fixture/ — no fixture, no merge"]
    try:
        recorded = sorted(
            p for p in fixture_dir.iterdir() if p.is_file() and not p.name.startswith(".")
        )
    except OSError as exc:
        return [f"rule 2: fixture/ could not be listed: {exc}"]
    if not recorded:
        return ["rule 2: fixture/ is empty — no fixture, no merge"]

    try:
        connector = load_connector(package)
    except ConnectorError as exc:
        return [f"rule 2: {exc}"]

    listing = fixture_dir / "list.html"
    if not listing.is_file():
        return [f"rule 2: fixture/list.html is missing — {[p.name for p in recorded]} recorded"]

    try:
        items = parse_list_page(connector, listing.read_text(encoding="utf-8"))
    except (ConnectorError, OSError, UnicodeDecodeError) as exc:
        return [f"rule 2: the connector could not read its own fixture: {exc}"]
    if not items:
        return [
            "rule 2: the connector selects nothing from its own fixture — a recorded response "
            "it cannot read proves the opposite of what it is for"
        ]

    detail_fields: dict[str, str] | None = None
    detail = fixture_dir / "detail.html"
    if connector.detail is not None:
        # A declared detail page must be *demonstrated*, not merely declared.
        # Review on #77: guarding on `detail.is_file()` meant a connector whose
        # listing alone yields a valid offer passed while its detail selectors
        # were never once run — the untested half of the connector being the
        # half most likely to break, since detail markup changes independently.
        if not detail.is_file():
            return [
                "rule 2: the connector declares a detail page but fixture/detail.html is "
                "missing — a declared selector with no recorded response is unproven"
            ]
        try:
            detail_fields = parse_detail_page(connector, detail.read_text(encoding="utf-8"))
        except (ConnectorError, OSError, UnicodeDecodeError) as exc:
            return [f"rule 2: the connector could not read fixture/detail.html: {exc}"]
        if not detail_fields:
            return [
                "rule 2: the connector's detail selectors match nothing in "
                "fixture/detail.html — a recorded response it cannot read proves the "
                "opposite of what it is for"
            ]

    try:
        build_offer(
            connector,
            list_fields=items[0],
            detail_fields=detail_fields,
            url=items[0].get("detail_url") or "https://example.invalid/offer",
            source_ref=f"{connector.site}:{connector.locale}",
        )
    except (ConnectorError, ValidationError) as exc:
        return [f"rule 2: the fixture does not yield a valid offer: {exc}"]
    return []


def _redacted(key: str, value: str) -> str:
    """The placeholder for one value, in the spelling the capture already uses."""
    if value in {"true", "false", "null"}:
        return value
    if not value.endswith('"'):
        return REDACTED_NUMBER
    quote = '\\"' if value.startswith("\\") else '"'
    word = REDACTED_IP if _is_address_bearing(key) else REDACTED_STRING
    return f"{quote}{word}{quote}"


def requester_location_blocks(text: str) -> list[tuple[int, int]]:
    """The span of every requester-location block in a capture.

    A block is a flat JSON object — scalar members only, which is what makes it
    the *innermost* one — that either carries an address-bearing key or is
    **introduced by** one (`_seeds_a_block`), extended in **both** directions to
    take in its own key and the run of scalar pairs written immediately either
    side of it. The introducing key seeded for `custom`/`customIDs` alone for
    six rounds, so an object announced by the address key rather than
    containing one — `{"ipLocation":{"city":…,"zip_code":…,"lat":…}}` — was
    reached by no clause and reported by no reading. Flatness is what keeps this off the
    enclosing object: on a Next.js page that is the whole props payload,
    translation strings and all, and sweeping it would take the board's own
    copy with it.

    The ceiling, stated rather than dressed up: adjacency is not membership. A
    scalar the board writes in the same object but *separated from the seed by
    a nested member that does not itself seed* is not reached. Closing that
    needs the enclosing object's own braces, and these captures put 547 braces
    inside string values, in a doubly-escaped stream — so the tokeniser it
    would take does not exist here. What is claimed is the run; what is not
    claimed is the object.

    A second ceiling, found by auditing this function rather than reported
    against it: the two runs are **not** symmetric. The leading run is searched
    for every block; the trailing run fires only for a block a requester key
    introduced. The symmetric version was written first and over-collected —
    it swept `children` (an RSC stream reference), `protocol` and `host` into
    fifteen violations across the library. So a requester scalar written
    *after* a block that seeded on its own address-bearing key is not reached.
    That is fail-open, and it is recorded here rather than closed, because
    closing it needs the same object boundary the paragraph above says is
    unavailable.

    **What is actually in that unreached run is measured, not assumed**, and
    an earlier draft of this docstring got it wrong in the fail-open
    direction: it said the neighbours are page data. Three of the seven are
    not. Identically in all three committed captures the run is `ip`,
    `userAppliedJobs`, `userJobAlertData`, `protocol`, `host`,
    `isDefaultLanguage`, `children` — so the first is the requester's own
    address, and the next two are the requester's activity. `ip` is
    address-bearing, so `_pairs_to_redact` sweeps it wherever it sits and it
    is redacted in every committed capture; the other two are `$undefined`
    here, which is a fact about this data and not a property of this rule.

    The risk the paragraph above names — that a reordering the board is free
    to make would leak them "with nothing observable moving" — is the part
    that is now closed, and only that part:
    `test_the_unreached_trailing_run_is_still_what_was_adjudicated`
    re-measures this list from the committed bytes, so a board that moves a
    key into this run turns the gate red instead of moving nothing.
    """
    spans = []
    for match in _FLAT_JSON_OBJECT.finditer(text):
        window = max(0, match.start() - _RUN_WINDOW)
        lead = _LEADING_RUN.search(text, window, match.start())
        introduced_by = lead.group(3) if lead else ""
        if not _seeds_a_block(introduced_by) and not any(
            _is_address_bearing(key) for key, _ in _PAIR.findall(match.group(0))
        ):
            continue
        end = match.end()
        if introduced_by in REQUESTER_OBJECT_KEYS:
            trail = _TRAILING_RUN.match(text, end, end + _RUN_WINDOW)
            end = trail.end() if trail else end
        spans.append(((lead.start() if lead else match.start()), end))
    return spans


def unaudited_requester_sites(text: str) -> list[tuple[int, str]]:
    """Every place rule 7 goes silent over structure it cannot read.

    Rule 7's clauses all begin by matching structure, so every one of them is
    silent when the structure does not match: a capture the grammar cannot read
    yields no pairs, no blocks and no violations, which is indistinguishable
    from a capture with nothing in it. That is the fail-open direction, and it
    is not hypothetical — `_STRING_BODY` cannot represent an escaped quote in a
    plain string, and a value ending in an escaped backslash consumes its own
    terminator, after which `_FLAT_JSON_OBJECT` matches nothing for the rest of
    the object.

    So none of this widens the grammar; it makes the grammar's *reach*
    observable. Three readings, each asking a question the structure answers
    without the grammar having to have succeeded:

    1. a scalar key site `_PAIR` does not reach — the grammar broke at the key;
    2. a seed inside no matched block — clause 1's introducing-key seed, which
       the key-level reading never asked about because those blocks need no
       address-bearing key in them;
    3. a key `_PAIR` reaches that the key-site reading cannot locate — the
       containment in the direction nothing computed for six rounds. Reading 1
       has always been `site - pair`; while the two carried different key
       classes, `pair - site` was **4** on committed bytes and no reading
       anywhere said so, which is how a key the locator could not spell came to
       seed a block the census could not count. Both now share `_STRING_BODY`,
       so this reading is empty by construction — and it is asserted rather
       than argued, because "empty by construction" is what the value axis was
       said to be for a round before it was.

    **A third reading was written here twice and both were unsound, so what
    stands in its place is a census rather than a rule.** The question it tried
    to answer is *"did the grammar lose an object it should have swept?"*, and
    answering it needs the object's own boundary. Round 5 approximated the
    boundary with `text.rfind("{")` — the nearest preceding brace, which any
    `{` inside a string value closes over — and round 6 replaced that with a
    string-aware brace-balance scan, which is the tokeniser
    `requester_location_blocks` says twice cannot be written here. The scan was
    run to find out rather than argued about: at the one unblocked address key
    in `fixture/detail.html` it arrives with an unclosed `[` on the stack and
    no enclosing object at all, because a capture is a whole HTML page and its
    braces do not balance. Both proxies answer "did the grammar break?" when
    the question is "was this key's object swept?", and both were silent on
    cases that leak. `unblocked_address_key_sites` measures the thing directly
    instead, and `measure` commits the count.
    """
    reached = {match.start(1): match.group(1) for match in _PAIR.finditer(text)}
    located = {match.start(1): match.group(1) for match in _SCALAR_KEY_SITE.finditer(text)}
    blocks = requester_location_blocks(text)

    out = [
        (start, f"the pair grammar cannot read the key {key!r} here")
        for start, key in located.items()
        if start not in reached
    ]
    out += [
        (match.start(1), f"the requester object {match.group(1)!r} is in no matched block")
        for match in _OBJECT_SEED.finditer(text)
        if _seeds_a_block(match.group(1)) and not _within(match.start(1), match.end(1), blocks)
    ]
    out += [
        (start, f"the key-site reading cannot locate the key {key!r} the pair grammar reaches")
        for start, key in reached.items()
        if start not in located
    ]
    return sorted(out)


def _within(start: int, end: int, blocks: Sequence[tuple[int, int]]) -> bool:
    return any(a <= start and end <= b for a, b in blocks)


def unblocked_address_key_sites(text: str) -> list[tuple[int, str]]:
    """Address-bearing key sites clause 1 located no block around.

    Clause 2 redacts the pair itself wherever it sits, so a site here is not a
    leak of the address. What it is, is a site whose *neighbours* nothing
    swept — and that is the whole of what rule 7 buys over a list of field
    names, so the sites themselves are worth committing rather than describing.

    It is not zero and cannot be: clause 1 is scoped to the innermost **flat**
    object, and talent.com writes `ip` one level out from the block, beside
    `userAppliedJobs`, `protocol` and `host` in an object that has nested
    members and so is deliberately out of that scope. One per talent.com
    capture, and `requester_location_blocks` adjudicates what is in that
    unreached run. `measure` commits the offset and key of each site, one row
    per capture rather than a count or a sum, for the reason given there.

    The record moves the moment a block stops being located, which is the
    failure no rule expressible here catches: breaking `prefilledLocation`'s
    value inside the real `location` object of `fixture/detail.html` costs that
    block, leaves `Barcelona` in the scrubbed output — and adds a second site to
    that capture's row while every other reading stays silent.
    """
    blocks = requester_location_blocks(text)
    return sorted(
        (match.start(1), match.group(1))
        for match in _SCALAR_KEY_SITE.finditer(text)
        if _is_address_bearing(match.group(1)) and not _within(match.start(1), match.end(1), blocks)
    )


def _pairs_to_redact(text: str) -> list[tuple[int, int, str, str]]:
    """Every `"key": value` pair the rule reaches, as `(start, end, key, value)`."""
    blocks = requester_location_blocks(text)
    return [
        (match.start(), match.end(), match.group(1), match.group(2))
        for match in _PAIR.finditer(text)
        if _is_address_bearing(match.group(1))
        or any(start <= match.start() and match.end() <= end for start, end in blocks)
    ]


def scrub_requester_location(text: str) -> tuple[str, int]:
    """Redact the requester's own location out of a capture, in the raw bytes.

    Returns the rewritten text and how many pairs changed. Never parses and
    re-serialises: what is committed has to be what the board sent, minus the
    part that is about whoever asked.
    """
    out: list[str] = []
    cursor = 0
    changed = 0
    removed: set[str] = set()
    for start, end, key, value in _pairs_to_redact(text):
        replacement = _redacted(key, value)
        if replacement == value:
            continue
        out.append(text[cursor:start])
        out.append(text[start:end].replace(value, replacement, 1))
        cursor = end
        changed += 1
        stripped = value.strip('\\"')
        if stripped:
            removed.add(stripped)
    out.append(text[cursor:])

    def _attribute(match: re.Match[str]) -> str:
        nonlocal changed
        if match.group(2) not in removed:
            return match.group(0)
        changed += 1
        return f'{match.group(1)}="{REDACTED_STRING}"'

    return _HTML_ATTRIBUTE.sub(_attribute, "".join(out)), changed


def captures(package: Path) -> Iterator[tuple[Path, str | Exception]]:
    """Every committed file in the package, as text or as the error reading it.

    Every committed file, not every `*.html`. The extension was a proxy for
    "the capture", and it is the wrong one: `probe/captured.json` records the
    URL that was fetched, and this board answers 307 by appending the city it
    geolocated the requester to — so the one file naming a URL was the one file
    never scanned.

    **The encoding was the same proxy, one axis over, and it survived the round
    that removed the glob.** The `OSError` arm reported; the `UnicodeDecodeError`
    arm one line above it `continue`d, so a file this rule could not decode left
    the population silently rather than loudly. Measured: re-encoding a leaky
    `probe/captured.json` as UTF-16 took the package from 1 violation to **0**
    with the address still on disk and `captures` yielding 5 of its 6 files. The
    latin-1 backstop does not cover it either — `_quads_in` finds nothing
    through the NULs, and on ISO-8859-1 it catches a bare IPv4 and never a city,
    a postcode or a pair of coordinates. So both arms report: whether a file is
    a capture is not a question this decides by whether it decodes.

    One traversal, shared by the rule and by the measurement `measure` commits
    about it. Two would be two populations that agree today.
    """
    for path in sorted(p for p in package.rglob("*") if p.is_file()):
        try:
            yield path, path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            yield path, exc


def check_capture_redaction(package: Path) -> list[str]:
    """Rule 7 — no capture in the package still carries who fetched it."""
    violations = []
    for path, raw in captures(package):
        if not isinstance(raw, str):
            violations.append(f"rule 7: {path.relative_to(package)} could not be read: {raw}")
            continue
        for offset, what in unaudited_requester_sites(raw):
            violations.append(
                f"rule 7: {path.relative_to(package)} at byte {offset}: {what} — a "
                "capture this rule cannot read is never a capture with nothing to "
                "redact"
            )
        for _, _, key, value in _pairs_to_redact(raw):
            if _redacted(key, value) != value:
                violations.append(
                    f"rule 7: {path.relative_to(package)} carries the requester's own "
                    f"{key} as {value} — a capture ships the board's response, never "
                    "who asked for it"
                )
    return violations


def check_package(package: Path) -> PackageReport:
    """Every rule, over one package."""
    violations = [
        *check_layout(package),
        *check_meta(package),
        *check_code(package),
        *check_fixture(package),
        *check_capture_redaction(package),
    ]
    return PackageReport(name=package.name, violations=tuple(violations))


def check_library(directory: Path = DEFAULT_CONNECTORS_DIR) -> ContractReport:
    """Every package under `directory`."""
    return ContractReport(packages=[check_package(p) for p in connector_packages(directory)])


# The invocation shapes that check a library other than ours: `--connectors DIR`
# with no destination named, which is exactly what `docs/distribution.md` §5
# hands a contributor. Held as data so D-11's gate can assert over the real
# decision function rather than restating it.
_FOREIGN_INVOCATIONS: tuple[tuple[tuple[str, ...], bool], ...] = (((), False),)


def evidence_target(positional: Sequence[str], own_library: bool) -> Path | None:
    """Where this invocation records, or `None` for "measured, recorded nowhere".

    The one place the decision lives, so `_main` and D-11's gate cannot drift:
    a gate that restates the rule instead of exercising it passes while the code
    does the opposite.
    """
    default_target = DEFAULT_EVIDENCE_PATH if own_library else None
    return Path(positional[0]) if positional else default_target


def measure(directory: Path = DEFAULT_CONNECTORS_DIR) -> dict[str, Any]:
    """T53's gate over `directory` — measured, not recorded.

    Split out from `write_evidence` so that *checking* a library and
    *recording a measurement about this repository* are two separate acts. They
    were one, and a contributor running the command this repo documents as
    theirs — over their own directory, per `docs/distribution.md` §5 — silently
    overwrote our committed `status/evidence/T53.json` with a result about
    their machine (D-11).
    """
    report = check_library(directory)
    return {
        "connector_contract_violations": len(report.violations),
        "packages_checked": len(report.packages),
        # D-11. Zero invocation shapes that check somebody else's library may
        # record into ours. Asserted over `evidence_target` itself, so restoring
        # the old unconditional default moves this number rather than leaving a
        # gate that agrees with prose the code no longer follows.
        "evidence_writes_for_a_foreign_library": sum(
            1
            for positional, own in _FOREIGN_INVOCATIONS
            if evidence_target(positional, own) == DEFAULT_EVIDENCE_PATH
        ),
        # Rule 7's own ceiling, committed as numbers rather than described in
        # prose, because prose is what a regression walks past. An
        # address-bearing key clause 1 located no block around is a key whose
        # *neighbours* nothing swept, and that sweep is the whole of what rule
        # 7 buys over a list of field names. One per talent.com capture today —
        # the `ip` the board writes one level out from the block — and this is
        # the only reading that moves when a block stops being located, which
        # no rule expressible here detects: see `unaudited_requester_sites` on
        # the two proxies that tried and the tokeniser they would have needed.
        #
        # **The sites themselves, because every summary of them compensates.**
        # Round 7 made this a row per capture, having measured that one integer
        # summed over 27 packages hides a loss: the block lost in `talent_es`'s
        # `fixture/detail.html` takes the pooled total 3 → 4, and renaming one
        # unrelated `ip` in `probe/list.html` takes it back to 3 with the block
        # still lost and still leaking. A row per capture closes that, and
        # round 8's reader found the same defect one scope in: the row was
        # `len(sites)`, so the *same* two edits inside *one* capture cancel at
        # the count and the committed record does not move at all.
        #
        # A count is a proxy for the sites; the sites are the property. There
        # is no summary of them that cannot be compensated — keys alone cancel
        # when the exposed key equals the vanished one — so the record holds
        # each site's offset and key, which are unique within a capture and
        # therefore cannot cancel. This churns when a fixture is re-captured or
        # re-excerpted, and that is correct: the record is about those bytes.
        "address_key_sites_outside_every_block": {
            f"{package.name}/{path.relative_to(package)}": [
                [offset, key] for offset, key in sorted(sites)
            ]
            for package in connector_packages(directory)
            for path, text in captures(package)
            if isinstance(text, str) and (sites := unblocked_address_key_sites(text))
        },
        "violations": report.violations,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    directory: Path = DEFAULT_CONNECTORS_DIR,
) -> dict[str, Any]:
    """Measure T53's gate from the committed connector library and record it."""
    measured = measure(directory)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """The conformance command.

        python -m integral.connector_contract [evidence-path] [--connectors DIR]

    `--connectors` is what makes this the *contributor's* command and not just
    ours: someone writing a connector on their own machine runs it over their
    own directory and gets the identical verdict CI will reach, which is the
    whole point of there being one command rather than a checklist.

    Evidence is written only when the caller said where it goes, or when the
    check ran over *this repository's* library. Recording used to be
    unconditional, so the contributor form above — the one §5 tells people to
    run — overwrote our committed `status/evidence/T53.json` with a
    `packages_checked` about their directory. `make evidence` then compared the
    result against the code and reported drift, and committing that number
    would have broken T53's gate for a reason nothing in the diff explained
    (D-11). A verdict about somebody else's directory is not evidence about
    ours; the exit code and the printed JSON carry it instead.
    """
    args = argv[1:]
    directory = DEFAULT_CONNECTORS_DIR
    own_library = True
    if "--connectors" in args:
        index = args.index("--connectors")
        if index + 1 >= len(args):
            print("connector-contract: --connectors needs a directory", file=sys.stderr)
            return 2
        directory = Path(args[index + 1])
        own_library = False
        args = args[:index] + args[index + 2 :]
    positional = [arg for arg in args if not arg.startswith("--")]
    # None means "measured, recorded nowhere" — see the docstring.
    target = evidence_target(positional, own_library)
    try:
        measured = measure(directory) if target is None else write_evidence(target, directory)
    except (ConnectorError, OSError, UnicodeDecodeError) as exc:
        # A gate that dies with a traceback has not failed — it has not run,
        # and CI cannot tell those apart from an exit code alone. Every route
        # out of here is a documented status (review, #77). Note that a *single*
        # unreadable package is not this path: it is a violation of the rule
        # whose file could not be read, reported beside the others and exiting
        # 1. This is for the library itself being unreachable.
        print(f"connector-contract: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(measured, ensure_ascii=False))
    if measured["packages_checked"] < MINIMUM_PACKAGES:
        print(
            f"only {measured['packages_checked']} package(s) checked "
            f"(floor {MINIMUM_PACKAGES}) — a clean result over nothing is not a result",
            file=sys.stderr,
        )
        return 3
    for violation in measured["violations"]:
        print(f"connector contract: {violation}", file=sys.stderr)
    return 1 if measured["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
