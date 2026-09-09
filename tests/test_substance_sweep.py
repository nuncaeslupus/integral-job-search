"""T114 — the substance sweep must read the documents, not the manifest.

T46's sweep skipped any episode listed in `disclosed`, and `disclosed` was built
from `manifest.json`. So an episode line deleted from `letter.md` after drafting
kept its manifest row, kept its exemption, and its substance went out inside a
headline with nothing backing it. `unapproved_episode_disclosures` measured 0 and
`episode_approval_coverage` measured 1.0 over a document demonstrably carrying an
unapproved story — a route past the check that looks clean, which is the whole
reason it is worth a gate of its own.

The gate is `disclosures_unbacked_by_a_generated_document == 0`, and every case
here is derived from what §6.2 and step 11 require rather than from what the code
does: an episode reaches an employer only with a per-use approval, and a payload
that describes a document is a promise about that document. A manifest row whose
line no document carries breaks the second promise on its own, whether or not
anything is smuggled through the first.

Direction matters throughout. Refusing a draft that is really clean costs a
regeneration; letting an unbacked story through costs the candidate's
credibility with an employer, so every ambiguous case below is resolved toward
refusing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral import approval
from integral.approval import (
    MINIMUM_DISCLOSURE_PROBES,
    MINIMUM_MANIFEST_DISCLOSURES_COMPARED,
    MINIMUM_PARAPHRASE_CHECKS,
    MINIMUM_PARAPHRASE_STATES,
    ApprovalError,
    PersonalDetails,
    _disclosure_report,
    _paraphrase_report,
    _refuse_unbacked_disclosures,
    _version_parts,
    disclosures_unbacked_by_a_document,
    measure_prepared,
    payload_digest,
    prepare,
    probe_paraphrase_undecidability,
    probe_unbacked_disclosures,
    read_payload,
    record_sent,
    write_disclosure_evidence,
    write_paraphrase_evidence,
)
from integral.cv_store import (
    CVMaster,
    Episode,
    Experience,
    Skill,
    SourcedText,
    write_master,
)
from integral.generate import read_manifest
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog
from integral.retraction import retract

ADVERT = (
    "We are hiring a data engineer in Girona. You will own a PostgreSQL estate "
    "and lead a migration off legacy systems."
)
OFFER = "girona-1"

WIN = "Cut the nightly billing run from six hours to forty minutes by rewriting reconciliation."
TWIN = "Cut the nightly billing run from six hours to forty minutes by rewriting the ledger job."
FAILURE = (
    "Shipped a schema change without a backfill and left invoicing wrong for two days "
    "before anyone noticed."
)

DETAILS = PersonalDetails(
    full_name="Ada Lovelace",
    email="ada@example.invalid",
    phone="+34 600 111 222",
    postal_address="3 Carrer Nou, 17001 Girona",
    date_of_birth="1815-12-10",
)


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


def _master(store: ProfileStore, headline: str | None = None) -> CVMaster:
    built = CVMaster(
        headline=None if headline is None else SourcedText(text=headline),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(
            Episode(kind="achievement", text=WIN),
            Episode(kind="failure", text=FAILURE),
        ),
    )
    write_master(store, built)
    return built


def _prepare(store: ProfileStore, master: CVMaster, *, approved: tuple[int, ...] = (0,)) -> int:
    payload = prepare(
        store,
        master,
        offer_id=OFFER,
        advert=ADVERT,
        recipient="hiring team, Girona",
        details=DETAILS,
        asks=("PostgreSQL",),
        approved_episodes=approved,
    )
    return payload.version


def _where(store: ProfileStore, version: int = 1) -> Path:
    return store.path(*_version_parts(OFFER, version))


def _drop_line(document: Path, text: str) -> None:
    """Delete one line from a finished document, leaving the manifest alone."""
    kept = [line for line in document.read_text(encoding="utf-8").splitlines() if line != text]
    document.write_text("\n".join(kept) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# the defect itself


def test_a_deleted_episode_line_whose_substance_survives_in_a_headline_is_flagged(
    store: ProfileStore,
) -> None:
    """§6.2: an episode reaches an employer only with a per-use approval.

    The headline carries the whole story, so deleting the episode line changes
    nothing about what the employer reads. With the approval gone there is
    nothing backing the substance, and the sweep is the only thing that looks.
    """
    master = _master(store, headline=WIN.rstrip("."))
    version = _prepare(store, master)
    where = _where(store, version)
    _drop_line(where / "letter.md", WIN)
    (where / "approvals.json").unlink()

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["unapproved_episode_disclosures"] >= 1
    assert any(
        "the substance of a story-bank episode" in finding and WIN in finding
        for finding in measured["unapproved_episodes"]
    )
    assert measured["episode_approval_coverage"] != 1.0


def test_a_manifest_entry_with_no_document_line_is_a_finding_not_a_skip(
    store: ProfileStore,
) -> None:
    """A payload that describes a document is a promise about that document.

    The approval is untouched here, so nothing is smuggled: what is wrong is
    that `manifest.json` and `payload.json` both report a disclosure the letter
    does not carry. A false summary is worse than no summary, so it is a
    finding rather than a silent skip.
    """
    master = _master(store)
    version = _prepare(store, master)
    _drop_line(_where(store, version) / "letter.md", WIN)

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["disclosures_unbacked_by_a_generated_document"] == 1
    assert measured["unbacked_disclosures"] == [
        f"{OFFER}/v{version} letter.md: {WIN} — the manifest records this episode as "
        "disclosed, and the document does not carry it"
    ]
    # The phantom row must stop being counted as a disclosure that happened.
    assert measured["episode_disclosures"] == 0


def test_a_version_whose_documents_agree_with_its_manifest_is_clean(
    store: ProfileStore,
) -> None:
    """The over-refusal control. Untouched output must measure nothing at all."""
    master = _master(store, headline="Data engineer — billing systems")
    version = _prepare(store, master)

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["disclosures_unbacked_by_a_generated_document"] == 0
    assert measured["unapproved_episode_disclosures"] == 0
    assert measured["episode_disclosures"] == 1


# ---------------------------------------------------------------------------
# the boundary refuses, rather than reporting and continuing


def test_record_sent_refuses_a_version_whose_manifest_outruns_its_documents(
    store: ProfileStore,
) -> None:
    """§6.2 stops one step short of sending, so the file on disk is the send.

    `payload.json` was written when the letter still carried the line. Editing
    the letter afterwards leaves the confirmed payload describing a document
    that no longer exists, and the digest cannot see it — only re-measuring can.
    """
    master = _master(store)
    version = _prepare(store, master)
    payload = read_payload(store, OFFER, version)
    _drop_line(_where(store, version) / "letter.md", WIN)

    with pytest.raises(ApprovalError, match="does not carry"):
        record_sent(store, master, OFFER, version, confirms=payload_digest(payload))


def test_an_edited_episode_line_is_both_unwritten_and_unbacked(store: ProfileStore) -> None:
    """Rewording is deletion plus insertion, and must read as both.

    The manifest's row no longer names any line, and the line that replaced it
    is a sentence no approval was given over.
    """
    master = _master(store)
    version = _prepare(store, master)
    letter = _where(store, version) / "letter.md"
    letter.write_text(
        letter.read_text(encoding="utf-8").replace(WIN, "Cut the nightly billing run, mostly."),
        encoding="utf-8",
    )

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["disclosures_unbacked_by_a_generated_document"] == 1
    assert measured["unapproved_episode_disclosures"] >= 1


def test_the_whole_letter_deleted_leaves_its_manifest_rows_unbacked(store: ProfileStore) -> None:
    """A document that is not there carries nothing, and the manifest still claims it."""
    master = _master(store)
    version = _prepare(store, master)
    (_where(store, version) / "letter.md").unlink()

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["disclosures_unbacked_by_a_generated_document"] == 1
    assert measured["episode_disclosures"] == 0


# ---------------------------------------------------------------------------
# the accounting — one line backs one claim, and an episode never borrows another's


def test_an_episode_claim_cannot_be_satisfied_by_another_claims_identical_line(
    store: ProfileStore,
) -> None:
    """The headline spelled exactly like the story is the sharpest case.

    `letter.md` then carries that sentence twice, once for the headline and once
    for the episode. Delete the episode line and a check that only asks "does the
    document contain this text" reads clean — the headline's own line answers
    for it — and the sweep skips the episode again. One line backs one claim, and
    a non-episode row reserves its line first.
    """
    master = _master(store, headline=WIN)
    version = _prepare(store, master)
    letter = _where(store, version) / "letter.md"
    body = letter.read_text(encoding="utf-8")
    assert body.count(WIN) == 2
    # Remove exactly one of the two identical lines.
    lines = body.splitlines()
    lines.remove(WIN)
    letter.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (_where(store, version) / "approvals.json").unlink()

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["disclosures_unbacked_by_a_generated_document"] == 1
    assert measured["unapproved_episode_disclosures"] >= 1


def test_a_manifest_row_duplicated_is_unbacked_once(store: ProfileStore) -> None:
    """Two rows over one line: the second is a disclosure the document does not carry."""
    master = _master(store)
    version = _prepare(store, master)
    path = _where(store, version) / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    episode = next(claim for claim in manifest["claims"] if claim["section"] == "episodes")
    manifest["claims"].append(dict(episode))
    path.write_text(json.dumps(manifest), encoding="utf-8")

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["disclosures_unbacked_by_a_generated_document"] == 1
    assert measured["episode_disclosures"] == 1


def test_a_manifest_row_naming_another_document_is_unbacked(store: ProfileStore) -> None:
    """A claim is scoped to the document it names, so a line in `cv.md` cannot answer for it."""
    master = _master(store)
    version = _prepare(store, master)
    where = _where(store, version)
    path = where / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for claim in manifest["claims"]:
        if claim["section"] == "episodes":
            claim["document"] = "cv.md"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["disclosures_unbacked_by_a_generated_document"] == 1


# ---------------------------------------------------------------------------
# where this crosses D-24


def test_a_retracted_episode_whose_line_was_deleted_is_still_found(store: ProfileStore) -> None:
    """D-24 fixed approval outliving its evidence; this is disclosure outliving its document.

    Both at once is the case neither gate saw: retracting withdraws the approval,
    deleting the line removes the thing the withdrawal would have been reported
    over, and the manifest row kept the substance exempt from the sweep.
    """
    master = _master(store, headline=WIN.rstrip("."))
    row = EvidenceLog(store).append(
        recorded_at="2026-01-01T09:00:00+00:00",
        step="history",
        kind="episode",
        text=WIN,
        source="conversation",
    )
    version = _prepare(store, master)
    retract(EvidenceLog(store), row.id, at="2026-01-02T09:00:00+00:00")
    _drop_line(_where(store, version) / "letter.md", WIN)

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["unapproved_episode_disclosures"] >= 1
    assert measured["disclosures_unbacked_by_a_generated_document"] == 1


# ---------------------------------------------------------------------------
# the reading over a whole profile, and the empty-scan rule


def test_the_reading_names_every_version_whose_manifest_outruns_its_documents(
    store: ProfileStore,
) -> None:
    master = _master(store)
    version = _prepare(store, master)
    _drop_line(_where(store, version) / "letter.md", WIN)

    reading = disclosures_unbacked_by_a_document(store, master)

    assert reading["disclosures_unbacked_by_a_generated_document"] == 1
    assert reading["manifest_disclosures_compared"] == 1
    assert reading["gate_status"] == "measured"


def test_the_reading_is_unmeasured_when_no_disclosure_was_compared(
    store: ProfileStore,
) -> None:
    """A zero over a sweep that read no documents is the clean zero this gate refuses."""
    master = _master(store)
    _prepare(store, master, approved=())

    reading = disclosures_unbacked_by_a_document(store, master)

    assert reading["manifest_disclosures_compared"] == 0
    assert reading["gate_status"] == "unmeasured"
    assert reading["disclosures_unbacked_by_a_generated_document"] == 0


def test_the_reading_is_unmeasured_when_nothing_was_ever_generated(
    store: ProfileStore,
) -> None:
    reading = disclosures_unbacked_by_a_document(store, _master(store))

    assert reading["gate_status"] == "unmeasured"
    assert reading["manifest_disclosures_compared"] == 0


# ---------------------------------------------------------------------------
# the probes — the half of the gate that is allowed to find something


def test_the_probes_catch_every_planted_defect(tmp_path: Path) -> None:
    measured = probe_unbacked_disclosures(tmp_path / "profiles")

    assert measured["disclosure_probe_failures"] == []
    assert measured["disclosure_probes"] >= MINIMUM_DISCLOSURE_PROBES
    assert measured["gate_status"] == "measured"
    # The probes plant divergences on purpose, so the aggregate is over the two
    # trees they leave untouched: a non-zero here is the fix over-refusing.
    assert measured["disclosures_unbacked_by_a_generated_document"] == 0
    assert measured["manifest_disclosures_compared"] >= 2


def test_the_recorded_evidence_clears_its_own_floors(tmp_path: Path) -> None:
    """The floor is over the whole record — the probes plus the corpus pass.

    A probe set alone compares a handful of disclosures, which is the empty-scan
    shape this gate exists to refuse; the corpus is what makes the zero mean
    something, so the floor is asserted where the two are added up.
    """
    measured = write_disclosure_evidence(tmp_path / "T114.json")

    assert measured["manifest_disclosures_compared"] >= MINIMUM_MANIFEST_DISCLOSURES_COMPARED
    assert measured["disclosures_unbacked_by_a_generated_document"] == 0
    assert measured["gate_status"] == "measured"
    assert json.loads((tmp_path / "T114.json").read_text(encoding="utf-8")) == measured


def test_the_refusal_helper_fires_only_on_a_divergence() -> None:
    """`prepare`'s call site is defensive, so the helper is pinned directly.

    `generate` writes the documents and the manifest in one call, so at drafting
    time the two agree by construction and only `record_sent` can reach the
    refusal through the public path. The guard stays because `prepare` re-reads
    what it just wrote rather than trusting it — the discipline the module
    docstring already states — and a guard nothing exercises is a guard nobody
    can tell is still wired up.
    """
    _refuse_unbacked_disclosures(
        {"disclosures_unbacked_by_a_generated_document": 0, "unbacked_disclosures": []},
        "so nothing happens",
    )

    with pytest.raises(ApprovalError, match="do not carry"):
        _refuse_unbacked_disclosures(
            {
                "disclosures_unbacked_by_a_generated_document": 1,
                "unbacked_disclosures": ["girona-1/v1 letter.md: a story — no line carries it"],
            },
            "so nothing here is sendable",
        )


def test_the_manifest_the_probes_read_is_the_one_on_disk(store: ProfileStore) -> None:
    """A guard on the fixtures themselves: the episode claim must exist to be deleted."""
    master = _master(store)
    version = _prepare(store, master)

    claims = read_manifest(store, OFFER, version).claims

    assert [claim.text for claim in claims if claim.section == "episodes"] == [WIN]


# ---------------------------------------------------------------------------
# the cases the second-reader round on #409 derived and nothing pinned


def test_an_episodes_substance_surviving_in_a_cv_bullet_is_flagged(store: ProfileStore) -> None:
    """A bullet reaches the employer exactly as a headline does.

    §6.2 asks whether an episode's substance reaches an employer with a per-use
    approval behind it, and says nothing about *which* line carries it. The
    headline is only the shape the defect was first found in; an experience
    description on `cv.md` is the same route, and the letter's episode line
    being deleted leaves the story going out of a second document with the
    approval gone. A miss here is fail-open — unbacked substance in front of an
    employer — so the case is pinned rather than left to the headline's.
    """
    master = CVMaster(
        headline=SourcedText(text="Data engineer — billing systems"),
        experience=(
            Experience(
                title="Data engineer",
                organisation="Vall S.A.",
                description=WIN.rstrip("."),
            ),
        ),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(Episode(kind="achievement", text=WIN), Episode(kind="failure", text=FAILURE)),
    )
    write_master(store, master)
    version = _prepare(store, master)
    where = _where(store, version)
    _drop_line(where / "letter.md", WIN)
    (where / "approvals.json").unlink()

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["disclosures_unbacked_by_a_generated_document"] == 1
    assert any(
        "the substance of a story-bank episode" in finding and WIN in finding
        for finding in measured["unapproved_episodes"]
    )
    assert measured["episode_approval_coverage"] != 1.0


def test_a_manifest_row_naming_a_document_that_was_never_generated_is_unbacked(
    store: ProfileStore,
) -> None:
    """A document that does not exist carries nothing, so the row is a finding.

    Distinct from the row re-pointed at `cv.md`: that document is on disk and
    could in principle answer, and the answer is refused because a claim is
    scoped to the document it names. Here there is nothing to ask at all. The
    fail-open reading is that a name matching no file is skipped as "not
    applicable", which is the manifest deciding its own exemption — the shape
    this whole task is about — so an absent document is unbacked.
    """
    master = _master(store)
    version = _prepare(store, master)
    path = _where(store, version) / "manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    for claim in raw["claims"]:
        if claim["section"] == "episodes":
            claim["document"] = "portfolio.md"
    path.write_text(json.dumps(raw), encoding="utf-8")

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["disclosures_unbacked_by_a_generated_document"] == 1
    assert measured["unbacked_disclosures"] == [
        f"{OFFER}/v{version} portfolio.md: {WIN} — the manifest records this episode as "
        "disclosed, and the document does not carry it"
    ]
    # And the line the letter really carries is now backed by nothing, so it is
    # reported too rather than passing on the strength of the redirected row.
    assert measured["unapproved_episode_disclosures"] == 1
    assert measured["episode_disclosures"] == 0


def test_two_overlapping_episodes_with_one_retracted_are_both_stopped(
    store: ProfileStore,
) -> None:
    """The twin is not a way around the retraction, and the deletion is not either.

    D-24: a retraction withdraws the approval over the retracted evidence *and*
    over anything carrying its substance, because otherwise re-approving a
    near-copy sends the withdrawn story. T114: deleting the retracted line does
    not delete the manifest row that says the letter discloses it. Together the
    fail-open reading is that the deletion removes what the withdrawal would
    have been reported over while the twin's line goes out carrying the same
    eight-word window — so both halves must fire on one measurement.
    """
    master = CVMaster(
        headline=SourcedText(text="Data engineer — billing systems"),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(Episode(kind="achievement", text=WIN), Episode(kind="achievement", text=TWIN)),
    )
    write_master(store, master)
    row = EvidenceLog(store).append(
        recorded_at="2026-01-01T09:00:00+00:00",
        step="history",
        kind="episode",
        text=WIN,
        source="conversation",
    )
    version = _prepare(store, master, approved=(0, 1))
    retract(EvidenceLog(store), row.id, at="2026-01-02T09:00:00+00:00")
    _drop_line(_where(store, version) / "letter.md", WIN)

    measured = measure_prepared(store, master, OFFER, version)

    # T114's half: the row over the deleted line.
    assert measured["disclosures_unbacked_by_a_generated_document"] == 1
    assert WIN in measured["unbacked_disclosures"][0]
    # D-24's half: the twin still on the page shares the withdrawn substance.
    assert any(
        "retracted the evidence this approval was given over" in finding and TWIN in finding
        for finding in measured["unapproved_episodes"]
    )
    assert measured["episode_approval_coverage"] != 1.0


def test_an_untouched_draft_of_two_overlapping_episodes_is_clean(store: ProfileStore) -> None:
    """The over-refusal control for the case above — the overlap alone is not a defect."""
    master = CVMaster(
        headline=SourcedText(text="Data engineer — billing systems"),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(Episode(kind="achievement", text=WIN), Episode(kind="achievement", text=TWIN)),
    )
    write_master(store, master)
    version = _prepare(store, master, approved=(0, 1))

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["disclosures_unbacked_by_a_generated_document"] == 0
    assert measured["unapproved_episode_disclosures"] == 0
    assert measured["episode_disclosures"] == 2


# ---------------------------------------------------------------------------
# the status is computed, not stated


def test_the_gate_status_is_derived_from_what_was_compared_at_both_sites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`unmeasured` means nothing if a site can simply say `measured` (T123's family).

    The floor stops a forged `measured` over `compared: 0` from *passing* the
    gate, but a floor is not an assertion that the status was computed at all:
    hardcoding `"measured"` at both aggregate sites left the module's own main
    and the whole suite green. `disclosures_unbacked_by_a_document` is pinned by
    the two readings above; these are the two sites nothing reached, each driven
    with a join that compared nothing and each of which must say so.
    """
    empty: dict[str, object] = {
        "disclosures_unbacked_by_a_generated_document": 0,
        "unbacked_disclosures": [],
        "manifest_disclosures_compared": 0,
        "gate_status": "unmeasured",
    }

    # The probe set's own aggregate. Its scan is stubbed out, so the probes read
    # nothing back and the run has compared nothing — and it must not report a
    # measurement it did not make. The vacuity check inside the probes fires too,
    # which is the second half of the same property.
    monkeypatch.setattr(
        approval, "disclosures_unbacked_by_a_document", lambda store, master: dict(empty)
    )
    probed = probe_unbacked_disclosures(tmp_path / "probes")
    assert probed["manifest_disclosures_compared"] == 0
    assert probed["gate_status"] == "unmeasured"
    assert probed["disclosure_probe_failures"] != []

    # The recorded evidence's aggregate. Both halves compared nothing, so the
    # written record has to say `unmeasured` — and `_disclosure_report` fails on
    # it rather than on the floor alone.
    monkeypatch.setattr(
        approval,
        "probe_unbacked_disclosures",
        lambda root: {**empty, "disclosure_probes": 0, "disclosure_probe_failures": []},
    )
    written = write_disclosure_evidence(tmp_path / "T114.json", corpus=dict(empty))

    assert written["gate_status"] == "unmeasured"
    recorded = json.loads((tmp_path / "T114.json").read_text(encoding="utf-8"))
    assert recorded["gate_status"] == "unmeasured"
    assert _disclosure_report(written) == 1


# ---------------------------------------------------------------------------
# T156 — a paraphrase must be reported as undecidable, never as withheld
#
# Rewritten once already. The first version added a normalised-word-overlap
# proxy for "is this a paraphrase" and derived its over-refusal controls from
# the proxy's own threshold constants — a check argued from the code, not from
# the spec, which is the circularity CLAUDE.md's fixtures section exists to
# break. A second reader measured that proxy end to end against 8 constructed
# genuine paraphrases and 30 constructed innocent same-domain documents and
# found it anti-correlated with the property it was meant to proxy: 0 of 8
# caught, 21 of 30 wrongly flagged.
#
# The rule below needs no threshold. `approval._carries`'s own docstring states
# the limit plainly: eight-word shingles beat punctuation, spacing, case,
# truncation and extension, but "it does not beat a genuine paraphrase, and
# nothing cheap does." A check that can only ever confirm *presence* can never
# confirm *absence*, so an episode that is neither manifest-disclosed nor
# shingle-matched is a case this sweep has **no evidence about**, full stop —
# not a case in some vocabulary band and not a case outside it. Every case
# below is derived from that limit and from §6.2 (an episode reaches an
# employer only with a per-use approval, so a false "withheld" is exactly the
# confidence this module must not sell) — never from what `measure_prepared`
# happens to return.

# A reordering of WIN that keeps most of its long, specific words — the
# eight-word window is gone (verified in the first test below), but a human
# reading both sentences would recognise the same achievement.
PARAPHRASE = (
    "Rewriting the reconciliation step cut billing run time from six hours "
    "down to forty minutes each night."
)

# The second reader's C3 case by name: a paraphrase thorough enough to share
# almost none of the win episode's surface vocabulary (synonym substitution
# rather than reordering). This is the exact shape a word-overlap proxy cannot
# reach, because a paraphrase substitutes content words *by definition* — and
# it is no longer excluded from this gate's numerator, because the
# unconditional rule needs no vocabulary to catch it.
THOROUGH_PARAPHRASE = (
    "By reworking how the ledgers were reconciled, the overnight invoicing "
    "job that used to take six hours now finishes in well under an hour."
)

# Same-domain, retells nothing: shares "nightly", "billing", "reconciliation"
# with WIN but describes an ongoing role rather than the six-hours-to-forty-
# minutes event. This is the shape the second reader's report measured the
# retired proxy wrongly flagging (`billing-ownership`, `support-escalation`);
# under the unconditional rule there is no vocabulary check left to trip.
INNOCENT_WIN_ADJACENT = (
    "Owns the nightly billing reconciliation runbook and leads the on-call "
    "rotation for finance systems."
)


def test_a_paraphrase_shares_no_eight_word_window_with_the_episode_it_retells() -> None:
    """The fixtures' own precondition, pinned rather than assumed.

    If this ever failed, the tests below would be exercising the shingle
    matcher `_carries` already covers, not the gap this task closes.
    """
    from integral.approval import _carries

    assert not _carries(PARAPHRASE, WIN)
    assert not _carries(THOROUGH_PARAPHRASE, WIN)


def test_a_paraphrased_headline_is_undecidable_not_withheld(store: ProfileStore) -> None:
    """§6.2: a false "withheld" is a confidence this sweep did not earn.

    The episode is never approved and never named in any manifest row, so
    before this task `episodes_withheld` counted it. `_carries` can confirm
    presence and never absence, so a shingle miss proves nothing — the fix is
    not a cleverer detector, it is refusing to round "cannot confirm absent"
    up to "confirmed absent".
    """
    master = _master(store, headline=PARAPHRASE)
    version = _prepare(store, master, approved=())

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["episodes_undecidable"] == 2
    assert any(WIN in item for item in measured["undecidable_episodes"])
    assert any(FAILURE in item for item in measured["undecidable_episodes"])
    # Not a confirmed disclosure either — the sweep does not know that, and
    # §6.2's boundary must not block a draft over what it cannot confirm.
    assert measured["unapproved_episode_disclosures"] == 0


def test_a_paraphrased_cv_bullet_is_undecidable_not_withheld(store: ProfileStore) -> None:
    """The same gap, in the document T114 added a case for: a CV bullet.

    §6.2 asks whether an episode's substance reaches an employer, never which
    line carries it — a bullet reaches the employer exactly as a headline
    does, so the fix cannot be blind to one of the two.
    """
    master = CVMaster(
        headline=SourcedText(text="Data platform engineer"),
        experience=(
            Experience(title="Data engineer", organisation="Vall S.A.", description=PARAPHRASE),
        ),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(Episode(kind="achievement", text=WIN), Episode(kind="failure", text=FAILURE)),
    )
    write_master(store, master)
    version = _prepare(store, master, approved=())

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["episodes_undecidable"] == 2
    assert any(WIN in item for item in measured["undecidable_episodes"])


def test_a_thorough_paraphrase_is_caught_by_the_unconditional_rule(store: ProfileStore) -> None:
    """The case a threshold-based proxy could not reach — this rule needs no threshold.

    Measured by the second reader on #435 (C3): a rewording sharing almost no
    surface vocabulary with the episode it retells defeated the word-overlap
    proxy exactly as it defeats `_carries`. It does not defeat "was there a
    shingle match, yes or no" — nothing about this rule asks how much
    vocabulary is shared.
    """
    master = _master(store, headline=THOROUGH_PARAPHRASE)
    version = _prepare(store, master, approved=())

    measured = measure_prepared(store, master, OFFER, version)

    assert any(WIN in item for item in measured["undecidable_episodes"])


def test_an_innocent_same_domain_document_is_not_a_confirmed_disclosure(
    store: ProfileStore,
) -> None:
    """The over-refusal shape the retired proxy actually failed on.

    A document that shares an episode's vocabulary while retelling none of its
    event must never be treated as a confirmed disclosure — that would block a
    clean draft, the direction CLAUDE.md's fixtures section weights hardest
    against. It may still land in `episodes_undecidable` (this sweep has no
    more evidence that it is absent than that it is present), and that is not
    an over-refusal: nothing is blocked, nothing is asserted falsely.
    """
    master = _master(store, headline=INNOCENT_WIN_ADJACENT)
    payload = prepare(
        store,
        master,
        offer_id=OFFER,
        advert=ADVERT,
        recipient="hiring team, Girona",
        details=DETAILS,
        asks=("PostgreSQL",),
        approved_episodes=(),
    )

    measured = measure_prepared(store, master, OFFER, payload.version)

    assert measured["unapproved_episode_disclosures"] == 0
    assert payload.version == 1


def test_a_genuinely_unrelated_episode_is_undecidable_like_any_other(store: ProfileStore) -> None:
    """No vocabulary check means no special case for "shares no vocabulary" either.

    An episode with no textual relationship at all to the document is treated
    identically to a genuine paraphrase: undecidable, because this sweep has
    exactly the same (lack of) evidence about both. Sharing more or less
    vocabulary was never the property in question.
    """
    master = _master(store, headline="Data engineer — billing systems")
    version = _prepare(store, master, approved=(0,))

    measured = measure_prepared(store, master, OFFER, version)

    assert any(FAILURE in item for item in measured["undecidable_episodes"])
    assert measured["unapproved_episode_disclosures"] == 0


def test_exact_substance_is_a_confirmed_finding_not_a_downgrade(store: ProfileStore) -> None:
    """The `elif` that reaches "undecidable" is only ever tried after `_carries` fails.

    An exact match is the case T46 already catches with full confidence, and
    this task must not weaken that into a hedge.
    """
    master = _master(store, headline=WIN.rstrip("."))
    write_master(store, master)

    with pytest.raises(ApprovalError):
        _prepare(store, master, approved=())

    measured = measure_prepared(store, master, OFFER, 1)

    assert measured["unapproved_episode_disclosures"] == 1
    assert not any(WIN in item for item in measured["undecidable_episodes"])


def test_a_literal_planted_line_is_confirmed_not_undecidable(store: ProfileStore) -> None:
    """Present verbatim in the raw document is positive evidence, not "no evidence".

    The line is unbacked, so it is already named by the unbackable-line
    finding; it must not *also* read as a case this sweep cannot adjudicate,
    which would understate the confidence a verbatim match actually supports.
    """
    master = _master(store)
    version = _prepare(store, master, approved=(0,))
    letter = _where(store, version) / "letter.md"
    letter.write_text(letter.read_text(encoding="utf-8") + FAILURE + "\n", encoding="utf-8")

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["unapproved_episode_disclosures"] == 1
    assert not any(FAILURE in item for item in measured["undecidable_episodes"])


def test_an_approved_disclosed_episode_is_never_flagged_undecidable(
    store: ProfileStore,
) -> None:
    """An episode backed by its own approval shares heavy vocabulary with its
    own rendered line by construction, and that is not ambiguity.

    Both episodes are approved and disclosed here so nothing is left over for
    the third state to (correctly) report: FAILURE approved on its own would
    otherwise land in `episodes_undecidable` too, which is not this test's
    subject and would make a passing assertion here accidental rather than
    about the property named in the docstring.
    """
    master = _master(store)
    version = _prepare(store, master, approved=(0, 1))

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["episodes_undecidable"] == 0
    assert measured["episode_disclosures"] == 2


def test_payload_names_the_undecidable_episode(store: ProfileStore) -> None:
    """The module docstring's T156 section: payload.json says what it knows.

    An undecidable case is not a finding — nothing is written over one — but
    it is not a clean bill of health either, so `prepare` must not stay silent
    about it.
    """
    master = _master(store, headline=PARAPHRASE)
    payload = prepare(
        store,
        master,
        offer_id=OFFER,
        advert=ADVERT,
        recipient="hiring team, Girona",
        details=DETAILS,
        asks=("PostgreSQL",),
        approved_episodes=(),
    )

    assert any(WIN in item for item in payload.undecidable_episodes)
    assert (
        read_payload(store, OFFER, payload.version).undecidable_episodes
        == payload.undecidable_episodes
    )


def test_the_boundary_refusal_names_an_undecidable_episode_too(store: ProfileStore) -> None:
    """F4: the docstring's claim that the boundary is "told which one they got" — pinned.

    A refusal fired for one, confirmed reason (a verbatim planted line) must
    not go silent about a second, genuinely undecidable episode sitting in the
    same draft. Not itself a refusal — §6.2 only requires stopping over a
    *known* unapproved disclosure — so it rides along on a refusal that is
    already happening for another reason.
    """
    smuggled = Episode(
        kind="achievement", text="Renegotiated the hosting contract and cut spend by a third."
    )
    master = CVMaster(
        headline=SourcedText(text=PARAPHRASE.replace("Rewriting", "Reworking")),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(
            Episode(kind="achievement", text=WIN),
            Episode(kind="failure", text=FAILURE),
            smuggled,
        ),
    )
    write_master(store, master)
    payload = prepare(
        store,
        master,
        offer_id=OFFER,
        advert=ADVERT,
        recipient="hiring team, Girona",
        details=DETAILS,
        asks=("PostgreSQL",),
        approved_episodes=(0,),
    )
    letter = _where(store, payload.version) / "letter.md"
    letter.write_text(letter.read_text(encoding="utf-8") + smuggled.text + "\n", encoding="utf-8")

    with pytest.raises(ApprovalError) as excinfo:
        record_sent(store, master, OFFER, payload.version, confirms=payload_digest(payload))

    message = str(excinfo.value)
    assert smuggled.text in message
    assert "undecid" in message
    assert FAILURE in message


# ---------------------------------------------------------------------------
# the probes and the recorded evidence


def test_the_paraphrase_probes_catch_every_constructed_case(tmp_path: Path) -> None:
    measured = probe_paraphrase_undecidability(tmp_path / "profiles")

    assert measured["paraphrase_probe_failures"] == []
    assert measured["paraphrase_states_evaluated"] >= MINIMUM_PARAPHRASE_STATES
    assert measured["gate_status"] == "measured"
    assert measured["paraphrased_substance_reported_as_withheld"] == 0


def test_the_recorded_paraphrase_evidence_clears_its_own_floor(tmp_path: Path) -> None:
    measured = write_paraphrase_evidence(tmp_path / "T156.json")

    assert measured["paraphrase_states_evaluated"] >= MINIMUM_PARAPHRASE_STATES
    assert measured["paraphrase_checks_evaluated"] >= MINIMUM_PARAPHRASE_CHECKS
    assert measured["paraphrased_substance_reported_as_withheld"] == 0
    assert measured["gate_status"] == "measured"
    assert json.loads((tmp_path / "T156.json").read_text(encoding="utf-8")) == measured


def test_deleting_an_over_refusal_state_breaches_the_floor(tmp_path: Path) -> None:
    """F3, pinned directly: the floor must guard *states*, not merely `check()` calls.

    Deleting a state's `fresh()` call and every `check()` beneath it must lower
    `paraphrase_states_evaluated` below `MINIMUM_PARAPHRASE_STATES` — so this
    drives the real function and asserts the floor would in fact catch a
    shrunken states list, rather than trusting the constant's comment. Both
    floors are pinned to the actual count, so either kind of shrinkage — fewer
    states, or the same states with fewer assertions each — is caught by one
    of the two rather than by neither.
    """
    measured = probe_paraphrase_undecidability(tmp_path / "profiles")
    # The actual probe already clears both floors with no margin to spare a
    # deletion: both constants are the exact counts, so simulating one fewer
    # of either is simply one less than what was measured.
    assert measured["paraphrase_states_evaluated"] - 1 < MINIMUM_PARAPHRASE_STATES
    assert measured["paraphrase_checks_evaluated"] - 1 < MINIMUM_PARAPHRASE_CHECKS
    assert measured["paraphrase_states_evaluated"] == MINIMUM_PARAPHRASE_STATES
    assert measured["paraphrase_checks_evaluated"] == MINIMUM_PARAPHRASE_CHECKS


def test_the_paraphrase_report_fails_on_a_nonzero_metric(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_paraphrase_report` must fail the gate itself, not just print the number.

    T123's family: a report function that always returns 0 leaves a red metric
    printed but not acted on, which reads as a passing gate from the exit code
    `open_task_pr.sh` and CI actually check.
    """
    passing = {
        "paraphrase_states_evaluated": MINIMUM_PARAPHRASE_STATES,
        "paraphrase_checks_evaluated": MINIMUM_PARAPHRASE_CHECKS,
        "paraphrased_substance_reported_as_withheld": 0,
        "paraphrase_probe_failures": [],
        "gate_status": "measured",
    }
    assert _paraphrase_report(dict(passing)) == 0
    assert _paraphrase_report({**passing, "paraphrased_substance_reported_as_withheld": 1}) == 1
    assert (
        _paraphrase_report(
            {**passing, "paraphrase_states_evaluated": 0, "gate_status": "unmeasured"}
        )
        == 1
    )
    # The checks floor, on its own, guards against padding the states count
    # with an empty `fresh()` call — the "floor counting the wrong population"
    # shape F3 named — by catching a states count that clears its own floor
    # while the checks beneath it thin out.
    assert _paraphrase_report({**passing, "paraphrase_checks_evaluated": 0}) == 1

    monkeypatch.setattr(
        approval,
        "probe_paraphrase_undecidability",
        lambda root: {
            "paraphrase_states_evaluated": 0,
            "paraphrase_checks_evaluated": 0,
            "paraphrased_substance_reported_as_withheld": 0,
            "paraphrase_probe_failures": [],
            "gate_status": "unmeasured",
        },
    )
    written = write_paraphrase_evidence(tmp_path / "T156.json")
    assert written["gate_status"] == "unmeasured"
    assert _paraphrase_report(written) == 1
