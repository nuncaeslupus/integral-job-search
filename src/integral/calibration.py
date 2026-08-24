"""Calibration (T20a) — the blind sitting, the recorded ordering, `rank_spearman` (T20).

T20 is `[HUMAN]`: the candidate ranks twenty held-out adverts by hand and
`rank_spearman >= 0.60` says whether the system agrees with them. Everything
around that act is software, and this module is that software. T20 keeps the
judgement; nothing here may produce an ordering.

Two gates, two subcommands, one module — the shape `integral.harness` already
uses for T4 (`gate`) and T5 (`labels`):

* `leaks` writes `status/evidence/T20a.json` and needs no candidate. Its number
  is `blind_ranking_leaks`, and it counts the ways the presentation could tell
  the candidate what the system already thinks. A leak does not make T20 fail —
  it makes T20 **pass while measuring the anchor rather than the judgement**,
  which is the failure D-2 named for cue-derived gold and T9 named for a shared
  split. So the leak count is the gate, and `measure_leaks` plants every leak it
  claims to detect: a zero that has never been anything else certifies nothing.
* `spearman` writes `status/evidence/T20.json` and cannot run without one.
  Until an ordering is recorded it is `null` with `rank_status: "unmeasured"` —
  D-2's third outcome, not a pass and not a fail. On a fresh clone that is what
  `make evidence` will always write, and it is the honest answer: the
  measurement has not been taken here.

The twenty are drawn from the **evaluation** split only, deterministically from
the ad id. T9's `elicitation_eval_overlap == 0` is the reason: an advert used to
elicit preferences and then scored measures memorisation. Eligibility is
membership of that split and nothing else — deliberately *not* "has labels".
Only four ads in `corpus/labelled/ads.jsonl` carry a label today, and drawing
from those would sample the labelling campaign's leftovers rather than the
market. The candidate reads the advert text, which every entry has.

The ordering itself is recorded in the **profile store**, never in the
repository. A permutation of twenty adverts is a statement about a person, of
the same kind as T10's part-worths and T9's reactions, and neither of those is
committed either. `integral.state_home` already owns where that lives.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from integral.harness import DEFAULT_STORE_PATH, LabelledAd, load_store, split_rank
from integral.identity import (
    IdentityError,
    ProfileStore,
    default_profiles_root,
    read_active_handle,
)
from integral.offers import compute_offer_id

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T20a.json"
RANK_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T20.json"

# How many held-out adverts the candidate ranks. Twenty is `status/plan.md`'s
# number for T20 and the size the sitting was scoped to; it is not a knob.
TWENTY = 20

# Where the candidate's ordering lives inside their own tree.
ORDERING_PARTS = ("calibration", "blind_ranking.json")
RANKINGS_DIR = "rankings"

# A note is signed. One box collapses "the remote policy is why I looked" and
# "the stack is why I stopped" into a single string, and the sign is exactly
# what a search strategy needs: an attractor says where to look next, a
# knockout says what to stop returning.
NOTE_SIDES = ("liked", "disliked")

# Everything a blind page may carry. The candidate reads the **advert**, and
# nothing else — so this is a closed set, not a minimum.
PAGE_KEYS = frozenset({"position", "offer_id", "title", "company", "language", "text"})

# Key names that mean the system's opinion has reached the page. Checked
# recursively and by name: a score nested one level down is still a score.
FORBIDDEN_KEYS = frozenset(
    {
        "contribution_eur_month",
        "dominated",
        "dominated_by",
        "explanation",
        "explanations",
        "facets",
        "pareto",
        "rank",
        "ranking",
        "salary_equivalent_total",
        "score",
        "scores",
        "weights",
    }
)

# Key names that mean a previous pass is visible while ranking, which would turn
# a re-run into a confirmation of the first pass rather than a second judgement.
RECORDED_KEYS = frozenset(
    {"ordering", "previous_ordering", "previously_recorded", "recorded_ordering"}
)

SCORE_LEAK = "a_score_or_explanation_reaches_the_page"
RECORDED_LEAK = "the_recorded_ordering_is_visible"
RANKING_LEAK = "presentation_follows_the_system_ranking"
UNEXPECTED_LEAK = "an_unexpected_field_reaches_the_page"


class CalibrationError(Exception):
    """A caller mistake — never a normal outcome of a sitting."""


# -- the draw -------------------------------------------------------------


def evaluation_ads(store_path: Path = DEFAULT_STORE_PATH) -> list[LabelledAd]:
    """Every evaluation-split ad, in a stable id-derived order.

    `split_rank` is `harness`'s own ordering key, reused rather than reinvented
    so the draw cannot disagree with the split it draws from.
    """
    return sorted(
        (ad for ad in load_store(store_path) if ad.split == "evaluation"),
        key=lambda ad: split_rank(ad.id),
    )


def draw(count: int = TWENTY, store_path: Path = DEFAULT_STORE_PATH) -> list[LabelledAd]:
    """The `count` adverts the candidate will rank — the same ones on every machine."""
    ads = evaluation_ads(store_path)
    if len(ads) < count:
        raise CalibrationError(
            f"the evaluation split holds {len(ads)} ads and the sitting needs {count}"
        )
    return ads[:count]


def offer_id(ad: LabelledAd) -> str:
    """The canonical id, so the two sides cannot disagree about what an id *is*.

    T11's `compute_offer_id` over the advert text — the same value `Offer.id`
    carries and the same one the evidence log accepts as an offer subject. The
    corpus's own `ad.id` is a collection artefact and never leaves this module.
    """
    return compute_offer_id(ad.text)


# -- the blind presentation ----------------------------------------------


def presentation_order(offer_ids: Iterable[str]) -> list[str]:
    """A deterministic shuffle keyed on the id alone.

    Sorting by the offer id is a shuffle with respect to everything that
    matters: the id is a digest of the advert text, so the resulting order is
    unrelated to the draw order (which is keyed on the corpus id), to salary, to
    any score, and — the property the gate is about — to whatever the system
    would rank these twenty. A caller holding that ranking cannot influence this
    function, because it is not an argument.
    """
    return sorted(set(offer_ids))


def presentation(ads: Sequence[LabelledAd]) -> dict[str, Any]:
    """The pages the candidate reads: the advert, its position, and nothing else."""
    by_id = {offer_id(ad): ad for ad in ads}
    pages = []
    for position, identifier in enumerate(presentation_order(by_id), start=1):
        ad = by_id[identifier]
        pages.append(
            {
                "position": position,
                "offer_id": identifier,
                "title": ad.title,
                "company": ad.company,
                "language": ad.language,
                "text": ad.text,
            }
        )
    return {"pages": pages}


def _key_names(payload: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(payload, Mapping):
        names |= set(map(str, payload.keys()))
        for value in payload.values():
            names |= _key_names(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            names |= _key_names(item)
    return names


def leaks(payload: Mapping[str, Any], *, system_order: Sequence[str]) -> list[str]:
    """Every way this presentation tells the candidate what the system thinks."""
    found: list[str] = []
    names = _key_names(payload)
    page_keys: set[str] = set()
    for page in payload.get("pages", []):
        page_keys |= set(map(str, page))

    if names & FORBIDDEN_KEYS:
        found.append(SCORE_LEAK)
    if names & RECORDED_KEYS:
        found.append(RECORDED_LEAK)

    shown = [str(page["offer_id"]) for page in payload.get("pages", [])]
    ranked = list(system_order)
    # Reversed counts too: an order that is the ranking upside down is just as
    # much a function of the ranking as one that copies it.
    if ranked and shown in (ranked, list(reversed(ranked))):
        found.append(RANKING_LEAK)

    unexpected = (set(payload) - {"pages"}) | (page_keys - PAGE_KEYS)
    if unexpected - FORBIDDEN_KEYS - RECORDED_KEYS:
        found.append(UNEXPECTED_LEAK)
    return found


# -- the recorded ordering ------------------------------------------------


def require_permutation(ordering: Sequence[str], drawn: Sequence[str]) -> None:
    """Refuse anything that is not an exact permutation of the drawn twenty.

    Named, not counted. Correlating a truncated pair — by `zip`, or by indexing
    a rank map with a missing key — computes a confident number over a sample
    nobody chose, which is worse than refusing.
    """
    given = list(ordering)
    expected = list(drawn)
    duplicates = sorted({identifier for identifier in given if given.count(identifier) > 1})
    if duplicates:
        raise CalibrationError(f"the ordering repeats {len(duplicates)} id(s): {duplicates}")
    unknown = sorted(set(given) - set(expected))
    if unknown:
        raise CalibrationError(f"the ordering names {len(unknown)} id(s) not drawn: {unknown}")
    missing = sorted(set(expected) - set(given))
    if missing:
        raise CalibrationError(f"the ordering omits {len(missing)} drawn id(s): {missing}")


def record(
    store: ProfileStore,
    ordering: Sequence[str],
    *,
    blocks: Mapping[str, Sequence[str]] | None = None,
    notes: Mapping[str, Mapping[str, str]] | None = None,
    count: int = TWENTY,
) -> Path:
    """Write the candidate's ordering under their own tree, after validating it.

    `blocks` and `notes` are what the sitting produced beside the order, and
    they are kept because the order alone cannot express them. A candidate who
    discards an advert for a stack they have never written has stated a
    **knockout**, not a low score, and the two are different objects: a weight
    fitted from a rank would read that discard as "worth less money", which is
    not what it means. The block names are the candidate's own words, so what
    the three groups meant stays readable beside what went into them.

    A note is **signed**: `liked` and `disliked` are separate fields, because one
    free-text box mixes an attractor and a knockout into a single string and
    nothing downstream can pull them apart again. "Interesting, but they want
    someone more senior and the pay is not stated" is one good reason to search
    and two reasons to reject, and preference-directed sourcing needs to know
    which half was which.

    All three are validated against the same drawn set as the ordering — a note
    attached to an advert nobody was shown is a note about nothing.
    """
    drawn = [offer_id(ad) for ad in draw(count)]
    require_permutation(ordering, drawn)
    payload: dict[str, Any] = {"drawn": drawn, "ordering": list(ordering)}
    if blocks is not None:
        grouped = {str(name): [str(x) for x in members] for name, members in blocks.items()}
        stray = sorted({x for members in grouped.values() for x in members} - set(drawn))
        if stray:
            raise CalibrationError(f"the blocks name {len(stray)} id(s) not drawn: {stray}")
        payload["blocks"] = grouped
    if notes is not None:
        # An untouched box is dropped rather than stored as an empty string:
        # "said nothing" and "was never asked" must not become the same record.
        kept: dict[str, dict[str, str]] = {}
        for key, sides in notes.items():
            said = {
                side: str(sides[side]).strip()
                for side in NOTE_SIDES
                if str(sides.get(side, "")).strip()
            }
            if said:
                kept[str(key)] = said
        stray = sorted(set(kept) - set(drawn))
        if stray:
            raise CalibrationError(f"the notes name {len(stray)} id(s) not drawn: {stray}")
        payload["notes"] = kept
    return store.write_json(payload, *ORDERING_PARTS)


def recorded(store: ProfileStore) -> dict[str, Any] | None:
    """The ordering this candidate gave, or `None` if they have not sat down yet."""
    if not store.exists(*ORDERING_PARTS):
        return None
    payload = store.read_json(*ORDERING_PARTS)
    if not isinstance(payload, Mapping) or "ordering" not in payload:
        raise CalibrationError(f"{'/'.join(ORDERING_PARTS)} is not a recorded ordering")
    return dict(payload)


# -- the correlation ------------------------------------------------------

Group = str | Sequence[str]


def ranks(order: Sequence[Group]) -> dict[str, float]:
    """`{id: rank}` from an ordering, best first.

    A nested group shares the average of the ranks it spans. That is how the
    system's own ordering arrives: `rank.frontier` publishes the Pareto set in
    order and collapses the rest into a `{id: dominated_by:<id>}` map with no
    order among its members, so those genuinely tie for last.
    """
    assigned: dict[str, float] = {}
    position = 1
    for element in order:
        members = [element] if isinstance(element, str) else list(element)
        if not members:
            continue
        average = position + (len(members) - 1) / 2
        for identifier in members:
            assigned[identifier] = average
        position += len(members)
    return assigned


def spearman(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    """Spearman's rho — Pearson over the two rank maps, ties already averaged."""
    if set(a) != set(b):
        raise CalibrationError(
            "the two orderings do not cover the same ids: "
            f"{sorted(set(a) ^ set(b))[:5]} differ"
        )
    if len(a) < 2:
        raise CalibrationError("two ids at least are needed for a correlation")
    keys = sorted(a)
    mean_a = sum(a[key] for key in keys) / len(keys)
    mean_b = sum(b[key] for key in keys) / len(keys)
    covariance = sum((a[key] - mean_a) * (b[key] - mean_b) for key in keys)
    spread_a = sum((a[key] - mean_a) ** 2 for key in keys)
    spread_b = sum((b[key] - mean_b) ** 2 for key in keys)
    if spread_a == 0 or spread_b == 0:
        raise CalibrationError("an ordering with no spread has no rank correlation")
    return float(covariance / (spread_a * spread_b) ** 0.5)


def system_order(store: ProfileStore, drawn: Sequence[str]) -> list[Group] | None:
    """The system's own ordering of exactly these ids, from a stored ranking run.

    Read from `rankings/<run_id>.json` — T9's artefact, not a second one written
    for this gate. A run that covers a different set of offers is not an
    ordering of the twenty and is passed over rather than trimmed to fit.
    """
    directory = store.path(RANKINGS_DIR)
    if not directory.is_dir():
        return None
    for path in sorted(directory.glob("*.json"), reverse=True):
        ranking = json.loads(path.read_text(encoding="utf-8"))
        pareto = [str(identifier) for identifier in ranking.get("pareto", [])]
        collapsed = sorted(str(identifier) for identifier in ranking.get("dominated", {}))
        if set(pareto) | set(collapsed) != set(drawn):
            continue
        return [*pareto, collapsed] if collapsed else list(pareto)
    return None


def measure_spearman(store: ProfileStore | None) -> dict[str, Any]:
    """T20's gate — or its honest refusal to compute one."""
    unmeasured: dict[str, Any] = {"rank_spearman": None, "rank_status": "unmeasured"}
    if store is None:
        return unmeasured
    if is_fiction(store):
        # S11: a candidate invented to exercise a step must not certify a gate.
        # Their ordering is a real permutation and rho over it is a real number,
        # which is exactly the danger — T20 asks whether the system agrees with
        # *this person*, and a persona answers a question nobody asked. The mark
        # is set at creation and cannot be added afterwards, so this is the one
        # moment it can be trusted.
        return unmeasured
    ordering = recorded(store)
    if ordering is None:
        return unmeasured
    drawn = [str(identifier) for identifier in ordering["drawn"]]
    require_permutation([str(x) for x in ordering["ordering"]], drawn)
    theirs = system_order(store, drawn)
    if theirs is None:
        return unmeasured
    manual = ranks([str(identifier) for identifier in ordering["ordering"]])
    return {"rank_spearman": spearman(manual, ranks(theirs)), "rank_status": "measured"}


def is_fiction(store: ProfileStore) -> bool:
    """Was this profile created to exercise a step rather than to be served?"""
    try:
        return bool(store.identity().fiction)
    except (IdentityError, FileNotFoundError, OSError):
        # No readable identity is not a real candidate either, and a gate is
        # not the place to find out — `measure_spearman` reads this as "do not
        # certify", which is the safe direction.
        return True


def active_store() -> ProfileStore | None:
    """The candidate this session identified, or `None` — §6.1, via `identity`."""
    session_id = os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID") or os.environ.get(
        "CLAUDE_CODE_SESSION_ID"
    )
    try:
        root = default_profiles_root()
    except Exception:
        # Resolution can fail (no state home, or one that points into a work
        # tree). That is `unmeasured`, not a crash in `make evidence`.
        return None
    handle = read_active_handle(root, session_id=session_id)
    return ProfileStore(root, handle) if handle else None


# -- the leak gate --------------------------------------------------------


def measure_leaks(store_path: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    """`blind_ranking_leaks`, with every leak it claims to detect planted first."""
    ads = draw(store_path=store_path)
    page_order = [page["offer_id"] for page in presentation(ads)["pages"]]
    # A fixture built to make the two agree: the system ranks them in the order
    # they were drawn, and the presentation must not be that order.
    agreeing = [offer_id(ad) for ad in ads]

    plants: dict[str, dict[str, Any]] = {}
    scored = presentation(ads)
    scored["pages"][0]["salary_equivalent_total"] = 3200.0
    plants[SCORE_LEAK] = scored

    shown = presentation(ads)
    shown["recorded_ordering"] = agreeing
    plants[RECORDED_LEAK] = shown

    plants[RANKING_LEAK] = presentation(ads)

    undetected = sorted(
        name
        for name, payload in plants.items()
        if name
        not in leaks(payload, system_order=page_order if name == RANKING_LEAK else agreeing)
    )
    found = leaks(presentation(ads), system_order=agreeing)
    return {
        # A detector that cannot see a leak somebody planted makes its own zero
        # meaningless, so an undetected plant counts as a leak in its own right.
        "blind_ranking_leaks": len(found) + len(undetected),
        "leaks_found": found,
        "plants_detected": sorted(set(plants) - set(undetected)),
        "plants_undetected": undetected,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure_leaks()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


def write_rank_evidence(evidence: Path = RANK_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure_spearman(active_store())
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


# -- CLI ------------------------------------------------------------------


def _leaks(evidence: Path) -> int:
    measured = write_evidence(evidence)
    print(f"blind_ranking_leaks: {measured['blind_ranking_leaks']} (== 0)")
    if measured["plants_undetected"]:
        print(
            "the count did not rise for a planted leak: "
            f"{measured['plants_undetected']}",
            file=sys.stderr,
        )
        return 1
    return 0 if measured["blind_ranking_leaks"] == 0 else 1


def _spearman(evidence: Path) -> int:
    measured = write_rank_evidence(evidence)
    if measured["rank_status"] == "unmeasured":
        print("rank_spearman: unmeasured — no ordering recorded for the active candidate")
        return 0
    print(f"rank_spearman: {measured['rank_spearman']:.4f} (>= 0.60)")
    return 0


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="T20a's blind sitting and T20's rho.")
    sub = parser.add_subparsers(dest="command")
    leaks_parser = sub.add_parser("leaks", help="write T20a's evidence")
    leaks_parser.add_argument("evidence", nargs="?", default=str(DEFAULT_EVIDENCE_PATH), type=Path)
    rho_parser = sub.add_parser("spearman", help="write T20's evidence")
    rho_parser.add_argument("evidence", nargs="?", default=str(RANK_EVIDENCE_PATH), type=Path)

    args = parser.parse_args(argv)
    if args.command is None:
        # `make evidence` invokes every module bare; both gates are this
        # module's to regenerate.
        return _leaks(DEFAULT_EVIDENCE_PATH) or _spearman(RANK_EVIDENCE_PATH)
    if args.command == "leaks":
        return _leaks(args.evidence)
    return _spearman(args.evidence)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
