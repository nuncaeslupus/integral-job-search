"""T244 — whether the candidate can do the job, as three axes of the ranking.

Three things the project already measured were never compared with the person
they were measured for: the technologies an advert names (`stack_fit`), the
level it asks for (`seniority_expectation`) and the English it demands
(`english_demand`). A Staff role naming five technologies the CV lacks ranked
exactly as a mid role the candidate could start on Monday.

**Each component is its own dimension** — `fit_stack`, `fit_seniority`,
`fit_english` — a shortfall in `[-1, 0]`, or unknown on its own. Two adverts
that are both silent on English still compare on the stack and the level they
both state; one unknown component never erases the others. The ranker reads
them pairwise (`rank.PAIRWISE_DIMENSIONS`): dominance compares the components
known on both sides and is never *blocked* by one that is not, and the tiebreak
orders only offers that state the same components.

**A surplus earns nothing.** Being senior for a mid role or fluent for a role
that needs none is a different question from "can do this without trouble".
`0` is "no gap", never "a good match".

**Unknown stays unknown, per component.** An advert that names no technology,
states no level, or asks for no language level has said nothing, and neither has
a profile that records no level. A *silent* advert is not a match, and it earns
no bonus: it carries the component in `unknown` and `rank` claims nothing about
it. Only a statement the rules stage read counts — a model-stage value for
`seniority_expectation` is the "plain practitioner title" default the
dimension's own tell describes, which is silence read as a level.

What this module does not do is decide what fit is worth against money. These
are axes and a tiebreak, never a price: that is a preference, and it lives in
T10's weights.

**What the profile records.** `cv/master.json` holds one `level` per language,
not a spoken and a written one, so both inputs are filled from it; the type
takes them separately for the day the profile records them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields, replace
from functools import lru_cache
from typing import Any, get_args

from integral.candidate import LEVEL_ORDER, Level
from integral.cv_store import Experience, load_master
from integral.dimensions import Dimension, load_dimensions
from integral.extraction import NormalisedAd, cue_findings
from integral.identity import ProfileStore
from integral.rank import FIT_DIMENSIONS, Candidate, RankingError
from integral.stack_fit import fits_for_store

#: `seniority_expectation`'s own rungs run 0.2 (junior) to 0.8 (senior).
_SENIORITY_SPAN = 0.8 - 0.2

#: The English a demand needs, as a `Level`: nothing asked, then conversational
#: ("B1-B2", 0.6), then professional ("C1/fluent", and every value above 0.6).
#: The lowest level that satisfies the rung — a C1 speaker meets "fluent".
_PROFESSIONAL = LEVEL_ORDER["professional"]

_SHORTFALL_BUCKETS = ("missing", "weak")  # `averse` is a preference, not a lack
_ALL_BUCKETS = ("match", "used", "weak", "averse", "missing")


@dataclass(frozen=True)
class OfferDemand:
    """What the offer asks. `None` is "the advert does not say"."""

    stack: Mapping[str, Any] | None = None  # `stack_fit.fit`'s dict
    seniority: float | None = None  # `seniority_expectation`, 0.2-0.8
    english: float | None = None  # `english_demand`, 0.0-1.0


@dataclass(frozen=True)
class CandidateAbility:
    """What the candidate holds. `None` is "the profile records nothing"."""

    seniority: float | None = None  # the last level held, on the same 0.2-0.8 scale
    spoken: Level | None = None
    written: Level | None = None


@dataclass(frozen=True)
class FitReading:
    """Three shortfalls in `[-1, 0]`, each `None` when it cannot be read."""

    stack: float | None
    seniority: float | None
    english: float | None

    def components(self) -> dict[str, float | None]:
        """`{dimension: shortfall}`, the names derived from the fields."""
        return {f"fit_{f.name}": getattr(self, f.name) for f in fields(self)}


# One closed rule: the dimension names `rank` reads pairwise are the fields here.
if tuple(FitReading(None, None, None).components()) != FIT_DIMENSIONS:  # pragma: no cover
    raise RankingError("rank.FIT_DIMENSIONS does not match FitReading's fields")


def _stack(fit: Mapping[str, Any] | None) -> float | None:
    if fit is None:
        return None
    named = sum(len(fit.get(bucket) or ()) for bucket in _ALL_BUCKETS)
    if fit.get("verdict") == "unknown" or named == 0:
        return None
    short = sum(len(fit.get(bucket) or ()) for bucket in _SHORTFALL_BUCKETS)
    return -short / named


def _seniority(demand: float | None, held: float | None) -> float | None:
    if demand is None or held is None:
        return None
    return -min(1.0, max(0.0, demand - held) / _SENIORITY_SPAN)


def _required_level(demand: float) -> int:
    if demand <= 0:
        return 0
    return LEVEL_ORDER["conversational"] if demand <= 0.6 else _PROFESSIONAL


def _english(demand: float | None, spoken: Level | None, written: Level | None) -> float | None:
    if demand is None or spoken is None or written is None:
        return None
    # The job runs in both modes, so the weaker one is the one that limits.
    have = min(LEVEL_ORDER[spoken], LEVEL_ORDER[written])
    return -min(1.0, max(0, _required_level(demand) - have) / _PROFESSIONAL)


def read_fit(offer: OfferDemand, me: CandidateAbility) -> FitReading:
    return FitReading(
        stack=_stack(offer.stack),
        seniority=_seniority(offer.seniority, me.seniority),
        english=_english(offer.english, me.spoken, me.written),
    )


def with_fit(candidate: Candidate, reading: FitReading) -> Candidate:
    """The candidate with every component accounted for: a score, or an admitted unknown."""
    scores = dict(candidate.scores)
    unknown = set(candidate.unknown)
    for name, value in reading.components().items():
        if name in scores or name in unknown:
            raise RankingError(f"{candidate.offer_id} already accounts for {name!r}")
        if value is None:
            unknown.add(name)
        else:
            scores[name] = value
    return replace(candidate, scores=scores, unknown=frozenset(unknown))


# ---------------------------------------------------------------------------
# step 9's path: the store in, candidates with fit out


@lru_cache(maxsize=1)
def _dimensions() -> dict[str, Dimension]:
    return {d.id: d for d in load_dimensions()}


def _held_seniority(title: str) -> float | None:
    """The level a job title states, by the same cues an advert is read with.

    A plain title ("Developer") states none and stays unknown — it is not "mid".
    """
    found: list[float] = []
    for language in ("en", "es", "ca"):
        ad = NormalisedAd(offer_id="cv", language=language, text=title)
        score = cue_findings(ad, _dimensions()["seniority_expectation"])
        if score is not None and score.value > 0:
            found.append(score.value)
    return max(found) if found else None


_MONTHS = {
    "jan": 1, "ene": 1, "gen": 1, "feb": 2, "mar": 3, "apr": 4, "abr": 4, "may": 5, "mai": 5,
    "jun": 6, "jul": 7, "aug": 8, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11,
    "dec": 12, "dic": 12, "des": 12,
}  # fmt: skip
_OPEN_WORDS = frozenset(
    {"present", "current", "now", "ongoing", "actual", "actualidad", "hoy", "avui", "actualitat"}
)
_ISO = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-\d{1,2})?)?$")
_NUMERIC = re.compile(r"^(\d{1,2})[/.-](\d{4})$")
_NAMED = re.compile(r"^([^\W\d_]+)\.?\s+(\d{4})$")


def _parse_date(text: str) -> tuple[int, int] | None:
    """`(year, month)` from the spellings a CV uses, or `None` when it cannot be read.

    A month-less year is month 0, so it sorts before any month of that year.
    """
    text = text.strip()
    if match := _ISO.match(text):
        return int(match[1]), int(match[2] or 0)
    if match := _NUMERIC.match(text):
        return int(match[2]), int(match[1])
    if (match := _NAMED.match(text)) and (month := _MONTHS.get(match[1].lower()[:3])):
        return int(match[2]), month
    return None


def last_held_level(experience: Sequence[Experience]) -> float | None:
    """The level the CV supports for the last role held, never more than it supports.

    Which role is last is read from dates parsed as dates, not compared as text.
    Where it cannot be settled — several open roles, an open role that began
    before a closed one ended, or a date that does not parse — every role that
    could be the last is a candidate, and the answer is the **lowest** of them.
    A candidate whose title states no level makes the answer unknown: it could be
    the last role, and nothing says it was not junior.
    """
    if not experience:
        return None
    ended: dict[int, tuple[int, int]] = {}
    started: dict[int, tuple[int, int]] = {}
    open_roles: list[int] = []
    ambiguous = False
    for index, job in enumerate(experience):
        if job.start is not None:
            if (when := _parse_date(job.start)) is None:
                ambiguous = True
            else:
                started[index] = when
        if job.end is None or job.end.strip().lower() in _OPEN_WORDS:
            open_roles.append(index)
        elif (when := _parse_date(job.end)) is None:
            ambiguous = True
        else:
            ended[index] = when
    if ambiguous:
        candidates = set(range(len(experience)))
    elif open_roles:
        known = [started[i] for i in open_roles if i in started]
        floor = min(known) if len(known) == len(open_roles) else None
        candidates = set(open_roles) | {
            i for i, end in ended.items() if floor is None or end > floor
        }
    else:
        latest = max(ended.values())
        candidates = {i for i, end in ended.items() if end == latest}
    levels = [_held_seniority(experience[i].title) for i in sorted(candidates)]
    if any(level is None for level in levels):
        return None
    return min(level for level in levels if level is not None)


def abilities_from_store(store: ProfileStore) -> CandidateAbility:
    """`cv/master.json` as `CandidateAbility`: the last role held and English."""
    master = load_master(store)
    english = [LEVEL_ORDER[e.level] for e in master.languages if e.language == "en"]
    best: Level | None = None
    if english:
        best = get_args(Level)[max(english)]  # `LEVEL_ORDER` is the enumeration of this
    return CandidateAbility(
        seniority=last_held_level(master.experience),
        spoken=best,
        written=best,
    )


def _stated(scores: Iterable[Mapping[str, Any]], dimension: str) -> float | None:
    """A value the rules stage read from the advert, or `None`.

    A model-stage value is not taken: for these two dimensions it is how a plain
    title or a missing mention becomes a level. A negated reading is a denial
    ("English not required"), which is a demand of zero.
    """
    for score in scores:
        if score.get("dimension") == dimension and score.get("provenance") == "rules":
            return max(0.0, float(score["value"]))
    return None


def demands_from_store(store: ProfileStore, offer_ids: Sequence[str]) -> dict[str, OfferDemand]:
    stacks = fits_for_store(store, offer_ids)
    demands: dict[str, OfferDemand] = {}
    for offer_id in offer_ids:
        path = store.path("extractions", f"{offer_id}.json")
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        scores = payload.get("scores") if isinstance(payload, dict) else None
        scores = scores if isinstance(scores, list) else []
        demands[offer_id] = OfferDemand(
            stack=stacks.get(offer_id),
            seniority=_stated(scores, "seniority_expectation"),
            english=_stated(scores, "english_demand"),
        )
    return demands


def fit_candidates(store: ProfileStore, candidates: Sequence[Candidate]) -> list[Candidate]:
    """Step 9: every candidate with its three fit components accounted for.

    Rank with `dimensions=[*dims, *FIT_DIMENSIONS]` — `rank.rankable_dimensions`
    does not add them.
    """
    me = abilities_from_store(store)
    demands = demands_from_store(store, [c.offer_id for c in candidates])
    return [with_fit(c, read_fit(demands[c.offer_id], me)) for c in candidates]
