"""T160: the one rule behind every "this floor is a literal" pin.

Three committed tests assert that a floor constant is an integer literal and
not an expression over the population it guards (`len(X)` shrinks with the very
deletion the floor exists to catch, so the guard can never fire). Each used to
read the module's top-level statements only, so a rebinding **one block deep**
escaped all of them while a decoy literal kept the pin satisfied::

    MINIMUM_ARRANGEMENTS_PROBED = 13            # the decoy the pin sees
    if True:
        MINIMUM_ARRANGEMENTS_PROBED = len(ARRANGEMENTS) + 1   # what binds

Measured on #425's fifth read: 51 tests green, and the pre-fix fail-open back in
full. The rule here is closed rather than enumerated: `ast.walk` visits every
node at every depth, and *any* node that binds the name (assignment, annotated
or augmented assignment, walrus, loop or comprehension target, `with ... as`,
`except ... as`, import alias, `def`/`class` of that name, `global`) is a
binding. A floor has exactly one, at module level, and its value is an integer
literal. All three pins call `binding_defects`: one implementation of the rule.

`python -m integral.literal_pin` measures `literal_pins_a_nested_rebinding_escapes`
into `status/evidence/T160.json`: for each committed pin it appends each nested
rebinding form beside the real, unchanged decoy literal, and counts the pins for
which `binding_defects` stays silent.
"""

from __future__ import annotations

import ast
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = Path(__file__).resolve().parent
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T160.json"

#: The committed literal-pins, as (module file, pinned constant). Each has a test
#: that calls `binding_defects`: `verified_gate`'s two and `gate_reader_agreement`'s
#: one. Declared here and floored at the literal below, since a count derived from
#: this table would shrink with a dropped pin.
PINS: tuple[tuple[str, str], ...] = (
    ("verified_gate.py", "MINIMUM_CONTRACTS"),
    ("verified_gate.py", "MINIMUM_CI_CLAIM_SCENARIOS"),
    ("gate_reader_agreement.py", "MINIMUM_ARRANGEMENTS_PROBED"),
)
#: Equal to the table today, so the first dropped row breaches it.
#: arsenal-floor-margin: MINIMUM_PINS_SWEPT value=3
MINIMUM_PINS_SWEPT = 3

#: Rebinding forms appended after the real source, each nested, with the real
#: literal left in place as the decoy. `{n}` is the pinned name.
NESTED_REBINDINGS: dict[str, str] = {
    "if": "if True:\n    {n} = len(PIN_POPULATION) + 1\n",
    "if_literal": "if True:\n    {n} = 1\n",
    "if_annotated": "if True:\n    {n}: int = len(PIN_POPULATION)\n",
    "try": "try:\n    {n} = len(PIN_POPULATION)\nexcept Exception:\n    pass\n",
    "for": "for {n} in range(1):\n    pass\n",
    "with": "with open('x') as {n}:\n    pass\n",
    "while": "while True:\n    {n} = len(PIN_POPULATION)\n    break\n",
    "walrus": "if ({n} := len(PIN_POPULATION)):\n    pass\n",
    "augassign": "if True:\n    {n} += 1\n",
    "import_alias": "if True:\n    from os import sep as {n}\n",
    "except_alias": "try:\n    pass\nexcept Exception as {n}:\n    pass\n",
    "nested_if": "if True:\n    if True:\n        {n} = len(PIN_POPULATION)\n",
}


def _stored(target: ast.AST) -> list[str]:
    return [
        s.id for s in ast.walk(target) if isinstance(s, ast.Name) and isinstance(s.ctx, ast.Store)
    ]


def _bound_names(node: ast.AST) -> list[tuple[str, ast.AST | None]]:
    """Every (name, plain value or None) this one node binds."""
    out: list[tuple[str, ast.AST | None]] = []
    if isinstance(node, ast.Assign):
        for target in node.targets:
            plain = node.value if isinstance(target, ast.Name) else None
            out.extend((n, plain) for n in _stored(target))
    elif isinstance(node, ast.AnnAssign):
        if isinstance(node.target, ast.Name):
            out.append((node.target.id, node.value))
    elif isinstance(node, ast.AugAssign):
        out.extend((n, None) for n in _stored(node.target))
    elif isinstance(node, ast.NamedExpr):
        out.append((node.target.id, None))
    elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        out.extend((n, None) for n in _stored(node.target))
    elif isinstance(node, ast.withitem) and node.optional_vars is not None:
        out.extend((n, None) for n in _stored(node.optional_vars))
    elif isinstance(node, ast.ExceptHandler) and node.name:
        out.append((node.name, None))
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        out.extend((a.asname or a.name.split(".")[0], None) for a in node.names)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        out.append((node.name, None))
    elif isinstance(node, (ast.Global, ast.Nonlocal)):
        out.extend((n, None) for n in node.names)
    elif isinstance(node, ast.arg):
        out.append((node.arg, None))
    return out


def binding_defects(source: str, name: str) -> list[str]:
    """Why `name` is not "one module-level integer literal"; empty when it is.

    Walks every node at every depth, so a rebinding nested in any block counts.
    An annotated literal (`NAME: int = 3`) is a literal. A parameter or local of
    the same name is also flagged: that false alarm is fail-closed, costing a
    rename, where a silent pass would restore the fail-open.
    """
    tree = ast.parse(source)
    top_level = {id(n) for n in tree.body}
    sites = [
        (node, value)
        for node in ast.walk(tree)
        for bound, value in _bound_names(node)
        if bound == name
    ]
    if not sites:
        return [f"{name} is never bound"]
    defects: list[str] = []
    if len(sites) != 1:
        lines = sorted(getattr(n, "lineno", 0) for n, _ in sites)
        defects.append(f"{name} is bound {len(sites)} times (lines {lines}); a floor binds once")
    for node, value in sites:
        line = getattr(node, "lineno", 0)
        if id(node) not in top_level:
            defects.append(f"{name} is bound at line {line} below module level")
        elif not (
            isinstance(value, ast.Constant)
            and isinstance(value.value, int)
            and not isinstance(value.value, bool)
        ):
            defects.append(f"{name} at line {line} is not an integer literal")
    return defects


def _unmeasured(reason: str) -> dict[str, Any]:
    return {
        "literal_pins_a_nested_rebinding_escapes": -1,
        "gate_status": "unmeasured",
        "reason": reason,
    }


def measure(
    src_dir: Path = _SRC,
    pins: tuple[tuple[str, str], ...] = PINS,
    reader: Callable[[str, str], list[str]] = binding_defects,
) -> dict[str, Any]:
    """Count the pins for which a nested rebinding plus the real decoy stays silent.

    `reader` is what the pins call; tests pass the old top-level-only reader to
    show the metric reads 3 against it, which is the "must read at least 2
    before the fix" requirement as a fixture rather than a recollection.
    """
    escapes: list[str] = []
    forms_missed: dict[str, list[str]] = {}
    swept = 0
    for filename, name in pins:
        path = src_dir / filename
        if not path.is_file():
            return _unmeasured(f"{filename} is missing")
        source = path.read_text(encoding="utf-8")
        if reader(source, name):
            return _unmeasured(f"{filename}:{name} is not a clean literal to begin with")
        swept += 1
        missed = [
            form
            for form, template in NESTED_REBINDINGS.items()
            if not reader(source + "\n" + template.format(n=name), name)
        ]
        if missed:
            escapes.append(f"{filename}:{name}")
            forms_missed[f"{filename}:{name}"] = missed
    return {
        "literal_pins_a_nested_rebinding_escapes": len(escapes),
        "escaping_pins": escapes,
        "forms_that_escaped": forms_missed,
        "nested_forms_tried": sorted(NESTED_REBINDINGS),
        "pins_swept_at_least": MINIMUM_PINS_SWEPT,
        "gate_status": "measured" if swept >= MINIMUM_PINS_SWEPT else "unmeasured",
        "_swept": swept,
    }


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed: the floor, never the census of the day."""
    return {k: v for k, v in measured.items() if not k.startswith("_")}


def _main(argv: list[str] | None = None) -> int:
    check = "--check" in (argv or sys.argv)[1:]
    measured = measure()
    print(json.dumps(record(measured), ensure_ascii=False))
    status = measured["gate_status"]
    if not check:
        DEFAULT_EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_EVIDENCE_PATH.write_text(
            json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    if status != "measured":
        return 3
    return 1 if measured["literal_pins_a_nested_rebinding_escapes"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
