"""T160: the shared literal-pin rule, driven against every nesting form.

Cases derive from the claim "a floor is bound once, at module level, as an
integer literal", not from what `binding_defects` happens to return.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral import literal_pin
from integral.literal_pin import NESTED_REBINDINGS, PINS, binding_defects, measure

DECOY = "MINIMUM_X = 13\nPOP = [1, 2]\n"


def _top_level_only(source: str, name: str) -> list[str]:
    """The reader every pin used before T160: `.body` of the module, nothing deeper."""
    import ast

    hits = [
        n
        for n in ast.parse(source).body
        if isinstance(n, ast.Assign)
        and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name)
        and n.targets[0].id == name
    ]
    ok = len(hits) == 1 and isinstance(hits[0].value, ast.Constant)
    return [] if ok else ["bad"]


def test_a_clean_literal_passes_including_annotated() -> None:
    assert binding_defects(DECOY, "MINIMUM_X") == []
    assert binding_defects("MINIMUM_X: int = 13\n", "MINIMUM_X") == []


@pytest.mark.parametrize("form", sorted(NESTED_REBINDINGS))
def test_every_nested_form_beside_a_decoy_fails_the_pin(form: str) -> None:
    mutated = DECOY + NESTED_REBINDINGS[form].format(n="MINIMUM_X")
    assert binding_defects(mutated, "MINIMUM_X") != []


@pytest.mark.parametrize(
    "mutated",
    [
        "MINIMUM_X = len(POP) + 1\n",
        "MINIMUM_X = int(len(POP))\n",
        "MINIMUM_X = 13\nMINIMUM_X = len(POP)\n",
        "MINIMUM_X = 13 if POP else 1\n",
        "from os import sep as MINIMUM_X\n",
        "MINIMUM_X = True\n",
        "def f():\n    global MINIMUM_X\n    MINIMUM_X = 1\nMINIMUM_X = 13\n",
        "MINIMUM_X = 13\nclass C:\n    def m(self, MINIMUM_X): ...\n",
        "POP = []\n",
    ],
)
def test_other_attack_forms_and_the_unbound_name_fail(mutated: str) -> None:
    assert binding_defects(mutated, "MINIMUM_X") != []


def test_the_metric_reads_all_pins_against_the_old_reader() -> None:
    """Before the fix: every committed pin escaped (the task requires >= 2)."""
    old = measure(reader=_top_level_only)
    assert old["literal_pins_a_nested_rebinding_escapes"] == len(PINS) >= 2


def test_the_metric_reads_zero_against_the_shared_reader() -> None:
    measured = measure()
    assert measured["literal_pins_a_nested_rebinding_escapes"] == 0
    assert measured["gate_status"] == "measured"


def test_a_dropped_pin_row_is_unmeasured_not_clean() -> None:
    measured = measure(pins=PINS[:1])
    assert measured["literal_pins_a_nested_rebinding_escapes"] == 0
    assert measured["gate_status"] == "unmeasured"


def test_the_floor_on_pins_swept_is_a_literal_and_equals_the_table() -> None:
    source = Path(literal_pin.__file__).read_text(encoding="utf-8")
    assert binding_defects(source, "MINIMUM_PINS_SWEPT") == []
    assert literal_pin.MINIMUM_PINS_SWEPT == len(PINS) == 3


def test_every_committed_pin_test_uses_the_shared_rule() -> None:
    """The pins are tests; each must call `binding_defects` for its constant."""
    root = Path(__file__).parent
    for _filename, name in PINS:
        tests = "".join(p.read_text(encoding="utf-8") for p in root.glob("test_*.py"))
        assert f'binding_defects(source, "{name}")' in tests, (
            f"{name} has no pin reading it through binding_defects"
        )


def test_the_record_commits_the_floor_and_no_census() -> None:
    committed = literal_pin.record(measure())
    assert not any(k.startswith("_") for k in committed)
    assert committed["pins_swept_at_least"] == 3
    assert json.loads(json.dumps(committed)) == committed
