#!/usr/bin/env python3
"""T107's acceptance check: the catalogue is complete, current, and honest.

A script rather than a heredoc inside the task's fenced block, because a gate
that cannot be run on its own cannot be run by a reviewer either — and the one
thing a gate must never be is unreadable to the person deciding whether to
trust it.
"""

from __future__ import annotations

import sys

from integral import presentation, strings


def main() -> int:
    catalogue = strings.load()

    absent, outdated = strings.missing(catalogue), strings.stale(catalogue)
    if absent or outdated:
        print(f"missing: {absent}\nstale: {outdated}", file=sys.stderr)
        return 1

    # The rule, exercised rather than asserted: editing the source invalidates
    # every translation of that string, and nothing else.
    probe = strings.load()
    probe["entries"]["excluded_heading"]["en"] = "Ruled out"
    expected = {"es:excluded_heading", "ca:excluded_heading"}
    if set(strings.stale(probe)) != expected:
        print(
            f"editing the source did not invalidate its translations: {strings.stale(probe)}",
            file=sys.stderr,
        )
        return 1

    # An unserved language falls back on every string and reports every one —
    # silent English is the defect, announced English is the feature.
    if set(strings.fallbacks(catalogue, "de")) != set(strings.keys(catalogue)):
        print("an unserved language did not report its fallbacks", file=sys.stderr)
        return 1
    if strings.fallbacks(catalogue, "es"):
        print(
            f"es reported fallbacks it should not have: {strings.fallbacks(catalogue, 'es')}",
            file=sys.stderr,
        )
        return 1

    # The English page is byte-identical to what it was before the seam, so
    # every gate matching exact bytes still matches.
    for constant, expected_text in (
        (presentation.EXCLUDED_HEADING, "Excluded"),
        (presentation.UNKNOWN, "unknown"),
        (presentation.ESTIMATED_MARKER, "(estimated — the advert did not say)"),
    ):
        if constant != expected_text:
            print(f"the source page changed: {constant!r} != {expected_text!r}", file=sys.stderr)
            return 1

    measured = strings.measure()
    if measured["gate_status"] != "measured":
        print(f"unmeasured: {measured.get('reasons')}", file=sys.stderr)
        return 3
    print(
        "candidate_facing_strings_without_a_translation = "
        f"{measured['candidate_facing_strings_without_a_translation']} over "
        f"{measured['candidate_facing_strings_evaluated']} evaluated "
        f"({measured['strings_scanned']} strings x {len(measured['languages_served'])} languages)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
