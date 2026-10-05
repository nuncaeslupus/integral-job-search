"""T226 — a list shown with no `present()` row, a discard heard with no `rule_out`.

Steps 9 and 10 state both calls in prose only, so skipping one is silent: on
2026-10-01 a candidate was shown ranked offers and gave reasons for discarding
several, `search/presentations.jsonl` had no row for the day, no `rule_out` was
recorded, and the next day the same offers were shown again. Nothing noticed
because nothing read the two records against each other.

Two checks, each comparing one record with the record that must accompany it:

* `unpresented_ranking` — the newest `rankings/<run_id>.json` names offers, and
  no `presentations.jsonl` row at or after that run shows any of them.
* `unrecorded_discards` — a step-10 **decision** row (the shape
  `feedback.record_decision` writes: `step="feedback"`, `kind="statement"`,
  `source="offer_reaction"`, about one offer) that no lifecycle history event
  carries as its reason. It is `feedback.orphaned_reasons` read the other way
  round. A step-5 stimulus reaction, or a step-10 aside recorded as
  `kind="reaction"`, owes no decision and is not read; an offer purged after
  being ruled out (`lifecycle.purge_offer` keeps a tombstone and drops the
  history) is carried by its tombstone.

Both fail closed: a ranking file that cannot be read or dated is reported as a
gap, never read as "nothing to check".
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from integral.feedback import _lifecycle_records
from integral.identity import Identity, IdentityError, ProfileStore
from integral.lifecycle import current_tombstones
from integral.presentation_log import _rows
from integral.profile import EvidenceLog
from integral.profile_standing import standing_for_store
from integral.stack_fit import fits_for_store


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def unpresented_ranking(store: ProfileStore) -> list[dict[str, Any]]:
    """The newest ranking, when no presentation row at or after it shows its offers.

    A ranking is dated by its `run_id`, falling back to its file name
    (`rank.write_ranking` names the file `<run_id>.json`). A file that neither
    dates cannot be ordered, so it might be the newest: it is reported. The
    newest dated file is reported when it cannot be read. A ranking naming no
    offers has nothing to show. Empty means no gap.
    """
    directory = store.path("rankings")
    if not directory.is_dir():
        return []
    dated: list[tuple[datetime, str, dict[str, Any] | None]] = []
    gaps: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        data = _read(path)
        when = _when(data.get("run_id") if data else None) or _when(path.stem)
        if when is None:
            gaps.append({"ranking": path.name, "problem": "undatable"})
        else:
            dated.append((when, path.name, data))
    if gaps or not dated:
        return gaps
    ran, name, data = max(dated, key=lambda entry: (entry[0], entry[1]))
    if data is None or not isinstance(data.get("pareto"), list):
        return [{"ranking": name, "problem": "unreadable"}]
    offers = {str(i) for i in data["pareto"]}
    if not offers:
        return []
    for row in _rows(store):
        shown = _when(row.get("at"))
        if shown is None or shown < ran:
            continue
        if offers & {str(i) for i in row.get("offer_ids", ())}:
            return []
    return [{"ranking": name, "problem": "no present() row", "offers": sorted(offers)}]


def unstated_standing(store: ProfileStore) -> list[dict[str, Any]]:
    """T209: the newest batch shown did not say the standing computed for *its* offers.

    The lines are recomputed from the row's own `offer_ids` and the store
    (`profile_standing.standing_for_store` over `stack_fit.fits_for_store`) and must equal
    what the row recorded. Presence is not enough: a blank line, a "not assessed" pair
    recorded while fits exist, or lines computed for other offers all fail. The newest
    batch is the last row in the append-only file, by row identity, never by timestamp.
    The language is the candidate's own (`identity.json`), never the row's: a recompute
    parameterised by the record under test cannot disagree with it. The store is read as it
    is now, so a later CV edit flags the batch — fail-closed, and presenting again clears it.
    No rows is `unpresented_ranking`'s finding, not this one's.
    """
    rows = _rows(store)
    if not rows:
        return []
    newest = rows[-1]
    ids = [str(i) for i in newest.get("offer_ids", ())]
    said = newest.get("standing")
    try:
        language: str = Identity.model_validate(store.read_json("identity.json")).language
    except (IdentityError, ValueError, OSError):
        return [{"at": newest.get("at"), "problem": "the candidate's language cannot be read"}]
    expected = standing_for_store(store, fits_for_store(store, ids), ids, language=language)
    if (
        isinstance(said, dict)
        and said.get("strengths") == expected.strengths
        and said.get("widen") == expected.widen
    ):
        return []
    return [{"at": newest.get("at"), "problem": "no standing lines for this batch's offers"}]


def unrecorded_discards(store: ProfileStore) -> list[dict[str, str]]:
    """Step-10 decision rows whose words no lifecycle event carries (counted, not set-matched)."""
    carried: Counter[tuple[str, str]] = Counter()
    for record in _lifecycle_records(store):
        for event in record.history:
            if event.from_status is not None and (event.reason or "").strip():
                carried[(record.offer_id, str(event.reason))] += 1
    purged = set(current_tombstones(store))
    gaps: list[dict[str, str]] = []
    for row in EvidenceLog(store).effective_rows():
        if row.about is None or row.about.kind != "offer" or row.source != "offer_reaction":
            continue
        if row.step != "feedback" or row.kind != "statement" or row.about.id in purged:
            continue
        key = (row.about.id, row.text)
        if carried[key]:
            carried[key] -= 1
            continue
        gaps.append({"offer": row.about.id, "reason": row.text, "row": row.id})
    return gaps
