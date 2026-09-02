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

**The measurement cannot construct both sides of its own equality.** `measure()`
writes approvals and documents in one call from one tuple, so they agree by
construction: on its own it proves only that `generate` emits the indices it was
handed, and every check in this module could be deleted with the evidence
unchanged. `probe_boundary` is the other half — ten scenarios that are defects on
purpose, each asserting the boundary *catches* it. `_main` fails if any probe
fails or if fewer than `MINIMUM_PROBES` ran.

## The chokepoint

`generate` renders an episode only when handed one, and `integral.approval` is
its only supported caller — but a keyword argument inside a package is a
convention, not a lock. What is enforced is the thing that matters: **nothing
becomes sendable while an unapproved disclosure is in the document.** `prepare`
re-reads what it just wrote and refuses to write a payload over a finding, and
`record_sent` re-runs the whole measurement against the files as they stand at
send time — so a document edited after drafting is caught at the boundary, not
trusted because it was clean an hour ago.

**What the confirmation proves, and what it does not.** `record_sent` requires
the payload's own digest, which pins *which* payload was named — a standing "send
whatever you like" and a yes given to a different draft both fail it. It says
nothing about *who* named it: anyone holding the payload can compute the digest,
and `measure()` does exactly that. Consent by a human is outside what this file
can check; what it can check is that consent was given to a specific, complete,
unchanged payload, and that is what it checks.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from integral.cv_store import (
    ConversationTurn,
    CVMaster,
    Episode,
    Skill,
    SourcedText,
    _atomic_write_json,
    write_master,
)
from integral.generate import (
    DEFAULT_FIXTURE_MASTER,
    _claim_lines,
    _entries,
    generate,
    read_manifest,
    render_entry,
)
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T46.json"
DEFAULT_D24_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-24.json"

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
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    offer_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    recipient: str = Field(min_length=1)
    documents: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    episodes: tuple[str, ...] = ()
    contact_details: dict[str, str] = Field(default_factory=dict)


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
    return _NOT_WORD.sub(" ", text.casefold()).split()


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


def _squash(text: str) -> str:
    """Letters and digits only — a detail written a slightly different way."""
    return re.sub(r"[^0-9a-z]+", "", text.casefold())


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
            "written: " + "; ".join(measured["unapproved_episodes"])
        )

    payload = Payload(
        offer_id=offer_id,
        version=manifest.version,
        recipient=recipient,
        documents=tuple(sorted(path.name for path in store.path(*where).glob("*.md"))),
        claims=tuple(f"{claim.document}: {claim.text}" for claim in manifest.claims),
        episodes=tuple(approval.text for approval in approvals.episodes),
        contact_details=details.stated(),
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
            "is sendable: " + "; ".join(measured["unapproved_episodes"])
        )
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

    * **the retracted row's own text.** A text match, so it cannot tell two rows
      carrying the same sentence apart and withdraws the approval for both. That
      is deliberate: §6.2 would rather refuse a live episode than send a
      withdrawn one, and the approval carries nothing finer to match on.
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
    texts = {row.text for row in log.rows() if row.kind == "episode" and row.id in suppressed}
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
    withdrawn = approved & retracted_episode_texts(store, master)
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
    written: list[str] = []
    for name, body in documents.items():
        for line in _claim_lines(body):
            key = (name, line)
            written.append(line)
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
                findings.append(
                    f"{offer_id}/v{version} {name}: {line} — "
                    + (
                        "the candidate retracted the evidence this approval was given over"
                        if line in withdrawn
                        else "no per-use approval backs this line"
                    )
                )

    # Substance carried by something that is not an episode line: a headline or a
    # job description holding the same sentence reaches the employer just the
    # same, and used to leave `payload.json` reporting the story as withheld.
    # Checked over the backed lines only, so a line already reported above is not
    # counted a second time.
    episode_claims = [claim for claim in claims if claim.section == "episodes"]
    disclosed = {claim.text for claim in episode_claims}
    carried = 0
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

    checked = len(episode_claims) + len(findings)
    return {
        # A fraction over nothing checked is the third D-2 outcome, not a
        # passing 1.0 — `_main` fails on it.
        "episode_approval_coverage": None if checked == 0 else (checked - len(findings)) / checked,
        "unapproved_episode_disclosures": len(findings),
        "unapproved_episodes": sorted(findings),
        "episode_disclosures": len(episode_claims) + carried,
        # Measured against **every** line on disk, not just the backed ones. A
        # planted episode is excluded from `surviving`, so counting withholding
        # over `intact` reported the same sentence as disclosed and withheld in
        # one call — a summary contradicting itself.
        "episodes_withheld": sum(
            1
            for episode in master.episodes
            if episode.text not in disclosed and not _carries("\n".join(written), episode.text)
        ),
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
            if approval.text not in withdrawn:
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
MINIMUM_PROBES = 10


def _probe_master(headline: str = "Backend engineer — data platforms") -> CVMaster:
    return CVMaster(
        headline=SourcedText(text=headline),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=_FIXTURE_EPISODES,
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

    return {"detection_probes": checks, "detection_probe_failures": failures}


# Ten assertions across eight scenarios, six of which put an approval in front of
# a live retraction. Floors, not the count of the day: adding a scenario raises
# them, and a probe set that quietly shrank stops clearing them.
MINIMUM_RETRACTION_PROBES = 10
MINIMUM_RETRACTED_APPROVALS_EVALUATED = 6

_REWORDED_ROW = "Cut the nightly billing run right down — it used to take us six hours."


def probe_retracted_sends(root: Path) -> dict[str, Any]:
    """D-24: drive the send boundary against a story the candidate withdrew.

    Each scenario is a fresh profile with its own evidence log, because a
    retraction is a fact about a log and the interesting cases differ in what
    the log says. Six of the eight are defects on purpose; two are the
    over-refusal the fix must not become.
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

    return {
        "retracted_episodes_still_sendable": len(sendable),
        "retracted_episodes_sendable": sorted(sendable),
        "retracted_episodes_evaluated": evaluated,
        "gate_status": "measured" if evaluated else "unmeasured",
        "retraction_probes": checks,
        "retraction_probe_failures": failures,
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
    withheld = 0
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
            withheld += measured["episodes_withheld"]
            unapproved.extend(measured["unapproved_episodes"])
            if position < _RECORDED_SENDS:
                record_sent(store, master, ad.id, payload.version, confirms=payload_digest(payload))
                recorded += 1

        leaked = personal_details_in_master(store, _FIXTURE_DETAILS)
        unconfirmed = sends_without_confirmation(store)

    with tempfile.TemporaryDirectory() as scratch:
        probed = probe_boundary(Path(scratch) / "profiles")

    return {
        "episode_approval_coverage": (
            None if disclosures == 0 else (disclosures - len(unapproved)) / disclosures
        ),
        "unapproved_episode_disclosures": len(unapproved),
        "unapproved_episodes": sorted(unapproved),
        "episode_disclosures": disclosures,
        "episodes_withheld": withheld,
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


def _retraction_report(measured: dict[str, Any]) -> int:
    """Print D-24's measurement and say whether it fails the gate."""
    print(json.dumps(measured, ensure_ascii=False))
    failures = 0
    for name in measured["retraction_probe_failures"] + measured["retracted_episodes_sendable"]:
        print(f"✗ a retracted episode was still sendable: {name}", file=sys.stderr)
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
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    failures = 0
    for key, label in (
        ("unapproved_episodes", "disclosed with no per-use approval"),
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
    retraction_exit = _retraction_report(write_retraction_evidence())
    return 1 if (failures or retraction_exit) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
