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
is a write path that skips the call, so the metric can read above zero.

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
MINIMUM_CASES_MEASURED = 5

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


def versions_on_disk(store: ProfileStore) -> list[tuple[str, int]]:
    root = store.path("cv", "generated")
    found: list[tuple[str, int]] = []
    if root.is_dir():
        for child in sorted(root.iterdir(), key=lambda p: p.name):
            if child.is_dir() and not child.is_symlink():
                found.extend((child.name, n) for n in _versions(child))
    return found


def missing_from_index(store: ProfileStore) -> list[str]:
    """Versions on disk that the committed INDEX.md does not list, as `offer/vN`.

    Reads the file on disk, not `render_index`: a write path that never called
    `refresh_index` leaves the file as it was, and that is the thing measured."""
    path = store.path("cv", "generated", INDEX_NAME)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    listed: dict[str, set[int]] = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[2].startswith("`") and cells[2].endswith("`"):
            listed[cells[2].strip("`")] = {int(n) for n in re.findall(r"\bv(\d+)\b", cells[3])}
    return [
        f"{offer_id}/v{n}"
        for offer_id, n in versions_on_disk(store)
        if n not in listed.get(offer_id, set())
    ]


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


def measure() -> dict[str, Any]:
    """`generated_versions_missing_from_the_index` over constructed trees.

    Five cases. The real write paths (`generate`, `link_employer`, `stage_send`)
    must leave nothing missing; the constructed skipping path must be caught, so
    the count is shown able to read above zero."""
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
        cases["real_generate_two_offers_two_versions"] = len(missing_from_index(store))

        link_employer(store, "sha256:aaa", "acme")
        text = store.path("cv", "generated", INDEX_NAME).read_text(encoding="utf-8")
        cases["real_link_lists_the_employer_slug"] = len(missing_from_index(store)) + (
            0 if "`acme`" in text else 1
        )

        store = fresh("skip")
        _case_generate(store, "sha256:ccc", skip=False)
        _case_generate(store, "sha256:ccc", skip=True)
        cases["constructed_write_skipping_the_index"] = len(missing_from_index(store))

        store = fresh("stale")
        _case_generate(store, "sha256:ddd", skip=False)
        store.path("cv", "generated", INDEX_NAME).write_text("# hand kept\n", encoding="utf-8")
        cases["constructed_hand_kept_index"] = len(missing_from_index(store))

        store = fresh("deterministic")
        _case_generate(store, "sha256:eee", skip=False)
        first = store.path("cv", "generated", INDEX_NAME).read_bytes()
        refresh_index(store)
        cases["regeneration_is_byte_identical"] = int(
            store.path("cv", "generated", INDEX_NAME).read_bytes() != first
        )

    real = ("real_generate_two_offers_two_versions", "real_link_lists_the_employer_slug")
    return {
        "generated_versions_missing_from_the_index": sum(cases[k] for k in real)
        + cases["regeneration_is_byte_identical"],
        "constructed_skipping_write_missing": cases["constructed_write_skipping_the_index"],
        "constructed_hand_kept_index_missing": cases["constructed_hand_kept_index"],
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
        and measured["cases_measured"] >= MINIMUM_CASES_MEASURED
    )


def _main(argv: list[str]) -> int:
    measured = write_evidence(Path(argv[1]) if len(argv) > 1 else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))
    return 0 if gate_passes(measured) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv))
