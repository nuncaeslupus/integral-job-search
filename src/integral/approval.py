"""T46 — details asked at the point of use, per-use episode approval, the send boundary.

Three rules from spec step 11 and §6.2, each made mechanical rather than
remembered:

**Personal details are asked here, for this document.** Date of birth, address,
telephone, the name to print — none of them improve a *search*, so gathering
them at Intake is collecting something months before anything needs it. They are
written into the version directory of the document that required them
(`cv/generated/<offer_id>/v<N>/personal.json`) and never into `cv/master.json`.
The measurement reads `master.json` off disk and names anything of this kind
sitting in it, by key *or* by value: a detail that reached the intake store got
there speculatively, whichever field it is hiding in.

**A story-bank episode reaches an employer-bound document only with per-use
approval.** Recounting a failure to the tool was never consent to send it to a
company. The approval is bound to `(offer_id, version, episode_index, text)`, so
it is per *use* in the literal sense: a regeneration writes `v<N+1>` and inherits
nothing, and an approval whose text no longer matches the store entry backs
nothing. `generate` cannot select an episode on its own — `episodes` is an
argument, and this module is the only caller that supplies it.

The gate, `unapproved_episode_disclosures == 0`, is measured the way T45's is:
over the **files on disk**, against the store. Whatever put an episode into a
finished document — this module, a hand edit, a later feature, a model — the
measurement sees the text in the file and asks the approval file whether
anything backs it. Asking the writer whether it behaved is not a check.

**No autonomous outward action.** Nothing here sends. `prepare` writes the
documents, the personal details to paste into the employer's form, and
`payload.json` — the summary of everything that would go, which documents, which
claims, which contact details, to whom. `record_sent` records that the candidate
sent it, and takes the payload's own digest as the confirmation: a standing
"yes, send whatever you like for this offer" cannot produce one, and neither can
a confirmation given for a different version. That is the §6.2 rule — approved
once per application, never as a standing permission — expressed as an equality
instead of a promise.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from integral.cv_store import CVMaster, Episode, _atomic_write_json, write_master
from integral.generate import DEFAULT_FIXTURE_MASTER, generate
from integral.identity import ProfileStore, create_profile

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T46.json"

SCHEMA_VERSION: Literal[1] = 1

# What "a personal detail" means here, and the closed list the measurement looks
# for in the intake store. Spec step 1 forbids every one of them at Intake by
# name; step 11 is where they are asked for, for the document being produced.
PERSONAL_FIELDS: tuple[str, ...] = (
    "full_name",
    "email",
    "phone",
    "postal_address",
    "date_of_birth",
)


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
    """One episode, cleared for one document.

    `text` pins *what* was approved. An approval that named only an index would
    survive the store entry being edited underneath it, which would let a
    changed episode ride out on last week's consent.
    """

    offer_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    episode_index: int = Field(ge=0)
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
    whom. It is written; it is never sent.
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

    `approved_episodes` is the candidate's per-use approval for this document,
    given now, for this draft. It is recorded next to the draft it authorised so
    the measurement can check the document against it, and it authorises nothing
    else: the next regeneration is a new version and asks again.
    """
    manifest = generate(
        store, master, offer_id=offer_id, advert=advert, asks=asks, episodes=approved_episodes
    )
    where = _version_parts(offer_id, manifest.version)
    approvals = Approvals(
        offer_id=offer_id,
        version=manifest.version,
        episodes=tuple(
            EpisodeApproval(
                offer_id=offer_id,
                version=manifest.version,
                episode_index=index,
                text=master.episodes[index].text,
            )
            for index in dict.fromkeys(approved_episodes)
        ),
    )
    _atomic_write_json(store, approvals.model_dump(mode="json"), *where, "approvals.json")
    _atomic_write_json(store, details.model_dump(mode="json"), *where, "personal.json")

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


def record_sent(
    store: ProfileStore,
    offer_id: str,
    version: int,
    *,
    confirms: str,
    sent_at: str | None = None,
) -> Path:
    """Record that the candidate sent this application. Nothing here sends it.

    `confirms` must be `payload_digest` of the payload on disk. A standing
    permission cannot produce that string, and neither can a yes given to a
    different draft, so the last decision stays with the person whose name is on
    the application.
    """
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


def _backed(master: CVMaster, approvals: Approvals | None, offer_id: str, version: int) -> set[str]:
    """The episode texts an approval on disk genuinely backs for this version."""
    if approvals is None or approvals.offer_id != offer_id or approvals.version != version:
        return set()
    return {
        approval.text
        for approval in approvals.episodes
        if approval.offer_id == offer_id
        and approval.version == version
        and approval.episode_index < len(master.episodes)
        and master.episodes[approval.episode_index].text == approval.text
    }


def read_approvals(store: ProfileStore, offer_id: str, version: int) -> Approvals | None:
    """The approval file for one version, or `None` if nothing approved anything."""
    path = store.path(*_version_parts(offer_id, version), "approvals.json")
    if not path.exists():
        return None
    return Approvals.model_validate_json(path.read_text(encoding="utf-8"))


def measure_prepared(
    store: ProfileStore, master: CVMaster, offer_id: str, version: int
) -> dict[str, Any]:
    """The gate for one prepared document: is every episode in it approved?

    The documents are read from disk and the store episodes are looked for in
    them. Detection is by presence of the episode's text anywhere in a document,
    not by matching a line the manifest already agrees about — the failure this
    guards against is an episode arriving by a route nobody registered.
    """
    where = store.path(*_version_parts(offer_id, version))
    backed = _backed(master, read_approvals(store, offer_id, version), offer_id, version)
    written = "\n".join(path.read_text(encoding="utf-8") for path in sorted(where.glob("*.md")))

    disclosed: list[str] = []
    unapproved: list[str] = []
    for index, episode in enumerate(master.episodes):
        if episode.text not in written:
            continue
        disclosed.append(f"{offer_id}/v{version}: episode {index} — {episode.text}")
        if episode.text not in backed:
            unapproved.append(f"{offer_id}/v{version}: episode {index} — {episode.text}")

    return {
        "episode_disclosures": len(disclosed),
        "episodes_withheld": len(master.episodes) - len(disclosed),
        "unapproved_episode_disclosures": len(unapproved),
        "unapproved_episodes": unapproved,
    }


def personal_details_in_master(store: ProfileStore, details: PersonalDetails) -> list[str]:
    """Personal details that reached `cv/master.json` — read from the file.

    By key and by value: `master.json` refuses an unknown key at load time, so a
    detail that got in did it by wearing another field's name, and the value is
    what finds it there.
    """
    path = store.path("cv", "master.json")
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    loaded = json.loads(raw)
    found = [f"cv/master.json: {field}" for field in PERSONAL_FIELDS if field in loaded]
    found += [
        f"cv/master.json: the {field} given at step 11 is in the intake store"
        for field, value in details.stated().items()
        if value in raw
    ]
    return sorted(set(found))


def sends_without_confirmation(store: ProfileStore) -> list[str]:
    """Application records on disk whose confirmation does not name their payload."""
    root = store.path("applications")
    if not root.is_dir():
        return []
    broken: list[str] = []
    for record in sorted(root.glob("*/v*.json")):
        data = json.loads(record.read_text(encoding="utf-8"))
        try:
            digest = payload_digest(read_payload(store, data["offer_id"], data["version"]))
        except (OSError, ValueError):
            broken.append(f"{data['offer_id']}/v{data['version']}: no payload on disk to confirm")
            continue
        if data.get("confirmed_digest") != digest:
            broken.append(f"{data['offer_id']}/v{data['version']}: confirms a different payload")
    return broken


# ---------------------------------------------------------------------------
# the gate — measured over the real corpus, against a stated fixture candidate

# The fixture candidate's story bank. Two episodes, and the measurement approves
# exactly one of them per advert, so every run exercises both branches: the
# episode that was cleared and the one that was not. A run that approved
# everything would report zero unapproved disclosures for a tool with no
# approval check in it at all.
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

# How many prepared applications the measurement also carries through the send
# boundary. A handful, not all of them: the property being measured is that a
# recorded send names its payload, and that is not more true at a hundred.
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
                record_sent(store, ad.id, payload.version, confirms=payload_digest(payload))
                recorded += 1

        leaked = personal_details_in_master(store, _FIXTURE_DETAILS)
        unconfirmed = sends_without_confirmation(store)

    return {
        # A fraction over no disclosures at all is the third D-2 outcome, not a
        # passing 1.0: nothing was measured, and `_main` says so and fails.
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


def _main(argv: list[str] | None = None) -> int:
    """Write T46's gate evidence. Exit 1 on any disclosure no approval backs."""
    args = [arg for arg in (argv if argv is not None else sys.argv)[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    failures = 0
    for key, label in (
        ("unapproved_episodes", "episode disclosed with no per-use approval"),
        ("personal_details_in_master", "personal detail in the intake store"),
        ("sends_without_confirmation", "send recorded without confirming its payload"),
    ):
        for name in measured[key]:
            print(f"✗ {label}: {name}", file=sys.stderr)
            failures += 1
    print(json.dumps(measured, ensure_ascii=False))
    if measured["episode_approval_coverage"] != 1.0:
        # Including `None`. A run that disclosed no episode never exercised the
        # approval path, and reporting a met gate off it would be a gate that
        # passes because nothing happened.
        print(
            f"episode_approval_coverage is {measured['episode_approval_coverage']!r}, not 1.0",
            file=sys.stderr,
        )
        return 1
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
