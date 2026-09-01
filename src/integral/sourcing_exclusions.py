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

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T90.json"

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


def matches(candidate: Candidate, exclusion: Exclusion) -> bool:
    """Is this advert one the candidate ruled out?

    Word-boundary matched, because `cloud` inside `Cloudflare` would start
    deleting roles nobody ruled out — an exclusion that over-reaches is the
    same loss of trust arriving from the other direction.
    """
    raw = f"{candidate.title or ''} {candidate.text}"
    for join in ("", " "):
        needle = _fold(exclusion.value, join)
        if not needle.strip():
            continue
        pattern = rf"(?<![0-9a-z]){re.escape(needle)}(?![0-9a-z])"
        if re.search(pattern, _fold(raw, join)):
            return True
    return False


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


def _main(argv: list[str]) -> int:
    """`python -m integral.sourcing_exclusions [path]` → T90's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    if measured["restated_exclusions_resurfaced"]:
        return 1
    if measured["gate_status"] == "unmeasured":
        print(
            "restated_exclusions_resurfaced: UNMEASURED — nothing was shown, so nothing "
            "resurfaced. Not a pass and not a fail.",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
