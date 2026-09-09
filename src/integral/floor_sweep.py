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

#: Every spelling this repository uses for a floor. `MINIMUM_`/`MIN_` alone is what the
#: previous (T122-era) sweep used; the other two are the first named blind spot.
_FLOOR_NAME_RE = re.compile(
    r"^(?:MINIMUM_[A-Z0-9_]+|MIN_[A-Z0-9_]+|[A-Z][A-Z0-9_]*_AT_LEAST|[A-Z][A-Z0-9_]*_MINIMUM)$"
)

#: A floor's own name pattern would also match this module's diagnostics constant.
#: Excluded by identity, not by name, a few lines down.

#: Phrasing this repository actually uses, in the floors already read while building
#: this module, to argue that a floor's margin below its population is deliberate
#: rather than an accident: `salary_recovery.MINIMUM_WORDING_CASES` ("Raised from 40
#: ... sits far below"), `gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED` ("one unit
#: of slack"), `gate_reader_agreement.MINIMUM_GATES_COMPARED` ("sits under today's
#: total"), `audit_followup.CASES_AT_LEAST` / `connector_policy.ADJUDICATIONS_AT_LEAST`
#: ("deliberately under"), `connector_policy.PACKAGES_AT_LEAST` ("Same reasoning"),
#: `robots.FIXTURES_AT_LEAST` / `second_reader`'s four ("Raised ... to", "raised
#: again", "kept its slack", "small on purpose"), `review_reader`'s four ("the margin
#: over the observed count is unchanged"). Not a promise no future comment will need a
#: new phrase — a floor this misses is one this module under-reports, never one it
#: wrongly clears, because a positive margin with no match here is a finding.
_MARGIN_ARGUED_RE = re.compile(
    r"\bmargin\b|\bslack\b|\braised\b|deliberately\s+(?:under|below)|"
    r"sits\s+(?:well\s+|far\s+)?(?:under|below)|\bwell\s+below\b|\bfar\s+below\b|"
    r"same\s+reasoning|on\s+purpose",
    re.IGNORECASE,
)

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


def _top_level_int_name_assignments(tree: ast.Module) -> list[tuple[str, int, ast.expr]]:
    """Every module-level `NAME = <expr>` (or annotated) whose name matches the floor spelling."""
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
            if isinstance(target, ast.Name) and _FLOOR_NAME_RE.match(target.id):
                found.append((target.id, node.lineno, value))
    return found


def _literal_int(expr: ast.expr) -> int | None:
    if (
        isinstance(expr, ast.Constant)
        and isinstance(expr.value, int)
        and not isinstance(expr.value, bool)
    ):
        return expr.value
    return None


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
                returns = [
                    n.value
                    for n in ast.walk(callee)
                    if isinstance(n, ast.Return) and n.value is not None
                ]
                if len(returns) == 1:
                    return _collection_kind(returns[0], tree, callee, None, depth + 1)
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
            dict_literal, dict_func = _resolve_to_dict_literal(obj_value, tree, func)
            if dict_literal is not None:
                for key_node, value_node in zip(
                    dict_literal.keys, dict_literal.values, strict=True
                ):
                    if (
                        isinstance(key_node, ast.Constant)
                        and key_node.value == key_string
                        and value_node is not None
                    ):
                        return _collection_kind(value_node, tree, dict_func, None, depth + 1)
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
            returns = [
                n.value
                for n in ast.walk(callee)
                if isinstance(n, ast.Return) and n.value is not None
            ]
            if len(returns) == 1:
                # The callee might itself only delegate (`write_evidence` calling
                # `measure` and returning what it got) — recurse one more hop rather
                # than requiring the dict literal to be textually present here.
                return _resolve_to_dict_literal(returns[0], tree, callee, depth + 1)
    return None, None


def _population_for(
    other_operand: ast.expr,
    tree: ast.Module,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    before_lineno: int | None,
) -> tuple[bool, int | None]:
    """`(in_scope, population)`. `in_scope` is True only if `other_operand` traces to a
    `len(...)` call; `population` is the concrete count when that `len(...)`'s argument
    is a literal collection this module can count, else `None` for a dynamic one."""
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
    side; returns `(other_side, enclosing_function_or_None, lineno)` for each."""
    sites: list[tuple[ast.expr, ast.FunctionDef | ast.AsyncFunctionDef | None, int]] = []
    functions = _all_function_defs(tree)

    def enclosing(node: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        return _innermost_enclosing(node, functions)

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = node.left, node.comparators[0]
            if isinstance(left, ast.Name) and left.id == name:
                sites.append((right, enclosing(node), node.lineno))
            elif isinstance(right, ast.Name) and right.id == name:
                sites.append((left, enclosing(node), node.lineno))
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


def _delegated_other_operand(
    tree: ast.Module, name: str
) -> tuple[ast.expr, ast.FunctionDef | ast.AsyncFunctionDef | None, int] | None:
    """The third named blind spot: a floor passed as an argument to a same-module
    helper that does the comparison inside its own body. Follows exactly one call of
    indirection — the shape every delegated floor in this repository actually uses."""
    top_level_functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    all_functions = _all_function_defs(tree)

    def enclosing(node: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        return _innermost_enclosing(node, all_functions)

    for node in ast.walk(tree):
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
                if isinstance(expr, ast.Name) and expr.id == name
            ),
            None,
        )
        if floor_param is None:
            continue
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
                    caller_expr = mapping[other_param_name]
                    return caller_expr, enclosing(node), node.lineno
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
        # Require only that the floor's value is explained at all.
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
        return None, DynamicFloor(module=module.stem, name=name, lineno=lineno), True

    margin = population - literal_value
    if margin <= 0:
        return None, None, True

    if _MARGIN_ARGUED_RE.search(comment):
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
        if module.stem == "floor_sweep":
            # This module's own diagnostics constants match the name pattern (none are
            # floors); excluded by identity rather than added to every other module's
            # allowlist story.
            continue
        for name, lineno, value_expr in _top_level_int_name_assignments(module.tree):
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


#: The denominator's floor, in the `naming.MINIMUM_SCANNED` style (T100), and a
#: literal for `gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED`'s reason (see the
#: module docstring): derived from the sweep's own result it would shrink with any
#: floor the sweep stops finding, which is this task's own defect committed inside
#: this task's gate. Measured at 46 floors in scope the day this was written — the
#: three named in the task's table (`profile`, `bodyless_post`, `page_placeholder`),
#: eleven more of the identical "self-test's own running tally, no margin argued"
#: shape the broadened sweep found once it could trace a delegated call and a
#: cross-function dict return (`elicit_extract`, `trait_sufficiency`, `candidate`,
#: `constraints_step`, `decline`, `freshness`, `offers`, `question_bank`,
#: `retraction`, `revision`, `scoring` — all fixed the same way, by raising the floor
#: to what the probe measures today), and the rest already compliant
#: (`naming`, `gate_reader_agreement` x2, `salary_recovery`, `review_reader` x4,
#: `audit_followup`, `connector_policy` x2, `robots`, `second_reader` x4,
#: `extraction`, `interview` x2, `sourcing`, `connector_health`, `connector_procedure`,
#: `capture_provenance`, `pagination_capture`). Committed well under that so a module
#: losing its floor entirely does not have to be the first thing this gate notices.
MINIMUM_FLOORS_SWEPT = 30


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
