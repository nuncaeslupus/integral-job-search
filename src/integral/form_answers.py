"""T339: application-form answers are a step-11 output, drafted from the store and recorded.

Nearly every ATS asks free-text questions (why us, notice period, salary, permit,
where you heard of us), often with a character limit. They used to be drafted by
hand into a scratch file beside the documents. Here they are a document of the
version, ``form_answers.md``, with a record ``form_answers.json`` that is **not**
sent (it is not Markdown, so ``approval.prepare`` does not list it as a payload
document). The record says, for each answer, which evidence rows it rests on and
which limit it was shortened to, the way the letter's authorship table does.

The rules, each pinned by its own test and by a probe in ``measure``:

* **Store entries only.** An answer cites at least one live evidence row of a
  kind that states something about the candidate (``STORE_KINDS``). A row that
  does not exist, was retracted, is a ``reaction``, ``outcome`` or ``retraction``,
  or shares no word with the answer backs nothing.
* **Every word comes from a cited row.** Each token of the answer, of any length, must
  occur in a cited row (at least one word of four letters must be shared). Only a closed
  set of articles, linking verbs, "and"/"or" and prepositions is exempt, so an invented
  permit, certification or tool (UK, EU, PhD, AWS, Go) brings a token no cited row holds.
* **A hyphenated word is one token** ("non-EU", "ex-employee"), so a prefix cannot be dropped
  from it: the bare word is a token no cited row holds. No prefix list. A spaced "non EU" is read
  as "non-EU"; "well known" against "well-known" is two tokens against one (refused, fail-closed).
* **A row that holds a denial is quoted whole, or not used.** A cited row with a negation cue
  anywhere in it (any line, any sentence) is *guarded*: a cue is what ``claim_trace.is_denial``
  sees, or one of ``claim_trace.NON_CUE_NEGATIONS`` ("without", "sin", "sense", "zero", which a
  CV leaves unread on purpose but where a guard costs only a whole-row quote), or a bare "n't".
  A guarded row that is cited and not quoted whole anywhere in the answer is a defect too, so a
  denial cannot be cited for support while it is dropped. A guarded row can back words of the
  answer only as a verbatim quote of the **whole row**, token for token (CRLF, curly quotes,
  spacing and a leading list marker such as ``1.`` or ``-`` aside). Every answer word not inside
  such a quote must come from an unguarded row, and an answer clause that carries a negation
  must lie wholly inside one. So a denial on a later line, a hard-wrapped one, a scope or a
  condition on
  another line, a reply that points back ("No, it is not needed"), and a claim appended after a
  quote are all refused by the same rule, with no sentence or line splitting deciding what may
  be dropped. The cost is deliberate: the part of a guarded row the candidate wants to send
  cannot be taken out of it, so the drafter asks the candidate to restate it as a row of its own.
  A number must be in the cited words (``claim_trace.paragraph_defects``).
* **The question is a line sent too.** It must read as the employer's question: one
  line, one sentence, no digit or denial, no first-person word, and short.
* **A stated limit is a limit.** ``shorten`` keeps whole sentences, in order,
  and refuses rather than cut mid-sentence or invent an ellipsis; an answer over
  its limit is a defect, so the limit cannot be ignored by editing afterwards.
* **Story-bank episodes need per-use approval.** An ``episode`` row may be cited
  only if its text is in the version's approved episodes, and every other
  episode the master holds is swept for by ``approval.measure_prepared`` over the
  answer's lines exactly as over the letter's.
* **Staged with the payload.** ``approval.prepare(..., form_answers=...)`` writes
  the document before the payload is measured, so it is in ``payload.documents``
  and in the digest the candidate confirms, and ``stage_send`` copies it to
  ``send/``. ``backed_lines`` is how ``measure_prepared`` learns which of its
  lines a store entry backs; an edited line, or an answer whose row was retracted
  after drafting, stops being backed and the send is refused.

What is not claimed: that a question is the employer's. A short noun phrase or a question
sentence with no first-person word, number or denial cannot be told from a real one, so the
rule only refuses the question that reads as a statement; the candidate reads what is staged.
Nor that the words of an answer were *derived* from the cited
rows. Drawing every word from a cited row is a floor, not a proof, and whether the
answer is something the candidate would say is for the candidate to read.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from integral.claim_trace import (
    DENIAL_KIND,
    NON_CUE_NEGATIONS,
    fold,
    is_denial,
    paragraph_defects,
)
from integral.cv_store import _atomic_write_json, _atomic_write_text
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog, EvidenceRow

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T339.json"

FORM_ANSWERS_DOC = "form_answers.md"
FORM_ANSWERS_RECORD = "form_answers.json"
# Rows that state something about the candidate. A `reaction` is a private response to an
# advert, a `retraction` is bookkeeping, and an `outcome` holds a step-10 rejection reason or an
# interview lesson ("never leaves the machine", step 10): none is something to tell an employer.
STORE_KINDS = frozenset({"episode", "statement", "constraint", "candidate_statement"})
_WORD = re.compile(r"[^\W\d_]+")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
# Where a clause of the ANSWER is cut to find the denials in it. Cutting finely only finds more
# denials; what a denial must be quoted with is decided by the row's lines, never by this cut.
_TERMINATORS = ".!?…:;"
_CLAUSE_END = re.compile(r"[.!?…:;]+(?=\s|$)|\n+")
SOURCE_DEFECT = "source"


class FormAnswerError(ValueError):
    """An answer set that cannot be recorded, or a sentence that cannot be shortened."""


class FormAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1)
    text: str = Field(min_length=1)
    char_limit: int | None = Field(default=None, ge=1)
    evidence_ids: tuple[str, ...] = ()


class FormAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    offer_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    answers: tuple[FormAnswer, ...] = ()


def shorten(text: str, limit: int) -> str:
    """The longest run of whole leading sentences of `text` that fits in `limit` characters.

    Never cuts inside a sentence and adds nothing, so the result is the candidate's
    own sentences, in order. When not even the first fits, it raises: shortening
    that sentence is a rewrite, and the candidate is asked for it.
    """
    if limit < 1:
        raise FormAnswerError("a character limit must be at least 1")
    sentences = [s for s in _SENTENCE_END.split(" ".join(text.split())) if s]
    kept = ""
    for sentence in sentences:
        candidate = f"{kept} {sentence}".strip()
        if len(candidate) > limit:
            break
        kept = candidate
    if not kept:
        raise FormAnswerError(
            f"the first sentence is {len(sentences[0]) if sentences else 0} characters, over "
            f"the {limit} limit: ask the candidate for a shorter one rather than cutting it"
        )
    return kept


def _words(text: str) -> set[str]:
    # Words of 4+ letters, the unit of the "every word comes from a cited row" rule. A floor,
    # not a proof of derivation (module docstring).
    return {w.casefold() for w in _WORD.findall(text) if len(w) >= 4}


# A hyphenated compound is ONE token ("non-eu", "ex-employee"): dropping its prefix leaves a word
# no cited row holds, so no prefix list is needed. Spaced "non EU" stays two tokens (a gap).
_TOKEN = re.compile(r"[^\W_]+(?:['-][^\W_]+)*")
# The candidate's own voice. An employer's question is addressed to "you", so a question that
# speaks as "I" is a claim placed where no citation is looked for.
_FIRST_PERSON = frozenset({"i", "i'm", "i've", "i'd", "i'll", "me", "my", "mine", "myself"})
# The only tokens an answer may use without finding them in a cited row: articles, linking
# verbs, "and"/"or" and plain prepositions. Every other token of any length (UK, US, EU, PhD,
# AWS, Go, C) must occur in a cited row, so a short word that carries a claim is never exempt.
_FUNCTION_WORDS = frozenset(
    {"a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "with", "by", "from"}
    | {"i", "my"}
)


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]


def _clauses(text: str) -> list[str]:
    return [p.strip() for p in _CLAUSE_END.split(text) if p.strip()]


def denial_sentences(text: str) -> list[str]:
    """Each clause of `text` (cut at . ! ? ... : ; or a line end) that carries a negation."""
    return [c for c in _clauses(text) if is_denial(c)]


def _holds_negation(text: str) -> bool:
    """A cue ``is_denial`` sees, or one it leaves out for CV use (``NON_CUE_NEGATIONS``), or a
    bare ``n't`` token ("do n't"). Here a guarded row costs only a whole-row quote."""
    return is_denial(text) or any(
        part in _OMITTED_CUES or part == "n't"
        for token in _tokens(text)
        for part in token.split("-")
    )


# A spaced "non EU" is the same compound as "non-EU": joined before tokenising, so dropping the
# "non" leaves a token no cited row holds. (A spaced "no EU" needs nothing: "no" is a cue, so
# the row is guarded and its words back an answer only inside a whole-row quote.)
# Every Unicode dash (category Pd) and the minus sign, derived rather than listed.
_DASHES = re.escape(
    "".join(c for c in map(chr, range(0x110000)) if unicodedata.category(c) == "Pd") + "\u2212"
)
_SPACED_NON = re.compile(rf"(?<![\w'-])non[\s{_DASHES}]+(?=[^\W_])", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(_SPACED_NON.sub("non-", fold(text)))


# A quote is compared on words AND punctuation, so a comma, a full stop or a question mark moved
# inside it is a different quote. Curly double quotes are the same punctuation as straight ones.
_QUOTE_TOKEN = re.compile(rf"{_TOKEN.pattern}|[^\w\s]")
_QUOTE_FOLD = str.maketrans(dict.fromkeys("\u201c\u201d\u201e\u00ab\u00bb", '"'))


def _quote_tokens(text: str) -> list[str]:
    return _QUOTE_TOKEN.findall(_SPACED_NON.sub("non-", fold(text)).translate(_QUOTE_FOLD))


def _is_word(token: str) -> bool:
    return _TOKEN.fullmatch(token) is not None


# A real list marker is a short number ("1." "12)") or a bullet. A four-digit number is a year
# that a wrapped line may begin with ("2019. I left"), and stripping it would drop it from a quote.
_LIST_MARKER = re.compile(r"^\s*(?:\d{1,3}[.)]|[-*\u2022])\s+")


def _row_tokens(row: str) -> list[str]:
    """The tokens of a whole row, line by line, each line's leading list marker (1. - *) dropped.
    Punctuation is kept as tokens: the row is quoted whole, punctuation included."""
    return [t for line in row.splitlines() for t in _quote_tokens(_LIST_MARKER.sub("", line))]


def _clause_pieces(text: str) -> list[tuple[str, list[str]]]:
    """Each clause of the answer with its quote tokens, the clause's own terminator included."""
    out: list[tuple[str, list[str]]] = []
    pos = 0
    for m in [*_CLAUSE_END.finditer(text), None]:
        end = len(text) if m is None else m.start()
        term = "" if m is None or m.group().startswith("\n") else m.group()
        clause = (text[pos:end] + term).strip()
        if clause:
            out.append((clause, _quote_tokens(clause)))
        pos = end if m is None else m.end()
    return out


def _at(haystack: Sequence[str], needle: Sequence[str]) -> list[int]:
    n = len(needle)
    return [i for i in range(len(haystack) - n + 1) if list(haystack[i : i + n]) == list(needle)]


def _question_defects(question: str) -> list[str]:
    q = " ".join(question.split())
    toks = _tokens(q)
    why = []
    if len(_sentences(q)) > 1 or "\n" in question:
        why.append("more than one sentence")
    if any(c.isdigit() for c in q):
        why.append("a number")
    if denial_sentences(q):
        why.append("a denial")
    if _FIRST_PERSON & set(toks):
        why.append("a first-person claim")
    if len(toks) > (25 if q.endswith("?") else 6):
        why.append("too long for a question or a label")
    return [f"question: the question is a line sent to the employer and has {w}" for w in why]


_OMITTED_CUES = frozenset(fold(w) for w in NON_CUE_NEGATIONS)


def _denial_defects(text: str, cited: Sequence[str]) -> list[str]:
    """A cited row holding a denial anywhere is guarded: it backs words only as a whole-row quote.

    Every word of the answer that is not inside such a quote must come from an unguarded row, and
    a clause of the answer that carries a negation must lie wholly inside such a quote."""
    guarded = [_row_tokens(row) for row in cited if _holds_negation(" ".join(row.split()))]
    free = {
        t for row in cited if not _holds_negation(" ".join(row.split())) for t in _row_tokens(row)
    }
    free |= _FUNCTION_WORDS
    clauses = _clause_pieces(text)
    mine = [t for _, piece in clauses for t in piece]
    covered: set[int] = set()
    finals: set[int] = set()
    offset = 0
    for _, piece in clauses:
        offset += len(piece)
        finals.add(offset - 1)
    for quote in guarded:
        for start in _at(mine, quote):
            end = start + len(quote)
            covered.update(range(start, end))
            # A row quoted whole that has no terminator of its own may take the clause terminator
            # the answer adds after it; a row that ends in one must keep that exact one.
            if _is_word(quote[-1]) and end in finals and mine[end] in _TERMINATORS:
                covered.add(end)
    defects = []
    offset = 0
    for clause, piece in clauses:
        span = range(offset, offset + len(piece))
        offset += len(piece)
        if _holds_negation(clause) and not all(i in covered for i in span):
            defects.append(f"denial: {clause!r} is not a whole-row quote of a cited row")
    held = {t for quote in guarded for t in quote if _is_word(t) and not _holds_negation(t)}
    for quote in guarded:
        if not _at(mine, quote):
            defects.append(
                "denial: a cited row that holds a denial is not quoted whole in the answer"
            )
    outside = [t for i, t in enumerate(mine) if i not in covered and t in held and t not in free]
    if outside:
        defects.append(
            f"denial: {', '.join(sorted(set(outside)))} rest on a cited row that holds a denial "
            "and is not quoted whole"
        )
    return defects


def _live_rows(store: ProfileStore) -> dict[str, EvidenceRow]:
    log = EvidenceLog(store)
    return {row.id: row for row in log.effective_rows()} if log.exists() else {}


def answer_defects(
    answer: FormAnswer, live: dict[str, EvidenceRow], approved_episodes: Collection[str]
) -> list[str]:
    """What is wrong with one answer. Defects starting ``source:`` are the gate's count."""
    defects: list[str] = []
    text = answer.text.strip()
    if not text:
        defects.append("empty: the answer says nothing")
    if "\n" in answer.question or any(ln.lstrip().startswith("#") for ln in text.splitlines()):
        defects.append("shape: a question on one line and an answer with no heading line")
    defects += _question_defects(answer.question)
    if answer.char_limit is not None and len(text) > answer.char_limit:
        defects.append(f"limit: {len(text)} characters, over the stated {answer.char_limit}")
    if not answer.evidence_ids:
        defects.append(f"{SOURCE_DEFECT}: cites no store entry")
    cited: list[str] = []
    for ev in answer.evidence_ids:
        row = live.get(ev)
        if row is None:
            defects.append(f"{SOURCE_DEFECT}: {ev} is not a live evidence row")
        elif row.kind not in STORE_KINDS:
            defects.append(f"{SOURCE_DEFECT}: {ev} is a {row.kind} row, which is not for sending")
        elif row.kind == "episode" and row.text not in approved_episodes:
            defects.append(
                f"{SOURCE_DEFECT}: {ev} is a story-bank episode with no per-use approval"
            )
        elif not _words(row.text) & _words(text):
            defects.append(f"{SOURCE_DEFECT}: {ev} shares no word with the answer")
        else:
            cited.append(row.text)
    held = set(_tokens(" ".join(cited))) | _FUNCTION_WORDS
    if cited and (extra := sorted(set(_tokens(text)) - held)):
        defects.append(f"{SOURCE_DEFECT}: {', '.join(extra)} come from no cited row")
    flat = " ".join(text.split())
    defects += _denial_defects(text, cited)
    defects += [
        f"{d.kind}: {d.detail}"
        for d in paragraph_defects("edited", flat, cited)
        if d.kind != DENIAL_KIND
    ]
    return defects


def record_defects(
    store: ProfileStore, answers: Sequence[FormAnswer], approved_episodes: Collection[str]
) -> list[str]:
    live = _live_rows(store)
    defects = []
    seen = Counter(a.question.strip().casefold() for a in answers)
    for n, answer in enumerate(answers, 1):
        if seen[answer.question.strip().casefold()] > 1:
            defects.append(f"answer {n}: the question {answer.question!r} is answered twice")
        defects += [f"answer {n}: {d}" for d in answer_defects(answer, live, approved_episodes)]
    return defects


def render(answers: Sequence[FormAnswer]) -> str:
    """``form_answers.md``: each question as a heading, its answer beneath."""
    blocks = [f"## {a.question.strip()}\n\n{a.text.strip()}" for a in answers]
    return "\n\n".join(blocks) + "\n"


def _version_parts(offer_id: str, version: int) -> tuple[str, ...]:
    return ("cv", "generated", offer_id, f"v{version}")


def write_answers(
    store: ProfileStore,
    offer_id: str,
    version: int,
    answers: Sequence[FormAnswer],
    *,
    approved_episodes: Collection[str] = (),
) -> Path:
    """Record `answers` for one version and write the document. Refuses any defect.

    Nothing is written for a defective set, and a version already staged is not
    rewritten (a sent version is never edited; the next is ``v<N+1>``).
    """
    if not answers:
        raise FormAnswerError("no form answers to record")
    where = _version_parts(offer_id, version)
    folder = store.path(*where)
    if not folder.is_dir():
        raise FormAnswerError(f"{offer_id} v{version} was never written")
    if store.path(*where, "send").exists() or store.path(*where, "send.json").exists():
        raise FormAnswerError("this version is already staged in send/: record a new version")
    defects = record_defects(store, answers, approved_episodes)
    if defects:
        raise FormAnswerError("; ".join(defects))
    record = FormAnswers(offer_id=offer_id, version=version, answers=tuple(answers))
    _atomic_write_json(store, record.model_dump(mode="json"), *where, FORM_ANSWERS_RECORD)
    return _atomic_write_text(store, render(answers), *where, FORM_ANSWERS_DOC)


def read_answers(store: ProfileStore, offer_id: str, version: int) -> FormAnswers | None:
    path = store.path(*_version_parts(offer_id, version), FORM_ANSWERS_RECORD)
    if not path.exists():
        return None
    try:
        record = FormAnswers.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if (record.offer_id, record.version) == (offer_id, version) else None


def backed_lines(
    store: ProfileStore, offer_id: str, version: int, approved_episodes: Collection[str]
) -> Counter[str]:
    """The lines of ``form_answers.md`` a store entry backs, one per occurrence.

    Re-judged against the evidence log **now**, so a row retracted after drafting
    un-backs its answer. An unreadable or absent record backs nothing.
    """
    record = read_answers(store, offer_id, version)
    if record is None:
        return Counter()
    live = _live_rows(store)
    backed: Counter[str] = Counter()
    for answer in record.answers:
        if answer_defects(answer, live, approved_episodes):
            continue
        for line in render([answer]).splitlines():
            if line.strip():
                backed[line.strip()] += 1
    return backed


# ---------------------------------------------------------------------------
# the gate: a clean corpus, and one probe per hole


def _corpus_and_probes() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "profiles"
        identity = create_profile(root, "Probe", handle="probe", language="en")
        store = ProfileStore(root, identity.handle)
        log = EvidenceLog(store)

        def row(kind: Any, text: str) -> str:
            return log.append(
                recorded_at="2026-10-17T09:00:00Z", step="history", kind=kind, text=text,
                source="conversation",
            ).id  # fmt: skip

        notice = row("constraint", "My notice period is two months at my current employer.")
        salary = row("statement", "I would expect around sixty thousand euros a year.")
        permit = row("statement", "I hold a permanent residence permit for Spain.")
        why = row("statement", "I want to work on logistics software at a company this size.")
        story = row(
            "episode",
            "I rewrote billing reconciliation and the run fell from six hours to forty minutes.",
        )
        ops = row("statement", "I work with Kubernetes and Docker for client deployments.")
        reaction = row("reaction", "The remote policy on this advert put me off a little.")
        retracted = row("statement", "I know Kubernetes well from two years of client work.")
        log.append(
            recorded_at="2026-10-17T09:01:00Z", step="history", kind="retraction",
            text="Forget that.", source="conversation", retracts=retracted,
        )  # fmt: skip
        # the reviewer's cases on #822 (second-reader report 6232424809), F1-F5
        rejection = row("outcome", "The manager was dismissive and I would not go back.")
        lesson = row("outcome", "In the interview I lost the thread when asked about pricing.")
        no_permit = row("statement", "I do not hold a work permit for the United Kingdom.")
        used = row("statement", "I used Kubernetes at Acme for two years.")
        no_sponsor = row("constraint", "I do not need visa sponsorship.")
        # round-2 reviewer cases (report 6233180546): N1 short invented tokens, N2 cut denials
        spain = row("statement", "I have a valid work permit for Spain.")
        degree = row("statement", "I have a degree in physics.")
        scoped = row(
            "statement",
            "I do not need visa sponsorship for Spain, but I need it for the United Kingdom.",
        )
        cond = row(
            "statement", "Once my residence card is renewed I will not need visa sponsorship."
        )
        said = row("statement", "My manager said I do not need supervision, which was wrong.")
        # round-4 reviewer cases (report 6235094699): A1-A6
        usa = row("statement", "In the U.S. I do not need visa sponsorship.")
        jan = row("statement", "From Jan. I will not need visa sponsorship.")
        ell = row("statement", "My manager said\u2026 I do not need supervision.")
        nl = row("statement", "My manager said:\nI do not need supervision.")
        qno = row("statement", "Do I need visa sponsorship? No.")
        qno2 = row("statement", "Do I need visa sponsorship?\nNo.")
        notyet = row("statement", "Do I hold a work permit for Spain? Not yet.")
        # round-5 reviewer cases (report 6236128412): B1-B9, one rule: a guarded row is quoted whole
        b1 = row("statement", "Do I need visa sponsorship?\nNo, it is not needed.")
        b2 = row("statement", "I hold a UK work permit.\nIt is no longer valid.")
        b3 = row(
            "statement", "I hold a UK work permit.\nThat was true until 2023; it no longer is."
        )
        b4 = row("statement", "Did I ever hold a UK work permit?\nNope, never did.")
        b5 = row("statement", "I do not\nneed visa sponsorship for Spain.")
        b6 = row("statement", "I have never\nheld a UK work permit.")
        b7 = row(
            "statement", "I do not need visa sponsorship to work\nin Spain; for the UK I would."
        )
        b9 = row("statement", "It is true that I moved to Girona.")
        listed = row("statement", "1. I do not need visa sponsorship.")
        girona = row("statement", "I live in Girona and I like trains.")
        # round-6 reviewer cases (report 6238354981): N1 a dropped prefix, N2-N5 negations that
        # claim_trace leaves out for CV use, RC1 a guarded row cited and not quoted
        noneu = row("statement", "I am a non-EU citizen.")
        exemp = row("statement", "I am an ex-employee of Acme.")
        known = row("statement", "I am a well-known engineer in Girona.")
        without = row("statement", "I am still without a UK work permit; I have one for Spain.")
        sin = row(
            "statement",
            "Sigo sin permiso de trabajo para el Reino Unido; lo tengo para Espa\u00f1a.",
        )
        zero = row("statement", "I have zero years of Kubernetes experience.")
        spaced = row("statement", "I do n't need visa sponsorship.")
        rc_no = row("statement", "I do not need visa sponsorship for Spain.")
        rc_uk = row("statement", "I need visa sponsorship for the UK.")
        rc_moved = row("statement", "I moved to Spain in 2020.")
        # round-3 reviewer cases (report 6233957716): R1-R3 cut sentence, R4-R8 dropped denials
        boss = row("statement", "My manager said: I do not need supervision.")
        semi = row("statement", "I do not need visa sponsorship; that holds for Spain only.")
        aws = row("statement", "I do not use AWS; I prefer Azure.")
        eu = row("statement", "I am not in the EU. I live in Morocco now.")
        car = row("statement", "I do not own a car. I cycle everywhere.")
        visa = row("statement", "I do not need a work visa for Spain.")
        one = row(
            "statement",
            "I do not need a work visa for Spain. "
            "I do not hold a work permit for the United Kingdom.",
        )
        notice_was = "My notice period was two months."
        approved = {log_row.text for log_row in log.rows() if log_row.id == story}
        live = _live_rows(store)

        def a(text: str, *ids: str, limit: int | None = None, q: str = "Q") -> FormAnswer:
            return FormAnswer(question=q, text=text, char_limit=limit, evidence_ids=ids)

        clean = [
            ("notice period", a("My notice period is two months.", notice, limit=60)),
            ("salary", a("I would expect around sixty thousand euros a year.", salary)),
            ("permit", a("I hold a permanent residence permit for Spain.", permit)),
            ("why us", a("I want to work on logistics software.", why, limit=80)),
            ("approved episode", a(
                "I rewrote billing reconciliation and the run fell from six hours to "
                "forty minutes.", story)),
            ("denial quoted word for word", a("I do not need visa sponsorship.", no_sponsor)),
        ]  # fmt: skip
        notice_text = "My notice period is two months."
        S, SC, SD = (
            frozenset(k) for k in ({"source"}, {"source", "hand_typed_count"}, {"source", "denial"})
        )
        LIM = frozenset({"limit"})
        # (case, the defect kinds required, the answer, the approved episodes). `()` is a
        # case that must be accepted: a probe that cannot pass is no proof the rule is not
        # simply refusing everything.
        holes: list[tuple[str, frozenset[str], FormAnswer, Collection[str]]] = [
            ("no citation", SC, a(notice_text), approved),
            ("unknown id", SC, a(notice_text, "ev-999999"), approved),
            ("retracted row", S, a("I know Kubernetes well.", retracted), approved),
            ("reaction row", S, a("The remote policy put me off.", reaction), approved),
            ("unrelated row", SC, a(notice_text, salary), approved),
            ("episode without approval", SC, clean[4][1], ()),
            ("over the limit", LIM, a(notice_text, notice, limit=10), approved),
            ("denial not cited", SD,
                a("I have never used Kubernetes.", ops), approved),
            ("number not cited", SC,
                a("My notice period is three months.", notice), approved),
            ("F1 rejection reason", SD,
                a("The manager was dismissive and I would not go back.", rejection), approved),
            ("F1 interview lesson", S,
                a("I lost the thread when asked about pricing.", lesson), approved),
            ("F2 denial dropped", frozenset({"denial"}),
                a("I hold a work permit for the United Kingdom.", no_permit), approved),
            ("F3 invented permit on a common word", S,
                a("I have a valid work permit for the United States.", why), approved),
            ("F3 invented certification on a common word", S,
                a("I am a certified AWS architect and want to work remotely.", why), approved),
            ("F3 invented certification of a used tool", S,
                a("I am a certified Kubernetes administrator.", used), approved),
            ("F4 claim in the question", frozenset({"question"}),
                a("My notice period is two months.", notice,
                  q="I am a certified Kubernetes administrator with a UK work permit"), approved),
            ("N1 invented UK on a short token", S,
                a("I have a valid work permit for Spain and the UK.", spain), approved),
            ("N1 invented US and EU", S,
                a("I have a valid work permit for the US and EU.", spain), approved),
            ("N1 invented PhD", S, a("I have a PhD in physics.", degree), approved),
            ("N2 scope dropped", frozenset({"denial"}),
                a("I do not need visa sponsorship.", scoped), approved),
            ("N2 condition dropped", frozenset({"denial"}),
                a("I will not need visa sponsorship.", cond), approved),
            ("N2 disputed report", frozenset({"denial"}),
                a("I do not need supervision.", said), approved),
            ("R1 attribution before a colon dropped", frozenset({"denial"}),
                a("I do not need supervision.", boss), approved),
            ("R2 scope after a semicolon dropped", frozenset({"denial"}),
                a("I do not need visa sponsorship.", semi), approved),
            ("R4 short-word denial dropped", frozenset({"denial"}),
                a("I use AWS. I prefer Azure.", aws), approved),
            ("R5 denial of EU dropped", frozenset({"denial"}),
                a("I am in the EU. I live in Morocco now.", eu), approved),
            ("R6 denial of a car dropped", frozenset({"denial"}),
                a("I own a car. I cycle everywhere.", car), approved),
            ("R7 one denial quoted, another reversed", frozenset({"denial"}),
                a("I do not need a work visa for Spain. I hold a work permit for the "
                  "United Kingdom.", visa, no_permit), approved),
            ("R8 the same two in one row", frozenset({"denial"}),
                a("I do not need a work visa for Spain. I hold a work permit for the "
                  "United Kingdom.", one), approved),
            ("D2 tense flip through was", S, a(notice_was, notice), approved),
            ("R1 the whole sentence is accepted", frozenset(),
                a("My manager said: I do not need supervision.", boss), approved),
            ("A1 scope before an abbreviation dropped", frozenset({"denial"}),
                a("I do not need visa sponsorship.", usa), approved),
            ("A2 condition before an abbreviation dropped", frozenset({"denial"}),
                a("I will not need visa sponsorship.", jan), approved),
            ("A3 attribution before an ellipsis dropped", frozenset({"denial"}),
                a("I do not need supervision.", ell), approved),
            ("A4 attribution before a line break dropped", frozenset({"denial"}),
                a("I do not need supervision.", nl), approved),
            ("A5 contentless No answering a question", frozenset({"denial"}),
                a("I need visa sponsorship.", qno), approved),
            ("A6 contentless Not yet answering a question", frozenset({"denial"}),
                a("I hold a work permit for Spain.", notyet), approved),
            ("A5 contentless No on its own line", frozenset({"denial"}),
                a("I need visa sponsorship.", qno2), approved),
            ("A1 the whole row is accepted", frozenset(),
                a("In the U.S. I do not need visa sponsorship.", usa), approved),
            ("A4 the whole two-line row is accepted", frozenset(),
                a("My manager said: I do not need supervision.", nl), approved),
            ("A5 the whole question and No is accepted", frozenset(),
                a("Do I need visa sponsorship? No.", qno), approved),
            ("B1 anaphoric No on a later line", frozenset({"denial"}),
                a("I need visa sponsorship.", b1), approved),
            ("B2 later line withdraws the claim", frozenset({"denial"}),
                a("I hold a UK work permit.", b2), approved),
            ("B3 later line says it no longer holds", frozenset({"denial"}),
                a("I hold a UK work permit.", b3), approved),
            ("B4 Nope on a later line", frozenset({"denial"}),
                a("I ever hold a UK work permit.", b4), approved),
            ("B5 hard wrap after the negator", frozenset({"denial"}),
                a("I need visa sponsorship for Spain.", b5), approved),
            ("B6 hard wrap after never", frozenset({"denial"}),
                a("I held a UK work permit.", b6), approved),
            ("B7 scope continues on the next line", frozenset({"denial"}),
                a("I do not need visa sponsorship to work.", b7), approved),
            ("B8 a claim appended after a quote", frozenset({"denial"}),
                a("Do I hold a work permit for Spain? Not yet. I hold a work permit for Spain.",
                  notyet), approved),
            ("B9 a negation wrapped round a quote", frozenset({"denial"}),
                a("It is not true that I do not need visa sponsorship.", no_sponsor, b9),
                approved),
            ("N1 non-EU reversed to EU", frozenset({"source"}),
                a("I am an EU citizen.", noneu), approved),
            ("N1 ex-employee reversed to employee", frozenset({"source"}),
                a("I am an employee of Acme.", exemp), approved),
            ("N4 without a permit reversed", frozenset({"denial"}),
                a("I have a UK work permit.", without), approved),
            ("N5 sin permiso reversed", frozenset({"denial"}),
                a("Tengo permiso de trabajo para el Reino Unido.", sin), approved),
            ("N3 zero years reversed", frozenset({"denial"}),
                a("I have years of Kubernetes experience.", zero), approved),
            ("N2 spaced n't reversed", frozenset({"denial"}),
                a("I do need visa sponsorship.", spaced), approved),
            ("RC1 denial cited and not quoted", frozenset({"denial"}),
                a("I need visa sponsorship for Spain.", rc_no, rc_uk, rc_moved), approved),
            ("N1 a hyphenated word quoted is accepted", frozenset(),
                a("I am a well-known engineer in Girona.", known), approved),
            ("N1 a hyphenated word paraphrased is accepted", frozenset(),
                a("In Girona I am a well-known engineer.", known), approved),
            ("B the whole multi-line row is accepted", frozenset(),
                a("Do I need visa sponsorship? No, it is not needed.", b1), approved),
            ("B the whole hard-wrapped row is accepted", frozenset(),
                a("I do not need visa sponsorship for Spain.", b5), approved),
            ("B a list-numbered row quoted whole is accepted", frozenset(),
                a("I do not need visa sponsorship.", listed), approved),
            ("B an unguarded row is paraphrased freely", frozenset(),
                a("I like trains and I live in Girona.", girona), approved),
            ("N3 me in the question", frozenset({"question"}),
                a("My notice period is two months.", notice, q="Hire me, AWS certified"),
                approved),
            ("F5 denial quoted is accepted", frozenset(),
                a("I do not need visa sponsorship.", no_sponsor), approved),
            ("F5 denial quoted with the question asked", frozenset(),
                a("I do not hold a work permit for the United Kingdom.", no_permit,
                  q="Do you hold a UK work permit?"), approved),
        ]  # fmt: skip
        corpus = [
            {"case": label, "source_defects": _count_source(answer_defects(ans, live, approved))}
            for label, ans in clean
        ]
        probes = [
            {
                "case": label,
                "expected_defect_kinds": sorted(want),
                "found_defect_kinds": sorted(_kinds(answer_defects(ans, live, appr))),
            }
            for label, want, ans, appr in holes
        ]
        return corpus, probes


def _kinds(defects: Sequence[str]) -> set[str]:
    return {d.split(":", 1)[0] for d in defects}


def _count_source(defects: Sequence[str]) -> int:
    return sum(1 for d in defects if d.startswith(f"{SOURCE_DEFECT}:"))


def measure() -> dict[str, Any]:
    """``form_answers_without_a_store_source`` over a clean corpus, plus the probes.

    The first is 0 by construction (the corpus is hand-picked clean), so it can only catch a
    rule that starts refusing the clean answers. ``probe_cases_misjudged`` is the count that can
    catch a rule that stops refusing: it compares the defect kinds each probe raises with the
    kinds it must raise, and a probe that must be accepted must raise none.
    """
    corpus, probes = _corpus_and_probes()
    misjudged = sum(1 for p in probes if p["found_defect_kinds"] != p["expected_defect_kinds"])
    return {
        "form_answers_without_a_store_source": sum(c["source_defects"] for c in corpus),
        "answers_checked": len(corpus),
        "probe_cases": len(probes),
        "probe_cases_misjudged": misjudged,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write T339's evidence. Exit 1 on a sourceless answer or misjudged probe, 3 if none ran."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))
    if 0 in (measured["answers_checked"], measured["probe_cases"]):
        print("nothing was measured: a clean zero over no answers is not a pass", file=sys.stderr)
        return 3
    if measured["form_answers_without_a_store_source"] or measured["probe_cases_misjudged"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
