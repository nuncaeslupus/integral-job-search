"""T120 — the second robots reader, read against a table it did not write.

Every `expected` in `integral.second_reader_cases` was derived from RFC 9309 by
a session instructed not to open `src/` and never to settle a verdict by running
code. These tests are the machinery that puts this repository's reader in front
of that table; the table itself is the fixture, and the count of cases it
carries is what `status/evidence/T120.json` is denominated by.

The one thing these tests must never do is decide correctness by execution. No
assertion below reads a verdict out of `second_reader.allows` and calls it
right: each one compares that verdict against a written-down `expected` and a
cited section, which is the circularity T70 took ten defects learning to break.
"""

from __future__ import annotations

import json
import time
import urllib.robotparser
from pathlib import Path

import pytest

from integral import robots
from integral import second_reader as sr
from integral import second_reader_cases as cases

AGENT = "integral-job-search/0.1"


def _stdlib_allows(text: str, agent: str, target: str) -> bool:
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch(agent, target)


def test_the_second_reader_refuses_a_path_the_stdlib_allows_on_the_same_file() -> None:
    """The demonstration T120's gate block asks for, made on real cases.

    A "longest-match" reader that happens to answer exactly as
    `urllib.robotparser` does on every committed case has demonstrated nothing:
    the stdlib's inability to refuse is the whole reason this module exists. So
    the table must contain the disagreement, and it must be in the refusing
    direction — this reader saying no where the stdlib says yes.
    """
    disagreements = [
        case
        for case in cases.CASES
        if case.expected == cases.DISALLOW_VERDICT
        and not sr.allows(case.robots_txt, case.agent, case.path)
        and _stdlib_allows(case.robots_txt, case.agent, case.path)
    ]
    assert len(disagreements) >= sr.STDLIB_DISAGREEMENTS_AT_LEAST, (
        "the second reader refuses no path the stdlib allows, so replacing the "
        f"stdlib has been asserted and not shown: {[c.id for c in disagreements]}"
    )
    # And the direction is the one that matters: each is a path RFC 9309
    # refuses, which the reader being replaced admitted. Fail-open, every one.
    for case in disagreements:
        assert case.expected == cases.DISALLOW_VERDICT, case.id


def test_every_second_reader_fixture_reads_as_the_rfc_requires() -> None:
    """The gate itself: `second_reader_verdicts_misread == 0`.

    A failure here names the case, the section its verdict was read off, and
    whether the miss is fail-open — the reader allowing what the RFC refuses —
    or fail-closed. The two are not the same finding and the message says which.
    """
    measured = sr.measure()
    assert measured["second_reader_verdicts_misread"] == 0, "\n".join(
        f"{case['id']}: {case['section']} requires {case['expected']} for "
        f"{case['path']!r}, reader says {case['actual']} ({case['direction']}) — "
        f"{case['why']}"
        for case in measured["misread_cases"]
    )


def test_a_scan_under_its_floor_reports_unmeasured_rather_than_a_clean_zero() -> None:
    """A reader that reads nothing misreads nothing, and that is not a pass.

    Three ways a table can be too weak to mean anything, each of which has to
    read `unmeasured` rather than a clean zero: too few cases, too few in the
    fail-open direction, and too much agreement with the parser being replaced.
    """
    empty = sr.measure(())
    assert empty["second_reader_verdicts_misread"] == 0
    assert empty["gate_status"] == "unmeasured"

    one = sr.measure(cases.CASES[:1])
    assert one["gate_status"] == "unmeasured"

    # A full-sized table of nothing but fail-closed cases is still unmeasured:
    # the direction that matters is the one a weak matcher gets wrong by
    # allowing, and a table without those says nothing about it.
    neutral = tuple(case for case in cases.CASES if case.direction != cases.FAIL_OPEN_RISK)
    assert sr.measure(neutral)["gate_status"] == "unmeasured"

    assert sr.measure()["gate_status"] == "measured"


def test_the_committed_table_clears_every_floor_it_is_denominated_by() -> None:
    """The floors are floors, not the count of the day (T100) — and they hold."""
    measured = sr.measure()
    assert measured["second_reader_fixtures_checked"] >= sr.FIXTURES_AT_LEAST
    assert measured["fail_open_cases_checked"] >= sr.FAIL_OPEN_CASES_AT_LEAST
    assert measured["paths_refused_that_the_stdlib_allows"] >= sr.STDLIB_DISAGREEMENTS_AT_LEAST
    assert measured["gate_status"] == "measured"


def test_every_case_names_the_section_its_verdict_was_read_off() -> None:
    """A verdict with no citation cannot be checked against anything.

    The table is only worth what its derivations are: a case whose `expected`
    is a bare ALLOW/DISALLOW is indistinguishable from one copied off a run of
    the code, which is the thing the second session exists to rule out.
    """
    seen: set[str] = set()
    for case in cases.CASES:
        assert case.id not in seen, f"duplicate case id {case.id}"
        seen.add(case.id)
        assert case.expected in (cases.ALLOW_VERDICT, cases.DISALLOW_VERDICT), case.id
        assert case.direction in cases.DIRECTIONS, case.id
        assert case.section.strip(), f"{case.id}: no section cited"
        assert case.why.strip(), f"{case.id}: no derivation given"
        assert case.path.startswith("/"), f"{case.id}: {case.path!r} is not a request path"


def test_a_misread_case_returns_one_rather_than_the_three_evidence_records(
    tmp_path: Path,
) -> None:
    """Exit 1 on a misread, 3 under the floor, 0 otherwise — and never 0 for both.

    `make evidence` records a 3 and continues; it stops on a 1. So a reader that
    gets a case wrong must not be able to reach the exit that means "recorded,
    carry on", and a table too small must not reach the exit that means "pass".
    """
    target = tmp_path / "T120.json"

    assert sr._main([str(target)]) == 0
    assert json.loads(target.read_text())["second_reader_verdicts_misread"] == 0

    wrong = cases.CASES[0]
    flipped = (
        cases.ALLOW_VERDICT if wrong.expected == cases.DISALLOW_VERDICT else cases.DISALLOW_VERDICT
    )
    mutated = (
        *cases.CASES[1:],
        cases.Case(
            id=wrong.id,
            robots_txt=wrong.robots_txt,
            agent=wrong.agent,
            path=wrong.path,
            expected=flipped,
            section=wrong.section,
            why=wrong.why,
            direction=wrong.direction,
        ),
    )
    assert sr.measure(mutated)["second_reader_verdicts_misread"] == 1


def test_the_record_commits_floors_and_not_the_counts_of_the_day() -> None:
    """T100, applied before it can bite: a new case must not be evidence drift."""
    committed = sr.record(sr.measure())
    assert "second_reader_fixtures_at_least" in committed
    assert "second_reader_fixtures_checked" not in committed
    assert "fail_open_cases_checked" not in committed
    assert "paths_refused_that_the_stdlib_allows" not in committed
    assert committed["gate_status"] == "measured"


def test_the_committed_evidence_matches_what_the_reader_measures_now() -> None:
    """The file in `status/evidence/` is the measurement, not a memory of one."""
    on_disk = json.loads(sr.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert on_disk == sr.record(sr.measure())


@pytest.mark.parametrize(
    ("pattern", "target", "matched"),
    [
        # §2.2.3: `*` is any sequence INCLUDING the empty one, so `/a*b` covers
        # `/ab`. A matcher compiling `*` to `.+` refuses to see this, and the
        # rule it silently drops is usually a Disallow.
        ("/a*b", "/ab", True),
        ("/a*b", "/axxb", True),
        # --- implementer-derived, and labelled as such -----------------------
        # These four are NOT from the independent table, and they are here
        # rather than in `second_reader_cases` for that reason: that module's
        # whole value is that its author never saw this code, and adding a case
        # of my own to it would spend exactly what it is for.
        #
        # They exist because a mutation round found the gap. Every pattern in
        # the spec-derived table has at most one *significant* wildcard, so the
        # matcher's middle-run branch — the literal runs between the first and
        # last wildcards — was never exercised, and a mutation making an
        # interior `*` require at least one character survived the whole table.
        # The verdicts are read off the same §2.2.3 sentence the table cites for
        # `star_matches_empty_sequence`: "any sequence of characters", the empty
        # sequence included, applied to each wildcard rather than to one.
        ("/a*b*c", "/abc", True),
        ("/a*b*c", "/axxbyyc", True),
        ("/a*b*c", "/acb", False),
        ("/a*b*c$", "/axxbyyc", True),
        # An empty pattern matches nothing at all: `Disallow:` is the documented
        # way to restrict nothing, and reading it as the zero-length prefix
        # every path starts with would invert it into a site-wide refusal.
        ("", "/anything", False),
        # §2.2.2's matching is a prefix match anchored at the first octet, so a
        # pattern that occurs mid-path does not match.
        ("/jobs", "/en/jobs", False),
        ("/jobs", "/jobs/123", True),
    ],
)
def test_the_metacharacters_behave_as_section_2_2_3_describes(
    pattern: str, target: str, matched: bool
) -> None:
    assert sr.matches(pattern, target) is matched


def test_percent_canonicalisation_resolves_only_the_unreserved_set() -> None:
    """§2.2.3 equivalence, in the direction that can be got wrong safely.

    `%7E` and `~` are the same octet and must compare equal. `%2F` and `/` are
    NOT: resolving an encoded slash would let a rule about `/a%2Fb` quietly
    cover `/a/b`, which is a rule matching more than it says.
    """
    assert sr.canonical("/%7Euser") == sr.canonical("/~user")
    assert sr.canonical("/a%2Fb") != sr.canonical("/a/b")
    assert sr.canonical("/a%2fb") == sr.canonical("/a%2Fb")
    # A `%` that begins no valid escape stays a literal `%` rather than raising
    # or being dropped, so both sides of a comparison spell it the same way.
    assert sr.canonical("/100%") == "/100%"
    assert sr.canonical("/%zz") == "/%zz"


def test_the_same_table_is_run_against_the_repo_matcher_and_the_gap_is_pinned() -> None:
    """The one disagreement the independent table bought, kept visible.

    `integral.robots` is the matcher that decides real fetches. Running the
    spec-derived cases through it too costs nothing and found a **fail-open**:
    §2.2.2's own example table requires DISALLOW for
    `/foo/bar?baz=https://foo.bar` under a rule written in the encoded form, and
    `robots.allows_text` returns True.

    Fixing that is not T120's job — T120 replaces the SECOND reader — but
    shipping the artefact that proves it while recording the proof nowhere is
    exactly the "read and waved through" this repository's rules forbid. So the
    set is pinned: a second disagreement appearing fails here, by name, instead
    of a number going quietly from one to two.
    """
    measured = sr.measure()
    found = tuple(case["id"] for case in measured["repo_matcher_disagreement_cases"])

    assert found == sr.REPO_MATCHER_DISAGREEMENTS, (
        "the set of cases where the repo's primary matcher departs from RFC 9309 "
        f"changed: {found} vs the pinned {sr.REPO_MATCHER_DISAGREEMENTS}. A new "
        "entry is a new fail-open in `integral.robots`; an empty set means it was "
        "fixed and this pin should be emptied with it."
    )
    assert measured["repo_matcher_verdicts_against_the_rfc"] == len(found)
    # And the direction, asserted rather than assumed: every pinned case is one
    # the RFC refuses and the repo matcher allows. Vacuous while the tuple is
    # empty, which is the state T151 put it in — the assertions that carry the
    # weight now are the ones below.
    for case_id in sr.REPO_MATCHER_DISAGREEMENTS:
        case = next(c for c in cases.CASES if c.id == case_id)
        assert case.expected == cases.DISALLOW_VERDICT
        assert case.direction == cases.FAIL_OPEN_RISK
        assert sr.allows(case.robots_txt, case.agent, case.path) is False


def test_the_implementer_table_is_run_against_the_repo_matcher_too_and_pinned() -> None:
    """The population `repo_matcher_verdicts_against_the_rfc` does not reach.

    That metric is computed over `CASES` alone — deliberately, because those
    verdicts were written by a session that had seen neither matcher, and that
    is what a zero there is worth. `REGRESSION_CASES` is a table of RFC-derived
    verdicts too, and nothing ever ran `integral.robots` against it. So the
    metric read a truthful **0** while the primary matcher disagreed with seven
    rows of the other table, five of them fail-open — an honest number over an
    unmeasured population, which is the exact defect this module exists to
    catch, met one table over.

    Measuring it does not make it T151's gate: the two numbers say different
    things and are reported side by side. What this asserts is that the set is
    pinned by **id and by direction**, so a new disagreement fails here by name
    and a disappearing one has to be accounted for rather than absorbed.
    """
    measured = sr.measure()
    found = tuple(case["id"] for case in measured["repo_matcher_regression_disagreement_cases"])

    assert found == sr.REPO_MATCHER_REGRESSION_DISAGREEMENTS, (
        "the set of implementer-derived cases where `integral.robots` departs from "
        f"this table changed: {found} vs the pinned "
        f"{sr.REPO_MATCHER_REGRESSION_DISAGREEMENTS}"
    )
    assert measured["repo_matcher_verdicts_against_the_implementer_table"] == len(found)
    assert found, "an empty set here is the unmeasured state this pin replaced"

    by_id = {case.id: case for case in sr.REGRESSION_CASES}
    for record in measured["repo_matcher_regression_disagreement_cases"]:
        case = by_id[record["id"]]
        # The direction is recorded rather than assumed: five of these permit
        # what the table refuses and one refuses what it permits, and collapsing
        # them into a count would hide which kind grew.
        assert record["direction"] in {"fail_open", "fail_closed"}
        assert (record["direction"] == "fail_open") == (
            record["repo_matcher"] == cases.ALLOW_VERDICT
        )
        assert record["expected"] == case.expected


def test_the_divergence_between_the_two_matchers_is_pinned_and_live() -> None:
    """The reading disagreement itself, kept measured while it waits for a task.

    `integral.robots` emits a region-ambiguous run in BOTH canonical spellings,
    for allows as well as disallows, and scores precedence on whichever matched
    — reading (c). This module canonicalises the rule once and widens the
    TARGET instead, one-directionally, so an ambiguity is never resolved into a
    permission — reading (P). §2.2.2 returns Undefined for a contest involving a
    wildcard rule, so its text chooses neither, and is un-silent that a crawler
    must choose one.

    Deferring that choice to a task is right; deferring it with **nothing
    observing the gap** is what this repository built LOW-confidence contested
    cases to avoid. So the archetype is committed, the reading this table takes
    is the fail-closed one, and both halves are asserted live: if either module
    moves, this fails rather than the divergence quietly closing or widening.
    """
    case = next(
        c for c in sr.REGRESSION_CASES if c.id == "wildcard_region_spelling_readings_diverge"
    )
    assert case.confidence == "LOW"
    assert "(P)" in case.why and "(c)" in case.why, "a contested row must name both readings"
    assert case.expected == cases.DISALLOW_VERDICT, "this table takes the fail-closed reading"

    # (P), here: the allow reaches no spelling this reader offers it.
    assert sr.allows(case.robots_txt, case.agent, case.path) is False
    # (c), there: it reaches the query and outweighs the disallow.
    assert robots.allows_text(case.robots_txt, case.agent, case.path) is True
    assert case.id in sr.REPO_MATCHER_REGRESSION_DISAGREEMENTS


def test_a_low_confidence_regression_row_states_its_argument() -> None:
    """The same rule `CONTESTED_CASES` applies to the independent table.

    A `LOW` with no argument behind it is not a case, it is a guess wearing a
    label — and the implementer-derived table has no `CONTESTED_CASES` list of
    its own, so nothing checked this side.
    """
    low = [case for case in sr.REGRESSION_CASES if case.confidence == "LOW"]
    assert low, "the divergence row is LOW; a table with none has lost it"
    for case in low:
        assert case.confidence_note.strip(), f"{case.id}: LOW with no argument behind it"


def test_the_regression_table_floor_tracks_the_table() -> None:
    """A pin over a table that may silently shrink is not a pin.

    `REPO_MATCHER_REGRESSION_DISAGREEMENTS` names seven rows of
    `REGRESSION_CASES`; deleting those rows empties the set and satisfies the
    pin. The floor is what stops that, and it sat at 6 while the table carried
    18 — a floor that could not catch a table losing two thirds of itself.
    """
    assert len(sr.REGRESSION_CASES) >= sr.REGRESSION_CASES_AT_LEAST
    assert len(sr.REPO_MATCHER_REGRESSION_DISAGREEMENTS) <= sr.REGRESSION_CASES_AT_LEAST
    ids = {case.id for case in sr.REGRESSION_CASES}
    for case_id in sr.REPO_MATCHER_REGRESSION_DISAGREEMENTS:
        assert case_id in ids, f"{case_id} is pinned but no longer in the table"


def test_the_nine_cases_t151_closed_are_still_refused_by_the_repo_matcher() -> None:
    """An empty pin is only evidence if the cases that filled it still run.

    `REPO_MATCHER_DISAGREEMENTS` emptying is the shape of both "the fail-open was
    fixed" and "the nine cases were deleted", and the assertion above cannot tell
    those apart: it compares a measurement over the table against a tuple, and
    removing a row from the table satisfies it too. So the nine are named
    separately and re-run here through `integral.robots` itself.

    Each was fail-OPEN — RFC 9309 §2.2.2 requires the reserved octets they carry
    to be percent-encoded before comparison, in the path as well as the query, so
    the rule and the request are two spellings of one URI and the rule refuses.
    `integral.robots` answered ALLOW for all nine until T151 replaced
    `_CHUNK_SAFE` with a per-region reading of RFC 3986's `reserved` production.
    """
    assert len(sr.REPO_MATCHER_CASES_CLOSED_BY_T151) == 9
    for case_id in sr.REPO_MATCHER_CASES_CLOSED_BY_T151:
        case = next(c for c in cases.CASES if c.id == case_id)
        assert case.expected == cases.DISALLOW_VERDICT, case_id
        assert case.direction == cases.FAIL_OPEN_RISK, case_id
        assert robots.allows_text(case.robots_txt, case.agent, case.path) is False, case_id


def test_a_rule_reaching_the_query_through_a_wildcard_still_matches() -> None:
    """A rule must not depend on how its author happened to spell it.

    `canonical` decides which octets are "query data" from a literal `?`, and a
    rule can reach the query through a wildcard instead — so
    `Disallow: /*http://` was canonicalised as path octets (literal `:` and
    `//`) while the target's were encoded, and the rule matched nothing.
    `Disallow: /*?*http://` — the same intent, differently spelled — worked.
    The fail-open one was the shorter and more natural of the two.

    Found by the independent pre-PR review; no case in the spec table has a
    wildcard spanning the `?`, so the gate was green over it. Implementer-derived
    and labelled as such, which is why it lives here and not in the case table.
    """
    document = "User-agent: *\nDisallow: /*http://\n"
    equivalent = "User-agent: *\nDisallow: /*?*http://\n"
    target = "/out?url=http://evil.com"

    assert sr.allows(document, AGENT, target) is False
    assert sr.allows(equivalent, AGENT, target) is False
    # The encoded spelling of the same request is refused by both, too.
    assert sr.allows(document, AGENT, "/out?url=http%3A%2F%2Fevil.com") is False
    # And a path the rule genuinely does not cover is still allowed — the fix
    # widens which spellings match, never which rules exist.
    assert sr.allows(document, AGENT, "/out?url=ftp://example.com") is True


def test_both_query_spellings_are_offered_and_a_pathless_target_has_one() -> None:
    """`spellings` differs only in the query, so a plain path yields one form."""
    assert sr.spellings("/a/b") == (sr.canonical("/a/b"),)
    assert len(sr.spellings("/out?url=http://x")) == 2
    # `%2F` in a PATH is never resolved to a separator in either spelling: that
    # is the fail-open case 29 guards, and it is unaffected by the query rule.
    assert all("%2F" in spelling for spelling in sr.spellings("/a%2Fb"))


def test_the_contested_readings_are_recorded_by_name() -> None:
    """A LOW-confidence row gates, and the fact that it does is written down.

    The deriving session marked five cases as ones RFC 9309's text does not
    settle. They gate like any other — each is the fail-closed reading of its
    ambiguity — but a future session whose correct reader fails exactly these
    needs to find out that it has met a reading disagreement rather than a bug.
    """
    assert set(sr.CONTESTED_CASES) == {case.id for case in cases.CASES if case.confidence == "LOW"}
    assert sr.CONTESTED_CASES, "a table with no contested rows is not this table"
    assert sr.measure()["contested_readings_gating"] == list(sr.CONTESTED_CASES)
    for case_id in sr.CONTESTED_CASES:
        case = next(c for c in cases.CASES if c.id == case_id)
        assert case.confidence_note.strip(), f"{case_id}: LOW with no argument behind it"


def test_a_hostile_pattern_cannot_hang_the_matcher() -> None:
    """robots.txt comes from a third party, so its cost must not be theirs to set.

    The obvious implementation compiles `*` to `.*` and calls `re.match`. It is
    correct on every case in the table and it backtracks exponentially: measured
    on this module's own earlier regex version, fourteen wildcards against a
    sixty-character path did not finish in two minutes. A permission check that
    never returns is one that never says no.
    """
    document = "User-agent: *\nDisallow: /" + "a*" * 200 + "z\n"
    target = "/" + "a" * 5000

    start = time.monotonic()
    assert sr.allows(document, AGENT, target) is True
    assert time.monotonic() - start < 1.0, "the matcher is backtracking again"


def test_main_returns_one_on_a_misread_and_three_under_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two exit codes the acceptance gate names, asserted on `_main` itself.

    The gate block states the contract: the run "must **return 1** on any
    misread case and **return 3** — `unmeasured`, not a pass — when the fixture
    table is under its floor, so a zero over an empty table is never a pass."
    Those codes are what `make evidence` reads: a 3 is recorded and the run
    continues, a 1 stops it.

    Until the pre-PR review said so, nothing here ran `_main` over anything but
    the healthy table. Replacing both `return 1` and `return 3` with `return 0`
    left the whole suite green — the one mechanism that makes a misread stop the
    evidence run, and the one that stops an under-floor table reading as a pass,
    were both silently removable. The sibling test above is *named* for the exit
    code and asserted the misread count instead, which is exactly the gap
    CLAUDE.md's "a green gate is necessary and is not sufficient" describes.
    """
    # 0 — the healthy table, so the three codes are told apart rather than one
    # of them being reachable by everything.
    assert sr._main([str(tmp_path / "healthy.json")]) == 0

    # 1 — a table the reader misreads. The `expected` is flipped, so the reader
    # is right and the table is wrong; what is under test is the exit code, and
    # `measure` cannot tell which side of a disagreement is at fault.
    wrong = cases.CASES[0]
    flipped = (
        cases.ALLOW_VERDICT if wrong.expected == cases.DISALLOW_VERDICT else cases.DISALLOW_VERDICT
    )
    misreading = (
        cases.Case(
            id=wrong.id,
            robots_txt=wrong.robots_txt,
            agent=wrong.agent,
            path=wrong.path,
            expected=flipped,
            section=wrong.section,
            why=wrong.why,
            direction=wrong.direction,
        ),
        *cases.CASES[1:],
    )
    monkeypatch.setattr(sr, "CASES", misreading)
    target = tmp_path / "misread.json"
    assert sr._main([str(target)]) == 1
    assert json.loads(target.read_text())["second_reader_verdicts_misread"] == 1

    # 3 — a table under its floor. Not a pass and not a fail: `make evidence`
    # records it and carries on, which is only safe while it cannot be confused
    # with the 0 above.
    monkeypatch.setattr(sr, "CASES", cases.CASES[:2])
    under = tmp_path / "under.json"
    assert sr._main([str(under)]) == 3
    assert json.loads(under.read_text())["gate_status"] == "unmeasured"
    assert json.loads(under.read_text())["second_reader_verdicts_misread"] == 0


def test_a_widened_spelling_never_turns_a_refusal_into_a_permission() -> None:
    """The one-directional widening, asserted as the property rather than by case.

    `spellings` exists because a rule reaching the query through a wildcard
    cannot be canonicalised positionally, and the extra spellings resolve that
    ambiguity. Resolving it in favour of an `Allow` is how a `Disallow` stops
    deciding — so the extra spellings go to `Disallow` patterns only, and this
    asserts that directly on both witnesses the review produced.
    """
    for document, target in (
        ("User-agent: *\nDisallow: /jobs\nAllow: /*/apply\n", "/jobs?next=%2Fapply"),
        ("User-agent: *\nDisallow: /x\nAllow: /*http://\n", "/x?u=http%3A%2F%2Fy"),
    ):
        without_allow = "\n".join(
            line for line in document.splitlines() if not line.startswith("Allow:")
        )
        # The disallow decides the path on its own …
        assert sr.allows(without_allow, AGENT, target) is False
        # … and adding an `Allow` that only a widened spelling reaches must not
        # take that decision away from it.
        assert sr.allows(document, AGENT, target) is False
