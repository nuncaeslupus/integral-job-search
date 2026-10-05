"""T240: every application a candidate has sent, as one page they can regenerate.

A candidate asked for the whole list of what they had sent, then for a fuller
one: what each advert asked for, what they hold, what they lack. Until now a
session answered with a scratch script and a hand-typed notes file. This module
is that page, built from records the package already writes.

**Where each column comes from.** Nothing here is typed per candidate.

* *Sent* is the earliest ``sent_at`` of ``applications/<offer>/v<N>.json`` (the
  record ``approval.record_sent`` writes). An application recorded only by
  ``applications/<offer>/status.json`` carries ``recorded_at``, the day it was
  *noted*, and the board labels it that way rather than showing it as a send date.
  A status-only ``drafted`` is not a sent application and is counted, not shown.
* *Status* is ``status.json``'s; *status at source* and *last seen* come from the
  stored offer (``expired`` / ``fetched_at``). A field the record does not hold
  reads ``not recorded``, never a guess.
* *Asked* is the extraction's skills the advert **requires**. *Holds* is a skill
  a generated document of that application carries (the generation manifest's
  claims). *Lacks* is only a level the candidate themselves stated as ``none``.
  Everything else, including every skill the manifest lists as a gap, is **not on
  record**: the profile being silent is not the candidate being unable, and the
  board never says "lacks" for it.

**Tracking links.** ``sent.json`` and the other application records are immutable,
so a link learned later is appended to ``tracking/links.jsonl`` (newest row per
offer wins). It sits beside ``applications/``, not inside it, and the board is
written to ``reports/applications.html``; ``revision._CLASSES`` places both.

Only ``http`` and ``https`` addresses become links. The page is built by
``report_style.page`` and written by ``report_style.write_report``.

    python -m integral.applications_board --id <handle> [--input-dir <profiles-root>]
    python -m integral.applications_board --id <handle> --track <offer_id> <url>
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from integral import report_style
from integral.identity import IdentityError, ProfileStore, default_profiles_root

BOARD_PARTS = ("reports", "applications.html")
TRACKING_PARTS = ("tracking", "links.jsonl")

NOT_RECORDED = "not recorded"
_WEB_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_VERSION_RECORD = re.compile(r"v(\d+)\.json")

SENT = "sent"
NOTED = "noted"

#: What the board says about the date it shows, so the two are never mistaken.
DATE_LABELS = {SENT: "Sent", NOTED: "Noted (not the send date)"}

HOLDS, LACKS, UNRECORDED = "holds", "lacks", "not on record"


class BoardError(Exception):
    """A tracking link was refused, or an application could not be found."""


@dataclass(frozen=True)
class Fit:
    """The advert's required skills, each in exactly one of three places."""

    read: bool
    asked: tuple[str, ...] = ()
    holds: tuple[str, ...] = ()
    lacks: tuple[str, ...] = ()
    not_on_record: tuple[str, ...] = ()


@dataclass(frozen=True)
class Row:
    offer_id: str
    employer: str
    role: str
    date: str
    date_kind: str
    status: str
    source_status: str
    last_seen: str
    advert_url: str
    tracking_url: str
    fit: Fit
    notes: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class Board:
    rows: tuple[Row, ...]
    #: Application folders that are not on the board, by reason (a `drafted` status).
    left_out: dict[str, str]


# ---------------------------------------------------------------------------
# reading


def _json(store: ProfileStore, *parts: str) -> Any | None:
    """A record's JSON, or ``None`` when it is absent or unreadable.

    An unreadable record is reported by the caller as a note on its row; it never
    removes the application from the board.
    """
    path = store.path(*parts)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _day(stamp: object) -> str:
    text = stamp if isinstance(stamp, str) else ""
    return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else (text or NOT_RECORDED)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else NOT_RECORDED


def tracking_links(store: ProfileStore) -> dict[str, str]:
    """The newest reported tracking link per offer; a malformed row is skipped."""
    found: dict[str, str] = {}
    path = store.path(*TRACKING_PARTS)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return found
    for line in lines:
        try:
            row = json.loads(line)
            offer_id, url = row["offer_id"], row["url"]
        except (ValueError, KeyError, TypeError):
            continue
        if isinstance(offer_id, str) and isinstance(url, str):
            found[offer_id] = url
    return found


def _sent_at(directory: Path) -> tuple[str, bool]:
    """The earliest ``sent_at`` among this offer's send records, and whether any is unreadable."""
    stamps: list[str] = []
    broken = False
    # `sent.json` is the older single-record spelling some candidates' trees hold.
    for record in [*sorted(directory.glob("v*.json")), directory / "sent.json"]:
        if record.name != "sent.json" and not _VERSION_RECORD.fullmatch(record.name):
            continue
        if record.name == "sent.json" and not record.exists():
            continue
        try:
            stamp = json.loads(record.read_text(encoding="utf-8"))["sent_at"]
        except (OSError, ValueError, KeyError, TypeError):
            broken = True
            continue
        if isinstance(stamp, str):
            stamps.append(stamp)
        else:
            broken = True
    return (min(stamps) if stamps else ""), broken


def _held_levels(store: ProfileStore) -> dict[str, str | None]:
    """Technology id -> the level the candidate holds, from the one reading stack_fit makes."""
    from integral import stack_fit
    from integral.approval import retracted_episode_texts
    from integral.cv_store import load_master
    from integral.profile import EvidenceLog

    try:
        log = EvidenceLog(store)
        master = load_master(store)
        held = stack_fit.candidate_stack(
            master,
            log.effective_rows(),
            log.suppressed_ids() if log.exists() else frozenset(),
            retracted_episode_texts(store, master),
        )
    except Exception:  # an unreadable profile is "not on record", never a crash of the board
        return {}
    return {technology: entry.level for technology, entry in held.items()}


def _latest_manifest(store: ProfileStore, offer_id: str) -> tuple[tuple[str, ...], str] | None:
    """(gaps, claims text) of this offer's highest generation version, if one reads."""
    base = store.path("cv", "generated", offer_id)
    versions = sorted(
        (int(p.name[1:]), p) for p in base.glob("v*") if re.fullmatch(r"v\d+", p.name)
    )
    for _, directory in reversed(versions):
        try:
            data = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            gaps = tuple(str(g) for g in data.get("gaps", ()))
            claims = "\n".join(str(c["text"]) for c in data.get("claims", ()))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        return gaps, claims
    return None


def _required_skills(store: ProfileStore, offer_id: str) -> tuple[str, ...] | None:
    """Skills the advert requires, or ``None`` when no extraction has read it for skills."""
    data = _json(store, "extractions", f"{offer_id}.json")
    if not isinstance(data, dict) or not isinstance(data.get("skills"), list):
        return None
    names: list[str] = []
    for reading in data["skills"]:
        if (
            isinstance(reading, dict)
            and reading.get("role") == "required"
            and isinstance(reading.get("skill"), str)
            and reading["skill"].strip()
            and reading["skill"].strip() not in names
        ):
            names.append(reading["skill"].strip())
    return tuple(names)


def _mentions(haystack: str, needle: str) -> bool:
    from integral.generate import _mentions as mentions

    return bool(needle) and mentions(haystack, needle)


def classify_skill(
    skill: str,
    *,
    gaps: tuple[str, ...],
    claims: str | None,
    levels: dict[str, str | None],
) -> str:
    """One required skill: ``holds``, ``lacks`` or ``not on record``.

    ``lacks`` needs the candidate to have said ``none``. A manifest gap, no
    manifest, and a manifest that simply does not carry the skill are all
    ``not on record``: the generation looked and the profile was silent.
    """
    from integral import stack_fit

    if any(levels.get(t) == "none" for t in stack_fit.named(skill, label=True)):
        return LACKS
    if any(_mentions(gap, skill) or _mentions(skill, gap) for gap in gaps):
        return UNRECORDED
    if claims is not None and _mentions(claims, skill):
        return HOLDS
    return UNRECORDED


def fit_for(store: ProfileStore, offer_id: str, levels: dict[str, str | None]) -> Fit:
    asked = _required_skills(store, offer_id)
    if asked is None:
        return Fit(read=False)
    manifest = _latest_manifest(store, offer_id)
    gaps, claims = manifest if manifest else ((), None)
    buckets: dict[str, list[str]] = {HOLDS: [], LACKS: [], UNRECORDED: []}
    for skill in asked:
        buckets[classify_skill(skill, gaps=gaps, claims=claims, levels=levels)].append(skill)
    return Fit(
        read=True,
        asked=asked,
        holds=tuple(buckets[HOLDS]),
        lacks=tuple(buckets[LACKS]),
        not_on_record=tuple(buckets[UNRECORDED]),
    )


def collect(store: ProfileStore) -> Board:
    """Every application folder, as a row, unless it was only ever drafted.

    An application whose offer, status or send record cannot be read is still a
    row, with the gap named in ``notes``: dropping it would hide a send.
    """
    root = store.path("applications")
    links = tracking_links(store)
    levels = _held_levels(store)
    rows: list[Row] = []
    left_out: dict[str, str] = {}
    directories = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    for directory in directories:
        offer_id = directory.name
        notes: list[str] = []
        sent, broken = _sent_at(directory)
        if broken:
            notes.append("a send record could not be read")
        status_record = _json(store, "applications", offer_id, "status.json")
        status = NOT_RECORDED
        noted = ""
        if isinstance(status_record, dict):
            status = _text(status_record.get("status")).replace("_", " ")
            noted = _text(status_record.get("recorded_at"))
        elif store.path("applications", offer_id, "status.json").exists():
            notes.append("status.json could not be read")
        if not sent and status == "drafted":
            left_out[offer_id] = "only drafted, never sent"
            continue
        if sent:
            date, kind = _day(sent), SENT
        else:
            date, kind = _day(noted if noted != NOT_RECORDED else ""), NOTED
        offer = _json(store, "offers", f"{offer_id}.json")
        offer = offer if isinstance(offer, dict) else {}
        if not offer:
            notes.append("the stored offer is missing, so employer and role are not recorded")
        rows.append(
            Row(
                offer_id=offer_id,
                employer=_text(offer.get("company")),
                role=_text(offer.get("title")),
                date=date,
                date_kind=kind,
                status=status,
                source_status="expired" if offer.get("status") == "expired" else NOT_RECORDED,
                last_seen=_day(offer.get("fetched_at")),
                advert_url=_text(offer.get("url")),
                tracking_url=links.get(offer_id, NOT_RECORDED),
                fit=fit_for(store, offer_id, levels),
                notes=tuple(notes),
            )
        )
    rows.sort(key=lambda r: (r.date == NOT_RECORDED, r.date))
    return Board(rows=tuple(rows), left_out=left_out)


# ---------------------------------------------------------------------------
# writing a tracking link


def record_tracking(store: ProfileStore, offer_id: str, url: str, *, reported_at: str) -> Path:
    """Append a tracking link the candidate reported for an application they sent."""
    if not _WEB_URL.fullmatch(url.strip()):
        raise BoardError(f"{url!r} is not an http or https address")
    if not store.path("applications", offer_id).is_dir():
        raise BoardError(f"{offer_id!r} has no application on record, so nothing to track")
    row = {"offer_id": offer_id, "url": url.strip(), "reported_at": reported_at}
    return store.append_jsonl(row, *TRACKING_PARTS)


# ---------------------------------------------------------------------------
# the page

_TONES = {"hired": "positive", "offer": "positive", "interview": "accent"}
_NEGATIVE = frozenset({"rejected", "withdrawn", "offer declined", "no response"})


def _names(items: tuple[str, ...], empty: str) -> str:
    return ", ".join(items) if items else empty


def _fit_facts(fit: Fit) -> str:
    if not fit.read:
        return (
            '<p class="muted">What the advert asked for has not been read from it yet, '
            "so there is nothing to compare.</p>"
        )
    return report_style.facts(
        [
            ("Asked", _names(fit.asked, "no required skill named")),
            ("Holds", _names(fit.holds, "none")),
            ("Lacks (the candidate said so)", _names(fit.lacks, "none")),
            ("Not on record", _names(fit.not_on_record, "none")),
        ]
    )


def _card(row: Row) -> str:
    tone = "negative" if row.status in _NEGATIVE else _TONES.get(row.status, "neutral")
    shown = report_style.Markup(report_style.chip(row.status, tone))
    details = report_style.facts(
        [
            (DATE_LABELS[row.date_kind], row.date),
            ("Status", shown),
            ("Status at source", row.source_status),
            ("Last seen", row.last_seen),
            ("Advert", report_style.link(row.advert_url)),
            ("Tracking", report_style.link(row.tracking_url)),
        ]
    )
    notes = "".join(f'<p class="muted">{html.escape(n)}</p>' for n in row.notes)
    return report_style.card(f"{row.employer} — {row.role}", details + _fit_facts(row.fit) + notes)


def render(board: Board, *, generated_at: str) -> str:
    counts = Counter(row.status for row in board.rows)
    summary = report_style.tiles(
        [("Applications", len(board.rows))] + [(status, n) for status, n in sorted(counts.items())]
    )
    cards = "\n".join(_card(row) for row in board.rows)
    if not board.rows:
        cards = '<p class="muted">No application has been sent or recorded yet.</p>'
    left = ""
    if board.left_out:
        left = (
            f'<p class="muted">{len(board.left_out)} drafted application(s) not shown: '
            "never sent.</p>"
        )
    stamp = f'<p class="muted">Generated {html.escape(generated_at)}.</p>'
    body = f"<main>\n<h1>Applications</h1>\n{stamp}\n{summary}\n{cards}\n{left}\n</main>"
    return report_style.page("Applications", body)


def write_board(store: ProfileStore, *, now: datetime | None = None) -> Path:
    moment = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    return report_style.write_report(
        store, render(collect(store), generated_at=moment), *BOARD_PARTS
    )


# ---------------------------------------------------------------------------
# the command


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="integral.applications_board")
    parser.add_argument("--id", required=True, help="the candidate's handle")
    parser.add_argument("--input-dir", type=Path, help="the profiles root")
    parser.add_argument(
        "--track", nargs=2, metavar=("OFFER_ID", "URL"), help="record a tracking link, then render"
    )
    args = parser.parse_args(argv)
    store = ProfileStore(args.input_dir or default_profiles_root(), args.id)
    try:
        if args.track:
            offer_id, url = args.track
            record_tracking(
                store, offer_id, url, reported_at=datetime.now(UTC).isoformat(timespec="seconds")
            )
        path = write_board(store)
    except (BoardError, IdentityError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
