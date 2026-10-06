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
* **Between** steps, the references hold: an extraction names a stored offer, a
  ranking names only offers that survived liveness and filtering and have an
  extraction, and an application is drafted only for a ranked offer.
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
from integral.cv_store import CVMaster, Episode, write_master
from integral.generate import read_manifest
from integral.identity import ProfileStore, create_profile
from integral.offers import Offer, compute_offer_id, load_offer, save_offer
from integral.prior_documents import digest as prior_digest
from integral.process_spec import StepList, load_steps
from integral.profile import EvidenceLog
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


class Sent(Strict):
    revision: int


class Fixture(Strict):
    schema_version: int
    provenance: str
    candidate: Candidate
    master: str
    episodes: tuple[dict[str, str], ...]
    constraints: dict[str, dict[str, str]]
    constraints_revisited: dict[str, dict[str, str]]
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
# the step writers — each writes what the real step leaves behind, from the fixture


def _offer_ids(fixture: Fixture) -> dict[str, str]:
    return {spec.slug: compute_offer_id(spec.text) for spec in fixture.offers}


def _write(store: ProfileStore, fixture: Fixture, run: StepRun, master: CVMaster) -> None:
    log = EvidenceLog(store)
    ids = _offer_ids(fixture)
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
        for spec in fixture.offers:
            offer = Offer(
                id=ids[spec.slug],
                source="manual",
                title=spec.title,
                company=spec.company,
                text=spec.text,
            )
            retired = {"liveness": "expired", "filtering": "filtered"}.get(run.stage)
            if run.stage != "collect" and spec.outcome != retired:
                continue  # this stage only touches the offers it retires
            if spec.outcome == "expired" and run.stage == "liveness":
                offer = offer.model_copy(update={"status": "expired"})
            if spec.outcome == "filtered" and run.stage == "filtering":
                offer = offer.model_copy(update={"status": "screened_out"})
            save_offer(store, offer)
    elif run.step == "understanding":
        for spec in fixture.offers:
            if spec.outcome != "ranked":
                continue
            store.write_json(
                {"offer_id": ids[spec.slug], "scores": {"fit_stack": 1.0}},
                "extractions",
                f"{ids[spec.slug].replace(':', '-')}.json",
            )
    elif run.step == "ranking":
        ranked = [ids[s.slug] for s in fixture.offers if s.outcome == "ranked"]
        store.write_json({"level": "L1", "offers": ranked}, "rankings", f"{run.stage}.json")
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


def _seams(replay: Replay, store: ProfileStore, fixture: Fixture, run: StepRun) -> None:
    """The references between artefacts that this step has just made true or false."""
    ids = _offer_ids(fixture)
    where = f"{run.step}/{run.stage}"
    if run.step == "sourcing":
        for spec in fixture.offers:
            path_exists = store.exists("offers", f"{ids[spec.slug]}.json")
            replay.check(path_exists, f"{where}: offer {spec.slug} was not stored")
        if run.stage == "liveness":
            for spec in fixture.offers:
                if spec.outcome == "expired":
                    stored = load_offer(store, ids[spec.slug])
                    replay.check(
                        stored.status == "expired",
                        f"{where}: expired offer {spec.slug} is still {stored.status!r}",
                    )
        if run.stage == "filtering":
            for spec in fixture.offers:
                if spec.outcome == "filtered":
                    stored = load_offer(store, ids[spec.slug])
                    replay.check(
                        stored.status == "screened_out",
                        f"{where}: filtered offer {spec.slug} is still {stored.status!r}",
                    )
    elif run.step == "understanding":
        for spec in fixture.offers:
            if spec.outcome == "ranked":
                name = f"{ids[spec.slug].replace(':', '-')}.json"
                payload = store.read_json("extractions", name)
                replay.check(
                    payload.get("offer_id") == ids[spec.slug]
                    and store.exists("offers", f"{ids[spec.slug]}.json"),
                    f"{where}: extraction for {spec.slug} names no stored offer",
                )
    elif run.step == "ranking":
        ranking = store.read_json("rankings", f"{run.stage}.json")
        for offer_id in ranking["offers"]:
            stored = load_offer(store, offer_id)
            replay.check(
                stored.status not in {"expired", "screened_out"},
                f"{where}: the ranking carries {offer_id}, which is {stored.status}",
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
                    ids[spec.slug] not in ranking["offers"],
                    f"{where}: {spec.outcome} offer {spec.slug} reached the ranking",
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
    ranked = {ids[s.slug] for s in fixture.offers if s.outcome == "ranked"}
    previous: dict[str, dict[str, Any]] = {}
    sent_payload: tuple[str, int, Payload] | None = None
    for revision in fixture.revisions:
        offer_id = ids[revision.offer]
        label = f"revision {revision.n} ({revision.offer} v{revision.expect.version})"
        replay.check(offer_id in ranked, f"{label}: drafted for an offer that was never ranked")
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
    return {
        "end_to_end_replay_defects": len(result.defects),
        "steps_replayed_at_least": MINIMUM_STEPS_REPLAYED,
        "revisions_replayed_at_least": MINIMUM_REVISIONS_REPLAYED,
        "steps_replayed": result.steps_replayed,
        "revisions_replayed": result.revisions_replayed,
        "defects": result.defects,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH, fixture_path: Path = DEFAULT_FIXTURE_PATH
) -> dict[str, Any]:
    measured = measure(fixture_path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.end_to_end [path]` → T149's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    fixture_path = Path(positional[1]) if len(positional) > 1 else DEFAULT_FIXTURE_PATH
    measured = write_evidence(target, fixture_path)
    print(json.dumps(measured, ensure_ascii=False))
    if (
        measured["steps_replayed"] < MINIMUM_STEPS_REPLAYED
        or measured["revisions_replayed"] < MINIMUM_REVISIONS_REPLAYED
    ):
        print(
            f"only {measured['steps_replayed']} steps and {measured['revisions_replayed']} "
            "revisions were replayed — the run stopped early, so nothing after it was measured",
            file=sys.stderr,
        )
        return 3
    for defect in measured["defects"]:
        print(defect, file=sys.stderr)
    return 1 if measured["defects"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
