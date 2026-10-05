"""T209 — what in the profile is working, and what would widen the fit, at ranking.

A real session asked for "telling them their strong points or telling what to
improve" at step 9. The ranking already holds the join this needs:
`integral.stack_fit` puts each shown offer's technologies into buckets against
the candidate's CV and statements. This module only counts those buckets across
the offers on screen and fills two catalogue sentences — no model composes the
prose, and no number is stated that is not a count of the input.

A strength is a technology the advert names and the candidate holds at working
level or above (`match`). What would widen the fit is a technology the adverts
name that the candidate lacks or holds at a low level (`missing`, `weak`) —
the same two buckets `integral.fit` treats as a shortfall. `averse` is a
preference, not a lack, so it is never offered as something to improve.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from integral import strings

_CATALOGUE = strings.load()

STRENGTH_BUCKETS: tuple[str, ...] = ("match",)
WIDEN_BUCKETS: tuple[str, ...] = ("missing", "weak")

#: At most this many technologies per line, so the line stays one line.
MAX_ITEMS = 5


@dataclass(frozen=True)
class Standing:
    strengths: str
    widen: str


def _tally(
    stack: Mapping[str, Mapping[str, Any]], buckets: tuple[str, ...]
) -> tuple[Counter[str], dict[str, str]]:
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    for offer_fit in stack.values():
        seen: set[str] = set()
        for bucket in buckets:
            seen.update(offer_fit.get(bucket) or ())
        for technology in seen:
            counts[technology] += 1
            names.setdefault(technology, offer_fit["spans"][technology])
    return counts, names


def _line(
    counts: Counter[str],
    names: Mapping[str, str],
    *,
    shown: int,
    lead: str,
    empty: str,
    language: str,
) -> str:
    if not counts:
        return strings.text(_CATALOGUE, empty, language)
    ordered = sorted(counts, key=lambda t: (-counts[t], t))[:MAX_ITEMS]
    item = strings.text(_CATALOGUE, "standing_item", language)
    items = ", ".join(item.format(name=names[t], count=counts[t], shown=shown) for t in ordered)
    return strings.text(_CATALOGUE, lead, language).format(items=items)


def standing(stack: Mapping[str, Mapping[str, Any]], *, language: str = "es") -> Standing:
    """The two lines for the offers shown, from `stack_fit.fits_for_store`'s result.

    Offers whose advert names no technology (`verdict == "unknown"`) say nothing
    about the stack; when every shown offer is one of those, both lines say so
    instead of reporting an empty strength list as if it were a finding.
    """
    informative = {k: v for k, v in stack.items() if v.get("verdict") != "unknown"}
    if not informative:
        unknown = strings.text(_CATALOGUE, "standing_unknown", language)
        return Standing(strengths=unknown, widen=unknown)
    shown = len(informative)
    strong, strong_names = _tally(informative, STRENGTH_BUCKETS)
    wide, wide_names = _tally(informative, WIDEN_BUCKETS)
    return Standing(
        strengths=_line(
            strong,
            strong_names,
            shown=shown,
            lead="standing_strengths",
            empty="standing_no_strengths",
            language=language,
        ),
        widen=_line(
            wide,
            wide_names,
            shown=shown,
            lead="standing_widen",
            empty="standing_no_widen",
            language=language,
        ),
    )
