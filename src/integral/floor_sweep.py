"""T159 — a floor whose distance from its population is not deliberate.

A floor exists so that a clean zero over an empty or shrunken scan cannot pass as a
measurement (`naming.MINIMUM_SCANNED`'s job, repeated a dozen times across this
repository). Three shipped floors did not do that, found by hand during T122's fourth
review round rather than by anything that runs:

| module | floor | population | effect |
|---|---|---|---|
| `profile.MINIMUM_FIELDS_CHECKED` | `len(_D6_FIXTURE)` | same | `len(X)<len(X)`: never fires |
| `bodyless_post.MINIMUM_PROBES` | `8` | `len(PROBES) == 9` | first deletion breaches nothing |
| `page_placeholder.MINIMUM_PROBES` | `21` | `len(PROBES) == 25` | four deletions breach nothing |

**The rule this module enforces:** every committed floor either sits where the first
deletion breaches it, or states the margin it keeps and why. Nothing else. A floor
whose distance from its population is an accident is a floor that reports a
measurement it did not make.

## Sweeping is the hard half

Three blind spots were already found and named before this module was written, each
independently capable of re-opening the class this module exists to close:

1. **The name filter.** `MINIMUM_`/`MIN_` alone misses this repository's other two
   spellings — `*_AT_LEAST` and `*_MINIMUM` — which between them name real floors
   (`audit_followup.CASES_AT_LEAST`, `robots.FIXTURES_AT_LEAST`, `second_reader`'s
   four, `connector_policy`'s two, `connector_exchange.LEAK_NEEDLE_MINIMUM`,
   `salary_recovery.HOUSE_ESTIMATE_MINIMUM`). `_FLOOR_NAME_RE` below matches all four
   spellings, not the two the previous sweep used.
2. **An equality fingerprint.** A candidate set built by checking whether the floor
   equals its population *by construction* cannot find a floor that is *below* its
   population with no argument for the gap — the entire class in question, and the
   shape of two of the three violations in the table above. This module instead
   computes the actual margin where the population is a fixed, in-repo collection,
   and requires a written argument only where a real gap exists (`_MARGIN_ARGUED_RE`).
3. **A comparison delegated to a helper.** `review_reader._floor(observed, minimum)`
   takes the floor as an argument and does the comparison inside its own body, so a
   sweep that looks only at `Compare` nodes mentioning the floor's name directly never
   finds the four floors that go through it. `_delegated_other_operand` below follows
   exactly one call of indirection: it finds the call site, maps the floor's argument
   position to the callee's parameter name, finds a `Compare` inside the callee body
   between that parameter and another one, and maps the *other* parameter back to
   whatever expression the caller actually passed for it.

## What "in scope" means, and what is deliberately left out

Not every `MINIMUM_`/`MIN_`/`*_AT_LEAST`/`*_MINIMUM`-named constant in this repository
guards a population in the sense this module is about. `elicit_extract.MIN_ANSWER_CHARS`,
`process_spec.MIN_ITEM_WORDS`, `step_specs.MIN_FIELD_WORDS`, `skill_budget.MIN_HEADROOM_CHARS`
and `annotation.MIN_IDENTIFYING_LENGTH` are validity thresholds on **one piece of
content** — how long a single answer or field is — not floors on how much a scan
examined. `corpus.MIN_ADS_PER_FAMILY` and `salary_recovery.HOUSE_ESTIMATE_MINIMUM` are
business-rule thresholds compared against a per-group count that is never itself the
length of a collection. None of these is compared, even through one hop of tracing, to
a `len(...)` of anything — which is the one structural fact this module uses to decide
whether a name is a *population* floor at all: **a floor joins this sweep only if the
side of its comparison it bounds can be traced, through at most a local reassignment or
one delegated call, back to a `len(...)` call.** A comparison against a bare scalar
(`words < MIN_FIELD_WORDS`, `count >= HOUSE_ESTIMATE_MINIMUM`) never reaches one, so
those names are read and set aside, not silently counted as compliant.

Within that in-scope set, two different questions are being asked, because they have
different honest answers:

- **A floor over a fixed, code-owned collection** — a tuple of probes, arrangements,
  wording cases, or a fixture this module itself lists — has a population someone
  really could shrink by one edit. For these, "sits where the first deletion breaches
  it" is checked *arithmetically*: the population is counted from the collection
  literal (directly, or through a default parameter, or through the delegated-call
  mapping), and the margin is `population - floor`. Zero or negative margin passes
  outright (a breach already fires, or fires on the very next deletion). A positive
  margin passes only if the declaration's own preceding comment argues it in writing
  (`_MARGIN_ARGUED_RE`) — matching what `salary_recovery.MINIMUM_WORDING_CASES` and
  `second_reader.STDLIB_DISAGREEMENTS_AT_LEAST` already do in prose. A floor that is
  not even a literal — `profile.MINIMUM_FIELDS_CHECKED = len(_D6_FIXTURE)` — fails this
  before arithmetic is even possible: a bound derived from the population it bounds
  moves with it and can never fire, the exact shape T122 fixed on
  `gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED` by keeping the replacement a
  hand-written literal.
- **A floor over a population this repository does not itself enumerate** — a corpus
  scan, a labelled-evaluation split, PRs read from GitHub, a third party's own
  behaviour (`second_reader.STDLIB_DISAGREEMENTS_AT_LEAST` is pinned to
  `urllib.robotparser`, not to this repository's own table), or a scripted probe's own
  running `checks`/`asks`/`turns` tally built by `+= 1` in a loop rather than a
  collection this module can count — has no single "the first deletion" a diff in this
  repository could make in the same mechanical sense a tuple literal does. Counting
  exact margin against it structurally would be measuring the wrong thing, and T115
  (`floors_that_do_not_fail_the_gate`, #309) already owns the adjacent question of what
  happens when such a floor *is* breached. This module asks only that the declaration
  carry some explanation at all, and reports these separately
  (`dynamic_population_floors`) rather than folding them into the arithmetic count.
  That does not excuse an actual gap, though: eleven of these — every scripted-probe
  tally this sweep could trace through a cross-function return — turned out to be
  silently under their probe's real count with no explanation at all
  (`candidate.MINIMUM_CASES`, `constraints_step.MINIMUM_CHECKS`, `decline.MINIMUM_ASKS`,
  `freshness.MINIMUM_OFFERS`, `offers.MINIMUM_CHECKS`, `question_bank.MINIMUM_PROBES`,
  `retraction.MINIMUM_SCANNED`, `revision.MINIMUM_AGED`, `scoring.MINIMUM_TURNS`, and
  the two named beside `profile`/`bodyless_post`/`page_placeholder` above,
  `elicit_extract.MINIMUM_CHECKS` and `trait_sufficiency.MINIMUM_CHECKS`) — each raised
  by hand to what its own probe measures today, verified by running it rather than
  guessed, the same discipline the fixed-collection fixes above use.

## Round 2 — the classification was the defect

A second reader BLOCKED round 1 on PR #436 with one diagnosis: **only 11 of 46 swept
floors were ever checked arithmetically; everything else was classified away into a
branch where nothing could fail.** Six findings, all fail-open, all behind a green
gate. Answering them one at a time was explicitly the wrong move — enumeration has no
last element — so this round changes the *shape* of the classification instead:

1. **All fourteen floors round 1 fixed could be dropped to `1` with the metric still
   reading `0`.** The three arithmetic ones were excused by `_MARGIN_ARGUED_RE`
   matching the words `raised`/`slack` regardless of whether the number beside them was
   still true; the other eleven, classified `dynamic`, needed only *a* comment, not a
   *true* one. Fixed by `_zero_slack_claim_contradicts`: every one of the fourteen
   comments states a specific number ("Raised to what the probe carries — N, zero
   slack"), and that number is now re-extracted and compared against the floor's
   *current* value on every sweep — a keyword match cannot tell a claim that used to be
   true from one that still is, but a re-extracted number can.
2. **The name filter was still a filter.** However many spellings `_FLOOR_NAME_RE` grew,
   a name outside all of them (`bulk_filter.MUST_KEEP_ROWS`) stayed invisible.
   `_CONSTANT_NAME_RE` now accepts this repository's whole module-constant convention
   (a name starting with a letter, all caps), and what actually decides scope is
   `_is_len_derived` on the *value* — never the spelling.
   `bulk_filter.MUST_KEEP_ROWS` never appears as a direct `Compare` operand either (it
   is boxed into a dict three lines below and read back out); `_resolves_to_name` finds
   it through the same Subscript/dict-literal hops `_collection_kind` already followed
   for a population, applied to the floor's own side of the comparison.
3. **`floors_swept_at_least = 30` against 46 tolerated hiding all fourteen.** Round 2's
   broadened discovery raises the true count on its own (see below); the committed floor
   is raised to sit within a few points of it, not sixteen.
4. **The gate exempted itself.** `floor_sweep.py` was skipped by module identity, so
   `MINIMUM_FLOORS_SWEPT` was the one committed floor this rule structurally could not
   classify. Round 2 does not special-case it: `_module_constant_candidates`'s
   value-shape filter already keeps every other diagnostics constant in this module off
   the candidate list without a name-based allowlist, so nothing but the real floor is
   left to sweep.
5. **The "never wrongly clears" claim was false**, the same shape as `resolve_identity`'s
   "only ever merges" — measurably false there too. `_MARGIN_ARGUED_RE`'s own comment
   now says so plainly instead of repeating the disproved claim.
6. **The roll-call inside `MINIMUM_FLOORS_SWEPT`'s own comment named modules as
   "already compliant" that the sweep could not see at all** — `gate_reader_agreement`
   is the exemplar the task file itself cites, and it was genuinely out of scope: its
   only comparison site reads a `dict` passed to `floor_breaches` as a *parameter*, and
   round 1's tracing never followed a value across a call boundary to find out what a
   parameter actually held. Round 2 adds exactly that (`_resolve_parameter_via_callers`,
   `_resolve_subscript_param_via_callers`) — one hop, and only when every call site in the
   module binds the parameter the same way — which is what pulled
   `gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED` in from `bounds_read_and_out_of_scope`
   for the first time, along with `MUST_KEEP_ROWS` and every other module whose own gate
   separates "build the measurement" from "check the floor" this same way (`interview`,
   `pay`, `profile_capture` among them — three more undocumented, silently-under floors
   this broadened tracing found and this task also raised, the same discipline as the
   original eleven). What it did *not* pull in —
   `gate_reader_agreement.MINIMUM_GATES_COMPARED` — combines a genuinely external count
   (`int(board["compared"])`, read from outside this repository) with `len(probes)`; no
   arithmetic shape this module supports may combine two dynamic quantities, so this one
   stays honestly out of scope. The roll-call itself is gone from this comment for the
   reason the finding names: a hand-maintained list of "compliant" module names is prose
   nothing tests, and it drifts. `status/evidence/T159.json`'s own
   `dynamic_population_floors` and `bounds_read_and_out_of_scope` are regenerated on
   every run and cannot say something the sweep does not currently believe.

`_population_for` also grew one more traced shape while this round was open:
`len(X) + N` / `len(X) - N` (`gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED`'s own
reasoning — "the list this is read against is `len(ARRANGEMENTS) + 1`") is now counted
arithmetically rather than falling out of scope the moment a `BinOp` sits where a bare
`len(...)` used to.

## The denominator

`floors_swept` is every floor this module classified, one way or the other. Per
T100/T122, it is committed as a **literal** floor (`MINIMUM_FLOORS_SWEPT`), not as the
count of the day: derived from the sweep's own result, it would shrink with any floor
the sweep stops finding — this task's own defect, committed inside this task's gate,
which is precisely what T122's review round flagged and what `record` below refuses to
repeat.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = Path(__file__).resolve().parent
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T159.json"

#: Round 2's fix for the reader's first finding: this repository's module-constant
#: convention (a name starting with a letter, all caps) — not a floor-specific
#: spelling. `bulk_filter.MUST_KEEP_ROWS` and `bodyless_post.PROBES_FLOOR`-shaped
#: names (neither `MINIMUM_`/`MIN_`/`_AT_LEAST`/`_MINIMUM`) are exactly what the old,
#: floor-shaped-only pattern could never see, no matter how many more spellings were
#: added to it — an enumeration of spellings has no last element. What makes a name
#: worth sweeping is what its *value* is (see `_is_len_derived` below and
#: `_module_constant_candidates`), never how it is spelled.
_CONSTANT_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

#: Phrasing this repository actually uses, in the floors already read while building
#: this module, to argue that a floor's margin below its population is deliberate
#: rather than an accident: `salary_recovery.MINIMUM_WORDING_CASES` ("Raised from 40
#: ... sits far below"), `gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED` ("one unit
#: of slack"), `gate_reader_agreement.MINIMUM_GATES_COMPARED` ("sits under today's
#: total"), `audit_followup.CASES_AT_LEAST` / `connector_policy.ADJUDICATIONS_AT_LEAST`
#: ("deliberately under"), `connector_policy.PACKAGES_AT_LEAST` ("Same reasoning"),
#: `robots.FIXTURES_AT_LEAST` / `second_reader`'s four ("Raised ... to", "raised
#: again", "kept its slack", "small on purpose"), `review_reader`'s four ("the margin
#: over the observed count is unchanged").
#:
#: **This is a keyword match, and a keyword match is not a claim of correctness —
#: round 1's own docstring said the opposite ("never one it wrongly clears") and a
#: second reader measured that false: every one of the fourteen comments this task
#: wrote reads "Raised to what the probe carries — N, zero slack", and the trigger
#: words (`raised`, `slack`) stay in the text forever, including after a later edit
#: drops the floor to something the sentence no longer describes.** Regex-matched
#: prose can certify a margin that used to be true. `_zero_slack_claim_contradicts`
#: below is what actually falsifies a stale claim rather than merely detecting the
#: presence of words that once argued a true one; this pattern still gates whether
#: an *argument* was attempted at all, which a claim carrying no number at all (the
#: older, spelled-out style — "one unit of slack", "sits under today's total") has
#: no other way to state.
_MARGIN_ARGUED_RE = re.compile(
    r"\bmargin\b|\bslack\b|\braised\b|deliberately\s+(?:under|below)|"
    r"sits\s+(?:well\s+|far\s+)?(?:under|below)|\bwell\s+below\b|\bfar\s+below\b|"
    r"same\s+reasoning|on\s+purpose",
    re.IGNORECASE,
)

#: A *specific, falsifiable* form `_MARGIN_ARGUED_RE` cannot check: this task's own
#: idiom for a zero-margin claim ("N, zero slack" / "no slack" / "zero margin").
#: Unlike "sits well below" (true of a whole family of margins, never stale merely
#: because the population moved a little), "zero slack" asserts an exact equality —
#: floor equals population — and so states a number a later edit can silently
#: falsify while leaving the sentence looking exactly as true as it did the day it
#: was written.
_ZERO_SLACK_CLAIM_RE = re.compile(
    r"\bzero\s+slack\b|\bzero\s+margin\b|\bno\s+slack\b", re.IGNORECASE
)

_DIGITS_RE = re.compile(r"\d+")

#: A minimal English cardinal vocabulary — this repository argues some floors in
#: words rather than digits (`profile.MINIMUM_FIELDS_CHECKED`'s own comment says
#: "Ten today", `gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED`'s says "It is
#: thirteen, not twelve"). A digit-only check would silently miss exactly the
#: floors round 1 named in the task table.
_ONES_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS_WORDS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


def _spelled_out_numbers(text: str) -> set[int]:
    """Every cardinal number `text` states in English words — "nine", "twenty
    five" — never composing "hundred" (no zero-slack claim in this repository
    combines one with a three-digit number, and getting that composition wrong
    would be worse than not attempting it)."""
    words = re.findall(r"[a-z]+", text.lower())
    found: set[int] = set()
    i = 0
    while i < len(words):
        word = words[i]
        if word in _TENS_WORDS:
            value = _TENS_WORDS[word]
            if i + 1 < len(words) and words[i + 1] in _ONES_WORDS:
                value += _ONES_WORDS[words[i + 1]]
                i += 1
            found.add(value)
        elif word in _ONES_WORDS:
            found.add(_ONES_WORDS[word])
        i += 1
    return found


def _normalize_comment_text(comment: str) -> str:
    """`comment` with each line's `#`/`#:` prefix stripped and every line joined by
    a single space.

    Every phrase check below runs against this, never the raw comment block: a
    comment line-wraps at this repository's own ruff width, and a phrase can land
    split across two lines with a `#: ` in between — `elicit_extract.MINIMUM_CHECKS`'s
    own comment wraps "zero" and "slack" onto separate lines, and `\\bzero\\s+slack\\b`
    over the raw text sees `"zero\\n#: slack"`, where `#:` is not whitespace and the
    match fails. Read on raw text, that gap would have hidden the exact stale-claim
    contradiction this check exists to catch — silently, on one of the fourteen
    floors this very task fixed.
    """
    words: list[str] = []
    for line in comment.splitlines():
        stripped = re.sub(r"^\s*#:?\s*", "", line.strip())
        if stripped:
            words.append(stripped)
    return " ".join(words)


def _zero_slack_claim_contradicts(comment: str, literal_value: int) -> bool:
    """True when `comment` states a "zero slack" (or "zero margin" / "no slack")
    claim beside a specific number, and that number is not the floor's own current
    value.

    This is the concrete fix for the reader's first finding: every one of this
    task's fourteen fixed floors is commented "Raised to what the probe/table
    carries — N, zero slack" — a comment written once, for the value that was true
    the day it was written. `_MARGIN_ARGUED_RE` matches the words `raised` and
    `slack` in that sentence forever, including after a later edit changes N to
    something the sentence no longer describes; this instead re-extracts the
    number the comment actually claims and compares it against what the code
    currently declares, so a floor dropped out from under a comment that still
    reads "9, zero slack" is caught even though every trigger word is still
    sitting right there. Silent (returns `False`, deferring to the keyword check
    above) when a "zero slack" phrase carries no number at all — the older,
    spelled-out style (`connector_transport.MINIMUM_RECORD_KEYS_COMPARED`'s "The
    record carries twelve keys and this is twelve — no slack") already survives
    `_spelled_out_numbers`, but a claim with literally no adjacent number is not
    one this check can falsify, so it is not one it accuses either.
    """
    normalized = _normalize_comment_text(comment)
    for match in _ZERO_SLACK_CLAIM_RE.finditer(normalized):
        window = normalized[max(0, match.start() - 40) : match.end() + 10]
        claimed = {int(digits) for digits in _DIGITS_RE.findall(window)}
        claimed |= _spelled_out_numbers(window)
        if claimed and literal_value not in claimed:
            return True
    return False


#: String-returning method calls this module treats as producing a scalar (the length
#: of *one* piece of text), never a population. Seen guarding `elicit_extract.MIN_ANSWER_CHARS`
#: (`answer.strip()`) among others.
_SCALAR_STRING_METHODS = frozenset(
    {
        "strip",
        "lower",
        "upper",
        "casefold",
        "title",
        "capitalize",
        "format",
        "strftime",
        "get",
        "join",
    }
)

#: Functions that wrap an iterable without changing how many items are in it — seen
#: wrapping a comprehension before it is measured (`sorted(item.name for item in probes)`
#: in `gate_reader_agreement`).
_COUNT_PRESERVING_WRAPPERS = frozenset({"sorted", "list", "tuple", "set", "frozenset"})


@dataclass(frozen=True)
class FloorFinding:
    """One floor that does not refuse the first deletion of its population."""

    module: str
    name: str
    lineno: int
    reason: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "name": self.name,
            "line": self.lineno,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class DynamicFloor:
    """An in-scope floor whose population this repository does not itself enumerate."""

    module: str
    name: str
    lineno: int

    def as_dict(self) -> dict[str, Any]:
        return {"module": self.module, "name": self.name, "line": self.lineno}


@dataclass
class _ModuleInfo:
    stem: str
    path: Path
    source: str
    lines: list[str] = field(default_factory=list)
    tree: ast.Module = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.lines = self.source.splitlines()


def _module_infos(src_dir: Path) -> list[_ModuleInfo]:
    infos = []
    for path in sorted(src_dir.glob("*.py")):
        if path.stem == "__init__":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        infos.append(_ModuleInfo(stem=path.stem, path=path, source=source, tree=tree))
    return infos


def _literal_int(expr: ast.expr) -> int | None:
    if (
        isinstance(expr, ast.Constant)
        and isinstance(expr.value, int)
        and not isinstance(expr.value, bool)
    ):
        return expr.value
    return None


def _is_len_derived(expr: ast.expr, depth: int = 0) -> bool:
    """True when `expr`'s own top-level shape is a `len(...)` call, or simple
    `+`/`-` arithmetic combining one with a plain integer literal
    (`len(ARRANGEMENTS) + 1`) — the shape a *self-referential* floor takes.

    This is never true for a bare collection literal, even though `PROBES = (1, 2,
    3)` is exactly as capitalised as a floor: the population is not a count of
    itself, and round 2's broadened, spelling-independent candidate discovery
    (`_module_constant_candidates`) would otherwise sweep every fixed-collection
    constant in the repository as a "floor" whose value is not even an integer.
    """
    if depth > 3:
        return False
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "len":
        return True
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.Add, ast.Sub)):
        left_is_len = _is_len_derived(expr.left, depth + 1)
        right_is_len = _is_len_derived(expr.right, depth + 1)
        left_is_literal = _literal_int(expr.left) is not None
        right_is_literal = _literal_int(expr.right) is not None
        return (left_is_len and right_is_literal) or (right_is_len and left_is_literal)
    return False


def _module_constant_candidates(tree: ast.Module) -> list[tuple[str, int, ast.expr]]:
    """Every module-level `NAME = <expr>` (or annotated) naming a module constant by
    this repository's own convention — a name starting with a letter, all caps —
    whose *value* is either a plain integer literal or itself a `len(...)`-derived
    expression (`_is_len_derived`).

    Round 1 gated this step on the floor's own name (`MINIMUM_`/`MIN_`/`_AT_LEAST`/
    `_MINIMUM`), which is exactly what let `bulk_filter.MUST_KEEP_ROWS` and a
    hypothetical `PROBES_FLOOR` go unswept: the name filter is still a filter,
    however many spellings it lists. Scoping by *value shape* instead is what makes
    the broadened name pattern safe: `PROBES = (1, 2, 3)` is just as capitalised as
    `MUST_KEEP_ROWS = 3`, but its value is the collection itself, not a count, so
    `_is_len_derived` (false for a bare literal) keeps it off this list — the
    module never has to special-case a name it does not recognise as a table.
    """
    found: list[tuple[str, int, ast.expr]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if not (isinstance(target, ast.Name) and _CONSTANT_NAME_RE.match(target.id)):
                continue
            if _literal_int(value) is not None or _is_len_derived(value):
                found.append((target.id, node.lineno, value))
    return found


#: A bare `NAME = value` (optionally annotated) line — used only to recognise a
#: sibling floor declared right above this one, so `interview.MINIMUM_TRAIT_EPISODES`
#: / `MINIMUM_TRAIT_OCCASIONS` (one shared comment above the first of the pair) reads
#: that comment for the second floor too, rather than reporting it undocumented for a
#: formatting reason that has nothing to do with whether it is argued.
_SIBLING_ASSIGNMENT_RE = re.compile(r"^[A-Z][A-Z0-9_]*\s*(?::[^=]+)?=\s*.+$")


def _comment_block_above(lines: list[str], lineno: int) -> str:
    """The contiguous `#`-prefixed lines above a 1-indexed declaration line.

    Skips back over any immediately-preceding bare constant declarations first, so a
    comment written once for a group of floors is read for each of them. Also tolerates
    a single blank line between the code and the comment — a section-header block
    followed by a blank line before the constant it introduces
    (`reader_notes.MINIMUM_PROBES`) is a real explanation, not a missing one.
    """
    i = lineno - 2  # zero-indexed line just above the declaration
    while (
        i >= 0
        and not lines[i].strip().startswith("#")
        and _SIBLING_ASSIGNMENT_RE.match(lines[i].strip())
    ):
        i -= 1
    if i >= 0 and lines[i].strip() == "" and i - 1 >= 0 and lines[i - 1].strip().startswith("#"):
        i -= 1
    collected: list[str] = []
    while i >= 0 and lines[i].strip().startswith("#"):
        collected.append(lines[i])
        i -= 1
    collected.reverse()
    return "\n".join(collected)


def _all_function_defs(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _innermost_enclosing(
    node: ast.AST, functions: list[ast.FunctionDef | ast.AsyncFunctionDef]
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The most tightly-nested function in `functions` whose body spans `node`."""
    best: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for fn in functions:
        if (
            hasattr(fn, "lineno")
            and hasattr(node, "lineno")
            and fn.lineno <= node.lineno <= (getattr(fn, "end_lineno", None) or 10**9)
            and (best is None or fn.lineno > best.lineno)
        ):
            best = fn
    return best


def _module_level_value(tree: ast.Module, name: str) -> ast.expr | None:
    """Whatever a module-level `NAME = <expr>` (or annotated) assigns, unfiltered."""
    for node in tree.body:
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                return value
    return None


def _module_level_literal_collection(tree: ast.Module, name: str) -> ast.expr | None:
    value = _module_level_value(tree, name)
    if isinstance(value, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return value
    return None


def _param_default(
    func: ast.FunctionDef | ast.AsyncFunctionDef, param_name: str
) -> ast.expr | None:
    args = func.args
    positional = list(args.posonlyargs) + list(args.args)
    defaults = list(args.defaults)
    # Standard Python alignment: defaults line up with the *trailing* positional args.
    offset = len(positional) - len(defaults)
    for index, arg in enumerate(positional):
        if arg.arg == param_name and index >= offset:
            return defaults[index - offset]
    for kwarg, kwdefault in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        if kwarg.arg == param_name and kwdefault is not None:
            return kwdefault
    return None


def _subscript_string_key(node: ast.Subscript) -> tuple[str, str] | None:
    """`obj["key"]` → `(obj_name, "key")`, when `obj` is a bare name and the key a string."""
    if not isinstance(node.value, ast.Name):
        return None
    key_node = node.slice
    if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
        return (node.value.id, key_node.value)
    return None


def _assignments_to_name(
    func: ast.FunctionDef | ast.AsyncFunctionDef, name: str, before_lineno: int | None
) -> list[ast.expr]:
    found: list[tuple[int, ast.expr]] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                found.append((node.lineno, node.value))
    if before_lineno is not None:
        found = [pair for pair in found if pair[0] < before_lineno] or found
    found.sort(key=lambda pair: pair[0])
    return [value for _, value in found]


def _assignments_to_subscript(
    func: ast.FunctionDef | ast.AsyncFunctionDef, key: tuple[str, str], before_lineno: int | None
) -> list[ast.expr]:
    found: list[tuple[int, ast.expr]] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Subscript):
                found_key = _subscript_string_key(target)
                if found_key == key:
                    found.append((node.lineno, node.value))
    if before_lineno is not None:
        found = [pair for pair in found if pair[0] < before_lineno] or found
    found.sort(key=lambda pair: pair[0])
    return [value for _, value in found]


def _appended_in_a_loop(func: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    """True if `name.append(...)` / `.add(...)` / `.update(...)` appears anywhere in `func`."""
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"append", "add", "update", "extend"}
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == name
        ):
            return True
    return False


def _incremented_in_a_loop(func: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    """True if `name += ...` appears anywhere in `func` — the running-count shape
    `naming.measure`'s `scanned` and `review_reader.measure`'s `reports_found` both
    use instead of a comprehension."""
    for node in ast.walk(func):
        if (
            isinstance(node, ast.AugAssign)
            and isinstance(node.op, ast.Add)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            return True
    return False


_UNKNOWN = "unknown"
_SCALAR = "scalar"
_LITERAL = "literal"
_DYNAMIC = "dynamic"


def _resolve_parameter_via_callers(
    func: ast.FunctionDef | ast.AsyncFunctionDef, param_name: str, tree: ast.Module, depth: int
) -> tuple[str, int | None]:
    """`func`'s own `param_name` is never assigned inside `func` — a parameter with
    no default is bound by whoever *calls* `func`, not by `func` itself.

    This is the shape most of this repository's own "breach" functions take:
    `gate_reader_agreement.floor_breaches(measured)` reads
    `measured["arrangements_probed"]`, but `measured` only ever means anything at
    the three call sites that pass it, each `measured = measure(...)` a few lines
    above. Finds every call to `func` by name anywhere in the module, resolves
    what each one binds to `param_name` in *that caller's own* scope, and accepts
    the answer only when every call site agrees — a function this sweep cannot
    show has one consistent meaning for a parameter is not one it may guess at
    from the first call site it happens to find.
    """
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == func.name
    ]
    if not calls:
        return _UNKNOWN, None
    all_functions = _all_function_defs(tree)
    results: list[tuple[str, int | None]] = []
    for call in calls:
        mapping = _bind_call_arguments(call, func)
        arg_expr = mapping.get(param_name)
        if arg_expr is None:
            return _UNKNOWN, None
        caller_func = _innermost_enclosing(call, all_functions)
        results.append(_collection_kind(arg_expr, tree, caller_func, call.lineno, depth + 1))
    first = results[0]
    if first[0] in (_LITERAL, _DYNAMIC) and all(result == first for result in results):
        return first
    return _UNKNOWN, None


def _dict_value_for_key(dict_literal: ast.Dict, key_string: str) -> ast.expr | None:
    for key_node, value_node in zip(dict_literal.keys, dict_literal.values, strict=True):
        if (
            isinstance(key_node, ast.Constant)
            and key_node.value == key_string
            and value_node is not None
        ):
            return value_node
    return None


def _resolve_subscript_param_via_callers(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    param_name: str,
    key_string: str,
    tree: ast.Module,
    depth: int,
) -> tuple[str, int | None]:
    """What `param_name[key_string]` denotes, when `param_name` is one of
    `func`'s own parameters bound by whoever calls it
    (`floor_breaches(measured)` reading `measured["arrangements_probed"]`).

    Resolved separately, in *each* caller's own scope, all the way down to a
    classified `(kind, count)` — never by comparing the dict literals or the raw
    argument expressions themselves, both of which can look identical across two
    callers that mean different things (`measure(probes=PROBES)` and
    `measure_other(probes=OTHER_PROBES)` both return `{"probes_evaluated":
    len(probes)}` — the same dict shape, a different population once `probes` is
    read in each function's own scope). Only full agreement on the *final*
    classification counts.
    """
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == func.name
    ]
    if not calls:
        return _UNKNOWN, None
    all_functions = _all_function_defs(tree)
    results: list[tuple[str, int | None]] = []
    for call in calls:
        mapping = _bind_call_arguments(call, func)
        arg_expr = mapping.get(param_name)
        if arg_expr is None:
            return _UNKNOWN, None
        caller_func = _innermost_enclosing(call, all_functions)
        dict_literal, dict_func = _resolve_to_dict_literal(arg_expr, tree, caller_func)
        if dict_literal is None:
            return _UNKNOWN, None
        value_node = _dict_value_for_key(dict_literal, key_string)
        if value_node is None:
            return _UNKNOWN, None
        results.append(_collection_kind(value_node, tree, dict_func, None, depth + 1))
    first = results[0]
    if first[0] in (_LITERAL, _DYNAMIC) and all(result == first for result in results):
        return first
    return _UNKNOWN, None


def _collection_kind(
    expr: ast.expr,
    tree: ast.Module,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    before_lineno: int | None,
    depth: int = 0,
) -> tuple[str, int | None]:
    """Classify what `expr` denotes: a counted literal, a dynamically-built collection,
    a scalar (one piece of text), or unknown. Follows at most a few hops of local
    reassignment so this stays a sweep, not a full dataflow analysis."""
    if depth > 5:
        return _UNKNOWN, None

    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        return _LITERAL, len(expr.elts)
    if isinstance(expr, ast.Dict):
        return _LITERAL, len(expr.keys)
    if isinstance(expr, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return _DYNAMIC, None

    if isinstance(expr, ast.IfExp):
        # `X = DEFAULT if param is None else param` — the module's own fixture unless
        # a caller overrides it. Seen in `review_reader.measure`
        # (`states = CONTROLS if controls is None else controls`). The overriding
        # branch is never staticaly known, so this is a *dynamic* population even
        # when the default branch alone would count as a literal — the sweep must
        # not claim an exact count a caller can change.
        body_kind, _ = _collection_kind(expr.body, tree, func, before_lineno, depth + 1)
        else_kind, _ = _collection_kind(expr.orelse, tree, func, before_lineno, depth + 1)
        if body_kind in (_LITERAL, _DYNAMIC) or else_kind in (_LITERAL, _DYNAMIC):
            return _DYNAMIC, None
        return _UNKNOWN, None

    if isinstance(expr, ast.Call):
        if isinstance(expr.func, ast.Name) and expr.func.id == "len" and len(expr.args) == 1:
            inner_kind, inner_count = _collection_kind(
                expr.args[0], tree, func, before_lineno, depth + 1
            )
            if inner_kind == _LITERAL:
                return _LITERAL, inner_count
            if inner_kind == _DYNAMIC:
                return _DYNAMIC, None
            return _UNKNOWN, None
        if (
            isinstance(expr.func, ast.Name)
            and expr.func.id in _COUNT_PRESERVING_WRAPPERS
            and expr.args
        ):
            inner_kind, inner_count = _collection_kind(
                expr.args[0], tree, func, before_lineno, depth + 1
            )
            if inner_kind in (_LITERAL, _DYNAMIC):
                return (_LITERAL, inner_count) if inner_kind == _LITERAL else (_DYNAMIC, None)
            return _UNKNOWN, None
        if isinstance(expr.func, ast.Attribute) and expr.func.attr in _SCALAR_STRING_METHODS:
            return _SCALAR, None
        if (
            isinstance(expr.func, ast.Name)
            and expr.func.id in {"set", "list", "dict", "frozenset"}
            and not expr.args
        ):
            return _LITERAL, 0
        if isinstance(expr.func, ast.Name):
            # A call to a same-module function — seen building the fixed control set a
            # delegated floor is checked against (`review_reader.CONTROLS =
            # _control_prs()`) and, with arguments, the ubiquitous `measured =
            # measure(...)` shape a `_main`/`write_evidence` reads its own gate from.
            # One hop into the callee's own `return` is enough to reach what it
            # builds; this never evaluates the call, so what the *arguments* are does
            # not matter, only what the callee's body always returns.
            callee = _top_level_function(tree, expr.func.id)
            if callee is not None:
                returns = _function_returns(callee)
                chosen = _unambiguous_return(returns)
                if chosen is not None:
                    return _collection_kind(chosen, tree, callee, None, depth + 1)
                if len(returns) > 1:
                    return _DYNAMIC, None
        return _UNKNOWN, None

    if isinstance(expr, ast.Name):
        module_literal = _module_level_literal_collection(tree, expr.id)
        if module_literal is not None:
            return _collection_kind(module_literal, tree, func, before_lineno, depth + 1)
        module_value = _module_level_value(tree, expr.id)
        if module_value is not None:
            # Not a literal collection directly (handled above), but a module-level
            # name all the same — e.g. `CONTROLS = _control_prs()`. Recurse into
            # whatever it holds rather than stopping at "not a literal".
            return _collection_kind(module_value, tree, None, None, depth + 1)
        if func is not None:
            default = _param_default(func, expr.id)
            if default is not None:
                return _collection_kind(default, tree, func, before_lineno, depth + 1)
            assignments = _assignments_to_name(func, expr.id, before_lineno)
            if assignments:
                rhs = assignments[-1]
                if (
                    isinstance(rhs, (ast.List, ast.Set))
                    and not rhs.elts
                    and _appended_in_a_loop(func, expr.id)
                ):
                    return _DYNAMIC, None
                if (
                    isinstance(rhs, ast.Constant)
                    and isinstance(rhs.value, int)
                    and not isinstance(rhs.value, bool)
                    and _incremented_in_a_loop(func, expr.id)
                ):
                    return _DYNAMIC, None
                return _collection_kind(rhs, tree, func, before_lineno, depth + 1)
            param_names = (
                {a.arg for a in func.args.posonlyargs}
                | {a.arg for a in func.args.args}
                | {a.arg for a in func.args.kwonlyargs}
            )
            if expr.id in param_names:
                return _resolve_parameter_via_callers(func, expr.id, tree, depth)
        return _UNKNOWN, None

    if isinstance(expr, ast.Subscript):
        key = _subscript_string_key(expr)
        if key is not None:
            base_name, key_string = key

            # Shape one: `obj["key"] = <expr>` somewhere earlier in the same function
            # (`committed["arrangements_probed"] = ...`).
            if func is not None:
                assignments = _assignments_to_subscript(func, key, before_lineno)
                if assignments:
                    return _collection_kind(assignments[-1], tree, func, before_lineno, depth + 1)

            # Shape two, far more common in this repository: `obj = {"key": <expr>,
            # ...}` — a dict literal, either assigned directly in this function, held
            # at module level, or built by a same-module function's `return` (the
            # `measured = measure(...)` a `_main`/`write_evidence` reads its own gate
            # from). Resolve `obj` however a bare Name would be, then read the key out
            # of whatever dict literal that resolves to, in *that* dict's own scope.
            obj_value: ast.expr | None = None
            if func is not None:
                name_assignments = _assignments_to_name(func, base_name, before_lineno)
                if name_assignments:
                    obj_value = name_assignments[-1]
            if obj_value is None:
                obj_value = _module_level_value(tree, base_name)
            if obj_value is not None:
                dict_literal, dict_func = _resolve_to_dict_literal(obj_value, tree, func)
                if dict_literal is not None:
                    value_node = _dict_value_for_key(dict_literal, key_string)
                    if value_node is not None:
                        return _collection_kind(value_node, tree, dict_func, None, depth + 1)
                return _UNKNOWN, None
            if func is not None and base_name in (
                {a.arg for a in func.args.posonlyargs}
                | {a.arg for a in func.args.args}
                | {a.arg for a in func.args.kwonlyargs}
            ):
                # `base_name` is never assigned inside `func` at all — it is one of
                # `func`'s own parameters, bound by whoever calls it
                # (`floor_breaches(measured)`'s shape). Resolved separately, in
                # *each* caller's own scope, by `_resolve_subscript_param_via_callers`.
                return _resolve_subscript_param_via_callers(
                    func, base_name, key_string, tree, depth
                )
        return _UNKNOWN, None

    return _UNKNOWN, None


def _top_level_function(
    tree: ast.Module, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    return next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ),
        None,
    )


def _function_returns(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
    return [n.value for n in ast.walk(func) if isinstance(n, ast.Return) and n.value is not None]


def _unambiguous_return(returns: list[ast.expr]) -> ast.expr | None:
    """The one return value worth following out of several.

    This repository's own gate modules commonly write `measure()` as one or more
    early bail-outs (`return _unmeasured(...)`) guarding a single substantive
    branch that builds the real result — `gate_reader_agreement.measure` returns
    four different things, three of them `_unmeasured(...)` calls for "no verifier
    at ...", "no task tree at ...", and so on. A single literal `Dict` among
    several returns is that substantive branch; two, or zero, is genuinely
    ambiguous, and this declines to guess between them.
    """
    if len(returns) == 1:
        return returns[0]
    dict_returns = [r for r in returns if isinstance(r, ast.Dict)]
    if len(dict_returns) == 1:
        return dict_returns[0]
    return None


def _resolve_to_dict_literal(
    value: ast.expr | None,
    tree: ast.Module,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    depth: int = 0,
) -> tuple[ast.Dict | None, ast.FunctionDef | ast.AsyncFunctionDef | None]:
    """`value` (an already-found local assignment, or `None` to fall through to a
    module-level lookup) resolved down to the `Dict` literal it ultimately holds, and
    the function whose scope that literal's *values* should be read in — the callee's,
    when `value` was a call, since a dict a function builds names its own locals."""
    if value is None or depth > 5:
        return None, None
    if isinstance(value, ast.Dict):
        return value, func
    if isinstance(value, ast.Name):
        # `return measured` where `measured = probe_constraint_survival(...)` a few
        # lines up — the callee only names its result rather than returning the call
        # (or the dict literal) directly. One more hop, in the *same* function's own
        # scope, before falling back to a module-level name.
        local = _assignments_to_name(func, value.id, None) if func is not None else []
        if local:
            return _resolve_to_dict_literal(local[-1], tree, func, depth + 1)
        return _resolve_to_dict_literal(_module_level_value(tree, value.id), tree, None, depth + 1)
    if isinstance(value, ast.IfExp):
        # `measured = measure(...) if target is None else write_evidence(...)` — try
        # the branches in order and take whichever resolves; this is reading the
        # *shape* of what gets returned, not evaluating which branch runs.
        for branch in (value.body, value.orelse):
            resolved, resolved_func = _resolve_to_dict_literal(branch, tree, func, depth + 1)
            if resolved is not None:
                return resolved, resolved_func
        return None, None
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        callee = _top_level_function(tree, value.func.id)
        if callee is not None:
            returns = _function_returns(callee)
            chosen = _unambiguous_return(returns)
            if chosen is not None:
                # The callee might itself only delegate (`write_evidence` calling
                # `measure` and returning what it got) — recurse one more hop rather
                # than requiring the dict literal to be textually present here.
                return _resolve_to_dict_literal(chosen, tree, callee, depth + 1)
    return None, None


def _resolves_to_name(
    expr: ast.expr,
    target_name: str,
    tree: ast.Module,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    before_lineno: int | None,
    depth: int = 0,
) -> bool:
    """True when `expr`, traced through the same Name/Subscript/dict-literal hops
    `_collection_kind` already follows for a *population*, ultimately names the
    floor `target_name` itself.

    This is the mirror image of that tracing, needed because a floor is not always
    a bare `Compare` operand: `bulk_filter.MUST_KEEP_ROWS`'s only enforcement site
    is `measured["must_keep_rows_evaluated"] < measured["must_keep_rows_at_least"]`
    — the floor's own name appears nowhere in that `Compare`, only three lines
    above it, boxed into the dict `measured["must_keep_rows_at_least"]` reads back
    out. A sweep that only recognised `Name(id=floor)` directly on one side of a
    `Compare` could never find it, no matter how the name were spelled.
    """
    if depth > 5:
        return False
    if isinstance(expr, ast.Name):
        if expr.id == target_name:
            return True
        if func is not None:
            assignments = _assignments_to_name(func, expr.id, before_lineno)
            if assignments:
                return _resolves_to_name(
                    assignments[-1], target_name, tree, func, before_lineno, depth + 1
                )
        module_value = _module_level_value(tree, expr.id)
        if module_value is not None:
            return _resolves_to_name(module_value, target_name, tree, None, None, depth + 1)
        return False
    if isinstance(expr, ast.Subscript):
        key = _subscript_string_key(expr)
        if key is None:
            return False
        base_name, key_string = key
        obj_value: ast.expr | None = None
        if func is not None:
            name_assignments = _assignments_to_name(func, base_name, before_lineno)
            if name_assignments:
                obj_value = name_assignments[-1]
        if obj_value is None:
            obj_value = _module_level_value(tree, base_name)
        dict_literal, dict_func = _resolve_to_dict_literal(obj_value, tree, func)
        if dict_literal is not None:
            for key_node, value_node in zip(dict_literal.keys, dict_literal.values, strict=True):
                if (
                    isinstance(key_node, ast.Constant)
                    and key_node.value == key_string
                    and value_node is not None
                ):
                    return _resolves_to_name(
                        value_node, target_name, tree, dict_func, None, depth + 1
                    )
        return False
    return False


def _population_for(
    other_operand: ast.expr,
    tree: ast.Module,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    before_lineno: int | None,
) -> tuple[bool, int | None]:
    """`(in_scope, population)`. `in_scope` is True only if `other_operand` traces to a
    `len(...)` call, or simple `+`/`-` arithmetic on one; `population` is the concrete
    count when that reduces to a literal collection this module can count, else `None`
    for a dynamic one."""
    if (
        isinstance(other_operand, ast.Call)
        and isinstance(other_operand.func, ast.Name)
        and other_operand.func.id == "len"
        and len(other_operand.args) == 1
    ):
        kind, count = _collection_kind(other_operand.args[0], tree, func, before_lineno)
        if kind == _LITERAL:
            return True, count
        if kind == _DYNAMIC:
            return True, None
        return False, None

    if isinstance(other_operand, ast.BinOp) and isinstance(other_operand.op, (ast.Add, ast.Sub)):
        # `len(X) + N` / `len(X) - N` / `N + len(X)` —
        # `gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED`'s own reasoning:
        # "`measure` probes `ARRANGEMENTS` *and* `UNGATED_ARRANGEMENT`, so the list
        # this is read against is `len(ARRANGEMENTS) + 1`". Traced by recursing into
        # whichever side is itself `len(...)`-derived and requiring the other side
        # to be a plain int literal — never two collections combined, which this
        # sweep has no business counting, and never accepted merely because a
        # `BinOp` sits where a bare `len(...)` used to.
        left, right = other_operand.left, other_operand.right
        left_offset = _literal_int(left)
        right_offset = _literal_int(right)
        sign = -1 if isinstance(other_operand.op, ast.Sub) else 1
        if right_offset is not None and left_offset is None:
            in_scope, population = _population_for(left, tree, func, before_lineno)
            if in_scope:
                return True, (None if population is None else population + sign * right_offset)
            return False, None
        if (
            left_offset is not None
            and right_offset is None
            and isinstance(other_operand.op, ast.Add)
        ):
            in_scope, population = _population_for(right, tree, func, before_lineno)
            if in_scope:
                return True, (None if population is None else population + left_offset)
            return False, None
        return False, None

    # Not itself a `len(...)` call — trace it (bare name or subscript) and see whether
    # it *becomes* one within a couple of hops.
    kind, count = _collection_kind(other_operand, tree, func, before_lineno)
    # `_collection_kind` on a bare Name/Subscript recurses through `len(...)` internally
    # via the Call branch above, so a result of literal/dynamic here already means the
    # traced value passed through a `len(...)` at some point *if and only if* the
    # traversal actually hit that branch. To keep the "must reach len()" rule honest
    # for the direct (non-len-wrapped) case, require the traced chain to have gone
    # through a Subscript/Name — i.e. never accept a bare literal collection compared
    # directly with no `len()` anywhere, which would be comparing a floor to a
    # container rather than to a count.
    if isinstance(other_operand, (ast.Name, ast.Subscript)):
        if kind == _LITERAL:
            return True, count
        if kind == _DYNAMIC:
            return True, None
    return False, None


def _compare_sites(
    tree: ast.Module, name: str
) -> list[tuple[ast.expr, ast.FunctionDef | ast.AsyncFunctionDef | None, int]]:
    """Every `Compare` in the module with exactly one operator where `name` is one
    side — directly, or (round 2) boxed into a dict a few lines above and read back
    out through a subscript (`_resolves_to_name`). Returns `(other_side,
    enclosing_function_or_None, lineno)` for each."""
    sites: list[tuple[ast.expr, ast.FunctionDef | ast.AsyncFunctionDef | None, int]] = []
    functions = _all_function_defs(tree)

    def enclosing(node: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        return _innermost_enclosing(node, functions)

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = node.left, node.comparators[0]
            func = enclosing(node)
            if _resolves_to_name(left, name, tree, func, node.lineno):
                sites.append((right, func, node.lineno))
            elif _resolves_to_name(right, name, tree, func, node.lineno):
                sites.append((left, func, node.lineno))
    return sites


def _bind_call_arguments(
    call: ast.Call, func: ast.FunctionDef | ast.AsyncFunctionDef
) -> dict[str, ast.expr]:
    positional = list(func.args.posonlyargs) + list(func.args.args)
    mapping: dict[str, ast.expr] = {}
    for index, arg_expr in enumerate(call.args):
        if index < len(positional):
            mapping[positional[index].arg] = arg_expr
    for kw in call.keywords:
        if kw.arg is not None:
            mapping[kw.arg] = kw.value
    return mapping


def _direct_compare_in_callee(
    callee: ast.FunctionDef | ast.AsyncFunctionDef, floor_param: str, mapping: dict[str, ast.expr]
) -> ast.expr | None:
    """Inside `callee`'s own body, a `Compare` between its `floor_param` and another
    of its own parameters — mapped back to whatever expression *this* call site
    passed for that other parameter."""
    for inner in ast.walk(callee):
        if isinstance(inner, ast.Compare) and len(inner.ops) == 1:
            left, right = inner.left, inner.comparators[0]
            other_param_name: str | None = None
            if (
                isinstance(left, ast.Name)
                and left.id == floor_param
                and isinstance(right, ast.Name)
            ):
                other_param_name = right.id
            elif (
                isinstance(right, ast.Name)
                and right.id == floor_param
                and isinstance(left, ast.Name)
            ):
                other_param_name = left.id
            if other_param_name is not None and other_param_name in mapping:
                return mapping[other_param_name]
    return None


def _calls_passing(
    root: ast.AST,
    current_name: str,
    top_level_functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> list[tuple[ast.Call, ast.FunctionDef | ast.AsyncFunctionDef, dict[str, ast.expr], str]]:
    """Every call anywhere under `root` to a same-module top-level function that
    passes `current_name`, unchanged, as one argument — `(call, callee, argument
    mapping, the callee's parameter name that argument binds to)` for each."""
    found: list[
        tuple[ast.Call, ast.FunctionDef | ast.AsyncFunctionDef, dict[str, ast.expr], str]
    ] = []
    for node in ast.walk(root):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        callee = top_level_functions.get(node.func.id)
        if callee is None:
            continue
        mapping = _bind_call_arguments(node, callee)
        floor_param = next(
            (
                param
                for param, expr in mapping.items()
                if isinstance(expr, ast.Name) and expr.id == current_name
            ),
            None,
        )
        if floor_param is not None:
            found.append((node, callee, mapping, floor_param))
    return found


def _delegated_other_operand(
    tree: ast.Module, name: str
) -> tuple[ast.expr, ast.FunctionDef | ast.AsyncFunctionDef | None, int] | None:
    """The third named blind spot: a floor passed as an argument to a same-module
    helper that does the comparison inside its own body — or, round 2, passed on
    unchanged to a *second* same-module helper that does. `review_reader._floor`
    is the one-hop shape every delegated floor in this repository actually uses
    today; a hypothetical `outer(floor)` calling `inner(floor)` which does the
    actual `Compare` is the two-hop shape the reader named as silently dropped, so
    this follows one call of indirection past the first before giving up — never
    a general recursive walk, which would stop being a sweep."""
    top_level_functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    all_functions = _all_function_defs(tree)

    def enclosing(node: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        return _innermost_enclosing(node, all_functions)

    for node, callee, mapping, floor_param in _calls_passing(tree, name, top_level_functions):
        direct = _direct_compare_in_callee(callee, floor_param, mapping)
        if direct is not None:
            return direct, enclosing(node), node.lineno

        # No comparison in `callee` itself — does `callee` pass `floor_param` on,
        # unchanged, to a second same-module function that does the comparison?
        for _inner_node, inner_callee, inner_mapping, inner_floor_param in _calls_passing(
            callee, floor_param, top_level_functions
        ):
            if inner_callee is callee:
                continue
            inner_other = _direct_compare_in_callee(inner_callee, inner_floor_param, inner_mapping)
            if inner_other is None:
                continue
            # `inner_other` is an expression in `callee`'s own parameter names (it
            # came from `inner_mapping`, built from a call *inside* `callee`); if it
            # names one of them, substitute the *outer* call's own argument for it
            # so the result is an expression in the original caller's scope.
            if isinstance(inner_other, ast.Name) and inner_other.id in mapping:
                inner_other = mapping[inner_other.id]
            return inner_other, enclosing(node), node.lineno
    return None


def _classify_floor(
    module: _ModuleInfo, name: str, lineno: int, value_expr: ast.expr
) -> tuple[FloorFinding | None, DynamicFloor | None, bool]:
    """Returns `(finding_if_any, dynamic_record_if_any, was_in_scope)`."""
    literal_value = _literal_int(value_expr)

    if literal_value is None:
        # Rule (a): not even a literal. Always in scope, always a violation — a bound
        # derived from the population it bounds moves with it and can never fire.
        return (
            FloorFinding(
                module=module.stem,
                name=name,
                lineno=lineno,
                reason="derived_from_its_own_population",
                detail=(
                    f"{name} is declared as {ast.dump(value_expr, annotate_fields=False)!r}, "
                    "not a literal — if its comparison site measures the same collection, "
                    "the check is `len(X) < len(X)` and can never fire"
                ),
            ),
            None,
            True,
        )

    site = _compare_sites(module.tree, name)
    other: ast.expr | None = None
    func: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    site_lineno = lineno
    if site:
        other, func, site_lineno = site[0]
    else:
        delegated = _delegated_other_operand(module.tree, name)
        if delegated is not None:
            other, func, site_lineno = delegated

    if other is None:
        return None, None, False

    in_scope, population = _population_for(other, module.tree, func, site_lineno)
    if not in_scope:
        return None, None, False

    comment = _comment_block_above(module.lines, lineno)

    if population is None:
        # Dynamic population: no single "first deletion" this repository could make.
        # Round 1 required only that the floor's value be explained *at all* — the
        # reader's finding: any nonempty comment cleared it, forever, even after a
        # later edit made the comment's own numbers false. Round 2 still cannot
        # compute a margin for a population nothing here enumerates, but it can
        # still catch the one falsifiable claim this repository's own idiom makes
        # about one ("N, zero slack") going stale.
        if not comment.strip():
            return (
                FloorFinding(
                    module=module.stem,
                    name=name,
                    lineno=lineno,
                    reason="undocumented",
                    detail=f"{name} guards a population this repository does not itself "
                    "enumerate, and carries no comment explaining the chosen value",
                ),
                None,
                True,
            )
        if _zero_slack_claim_contradicts(comment, literal_value):
            return (
                FloorFinding(
                    module=module.stem,
                    name=name,
                    lineno=lineno,
                    reason="stale_margin_claim",
                    detail=(
                        f"{name} is {literal_value}, but its comment claims 'zero slack' "
                        "against a different number — the value the comment argued for "
                        "and the value the code now declares have drifted apart"
                    ),
                ),
                None,
                True,
            )
        return None, DynamicFloor(module=module.stem, name=name, lineno=lineno), True

    margin = population - literal_value
    if margin <= 0:
        return None, None, True

    # Past this point margin is strictly positive, so a comment claiming "zero
    # slack" is already false regardless of what number sits beside it — the
    # margin computed a moment ago already refutes it. `_zero_slack_claim_contradicts`'s
    # number-matching is for the *dynamic* branch below, where no margin can be
    # computed at all and a stale number is the only thing left to check; here the
    # arithmetic already settles it.
    if _ZERO_SLACK_CLAIM_RE.search(_normalize_comment_text(comment)):
        return (
            FloorFinding(
                module=module.stem,
                name=name,
                lineno=lineno,
                reason="stale_margin_claim",
                detail=(
                    f"{name} is {literal_value}, population is {population} (margin {margin}), "
                    "but its comment claims 'zero slack' — the keyword match alone "
                    "(`raised`, `slack`) would still clear this"
                ),
            ),
            None,
            True,
        )

    if _MARGIN_ARGUED_RE.search(_normalize_comment_text(comment)):
        return None, None, True

    return (
        FloorFinding(
            module=module.stem,
            name=name,
            lineno=lineno,
            reason="silent_margin",
            detail=(
                f"{name} is {literal_value}, population is {population} "
                f"(margin {margin}) — the first {margin} deletion(s) breach nothing, "
                "and no comment above the declaration argues the gap"
            ),
        ),
        None,
        True,
    )


def measure(src_dir: Path = _SRC_DIR) -> dict[str, Any]:
    """T159's gate: floors that do not refuse the first deletion of their population."""
    findings: list[FloorFinding] = []
    dynamic: list[DynamicFloor] = []
    swept = 0
    excluded: list[str] = []

    for module in _module_infos(src_dir):
        # Round 1 excluded this module from its own sweep by identity — the reader's
        # fourth finding: "the gate exempts itself", the one committed floor this
        # rule structurally could not classify. Round 2 does not special-case it: its
        # only int-shaped, all-caps candidate is `MINIMUM_FLOORS_SWEPT` itself, and
        # `_module_constant_candidates`'s value-shape filter (not name-based) already
        # keeps every other diagnostics constant here off the list without help.
        for name, lineno, value_expr in _module_constant_candidates(module.tree):
            finding, dynamic_record, in_scope = _classify_floor(module, name, lineno, value_expr)
            if not in_scope:
                excluded.append(f"{module.stem}.{name}")
                continue
            swept += 1
            if finding is not None:
                findings.append(finding)
            if dynamic_record is not None:
                dynamic.append(dynamic_record)

    return {
        "floors_that_do_not_refuse_the_first_deletion": len(findings),
        "findings": [f.as_dict() for f in sorted(findings, key=lambda f: (f.module, f.name))],
        "floors_swept": swept,
        "dynamic_population_floors": [
            d.as_dict() for d in sorted(dynamic, key=lambda d: (d.module, d.name))
        ],
        "bounds_read_and_out_of_scope": sorted(excluded),
        "gate_status": "measured",
    }


#: The denominator's floor, in the `naming.MINIMUM_SCANNED` style (T100): derived
#: from the sweep's own result it would shrink with any floor the sweep stops
#: finding, which is this task's own defect committed inside this task's gate.
#:
#: Measured at 57 floors in scope after round 2's broadened, value-shaped discovery
#: (`_module_constant_candidates`, `_resolves_to_name`, the two-hop delegation and
#: caller-parameter tracing) — round 1's own count was 46, and 30-against-46 was
#: exactly wide enough to hide all fourteen of round 1's fixed floors, which is the
#: reader's third finding on PR #436. Committed at 54, three points of slack:
#: raised alongside every measured broadening this round made, and narrow enough
#: that hiding more than a couple of floors — renaming them out of the candidate
#: set, or reclassifying several as dynamic — breaches it, where 30-against-46
#: tolerated sixteen. Per-module detail is deliberately not repeated here: a
#: hand-typed roll call of "already compliant" modules is exactly the prose this
#: task's own second finding showed cannot be trusted (`gate_reader_agreement` was
#: named compliant in round 1's version of this same comment and was, at the time,
#: genuinely out of scope). `status/evidence/T159.json`'s own
#: `dynamic_population_floors` and `bounds_read_and_out_of_scope` are regenerated
#: every run and are the only account of *which* floors are which that this module
#: stands behind.
MINIMUM_FLOORS_SWEPT = 54


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed, out of what was measured — the census swapped for its floor."""
    committed = {key: value for key, value in measured.items() if key != "floors_swept"}
    committed["floors_swept_at_least"] = MINIMUM_FLOORS_SWEPT
    return committed


#: Not declared here. `EVIDENCE_SOURCES` (T150) is for a census specifically
#: sensitive to the two tree mutations that check compares against — a Markdown
#: file added, a task archived — and `naming`/`arsenal_source`/`repo_gate` are the
#: only modules whose count moves under either. `floors_swept` counts constants in
#: `src/integral/*.py`; neither mutation touches that tree, so registering here
#: would only ever report `stable` trivially, and — the concrete cost, met while
#: writing this module — `repo_gate` cannot resolve a registrant it does not
#: already import, which every module *not* declaring one already avoids.


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH, src_dir: Path | None = None
) -> dict[str, Any]:
    """Measure and record `status/evidence/T159.json`; return what was measured.

    Refuses to write only when the sweep itself examined too little to trust — a
    breach of `floors_swept`'s floor. A nonzero finding count is still written: the
    whole point of this gate is to be able to fail with the finding visible.

    `src_dir` defaults to `None`, resolved to the module-level `_SRC_DIR` *inside*
    the call rather than baked into the signature — a default parameter value is
    bound once, at import time, so a test that monkeypatches `_SRC_DIR` (to point
    `_main` at a throwaway tree) would otherwise have no effect on this function's
    own default at all.
    """
    measured = measure(_SRC_DIR if src_dir is None else src_dir)
    if measured["floors_swept"] < MINIMUM_FLOORS_SWEPT:
        return measured
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str] | None = None) -> int:
    """Write T159's evidence.

    **Exit 1, not 3** on a breach or a finding — T115's finding about this
    repository's other floors, applied here from the day this one was written: `make
    evidence` prints 3 as "unmeasured (recorded)" and carries on, which makes a floor
    that exits 3 decoration rather than a gate.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    evidence = Path(args[0]) if args else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(evidence)
    print(json.dumps(measured, ensure_ascii=False))

    if measured["floors_swept"] < MINIMUM_FLOORS_SWEPT:
        print(
            f"only {measured['floors_swept']} floor(s) swept (floor {MINIMUM_FLOORS_SWEPT}) — "
            "a clean zero over a shrunken sweep is not a measurement",
            file=sys.stderr,
        )
        return 1

    for finding in measured["findings"]:
        print(
            f"✗ {finding['module']}.{finding['name']} ({finding['reason']}): {finding['detail']}",
            file=sys.stderr,
        )
    return 1 if measured["findings"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
