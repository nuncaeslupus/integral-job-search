"""T192: a digest of what this candidate's other generated documents already hold.

Step 11 drafts a CV and a letter for one offer. Before this module its only look
backwards was at earlier versions of *that* offer, so framing the candidate had
already polished for another offer was never surfaced and every draft started
from zero. This walks every ``cv/generated/<offer_id>/v<N>/manifest.json`` and
prints one compact entry per offer — who it was for, how many versions exist,
which documents each version holds, which sections they carry beyond the
generated standard set, and which story-bank episodes they disclosed — so reuse
can be *proposed*, by a script, without the model re-reading N full documents.

It proposes nothing itself and approves nothing. An episode listed as cited was
approved for **that** offer's document only; carrying it into another needs a
fresh per-use approval, whatever the digest says.

Closed rules rather than enumerations, so a case added later is covered without
anyone remembering to list it:

* **Everything under ``cv/generated`` is accounted for.** An entry that is not a
  well-formed ``<offer>/v<N>`` directory holding a manifest that parses, names its
  own offer and version, and sits beside readable document text is reported in
  ``skipped`` by path and reason — as is an empty offer directory or a regular file
  where ``cv/generated`` should be. Nothing is dropped silently, and any skip makes
  the CLI exit 1.
* **A version's documents are every ``*.md`` in it except the trace file**
  (``application_authorship.TRACE_FILE``). ``approval.prepare`` globs ``*.md`` and so
  includes the trace file; the digest uses that glob minus the trace, not a list of
  names. The digest names the documents, so a letter's framing is discoverable even
  though it has no headings, and names every other regular file that is neither a
  ``*.md`` nor a ``*.json`` (``carta.txt``, ``cv.MD``, rendered HTML) as *not read*,
  so nothing sits in a version unmentioned.
* **A cited episode is any manifest claim with ``section == "episodes"`` and any
  text in the version's ``approvals.json``.** A manifest claim is rendered from
  ``cv/master.json``, not from ``profile/stories.jsonl``, and no code makes the two
  texts equal, so a story row is only an *annotation* (its id, when it resolves);
  it is never the condition for listing. Each is a story-bank episode that needs a
  fresh approval for the new posting.
* **Undetermined is not zero.** A document line the manifest does not trace (a
  hand-written ``carta.md``) may carry an episode nothing records, so such a version
  reports its episodes as undetermined, naming the files.
* **A distinguishing section is a heading of level 2 or deeper in a version's
  documents that is not one of ``generate``'s own headings.** Fenced code is not a
  heading. This is a proxy for "framing worth a look" and is only a pointer: read the
  named documents.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from integral.application_authorship import TRACE_FILE
from integral.approval import Approvals, _normalised_equal
from integral.generate import _HEADINGS, Manifest, _claim_lines
from integral.identity import IdentityError, ProfileLeak, ProfileStore
from integral.offers import OfferError, load_offer
from integral.state_home import StateHomeRefused, ensure_outside_a_work_tree, profiles_root

STANDARD_SECTIONS = frozenset(_HEADINGS.values())
_VERSION = re.compile(r"v([1-9][0-9]*)")
_HEADING = re.compile(r"^(#{2,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^[ \t]*(```|~~~)")
_SNIPPET = 70
# What a read can raise. `ValueError` is `ValidationError` and `UnicodeDecodeError` both;
# `ProfileLeak` is a symlink out of the tree, which must be reported, not crash the digest.
_READ_ERRORS = (IdentityError, ProfileLeak, OSError, ValueError, RecursionError)


@dataclass(frozen=True)
class Skipped:
    """Something under ``cv/generated`` (or its inputs) the digest could not read."""

    where: str
    reason: str


@dataclass(frozen=True)
class CitedEpisode:
    """A story-bank episode a document disclosed. `story_id` is only an annotation."""

    text: str
    story_id: str | None


@dataclass(frozen=True)
class OfferDigest:
    offer_id: str
    company: str | None
    title: str | None
    versions: tuple[int, ...]
    documents: tuple[tuple[int, tuple[str, ...]], ...]
    unread_files: tuple[tuple[int, tuple[str, ...]], ...]
    sections: tuple[str, ...]
    cited_episodes: tuple[CitedEpisode, ...]
    undetermined: tuple[str, ...]  # documents carrying lines no manifest claim traces


@dataclass(frozen=True)
class Digest:
    offers: tuple[OfferDigest, ...]
    skipped: tuple[Skipped, ...]
    stories_read: int = 0


@dataclass
class _Acc:
    versions: list[int] = field(default_factory=list)
    documents: dict[int, tuple[str, ...]] = field(default_factory=dict)
    unread_files: dict[int, tuple[str, ...]] = field(default_factory=dict)
    sections: set[str] = field(default_factory=set)
    episode_texts: set[str] = field(default_factory=set)
    undetermined: set[str] = field(default_factory=set)


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
    try:
        if not store.exists("profile", "stories.jsonl"):
            return []
        rows = list(store.read_jsonl("profile", "stories.jsonl"))
    except _READ_ERRORS as exc:
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
) -> None:
    """Fold one version into `acc`, or report why it cannot be."""
    where = f"cv/generated/{offer_id}/v{number}"
    parts = ("cv", "generated", offer_id, f"v{number}")
    try:
        manifest = Manifest.model_validate_json(store.read_text(*parts, "manifest.json"))
    except _READ_ERRORS as exc:
        skipped.append(Skipped(f"{where}/manifest.json", f"{type(exc).__name__}: {exc}"))
        return
    if (manifest.offer_id, manifest.version) != (offer_id, number):
        # The directory name must not be able to redirect the digest at a
        # manifest that is about something else.
        skipped.append(
            Skipped(
                f"{where}/manifest.json",
                f"names offer {manifest.offer_id!r} v{manifest.version}, not this directory",
            )
        )
        return
    approved: list[str] = []
    try:
        if store.exists(*parts, "approvals.json"):
            approvals = Approvals.model_validate_json(store.read_text(*parts, "approvals.json"))
            if (approvals.offer_id, approvals.version) != (offer_id, number):
                raise ValueError(f"names offer {approvals.offer_id!r} v{approvals.version}")
            approved = [a.text for a in approvals.episodes]
        names = sorted(p.name for p in store.path(*parts).glob("*.md") if p.name != TRACE_FILE)
        unread = sorted(
            p.name
            for p in store.path(*parts).iterdir()
            if p.is_file() and not p.name.endswith(".md") and p.suffix.lower() != ".json"
        )
        texts = {name: store.read_text(*parts, name) for name in names}
    except _READ_ERRORS as exc:
        skipped.append(Skipped(where, f"{type(exc).__name__}: {exc}"))
        return
    if not names:
        skipped.append(Skipped(where, "no document (*.md other than the trace file) is present"))
        return
    for name, text in texts.items():
        traced = {c.text.strip() for c in manifest.claims if c.document == name}
        if any(line not in traced for line in _claim_lines(text)):
            acc.undetermined.add(f"{where}/{name}")
        acc.sections.update(h for h in headings(text) if h not in STANDARD_SECTIONS)
    acc.versions.append(number)
    acc.documents[number] = tuple(names)
    if unread:
        acc.unread_files[number] = tuple(unread)
    acc.episode_texts |= {c.text.strip() for c in manifest.claims if c.section == "episodes"}
    acc.episode_texts |= {t.strip() for t in approved}


def digest(store: ProfileStore) -> Digest:
    skipped: list[Skipped] = []
    stories = _read_stories(store, skipped)
    by_offer: dict[str, _Acc] = {}
    entries: list[Any] = []
    try:
        root = store.path("cv", "generated")
        if root.is_dir():
            entries = sorted(root.iterdir(), key=lambda p: p.name)
        elif root.exists():
            skipped.append(Skipped("cv/generated", "not a directory"))
    except _READ_ERRORS as exc:
        skipped.append(Skipped("cv/generated", f"{type(exc).__name__}: {exc}"))
    for offer_dir in entries:
        rel = f"cv/generated/{offer_dir.name}"
        if not offer_dir.is_dir() or offer_dir.is_symlink():
            skipped.append(Skipped(rel, "not an offer directory"))
            continue
        acc = by_offer.setdefault(offer_dir.name, _Acc())
        children = sorted(offer_dir.iterdir(), key=lambda p: p.name)
        if not children:
            skipped.append(Skipped(rel, "empty offer directory"))
        for version_dir in children:
            match = _VERSION.fullmatch(version_dir.name)
            if not match or not version_dir.is_dir() or version_dir.is_symlink():
                skipped.append(Skipped(f"{rel}/{version_dir.name}", "not a v<N> version"))
                continue
            _read_version(store, offer_dir.name, int(match.group(1)), acc, skipped)

    offers: list[OfferDigest] = []
    for offer_id, acc in by_offer.items():
        if not acc.versions:
            # Every version was skipped (or none existed); each is in `skipped` by name.
            continue
        company: str | None = None
        title: str | None = None
        try:
            offer = load_offer(store, offer_id)
            company, title = offer.company, offer.title
        except (OfferError, *_READ_ERRORS) as exc:
            # The documents are still worth showing; the missing name is reported.
            skipped.append(Skipped(f"offers/{offer_id}.json", f"{type(exc).__name__}: {exc}"))
        cited = tuple(
            CitedEpisode(text, next((i for i, t in stories if _normalised_equal(t, text)), None))
            for text in sorted(acc.episode_texts)
        )
        offers.append(
            OfferDigest(
                offer_id=offer_id,
                company=company,
                title=title,
                versions=tuple(sorted(acc.versions)),
                documents=tuple(sorted(acc.documents.items())),
                unread_files=tuple(sorted(acc.unread_files.items())),
                sections=tuple(sorted(acc.sections)),
                cited_episodes=cited,
                undetermined=tuple(sorted(acc.undetermined)),
            )
        )
    return Digest(tuple(offers), tuple(skipped), len(stories))


def _snippet(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _SNIPPET else flat[: _SNIPPET - 1] + "…"


def render(result: Digest) -> str:
    lines: list[str] = []
    if not result.offers and not result.skipped:
        lines.append("no generated documents yet — nothing to reuse")
    for offer in result.offers:
        name = " — ".join(part for part in (offer.company, offer.title) if part) or "(unnamed)"
        lines.append(f"{offer.offer_id} | {name}")
        lines.append(f"  versions: {len(offer.versions)} (latest v{offer.versions[-1]})")
        lines.extend(f"    v{n}: {', '.join(names)}" for n, names in offer.documents)
        lines.extend(
            f"    v{n} also holds, not read: {', '.join(names)}" for n, names in offer.unread_files
        )
        lines.append(f"  sections beyond the standard set: {', '.join(offer.sections) or 'none'}")
        count = len(offer.cited_episodes)
        if offer.undetermined:
            lines.append(
                f"  story-bank episodes cited: {count} listed, UNDETERMINED — these documents "
                "carry lines no manifest claim traces, so more may be in them:"
            )
            lines.extend(f"    {where}" for where in offer.undetermined)
        else:
            lines.append(f"  story-bank episodes cited: {count}")
        for episode in offer.cited_episodes:
            tag = f"[{episode.story_id}] " if episode.story_id else ""
            lines.append(f"    {tag}{_snippet(episode.text)}")
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
                "documents": {f"v{n}": list(names) for n, names in o.documents},
                "unread_files": {f"v{n}": list(names) for n, names in o.unread_files},
                "sections": list(o.sections),
                "cited_episodes": [
                    {"text": e.text, "story_id": e.story_id} for e in o.cited_episodes
                ],
                "undetermined": list(o.undetermined),
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
