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
import re
import unicodedata
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


@pytest.mark.parametrize(
    "who",
    ["NuncaEsLupus", "NUNCAESLUPUS", " nuncaeslupus ", "\tnuncaeslupus\n", "  NuncaEsLupus  "],
)
def test_the_pr_author_cannot_review_their_own_head_under_another_spelling(who: str) -> None:
    """#408 round 2, the serious half: the identity relation, not its blankness.

    Round 1 normalised the author for emptiness (`comment.author.strip()`) and
    left `comment.author == pr.author` raw, two lines below. GitHub logins are
    case-insensitive, so `NuncaEsLupus` is `nuncaeslupus` — and the implementer
    could clear their own PR by holding shift, which CLAUDE.md forbids by name
    (*"the implementer never signs it off"*). Padding is the same account for
    the same reason. Fail-open: these all answered `allowed/0`.
    """
    pr = _pr(author="nuncaeslupus", comments=(_report(author=who),))
    verdict = rr.read(pr)
    assert (verdict.state, verdict.code) == (rr.BLOCKED, 2)
    assert verdict.merge_may_proceed is False


@pytest.mark.parametrize("who", ["​", "﻿", "\x00", "...", "​﻿ \x00"])
def test_an_author_that_survives_strip_but_names_nobody_is_still_unresolved(who: str) -> None:
    """`str.strip()` removes none of U+200B, U+FEFF or `\\x00`.

    So each of these is a *non-blank* string that differs from every login,
    which round 1's `strip()` guard let through and the raw `==` then read as
    "somebody else". `resolve_identity` deletes invisible characters and then
    requires an alphanumeric to remain, so an author made only of them — and a
    punctuation-only one, which names no account a human can check — resolves to
    `None` rather than to a second reader.
    """
    verdict = rr.read(_pr(comments=(_report(author=who),)))
    assert (verdict.state, verdict.code) == (rr.UNRESOLVABLE, 2)
    assert verdict.merge_may_proceed is False


def test_one_helper_answers_both_questions_the_module_asks_about_an_author() -> None:
    """The root cause was two normalisation rules for one relation (#408 rd 2)."""
    assert rr.resolve_identity("NuncaEsLupus") == "nuncaeslupus"
    assert rr.resolve_identity("  nuncaeslupus\t") == "nuncaeslupus"
    for nobody in ("", "   ", "​", "﻿", "\x00", "...", "---", "@", "()"):
        assert rr.resolve_identity(nobody) is None
    # A real second reader still resolves, and to something that is not the author.
    assert rr.resolve_identity("reviewer") != rr.resolve_identity("author")


def test_the_alphabet_is_a_validator_and_never_a_filter() -> None:
    """#408 round 5, stated as the property rather than as its instances.

    Round 4 applied the login alphabet as a **deletion filter**, which enumerates
    by complement: it strips only decoration made of characters outside
    `[A-Za-z0-9-]`, so decoration made of characters *inside* it is welded on and
    the weld is a different identity. The rule is now that the whole string must
    match `_GITHUB_LOGIN`, so a string that is not a login resolves to nobody
    instead of being repaired into somebody.

    The property, in one line: for every input, `resolve_identity` returns either
    `None` or **the input itself**, up to outer whitespace and case. Nothing else
    is reachable, so no decoration can be manufactured into an identity.
    """
    for raw in (
        "nuncaeslupus (OWNER)",
        "nuncaeslupus[bot]",
        "nuncaeslupus - maintainer",
        "\u00b2",
        "\u2167",
        "\u2122",
        "\u24b6",
        "\u00bd",
        "\u338f",
        "stra\u00dfe",
        "\u212akelvin",
        "nuncaeslupus--x",
        "-nuncaeslupus",
        "nuncaeslupus-",
    ):
        assert rr.resolve_identity(raw) is None, raw
    for raw in ("nuncaeslupus", "NuncaEsLupus", "  reviewer\n", "nunca-es-lupus", "2ndreader"):
        resolved = rr.resolve_identity(raw)
        assert resolved == raw.strip().casefold(), raw


@pytest.mark.parametrize(
    "spelling",
    [
        # round 4 — decoration made of characters OUTSIDE the login alphabet
        "@nuncaeslupus",
        "nuncaeslupus.",
        "(nuncaeslupus)",
        "nuncaeslupus:",
        "**nuncaeslupus**",
        "\uff20nuncaeslupus",  # FULLWIDTH COMMERCIAL AT
        "\uff4e\uff55\uff4e\uff43\uff41\uff45\uff53\uff4c\uff55\uff50\uff55\uff53",  # fullwidth
        "nunca es lupus",
        "- nuncaeslupus",
        "  @NuncaEsLupus.\t",
        # round 5 — decoration WELDED on out of characters inside the alphabet
        "nuncaeslupus (OWNER)",
        "nuncaeslupus (MEMBER)",
        "nuncaeslupus[bot]",
        "nuncaeslupus - maintainer",
        "nuncaeslupus, COLLABORATOR",
        # round 5 — a single character NFKC rewrote into a whole other identity
        "\u00b2",
        "\u2167",
        "\u2122",
        "\u24b6",
        "\u00bd",
        "\u338f",
    ],
)
def test_a_decorated_author_never_clears_the_head(spelling: str) -> None:
    """Every spelling that cleared `nuncaeslupus`'s own PR, at the COMMENT side.

    Each of these was measured through the shipped `check` CLI on the head that
    introduced it — exit 0, `merge_may_proceed: true`. The assertion is written
    as *never a pass* rather than as *resolves to the author*, because that is
    the invariant the whole ladder shares and the two rounds answer it
    differently: round 4 repaired the spelling into the author's identity
    (`blocked/2`), and round 5 refuses to build an identity out of a string that
    is not a login (`unresolvable/2`). Same exit code, same refusal.
    """
    verdict = rr.read(_pr(author="nuncaeslupus", comments=(_report(author=spelling),)))
    assert verdict.merge_may_proceed is False, spelling
    assert verdict.code == 2, spelling


@pytest.mark.parametrize(
    "spelling",
    [
        "nuncaeslupus (OWNER)",
        "nuncaeslupus[bot]",
        "nuncaeslupus - maintainer",
        "\u2122",
        "\uff4e\uff55\uff4e\uff43\uff41\uff45\uff53\uff4c\uff55\uff50\uff55\uff53",
    ],
)
def test_a_decorated_pr_author_never_clears_its_own_head(spelling: str) -> None:
    """The control class no round had, and structurally why four rounds each fell short.

    Every earlier round decorated the **comment** side only. `resolve_identity`
    is reached through `pr.author` too, and a defect there is the more dangerous
    of the two: it makes the implementer resolve to somebody who is not
    themselves, so their own marker reads as a second reader's. Three of these
    passed at exit 0 on the round-4 head with the comment written by the plain
    `nuncaeslupus`.
    """
    verdict = rr.read(_pr(author=spelling, comments=(_report(author="nuncaeslupus"),)))
    assert verdict.merge_may_proceed is False, spelling
    assert verdict.code == 2, spelling


def test_a_pr_author_written_in_another_case_is_still_the_same_account() -> None:
    """The author-side mirror of round 2 — casefold must survive the validator."""
    verdict = rr.read(_pr(author="NuncaEsLupus", comments=(_report(author="nuncaeslupus"),)))
    assert (verdict.state, verdict.code) == (rr.BLOCKED, 2)


def test_normalisation_never_splits_one_identity_into_two() -> None:
    """Round 4's safety argument, and the case that falsifies it.

    It claimed the pipeline "only ever *merges* strings … and none is ever split
    into two", so every collision was fail-closed. Deletion shortens and NFKC
    lengthens, so it did both: `resolve_identity("stra\u00dfe")` returned
    `strae`, not `strasse`. **Every split is fail-open** — it moves a writer away
    from the author and toward "somebody else". A validator cannot split: the
    only strings it maps onto a login are that login's own case variants.
    """
    for split_pair in (("stra\u00dfe", "strasse"), ("\u2167", "viii"), ("\u2122", "tm")):
        decorated, welded = split_pair
        assert rr.resolve_identity(decorated) is None
        assert rr.resolve_identity(decorated) != rr.resolve_identity(welded)
    # And the merge direction is exhausted by case, which GitHub itself merges.
    assert rr.resolve_identity("NUNCAESLUPUS") == rr.resolve_identity("nuncaeslupus")


def test_the_rule_never_merges_two_real_logins() -> None:
    """The hyphen is IN the login grammar, so hyphenation is not decoration.

    This is the control on the fix rather than on the defect, and it is the one
    that says the validator has not gone too far: `nunca-es-lupus` is a
    well-formed login and a different account, so it still clears
    `nuncaeslupus`'s PR at exit 0. A rule strict enough to refuse it would
    refuse real second readers, which fails in the direction that costs a read
    but is still a rule nobody would keep.
    """
    assert rr.resolve_identity("nunca-es-lupus") != rr.resolve_identity("nuncaeslupus")
    verdict = rr.read(_pr(author="nuncaeslupus", comments=(_report(author="nunca-es-lupus"),)))
    assert (verdict.state, verdict.code) == (rr.ALLOWED, 0)


def test_every_identity_that_resolves_is_a_well_formed_login() -> None:
    """The reviewer's `\u00b2` / `\u2167` nuance, settled by refusing them outright.

    Round 3 decided "names somebody" with `str.isalnum()`, which is Unicode-wide,
    so `\u00b2` and `\u2167` resolved to themselves. Round 4 NFKC-folded them into
    `2` and `viii` — still identities no account bears, and still enough to clear
    a head at exit 0, which is what round 5 measured. The output looking like a
    login was never the question; the question is whether normalisation had to
    rewrite the input to get there. So neither resolves at all now, and every
    identity that does resolve is the string GitHub itself would accept.
    """
    for nobody in ("\u00b2", "\u2167", "@nuncaeslupus", "- nunca-es-lupus -", "\u2122"):
        assert rr.resolve_identity(nobody) is None, nobody
    for real in ("reviewer", "nunca-es-lupus", "2ndreader", "NuncaEsLupus"):
        resolved = rr.resolve_identity(real)
        assert resolved is not None
        assert re.fullmatch(r"[a-z0-9](?:-?[a-z0-9])*", resolved), resolved


# --------------------------------------------------------------------------
# The regression ladder
# --------------------------------------------------------------------------
#
# #408 produced five fixes for one class, and each of the first four was
# pushed behind a green gate. What no round had was a check that the NEXT
# round's rule still refuses what this round's refused — so a sixth fix could
# close round 5's spellings and silently reopen round 3's, exactly as round 4's
# NFKC fold reopened the `isalnum()` hole it was meant to close.
#
# So each historical implementation is kept here and re-run against the CURRENT
# controls. A rung that scores 0 is a rung whose own defect nothing is watching
# any more. This is the one test that has to be updated by every future round:
# add your predecessor to the ladder.


def _round_0(raw: str) -> str | None:
    """No normalisation at all: the identity comparison was on raw strings."""
    return raw


def _round_1(raw: str) -> str | None:
    """`.strip()` decided blankness; the comparison two lines below stayed raw."""
    return raw if raw.strip() else None


_INVISIBLE = {"Cc", "Cf", "Cs", "Zl", "Zp"}


def _round_3(raw: str) -> str | None:
    """Delete Unicode Cc/Cf/Cs/Zl/Zp, strip, casefold; `isalnum()` meant 'names somebody'."""
    kept = "".join(c for c in raw if unicodedata.category(c) not in _INVISIBLE).strip()
    if not any(c.isalnum() for c in kept):
        return None
    return kept.casefold()


def _round_4(raw: str) -> str | None:
    """NFKC-fold, delete everything outside `[A-Za-z0-9-]`, trim hyphens, casefold."""
    kept = re.sub(r"[^A-Za-z0-9-]", "", unicodedata.normalize("NFKC", raw)).strip("-")
    if not kept:
        return None
    return kept.casefold()


def _alphabet_as_a_filter(raw: str) -> str | None:
    """The round-5 defect in one line: the same alphabet, applied as a deletion."""
    kept = re.sub(r"[^A-Za-z0-9-]", "", raw).strip("-")
    return kept.casefold() if kept else None


def _validator_without_casefold(raw: str) -> str | None:
    """Mutant: drop the one merge GitHub's own case-insensitivity licenses."""
    candidate = raw.strip()
    return candidate if rr._GITHUB_LOGIN.fullmatch(candidate) else None


def _validator_without_strip(raw: str) -> str | None:
    """Mutant: drop the outer-whitespace trim a capture's framing needs."""
    return raw.casefold() if rr._GITHUB_LOGIN.fullmatch(raw) else None


LADDER: tuple[tuple[str, object], ...] = (
    ("round 0 — no normalisation", _round_0),
    ("round 1/2 — .strip() for blankness, raw compare", _round_1),
    ("round 3 — delete invisibles, isalnum()", _round_3),
    ("round 4 — NFKC then delete outside the alphabet", _round_4),
    ("mutant — the alphabet as a filter, not a validator", _alphabet_as_a_filter),
    ("mutant — the validator without casefold", _validator_without_casefold),
    ("mutant — the validator without strip", _validator_without_strip),
)


@pytest.mark.parametrize("label,implementation", LADDER, ids=[row[0] for row in LADDER])
def test_every_earlier_rule_still_reddens_its_own_controls(
    label: str, implementation: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No rung may score a clean zero — that is what a silently reopened hole looks like."""
    monkeypatch.setattr(rr, "resolve_identity", implementation)
    record = rr.measure()
    assert record["merges_allowed_without_a_review_of_the_head"] > 0, (
        f"{label} scores 0 against today's controls, so nothing is watching the defect "
        "it introduced — a future fix could reintroduce it behind a green gate"
    )


def test_the_shipped_rule_is_the_baseline_and_scores_zero() -> None:
    """The bottom of the ladder. Every rung above it is measured against this."""
    assert rr.measure()["merges_allowed_without_a_review_of_the_head"] == 0


def test_the_ladder_is_measured_against_a_control_set_that_only_grows() -> None:
    """CLAUDE.md: *"the measured denominator must rise"* — the floors are how.

    A ladder over a shrinking control set proves nothing: deleting the controls
    a rung reddens makes that rung green. The floors are the guard, so they are
    asserted here beside the ladder rather than only inside `measure`.
    """
    assert len(rr.CONTROLS) >= rr.MINIMUM_PRS_EVALUATED
    record = rr.measure()
    assert record["prs_evaluated_at_least"] == rr.MINIMUM_PRS_EVALUATED
    assert record["second_reader_reports_found_at_least"] == rr.MINIMUM_REPORTS_FOUND
    assert record["floor_breaches"] == []


def test_a_pr_author_that_only_looks_non_blank_is_unresolvable() -> None:
    """The blankness guard on the PR's own author goes through the same helper."""
    for who in ("​", "\x00", "..."):
        verdict = rr.read(_pr(author=who, comments=(_report(),)))
        assert (verdict.state, verdict.code) == (rr.UNRESOLVABLE, 2)


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
