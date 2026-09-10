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

import ast
import inspect
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
    _normalised_equal,
    _paraphrase_report,
    _refuse_unbacked_disclosures,
    _undecidable_suffix,
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
from integral.generate import Manifest, read_manifest
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


def test_undecidable_suffix_appends_only_when_something_is_undecidable() -> None:
    """`_undecidable_suffix` on its own: empty when there is nothing to add,
    otherwise the episode text and the word "undecid" that every raise site's
    message is checked for below.
    """
    assert _undecidable_suffix({}) == ""
    assert _undecidable_suffix({"episodes_undecidable": 0, "undecidable_episodes": []}) == ""

    measured = {
        "episodes_undecidable": 1,
        "undecidable_episodes": ["girona-1/v1: a mystery episode — no evidence either way"],
    }
    suffix = _undecidable_suffix(measured)
    assert "undecid" in suffix
    assert "mystery episode" in suffix


def test_undecidable_suffix_does_not_key_error_on_measures_aggregate_shape() -> None:
    """F5 (#435 round 4, latent fail-closed): the guard and the read must agree.

    `measure()`'s aggregate dict carries a nonzero `episodes_undecidable`
    total (a running sum across every advert) but no `undecidable_episodes`
    list at all — that key only ever exists on `measure_prepared`'s per-call
    output. Guarding on the count and then indexing the list would `KeyError`
    the moment anything ever hands this function that aggregate; guarding on
    the list itself cannot desync from what it then reads.
    """
    aggregate_shaped = {"episodes_undecidable": 208, "unapproved_episode_disclosures": 0}
    assert "undecidable_episodes" not in aggregate_shaped
    assert _undecidable_suffix(aggregate_shaped) == ""


def test_the_refusal_helper_names_an_undecidable_episode_too() -> None:
    """N1 (#435 round 3): `_refuse_unbacked_disclosures`'s own raise, pinned directly.

    Round 2 pinned `_undecidable_suffix` only at `record_sent`'s raise
    (`test_the_boundary_refusal_names_an_undecidable_episode_too` below).
    Dropping the suffix from *this* function's raise instead left every test
    in the suite green — the reader had to call this helper directly, with an
    undecidable episode in the measured dict, to see it at all. Driven here
    rather than through `prepare`/`record_sent` so the assertion is about this
    raise's own construction, not about whichever caller happens to route
    through it.
    """
    measured = {
        "disclosures_unbacked_by_a_generated_document": 1,
        "unbacked_disclosures": ["girona-1/v1 letter.md: a story — no line carries it"],
        "episodes_undecidable": 1,
        "undecidable_episodes": ["girona-1/v1: a mystery episode — no evidence either way"],
    }

    with pytest.raises(ApprovalError) as excinfo:
        _refuse_unbacked_disclosures(measured, "so nothing here is sendable")

    message = str(excinfo.value)
    assert "undecid" in message
    assert "mystery episode" in message


def test_prepares_own_refusal_names_an_undecidable_episode_too(store: ProfileStore) -> None:
    """N1 (#435 round 3): `prepare`'s own raise is a distinct site from
    `record_sent`'s, pinned directly rather than only through the helper above.

    A headline carrying WIN's text verbatim fires `prepare`'s refusal without
    ever reaching `record_sent` — the module docstring's own point that
    `record_sent` is not the only public path to this raise. FAILURE is
    genuinely unrelated to anything on the page, so it lands in
    `undecidable_episodes` in the same measurement, and the message `prepare`
    raises must say so.
    """
    master = _master(store, headline=WIN.rstrip("."))

    with pytest.raises(ApprovalError) as excinfo:
        _prepare(store, master, approved=())

    message = str(excinfo.value)
    assert "undecid" in message
    assert FAILURE in message


def test_every_raise_site_over_measured_names_the_undecidable_episodes() -> None:
    """N1 (#435 round 3): a closed rule over the raise sites, not three more tests.

    Three sites read `measured` today and must each append
    `_undecidable_suffix(measured)`: `prepare`'s raise, `record_sent`'s raise,
    and `_refuse_unbacked_disclosures`'s raise (called from both). The three
    tests above drive each of them directly and would each go red on its own
    if the suffix were dropped there — but three hand-written tests are an
    enumeration with no last element, and a fourth raise site added tomorrow
    would simply not be one of them.

    So this reads `approval.py`'s own source instead of naming functions: every
    `raise ApprovalError(...)` whose constructed message reads the name
    `measured` must also call `_undecidable_suffix` somewhere in that same
    raise statement. A raise that never touches `measured` at all (a bad
    confirmation digest, an already-sent record, a version never written) is
    correctly untouched by this rule — it has no undecidable episodes to lose.
    """
    tree = ast.parse(inspect.getsource(approval))

    def _reads_name(node: ast.AST, name: str) -> bool:
        return any(isinstance(child, ast.Name) and child.id == name for child in ast.walk(node))

    def _calls(node: ast.AST, func_name: str) -> bool:
        return any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == func_name
            for child in ast.walk(node)
        )

    sites: list[tuple[int, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        call = node.exc
        is_approval_error = (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "ApprovalError"
        )
        if is_approval_error and _reads_name(call, "measured"):
            sites.append((node.lineno, _calls(call, "_undecidable_suffix")))

    # A rule with nothing to check is not a rule — see CLAUDE.md's fixtures
    # section on a check whose population never reaches the branch it is
    # about. Three sites are known to exist today (`prepare`, `record_sent`,
    # `_refuse_unbacked_disclosures`); this floor catches the rule going
    # vacuous if every one of them were ever refactored away from `measured`.
    assert len(sites) >= 3, (
        f"expected at least 3 `raise ApprovalError(...)` sites reading `measured` in "
        f"approval.py, found {len(sites)} — this rule cannot check what does not exist"
    )
    unpinned = [lineno for lineno, pinned in sites if not pinned]
    assert unpinned == [], (
        "raise ApprovalError(...) at approval.py line(s) "
        f"{unpinned} builds its message from `measured` without also calling "
        "_undecidable_suffix(measured)"
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


def test_two_unrelated_episodes_sharing_a_window_are_not_conflated(store: ProfileStore) -> None:
    """N2 (#435 round 3): a shingle match against an *approved* line is not
    evidence for a *different*, unapproved episode.

    WIN is approved and rendered; TWIN is a second, distinct episode that is
    never approved and never rendered, but shares WIN's own eight-word run
    almost word for word (see the two constants' definitions above). Before
    this fix the `elif` in `measure_prepared` checked the raw text of every
    *written* line, approved ones included — so TWIN's shingle matched WIN's
    own approved sentence and TWIN was silently cleared from every channel:
    not a finding, and not `episodes_undecidable` either. That is a worse
    fail-open than an honest "undecided" would have been — TWIN's own,
    distinguishing substance ("the ledger job") is nowhere on the page, and
    nothing said so. The comment above the `elif` in `approval.py` was wrong
    about exactly this case; this fixture is what makes the corrected
    behaviour a checked property rather than a comment nothing runs.
    """
    master = CVMaster(
        headline=SourcedText(text="Data engineer — billing systems"),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(Episode(kind="achievement", text=WIN), Episode(kind="achievement", text=TWIN)),
    )
    write_master(store, master)
    version = _prepare(store, master, approved=(0,))

    measured = measure_prepared(store, master, OFFER, version)

    assert measured["unapproved_episode_disclosures"] == 0
    assert any(TWIN in item for item in measured["undecidable_episodes"])


def test_a_seam_between_two_unbacked_lines_does_not_manufacture_a_match(
    store: ProfileStore,
) -> None:
    """F1 (#435 round 4, fail-open blocker): `unbacked` lines are checked one
    at a time, never joined, because two lines that are never adjacent on any
    real page a candidate could look at can still land next to each other in
    a `"\\n".join(unbacked)` string.

    `seam_head` is planted into `cv.md`, `seam_tail` into `letter.md` —
    different *documents*, so there is no real page on which these two lines
    are adjacent, or even in the same file. Round 3's fix still joined every
    `unbacked` line with `"\\n"` before searching (`_words` treats a newline as
    ordinary whitespace, so the join is invisible to the shingle test), and
    `e3_text`'s eight words are split exactly 4/4 across that seam: no single
    planted line carries more than four of them, but the tail of `seam_head`
    directly against the head of `seam_tail` carries all eight contiguously.
    Under the join that read as "confirmed present" and cleared `e3_text` from
    every channel — not a finding (its own text was never written anywhere),
    and not `episodes_undecidable` either. Round 4 checks each `unbacked` line
    on its own, so this can no longer happen: closing the seam, not merely
    bounding it.
    """
    seam_head = "Zulu yankee xray whiskey alpha bravo charlie delta"
    seam_tail = "echo foxtrot golf hotel india juliet kilo lima"
    e3_text = "Alpha bravo charlie delta echo foxtrot golf hotel"
    master = CVMaster(
        headline=SourcedText(text="Data engineer — billing systems"),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(Episode(kind="achievement", text=WIN), Episode(kind="failure", text=e3_text)),
    )
    write_master(store, master)
    version = _prepare(store, master, approved=(0,))
    where = _where(store, version)
    (where / "cv.md").write_text(
        (where / "cv.md").read_text(encoding="utf-8") + seam_head + "\n", encoding="utf-8"
    )
    (where / "letter.md").write_text(
        (where / "letter.md").read_text(encoding="utf-8") + seam_tail + "\n", encoding="utf-8"
    )

    measured = measure_prepared(store, master, OFFER, version)

    # Each planted line is its own, correctly-reported unbacked finding —
    # the seam must not swallow either of those or manufacture a third.
    assert measured["unapproved_episode_disclosures"] == 2
    assert any(seam_head in item for item in measured["unapproved_episodes"])
    assert any(seam_tail in item for item in measured["unapproved_episodes"])
    # `e3_text` itself was never written anywhere, whole, on any page — it
    # must read as undecided, never as a confirmed disclosure conjured by the
    # join.
    assert not any(e3_text in item for item in measured["unapproved_episodes"])
    assert any(e3_text in item for item in measured["undecidable_episodes"])


def test_a_duplicated_approved_line_does_not_conflate_a_twin(store: ProfileStore) -> None:
    """R5-1 (#435 round 5, the blocker), route (A): `unbacked` is populated by
    a Counter test (`backed[key] == 0`), never by a text test, so an
    *approved* line duplicated on the page lands there too — and round four's
    `elif` read that duplicate's text as "confirmed present" for TWIN, a
    different, unapproved episode sharing WIN's eight-word window, clearing
    TWIN from every channel exactly as the round-three defect did.
    """
    master = CVMaster(
        headline=SourcedText(text="Data engineer — billing systems"),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(Episode(kind="achievement", text=WIN), Episode(kind="achievement", text=TWIN)),
    )
    write_master(store, master)
    version = _prepare(store, master, approved=(0,))
    where = _where(store, version)
    (where / "letter.md").write_text(
        (where / "letter.md").read_text(encoding="utf-8") + WIN + "\n", encoding="utf-8"
    )

    measured = measure_prepared(store, master, OFFER, version)

    # The duplicate is unbacked in its own right and earns its own finding.
    assert measured["unapproved_episode_disclosures"] == 1
    assert any(WIN in item for item in measured["unapproved_episodes"])
    # TWIN must not be silently cleared by the duplicate's approved wording.
    assert not any(TWIN in item for item in measured["unapproved_episodes"])
    assert any(TWIN in item for item in measured["undecidable_episodes"])


def test_a_deleted_manifest_row_for_an_approved_line_does_not_conflate_a_twin(
    store: ProfileStore,
) -> None:
    """R5-1, route (B): the manifest row for WIN removed after drafting —
    T114's class of post-draft edit, applied to this seam rather than to the
    disclosure sweep — while WIN's approval and its rendered line both stay on
    disk. With the claim gone, `backed` is never incremented for WIN's key, so
    WIN's own untouched line lands in `unbacked` by the same Counter-vs-text
    gap as the duplicate above, and must not clear TWIN from both channels
    either.
    """
    master = CVMaster(
        headline=SourcedText(text="Data engineer — billing systems"),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(Episode(kind="achievement", text=WIN), Episode(kind="achievement", text=TWIN)),
    )
    write_master(store, master)
    version = _prepare(store, master, approved=(0,))
    where = _where(store, version)
    manifest_path = where / "manifest.json"
    manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    manifest = manifest.model_copy(
        update={"claims": tuple(claim for claim in manifest.claims if claim.text != WIN)}
    )
    manifest_path.write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")

    measured = measure_prepared(store, master, OFFER, version)

    # WIN's own line, now unbacked, earns its own finding.
    assert measured["unapproved_episode_disclosures"] == 1
    assert any(WIN in item for item in measured["unapproved_episodes"])
    # TWIN must not be silently cleared by WIN's now-unbacked approved wording.
    assert not any(TWIN in item for item in measured["unapproved_episodes"])
    assert any(TWIN in item for item in measured["undecidable_episodes"])


@pytest.mark.parametrize(
    ("edit", "near_copy"),
    [
        ("trailing period dropped", WIN.rstrip(".")),
        ("uppercased", WIN.upper()),
        ("comma inserted", WIN.replace("forty minutes by", "forty minutes, by")),
        ("clause appended", WIN.rstrip(".") + ", ahead of schedule."),
        ("double space", WIN.replace("nightly billing", "nightly  billing")),
    ],
)
def test_a_near_copy_of_an_approved_line_does_not_conflate_a_twin(
    store: ProfileStore, edit: str, near_copy: str
) -> None:
    """R6-1 (#435 round 6, the blocker): round five's fix is `if line not in
    approved`, an **exact-text** test standing in front of `_carries`, a
    **normalised-shingle** predicate. Every edit here is one `_carries`'s own
    docstring says it beats — punctuation, spacing, case, truncation and
    extension — so the near-copy is never byte-equal to WIN's approved text,
    gets searched again by the old filter, and (before round six) cleared
    TWIN from every channel exactly as an exact duplicate did before round
    five.
    """
    master = CVMaster(
        headline=SourcedText(text="Data engineer — billing systems"),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(Episode(kind="achievement", text=WIN), Episode(kind="achievement", text=TWIN)),
    )
    write_master(store, master)
    version = _prepare(store, master, approved=(0,))
    where = _where(store, version)
    (where / "letter.md").write_text(
        (where / "letter.md").read_text(encoding="utf-8") + near_copy + "\n", encoding="utf-8"
    )

    measured = measure_prepared(store, master, OFFER, version)

    # The near-copy is unbacked in its own right and earns its own finding.
    assert measured["unapproved_episode_disclosures"] == 1, edit
    # TWIN must not be silently cleared by the near-copy's wording.
    assert not any(TWIN in item for item in measured["unapproved_episodes"]), edit
    assert any(TWIN in item for item in measured["undecidable_episodes"]), edit


def test_a_retraction_with_no_document_edit_does_not_conflate_a_twin(
    store: ProfileStore,
) -> None:
    """R6-2 (#435 round 6, the blocker): `measure_prepared` computes
    `approved -= withdrawn` for a D-24 retraction, so WIN's text leaves
    `approved` the instant its evidence is retracted — with **no document
    edit at all**. Round five's fix keys off `approved`, so this route needs
    no near-copy trickery: the moment WIN's text is no longer `in approved`,
    the old filter searches WIN's own still-rendered line again and clears
    TWIN, a different, unapproved episode, from every channel.
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
    version = _prepare(store, master, approved=(0,))
    retract(EvidenceLog(store), row.id, at="2026-01-02T09:00:00+00:00")

    measured = measure_prepared(store, master, OFFER, version)

    # WIN's own line, now unbacked by the retraction, earns its own finding.
    assert measured["unapproved_episode_disclosures"] == 1
    assert any(WIN in item for item in measured["unapproved_episodes"])
    # TWIN must not be silently cleared by WIN's now-unbacked, retracted line.
    assert not any(TWIN in item for item in measured["unapproved_episodes"])
    assert any(TWIN in item for item in measured["undecidable_episodes"])


def test_normalised_equal_is_pinned_in_both_directions() -> None:
    """R8 (#435 round 8, F-1 and F-2). `_normalised_equal` is the primitive
    the sweep's confirm branch trusts absolutely — a match rules out every
    rival with no further check (see the module docstring's R7/R8 sections)
    — so it is pinned directly here, in both directions F-2 named:

    * a pair that must compare **equal** and would not without folding
      (case and whitespace only) — the reason `unicodedata.normalize` and
      `.casefold()` are called at all, refuting a bare `line == episode`
      mutant;
    * seven pairs, the round-7 second-reader's own constructed cases (#435
      F-1's report), that must compare **unequal** and would not under the
      old `_words`-based rule (`\\W`-stripping deletes exactly the character
      that distinguishes each pair) — refuting both that mutant and an
      order-insensitive bag-of-words variant of it (F-2's second surviving
      mutant), since every pair below differs in more than word order.
    """
    # Needs normalisation: only case and a doubled internal space differ.
    assert _normalised_equal(
        "CUT THE NIGHTLY  BILLING run from six hours to forty minutes.",
        "cut the nightly billing run from six hours to forty minutes.",
    )

    # Must never compare equal — `Episode.kind` names `"number"` as a
    # first-class kind, so a numeric claim is squarely in scope, not an edge
    # case this primitive may decline.
    distinct_pairs = (
        ("Margin moved +12% after the rewrite", "Margin moved -12% after the rewrite"),
        ("won 3:1 on renewals", "won 3 1 on renewals"),
        ("cut costs 40%", "cut costs 40"),
        ("grew 10-20 percent", "grew 10 20 percent"),
        ("We shipped it", "We shipped it?"),
        (
            "The manager said the client was wrong",
            "The manager, said the client, was wrong",
        ),
        ("Cut the run 6h -> 40m", "Cut the run 6h 40m"),
    )
    for a, b in distinct_pairs:
        assert not _normalised_equal(a, b), (a, b)
        assert not _normalised_equal(b, a), (b, a)  # symmetry — neither direction folds


def test_a_sign_flip_does_not_conflate_a_different_episode(store: ProfileStore) -> None:
    """F-1 (#435 round 7 second-reader report), fixed at R8 (#435 round 8,
    the blocker). `_words` deletes `+`/`-`, so an approved achievement's own
    duplicated line and an unapproved failure episode about the *opposite*
    reading of the same metric reduced to the identical word run and the
    failure was silently cleared from every channel — a whole-run collision,
    not a shingle-window one, so R7-1's rival-check removal did not touch it:
    there was no rival to fail to find, the equality test itself was wrong.
    """
    achievement = "Gross margin moved +12% in the quarter after the rewrite shipped."
    failure = "Gross margin moved -12% in the quarter after the rewrite shipped."
    master = CVMaster(
        headline=SourcedText(text="Data engineer — billing systems"),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(
            Episode(kind="achievement", text=achievement),
            Episode(kind="failure", text=failure),
        ),
    )
    write_master(store, master)
    version = _prepare(store, master, approved=(0,))
    where = _where(store, version)
    (where / "letter.md").write_text(
        (where / "letter.md").read_text(encoding="utf-8") + achievement + "\n", encoding="utf-8"
    )

    measured = measure_prepared(store, master, OFFER, version)

    # The duplicated approved line is unbacked in its own right and earns its
    # own finding, exactly as an exact duplicate does for a shingle-overlap
    # twin (R5-1's route).
    assert measured["unapproved_episode_disclosures"] == 1
    # The failure episode must not be silently cleared by the sign flip.
    assert not any(failure in item for item in measured["unapproved_episodes"])
    assert any(failure in item for item in measured["undecidable_episodes"])


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
