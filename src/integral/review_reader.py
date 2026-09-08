"""D-28 — the review half of `merge-policy` gets a mechanical reader.

`merge-policy` is `after-ci-and-review`. T103 gave the **CI** half a reader:
`merge_policy.py` refuses to call a merge allowed while the latest `CI`
conclusion on `main` is not `success`. The **review** half had none. Nothing
computed whether a review happened; a session decided by looking, and what a
session looked at was a green tick that said `pass` when the reviewer was rate
limited and `pass` again when it had skipped a draft. Both render identically
in `--json statusCheckRollup`, so "reviewed and found nothing" and "never
looked at it" were the same colour.

The re-scope of 2026-09-04 changed who writes the review, not what has to be
true. CLAUDE.md's *"The review half of `merge-policy` is a second session, not
a bot"* defines it: **a session other than the implementer reads the PR and
reports on it; the implementer never signs it off; accepted findings are
committed as fixtures before merge; docs-only PRs are exempt.** This module is
that rule's reader, and the condition it makes checkable is the one the task
names:

    a merge must not proceed until a second-reader report exists for the
    HEAD COMMIT.

A review of an earlier tree is not a review of this one. That binding is what
#320 cost nine unworked findings to prove: the PR read as reviewed while its
only review object pointed at a superseded commit.

**The shape is `claude-arsenal/bin/adversarial_review.sh`'s, deliberately.**
That script already implements this discipline for the pre-PR gate — a receipt
bound to the digest of what was reviewed, `check` exiting 2 when there is no
review on record and 3 when the receipt is stale. Reusing its exit vocabulary
rather than inventing a second one means the two halves of "has this been read"
answer in one language:

    0  a second reader cleared THIS head (or the PR is docs-only and exempt)
    1  a second reader read this head and said BLOCK
    2  no report on record — NOT a pass, and never confused with one
    3  a report exists, but for another commit — stale

**A missing report must never read as a pass.** Every way this reader can fail
to find a report exits non-zero, and the evidence record writes `-1` into its
own gate key when it cannot measure, so a vacuous run fails `merges_allowed…
== 0` instead of satisfying it with a clean zero over nothing.

**The marker is not free text.** "Reviewed" in a comment body is what a report
looks like today, and a scan matching prose passes on a comment carrying the
word and fails on a thorough review that does not. The report ends with one
line, emitted by `python -m integral.review_reader emit --head <sha>`:

    arsenal-second-reader: head=<40-hex sha> verdict=CLEAR

Three properties are read off it and each is a way a report can fail to be one:

* **`head` must equal the PR's head commit.** A marker for another commit is
  stale, not absent — a distinction the exit codes keep.
* **The comment's author must not be the PR's author.** The implementer never
  signs it off; a marker the author quotes out of somebody else's report is
  still their own comment, and is refused. A **blank** author is refused for the
  same reason the PR's own blank author is: `author != pr.author` is vacuously
  true for an identity that never resolved, so the one relation this module
  reasons about would read an unknown writer as a second reader — approval out
  of an absence, the shape the whole module refuses.
* **`verdict=BLOCK` blocks**, including on a docs-only PR. Exemption applies to
  a PR nobody objected to, never over an objection somebody raised.

**The measurement is over constructed states, not over live GitHub.** The gate
must say the same thing offline, on a laptop with no token, and in a session
whose REST channel answers 403 — and a number that depends on which PRs happen
to be open on the night it runs is not a measurement of the reader. So
`CONTROLS` below are the states, each with the verdict the rule requires and
the section that requires it, and `merges_allowed_without_a_review_of_the_head`
counts the ones this reader gets wrong. A reader that has broken counts as a
violation, exactly as T103's policy controls do: the number moves when the
reader breaks and not only when a policy changes.

Both denominators are **floors** (T100): `prs_evaluated_at_least` and
`second_reader_reports_found_at_least` are asserted, not counted, so the record
does not drift with the control list. The second floor is the one that matters
most — it is what stops a marker parser that has stopped matching anything from
scoring a serene zero, because a reader that finds no reports also finds no
merges allowed without one.

`docs_only_prs_excluded` sits beside the numerator because **an exclusion with
no counter is silence**: a code PR misclassified as docs-only would merge unread
with nothing in the record to show for it.

A breach returns **1, never 3**. `Makefile:58-70` maps exit 3 to "unmeasured
(recorded)" and *continues*, which is the fail-open shape #297 recorded; this
module's unmeasured verdict has to stop `make evidence`, because "the reader
could not read anything" is precisely when a merge must not proceed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D28.json"
DEFAULT_CLAUDE_MD = _REPO_ROOT / "CLAUDE.md"

#: The marker's name. A report is a PR comment ending in a line of this shape;
#: nothing else counts as one.
MARKER_NAME = "arsenal-second-reader"

MARKER_RE = re.compile(
    rf"^[ \t>]*{MARKER_NAME}:[ \t]+head=(?P<head>[0-9a-fA-F]{{40}})[ \t]+"
    r"verdict=(?P<verdict>CLEAR|BLOCK)[ \t]*$",
    re.MULTILINE,
)

#: The module path a session is told to run. Named as a constant because the
#: record asserts CLAUDE.md still names it: a reader nobody is told to run stops
#: no merges, which is the "rule in prose that nothing reads" failure one layer
#: out. This is D-22's prose half applied to this gate — the one reading here
#: taken from text rather than from behaviour, and it is labelled as such.
MODULE_PATH = "integral.review_reader"

#: What a PR has to be for the docs-only exemption to apply: every changed path
#: ends in `.md`. Deliberately narrow. A wider rule (anything under `status/`,
#: anything not under `src/`) would exempt an evidence number or a workflow
#: change, and the cost of the two errors is not symmetric — a docs PR read by a
#: second session costs one read, a code PR exempted by mistake merges unread.
DOC_SUFFIXES: tuple[str, ...] = (".md",)

ALLOWED = "allowed"
BLOCKED = "blocked"
EXEMPT = "exempt"
UNRESOLVABLE = "unresolvable"

#: Floors, in `naming.MINIMUM_SCANNED` style (T100). Committed as the value the
#: code asserts rather than the count of the day, so the record is invariant
#: under adding a control.
MINIMUM_PRS_EVALUATED = 25
MINIMUM_REPORTS_FOUND = 2


@dataclass(frozen=True)
class Comment:
    """One PR comment: who wrote it, and what it says."""

    author: str
    body: str


@dataclass(frozen=True)
class PullRequest:
    """The state a merge decision is taken over.

    `files` is the list of paths the PR changes — needed because the docs-only
    exemption is a claim about them, and an empty list is *not* a docs-only PR
    but a state that could not be resolved.
    """

    number: int
    author: str
    head_sha: str
    files: tuple[str, ...] = ()
    comments: tuple[Comment, ...] = ()


@dataclass(frozen=True)
class Verdict:
    """What the reader concludes, and the exit code that says so.

    One object serves both callers — the evidence measurement and the `check`
    subcommand — because two mappings from the same states to the same answers
    drift, and the one that drifts is the one nobody runs.
    """

    state: str
    code: int
    reason: str
    #: The head-bound reports (by somebody other than the author) that were
    #: found on this PR, whatever they said.
    reports: tuple[Comment, ...] = field(default=())

    @property
    def merge_may_proceed(self) -> bool:
        return self.state in {ALLOWED, EXEMPT}


def markers(body: str) -> list[tuple[str, str]]:
    """Every `arsenal-second-reader:` marker in a comment body.

    Returns `(head, verdict)` pairs with the head lowercased. A body with no
    marker returns `[]`, which is the whole point: prose saying "reviewed, looks
    good" is not a report and never becomes one by being emphatic.
    """
    return [(m.group("head").lower(), m.group("verdict")) for m in MARKER_RE.finditer(body)]


def is_docs_only(files: tuple[str, ...]) -> bool:
    """Whether every changed path is documentation.

    An empty list is **not** docs-only. Vacuous truth here would exempt a PR
    whose file list simply failed to resolve, which is the fail-open reading of
    an absence — the shape this whole module exists to refuse.
    """
    if not files:
        return False
    return all(path.endswith(DOC_SUFFIXES) for path in files)


def _is_sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{40}", value))


#: Everything a GitHub login **can** be: ASCII letters, digits and the hyphen.
#: The rule below is written as this allowlist rather than as a list of things
#: to remove, and that is the whole point — see `resolve_identity`.
_OUTSIDE_THE_LOGIN_ALPHABET = re.compile(r"[^A-Za-z0-9-]")


def resolve_identity(raw: str) -> str | None:
    """The one place an author string becomes an identity, or fails to.

    **Both** questions this module asks about an author go through this
    function: "did this identity resolve at all?" and "is it the same person as
    the PR's author?".

    **The rule is defined by what a login can be, not by what it must not
    contain**, and #408 took four review rounds to reach that, each of which
    normalised one more layer of decoration and stopped:

    * Round 1 fixed a **blank** author with `.strip()` and left the identity
      comparison raw, so `NuncaEsLupus` still cleared its own PR.
    * Round 2 routed blankness through one helper but compared raw strings.
    * Round 3 made one helper — delete Unicode `Cc/Cf/Cs/Zl/Zp`, `strip()`,
      `casefold()` — and both call sites used it. Nine spellings refused.
    * Round 4 found the same class alive: that helper deleted *invisible*
      padding and not *visible* padding. `@nuncaeslupus`, `nuncaeslupus.`,
      `(nuncaeslupus)`, `nuncaeslupus` spelled in U+FF41..U+FF5A fullwidth
      letterforms, and
      `nunca es lupus` each resolved unequal to `nuncaeslupus` and cleared that
      account's own PR — through the shipped CLI, `merge_may_proceed: true`.

    A fifth strip-list would have been the fourth iteration of one mistake.
    Enumerating what must not appear can only ever remove the decorations
    somebody thought of; there is always another. So the rule inverts:

    1. **NFKC-fold.** Compatibility composition maps the fullwidth, circled,
       superscript and other presentational forms of a character onto the plain
       one, so U+FF4E U+FF55 U+FF4E U+FF43 U+FF41 and U+FF20 arrive as
       `nunca` and `@`.
    2. **Delete every character outside `[A-Za-z0-9-]`** — the alphabet GitHub
       logins are drawn from. `@`, `.`, `(`, `)`, `:`, `*` and the space are
       gone not because they were listed but because they were never in.
    3. **Trim leading and trailing hyphens**, because a login may not begin or
       end with one. A markdown bullet (`- nuncaeslupus`) is decoration by the
       grammar's own definition, not by an exception written for it.
    4. **`casefold()`**, because GitHub logins are case-insensitive:
       `nuncaeslupus` and `NuncaEsLupus` are one account.

    `None` — identity unresolved — is returned when nothing survives. Nothing
    surviving is exactly "this string held no character a login is made of",
    which subsumes round 1's blank, round 3's `"..."`, `"\\u200b"`, `"\\ufeff"`
    and `"\\x00"`: none of them contribute a single character to the alphabet.

    **Why this is safe to make aggressive.** Steps 1-3 only ever *merge*
    strings — many spellings collapse onto one identity, and none is ever split
    into two. The only use of the result is the equality
    `writer == pr_identity`, and a merge can therefore push a writer only
    *toward* the author, i.e. toward `blocked`. There is no reviewer roster to
    impersonate into: resolving to the author's identity never clears anything,
    it refuses. So the collisions this creates are **fail-closed**, which is the
    direction CLAUDE.md weights for. `straße`/`strasse` and U+212A KELVIN SIGN
    against `kelvin` are the checked cases: NFKC leaves `ß` alone and folds
    U+212A to `K` → `k`, and either way a collision costs one more read rather
    than a merge nobody reviewed.

    It also settles the Unicode-wide `isalnum()` that round 3 used to decide
    "names somebody": `²` and `Ⅷ` are alphanumeric to Python and name no
    account, so they resolved as identities. Every identity this returns is now
    a **well-formed login** — a string a human can look up on the PR — which is
    all this module's contract ever claimed.
    """
    folded = unicodedata.normalize("NFKC", raw)
    kept = _OUTSIDE_THE_LOGIN_ALPHABET.sub("", folded).strip("-")
    if not kept:
        return None
    return kept.casefold()


def read(pr: PullRequest) -> Verdict:
    """Does a second-reader report exist for this PR's head commit?

    The order of the checks is load-bearing:

    1. An unresolvable head or an empty file list is `unresolvable` — code 2,
       the same as no report, because neither is a pass. So is a marker whose
       *comment* author does not resolve through `resolve_identity`: an identity
       that did not resolve cannot be shown to differ from the PR's, so
       self-review cannot be ruled out and it is not a second reader. Both
       author fields go through that **one** helper, and the "is this somebody
       else?" comparison is made between its outputs — never between the raw
       captured strings, which differ by case and padding for one account.
    2. A `BLOCK` on the head blocks, **before** the docs-only exemption is
       considered. Exemption is for a PR nobody objected to.
    3. A `CLEAR` on the head by somebody other than the author allows.
    4. Docs-only, with nothing on record, is exempt.
    5. Otherwise blocked — and if a marker exists for a *different* commit, the
       code is 3 (stale) rather than 2 (absent), because "reviewed, then kept
       coding" is a different situation from "never reviewed" and both are
       hidden by a rollup that only shows a tick.
    """
    if not _is_sha(pr.head_sha):
        return Verdict(UNRESOLVABLE, 2, f"head commit {pr.head_sha!r} does not resolve to a sha")
    pr_identity = resolve_identity(pr.author)
    if pr_identity is None:
        return Verdict(
            UNRESOLVABLE, 2, "the PR's author is unknown, so self-review cannot be ruled out"
        )
    if not pr.files:
        return Verdict(
            UNRESOLVABLE,
            2,
            "no changed paths captured, so the docs-only exemption cannot be decided",
        )

    head = pr.head_sha.lower()
    on_head: list[tuple[Comment, str]] = []
    on_another_commit = False
    by_the_author = False
    for comment in pr.comments:
        for marked_head, verdict in markers(comment.body):
            writer = resolve_identity(comment.author)
            if writer is None:
                return Verdict(
                    UNRESOLVABLE,
                    2,
                    "a marker's author is unknown, so self-review cannot be ruled out",
                )
            if writer == pr_identity:
                by_the_author = True
                continue
            if marked_head != head:
                on_another_commit = True
                continue
            on_head.append((comment, verdict))

    reports = tuple(comment for comment, _ in on_head)
    blocking = [comment for comment, verdict in on_head if verdict == "BLOCK"]
    if blocking:
        return Verdict(
            BLOCKED,
            1,
            f"a second reader ({blocking[0].author}) BLOCKed {head[:12]}",
            reports,
        )
    if reports:
        return Verdict(
            ALLOWED,
            0,
            f"a second reader ({reports[0].author}) cleared {head[:12]}",
            reports,
        )
    if is_docs_only(pr.files):
        return Verdict(EXEMPT, 0, "docs-only PR: every changed path is documentation")
    if on_another_commit:
        return Verdict(
            BLOCKED,
            3,
            f"the only report on record is for another commit, not {head[:12]}",
        )
    if by_the_author:
        return Verdict(
            BLOCKED,
            2,
            "the only marker on record was written by the PR's own author, "
            "who is not a second reader",
        )
    return Verdict(BLOCKED, 2, f"no second-reader report for {head[:12]}")


def marker_line(head: str, verdict: str = "CLEAR") -> str:
    """The line a second reader ends its report with.

    Emitted rather than typed: the writer of the marker is a tool, so the
    reader is matching something that was generated, not prose somebody
    remembered the shape of.
    """
    if not _is_sha(head):
        raise ValueError(
            f"{head!r} is not a 40-character commit sha — an abbreviated sha binds nothing"
        )
    if verdict not in {"CLEAR", "BLOCK"}:
        raise ValueError(f"{verdict!r} is not CLEAR or BLOCK")
    return f"{MARKER_NAME}: head={head.lower()} verdict={verdict}"


def pull_request_from(capture: object) -> PullRequest | None:
    """A `PullRequest` from a captured JSON object, or `None` if it is not one.

    The capture is written by hand from a GitHub tool result — the pattern
    CLAUDE.md already describes for the board JSON, and what lets this reader
    work on a surface whose REST channel answers 403. Every field is validated
    rather than coerced: a comments list that arrived as a string becomes an
    empty tuple, and an empty tuple is `unresolvable`, not a pass.
    """
    if not isinstance(capture, dict):
        return None
    number = capture.get("number")
    author = capture.get("author")
    head = capture.get("head_sha")
    files = capture.get("files")
    comments = capture.get("comments")
    parsed: list[Comment] = []
    if isinstance(comments, list):
        for entry in comments:
            if not isinstance(entry, dict):
                continue
            body = entry.get("body")
            who = entry.get("author")
            if isinstance(body, str) and isinstance(who, str):
                parsed.append(Comment(author=who, body=body))
    return PullRequest(
        number=number if isinstance(number, int) and not isinstance(number, bool) else 0,
        author=author if isinstance(author, str) else "",
        head_sha=head if isinstance(head, str) else "",
        files=tuple(p for p in files if isinstance(p, str)) if isinstance(files, list) else (),
        comments=tuple(parsed),
    )


_HEAD = "d4a3b21c0f9e8d7c6b5a49382716f5e4d3c2b1a0"
_OLDER = "0a1b2c3d4e5f61728394a5b6c7d8e9f012345678"


def _control_prs() -> tuple[tuple[str, PullRequest, str, int, str], ...]:
    """The constructed states, each with the verdict the rule requires.

    Every expectation cites the text it comes from. A verdict argued from what
    this module does is the circularity the second-reader rule exists to break,
    so the citation is part of the control and is written into the record.
    """
    cleared = Comment("reviewer", f"Read the diff.\n\n{marker_line(_HEAD)}")
    blocked = Comment("reviewer", f"Two findings.\n\n{marker_line(_HEAD, 'BLOCK')}")
    stale = Comment("reviewer", f"Read the diff.\n\n{marker_line(_OLDER)}")
    code = ("src/integral/thing.py",)
    docs = ("arsenal/session/handover.md", "status/plan.md")
    rule = "CLAUDE.md § The review half of `merge-policy` is a second session, not a bot"
    return (
        (
            "a_second_reader_cleared_this_head",
            PullRequest(1, "author", _HEAD, code, (cleared,)),
            ALLOWED,
            0,
            f"{rule}: a PR may merge once a session other than its implementer has read it",
        ),
        (
            "no_report_at_all",
            PullRequest(2, "author", _HEAD, code, ()),
            BLOCKED,
            2,
            f"{rule}: if no other session has read a PR, it is not reviewed",
        ),
        (
            "a_report_on_a_superseded_commit",
            PullRequest(3, "author", _HEAD, code, (stale,)),
            BLOCKED,
            3,
            "t-41fda10d: a report on the wrong commit does not count (#320's nine\n"
            "unworked findings)",
        ),
        (
            "a_green_check_that_was_rate_limited",
            PullRequest(
                4,
                "author",
                _HEAD,
                code,
                (Comment("coderabbitai[bot]", "Review rate limited. Please try again later."),),
            ),
            BLOCKED,
            2,
            "t-41fda10d: a rate-limited check reporting `pass` must not resolve to allowed",
        ),
        (
            "a_green_check_skipped_on_a_draft",
            PullRequest(
                5,
                "author",
                _HEAD,
                code,
                (Comment("coderabbitai[bot]", "Review skipped: draft pull request"),),
            ),
            BLOCKED,
            2,
            "t-41fda10d: a draft-skipped check reporting `pass` must not resolve to allowed",
        ),
        (
            "the_author_reviewed_their_own_head",
            PullRequest(6, "author", _HEAD, code, (Comment("author", marker_line(_HEAD)),)),
            BLOCKED,
            2,
            f"{rule}: the implementer never signs it off",
        ),
        (
            "the_author_quotes_another_readers_marker",
            PullRequest(
                7,
                "author",
                _HEAD,
                code,
                (Comment("author", f"They said:\n\n> {marker_line(_HEAD)}"),),
            ),
            BLOCKED,
            2,
            f"{rule}: the implementer never signs it off — quoting a marker is\n"
            "still their own comment",
        ),
        (
            "a_docs_only_pr_with_no_report",
            PullRequest(8, "author", _HEAD, docs, ()),
            EXEMPT,
            0,
            f"{rule}: docs-only PRs are exempt — a handover or a task-file edit merges on green CI",
        ),
        (
            "a_docs_only_pr_a_second_reader_blocked",
            PullRequest(9, "author", _HEAD, docs, (blocked,)),
            BLOCKED,
            1,
            f"{rule}: the exemption is for a diff a test would catch, not a\n"
            "licence over an objection",
        ),
        (
            "a_code_pr_that_also_touches_docs",
            PullRequest(10, "author", _HEAD, ("README.md", "src/integral/thing.py"), ()),
            BLOCKED,
            2,
            f"{rule}: the rule is about diffs that can be wrong in a way a test does not catch",
        ),
        (
            "a_report_that_only_says_reviewed_in_prose",
            PullRequest(
                11,
                "author",
                _HEAD,
                code,
                (Comment("reviewer", "Reviewed. LGTM, no findings."),),
            ),
            BLOCKED,
            2,
            "t-41fda10d: do not let the marker be free text — a scan matching prose\n"
            "passes on a comment that says the word",
        ),
        (
            "a_marker_with_a_truncated_sha",
            PullRequest(
                12,
                "author",
                _HEAD,
                code,
                (Comment("reviewer", f"{MARKER_NAME}: head={_HEAD[:12]} verdict=CLEAR"),),
            ),
            BLOCKED,
            2,
            "t-41fda10d: the marker names the head commit it read — an abbreviated\n"
            "sha binds nothing",
        ),
        (
            "a_second_reader_blocked_this_head",
            PullRequest(13, "author", _HEAD, code, (blocked,)),
            BLOCKED,
            1,
            f"{rule}: the report goes on the PR, naming for each finding the input and the verdict",
        ),
        (
            "a_head_commit_that_does_not_resolve",
            PullRequest(14, "author", "", code, (cleared,)),
            UNRESOLVABLE,
            2,
            "t-41fda10d: `review_reader_status: unmeasured` when the scan cannot\n"
            "resolve PRs or markers",
        ),
        (
            "a_pr_with_no_changed_paths_captured",
            PullRequest(15, "author", _HEAD, (), ()),
            UNRESOLVABLE,
            2,
            "t-41fda10d: an exclusion with no counter is silence — an unresolved\n"
            "file list is not docs-only",
        ),
        (
            "a_marker_whose_author_did_not_resolve",
            PullRequest(16, "author", _HEAD, code, (Comment("", marker_line(_HEAD)),)),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — an author that did not\n"
            "resolve cannot be shown to be somebody else, so self-review is not ruled out",
        ),
        # ── #408 round 2: the identity relation itself, not just its blankness ──
        # The guard above normalised the author for *blankness* and the relation
        # two lines below compared the raw strings, so nine spellings of the PR's
        # own author still cleared it. Each of these is one of those spellings,
        # committed so the fix is measured rather than asserted.
        (
            "the_author_reviewed_their_own_head_under_a_different_case",
            PullRequest(
                17,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("NuncaEsLupus", marker_line(_HEAD)),),
            ),
            BLOCKED,
            2,
            f"{rule}: the implementer never signs it off — GitHub logins are\n"
            "case-insensitive, so capitalising one is the same account",
        ),
        (
            "the_author_reviewed_their_own_head_with_a_padded_login",
            PullRequest(
                18,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("  nuncaeslupus\t", marker_line(_HEAD)),),
            ),
            BLOCKED,
            2,
            f"{rule}: the implementer never signs it off — surrounding whitespace\n"
            "names the same account",
        ),
        (
            "a_marker_whose_author_is_a_zero_width_space",
            PullRequest(19, "author", _HEAD, code, (Comment("​", marker_line(_HEAD)),)),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — `str.strip()` does not\n"
            "remove U+200B, so an invisible author is non-blank and names nobody",
        ),
        (
            "a_marker_whose_author_is_a_byte_order_mark",
            PullRequest(20, "author", _HEAD, code, (Comment("﻿", marker_line(_HEAD)),)),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — U+FEFF survives\n"
            "`str.strip()` for the same reason U+200B does",
        ),
        (
            "a_marker_whose_author_is_a_nul_byte",
            PullRequest(21, "author", _HEAD, code, (Comment("\x00", marker_line(_HEAD)),)),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — a control character is\n"
            "not whitespace and identifies no account",
        ),
        (
            "a_marker_whose_author_is_punctuation_only",
            PullRequest(22, "author", _HEAD, code, (Comment("...", marker_line(_HEAD)),)),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — an author with no\n"
            "alphanumeric character names nobody a human can check, so the identity\n"
            "is unresolved rather than merely unequal to the PR's",
        ),
        # ── #408 round 4: visible padding, which round 3's helper did not touch ──
        # Round 3 deleted the *invisible* decorations and stopped there, so a
        # login wearing a visible one — an at-sign, a full stop, brackets, a
        # fullwidth letterform, a space — resolved unequal to the same account
        # and cleared its own PR. Reproduced through the shipped `check` CLI,
        # all five exiting 0 with `merge_may_proceed: true`. The fix is not a
        # sixth decoration to strip but the inverse rule: NFKC-fold, then keep
        # only what a GitHub login is made of.
        (
            "the_author_reviewed_their_own_head_as_an_at_mention",
            PullRequest(
                23,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("@nuncaeslupus", marker_line(_HEAD)),),
            ),
            BLOCKED,
            2,
            f"{rule}: the implementer never signs it off — `@login` is how a\n"
            "hand-written capture ordinarily spells a login, and `@` is not a\n"
            "character a GitHub login contains",
        ),
        (
            "the_author_reviewed_their_own_head_with_a_trailing_full_stop",
            PullRequest(
                24,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("nuncaeslupus.", marker_line(_HEAD)),),
            ),
            BLOCKED,
            2,
            f"{rule}: the implementer never signs it off — sentence punctuation\n"
            "is not part of the login it follows",
        ),
        (
            "the_author_reviewed_their_own_head_parenthesised",
            PullRequest(
                25,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("(nuncaeslupus)", marker_line(_HEAD)),),
            ),
            BLOCKED,
            2,
            f"{rule}: the implementer never signs it off — brackets around a\n"
            "login name the same account",
        ),
        (
            "the_author_reviewed_their_own_head_in_fullwidth_letterforms",
            PullRequest(
                26,
                "nuncaeslupus",
                _HEAD,
                code,
                (
                    Comment(
                        "\uff4e\uff55\uff4e\uff43\uff41\uff45\uff53\uff4c\uff55\uff50\uff55\uff53",
                        marker_line(_HEAD),
                    ),
                ),
            ),
            BLOCKED,
            2,
            f"{rule}: the implementer never signs it off — a fullwidth letterform\n"
            "is a presentational variant of the same letter, which is what NFKC\n"
            "compatibility composition is defined to fold",
        ),
        (
            "the_author_reviewed_their_own_head_with_internal_spaces",
            PullRequest(
                27,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("nunca es lupus", marker_line(_HEAD)),),
            ),
            BLOCKED,
            2,
            f"{rule}: the implementer never signs it off — a GitHub login holds\n"
            "no space, so a spaced spelling is the same account written loosely",
        ),
        (
            "the_author_reviewed_their_own_head_as_a_markdown_bullet",
            PullRequest(
                28,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("- nuncaeslupus", marker_line(_HEAD)),),
            ),
            BLOCKED,
            2,
            f"{rule}: the implementer never signs it off — a login may neither\n"
            "begin nor end with a hyphen, so a leading one is a list bullet",
        ),
        (
            "a_marker_whose_author_is_a_run_of_hyphens",
            PullRequest(29, "author", _HEAD, code, (Comment("---", marker_line(_HEAD)),)),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — a login may neither\n"
            "begin nor end with a hyphen, so a string of them is no login at all\n"
            "and names nobody a human can check",
        ),
        (
            "a_second_reader_whose_login_differs_only_by_hyphens",
            PullRequest(
                30,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("nunca-es-lupus", marker_line(_HEAD)),),
            ),
            ALLOWED,
            0,
            f"{rule}: a PR may merge once a session other than its implementer has\n"
            "read it — the hyphen IS in the login alphabet, so `nunca-es-lupus` is\n"
            "a different account from `nuncaeslupus` and this control is the one\n"
            "that stops the round-4 fold from merging two real people into one",
        ),
    )


CONTROLS = _control_prs()


def _floor(observed: int, minimum: int) -> tuple[int, bool]:
    """What to record for a floor, and whether it was breached.

    A floor is recorded as the value the code **asserts** so the number does not
    drift with the control list (T100). But recording the floor when the run did
    not meet it writes a claim the run never made — T111's defect exactly — so a
    breached floor records what was actually observed and is named in
    `floor_breaches`.
    """
    return (minimum, False) if observed >= minimum else (observed, True)


def measure(
    controls: tuple[tuple[str, PullRequest, str, int, str], ...] | None = None,
    claude_md: Path | None = None,
) -> dict[str, Any]:
    """D-28's reading: `merges_allowed_without_a_review_of_the_head`."""
    states = CONTROLS if controls is None else controls
    doc = DEFAULT_CLAUDE_MD if claude_md is None else claude_md

    readings: list[dict[str, Any]] = []
    violations: list[str] = []
    reports_found = 0
    docs_only_excluded = 0

    for name, pr, expected_state, expected_code, citation in states:
        verdict = read(pr)
        reports_found += len(verdict.reports)
        if verdict.state == EXEMPT:
            docs_only_excluded += 1
        mismatch = verdict.state != expected_state or verdict.code != expected_code
        direction = ""
        if mismatch:
            required_may_proceed = expected_state in {ALLOWED, EXEMPT}
            direction = (
                "fail-open"
                if verdict.merge_may_proceed and not required_may_proceed
                else "fail-closed"
            )
            violations.append(
                f"{name}: the rule requires {expected_state}/{expected_code} "
                f"({citation}); the reader answered {verdict.state}/{verdict.code} "
                f"— {verdict.reason} [{direction}]"
            )
        readings.append(
            {
                "control": name,
                "required": f"{expected_state}/{expected_code}",
                "observed": f"{verdict.state}/{verdict.code}",
                "derived_from": citation,
                "direction": direction,
            }
        )

    # The prose half, and the only reading here taken from text rather than from
    # behaviour: a reader no session is told to run stops no merges.
    try:
        documented = MODULE_PATH in doc.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        documented = False
    if not documented:
        violations.append(
            f"no session is told to run the reader: {doc.name} does not name `{MODULE_PATH}` "
            "[fail-open]"
        )

    prs_floor, prs_breached = _floor(len(states), MINIMUM_PRS_EVALUATED)
    reports_floor, reports_breached = _floor(reports_found, MINIMUM_REPORTS_FOUND)
    breaches: list[str] = []
    if prs_breached:
        breaches.append(
            f"prs_evaluated_at_least: {len(states)} states evaluated, "
            f"floor is {MINIMUM_PRS_EVALUATED}"
        )
    if reports_breached:
        breaches.append(
            f"second_reader_reports_found_at_least: {reports_found} head-bound reports parsed, "
            f"floor is {MINIMUM_REPORTS_FOUND} — the marker reader may have stopped matching"
        )

    record: dict[str, Any] = {
        "merges_allowed_without_a_review_of_the_head": len(violations),
        "prs_evaluated_at_least": prs_floor,
        "second_reader_reports_found_at_least": reports_floor,
        "docs_only_prs_excluded": docs_only_excluded,
        "marker": marker_line(_HEAD).replace(_HEAD, "<40-hex head sha>"),
        "reader_named_in_claude_md": documented,
        "floor_breaches": breaches,
        "readings_that_allow_a_merge_without_a_review": violations,
        "readings": readings,
        "review_reader_status": "measured",
    }
    if breaches:
        # A floor breach is not a clean zero and not a verdict: the scan that
        # was supposed to happen did not. `-1` fails `== 0` in the evidence
        # record itself, so the exit code is not the only alarm (T123).
        record["merges_allowed_without_a_review_of_the_head"] = -1
        record["review_reader_status"] = "unmeasured"
        record["unmeasured_reason"] = "; ".join(breaches)
    return record


def write_evidence(evidence: Path | None = None) -> dict[str, Any]:
    """Measure, then record `status/evidence/D28.json` — in that order (#297)."""
    path = DEFAULT_EVIDENCE_PATH if evidence is None else evidence
    measured = measure()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def exit_code_for(record: dict[str, Any]) -> int:
    """0 measured and clean, 1 anything else — and **never 3**.

    `Makefile:58-70` maps 3 to "unmeasured (recorded)" and continues. For every
    other module that is right: the check ran and found it cannot be scored yet.
    Here it would be the fail-open reading of the very absence this gate exists
    to catch, so an unmeasured reader stops `make evidence` like a breach does.
    """
    if record["review_reader_status"] != "measured":
        return 1
    return 1 if record["merges_allowed_without_a_review_of_the_head"] else 0


def _cmd_emit(head: str, verdict: str) -> int:
    try:
        print(marker_line(head, verdict))
    except ValueError as exc:
        print(f"review_reader: {exc}", file=sys.stderr)
        return 2
    return 0


def _cmd_check(state_path: Path) -> int:
    """Answer, for one captured PR state, whether a merge may proceed.

    Every failure to read the capture exits 2 — the code that means "no review
    on record", never 0. A reader that cannot see the PR has not cleared it.
    """
    try:
        capture = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"review_reader: cannot read {state_path}: {exc}", file=sys.stderr)
        print("review_reader: that is not a pass — no report is on record.", file=sys.stderr)
        return 2
    pr = pull_request_from(capture)
    if pr is None:
        print(f"review_reader: {state_path} is not a PR state object", file=sys.stderr)
        return 2
    verdict = read(pr)
    print(
        json.dumps(
            {
                "pr": pr.number,
                "head": pr.head_sha,
                "state": verdict.state,
                "reason": verdict.reason,
                "merge_may_proceed": verdict.merge_may_proceed,
            },
            ensure_ascii=False,
        )
    )
    print(f"review_reader: {verdict.state} — {verdict.reason}", file=sys.stderr)
    return verdict.code


def _main(argv: list[str] | None = None) -> int:
    """`python -m integral.review_reader [emit|check] …`.

    With no arguments it measures and writes D-28's evidence, which is how
    `make evidence` invokes every module here.
    """
    args = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        description="D-28: a merge waits for a second-reader report on the head commit"
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("measure", help="write status/evidence/D28.json (the default)")
    emit = sub.add_parser("emit", help="print the marker line a second reader's report ends with")
    emit.add_argument("--head", required=True, help="the 40-character head sha that was read")
    emit.add_argument("--verdict", default="CLEAR", choices=["CLEAR", "BLOCK"])
    check = sub.add_parser(
        "check", help="is there a second-reader report for this PR's head? (0/1/2/3)"
    )
    check.add_argument("state", help="a JSON capture: number, author, head_sha, files, comments")
    parsed = parser.parse_args(args)

    if parsed.command == "emit":
        return _cmd_emit(parsed.head, parsed.verdict)
    if parsed.command == "check":
        return _cmd_check(Path(parsed.state))

    measured = write_evidence()
    print(json.dumps(measured, ensure_ascii=False))
    for reason in measured["readings_that_allow_a_merge_without_a_review"]:
        print(reason, file=sys.stderr)
    if measured["review_reader_status"] != "measured":
        print(measured["unmeasured_reason"], file=sys.stderr)
    return exit_code_for(measured)


if __name__ == "__main__":
    raise SystemExit(_main())
