"""T192: a digest of what this candidate's other generated documents already hold.

Step 11 drafts a CV and a letter for one offer. Before this module its only look
backwards was at earlier versions of *that* offer, so framing the candidate had
already polished for another offer was never surfaced and every draft started
from zero. This walks every ``cv/generated/<offer_id>/v<N>/manifest.json`` and
prints one compact entry per offer — who it was for, how many versions exist,
which sections the documents carry beyond the generated standard set, and which
``profile/stories.jsonl`` episodes the manifests cite — so reuse can be
*proposed*, by a script, without the model re-reading N full documents.

It proposes nothing itself and approves nothing. An episode listed as cited was
approved for **that** offer's document only; carrying it into another needs a
fresh per-use approval, whatever the digest says.

Closed rules rather than enumerations, so a case added later is covered without
anyone remembering to list it:

* **Everything under ``cv/generated`` is accounted for.** An entry that is not a
  well-formed ``<offer>/v<N>`` directory holding a manifest that parses, names its
  own offer and version, and sits beside readable document text is reported in
  ``skipped`` by path and reason. Nothing is dropped silently, and any skip makes
  the CLI exit 1 — a digest that read half the candidate's work and said nothing
  would invite a draft that "reuses everything" while missing the best letter.
* **A cited story is a manifest ``episodes`` claim whose text equals a story
  row's text.** That is the join ``generate`` itself makes (the claim *is* the
  rendered episode), so there is no second notion of "cited" to drift. Episode
  claims that match no story are counted and shown, never discarded.
* **A distinguishing section is any heading of level 2 or deeper in a version's
  documents that is not one of ``generate``'s own headings.** Level 1 is the
  document title, not a section; fenced code is not a heading. The standard set is
  read from ``generate._HEADINGS`` rather than copied.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from integral.generate import _HEADINGS, Manifest
from integral.identity import IdentityError, ProfileStore
from integral.offers import OfferError, load_offer
from integral.state_home import StateHomeRefused, ensure_outside_a_work_tree, profiles_root

#: The documents a version can carry. `trazabilidad.md` is the trace of the
#: documents, not a document, and `send/` is a copy of them.
DOCUMENT_FILES = ("cv.md", "letter.md", "carta.md")
STANDARD_SECTIONS = frozenset(_HEADINGS.values())
_VERSION = re.compile(r"v([1-9][0-9]*)")
_HEADING = re.compile(r"^(#{2,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^[ \t]*(```|~~~)")
_SNIPPET = 70


@dataclass(frozen=True)
class Skipped:
    """Something under ``cv/generated`` (or its inputs) the digest could not read."""

    where: str
    reason: str


@dataclass(frozen=True)
class OfferDigest:
    offer_id: str
    company: str | None
    title: str | None
    versions: tuple[int, ...]
    sections: tuple[str, ...]
    cited_stories: tuple[tuple[str, str], ...]  # (story id, text)
    unmatched_episode_claims: tuple[str, ...]


@dataclass(frozen=True)
class Digest:
    offers: tuple[OfferDigest, ...]
    skipped: tuple[Skipped, ...]
    stories_read: int = 0


@dataclass
class _Acc:
    versions: list[int] = field(default_factory=list)
    sections: set[str] = field(default_factory=set)
    episode_texts: set[str] = field(default_factory=set)


def headings(text: str) -> list[str]:
    """Section headings of a Markdown document: level 2+, outside fenced code."""
    found: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        marker = _FENCE.match(line)
        if marker:
            fence = None if fence == marker.group(1) else (fence or marker.group(1))
            continue
        if fence is None and (match := _HEADING.match(line.strip())):
            found.append(match.group(2).strip())
    return found


def _read_stories(store: ProfileStore, skipped: list[Skipped]) -> list[tuple[str, str]]:
    if not store.exists("profile", "stories.jsonl"):
        return []
    try:
        rows = list(store.read_jsonl("profile", "stories.jsonl"))
    except (IdentityError, OSError, ValueError, RecursionError) as exc:
        skipped.append(Skipped("profile/stories.jsonl", f"{type(exc).__name__}: {exc}"))
        return []
    stories: list[tuple[str, str]] = []
    for number, row in enumerate(rows, start=1):
        ident = row.get("id") if isinstance(row, dict) else None
        text = row.get("text") if isinstance(row, dict) else None
        if not (isinstance(ident, str) and ident and isinstance(text, str) and text.strip()):
            skipped.append(
                Skipped(f"profile/stories.jsonl row {number}", "no string `id` and `text`")
            )
            continue
        stories.append((ident, text.strip()))
    return stories


def _read_version(
    store: ProfileStore, offer_id: str, number: int, acc: _Acc, skipped: list[Skipped]
) -> bool:
    """Fold one version into `acc`; report why and return False if it cannot be."""
    where = f"cv/generated/{offer_id}/v{number}"
    try:
        manifest = Manifest.model_validate_json(
            store.read_text("cv", "generated", offer_id, f"v{number}", "manifest.json")
        )
    except (IdentityError, OSError, ValueError, RecursionError) as exc:
        # `ValueError` is `ValidationError` and `UnicodeDecodeError` both.
        skipped.append(Skipped(f"{where}/manifest.json", f"{type(exc).__name__}: {exc}"))
        return False
    if (manifest.offer_id, manifest.version) != (offer_id, number):
        # The directory name must not be able to redirect the digest at a
        # manifest that is about something else.
        skipped.append(
            Skipped(
                f"{where}/manifest.json",
                f"names offer {manifest.offer_id!r} v{manifest.version}, not this directory",
            )
        )
        return False
    sections: set[str] = set()
    read_any = False
    for name in DOCUMENT_FILES:
        if not store.exists("cv", "generated", offer_id, f"v{number}", name):
            continue
        try:
            text = store.read_text("cv", "generated", offer_id, f"v{number}", name)
        except (IdentityError, OSError, ValueError) as exc:
            skipped.append(Skipped(f"{where}/{name}", f"{type(exc).__name__}: {exc}"))
            return False
        read_any = True
        sections.update(h for h in headings(text) if h not in STANDARD_SECTIONS)
    if not read_any:
        skipped.append(Skipped(where, f"none of {', '.join(DOCUMENT_FILES)} is present"))
        return False
    acc.versions.append(number)
    acc.sections |= sections
    acc.episode_texts |= {c.text.strip() for c in manifest.claims if c.section == "episodes"}
    return True


def digest(store: ProfileStore) -> Digest:
    skipped: list[Skipped] = []
    stories = _read_stories(store, skipped)
    root = store.path("cv", "generated")
    by_offer: dict[str, _Acc] = {}
    if root.is_dir():
        for offer_dir in sorted(root.iterdir(), key=lambda p: p.name):
            rel = f"cv/generated/{offer_dir.name}"
            if not offer_dir.is_dir() or offer_dir.is_symlink():
                skipped.append(Skipped(rel, "not an offer directory"))
                continue
            acc = by_offer.setdefault(offer_dir.name, _Acc())
            for version_dir in sorted(offer_dir.iterdir(), key=lambda p: p.name):
                match = _VERSION.fullmatch(version_dir.name)
                if not match or not version_dir.is_dir() or version_dir.is_symlink():
                    skipped.append(Skipped(f"{rel}/{version_dir.name}", "not a v<N> version"))
                    continue
                _read_version(store, offer_dir.name, int(match.group(1)), acc, skipped)

    offers: list[OfferDigest] = []
    for offer_id, acc in by_offer.items():
        company: str | None = None
        title: str | None = None
        if acc.versions:
            try:
                offer = load_offer(store, offer_id)
                company, title = offer.company, offer.title
            except (OfferError, OSError, ValueError, RecursionError) as exc:
                # The documents are still worth showing; the missing name is reported.
                skipped.append(Skipped(f"offers/{offer_id}.json", f"{type(exc).__name__}: {exc}"))
        cited = tuple(sorted((i, t) for i, t in stories if t in acc.episode_texts))
        known = {t for _, t in stories}
        offers.append(
            OfferDigest(
                offer_id=offer_id,
                company=company,
                title=title,
                versions=tuple(sorted(acc.versions)),
                sections=tuple(sorted(acc.sections)),
                cited_stories=cited,
                unmatched_episode_claims=tuple(sorted(acc.episode_texts - known)),
            )
        )
    # An offer whose every version was skipped has no digest to show; it is in
    # `skipped` by name already, so it is not also printed as an empty entry.
    shown = tuple(o for o in offers if o.versions)
    return Digest(shown, tuple(skipped), len(stories))


def _snippet(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _SNIPPET else flat[: _SNIPPET - 1] + "…"


def render(result: Digest) -> str:
    lines: list[str] = []
    if not result.offers and not result.skipped:
        lines.append("no generated documents yet — nothing to reuse")
    for offer in result.offers:
        name = " — ".join(part for part in (offer.company, offer.title) if part) or "(unnamed)"
        last = offer.versions[-1]
        lines.append(f"{offer.offer_id} | {name}")
        lines.append(f"  versions: {len(offer.versions)} (latest v{last})")
        lines.append(f"  sections beyond the standard set: {', '.join(offer.sections) or 'none'}")
        lines.append(f"  stories cited: {len(offer.cited_stories)}")
        lines.extend(f"    {ident}: {_snippet(text)}" for ident, text in offer.cited_stories)
        if offer.unmatched_episode_claims:
            lines.append(
                f"  episode claims matching no story: {len(offer.unmatched_episode_claims)}"
            )
            lines.extend(f"    {_snippet(t)}" for t in offer.unmatched_episode_claims)
    if result.skipped:
        lines.append(f"SKIPPED {len(result.skipped)} — not read, so not in the digest above:")
        lines.extend(f"  {s.where}: {s.reason}" for s in result.skipped)
    return "\n".join(lines)


def as_json(result: Digest) -> dict[str, Any]:
    return {
        "offers": [
            {
                "offer_id": o.offer_id,
                "company": o.company,
                "title": o.title,
                "versions": list(o.versions),
                "sections": list(o.sections),
                "cited_stories": [{"id": i, "text": t} for i, t in o.cited_stories],
                "unmatched_episode_claims": list(o.unmatched_episode_claims),
            }
            for o in result.offers
        ],
        "skipped": [{"where": s.where, "reason": s.reason} for s in result.skipped],
        "stories_read": result.stories_read,
    }


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m integral.prior_documents")
    parser.add_argument("--id", required=True, dest="handle")
    parser.add_argument("--input-dir", default=None)
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        flag = True if args.dev else None
        root = (
            ensure_outside_a_work_tree(args.input_dir, source="--input-dir", dev=flag)
            if args.input_dir
            else profiles_root(dev=flag)
        )
        store = ProfileStore(root, args.handle)
        store.identity()
        result = digest(store)
    except (StateHomeRefused, IdentityError) as exc:
        print(f"prior_documents: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(as_json(result), ensure_ascii=False) if args.as_json else render(result))
    return 1 if result.skipped else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli(sys.argv[1:]))
