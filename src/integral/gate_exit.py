"""Which of several exit codes a module that owns more than one gate reports.

`make evidence` reads three: `0` is a pass, `3` is `unmeasured` — the check
ran and found it cannot be scored yet, which is recorded and **continued past**
— and anything else is a hard stop. A module owning two gates runs both and has
to report one number, and three of them combined the two with `max`.

`max(1, 3) == 3`. So a gate that really failed was reported as `unmeasured`
whenever the *other* gate's scan happened to be under its floor, `make
evidence` printed `unmeasured (recorded)`, and the run carried on. Nothing was
wrong with either measurement; the arithmetic that combined them was, because
the numeric order of these codes is not their severity order and nothing said
so. It is fail-open, and it is silent — the failing gate still printed its
violations to stderr, into a target whose output is `>/dev/null`.

Severity is stated once, here, and it is the whole of this module:

    0 (passed)  <  3 (unmeasured)  <  1 (a gate failed)  <  2 (misuse)

`unmeasured` outranks a pass because "cannot be scored yet" is not a pass. It
loses to a failure because a failure is a finding and `unmeasured` is the
absence of one — reporting the absence over the finding is exactly the swallow
above. Misuse ranks highest because a mistyped invocation measured nothing at
all, so no verdict printed beside it can be trusted either.
"""

from __future__ import annotations

#: The exit codes this repository assigns a meaning to, in increasing severity.
SEVERITY: tuple[int, ...] = (0, 3, 1, 2)


def _rank(code: int) -> tuple[int, int]:
    """Severity of one code. An unlisted code outranks every listed one.

    A code nobody has assigned a meaning to is not a pass, and treating it as
    one would be this module's own defect wearing the fix's clothes.
    """
    if code in SEVERITY:
        return (0, SEVERITY.index(code))
    return (1, code)


def worst(*codes: int) -> int:
    """The most severe of `codes` — never `max`, which orders them numerically.

    No codes at all is `0`: nothing ran, so nothing failed. That case is not
    reachable from the call sites here, and is defined rather than left to
    `max`'s `ValueError`.
    """
    if not codes:
        return 0
    return max(codes, key=_rank)
