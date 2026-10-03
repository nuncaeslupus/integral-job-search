"""T244 — whether the candidate can do the job, as one axis of the ranking.

Three things the project already measured were never compared with the person
they were measured for: the technologies an advert names (`stack_fit`), the
level it asks for (`seniority_expectation`) and the English it demands
(`english_demand`). A Staff role naming five technologies the CV lacks ranked
exactly as a mid role the candidate could start on Monday.

**Each component is a shortfall in `[-1, 0]`, and a surplus earns nothing.**
Being senior for a mid role or fluent for a role that needs none is not "can do
this without trouble" — it is a different question, and paying a bonus for it
would be a preference nobody stated. `0` is "no gap", never "a good match".

**The reading is the mean of the three, so it is monotone in every one.**
Improving any component never lowers it, which is the property the ranking is
held to. A `min` would tie two offers that differ only in a component that is
not the weakest, and the order would then claim nothing about a real difference.

**Unknown stays unknown, per component and for the whole.** An advert that
names no technology, states no level, or demands no language level has said
nothing, and neither has a profile that records no level. Any unknown component
makes the whole reading unknown: there is no score, so the candidate carries
`fit` in `unknown` and `rank` claims nothing about it in either direction. The
alternative — averaging the known components — would let a silent advert read as
a good fit by omission, a bonus disguised as data.

What this module does not do is decide what fit is worth against money. It is an
axis (dominance reads it) and a tiebreak (`rank._fit_before_the_alphabet`), never
a price: that is a preference, and it lives in T10's weights.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from integral.candidate import LEVEL_ORDER, Level
from integral.rank import FIT_DIMENSION, Candidate, RankingError

#: The dimension name the reading is carried under in `Candidate.scores`.
FIT = FIT_DIMENSION

#: `seniority_expectation`'s own rungs run 0.2 (junior) to 0.8 (senior).
_SENIORITY_SPAN = 0.8 - 0.2

#: `english_demand` is `[0, 1]` and `Level` runs `none`..`native`; the demand is
#: read as that fraction of the ladder.
_TOP_RUNG = max(LEVEL_ORDER.values())

_SHORTFALL_BUCKETS = ("missing", "averse", "weak")
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

    @property
    def score(self) -> float | None:
        parts = (self.stack, self.seniority, self.english)
        if any(part is None for part in parts):
            return None
        return sum(part for part in parts if part is not None) / len(parts)


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


def _english(demand: float | None, spoken: Level | None, written: Level | None) -> float | None:
    if demand is None or spoken is None or written is None:
        return None
    # The job runs in both modes, so the weaker one is the one that limits.
    have = min(LEVEL_ORDER[spoken], LEVEL_ORDER[written])
    return -min(1.0, max(0.0, demand * _TOP_RUNG - have) / _TOP_RUNG)


def read_fit(offer: OfferDemand, me: CandidateAbility) -> FitReading:
    return FitReading(
        stack=_stack(offer.stack),
        seniority=_seniority(offer.seniority, me.seniority),
        english=_english(offer.english, me.spoken, me.written),
    )


def with_fit(candidate: Candidate, reading: FitReading) -> Candidate:
    """The candidate with `fit` accounted for: a score, or an admitted unknown."""
    if FIT in candidate.scores or FIT in candidate.unknown:
        raise RankingError(f"{candidate.offer_id} already accounts for {FIT!r}")
    score = reading.score
    if score is None:
        return replace(candidate, unknown=candidate.unknown | {FIT})
    return replace(candidate, scores={**candidate.scores, FIT: score})
