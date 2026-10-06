"""T149: replay the first complete run end to end, over a stated fictional candidate.

Every other gate in this repository measures one step. The tool has now been run
once from the first question to a sent application, and a step skill could be
changed afterwards with nothing noticing until a live session went wrong.

The run itself is one real person's tree and is not committed. What is committed
is a **translation**, `tests/fixtures/end_to_end/run.json`, over the fictional
candidate `tests/fixtures/generation/master.json` already provides: the step
sequence (including the steps that were revisited), the artefact each step
wrote, and thirteen document revisions with what each one changed and why.

`replay` builds a throwaway profile and walks that sequence with the real
machinery, asking at each seam the question the failures were actually about:
*did the step before hand this step something it could use?*

* **Before** a step runs, `step_runtime.missing_inputs` must be empty for it
  against what the profile holds *at that moment* — the order is the fixture's,
  not the graph's canonical one, because the real run was not canonical
  (reactions ran after ranking).
* **After** it runs, every artefact the fixture says it wrote must be seen by the
  detector that the next step's `missing_inputs` consults. Writing a file the
  detector cannot see is a step that produced nothing.
* **Between** steps, each stage is derived from what the one before left on
  disk, with the real code: `liveness.read_response` and `expire` over the stored
  advert text, `candidate.filter_hard_constraints` over the stored constraints,
  `extraction.extract` and `rank.rank` over the offers still presentable. The
  fixture's `outcome` labels are only the expectation the result is compared
  with, never an input. Offers are served to liveness as a 200 page carrying their
  stored title and text (nothing is fetched), and the connector-read facts the constraint
  screen compares are fixture data; extraction runs its rules stage only, with
  no model. An application is drafted only for an offer a `rankings/*.json` on
  disk names at that moment.
* **The documents** are drafted through `approval.prepare` — the real generator,
  the real manifest, the real `to` block (`Payload.recipient`) — and each
  revision is compared with what the fixture says it must be and with the
  revision before it, which it must differ from: a revision that changed nothing
  is a draft that was not a revision. The sent revision is staged, verified and
  recorded, and rendered with the style sheet the render uses.

The gate is `end_to_end_replay_defects == 0`. A replay that walked too little to
mean anything exits 3 (unmeasured), never a clean zero.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from integral.application_render import CSS, render_document
from integral.approval import (
    ApprovalError,
    Payload,
    PersonalDetails,
    payload_digest,
    prepare,
    read_payload,
    record_sent,
    stage_send,
    verify_send,
)
from integral.candidate import CandidateError, OfferFacts, filter_hard_constraints, load_constraints
from integral.cv_store import CVMaster, Episode, write_master
from integral.dimensions import Dimension, ad_side, load_dimensions
from integral.extraction import ExtractionError, OfferExtraction, extract
from integral.generate import read_manifest
from integral.identity import IdentityError, ProfileStore, create_profile
from integral.liveness import RETIRED_STATUSES, SourceCheck, expire, presentable, read_response
from integral.offers import Offer, OfferError, compute_offer_id, load_offer, save_offer
from integral.prior_documents import digest as prior_digest
from integral.process_spec import StepList, load_steps
from integral.profile import EvidenceLog
from integral.rank import RankingError, from_extraction, rank
from integral.step_runtime import (
    ProfileView,
    missing_inputs,
    present_artefacts,
    unknown_artefacts,
)
from integral.voice import record as record_voice

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T149.json"
DEFAULT_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "end_to_end" / "run.json"

_STAMP = "2026-10-01T09:00:00Z"
_DETAILS = PersonalDetails(
    full_name="Marta Ferrer",
    email="marta@example.invalid",
    phone="+34 600 000 000",
    postal_address="1 Carrer de Prova, 17001 Girona",
    date_of_birth="1990-01-01",
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Candidate(Strict):
    display_name: str
    handle: str
    language: str


class Story(Strict):
    id: str
    text: str
    dimensions: tuple[str, ...]


class Reaction(Strict):
    text: str
    dimensions: tuple[str, ...]


class OfferSpec(Strict):
    slug: str
    title: str
    company: str
    # The facts a connector read off the advert, which the real constraint screen compares.
    country: str
    region: str | None
    delivery: str  # "remote" | "hybrid" | "onsite"
    requires_relocation: bool = False
    # The EXPECTATION: what the real stages must do with this offer. Never an input.
    outcome: str  # "ranked" | "expired" | "filtered"
    text: str


class StepRun(Strict):
    step: str
    stage: str
    revisit: bool
    writes: tuple[str, ...]
    assumed: str | None = None


class VoiceSpec(Strict):
    statement: str
    forbid: tuple[str, ...]


class Expect(Strict):
    version: int
    cv_skills: tuple[str, ...]
    letter_episodes: tuple[int, ...]
    gaps: tuple[str, ...]
    voice_omitted: tuple[str, ...]


class Revision(Strict):
    n: int
    offer: str
    recipient: str
    asks: tuple[str, ...]
    approved_episodes: tuple[int, ...]
    judgement: str
    expect: Expect
    voice: VoiceSpec | None = None
    assumed: str | None = None


class Sent(Strict):
    revision: int
    assumed: str | None = None


class Fixture(Strict):
    schema_version: int
    provenance: str
    candidate: Candidate
    master: str
    episodes: tuple[dict[str, str], ...]
    constraints: dict[str, dict[str, Any]]
    constraints_revisited: dict[str, dict[str, Any]]
    stories: tuple[Story, ...]
    traits: dict[str, dict[str, int]]
    reactions: tuple[Reaction, ...]
    offers: tuple[OfferSpec, ...]
    sequence: tuple[StepRun, ...]
    revisions: tuple[Revision, ...]
    sent: Sent


def load_fixture(path: Path = DEFAULT_FIXTURE_PATH) -> Fixture:
    return Fixture.model_validate_json(path.read_text(encoding="utf-8"))


@dataclass
class Replay:
    defects: list[str] = field(default_factory=list)
    steps_replayed: int = 0
    revisions_replayed: int = 0
    checks: int = 0

    def check(self, ok: bool, message: str) -> bool:
        self.checks += 1
        if not ok:
            self.defects.append(message)
        return ok


# ---------------------------------------------------------------------------
# the step writers — each derives what it leaves behind from what is on disk
#
# The fixture's `outcome` labels are the EXPECTATION. A stage never reads them to
# decide what to write: liveness runs the real closure reader over the stored
# advert text, filtering runs the real constraint screen over the stored
# constraints, and understanding and ranking run the real extraction and ranker
# over the offers the earlier stages left presentable. `_seams` then compares
# what came out with the labels.


def _offer_ids(fixture: Fixture) -> dict[str, str]:
    return {spec.slug: compute_offer_id(spec.text) for spec in fixture.offers}


@lru_cache(maxsize=1)
def _dimensions() -> tuple[Dimension, ...]:
    return tuple(ad_side(load_dimensions()))


def _stored_offers(store: ProfileStore) -> list[Offer]:
    return [load_offer(store, path.stem) for path in sorted(store.path("offers").glob("*.json"))]


def _in_play(offer: Offer) -> bool:
    return offer.status not in RETIRED_STATUSES and offer.status != "screened_out"


def _source_check(offer: Offer) -> SourceCheck:
    """What fetching the advert's own page says: the stored title and text, served as a 200."""
    title, text = escape(offer.title or ""), escape(offer.text)
    page = (
        f"<html><head><title>{title}</title></head>"
        f"<body><h1>{title}</h1><p>{text}</p></body></html>"
    )
    return read_response(offer.id, 200, page, title=offer.title)


def _facts(fixture: Fixture, offer_id: str) -> OfferFacts:
    spec = next(s for s in fixture.offers if compute_offer_id(s.text) == offer_id)
    return OfferFacts(
        offer_id=offer_id,
        country=spec.country,
        region=spec.region,
        delivery=spec.delivery,  # type: ignore[arg-type]
        requires_relocation=spec.requires_relocation,
    )


def _ranking_name(run: StepRun) -> str:
    return f"{_STAMP}-{run.stage}.json"


def _ranking_ids(ranking: dict[str, Any]) -> list[str]:
    return [*ranking.get("pareto", []), *ranking.get("dominated", {})]


def ranked_offers(store: ProfileStore) -> set[str]:
    """Offer ids named by any `rankings/*.json` on disk right now."""
    named: set[str] = set()
    for path in sorted(store.path("rankings").glob("*.json")):
        named.update(_ranking_ids(json.loads(path.read_text(encoding="utf-8"))))
    return named


def _write(store: ProfileStore, fixture: Fixture, run: StepRun, master: CVMaster) -> None:
    log = EvidenceLog(store)
    if run.step == "identify":
        store.write_json({"handle": store.handle, "sufficiency": "L0"}, "session", "state.json")
    elif run.step == "intake":
        write_master(store, master)
    elif run.step == "constraints":
        fields = dict(fixture.constraints)
        if run.revisit:
            fields.update(fixture.constraints_revisited)
        store.write_json({"fields": fields}, "profile", "constraints.json")
    elif run.step == "history":
        for story in fixture.stories:
            store.append_jsonl({"id": story.id, "text": story.text}, "profile", "stories.jsonl")
            log.append(
                recorded_at=_STAMP,
                step="history",
                kind="episode",
                text=story.text,
                source="conversation",
                dimensions=story.dimensions,
            )
    elif run.step == "traits":
        store.write_json({"dimensions": fixture.traits}, "profile", "traits.json")
    elif run.step == "sourcing":
        _source(store, fixture, run)
    elif run.step == "understanding":
        for offer in _stored_offers(store):
            if _in_play(offer):
                extraction = extract(offer, list(_dimensions()), default_language="en")
                store.write_json(
                    extraction.model_dump(mode="json"),
                    "extractions",
                    f"{offer.id.replace(':', '-')}.json",
                )
    elif run.step == "ranking":
        _rank(store, run)
    elif run.step == "reactions":
        for reaction in fixture.reactions:
            log.append(
                recorded_at=_STAMP,
                step="reactions",
                kind="reaction",
                text=reaction.text,
                source="offer_reaction",
                dimensions=reaction.dimensions,
            )
    # `application` is replayed by `_documents`, through the real generator.


def _source(store: ProfileStore, fixture: Fixture, run: StepRun) -> None:
    if run.stage == "collect":
        for spec in fixture.offers:
            save_offer(
                store,
                Offer(
                    id=compute_offer_id(spec.text),
                    source="manual",
                    title=spec.title,
                    company=spec.company,
                    text=spec.text,
                ),
            )
    elif run.stage == "liveness":
        for offer in _stored_offers(store):
            save_offer(store, expire(offer, _source_check(offer)))
    elif run.stage == "filtering":
        constraints = load_constraints(store.read_json("profile", "constraints.json"))
        live = [offer for offer in _stored_offers(store) if _in_play(offer)]
        result = filter_hard_constraints(constraints, [_facts(fixture, o.id) for o in live])
        refused = {removal.offer_id for removal in result.removed}
        for offer in live:
            if offer.id in refused:
                save_offer(store, offer.model_copy(update={"status": "screened_out"}))


def _rank(store: ProfileStore, run: StepRun) -> None:
    stored = _stored_offers(store)
    shown, _ = presentable(stored, {o.id: _source_check(o) for o in stored})
    names = [d.id for d in _dimensions()]
    candidates = []
    for offer in shown:
        name = f"{offer.id.replace(':', '-')}.json"
        if _in_play(offer) and store.exists("extractions", name):
            extraction = OfferExtraction.model_validate(store.read_json("extractions", name))
            candidates.append(from_extraction(extraction, dimensions=names, salary_per_month=None))
    ranking = rank(
        candidates,
        dimensions=names,
        revision=EvidenceLog(store).revision(),
        weights=None,
        at=f"{_STAMP}-{run.stage}",
    )
    store.write_json(ranking, "rankings", _ranking_name(run))


def _status(store: ProfileStore, offer_id: str) -> str | None:
    try:
        return load_offer(store, offer_id).status
    except OfferError:
        return None


def _seams(replay: Replay, store: ProfileStore, fixture: Fixture, run: StepRun) -> None:
    """What this step left on disk, against what the fixture says should be true."""
    ids = _offer_ids(fixture)
    where = f"{run.step}/{run.stage}"
    if run.step == "sourcing":
        for spec in fixture.offers:
            path_exists = store.exists("offers", f"{ids[spec.slug]}.json")
            replay.check(path_exists, f"{where}: offer {spec.slug} was not stored")
        for stage, status, outcome in (
            ("liveness", "expired", "expired"),
            ("filtering", "screened_out", "filtered"),
        ):
            if run.stage != stage:
                continue
            for spec in fixture.offers:
                got = _status(store, ids[spec.slug])
                if spec.outcome == outcome:
                    replay.check(
                        got == status,
                        f"{where}: {outcome} offer {spec.slug} is still {got!r}",
                    )
                else:
                    replay.check(
                        got != status,
                        f"{where}: offer {spec.slug} was {status} by the real code, "
                        f"but the fixture says it is {spec.outcome}",
                    )
    elif run.step == "understanding":
        for spec in fixture.offers:
            name = f"{ids[spec.slug].replace(':', '-')}.json"
            if spec.outcome == "ranked":
                payload = (
                    store.read_json("extractions", name)
                    if store.exists("extractions", name)
                    else {}
                )
                replay.check(
                    payload.get("offer_id") == ids[spec.slug]
                    and store.exists("offers", f"{ids[spec.slug]}.json"),
                    f"{where}: extraction for {spec.slug} names no stored offer",
                )
            else:
                replay.check(
                    not store.exists("extractions", name),
                    f"{where}: an extraction was written for {spec.outcome} offer {spec.slug}",
                )
    elif run.step == "ranking":
        named = _ranking_ids(store.read_json("rankings", _ranking_name(run)))
        for offer_id in named:
            replay.check(
                _status(store, offer_id) not in {"expired", "screened_out"},
                f"{where}: the ranking carries {offer_id}, which is {_status(store, offer_id)}",
            )
            replay.check(
                any(
                    p.name.startswith(offer_id.replace(":", "-"))
                    for p in store.path("extractions").glob("*.json")
                ),
                f"{where}: the ranking carries {offer_id}, which has no extraction",
            )
        for spec in fixture.offers:
            if spec.outcome != "ranked":
                replay.check(
                    ids[spec.slug] not in named,
                    f"{where}: {spec.outcome} offer {spec.slug} reached the ranking",
                )
            else:
                replay.check(
                    ids[spec.slug] in named,
                    f"{where}: ranked offer {spec.slug} is missing from the ranking",
                )


# ---------------------------------------------------------------------------
# the document revisions


def _claims(store: ProfileStore, offer_id: str, version: int) -> dict[str, list[Any]]:
    manifest = read_manifest(store, offer_id, version)
    return {
        "cv_skills": [
            c.text.split(" (")[0]
            for c in manifest.claims
            if c.document == "cv.md" and c.section == "skills"
        ],
        "letter_episodes": [
            c.entry_index
            for c in manifest.claims
            if c.document == "letter.md" and c.section == "episodes"
        ],
        "gaps": list(manifest.gaps),
        "voice_omitted": [
            o.text.split(" (")[0]
            for o in manifest.omissions
            if o.section == "skills" and o.reason.startswith("voice preference")
        ],
    }


def _documents(replay: Replay, store: ProfileStore, fixture: Fixture, master: CVMaster) -> None:
    ids = _offer_ids(fixture)
    adverts = {spec.slug: spec.text for spec in fixture.offers}
    # What the application step may draft for is what the ranking left ON DISK
    # at this moment, not what the fixture says was ranked.
    ranked = ranked_offers(store)
    replay.check(bool(ranked), "application/documents: no ranking is on disk to draft for")
    previous: dict[str, dict[str, Any]] = {}
    sent_payload: tuple[str, int, Payload] | None = None
    for revision in fixture.revisions:
        offer_id = ids[revision.offer]
        label = f"revision {revision.n} ({revision.offer} v{revision.expect.version})"
        replay.check(offer_id in ranked, f"{label}: drafted for an offer no ranking on disk names")
        if revision.voice is not None:
            record_voice(
                EvidenceLog(store), revision.voice.statement, revision.voice.forbid, at=_STAMP
            )
        try:
            payload = prepare(
                store,
                master,
                offer_id=offer_id,
                advert=adverts[revision.offer],
                recipient=revision.recipient,
                details=_DETAILS,
                asks=revision.asks,
                approved_episodes=revision.approved_episodes,
            )
        except ApprovalError as exc:
            replay.check(False, f"{label}: the drafting was refused: {exc}")
            continue
        replay.revisions_replayed += 1
        replay.check(
            payload.version == revision.expect.version,
            f"{label}: drafted as v{payload.version}",
        )
        # Read back from disk, not taken from the object `prepare` returned: the
        # `to` block is what reaches the file the candidate confirms and sends.
        stored = read_payload(store, offer_id, payload.version)
        replay.check(
            stored.recipient == revision.recipient,
            f"{label}: the `to` block on disk reads {stored.recipient!r}, "
            f"not {revision.recipient!r}",
        )
        replay.check(
            payload_digest(stored.model_copy(update={"recipient": "someone else"}))
            != payload_digest(stored),
            f"{label}: the `to` block is not part of what the candidate confirms",
        )
        try:
            seen = _claims(store, offer_id, payload.version)
        except (OSError, ValidationError, ValueError) as exc:
            replay.check(False, f"{label}: the claim manifest is unreadable: {exc}")
            continue
        expected = revision.expect.model_dump()
        expected.pop("version")
        for key, want in expected.items():
            got = seen[key]
            replay.check(
                got == list(want),
                f"{label}: {key} is {got!r}, the fixture says {list(want)!r}",
            )
        state = {**seen, "recipient": payload.recipient}
        if revision.expect.version > 1:
            replay.check(
                state != previous.get(offer_id),
                f"{label}: changed nothing from the revision before it",
            )
        previous[offer_id] = state
        if revision.n == fixture.sent.revision:
            sent_payload = (offer_id, payload.version, payload)

    digest = prior_digest(store)
    replay.check(not digest.skipped, f"prior documents skipped: {digest.skipped!r}")
    replay.check(
        not any(o.undetermined for o in digest.offers),
        "a revision carries a line its manifest does not trace",
    )
    wanted = {
        offer: sorted(r.expect.version for r in fixture.revisions if r.offer == offer)
        for offer in {r.offer for r in fixture.revisions}
    }
    for offer, versions in sorted(wanted.items()):
        found = next((o for o in digest.offers if o.offer_id == ids[offer]), None)
        replay.check(
            found is not None and list(found.versions) == versions,
            f"{offer}: the next revision would see versions "
            f"{None if found is None else list(found.versions)}, not {versions}",
        )
    _send(replay, store, master, sent_payload)


def _send(
    replay: Replay,
    store: ProfileStore,
    master: CVMaster,
    sent: tuple[str, int, Payload] | None,
) -> None:
    if not replay.check(sent is not None, "no revision was marked as the one sent"):
        return
    assert sent is not None
    offer_id, version, _ = sent
    confirms = payload_digest(read_payload(store, offer_id, version))
    try:
        stage_send(store, master, offer_id, version, confirms=confirms)
        defects = verify_send(store, offer_id, version)
        replay.check(not defects, f"the send folder is not what was approved: {defects}")
        # The check must be able to say no: a letter edited after staging is refused.
        letter = store.path("cv", "generated", offer_id, f"v{version}", "send", "letter.md")
        original = letter.read_text(encoding="utf-8")
        letter.write_text(original + "\nAn unapproved sentence.\n", encoding="utf-8")
        try:
            tampered = verify_send(store, offer_id, version)
        finally:
            letter.write_text(original, encoding="utf-8")
        replay.check(bool(tampered), "a send folder edited after staging still verifies")
        record_sent(store, master, offer_id, version, confirms=confirms)
    except ApprovalError as exc:
        replay.check(False, f"the sent revision was refused: {exc}")
        return
    replay.check(
        store.exists("applications", offer_id, f"v{version}.json"),
        "the send was not recorded",
    )
    folder = ("cv", "generated", offer_id, f"v{version}", "send")
    for name, kind in (("cv.md", "cv"), ("letter.md", "letter")):
        rendered = render_document(store.read_text(*folder, name), title=name, kind=kind, lang="en")
        replay.check(CSS in rendered, f"{name} was rendered without the committed style sheet")
        replay.check(
            re.search(r"<link\b|@import|https?://", rendered) is None,
            f"{name} renders with something outside the one self-contained page",
        )


# ---------------------------------------------------------------------------
# the replay


def replay(root: Path, fixture: Fixture | None = None, steps: StepList | None = None) -> Replay:
    fixture = fixture or load_fixture()
    steps = steps or load_steps()
    result = Replay()
    by_id = {step.id: step for step in steps.steps}

    stray = unknown_artefacts(steps)
    result.check(not stray, f"the graph names artefacts no detector can see: {stray}")

    master = CVMaster.model_validate_json((_REPO_ROOT / fixture.master).read_text(encoding="utf-8"))
    master = master.model_copy(
        update={"episodes": tuple(Episode(**episode) for episode in fixture.episodes)}  # type: ignore[arg-type]
    )

    identity = create_profile(
        root,
        fixture.candidate.display_name,
        handle=fixture.candidate.handle,
        language=fixture.candidate.language,  # type: ignore[arg-type]
        fiction=True,
    )
    store = ProfileStore(root, identity.handle)

    seen: set[str] = set()
    for run in fixture.sequence:
        where = f"{run.step}/{run.stage}"
        step = by_id.get(run.step)
        if not result.check(step is not None, f"{where}: the graph has no step {run.step!r}"):
            continue
        assert step is not None
        present = present_artefacts(ProfileView(store), steps)
        missing = missing_inputs(step, present)
        result.check(
            not missing,
            f"{where}: ran without {', '.join(missing)}, which the step before did not hand over",
        )
        result.check(
            set(run.writes) <= set(step.produces),
            f"{where}: writes {sorted(set(run.writes) - set(step.produces))} the graph "
            "does not say this step produces",
        )
        result.check(
            not run.revisit or run.step in seen,
            f"{where}: marked as a revisit of {run.step}, which this run has not been to before",
        )
        seen.add(run.step)
        try:
            if run.step == "application":
                _documents(result, store, fixture, master)
            else:
                _write(store, fixture, run, master)
            view = ProfileView(store)
            after = present_artefacts(view, steps)
            unseen = [a for a in run.writes if a not in after]
            result.check(
                not unseen,
                f"{where}: wrote {', '.join(unseen)}, which nothing downstream can see",
            )
            _seams(result, store, fixture, run)
        except (
            ApprovalError,
            CandidateError,
            ExtractionError,
            IdentityError,
            OfferError,
            RankingError,
            OSError,
            ValueError,
            KeyError,
        ) as exc:
            result.check(False, f"{where}: stopped with {type(exc).__name__}: {exc}")
        result.steps_replayed += 1
    return result


#: Raised to what the fixture carries — 14 steps, zero slack — because a replay
#: that walked fewer would report `0` over a run it did not make. The fixture is
#: a list this module reads, so deleting a step from it is the first deletion
#: this floor breaches.
#: arsenal-floor-margin: MINIMUM_STEPS_REPLAYED value=14
MINIMUM_STEPS_REPLAYED = 14
#: Raised to what the fixture carries — 13 revisions, zero slack: the thirteen of
#: the first complete run, each drafted through the real generator.
#: arsenal-floor-margin: MINIMUM_REVISIONS_REPLAYED value=13
MINIMUM_REVISIONS_REPLAYED = 13


def measure(fixture_path: Path = DEFAULT_FIXTURE_PATH) -> dict[str, Any]:
    fixture = load_fixture(fixture_path)
    with tempfile.TemporaryDirectory(prefix="integral-t149-") as tmp:
        result = replay(Path(tmp) / "profiles", fixture)
    measured: dict[str, Any] = {
        "end_to_end_replay_defects": len(result.defects),
        "end_to_end_replay_status": "measured",
        "steps_replayed_at_least": MINIMUM_STEPS_REPLAYED,
        "revisions_replayed_at_least": MINIMUM_REVISIONS_REPLAYED,
        "steps_replayed": result.steps_replayed,
        "revisions_replayed": result.revisions_replayed,
        "defects": result.defects,
    }
    return measured


def _dump(evidence: Path, measured: dict[str, Any]) -> None:
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH, fixture_path: Path = DEFAULT_FIXTURE_PATH
) -> dict[str, Any]:
    measured = measure(fixture_path)
    _dump(evidence, measured)
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.end_to_end [path]` -> T149's gate evidence.

    A replay that walked less than the floors is not a clean zero: the evidence
    is rewritten with `-1` and `unmeasured`, saying that nothing after the point
    it stopped was looked at.
    """
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    fixture_path = Path(positional[1]) if len(positional) > 1 else DEFAULT_FIXTURE_PATH
    measured = write_evidence(target, fixture_path)
    if (
        measured["steps_replayed"] < MINIMUM_STEPS_REPLAYED
        or measured["revisions_replayed"] < MINIMUM_REVISIONS_REPLAYED
    ):
        measured["end_to_end_replay_defects"] = -1
        measured["end_to_end_replay_status"] = "unmeasured"
        _dump(target, measured)
        print(json.dumps(measured, ensure_ascii=False))
        print(
            f"only {measured['steps_replayed']} steps and {measured['revisions_replayed']} "
            "revisions were replayed - the run stopped early, so nothing after it was measured",
            file=sys.stderr,
        )
        return 3
    print(json.dumps(measured, ensure_ascii=False))
    for defect in measured["defects"]:
        print(defect, file=sys.stderr)
    return 1 if measured["defects"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
