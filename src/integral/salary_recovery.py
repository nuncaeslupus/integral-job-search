"""T92 — the figure the advert stated somewhere we were not reading.

Round 3 of the live session dropped **13 of 17** survivors under one rule: *no
salary and no cheap approximation, therefore not shown*. Salary **silence** is
the binding constraint on what a candidate ever sees — and nobody looked for the
figure before the row was thrown away.

Four lookups, cheapest first, before a silent offer may be dropped:

1. **The advert's own body.** Six HTML connectors leave `salary` unmapped
   because the list card prints one unsplittable string
   (`connectors/tecnoempleo_es/connector.yaml` says so in as many words: *"The
   band is not lost to a reader — it is in the ad body, which `text` carries."*).
   The band is right there; nothing was reading it.
2. **The same advert on another board.** `dedup.py` already pairs canonical
   duplicates. If one copy states a band, the silent copy is not silent.
3. **The board's detail page.** Passed in as a reader, never fetched here — the
   same contract `enrichment.enrich` uses for its finder: what to fetch, and
   under whose robots.txt, is a connector question, and a default fetcher inside
   a recovery path is a network call hidden in a scoring path.
4. **An approximation**, when the caller supplies an estimator. The candidate
   accepted one *provided it is labelled*: "read about that company to give an
   approximation".

**An estimate must never read as a stated figure.** `Salary.stated` is the whole
of that promise, and it is kept mechanically here rather than by discipline: the
estimate route overwrites `stated` to `False` on whatever the estimator returned,
so an estimator that lies cannot launder its band into a claim. The basis travels
beside the figure in `Recovered.basis`, never inside `Salary` — §5.2's offer has
no field for provenance and inventing one would put the estimate exactly where
`Salary(stated=True)` can pick it up. That is the getmanfred scale bug, one layer
up, and the task names it.

**A source that fabricates uniformly is detected, not consumed.**
`connectors/ruled-out.yaml`'s fourth test: remoteok stamped the identical
`USD 80000-150000 YEAR` onto 48 of 50 adverts, one of them a car dealership whose
own text states GBP 28,000, and marked none of them. *A spot check on any single
advert passes; the spread is what exposes it.* So `house_estimate_bands` reads the
spread across a source before any duplicate donates its band, and a
present-but-zero figure — getmanfred's `salaryFrom: 0` sentinel — is refused as
what it is rather than stored as a wage.

## How the text is read, and why it refuses so much

A wrong figure shown to a candidate is far worse than a missing one, because they
will act on it. Every rule below therefore resolves ambiguity by returning
nothing:

* **A figure must carry a currency.** `€`, `$`, `£`, `EUR`, `USD`, `GBP`, `euros`
  — adjacent, before or after. This is the rule that keeps `14` out of "per 14
  pagues" and `8` out of "Beneficios8% DESCUENTO".
* **A figure must sit beside a pay cue** — `salari(o)`, `sou`, `sueldo`,
  `retribució(n)`, `remuneración`, `salary`, `compensation`, `wage`, or a
  gross marker (`brut`, `bruto`, `gross`, `b/a`). Cue and figure must share a
  *segment*, so "Salary: competitive. Home office budget of €500." reads as
  silence. Every money trap in the committed corpus — a €1.000 training budget, a
  €3.000 laptop budget, a $500 home-office allowance, a $400M Series D, "$60
  million+ from Insight Partners" — is refused by this rule alone, because none
  of them is near a pay cue. `pay` and `ote` are cues only with an adjacent
  qualifier: bare, "We pay our AWS bill of 45,000 EUR per year" is a salary.
* **A figure governed by a noun that is not a wage is refused**, on either side
  of it: "we offer $100,000 in equity" and "equity worth up to $100,000" are the
  same sentence twice. The noun governs unless an explicit *wage* noun stands
  between it and the figure, which is what keeps "$50,000 + commission" and
  "Base salary $130,000 - $160,000" reading as the salaries they are.
* **A parenthetical is read as written unless it excludes.** "(excluding equity
  and bonus)" is blanked because naming those nouns is how it says the band
  holds neither; "(equity, not salary)" and "(this is the equity component)" are
  not, because they say the opposite. Discriminating on the bracket rather than
  on the verb deleted both kinds and let the second through.
* **Net pay is refused outright.** `Salary` has no gross/net field, so a net
  figure stored here would be compared against gross figures everywhere else.
  Catalan's bare `net` is matched, and `.NET` is not (the lookbehind).
* **Two readings mean no reading.** Two figures in one segment that are not a
  range, two segments that disagree, two currencies, two conflicting period
  words, **two duplicates whose bands differ**: all return `None`. A segment
  naming two periods is not the same as a segment naming none — collapsing them
  let "Sou brut: 6.000 € al mes, amb revisió anual" be read as €6.000 *a year*,
  a €72k role shown at a twelfth of its value as a stated fact.
* **Every figure is bounds-checked for its period, on every route.** A number
  outside the range a real wage occupies is a misparse whatever produced it, and
  "whatever produced it" includes a donor's `salary` field and an estimator:
  `_band_defect` is the one place that decides, and `Recovered` cannot be
  constructed around it.

## Stated ceilings

* **A bare number is never read**, so "Salari mensual brut 1800" — one advert in
  the committed corpus — is silence to us. Requiring the currency is what makes
  every trap above cheap to refuse; recovering that one advert would cost the
  guard.
* **Contractor rates are not read.** "Typical rates: $120-$170/hr" has no pay cue
  in this vocabulary. Adding `rate` would also admit "exchange rate", "success
  rate"; the corpus advert that has it also quotes three different rates, which
  the two-readings rule would refuse anyway.
* **A monthly figure is stored as monthly.** No annualising: "14 pagues" makes
  x12 wrong and x14 a guess, and the period is a field `Salary` already has.
* **A figure whose period is on another line is not read.** feinaactiva serves
  a structured block — `Salario\\nTipo (bruto)Mes\\nSalario mínimo1.300 €\\nSalario
  máximo1.600 €` — where "Mes" is one line above the figures, and the rule that
  cue, figure and period share a segment is what refuses it. That rule is also
  what refuses every money trap above, so the trade is deliberate: one advert in
  the committed corpus, against the guard that makes the rest safe.
* **A band that depends on where you live is refused.** "targeted at
  $180,000/yr to $200,000/yr in Denver … $220,000/yr to $245,000/yr for San
  Francisco" states two bands, and choosing one for a candidate whose location we
  have not matched against the advert's is picking at random.
* **The card shows the generic basis, not this offer's.** T95's `ESTIMATE_BASIS`
  is one constant on the card; `Recovered.basis` carries the per-offer provenance
  in the data. Threading it into `presentation.card` is a change to T95's
  surface, not this one's.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from math import isfinite
from pathlib import Path
from typing import Any, Literal

# Both private, both deliberately reused rather than reimplemented.
# `_as_float` is the audited thousands/decimal disambiguator: re-deriving it
# here is how "1.234,56" becomes 1.23456 for the second time.
from integral.connectors import _as_float
from integral.corpus import load_ads
from integral.dedup import find_duplicates
from integral.offers import Offer, Salary, compute_offer_id
from integral.presentation import ESTIMATED_MARKER, _salary

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T92.json"

#: The three languages the candidate track supports. `corpus.LANGUAGES` says the
#: same thing; repeated here because the per-language census is this module's
#: parity evidence and must not silently shrink to whatever the corpus holds.
LANGUAGES: tuple[str, ...] = ("es", "ca", "en")

#: Floors, not counts of the day (T100). A census that reports a clean zero over
#: an empty scan is the failure this whole increment is about.
MINIMUM_CORPUS_ADS = 150
#: Raised from 40 when the second-reader audit landed 54 more cases: a floor
#: that sits far below the set it guards stops guarding anything. Still a floor
#: — never the count of the day.
MINIMUM_WORDING_CASES = 120

Route = Literal["advert_text", "duplicate", "detail_page", "estimate"]

#: Every route, in the order `recover` attempts them — cheapest first.
ROUTES: tuple[Route, ...] = ("advert_text", "duplicate", "detail_page", "estimate")


class SalaryRecoveryError(Exception):
    """A caller asked for something this module refuses to do."""


# ---------------------------------------------------------------------------
# Reading a band out of advert text


# A segment is the span a cue and its figure must share. Split on sentence ends
# (followed by whitespace, so "1.850" survives), newlines and bullets — never on
# a dash, which is the range glue in "$45,000 - $50,000".
_SEGMENT_SPLIT = re.compile(r"(?<=[.;!?])\s+|[\n\r]+|\s*[•·▪|]\s*")

#: The nouns that mean *this job's wage* and nothing else. Narrower than
#: `_CUE` on purpose: `_disqualified` uses this set to decide whether a wage
#: noun stands between a figure and a "not a wage" noun, and a gross marker
#: cannot play that part — "Gross package … in stock options" is gross
#: *something*, and the something is not pay. `pay` and `ote` are out for the
#: same reason (see `_CUE`): both are leaky enough to need a qualifier before
#: they mean anything, and a leaky cue is not evidence a figure is a wage.
_WAGE_NOUN = re.compile(
    r"\b(?:salari|salaris|salario|salarios|salarial|sou|sous|sueldo|sueldos"
    r"|remuneraci[oó]|remuneraci[oó]n|retribuci[oó]|retribuci[oó]n"
    r"|salary|compensation|remuneration|wage|wages)\b",
    re.IGNORECASE,
)

#: A pay cue. Gross markers count: tecnoempleo's list card prints
#: "30.000€ - 36.000€ b/a" with no pay noun anywhere near it.
#:
#: `pay` and `ote` are **not** bare alternatives. Bare, `pay` is a verb far more
#: often than a noun — "We pay our AWS bill of 45,000 EUR per year" and "our OTE
#: model: customers pay 45,000 EUR per year for the product" both became
#: salaries — so each needs an adjacent qualifier: an adjective in front of
#: `pay`, or a colon / `range|scale|rate|band` behind it; a colon, `of`, or a
#: money token beside `ote`. "Pay: £15.50 per hour" still reads.
_CUE = re.compile(
    r"\b(?:salari|salaris|salario|salarios|salarial|sou|sous|sueldo|sueldos"
    r"|remuneraci[oó]|remuneraci[oó]n|retribuci[oó]|retribuci[oó]n"
    r"|salary|compensation|remuneration|wage|wages"
    r"|brut|bruta|bruts|brutes|bruto|brutos|brutas|gross)\b"
    r"|\b(?:base|gross|total|annual|monthly|weekly|hourly|daily|basic|starting)\s+pay\b"
    r"|\bpay\s*(?::|\b(?:range|scale|rate|band)\b)"
    r"|\bote\s*(?::|\bof\b)|[\d€$£]\s*\bote\b"
    r"|\bb/a\b|\bb/m\b",
    re.IGNORECASE,
)

#: Net pay, refused. The lookbehind is what keeps `.NET` out of a Catalan rule:
#: Catalan's word for net *is* "net", and a tech advert naming ASP.NET beside a
#: salary would otherwise lose its band.
_NET = re.compile(
    r"(?<![.\w])nets?(?![\w])"
    r"|\bnet[oa]s?\b|\bnetes\b|\bl[ií]quid[oa]s?\b"
    r"|take[-\s]home|\ben mano\b",
    re.IGNORECASE,
)

#: An amount, with the currency that must be adjacent to it. Both currency
#: groups are optional so bare numbers are still *found* — they are needed to
#: recognise "30.000 - 36.000 €", where only the last member carries the symbol
#: — but a group with no currency anywhere in it is discarded before it can
#: become a band.
#:
#: A whitespace thousands separator — the ES/CA/FR typographic convention, and
#: what U+00A0 and U+202F exist for — is read only in a *valid grouping*: one to
#: three digits, then runs of exactly three. That is what still keeps
#: "Publicado 28/08/2026 30.000€" reading as 30.000€ rather than as one
#: 202,630,000-euro number: "2026" is a four-digit leading group, so the grouped
#: alternative cannot start there and the plain alternative stops at the space.
#: All three renderings of "30 000" now read identically — before this, U+00A0
#: parsed, U+202F silently did not, and a plain space was not admitted at all.
_MONEY = re.compile(
    r"(?P<pre>US\$|€|\$|£|EUR|USD|GBP)?[ \u00a0\u202f]{0,2}"
    r"(?P<num>\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?|\d[\d.,]*\d|\d)"
    r"[ \u00a0\u202f]{0,2}(?P<k>[kK](?![A-Za-z]))?"
    r"[ \u00a0\u202f]{0,2}"
    r"(?P<post>€|\$|£|EUR|USD|GBP|euros|euro|eurs|d[oó]lares|libras)?",
    re.IGNORECASE,
)

# ponytail: `$` is USD wherever it appears, with no locale check. That is wrong
# for MXN, CAD, AUD, ARS, CLP and COP, all of which write `$`, and it is wrong
# *loudly*: "Salario bruto anual de 600.000 $ en Ciudad de México" is a ~17x
# overstatement presented to the candidate as a figure the employer stated. It
# is not fixed here because no committed connector fetches from any of those
# markets, so the fix would be untested guesswork and the guess ("Mexico in the
# text ⇒ MXN") is a location parser this module has no business growing.
# Upgrade path, when the first such connector lands: the connector already
# declares its market in `connectors/<name>/meta.yaml`, so pass that market in
# and let it choose the symbol's meaning — `band_in_text` gains a keyword
# argument, `_CURRENCIES` gains a per-market table, and the three cases pinned
# in `WORDING_CASES` under (h) flip from USD to the right currency. Until then
# they pin what this actually does, so the next connector's author reads it in
# the fixtures rather than in a candidate's ranked list.
_CURRENCIES: dict[str, str] = {
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "eurs": "EUR",
    "$": "USD",
    "us$": "USD",
    "usd": "USD",
    "dolares": "USD",
    "dólares": "USD",
    "£": "GBP",
    "gbp": "GBP",
    "libras": "GBP",
}

#: What may sit between two figures and still leave them one range. Anything
#: else — a comma, "más", "plus" — makes them two readings, and two readings
#: mean no reading.
_GLUE = re.compile(
    r"^\s*(?:[-\u2013\u2014/]|a|y|e|i|to|and|hasta|fins\s+a|fins|up\s+to"
    r"|(?:salari|salario|sou|sueldo)\s*m[aáà]xim[oa]?)\s*$",
    re.IGNORECASE,
)

#: Money that is not this job's wage.
#:
#: The vocabulary is the same in all three languages or it is a parity failure
#: (#294): `acci[oó](?:nes|ns|n)?` covers ES `acción`/`acciones` **and** CA
#: `acció`/`accions`, which the ES-only form missed — "Accions per valor de
#: 90.000 € bruts anuals" read as a €90k salary while its Spanish twin was
#: refused. English `commission` is deliberately absent: `comiss?i[oó]…` matches
#: `comisión`/`comissió` and cannot reach it, because "$50,000 + commission" is
#: a salary with a commission on top and must stay one.
_NOT_A_WAGE = re.compile(
    r"\b(?:equity|stock|shares|rsus?|acci[oó](?:nes|ns|n)?|participacions?"
    r"|bonus|bono|bonificaci[oó]n|incentivos?|referral"
    r"|budget|presupuesto|pressupost|allowance|ayuda|ajuda"
    r"|diet(?:es|as|a)|comiss?i[oó](?:nes|ns|n)?|aportaci[oó](?:nes|ns|n)?"
    r"|salary\s+sacrifice|relocation|home\s+office"
    r"|funding|revenue|facturaci[oó]n|turnover|valuation)\b",
    re.IGNORECASE,
)

_PARENTHETICAL = re.compile(r"\([^()]*\)")

#: The verb that makes a parenthetical name a disqualifier in order to *exclude*
#: it. "(excluding equity and bonus)" says the band contains neither, so reading
#: those two nouns as disqualifiers inverts the sentence. Every other
#: parenthetical is read as written — the old rule stripped all of them, which is
#: what let "(equity, not salary)" and "(this is the equity component)" through.
#: The discrimination is on the verb, never on the bracket.
_EXCLUSION = re.compile(
    r"\b(?:excluding|excluded|excludes|not\s+included|sin\s+incluir|exclou)\b",
    re.IGNORECASE,
)

#: A lone figure preceded by one of these is a ceiling, not a floor.
_UPPER = re.compile(r"\b(?:hasta|fins\s+a|up\s+to|m[aá]xim[oa]?|maximum)\b\s*$", re.IGNORECASE)

_PERIODS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "year",
        re.compile(
            r"\banual(?:s|es)?\b|\ba[nñ]o\b|\bb/a\b|/\s*a[nñ]o\b"
            r"|per\s+annum\b|\bp\.a\.|per\s+year\b|/\s*(?:yr|year)\b"
            r"|\byearly\b|\bannual(?:ly)?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "month",
        re.compile(
            r"\bmensual(?:s|es)?\b|\bmes\b|al\s+mes\b|/\s*mes\b|\bb/m\b|\bpcm\b"
            r"|per\s+month\b|/\s*month\b|\bmonthly\b",
            re.IGNORECASE,
        ),
    ),
    (
        "day",
        re.compile(r"\bdiari[oa]?s?\b|\bd[ií]a\b|per\s+day\b|/\s*day\b|\bdaily\b", re.IGNORECASE),
    ),
    (
        "hour",
        re.compile(
            r"\bhora\b|\bhores\b|\bhoras\b|per\s+hour\b|/\s*h(?:ora|our|r)?\b|\bhourly\b",
            re.IGNORECASE,
        ),
    ),
)

#: A **pay period** `_BOUNDS` has no entry for. `_CUE` already accepts
#: `weekly pay`, and `_PERIODS` has no week pattern, so such a segment reached
#: the size-inference branch below as "no period word at all" and any figure
#: ≥ 5.000 was stored as a *stated annual* band: "Weekly pay: 6,000 EUR" read as
#: EUR 6.000 a year. A period this module cannot represent is refused, never
#: inferred — the same rule as a segment naming two of them.
#:
#: Scoped to **pay periods only**, which is the whole difficulty. "Retribució
#: mensual bruta (12 pagues i 40h setmanals) 1458€" states hours per week, not a
#: wage per week, and a bare `setmanal`/`semanal` alternative would refuse an
#: advert that reads correctly today. So the week word counts only after a
#: period marker (`per`, `a la`, `/`, `cada`) or directly beside a wage noun.
#: The fortnight forms are here for the same reason as the weekly ones and not
#: because a corpus advert uses them: `_BOUNDS` cannot bound either.
_UNBOUNDED_PERIOD = re.compile(
    r"(?:/\s*|\bper\s+|\ba\s+(?:la\s+)?|\bpor\s+|\bcada\s+)"
    r"(?:week|setmana|semana|quinzena|quincena|fortnight)\b"
    r"|\b(?:weekly|setmanals?|semanal(?:es)?|quinzenals?|quincenal(?:es)?|fortnightly)\s+"
    r"(?:pay|salary|wage|salari|salario|sou|sueldo|paga|retribuci[oó]n?|remuneraci[oó]n?)\b"
    r"|\b(?:pay|salary|wage|salari|salario|sou|sueldo|paga|retribuci[oó]n?|remuneraci[oó]n?)\s+"
    r"(?:brut[oa]?s?\s+|brutes\s+)?"
    r"(?:weekly|setmanals?|semanal(?:es)?|quinzenals?|quincenal(?:es)?|fortnightly)\b",
    re.IGNORECASE,
)

#: "1.800 € per 12 pagues" states a *monthly* wage: the Spanish and Catalan
#: convention is that a figure quoted with a payment count is the payment. Only
#: consulted when no explicit period word is present, so "anual … (12 pagues)"
#: still reads as annual rather than as a contradiction.
_PAYMENTS = re.compile(r"\b\d{1,2}\s*pag(?:a|as|ues|es)\b", re.IGNORECASE)

#: Any mention of money at all — the honest denominator for "how much did the
#: parser recover", since most adverts state no salary and never could.
_MENTIONS_MONEY = re.compile(r"[€$£]|\bEUR\b|\bUSD\b|\bGBP\b|\beuros?\b", re.IGNORECASE)

#: What a real wage looks like, per period. A figure outside its range is a
#: misparse whatever produced it — and this is also what stops an inferred
#: annual period from turning a €500 allowance into a salary.
_BOUNDS: dict[str, tuple[float, float]] = {
    "year": (5_000.0, 1_000_000.0),
    "month": (300.0, 100_000.0),
    "day": (30.0, 5_000.0),
    "hour": (3.0, 1_000.0),
}


def _currency_of(match: re.Match[str]) -> str | None:
    for group in ("pre", "post"):
        token = match.group(group)
        if token:
            return _CURRENCIES.get(token.lower())
    return None


#: `_as_float` removes the plain space and U+00A0 and leaves U+202F, so a narrow
#: no-break space reached it as a letter and came back `None`. Removed here
#: instead, once, for all three renderings.
_THOUSANDS_WHITESPACE = str.maketrans("", "", " \u00a0\u202f")


def _value_of(match: re.Match[str]) -> float | None:
    value = _as_float(match.group("num").translate(_THOUSANDS_WHITESPACE))
    if value is None:
        return None
    return value * 1000 if match.group("k") else value


def _periods_in(segment: str) -> tuple[str, ...]:
    """Every period this segment names — none, one, or a contradiction.

    The three answers must stay distinguishable at the call site. Collapsing a
    contradiction into `None` made "Sou brut: 6.000 € al mes, amb revisió anual"
    — ordinary ES/CA boilerplate — indistinguishable from a segment with no
    period word at all, and the caller then inferred "year" from the figure's
    size: a €72k role shown as €6k, as a fact the employer stated.
    """
    named = tuple(name for name, pattern in _PERIODS if pattern.search(segment))
    if named:
        return named
    # "1.800 € per 12 pagues" states a monthly wage; only consulted when no
    # explicit period word is present.
    return ("month",) if _PAYMENTS.search(segment) else ()


def _without_exclusions(segment: str) -> str:
    """The segment with any *exclusion* parenthetical blanked, same length.

    Length-preserving because `_disqualified` compares offsets against the
    figure's span in the original segment.
    """
    parts = list(segment)
    for match in _PARENTHETICAL.finditer(segment):
        if _EXCLUSION.search(match.group()):
            parts[match.start() : match.end()] = " " * (match.end() - match.start())
    return "".join(parts)


def _disqualified(segment: str, start: int, end: int) -> bool:
    """Is the figure at `[start, end)` governed by a noun that is not a wage?

    A `_NOT_A_WAGE` noun governs the figure **unless an explicit wage noun
    stands between the two**. That is the whole rule, and it holds on both
    sides: the old one looked only at the text before the figure, so
    "Salary package: we offer $100,000 in equity" and "Sou: 90.000 € bruts
    anuals en accions" both read as stated salaries.

    Scanning outward from the figure to each disqualifier is what keeps
    "$50,000 + commission" — the case the prefix-only rule existed for — and
    "Base salary $130,000 - $160,000" working: nothing disqualifying lies
    between the figure and its own noun. It is also what refuses
    "Gross pay includes 20,000 EUR as an annual bonus", where the only thing
    between the figure and `bonus` is "as an annual", and `pay` is not a wage
    noun (see `_WAGE_NOUN`).
    """
    text = _without_exclusions(segment)
    for match in _NOT_A_WAGE.finditer(text):
        if match.end() <= start:
            between = text[match.end() : start]
        elif match.start() >= end:
            between = text[end : match.start()]
        else:
            between = ""  # it overlaps the figure; nothing can stand between
        if not _WAGE_NOUN.search(between):
            return True
    return False


def _band_in_segment(segment: str) -> Salary | None:
    """The one band this segment states, or `None` if it states none or two."""
    if not _CUE.search(segment) or _NET.search(segment):
        return None
    matches = list(_MONEY.finditer(segment))
    if not matches:
        return None

    # Group figures joined by range glue, then keep only groups whose members
    # carry a currency between them.
    groups: list[list[re.Match[str]]] = [[matches[0]]]
    for previous, current in pairwise(matches):
        if _GLUE.match(segment[previous.end() : current.start()]):
            groups[-1].append(current)
        else:
            groups.append([current])

    banded = [group for group in groups if any(_currency_of(m) for m in group)]
    if len(banded) != 1:
        return None  # nothing priced, or two priced things — either way, silence
    group = banded[0]
    if len(group) > 2:
        return None
    if _disqualified(segment, group[0].start(), group[-1].end()):
        return None  # the noun governing this figure is not "salary"

    currencies = {_currency_of(m) for m in group if _currency_of(m)}
    if len(currencies) != 1:
        return None
    currency = currencies.pop()

    values = [_value_of(m) for m in group]
    if any(value is None for value in values) or not all(values):
        return None  # unreadable, or a `salaryFrom: 0` sentinel
    figures = sorted(value for value in values if value is not None)

    named = _periods_in(segment)
    if len(named) > 1:
        return None  # the segment says two things; it has said nothing
    if named:
        period = named[0]
    else:
        # No period word *at all* — which is not the same as two, and inferring
        # from the figure's size is only sound here. A four-figure sum with a
        # pay cue beside it is an annual salary in every market this tool
        # covers; anything smaller could equally be monthly, daily or an
        # allowance, and is refused.
        #
        # …unless the segment names a pay period `_BOUNDS` cannot bound, which
        # is not "no period" either: it is a period we cannot store, and
        # inferring annual from it is how "Weekly pay: 6,000 EUR" became a
        # €6.000 year.
        if _UNBOUNDED_PERIOD.search(segment):
            return None
        if figures[0] < _BOUNDS["year"][0]:
            return None
        period = "year"

    low, high = _BOUNDS[period]
    if any(value < low or value > high for value in figures):
        return None

    if len(figures) == 2:
        return Salary(min=figures[0], max=figures[1], currency=currency, period=period, stated=True)
    only = figures[0]
    if _UPPER.search(segment[: group[0].start()]):
        return Salary(max=only, currency=currency, period=period, stated=True)
    return Salary(min=only, currency=currency, period=period, stated=True)


def band_in_text(text: str) -> Salary | None:
    """The band this advert states in its body, or `None`.

    Every segment is read, and they must agree: an advert quoting two different
    salaries has not stated one, and picking either is picking at random.
    """
    found: list[Salary] = []
    for segment in _SEGMENT_SPLIT.split(text):
        band = _band_in_segment(segment)
        if band is not None and band not in found:
            found.append(band)
    return found[0] if len(found) == 1 else None


# ---------------------------------------------------------------------------
# A source that fabricates uniformly


BandKey = tuple[float | None, float | None, str | None, str | None]

#: How many adverts must carry the identical band, and what share of that
#: source's stated bands it must be, before the band is read as a house
#: estimate. remoteok's shape was 48 of 50; five is low enough to catch a small
#: sample of the same behaviour and high enough that two employers landing on
#: the same round number is not an accusation.
HOUSE_ESTIMATE_MINIMUM = 5
HOUSE_ESTIMATE_FRACTION = 0.5


def band_key(salary: Salary) -> BandKey:
    return (salary.min, salary.max, salary.currency, salary.period)


def house_estimate_bands(
    offers: Sequence[Offer],
    *,
    minimum: int = HOUSE_ESTIMATE_MINIMUM,
    fraction: float = HOUSE_ESTIMATE_FRACTION,
) -> frozenset[tuple[str, BandKey]]:
    """`(source, band)` pairs where the source stamps one band on most of its
    adverts — `connectors/ruled-out.yaml`'s fourth test, run over a batch.

    The spread, not a spot check: any single one of remoteok's 48 rows looked
    exactly like a board that publishes salaries.
    """
    per_source: dict[str, Counter[BandKey]] = defaultdict(Counter)
    for offer in offers:
        if offer.salary is not None and offer.salary.stated:
            per_source[offer.source][band_key(offer.salary)] += 1
    return frozenset(
        (source, band)
        for source, counts in per_source.items()
        for band, count in counts.items()
        if count >= minimum and count >= fraction * sum(counts.values())
    )


# ---------------------------------------------------------------------------
# The four lookups


def _band_defect(salary: Salary) -> str | None:
    """Why this band may not be shown to a candidate, or `None` if it may.

    The same rules `_band_in_segment` already applies to text — a figure must
    exist, **carry a currency**, be a real number, be positive (RO4's *"zero is
    not a wage"*, the `salaryFrom: 0` sentinel), have a floor no higher than its
    ceiling, and sit inside `_BOUNDS` for its period. The currency rule was the
    one left behind: `_band_in_segment` refuses an unpriced figure outright, but
    a donor or an estimator could hand the card a bare `45000 to 55000` with
    nothing saying of what. `_band_in_segment` and `_usable_donor`
    enforced them on two of the four routes; the estimate route validated the
    `stated` flag and nothing else, so `nan`, `inf`, `-50000` and `1e12` all
    rendered on the card. A band with no period is bounded as annual: the widest
    band any period allows would be no check at all.
    """
    figures = [figure for figure in (salary.min, salary.max) if figure is not None]
    if not figures:
        return "a recovery with no figure is not a recovery"
    if not salary.currency:
        return f"a figure with no currency is a bare number: {salary!r}"
    if not all(isfinite(figure) for figure in figures):
        return f"a figure that is not a finite number: {salary!r}"
    if any(figure <= 0 for figure in figures):
        return f"zero is not a wage: {salary!r}"
    if salary.min is not None and salary.max is not None and salary.min > salary.max:
        return f"a floor above its own ceiling: {salary!r}"
    bounds = _BOUNDS.get(salary.period or "year")
    if bounds is None:
        return f"a period this module cannot bound: {salary.period!r}"
    low, high = bounds
    if any(figure < low or figure > high for figure in figures):
        return f"outside what a real {salary.period or 'annual'} wage looks like: {salary!r}"
    return None


@dataclass(frozen=True)
class Recovered:
    """One figure, and where it came from.

    `basis` is prose a candidate can read. It lives here rather than on
    `Salary` because §5.2's offer has no provenance field and adding one is how
    an estimate ends up somewhere `Salary(stated=True)` can pick it up.
    """

    salary: Salary
    route: Route
    basis: str
    donor_id: str | None = None

    def __post_init__(self) -> None:
        if not self.basis.strip():
            raise SalaryRecoveryError(f"a {self.route} recovery with no basis is a bare number")
        if self.route == "estimate" and self.salary.stated:
            raise SalaryRecoveryError("an estimate may never be stated")
        # Every route, not just the two that parse text. This is the last place
        # a figure can be stopped before a candidate reads it.
        defect = _band_defect(self.salary)
        if defect is not None:
            raise SalaryRecoveryError(f"a {self.route} recovery is not a wage: {defect}")


def is_silent(offer: Offer) -> bool:
    """No figure at all. A `Salary` carrying only a currency is still silence."""
    salary = offer.salary
    return salary is None or (salary.min is None and salary.max is None)


def _usable_donor(donor: Offer, house_bands: frozenset[tuple[str, BandKey]]) -> bool:
    salary = donor.salary
    if salary is None or not salary.stated or is_silent(donor):
        return False
    if (donor.source, band_key(salary)) in house_bands:
        return False
    # The same rules the text route applies, so a donor cannot import a band
    # `_band_in_segment` would have refused — `salaryFrom: 0` included. Checked
    # here rather than left to `Recovered`, so an unusable donor is skipped for
    # the next one instead of raising out of `recover`.
    return _band_defect(salary) is None


DetailReader = Callable[[Offer], str | None]
Estimator = Callable[[Offer], tuple[Salary, str] | None]


def recover(
    offer: Offer,
    *,
    donors: Sequence[Offer] = (),
    detail_reader: DetailReader | None = None,
    estimator: Estimator | None = None,
    house_bands: frozenset[tuple[str, BandKey]] = frozenset(),
) -> tuple[Recovered | None, tuple[Route, ...]]:
    """Look for this offer's salary, and report every route that was tried.

    The second element is what makes "dropped only after both lookups"
    checkable: a caller that drops an offer can be asked which lookups it
    performed first, and an unattempted route is the defect this task names.
    """
    if not is_silent(offer):
        return None, ()

    attempted: list[Route] = ["advert_text"]
    band = band_in_text(offer.text)
    if band is not None:
        return Recovered(band, "advert_text", "stated in the body of this advert"), tuple(attempted)

    attempted.append("duplicate")
    donated = [
        (donor, donor.salary)
        for donor in donors
        if donor.id != offer.id and _usable_donor(donor, house_bands) and donor.salary is not None
    ]
    wanted = offer.salary.currency if offer.salary is not None else None
    if wanted is not None:
        # The recipient already says which currency this job pays in. A donor
        # band in another one is not this job's band, whatever the join says.
        donated = [pair for pair in donated if pair[1].currency in (None, wanted)]
    # Two donors that disagree are two readings, and two readings mean no
    # reading — `band_in_text`'s own rule, applied across the copies of one
    # advert rather than within one. Returning the first usable donor made the
    # answer depend on the order `find_duplicates` happened to yield: EUR 45-55k
    # and USD 150-190k for the same job, whichever came first.
    if len({band_key(salary) for _, salary in donated}) == 1:
        donor, salary = donated[0]
        return (
            Recovered(
                salary,
                "duplicate",
                f"stated by the same advert on {donor.source}",
                donor_id=donor.id,
            ),
            tuple(attempted),
        )

    if detail_reader is not None:
        attempted.append("detail_page")
        detail = detail_reader(offer)
        if detail:
            band = band_in_text(detail)
            if band is not None:
                return (
                    Recovered(
                        band, "detail_page", f"stated on this advert's page on {offer.source}"
                    ),
                    tuple(attempted),
                )

    if estimator is not None:
        attempted.append("estimate")
        estimated = estimator(offer)
        if estimated is not None:
            salary, basis = estimated
            # Not a request: whatever the estimator claimed, an estimate is
            # never stated. This is the only place the flag is set, so an
            # estimator that lies cannot launder its band into a claim.
            estimate = salary.model_copy(update={"stated": False})
            # The same discipline `_usable_donor` gives the duplicate route, for
            # the same reason. `Recovered.__post_init__` raises on a defective
            # band, which is right for a direct constructor call and wrong here:
            # this band is caller-supplied, so a single estimator returning
            # `nan` used to raise out of `recover`, out of `recover_all`, and
            # discard every other offer's recovery in the batch. A bad estimate
            # costs its own offer and nothing else.
            if basis.strip() and _band_defect(estimate) is None:
                return Recovered(estimate, "estimate", basis), tuple(attempted)

    return None, tuple(attempted)


@dataclass(frozen=True)
class RecoveryReport:
    """What a batch's silent offers turned into."""

    recovered: dict[str, Recovered]
    attempted: dict[str, tuple[Route, ...]]
    dropped: tuple[str, ...]
    silent: tuple[str, ...]
    house_bands: frozenset[tuple[str, BandKey]]

    def routes_missed(self, available: Iterable[Route]) -> dict[str, tuple[Route, ...]]:
        """For every dropped offer, the routes that existed and were not tried.

        This is the gate. "Nobody looked for the figure" is the accusation, and
        an empty answer here is the only thing that refutes it.
        """
        wanted = tuple(available)
        return {
            offer_id: tuple(route for route in wanted if route not in self.attempted[offer_id])
            for offer_id in self.dropped
            if any(route not in self.attempted[offer_id] for route in wanted)
        }


def recover_all(
    offers: Sequence[Offer],
    *,
    detail_reader: DetailReader | None = None,
    estimator: Estimator | None = None,
) -> RecoveryReport:
    """Run every lookup over a batch, once. Duplicate pairs and the
    house-estimate spread are both batch-wide facts, so both are computed here
    rather than per offer."""
    # A donor's band counts whether it arrived in the `salary` field or in the
    # body of its own advert. The task's case is a connector that left `salary`
    # unmapped on *both* copies while one of them prints the band in its text:
    # reading only the field would leave that figure one join away and unjoined.
    by_id: dict[str, Offer] = {}
    for offer in offers:
        band = band_in_text(offer.text) if is_silent(offer) else None
        by_id[offer.id] = offer if band is None else offer.model_copy(update={"salary": band})
    house_bands = house_estimate_bands(list(by_id.values()))
    partners: dict[str, list[Offer]] = defaultdict(list)
    for match in find_duplicates(offers):
        partners[match.offer_a].append(by_id[match.offer_b])
        partners[match.offer_b].append(by_id[match.offer_a])

    recovered: dict[str, Recovered] = {}
    attempted: dict[str, tuple[Route, ...]] = {}
    dropped: list[str] = []
    silent: list[str] = []
    for offer in offers:
        if not is_silent(offer):
            continue
        silent.append(offer.id)
        found, tried = recover(
            offer,
            donors=partners[offer.id],
            detail_reader=detail_reader,
            estimator=estimator,
            house_bands=house_bands,
        )
        attempted[offer.id] = tried
        if found is None:
            dropped.append(offer.id)
        else:
            recovered[offer.id] = found
    return RecoveryReport(
        recovered=recovered,
        attempted=attempted,
        dropped=tuple(dropped),
        silent=tuple(silent),
        house_bands=house_bands,
    )


def applied(offer: Offer, found: Recovered) -> Offer:
    """The offer carrying its recovered figure. `stated` comes from `Recovered`,
    which already forced it `False` for an estimate."""
    return offer.model_copy(update={"salary": found.salary})


# ---------------------------------------------------------------------------
# The fixture the gate reads


def _band(
    low: float | None,
    high: float | None,
    currency: str,
    period: str,
) -> Salary:
    return Salary(min=low, max=high, currency=currency, period=period, stated=True)


#: Wording, and the band the wording states. Derived from the committed corpus
#: and from the task text **before** the parser was written, so the cases are
#: not a description of what the code already does. Every `None` is a deliberate
#: refusal, and the comment beside it says which rule refuses it.
WORDING_CASES: tuple[tuple[str, str, Salary | None], ...] = (
    # --- Spanish -----------------------------------------------------------
    ("es", "Salario según convenio - 26.000€ b/a", _band(26000, None, "EUR", "year")),
    ("es", "Salario: 30.000€ - 36.000€ brutos anuales", _band(30000, 36000, "EUR", "year")),
    ("es", "Desde 24.000 € brutos anuales", _band(24000, None, "EUR", "year")),
    ("es", "Salario: hasta 40.000 € brutos/año", _band(None, 40000, "EUR", "year")),
    ("es", "A partir de 35.000 euros brutos anuales", _band(35000, None, "EUR", "year")),
    (
        "es",
        "Salario Tipo (bruto)Mes Salario mínimo1.300 € Salario máximo1.600 €",
        _band(1300, 1600, "EUR", "month"),
    ),
    ("es", "Retribución: 45.000 € - 55.000 €", _band(45000, 55000, "EUR", "year")),
    (
        "es",
        "Banda salarial: 40.000 \u20ac \u2013 48.000 \u20ac brutos/a\u00f1o",
        _band(40000, 48000, "EUR", "year"),
    ),
    ("es", "Sueldo: 2.000 € al mes (14 pagas)", _band(2000, None, "EUR", "month")),
    ("es", "Salario: 1.234,56 €/mes", _band(1234.56, None, "EUR", "month")),
    ("es", "Remuneración: 18€/hora", _band(18, None, "EUR", "hour")),
    ("es", "Salario neto de 1.800 € al mes", None),  # net is refused outright
    ("es", "Sueldo líquido de 1.900 € mensuales", None),  # net, other wording
    (
        "es",
        "Salario competitivo. Presupuesto de formación personal: 1.000 € "
        "para que sigas aprendiendo.",
        None,
    ),  # the cue and the figure are in different segments
    ("es", "Salario: 30.000€ anuales, más 1.000€ de bonus", None),  # two readings
    ("es", "Salario 30.000 € anuales o 2.500 € mensuales", None),  # two period words
    ("es", "Sueldo de 1.200 €", None),  # no period, and too small to be annual
    ("es", "Salario: 1.234.567 € brutos anuales", None),  # outside the annual bounds
    ("es", "Salario: 25.000-30.000", None),  # no currency
    ("es", "Salario mínimo interprofesional", None),  # a cue with no figure
    ("es", "Salario fijo más un 10% variable", None),  # a percentage is not a figure
    ("es", "Salario bruto anual de 0 €", None),  # the `salaryFrom: 0` sentinel
    # --- Catalan -----------------------------------------------------------
    ("ca", "Sou: 1.850 € bruts mensuals per 14 pagues", _band(1850, None, "EUR", "month")),
    ("ca", "Salari brut anual 20.184,34 euros (12 pagues)", _band(20184.34, None, "EUR", "year")),
    (
        "ca",
        "Ofereix: sou brut mensual negociable entre 1.571,43€ i 2.285,71€ (amb 14 pagues)",
        _band(1571.43, 2285.71, "EUR", "month"),
    ),
    ("ca", "Sou brut 1.800 a 2.000 € per 12 pagues.", _band(1800, 2000, "EUR", "month")),
    ("ca", "Retribució econòmica: 17,00 € bruts / hora.", _band(17.0, None, "EUR", "hour")),
    ("ca", "Rang salarial: 28.750 €", _band(28750, None, "EUR", "year")),
    (
        "ca",
        "Retribució competitiva: 31.000€ bruts anuals aproximats (segons conveni SISCAT - Grup 5)",
        _band(31000, None, "EUR", "year"),
    ),
    (
        "ca",
        "Retribució mensual bruta (12 pagues i 40h setmanals) 1458€",
        _band(1458, None, "EUR", "month"),
    ),
    ("ca", "Sou 1100 euros bruts mensuals.", _band(1100, None, "EUR", "month")),
    ("ca", "Fins a 2.100 € bruts mensuals", _band(None, 2100, "EUR", "month")),
    ("ca", "Salari: 30.000 € bruts anuals", _band(30000, None, "EUR", "year")),
    ("ca", "Sou net de 1.400 € mensuals", None),  # Catalan's bare "net"
    ("ca", "Salari mensual brut 1800", None),  # no currency — the stated ceiling
    ("ca", "Sou a convenir segons vàlua", None),  # a cue with no figure
    # --- English -----------------------------------------------------------
    ("en", "Salary - $45,000 - $50,000 USD + commission", _band(45000, 50000, "USD", "year")),
    (
        "en",
        "Annual base salary range (excluding equity and bonus): $152,405 — $179,300 USD",
        _band(152405, 179300, "USD", "year"),
    ),
    ("en", "Salary: £28,000 per annum", _band(28000, None, "GBP", "year")),
    ("en", "Compensation: £80k - £120k", _band(80000, 120000, "GBP", "year")),
    ("en", "Pay: £15.50 per hour", _band(15.5, None, "GBP", "hour")),
    ("en", "Salary: up to £45,000", _band(None, 45000, "GBP", "year")),
    ("en", "Gross salary of €3,000 per month", _band(3000, None, "EUR", "month")),
    ("en", "Salary: €50,000-€70,000 gross per year", _band(50000, 70000, "EUR", "year")),
    (
        "en",
        "Salary: £450 per day for the duration of the contract",
        _band(450, None, "GBP", "day"),
    ),
    ("en", "Net salary of £2,000 per month", None),  # net
    ("en", "Take-home pay of €1,900 per month", None),  # net, other wording
    ("en", "A $500 home office setup allowance", None),  # no pay cue
    ("en", "We raised $60 million+ from Insight Partners", None),  # no pay cue
    (
        "en",
        "The company's momentum was validated by a $400M Series D financing round",
        None,
    ),  # no pay cue
    ("en", "Your laptop: you will have a budget of €3.000 to set everything up.", None),
    ("en", "USD Remuneration Profit Sharing Maternity Coverage", None),  # cue, no figure
    ("en", "Typical rates: $120-$170/hr", None),  # contractor rates — stated ceiling
    ("en", "Salary of €50,000 per year, plus a €5,000 signing bonus", None),  # two readings
    (
        "en",
        "Salary: competitive. Home office budget of €500.",
        None,
    ),  # different segments
    (
        "en",
        "We are an ASP.NET shop. Salary: £55,000 - £65,000 per annum",
        _band(55000, 65000, "GBP", "year"),
    ),  # `.NET` must not read as net pay
    # --- Second pass: wording the first pass did not anticipate ------------
    # Written against the rules above rather than against the parser, and run
    # before the parser was finished. The one marked FAIL-OPEN is the defect
    # this pass found: the parser read an equity grant as a salary.
    (
        "en",
        "Compensation includes equity worth up to $100,000 over four years",
        None,
    ),  # FAIL-OPEN, fixed: equity is not a wage
    ("en", "Salary from $60,000 up to $80,000", _band(60000, 80000, "USD", "year")),
    (
        "en",
        "Base salary $130,000 - $160,000. Equity: $200,000 - $400,000.",
        _band(130000, 160000, "USD", "year"),
    ),
    ("en", "Salary range: $95,000 to $120,000 per year", _band(95000, 120000, "USD", "year")),
    ("en", "Wage: £11.44 per hour (national living wage)", _band(11.44, None, "GBP", "hour")),
    ("en", "Salary: £2,500 pcm", _band(2500, None, "GBP", "month")),
    ("en", "Compensation: 120K USD annually", _band(120000, None, "USD", "year")),
    ("en", "Salary: we offer a $1,000 referral bonus and a gym membership", None),
    ("en", "Gross domestic product of €2.000.000 — we are a fintech", None),
    (
        "es",
        "Salario 30.000 € brutos anuales para la sede de Madrid y 36.000 € para Zurich",
        None,
    ),  # two offices, two figures, no single band
    (
        "es",
        "El salario está entre 30.000 y 36.000 euros brutos anuales",
        _band(30000, 36000, "EUR", "year"),
    ),
    (
        "es",
        "Salario: desde 18.000 € hasta 24.000 € brutos anuales",
        _band(18000, 24000, "EUR", "year"),
    ),
    ("es", "Salario: 3.000.000 € brutos anuales", None),  # outside the annual bounds
    ("es", "Salario: 30k - 40k € brutos anuales", _band(30000, 40000, "EUR", "year")),
    ("es", "Salario bruto mensual 1.200 € x 14 pagas", _band(1200, None, "EUR", "month")),
    ("es", "Salario: 1.400 euros netos al mes", None),  # net
    ("es", "Salario: se valorará experiencia. Plus de transporte de 200 € al mes.", None),
    ("ca", "Salari brut anual: de 25.000 a 30.000 euros", _band(25000, 30000, "EUR", "year")),
    (
        "ca",
        "Salaris d'entre 1.400 i 1.800 euros bruts mensuals",
        _band(1400, 1800, "EUR", "month"),
    ),
    ("ca", "Salari: 20€ bruts/hora", _band(20, None, "EUR", "hour")),
    (
        "ca",
        "Retribució bruta anual 45.000 € (12 pagues) + variable del 10%",
        _band(45000, None, "EUR", "year"),
    ),
    ("ca", "Retribució: 1.500 €/mes nets", None),  # Catalan plural "nets"
    ("ca", "Sou: a convenir. Ajuda de menjador de 11 € diaris.", None),  # a meal allowance
    # --- The named ceilings, pinned as cases so they cannot drift silently --
    (
        "es",
        "Salario\nTipo (bruto)Mes\nSalario mínimo1.300 €\nSalario máximo1.600 €",
        None,
    ),  # feinaactiva's block: the period is a line above the figures
    (
        "en",
        "Our cash compensation amount for this role is targeted at $180,000/yr to "
        "$200,000/yr in Denver, and $220,000/yr to $245,000/yr for San Francisco.",
        None,
    ),  # two bands, one per location
    (
        "ca",
        "El salari inicial serà de 1.800 euros bruts incrementant-se progressivament.",
        None,
    ),  # no period stated, and too small to be an annual figure
    # --- Third pass: a second reader's adversarial cases ---------------------
    # Every case below was written from the rules in this docstring and run
    # **before** the fix, and every one of them was read as a stated salary by
    # the parser that shipped a green gate. They are grouped by the defect they
    # caught, so a regression names its own cause.
    #
    # (a) `_NOT_A_WAGE` was scoped to the text *before* the figure, so the noun
    # that governs a figure from behind never disqualified anything.
    ("en", "Salary package: we offer $100,000 in equity.", None),
    ("en", "Gross package: 50,000 EUR in stock options per year.", None),
    ("en", "Gross pay includes 20,000 EUR as an annual bonus.", None),
    ("es", "Salario: 10.000 € anuales en acciones.", None),
    ("ca", "Sou: 90.000 € bruts anuals en accions.", None),
    ("en", "Gross compensation: 15,000 EUR per year of equity vesting.", None),
    # (b) Every parenthetical was stripped before `_NOT_A_WAGE` read the
    # segment, which deleted the disqualifying ones along with the excluding
    # one. The verb decides now, not the bracket.
    ("en", "Compensation up to $100,000 (equity, not salary).", None),
    ("en", "Gross package of 80,000 EUR per year (this is the equity component).", None),
    (
        "es",
        "Salario bruto anual (sin incluir bonus ni acciones): 40.000 € - 50.000 €",
        _band(40000, 50000, "EUR", "year"),
    ),  # the exclusion parenthetical still reads as the salary it is
    # (c) Two period words collapsed into "no period", and "no period" inferred
    # "year" from the figure's size — a €72k role shown to the candidate as €6k.
    ("ca", "Sou brut: 6.000 € al mes, amb revisió anual.", None),
    ("es", "Salario bruto de 6.000 € al mes, con revisión anual.", None),
    ("en", "Gross pay 6,000 EUR per month, reviewed annually.", None),
    ("es", "Salario bruto de 8.000 € mensuales en 14 pagas anuales.", None),
    ("en", "Gross salary 30,000 EUR per year, paid monthly.", None),
    # (d) `_NOT_A_WAGE` was ES-only where it should have been ES/CA/EN (#294),
    # and six nouns were missing outright. The ES twin already refused; its
    # Catalan form did not, which is the exact shape of a parity failure.
    ("ca", "Accions per valor de 90.000 € bruts anuals.", None),
    ("ca", "Acció de l'empresa valorada en 90.000 € bruts anuals.", None),
    ("es", "Acciones por valor de 90.000 € brutos anuales.", None),  # the twin, still refused
    ("es", "Dietas de 30 € brutos diarios.", None),
    ("ca", "Dietes de 30 € bruts diaris.", None),
    ("es", "Comisión bruta anual de hasta 20.000 €.", None),
    ("ca", "Comissió bruta anual de fins a 20.000 €.", None),
    ("es", "Plan de pensiones: aportación bruta de 6.000 € anuales.", None),
    ("en", "Gross salary sacrifice scheme worth 6,000 EUR per year.", None),
    ("en", "We pay a relocation package of up to 8,000 EUR per year.", None),
    ("en", "We pay for your home office, up to 5,000 EUR per year.", None),
    # (e) One case in eighty-two exercised `_NOT_A_WAGE`, out of twenty-two
    # alternatives. An unexercised alternative is an untested one, and this is
    # the branch that decides whether an equity grant is a wage.
    ("en", "Gross salary of $90,000 per year in stock.", None),
    ("en", "Gross compensation of £70,000 per year in shares.", None),
    ("en", "Gross compensation of $120,000 per year in RSUs.", None),
    ("ca", "Sou brut anual de 40.000 € en participacions.", None),
    ("es", "Sueldo bruto anual más un bono de 6.000 €.", None),
    ("es", "Bonificación bruta anual de 8.000 €.", None),
    ("es", "Incentivos brutos anuales de hasta 12.000 €.", None),
    ("en", "Gross referral award of £6,000 per year.", None),
    ("en", "Gross training budget of €6,000 per year.", None),
    ("es", "Presupuesto bruto anual de 6.000 € para formación.", None),
    ("ca", "Pressupost brut anual de 6.000 € per a formació.", None),
    ("en", "Gross allowance of €7,000 per year for equipment.", None),
    ("es", "Ayuda bruta anual de 6.000 € para transporte.", None),
    ("ca", "Ajuda bruta anual de 6.000 € per al transport.", None),
    ("en", "Gross funding of £900,000 per year for the lab.", None),
    ("en", "Gross revenue of £900,000 per year.", None),
    ("es", "Facturación bruta anual de 900.000 €.", None),
    ("en", "Gross turnover of £900,000 per year.", None),
    ("en", "Our gross valuation rose by £900,000 per year.", None),
    # (f) `pay` and `ote` were bare alternatives in `_CUE`, so a sentence about
    # what the company pays *out* became a salary.
    ("en", "We pay our AWS bill of 45,000 EUR per year.", None),
    ("en", "Our OTE model: customers pay 45,000 EUR per year for the product.", None),
    ("en", "OTE: £60,000 per annum", _band(60000, None, "GBP", "year")),  # the real use survives
    # (g) The three renderings of a whitespace thousands separator. U+00A0
    # parsed, U+202F silently returned nothing, and a plain space was not
    # admitted; they agree now, and the date hazard the module docstring names
    # still reads as the salary it is rather than as 202,630,000 euros.
    ("es", "Salario bruto anual de 30\u00a0000 €", _band(30000, None, "EUR", "year")),
    ("es", "Salario bruto anual de 30\u202f000 €", _band(30000, None, "EUR", "year")),
    ("es", "Salario bruto anual de 30 000 €", _band(30000, None, "EUR", "year")),
    (
        "es",
        "Publicado 28/08/2026 30.000€ brutos anuales",
        _band(30000, None, "EUR", "year"),
    ),  # four-digit leading group ⇒ "2026 30.000" is never one number
    # (h) `$` is read as USD wherever it appears — a known ceiling, pinned here
    # rather than fixed. See the `ponytail:` note beside `_CURRENCIES`.
    (
        "es",
        "Salario bruto anual de 600.000 $ en Ciudad de México",
        _band(600000, None, "USD", "year"),
    ),  # MXN read as USD: a 17x overstatement, and today's behaviour
    ("en", "Gross salary of $95,000 per year in Toronto", _band(95000, None, "USD", "year")),
    ("en", "Gross salary of $110,000 per year in Sydney", _band(110000, None, "USD", "year")),
    # --- Fourth pass: a review round on the third ---------------------------
    # (i) A pay period `_BOUNDS` cannot bound reached the size-inference branch
    # as "no period word at all", and any figure ≥ 5.000 was then stored as a
    # **stated annual** band. `_CUE` already accepted `weekly pay`, so the cue
    # existed and the period did not: "Weekly pay: 6,000 EUR" read as EUR 6.000
    # a *year*, a fifty-second of what the advert says, as a fact the employer
    # stated. Same class as (c) — a period the module cannot represent must be
    # refused, never inferred. Every one of these read as an annual band before
    # `_UNBOUNDED_PERIOD` existed.
    ("en", "Weekly pay: 6,000 EUR", None),
    ("en", "Salary: 6,000 GBP per week", None),
    ("en", "Gross pay of 6,000 EUR a week", None),
    ("es", "Salario semanal: 6.000 €", None),
    ("es", "Salario de 6.000 € a la semana", None),
    ("es", "Salario quincenal: 6.000 € brutos", None),
    ("ca", "Sou setmanal: 6.000 €", None),
    ("ca", "Sou brut de 6.000 € per setmana", None),
    # …and the cases the scoping exists for, which read correctly *before* this
    # pass and must still read after it. "40h setmanals" states hours per week,
    # not a wage per week: a bare `setmanal`/`semanal` alternative would refuse
    # both of these, which is a fail-closed regression traded for the fix above.
    # The second names no bounded period at all, so it is the one that actually
    # reaches the branch `_UNBOUNDED_PERIOD` guards.
    (
        "ca",
        "Retribució mensual bruta de 1.458 € (40h setmanals)",
        _band(1458, None, "EUR", "month"),
    ),
    (
        "ca",
        "Sou brut de 30.000 € en una jornada de 40h setmanals",
        _band(30000, None, "EUR", "year"),
    ),
    (
        "es",
        "Salario bruto de 30.000 € en una jornada de 40h semanales",
        _band(30000, None, "EUR", "year"),
    ),
)


def _offer(source: str, text: str, salary: Salary | None = None) -> Offer:
    return Offer(id=compute_offer_id(text), source=source, text=text, salary=salary)


_HOUSE_BAND = Salary(min=80000, max=150000, currency="USD", period="year", stated=True)

#: Long enough for `dedup.find_duplicates` to pair two copies of it, so the
#: blast-radius check measures the join rather than two unrelated adverts.
_POISON_BODY = (
    "Staff platform engineer, remote within the EU. You will own the deployment "
    "pipeline end to end, working in Go and Terraform against a Kubernetes "
    "estate, and you will be the person other teams ask before they ship. We "
    "care about the parts of the job nobody writes down: on-call that is humane, "
    "reviews that are read, and a runbook that is true."
)


def _house_estimate_fixture() -> list[Offer]:
    """`connectors/ruled-out.yaml`'s fourth test, in miniature: one board that
    stamps the same band on nearly everything, and one that does not.

    The car dealership is the row that made the real case obvious — its own
    text states GBP 28,000 while the board's structured field claims the house
    band — so it is here too, as the duplicate that must not be poisoned.
    """
    offers = [
        _offer(
            "houseboard",
            f"Remote engineering role number {index}, working across our platform team.",
            _HOUSE_BAND,
        )
        for index in range(9)
    ]
    offers.append(
        _offer(
            "houseboard",
            "Vehicle progressor, Dunfermline. Basic salary of GBP 28,000 plus bonus.",
            _HOUSE_BAND,
        )
    )
    offers.append(
        _offer(
            "honestboard",
            "Data engineer in Barcelona, working on the ingestion pipeline every day.",
            Salary(min=42000, max=52000, currency="EUR", period="year", stated=True),
        )
    )
    return offers


# ---------------------------------------------------------------------------
# Measurement


def _check_wording() -> tuple[int, int, list[str]]:
    """Every case reads as the spec requires, over a set that has not shrunk.

    The floor is checked **here** and not only in `tests/`, which is
    `naming.MINIMUM_SCANNED`'s defect one module over: `_check_wording` reported
    only misread cases, so `WORDING_CASES` could fall under
    `MINIMUM_WORDING_CASES` and `_main` would still return 0 — a clean zero over
    a set small enough to mean nothing. It is a defect rather than an
    `unmeasured` verdict on purpose: `Makefile`'s `evidence` target maps exit 3
    to "unmeasured (recorded)" and carries on, so a 3 here would not fail
    `make evidence`. `_main` folds this into its exit 1.
    """
    defects = []
    for language, text, expected in WORDING_CASES:
        actual = band_in_text(text)
        if actual != expected:
            defects.append(f"[{language}] {text!r}: expected {expected!r}, read {actual!r}")
    if len(WORDING_CASES) < MINIMUM_WORDING_CASES:
        defects.append(
            f"only {len(WORDING_CASES)} wording cases; the floor is {MINIMUM_WORDING_CASES}"
        )
    return len(defects), len(WORDING_CASES), defects


def corpus_offers() -> list[Offer]:
    """Every committed advert as an `Offer` with no salary field — which is
    exactly the row round 3 dropped, 208 times over.

    The corpus carries no `salary` key at all, so every one of these is silent
    by construction. That makes it the honest denominator for the gate: the
    lookups run over real adverts in three languages rather than over two
    strings written to be dropped.
    """
    offers: list[Offer] = []
    seen: set[str] = set()
    for ad in load_ads():
        text = str(ad.get("text", ""))
        offer_id = compute_offer_id(text)
        if offer_id in seen:
            continue
        seen.add(offer_id)
        offers.append(Offer(id=offer_id, source=str(ad.get("source", "corpus")), text=text))
    return offers


def _check_corpus(report: RecoveryReport) -> tuple[int, int, list[str], dict[str, dict[str, int]]]:
    """Read every committed advert, and check our own spread.

    The census is the parity evidence: a parser that only reads English is a
    silent partial feature (issue #294), and the only way to see that is to
    count what it recovers per language against what there was to read.

    The defect is the one `connectors/ruled-out.yaml` names, turned on
    ourselves: if *we* produce the identical band from most of one source's
    adverts, we are the thing stamping a house estimate.

    `mentions_money` is there because `recovered / read` is not a rate: most
    adverts state no salary at all, so a low share is the market rather than
    the parser. What a reader wants is how many of the adverts that name money
    turned into a band, and how that differs between the three languages.

    `recovered` counts the **whole** recovery — every route `report` used, not
    only what `band_in_text` read. Counting the text route alone made the census
    total 17 against `corpus_recovered_by_route`'s 18: the one advert recovered
    from a duplicate had no language bucket at all, and two numbers in the same
    evidence file disagreed about how many adverts were recovered.
    """
    ads = load_ads()
    blank = {"read": 0, "mentions_money": 0, "recovered": 0}
    census: dict[str, dict[str, int]] = {language: dict(blank) for language in LANGUAGES}
    per_source: dict[str, Counter[BandKey]] = defaultdict(Counter)
    # `corpus_offers` dedupes by offer id and keeps the first advert with that
    # text, so the census must resolve a recovery to a language the same way.
    language_of: dict[str, str] = {}
    for ad in ads:
        language = str(ad.get("language", ""))
        census.setdefault(language, dict(blank))
        census[language]["read"] += 1
        text = str(ad.get("text", ""))
        language_of.setdefault(compute_offer_id(text), language)
        if _MENTIONS_MONEY.search(text):
            census[language]["mentions_money"] += 1
        band = band_in_text(text)
        if band is not None:
            per_source[str(ad.get("source", ""))][band_key(band)] += 1
    for offer_id in report.recovered:
        language = language_of.get(offer_id, "")
        census.setdefault(language, dict(blank))
        census[language]["recovered"] += 1

    defects = [
        f"we read the identical band {band!r} out of {count} of {source}'s adverts"
        for source, counts in per_source.items()
        for band, count in counts.items()
        if count >= HOUSE_ESTIMATE_MINIMUM
        and count >= HOUSE_ESTIMATE_FRACTION * sum(counts.values())
    ]
    if len(ads) < MINIMUM_CORPUS_ADS:
        defects.append(f"only {len(ads)} adverts scanned; the floor is {MINIMUM_CORPUS_ADS}")
    return len(defects), len(ads), defects, census


#: Bands no route may ever produce. Every one of them rendered on the card
#: before `_band_defect` ran on all four routes — `nan EUR/year (estimated —
#: the advert did not say)` is what the estimate route printed, because the only
#: thing it checked was the `stated` flag.
_IMPOSSIBLE_BANDS: tuple[Salary, ...] = (
    Salary(min=float("nan"), currency="EUR", period="year", stated=False),
    Salary(min=40000, max=float("inf"), currency="EUR", period="year", stated=False),
    Salary(min=-50000, currency="EUR", period="year", stated=False),
    Salary(min=0, max=0, currency="EUR", period="year", stated=False),
    Salary(min=90000, max=10000, currency="EUR", period="year", stated=False),
    Salary(min=1e12, currency="EUR", period="year", stated=False),
    # A bare number with no unit. `_band_in_segment` refuses a figure with no
    # currency outright — it is the rule that keeps "14" out of "per 14 pagues"
    # — but `_band_defect` did not, so a donor or an estimator could hand the
    # card `45000 to 55000` with nothing saying of what.
    Salary(min=45000, max=55000, period="year", stated=False),
)

_ESTIMATE_CHECKS = 6 + len(_IMPOSSIBLE_BANDS)


def _check_estimate() -> tuple[int, int, list[str]]:
    """An estimate may not reach `Salary(stated=True)`, may not reach the card
    unmarked, and may not be a number no wage could be. Three different lies:
    the flag, the label, and the figure itself.
    """
    defects: list[str] = []
    silent = _offer(
        "board", "A role the advert never priced, described in full over several lines."
    )

    def liar(_: Offer) -> tuple[Salary, str]:
        # Deliberately dishonest: claims the employer stated it.
        return (
            Salary(min=48000, max=58000, currency="EUR", period="year", stated=True),
            "from the range this role and level pays on comparable adverts",
        )

    found, attempted = recover(silent, estimator=liar)
    if found is None:
        defects.append("the estimate route produced nothing where an estimator was supplied")
        return len(defects), _ESTIMATE_CHECKS, defects
    if found.salary.stated:
        defects.append("an estimate reached Salary(stated=True)")
    if not found.basis.strip():
        defects.append("an estimate carried no basis")
    card_row = _salary(applied(silent, found))
    if ESTIMATED_MARKER not in card_row:
        defects.append(f"an estimate rendered without its marker: {card_row!r}")
    if "estimate" not in attempted:
        defects.append("the estimate route was not recorded as attempted")
    for band in _IMPOSSIBLE_BANDS:
        try:
            Recovered(band, "estimate", "from comparable adverts")
        except SalaryRecoveryError:
            continue
        defects.append(f"a figure no wage could be reached the card: {band!r}")

    # Blast radius, the other way round. `Recovered.__post_init__` refusing a
    # defective band is right for a direct constructor call and wrong as a way
    # to end a batch: the estimate route builds `Recovered` out of whatever the
    # caller's estimator returned, so one `nan` raised out of `recover`, out of
    # `recover_all`, and took every other offer's recovery with it. The
    # duplicate route already drops an unusable donor and keeps going; so does
    # this one now.
    poisoned = _offer(
        "boardone", "Data engineer in Barcelona owning the ingestion pipeline, Python and dbt."
    )
    sound = _offer(
        "boardtwo", "Night warehouse operative in Manresa, forklift licence, permanent contract."
    )

    def poisoner(offer: Offer) -> tuple[Salary, str]:
        if offer.id == poisoned.id:
            return (
                Salary(min=float("nan"), currency="EUR", period="year", stated=False),
                "from comparable adverts",
            )
        return (
            Salary(min=48000, max=58000, currency="EUR", period="year", stated=False),
            "from comparable adverts",
        )

    try:
        batch = recover_all([poisoned, sound], estimator=poisoner)
    except SalaryRecoveryError as error:
        defects.append(f"one defective estimate ended the whole batch: {error}")
    else:
        if poisoned.id in batch.recovered:
            defects.append(
                f"a defective estimate was recovered anyway: {batch.recovered[poisoned.id]!r}"
            )
        if sound.id not in batch.recovered:
            defects.append("a sound estimate was discarded alongside a defective one")
    return len(defects), _ESTIMATE_CHECKS, defects


def _check_duplicate_join() -> tuple[int, int, list[str]]:
    """A duplicate's band is taken; a house estimate's is not; a zero is not."""
    defects: list[str] = []
    fixture = _house_estimate_fixture()
    house = house_estimate_bands(fixture)
    if ("houseboard", band_key(_HOUSE_BAND)) not in house:
        defects.append("the house estimate stamped on 10 of 11 adverts was not detected")

    silent = _offer("aggregator", "Data engineer in Barcelona, working on the ingestion pipeline.")
    honest = fixture[-1]
    poisoned = fixture[0]
    zeroed = _offer(
        "sentinelboard",
        "Data engineer in Barcelona, working on the ingestion pipeline for us.",
        Salary(min=0, currency="EUR", period="year", stated=True),
    )

    found, _ = recover(silent, donors=[honest], house_bands=house)
    if found is None or found.route != "duplicate" or found.donor_id != honest.id:
        defects.append("a duplicate stating a band did not supply the silent copy")
    elif not found.salary.stated:
        defects.append("a figure the employer stated on another board was demoted to an estimate")

    found, _ = recover(silent, donors=[poisoned], house_bands=house)
    if found is not None:
        defects.append(f"a house estimate was consumed as a stated band: {found.salary!r}")

    found, _ = recover(silent, donors=[zeroed], house_bands=house)
    if found is not None:
        defects.append(f"a `salaryFrom: 0` sentinel was consumed as a wage: {found.salary!r}")

    # Two donors that disagree, both orders. Returning the first usable donor
    # made the answer a function of list order: the same job priced at EUR
    # 45-55k or at USD 150-190k depending on which copy `find_duplicates`
    # yielded first.
    euros = _offer(
        "boardone",
        "Data engineer in Barcelona, ingestion pipeline, hybrid two days a week.",
        Salary(min=45000, max=55000, currency="EUR", period="year", stated=True),
    )
    dollars = _offer(
        "boardtwo",
        "Data engineer in Barcelona, ingestion pipeline, hybrid two days per week.",
        Salary(min=150000, max=190000, currency="USD", period="year", stated=True),
    )
    for order in ([euros, dollars], [dollars, euros]):
        found, _ = recover(silent, donors=order, house_bands=house)
        if found is not None:
            defects.append(
                "two donors that contradict each other still donated a band "
                f"({[donor.source for donor in order]}): {found.salary!r}"
            )

    # The recipient says EUR; the donor's band is in USD. Whatever the join
    # matched, that is not this job's figure.
    in_euros = _offer(
        "aggregator",
        "Data engineer in Barcelona, working on the ingestion pipeline.",
        Salary(currency="EUR", stated=False),
    )
    found, _ = recover(in_euros, donors=[dollars], house_bands=house)
    if found is not None:
        defects.append(f"a donor band contradicted the recipient's currency: {found.salary!r}")

    # A band with no currency is a bare number. `_band_in_segment` refuses one
    # in text; `_usable_donor` delegates to `_band_defect`, which did not, and
    # the recipient filter admits `currency in (None, wanted)` — so a donor
    # carrying min/max/period and no unit donated `45000 to 55000` of nothing.
    unpriced = _offer(
        "unpricedboard",
        "Data engineer in Barcelona, working on the ingestion pipeline all week.",
        Salary(min=45000, max=55000, period="year", stated=True),
    )
    found, _ = recover(silent, donors=[unpriced], house_bands=house)
    if found is not None:
        defects.append(f"a donor band with no currency was consumed: {found.salary!r}")

    # A donor whose band is impossible is skipped, not raised out of `recover`.
    broken = _offer(
        "brokenboard",
        "Data engineer in Barcelona, working on the ingestion pipeline for them.",
        Salary(min=float("inf"), currency="EUR", period="year", stated=True),
    )
    try:
        found, _ = recover(silent, donors=[broken], house_bands=house)
    except SalaryRecoveryError as error:
        defects.append(f"an unusable donor raised instead of being skipped: {error}")
    else:
        if found is not None:
            defects.append(f"a non-finite donor band was consumed: {found.salary!r}")

    # Blast radius. `recover_all` writes each advert's parsed band back into the
    # donor pool as `Salary(stated=True)`, so one misparse does not stay in one
    # advert: it becomes the *stated* band on every near-duplicate, carrying a
    # basis that says another board's employer said it. One poisoned advert and
    # one twin is the smallest batch that measures it.
    poisoned = _offer("poisonboard", _POISON_BODY + " Salary package: we offer $250,000 in equity.")
    twin = _offer("mirrorboard", _POISON_BODY + " Apply on our portal for the full conditions.")
    spread = recover_all([poisoned, twin])
    if spread.recovered:
        blast = [f"{found.route}={found.salary!r}" for found in spread.recovered.values()]
        defects.append(
            f"an equity grant was read as a salary and donated to its duplicate: {blast}"
        )
    return len(defects), 11, defects


def _no_detail(_: Offer) -> str | None:
    return None  # no network here; the reader is the seam, not a fetcher


def _check_drop_discipline(report: RecoveryReport) -> tuple[int, int, list[str], dict[str, int]]:
    """The plan's metric: `salary_silent_offers_dropped_without_a_lookup`.

    Run over the committed corpus, not over a pair of strings. Two things are
    asserted, because the count alone is satisfiable by a run that looked at
    nothing: every dropped offer must have had all three available routes
    tried, **and** the routes must actually recover something — a lookup that
    is performed and never succeeds is the accusation restated, not answered.

    The report is passed in rather than built here so that `_check_corpus`'s
    per-language census counts the same recoveries this counts per route. Two
    passes over the corpus is how the evidence file came to hold 18 recoveries
    in one key and 17 in another.
    """
    available: tuple[Route, ...] = ("advert_text", "duplicate", "detail_page")
    missed = report.routes_missed(available)
    defects = [
        f"{offer_id} was dropped without trying {', '.join(routes)}"
        for offer_id, routes in missed.items()
    ]
    by_route = Counter(found.route for found in report.recovered.values())
    if not by_route:
        defects.append("every lookup ran and none of them ever recovered a figure")
    # Per route, not only in aggregate. The headline count is *structurally*
    # zero: `_check_drop_discipline` always supplies a `detail_reader`, so
    # `recover` always appends all three routes to `attempted` and
    # `routes_missed` can never be non-empty here. The protection that actually
    # bites is that each cheap route recovers something over the real corpus,
    # and it lived only in `tests/test_salary_recovery.py`. Mirrored here so the
    # evidence file stands on its own.
    for route in ("advert_text", "duplicate"):
        if not by_route.get(route):
            defects.append(f"no advert in the corpus was recovered by the {route} route")
    return (
        len(missed),
        len(report.silent) * len(available),
        defects,
        {route: by_route.get(route, 0) for route in available},
    )


def measure() -> dict[str, Any]:
    """T92's gate: `salary_silent_offers_dropped_without_a_lookup`, the name
    `status/plan.md` declares.

    Five checks, five denominators. The gate metric is the one the plan names,
    and the other four are recorded beside it and asserted by
    `tests/test_salary_recovery.py` — a defect in any of them fails this
    module's exit code too, because a green drop-discipline count over a parser
    that reads money wrongly is the failure this increment exists to catch.

    A count of zero over nothing checked is what a check that never ran also
    reports, so `gate_status` reads `unmeasured` while the denominator is
    empty, and `corpus_ads_at_least` / `wording_cases_at_least` are floors
    rather than counts of the day (T100).
    """
    offers = corpus_offers()
    # One pass over the corpus, read by both the per-route count and the
    # per-language census, so the two can never disagree about how many adverts
    # were recovered.
    report = recover_all(offers, detail_reader=_no_detail)
    wording, wording_seen, wording_defects = _check_wording()
    corpus, corpus_seen, corpus_defects, census = _check_corpus(report)
    estimate, estimate_seen, estimate_defects = _check_estimate()
    duplicate, duplicate_seen, duplicate_defects = _check_duplicate_join()
    dropped, dropped_seen, dropped_defects, by_route = _check_drop_discipline(report)

    defects = (
        wording_defects + corpus_defects + estimate_defects + duplicate_defects + dropped_defects
    )
    other = wording + corpus + estimate + duplicate
    return {
        "salary_silent_offers_dropped_without_a_lookup": dropped,
        "salary_silent_offers_dropped_without_a_lookup_evaluated": dropped_seen,
        "gate_status": "measured" if dropped_seen else "unmeasured",
        "silent_offers_evaluated": len(offers),
        "corpus_recovered_by_route": by_route,
        "wording_cases_misread": wording,
        "wording_cases_evaluated": wording_seen,
        "wording_cases_at_least": MINIMUM_WORDING_CASES,
        "corpus_house_estimates_of_our_own": corpus,
        "corpus_ads_evaluated": corpus_seen,
        "corpus_ads_at_least": MINIMUM_CORPUS_ADS,
        "corpus_recovery_by_language": census,
        "estimate_provenance_failures": estimate,
        "estimate_checks_evaluated": estimate_seen,
        "duplicate_join_failures": duplicate,
        "duplicate_join_checks_evaluated": duplicate_seen,
        "other_defects_total": other,
        "defects": defects,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Measure T92's salary recovery.")
    parser.add_argument("evidence", nargs="?", default=str(DEFAULT_EVIDENCE_PATH), type=Path)
    args = parser.parse_args(argv)
    measured = write_evidence(args.evidence)

    key = "salary_silent_offers_dropped_without_a_lookup"
    print(f"{key}: {measured[key]} (== 0) over {measured[key + '_evaluated']} checks")
    print(f"recovery by language: {json.dumps(measured['corpus_recovery_by_language'])}")
    if measured["gate_status"] == "unmeasured":
        print("nothing was evaluated; the gate cannot be scored", file=sys.stderr)
        return 3
    if measured["defects"]:
        for defect in measured["defects"]:
            print(defect, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
