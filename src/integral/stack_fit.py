"""T219 — the candidate's stack against the offer's, stated from data.

A real session on 2026-09-30 asked the candidate, at step 9, which technologies
he knew and whether he had built agents. `cv/master.json` already said so — a
`skills` list with levels and provenance, `experience`, `episodes` — but the
ranking read only the extractions and the profile files, so an offer naming Go,
TypeScript and Kubernetes reached a Python engineer's frontier with nothing
saying it wanted a different engineer. This module is the missing join, and
`arsenal/tasks/_history/t-46d07599.md` is its spec: every rule below is cited
there by number (R1-R11), and the gate's fixtures are a second session's
reading of that text, not of this code.

Three decisions worth stating.

**Named, not required.** An advert that lists Kubernetes under "nice to have"
has still named it, and telling the two apart is a reading of prose this
module does not pretend to do (R5). The fit says "names", never "requires".

**What the candidate said beats what the CV says (R7), on two axes.** A CV is a
document written for employers; a statement is the candidate talking to us, and
it is later. So a stance row's level replaces the CV's — downwards included,
and `none` is a level the CV vocabulary cannot hold (*"Kubernetes no sé cómo
funciona"*). Aversion is the second axis and does not touch the level: *"odio
Java"* does not unlearn Java, so the CV's `working` stays true for an
application document while the ranking states a Java offer as a mismatch of
preference. Merging the two into one number would make one of those false.

**Stated, not scored (R10).** The fit rides beside the ranking under
`stack_fit`; it is not a dominance axis and moves no offer. Scoring it would
decide what a stack match is worth against pay or a commute, which is a
preference, and T10's weights do not hold one. What it fixes is the silence:
an offer whose stack is wrong for the candidate now says so, in the
technology's name, on the card.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from integral import strings
from integral.cv_store import ConversationTurn, CVMaster, load_master
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog, EvidenceRow, SkillStance

_CATALOGUE = strings.load()
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T219.json"
DEFAULT_CASES_PATH = _REPO_ROOT / "tests" / "fixtures" / "stack_fit" / "cases.json"

# The second reader committed 134 cases; a floor,
# not the count of the day, so a case added later does not move it and an
# emptied or truncated file cannot score a clean zero over nothing.
MINIMUM_CASES = 130

Verdict = Literal["match", "partial", "mismatch", "unknown"]
BUCKETS: tuple[str, ...] = ("match", "used", "weak", "averse", "missing")

# R1. `*` in the spec is `exact=True` here: a name that is also an ordinary word
# counts only spelled exactly as shown (R3).
_Name = tuple[str, bool]
VOCABULARY: dict[str, tuple[_Name, ...]] = {
    "python": (("Python", False),),
    "java": (("Java", False),),
    "javascript": (
        ("JavaScript", False),
        ("Java Script", False),
        ("ECMAScript", False),
        ("JS", True),
    ),
    "typescript": (("TypeScript", False),),
    "nodejs": (("Node.js", False), ("NodeJS", False), ("Node JS", False)),
    "go": (("Go", True), ("Golang", False)),
    "rust": (("Rust", True),),
    "kotlin": (("Kotlin", False),),
    "scala": (("Scala", False),),
    "swift": (("Swift", True),),
    "ruby": (("Ruby", False), ("Rails", False)),
    "php": (("PHP", False),),
    "csharp": (("C#", False),),
    "cpp": (("C++", False),),
    "dotnet": ((".NET", False), ("dotnet", False)),
    "sql": (("SQL", False),),
    "postgresql": (("PostgreSQL", False), ("Postgres", False)),
    "mysql": (("MySQL", False),),
    "mongodb": (("MongoDB", False), ("Mongo", False)),
    "redis": (("Redis", False),),
    "kafka": (("Kafka", False),),
    "spark": (("Spark", True), ("PySpark", False)),
    "kubernetes": (("Kubernetes", False), ("K8s", False)),
    "docker": (("Docker", False),),
    "terraform": (("Terraform", False),),
    "aws": (("AWS", False), ("Amazon Web Services", False)),
    "gcp": (("GCP", False), ("Google Cloud", False)),
    "azure": (("Azure", False),),
    "react": (("React", True), ("ReactJS", False), ("React.js", False)),
    "vue": (("Vue", False), ("Vue.js", False)),
    "angular": (("Angular", False),),
    "django": (("Django", False),),
    "fastapi": (("FastAPI", False),),
    "flask": (("Flask", True),),
    "linux": (("Linux", False),),
    "llm": (
        ("LLM", False),
        ("LLMs", False),
        ("large language model", False),
        ("large language models", False),
    ),
    "ai_agents": (
        ("AI agent", False),
        ("AI agents", False),
        ("LLM agent", False),
        ("LLM agents", False),
        ("agentic", False),
        ("multi-agent", False),
        ("agentes de IA", False),
        ("agentes IA", False),
    ),
    "langchain": (("LangChain", False),),
}

# R4: `Go` is also the verb.
_GO_VERB_NEXT = re.compile(r"\s+(?:to|ahead|live|further|beyond)\b", re.IGNORECASE)
_SENTENCE_END = ".!?:"


def _compile(name: str, exact: bool) -> re.Pattern[str]:
    """R2's boundaries: a word character at the name's edge may not continue it.

    A name whose edge is a symbol (`.NET`, `C++`, `C#`) owns that symbol (R2),
    so only a repetition of it would be "a longer word" — `C+++` is not C++.
    """
    body = r"\s+".join(re.escape(part) for part in name.split(" "))
    # `\w` rather than an ASCII class: `Pythonía` is one word, not Python.
    left = r"(?<!\w)" if re.match(r"\w", name[0]) else ""
    right = r"(?!\w)" if re.match(r"\w", name[-1]) else f"(?!{re.escape(name[-1])})"
    return re.compile(left + body + right, 0 if exact else re.IGNORECASE)


_PATTERNS: dict[str, tuple[tuple[re.Pattern[str], bool], ...]] = {
    technology: tuple((_compile(name, exact), name == "Go") for name, exact in names)
    for technology, names in VOCABULARY.items()
}

#: The technology ids the vocabulary knows, for readers that resolve a bare word to one.
VOCABULARY_IDS: tuple[str, ...] = tuple(_PATTERNS)


def _opens_a_sentence(text: str, start: int) -> bool:
    prefix = text[:start]
    stripped = prefix.rstrip()
    if not stripped:
        return True
    gap = prefix[len(stripped) :]
    return "\n" in gap or stripped[-1] in _SENTENCE_END


def _is_go_the_verb(text: str, match: re.Match[str], *, label: bool) -> bool:
    if not label and _opens_a_sentence(text, match.start()):
        return True
    rest = text[match.end() :]
    return rest.startswith("-") or _GO_VERB_NEXT.match(rest) is not None


def named(text: str, *, label: bool = False) -> dict[str, str]:
    """Every technology `text` names (R1-R4), with the first span that named it.

    `label=True` reads a skill name (R6) or an offer title (R5): a label is not
    a sentence, so R4's sentence-start clause does not apply and a skill or a
    title called `Go Developer` names go. The hyphen and next-word clauses
    still do — a skill called `Go-to-market` is not Go.
    """
    found: dict[str, str] = {}
    for technology, patterns in _PATTERNS.items():
        for pattern, is_go in patterns:
            for match in pattern.finditer(text):
                if is_go and _is_go_the_verb(text, match, label=label):
                    continue
                found[technology] = match.group(0)
                break
            if technology in found:
                break
    return found


def offer_named(title: str, text: str) -> dict[str, str]:
    """R5: what an offer names — its text as prose, its title as a label."""
    return named(text) | named(title, label=True)


# ---------------------------------------------------------------------------
# the candidate side

_LEVEL_ORDER = {"none": 0, "basic": 1, "working": 2, "strong": 3, "expert": 4}
_KNOWN = frozenset({"working", "strong", "expert"})


@dataclass(frozen=True)
class Held:
    """One technology as the candidate holds it, and where that was read.

    `level` is `None` for *used, level unstated* (R6). `source` names the
    record: `cv:skills[2]`, `cv:experience[0]`, `cv:episodes[1]`, or the
    evidence row id a statement came from (R7).
    """

    level: str | None
    averse: bool
    source: str


class StackFitError(Exception):
    """A statement names a technology the vocabulary cannot resolve."""


def resolve_technology(word: str, *, row_id: str = "") -> str:
    """A stance's `technology` as an R1 id: the id itself, or any R1 name.

    Case and `_`-for-space are forgiven here (`k8s`, `golang`, `js`,
    `amazon_web_services`) because a stance is written by a model from what
    the candidate said, not read out of prose. Anything else raises: a
    statement stored under a key no offer can name would be ignored in
    silence, and ignoring "no sé Kubernetes" credits the CV's level instead.
    """
    if word in VOCABULARY:
        return word
    spoken = word.replace("_", " ").casefold()
    for technology, names in VOCABULARY.items():
        if any(name.casefold() == spoken for name, _ in names):
            return technology
    raise StackFitError(
        f"{row_id or 'a statement'} names {word!r}, which is no technology in "
        "integral.stack_fit.VOCABULARY — record it under one of those ids"
    )


def candidate_stack(
    master: CVMaster,
    statements: Iterable[EvidenceRow] = (),
    retracted_ids: frozenset[str] = frozenset(),
    retracted_texts: frozenset[str] = frozenset(),
) -> dict[str, Held]:
    """R6 then R7: the CV's reading, overridden by what the candidate said.

    T245: work told in conversation reaches the evidence log and the story bank
    without reaching `cv/master.json`, so the log's own prose counts too. An
    effective `episode` row records work done; a technology it names is *used,
    level unstated* (source `log:<row id>`), never missing. Only `episode`: a
    `statement`, `reaction`, `constraint` or `outcome` row says what the
    candidate thinks, wants or refuses, and "never used Kubernetes" or "no PHP
    shops" would credit the very technology it denies. The conversational CV
    entries `cv_store` writes are statements, but they sit in `master` with
    their provenance and are read there. `retracted_ids` are the evidence rows
    a retraction suppresses and `retracted_texts` their sentences
    (`approval.retracted_episode_texts`): a master episode matching either is
    skipped, so forgetting a story forgets its technologies too.

    `statements` is the effective log (`EvidenceLog.effective_rows`), so a
    retracted row never arrives; rows without a `skill` stance are ignored.
    """
    from integral.approval import _withdrawn_by

    levels: dict[str, tuple[str | None, str]] = {}
    for index, skill in enumerate(master.skills):
        for technology in named(skill.name, label=True):
            current = levels.get(technology)
            if (
                current is None
                or current[0] is None
                or (
                    skill.level is not None and _LEVEL_ORDER[skill.level] > _LEVEL_ORDER[current[0]]
                )
            ):
                levels[technology] = (skill.level, f"cv:skills[{index}]")
    prose = [
        (f"cv:experience[{i}]", f"{e.title}\n{e.organisation}\n{e.description}")
        for i, e in enumerate(master.experience)
    ] + [
        (f"cv:episodes[{i}]", e.text)
        for i, e in enumerate(master.episodes)
        if not any(
            isinstance(src, ConversationTurn) and src.evidence_id in retracted_ids
            for src in e.provenance
        )
        and not _withdrawn_by(e.text, retracted_texts)
    ]
    rows = list(statements)
    prose += [(f"log:{row.id}", row.text) for row in rows if row.kind == "episode"]
    for source, text in prose:
        for technology in named(text):
            levels.setdefault(technology, (None, source))

    averse: dict[str, bool] = {}
    for row in rows:
        stance: SkillStance | None = row.skill
        if row.kind != "statement" or stance is None:
            continue
        technology = resolve_technology(stance.technology, row_id=row.id)
        if stance.level is not None:
            levels[technology] = (stance.level, row.id)
        if stance.averse is not None:
            averse[technology] = stance.averse
            levels.setdefault(technology, (None, row.id))

    return {
        technology: Held(level=level, averse=averse.get(technology, False), source=source)
        for technology, (level, source) in levels.items()
    }


def _mentioned(held: Held) -> bool:
    """A technology an aversion-only statement introduced is not a CV mention."""
    return not (held.level is None and held.source.startswith("ev-"))


# ---------------------------------------------------------------------------
# the fit


def fit(title: str, text: str, held: Mapping[str, Held]) -> dict[str, Any]:
    """R5, R8, R9: what the offer names, bucketed against what the candidate holds."""
    spans = offer_named(title, text)
    buckets: dict[str, list[str]] = {bucket: [] for bucket in BUCKETS}
    sources: dict[str, str] = {}
    for technology in sorted(spans):
        entry = held.get(technology)
        if entry is not None:
            sources[technology] = entry.source
        if entry is not None and entry.averse:
            buckets["averse"].append(technology)
        elif entry is None or not _mentioned(entry):
            buckets["missing"].append(technology)
        elif entry.level is None:
            buckets["used"].append(technology)
        elif entry.level in _KNOWN:
            buckets["match"].append(technology)
        else:
            buckets["weak"].append(technology)
    return {
        "verdict": verdict(buckets, named_count=len(spans)),
        **buckets,
        "spans": dict(sorted(spans.items())),
        "sources": sources,
    }


def verdict(buckets: Mapping[str, Sequence[str]], *, named_count: int) -> Verdict:
    if named_count == 0:
        return "unknown"
    if len(buckets["match"]) == named_count:
        return "match"
    if not buckets["match"] and not buckets["used"]:
        return "mismatch"
    return "partial"


def fits_for_store(store: ProfileStore, offer_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Step 9's call: `cv/master.json` and the evidence log against each stored offer.

    An offer that is not on disk is left out rather than guessed at; the
    ranking then carries no fit for it, which reads as unknown, not as a match.
    """
    from integral.approval import retracted_episode_texts

    log = EvidenceLog(store)
    master = load_master(store)
    held = candidate_stack(
        master,
        log.effective_rows(),
        log.suppressed_ids() if log.exists() else frozenset(),
        retracted_episode_texts(store, master),
    )
    fits: dict[str, dict[str, Any]] = {}
    for offer_id in offer_ids:
        path = store.path("offers", f"{offer_id}.json")
        if not path.is_file():
            continue
        offer = json.loads(path.read_text(encoding="utf-8"))
        fits[offer_id] = fit(offer.get("title") or "", offer.get("text") or "", held)
    return fits


def summary_line(offer_fit: Mapping[str, Any], *, language: str = "es") -> str:
    """The card's stack line (R11): what the offer names and what the CV holds.

    Filled from the fit, never composed by a model — the same rule step 9's
    card follows for everything else. The wording lives in
    `strings/catalogue.json`, so `presentation.untranslated(language)` covers it.
    """
    if offer_fit["verdict"] == "unknown":
        return strings.text(_CATALOGUE, "stack_none_named", language)
    parts = [
        f"{strings.text(_CATALOGUE, f'stack_{bucket}', language)}: "
        f"{', '.join(offer_fit['spans'][t] for t in offer_fit[bucket])}"
        for bucket in BUCKETS
        if offer_fit[bucket]
    ]
    return "; ".join(parts) + "."


# ---------------------------------------------------------------------------
# the gate


def _master_from_case(cv: Mapping[str, Any]) -> CVMaster:
    return CVMaster.model_validate(
        {
            "skills": list(cv.get("skills", ())),
            "experience": [{"description": "", **entry} for entry in cv.get("experience", ())],
            "episodes": [{"kind": "context", "text": text} for text in cv.get("episodes", ())],
        }
    )


def _statement_rows(statements: Sequence[Mapping[str, Any]]) -> list[EvidenceRow]:
    """The case's statements as an effective log: a retracted one never arrives."""
    rows: list[EvidenceRow] = []
    for number, statement in enumerate(statements, start=1):
        if statement.get("retracted"):
            continue
        stance = {k: v for k, v in statement.items() if k != "retracted"}
        rows.append(
            EvidenceRow(
                id=f"ev-{number:06d}",
                recorded_at="2026-09-30T00:00:00Z",
                step="ranking",
                kind="statement",
                text=json.dumps(stance, sort_keys=True),
                source="conversation",
                skill=SkillStance.model_validate(stance),
            )
        )
    return rows


def disagreements(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Each case whose expectation the module does not meet, with what it returned."""
    wrong: list[dict[str, Any]] = []
    for case in cases:
        if case["kind"] == "named":
            got: Any = sorted(offer_named(case.get("title", ""), case["text"]))
            want: Any = sorted(case["expected_named"])
        else:
            held = candidate_stack(
                _master_from_case(case.get("cv", {})),
                _statement_rows(case.get("statements", ())),
            )
            result = fit(case.get("title", ""), case["text"], held)
            got = {key: result[key] for key in ("verdict", *BUCKETS)}
            want = {"verdict": case["expected"]["verdict"]} | {
                bucket: sorted(case["expected"].get(bucket, ())) for bucket in BUCKETS
            }
        if got != want:
            wrong.append({"id": case["id"], "rule": case.get("rule"), "want": want, "got": got})
    return wrong


def _probe_store(root: Path, *, with_statement: bool) -> str | None:
    """End to end: `master.json` and a stance row in, `rank`'s `stack_fit` out.

    Returns the verdict the ranking carried for the Java offer, or `None` when
    the ranking carried no fit at all — the failure this task exists to fix.
    """
    from integral.cv_store import write_master
    from integral.rank import Candidate, point_band, rank

    identity = create_profile(
        root, f"Stack probe {with_statement}", handle=f"stack-probe-{int(with_statement)}"
    )
    store = ProfileStore(root, identity.handle)
    write_master(
        store,
        CVMaster.model_validate({"skills": [{"name": "Java", "level": "working"}]}),
    )
    if with_statement:
        EvidenceLog(store).append(
            recorded_at="2026-09-30T10:00:00Z",
            step="ranking",
            kind="statement",
            text="odio Java",
            source="conversation",
            skill=SkillStance(technology="java", averse=True),
        )
    store.write_json(
        {"id": "probe-java", "title": "Backend engineer", "text": "Java and Spring."},
        "offers",
        "probe-java.json",
    )
    ranking = rank(
        [
            Candidate(
                offer_id="probe-java",
                salary_per_month=3000.0,
                pay=point_band(3000.0, "EUR"),
                scores={},
            )
        ],
        dimensions=(),
        revision=EvidenceLog(store).revision(),
        weights=None,
        at="2026-09-30T10:00:00Z",
        stack=fits_for_store(store, ["probe-java"]),
    )
    carried = ranking.get("stack_fit", {}).get("probe-java")
    return None if carried is None else str(carried["verdict"])


def measure(cases_path: Path = DEFAULT_CASES_PATH) -> dict[str, Any]:
    try:
        cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    except (OSError, ValueError, KeyError) as exc:
        return {
            "gate_status": "unmeasured",
            "reason": f"cannot read {cases_path.name}: {exc}",
            "stack_fit_cases_disagreeing": -1,
        }
    wrong = disagreements(cases)
    with tempfile.TemporaryDirectory() as tmp:
        plain = _probe_store(Path(tmp), with_statement=False)
        stated = _probe_store(Path(tmp), with_statement=True)
    # The CV says Java at `working`: without a statement that is a match, and
    # "odio Java" must turn it into a mismatch. Either reading missing means
    # the ranking did not see the store.
    unread = int(plain != "match") + int(stated != "mismatch")
    status = "measured" if len(cases) >= MINIMUM_CASES else "unmeasured"
    return {
        "gate_status": status,
        "stack_fit_cases_disagreeing": len(wrong) if status == "measured" else -1,
        "cases_checked_at_least": MINIMUM_CASES,
        "disagreeing_case_ids": sorted(entry["id"] for entry in wrong),
        "cv_records_unread_by_ranking": unread,
        "technologies_in_vocabulary": len(VOCABULARY),
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Measure T219's stack fit.")
    parser.add_argument("evidence", nargs="?", default=str(DEFAULT_EVIDENCE_PATH), type=Path)
    args = parser.parse_args(argv)
    measured = write_evidence(args.evidence)
    print(f"stack_fit_cases_disagreeing: {measured['stack_fit_cases_disagreeing']} (== 0)")
    if measured["gate_status"] != "measured":
        print(f"T219 cannot be scored: {measured.get('reason', 'too few cases')}", file=sys.stderr)
        return 3
    for entry in measured["disagreeing_case_ids"]:
        print(f"  disagrees: {entry}", file=sys.stderr)
    if measured["cv_records_unread_by_ranking"]:
        print("the ranking did not carry the store's stack fit", file=sys.stderr)
        return 1
    return 0 if measured["stack_fit_cases_disagreeing"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
