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

**T155 — an unattributable marker clears nothing and vetoes nothing.**

Until this task, a marker whose comment author failed the login grammar returned
`unresolvable/2` for the **whole** pull request, so one `github-actions[bot]`
comment discarded a genuine second reader's head-bound `verdict=CLEAR`, in either
comment order. T155's file left the rule open — *skip the unattributable marker
and keep counting*, or *refuse wholesale and say so in the reason* — and required
the choice to be argued from CLAUDE.md § *The review half of `merge-policy` is a
second session, not a bot*. **The choice is to skip it, and to record it in every
verdict that stands beside one.** Four things in that section decide it:

* **The condition is existential over reports.** *"A code PR may merge once a
  session other than its implementer has read it and reported on the PR."* That
  is satisfied by **exhibiting one** such report. A comment nobody can attribute
  is not a counter-example to a report that exists; it is not a report at all.
* **The guard's own premise is narrower than the answer it used to give.** Its
  reason string says *"self-review cannot be ruled out"* — a statement about the
  marker whose author did not resolve, concluding that **that** marker is not a
  second reader's. Nothing in it bears on a different comment whose author does
  resolve and does differ from the PR's. Returning for the whole PR was a
  non-sequitur from the module's own sentence.
* **A marker naming nobody is already the category `markers()` discards.**
  Prose saying "reviewed, looks good" is refused for naming no head; an author
  outside the login grammar names no writer. Both are comments that fail to be
  reports, and the module's answer to a non-report has always been to keep
  reading, not to stop.
* **The section is titled *not a bot*.** Under the old rule the deciding input on
  a reviewed PR was a bot's display name — a string no session chose, in a format
  GitHub picked. Letting that veto a human read is the section's own subject,
  inverted.

**The losing branch's risk, recorded because it is real.** *Refuse wholesale* is
fail-closed, and this rule is not: it hands back the ability to merge a PR that
carries a marker this module cannot attribute. The specific danger the refusal
covered is that **the implementer can appear under an unresolvable spelling of
themselves** — `nuncaeslupus (OWNER)` is round 5's own control — and after this
change such a marker is discarded silently instead of stopping the PR. Two things
bound it, and the second is why the recording is not decoration:

1. **A discarded marker can never supply a clearance.** It is dropped before any
   branch that allows, so the implementer wearing a badge cannot clear their own
   PR by that route in either comment order; what clears is a *different*
   account's resolvable marker, which is exactly what the rule asks for. The
   remaining self-clearance path is unchanged and still recorded: control #51's
   weld that stays inside the alphabet.
2. **An unattributable author is a canary for a capture whose author fields are
   being mangled**, and if one comment's author arrives mangled another's may
   too — mangled, this time, into something that resolves and reads as somebody
   else. Skipping quietly spends that canary. So the skip is never quiet: the
   verdict names the author it could not resolve, in `repr()`, and says
   `CLEARANCE_STANDS` or `CLEARANCE_SET_ASIDE`. Exit 0 with a line naming
   `'github-actions[bot]'` is what tells a human to fix the capture rather than
   to hunt for a review that is already there.

**And the skip is not symmetric.** An unattributable **`BLOCK`** on the head is
honoured — `unresolvable/2` — because the two error directions are not
symmetric anywhere else in this module either: *"Exemption applies to a PR nobody
objected to, never over an objection somebody raised."* **That sentence is this
module's own rule — the D-28 list above — and not CLAUDE.md's**, which says only
that docs-only PRs are exempt and spells out no carve-out over an objection.
Cited to the governing document it would read as externally mandated; it is a
decision taken here, and revisable here. A clearance from nobody is an approval
out of an absence; an objection from nobody is a reason to look.
So a marker naming nobody may still decide the answer for the set in exactly one
direction, and it is the fail-closed one.

**The scope of "vetoes nothing" is the whole tail of `read`, not its first
branch — three residuals, from the second reader on #421 (F1-F3).** The first
version of this fix guarded check 5 on `if unattributable:` and left it sitting
*ahead* of the docs-only, stale and author-only branches, while the check's own
sentence scoped it to "an unattributable marker with nothing else on record". So
a bot's name still turned a stale report's **code 3 into a 2**, still withheld
the docs-only exemption, and still emitted *"the only marker on record"* beside a
second marker — the same defect, one branch further down, and all three
fail-closed. Check 5 now sits last, where "nothing else on record" is what
reaching it means, and the `discarded` canary rides on the three reasons it used
to replace.

**F2 is the one decision here that moves fail-open, and it is taken
deliberately.** Restoring the exemption turns that state from `unresolvable/2`
into `exempt/0`: a merge that was refused is now allowed. CLAUDE.md says to
weight that direction hardest, and the conservative option — keep the refusal and
pin it as a second, argued veto — was available. It is not taken, for three
reasons:

* **The exemption resolves no identity.** *"Docs-only PRs are exempt — a
  handover or a task-file edit merges on green CI."* That is a claim about the
  **changed paths**, decided by `is_docs_only(pr.files)`. An author string this
  module cannot resolve is not evidence about a file list, and there is no
  mechanism by which a mangled author makes a `.py` path read as `.md`.
* **Refusing here would be incoherent with the answer already argued above.**
  The clearance case keeps counting *because* an unattributable marker is not a
  report — and identity is genuinely load-bearing there. If "one bad field
  impugns the whole capture" were accepted for the exemption, it would apply with
  more force to the clearance, which is exactly the reasoning T155 rejected. The
  permissive branch is taken in the case where identity matters and the
  restrictive one in the case where it does not; that is not a defensible pair.
* **Every input that moves is one that already passed without the marker.**
  #421's second reader bounded this step by exhaustion rather than by example:
  it diffed this rule against the pre-fix commit over **2907 constructed
  inputs** — every comment multiset of size 0-3 drawn from 16 comment kinds,
  over three filesets. **371** move refuse→allow and **0** move allow→refuse;
  all 371 are docs-only and none is a code PR; none carries a head-bound
  `BLOCK` from an unattributable author or from any other reader; and deleting
  the unattributable markers from all 371 leaves every one of them passing
  anyway — **0** counterexamples. An unattributable author is never treated
  more permissively than a resolvable one in the same position (0 violations).
  That is the property this branch actually has, and it is stronger than the
  sentence that stood here before it — *"the step is exactly one state wide"* —
  which was true of `SCOPE_STATES` and not of the input space, and invited the
  next reader to believe one fixture bounded the space.
* **The bound is committed.** An unattributable **BLOCK** on a docs-only PR is
  still `unresolvable/2`, because *"Exemption applies to a PR nobody objected
  to, never over an objection somebody raised"* — again **this module's own
  rule and not CLAUDE.md's**.
  `a_docs_only_pr_an_unattributable_marker_objected_to` pins it, beside the
  state it bounds.
* **Nothing is granted that was not already granted.** CLAUDE.md defines the
  direction to fear as *"the check said yes to something it was built to
  refuse"* — and a docs-only PR is the one thing this check was built to say
  yes to outright. Delete the bot's comment and the same PR is `exempt/0`
  already; the marker is not evidence for the exemption, it is simply not
  evidence against it. So this branch does not hand out a permission, it
  withdraws a veto a marker naming nobody was never entitled to cast, which is
  the sentence the whole task is named for. The fixture for this state asserts
  the two answers are *equal* — with the marker and without it — rather than
  merely asserting the one, so a drift in either direction is what fails.

**What would make this wrong**, recorded so the next reader can check rather than
re-derive: a capture path that decides `files` from the same mangled source as
`author` — then one broken field really would impugn the other, and the
conservative branch becomes the right one. Nothing in `pull_request_from` does
that today: `pull_request_from` reads `files` and `author` from separate keys,
and `is_docs_only` refuses an empty list as vacuous truth. It *filters* `files`
rather than validating it — a non-string entry is dropped, which can only
narrow a list toward the exemption — but that is unchanged here and equally
true on `main`, and #421 recorded it as its own task rather than this diff's.

`status/evidence/T155.json` is the gate:
`unresolvable_marker_authors_with_an_unrecorded_effect` over `SCOPE_STATES` —
six unattributable authors paired with a genuine head-bound clearance in both
comment orders, plus an unattributable BLOCK, a stale unattributable marker, a
resolvable BLOCK, a docs-only PR, and #421's residuals — counting a state whose
outcome is wrong **or** whose reason does not name the author and record the
effect. That `or` is load-bearing: against the code as it stood, the metric read
**22 of 22**, of which 18 failed on outcome and 4 on the reason alone.

**The states claim to cover both comment orders, and that claim is now checked
rather than labelled** (#421 F4). It was asserted by comparing state *names*, so
collapsing the two orders onto one comment tuple left the whole suite green and
the metric at 0 — a gate certifying coverage it did not have, which is the
vacuous-coverage shape one level up from the one this task fixes.
`test_both_orders_carry_different_comment_sequences` compares the constructed
`Comment` tuples and pins the marker to opposite ends.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D28.json"
DEFAULT_T155_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T155.json"
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
#:
#: Both were raised by #408 round 5 — 25→40 and 2→6 — because CLAUDE.md requires
#: it: *"the measured denominator must rise: if the audit accepted twelve cases,
#: the evidence counts twelve more than it did."* Seventeen controls were added
#: (47 states, 7 head-bound reports), and a floor left at the old value would let
#: every one of them be deleted again without the record noticing.
#:
#: Raised again by the round-5 second-reader report — 40→44 and 6→8 — for the
#: same reason: four controls landed (51 states, 9 head-bound reports), three for
#: F1's length bound and one recording F2's limitation, and each floor moves by
#: exactly what was added so the margin over the observed count is unchanged.
MINIMUM_PRS_EVALUATED = 44
MINIMUM_REPORTS_FOUND = 8

#: T155's floor, same style: the marker-scope states are the denominator of
#: `unresolvable_marker_authors_with_an_unrecorded_effect`, and a control list
#: that shrank to nothing would otherwise score a serene zero.
MINIMUM_SCOPE_STATES = 29

#: The second T155 floor, and the one #421's F4 required. Counting *states* says
#: nothing about whether they are distinct: collapsing both comment orders onto
#: the same tuple — changing only the label — left the count at 29, the metric at
#: 0 and the whole suite green, so the gate certified coverage it did not have.
#: `measure_marker_scope` therefore counts distinct constructed states — the
#: inputs actually handed to `read` — and floors that too. A collapse now
#: breaches this floor and the record reads `unmeasured`, which is the gate
#: catching it rather than only a test beside the gate.
#:
#: #421's N1 is why the count is of the inputs and not of `case.name`: swapping
#: the one for the other survived all 146 tests with the metric at 0, and
#: composed with F4's own mutant it reported a serene zero over a state set
#: genuinely collapsed to 16. A floor that counts labels rather than the things
#: labelled is the defect it was added to close, so the discriminator has to be
#: a state that is a twin under a *different* name — which is the one the
#: fixtures now seed.
MINIMUM_DISTINCT_SCOPE_STATES = 29

#: The two phrases a verdict carries when an unattributable marker sits beside a
#: head-bound clearance. They are **named constants because T155's gate asserts
#: them**: "the effect was recorded" has to be checkable by something other than
#: a human reading prose, which is the same reason `markers()` refuses free text.
#: `read` emits exactly one of them in that situation, and never both.
CLEARANCE_STANDS = "the clearance stands"
CLEARANCE_SET_ASIDE = "the clearance was set aside"

#: The canary itself, carried by **every** verdict standing beside an
#: unattributable marker — including the three that used to be shadowed by it
#: (#421 F1-F3: a stale report, the docs-only exemption, the author's own
#: marker). Named for the same reason the two above are: what the reason has to
#: record is checkable, not a matter of a human liking the prose.
RECORDED_BUT_INERT = "is on record and cleared nothing"

#: What the one honoured veto says. An unattributable BLOCK is the single
#: direction in which a marker naming nobody still decides the answer for the
#: set, so the sentence that carries it is pinned too.
OBJECTION_HONOURED = "an objection this reader cannot attribute is not a pass"


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


#: Everything a GitHub login **is**: ASCII letters and digits, with interior
#: single hyphens, and **at most 39 characters**. This is applied as a
#: **validator** over the whole string — never as a filter over its characters —
#: and `resolve_identity` says why.
#:
#: The length bound is #408's F1: unbounded, `"r" * 5000` validated and cleared a
#: head at exit 0 — a string no GitHub account can bear, accepted as a second
#: reader. That is not a self-clearance path, which is why the round-5 verdict was
#: CLEAR, but it is the fail-open direction, and a grammar written to say what a
#: login **is** has to be closed in every direction or it is back to enumerating.
#:
#: The repetition consumes exactly **one** character per step — `-(?=[A-Za-z0-9])`
#: takes the hyphen and only looks ahead at the alphanumeric — so `{0,38}` bounds
#: the whole string at 39 rather than bounding the number of alnum characters.
#: The obvious spelling, `(?:-?[A-Za-z0-9]){0,38}`, does the latter and lets a
#: hyphen-alternating 77-character string through; `#50` is the control on that.
#: This is GitHub's own documented username grammar, character for character, and
#: it refuses `--` for exactly the reason the round-5 hypothesis was refuted: no
#: branch consumes a hyphen that is not followed by an alphanumeric.
_GITHUB_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")

#: The bound above, named so a control can cite it rather than restating `39`.
MAXIMUM_LOGIN_LENGTH = 39


def resolve_identity(raw: str) -> str | None:
    """The one place an author string becomes an identity, or fails to.

    **Both** questions this module asks about an author go through this
    function: "did this identity resolve at all?" and "is it the same person as
    the PR's author?".

    **The rule is that the string must already BE a login.** #408 took five
    review rounds to reach that, and the first four each normalised one more
    layer of decoration and stopped:

    * Round 1 fixed a **blank** author with `.strip()` and left the identity
      comparison raw, so `NuncaEsLupus` still cleared its own PR.
    * Round 2 routed blankness through one helper but compared raw strings.
    * Round 3 made one helper — delete Unicode `Cc/Cf/Cs/Zl/Zp`, `strip()`,
      `casefold()` — and both call sites used it. Nine spellings refused.
    * Round 4 found the same class alive: that helper deleted *invisible*
      padding and not *visible* padding. `@nuncaeslupus`, `nuncaeslupus.`,
      `(nuncaeslupus)`, a fullwidth spelling and `nunca es lupus` each resolved
      unequal to `nuncaeslupus` and cleared that account's own PR.
    * Round 5 found it alive again, one layer deeper, because round 4's answer —
      *NFKC-fold, then delete everything outside `[A-Za-z0-9-]`* — is still an
      enumeration: **an allowlist applied as a deletion filter enumerates by
      complement.** It removes only decoration made of characters *outside* the
      alphabet. Decoration made of characters *inside* it is **welded onto the
      login**, and the weld is a different identity, so it reads as somebody
      else and clears the PR. `nuncaeslupus (OWNER)` — a `gh` association-badge
      transcription, one step past round 4's own accepted `(nuncaeslupus)` —
      became `nuncaeslupusowner`: exit 0, `merge_may_proceed: true`, *"a second
      reader (nuncaeslupus (OWNER)) cleared …"*, on a PR authored by
      `nuncaeslupus`. Eight comment-side spellings and three PR-author-side
      mirrors did the same.

    **So the alphabet is a validator, not a filter.** The whole string, after
    the two transformations named below, must match `_GITHUB_LOGIN` — and
    anything else returns `None`, i.e. *unresolvable*, code 2. A residual
    oddity is never **repaired into** an identity; it fails to be one. That
    single move closes three classes at once:

    * **welded decoration** — `nuncaeslupus (OWNER)`, `nuncaeslupus[bot]`,
      `nuncaeslupus - maintainer` are not logins, so they name nobody, so no
      marker they carry clears anything;
    * **compatibility rewriting** — `²`, `Ⅷ`, `™`, `Ⓐ`, `½`, `㎏` each resolved
      under round 4 to a *distinct* identity (`2`, `viii`, `tm`, `a`, `12`,
      `kg`) and cleared the head at exit 0. NFKC is gone: the discriminator is
      not whether the output *looks* like a login (`2` does; so does `reviewer`)
      but whether normalisation had to **rewrite the input into something
      else**;
    * **splitting** — see the safety note below.

    Only two transformations survive, and neither can invent an identity the
    input did not already carry:

    1. **`str.strip()`** — outer whitespace is transport framing. It removes
       characters no login can contain, from the ends only, so it can never
       weld two fragments into a third identity.
    2. **`casefold()`**, because GitHub logins are case-insensitive:
       `nuncaeslupus` and `NuncaEsLupus` are one account. It runs *after*
       validation, so its input is already ASCII `[A-Za-z0-9-]`, where it is
       exactly `lower()` and merges only the case pairs GitHub itself merges.

    **The round-4 safety argument was false, and this is why the transform had
    to go rather than be extended.** It claimed the pipeline "only ever
    *merges* strings … and none is ever split into two", so every collision was
    fail-closed. Its own worked example refutes it: `resolve_identity("straße")`
    returned `strae`, **not** `strasse`. Deletion shortens and NFKC lengthens
    (`™`→`TM`, `№`→`No`, `Ⅷ`→`VIII`), so the transform did not only merge — and
    **every split is fail-open**, because a split moves a writer *away* from the
    author and toward "somebody else". Validation cannot split: it either
    returns the string GitHub itself would case-fold, or nothing.

    `None` — identity unresolved — subsumes round 1's blank, round 3's `"..."`,
    `"\u200b"`, `"\ufeff"` and `"\x00"`, round 4's `@`/`.`/`()`/fullwidth/
    spaced spellings, and round 5's welds and rewrites. None of them is a
    login, and `read` treats an unresolved author on a marker as "self-review
    cannot be ruled out" — code 2, never a pass.

    The one thing this must **not** do is refuse a real second reader, and
    `nunca-es-lupus` is the control on that: the hyphen is in the grammar, so a
    hyphenated login is a different, well-formed account and still clears
    `nuncaeslupus`'s PR at code 0.

    **Length is part of the grammar** and the round-5 report found it missing:
    `"r" * 5000` validated and cleared a head at 0. `_GITHUB_LOGIN` now bounds
    the whole string at `MAXIMUM_LOGIN_LENGTH`, with controls at 39 (clears) and
    at 40 (refuses) so the boundary is pinned on the side that would refuse real
    readers as well as on the side that let a non-login through.

    **One fail-open survives and is recorded rather than fixed**: a weld that
    stays *inside* the alphabet — `nuncaeslupusOWNER` — is a well-formed login
    for another account, so it resolves and clears its own author's PR.
    Validation cannot see it, and no rule that refused it would spare `nunca`
    reviewing `nuncaeslupus`. Control #51 asserts that behaviour and says what
    keeps it unreachable today.
    """
    candidate = raw.strip()
    if not _GITHUB_LOGIN.fullmatch(candidate):
        return None
    return candidate.casefold()


def read(pr: PullRequest) -> Verdict:
    """Does a second-reader report exist for this PR's head commit?

    The order of the checks is load-bearing, and **it is not the order of this
    list**. The numbers are stable names: #421's F1-F3, the module docstring,
    the comment beside check 5 and `T155.json`'s citations all refer to these
    branches by number, so 5 keeps its number and states its position instead
    of being renumbered under them. In execution order the list reads
    1, 2, 3, 4, 6, 7, 5.

    1. An unresolvable head or an empty file list is `unresolvable` — code 2,
       the same as no report, because neither is a pass. So is a marker whose
       *comment* author does not resolve through `resolve_identity`: an identity
       that did not resolve cannot be shown to differ from the PR's, so
       self-review cannot be ruled out and it is not a second reader. Both
       author fields go through that **one** helper, and the "is this somebody
       else?" comparison is made between its outputs — never between the raw
       captured strings, which differ by case and padding for one account.
       **That conclusion is about the marker it fires on, and T155 scopes it
       there**: an unattributable marker clears nothing and vetoes nothing, and
       every verdict standing beside one names its author and says what became
       of the clearance. See the module docstring for the argument.
    2. A `BLOCK` on the head blocks, **before** the docs-only exemption is
       considered. Exemption is for a PR nobody objected to.
    3. An **unattributable** `BLOCK` on the head is `unresolvable` — the one
       direction in which a marker naming nobody still decides the answer for
       the set, and it is the fail-closed one (T155).
    4. A `CLEAR` on the head by somebody other than the author allows, and says
       in its reason that any unattributable marker beside it was discarded.
    5. An unattributable marker with nothing else on record is `unresolvable`,
       exactly as before — there is then nothing else to count. **Checked
       last, after 6 and 7**: reaching that line is what "nothing else on
       record" means. Read ahead of them — as this list said until #421's N4,
       and as the code itself did until F1-F3 — it answers `unresolvable/2`
       for all three of their inputs instead: a docs-only PR carrying only
       such a marker (`exempt/0`, item 6), a stale genuine report beside one
       (`blocked/3`, item 7), and the author's own marker beside one
       (`blocked/2`, item 7). All three fail-closed, all three the shape T155
       exists to remove.
    6. Docs-only is exempt when no **head-bound report** is on record. An
       unattributable marker beside it is not a report and does not withhold
       the exemption — it is named in the reason as recorded-but-inert, which
       is why "nothing on record" is the wrong reading of this item and item 5
       does not race it.
    7. Otherwise blocked — code 3 (stale) if a marker exists for a *different*
       commit, because "reviewed, then kept coding" is a different situation
       from "never reviewed" and both are hidden by a rollup that only shows a
       tick; code 2 if the only marker on record is the PR author's own, who
       is not a second reader.
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
    unattributable: list[str] = []
    unattributable_objection = False
    for comment in pr.comments:
        for marked_head, verdict in markers(comment.body):
            writer = resolve_identity(comment.author)
            if writer is None:
                if comment.author not in unattributable:
                    unattributable.append(comment.author)
                if marked_head == head and verdict == "BLOCK":
                    unattributable_objection = True
                continue
            if writer == pr_identity:
                by_the_author = True
                continue
            if marked_head != head:
                on_another_commit = True
                continue
            on_head.append((comment, verdict))

    reports = tuple(comment for comment, _ in on_head)
    blocking = [comment for comment, verdict in on_head if verdict == "BLOCK"]
    cleared = [comment for comment, verdict in on_head if verdict == "CLEAR"]
    named = ", ".join(repr(who) for who in unattributable)
    discarded = (
        f"; a marker author naming nobody ({named}) {RECORDED_BUT_INERT}" if unattributable else ""
    )
    if blocking:
        aside = f", so {CLEARANCE_SET_ASIDE}" if cleared else ""
        return Verdict(
            BLOCKED,
            1,
            f"a second reader ({blocking[0].author}) BLOCKed {head[:12]}{aside}{discarded}",
            reports,
        )
    if unattributable_objection:
        aside = f"{CLEARANCE_SET_ASIDE}" if cleared else "no clearance was on record"
        return Verdict(
            UNRESOLVABLE,
            2,
            f"a marker on {head[:12]} says BLOCK and its author names nobody ({named}), "
            f"so {aside}: {OBJECTION_HONOURED}, and the capture is what needs fixing",
            reports,
        )
    if reports:
        stands = (
            f"{discarded}, so {CLEARANCE_STANDS}: it is not a report, and it is not a veto over one"
            if unattributable
            else ""
        )
        return Verdict(
            ALLOWED,
            0,
            f"a second reader ({reports[0].author}) cleared {head[:12]}{stands}",
            reports,
        )
    if is_docs_only(pr.files):
        return Verdict(EXEMPT, 0, f"docs-only PR: every changed path is documentation{discarded}")
    if on_another_commit:
        return Verdict(
            BLOCKED,
            3,
            f"the only report on record is for another commit, not {head[:12]}{discarded}",
        )
    if by_the_author:
        return Verdict(
            BLOCKED,
            2,
            "the only marker on record was written by the PR's own author, "
            f"who is not a second reader{discarded}",
        )
    # Check 5 sits HERE, not before the three branches above: its own sentence is
    # "an unattributable marker with nothing else on record", and nothing else on
    # record is what reaching this line means. Placed earlier it turned a stale
    # report's code 3 into a 2, withheld the docs-only exemption, and shadowed
    # the author's-own-marker reason — all three fail-closed, all three the very
    # shape T155 was filed to remove, and all three found by the second reader on
    # #421 (F1-F3). The `discarded` canary now rides on the reasons it was
    # shadowing instead of replacing them.
    if unattributable:
        return Verdict(
            UNRESOLVABLE,
            2,
            f"the only marker on record has an author naming nobody ({named}), "
            "so self-review cannot be ruled out",
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
        # all five exiting 0 with `merge_may_proceed: true`.
        #
        # Round 4 answered them by NFKC-folding and then deleting everything
        # outside `[A-Za-z0-9-]`, which repaired each spelling INTO the author's
        # identity — `blocked/2`. Round 5 showed that repair is the defect (see
        # below), so the alphabet is now a validator: none of these is a login,
        # so each resolves to nobody. `unresolvable/2` — the same exit code, the
        # same refusal, and no identity invented on the way.
        (
            "a_marker_whose_author_is_an_at_mention",
            PullRequest(
                23,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("@nuncaeslupus", marker_line(_HEAD)),),
            ),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — `@login` is how a\n"
            "hand-written capture ordinarily spells a login, and `@` is not a\n"
            "character a GitHub login contains, so the string is no login and\n"
            "names nobody — self-review is not ruled out",
        ),
        (
            "a_marker_whose_author_carries_a_trailing_full_stop",
            PullRequest(
                24,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("nuncaeslupus.", marker_line(_HEAD)),),
            ),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — sentence punctuation is\n"
            "not part of a login, so `nuncaeslupus.` is not one and names nobody",
        ),
        (
            "a_marker_whose_author_is_parenthesised",
            PullRequest(
                25,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("(nuncaeslupus)", marker_line(_HEAD)),),
            ),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — brackets are not login\n"
            "characters, so a parenthesised login is not a login",
        ),
        (
            "a_marker_whose_author_is_in_fullwidth_letterforms",
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
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — U+FF41..U+FF5A are not\n"
            "the ASCII letters a login is drawn from. Round 4 NFKC-folded them\n"
            "back; round 5 removed that fold because the same fold turns `™`\n"
            "into the identity `tm`, so the spelling now names nobody instead",
        ),
        (
            "a_marker_whose_author_holds_internal_spaces",
            PullRequest(
                27,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("nunca es lupus", marker_line(_HEAD)),),
            ),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — a GitHub login holds no\n"
            "space, so a spaced spelling is not a login and names nobody",
        ),
        (
            "a_marker_whose_author_is_a_markdown_bullet",
            PullRequest(
                28,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("- nuncaeslupus", marker_line(_HEAD)),),
            ),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — a login may neither begin\n"
            "nor end with a hyphen, so `- nuncaeslupus` is not one",
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
        # ── #408 round 5: the alphabet was an allowlist applied as a DELETION ──
        # Round 4's rule enumerated by complement. Deleting "everything outside
        # `[A-Za-z0-9-]`" removes only decoration made of characters OUTSIDE the
        # alphabet; decoration made of characters INSIDE it is welded onto the
        # login and the weld is a DIFFERENT identity, so it reads as somebody
        # else and clears the PR. Eight comment-side spellings and three
        # PR-author-side mirrors did exactly that through the shipped `check`
        # CLI — exit 0, `merge_may_proceed: true`.
        (
            "a_marker_whose_author_wears_an_association_badge",
            PullRequest(
                31,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("nuncaeslupus (OWNER)", marker_line(_HEAD)),),
            ),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — `gh` prints the author\n"
            "association beside the login, and round 4 welded it on as\n"
            "`nuncaeslupusowner`, an identity that is not the author's and cleared\n"
            "the head at exit 0. A badge is not part of a login, so the string is\n"
            "not one",
        ),
        (
            "a_marker_whose_author_carries_a_bot_suffix",
            PullRequest(
                32,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("nuncaeslupus[bot]", marker_line(_HEAD)),),
            ),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — brackets are outside the\n"
            "alphabet and `bot` is inside it, so round 4 welded `nuncaeslupusbot`",
        ),
        (
            "a_marker_whose_author_is_followed_by_a_role_word",
            PullRequest(
                33,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("nuncaeslupus - maintainer", marker_line(_HEAD)),),
            ),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — the worst shape of the\n"
            "weld: `nuncaeslupus-maintainer` is a WELL-FORMED login that no account\n"
            "bears, so nothing downstream could tell it was manufactured",
        ),
        # The same class reached by rewriting rather than by welding. Each of
        # these is a single character that NFKC expands into letters, so round 4
        # resolved it to a distinct identity — `2`, `viii`, `tm`, `a`, `12`,
        # `kg` — and cleared the head at exit 0. The discriminator is not what
        # the output looks like (`2` looks no worse than `reviewer`) but that
        # normalisation had to rewrite the input into something else.
        (
            "a_marker_whose_author_is_a_superscript_digit",
            PullRequest(34, "author", _HEAD, code, (Comment("\u00b2", marker_line(_HEAD)),)),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — U+00B2 is not an ASCII\n"
            "digit; NFKC rewrote it into the identity `2`, which named a second\n"
            "reader that does not exist",
        ),
        (
            "a_marker_whose_author_is_a_roman_numeral",
            PullRequest(35, "author", _HEAD, code, (Comment("\u2167", marker_line(_HEAD)),)),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — NFKC LENGTHENS U+2167\n"
            "into `VIII`, which is the counterexample to round 4's claim that the\n"
            "transform only ever merges",
        ),
        (
            "a_marker_whose_author_is_a_trademark_sign",
            PullRequest(36, "author", _HEAD, code, (Comment("\u2122", marker_line(_HEAD)),)),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — `™` became `tm`, a login\n"
            "shape a human would read as an account and could not find",
        ),
        (
            "a_marker_whose_author_is_a_circled_letter",
            PullRequest(37, "author", _HEAD, code, (Comment("\u24b6", marker_line(_HEAD)),)),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — a circled letterform is\n"
            "presentation, and folding it produced the identity `a`",
        ),
        (
            "a_marker_whose_author_is_a_vulgar_fraction",
            PullRequest(38, "author", _HEAD, code, (Comment("\u00bd", marker_line(_HEAD)),)),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — `½` folds to a digit, a\n"
            "FRACTION SLASH and a digit; the slash is then deleted, welding the\n"
            "identity `12`: a rewrite and a weld in one character",
        ),
        (
            "a_marker_whose_author_is_a_squared_unit",
            PullRequest(39, "author", _HEAD, code, (Comment("\u338f", marker_line(_HEAD)),)),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — `㎏` folds to `kg`",
        ),
        # ── The class no round had a control for: the PR AUTHOR field itself ──
        # Every earlier round decorated the COMMENT side only, which is
        # structurally why each stopped one layer short — a defect in
        # `resolve_identity` reached through `pr.author` had nothing watching it.
        # These three passed at exit 0 on the round-4 head.
        (
            "the_pr_authors_own_field_wears_an_association_badge",
            PullRequest(
                40,
                "nuncaeslupus (OWNER)",
                _HEAD,
                code,
                (Comment("nuncaeslupus", marker_line(_HEAD)),),
            ),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — the mirror of #31. The\n"
            "author welded to `nuncaeslupusowner`, so their own marker read as a\n"
            "second reader's and cleared the head at exit 0",
        ),
        (
            "the_pr_authors_own_field_carries_a_bot_suffix",
            PullRequest(
                41,
                "nuncaeslupus[bot]",
                _HEAD,
                code,
                (Comment("nuncaeslupus", marker_line(_HEAD)),),
            ),
            UNRESOLVABLE,
            2,
            f"{rule}: the implementer never signs it off — the mirror of #32, and\n"
            "the direction that matters: a decorated AUTHOR field is what lets the\n"
            "author be somebody else",
        ),
        (
            "the_pr_authors_own_field_is_a_compatibility_character",
            PullRequest(42, "\u2122", _HEAD, code, (Comment("reviewer", marker_line(_HEAD)),)),
            UNRESOLVABLE,
            2,
            "t-41fda10d: an unresolvable PR author is `unresolvable/2` — round 4\n"
            "rewrote `™` into the identity `tm` and answered `allowed/0` over a PR\n"
            "whose author it had invented",
        ),
        (
            "the_pr_authors_own_field_is_in_fullwidth_letterforms",
            PullRequest(
                43,
                "\uff4e\uff55\uff4e\uff43\uff41\uff45\uff53\uff4c\uff55\uff50\uff55\uff53",
                _HEAD,
                code,
                (Comment("nuncaeslupus", marker_line(_HEAD)),),
            ),
            UNRESOLVABLE,
            2,
            "t-41fda10d: the author-side mirror of #26. It was already fail-closed\n"
            "under round 4 (folded to the same account, `blocked/2`) and stays\n"
            "fail-closed here for a different reason — a fullwidth spelling is not\n"
            "a login. Committed so the AUTHOR side has a control either way",
        ),
        # ── Directional controls on the validator: it must refuse decoration and
        # nothing else. A rule this strict fails the other way — refusing real
        # second readers — and these are what would catch that.
        (
            "the_pr_author_written_in_another_case_is_still_the_same_account",
            PullRequest(
                44,
                "NuncaEsLupus",
                _HEAD,
                code,
                (Comment("nuncaeslupus", marker_line(_HEAD)),),
            ),
            BLOCKED,
            2,
            f"{rule}: the implementer never signs it off — casefold survives the\n"
            "validator, on the AUTHOR side too: GitHub logins are case-insensitive",
        ),
        (
            "a_second_reader_whose_login_holds_a_digit",
            PullRequest(45, "author", _HEAD, code, (Comment("reviewer2", marker_line(_HEAD)),)),
            ALLOWED,
            0,
            f"{rule}: a PR may merge once a session other than its implementer has\n"
            "read it — digits are in the login grammar and must not be refused",
        ),
        (
            "a_second_reader_whose_login_begins_with_a_digit",
            PullRequest(46, "author", _HEAD, code, (Comment("2ndreader", marker_line(_HEAD)),)),
            ALLOWED,
            0,
            f"{rule}: a login may begin with a digit, so `^[A-Za-z0-9]` and not\n"
            "`^[A-Za-z]` — a validator that refused this would block real readers",
        ),
        (
            "a_second_reader_whose_login_is_padded_by_the_capture",
            PullRequest(47, "author", _HEAD, code, (Comment("  reviewer\n", marker_line(_HEAD)),)),
            ALLOWED,
            0,
            f"{rule}: a PR may merge once a session other than its implementer has\n"
            "read it — outer whitespace is transport framing, not identity, and it\n"
            "is the one thing `str.strip()` may still remove because it cannot weld",
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
        # ── The bound on the alphabet (#408 F1). The grammar said what a login
        # is made OF and never how long it may be, so `"r" * 5000` validated and
        # cleared a head at exit 0. Both sides of the boundary are pinned: a
        # bound committed only on its failing side is a bound nothing stops from
        # being tightened until it refuses real readers.
        (
            "a_second_reader_whose_login_is_the_longest_github_allows",
            PullRequest(
                48,
                "author",
                _HEAD,
                code,
                (Comment("r" * MAXIMUM_LOGIN_LENGTH, marker_line(_HEAD)),),
            ),
            ALLOWED,
            0,
            f"{rule}: a PR may merge once a session other than its implementer has\n"
            f"read it — {MAXIMUM_LOGIN_LENGTH} characters is the longest login GitHub\n"
            "issues, so the bound must clear it or it refuses real second readers",
        ),
        (
            "a_marker_whose_author_is_longer_than_any_github_login",
            PullRequest(
                49,
                "author",
                _HEAD,
                code,
                (Comment("r" * (MAXIMUM_LOGIN_LENGTH + 1), marker_line(_HEAD)),),
            ),
            UNRESOLVABLE,
            2,
            "t-41fda10d (#408 F1): a string no GitHub account can bear names nobody,\n"
            "so it is `unresolvable/2`. Unbounded it validated and cleared the head\n"
            "at exit 0 — the fail-open direction over a grammar meant to be closed",
        ),
        (
            "a_marker_whose_author_pads_past_the_bound_with_hyphens",
            PullRequest(
                50,
                "author",
                _HEAD,
                code,
                (Comment("a-" * 20 + "a", marker_line(_HEAD)),),
            ),
            UNRESOLVABLE,
            2,
            "t-41fda10d (#408 F1): the bound is on CHARACTERS, not on alphanumerics.\n"
            "41 characters of well-formed alternation is still longer than any login,\n"
            "and the obvious spelling of the bound — `(?:-?[A-Za-z0-9]){0,38}` —\n"
            "counts pairs and lets 77 characters through. This is the control that\n"
            "distinguishes the two",
        ),
        # ── A RECORDED LIMITATION, not a passing property (#408 F2) ──────────
        # This control asserts what the reader does TODAY, and what it does today
        # is fail open. `nuncaeslupusOWNER` is the PR author's login with an
        # association badge welded on *inside* the alphabet, so it is a
        # well-formed login for a different account, resolves, and clears the
        # author's own PR at exit 0. Validation cannot see it: `nuncaeslupusowner`
        # and `nuncaeslupus` are two logins, and refusing one because it contains
        # the other would refuse `nunca` reviewing `nuncaeslupus` — a real reader.
        #
        # It is unreachable as capture formats stand: every spelling `gh` or a
        # GitHub badge actually emits separates the login from the decoration with
        # a space, parens or brackets — `nuncaeslupus (OWNER)` (#31),
        # `nuncaeslupus[bot]` (#32), `nuncaeslupus - maintainer` — and every one of
        # those is refused, because the separator is outside the alphabet. The weld
        # has to be typed by hand.
        #
        # What would make it reachable: any capture path that strips punctuation
        # before this module sees the author, or a tool that concatenates a login
        # and a role with no separator. The day either appears, this control turns
        # red in the fail-open direction, which is the whole reason it is committed
        # rather than left in a review comment — an unreachable fail-open nobody
        # wrote down becomes a reachable one the day a format changes.
        (
            "an_author_weld_that_stays_inside_the_alphabet_is_a_known_limitation",
            PullRequest(
                51,
                "nuncaeslupus",
                _HEAD,
                code,
                (Comment("nuncaeslupusOWNER", marker_line(_HEAD)),),
            ),
            ALLOWED,
            0,
            "t-41fda10d (#408 F2): RECORDED LIMITATION, not a requirement of the\n"
            "rule. A weld inside the login alphabet is a well-formed login for\n"
            "another account and validation cannot distinguish it from a real\n"
            "second reader whose name shares a prefix. Unreachable at every capture\n"
            "format that exists today — all of them separate with a character the\n"
            "alphabet refuses — and committed so that stops being true out loud",
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


# ──────────────────────────────────────────────────────────────────────────
# T155 — the scope of an unattributable marker
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScopeState:
    """One constructed state pairing an unattributable marker with a clearance.

    `unattributable` is the raw author string the verdict's reason must name —
    checked as `repr(...)`, never as the bare string, because a **blank** author
    is a substring of every reason ever written and would satisfy "names the
    author" vacuously. That is the same vacuous-truth shape `is_docs_only`
    refuses for an empty file list.

    `effect` is the phrase the reason has to carry: what became of the thing the
    verdict turns on. For the clearance pairings that is `CLEARANCE_STANDS` or
    `CLEARANCE_SET_ASIDE`; for the residuals #421 accepted (F1-F3) the marker
    stands beside a *stale* report, the docs-only exemption or the author's own
    marker instead, and the phrase is `RECORDED_BUT_INERT` — the canary that now
    rides on those reasons rather than replacing them. A state whose outcome is
    right and whose reason carries neither still counts as a violation: the
    gate's `or`.

    `order` says where the unattributable marker sits — `unattributable_first`,
    `clearance_first`, or `single` for a state with one comment, where there is
    no order to vary. **It is not decoration**: #421 F4 found that asserting the
    two orders by their *names* is satisfied by two identical comment tuples, so
    `test_both_orders_carry_different_comment_sequences` reads this field to pair
    the states up and then compares the sequences themselves.
    """

    name: str
    pr: PullRequest
    state: str
    code: int
    unattributable: str
    effect: str
    citation: str
    order: str = "single"


#: The names a capture actually carries for a writer this module cannot resolve.
#: Each is paired with why it resolves to nobody, so the control cites the
#: grammar rather than the behaviour.
_UNATTRIBUTABLE_AUTHORS: tuple[tuple[str, str, str], ...] = (
    (
        "github_actions",
        "github-actions[bot]",
        "`[` is outside the login alphabet, so the string is no login — this is\n"
        "F3's own example, the one that vetoed a real reader on #408",
    ),
    (
        "dependabot",
        "dependabot[bot]",
        "the same shape from a second bot: a PR carrying routine automation must\n"
        "not become unmergeable because the automation commented on it",
    ),
    (
        "coderabbitai",
        "coderabbitai[bot]",
        "the review bot that left on 2026-09-04 — its comments outlive it in every\n"
        "old capture, and none of them is a second reader either way",
    ),
    (
        "a_blank_author",
        "",
        "an author field that arrived empty names nobody (control #16); it is the\n"
        "state `repr()` exists for, since `'' in reason` is vacuously true",
    ),
    (
        "an_author_longer_than_any_login",
        "r" * (MAXIMUM_LOGIN_LENGTH + 1),
        "#408 F1: 40 characters is longer than any account GitHub issues, so the\n"
        "string names nobody — and still must not veto somebody who does",
    ),
    (
        "the_prs_own_author_wearing_a_badge",
        "nuncaeslupus (OWNER)",
        "#408 round 5's weld, and the LOSING BRANCH'S RISK made a control: this IS\n"
        "the implementer under a spelling that resolves to nobody. Their marker\n"
        "clears nothing; the clearance that stands is a different, resolvable\n"
        "account's, which is what the rule requires of a second reader",
    ),
)


def _scope_states() -> tuple[ScopeState, ...]:
    """T155's states: an unattributable marker beside a genuine clearance.

    Every pairing is built **in both comment orders**, because the defect fired
    on the presence of the unattributable author and not on where it sat — a fix
    that only looked at the first marker, or only at the last, would pass one
    order and fail the other.
    """
    rule = "CLAUDE.md § The review half of `merge-policy` is a second session, not a bot"
    code = ("src/integral/thing.py",)
    docs = ("arsenal/session/handover.md",)
    cleared = Comment(
        "reviewer", f"Read the diff. Two findings, both answered.\n\n{marker_line(_HEAD)}"
    )
    objected = Comment("other-reader", f"One finding stands.\n\n{marker_line(_HEAD, 'BLOCK')}")
    stale = Comment("reviewer", f"Read the diff at the time.\n\n{marker_line(_OLDER)}")
    own = Comment("nuncaeslupus", f"Answered the findings.\n\n{marker_line(_HEAD)}")

    def echo(who: str, verdict: str = "CLEAR", head: str = _HEAD) -> Comment:
        return Comment(who, f"Automated summary of this thread.\n\n{marker_line(head, verdict)}")

    def orders(
        unattributable: Comment, *rest: Comment
    ) -> tuple[tuple[str, tuple[Comment, ...]], ...]:
        """The same comments with the unattributable marker at each end.

        Both orders, always: F3's guard fired on the presence of the author and
        not on its position, so a fix reading only the first or only the last
        marker would pass one of these and fail the other.
        """
        return (
            ("unattributable_first", (unattributable, *rest)),
            ("clearance_first", (*rest, unattributable)),
        )

    states: list[ScopeState] = []
    number = 101

    for label, who, why in _UNATTRIBUTABLE_AUTHORS:
        for order, comments in orders(echo(who), cleared):
            states.append(
                ScopeState(
                    f"{label}_beside_a_clearance__{order}",
                    PullRequest(number, "nuncaeslupus", _HEAD, code, comments),
                    ALLOWED,
                    0,
                    who,
                    CLEARANCE_STANDS,
                    f"{rule}: a PR may merge once a session OTHER THAN ITS IMPLEMENTER has\n"
                    f"read it and reported — {why}",
                    order,
                )
            )
            number += 1

    for label, who in (("github_actions", "github-actions[bot]"), ("a_blank_author", "")):
        for order, comments in orders(echo(who, "BLOCK"), cleared):
            states.append(
                ScopeState(
                    f"an_unattributable_BLOCK_from_{label}__{order}",
                    PullRequest(number, "nuncaeslupus", _HEAD, code, comments),
                    UNRESOLVABLE,
                    2,
                    who,
                    CLEARANCE_SET_ASIDE,
                    "this module's own rule, in the D-28 list above and older than #421:\n"
                    "the exemption — and by the same asymmetry a clearance — is for a PR\n"
                    "nobody objected to, never over an objection somebody raised. That\n"
                    f"carve-out is NOT spelled out by {rule},\n"
                    "which is why it is cited here as ours.\n"
                    "An objection this reader cannot attribute is not a pass, so the one\n"
                    "direction in which an unattributable marker still decides the set is\n"
                    "the fail-closed one",
                    order,
                )
            )
            number += 1

    for order, comments in orders(echo("github-actions[bot]", "CLEAR", _OLDER), cleared):
        states.append(
            ScopeState(
                f"an_unattributable_marker_for_another_commit__{order}",
                PullRequest(number, "nuncaeslupus", _HEAD, code, comments),
                ALLOWED,
                0,
                "github-actions[bot]",
                CLEARANCE_STANDS,
                "t-41fda10d: a marker on the wrong commit binds nothing, and one that\n"
                "also names nobody binds nothing twice — it does not make the PR stale\n"
                "(code 3) either, because there is no report to be stale ABOUT",
                order,
            )
        )
        number += 1

    for order, comments in orders(echo("github-actions[bot]"), cleared, objected):
        states.append(
            ScopeState(
                f"a_resolvable_reader_blocked_the_same_head__{order}",
                PullRequest(number, "nuncaeslupus", _HEAD, code, comments),
                BLOCKED,
                1,
                "github-actions[bot]",
                CLEARANCE_SET_ASIDE,
                f"{rule}: a BLOCK from a second session is the objection the whole rule\n"
                "is for; the bot's marker changes nothing in either direction, and the\n"
                "reason still has to say what became of the clearance beside it",
                order,
            )
        )
        number += 1

    for order, comments in orders(echo("github-actions[bot]"), cleared):
        states.append(
            ScopeState(
                f"a_docs_only_pr_a_second_reader_cleared__{order}",
                PullRequest(number, "nuncaeslupus", _HEAD, docs, comments),
                ALLOWED,
                0,
                "github-actions[bot]",
                CLEARANCE_STANDS,
                f"{rule}: docs-only PRs are exempt, and a report is stronger evidence\n"
                "than the exemption — a docs PR that WAS read reads as read, not as\n"
                "unreadable because a bot commented on it",
                order,
            )
        )
        number += 1

    # ── The residuals of T155's own defect, accepted from #421 (F1-F3) ───────
    # Check 5 used to sit ahead of the three branches below, so a bot's name
    # turned a stale report's code 3 into a 2, withheld an exemption CLAUDE.md
    # grants outright, and shadowed the author's-own-marker reason with a
    # sentence that was false on its face ("the only marker on record", beside a
    # second marker). All three are the shape T155 was filed to remove, surviving
    # one branch further down the function.

    for order, comments in orders(echo("github-actions[bot]"), stale):
        states.append(
            ScopeState(
                f"a_stale_genuine_report_beside_an_unattributable_marker__{order}",
                PullRequest(number, "nuncaeslupus", _HEAD, code, comments),
                BLOCKED,
                3,
                "github-actions[bot]",
                RECORDED_BUT_INERT,
                "t-41fda10d (#421 F1): 'reviewed, then kept coding' is a different\n"
                "situation from 'never reviewed', and both are hidden by a rollup that\n"
                "only shows a tick. Skipping the unattributable marker leaves a genuine\n"
                "report for another commit on record, which is stale — code 3. A bot's\n"
                "name must not turn 3 into 2",
                order,
            )
        )
        number += 1

    for order, comments in orders(echo(""), own):
        states.append(
            ScopeState(
                f"the_authors_own_marker_beside_an_unattributable_one__{order}",
                PullRequest(number, "nuncaeslupus", _HEAD, code, comments),
                BLOCKED,
                2,
                "",
                RECORDED_BUT_INERT,
                f"{rule} (#421 F3): the implementer never signs it off, and THAT is\n"
                "what a human reading this exit has to be told. Same code either way;\n"
                "the shadowed reason was strictly worse and, saying 'the only marker on\n"
                "record', factually false beside a second marker",
                order,
            )
        )
        number += 1

    states.append(
        ScopeState(
            "a_docs_only_pr_carrying_only_an_unattributable_marker",
            PullRequest(number, "nuncaeslupus", _HEAD, docs, (echo("github-actions[bot]"),)),
            EXEMPT,
            0,
            "github-actions[bot]",
            RECORDED_BUT_INERT,
            f"{rule} (#421 F2): 'Docs-only PRs are exempt — a handover or a task-file\n"
            "edit merges on green CI.' The exemption is a claim about the CHANGED PATHS\n"
            "and resolves no identity, so an author this reader cannot resolve is not\n"
            "evidence against it. See the module docstring for why this branch is taken\n"
            "in the fail-open direction rather than the conservative one",
            order="single",
        )
    )
    number += 1

    states.append(
        ScopeState(
            "a_docs_only_pr_an_unattributable_marker_objected_to",
            PullRequest(
                number, "nuncaeslupus", _HEAD, docs, (echo("github-actions[bot]", "BLOCK"),)
            ),
            UNRESOLVABLE,
            2,
            "github-actions[bot]",
            OBJECTION_HONOURED,
            "this module's own rule, stated in the docstring above and older than\n"
            "#421: 'Exemption applies to a PR nobody objected to, never over an\n"
            f"objection somebody raised' — the carve-out {rule} does NOT itself\n"
            "spell out, which is why it is cited here as ours. This is the BOUND on\n"
            "the state above — the exemption survives a marker naming nobody and does\n"
            "NOT survive one that objects, so the fail-open step F2 takes is exactly\n"
            "one state wide",
            order="single",
        )
    )
    number += 1

    states.append(
        ScopeState(
            "a_code_pr_carrying_only_an_unattributable_marker",
            PullRequest(number, "nuncaeslupus", _HEAD, code, (echo("github-actions[bot]"),)),
            UNRESOLVABLE,
            2,
            "github-actions[bot]",
            "so self-review cannot be ruled out",
            "t-41fda10d: check 5 still fires when its own sentence is true — nothing\n"
            "else IS on record. The control that stops F1-F3's remedy degenerating into\n"
            "deleting the guard: a marker naming nobody never becomes a report, and a\n"
            "code PR carrying only one has not been read",
            order="single",
        )
    )
    number += 1

    return tuple(states)


SCOPE_STATES = _scope_states()


def measure_marker_scope(states: tuple[ScopeState, ...] | None = None) -> dict[str, Any]:
    """T155's reading: `unresolvable_marker_authors_with_an_unrecorded_effect`.

    A state counts when its outcome is not the one the rule above requires **or**
    when the reason does not name the unattributable author and say what became
    of the clearance. The disjunction is load-bearing and was a conjunction until
    the second reader on #408 caught it: under `and`, the "refuse wholesale"
    answer scored zero over code nobody had changed, because that code already
    returned `unresolvable/2`. A gate satisfied by doing nothing is the defect
    this repository keeps meeting.
    """
    evaluated = SCOPE_STATES if states is None else states
    readings: list[dict[str, Any]] = []
    unrecorded: list[str] = []

    for case in evaluated:
        verdict = read(case.pr)
        outcome_ok = verdict.state == case.state and verdict.code == case.code
        named_ok = repr(case.unattributable) in verdict.reason
        effect_ok = case.effect in verdict.reason
        if not (outcome_ok and named_ok and effect_ok):
            required_may_proceed = case.state in {ALLOWED, EXEMPT}
            direction = (
                "fail-open"
                if verdict.merge_may_proceed and not required_may_proceed
                else "fail-closed"
            )
            missing = []
            if not outcome_ok:
                missing.append(f"the rule requires {case.state}/{case.code}")
            if not named_ok:
                missing.append(f"the reason does not name {case.unattributable!r}")
            if not effect_ok:
                missing.append(f"the reason does not say {case.effect!r}")
            unrecorded.append(
                f"{case.name}: {'; '.join(missing)} ({case.citation}); the reader answered "
                f"{verdict.state}/{verdict.code} — {verdict.reason} [{direction}]"
            )
        readings.append(
            {
                "state": case.name,
                "required": f"{case.state}/{case.code}",
                "observed": f"{verdict.state}/{verdict.code}",
                "names_the_unattributable_author": named_ok,
                "records_the_effect": effect_ok,
                "derived_from": case.citation,
            }
        )

    floor, breached = _floor(len(evaluated), MINIMUM_SCOPE_STATES)
    # What was actually handed to `read`, not what the labels claim. Two states
    # carrying the same input are one state measured twice (#421 F4), and a
    # count that cannot tell them apart is a coverage claim nobody checked.
    #
    # The key is every field `read` reads — author, head sha, files, comments —
    # and deliberately **not** `number`, a per-state counter that would make
    # distinctness true by construction. `case.name` is the same vacuity in a
    # second spelling, and it survived the entire suite until #421's N1 pinned
    # it, which is F4's own shape one level up, inside F4's remedy.
    #
    # Pinning two spellings one at a time is not pinning the class, and #421's
    # N3 measured the gap: with the name pinned and `number` argued against in
    # this very comment, THREE further keys still passed all 148 tests with a
    # serene zero and exit 0 — adding `number`, keying on the whole
    # `PullRequest` (the tidier spelling of "every field `read` reads", and so
    # the likeliest future refactor), and adding `order`. Each, composed with
    # F4's mutant, certified 29 states over 16 genuinely distinct inputs. Being
    # right about `number` in a comment is not the same as testing it.
    #
    # So the bound is stated as the class instead of as a list of spellings:
    # `..._varying_every_field_read_does_not_read_is_one_state` twins a state
    # across EVERY non-input field at once — derived from the dataclasses, not
    # enumerated, so a field added later is varied without anyone remembering
    # to — while holding the input identical and proving it identical by
    # `read`ing both. Any key that reads a label, an expectation or a counter
    # counts that twin as new; this key counts it as the repeat it is.
    # `..._is_not_the_same_state` bounds the opposite side: a key too narrow to
    # see the author.
    inputs = ((c.pr.author, c.pr.head_sha, c.pr.files, c.pr.comments) for c in evaluated)
    distinct = len(set(inputs))
    distinct_floor, distinct_breached = _floor(distinct, MINIMUM_DISTINCT_SCOPE_STATES)
    record: dict[str, Any] = {
        "unresolvable_marker_authors_with_an_unrecorded_effect": len(unrecorded),
        "marker_scope_states_at_least": floor,
        "distinct_constructed_states_at_least": distinct_floor,
        "rule": (
            "an unattributable marker clears nothing and vetoes nothing, and every "
            "verdict beside one says what became of the clearance"
        ),
        "gate_status": "measured",
        "states_with_an_unrecorded_effect": unrecorded,
        "readings": readings,
    }
    breaches: list[str] = []
    if breached:
        breaches.append(
            f"marker_scope_states_at_least: {len(evaluated)} states evaluated, "
            f"floor is {MINIMUM_SCOPE_STATES}"
        )
    if distinct_breached:
        breaches.append(
            f"distinct_constructed_states_at_least: {len(evaluated)} states collapse to "
            f"{distinct} distinct constructed inputs (author, head sha, files, comments), "
            f"floor is {MINIMUM_DISTINCT_SCOPE_STATES} — states that are not distinct are "
            "one state measured twice"
        )
    if breaches:
        record["unresolvable_marker_authors_with_an_unrecorded_effect"] = -1
        record["gate_status"] = "unmeasured"
        record["unmeasured_reason"] = "; ".join(breaches)
    return record


def write_scope_evidence(evidence: Path | None = None) -> dict[str, Any]:
    """Measure, then record `status/evidence/T155.json` — in that order (#297)."""
    path = DEFAULT_T155_EVIDENCE_PATH if evidence is None else evidence
    measured = measure_marker_scope()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


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


def scope_exit_code_for(record: dict[str, Any]) -> int:
    """T155's half of the exit status — 0 measured and clean, 1 anything else.

    Never 3, for `exit_code_for`'s reason: a reader that cannot say what an
    unattributable marker did to a clearance is one whose verdicts nobody can
    audit, and `make evidence` records a 3 and continues.
    """
    if record["gate_status"] != "measured":
        return 1
    return 1 if record["unresolvable_marker_authors_with_an_unrecorded_effect"] else 0


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

    # T155's record is written by the same invocation `make evidence` already
    # makes: one module, two gates, like `repo_gate`'s four. A second module
    # would have had to import this one to reach `read`, and the reader whose
    # behaviour is being measured must be the one that ships.
    scope = write_scope_evidence()
    print(json.dumps(scope, ensure_ascii=False))
    for reason in scope["states_with_an_unrecorded_effect"]:
        print(reason, file=sys.stderr)
    if scope["gate_status"] != "measured":
        print(scope["unmeasured_reason"], file=sys.stderr)

    return exit_code_for(measured) or scope_exit_code_for(scope)


if __name__ == "__main__":
    raise SystemExit(_main())
