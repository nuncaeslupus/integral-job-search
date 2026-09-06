"""The phrases this candidate searches with, and how each of them did.

Two halves of one subject: what was asked for, and what came back.

**The store for the second half already existed.** `offers/_fetches.jsonl`
has recorded `{connector, url, status, items, steered, query, at, offer_ids}`
per request since T126 — provenance that `sourcing.offers_without_a_recorded_
fetch` already gates. Nothing new is written to rank a phrase. What was
missing is that every phrase went out joined into one AND-ed string, so the
`query` column held `agentic python engineer` on 50 of 62 rows and could not
be read per phrase at all. `Aim` no longer joins; one request per phrase is
what turns that column into a record of which phrase found what.

What genuinely did not exist is `search/aim.json`. The phrases survived a
session only as an evidence row, so the next session did not know that
"agentic ai" was the thing that had worked — which is the whole reason this
module exists.

**Ranking is by unique contribution, not by volume.** A phrase that returns
forty adverts three other phrases also returned has told nobody anything; one
that returns four nobody else found has. Sorting by `offers` alone rewards
the broadest phrase every time, which is the opposite of the steer a
candidate needs.

**A phrase that returned nothing stays in the ranking.** It is the most
useful row in the file — it is the one that says do not spend a run on this
again — and it is exactly the row a table built by grouping results would
never contain.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from integral.candidate import Aim, CandidateConstraints
from integral.connectors import ListRequest
from integral.identity import IdentityError, ProfileStore
from integral.offers import OfferStatus
from integral.robots import Robots
from integral.sourcing import FETCH_LOG

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T140.json"

#: Where the phrases live. Not `profile/constraints.json`: D-20's gate says
#: every pinned field is a hard filter, and the aim filters nothing — it
#: decides what is fetched, upstream of the set the filter narrows. `Aim`'s
#: own docstring makes that argument; this is where it lands on disk.
AIM_FILE = ("search", "aim.json")

#: Statuses that mean the candidate looked at the advert and said something.
#: `new` is not among them: an offer nobody has ruled on is not a rejection,
#: and counting it as one would score every phrase by how recently it ran.
_KEPT: frozenset[OfferStatus] = frozenset({"shortlisted", "applied"})
_REFUSED: frozenset[OfferStatus] = frozenset({"screened_out", "rejected"})


def save_aim(store: ProfileStore, aim: Aim) -> Path:
    """Write the phrases, so the next session starts where this one got to."""
    return store.write_json(
        {"state": aim.state, "terms": list(aim.terms), "evidence": list(aim.evidence)}, *AIM_FILE
    )


def load_aim(store: ProfileStore) -> Aim:
    """The recorded phrases, or an honest `unknown`.

    An absent file is `unknown`, never `Aim(state="stated", terms=())` —
    `ConstraintField` would refuse that anyway, and the distinction is the one
    that matters: "nobody has said" and "they said nothing" send a steerable
    board down different paths, one asking the candidate and one searching for
    the empty string.
    """
    if not store.exists(*AIM_FILE):
        return Aim(state="unknown")
    payload = store.read_json(*AIM_FILE)
    if not isinstance(payload, dict):
        raise IdentityError(f"{'/'.join(AIM_FILE)} must be an object")
    return Aim(
        state=payload.get("state", "unknown"),
        terms=tuple(payload.get("terms", ())),
        evidence=tuple(payload.get("evidence", ())),
    )


@dataclass
class PhraseRow:
    """One phrase's record, over every run that has used it."""

    phrase: str
    #: Order of first use, from 1. Reading the ranking by `n` is reading the
    #: history of the search: where it started, what it opened onto, what it
    #: abandoned. That is what the owner asked this file to preserve.
    n: int
    first_at: str
    last_at: str
    boards: list[str] = field(default_factory=list)
    fetches: int = 0
    items: int = 0
    #: Distinct offers any fetch under this phrase returned.
    offers: int = 0
    #: Offers **no other phrase** returned. The ranking key.
    only_this_phrase: int = 0
    kept: int = 0
    refused: int = 0

    @property
    def unseen(self) -> int:
        """Offers this phrase found that nobody has ruled on yet."""
        return self.offers - self.kept - self.refused


def _rows(store: ProfileStore) -> list[dict[str, Any]]:
    if not store.exists("offers", FETCH_LOG):
        return []
    return [row for row in store.read_jsonl("offers", FETCH_LOG) if isinstance(row, dict)]


def _status_of(store: ProfileStore, offer_id: str) -> OfferStatus | None:
    try:
        payload = store.read_json("offers", f"{offer_id}.json")
    except IdentityError:
        return None
    status = payload.get("status") if isinstance(payload, dict) else None
    return status if isinstance(status, str) else None  # type: ignore[return-value]


def rank(store: ProfileStore) -> list[PhraseRow]:
    """Every phrase ever searched for, best first.

    "Best" is unique contribution, then what the candidate kept, then volume.
    Volume is last deliberately — see the module docstring.
    """
    by_phrase: dict[str, PhraseRow] = {}
    ids_by_phrase: dict[str, set[str]] = {}
    for row in _rows(store):
        phrase = row.get("query")
        if not isinstance(phrase, str) or not phrase:
            # An unsteered board's fetch. Real, and not about any phrase.
            continue
        at = str(row.get("at", ""))
        record = by_phrase.get(phrase)
        if record is None:
            record = PhraseRow(phrase=phrase, n=len(by_phrase) + 1, first_at=at, last_at=at)
            by_phrase[phrase] = record
            ids_by_phrase[phrase] = set()
        record.last_at = max(record.last_at, at)
        record.fetches += 1
        record.items += int(row.get("items", 0) or 0)
        board = str(row.get("connector", ""))
        if board and board not in record.boards:
            record.boards.append(board)
        ids_by_phrase[phrase].update(str(i) for i in row.get("offer_ids", ()))

    seen_by_others: dict[str, set[str]] = {}
    for phrase in ids_by_phrase:
        others: set[str] = set()
        for other, other_ids in ids_by_phrase.items():
            if other != phrase:
                others |= other_ids
        seen_by_others[phrase] = others

    for phrase, ids in ids_by_phrase.items():
        record = by_phrase[phrase]
        record.offers = len(ids)
        record.only_this_phrase = len(ids - seen_by_others[phrase])
        for offer_id in ids:
            status = _status_of(store, offer_id)
            if status in _KEPT:
                record.kept += 1
            elif status in _REFUSED:
                record.refused += 1
    return sorted(
        by_phrase.values(),
        key=lambda r: (-r.only_this_phrase, -r.kept, -r.offers, r.n),
    )


def by_board(store: ProfileStore) -> list[dict[str, Any]]:
    """Phrase x board — where a phrase works, which is not the same question.

    "agentic ai" being worth running is one fact; it being worth running *on
    tecnoempleo* is another, and only the second decides where the next run
    spends its requests.
    """
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _rows(store):
        phrase = row.get("query")
        if not isinstance(phrase, str) or not phrase:
            continue
        key = (phrase, str(row.get("connector", "")))
        cell = cells.setdefault(
            key, {"phrase": key[0], "board": key[1], "fetches": 0, "items": 0, "offer_ids": set()}
        )
        cell["fetches"] += 1
        cell["items"] += int(row.get("items", 0) or 0)
        cell["offer_ids"].update(str(i) for i in row.get("offer_ids", ()))
    out = []
    for cell in cells.values():
        cell["offers"] = len(cell.pop("offer_ids"))
        out.append(cell)
    return sorted(out, key=lambda c: (-int(c["offers"]), str(c["phrase"]), str(c["board"])))


def report(store: ProfileStore) -> str:
    """The ranking as the candidate is shown it."""
    rows = rank(store)
    if not rows:
        return "no phrase has been searched for yet"
    lines = [f"{len(rows)} phrase(s) searched, best first — ranked by what only they found"]
    for row in rows:
        ruled = f"{row.kept} kept, {row.refused} ruled out" if row.offers else "nothing came back"
        lines.append(
            f"  {row.n}. {row.phrase!r} — {row.offers} offer(s), "
            f"{row.only_this_phrase} only this phrase found; {ruled}; "
            f"{len(row.boards)} board(s), first {row.first_at[:10]}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The gate — ten contracts, each run rather than read
#
# `T121` and `T136` are the standing lesson: three rounds of checking a script
# by searching its text were defeated first by its own comments and then by an
# unused string holding every pattern the checker looked for. So none of the
# contracts below reads a source file. Each builds a store, runs the thing,
# and reads what came out — a function returning one fixed answer fails on
# whichever contract it gets wrong.


def _temp_store(root: Path, handle: str = "fixture") -> ProfileStore:
    from integral.identity import create_profile

    create_profile(root, "Fixture", handle=handle, language="es", fiction=True)
    return ProfileStore(root, handle)


def _log(store: ProfileStore, phrase: str | None, board: str, ids: list[str], at: str) -> None:
    store.append_jsonl(
        {
            "connector": board,
            "url": f"https://{board}/x",
            "status": 200,
            "items": len(ids),
            "steered": phrase is not None,
            "query": phrase,
            "at": at,
            "offer_ids": ids,
        },
        "offers",
        FETCH_LOG,
    )


def _contract_aim_survives_a_new_store(root: Path) -> str | None:
    store = _temp_store(root)
    save_aim(store, Aim(state="stated", terms=("agentic ai", "python developer")))
    reloaded = load_aim(ProfileStore(root, "fixture"))
    if reloaded.state != "stated" or reloaded.terms != ("agentic ai", "python developer"):
        return f"a saved aim came back as {reloaded.state}/{reloaded.terms}"
    return None


def _contract_absent_aim_is_unknown(root: Path) -> str | None:
    store = _temp_store(root)
    aim = load_aim(store)
    if aim.state != "unknown" or aim.terms:
        return f"an absent aim loaded as {aim.state}/{aim.terms}, not unknown"
    return None


def _contract_a_phrase_is_kept_whole(root: Path) -> str | None:
    """A term is a phrase. Splitting it on spaces would be the silent bug."""
    store = _temp_store(root)
    save_aim(store, Aim(state="stated", terms=("agentic ai",)))
    terms = load_aim(ProfileStore(root, "fixture")).terms
    if terms != ("agentic ai",):
        return f"the phrase came back as {terms}"
    return None


def _contract_one_request_per_phrase(root: Path) -> str | None:
    """The AND fix, measured as requests rather than as a joined string."""
    sent = _drive(root, ("agentic ai", "python developer"))
    if sent is None:
        return "no steerable board answered, so the contract could not run"
    steered = [url for url in sent if "agentic" in url or "python" in url]
    joined = [url for url in steered if "agentic" in url and "python" in url]
    if joined:
        return f"{len(joined)} request(s) carried both phrases at once: {joined[0]}"
    if not any("agentic" in url for url in steered) or not any(
        "python+developer" in url or "python%20developer" in url or "python" in url
        for url in steered
    ):
        return "a phrase was never sent on its own"
    return None


def _contract_an_unsteered_board_is_fetched_once(root: Path) -> str | None:
    sent = _drive(root, ("agentic ai", "python developer"), unsteered_only=True)
    if sent is None:
        return "no unsteered board answered, so the contract could not run"
    repeated = [url for url in set(sent) if sent.count(url) > 1]
    if repeated:
        return (
            f"a board that does not search was fetched {sent.count(repeated[0])} times "
            f"for {repeated[0]} — once per phrase, for one answer"
        )
    return None


def _drive(
    root: Path, phrases: tuple[str, ...], *, unsteered_only: bool = False
) -> list[str] | None:
    """Run the real driver over the committed packages, recording every URL."""
    from integral.candidate import Location as _Location
    from integral.connectors import accepts_query as _accepts
    from integral.sourcing import (
        DEFAULT_CONNECTORS_DIR,
        Response,
        _connector_of,
        packages_for,
        source,
    )

    constraints = CandidateConstraints(
        location=_Location(
            state="stated",
            country="ES",
            accepts_onsite_in_country=True,
            commutable_regions=("Barcelona",),
        )
    )
    wanted = [
        package
        for package in packages_for(constraints, DEFAULT_CONNECTORS_DIR)
        if _accepts(_connector_of(package, DEFAULT_CONNECTORS_DIR)) is not unsteered_only
    ]
    if not wanted:
        return None
    sent: list[str] = []

    def answer(request: ListRequest) -> Response:
        sent.append(request.url)
        return Response(200, "<html></html>")

    store = _temp_store(root)
    source(
        store,
        constraints,
        Aim(state="stated", terms=phrases),
        fetch=answer,
        at="2026-01-01T00:00:00+00:00",
        directory=DEFAULT_CONNECTORS_DIR,
        robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
    )
    hosts = {p.site for p in wanted if p.site}
    return [url for url in sent if any((p or "") in url for p in hosts)]


def _contract_a_run_records_what_it_searched_with(root: Path) -> str | None:
    """The bug this module exists for, stated as a case.

    Persisting on the caller's initiative is persistence that is skipped
    exactly when a session ends badly, which is when it was most needed.
    """
    if _drive(root, ("agentic ai",)) is None:
        return "no steerable board answered, so the contract could not run"
    reloaded = load_aim(ProfileStore(root, "fixture"))
    if reloaded.terms != ("agentic ai",):
        return f"after a run, the recorded aim read {reloaded.state}/{reloaded.terms}"
    return None


def _contract_an_empty_phrase_still_ranks(root: Path) -> str | None:
    store = _temp_store(root)
    _log(store, "agentic ai", "foorilla_en", ["sha256:a"], "2026-01-01T00:00:00+00:00")
    _log(store, "cobol on a mainframe", "foorilla_en", [], "2026-01-02T00:00:00+00:00")
    phrases = [row.phrase for row in rank(store)]
    if "cobol on a mainframe" not in phrases:
        return "a phrase that returned nothing vanished from the ranking"
    return None


def _contract_unique_ignores_shared_offers(root: Path) -> str | None:
    store = _temp_store(root)
    _log(store, "broad", "b", ["sha256:a", "sha256:b", "sha256:c"], "2026-01-01T00:00:00+00:00")
    _log(store, "narrow", "b", ["sha256:a", "sha256:z"], "2026-01-02T00:00:00+00:00")
    rows = {row.phrase: row for row in rank(store)}
    if rows["narrow"].only_this_phrase != 1:
        return f"narrow's unique contribution read {rows['narrow'].only_this_phrase}, not 1"
    if rows["broad"].only_this_phrase != 2:
        return f"broad's unique contribution read {rows['broad'].only_this_phrase}, not 2"
    return None


def _contract_volume_does_not_win(root: Path) -> str | None:
    """The whole point of the ranking key, stated as a case."""
    store = _temp_store(root)
    shared = [f"sha256:{n}" for n in range(20)]
    _log(store, "broad", "b", shared, "2026-01-01T00:00:00+00:00")
    _log(store, "also broad", "b", shared, "2026-01-02T00:00:00+00:00")
    _log(store, "narrow", "b", ["sha256:only"], "2026-01-03T00:00:00+00:00")
    first = rank(store)[0].phrase
    if first != "narrow":
        return f"{first!r} outranked a phrase that found something nobody else did"
    return None


def _contract_order_is_by_first_use(root: Path) -> str | None:
    store = _temp_store(root)
    _log(store, "first", "b", [], "2026-01-01T00:00:00+00:00")
    _log(store, "second", "b", ["sha256:a", "sha256:b"], "2026-01-02T00:00:00+00:00")
    _log(store, "first", "b", [], "2026-01-03T00:00:00+00:00")
    numbers = {row.phrase: row.n for row in rank(store)}
    if numbers != {"first": 1, "second": 2}:
        return f"the order of first use read {numbers}"
    return None


def _contract_an_unruled_offer_is_not_a_rejection(root: Path) -> str | None:
    """`new` is not `screened_out`, and scoring it as one would rank a phrase
    by how recently it ran rather than by how well it did."""
    store = _temp_store(root)
    _log(store, "p", "b", ["sha256:missing"], "2026-01-01T00:00:00+00:00")
    row = rank(store)[0]
    if row.refused or row.kept:
        return f"an offer nobody has ruled on counted as {row.kept} kept / {row.refused} refused"
    if row.unseen != 1:
        return f"unseen read {row.unseen}, not 1"
    return None


CONTRACTS = (
    ("an aim survives a new store", _contract_aim_survives_a_new_store),
    ("an absent aim is unknown", _contract_absent_aim_is_unknown),
    ("a phrase is kept whole", _contract_a_phrase_is_kept_whole),
    ("one request per phrase", _contract_one_request_per_phrase),
    ("an unsteered board is fetched once", _contract_an_unsteered_board_is_fetched_once),
    ("a run records what it searched with", _contract_a_run_records_what_it_searched_with),
    ("a phrase that found nothing still ranks", _contract_an_empty_phrase_still_ranks),
    ("unique contribution ignores shared offers", _contract_unique_ignores_shared_offers),
    ("volume does not win", _contract_volume_does_not_win),
    ("order is by first use", _contract_order_is_by_first_use),
    ("an unruled offer is not a rejection", _contract_an_unruled_offer_is_not_a_rejection),
)

#: Floor. A zero over a handful of contracts says nothing about the rest.
MINIMUM_CONTRACTS = 11


def measure() -> dict[str, Any]:
    import tempfile

    failures: list[str] = []
    for name, contract in CONTRACTS:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                complaint = contract(Path(tmp))
            except Exception as exc:  # a contract that cannot run has failed
                complaint = f"raised {type(exc).__name__}: {exc}"
        if complaint:
            failures.append(f"{name}: {complaint}")
    measured: dict[str, Any] = {
        "search_term_defects": len(failures),
        "contracts_run": len(CONTRACTS),
        "failed_contracts": failures,
        "gate_status": "measured",
    }
    if len(CONTRACTS) < MINIMUM_CONTRACTS:
        measured["gate_status"] = "unmeasured"
        measured["reasons"] = [
            f"only {len(CONTRACTS)} contract(s), floor {MINIMUM_CONTRACTS}",
        ]
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main() -> int:
    measured = write_evidence()
    print(json.dumps(measured, ensure_ascii=False))
    for failure in measured["failed_contracts"]:
        print(f"  FAILED {failure}", file=sys.stderr)
    if measured["gate_status"] == "unmeasured":
        return 3
    return 1 if measured["search_term_defects"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
