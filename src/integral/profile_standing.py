"""T209 — what in the profile is working, and what would widen the fit, at ranking.

A real session asked for "telling them their strong points or telling what to
improve" at step 9. The ranking already holds the join this needs:
`integral.stack_fit` puts each shown offer's technologies into buckets against
the candidate's CV and statements. This module only counts those buckets over
the offers **on the page** and fills catalogue sentences — no model composes
the prose, and no number is stated that is not a count of the input.

A strength is a technology the advert names and the candidate holds at working
level or above (`match`). `used` (used, level unstated) is deliberately neither
a strength nor a gap. What would widen the fit is a technology the adverts name
that the candidate lacks or holds at a low level (`missing`, `weak`) — the same
two buckets `integral.fit` treats as a shortfall — **minus anything the
candidate ruled out**, whichever way they said it: a skill stance `averse`, a
`skill:` exclusion (`sourcing_exclusions`) or a constraint row naming it. A
technology someone refused is never offered back as homework, and the widen line
ends by asking whether any of it is of interest rather than assigning it.

The denominator is the offers shown: an offer naming no technology, or with no
fit carried, is still on the page and still counts.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from integral import skill_requirement, stack_fit, strings
from integral.identity import ProfileStore
from integral.profile import EvidenceLog
from integral.sourcing_exclusions import load_exclusions

_CATALOGUE = strings.load()

STRENGTH_BUCKETS: tuple[str, ...] = ("match",)
WIDEN_BUCKETS: tuple[str, ...] = ("missing", "weak")

#: At most this many technologies per line; the rest are counted, never dropped silently.
MAX_ITEMS = 5


@dataclass(frozen=True)
class Standing:
    strengths: str
    widen: str


def ruled_out(store: ProfileStore) -> frozenset[str]:
    """Technologies the candidate refused, read by the readers those features use.

    `sourcing_exclusions.load_exclusions` for `skill:` exclusions, resolved the way
    `skill_requirement` resolves them; `stack_fit.named` over the log's constraint
    rows; `stack_fit`'s own `averse` stance is already its own bucket.
    """
    out: set[str] = set()
    for exclusion in load_exclusions(store):
        if exclusion.facet.strip().lower() == skill_requirement.FACET:
            ident = skill_requirement.identity(exclusion.value)
            if ident is not None:
                out.add(ident)
    for row in EvidenceLog(store).effective_rows():
        if row.kind == "constraint":
            out.update(stack_fit.named(row.text))
    return frozenset(out)


def _t(key: str, language: str) -> str:
    return strings.text(_CATALOGUE, key, language)


def _tally(
    fits: Iterable[Mapping[str, Any]], buckets: tuple[str, ...], skip: frozenset[str]
) -> tuple[Counter[str], dict[str, str]]:
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    for offer_fit in fits:
        seen: set[str] = set()
        for bucket in buckets:
            seen.update(offer_fit.get(bucket) or ())
        for technology in seen - skip:
            counts[technology] += 1
            span = offer_fit["spans"][technology]
            names[technology] = min(names.get(technology, span), span)
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
        return _t(empty, language)
    ordered = sorted(counts, key=lambda t: (-counts[t], t))
    item = _t("standing_item", language)
    items = ", ".join(
        item.format(name=names[t], count=counts[t], shown=shown) for t in ordered[:MAX_ITEMS]
    )
    if len(ordered) > MAX_ITEMS:
        items += _t("standing_more", language).format(n=len(ordered) - MAX_ITEMS)
    return _t(lead, language).format(items=items)


def standing(
    stack: Mapping[str, Mapping[str, Any]] | None,
    shown: Sequence[str],
    *,
    ruled_out: frozenset[str] = frozenset(),
    language: str = "es",
) -> Standing:
    """The two lines for the offers on the page.

    `shown` is the page's offer ids, not the whole ranking; `stack` is
    `stack_fit.fits_for_store`'s result and may hold more. The denominator is
    `len(shown)` whatever each offer says. When none of the shown offers carries
    a fit nothing was assessed, which is not the same as the adverts naming
    nothing: both lines then say "not assessed".
    """
    ids = list(dict.fromkeys(shown))
    fits = [stack[i] for i in ids if stack is not None and i in stack]
    if not fits:
        not_assessed = _t("stack_not_assessed", language)
        return Standing(strengths=not_assessed, widen=not_assessed)
    informative = [f for f in fits if f.get("verdict") != "unknown"]
    if not informative:
        unknown = _t("standing_unknown", language)
        return Standing(strengths=unknown, widen=unknown)
    strong, strong_names = _tally(informative, STRENGTH_BUCKETS, frozenset())
    wide, wide_names = _tally(informative, WIDEN_BUCKETS, ruled_out)
    widen = _line(
        wide,
        wide_names,
        shown=len(ids),
        lead="standing_widen",
        empty="standing_no_widen",
        language=language,
    )
    if wide:
        widen = f"{widen} {_t('standing_ask', language)}"
    return Standing(
        strengths=_line(
            strong,
            strong_names,
            shown=len(ids),
            lead="standing_strengths",
            empty="standing_no_strengths",
            language=language,
        ),
        widen=widen,
    )


def standing_for_store(
    store: ProfileStore,
    stack: Mapping[str, Mapping[str, Any]] | None,
    shown: Sequence[str],
    *,
    language: str = "es",
) -> Standing:
    """Step 9's call: the page's offers, with what the candidate ruled out read from disk."""
    return standing(stack, shown, ruled_out=ruled_out(store), language=language)
