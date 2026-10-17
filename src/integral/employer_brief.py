"""T344 — an offer reaches the candidate's decision with a brief on its real employer.

Two failures met on 2026-10-16: an aggregator re-posting an advert under its own
name, and a posting closed at the source while aggregators still showed it. The
session does the browsing (gated on `integral.robots.Robots().allows(url)`); this
module only records what it found and reads the record back. No network code.

A brief is `offers/briefs/<offer_id>.json`. "Presented to the candidate" is not
re-recorded: it is `presentations.jsonl`'s `offer_ids` (`presentation_log.present`).

An offer counts as briefed when its brief is complete, was checked against every
exclusion the candidate has stated *now* (a topic ruled out after the brief was
written makes it stale), and is not known to be closed at the source unless the
offer is also marked `expired` in its lifecycle record.

    uv run python -m integral.employer_brief record --id H --offer O --employer … …
    uv run python -m integral.employer_brief show --id H --offer O
    uv run python -m integral.employer_brief missing --id H
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, get_args

from pydantic import ValidationError, field_validator

from integral.identity import IdentityError, ProfileStore, default_profiles_root
from integral.lifecycle import load_lifecycle_offer
from integral.offers import Strict, load_offer
from integral.presentation_log import PRESENTATIONS
from integral.sourcing_exclusions import Candidate, load_exclusions, ruled_out_by

Tri = Literal["true", "false", "unknown"]
ResolvedVia = Literal["apply_link", "advert_wording", "same_as_listed"]


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _parts(offer_id: str) -> tuple[str, str, str]:
    return ("offers", "briefs", f"{offer_id}.json")


class EmployerBrief(Strict):
    offer_id: str
    real_employer: str
    resolved_via: ResolvedVia
    source_posting_url: str | None = None
    live_at_source: Tri
    checked_at: str
    what_they_do: str
    sector: str
    #: Every exclusion `about` compared, and the ones the real employer tripped.
    exclusions_compared: tuple[str, ...]
    exclusions_tripped: tuple[str, ...] = ()
    #: "<value or estimate> — <source>", or "not published".
    pay: str
    hires_in_candidate_country: Tri

    @field_validator("real_employer", "what_they_do", "sector", "pay", "checked_at")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("blank")
        return value

    @field_validator("checked_at")
    @classmethod
    def _iso(cls, value: str) -> str:
        if _when(value) is None:
            raise ValueError("checked_at is not ISO-8601")
        return value


def load_brief(store: ProfileStore, offer_id: str) -> EmployerBrief | None:
    """The brief, or `None` when absent or unreadable (an unreadable brief is no brief)."""
    try:
        return EmployerBrief.model_validate(store.read_json(*_parts(offer_id)))
    except (IdentityError, ValidationError, OSError, ValueError):
        return None


def record_brief(
    store: ProfileStore,
    offer_id: str,
    *,
    real_employer: str,
    resolved_via: ResolvedVia,
    live_at_source: Tri,
    checked_at: str,
    what_they_do: str,
    sector: str,
    pay: str,
    hires_in_candidate_country: Tri,
    source_posting_url: str | None = None,
) -> EmployerBrief:
    """Write the brief; the exclusion comparison is computed here, never typed."""
    offer = load_offer(store, offer_id)
    exclusions = load_exclusions(store)
    # The brief's own words are a region of their own: appended to the advert they would
    # land inside its last section, which `topic_text` strips (T227).
    advert = Candidate(
        offer_id=offer_id, title=offer.title, text=offer.text, employer=real_employer
    )
    said = Candidate(offer_id=offer_id, text=f"{what_they_do}\n{sector}", employer=real_employer)
    tripped = dict.fromkeys((*ruled_out_by(advert, exclusions), *ruled_out_by(said, exclusions)))
    brief = EmployerBrief(
        offer_id=offer_id,
        real_employer=real_employer,
        resolved_via=resolved_via,
        source_posting_url=source_posting_url,
        live_at_source=live_at_source,
        checked_at=checked_at,
        what_they_do=what_they_do,
        sector=sector,
        exclusions_compared=tuple(e.about for e in exclusions),
        exclusions_tripped=tuple(tripped),
        pay=pay,
        hires_in_candidate_country=hires_in_candidate_country,
    )
    store.write_json(brief.model_dump(mode="json"), *_parts(offer_id))
    return brief


def _expired(store: ProfileStore, offer_id: str) -> bool:
    try:
        return load_lifecycle_offer(store, offer_id)[1].current_status == "expired"
    except Exception:
        return False


def is_briefed(
    store: ProfileStore, offer_id: str, stated: frozenset[str], first_shown: datetime | None
) -> bool:
    """Complete, current, clean, and written before the offer was first shown."""
    brief = load_brief(store, offer_id)
    if brief is None or not stated <= set(brief.exclusions_compared):
        return False
    if brief.exclusions_tripped or brief.hires_in_candidate_country == "false":
        return False
    checked = _when(brief.checked_at)
    if checked is None or first_shown is None or checked > first_shown:
        return False
    if brief.live_at_source == "false":
        return _expired(store, offer_id)
    # Open or unknown without the employer's own posting is "not checked".
    return bool(brief.source_posting_url and brief.source_posting_url.strip())


def presented_without_brief(store: ProfileStore) -> list[str]:
    """`offers_presented_for_decision_without_an_employer_brief`, as the offer ids.

    A presentations row that cannot be read is listed by name, never skipped silently.
    """
    stated = frozenset(e.about for e in load_exclusions(store))
    first: dict[str, datetime | None] = {}
    bad: list[str] = []
    if store.exists(*PRESENTATIONS):
        for n, line in enumerate(store.read_text(*PRESENTATIONS).splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                row = None
            ids = row.get("offer_ids") if isinstance(row, dict) else None
            if not isinstance(ids, list):
                bad.append(f"presentations.jsonl line {n}: unreadable row")
                continue
            at = _when(row.get("at"))
            for i in map(str, ids):
                old = first.get(i, at)
                first[i] = None if at is None or old is None else min(at, old)
    return bad + [i for i in sorted(first) if not is_briefed(store, i, stated, first[i])]


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="integral.employer_brief")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("record", "show", "missing"):
        p = sub.add_parser(name)
        p.add_argument("--id", required=True, help="the candidate's handle")
        p.add_argument("--root", type=Path, default=None)
        if name != "missing":
            p.add_argument("--offer", required=True)
        if name == "record":
            p.add_argument("--employer", required=True)
            p.add_argument("--resolved-via", required=True, choices=get_args(ResolvedVia))
            p.add_argument("--live", required=True, choices=get_args(Tri))
            p.add_argument("--checked-at", required=True)
            p.add_argument("--what", required=True)
            p.add_argument("--sector", required=True)
            p.add_argument("--pay", required=True)
            p.add_argument("--hires", required=True, choices=get_args(Tri))
            p.add_argument("--source-url", default=None)
    args = parser.parse_args(argv)
    store = ProfileStore(args.root or default_profiles_root(), args.id)
    if args.cmd == "missing":
        gaps = presented_without_brief(store)
        print(json.dumps({"offers_presented_for_decision_without_an_employer_brief": gaps}))
        return 1 if gaps else 0
    if args.cmd == "show":
        brief = load_brief(store, args.offer)
        print(brief.model_dump_json(indent=2) if brief else "no brief")
        return 0 if brief else 1
    done = record_brief(
        store,
        args.offer,
        real_employer=args.employer,
        resolved_via=args.resolved_via,
        live_at_source=args.live,
        checked_at=args.checked_at,
        what_they_do=args.what,
        sector=args.sector,
        pay=args.pay,
        hires_in_candidate_country=args.hires,
        source_posting_url=args.source_url,
    )
    print(done.model_dump_json())
    return 1 if done.exclusions_tripped else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
