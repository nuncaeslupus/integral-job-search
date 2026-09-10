"""T46 — details asked at the point of use, per-use episode approval, the send boundary.

Three rules from spec step 11 and §6.2, each made mechanical rather than
remembered:

**Personal details are asked here, for this document.** Date of birth, address,
telephone, the name to print — none of them improve a *search*, so gathering
them at Intake is collecting something months before anything needs it. They are
written into the version directory of the document that required them
(`cv/generated/<offer_id>/v<N>/personal.json`) and never into `cv/master.json`.

**A story-bank episode reaches an employer-bound document only with per-use
approval.** Recounting a failure to the tool was never consent to send it to a
company. An approval names `(offer_id, version, text)` — **the text, never a
list position**. A store index is a fact about the order of a list the candidate
edits; inserting an unrelated episode above an approved one used to invalidate
the approval, and editing one used to leave the old approval sitting there. What
was approved is a sentence, and the sentence is what goes to the employer.

**An approval cannot outlive the evidence it was granted over (D-24).** Retracting
an episode is how a candidate withdraws the thing the approval was given over, and
the approval used to survive it: `approvals.json` was the only thing consulted at
the send boundary, retraction never touched that file, and `record_sent`
re-measured against an unchanged approval and recorded the send. So
`measure_prepared` now subtracts `retracted_episode_texts` from what the approval
file backs. The subtraction, and not a store lookup — `retracted_episode_texts`
says why the log is read every time rather than a flag written when the retraction
landed, and why the join is deliberately coarse.

**No autonomous outward action.** Nothing here sends. `prepare` writes the
documents, the details to paste into the employer's form, and `payload.json` —
the summary of everything that would go. `record_sent` records that the
candidate sent it.

## What the gate measures, and how it can fail

`unapproved_episode_disclosures` counts **anything in a finished document that no
per-use approval backs**, over the files on disk. Three kinds, because there are
three ways a story reaches an employer:

1. a line no manifest row backs — unbackable is unapproved, and it is what an
   episode looks like after the candidate tidies it out of their story bank;
2. an episode line whose text no approval names;
3. an episode's **substance** carried by some other entry — a headline or a job
   description holding the same sentence. Detection is over normalised eight-word
   shingles, not an exact substring, because one character defeated the substring
   test while `payload.json` went on telling the candidate the story was
   withheld. A summary that is false is worse than no summary.

**What exempts an episode from that third sweep is a line the document carries,
never a row the manifest holds (T114).** The two part company the moment anything
edits a file after drafting, and the manifest is the half that cannot notice.
Deleting an episode line from `letter.md` used to leave its manifest row standing,
the row kept the episode exempt, and a headline carrying the same story sent it
with no approval behind it — `unapproved_episode_disclosures` 0, coverage 1.0,
over a document demonstrably disclosing it. Disclosure outliving its document,
which is D-24's shape on the other axis, and fail-open in the direction that
reaches an employer. The divergence is now reported in its own right as
`disclosures_unbacked_by_a_generated_document`, because `payload.json` is
assembled from those rows: a row over a line nothing carries is this tool
describing a letter it is not looking at, which is the same false summary.

**A paraphrase walks past the shingle, and the fix is to stop the sweep from
lying about it, not to chase the paraphrase (T156).** `_carries`'s own
docstring says the limit plainly: eight-word shingles beat punctuation,
spacing, case, truncation and extension, and "it does not beat a genuine
paraphrase, and nothing cheap does." Before this task the sweep acted as
though it *had* beaten one — an episode neither disclosed by a manifest row
nor shingle-matched anywhere on the page was folded into `episodes_withheld`,
a name that promises "not on this page" over a check that can only promise
"no eight-word window of it is on this page." Those are different claims, and
CLAUDE.md's fixtures section names exactly this shape: a gate whose fixtures
were derived from what the code already does rather than from the spec is
green over the wrong thing, and here the code was answering a question
(is this episode's *text* present?) that the module's own promise (does this
*substance* reach an employer?) never asked.

Two answers were open, and only one is taken — and this section was rewritten
once already, because the first cut of "report undecidability" was itself a
second detector wearing that name, and the second-reader round on #435 (C1-C5)
measured exactly why that failed:

1. *Detect more* — spend the docstring's named upgrade path, or a cheaper
   stand-in for it, so the sweep can call a paraphrase a paraphrase. **Rejected**,
   and the module's own words are the reason: "nothing cheap does" beat a
   genuine paraphrase, so a cheap stand-in cannot deliver the confident verdict
   this sweep exists to give — it can only ever be a different wrong confidence,
   traded for the current one. This is no longer only an argument: the first
   version of this fix built exactly such a stand-in (`_plausible_paraphrase`,
   a normalised-word-overlap test with two tuned floors) and a second reader
   measured it end to end. It caught **0 of 8** constructed genuine paraphrases
   — overlap was exactly 0 on all eight, because a paraphrase is *by
   definition* a substitution of the content words, so the overlap it leaves
   behind is empty — and flagged a large share of innocent same-domain
   documents that retold no substance at all, because two documents about the
   same kind of work *by definition* share their content words: a second
   reader's own thirty constructed innocents (round 5, #435) scored **0 of 30**
   built as single sentences and **30 of 30** built as full paragraphs, with no
   committed corpus fixing which shape is representative — the number this
   paragraph asserted before that round (21 of 30) did not reproduce against
   either construction and is not repeated here for that reason (F-4, round
   6). What *does* reproduce in both constructions, and is what this paragraph
   actually rests on: the overlap a same-domain innocent leaves behind is
   never small enough to distinguish from a paraphrase's own overlap, in
   either direction. Both failures come from the same fact, so no choice of
   thresholds fixes one without the other: a word-overlap proxy is not weakly
   correlated with paraphrase, it is anti-correlated with it. **The recorded
   risk of not taking this path**: the
   docstring's named upgrade (an embedding comparison, at a model call per
   episode per document) is the only thing that could ever tell a paraphrase
   from a shared subject, and it is still not built; nothing here claims
   otherwise.
2. *Report undecidability, unconditionally* — **taken**. Not "detect more
   cheaply, then call the residue undecidable" — that is answer 1 with an extra
   step, and it is what the rejected first cut actually was. The rule instead
   needs no constant and derives directly from `_carries`'s own limit: `_carries`
   can *confirm presence* (a shingle matched) and can never *confirm absence*
   (nothing cheap beats a paraphrase, so a shingle miss proves nothing about
   whether the substance is there some other way). An episode that is neither
   manifest-disclosed nor shingle-matched is therefore a case this sweep has
   **no evidence about**, full stop — not a case in some vocabulary-overlap
   band and not a case outside it. So every such episode enters the third
   state, `episodes_undecidable`, uniformly, and the old `episodes_withheld`
   field is retired rather than kept at whatever it now computes to (see the
   "second, sharper risk" below for why keeping it would itself be the family
   this repository keeps finding). Reported in `payload.json`, and named in
   the boundary's refusal message when a refusal
   fires for another reason, precisely because it is not itself a refusal —
   §6.2 asks this module to stop drafting or recording a send over a *known*
   unapproved disclosure, and an undecidable case is not known to be one. This
   is the reading CLAUDE.md's fixtures section calls the durable half of a fix:
   it converts a silent fail-open (a false "withheld") into a visible one (an
   honest "cannot tell"), rather than trading it for a second false confidence
   dressed up as caution. **The recorded risk of taking this path**: an
   undecidable case does not stop `prepare` or `record_sent` by itself, so a
   paraphrase still reaches the employer on the candidate's own say-so — this
   converts the silence into a visible flag for a human to weigh, it does not
   convert it into a refusal. That is the same trade the module already makes
   at the boundary of what §6.2 can check by text at all (see "What this
   boundary is, and what it is not" below): this file stops one step short of
   sending regardless, and an honest "undecided" is a stronger thing to hand
   the candidate at that step than a wrong "withheld" was. **A second, sharper
   risk this design accepts on purpose**: because the rule is unconditional,
   almost every episode not manifest-disclosed now lands in `episodes_undecidable`
   rather than in any "confirmed absent" bucket, since almost nothing on a real
   page is a verbatim eight-word match for prose nobody wrote to match it. A
   `episodes_withheld` field kept in the schema after this change could
   therefore only ever read at or near zero — a metric that cannot move with
   its own inputs is precisely the "metric independent of its own inputs" face
   CLAUDE.md's fixtures section names, so the field is deleted rather than kept
   at a number that would look like a measurement without being one. That is
   the honest size of what a shingle test alone can prove about absence: almost
   none, and a module that says so plainly is worth more than one asserting a
   number it cannot support.

**A third-round finding, fixed rather than left open, and fixed again in round
four.** The "confirmed present" check above (`elif _carries(..., episode.text)`)
was matching against *every* written line, including lines backed by a
**different, approved** episode's own rendered text. An unapproved episode
sharing an eight-word window with somebody else's approved sentence therefore
read as "confirmed present" and was cleared from every channel — not a
finding, and not `episodes_undecidable` either, a worse fail-open than an
honest "undecided" would have been. Round three narrowed the check's target
from every written line to the *unbacked* ones — the ones that actually
produced a finding — but still joined them with `"\n"` before searching, which
carries its own seam: joining a *subset* of lines can put two that were never
adjacent on the page next to each other in the joined text, and a shingle can
straddle that manufactured boundary. `_words` treats a newline as ordinary
whitespace, so nothing about the join stops this. That is fail-open in exactly
the same direction as the original defect — a shingle formed only by the join,
naming no real episode substance on the page, still clears the check — and it
was round three's own claim that this could only *remove* a match, never
manufacture one, which was not true. Round four narrowed the check to
`any(_carries(line, episode.text) for line in unbacked)`, one real, whole
line at a time, with no join and no seam to straddle there — but round four's
own claim that this "closes it rather than bounds it" was itself one layer
short (R5-1, round five). `unbacked` is populated by a **Counter** test
(`backed[key] == 0`), never a text test, so it can hold a line whose *text* is
an **approved** episode's own rendered sentence — duplicated on the page with
nothing left to back the second copy, or left behind after the manifest claim
that would have backed it is deleted while the approval and the rendered line
both stay on disk (T114's class of post-draft edit, applied to this seam
instead of to the disclosure sweep). Either way the round-four check still
read that approved wording as "confirmed present" for a *different*,
unapproved episode sharing its shingle window, and cleared it from both
channels exactly as the original, round-three defect did. Round five closes
it with `... for line in unbacked if line not in approved`: the same
per-line, no-join discipline round four established, with `unbacked` itself
never again searched while it still carries a text `approved` already backs.
`intact` (`surviving`, above) still joins the way round three's fix did, and
still carries that seam — in the *opposite*, fail-closed direction (a
manufactured match there adds an unearned finding and blocks an otherwise
clean draft), which is the docstring's named upgrade path to close, not a risk
this branch's fix owed on its own.

**Round five's own fix was one layer short, and it is the same layer every
time (R6, round six, #435).** `if line not in approved` is an **exact-text**
test standing guard in front of `_carries`, which is a **normalised-shingle**
predicate — the same "proxy for the property, rather than the property" shape
CLAUDE.md's fixtures section names, one level further in. Two routes reach the
identical outcome round five closed the first two of: **(R6-1)** a line one
edit away from an approved sentence — the trailing punctuation, casing,
inserted punctuation, an appended clause, or doubled whitespace that
`_carries`'s own docstring already says beat a plain comparison — is not
`in approved` by byte equality, so it is searched again and clears an
unapproved twin sharing its shingle exactly as before round five; **(R6-2)** a
D-24 retraction removes the text from `approved` with **no document edit at
all** (`approved -= withdrawn`, above), so the still-rendered line stops being
excluded and clears the twin the moment the candidate withdraws the very
episode it was standing in for. Both are measured, not argued: five near-copies
and one retraction, each independently confirmed to clear
`_FIXTURE_TWIN` from both `unapproved_episode_disclosures` and
`episodes_undecidable` before this fix, and each pinned as its own state in
`probe_paraphrase_undecidability` (states 16-21) after it.

Round six's fix asked the question the exact-text guard was standing in for
instead of a sixth way to spell "this text, near enough": *whose* evidence is
this line? `unbacked` was searched for `episode.text` only when **no other
episode's text** also shingle-matched the same line — a relation over
`master.episodes`, not a membership test against `approved`. The docstring
argued this needed no set to stay synchronised with, "so nothing that later
shrinks `approved` (a retraction) or fails to widen it (a near-copy) can
reopen the seam" — true of `approved`, and `approved` was the wrong set to
worry about. `master.episodes` is the list the candidate edits directly, and
tidying a story out of the bank after the draft was written — the very edit
`measure_prepared`'s own docstring names as the hole T114 exists to close —
removes the rival the relation needed, which is a check pinned against
*whichever episodes happen to still be in the bank*, not against whose
evidence the line actually is.

**Round six's own fix was one layer short, in the same shape as round five's
(R7-1, round seven, #435).** Two of the six states it committed regress the
moment the authoring episode is edited out of `master.episodes` after
drafting — the duplicated-line and manifest-row-deleted states (14, 15)
replayed with `win` additionally removed from the bank — because `approved`
still names `win`'s text after a bank edit and `master.episodes` no longer
does; the numerator these two states feed goes from correct to cleared. A
third state was never closed by either round: a single-episode bank has no
rival by construction, so a hand-added line sharing an eight-word window with
the one episode in the bank clears it with zero approvals and zero edits at
all — not a regression, since round five clears it too, but the same root.

**What closes it is removing the rival check, not repairing it.** The reason
every round from three through six needed one is that `_carries` is a
*shingle* predicate — satisfied by any overlapping eight-word window — and a
shingle window is exactly the thing two *different* sentences can share
(win's own near-copies; win and the twin that overlaps it by construction).
Confirming a *specific* episode from a test built to detect mere presence was
always going to need a second test to rule out the sentence actually
belonging to somebody else, and every rival set tried so far — `approved`,
`master.episodes` — was a live, editable proxy for "who wrote this," rather
than the thing itself. `_normalised_equal(line, episode.text)` asks a
stronger question that a *different* sentence cannot answer by coincidence
the way an overlapping window can: is this the *same whole run of words*,
end to end, once normalised the way `_carries` already normalises one? — this
was round seven's own claim, and R8 below shows the normalisation it relied
on was not safe to reuse. Win and the twin never pass this together, however
much of their opening words they share, because their final words differ. A
match here is therefore trustworthy on its own — it needs no rival, no
`approved`, no `master.episodes`, and no retraction, because none of those
can make two distinct sentences equal and none of them is needed to keep two
distinct sentences apart. This is CLAUDE.md's *"a closed rule rather than a
twin"* answer applied one level further in than round six's: not a
better-sourced rival set, but no rival set. Nine states already pinned in
`probe_paraphrase_undecidability` (12, 14-15, 16-21) must still resolve
correctly under it, and three more (R7-1's) are added: the two regressions
replayed with the bank additionally edited, and the single-episode state
neither round five nor round six closed.

**Round seven's own fix was one layer short too, and it was the layer
underneath "no rival set" rather than another rival (R8, #435 round 8, F-1).**
"Once normalised the way `_carries` already normalises one" was the mistake:
`_carries`'s normaliser (`_words`) does not merely fold case and spacing, it
**deletes** every non-word (`\\W`) character, and deletion is not safe to reuse for an
*equality* test the way it is for a *presence* test. Two sentences that
assert opposite things — `Gross margin moved +12%…` and `…-12%…` — reduce to
the identical word run once the sign is deleted, so `_normalised_equal`
called them equal, and an approved achievement's own line silently cleared
an unapproved failure episode about the same metric: fail-open, and a
regression against round 3's own N2 fix in miniature, since it is again one
episode's rendered line confirming a *different* episode. The second-reader's
own report (#435 F-1) named this a class — seven constructed pairs, not one —
and F-2 found why no round had caught it: instrumented across the whole
24-state probe, `_normalised_equal` was asked to return `True` exactly
twice, both byte-identical, so no committed state had ever exercised the
normalisation the docstring above described. `_normalised_equal` now folds
only case and a run of whitespace — see its own docstring — which costs the
near-copy tolerance the paragraph above claimed (a dropped period or an
inserted comma no longer self-matches; it falls through to `undecidable`
instead, the fail-closed side of the same trade) and buys back the ability
to tell `+12%` from `-12%`. Four more states are added for this round: R8-1's
three (25-27) replay 14, 15 and 21 with a sign-flipped pair in place of the
shingle-overlap twin, and R8-2's one (28) is the positive direction F-2 named
missing — a genuine case/whitespace near-copy this function must still
confirm, pinned rather than only asserted.

**Two messages this rule prints were also false where they sit, both found
and fixed the same round (F-3, F-4).** `undecidable_episodes`' explanatory
text chooses between two sentences depending on whether any *unbacked* line
shares an eight-word window with the episode — but state 12 (round 3's own
N2 fixture) has exactly one page-wide shingle match, an *approved* line,
which is backed and therefore invisible to a scan of `unbacked` alone: the
message said "no shingle match confirms it present anywhere on the page"
over a page that had one. The scan for this message now covers every claim
line on the page, backed or not (`all_lines`), so "anywhere on the page"
means what it says; the *confirm* branch above is unchanged and still
excludes approved lines, for the reason N2 already established. The other
message said a shingle match "is not this episode's own wording" whenever
equality failed — true when the match belongs to someone else, false when
the line is the episode's own sentence with a clause appended (round six's
own state 19 calls that construction a near-copy), since failing whole-run
equality only ever proves "not identical," never "unrelated." Reworded to
the claim the branch actually supports: not confirmed as the same wording,
word for word.

**The three sites that must all name an undecidable episode in a refusal are
pinned by a rule, not by three separate tests.** `prepare`'s raise, `record_sent`'s
raise, and `_refuse_unbacked_disclosures`'s raise (called from both) each append
`_undecidable_suffix(measured)`; a fourth `raise ApprovalError(...)` added later
that constructs its message from `measured` and forgets the suffix is caught by
`test_every_raise_site_over_measured_names_the_undecidable_episodes` in
`test_substance_sweep.py`, which parses this module's own source and asserts the
property structurally over every such site, present or future, rather than
naming three functions by hand.

**The measurement cannot construct both sides of its own equality.** `measure()`
writes approvals and documents in one call from one tuple, so they agree by
construction: on its own it proves only that `generate` emits the indices it was
handed, and every check in this module could be deleted with the evidence
unchanged. `probe_boundary` is the other half — ten scenarios that are defects on
purpose, each asserting the boundary *catches* it. `_main` fails if any probe
fails or if fewer than `MINIMUM_PROBES` ran.

## What this boundary is, and what it is not

`generate` renders an episode only when handed one, and `integral.approval` is
its only supported caller — but a keyword argument inside a package is a
convention, not a lock. What is enforced is that **nothing is drafted or
recorded as sent while an unapproved disclosure is in the document**: `prepare`
re-reads what it just wrote and refuses to write a payload over a finding, and
`record_sent` re-runs the whole measurement against the files as they stand at
send time — so a document edited after drafting is caught at the boundary, not
trusted because it was clean an hour ago.

**It is not a chokepoint on sending, and this file cannot be one.** §6.2 and
step 11 both stop one step short of sending: what the tool produces is
`cv/generated/<offer>/v<N>/letter.md` and the text to paste, and the candidate
presses send. So the file on disk *is* the send, and `record_sent` is
bookkeeping after the fact. A retraction that lands after drafting is caught
here — nothing further will draft or record — while the already-written letter
still carries the withdrawn story, because `retraction.purge_derived_citations`
scans `{profile, rankings, extractions, annotations}` and not `cv/generated`.
Purging it is **D-26**, and is deliberately not done here: a version already
named in `applications/` is the only record of what was actually sent, and §7
makes it immutable, so the purge has to skip those and that is a task, not a
line.

**What the confirmation proves, and what it does not.** `record_sent` requires
the payload's own digest, which pins *which* payload was named — a standing "send
whatever you like" and a yes given to a different draft both fail it. It says
nothing about *who* named it: anyone holding the payload can compute the digest,
and `measure()` does exactly that. Consent by a human is outside what this file
can check; what it can check is that consent was given to a specific, complete,
unchanged payload, and that is what it checks.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from integral.cv_store import (
    ConversationTurn,
    CVMaster,
    Episode,
    Experience,
    Skill,
    SourcedText,
    _atomic_write_json,
    write_master,
)
from integral.generate import (
    DEFAULT_FIXTURE_MASTER,
    Manifest,
    _claim_lines,
    _entries,
    generate,
    read_manifest,
    render_entry,
)
from integral.identity import ProfileStore, create_profile
from integral.profile import EVIDENCE_PARTS, EvidenceLog, Kind, ProfileError

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T46.json"
DEFAULT_D24_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-24.json"
DEFAULT_T114_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T114.json"
DEFAULT_T156_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T156.json"

SCHEMA_VERSION: Literal[1] = 1

# What "a personal detail" means here. Spec step 1 forbids every one of them at
# Intake by name; step 11 is where they are asked for, for the document being
# produced.
PERSONAL_FIELDS: tuple[str, ...] = (
    "full_name",
    "email",
    "phone",
    "postal_address",
    "date_of_birth",
)

# How many consecutive normalised words make a match. Long enough that no two
# unrelated sentences share one by accident; short enough to survive the edits
# that defeated a plain substring test.
_SHINGLE = 8


class ApprovalError(Exception):
    """An approval was missing, was for something else, or was not per-use."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PersonalDetails(Strict):
    """Asked at step 11, for one document, and stored beside that document.

    Only `full_name` is required — it is the one thing every employer's form
    needs. The rest are asked for when this employer's form asks for them, and
    a detail nobody asked for is simply absent.
    """

    full_name: str = Field(min_length=1)
    email: str | None = None
    phone: str | None = None
    postal_address: str | None = None
    date_of_birth: str | None = None

    def stated(self) -> dict[str, str]:
        """The details actually given, by field name."""
        return {field: value for field in PERSONAL_FIELDS if (value := getattr(self, field))}


class EpisodeApproval(Strict):
    """One episode's text, cleared for one document.

    No index. See the module docstring: a position in a list the candidate edits
    is not a stable name for a sentence, and the sentence is what goes out.
    """

    offer_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    text: str = Field(min_length=1)


class Approvals(Strict):
    """`cv/generated/<offer_id>/v<N>/approvals.json` — what this version may say."""

    schema_version: Literal[1] = SCHEMA_VERSION
    offer_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    episodes: tuple[EpisodeApproval, ...] = ()


class Payload(Strict):
    """`cv/generated/<offer_id>/v<N>/payload.json` — everything that would go.

    Not "shall I apply?" but the actual contents: the files, every claim in
    them, the episodes cleared for this one letter, the contact details, and to
    whom. It is written; it is never sent. It is also never written over a
    finding, so what it says about what is being sent is true.

    `undecidable_episodes` is T156's third state: not a finding — nothing here
    is written over one of those — but not a clean bill of health either. A
    payload with a non-empty tuple here is a promise this module can only half
    keep, and it says so rather than rounding to "withheld".
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    offer_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    recipient: str = Field(min_length=1)
    documents: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    episodes: tuple[str, ...] = ()
    contact_details: dict[str, str] = Field(default_factory=dict)
    undecidable_episodes: tuple[str, ...] = ()


def payload_digest(payload: Payload) -> str:
    """The name of this exact payload. What the candidate confirms is *this*."""
    body = json.dumps(payload.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _version_parts(offer_id: str, version: int) -> tuple[str, ...]:
    return ("cv", "generated", offer_id, f"v{version}")


# ---------------------------------------------------------------------------
# detection — normalised, because one character defeated the exact match

_NOT_WORD = re.compile(r"\W+", re.UNICODE)


def _words(text: str) -> list[str]:
    # NFC first, or `\W+` splits a decomposed `í` into `i` plus a combining mark
    # and every shingle around it differs from the composed spelling of the same
    # word. ES/EN/CA are supported identically, so a text that arrives decomposed
    # — which is what a paste from some editors and macOS filesystems gives —
    # must compare equal to the composed one (#305 review, D-4).
    return _NOT_WORD.sub(" ", unicodedata.normalize("NFC", text.casefold())).split()


def _carries(document: str, episode: str) -> bool:
    """Does `document` carry this episode's substance?

    ponytail: normalised eight-word shingles. Beats punctuation, spacing, case,
    truncation and extension — the edits that walked past a plain substring
    test. It does not beat a genuine paraphrase, and nothing cheap does; the
    upgrade path is an embedding comparison, at a model call per episode per
    document.
    """
    words = _words(episode)
    if not words:
        return False
    # Both sides padded, so a match consumes **whole** normalised words. Without
    # it a one-word episode ("Python") matched any longer word containing it
    # ("Pythonista"), and since `prepare` refuses to write a payload over a
    # finding, that is a draft blocked for content that is not the episode.
    body = f" {' '.join(_words(document))} "
    if len(words) <= _SHINGLE:
        return f" {' '.join(words)} " in body
    return any(
        f" {' '.join(words[start : start + _SHINGLE])} " in body
        for start in range(len(words) - _SHINGLE + 1)
    )


def _normalised_equal(line: str, episode: str) -> bool:
    r"""Is `line` this episode's own wording — the same whole run of words,
    not merely the same content?

    T156's R8 fix (#435 round 8, F-1). R7 answered this with
    `_words(line) == _words(episode)` — `_carries`'s own tokeniser, which is
    NFC-fold, casefold, then **delete** every `\W` character. Deletion is
    exactly the operation an equality test cannot afford: it strips the sign
    off a percentage, the colon out of a ratio, the hyphen out of a range,
    the `?` off a question, so two sentences that read as opposites reduce to
    the identical word run and pass here as one episode's own wording. The
    round-7 second-reader's own report (#435 F-1) measured this directly —
    `Gross margin moved +12%…` and `…-12%…` — and named it a class, not a
    case, with seven constructed pairs (`+12%`/`-12%`, `3:1`/`3 1`, `40%`/`40`,
    `10-20`/`10 20`, `We shipped it`/`We shipped it?`, a comma splice, an
    arrow-vs-space range): `Episode.kind` names `"number"` as a first-class
    kind, so a numeric claim is squarely this module's business, not an edge
    case it can decline.

    So this folds only what provably cannot change what a sentence says —
    case (`casefold`), decomposed-vs-composed spelling (NFC, D-4's reason),
    and a run of whitespace collapsed to one space — and deletes nothing.
    Every other character, including ordinary sentence punctuation, is kept
    exactly as written, on purpose: CLAUDE.md's closed-rule discipline is
    "normalise only what cannot carry meaning," and there is no non-enumerated
    way to name a punctuation mark that never carries it — the round-7 report
    found the eighth pair the moment the fifth was named, so no seventh is
    named here either. `_carries`'s own `_words` tokeniser is untouched: its
    job is *presence* over an eight-word window, where truncation and
    extension tolerance is a deliberate, named trade, not identity, which
    needs and must not take the same license.

    The accepted cost: a line edited only by dropping a trailing period,
    inserting a comma, or appending a clause no longer self-matches here, and
    falls through to the shingle-match branch below — `episodes_undecidable`,
    not a confirmed finding. That is the fail-**closed** direction this
    module already treats as the safe one (an honest "cannot tell" over a
    wrong "confirmed"), and every state pinned here before this round paid
    nothing for it: instrumented across the whole 24-state probe (#435 F-2),
    this function was asked to return `True` exactly twice, and both were
    byte-identical already — no committed state has ever depended on the
    tolerance this docstring describes, which is F-2's own finding and why a
    new state is pinned for it (below) rather than trusted to this prose.
    """

    def _fold(text: str) -> str:
        return " ".join(unicodedata.normalize("NFC", text.casefold()).split())

    return _fold(line) == _fold(episode)


def _squash(text: str) -> str:
    """Letters and digits only — a detail written a slightly different way."""
    return re.sub(r"[^0-9a-z]+", "", text.casefold())


def _undecidable_suffix(measured: dict[str, Any]) -> str:
    """T156: tell the boundary's refusal message which episodes are undecided.

    Called from every `ApprovalError` this module raises over `measure_prepared`'s
    output, so that a refusal fired for a *different*, confirmed reason does not
    stay silent about an undecidable episode sitting in the same draft — the
    module docstring's claim that the boundary is "told which one they got" is
    this line, not a description of behaviour that does not exist. Appending
    rather than raising on its own: an undecidable case is not itself a refusal
    (§6.2 only requires stopping over a *known* unapproved disclosure), so this
    never fires unless something else already has.

    Reads only `undecidable_episodes`, never `episodes_undecidable` — the two
    always agree in `measure_prepared`'s own output (one is `len()` of the
    other), but `measure()`'s aggregate dict carries a nonzero
    `episodes_undecidable` total with no `undecidable_episodes` list at all
    (F5, round 4: guarding on the count and then indexing the list `KeyError`s
    the moment anything hands this function that dict instead). Guarding on
    the list itself cannot desync from what it then reads.
    """
    episodes = measured.get("undecidable_episodes")
    if not episodes:
        return ""
    return " (also undecidable, not itself a refusal: " + "; ".join(episodes) + ")"


def _refuse_unbacked_disclosures(measured: dict[str, Any], consequence: str) -> None:
    """Stop at the boundary when the manifest names a disclosure no document carries (T114).

    A separate refusal from the unapproved-disclosure one above, and deliberately
    so: that one is about substance reaching an employer, this one is about the
    tool describing a document it is not looking at. Both stop the same two
    calls, because `payload.json` is assembled from the manifest's rows and a
    payload the candidate confirms has to be true about the files on disk.

    Over-refusing here costs a regeneration. Under-refusing means the candidate
    confirms a summary of a letter that no longer says what it says, which is
    the one direction §6.2 will not take.
    """
    if measured["disclosures_unbacked_by_a_generated_document"]:
        raise ApprovalError(
            f"the manifest records a disclosure this version's documents do not carry, "
            f"{consequence}: "
            + "; ".join(measured["unbacked_disclosures"])
            + _undecidable_suffix(measured)
        )


# ---------------------------------------------------------------------------
# preparing one application, and stopping short of sending it


def prepare(
    store: ProfileStore,
    master: CVMaster,
    *,
    offer_id: str,
    advert: str,
    recipient: str,
    details: PersonalDetails,
    asks: tuple[str, ...] = (),
    approved_episodes: tuple[int, ...] = (),
) -> Payload:
    """Draft the application for one advert and stop one step short of sending.

    `approved_episodes` indexes the store *now*, at the moment of drafting, and
    is resolved to text immediately — the recorded approval names the sentence.
    It authorises this draft and nothing else: the next regeneration is a new
    version and asks again.

    Raises `ApprovalError` — after the drafts are written, before any payload is
    — if the finished documents disclose anything no approval backs. There is
    then no payload, so there is nothing `record_sent` can act on.
    """
    manifest = generate(
        store,
        master,
        offer_id=offer_id,
        advert=advert,
        asks=asks,
        _approved_episodes=approved_episodes,
    )
    where = _version_parts(offer_id, manifest.version)
    approvals = Approvals(
        offer_id=offer_id,
        version=manifest.version,
        episodes=tuple(
            EpisodeApproval(offer_id=offer_id, version=manifest.version, text=text)
            for text in dict.fromkeys(master.episodes[index].text for index in approved_episodes)
        ),
    )
    _atomic_write_json(store, approvals.model_dump(mode="json"), *where, "approvals.json")
    _atomic_write_json(store, details.model_dump(mode="json"), *where, "personal.json")

    measured = measure_prepared(store, master, offer_id, manifest.version)
    if measured["unapproved_episode_disclosures"]:
        raise ApprovalError(
            "this draft discloses something no per-use approval backs, so no payload was "
            "written: " + "; ".join(measured["unapproved_episodes"]) + _undecidable_suffix(measured)
        )
    _refuse_unbacked_disclosures(measured, "so no payload was written")

    payload = Payload(
        offer_id=offer_id,
        version=manifest.version,
        recipient=recipient,
        documents=tuple(sorted(path.name for path in store.path(*where).glob("*.md"))),
        claims=tuple(f"{claim.document}: {claim.text}" for claim in manifest.claims),
        episodes=tuple(approval.text for approval in approvals.episodes),
        contact_details=details.stated(),
        undecidable_episodes=tuple(measured["undecidable_episodes"]),
    )
    _atomic_write_json(store, payload.model_dump(mode="json"), *where, "payload.json")
    return payload


def read_payload(store: ProfileStore, offer_id: str, version: int) -> Payload:
    path = store.path(*_version_parts(offer_id, version), "payload.json")
    return Payload.model_validate_json(path.read_text(encoding="utf-8"))


def read_approvals(store: ProfileStore, offer_id: str, version: int) -> Approvals | None:
    """The approval file for one version, or `None` if nothing approved anything."""
    path = store.path(*_version_parts(offer_id, version), "approvals.json")
    if not path.exists():
        return None
    return Approvals.model_validate_json(path.read_text(encoding="utf-8"))


def record_sent(
    store: ProfileStore,
    master: CVMaster,
    offer_id: str,
    version: int,
    *,
    confirms: str,
    sent_at: str | None = None,
) -> Path:
    """Record that the candidate sent this application. Nothing here sends it.

    The documents are re-measured against the approvals **as they stand now**,
    because a file can change between drafting and sending, and then the digest
    must name the payload on disk. See the module docstring for what that digest
    does and does not prove.
    """
    measured = measure_prepared(store, master, offer_id, version)
    if measured["unapproved_episode_disclosures"]:
        raise ApprovalError(
            "these documents disclose something no per-use approval backs, so nothing here "
            "is sendable: "
            + "; ".join(measured["unapproved_episodes"])
            + _undecidable_suffix(measured)
        )
    _refuse_unbacked_disclosures(measured, "so nothing here is sendable")
    payload = read_payload(store, offer_id, version)
    digest = payload_digest(payload)
    if confirms != digest:
        raise ApprovalError(
            f"the confirmation does not name this payload ({digest}) — approval is given "
            "once per application, over the payload that would actually go, and never "
            "as a standing permission"
        )
    parts = ("applications", offer_id, f"v{version}.json")
    if store.path(*parts).exists():
        raise ApprovalError(
            f"{offer_id} v{version} is already recorded as sent — an application record is "
            "immutable, because it is what the candidate answers questions about later"
        )
    record = {
        "schema_version": SCHEMA_VERSION,
        "offer_id": offer_id,
        "version": version,
        "confirmed_digest": digest,
        "sent_at": sent_at or datetime.now(UTC).isoformat(timespec="seconds"),
    }
    return _atomic_write_json(store, record, *parts)


# ---------------------------------------------------------------------------
# the measurement — reads the files, never the objects that wrote them


def _approved_texts(store: ProfileStore, offer_id: str, version: int) -> set[str]:
    """The episode texts an approval on disk backs for *this* document."""
    approvals = read_approvals(store, offer_id, version)
    if approvals is None or approvals.offer_id != offer_id or approvals.version != version:
        return set()
    return {
        approval.text
        for approval in approvals.episodes
        if approval.offer_id == offer_id and approval.version == version
    }


# Which retracted rows cannot be the story an approval names. An **exclusion**
# and not a whitelist of `episode`, because `add_conversation_entry` — the only
# production path putting an `Episode` into `cv/master.json` from a conversation
# — writes its row as `kind="statement"`, `step="intake"`, so a whitelist skipped
# the one path that matters (#305 review, D-2). A `constraint` is a fact about
# what would rule a job out, and a `retraction` row is bookkeeping about the log
# whose text ("Forget that.") is nobody's episode. Written as an exclusion so a
# kind added to `profile.Kind` later joins by default: that over-refuses, which
# §6.2 prefers, where a whitelist would fail open in silence.
#
# **`reaction` was in this set and is not any more** (#305 review, D-3, found by
# the second reader). It was excluded as "about an advert", which is the same
# reasoning that failed for `statement` in D-2: the kind names *which step wrote
# the row*, not *whether the text is a story*. Step 5 captures reactions raw —
# "extract afterwards — never ask them to categorise their own reaction" — so a
# reaction row is the candidate's unedited utterance in response to an advert,
# and a candidate reading a job ad routinely answers with the experience it
# reminds them of. Step 10 writes `reaction` rows too, which is *after* ranking,
# where narrating relevant experience is likeliest. `scoring.py` already reads
# `reaction` rows as trait-bearing evidence beside `episode` and `statement`.
#
# The direction decides it. An exclusion can only shrink `withdrawn`, and a
# smaller `withdrawn` permits more sends — so being wrong here is the fail-open
# §6.2 refuses, while being wrong the other way costs one over-refused episode.
# That is the same trade `_carries` already makes for duplicate text, and
# applying it to a `statement` but not to a `reaction` was the inconsistency.
_NEVER_A_STORY = frozenset({"constraint", "retraction"})


def _withdrawn_by(text: str, retracted: frozenset[str]) -> bool:
    """Does any retracted sentence carry this approval's substance, or vice versa?

    Not `text in retracted`. Byte equality let six single-character drifts —
    a trailing full stop, a curly apostrophe, a doubled space, casing, a normal
    form, and the raw utterance the polished sentence came from — each send a
    withdrawn story (#305 review, D-1). `_carries` is the same normalised
    eight-word shingle test the module already runs over documents, and it is
    checked both ways because either side can be the longer one: the log holds
    what the candidate said, the approval holds what was written down.

    It over-refuses on a short retracted row that turns up inside a longer
    approved sentence. That is the direction §6.2 asks for, and `_carries`
    returns `False` for an empty normalised text, so a whitespace-only row
    still withdraws nothing.
    """
    return any(_carries(text, row) or _carries(row, text) for row in retracted)


def retracted_episode_texts(store: ProfileStore, master: CVMaster) -> frozenset[str]:
    """Every episode sentence a live retraction has withdrawn (D-24).

    Read from the **log**, every time, rather than from a flag written into
    `approvals.json` when the retraction landed. The log is the only record that
    is always current: `unretract` puts a row back, `suppressed_ids` resolves the
    nesting, and a retraction written by any path at all — not only `retract` —
    is seen here. A mark stamped into the approval file at retraction time would
    have to be stamped by every writer and unstamped by `unretract`, and the one
    that forgot would fail open.

    Two ways a row reaches a sentence, because nothing joins them directly — an
    approval names `(offer_id, version, text)` and a retraction names a row id:

    * **the retracted row's own text**, matched by `_withdrawn_by` rather than by
      equality. A text match, so it cannot tell two rows carrying the same
      sentence apart and withdraws the approval for both. That is deliberate:
      §6.2 would rather refuse a live episode than send a withdrawn one, and the
      approval carries nothing finer to match on. Which kinds of row are read at
      all is `_NEVER_A_STORY`.
    * **a story-bank episode whose `provenance` names the retracted row.** A
      sentence the candidate polished on its way into the CV store no longer
      matches the log row word for word, and the text match alone reads clean —
      fail-open. `Episode.provenance` already carries the `ConversationTurn` the
      claim came from, so this join is exact and costs no schema change.

    This only ever *removes* authority. Episode backing still comes from
    `approvals.json` and nothing else — routing it back through a list the
    candidate edits is what the module docstring forbids, and a subtraction is
    not that.
    """
    log = EvidenceLog(store)
    if not log.exists():
        return frozenset()
    suppressed = log.suppressed_ids()
    if not suppressed:
        return frozenset()
    texts = {
        row.text for row in log.rows() if row.id in suppressed and row.kind not in _NEVER_A_STORY
    }
    texts |= {
        episode.text
        for episode in master.episodes
        for source in episode.provenance
        if isinstance(source, ConversationTurn) and source.evidence_id in suppressed
    }
    return frozenset(texts)


def measure_prepared(
    store: ProfileStore, master: CVMaster, offer_id: str, version: int
) -> dict[str, Any]:
    """The gate for one prepared document. Enumerates the **documents**, not the store.

    Enumerating the store was the hole: an episode deleted from the story bank
    after the draft was written stopped being looked for, and a document
    demonstrably carrying it measured clean.
    """
    where = store.path(*_version_parts(offer_id, version))
    if not where.is_dir():
        raise ApprovalError(
            f"{offer_id} v{version} was never written — there is no document to measure, "
            "and a version that does not exist is not a version that passed"
        )
    approved = _approved_texts(store, offer_id, version)
    # D-24: an approval cannot outlive the evidence it was granted over. Applied
    # here because `prepare` and `record_sent` both route through this function,
    # so a story withdrawn between drafting and sending is caught at whichever of
    # the two comes next, and neither has to remember to ask.
    retracted = retracted_episode_texts(store, master)
    withdrawn = {text for text in approved if _withdrawn_by(text, retracted)}
    approved -= withdrawn
    claims = read_manifest(store, offer_id, version).claims

    # What backs a line, by kind. A CV entry is backed by the store re-rendering
    # to it — T45's rule. An **episode line is backed by the approval file and
    # nothing else**: the store is a thing the candidate edits, and routing an
    # episode's authority through a list position was how reordering a story
    # bank turned into a gate failure. A Counter, not a set, because one backing
    # backs one line (T45's duplicated-line finding).
    backed: Counter[tuple[str, str]] = Counter()
    for claim in claims:
        if claim.section == "episodes":
            if claim.text in approved:
                backed[(claim.document, claim.text)] += 1
            continue
        entries = _entries(master, claim.section)
        if claim.entry_index < len(entries) and (
            render_entry(claim.section, entries[claim.entry_index]) == claim.text
        ):
            backed[(claim.document, claim.text)] += 1

    documents = {path.name: path.read_text(encoding="utf-8") for path in sorted(where.glob("*.md"))}
    findings: list[str] = []
    surviving: list[str] = []
    unbacked: list[str] = []
    # R8 (#435 round 8, F-3): every claim line on the page, backed or not,
    # approved or not — collected unconditionally so the undecidable
    # messages below can honestly say "anywhere on the page" rather than
    # "anywhere `surviving` or `unbacked` happens to include." `surviving`
    # and `intact` (below) still exclude approved lines on purpose (T156's
    # N2 fix; scanning them there would let an approved line falsely confirm
    # a different episode again) — this list is for message wording only,
    # never for a confirm branch.
    all_lines: list[str] = []
    for name, body in documents.items():
        for line in _claim_lines(body):
            all_lines.append(line)
            key = (name, line)
            if backed[key] > 0:
                backed[key] -= 1
                # Lines an approval explicitly names are excluded from the
                # substance sweep below: they are approved content, and an
                # episode the candidate later rewrote shares most of its
                # wording with the sentence they approved. Sweeping them would
                # report their own approved line back as a leak.
                if line not in approved:
                    surviving.append(line)
            else:
                # Unbackable is unapproved. A line nothing backs is exactly what
                # an episode looks like after the candidate tidies it out of
                # their story bank, and it used to measure clean.
                unbacked.append(line)
                findings.append(
                    f"{offer_id}/v{version} {name}: {line} — "
                    + (
                        "the candidate retracted the evidence this approval was given over"
                        if line in withdrawn
                        else "no per-use approval backs this line"
                    )
                )

    # T114: what exempts an episode from the sweep below is a line the **document**
    # carries, never a row the manifest holds. The manifest is a record of what
    # generation intended; the document is what reaches the employer, and the two
    # part company the moment anything edits a file after drafting. Reading
    # `disclosed` from the manifest meant deleting an episode line kept its
    # exemption: with the approval gone and the substance still in a headline, the
    # sweep skipped the one episode it existed to look for and the gate measured a
    # clean zero. Disclosure outliving its document, which is D-24's shape — an
    # approval outliving its evidence — on the other axis.
    episode_claims = [claim for claim in claims if claim.section == "episodes"]
    on_disk: Counter[tuple[str, str]] = Counter(
        (name, line) for name, body in documents.items() for line in _claim_lines(body)
    )
    # Non-episode rows reserve their line first, and are **not** asked to re-render
    # to do it. A headline spelled exactly like the story puts that sentence in
    # `letter.md` twice, so after the episode line is deleted one identical line is
    # still there: without the reservation the episode claim consumes the
    # headline's own line, calls itself disclosed, and the hole reopens under a
    # different spelling. Reserving on the strength of the row alone can only make
    # an episode claim harder to satisfy, which is the direction §6.2 asks for.
    for claim in claims:
        if claim.section != "episodes":
            reserved = (claim.document, claim.text)
            if on_disk[reserved] > 0:
                on_disk[reserved] -= 1
    disclosed: set[str] = set()
    unwritten: list[str] = []
    for claim in episode_claims:
        key = (claim.document, claim.text)
        if on_disk[key] > 0:
            on_disk[key] -= 1
            disclosed.add(claim.text)
        else:
            # A row over a line that is not there. Reported rather than skipped,
            # because `payload.json` is built from these rows and tells the
            # candidate what the letter says: a summary describing a document that
            # is not on disk is the false summary this module already refuses.
            unwritten.append(
                f"{offer_id}/v{version} {claim.document}: {claim.text} — the manifest "
                "records this episode as disclosed, and the document does not carry it"
            )

    # Substance carried by something that is not an episode line: a headline or a
    # job description holding the same sentence reaches the employer just the
    # same, and used to leave `payload.json` reporting the story as withheld.
    # Checked over the backed lines only, so a line already reported above is not
    # counted a second time.
    carried = 0
    # T156: every episode this loop reaches is either confirmed carried
    # (above), confirmed present some other way (below), or a case this sweep
    # has **no evidence about at all** — and that third bucket is reported
    # uniformly, not guessed at by a second heuristic. See the module
    # docstring's T156 section: `_carries` can only ever confirm *presence*,
    # never *absence* (nothing cheap beats a genuine paraphrase), so a shingle
    # miss proves nothing and every one of them is undecidable, full stop. A
    # first version of this rule tried a normalised-word-overlap proxy instead
    # of an unconditional third state, and a second reader measured it to be
    # anti-correlated with the property it was meant to proxy — 0 of 8
    # constructed genuine paraphrases caught, and a large share of innocent
    # same-domain documents wrongly flagged (0 of 30 or 30 of 30 depending on
    # whether the innocents are built as sentences or paragraphs — see the
    # module docstring's F-4, round 6, for why no single count is quoted here)
    # — because a paraphrase substitutes content
    # words *by definition*, so its overlap is empty, while two documents
    # about the same job share content words *by definition*, so theirs is
    # not. No threshold separates those populations; only "confirmed or not"
    # does. Tracked by text, not by index, for the same reason `EpisodeApproval`
    # names text: a position in `master.episodes` is not a stable handle
    # across the one loop that reads it.
    undecidable: list[str] = []
    intact = "\n".join(surviving)
    for episode in master.episodes:
        if episode.text in disclosed or episode.text in approved:
            continue
        if _carries(intact, episode.text):
            carried += 1
            findings.append(
                f"{offer_id}/v{version}: {episode.text} — the substance of a story-bank "
                "episode, carried by an entry no per-use approval names"
            )
            continue
        # R7-1 (#435 round 7): rounds three through six each tried to answer
        # "whose evidence is this line?" by *excluding* some rival explanation
        # from a shingle match — a text-exact `approved` membership test
        # (round five), then a normalised-shingle rival check against
        # `master.episodes` (round six). Both are a check pinned against a
        # proxy for the property: `approved` is a set a retraction edits,
        # `master.episodes` is the list the candidate edits directly by
        # tidying a story out of their bank, and removing or rewriting the
        # episode that authored a line makes that line's rival vanish with
        # it — the unapproved twin it was protecting is silently cleared
        # again the moment the *other* episode stops existing to compare
        # against. Two committed states (14, 15) regress exactly this way
        # under round six's rule; a third (a single-episode bank, so no
        # rival is even possible by construction) was never closed by either
        # round — round five clears it too.
        #
        # The fix removes the need for a rival check rather than finding a
        # sixth way to compute one. `_carries` is a *shingle* predicate: it
        # is satisfied by any overlapping eight-word window, which is exactly
        # what let two *different* sentences (win's approved text and its
        # near-copies; win's text and the twin that overlaps it) both satisfy
        # it against the same line — the ambiguity was never a property of
        # the line, it was a property of window-based matching applied to
        # confirm a *specific* episode rather than merely to detect presence.
        # `_normalised_equal`, below, asks a different, stronger question:
        # is this *whole* run of words the same as the episode's whole run of
        # words? Two distinct sentences that share an eight-word window do
        # not have to share every word — win and the twin never do (their
        # final two words differ), so equality of the whole word run can
        # never also hold for the rival that a shingle window let through.
        # Nothing here consults `approved`, `master.episodes` or a
        # retraction: an episode's own wording, unedited, is evidence for it
        # regardless of what else exists in the story bank or on disk.
        #
        # R8 (#435 round 8, F-1): "equal" as of round 7 meant `_words(line)
        # == _words(episode)` — `_carries`'s own tokeniser, which *deletes*
        # every `\W` character rather than merely folding case and spacing.
        # That is not "no *other* sentence's wording can pass this test by
        # coincidence" — it is exactly what let one: `+12%` and `-12%`
        # reduce to the same word run once the sign is deleted, and a
        # failure episode was silently cleared by an unrelated achievement's
        # approved line sharing every character but the sign. `_normalised_
        # equal` now folds only case and whitespace runs (see its own
        # docstring) and keeps every other character, so it is *narrower*
        # than the claim two paragraphs up used to be: win's own near-copies
        # (a dropped period, an inserted comma, an appended clause) no
        # longer self-match here either, and fall through to the
        # shingle-match branch below as `undecidable` rather than confirmed
        # — the fail-closed side of the same trade, and the side this
        # module already prefers.
        #
        # Checked one `unbacked` line at a time — never joined into one
        # string — for the reason given at `intact`, several names up:
        # joining a *subset* of lines can put two that were never adjacent on
        # the page next to each other, and a shingle (or a word-run
        # equality, which is exactly as vulnerable) can straddle that
        # manufactured boundary (round three's original defect; `_words`
        # treats a newline as ordinary whitespace).
        #
        # Thirteen states are pinned in `probe_paraphrase_undecidability` for
        # this rule specifically: N2 (12), R5-1A/B (14-15), R6-1's five
        # near-copies and R6-2's retraction (16-21) — every one of which
        # must still resolve the rival's line as *not* this episode's own
        # wording — R7-1's three (22-24): the same duplicated-line and
        # manifest-row states (14, 15) replayed with the authoring episode
        # additionally removed from `master.episodes`, and a single-episode
        # bank with a hand-added line sharing an eight-word window and zero
        # approvals (states 22 and 23 flip from cleared to undecidable
        # relative to round six; state 24 is not a regression and this rule
        # closes it anyway, because it needs no rival at all to do so) —
        # plus R8-1's three (25-27, #435 F-1): states 14, 15 and 21's own
        # constructions replayed with a *sign-flipped* second episode in
        # place of the shingle-overlap twin, so the rival and the confirmed
        # line differ by exactly the characters `_words`-based equality used
        # to delete, and R8-2's one (28, F-2): a genuine near-copy this rule
        # must still confirm, so the case/whitespace tolerance this function
        # actually has is pinned rather than merely asserted in its
        # docstring.
        if any(_normalised_equal(line, episode.text) for line in unbacked):
            # This episode's own wording, unedited, in a line this sweep has
            # *already* reported above as one of `findings`' unbackable rows
            # — so its substance reached the page and is not re-attributed to
            # it a second time. Not `undecidable` either: this is positive
            # evidence for *this* episode specifically, and nothing else can
            # satisfy whole-word-run equality against the same text (see
            # above).
            continue
        # R7-3 (#435 round 7, advisory), corrected at R8 (#435 round 8, F-3
        # and F-4): a shingle match can still exist here — some other line on
        # the page overlaps this episode's text by an eight-word window
        # without being its own wording verbatim — and when it does, saying
        # "no shingle match confirms it present anywhere on the page" is
        # false: a match exists, it is just not confirmably this episode's.
        # R7-3 scanned `unbacked` only, and a state as old as this module's
        # own N2 fixture (state 12) refuted its own message that way: the
        # only shingle match on that page is an *approved* line, which is
        # backed and therefore never in `unbacked` — so the "anywhere on the
        # page" message ran unchecked past it. R8 scans `all_lines` (every
        # claim line, backed or not) here instead, so "anywhere on the page"
        # means what it says; the equality check just above stays scoped to
        # `unbacked`, because self-matching against an *approved* line would
        # reopen N2 the way it did before round three's fix.
        #
        # F-4 (#435 round 7, corrected at R8): the other message read "is not
        # this episode's own wording" as a categorical claim, which is false
        # when the shingle match *is* this episode's own text with a clause
        # appended — this rule only ever established that the two are not
        # *identical* end to end, never that they are unrelated. Reworded to
        # the epistemic claim this branch actually supports.
        if any(_carries(line, episode.text) for line in all_lines):
            undecidable.append(
                f"{offer_id}/v{version}: {episode.text} — no per-use approval names it, "
                "no manifest row claims it, and a shingle match exists on the page that is "
                "not confirmed as this episode's own wording, word for word — this sweep "
                "has no evidence either way, so it is reported as undecided rather than "
                "withheld"
            )
        else:
            undecidable.append(
                f"{offer_id}/v{version}: {episode.text} — no per-use approval names it, "
                "no manifest row claims it, and no shingle match confirms it present "
                "anywhere on the page — this sweep has no evidence either way, so it is "
                "reported as undecided rather than withheld"
            )

    # Over the disclosures that actually happened, never the rows that claim one.
    # Counting the phantom rows here would let a manifest inflate the denominator
    # of the coverage fraction it is itself failing. Undecidable episodes are not
    # folded in here either, in either direction: they are not a disclosure that
    # happened and not a finding against coverage — `episode_approval_coverage`
    # keeps exactly the meaning it had before this task (T156's scope sentence).
    written_claims = len(episode_claims) - len(unwritten)
    checked = written_claims + len(findings)
    return {
        # A fraction over nothing checked is the third D-2 outcome, not a
        # passing 1.0 — `_main` fails on it.
        "episode_approval_coverage": None if checked == 0 else (checked - len(findings)) / checked,
        "unapproved_episode_disclosures": len(findings),
        "unapproved_episodes": sorted(findings),
        "disclosures_unbacked_by_a_generated_document": len(unwritten),
        "unbacked_disclosures": sorted(unwritten),
        "episode_disclosures": written_claims + carried,
        # T156: the third state, replacing `episodes_withheld` — see the module
        # docstring. `episodes_withheld` was a claim of *confirmed absence* that
        # nothing in this module can actually make (the same limit `_carries`'s
        # own docstring already stated), so it is not kept at a permanent 0:
        # a field that cannot read anything but 0 is the "metric independent
        # of its own inputs" shape CLAUDE.md's fixtures section warns about,
        # not a safer version of the field it replaces. `episodes_undecidable`
        # is not a per-use approval's business (it is not a finding against
        # coverage) and not a clean bill of health either: reported so
        # `payload.json` and the boundary can say what they actually know.
        "episodes_undecidable": len(undecidable),
        "undecidable_episodes": sorted(undecidable),
    }


def personal_details_in_master(store: ProfileStore, details: PersonalDetails) -> list[str]:
    """Personal details that reached `cv/master.json` — read from the file.

    ponytail: matched on letters and digits only, so a comma, a space or a `+`
    does not hide one. It does not catch a *reformatted* value — `10/12/1815`
    against a stored `1815-12-10` — and the upgrade path is a per-field parser
    rather than a string compare. The by-key branch below is cheap insurance
    only: `CVMaster` forbids unknown keys, so a loadable master cannot carry
    one, and it is a `master.json` written by something other than this codebase
    that the branch exists for.
    """
    path = store.path("cv", "master.json")
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    loaded = json.loads(raw)
    squashed = _squash(raw)
    found = [f"cv/master.json: {field}" for field in PERSONAL_FIELDS if field in loaded]
    found += [
        f"cv/master.json: the {field} given at step 11 is in the intake store"
        for field, value in details.stated().items()
        if (needle := _squash(value)) and needle in squashed
    ]
    return sorted(set(found))


def sends_without_confirmation(store: ProfileStore) -> list[str]:
    """Application records on disk whose confirmation does not name their payload."""
    root = store.path("applications")
    if not root.is_dir():
        return []
    broken: list[str] = []
    for record in sorted(root.rglob("*.json")):
        # Identity comes from the path, so a record too malformed to name itself
        # is still reportable. Everything that reads the file is inside the try:
        # a hand-written record is precisely what this looks for, and taking
        # `make evidence` down over one hides every other record behind it.
        where = record.relative_to(store.path())
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
            offer_id, version = data["offer_id"], data["version"]
            digest = payload_digest(read_payload(store, offer_id, version))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            broken.append(f"{where}: unreadable application record ({type(exc).__name__})")
            continue
        if data.get("confirmed_digest") != digest:
            broken.append(f"{offer_id}/v{version}: confirms a different payload")
    return broken


def retracted_episodes_sendable(store: ProfileStore, master: CVMaster) -> dict[str, Any]:
    """D-24's reading over one profile — a withdrawn story the boundary still lets out.

    Counts an approval on disk that (a) names a sentence a live retraction
    withdrew, (b) is actually carried by that version's finished documents, and
    (c) `measure_prepared` nonetheless reports nothing about — which is exactly
    the condition under which `record_sent` records the send. All three,
    because an approval standing over a sentence no document carries sends
    nothing, and counting it would fail the gate on a case with no victim.

    `retracted_episodes_evaluated` is the denominator: approvals actually
    compared against a retracted row. A profile with no retraction in its log
    compares nothing, so it reports `unmeasured` rather than a clean zero.
    """
    withdrawn = retracted_episode_texts(store, master)
    empty: dict[str, Any] = {
        "retracted_episodes_still_sendable": 0,
        "retracted_episodes_sendable": [],
        "retracted_episodes_evaluated": 0,
        "gate_status": "unmeasured",
    }
    generated = store.path("cv", "generated")
    if not withdrawn or not generated.is_dir():
        return empty

    evaluated = 0
    sendable: list[str] = []
    for path in sorted(generated.glob("*/v*/approvals.json")):
        approvals = Approvals.model_validate_json(path.read_text(encoding="utf-8"))
        measured: dict[str, Any] | None = None
        for approval in approvals.episodes:
            evaluated += 1
            if not _withdrawn_by(approval.text, withdrawn):
                continue
            documents = "\n".join(
                document.read_text(encoding="utf-8")
                for document in sorted(path.parent.glob("*.md"))
            )
            if not _carries(documents, approval.text):
                continue
            if measured is None:
                measured = measure_prepared(store, master, approvals.offer_id, approvals.version)
            if not measured["unapproved_episode_disclosures"]:
                sendable.append(
                    f"{approvals.offer_id}/v{approvals.version}: {approval.text} — retracted, "
                    "and the send boundary would still record it"
                )
    if evaluated == 0:
        return empty
    return {
        "retracted_episodes_still_sendable": len(sendable),
        "retracted_episodes_sendable": sorted(sendable),
        "retracted_episodes_evaluated": evaluated,
        "gate_status": "measured",
    }


def disclosures_unbacked_by_a_document(store: ProfileStore, master: CVMaster) -> dict[str, Any]:
    """T114's reading over one profile — a manifest row no finished document carries.

    Every `manifest.json` under `cv/generated/`, joined to the `.md` files beside
    it. The join is `measure_prepared`'s, so there is one rule about what counts
    as a document carrying a line rather than two that drift; this walks the
    versions and adds the answers up.

    `manifest_disclosures_compared` is the denominator: episode claims actually
    put in front of a document. A profile that generated nothing, and one whose
    generations disclosed no episode, both compare nothing — and report
    `unmeasured` rather than the clean zero an empty scan produces, because a
    fail-open check that has read no documents has proved exactly nothing.
    """
    empty: dict[str, Any] = {
        "disclosures_unbacked_by_a_generated_document": 0,
        "unbacked_disclosures": [],
        "manifest_disclosures_compared": 0,
        "gate_status": "unmeasured",
    }
    generated = store.path("cv", "generated")
    if not generated.is_dir():
        return empty

    compared = 0
    unbacked: list[str] = []
    for path in sorted(generated.glob("*/v*/manifest.json")):
        # The manifest names its own offer and version, so a directory renamed
        # underneath it cannot silently redirect the measurement at a version
        # that agrees with it.
        manifest = Manifest.model_validate_json(path.read_text(encoding="utf-8"))
        disclosures = sum(1 for claim in manifest.claims if claim.section == "episodes")
        if not disclosures:
            continue
        measured = measure_prepared(store, master, manifest.offer_id, manifest.version)
        compared += disclosures
        unbacked.extend(measured["unbacked_disclosures"])
    if compared == 0:
        return empty
    return {
        "disclosures_unbacked_by_a_generated_document": len(unbacked),
        "unbacked_disclosures": sorted(unbacked),
        "manifest_disclosures_compared": compared,
        "gate_status": "measured",
    }


# ---------------------------------------------------------------------------
# the probes — the half of the gate that is allowed to find something

# The fixture candidate's story bank. Two episodes, and the measurement approves
# exactly one of them per advert.
_FIXTURE_EPISODES: tuple[Episode, ...] = (
    Episode(
        kind="achievement",
        text="Cut the nightly billing run from six hours to forty minutes by rewriting the "
        "reconciliation step.",
    ),
    Episode(
        kind="failure",
        text="Shipped a schema change without a backfill and left invoicing wrong for two "
        "days before anyone noticed.",
    ),
)

# Overlapping the win above by a whole eight-word shingle, which is what
# `_withdrawn_by` matches on: retracting one has to withdraw the other.
_FIXTURE_TWIN = Episode(
    kind="achievement",
    text="Cut the nightly billing run from six hours to forty minutes by rewriting the "
    "ledger export.",
)

# R8 (#435 round 8, F-1): a pair chosen for the opposite reason to
# `_FIXTURE_TWIN` above. The twin overlaps `win` by a shingle *window* and
# diverges at the tail, so `_carries` can conflate them but exact word-run
# equality never could. This pair is the same story told twice — an
# achievement and the failure about the identical metric — differing in
# exactly one character `_words`' `\W`-deletion treats as noise and
# `_normalised_equal`'s R8 fold does not: the sign. Once `_words` strips it,
# both reduce to the identical word run end to end, which is what let the
# achievement's own approved line silently clear the failure episode before
# this round's fix — not a shingle-window coincidence, a whole-run one.
# `Episode.kind` names `"number"` as first-class, so this is not an edge case
# either.
_FIXTURE_SIGNED_ACHIEVEMENT = Episode(
    kind="achievement",
    text="Gross margin moved +12% in the quarter after the reconciliation rewrite shipped.",
)
_FIXTURE_SIGNED_FAILURE = Episode(
    kind="failure",
    text="Gross margin moved -12% in the quarter after the reconciliation rewrite shipped.",
)

_FIXTURE_DETAILS = PersonalDetails(
    full_name="Gate Fixture",
    email="gate.fixture@example.invalid",
    phone="+34 600 000 000",
    postal_address="12 Carrer de la Mostra, 17001 Girona",
    date_of_birth="1985-04-02",
)

_FIXTURE_ASKS: tuple[str, ...] = ("PostgreSQL", "Python", "Kubernetes", "Salesforce")

_PROBE_ADVERT = "We need a data engineer with PostgreSQL and a migration behind them."
_PROBE_OFFER = "probe-1"

# Every scenario `measure()` structurally cannot contain, because each one is a
# defect on purpose and the gate is `== 0`.
MINIMUM_PROBES = 16


def _probe_master(
    headline: str = "Backend engineer — data platforms",
    *,
    experience: tuple[Experience, ...] = (),
    episodes: tuple[Episode, ...] = _FIXTURE_EPISODES,
) -> CVMaster:
    """The probe candidate. `experience` and `episodes` are the axes T114's cases move.

    A headline was the only line the sweep had ever been driven over, and an
    experience bullet reaches the employer identically; two overlapping
    episodes are what put `_withdrawn_by` and the document join in one
    measurement. Both default to what every earlier probe already used.
    """
    return CVMaster(
        headline=SourcedText(text=headline),
        experience=experience,
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=episodes,
    )


def _probe_prepare(
    store: ProfileStore, master: CVMaster, approved: tuple[int, ...] = ()
) -> Payload:
    return prepare(
        store,
        master,
        offer_id=_PROBE_OFFER,
        advert=_PROBE_ADVERT,
        recipient="hiring team, probe",
        details=_FIXTURE_DETAILS,
        asks=("PostgreSQL",),
        approved_episodes=approved,
    )


def probe_boundary(root: Path) -> dict[str, Any]:
    """Drive the boundary against cases it must **catch**, in fresh trees under `root`.

    See the module docstring: without these the gate is unfalsifiable, because
    `measure()` writes both sides of its own equality in one call.
    """
    failures: list[str] = []
    checks = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    def fresh(handle: str, master: CVMaster) -> ProfileStore:
        identity = create_profile(root, "Probe", handle=handle, language="en")
        store = ProfileStore(root, identity.handle)
        write_master(store, master)
        return store

    win, failure = (episode.text for episode in _FIXTURE_EPISODES)
    plain = _probe_master()

    def letter_of(store: ProfileStore) -> Path:
        return store.path(*_version_parts(_PROBE_OFFER, 1), "letter.md")

    # 1 — a line planted in a finished document that nothing approved.
    store = fresh("planted", plain)
    _probe_prepare(store, plain, approved=(0,))
    letter = letter_of(store)
    letter.write_text(letter.read_text(encoding="utf-8") + failure + "\n", encoding="utf-8")
    measured = measure_prepared(store, plain, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] == 1
        and any(failure in item for item in measured["unapproved_episodes"]),
        "a planted unapproved episode was not caught and named",
    )

    # 2 — the same story deleted from the store afterwards. Enumerating the
    # store rather than the documents made this measure clean.
    tidied = plain.model_copy(update={"episodes": (_FIXTURE_EPISODES[0],)})
    measured = measure_prepared(store, tidied, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] >= 1,
        "deleting the episode from the store erased the finding",
    )

    # 3 — an episode's substance carried by a claimable free-text field. It
    # reaches both documents, and an exact-substring check missed it entirely.
    smuggled = _probe_master(headline=failure.rstrip("."))
    store = fresh("smuggled", smuggled)
    try:
        _probe_prepare(store, smuggled)
        caught = False
    except ApprovalError:
        caught = True
    check(caught, "an episode's substance smuggled through the headline was not caught")
    check(
        not store.path(*_version_parts(_PROBE_OFFER, 1), "payload.json").exists(),
        "a payload was written over a draft that discloses an unapproved episode",
    )

    # 4 — the story bank reordered after approval. No document changed and no
    # approved text changed, so this must stay clean: an approval bound to a
    # list position turned ordinary editing into a gate failure.
    store = fresh("reordered", plain)
    _probe_prepare(store, plain, approved=(0,))
    reordered = plain.model_copy(
        update={"episodes": (Episode(kind="context", text="Unrelated."), *_FIXTURE_EPISODES)}
    )
    check(
        measure_prepared(store, reordered, _PROBE_OFFER, 1)["unapproved_episode_disclosures"] == 0,
        "reordering the story bank broke an approval that named a sentence",
    )

    # 5 — an approval written for a different offer, dropped into this version's
    # file. Per-use means per *this* use.
    approvals = store.path(*_version_parts(_PROBE_OFFER, 1), "approvals.json")
    approvals.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "offer_id": _PROBE_OFFER,
                "version": 1,
                "episodes": [{"offer_id": "some-other-offer", "version": 1, "text": win}],
            }
        ),
        encoding="utf-8",
    )
    check(
        measure_prepared(store, plain, _PROBE_OFFER, 1)["unapproved_episode_disclosures"] >= 1,
        "an approval given for another offer backed this one",
    )

    # 6 — the approval file removed: zero approvals, never a permissive default.
    store.path(*_version_parts(_PROBE_OFFER, 1), "approvals.json").unlink()
    check(
        measure_prepared(store, plain, _PROBE_OFFER, 1)["unapproved_episode_disclosures"] >= 1,
        "a missing approvals file read as permission",
    )

    # 7 — a standing permission is not a confirmation.
    store = fresh("sending", plain)
    payload = _probe_prepare(store, plain, approved=(0,))
    try:
        record_sent(store, plain, _PROBE_OFFER, 1, confirms="yes, send anything for this offer")
        refused = False
    except ApprovalError:
        refused = True
    check(refused, "a standing permission was accepted as a confirmation")

    # 8 — the document tampered with after drafting. The digest still names the
    # payload, so only re-measuring at the boundary catches this.
    letter = letter_of(store)
    intact = letter.read_text(encoding="utf-8")
    letter.write_text(intact + failure + "\n", encoding="utf-8")
    try:
        record_sent(store, plain, _PROBE_OFFER, 1, confirms=payload_digest(payload))
        refused = False
    except ApprovalError:
        refused = True
    check(refused, "a document edited after drafting was still sendable")
    letter.write_text(intact, encoding="utf-8")

    # 9 — a hand-written send record naming a payload that is not there.
    record_sent(store, plain, _PROBE_OFFER, 1, confirms=payload_digest(payload))
    forged = store.path("applications", _PROBE_OFFER, "v2.json")
    forged.write_text(
        json.dumps({"offer_id": _PROBE_OFFER, "version": 1, "confirmed_digest": "0" * 64}),
        encoding="utf-8",
    )
    check(
        sends_without_confirmation(store) == [f"{_PROBE_OFFER}/v1: confirms a different payload"],
        "a send record that confirms a different payload was not named",
    )
    forged.unlink()
    check(sends_without_confirmation(store) == [], "a genuine send record was reported as broken")

    # 10 — a personal detail sitting in the intake store, written a slightly
    # different way. Without this the gate's `[]` is a pass over nothing.
    leaked = plain.model_copy(
        update={"headline": SourcedText(text="Backend engineer +34600000000")}
    )
    store = fresh("leaked", leaked)
    check(
        personal_details_in_master(store, _FIXTURE_DETAILS)
        == ["cv/master.json: the phone given at step 11 is in the intake store"],
        "a personal detail in the intake store was not named",
    )

    # 11 — a version nobody wrote is not a version that passed.
    try:
        measure_prepared(store, plain, _PROBE_OFFER, 99)
        refused = False
    except ApprovalError:
        refused = True
    check(refused, "a version that was never written measured clean")

    # 12 — T114, and the reason the sweep reads the documents rather than the
    # manifest. The headline carries the whole story, the letter's episode line is
    # deleted, and the approval is gone: the substance still reaches the employer
    # and nothing backs it. The manifest row used to keep that episode exempt from
    # the sweep, so this measured a clean zero at coverage 1.0.
    outlived = _probe_master(headline=win.rstrip("."))
    store = fresh("outlived", outlived)
    _probe_prepare(store, outlived, approved=(0,))
    letter = letter_of(store)
    letter.write_text(
        "\n".join(line for line in letter.read_text(encoding="utf-8").splitlines() if line != win)
        + "\n",
        encoding="utf-8",
    )
    store.path(*_version_parts(_PROBE_OFFER, 1), "approvals.json").unlink()
    measured = measure_prepared(store, outlived, _PROBE_OFFER, 1)
    check(
        any(
            "the substance of a story-bank episode" in item
            for item in measured["unapproved_episodes"]
        ),
        "a deleted episode line left its substance exempt from the sweep",
    )
    check(
        measured["episode_approval_coverage"] != 1.0,
        "a document carrying an unapproved story reported full approval coverage",
    )

    # 13 — the divergence on its own: a manifest row naming a line the document
    # does not carry. `payload.json` is assembled from those rows, so leaving it
    # unreported means telling the candidate the letter says something it does not.
    check(
        measured["disclosures_unbacked_by_a_generated_document"] == 1,
        "a manifest row over a line no document carries was not reported",
    )

    # 14 — the over-refusal control for 12 and 13 together. An untouched draft
    # agrees with its manifest and must measure nothing at all.
    store = fresh("agreeing", plain)
    _probe_prepare(store, plain, approved=(0,))
    measured = measure_prepared(store, plain, _PROBE_OFFER, 1)
    check(
        measured["disclosures_unbacked_by_a_generated_document"] == 0
        and measured["unapproved_episode_disclosures"] == 0,
        "a document that agrees with its manifest was reported as a divergence",
    )

    # 15 — T114 one document over. The substance survives in a CV **experience
    # bullet** rather than a headline, and §6.2 asks whether the story reaches
    # the employer, never which line carries it. Probe 12 above is the headline
    # shape; a sweep driven only over headlines is a sweep nothing has shown
    # reads the rest of what is sent. Accepted from the second-reader round on
    # #409, where the case passed and nothing pinned it.
    bulleted = _probe_master(
        headline="Data platform engineer",
        experience=(
            Experience(
                title="Data engineer",
                organisation="Probe S.A.",
                description=win.rstrip("."),
            ),
        ),
    )
    store = fresh("bulleted", bulleted)
    _probe_prepare(store, bulleted, approved=(0,))
    letter = letter_of(store)
    letter.write_text(
        "\n".join(line for line in letter.read_text(encoding="utf-8").splitlines() if line != win)
        + "\n",
        encoding="utf-8",
    )
    store.path(*_version_parts(_PROBE_OFFER, 1), "approvals.json").unlink()
    measured = measure_prepared(store, bulleted, _PROBE_OFFER, 1)
    check(
        any(
            "the substance of a story-bank episode" in item
            for item in measured["unapproved_episodes"]
        ),
        "an episode's substance surviving in a CV bullet was not swept",
    )
    check(
        measured["disclosures_unbacked_by_a_generated_document"] == 1,
        "the manifest row over the deleted line was not reported in the bullet case",
    )

    return {"detection_probes": checks, "detection_probe_failures": failures}


# Twenty-one assertions across nineteen scenarios, sixteen of which put an
# approval in front of a live retraction. Floors, not the count of the day:
# adding a scenario raises them, and a probe set that quietly shrank stops
# clearing them. Eleven of the nineteen came from the #305 second-reader audit,
# and every one of the eight it called fail-open was red before its fix.
MINIMUM_RETRACTION_PROBES = 21
MINIMUM_RETRACTED_APPROVALS_EVALUATED = 16

_REWORDED_ROW = "Cut the nightly billing run right down — it used to take us six hours."

# The #305 cases. Each is one edit away from the sentence the approval names,
# and each one sent before `_withdrawn_by` and `_NEVER_A_STORY` landed.
_OWNED_ROW = "Owned the client's month end close and cut the handover from three days to one."
# Fourteen words with the accented one eighth, so no eight-word shingle avoids
# it and only NFC normalisation in `_words` can match the two spellings.
_ACCENTED_ROW = (
    "Reduje el cierre contable de la vieja delegación de Lleida a cuarenta minutos justos."
)
_RAW_UTTERANCE = (
    "Yeah, so basically I cut the nightly billing run from six hours to forty minutes by "
    "rewriting the reconciliation step, that was the thing I did there."
)


def probe_retracted_sends(root: Path) -> dict[str, Any]:
    """D-24: drive the send boundary against a story the candidate withdrew.

    Each scenario is a fresh profile with its own evidence log, because a
    retraction is a fact about a log and the interesting cases differ in what
    the log says. Fourteen of the nineteen are defects on purpose; four are the
    over-refusal the fix must not become, and one pins an application record
    against being rewritten.
    """
    from integral.retraction import retract, unretract

    failures: list[str] = []
    checks = 0
    evaluated = 0
    sendable: list[str] = []

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    def fresh(handle: str) -> ProfileStore:
        identity = create_profile(root, "Probe", handle=handle, language="en")
        return ProfileStore(root, identity.handle)

    def episode_row(store: ProfileStore, text: str, at: str = "2026-01-01T09:00:00+00:00") -> str:
        return (
            EvidenceLog(store)
            .append(
                recorded_at=at, step="history", kind="episode", text=text, source="conversation"
            )
            .id
        )

    def scan(store: ProfileStore, master: CVMaster) -> None:
        nonlocal evaluated
        measured = retracted_episodes_sendable(store, master)
        evaluated += measured["retracted_episodes_evaluated"]
        sendable.extend(measured["retracted_episodes_sendable"])

    def sends(store: ProfileStore, master: CVMaster, payload: Payload) -> Path | None:
        try:
            return record_sent(
                store, master, _PROBE_OFFER, payload.version, confirms=payload_digest(payload)
            )
        except ApprovalError:
            return None

    def drafted(store: ProfileStore, master: CVMaster) -> Payload:
        write_master(store, master)
        return _probe_prepare(store, master, approved=(0,))

    win, failure = (episode.text for episode in _FIXTURE_EPISODES)
    plain = _probe_master()
    later = "2026-01-02T09:00:00+00:00"

    def bank(text: str) -> CVMaster:
        """The fixture story bank with a different sentence in the approved slot."""
        return plain.model_copy(
            update={
                "episodes": (
                    _FIXTURE_EPISODES[0].model_copy(update={"text": text}),
                    _FIXTURE_EPISODES[1],
                )
            }
        )

    def withdrawn_by(
        handle: str,
        row_text: str,
        *,
        kind: Kind = "episode",
        step: str = "history",
        master: CVMaster | None = None,
    ) -> None:
        """Approve the story, retract a row spelling it differently, expect a refusal."""
        held = plain if master is None else master
        store = fresh(handle)
        row = EvidenceLog(store).append(
            recorded_at="2026-01-01T09:00:00+00:00",
            step=step,
            kind=kind,
            text=row_text,
            source="conversation",
        )
        payload = drafted(store, held)
        retract(EvidenceLog(store), row.id, at=later)
        check(sends(store, held, payload) is None, f"{handle}: a retracted episode was sendable")
        scan(store, held)

    # 1 — the defect itself: approved, then the evidence behind it withdrawn.
    store = fresh("retracted")
    row = episode_row(store, win)
    payload = drafted(store, plain)
    retract(EvidenceLog(store), row, at=later)
    check(sends(store, plain, payload) is None, "a retracted episode was still sendable")
    scan(store, plain)

    # 2 — over-refusal: retracting a *different* story leaves this one sendable.
    store = fresh("untouched")
    episode_row(store, win)
    other = episode_row(store, failure, at="2026-01-01T10:00:00+00:00")
    payload = drafted(store, plain)
    retract(EvidenceLog(store), other, at=later)
    check(
        sends(store, plain, payload) is not None,
        "retracting another episode blocked a live approval",
    )
    scan(store, plain)

    # 3 — an application record is immutable, so a later retraction cannot rewrite it.
    store = fresh("immutable")
    row = episode_row(store, win)
    payload = drafted(store, plain)
    record = sends(store, plain, payload)
    check(record is not None, "a clean send was refused")
    before = record.read_bytes() if record is not None else b""
    retract(EvidenceLog(store), row, at=later)
    check(
        record is not None and record.read_bytes() == before,
        "a retraction rewrote an application record",
    )
    scan(store, plain)

    # 4 — two rows, one sentence. The approval names the sentence, so both go.
    store = fresh("duplicate")
    episode_row(store, win)
    twin = episode_row(store, win, at="2026-01-01T10:00:00+00:00")
    payload = drafted(store, plain)
    retract(EvidenceLog(store), twin, at=later)
    check(
        sends(store, plain, payload) is None,
        "one of two identical rows was retracted and the send stood",
    )
    scan(store, plain)

    # 5 — retracted before drafting: `prepare` refuses, so no payload is written.
    store = fresh("undrafted")
    row = episode_row(store, win)
    retract(EvidenceLog(store), row, at=later)
    write_master(store, plain)
    try:
        _probe_prepare(store, plain, approved=(0,))
        drafting_refused = False
    except ApprovalError:
        drafting_refused = True
    check(drafting_refused, "a retracted episode was drafted into an application")
    check(
        not store.path(*_version_parts(_PROBE_OFFER, 1), "payload.json").exists(),
        "a payload was written over a retracted episode",
    )
    scan(store, plain)

    # 6 — an accidental retraction, undone. The check reads the log, not a stamp.
    store = fresh("undone")
    row = episode_row(store, win)
    payload = drafted(store, plain)
    undo = retract(EvidenceLog(store), row, at=later)
    unretract(EvidenceLog(store), undo.id, at="2026-01-03T09:00:00+00:00")
    check(sends(store, plain, payload) is not None, "an undone retraction still blocked the send")
    scan(store, plain)

    # 7 — the sentence was polished on its way into the CV store, so only
    # `Episode.provenance` joins the approval to the row that was withdrawn.
    store = fresh("reworded")
    row = episode_row(store, _REWORDED_ROW)
    reworded = plain.model_copy(
        update={
            "episodes": (
                _FIXTURE_EPISODES[0].model_copy(
                    update={"provenance": (ConversationTurn(evidence_id=row),)}
                ),
                _FIXTURE_EPISODES[1],
            )
        }
    )
    payload = drafted(store, reworded)
    retract(EvidenceLog(store), row, at=later)
    check(
        sends(store, reworded, payload) is None,
        "a reworded episode outlived the row it came from",
    )
    scan(store, reworded)

    # 8 — only a story-bank row withdraws a story. Retracting a constraint that
    # happens to repeat the sentence must not block the send.
    store = fresh("constraint")
    stated = EvidenceLog(store).append(
        recorded_at="2026-01-01T09:00:00+00:00",
        step="constraints",
        kind="constraint",
        text=win,
        source="conversation",
    )
    payload = drafted(store, plain)
    retract(EvidenceLog(store), stated.id, at=later)
    check(
        sends(store, plain, payload) is not None,
        "retracting a constraint row withdrew an episode approval",
    )
    scan(store, plain)

    # 9-14 and 16 - one character apart from the approved sentence, and each one
    # sent while the join was byte equality (#305 review, D-1 and D-4).
    withdrawn_by("punctuated", win.rstrip("."))
    withdrawn_by("apostrophe", _OWNED_ROW.replace("'", "\u2019"), master=bank(_OWNED_ROW))
    withdrawn_by("spaced", win.replace("six hours", "six  hours"))
    withdrawn_by("cased", win.upper())
    withdrawn_by(
        "accented",
        unicodedata.normalize("NFD", _ACCENTED_ROW),
        master=bank(unicodedata.normalize("NFC", _ACCENTED_ROW)),
    )
    withdrawn_by("polished", _RAW_UTTERANCE)
    # The shape `add_conversation_entry` writes, and the one a `kind == "episode"`
    # whitelist skipped (#305 review, D-2).
    withdrawn_by("intake-statement", win, kind="statement", step="intake")

    # 15 — two rows for one story. The story bank holds what was said, intake
    # holds the row the CV entry is provenanced to; retracting the story-bank
    # row is the candidate withdrawing the story, and only the text joins it.
    store = fresh("two-rows")
    bank_row = episode_row(store, _RAW_UTTERANCE)
    intake = EvidenceLog(store).append(
        recorded_at="2026-01-01T09:30:00+00:00",
        step="intake",
        kind="statement",
        text=win,
        source="conversation",
    )
    provenanced = plain.model_copy(
        update={
            "episodes": (
                _FIXTURE_EPISODES[0].model_copy(
                    update={"provenance": (ConversationTurn(evidence_id=intake.id),)}
                ),
                _FIXTURE_EPISODES[1],
            )
        }
    )
    payload = drafted(store, provenanced)
    retract(EvidenceLog(store), bank_row, at=later)
    check(
        sends(store, provenanced, payload) is None,
        "retracting the story-bank row left the CV store episode sendable",
    )
    scan(store, provenanced)

    # 17 — a log that does not settle must stop the send. Written by hand,
    # because `append` refuses to retract a row that is not there yet and so
    # cannot make the cycle. No `scan`: reading this log is what raises.
    store = fresh("broken-chain")
    episode_row(store, win)
    payload = drafted(store, plain)
    evidence = store.path(*EVIDENCE_PARTS)
    evidence.write_text(
        evidence.read_text(encoding="utf-8")
        + "".join(
            json.dumps(
                {
                    "id": row_id,
                    "recorded_at": later,
                    "step": "any",
                    "kind": "retraction",
                    "text": "Forget that.",
                    "source": "conversation",
                    "retracts": retracts,
                }
            )
            + "\n"
            for row_id, retracts in (("ev-000900", "ev-000901"), ("ev-000901", "ev-000900"))
        ),
        encoding="utf-8",
    )
    try:
        sends(store, plain, payload)
        settled = True
    except ProfileError:
        settled = False
    check(not settled, "a retraction chain that does not settle was read as no retraction")

    # 18 — retract, undo, undo the undo. The third level puts the row back under.
    store = fresh("thrice")
    row = episode_row(store, win)
    payload = drafted(store, plain)
    first = retract(EvidenceLog(store), row, at=later)
    second = retract(EvidenceLog(store), first.id, at="2026-01-03T09:00:00+00:00")
    retract(EvidenceLog(store), second.id, at="2026-01-04T09:00:00+00:00")
    check(sends(store, plain, payload) is None, "a thrice-nested retraction left the story out")
    scan(store, plain)

    # 19 — the limit of the over-refusal: an empty sentence withdraws nothing.
    store = fresh("blank")
    row = episode_row(store, "   ")
    payload = drafted(store, plain)
    retract(EvidenceLog(store), row, at=later)
    check(
        sends(store, plain, payload) is not None,
        "a whitespace-only retracted row blocked a live approval",
    )
    scan(store, plain)

    return {
        "retracted_episodes_still_sendable": len(sendable),
        "retracted_episodes_sendable": sorted(sendable),
        "retracted_episodes_evaluated": evaluated,
        "gate_status": "measured" if evaluated else "unmeasured",
        "retraction_probes": checks,
        "retraction_probe_failures": failures,
    }


# Floors, not the count of the day, for T100's reason: a denominator committed as
# an exact value moves whenever the corpus does, and a probe set that quietly
# shrank would still clear an exact match. The corpus contributes one disclosure
# per advert, so the floor here is a long way under what a healthy run measures
# and a long way over what an empty scan could produce.
MINIMUM_DISCLOSURE_PROBES = 24
MINIMUM_MANIFEST_DISCLOSURES_COMPARED = 100


def probe_unbacked_disclosures(root: Path) -> dict[str, Any]:
    """T114: drive the boundary against a manifest that outruns its documents.

    Ten scenarios, eight of them defects on purpose. The other two are the
    over-refusal this must not become — an untouched draft has to stay sendable —
    and they are also the only trees the aggregate reading below scans, since the
    planted ones are divergent by construction and counting them would make the
    gate assert its own fixtures rather than the code.
    """
    from integral.retraction import retract

    failures: list[str] = []
    checks = 0
    compared = 0
    unbacked: list[str] = []

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    def fresh(handle: str, master: CVMaster) -> ProfileStore:
        identity = create_profile(root, "Probe", handle=handle, language="en")
        store = ProfileStore(root, identity.handle)
        write_master(store, master)
        return store

    def where(store: ProfileStore) -> Path:
        return store.path(*_version_parts(_PROBE_OFFER, 1))

    def drop_line(store: ProfileStore, text: str, document: str = "letter.md") -> None:
        path = where(store) / document
        kept = [line for line in path.read_text(encoding="utf-8").splitlines() if line != text]
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    def divergences(store: ProfileStore, master: CVMaster) -> int:
        count: int = measure_prepared(store, master, _PROBE_OFFER, 1)[
            "disclosures_unbacked_by_a_generated_document"
        ]
        return count

    def sweep_findings(store: ProfileStore, master: CVMaster) -> list[str]:
        found: list[str] = measure_prepared(store, master, _PROBE_OFFER, 1)["unapproved_episodes"]
        return found

    def scan(store: ProfileStore, master: CVMaster) -> None:
        """Add a tree that must read clean to the aggregate the gate is over."""
        nonlocal compared
        reading = disclosures_unbacked_by_a_document(store, master)
        compared += reading["manifest_disclosures_compared"]
        unbacked.extend(reading["unbacked_disclosures"])
        check(
            reading["gate_status"] == "measured",
            "a profile with a disclosed episode reported nothing to compare",
        )

    def sends(store: ProfileStore, master: CVMaster, payload: Payload) -> Path | None:
        try:
            return record_sent(store, master, _PROBE_OFFER, 1, confirms=payload_digest(payload))
        except ApprovalError:
            return None

    win, _failure = (episode.text for episode in _FIXTURE_EPISODES)
    plain = _probe_master()
    # The headline the substance sweep is about: the whole story, one full stop
    # short of the episode's own spelling, so the two are distinct strings and
    # only a normalised shingle match connects them.
    smuggled = _probe_master(headline=win.rstrip("."))

    # 1 — the defect. The letter's episode line is deleted, the approval is gone,
    # and the headline still carries the story word for word. Before this task the
    # manifest row kept the episode exempt and the whole measurement read clean.
    store = fresh("deleted", smuggled)
    _probe_prepare(store, smuggled, approved=(0,))
    drop_line(store, win)
    (where(store) / "approvals.json").unlink()
    check(divergences(store, smuggled) == 1, "a deleted episode line left its manifest row alone")
    check(
        any(
            "the substance of a story-bank episode" in item
            for item in sweep_findings(store, smuggled)
        ),
        "an episode's substance surviving in a headline was skipped by its own manifest row",
    )

    # 2 — the divergence on its own, with the approval untouched. Nothing is
    # smuggled here; what is wrong is that `payload.json` describes a letter that
    # does not say what it says, and the send boundary must refuse it.
    store = fresh("described", plain)
    payload = _probe_prepare(store, plain, approved=(0,))
    drop_line(store, win)
    check(divergences(store, plain) == 1, "a manifest row over a missing line was not reported")
    check(sends(store, plain, payload) is None, "a payload describing a deleted line was sendable")

    # 3 — the over-refusal control. An untouched draft agrees with its manifest,
    # measures nothing, and still sends.
    store = fresh("untouched", plain)
    payload = _probe_prepare(store, plain, approved=(0,))
    check(divergences(store, plain) == 0, "a document that agrees with its manifest was refused")
    check(sends(store, plain, payload) is not None, "a clean draft was refused")
    scan(store, plain)

    # 4 — the headline spelled *exactly* like the story, so the letter carries that
    # sentence twice. Delete the episode line and one identical line is still
    # there: a check that only asks "does this document contain the text" reads
    # clean off the headline's own line. A non-episode row reserves its line first.
    twin = _probe_master(headline=win)
    store = fresh("twinned", twin)
    _probe_prepare(store, twin, approved=(0,))
    letter = where(store) / "letter.md"
    lines = letter.read_text(encoding="utf-8").splitlines()
    check(lines.count(win) == 2, "the twinned fixture did not put the sentence in twice")
    lines.remove(win)
    letter.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (where(store) / "approvals.json").unlink()
    check(divergences(store, twin) == 1, "an episode row borrowed another claim's identical line")

    # 5 — the whole document removed. A file that is not there carries nothing.
    store = fresh("gone", plain)
    _probe_prepare(store, plain, approved=(0,))
    (where(store) / "letter.md").unlink()
    check(divergences(store, plain) == 1, "a deleted document left its manifest rows backed")

    # 6 — the row duplicated over one line. One line backs one claim (T45).
    store = fresh("doubled", plain)
    _probe_prepare(store, plain, approved=(0,))
    path = where(store) / "manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["claims"].append(
        dict(next(claim for claim in raw["claims"] if claim["section"] == "episodes"))
    )
    path.write_text(json.dumps(raw), encoding="utf-8")
    check(divergences(store, plain) == 1, "two manifest rows shared one document line")

    # 7 — the row re-pointed at the other document. A claim is scoped to the
    # document it names, so `cv.md` cannot answer for a row about `letter.md`.
    store = fresh("misfiled", plain)
    _probe_prepare(store, plain, approved=(0,))
    path = where(store) / "manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    for claim in raw["claims"]:
        if claim["section"] == "episodes":
            claim["document"] = "cv.md"
    path.write_text(json.dumps(raw), encoding="utf-8")
    check(divergences(store, plain) == 1, "an episode row was answered by a different document")

    # 8 — the line reworded rather than deleted. Deletion plus insertion, and it
    # has to read as both: the row names no line, and the line no approval names.
    store = fresh("reworded", plain)
    _probe_prepare(store, plain, approved=(0,))
    letter = where(store) / "letter.md"
    letter.write_text(
        letter.read_text(encoding="utf-8").replace(win, "Cut the billing run, more or less."),
        encoding="utf-8",
    )
    check(divergences(store, plain) == 1, "a reworded episode line kept its manifest row backed")
    check(sweep_findings(store, plain) != [], "a reworded episode line was backed by an approval")

    # 9 — where this crosses D-24. The retraction withdraws the approval and the
    # deletion removes the line the withdrawal would have been reported over, so
    # before this task neither gate had anything to say about a story still being
    # carried, in full, by the headline.
    store = fresh("withdrawn", smuggled)
    row = EvidenceLog(store).append(
        recorded_at="2026-01-01T09:00:00+00:00",
        step="history",
        kind="episode",
        text=win,
        source="conversation",
    )
    _probe_prepare(store, smuggled, approved=(0,))
    retract(EvidenceLog(store), row.id, at="2026-01-02T09:00:00+00:00")
    drop_line(store, win)
    check(divergences(store, smuggled) == 1, "a retracted, deleted episode line measured clean")
    check(
        sweep_findings(store, smuggled) != [],
        "a retracted episode's substance in a headline was skipped by its manifest row",
    )

    # 10 — every claim line stripped from both documents, manifest untouched. The
    # degenerate end of the same axis, and it must report rather than crash.
    store = fresh("stripped", plain)
    _probe_prepare(store, plain, approved=(0,))
    for document in sorted(where(store).glob("*.md")):
        document.write_text("", encoding="utf-8")
    check(divergences(store, plain) == 1, "emptying both documents left the manifest rows backed")

    # 11 — the empty-scan rule. A generation nobody approved an episode into has
    # no disclosure to compare, and the reading must say so rather than pass.
    store = fresh("nothing-approved", plain)
    _probe_prepare(store, plain)
    reading = disclosures_unbacked_by_a_document(store, plain)
    check(
        reading["gate_status"] == "unmeasured"
        and reading["manifest_disclosures_compared"] == 0
        and reading["disclosures_unbacked_by_a_generated_document"] == 0,
        "a profile that disclosed no episode scored a clean zero instead of unmeasured",
    )

    # 12 — a profile that never generated anything is unmeasured too, not clean.
    check(
        disclosures_unbacked_by_a_document(fresh("ungenerated", plain), plain)["gate_status"]
        == "unmeasured",
        "a profile with nothing generated scored a clean zero instead of unmeasured",
    )

    # 13 — a second clean tree for the aggregate, with an ordinary headline in the
    # way, so the denominator does not rest on a single shape of document.
    ordinary = _probe_master(headline="Data engineer — billing and reconciliation")
    store = fresh("ordinary", ordinary)
    payload = _probe_prepare(store, ordinary, approved=(0,))
    check(divergences(store, ordinary) == 0, "an ordinary headline was read as a divergence")
    check(sends(store, ordinary, payload) is not None, "an ordinary clean draft was refused")
    scan(store, ordinary)

    # 14 — the row re-pointed at a document that was **never generated**.
    # Distinct from 7, where `cv.md` exists and is refused because a claim is
    # scoped to the document it names: here there is nothing to ask at all, and
    # the fail-open reading is that a name matching no file is "not applicable"
    # and skipped — the manifest deciding its own exemption, which is the whole
    # subject of this task. Accepted from the second-reader round on #409.
    store = fresh("phantom-document", plain)
    _probe_prepare(store, plain, approved=(0,))
    path = where(store) / "manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    for claim in raw["claims"]:
        if claim["section"] == "episodes":
            claim["document"] = "portfolio.md"
    path.write_text(json.dumps(raw), encoding="utf-8")
    check(divergences(store, plain) == 1, "a row naming a document that never existed was skipped")

    # 15 — two overlapping episodes with one retracted, and the retracted one's
    # line deleted. D-24 withdraws the approval over anything carrying the
    # retracted substance; T114 keeps the row over the deleted line visible. The
    # fail-open reading is that the deletion removes what the withdrawal would
    # have been reported over while the twin's line goes out carrying the same
    # eight-word window, so both halves have to fire on one measurement.
    # Accepted from the second-reader round on #409.
    twins = _probe_master(
        headline="Data platform engineer",
        episodes=(_FIXTURE_EPISODES[0], _FIXTURE_TWIN),
    )
    store = fresh("overlapping", twins)
    row = EvidenceLog(store).append(
        recorded_at="2026-01-01T09:00:00+00:00",
        step="history",
        kind="episode",
        text=win,
        source="conversation",
    )
    _probe_prepare(store, twins, approved=(0, 1))
    retract(EvidenceLog(store), row.id, at="2026-01-02T09:00:00+00:00")
    drop_line(store, win)
    check(divergences(store, twins) == 1, "the row over the deleted twin's line measured clean")
    check(
        any(
            "retracted the evidence this approval was given over" in item
            and _FIXTURE_TWIN.text in item
            for item in sweep_findings(store, twins)
        ),
        "the surviving twin of a retracted episode was still sendable",
    )

    # 16 — the over-refusal control for 15, and a third clean tree for the
    # aggregate. Two episodes sharing an eight-word window is not by itself a
    # divergence: an untouched draft of them has to measure clean and still send.
    store = fresh("overlapping-clean", twins)
    payload = _probe_prepare(store, twins, approved=(0, 1))
    check(divergences(store, twins) == 0, "an untouched pair of overlapping episodes was refused")
    check(
        sends(store, twins, payload) is not None,
        "a clean draft of overlapping episodes was refused",
    )
    scan(store, twins)

    return {
        "disclosures_unbacked_by_a_generated_document": len(unbacked),
        "unbacked_disclosures": sorted(unbacked),
        "manifest_disclosures_compared": compared,
        "gate_status": "measured" if compared else "unmeasured",
        "disclosure_probes": checks,
        "disclosure_probe_failures": failures,
    }


# ---------------------------------------------------------------------------
# T156 — a paraphrase must be reported as undecidable, never as withheld
#
# Rewritten once already. The first version added a normalised-word-overlap
# proxy (`_plausible_paraphrase`) and threshold fixtures whose expected
# verdicts were computed from the proxy's own constants — arithmetic run
# backwards from the thing being checked, per CLAUDE.md's fixtures section.
# A second reader measured that proxy end to end and found it anti-correlated
# with paraphrase (0 of 8 genuine paraphrases caught; a large share of
# innocent same-domain documents wrongly flagged either way a paraphrase's
# length is constructed — see the module docstring's F-4, round 6, for the
# two-construction measurement in place of the single count this comment used
# to quote). The fixtures below are the
# replacement: no thresholds, no synthetic "boundary" pair, and the innocent
# controls are same-domain documents that share an episode's vocabulary
# without retelling its event — the shape the second reader's own report used.

# A genuine paraphrase of the win episode with several of its long words kept
# (billing, reconciliation, rewriting, hours, minutes) — reordered so no
# eight-word window matches (asserted inside the probe, never taken on faith).
_FIXTURE_PARAPHRASE = (
    "Rewriting the reconciliation step cut billing run time from six hours down "
    "to forty minutes each night."
)

# A thorough paraphrase of the same episode — synonym-substituted rather than
# reordered, so it shares almost none of the win episode's surface vocabulary.
# This is the shape the second reader's C3 finding named directly: the state a
# threshold-based proxy structurally cannot reach, because a paraphrase
# substitutes content words *by definition*. The unconditional rule below
# catches it precisely because it asks "is there a shingle match", not "how
# much vocabulary is shared" — there is no overlap-based fixture left for this
# one to defeat.
_FIXTURE_THOROUGH_PARAPHRASE = (
    "By reworking how the ledgers were reconciled, the overnight invoicing job "
    "that used to take six hours now finishes in well under an hour."
)

# Same-domain, retells nothing: shares "nightly", "billing", "reconciliation"
# with the win episode, but describes an ongoing role rather than the specific
# six-hours-to-forty-minutes event. Under the retired word-overlap proxy this
# was exactly the shape of case the second reader's report measured being
# wrongly flagged (`support-escalation`, `billing-ownership`); under the
# unconditional rule it is treated identically to every other unconfirmed
# episode — undecidable, not blocked — which is the point: there is no special
# case for "shares vocabulary" any more because there is no vocabulary check.
_FIXTURE_INNOCENT_WIN_ADJACENT = (
    "Owns the nightly billing reconciliation runbook and leads the on-call "
    "rotation for finance systems."
)

# The same shape against the failure episode: shares "schema" and "invoicing"
# but describes a review process, not the outage.
_FIXTURE_INNOCENT_FAILURE_ADJACENT = (
    "Reviews every schema change proposal for the invoicing service before it reaches production."
)

# A third episode, distinct from the fixture pair above, planted verbatim to
# create a confirmed finding alongside a genuinely undecidable one — the
# combination the boundary-message state below needs.
_FIXTURE_SMUGGLED_EPISODE = Episode(
    kind="achievement",
    text="Negotiated a vendor contract renewal that saved forty thousand euros over two years.",
)

# A paraphrase of the failure episode, for the boundary-message state: reworded
# so no shingle matches, while the smuggled episode above is planted verbatim
# in the same draft.
_FIXTURE_FAILURE_PARAPHRASE = (
    "The invoicing numbers went wrong for two days after a database change went "
    "out with no backfill, and nobody caught it right away."
)


def _named_undecidable(measured: dict[str, Any], episode_text: str) -> bool:
    """Does `measured["undecidable_episodes"]` name this exact episode?"""
    return any(episode_text in item for item in measured["undecidable_episodes"])


def _named_as_finding(measured: dict[str, Any], episode_text: str) -> bool:
    """Does `measured["unapproved_episodes"]` name this exact episode?"""
    return any(episode_text in item for item in measured["unapproved_episodes"])


# Twenty-eight constructed profiles (`fresh()` calls), one per numbered state
# below — a floor over the population the second reader's F3 finding named
# (states, not `check()` calls), set to the actual count rather than to a
# margin nobody argued: deleting one state now breaches this floor
# immediately. States 12-13 are round 3's (N2) and round 4's (F1) accepted
# findings; 14-15 are round 5's (R5-1); 16-21 are round 6's (R6-1's five
# near-copies and R6-2's retraction); 22-24 are round 7's (R7-1's two
# bank-edited regressions and the single-episode-bank state neither prior
# round closed); 25-28 are round 8's (R8-1's three signed-pair replays of
# 14, 15 and 21 — F-1's blocker — and R8-2's genuine near-copy — F-2's
# missing positive direction), committed here per CLAUDE.md's fixtures
# section: an accepted case pinned only in pytest is a report that was read
# and waved through, and the measured denominator has to rise or the
# acceptance did not happen.
# 11 -> 13 -> 15 -> 21 -> 24 -> 28.
MINIMUM_PARAPHRASE_STATES = 28
# Both denominators asserted, per the same reasoning T150 gives for
# `MINIMUM_EVIDENCE_KEYS_COMPARED`/`MINIMUM_EVIDENCE_SOURCES_COMPARED`: a floor
# on `states` alone is satisfiable by an empty `fresh()` call that asserts
# nothing, which is exactly the "floor counting the wrong population" shape
# F3 named. Also set to the actual count, so thinning a state's own checks
# without deleting the state trips this one instead. 21 -> 25 (states 12-13)
# -> 29 (states 14-15, two checks each) -> 30 (one more check added to state
# 9 itself, isolating the `approved` disjunct of its skip guard) -> 42 (states
# 16-21, six new states, two checks each) -> 48 (states 22-24, two checks
# each) -> 56 (states 25-28, two checks each).
MINIMUM_PARAPHRASE_CHECKS = 56


def probe_paraphrase_undecidability(root: Path) -> dict[str, Any]:
    """T156: a paraphrase must leave the sweep saying "undecided", never "withheld".

    Every state is derived from the module docstring's T156 section and from
    §6.2 — never from what the sweep happens to return, which is the
    circularity CLAUDE.md's fixtures section exists to break. Direction
    matters exactly as it does in `probe_unbacked_disclosures`: states 1-3 are
    genuine paraphrases the fix exists to stop mislabelling, states 4-9 are the
    over-refusal and boundary-scope controls this must not become or overstate,
    and 10-11 pin the two channels the third state is reported through.
    """
    failures: list[str] = []
    checks = 0
    states = 0
    reported_as_withheld = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    def fresh(handle: str, master: CVMaster) -> ProfileStore:
        nonlocal states
        states += 1
        identity = create_profile(root, "Probe", handle=handle, language="en")
        store = ProfileStore(root, identity.handle)
        write_master(store, master)
        return store

    win, failure = (episode.text for episode in _FIXTURE_EPISODES)

    def note_if_silently_cleared(measured: dict[str, Any], text: str) -> None:
        """The task's own gate numerator, factored out so every route that
        exercises the third state feeds it — not only the three genuine-
        paraphrase states below.

        F-3 (#435 round 6): states 14 and 15 asserted `_named_undecidable`
        directly and never called this, so a regression that silently cleared
        their twin from both channels moved `paraphrase_probe_failures` and
        the module's exit code but left `paraphrased_substance_reported_as_
        withheld` — the exact key the task's own gate block names — sitting at
        its clean 0. The denominators (`paraphrase_states_evaluated`,
        `paraphrase_checks_evaluated`) rose across rounds 5 and 6; this
        numerator's population had not. Called from every twin- and
        paraphrase-shaped state now (12-21 as well as 1-3), so a case named by
        neither channel is counted here regardless of which check happens to
        also fail.
        """
        nonlocal reported_as_withheld
        if not _named_undecidable(measured, text) and not _named_as_finding(measured, text):
            # Named by neither channel: the shape `episodes_withheld` used to
            # have, silently claiming confirmed absence. This is the numerator.
            reported_as_withheld += 1

    def check_genuine_paraphrase(measured: dict[str, Any], text: str, label: str) -> None:
        """The three assertions every genuine-paraphrase state makes, named once."""
        note_if_silently_cleared(measured, text)
        check(_named_undecidable(measured, text), f"{label}: not reported as undecidable")
        check(
            measured["unapproved_episode_disclosures"] == 0,
            f"{label}: an undecided paraphrase was treated as a confirmed disclosure",
        )

    def expect_clean_prepare(label: str, target: ProfileStore, master: CVMaster) -> Payload | None:
        """`_probe_prepare`, but a refusal this state does not expect is a
        recorded failure, not an uncaught crash.

        States 4 and 5 below assert that an innocent, same-domain draft
        prepares cleanly — `prepare` must not raise. Before this helper that
        assertion was only as strong as an unwrapped `_probe_prepare` call:
        if a regression made `prepare` wrongly refuse one of them,
        `ApprovalError` propagated straight out of this function, out of
        `write_paraphrase_evidence`, and out of `_main` uncaught. `make
        evidence`'s per-module loop still turns that into `GATE FAILED` on
        the nonzero exit, so it is not silent — but `evidence.write_text`
        two lines above never runs, so `status/evidence/T156.json` is left
        exactly as it was, and anything that reads *that file* rather than
        re-running the measurement — a stale dashboard, a cached `gate-check`
        pass — would go on reporting the committed, unrelated 0. It is also
        reported through a different channel than every other case in this
        probe: a bare traceback instead of a named entry in
        `paraphrase_probe_failures`, so the one place this module's own
        failures are supposed to collect stays silent about this one. Catching
        it here folds an unexpected refusal back into that same list.
        """
        try:
            return _probe_prepare(target, master)
        except ApprovalError as exc:
            check(
                False,
                f"{label}: an innocent same-domain draft was wrongly refused as an "
                f"unapproved disclosure ({exc})",
            )
            return None

    # 1 — the defect itself: a paraphrase in the headline, never approved and
    # never named in any manifest row. Before this task this measured a
    # confident `episodes_withheld == 1`; before the second-reader round, a
    # word-overlap proxy that happened to catch this one specific shape.
    paraphrased = _probe_master(headline=_FIXTURE_PARAPHRASE, episodes=(_FIXTURE_EPISODES[0],))
    store = fresh("paraphrase-headline", paraphrased)
    payload = _probe_prepare(store, paraphrased)
    measured = measure_prepared(store, paraphrased, _PROBE_OFFER, 1)
    check_genuine_paraphrase(measured, win, "paraphrase-headline")
    # Confirms answer 2's own recorded trade directly: an undecidable-only
    # draft is not itself a refusal, so `prepare` returns a payload.
    check(payload.version == 1, "an undecidable-only draft was refused rather than prepared")

    # 2 — the same substance, in a CV experience bullet rather than a headline.
    # T114 established the sweep must not be blind to a document other than
    # the headline; this is that same axis for T156.
    bulleted = CVMaster(
        headline=SourcedText(text="Data platform engineer"),
        experience=(
            Experience(
                title="Data engineer",
                organisation="Probe S.A.",
                description=_FIXTURE_PARAPHRASE,
            ),
        ),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(_FIXTURE_EPISODES[0],),
    )
    store = fresh("paraphrase-bullet", bulleted)
    _probe_prepare(store, bulleted)
    measured = measure_prepared(store, bulleted, _PROBE_OFFER, 1)
    check_genuine_paraphrase(measured, win, "paraphrase-bullet")

    # 3 — the second-reader's C3 case by name: a paraphrase thorough enough to
    # share almost no surface vocabulary with the episode it retells. The
    # retired word-overlap proxy caught 0 of 8 cases shaped like this one;
    # the unconditional rule needs no vocabulary at all to catch it.
    thorough = _probe_master(
        headline=_FIXTURE_THOROUGH_PARAPHRASE, episodes=(_FIXTURE_EPISODES[0],)
    )
    store = fresh("paraphrase-thorough", thorough)
    _probe_prepare(store, thorough)
    measured = measure_prepared(store, thorough, _PROBE_OFFER, 1)
    check_genuine_paraphrase(measured, win, "paraphrase-thorough")

    # 4 and 5 — the over-refusal shape the retired proxy actually failed on:
    # a same-domain document that shares an episode's vocabulary while
    # retelling none of its event. Under the unconditional rule there is no
    # vocabulary check left to trip, so this is not a "control" in the old
    # threshold sense — it is confirmation that sharing a subject is no longer
    # treated as evidence of anything, in either direction. Both drafts must
    # still prepare cleanly: nothing here is a confirmed finding.
    innocent_win = _probe_master(
        headline=_FIXTURE_INNOCENT_WIN_ADJACENT, episodes=(_FIXTURE_EPISODES[0],)
    )
    store = fresh("innocent-win-adjacent", innocent_win)
    maybe_payload = expect_clean_prepare("innocent-win-adjacent", store, innocent_win)
    if maybe_payload is not None:
        measured = measure_prepared(store, innocent_win, _PROBE_OFFER, 1)
        check(
            measured["unapproved_episode_disclosures"] == 0,
            "an innocent same-domain document was treated as a confirmed disclosure",
        )
        check(maybe_payload.version == 1, "an innocent same-domain document blocked the draft")

    innocent_failure = _probe_master(
        headline="Data engineer — billing systems",
        experience=(
            Experience(
                title="Data engineer",
                organisation="Probe S.A.",
                description=_FIXTURE_INNOCENT_FAILURE_ADJACENT,
            ),
        ),
        episodes=(_FIXTURE_EPISODES[1],),
    )
    store = fresh("innocent-failure-adjacent", innocent_failure)
    maybe_payload = expect_clean_prepare("innocent-failure-adjacent", store, innocent_failure)
    if maybe_payload is not None:
        measured = measure_prepared(store, innocent_failure, _PROBE_OFFER, 1)
        check(
            measured["unapproved_episode_disclosures"] == 0,
            "an innocent same-domain bullet was treated as a confirmed disclosure",
        )
        check(maybe_payload.version == 1, "an innocent same-domain bullet blocked the draft")

    # 6 — a genuinely unrelated episode, sharing no vocabulary at all, is
    # treated identically to states 1-5: undecidable, because the rule is
    # unconditional rather than conditioned on how much text is shared.
    plain = _probe_master()
    store = fresh("unrelated", plain)
    _probe_prepare(store, plain, approved=(0,))
    measured = measure_prepared(store, plain, _PROBE_OFFER, 1)
    check(
        _named_undecidable(measured, failure),
        "a genuinely unrelated episode was not reported as undecidable",
    )
    check(
        measured["unapproved_episode_disclosures"] == 0,
        "a genuinely unrelated episode was treated as a confirmed disclosure",
    )

    # 7 — exact substance still reads as a confirmed finding, never a
    # downgrade to undecidable: the `elif` in `measure_prepared` is reached
    # only when the `if` (shingle match) already failed.
    smuggled = _probe_master(headline=win.rstrip("."))
    store = fresh("exact-smuggled", smuggled)
    with contextlib.suppress(ApprovalError):
        _probe_prepare(store, smuggled)
    measured = measure_prepared(store, smuggled, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] == 1,
        "an exact match was not reported as a confirmed disclosure",
    )
    check(not _named_undecidable(measured, win), "an exact match was downgraded to undecidable")

    # 8 — a literal, unbacked planted line: present verbatim in the raw
    # document, so this sweep *does* have evidence — it must not be reported
    # as undecidable (no evidence) or counted twice against `findings`.
    store = fresh("planted-unbacked", plain)
    _probe_prepare(store, plain, approved=(0,))
    letter = store.path(*_version_parts(_PROBE_OFFER, 1), "letter.md")
    letter.write_text(letter.read_text(encoding="utf-8") + failure + "\n", encoding="utf-8")
    measured = measure_prepared(store, plain, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] == 1,
        "a planted unbacked line was not reported as a confirmed disclosure",
    )
    check(
        not _named_undecidable(measured, failure),
        "a literal planted line was reported as undecidable despite being confirmed present",
    )

    # 9 — an episode that is both approved and disclosed shares its own
    # vocabulary with its own rendered line by construction; it must never
    # appear in `undecidable_episodes` for that reason alone.
    store = fresh("approved-overlap", plain)
    _probe_prepare(store, plain, approved=(0, 1))
    measured = measure_prepared(store, plain, _PROBE_OFFER, 1)
    check(
        measured["episodes_undecidable"] == 0,
        "an approved, disclosed episode was flagged undecidable against its own text",
    )
    # The skip guard two loops below reads `disclosed or approved`, and the
    # case above exercises both disjuncts at once — it cannot tell which one
    # is doing the work.
    #
    # R7-2 (#435 round 7, advisory). A previous round of this comment argued
    # `disclosed` was not independently pinnable "because whenever an episode
    # is disclosed its literal, unedited text is on the page, and the `elif`
    # branch's self-match protects it regardless of whether `disclosed` is
    # even in the guard" — and then treated that as a fact about the *gate*
    # rather than checking it against a state the module's own mechanics
    # already construct. It is reachable: D-24 is exactly `disclosed and not
    # approved` by construction (`approved -= withdrawn` removes the text
    # from `approved` while the manifest row and the rendered line both stay
    # on disk), and state 21 already builds it. What was true under round
    # six's rival-against-`master.episodes` rule is not true here. Measured:
    # under R7's `_normalised_equal` self-match, dropping `disclosed` from
    # the guard (leaving `approved` alone) still leaves a disclosed-but-
    # unapproved episode's own exact wording sitting in `unbacked`, so the
    # `continue` two names below still fires on it regardless of the guard —
    # `disclosed` and the self-match test the property twice, not once. That
    # makes `disclosed` genuinely redundant in *this* rule (it was not, under
    # round six's), which is worth stating plainly rather than repeating a
    # claim measured against code this file no longer runs. It stays in the
    # guard anyway: removing it buys nothing (the self-match already covers
    # every case it would have), and a disjunct that costs nothing to keep is
    # not a defect merely for being provably unreachable — unlike a check
    # that reads green while measuring nothing, this one reads green because
    # a *different* line already measures the same thing. `approved` alone
    # *is* independently pinnable, unchanged from before: strip win's line
    # from `letter.md` after drafting (T114's own class of edit) while its
    # approval and manifest claim both stand. Its literal text is gone, so
    # nothing is left in `unbacked` to self-match against, and only the
    # `approved` half of the guard stops it landing in `undecidable`.
    letter = store.path(*_version_parts(_PROBE_OFFER, 1), "letter.md")
    letter.write_text(
        "\n".join(line for line in letter.read_text(encoding="utf-8").splitlines() if line != win)
        + "\n",
        encoding="utf-8",
    )
    measured = measure_prepared(store, plain, _PROBE_OFFER, 1)
    check(
        not _named_undecidable(measured, win),
        "the `approved` disjunct alone did not exempt a disclosed-but-deleted line",
    )

    # 10 — `payload.json` carries the third state rather than staying silent
    # about it, per the module docstring's T156 section.
    store = fresh("payload-carries", paraphrased)
    payload = _probe_prepare(store, paraphrased)
    check(
        len(payload.undecidable_episodes) == 1 and win in payload.undecidable_episodes[0],
        "an undecidable episode was prepared without payload.json naming it",
    )

    # 11 — the boundary's refusal message names the undecidable episode when a
    # refusal fires for a *different*, confirmed reason (F4): a draft holding
    # one approved-and-disclosed episode, one paraphrased-and-undecidable
    # episode, and one verbatim-planted-and-confirmed episode.
    combined = CVMaster(
        headline=SourcedText(text=_FIXTURE_FAILURE_PARAPHRASE),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(_FIXTURE_EPISODES[0], _FIXTURE_EPISODES[1], _FIXTURE_SMUGGLED_EPISODE),
    )
    store = fresh("boundary-message", combined)
    payload = _probe_prepare(store, combined, approved=(0,))
    letter = store.path(*_version_parts(_PROBE_OFFER, 1), "letter.md")
    letter.write_text(
        letter.read_text(encoding="utf-8") + _FIXTURE_SMUGGLED_EPISODE.text + "\n",
        encoding="utf-8",
    )
    try:
        record_sent(store, combined, _PROBE_OFFER, 1, confirms=payload_digest(payload))
        message = ""
    except ApprovalError as exc:
        message = str(exc)
    check(_FIXTURE_SMUGGLED_EPISODE.text in message, "the confirmed finding was not named")
    check("undecid" in message and failure in message, "the undecidable episode was not named")

    # 12 — N2 (#435 round 3): a shingle match against a *different, approved*
    # episode's own rendered line is not evidence for this one. `_FIXTURE_TWIN`
    # overlaps `win` by a whole eight-word window (see its own definition); win
    # is approved and rendered, the twin is not approved and never rendered.
    # Before round 3's fix the twin's shingle matched win's approved sentence
    # and the twin was silently cleared from every channel: not a finding, and
    # not undecidable either. This state moved zero times across two review
    # rounds while pinned only in pytest — accepted into this probe now so the
    # denominator that certifies T156 actually covers it.
    twinned = _probe_master(
        headline="Data platform engineer", episodes=(_FIXTURE_EPISODES[0], _FIXTURE_TWIN)
    )
    store = fresh("twin-unapproved", twinned)
    _probe_prepare(store, twinned, approved=(0,))
    measured = measure_prepared(store, twinned, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] == 0,
        "an approved episode's own line falsely confirmed a different, unapproved twin",
    )
    note_if_silently_cleared(measured, _FIXTURE_TWIN.text)
    check(
        _named_undecidable(measured, _FIXTURE_TWIN.text),
        "an unapproved twin sharing an approved line's window was not reported as undecidable",
    )

    # 13 — F1 (#435 round 4, the blocker): two lines that are never adjacent on
    # any real page — one planted in `cv.md`, one in `letter.md` — must not
    # manufacture a shingle across the seam where a naive `"\n".join(...)`
    # would put them together. `seam_episode`'s eight words are split 4/4
    # across exactly that seam: neither planted line alone carries more than
    # four of them, but the tail of one directly against the head of the
    # other carries all eight contiguously. Round 3's fix still joined every
    # `unbacked` line before searching and read this as "confirmed present";
    # round 4 checks each line on its own.
    seam_head = "Zulu yankee xray whiskey alpha bravo charlie delta"
    seam_tail = "echo foxtrot golf hotel india juliet kilo lima"
    seam_episode = Episode(
        kind="achievement", text="Alpha bravo charlie delta echo foxtrot golf hotel"
    )
    seamed = _probe_master(episodes=(_FIXTURE_EPISODES[0], seam_episode))
    store = fresh("seam", seamed)
    _probe_prepare(store, seamed, approved=(0,))
    cv = store.path(*_version_parts(_PROBE_OFFER, 1), "cv.md")
    cv.write_text(cv.read_text(encoding="utf-8") + seam_head + "\n", encoding="utf-8")
    letter = store.path(*_version_parts(_PROBE_OFFER, 1), "letter.md")
    letter.write_text(letter.read_text(encoding="utf-8") + seam_tail + "\n", encoding="utf-8")
    measured = measure_prepared(store, seamed, _PROBE_OFFER, 1)
    check(
        not any(seam_episode.text in item for item in measured["unapproved_episodes"]),
        "a seam between two unbacked lines manufactured a confirmed disclosure",
    )
    note_if_silently_cleared(measured, seam_episode.text)
    check(
        _named_undecidable(measured, seam_episode.text),
        "a seam between two unbacked lines silently cleared an unrelated episode",
    )

    # 14 — R5-1 (#435 round 5, the blocker), route (A): the approved line
    # duplicated verbatim. `win` is approved and rendered once; `_FIXTURE_TWIN`
    # is never approved and never rendered at all, and overlaps `win` by a
    # whole eight-word window (see its own definition). `unbacked` is
    # populated by a Counter test (`backed[key] == 0`), not a text test, so
    # the *second*, unbacked copy of win's own line lands in `unbacked` even
    # though its text is in `approved` — and before this round's fix that let
    # the elif read it as "confirmed present" for the twin, clearing the twin
    # from both channels exactly as the round-three defect did.
    duplicated = _probe_master(
        headline="Data platform engineer", episodes=(_FIXTURE_EPISODES[0], _FIXTURE_TWIN)
    )
    store = fresh("duplicated-approved-line", duplicated)
    _probe_prepare(store, duplicated, approved=(0,))
    letter = store.path(*_version_parts(_PROBE_OFFER, 1), "letter.md")
    letter.write_text(letter.read_text(encoding="utf-8") + win + "\n", encoding="utf-8")
    measured = measure_prepared(store, duplicated, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] == 1,
        "a duplicated approved line was not reported as its own unbacked disclosure",
    )
    note_if_silently_cleared(measured, _FIXTURE_TWIN.text)
    check(
        _named_undecidable(measured, _FIXTURE_TWIN.text),
        "a duplicated approved line falsely confirmed a different, unapproved twin (R5-1A)",
    )

    # 15 — R5-1, route (B): the manifest row for an approved, rendered episode
    # deleted after drafting — T114's class of post-draft edit, applied to
    # this seam rather than to the disclosure sweep — while the approval and
    # the rendered line both stay on disk. With the claim gone, `backed` is
    # never incremented for that key, so win's own untouched line lands in
    # `unbacked` by the same Counter-vs-text gap as route (A), and must not
    # clear the twin from both channels either.
    manifest_edited = _probe_master(
        headline="Data platform engineer", episodes=(_FIXTURE_EPISODES[0], _FIXTURE_TWIN)
    )
    store = fresh("manifest-row-deleted", manifest_edited)
    _probe_prepare(store, manifest_edited, approved=(0,))
    manifest_path = store.path(*_version_parts(_PROBE_OFFER, 1), "manifest.json")
    manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    manifest = manifest.model_copy(
        update={"claims": tuple(claim for claim in manifest.claims if claim.text != win)}
    )
    manifest_path.write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")
    measured = measure_prepared(store, manifest_edited, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] == 1,
        "a manifest row deleted out from under an approved line was not reported as its "
        "own unbacked disclosure",
    )
    note_if_silently_cleared(measured, _FIXTURE_TWIN.text)
    check(
        _named_undecidable(measured, _FIXTURE_TWIN.text),
        "a manifest row deleted out from under an approved line falsely confirmed a "
        "different, unapproved twin (R5-1B)",
    )

    # 16-20 — R6-1 (#435 round 6, the blocker): a line one edit away from win's
    # own approved sentence, not win itself. Round five's `if line not in
    # approved` is an exact-text test, so any of the five edits `_carries`'s
    # own docstring names as beaten by normalisation — dropped trailing
    # punctuation, case, inserted punctuation, an appended clause, doubled
    # whitespace — is not `in approved` by byte equality, gets searched again,
    # and (before round six's fix) cleared the twin from both channels exactly
    # as an exact duplicate did before round five.
    def check_near_copy_route(handle: str, near_copy: str, edit: str) -> None:
        twinned_near = _probe_master(
            headline="Data platform engineer", episodes=(_FIXTURE_EPISODES[0], _FIXTURE_TWIN)
        )
        store = fresh(handle, twinned_near)
        _probe_prepare(store, twinned_near, approved=(0,))
        letter = store.path(*_version_parts(_PROBE_OFFER, 1), "letter.md")
        letter.write_text(letter.read_text(encoding="utf-8") + near_copy + "\n", encoding="utf-8")
        measured = measure_prepared(store, twinned_near, _PROBE_OFFER, 1)
        check(
            measured["unapproved_episode_disclosures"] == 1,
            f"a near-copy of win's line ({edit}) was not reported as its own unbacked disclosure",
        )
        note_if_silently_cleared(measured, _FIXTURE_TWIN.text)
        check(
            _named_undecidable(measured, _FIXTURE_TWIN.text),
            f"a near-copy of win's line ({edit}) falsely confirmed a different, "
            "unapproved twin (R6-1)",
        )

    check_near_copy_route("near-copy-no-period", win.rstrip("."), "trailing period dropped")
    check_near_copy_route("near-copy-uppercased", win.upper(), "uppercased")
    check_near_copy_route(
        "near-copy-comma",
        win.replace("forty minutes by", "forty minutes, by"),
        "comma inserted",
    )
    check_near_copy_route(
        "near-copy-clause",
        win.rstrip(".") + ", ahead of schedule.",
        "clause appended",
    )
    check_near_copy_route(
        "near-copy-double-space",
        win.replace("nightly billing", "nightly  billing"),
        "double space",
    )

    # 21 — R6-2 (#435 round 6, the blocker): a D-24 retraction of win's own
    # evidence, with **no document edit at all**. `approved -= withdrawn`
    # (above) removes win's text from `approved` the moment the log carries a
    # retraction, so a filter keyed on `approved` stops applying to the
    # twin's line the instant the candidate withdraws the *other* episode —
    # nothing about the page itself changes.
    from integral.retraction import retract as _retract

    retracted_twin_state = _probe_master(
        headline="Data platform engineer", episodes=(_FIXTURE_EPISODES[0], _FIXTURE_TWIN)
    )
    store = fresh("retracted-approved-twin", retracted_twin_state)
    row = (
        EvidenceLog(store)
        .append(
            recorded_at="2026-01-01T09:00:00+00:00",
            step="history",
            kind="episode",
            text=win,
            source="conversation",
        )
        .id
    )
    _probe_prepare(store, retracted_twin_state, approved=(0,))
    _retract(EvidenceLog(store), row, at="2026-01-02T09:00:00+00:00")
    measured = measure_prepared(store, retracted_twin_state, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] == 1,
        "win's own line was not reported once its approval's evidence was retracted",
    )
    note_if_silently_cleared(measured, _FIXTURE_TWIN.text)
    check(
        _named_undecidable(measured, _FIXTURE_TWIN.text),
        "retracting win's evidence, with no document edit, falsely confirmed a different, "
        "unapproved twin (R6-2)",
    )

    # 22 — R7-1a (#435 round 7, the blocker): state 14's own construction —
    # win's exact line duplicated on the page, the second copy unbacked —
    # replayed with **win additionally removed from `master.episodes`** at
    # measurement time: the candidate tidying that story out of their bank
    # after the draft was written, letter untouched. Round six's rival check
    # quantified over `master.episodes`; with `win` no longer in it, there is
    # no "other" episode left to make the duplicate line ambiguous, and the
    # twin it was protecting is silently cleared again — the second reader's
    # own measurement: round five's `line not in approved` gets this right
    # (a bank edit does not touch `approvals.json`), round six's relation
    # gets it wrong. `approved` and the manifest's own claim texts are
    # unaffected by editing `master.json`, which is what this state pins.
    duplicated_edited = _probe_master(
        headline="Data platform engineer", episodes=(_FIXTURE_EPISODES[0], _FIXTURE_TWIN)
    )
    store = fresh("dup-line-bank-edited", duplicated_edited)
    _probe_prepare(store, duplicated_edited, approved=(0,))
    letter = store.path(*_version_parts(_PROBE_OFFER, 1), "letter.md")
    letter.write_text(letter.read_text(encoding="utf-8") + win + "\n", encoding="utf-8")
    bank_edited = duplicated_edited.model_copy(update={"episodes": (_FIXTURE_TWIN,)})
    measured = measure_prepared(store, bank_edited, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] == 1,
        "a duplicated approved line was not reported as its own unbacked disclosure "
        "once the authoring episode was removed from the bank (R7-1a)",
    )
    note_if_silently_cleared(measured, _FIXTURE_TWIN.text)
    check(
        _named_undecidable(measured, _FIXTURE_TWIN.text),
        "removing win from the bank after drafting reopened the duplicated-line seam and "
        "falsely confirmed a different, unapproved twin (R7-1a)",
    )

    # 23 — R7-1b (#435 round 7, the blocker): state 15's construction — win's
    # manifest row deleted post-draft, its one rendered line left unbacked —
    # replayed with the same bank edit as state 22. `approved` still names
    # win's text (it is read from `approvals.json`, untouched by either the
    # manifest edit or the bank edit), so the rival is still findable through
    # it even though the manifest claim that used to carry win's text is now
    # gone too.
    manifest_edited_and_bank_edited = _probe_master(
        headline="Data platform engineer", episodes=(_FIXTURE_EPISODES[0], _FIXTURE_TWIN)
    )
    store = fresh("manifest-row-bank-edited", manifest_edited_and_bank_edited)
    _probe_prepare(store, manifest_edited_and_bank_edited, approved=(0,))
    manifest_path = store.path(*_version_parts(_PROBE_OFFER, 1), "manifest.json")
    manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    manifest = manifest.model_copy(
        update={"claims": tuple(claim for claim in manifest.claims if claim.text != win)}
    )
    manifest_path.write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")
    bank_edited = manifest_edited_and_bank_edited.model_copy(update={"episodes": (_FIXTURE_TWIN,)})
    measured = measure_prepared(store, bank_edited, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] == 1,
        "a manifest row deleted out from under an approved line was not reported as its own "
        "unbacked disclosure once the authoring episode was removed from the bank (R7-1b)",
    )
    note_if_silently_cleared(measured, _FIXTURE_TWIN.text)
    check(
        _named_undecidable(measured, _FIXTURE_TWIN.text),
        "removing win from the bank after drafting reopened the manifest-row-deleted seam "
        "and falsely confirmed a different, unapproved twin (R7-1b)",
    )

    # 24 — R7-1c (#435 round 7, not a regression — round five clears it too,
    # and neither round ever closed it): a single-episode bank has no rival
    # by construction, so a hand-added line sharing an eight-word window with
    # the one episode clears it with **zero approvals and zero post-draft
    # edits** — the cheapest state in this family to build, and not an edge
    # case: any candidate with one story in their bank so far is this state.
    # `win` here is never approved, never manifested, and never removed from
    # anything; `_FIXTURE_TWIN.text` is hand-added directly, the way state 8
    # plants a raw line, and was never itself an episode in this bank. Round
    # six's rival check had nothing to compare `win` against (`master.episodes`
    # holds only `win`), so it passed the line as confirmed; `_normalised_equal`
    # closes it with no rival at all — `_FIXTURE_TWIN.text` is not the same
    # whole run of words as `win.text` (their final words differ), so it
    # cannot self-match, and `win` is correctly left undecidable.
    single = _probe_master(headline="Data platform engineer", episodes=(_FIXTURE_EPISODES[0],))
    store = fresh("single-episode-bank", single)
    _probe_prepare(store, single, approved=())
    letter = store.path(*_version_parts(_PROBE_OFFER, 1), "letter.md")
    letter.write_text(
        letter.read_text(encoding="utf-8") + _FIXTURE_TWIN.text + "\n", encoding="utf-8"
    )
    measured = measure_prepared(store, single, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] == 1,
        "a hand-added line sharing an eight-word window was not reported as its own "
        "unbacked disclosure on a single-episode bank (R7-1c)",
    )
    note_if_silently_cleared(measured, win)
    check(
        _named_undecidable(measured, win),
        "a single-episode bank left no rival to detect, and a hand-added line sharing an "
        "eight-word window falsely confirmed the one episode in the bank (R7-1c)",
    )

    # 25 — R8-1a (#435 round 8, the blocker, F-1's first route): state 14's
    # own construction — the approved episode's exact line duplicated on the
    # page as a second, unbacked copy — replayed with the *signed* pair
    # instead of the shingle-overlap twin. Before this round's fix, the
    # duplicate (still `+12%`) and the failure episode's text (`-12%`)
    # reduced to the identical word run once `_words` deleted the sign, and
    # the failure was silently cleared exactly as the twin was in state 14 —
    # not a shingle-window coincidence this time, a whole-run one, which is
    # why removing the rival check (R7-1) did not close it: there was no
    # rival to fail to find, the equality test itself was wrong.
    signed = _probe_master(
        headline="Data platform engineer",
        episodes=(_FIXTURE_SIGNED_ACHIEVEMENT, _FIXTURE_SIGNED_FAILURE),
    )
    store = fresh("signed-duplicated-line", signed)
    _probe_prepare(store, signed, approved=(0,))
    letter = store.path(*_version_parts(_PROBE_OFFER, 1), "letter.md")
    letter.write_text(
        letter.read_text(encoding="utf-8") + _FIXTURE_SIGNED_ACHIEVEMENT.text + "\n",
        encoding="utf-8",
    )
    measured = measure_prepared(store, signed, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] == 1,
        "a duplicated approved line was not reported as its own unbacked disclosure (R8-1a)",
    )
    note_if_silently_cleared(measured, _FIXTURE_SIGNED_FAILURE.text)
    check(
        _named_undecidable(measured, _FIXTURE_SIGNED_FAILURE.text),
        "a sign flip let the approved achievement's duplicated line falsely confirm the "
        "unapproved failure episode about the same metric (R8-1a, F-1)",
    )

    # 26 — R8-1b (#435 round 8, the blocker, F-1's second route): state 15's
    # construction — the approved episode's manifest row deleted post-draft,
    # leaving its one rendered line unbacked with no document edit — replayed
    # with the signed pair.
    signed_manifest = _probe_master(
        headline="Data platform engineer",
        episodes=(_FIXTURE_SIGNED_ACHIEVEMENT, _FIXTURE_SIGNED_FAILURE),
    )
    store = fresh("signed-manifest-row-deleted", signed_manifest)
    _probe_prepare(store, signed_manifest, approved=(0,))
    manifest_path = store.path(*_version_parts(_PROBE_OFFER, 1), "manifest.json")
    manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    manifest = manifest.model_copy(
        update={
            "claims": tuple(
                claim for claim in manifest.claims if claim.text != _FIXTURE_SIGNED_ACHIEVEMENT.text
            )
        }
    )
    manifest_path.write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")
    measured = measure_prepared(store, signed_manifest, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] == 1,
        "a manifest row deleted out from under an approved line was not reported as its "
        "own unbacked disclosure (R8-1b)",
    )
    note_if_silently_cleared(measured, _FIXTURE_SIGNED_FAILURE.text)
    check(
        _named_undecidable(measured, _FIXTURE_SIGNED_FAILURE.text),
        "a manifest row deleted out from under an approved line, combined with a sign "
        "flip, falsely confirmed the unapproved failure episode about the same metric "
        "(R8-1b, F-1)",
    )

    # 27 — R8-1c (#435 round 8, the blocker, F-1's third route, its own
    # sharpest: state 21's construction — a D-24 retraction of the approved
    # episode's evidence, with **zero document edits at all** — replayed with
    # the signed pair. Nothing about the page changes; only `approved` loses
    # the achievement's text, which is enough to move its own untouched line
    # into `unbacked` and, before this round's fix, into false agreement with
    # the failure episode's opposite-signed text.
    signed_retracted = _probe_master(
        headline="Data platform engineer",
        episodes=(_FIXTURE_SIGNED_ACHIEVEMENT, _FIXTURE_SIGNED_FAILURE),
    )
    store = fresh("signed-retracted-approved", signed_retracted)
    row = (
        EvidenceLog(store)
        .append(
            recorded_at="2026-01-01T09:00:00+00:00",
            step="history",
            kind="episode",
            text=_FIXTURE_SIGNED_ACHIEVEMENT.text,
            source="conversation",
        )
        .id
    )
    _probe_prepare(store, signed_retracted, approved=(0,))
    _retract(EvidenceLog(store), row, at="2026-01-02T09:00:00+00:00")
    measured = measure_prepared(store, signed_retracted, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] == 1,
        "the achievement's own line was not reported once its approval's evidence was "
        "retracted (R8-1c)",
    )
    note_if_silently_cleared(measured, _FIXTURE_SIGNED_FAILURE.text)
    check(
        _named_undecidable(measured, _FIXTURE_SIGNED_FAILURE.text),
        "retracting the achievement's evidence, with no document edit, combined with a "
        "sign flip, falsely confirmed the unapproved failure episode about the same "
        "metric (R8-1c, F-1)",
    )

    # 28 — R8-2 (#435 round 8, F-2): the positive direction F-2 named missing
    # — every prior state that needed `_normalised_equal` to return `True`
    # needed it on a byte-identical pair, so a mutant that deletes the fold
    # entirely (`line == episode`) passed all 24 states unnoticed. This state
    # is a genuine near-copy — case and doubled internal whitespace differ,
    # nothing else — planted as the *only* line for an unapproved,
    # unmanifested, single-episode bank. Confirmed here means the fold fired;
    # `_named_undecidable` must be `False`, which the byte-equality mutant
    # gets wrong (no doc string differs *by content*, only by case and
    # spacing, so a bare `==` sends it to the shingle-match branch instead).
    near_copy = " ".join(win.upper().split()).replace("BILLING RUN", "BILLING  RUN")
    single_for_near_copy = _probe_master(
        headline="Data platform engineer", episodes=(_FIXTURE_EPISODES[0],)
    )
    store = fresh("near-copy-self-match", single_for_near_copy)
    _probe_prepare(store, single_for_near_copy, approved=())
    letter = store.path(*_version_parts(_PROBE_OFFER, 1), "letter.md")
    letter.write_text(letter.read_text(encoding="utf-8") + near_copy + "\n", encoding="utf-8")
    measured = measure_prepared(store, single_for_near_copy, _PROBE_OFFER, 1)
    check(
        measured["unapproved_episode_disclosures"] == 1,
        "a case- and whitespace-varied near-copy was not reported as its own unbacked "
        "disclosure (R8-2)",
    )
    check(
        not _named_undecidable(measured, win),
        "a genuine near-copy (case and whitespace only) was not recognised as the "
        "episode's own wording and was wrongly left undecidable (R8-2, F-2)",
    )

    return {
        "paraphrase_states_evaluated": states,
        "paraphrase_checks_evaluated": checks,
        "paraphrased_substance_reported_as_withheld": reported_as_withheld,
        "paraphrase_probe_failures": failures,
        "gate_status": "measured" if states else "unmeasured",
    }


# ---------------------------------------------------------------------------
# the gate — measured over the real corpus, against a stated fixture candidate

# How many prepared applications the measurement also carries through the send
# boundary. A handful, not all of them.
_RECORDED_SENDS = 5


def measure(
    fixture_master: Path = DEFAULT_FIXTURE_MASTER,
    store_path: Path | None = None,
) -> dict[str, Any]:
    """`unapproved_episode_disclosures` over every advert in the labelled corpus.

    Real advert text, a stated fixture candidate — there is no person in this
    repository and there must not be one. The episodes are added to the fixture
    here rather than committed into it, so T45's fixture keeps measuring exactly
    what T45 wrote it to measure.

    This half proves the boundary holds on adverts it did not choose;
    `probe_boundary`, folded in below, proves it can find something.
    """
    from integral.harness import DEFAULT_STORE_PATH, load_store

    committed = CVMaster.model_validate_json(fixture_master.read_text(encoding="utf-8"))
    master = committed.model_copy(update={"episodes": _FIXTURE_EPISODES})
    ads = load_store(store_path or DEFAULT_STORE_PATH)

    disclosures = 0
    undecidable_total = 0
    unapproved: list[str] = []
    recorded = 0
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "profiles"
        identity = create_profile(root, "Gate Fixture", handle="fixture", language="en")
        store = ProfileStore(root, identity.handle)
        write_master(store, master)
        for position, ad in enumerate(ads):
            payload = prepare(
                store,
                master,
                offer_id=ad.id,
                advert=ad.text,
                recipient=f"hiring team, {ad.id}",
                details=_FIXTURE_DETAILS,
                asks=_FIXTURE_ASKS,
                approved_episodes=(0,),
            )
            measured = measure_prepared(store, master, ad.id, payload.version)
            disclosures += measured["episode_disclosures"]
            undecidable_total += measured["episodes_undecidable"]
            unapproved.extend(measured["unapproved_episodes"])
            if position < _RECORDED_SENDS:
                record_sent(store, master, ad.id, payload.version, confirms=payload_digest(payload))
                recorded += 1

        leaked = personal_details_in_master(store, _FIXTURE_DETAILS)
        unconfirmed = sends_without_confirmation(store)
        # T114 over the same tree, before the scratch directory goes: two hundred
        # real letters, each joined back to the manifest that claims to describe
        # it. `probe_unbacked_disclosures` is the half that plants divergences;
        # this is the half that says the check does not fire on documents nobody
        # touched, over a denominator neither this module nor T114 chose.
        unbacked = disclosures_unbacked_by_a_document(store, master)

    with tempfile.TemporaryDirectory() as scratch:
        probed = probe_boundary(Path(scratch) / "profiles")

    return {
        "episode_approval_coverage": (
            None if disclosures == 0 else (disclosures - len(unapproved)) / disclosures
        ),
        "unapproved_episode_disclosures": len(unapproved),
        "unapproved_episodes": sorted(unapproved),
        "disclosures_unbacked_by_a_generated_document": unbacked[
            "disclosures_unbacked_by_a_generated_document"
        ],
        "unbacked_disclosures": unbacked["unbacked_disclosures"],
        "manifest_disclosures_compared": unbacked["manifest_disclosures_compared"],
        "episode_disclosures": disclosures,
        "episodes_undecidable": undecidable_total,
        "personal_details_in_master": leaked,
        "sends_without_confirmation": unconfirmed,
        "applications_recorded": recorded,
        "adverts_prepared": len(ads),
        **probed,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    fixture_master: Path = DEFAULT_FIXTURE_MASTER,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T46.json`."""
    measured = measure(fixture_master)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def write_retraction_evidence(evidence: Path = DEFAULT_D24_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/D-24.json` — beside T46's, never inside it."""
    with tempfile.TemporaryDirectory(prefix="integral-d24-") as scratch:
        measured = probe_retracted_sends(Path(scratch) / "profiles")
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def write_disclosure_evidence(
    evidence: Path = DEFAULT_T114_EVIDENCE_PATH,
    corpus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T114.json` — the probes plus the corpus pass.

    `corpus` is `measure()`'s reading over the fixture tree, passed in by `_main`
    because it has already paid for it. Given nothing, this measures it again
    rather than reporting over the probes alone: a gate whose only denominator is
    the fixtures its own author wrote is the shape this task exists to close.
    """
    with tempfile.TemporaryDirectory(prefix="integral-t114-") as scratch:
        probed = probe_unbacked_disclosures(Path(scratch) / "profiles")
    over_the_corpus = measure() if corpus is None else corpus
    found = sorted([*probed["unbacked_disclosures"], *over_the_corpus["unbacked_disclosures"]])
    compared = (
        probed["manifest_disclosures_compared"] + over_the_corpus["manifest_disclosures_compared"]
    )
    measured = {
        "disclosures_unbacked_by_a_generated_document": len(found),
        "unbacked_disclosures": found,
        "manifest_disclosures_compared": compared,
        "gate_status": "measured" if compared else "unmeasured",
        "disclosure_probes": probed["disclosure_probes"],
        "disclosure_probe_failures": probed["disclosure_probe_failures"],
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _disclosure_report(measured: dict[str, Any]) -> int:
    """Print T114's measurement and say whether it fails the gate."""
    print(json.dumps(measured, ensure_ascii=False))
    failures = 0
    for key, label in (
        ("disclosure_probe_failures", "the disclosure boundary failed a planted case"),
        ("unbacked_disclosures", "a disclosure no generated document carries"),
    ):
        for name in measured[key]:
            print(f"✗ {label}: {name}", file=sys.stderr)
            failures += 1
    for key, floor in (
        ("disclosure_probes", MINIMUM_DISCLOSURE_PROBES),
        ("manifest_disclosures_compared", MINIMUM_MANIFEST_DISCLOSURES_COMPARED),
    ):
        if measured[key] < floor:
            print(f"{key} is {measured[key]}, below the floor of {floor}", file=sys.stderr)
            failures += 1
    # The corpus pass discloses an episode per advert and the probes leave two
    # clean trees standing, so `unmeasured` here is a measurement that stopped
    # reaching the documents — the clean zero this gate is about, one level up.
    if measured["gate_status"] != "measured":
        print(
            "no manifest disclosure was compared against a document — nothing was measured",
            file=sys.stderr,
        )
        failures += 1
    return 1 if failures else 0


def write_paraphrase_evidence(evidence: Path = DEFAULT_T156_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T156.json` — beside T46's, never inside it.

    Probes only, unlike T114's corpus-plus-probes reading: the corpus's two
    fixture episodes are chosen for T46 and D-24's purposes and are not
    themselves paraphrased anywhere in the labelled adverts, so folding the
    corpus pass in here would only add a denominator of confidently-clean
    states and no numerator either way. `MINIMUM_PARAPHRASE_STATES` is the
    floor over the constructed states instead, in the `naming.MINIMUM_SCANNED`
    style: a states list that shrank to nothing must not still clear `== 0`.
    """
    with tempfile.TemporaryDirectory(prefix="integral-t156-") as scratch:
        measured = probe_paraphrase_undecidability(Path(scratch) / "profiles")
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _paraphrase_report(measured: dict[str, Any]) -> int:
    """Print T156's measurement and say whether it fails the gate."""
    print(json.dumps(measured, ensure_ascii=False))
    failures = 0
    for name in measured["paraphrase_probe_failures"]:
        print(f"✗ the paraphrase boundary failed a constructed case: {name}", file=sys.stderr)
        failures += 1
    if measured["paraphrased_substance_reported_as_withheld"]:
        print(
            "paraphrased_substance_reported_as_withheld is "
            f"{measured['paraphrased_substance_reported_as_withheld']}, not 0",
            file=sys.stderr,
        )
        failures += 1
    for key, floor in (
        ("paraphrase_states_evaluated", MINIMUM_PARAPHRASE_STATES),
        ("paraphrase_checks_evaluated", MINIMUM_PARAPHRASE_CHECKS),
    ):
        if measured[key] < floor:
            print(f"{key} is {measured[key]}, below the floor of {floor}", file=sys.stderr)
            failures += 1
    # The probes always construct at least one paraphrase, so `unmeasured` here
    # is a probe set that stopped reaching the check — a broken gate, not an
    # unscored one, exactly as for T114 and D-24 above.
    if measured["gate_status"] != "measured":
        print(
            "no constructed paraphrase was measured — the probe measured nothing",
            file=sys.stderr,
        )
        failures += 1
    return 1 if failures else 0


def _retraction_report(measured: dict[str, Any]) -> int:
    """Print D-24's measurement and say whether it fails the gate."""
    print(json.dumps(measured, ensure_ascii=False))
    failures = 0
    # Two lists, two meanings, and one of them is the opposite of the other:
    # `retraction_probe_failures` holds the over-refusal cases too ("a clean
    # send was refused"), so printing "still sendable" over both told whoever
    # read the red gate the reverse of what had happened (#305 review).
    for key, label in (
        ("retraction_probe_failures", "the retraction boundary failed a planted case"),
        ("retracted_episodes_sendable", "a retracted episode was still sendable"),
    ):
        for name in measured[key]:
            print(f"✗ {label}: {name}", file=sys.stderr)
            failures += 1
    for key, floor in (
        ("retraction_probes", MINIMUM_RETRACTION_PROBES),
        ("retracted_episodes_evaluated", MINIMUM_RETRACTED_APPROVALS_EVALUATED),
    ):
        if measured[key] < floor:
            print(f"{key} is {measured[key]}, below the floor of {floor}", file=sys.stderr)
            failures += 1
    # The probes always plant a retraction, so `unmeasured` here is a probe set
    # that stopped reaching the check — a broken gate, not an unscored one.
    if measured["gate_status"] != "measured":
        print(
            "no approval was checked against a retraction — the probe measured nothing",
            file=sys.stderr,
        )
        failures += 1
    return 1 if failures else 0


def _main(argv: list[str] | None = None) -> int:
    """Write T46's and D-24's gate evidence. Exit 1 on any disclosure no approval backs."""
    args = [arg for arg in (argv if argv is not None else sys.argv)[1:] if not arg.startswith("--")]
    target = Path(args[0]) if args else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    failures = 0
    for key, label in (
        ("unapproved_episodes", "disclosed with no per-use approval"),
        ("unbacked_disclosures", "a disclosure no generated document carries"),
        ("personal_details_in_master", "personal detail in the intake store"),
        ("sends_without_confirmation", "send recorded without confirming its payload"),
        ("detection_probe_failures", "the boundary failed to catch a planted defect"),
    ):
        for name in measured[key]:
            print(f"✗ {label}: {name}", file=sys.stderr)
            failures += 1
    print(json.dumps(measured, ensure_ascii=False))

    # Three empty denominators, each of which would otherwise be a gate that
    # passed because nothing happened.
    for key, floor in (
        ("episode_disclosures", 1),
        ("applications_recorded", 1),
        ("detection_probes", MINIMUM_PROBES),
    ):
        if measured[key] < floor:
            print(f"{key} is {measured[key]}, below the floor of {floor}", file=sys.stderr)
            failures += 1
    if measured["episode_approval_coverage"] != 1.0:
        print(
            f"episode_approval_coverage is {measured['episode_approval_coverage']!r}, not 1.0",
            file=sys.stderr,
        )
        failures += 1
    # Written unconditionally, before the exit code is decided: short-circuiting
    # here would leave `D-24.json` stale whenever T46 was red, and `make
    # evidence` would then report drift in the gate that was still passing.
    # Beside T46's record wherever that was asked for, so a run pointed at a
    # scratch directory writes nothing into the repo (#305 review); with no
    # argument this is exactly `DEFAULT_D24_EVIDENCE_PATH`.
    retraction_exit = _retraction_report(
        write_retraction_evidence(target.with_name(DEFAULT_D24_EVIDENCE_PATH.name))
    )
    # T114's record, written on the same terms and for the same reason: it is
    # `measure()`'s corpus reading plus its own probes, and short-circuiting on a
    # red T46 would leave it stale while `make evidence` reported drift in a gate
    # that was still passing.
    disclosure_exit = _disclosure_report(
        write_disclosure_evidence(target.with_name(DEFAULT_T114_EVIDENCE_PATH.name), measured)
    )
    # T156's record, written on the same unconditional terms as the two above
    # and for the same reason.
    paraphrase_exit = _paraphrase_report(
        write_paraphrase_evidence(target.with_name(DEFAULT_T156_EVIDENCE_PATH.name))
    )
    return 1 if (failures or retraction_exit or disclosure_exit or paraphrase_exit) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
