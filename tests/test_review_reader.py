"""D-28: a merge waits for a second-reader report on the head commit.

The named gate test is `test_no_merge_is_allowed_without_a_review_of_the_head`.
Everything else guards a direction the reader could fail in, and the ones that
matter most are the fail-open ones: a report that is absent, stale, written by
the PR's own author, or made of prose must never resolve to "may merge".

Nothing here reaches the network. The states are constructed, which is what
makes the gate say the same thing on a laptop, offline, and in a session whose
REST channel answers 403.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral import review_reader as rr

HEAD = "d4a3b21c0f9e8d7c6b5a49382716f5e4d3c2b1a0"
OLDER = "0a1b2c3d4e5f61728394a5b6c7d8e9f012345678"
CODE = ("src/integral/thing.py",)
DOCS = ("arsenal/session/handover.md",)


def _pr(**kwargs: object) -> rr.PullRequest:
    base: dict[str, object] = {
        "number": 1,
        "author": "author",
        "head_sha": HEAD,
        "files": CODE,
        "comments": (),
    }
    base.update(kwargs)
    return rr.PullRequest(**base)  # type: ignore[arg-type]


def _report(author: str = "reviewer", head: str = HEAD, verdict: str = "CLEAR") -> rr.Comment:
    return rr.Comment(author, f"Findings below.\n\n{rr.marker_line(head, verdict)}")


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------


def test_no_merge_is_allowed_without_a_review_of_the_head() -> None:
    """D-28's gate: every constructed state gets the verdict the rule requires."""
    record = rr.measure()
    assert record["review_reader_status"] == "measured"
    assert record["merges_allowed_without_a_review_of_the_head"] == 0, record[
        "readings_that_allow_a_merge_without_a_review"
    ]


def test_the_record_carries_both_floors_and_the_exclusion_counter() -> None:
    record = rr.measure()
    assert record["prs_evaluated_at_least"] == rr.MINIMUM_PRS_EVALUATED
    assert record["second_reader_reports_found_at_least"] == rr.MINIMUM_REPORTS_FOUND
    # An exclusion with no counter is silence: the docs-only control is visible.
    assert record["docs_only_prs_excluded"] == 1
    assert record["floor_breaches"] == []


def test_every_control_cites_the_text_its_expectation_comes_from() -> None:
    """A verdict argued from what the code does is the circularity to avoid."""
    for reading in rr.measure()["readings"]:
        assert reading["derived_from"].strip(), reading


# --------------------------------------------------------------------------
# The fail-open directions
# --------------------------------------------------------------------------


def test_a_second_reader_clearing_this_head_allows_the_merge() -> None:
    verdict = rr.read(_pr(comments=(_report(),)))
    assert (verdict.state, verdict.code) == (rr.ALLOWED, 0)
    assert verdict.merge_may_proceed


def test_no_report_at_all_is_not_a_pass() -> None:
    verdict = rr.read(_pr())
    assert (verdict.state, verdict.code) == (rr.BLOCKED, 2)
    assert not verdict.merge_may_proceed


def test_a_report_on_a_superseded_commit_is_stale_not_absent_and_never_allowed() -> None:
    verdict = rr.read(_pr(comments=(_report(head=OLDER),)))
    assert (verdict.state, verdict.code) == (rr.BLOCKED, 3)


def test_the_pr_author_cannot_review_their_own_head() -> None:
    verdict = rr.read(_pr(comments=(_report(author="author"),)))
    assert (verdict.state, verdict.code) == (rr.BLOCKED, 2)


@pytest.mark.parametrize("who", ["", " ", "   \t "])
def test_a_marker_from_an_unresolved_author_is_not_a_second_reader(who: str) -> None:
    """A blank comment author is refused exactly as a blank PR author is.

    `read` decides "somebody else" from the single relation
    `comment.author == pr.author`, and that relation is vacuously false for an
    identity that never resolved — so without this guard an unattributed marker
    clears the PR (`allowed/0`, *"a second reader () cleared …"*). Approval read
    out of an absence is the shape the module exists to refuse, and it is the
    fail-open direction: the unknown writer may be the implementer.
    """
    verdict = rr.read(_pr(comments=(_report(author=who),)))
    assert (verdict.state, verdict.code) == (rr.UNRESOLVABLE, 2)
    assert verdict.merge_may_proceed is False


def test_an_unresolved_author_on_a_comment_carrying_no_marker_changes_nothing() -> None:
    """The guard fires on markers, not on every comment a capture happens to hold."""
    verdict = rr.read(_pr(comments=(rr.Comment("", "+1"), _report())))
    assert (verdict.state, verdict.code) == (rr.ALLOWED, 0)


def test_the_author_quoting_another_readers_marker_is_still_a_self_review() -> None:
    quoted = rr.Comment("author", f"They wrote:\n\n> {rr.marker_line(HEAD)}")
    verdict = rr.read(_pr(comments=(quoted,)))
    assert (verdict.state, verdict.code) == (rr.BLOCKED, 2)


@pytest.mark.parametrize(
    "body",
    [
        "Reviewed. LGTM, no findings.",
        "Review rate limited. Please try again later.",
        "Review skipped: draft pull request",
        "arsenal-second-reader: looks fine to me",
        f"arsenal-second-reader: head={HEAD[:12]} verdict=CLEAR",
        f"arsenal-second-reader: head={HEAD} verdict=YES",
    ],
)
def test_a_comment_without_a_well_formed_marker_is_not_a_report(body: str) -> None:
    """The marker is not free text, and an abbreviated sha binds nothing."""
    verdict = rr.read(_pr(comments=(rr.Comment("reviewer", body),)))
    assert (verdict.state, verdict.code) == (rr.BLOCKED, 2), body


def test_a_block_on_the_head_blocks() -> None:
    verdict = rr.read(_pr(comments=(_report(verdict="BLOCK"),)))
    assert (verdict.state, verdict.code) == (rr.BLOCKED, 1)


def test_a_block_beats_a_clear_from_another_reader() -> None:
    verdict = rr.read(_pr(comments=(_report(), _report(author="other", verdict="BLOCK"))))
    assert (verdict.state, verdict.code) == (rr.BLOCKED, 1)


# --------------------------------------------------------------------------
# The docs-only exemption, and its counter
# --------------------------------------------------------------------------


def test_a_docs_only_pr_is_exempt() -> None:
    verdict = rr.read(_pr(files=DOCS))
    assert (verdict.state, verdict.code) == (rr.EXEMPT, 0)


def test_the_exemption_does_not_survive_an_objection() -> None:
    verdict = rr.read(_pr(files=DOCS, comments=(_report(verdict="BLOCK"),)))
    assert (verdict.state, verdict.code) == (rr.BLOCKED, 1)


@pytest.mark.parametrize(
    "files",
    [
        ("README.md", "src/integral/thing.py"),
        ("status/evidence/D28.json",),
        ("Makefile",),
        (".github/workflows/ci.yml",),
    ],
)
def test_a_pr_that_is_not_all_markdown_is_not_docs_only(files: tuple[str, ...]) -> None:
    assert not rr.is_docs_only(files)
    assert rr.read(_pr(files=files)).state == rr.BLOCKED


def test_an_empty_file_list_is_not_vacuously_docs_only() -> None:
    """Vacuous truth here would exempt a PR whose files simply failed to resolve."""
    assert not rr.is_docs_only(())
    verdict = rr.read(_pr(files=()))
    assert (verdict.state, verdict.code) == (rr.UNRESOLVABLE, 2)


def test_a_head_that_does_not_resolve_is_unresolvable_not_allowed() -> None:
    for head in ("", "HEAD", "not-a-sha", HEAD[:39]):
        verdict = rr.read(_pr(head_sha=head, comments=(_report(),)))
        assert (verdict.state, verdict.code) == (rr.UNRESOLVABLE, 2), head


def test_an_uppercase_sha_still_binds_to_the_same_commit() -> None:
    marker = rr.Comment("reviewer", f"{rr.MARKER_NAME}: head={HEAD.upper()} verdict=CLEAR")
    assert rr.read(_pr(comments=(marker,))).state == rr.ALLOWED


# --------------------------------------------------------------------------
# Vacuity, floors, exit codes
# --------------------------------------------------------------------------


def test_a_scan_over_zero_prs_reports_unmeasured_and_never_a_clean_zero() -> None:
    record = rr.measure(controls=())
    assert record["review_reader_status"] == "unmeasured"
    assert record["merges_allowed_without_a_review_of_the_head"] == -1
    assert record["floor_breaches"]
    assert rr.exit_code_for(record) == 1


def test_a_breached_floor_records_what_was_observed_not_the_claim() -> None:
    """T111: `record()` must not write a floor claim the run never met."""
    record = rr.measure(controls=rr.CONTROLS[:2])
    assert record["prs_evaluated_at_least"] == 2
    assert record["review_reader_status"] == "unmeasured"
    assert any("prs_evaluated_at_least" in breach for breach in record["floor_breaches"])


def test_a_marker_reader_that_matches_nothing_breaches_the_reports_floor() -> None:
    """A dead parser finds no reports — and so finds no merges allowed either."""
    unreviewed = tuple(
        (name, rr.PullRequest(pr.number, pr.author, pr.head_sha, pr.files, ()), state, code, why)
        for name, pr, state, code, why in rr.CONTROLS
    )
    record = rr.measure(controls=unreviewed)
    assert record["review_reader_status"] == "unmeasured"
    assert record["merges_allowed_without_a_review_of_the_head"] == -1
    assert any("second_reader_reports_found_at_least" in b for b in record["floor_breaches"])


def test_an_unmeasured_reading_exits_1_and_never_3() -> None:
    """`Makefile:58-70` records 3 and continues — the fail-open shape (#297)."""
    assert rr.exit_code_for(rr.measure(controls=())) == 1
    assert rr.exit_code_for(rr.measure(controls=())) != 3


def test_the_reader_must_be_named_somewhere_a_session_reads(tmp_path: Path) -> None:
    silent = tmp_path / "CLAUDE.md"
    silent.write_text("nothing about the review half here\n", encoding="utf-8")
    record = rr.measure(claude_md=silent)
    assert record["reader_named_in_claude_md"] is False
    assert record["merges_allowed_without_a_review_of_the_head"] == 1
    assert rr.exit_code_for(record) == 1


def test_the_repository_tells_sessions_to_run_it() -> None:
    assert rr.measure()["reader_named_in_claude_md"] is True


def test_write_evidence_records_exactly_what_was_measured(tmp_path: Path) -> None:
    path = tmp_path / "D28.json"
    written = rr.write_evidence(path)
    assert json.loads(path.read_text(encoding="utf-8")) == written
    assert written["merges_allowed_without_a_review_of_the_head"] == 0


# --------------------------------------------------------------------------
# The marker writer
# --------------------------------------------------------------------------


def test_the_emitted_marker_is_what_the_reader_parses() -> None:
    line = rr.marker_line(HEAD)
    assert rr.markers(line) == [(HEAD, "CLEAR")]


@pytest.mark.parametrize("head", ["", HEAD[:12], "HEAD", "z" * 40])
def test_emit_refuses_a_sha_that_binds_nothing(head: str) -> None:
    with pytest.raises(ValueError):
        rr.marker_line(head)
    assert rr._main(["emit", "--head", head]) == 2


def test_emit_prints_a_marker_for_a_real_sha(capsys: pytest.CaptureFixture[str]) -> None:
    assert rr._main(["emit", "--head", HEAD.upper()]) == 0
    assert capsys.readouterr().out.strip() == rr.marker_line(HEAD)


# --------------------------------------------------------------------------
# The `check` subcommand — the reader a merge actually consults
# --------------------------------------------------------------------------


def _capture(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "pr.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_check_clears_a_pr_whose_head_a_second_reader_read(tmp_path: Path) -> None:
    state = _capture(
        tmp_path,
        {
            "number": 313,
            "author": "author",
            "head_sha": HEAD,
            "files": list(CODE),
            "comments": [{"author": "reviewer", "body": rr.marker_line(HEAD)}],
        },
    )
    assert rr._main(["check", str(state)]) == 0


@pytest.mark.parametrize(
    ("comments", "expected"),
    [
        ([], 2),
        ([{"author": "reviewer", "body": "Reviewed, looks good"}], 2),
        ([{"author": "author", "body": rr.marker_line(HEAD)}], 2),
        ([{"author": "reviewer", "body": rr.marker_line(OLDER)}], 3),
        ([{"author": "reviewer", "body": rr.marker_line(HEAD, "BLOCK")}], 1),
    ],
)
def test_check_exit_codes_distinguish_absent_stale_and_blocked(
    tmp_path: Path, comments: list[dict[str, str]], expected: int
) -> None:
    state = _capture(
        tmp_path,
        {
            "number": 313,
            "author": "author",
            "head_sha": HEAD,
            "files": list(CODE),
            "comments": comments,
        },
    )
    assert rr._main(["check", str(state)]) == expected


@pytest.mark.parametrize(
    "payload",
    [
        {"number": 1, "author": "author", "head_sha": HEAD, "files": list(CODE)},
        {"number": 1, "author": "author", "head_sha": HEAD, "files": list(CODE), "comments": "yes"},
        {"number": 1, "author": "author", "files": list(CODE), "comments": []},
        [1, 2, 3],
    ],
)
def test_a_capture_that_does_not_resolve_is_never_a_pass(tmp_path: Path, payload: object) -> None:
    assert rr._main(["check", str(_capture(tmp_path, payload))]) == 2


def test_an_unreadable_capture_is_never_a_pass(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    assert rr._main(["check", str(missing)]) == 2
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert rr._main(["check", str(broken)]) == 2
