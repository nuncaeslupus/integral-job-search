"""The gate-fence grammar `tools/verify_gates.py` and the corpus-scope tests share.

`parse_gate_block` reads the fenced ``gate`` block inside a task's
``## Acceptance gate`` section; `gate_declaration` classifies a payload as
``readable`` / ``unreadable`` / ``absent`` by that same grammar, so a fence no
reader reaches is a fault rather than a quieter tally (T122). It mirrors
`gate_evidence.py`'s regexes rather than importing them: that script lives
under a hyphenated vendored directory and exits the process instead of
returning.
"""

from __future__ import annotations

import re
from typing import Literal

# The fenced ``gate`` block inside the ## Acceptance gate section, and the
# ``field: value`` lines within it. Mirrors gate_evidence.py's grammar rather
# than importing it: that script lives under a hyphenated vendored directory,
# is not importable as a module, and exits the process instead of returning.
_SECTION_RE = re.compile(r"##\s+Acceptance gate\s*\n(.*?)(?=\n##\s|\Z)", re.DOTALL | re.IGNORECASE)
_BLOCK_RE = re.compile(r"```gate\s*\n(.*?)```", re.DOTALL)
_GATE_RE = re.compile(r"(<=|>=|==|!=|<|>)\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")

#: The fence opener, and the whole of what `tools/verify_gates.py` used to
#: test for. T122: a substring is not a grammar. A payload can carry these
#: seven characters and still declare nothing any reader will read — the label
#: bolded rather than headed, the fence in a section the reader's regex has
#: already walked past, the string quoted inside a ``text`` block. Every one of
#: those counted as a gate and was then handed to a checker that extracted
#: nothing and exited 0, so the board's "gate(s) asserted" tally went *up* for
#: a task whose evidence file was never opened and was not required to exist.
GATE_FENCE = "```gate"


def gate_declaration(text: str) -> Literal["readable", "unreadable", "absent"]:
    """What a payload's gate fence amounts to, by the grammar that reads it.

    Three outcomes, because the two that a boolean conflates need different
    handling and it is their conflation that T122 is about:

    * ``readable`` — `parse_gate_block` extracts a block, so `gate_evidence.py`
      extracts the same one and asserts it. This is the only state in which a
      task may be counted among the gates a verifier asserted.
    * ``unreadable`` — the fence is *there* and no reader reaches it. Not an
      ungated task: an ungated task is a task whose author declared no gate,
      and this one declared one that nothing enforces. Reporting it as ungated
      is what let `t-2a30f58a` and `t-246f6dde` (#334) sit at terminal status
      with their evidence files never opened, so it is reported as a fault.
    * ``absent`` — no fence at all. `t-62612ae0` (T124) is one such honest
      case: an executable ``bash`` gate and no evidence block, which this
      layer has nothing to say about. How many there are is deliberately not
      stated — a count here goes stale on the next such task, and nothing
      tests a docstring.

    The readable case is decided by `parse_gate_block` — the module comment
    above says why that is a *mirror* of `gate_evidence.py`'s regexes rather
    than an import of them, and a mirror is still two descriptions of one
    grammar. What T122 removes is the **third** description: `verify_gates.py`
    counting fences by substring while the checker read them by grammar. The
    remaining mirror is covered from the other end — a gate counted as
    asserted whose checker printed nothing is reported as a fault by
    `verify_gates.main`, which is a behavioural check that holds however far
    the two regex sets drift.
    """
    if parse_gate_block(text) is not None:
        return "readable"
    if GATE_FENCE in text:
        return "unreadable"
    return "absent"


def parse_gate_block(text: str) -> dict[str, str] | None:
    """The ``gate`` block's fields, or `None` if the payload declares no block."""
    section = _SECTION_RE.search(text)
    if section is None:
        return None
    block = _BLOCK_RE.search(section.group(1))
    if block is None:
        return None
    fields: dict[str, str] = {}
    for raw in block.group(1).splitlines():
        line = raw.strip()
        if not line:
            continue
        if ":" in line and not _GATE_RE.search(line.split(":", 1)[0]):
            name, value = line.split(":", 1)
            fields[name.strip().lower()] = value.strip().strip("'\"")
    return fields
