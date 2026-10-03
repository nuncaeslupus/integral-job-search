"""D-30: the repository's two RFC 9309 matchers take ONE reading of §2.2.2.

`integral.robots` (the matcher that decides real fetches) and
`integral.second_reader` (the independent one) both implement RFC 9309 §2.2.2,
and until D-30 they answered differently whenever a rule's literal run sat
behind a `*` that may itself span the path/query delimiter.

The reading, derived from the text and not from either module
-------------------------------------------------------------
**(P)** — a rule is canonicalised ONCE, as written, and weighs that canonical
length; it is the TARGET that is offered in a second spelling, and only to a
`Disallow`.

* §2.2.2 orders percent-encoding "prior to comparison", and applies it to "the
  URI and robots.txt paths" alike. A rule is a string; its text carries no
  region, so "its canonical form" is a property of the rule, one string.
* §2.2.3 makes `*` "any sequence of characters", so a run behind it may be
  compared against path octets or query octets. RFC 3986 §3.3 makes `/` the
  path's segment separator (structure, so it stays literal) and §3.4 admits `/`
  as ordinary query data (so it is encoded `%2F`). One text, two readings of the
  same run — the pattern has no `?` to say which.
* §2.2.2: "The most specific match found MUST be used. The most specific match
  is the match that has the most octets." Ranking rules by the octets of a
  match needs ONE length per rule, or two rules' order depends on the request.
* §2.2.2's own example table returns *Undefined* for every contest a wildcard
  rule takes part in, so the text does not choose; the choice is a risk
  decision, and this repository weighs a fail-open worse than a fail-closed.

Hence the asymmetry. A `Disallow` is offered the second spelling (it can only
make a refusal reach further). An `Allow` is not (an ambiguity is never
resolved into a permission). Weight is the as-written canonical length for both.

The losing branch, and its risk, recorded beside the choice
-----------------------------------------------------------
**(c)** — emit the ambiguous run in both spellings for allows too and weigh
whichever matched — is fail-OPEN: an `Allow` behind a `*` reaches a query and
outranks a `Disallow` (6 octets against a query, 4 against a path), so the same
rule's rank against a fixed competitor moves with the request. Measured by
`integral.second_reader`'s independent reader on #422: 150 of 1,836 contested
triples (8.2%) answered differently, 7:1 toward `robots.py` being the permissive
side.

**What (P) costs, stated rather than hidden.** (1) A site that writes
`Allow: /*/x` meaning to carve out a query gets the carve-out only through the
determinate spelling (`Allow: /*%2Fx`); the repository refuses more than the RFC
strictly requires. (2) A `Disallow` that reaches a query only through a `*`
weighs its as-written length, so a longer determinate `Allow` outranks it:
`Disallow: /*http://evil` (15) loses to `Allow: /out?url=http%3A` (16) on
`/out?url=http://evil.com`, where the Disallow alone refuses. That is the same
ranking `Disallow: /a*` (3) loses to `Allow: /abc` (4) under — the wildcard
weighs one octet — not a new exception, and `RECORDED_COST_TRIPLES` pins it so
it stays a decision.

What this module measures
-------------------------
`matcher_reading_divergences_unrecorded`: over a generated population, how many
triples the two matchers answer differently on that no committed row names. The
population is a closed product of rule, wildcard, run, region and target
components — a generator, never a list of cases — so a new component widens it
without anyone remembering to. Its size is the denominator, committed as a
floor (`naming.MINIMUM_SCANNED`'s style, T100): a generator that shrank would
otherwise score a clean zero over nothing, and an empty one reports
`gate_status: unmeasured`.

**What a zero here is not.** Two matchers agreeing is not a proof that (P) is
what they do — they could share a defect. The reading itself is pinned by
`tests/test_robots.py` and `tests/test_second_reader.py` against the RFC
derivation above, and this module is the check that the two stay ONE reading.
"""

from __future__ import annotations

import itertools
import json
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-30.json"

AGENT = "integral-job-search/0.1"

#: A triple: the whole robots.txt, the request target (path and query).
Triple = tuple[str, str]

# ---------------------------------------------------------------------------
# The generator. Every list is a COMPONENT; a triple is one choice from each.
# ---------------------------------------------------------------------------

#: The competing `Disallow` — literal, wildcard-led, anchored and delimiter-
#: carrying, so the Allow is contested at each of its possible lengths.
DISALLOW_PATTERNS = ("/a", "/a*", "/*", "/jobs", "/*a$", "/*/x", "/a?", "/a*x")

#: What the Allow starts with: nothing before its `*`, or a `*` that may span
#: the path/query delimiter, or literal text then a `*`.
ALLOW_LEADS = ("/", "/*", "/a*", "/*a")

#: The run behind the `*`. Each is chosen because RFC 3986 reads some octet in
#: it differently by region (`/`, `?`) or because the matcher treats it as
#: syntax (`$`, `*`) — the octets a run can get wrong.
ALLOW_RUNS = (
    "x",
    "/x",
    "/x/",
    "http://",
    "%2Fx",
    "%2fx",
    "?x",
    "?b=/x",
    "a/b",
    "/%2F",
    "$b",
    "=",
    "b=",
    "x$",
    "",
)

#: How the Allow ends: open, anchored, or another wildcard.
ALLOW_TAILS = ("", "$", "*")

TARGET_PATHS = ("/a", "/a/x", "/a/x/", "/jobs", "/jobs/x")

#: The query a target carries, spelled raw and encoded so the same data is
#: offered both ways.
TARGET_QUERIES = (
    "",
    "?",
    "?b=/x",
    "?b=%2Fx",
    "?u=http://x",
    "?x",
    "?b=x",
    "?q=a/b",
    "?/x",
    "?a=1&b=/x/",
)

#: The octets whose canonical form RFC 3986 §3.3 and §3.4 give differently in a
#: path and in a query. A run carrying one, behind a `*`, is the contested case.
REGION_SENSITIVE = "/?"


def allow_patterns() -> tuple[str, ...]:
    """Every Allow the components build, de-duplicated and ordered."""
    return tuple(
        sorted(
            {
                lead + run + tail
                for lead, run, tail in itertools.product(ALLOW_LEADS, ALLOW_RUNS, ALLOW_TAILS)
            }
        )
    )


def is_contested(allow: str) -> bool:
    """Whether an Allow carries a run whose region its own text leaves open.

    Read off RFC 9309 §2.2.3 and RFC 3986 §3.3/§3.4, never off a matcher: a run
    after a `*` that holds `/` or `?` has two canonical spellings. The first run
    sits at the path's first octet, so its region is not in doubt.
    """
    runs = allow.split("*")
    return any(any(ch in run for ch in REGION_SENSITIVE) for run in runs[1:])


def targets() -> tuple[str, ...]:
    return tuple(path + query for path in TARGET_PATHS for query in TARGET_QUERIES)


def generate() -> Iterator[Triple]:
    """The closed population of (robots.txt, target) triples."""
    for disallow in DISALLOW_PATTERNS:
        for allow in allow_patterns():
            text = f"User-agent: *\nDisallow: {disallow}\nAllow: {allow}\n"
            for target in targets():
                yield text, target


#: Divergences a committed row names. Empty is the settled state: D-30 took one
#: reading and eliminated the divergence rather than naming it. A triple belongs
#: here only with a dated owner's reason beside it — see `connectors/ruled-out.yaml`
#: for the standard — never because a session found it inconvenient.
RECORDED_DIVERGENCES: frozenset[Triple] = frozenset()

#: The cost of (P), pinned: both matchers answer ALLOW here, and the Disallow
#: alone would refuse. See the module docstring. It is not a divergence — the
#: matchers agree — it is the one place (P) is less safe than (c) was safe, kept
#: so removing it is an argued change.
RECORDED_COST_TRIPLES: tuple[Triple, ...] = (
    (
        "User-agent: *\nDisallow: /*http://evil\nAllow: /out?url=http%3A\n",
        "/out?url=http://evil.com",
    ),
)

#: Floors, in `naming.MINIMUM_SCANNED`'s style: what the generator guarantees,
#: committed as a literal so it does not move with the day's population. The
#: population is the product of the component tuples above after de-duplication,
#: and the floor is that size: slack under a floor is the shrunken-generator hole
#: it exists to close, since a dropped component would leave the gate `measured`
#: over a smaller scan. Zero slack, deliberately.
#: arsenal-floor-margin: MINIMUM_TRIPLES value=70000
MINIMUM_TRIPLES = 70000

#: The contested subset's own floor: the Allows carrying a region-sensitive run
#: behind a `*`, which are the only ones the divergence lives in. Without it the
#: whole population could stay above the total floor while those were deleted,
#: since uncontested triples alone can satisfy a total. Zero slack for the same
#: reason.
#: arsenal-floor-margin: MINIMUM_CONTESTED_TRIPLES value=25200
MINIMUM_CONTESTED_TRIPLES = 25200


def _verdicts(text: str, target: str) -> tuple[bool, bool]:
    # Imported here so neither matcher can reach the other through this module.
    from integral import robots, second_reader

    return bool(robots.allows_text(text, AGENT, target)), bool(
        second_reader.allows(text, AGENT, target)
    )


def _allow_of(text: str) -> str:
    return text.rsplit("Allow: ", 1)[1].rstrip("\n")


def measure(population: Iterable[Triple] | None = None) -> dict[str, Any]:
    """Run both matchers over the population and count the unrecorded gaps."""
    triples = list(generate() if population is None else population)
    compared = contested = divergences = unrecorded = 0
    robots_permissive = second_reader_permissive = 0
    examples: list[dict[str, Any]] = []
    for text, target in triples:
        compared += 1
        contested += int(is_contested(_allow_of(text)))
        robots_allows, second_allows = _verdicts(text, target)
        if robots_allows == second_allows:
            continue
        divergences += 1
        if robots_allows:
            robots_permissive += 1
        else:
            second_reader_permissive += 1
        if (text, target) not in RECORDED_DIVERGENCES:
            unrecorded += 1
            if len(examples) < 5:
                examples.append({"robots_txt": text, "target": target, "robots": robots_allows})
    cost_held = all(all(_verdicts(text, target)) for text, target in RECORDED_COST_TRIPLES)
    floored = compared >= MINIMUM_TRIPLES and contested >= MINIMUM_CONTESTED_TRIPLES
    status = "measured" if compared and floored else "unmeasured"
    return {
        "matcher_reading_divergences_unrecorded": unrecorded,
        "matcher_reading_divergences": divergences,
        "divergences_robots_more_permissive": robots_permissive,
        "divergences_second_reader_more_permissive": second_reader_permissive,
        "triples_compared": compared,
        "triples_compared_at_least": MINIMUM_TRIPLES,
        "contested_triples": contested,
        "contested_triples_at_least": MINIMUM_CONTESTED_TRIPLES,
        "recorded_divergences": len(RECORDED_DIVERGENCES),
        "recorded_cost_triples_held": cost_held,
        "unrecorded_examples": examples,
        "gate_status": status,
    }


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed: the counts of the day go out, the floors stay in."""
    moving = ("triples_compared", "contested_triples")
    return {key: value for key, value in measured.items() if key not in moving}


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH, population: Iterable[Triple] | None = None
) -> dict[str, Any]:
    """Measure and record `status/evidence/D-30.json`."""
    measured = measure(population)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str] | None = None) -> int:
    """`python -m integral.matcher_readings [--write-evidence [PATH]]`.

    Writes the record either way, because `make evidence` runs every module with
    no arguments. Exit 1 on an unrecorded divergence or a lost cost triple, 3
    when unmeasured (a verdict, not a pass), 0 otherwise.
    """
    args = [a for a in (argv or []) if a != "--write-evidence"]
    target = Path(args[0]) if args else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(record(measured), ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        print("matcher_reading_divergences_unrecorded: UNMEASURED", file=sys.stderr)
        return 3
    if (
        measured["matcher_reading_divergences_unrecorded"]
        or not measured["recorded_cost_triples_held"]
    ):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(_main(sys.argv[1:]))
