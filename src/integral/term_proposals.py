"""T248 - search terms grow from the adverts a search finds, with the candidate's yes.

`search/aim.json` is written once, at step 7, from what the candidate could
think of. Five titles they would have searched for (applied AI engineer,
developer platform, ...) were found only by reading adverts a board
recommended; nothing proposed them. This module proposes them, deterministically,
from the offers a round stored, and writes **nothing** until the candidate says
yes.

**The rule.** A title is proposed when

1. it recurs in at least 2 *distinct vacancies*. One
   advert is an anecdote the candidate already saw; two is the smallest number
   that separates "a phrase the market uses" from "one employer's wording".
   Higher would starve a low-volume market, which is where an aim most needs
   growing. Distinct means distinct employers; adverts naming no employer
   count together as one, since a cross-posted one cannot be told from two.
   One vacancy cross-posted on three boards is one vacancy, and counting it
   thrice would propose a term from a single advert. Boards are reported
   (`boards`) and rank ties, so a title seen across boards sorts first;
2. it has at least `WORDS_NEEDED` (2) significant words once gender markers, level
   words, work-mode words, a trailing location, function words (`of`, `de`)
   and grade tokens (`II`, `2`) are removed - a bare `engineer` is
   not a search, it is the whole market;
3. no aim term already covers it: a board's AND-ed query for that term would
   match the title (`sourcing.matches_aim` - every word of the term is a whole
   word of the title), so `ai engineer` already finds `generative ai engineer`
   and `software engineer` does not cover `applied ai engineer`. No synonym
   folding: `developer` is not `engineer` to a board's query;
4. the candidate has not declined it: a declined term with the same set of
   significant words is not asked again (declining `ai engineer` does not hide
   `applied ai engineer`);
5. the advert is not about a topic the candidate ruled out
   (`search/exclusions.json`): a term must not be proposed from adverts the
   search would have dropped.

Ponytail: a location written as `en Barcelona`/`in Berlin` is not stripped (it
is indistinguishable from `en Telecomunicaciones`/`in Test`); only `- X`, `| X`,
`@ X`, `, X` and parentheses are. Such a title is proposed with its location and
the candidate declines or edits it.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from integral.identity import IdentityError, ProfileStore
from integral.offers import load_offer
from integral.same_vacancy import (
    _GENDER,
    _LEVEL_SPELLINGS,
    _LEVELS,
    _NOISE,
    _ROMAN,
    employer_key,
)
from integral.search_terms import AIM_FILE, load_aim
from integral.sourcing import _words, matches_aim, recorded_offer_ids
from integral.sourcing_exclusions import candidate_of, load_exclusions, ruled_out_by

DECLINED_FILE = ("search", "declined_terms.json")
WORDS_NEEDED = 2

_MODE = frozenset({"remote", "remoto", "hybrid", "hibrido", "onsite", "presencial"})
_SEPARATED_TAIL = re.compile(r"\s+[-\u2013\u2014|@]\s+.*$|,\s.*$")
#: `Ingeniero/a`, `desarrollador/a`: the slash-and-vowel gender form of one word.
_GENDER_SLASH = re.compile(r"(?<=[^\W\d_])/[ao]\b", re.IGNORECASE)
_STOP = _NOISE - {"software", "remote", "remoto", "hybrid", "hibrido", "onsite", "presencial"}
_PARENTHESES = re.compile(r"\([^)]*\)|\[[^\]]*\]")


def recurs(vacancies: int) -> bool:
    """Two distinct employers: one advert is an anecdote the candidate already saw,
    two is the smallest count that tells a market phrase from one employer's
    wording; three would starve a thin market (see the module docstring)."""
    return vacancies >= 2


class TermError(Exception):
    """A proposal could not be accepted or declined."""


def _is_stop_or_grade(word: str) -> bool:
    """A function word, or a grade (`II`, `iii`, `2`) - not part of what the role is."""
    return word in _STOP or word in _ROMAN or word.isdigit()


def clean_title(title: str, *, literal: bool = False) -> str:
    """The title as a search phrase: lowercase, no gender, level, mode or location.

    Unless `literal`, also without function words and grade tokens, so `Head of
    Data` is `data` and `Software Engineer II` is `software engineer`. The
    literal form keeps them, because a board's AND query reads them.
    """
    text = _PARENTHESES.sub(" ", title)
    text = _GENDER_SLASH.sub("", text)
    text = _GENDER.sub(" ", text.casefold())
    text = _SEPARATED_TAIL.sub("", text)
    kept = [
        w
        for w in re.findall(r"[^\W_]+(?:[+#]+)?", text)
        if _LEVEL_SPELLINGS.get(w, w) not in _LEVELS
        and w not in _MODE
        and (literal or not _is_stop_or_grade(w))
    ]
    return " ".join(kept)


def _key(term: str) -> frozenset[str]:
    """The significant words of `term` - no synonym folding, no function words
    or grades. Two terms are the same term when these sets are equal."""
    return frozenset(w for w in _words(term) if not _is_stop_or_grade(w))


def _covers(aim_terms: tuple[str, ...], phrase: str) -> bool:
    """Whether searching any aim term would already return this title.

    The repo's own query matching (`sourcing.matches_aim`): every word of the
    term is a whole word of the title. `software engineer` therefore covers
    `software engineer ai` and does not cover `applied ai engineer`.
    """
    return matches_aim({"title": phrase}, aim_terms)


def declined(store: ProfileStore) -> list[str]:
    if not store.exists(*DECLINED_FILE):
        return []
    payload = store.read_json(*DECLINED_FILE)
    if not isinstance(payload, dict) or not isinstance(payload.get("terms"), list):
        raise IdentityError(f"{'/'.join(DECLINED_FILE)} must be an object with a terms list")
    return [str(t) for t in payload["terms"]]


@dataclass
class Proposal:
    term: str
    vacancies: int
    boards: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)


def _offers(store: ProfileStore, ids: set[str]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for offer_id in sorted(ids):
        try:
            offer = load_offer(store, offer_id)
        except (IdentityError, ValueError):
            continue
        if offer.title:
            found.append(
                {
                    "title": offer.title,
                    "company": offer.company,
                    "source": offer.source,
                    "id": offer_id,
                    "offer": offer,
                }
            )
    return found


def propose(store: ProfileStore, offer_ids: set[str] | None = None) -> list[Proposal]:
    """Terms the stored adverts suggest and the aim lacks. Reads; never writes.

    `offer_ids` limits the read to one round's offers; by default every offer a
    recorded fetch produced.
    """
    aim = load_aim(store)
    if aim.state != "stated":
        return []
    ids = recorded_offer_ids(store) if offer_ids is None else offer_ids
    refused = [_key(t) for t in declined(store)]
    exclusions = load_exclusions(store)
    groups: dict[frozenset[str], list[tuple[str, str, str]]] = {}
    for offer in _offers(store, ids):
        if ruled_out_by(candidate_of(offer["offer"]), exclusions):
            continue
        phrase = clean_title(offer["title"])
        key = _key(phrase)
        if len(key) < WORDS_NEEDED or key in refused:
            continue
        if _covers(aim.terms, clean_title(offer["title"], literal=True)):
            continue
        employer = employer_key(offer.get("company"))
        who = "|".join(employer) if employer else "no-employer"
        groups.setdefault(key, []).append((who, str(offer.get("source", "")), phrase))
    proposals = []
    for rows in groups.values():
        vacancies = len({who for who, _, _ in rows})
        if not recurs(vacancies):
            continue
        shapes = Counter(phrase for _, _, phrase in rows)
        best = sorted(shapes, key=lambda p: (-shapes[p], len(p), p))
        boards = sorted({b for _, b, _ in rows if b})
        proposals.append(Proposal(best[0], vacancies, boards, best))
    return sorted(proposals, key=lambda p: (-len(p.boards), -p.vacancies, p.term))


def _write_declined(store: ProfileStore, terms: list[str]) -> None:
    store.write_json({"terms": terms}, *DECLINED_FILE)


def _norm(term: str) -> str:
    return " ".join(term.split()).casefold()


def accept(store: ProfileStore, term: str) -> list[str]:
    """The candidate's yes: append exactly `term` to the stored aim.

    Every other key of `search/aim.json` is written back as it was. An exact
    duplicate is refused rather than added twice; a previously declined term is
    un-declined, because an explicit yes outranks an earlier no.
    """
    term = " ".join(term.split())
    if not term or not _key(term):
        raise TermError("a term needs at least one word")
    if not store.exists(*AIM_FILE):
        raise TermError("there is no aim to add to; the candidate has not stated one")
    payload = store.read_json(*AIM_FILE)
    if not isinstance(payload, dict) or payload.get("state") != "stated":
        raise TermError("the aim is not stated; add terms through step 7, not here")
    terms = list(payload.get("terms", ()))
    if _norm(term) in {_norm(t) for t in terms}:
        raise TermError(f"{term!r} is already in the aim")
    terms.append(term)
    store.write_json({**payload, "terms": terms}, *AIM_FILE)
    current = declined(store)
    remaining = [t for t in current if _key(t) != _key(term)]
    if len(remaining) != len(current):
        _write_declined(store, remaining)
    return terms


def decline(store: ProfileStore, term: str) -> list[str]:
    """The candidate's no: remember it so `propose` never offers it again."""
    term = " ".join(term.split())
    if not term or not _key(term):
        raise TermError("a term needs at least one word")
    current = declined(store)
    if _key(term) not in [_key(t) for t in current]:
        current.append(term)
        _write_declined(store, current)
    return current


def _main(argv: list[str]) -> int:
    import argparse

    from integral.identity import default_profiles_root

    parser = argparse.ArgumentParser(prog="integral.term_proposals")
    parser.add_argument("action", choices=("propose", "accept", "decline"))
    parser.add_argument("--handle", required=True)
    parser.add_argument("--term")
    parser.add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    store = ProfileStore(args.root or default_profiles_root(), args.handle)
    if args.action == "propose":
        rows = [
            {"term": p.term, "vacancies": p.vacancies, "boards": p.boards, "seen_as": p.titles}
            for p in propose(store)
        ]
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not args.term:
        parser.error(f"{args.action} needs --term")
    try:
        result = (accept if args.action == "accept" else decline)(store, args.term)
    except TermError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
