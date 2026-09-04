"""A module owning two gates reported the wrong one, by arithmetic.

`make evidence` reads three exit codes: `0` passed, `3` is `unmeasured` and is
recorded and continued past, anything else is a hard stop. Three modules
combined their two gates with `max` — and `max(1, 3) == 3`, so a gate that
really failed was reported as the *other* gate's `unmeasured` and the run
carried on. The failing gate's violations went to stderr, in a recipe that
sends stdout to `/dev/null` and never reads stderr.

Nothing was wrong with either measurement. The order of the codes is not their
severity order, and until `integral.gate_exit` nothing said so.
"""

from __future__ import annotations

import re
from pathlib import Path

from integral import connector_policy, liveness, robots
from integral.gate_exit import worst


def test_a_failure_outranks_an_unmeasured_gate() -> None:
    """The defect itself. A finding must not be reported as the absence of one."""
    assert max(1, 3) == 3
    assert worst(1, 3) == 1
    assert worst(3, 1) == 1


def test_unmeasured_outranks_a_pass() -> None:
    """"Cannot be scored yet" is not a pass — the reason `make evidence` prints
    it rather than `ok`."""
    assert worst(0, 3) == 3
    assert worst(3, 0) == 3


def test_misuse_outranks_everything() -> None:
    """Exit 2 is a mistyped invocation: nothing was measured, so no verdict
    printed beside it can be trusted either."""
    assert worst(2, 1) == 2
    assert worst(2, 3) == 2
    assert worst(0, 2) == 2


def test_two_passes_are_a_pass_and_no_codes_at_all_is_one() -> None:
    assert worst(0, 0) == 0
    assert worst() == 0
    assert worst(0) == 0


def test_a_code_with_no_assigned_meaning_is_never_reported_as_a_pass() -> None:
    """Guessing that an unknown code is benign would be this module's own
    defect wearing the fix's clothes."""
    assert worst(0, 7) == 7
    assert worst(3, 7) == 7
    assert worst(1, 7) == 7


#: A `max` whose first argument is an exit code — a name ending `_rc`, or a
#: call to one of the `_run_*` gate runners. `max` over anything else in these
#: modules is fine: `robots.py` uses one to floor a crawl delay.
_MAX_OVER_EXIT_CODES = re.compile(r"max\(\s*(?:[A-Za-z_]*_rc\b|_run_[A-Za-z_]+\()")


def test_no_module_that_owns_two_gates_still_combines_them_with_max() -> None:
    """The three sites, named. A fourth module written the same way is caught
    by this reading rather than by the next audit."""
    for module in (connector_policy, liveness, robots):
        source = module.__file__
        assert source is not None
        text = Path(source).read_text(encoding="utf-8")
        found = _MAX_OVER_EXIT_CODES.search(text)
        assert found is None, f"{module.__name__}: {found.group(0) if found else ''}"
        assert "worst(" in text, module.__name__
