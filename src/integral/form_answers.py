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
  does not exist, was retracted, is a ``reaction`` or ``retraction``, or shares
  no word with the answer backs nothing. Denials and numbers get the letter's
  rule (``claim_trace.paragraph_defects``): an absence, or a figure, must be in
  the words the answer cites.
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

What is not claimed: that the words of an answer were *derived* from the cited
rows. Sharing a word with a cited row is a floor, not a proof, and whether the
answer is something the candidate would say is for the candidate to read.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from integral.claim_trace import paragraph_defects
from integral.cv_store import _atomic_write_json, _atomic_write_text
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog, EvidenceRow

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T339.json"

FORM_ANSWERS_DOC = "form_answers.md"
FORM_ANSWERS_RECORD = "form_answers.json"
# Rows that state something about the candidate. A `reaction` is a private response to an
# advert and a `retraction` is bookkeeping: neither is something to tell an employer.
STORE_KINDS = frozenset({"episode", "statement", "constraint", "outcome", "candidate_statement"})
_WORD = re.compile(r"[^\W\d_]+")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
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
    # Words of 4+ letters: a cited row must share one with the answer, so a citation to an
    # unrelated row backs nothing. A floor, not a proof of derivation (module docstring).
    return {w.casefold() for w in _WORD.findall(text) if len(w) >= 4}


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
    defects += [
        f"{d.kind}: {d.detail}" for d in paragraph_defects("edited", " ".join(text.split()), cited)
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
        approved = {log_row.text for log_row in log.rows() if log_row.id == story}
        live = _live_rows(store)

        def a(text: str, *ids: str, limit: int | None = None) -> FormAnswer:
            return FormAnswer(question="Q", text=text, char_limit=limit, evidence_ids=ids)

        clean = [
            ("notice period", a("My notice period is two months.", notice, limit=60)),
            ("salary", a("I would expect around sixty thousand euros a year.", salary)),
            ("permit", a("I hold a permanent residence permit for Spain.", permit)),
            ("why us", a("I want to work on logistics software.", why, limit=80)),
            ("approved episode", a(
                "I rewrote billing reconciliation and the run fell from six hours to "
                "forty minutes.", story)),
        ]  # fmt: skip
        holes: list[tuple[str, int, FormAnswer, Collection[str]]] = [
            ("no citation", 1, a("My notice period is two months."), approved),
            ("unknown id", 1, a("My notice period is two months.", "ev-999999"), approved),
            ("retracted row", 1, a("I know Kubernetes well.", retracted), approved),
            ("reaction row", 1, a("The remote policy put me off a little.", reaction), approved),
            ("unrelated row", 1, a("My notice period is two months.", salary), approved),
            ("episode without approval", 1, clean[4][1], ()),
            ("over the limit", 0, a("My notice period is two months.", notice, limit=10), approved),
            ("denial not cited", 0, a("I have never used Kubernetes.", ops), approved),
            ("number not cited", 0, a("My notice period is three months.", notice), approved),
        ]  # fmt: skip
        corpus = [
            {"case": label, "source_defects": _count_source(answer_defects(ans, live, approved))}
            for label, ans in clean
        ]
        probes = [
            {
                "case": label,
                "expected_source_defects": want,
                "found_source_defects": _count_source(answer_defects(ans, live, appr)),
                "flagged": bool(answer_defects(ans, live, appr)),
            }
            for label, want, ans, appr in holes
        ]
        return corpus, probes


def _count_source(defects: Sequence[str]) -> int:
    return sum(1 for d in defects if d.startswith(f"{SOURCE_DEFECT}:"))


def measure() -> dict[str, Any]:
    """``form_answers_without_a_store_source`` over a clean corpus, plus the probes."""
    corpus, probes = _corpus_and_probes()
    misjudged = sum(
        1
        for p in probes
        if p["found_source_defects"] != p["expected_source_defects"] or not p["flagged"]
    )
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
