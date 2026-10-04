"""T226 — a list shown with no `present()` row, a reaction heard with no `rule_out`.

Steps 9 and 10 state both calls in prose only, so skipping one is silent: on
2026-10-01 a candidate was shown ranked offers and gave reasons for discarding
several, `search/presentations.jsonl` had no row for the day, no `rule_out` was
recorded, and the next day the same offers were shown again. Nothing noticed
because nothing read the two records against each other.

Two checks, each comparing one record with the record that must accompany it:

* `unpresented_ranking` — the latest `rankings/<run_id>.json` names offers, and
  no `presentations.jsonl` row at or after that run shows any of them.
* `unrecorded_discards` — an `offer_reaction` evidence row (the candidate's
  words about one offer) that no lifecycle history event carries as its reason.
  It is `feedback.orphaned_reasons` read the other way round: that finds a
  reason that stopped at the offer's history, this finds words that reached the
  evidence log without any decision ever being made on the offer.

Both fail closed: an unreadable timestamp or ranking file is reported as a gap,
never read as "nothing to check".
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from integral.feedback import _lifecycle_records
from integral.identity import ProfileStore
from integral.presentation_log import _rows
from integral.profile import EvidenceLog


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _latest_ranking(store: ProfileStore) -> tuple[str, dict[str, Any] | None] | None:
    directory = store.path("rankings")
    if not directory.is_dir():
        return None
    best: tuple[datetime, str, dict[str, Any] | None] | None = None
    floor = datetime.min.replace(tzinfo=UTC)
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        run_id = data.get("run_id") if isinstance(data, dict) else None
        when = _when(run_id) or floor
        entry = (when, path.name, data if isinstance(data, dict) else None)
        if best is None or entry[:2] > best[:2]:
            best = entry
    return None if best is None else (best[1], best[2])


def unpresented_ranking(store: ProfileStore) -> list[dict[str, Any]]:
    """The latest ranking, when no presentation row at or after it shows its offers.

    Empty means no gap. A ranking naming no offers has nothing to show; one that
    cannot be read, or whose run time cannot be, is reported (fail closed).
    """
    latest = _latest_ranking(store)
    if latest is None:
        return []
    name, data = latest
    if data is None or not isinstance(data.get("pareto"), list):
        return [{"ranking": name, "problem": "unreadable"}]
    offers = {str(i) for i in data["pareto"]}
    if not offers:
        return []
    ran = _when(data.get("run_id"))
    if ran is not None:
        for row in _rows(store):
            shown = _when(row.get("at"))
            if shown is None or shown < ran:
                continue
            if offers & {str(i) for i in row.get("offer_ids", ())}:
                return []
    return [{"ranking": name, "problem": "no present() row", "offers": sorted(offers)}]


def unrecorded_discards(store: ProfileStore) -> list[dict[str, str]]:
    """`offer_reaction` rows whose words no lifecycle event carries (counted, not set-matched)."""
    carried: Counter[tuple[str, str]] = Counter()
    for record in _lifecycle_records(store):
        for event in record.history:
            if event.from_status is not None and (event.reason or "").strip():
                carried[(record.offer_id, str(event.reason))] += 1
    gaps: list[dict[str, str]] = []
    for row in EvidenceLog(store).effective_rows():
        if row.about is None or row.about.kind != "offer" or row.source != "offer_reaction":
            continue
        key = (row.about.id, row.text)
        if carried[key]:
            carried[key] -= 1
            continue
        gaps.append({"offer": row.about.id, "reason": row.text, "row": row.id})
    return gaps
