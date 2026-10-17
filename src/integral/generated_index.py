"""T343 — `cv/generated/INDEX.md`, regenerated from what is on disk, never by hand.

Offer directories are `sha256:<hash>/v<N>/`, so finding a delivery meant reading
hash directories. The employer link (#805) names the latest delivery, but the map
of employer, role, versions and send path was a hand-kept file, and a hand-kept
map is stale the moment a version is written.

`render_index` is a pure function of the tree: the offer directories, their
`v<N>` folders and `manifest.json`, the employer links beside them, each
version's `send/` folder and the stored offer's company and title. Nothing in it
is a clock, a counter or a dict order, so two runs over one tree are
byte-identical and a regeneration that changes nothing writes nothing.

`refresh_index` is the one write. `generate.generate`, `generate.link_employer`
and `approval.stage_send` call it as their last step; those are the three places
that change what the index says. `status/evidence/T343.json` measures
`generated_versions_missing_from_the_index` over constructed trees, one of which
is a write path that skips the call, so the metric can read above zero. A
"missing" here means the file on disk is not byte-for-byte `render_index` of the
tree (`index_differs`); no cell is parsed, so a wrong link, a phantom version or
row, or a `|` in a company name cannot pass or break the check. The real cases
include a stored offer (employer and role columns) and a real `stage_send`
(send-path column, the call's position after the send folder is written, and the
early return over an intact folder).

The file sits beside the offer directories, so every walker of `cv/generated/`
has to skip it by name (`INDEX_NAME`); `revision.py` classes it historical, since
it is derived from a tree whose own class is authored and carries no revision.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from integral.cv_store import _atomic_write_text
from integral.identity import ProfileStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T343.json"

INDEX_NAME = "INDEX.md"
_VERSION_DIR = re.compile(r"^v(\d+)$")

#: Constructed cases the metric is measured over (a floor: deleting a case makes
#: the gate fail, it cannot silently shrink the denominator).
MINIMUM_CASES_MEASURED = 8

_EMPTY = "-"


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|") or _EMPTY


def _versions(offer_dir: Path) -> list[int]:
    found = [
        int(match.group(1))
        for child in offer_dir.iterdir()
        if child.is_dir() and not child.is_symlink() and (match := _VERSION_DIR.match(child.name))
    ]
    return sorted(found)


def _manifest_ok(version_dir: Path) -> bool:
    try:
        data = json.loads((version_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict)


def render_index(store: ProfileStore) -> str:
    """The index text for the tree as it stands."""
    from integral.generate import is_employer_alias
    from integral.offers import OfferError, load_offer

    root = store.path("cv", "generated")
    offers: list[Path] = []
    aliases: dict[str, list[str]] = {}
    if root.is_dir():
        for child in sorted(root.iterdir(), key=lambda p: p.name):
            if is_employer_alias(child):
                aliases.setdefault(child.readlink().name, []).append(child.name)
            elif child.is_dir() and not child.is_symlink():
                offers.append(child)

    lines = [
        "# Generated deliveries",
        "",
        "Regenerated from the manifests every time a version is written or an employer",
        "link is made. Do not edit by hand: the next write replaces it.",
        "",
        "| Employer | Role | Offer | Versions | Send path |",
        "| --- | --- | --- | --- | --- |",
    ]
    for offer_dir in offers:
        versions = _versions(offer_dir)
        if not versions:
            continue
        company = role = _EMPTY
        try:
            offer = load_offer(store, offer_dir.name)
            company, role = offer.company or _EMPTY, offer.title or _EMPTY
        except (OfferError, OSError, ValueError, RecursionError):
            pass
        slugs = ", ".join(f"`{slug}`" for slug in sorted(aliases.get(offer_dir.name, ())))
        employer = _cell(company) if not slugs else f"{_cell(company)} ({slugs})"
        shown = ", ".join(
            f"v{n}" if _manifest_ok(offer_dir / f"v{n}") else f"v{n} (no manifest)"
            for n in versions
        )
        send = _EMPTY
        for n in reversed(versions):
            folder = offer_dir / f"v{n}" / "send"
            if folder.is_dir() and not folder.is_symlink():
                send = f"`{offer_dir.name}/v{n}/send`"
                break
        lines.append(f"| {employer} | {_cell(role)} | `{offer_dir.name}` | {shown} | {send} |")
    return "\n".join(lines) + "\n"


def refresh_index(store: ProfileStore) -> Path:
    """Write `cv/generated/INDEX.md` if it differs from what the tree renders."""
    path = store.path("cv", "generated", INDEX_NAME)
    text = render_index(store)
    try:
        if path.read_text(encoding="utf-8") == text:
            return path
    except OSError:
        pass
    return _atomic_write_text(store, text, "cv", "generated", INDEX_NAME)


def index_differs(store: ProfileStore) -> int:
    """1 when `INDEX.md` on disk is not, byte for byte, what the tree renders; else 0.

    The closed rule: the file is a pure function of the manifests, so any other
    content is stale (a write that skipped `refresh_index`), hand-edited (a wrong
    link or send path), or invented (a phantom version or offer row). No cell is
    parsed, so no cell content can fool it or break it."""
    path = store.path("cv", "generated", INDEX_NAME)
    try:
        on_disk = path.read_text(encoding="utf-8")
    except OSError:
        return 1
    return int(on_disk != render_index(store))


# --- the gate ---------------------------------------------------------------


def _fixture_store(scratch: Path) -> ProfileStore:
    from integral.identity import create_profile

    root = scratch / "profiles"
    identity = create_profile(root, "Gate Fixture", handle="fixture", language="en")
    return ProfileStore(root, identity.handle)


def _master() -> Any:
    from integral.cv_store import CVMaster
    from integral.generate import DEFAULT_FIXTURE_MASTER

    return CVMaster.model_validate_json(DEFAULT_FIXTURE_MASTER.read_text(encoding="utf-8"))


_GATE_ADVERT = "We are hiring a data engineer in Girona to own a PostgreSQL estate."
GATE_COMPANY = "Acme | Co"
GATE_ROLE = "Data Engineer"


def _engine() -> dict[str, Any]:
    """The fixture PDF engine and its reader: no Pango, no optional extra."""
    from integral.send_set import fixture_renderer, fixture_text_reader

    return {"renderer": fixture_renderer, "pdf_reader": fixture_text_reader}


_FIXTURE_ENGINE = _engine()


def delivery_with_send(store: ProfileStore) -> tuple[Any, str, int]:
    """A real delivery: a stored offer with a company (containing `|`) and a title,
    one prepared version, and `stage_send` run over it. Returns master, offer id, version."""
    from integral.approval import PersonalDetails, payload_digest, prepare, read_payload
    from integral.approval import stage_send as stage
    from integral.cv_store import CVMaster, Experience, Skill, write_master
    from integral.offers import connect_manual, save_offer

    master = CVMaster(
        experience=(
            Experience(
                title="Data migration lead",
                organisation="Cintra Logistics",
                start="2021",
                end="2025",
                description="Moved the billing system off the mainframe.",
            ),
        ),
        skills=(Skill(name="PostgreSQL", level="strong"),),
    )
    write_master(store, master)
    offer = connect_manual(_GATE_ADVERT, title=GATE_ROLE, company=GATE_COMPANY)
    save_offer(store, offer)
    version = prepare(
        store,
        master,
        offer_id=offer.id,
        advert=_GATE_ADVERT,
        recipient="hiring team",
        details=PersonalDetails(
            full_name="Gate Fixture",
            email="gate@example.invalid",
            phone="+34 600 111 222",
            postal_address="3 Carrer Nou, 17001 Girona",
            date_of_birth="1815-12-10",
        ),
    ).version
    confirms = payload_digest(read_payload(store, offer.id, version))
    stage(store, master, offer.id, version, confirms=confirms, **_FIXTURE_ENGINE)
    return master, offer.id, version


def _case_generate(store: ProfileStore, offer: str, skip: bool) -> None:
    """Write one version. `skip=True` is the write path that forgets the index."""
    from integral import generated_index as me
    from integral.cv_store import _atomic_write_json
    from integral.generate import next_version

    version = next_version(store, offer)
    where = ("cv", "generated", offer, f"v{version}")
    _atomic_write_json(store, {"offer_id": offer, "version": version}, *where, "manifest.json")
    if not skip:
        me.refresh_index(store)


def _hand_edits_detected(store: ProfileStore) -> tuple[int, int]:
    """Apply each hand edit to a good index; count how many `index_differs` flags.

    Edits: a wrong employer slug, a wrong send path, a phantom version, a phantom
    offer row. Returns (detected, tried)."""
    path = store.path("cv", "generated", INDEX_NAME)
    good = path.read_text(encoding="utf-8")
    rows = [line for line in good.splitlines() if line.startswith("| ") and "`sha256:" in line]
    row = rows[0]
    edits = [
        good.replace("(`acme`)", "(`globex`)"),
        good.replace(row, row.replace(", v2", ", v2, v9", 1)),
        good + row.replace("`sha256:", "`sha256:zzz", 1) + "\n",
        good.replace(row, row[: -len("| - |")] + "| `sha256:aaa/v2/send` |"),
    ]
    detected = 0
    for edited in edits:
        path.write_text(edited, encoding="utf-8")
        detected += index_differs(store) if edited != good else 0
    path.write_text(good, encoding="utf-8")
    return detected, len(edits)


def measure() -> dict[str, Any]:
    """`generated_versions_missing_from_the_index` over constructed trees.

    Every case counts, for one tree, how far `INDEX.md` on disk is from
    `render_index` of that tree (byte for byte), plus the cells a real delivery
    must show. The real write paths (`generate`, `link_employer`, `stage_send`,
    and `stage_send` over an intact folder) must read 0; the constructed
    skipping, hand-kept and hand-edited indexes must be caught, so the count is
    shown able to read above zero."""
    from integral.approval import payload_digest, read_payload
    from integral.approval import stage_send as stage
    from integral.generate import generate, link_employer

    cases: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as scratch:
        base = Path(scratch)

        def fresh(name: str) -> ProfileStore:
            (base / name).mkdir()
            return _fixture_store(base / name)

        store = fresh("real")
        master = _master()
        for offer in ("sha256:aaa", "sha256:bbb"):
            generate(store, master, offer_id=offer, advert="Engineer")
            generate(store, master, offer_id=offer, advert="Engineer")
        cases["real_generate_two_offers_two_versions"] = index_differs(store)

        link_employer(store, "sha256:aaa", "acme")
        text = store.path("cv", "generated", INDEX_NAME).read_text(encoding="utf-8")
        cases["real_link_lists_the_employer_slug"] = index_differs(store) + (
            0 if "`acme`" in text else 1
        )
        detected, tried = _hand_edits_detected(store)
        cases["constructed_hand_edited_index"] = detected

        store = fresh("send")
        delivered, offer_id, version = delivery_with_send(store)
        text = store.path("cv", "generated", INDEX_NAME).read_text(encoding="utf-8")
        wanted = (
            "Acme \\| Co",
            f"| {GATE_ROLE} |",
            f"`{offer_id}/v{version}/send`",
        )
        cases["real_stage_send_shows_employer_role_and_send_path"] = index_differs(store) + sum(
            1 for cell in wanted if cell not in text
        )
        store.path("cv", "generated", INDEX_NAME).write_text("# hand kept\n", encoding="utf-8")
        confirms = payload_digest(read_payload(store, offer_id, version))
        stage(store, delivered, offer_id, version, confirms=confirms, **_FIXTURE_ENGINE)
        cases["real_idempotent_stage_send_repairs_the_index"] = index_differs(store)

        store = fresh("skip")
        _case_generate(store, "sha256:ccc", skip=False)
        _case_generate(store, "sha256:ccc", skip=True)
        cases["constructed_write_skipping_the_index"] = index_differs(store)

        store = fresh("stale")
        _case_generate(store, "sha256:ddd", skip=False)
        store.path("cv", "generated", INDEX_NAME).write_text("# hand kept\n", encoding="utf-8")
        cases["constructed_hand_kept_index"] = index_differs(store)

        store = fresh("deterministic")
        _case_generate(store, "sha256:eee", skip=False)
        first = store.path("cv", "generated", INDEX_NAME).read_bytes()
        refresh_index(store)
        cases["regeneration_is_byte_identical"] = int(
            store.path("cv", "generated", INDEX_NAME).read_bytes() != first
        )

    real = (
        "real_generate_two_offers_two_versions",
        "real_link_lists_the_employer_slug",
        "real_stage_send_shows_employer_role_and_send_path",
        "real_idempotent_stage_send_repairs_the_index",
        "regeneration_is_byte_identical",
    )
    return {
        "generated_versions_missing_from_the_index": sum(cases[k] for k in real),
        "constructed_skipping_write_missing": cases["constructed_write_skipping_the_index"],
        "constructed_hand_kept_index_missing": cases["constructed_hand_kept_index"],
        "constructed_hand_edits_detected": cases["constructed_hand_edited_index"],
        "constructed_hand_edits_tried": tried,
        "cases_measured": len(cases),
        "cases_measured_at_least": MINIMUM_CASES_MEASURED,
        "cases": cases,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def gate_passes(measured: dict[str, Any]) -> bool:
    return bool(
        measured["generated_versions_missing_from_the_index"] == 0
        and measured["constructed_skipping_write_missing"] > 0
        and measured["constructed_hand_kept_index_missing"] > 0
        and measured["constructed_hand_edits_detected"] == measured["constructed_hand_edits_tried"]
        and measured["constructed_hand_edits_tried"] > 0
        and measured["cases_measured"] >= MINIMUM_CASES_MEASURED
    )


def _main(argv: list[str]) -> int:
    measured = write_evidence(Path(argv[1]) if len(argv) > 1 else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))
    return 0 if gate_passes(measured) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv))
