"""T202 - an offer that is not the role the candidate is looking for is left out.

`sourcing.matches_aim` only ever narrowed an *unsteered* board, over title **and**
body, and a steered board's results were never looked at. Result on a live
round: 108 of 124 offers shown matched none of the candidate's six terms in the
title ("Offensive Security Engineer", "Administrativo/a Comercial Francés e
Inglés"), and a body that mentioned LLMs once was enough to pass an
administrative vacancy.

## What relevance is

A score over the **title** - the role - and only the title. The body of an
advert mentions everything its employer touches, so it is not evidence of what
the job is. The score is the best, over the candidate's search phrases, of

    (distinctive words of the phrase found in the title) / (distinctive words of the phrase)

A word is *generic* when more than half of the candidate's own phrases contain it
(`engineer` in `prompt engineer`, `applied ai engineer`, `agentic engineer`, ...):
it names the family of jobs, not the job, so finding it in a title proves
nothing. That is computed from the candidate's phrases, not listed, so there is
no job-title blocklist to go stale (the enumeration failure of #547): another
candidate's `data` aim has its own generic words. A phrase made only of generic
words uses all of them.

Both sides are first normalised by one closed table (`_PHRASES`, `_TOKENS`):
`GenAI`, `KI`, `IA`, `A.I.`, `Inteligencia Artificial` are `ai`, `Large Language
Model` is `llm`, `ingeniero/a` is `engineer`, `datos` is `data`. Then whole words
match, or a word plus a closed suffix (`eval`/`evals`, `llm`/`llmops`,
`agent`/`agentic`). Never a bare prefix: `java` is not `javascript`, `product` is
not `production`.

## The floor is the candidate's, not the code's

`search/relevance.json` holds `{"floor": 0.5, "related": [...]}`. An offer scoring
**below** the floor is left out; no file means *no filter* and nothing is
invented here. `related` is the other wording of the same aim (`rag engineer`,
`llmops`) that the step-07 expansion found and the candidate accepted: world
knowledge no word list in code can hold. A related phrase scores like an aim
phrase, but it does not decide which words are generic.

## Fail-open on everything unknown

A wrongly kept offer costs one row of reading; a wrongly dropped one costs a job
nobody is told about. So an offer with no title is kept, an unreadable floor
raises (never reads as "no filter"), and every exclusion is returned with its
score and nearest phrase so the round can print it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from integral.identity import IdentityError, ProfileStore, create_profile

RELEVANCE_FILE = ("search", "relevance.json")
_FUNCTION_WORDS = frozenset(
    [
        "de",
        "del",
        "la",
        "las",
        "el",
        "los",
        "un",
        "una",
        "en",
        "y",
        "e",
        "o",
        "of",
        "the",
        "a",
        "an",
        "and",
        "or",
        "for",
        "at",
        "in",
        "con",
        "para",
        "to",
        "with",
    ]
)
#: Offers the gate compares. Under it a clean zero rests on a thin scan.
MINIMUM_OFFERS_COMPARED = 20

#: One closed table, applied to the title **and** to the candidate's phrases, so
#: the two sides are always spelled the same way. Candidate-agnostic: it holds
#: what a word means in the job market (an abbreviation, the Spanish or German
#: word for a role), never which jobs are wanted.
_PHRASES = (
    (r"\ba\.\s?i\.?(?!\w)", "ai"),
    (r"\binteligencia artificial\b", "ai"),
    (r"\bkunstliche intelligenz\b", "ai"),
    (r"\blarge language models?\b", "llm"),
)
_TOKENS = {
    "genai": "generative ai",
    "gen": "generative",
    "generativa": "generative",
    "generativo": "generative",
    "ia": "ai",
    "ki": "ai",
    "rag": "llm",
    "produktmanager": "product manager",
    "ingeniero": "engineer",
    "ingeniera": "engineer",
    "ingenieur": "engineer",
    "desarrollador": "developer",
    "desarrolladora": "developer",
    "entwickler": "developer",
    "entwicklerin": "developer",
    "datos": "data",
    "daten": "data",
    "analista": "analyst",
    "gerente": "manager",
    "jefe": "manager",
    "cientifico": "scientist",
    "cientifica": "scientist",
}
#: What may follow a whole word and still be that word: `evals`, `llmops`,
#: `agentic`, `engineering`. Not `java`+`script` or `product`+`ion`.
_SUFFIXES = ("s", "es", "ops", "ic", "ing")


def _words(text: str) -> set[str]:
    from integral.sourcing import _words as words  # sourcing imports this module

    return words(text)


def _significant(text: str) -> frozenset[str]:
    folded = unicodedata.normalize("NFKD", text.casefold())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    for pattern, replacement in _PHRASES:
        folded = re.sub(pattern, f" {replacement} ", folded)
    out: set[str] = set()
    for word in _words(folded):
        out.update(_TOKENS.get(word, word).split())
    return frozenset(out - _FUNCTION_WORDS)


def same_word(a: str, b: str) -> bool:
    """The same whole word, or one with a closed suffix (`eval`/`evals`, `llm`/`llmops`)."""
    short, long_ = sorted((a, b), key=len)
    return short == long_ or (
        len(short) >= 3 and long_.startswith(short) and long_[len(short) :] in _SUFFIXES
    )


def _has(words: Iterable[str], word: str) -> bool:
    return any(same_word(word, other) for other in words)


@dataclass(frozen=True)
class Verdict:
    """One offer's relevance, with what a candidate needs to disagree with it."""

    relevant: bool
    score: float
    nearest: str | None
    because: str


@dataclass(frozen=True)
class RelevanceRule:
    """The candidate's phrases, their own floor, and the wording they accepted."""

    floor: float
    aim: tuple[str, ...]
    related: tuple[str, ...] = ()

    def _generic(self) -> frozenset[str]:
        phrases = [_significant(p) for p in self.aim if _significant(p)]
        if len(phrases) < 2:
            return frozenset()
        vocabulary = {w for p in phrases for w in p}
        return frozenset(
            w for w in vocabulary if 2 * sum(_has(p, w) for p in phrases) > len(phrases)
        )

    def score(self, title: str) -> tuple[float, str | None]:
        """Best share of a phrase's distinctive words found in `title`, and that phrase."""
        generic = self._generic()
        have = _significant(title)
        best, nearest = 0.0, None
        for phrase in (*self.aim, *self.related):
            words = _significant(phrase)
            if not words:
                continue
            need = frozenset(w for w in words if w not in generic) or words
            share = sum(_has(have, w) for w in need) / len(need)
            if share > best or nearest is None:
                best, nearest = share, phrase
        return best, nearest

    def judge(self, title: str | None) -> Verdict:
        if not (title or "").strip():
            return Verdict(True, 1.0, None, "no title to judge by, so kept")
        score, nearest = self.score(title or "")
        if score >= self.floor:
            return Verdict(True, score, nearest, f"score {score:.2f} >= floor {self.floor:.2f}")
        return Verdict(
            False,
            score,
            nearest,
            f"score {score:.2f} < floor {self.floor:.2f}; nearest of your phrases: «{nearest}»",
        )


def load_rule(store: ProfileStore, terms: Sequence[str]) -> RelevanceRule | None:
    """The candidate's rule, or `None` when no floor is recorded (no filter).

    A file that will not parse **raises**: an unreadable floor read as "no
    floor" is the filter quietly stopping.
    """
    if not terms or not store.exists(*RELEVANCE_FILE):
        return None
    where = "/".join(RELEVANCE_FILE)
    payload = store.read_json(*RELEVANCE_FILE)
    floor = payload.get("floor") if isinstance(payload, dict) else None
    related = payload.get("related", []) if isinstance(payload, dict) else None
    if (
        isinstance(floor, bool)
        or not isinstance(floor, int | float)
        or not 0 <= floor <= 1
        or not isinstance(related, list)
        or not all(isinstance(r, str) for r in related)
    ):
        raise IdentityError(
            f"{where} must be {{'floor': a number from 0 to 1, 'related': [phrases]}}"
        )
    return RelevanceRule(float(floor), tuple(terms), tuple(related))


def record(store: ProfileStore, floor: float, related: Sequence[str] = ()) -> Path:
    """Write the candidate's floor and accepted wording (validated by `load_rule`)."""
    path = store.write_json({"floor": floor, "related": list(related)}, *RELEVANCE_FILE)
    load_rule(store, ("x",))
    return path


# --- the gate -------------------------------------------------------------

AIM = (
    "prompt engineer",
    "applied ai engineer",
    "agentic engineer",
    "LLM engineer",
    "generative ai engineer",
    "ai evals",
)
#: Empty on purpose: the gate must pass on the table and the stems alone.
RELATED: tuple[str, ...] = ()
#: Seen on the live round of #552 (the first five), and further jobs that are not AI.
OFF_ROLE = (
    "Offensive Security Engineer",
    "Administrativo/a Comercial Francés e Inglés",
    "Aerial Robotics Research Engineer",
    "Quality Assurance Rater - Spanish ES",
    "Senior Software Engineer - Mobile",
    "Account Executive",
    "Senior Backend Engineer (Go)",
    "Customer Support Specialist",
    "Data Entry Clerk",
    "Mechanical Design Engineer",
    "Hardware Engineer",
    "Ingeniero de Redes",
    "Administrativo/a de Recursos Humanos",
    "Marketing Manager",
    "DevOps Engineer",
    "Ingeniero de Datos",
    "Produktmanager",
)
#: Wording the terms do not contain literally.
ON_AIM = (
    "LLMOps Engineer",
    "RAG Engineer",
    "Ingeniero/a de IA generativa",
    "Senior Prompt Engineer (m/f/d)",
    "AI Engineer",
    "Agentic AI Engineer",
    "Applied AI Engineer - Remote",
    "LLM Evaluation Specialist - AI Evals",
    "Generative AI Developer",
    "Ingeniero de Prompts",
    "GenAI Engineer",
    "Gen-AI Engineer",
    "Large Language Model Engineer",
    "A.I. Engineer",
    "KI Engineer",
    "Ingeniero/a de IA",
    "Ingeniera de Inteligencia Artificial",
)


def measure() -> dict[str, Any]:
    """Both directions, through the profile file: a floor written in code is not measured."""
    with tempfile.TemporaryDirectory() as root:
        create_profile(Path(root), "Test", handle="test", language="es", fiction=True)
        store = ProfileStore(Path(root), "test")
        record(store, 0.5, RELATED)
        rule = load_rule(store, AIM)
        if rule is None:
            raise IdentityError("the floor just recorded was not read back")
        presented = [t for t in (*OFF_ROLE, *ON_AIM) if rule.judge(t).relevant]
        return {
            "offers_compared": len(OFF_ROLE) + len(ON_AIM),
            "offers_presented_below_the_relevance_floor": sum(
                rule.score(t)[0] < rule.floor for t in presented
            ),
            "off_role_offers_presented": sum(t in presented for t in OFF_ROLE),
            "on_aim_offers_rejected": sum(t not in presented for t in ON_AIM),
        }


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="integral.relevance")
    parser.add_argument("--set-floor", type=float, help="record the floor (0 to 1)")
    parser.add_argument("--related", action="append", default=[], help="accepted wording")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--handle")
    args = parser.parse_args(argv)
    if args.set_floor is not None:
        if not (args.root and args.handle):
            parser.error("--set-floor needs --root and --handle")
        print(record(ProfileStore(args.root, args.handle), args.set_floor, args.related))
        return 0
    result = measure()
    print(json.dumps(result, indent=2))
    ok = (
        result["offers_presented_below_the_relevance_floor"] == 0
        and result["on_aim_offers_rejected"] == 0
        and result["off_role_offers_presented"] == 0
        and result["offers_compared"] >= MINIMUM_OFFERS_COMPARED
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
