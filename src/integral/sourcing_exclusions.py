"""T90 — a constraint the candidate stated is applied to the next search.

Twice the candidate said fintech and e-commerce were not of interest. Twice
more, frontend and cloud. All four kept arriving, and the candidate's own
diagnosis was the right question:

    Did you search for the ads all together at the beginning or are you
    adding filters with everything I'm telling you?

That question separates the two designs, and from the outside they are
indistinguishable **until the candidate rules something out and sees it
again**. A search executed once and re-sorted looks exactly like a search that
learns, right up to the moment it fails. The candidate reached that moment at
step 5 and lost confidence in the tool.

**A rank penalty is not an exclusion.** `weights.py` can push a fintech advert
to position 97 and it still appears, which is the observed behaviour and reads
as not listening. So the exclusion has to reach the *query*, before offers are
fetched — `next_query` is that path, and `Presentation.penalty_applied` exists
so the gate can say out loud that a demotion does not satisfy it.

**Note the asymmetry with `stated_constraints.py`**, which covers hard
constraints — permit, location, salary floor. A sector distaste is soft: it
must not silently delete a role that is otherwise a strong match. So the metric
is not "never fetched". It is that a restated exclusion is either honoured or
**named**, with the reason it survived, in words the candidate reads. An
override with no reason is not an override; it is the silent resurfacing with
an extra field attached, and `Override` refuses to be constructed that way.

What this does not buy: nothing here decides *when* a strong match is strong
enough to override. That is a judgement the ranking makes and this module only
requires it to be spoken.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from integral.identity import IdentityError, ProfileStore
from integral.offers import Offer

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T90.json"

#: Where what the candidate ruled out lives, beside the aim and for the same
#: reason (`search_terms.AIM_FILE`): a stated topic is not a hard constraint
#: (D-20's gate says every pinned field is one), it shapes what the search
#: **returns**. `sourcing.source` reads it itself, so no caller has to remember
#: to hand it over — T203 is what happens when a correct module waits for one to.
EXCLUSIONS_FILE = ("search", "exclusions.json")

#: A zero over nothing shown is not a pass. Four exclusions were restated in
#: the live session and each arrived again; the probe puts at least that many
#: presentations through the check before its count means anything.
MINIMUM_PRESENTATIONS = 8


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Exclusion(Strict):
    """Something the candidate ruled out, in their own words.

    `about` is `<facet>:<value>` — the same shape `ScopeDecision.about` uses,
    so a facet means the same thing on both sides of the conversation.
    `words` is what they actually said: it is what gets quoted back when an
    override has to be justified, and a paraphrase there is how a candidate
    ends up arguing with a summary of themselves.
    """

    about: str
    stated_at_cycle: int = Field(ge=1)
    words: str
    #: Other surface forms of the same topic, in Spanish, English and Catalan,
    #: which the session recording it supplies ("banca", "banking", "bancari").
    #: Serving code may not read the corpus's concept map (`corpus_scope`), so
    #: the cross-language half of the topic is carried on the row instead.
    #: Optional, so rows written before this field existed still load.
    terms: tuple[str, ...] = ()

    @property
    def facet(self) -> str:
        return self.about.partition(":")[0]

    @property
    def value(self) -> str:
        return self.about.partition(":")[2]

    @model_validator(mode="after")
    def _it_names_a_facet_and_a_value(self) -> Exclusion:
        facet, sep, value = self.about.partition(":")
        if not (facet.strip() and sep and value.strip()):
            raise ValueError(f"about {self.about!r} is not the <facet>:<value> a scope row records")
        if not self.words.strip():
            raise ValueError("an exclusion with no words is one the candidate cannot be shown")
        return self


class Override(Strict):
    """Why one advert survived an exclusion the candidate stated.

    The reason is mandatory and is not a status code. It is read aloud to the
    candidate, which is the entire difference between an escape hatch and a
    leak: an exclusion overridden silently is indistinguishable from one that
    was never applied, and the candidate has already told us what that feels
    like.
    """

    about: str
    reason: str

    @model_validator(mode="after")
    def _the_reason_is_something_a_candidate_can_read(self) -> Override:
        if not self.reason.strip():
            raise ValueError(
                "an override with no reason is not an override — it is the silent "
                "resurfacing this task exists to stop, with an extra field attached"
            )
        return self


class Candidate(Strict):
    """The little of an advert this module reads.

    Not `offers.Offer`: that model forbids extra fields and carries a dozen
    this check never looks at, and requiring a full offer to ask "was this
    ruled out" would make the question expensive enough to skip.
    """

    offer_id: str
    title: str | None = None
    text: str
    #: The employer's name is part of what an advert says: "Banco Sabadell"
    #: whose text never repeats the word is still a bank.
    employer: str | None = None


def candidate_of(offer: Offer) -> Candidate:
    """The one place a stored `Offer` becomes what `matches` reads.

    Every path by which an offer reaches the candidate — a sourced row, a
    stored offer about to be presented, a reaction stimulus — goes through
    this and `ruled_out_by`, so a field added to the check is added once.
    """
    return Candidate(offer_id=offer.id, title=offer.title, text=offer.text, employer=offer.company)


class Presentation(Strict):
    """One advert as the candidate sees it — position, demotion and all."""

    candidate: Candidate
    rank: int = Field(ge=1)
    #: True when the ranking pushed this down for matching an exclusion. It
    #: does **not** exempt anything; the field exists so the evidence can show
    #: that a demotion was counted, because "we already penalise it" was the
    #: answer that let this ship.
    penalty_applied: bool = False
    override: Override | None = None

    def say(self) -> str:
        """What the candidate is told about this advert surviving an exclusion."""
        if self.override is None:
            return ""
        return (
            f"{self.candidate.title or self.candidate.offer_id}: dijiste que "
            f"{self.override.about.partition(':')[2]} no, y aun así te lo enseño — "
            f"{self.override.reason}. Si prefieres que no vuelva a aparecer, dímelo."
        )


class Resurfaced(Strict):
    """One advert the candidate ruled out and saw anyway."""

    about: str
    offer_id: str
    rank: int
    penalty_applied: bool


class SearchQuery(Strict):
    """The request handed to the connectors for one cycle.

    `excluded` is carried on the query rather than applied afterwards because
    that is the whole finding: a filter that runs after the fetch is a ranking,
    and the candidate can tell the difference.
    """

    cycle: int = Field(ge=1)
    terms: tuple[str, ...]
    excluded: tuple[str, ...] = ()


def next_query(previous: SearchQuery, stated: Iterable[Exclusion]) -> SearchQuery:
    """The next cycle's request, carrying everything ruled out so far.

    Accumulating rather than replacing: an exclusion the candidate has to
    restate every cycle is the reported bug wearing the fix's clothes. It
    leaves only when someone lifts it, which is a different act with its own
    record.
    """
    return SearchQuery(
        cycle=previous.cycle + 1,
        terms=previous.terms,
        excluded=tuple(sorted(set(previous.excluded) | {e.about for e in stated})),
    )


def excluded_terms(query: SearchQuery) -> tuple[str, ...]:
    """The values a connector is asked to leave out, facets stripped.

    A connector takes words, not `<facet>:<value>` pairs. Keeping the pair on
    the query and stripping it here means the record stays reviewable while
    the request stays something a board can actually answer.
    """
    return tuple(about.partition(":")[2] for about in query.excluded)


#: Every spelling of the join between two words: the ASCII hyphen, the six
#: Unicode dashes, the underscore and the slash.
_SEPARATORS = r"[\u2010-\u2015\-_/]"


def _fold(text: str, join: str) -> str:
    """Lowercased, accent-stripped, with every separator rewritten as `join`.

    The candidate said "e-commerce"; adverts say "ecommerce", "E-Commerce" and
    "e-commerce" with a non-breaking hyphen (U+2011). A matcher that only catches the
    candidate's spelling is a filter that reads as not listening in exactly
    the way this task is about.

    `join` is the half review found missing on #285. **Deleting** separators is
    what makes "ecommerce" match "e-commerce" — and it also turns
    "fintech-focused scale-up" into "fintechfocused", where the word-boundary
    lookahead then rejects the needle "fintech" and the gate records a pass
    over an advert the candidate ruled out. Fail-open, in the one direction
    this module exists to close. So both foldings are computed and a hit in
    either is a match: deletion catches the compound spelled as one word,
    a space catches the compound spelled as two.
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(_SEPARATORS, join, stripped)


#: The endings a stated word may take and still be the same topic — the closed
#: rule that replaces listing every wording. Each language declares its own
#: plural, gender and adjective endings, and **all three are applied to every
#: word**, because an advert's language is not the candidate's and the same
#: topic arrives in any of them (ES/EN/CA are treated identically). Applied to
#: the folded (accent-free, lowercase) stem, so "bancària" is `banc` + `aria`.
#: A continuation outside this set is **not** the topic: `cloud` + `flare`.
SUFFIXES: dict[str, tuple[str, ...]] = {
    "es": ("s", "es", "a", "as", "o", "os", "e", "ario", "aria", "arios", "arias"),
    "en": ("s", "es", "ed", "er", "ers", "ing", "ary", "ist", "ists"),
    "ca": ("s", "es", "a", "as", "o", "os", "ari", "aris", "aria", "aries"),
}
#: Where the stem of an abstract noun stops, so the adjective built on it is
#: reached too: `publicidad` -> `publici` + `tario` (`publicitario`).
_ABSTRACT_ENDINGS = ("dad", "tat", "ty")
_ABSTRACT_SUFFIXES = ("tario", "taria", "tarios", "tarias", "tari", "taris", "tary")
_MIN_STEM = 4
#: Where a stem's own last letters change between its forms, so an ending
#: alone cannot reach the other: `cryptocurrency`/`cryptocurrencies` (EN y/i),
#: `construcció`/`construccions` (CA and ES o/on, folded), `banca`/`banques`
#: (CA c/qu). Each pair is applied in **both** directions to every stem, so
#: the candidate's singular finds the advert's plural and the reverse.
STEM_ALTERNATIONS: tuple[tuple[str, str], ...] = (("y", "i"), ("o", "on"), ("c", "qu"))


def _stems(needle: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The stems a folded word is matched by, and the endings each may take.

    The word itself; the word without its plural `s`/`es` (the candidate says
    "fintechs", the advert "FinTech"); that without its final vowel (`banca`
    -> `banc`, so `banco`, `bancario`); and, for an abstract noun, the stem of
    its adjective. A stem shorter than `_MIN_STEM` is never cut further, so a
    three-letter value stays itself.
    """
    base = needle
    for plural in ("es", "s"):
        if base.endswith(plural) and len(base) - len(plural) >= _MIN_STEM:
            base = base[: -len(plural)]
            break
    stems = {needle, base}
    if base[-1:] in "aeo" and len(base) - 1 >= _MIN_STEM:
        stems.add(base[:-1])
    for a, b in STEM_ALTERNATIONS:
        for this, other in ((a, b), (b, a)):
            for stem in tuple(stems):
                root = stem[: -len(this)]
                if stem.endswith(this) and len(root + other) >= _MIN_STEM:
                    stems.add(root + other)
    endings = {"", *(e for group in SUFFIXES.values() for e in group)}
    abstract = [
        base[: -len(a)] for a in _ABSTRACT_ENDINGS if base.endswith(a) and len(base) > len(a) + 3
    ]
    forms = tuple(sorted(stems, key=len, reverse=True))
    suffixes = tuple(sorted(endings, key=len, reverse=True))
    return (forms + tuple(abstract), suffixes + (_ABSTRACT_SUFFIXES if abstract else ()))


def matches(candidate: Candidate, exclusion: Exclusion) -> bool:
    """Is this advert one the candidate ruled out?

    The stated value, and every `term` recorded beside it, is matched as a
    **word plus a closed set of endings** (`SUFFIXES`), never as free text:
    `banca` finds `bancario`, `bancos` and `bancari`, and `cloud` still does
    not find `Cloudflare`, because `flare` is not an ending. Word-boundary
    matched on the left as well, so the topic cannot start mid-word.

    Title, text and employer are all read: an advert from "Banco Sabadell" is
    on the banking topic whether or not its text says so.
    """
    raw = f"{candidate.title or ''} {candidate.employer or ''} {candidate.text}"
    for join in ("", " "):
        haystack = _fold(raw, join)
        for surface in (exclusion.value, *exclusion.terms):
            needle = _fold(surface, join).strip()
            if not needle:
                continue
            stems, endings = _stems(needle)
            body = "|".join(re.escape(x) for x in stems)
            tail = "|".join(re.escape(x) for x in endings)
            if re.search(rf"(?<![0-9a-z])(?:{body})(?:{tail})(?![0-9a-z])", haystack):
                return True
    return False


def load_exclusions(store: ProfileStore) -> tuple[Exclusion, ...]:
    """Everything this candidate has ruled out, or `()` when nothing was.

    A file that will not parse **raises**. An unreadable list treated as an
    empty one is the filter quietly stopping — the reported defect, arriving
    through a corrupt file instead of a missing call.
    """
    if not store.exists(*EXCLUSIONS_FILE):
        return ()
    payload = store.read_json(*EXCLUSIONS_FILE)
    if not isinstance(payload, list):
        raise IdentityError(f"{'/'.join(EXCLUSIONS_FILE)} must be a list")
    try:
        return tuple(Exclusion.model_validate(row) for row in payload)
    except ValueError as exc:
        raise IdentityError(
            f"{'/'.join(EXCLUSIONS_FILE)} holds a row that is not one: {exc}"
        ) from exc


def record_exclusion(store: ProfileStore, exclusion: Exclusion) -> Path:
    """Keep a topic the candidate ruled out, so every later search leaves it out.

    Idempotent on `about`: saying it again replaces the row and never doubles
    it, and the candidate's latest words are the ones quoted back.
    """
    kept = [e for e in load_exclusions(store) if e.about != exclusion.about]
    return store.write_json([e.model_dump() for e in (*kept, exclusion)], *EXCLUSIONS_FILE)


def ruled_out_by(candidate: Candidate, exclusions: Iterable[Exclusion]) -> tuple[str, ...]:
    """The `about` of every exclusion this advert trips, in the order stated."""
    return tuple(e.about for e in exclusions if matches(candidate, e))


def resurfaced(
    presentations: Sequence[Presentation], exclusions: Sequence[Exclusion], *, cycle: int
) -> list[Resurfaced]:
    """Every advert shown at `cycle` that the candidate had already ruled out.

    Two things do **not** excuse one: a rank penalty, because the candidate
    still saw it; and an override naming some other exclusion, because
    justifying the cloud role says nothing about the fintech one.

    An exclusion does not apply to the cycle it was stated in — the offers
    already fetched when the candidate spoke are not evidence of not
    listening. The next search is.
    """
    found: list[Resurfaced] = []
    for shown in presentations:
        for exclusion in exclusions:
            if cycle <= exclusion.stated_at_cycle:
                continue
            if not matches(shown.candidate, exclusion):
                continue
            if shown.override is not None and shown.override.about == exclusion.about:
                continue
            found.append(
                Resurfaced(
                    about=exclusion.about,
                    offer_id=shown.candidate.offer_id,
                    rank=shown.rank,
                    penalty_applied=shown.penalty_applied,
                )
            )
    return found


def measure(
    *,
    presentations: Sequence[Presentation],
    exclusions: Sequence[Exclusion],
    cycle: int,
) -> dict[str, Any]:
    """`restated_exclusions_resurfaced` over one cycle's presentations."""
    found = resurfaced(presentations, exclusions, cycle=cycle)
    evaluated = len(presentations)
    return {
        "restated_exclusions_resurfaced": len(found),
        "restated_exclusions_resurfaced_evaluated": evaluated,
        "presentations_checked": evaluated,
        "gate_status": "measured" if evaluated else "unmeasured",
        "resurfaced": [r.model_dump() for r in found],
    }


#: The ways a plausible fix passes the gate while the candidate still sees what
#: they ruled out. Each is constructed by the probe and counted as a failure if
#: it is *accepted* — the same negative-control shape `sourcing_scope_review`
#: uses, and for the same reason: a check nothing tries to break is a check
#: that measures its author's optimism.
NEGATIVE_CONTROLS: tuple[str, ...] = (
    "a rank penalty instead of an exclusion — demoted to 97 and still on the page",
    "an override naming a different exclusion than the one the advert trips",
    "an exclusion carried for one cycle and dropped, so it must be restated",
)


def probe_exclusions() -> dict[str, Any]:
    """The live session of 2026-08-30, replayed, plus the controls above.

    The four exclusions are the four the candidate actually restated. The
    positive case is that after `next_query` carries them, the cycle that
    follows shows none of them; the controls are the fixes that would have
    looked like listening and were not.
    """
    stated = (
        Exclusion(about="sector:fintech", stated_at_cycle=2, words="fintech no me interesa"),
        Exclusion(about="sector:e-commerce", stated_at_cycle=2, words="e-commerce tampoco"),
        Exclusion(about="role:frontend", stated_at_cycle=3, words="frontend no, backend o datos"),
        Exclusion(about="stack:cloud", stated_at_cycle=3, words="cloud tampoco"),
    )
    failures: list[str] = []

    query = SearchQuery(cycle=3, terms=("data engineer", "analytics engineer"))
    query = next_query(query, stated)
    for exclusion in stated:
        if exclusion.about not in query.excluded:
            failures.append(f"{exclusion.about} never reached the query")
        if exclusion.value not in excluded_terms(query):
            failures.append(f"{exclusion.about} reached the query as a pair no connector can read")

    honoured = tuple(
        Presentation(
            candidate=Candidate(
                offer_id=f"honoured-{n}",
                title=title,
                text=f"{title}. Equipo de plataforma de datos.",
            ),
            rank=n + 1,
        )
        for n, title in enumerate(
            (
                "Analytics Engineer, salud digital",
                "Data Engineer, industria",
                "Senior Backend Engineer, logistica",
                "Data Platform Engineer, educacion",
                "Senior Data Engineer, energia",
            )
        )
    )

    # Control 1: the observed behaviour. Penalised, and still shown.
    demoted = Presentation(
        candidate=Candidate(
            offer_id="demoted",
            title="Senior Data Engineer, fintech",
            text="Fintech en crecimiento busca Data Engineer.",
        ),
        rank=97,
        penalty_applied=True,
    )
    # Control 2: an override that justifies the wrong exclusion.
    mismatched = Presentation(
        candidate=Candidate(
            offer_id="mismatched",
            title="Cloud Platform Engineer en una fintech",
            text="Plataforma cloud para pagos.",
        ),
        rank=2,
        override=Override(about="stack:cloud", reason="es el unico rol senior de la semana"),
    )
    # The escape hatch, used correctly: named, with a reason, about this advert.
    named = Presentation(
        candidate=Candidate(
            offer_id="named",
            title="Staff Data Engineer, fintech",
            text="Fintech. Salario muy por encima de tu suelo, 100% remoto.",
        ),
        rank=1,
        override=Override(
            about="sector:fintech",
            reason="salario un 40% por encima de tu suelo y 100% remoto",
        ),
    )

    for control, label in ((demoted, NEGATIVE_CONTROLS[0]), (mismatched, NEGATIVE_CONTROLS[1])):
        if not resurfaced([control], stated, cycle=4):
            failures.append(f"accepted: {label}")
    if resurfaced([named], stated, cycle=4):
        failures.append("the named override was counted — the escape hatch does not exist")
    if not named.say().strip():
        failures.append("the named override says nothing to the candidate")

    # Control 3: an exclusion carried for one cycle and dropped. `next_query`
    # accumulating rather than replacing is the difference between a filter
    # and a filter the candidate has to restate every cycle, which is the
    # reported bug wearing the fix's clothes. Walked one cycle at a time,
    # because a single call given all four cannot tell the two apart.
    walked = SearchQuery(cycle=1, terms=("data engineer",))
    for exclusion in stated:
        walked = next_query(walked, [exclusion])
    walked = next_query(walked, [])
    if set(walked.excluded) != {e.about for e in stated}:
        failures.append(f"accepted: {NEGATIVE_CONTROLS[2]}")

    shown = (*honoured, named)
    measured = measure(presentations=shown, exclusions=stated, cycle=4)
    # The controls went through `resurfaced` too, above, so counting only the
    # clean run would understate the work actually done. **Distinct**
    # presentations, though: `named` is in both tuples, and the first version
    # of this line added the lengths and reported 8 where 7 had been checked —
    # the floor cleared by a duplicate. That is the padded denominator the
    # sentence above rules out, written by the module that measures listening,
    # and it took review on #285 to see it. The fifth honoured presentation is
    # what meets the floor now, with real work.
    checked = len({id(p) for p in (*shown, demoted, mismatched, named)})
    measured["restated_exclusions_resurfaced_evaluated"] = checked
    measured["presentations_checked"] = checked
    measured["failures"] = failures + [
        f"{r['about']} resurfaced at rank {r['rank']}" for r in measured["resurfaced"]
    ]
    measured["exclusions_carried"] = list(query.excluded)
    measured["negative_controls"] = list(NEGATIVE_CONTROLS)
    if failures:
        measured["restated_exclusions_resurfaced"] += len(failures)
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T90.json`."""
    measured = probe_exclusions()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _record(argv: list[str]) -> int:
    """`record --handle H --about facet:value --words "…" [--term T …] [--cycle N] [--root DIR]`."""
    import argparse

    from integral.identity import default_profiles_root

    parser = argparse.ArgumentParser(prog="integral.sourcing_exclusions record")
    parser.add_argument("--handle", required=True)
    parser.add_argument("--about", required=True, help="<facet>:<value>, e.g. sector:banking")
    parser.add_argument("--words", required=True, help="what the candidate actually said")
    parser.add_argument(
        "--term",
        action="append",
        default=[],
        help="another surface form of the topic (ES, EN or CA); repeat it for each",
    )
    parser.add_argument("--cycle", type=int, default=1)
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    store = ProfileStore(args.root or default_profiles_root(), args.handle)
    exclusion = Exclusion(
        about=args.about, stated_at_cycle=args.cycle, words=args.words, terms=tuple(args.term)
    )
    path = record_exclusion(store, exclusion)
    print(f"recorded {exclusion.about} -> {path}")
    return 0


def _main(argv: list[str]) -> int:
    """`python -m integral.sourcing_exclusions [path]` → T90's and T203's gate evidence.

    `record …` is the producer: the conversation keeps a topic the candidate
    ruled out, so the next `source()` leaves it out.

    T203's measurement runs in a **subprocess** of its own module rather than an
    import: it reads the committed adverts, and this module is on the serving
    path, which may neither import a corpus reader nor launder one.
    """
    if len(argv) > 1 and argv[1] == "record":
        return _record(argv[2:])
    import subprocess

    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    live_args = [str(Path(positional[0]).with_name("T203.json"))] if positional else []
    live = subprocess.run(
        [sys.executable, "-m", "integral.exclusion_live_round", *live_args], check=False
    ).returncode
    if measured["restated_exclusions_resurfaced"] or live == 1:
        return 1
    if measured["gate_status"] == "unmeasured" or live == 3:
        print(
            "UNMEASURED — nothing was shown, so nothing resurfaced. Not a pass and not a fail.",
            file=sys.stderr,
        )
        return 3
    return live


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
