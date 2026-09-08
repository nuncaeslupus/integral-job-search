"""T123 — what a gate metric's *name* promises, checked at the point it is named.

Five metrics have shipped here promising more than they counted — `status_is_asserted`
(T108), `incidental_duplicate_drops` (#323), `negation_recall_hits_by_mechanism` (#318),
`robots_adjudications_without_a_competent_second_reader` (T116) and `verified_gate_defects`
(#333). Each was caught by a second reader, one at a time, after the code was written. The
read of #334 supplied the rule that catches them earlier:

> **A metric named after a *category* of things is satisfiable by there being none of
> them; a metric named after a *wrong outcome* is not.**

`floors_that_do_not_fail_the_gate == 0` is satisfied by there being no floors.
`probes_identical_to_their_fixture == 0` by there being no probes.
`growth_sensitive_evidence_keys == 0` by no keys being classified. Against that,
`bodyless_posts_sent_without_a_content_type == 0` names an event that went wrong: a POST
that was never sent is not a post lying around uncounted, so "none" is exactly the claim
the gate means to make.

This module classifies every gate metric the board declares, and reports the
category-named ones by name.

## The rule, stated

Three questions, in order, decided **from the name alone** — no implementation is read,
which is what makes the property checkable at the moment a metric is named.

**Step 1 — is the gate satisfiable by emptiness at all?** Only a gate an empty scan
*passes* can be vacuously true: `== 0`, `<= n`, `< n`. A `>=` or `>` gate is *refused* by
an empty scan — `corpus_size >= 500` fails at zero — so the vacuity this module is about
cannot arise there. Those metrics are recorded `out_of_scope` (clause **S1**) rather than
silently classified.

**Step 2 — does the name count things, or read a quantity?** `lint_typecheck_exit_code`,
`extraction_macro_f1`, `weight_salary_equivalent_roundtrip_error` are readings of one
number, not populations with members. "There being none of them" is not a way to satisfy a
reading. Verdict `not_a_count`, clause **M1**.

**Step 3 — the head noun decides.** Read the name as an English noun phrase and take its
head — the noun the qualifiers hang off.

- **E1 — the head names an occurrence**: a send, a fetch, a merge, a drop, a disclosure, a
  run, a dispatch. An occurrence exists only by occurring, so a count of zero is the
  assertion the gate wanted. Verdict `outcome`.
- **C1 — anything else**: the head names something this repository *holds* — a file, a
  key, a field, a probe, a floor, a package, a row, a string. The gate then counts a
  **subset** of a standing population, and it reads zero when that population is empty
  whatever the qualifier says about the subset. Verdict `category`.

**The qualifier is deliberately not consulted for the verdict.** This is where a rule that
merely fits today's board goes wrong: `floors_that_do_not_fail_the_gate`,
`probes_identical_to_their_fixture` and `status_presence_fields_named_as_identity` all
carry a fault marker — a privative (`do not`), a fault predicate (`identical to`), a
participle (`named as`) — and all three are category-named, because *floors*, *probes* and
*fields* are things this repository has whether or not anything went wrong. A rule keyed on
fault markers calls all three outcome-named, which is the fail-open direction: it certifies
exactly the three names #334 read as the problem. So a fault marker is **recorded** on the
reading (`borderline`) and changes nothing; a reader who disagrees with a specific call can
see which token pulled the other way and argue about that token.

**C1 is the default, and that is the whole safety property.** A head this module does not
recognise is `category` — the verdict that *requires a floor* — not `outcome`. A wrong
`category` verdict costs one floor nobody strictly needed; a wrong `outcome` verdict leaves
a zero standing on an empty scan, which is the failure being prevented. So the lexicon that
must be maintained is `_OCCURRENCE_HEADS` alone, and every entry in it is a noun that names
an act. Nothing is added to it because a metric would otherwise be reported.

## A category-named metric is not wrong — it is a metric that requires a floor

`old_name_references == 0` is category-named and entirely sound, because T55 commits
`files_scanned_at_least` beside it: the zero is read together with proof that the scan was
not empty. That is the repair for every category-named metric, and it is what this module's
**gate** asserts:

    category_named_metrics_recorded_without_a_denominator == 0

A metric is a finding when it is category-named, its payload exists and records its gated
key as a number, and **that payload carries nothing evidencing a non-empty scan** — no
positive count, no non-empty list or object. Such a record says "none of them" and cannot
say how many were looked at.

**Why that, and not `category_named_gate_metrics == 0`** — the name this task carried until
it was implemented. The board declares over 140 metrics an empty scan would satisfy, and a
large minority are category-named; T115, T117 and T111 are on that list by the task's own
reckoning, and the task says in as many words that a category-named metric *is not
automatically wrong*. A gate demanding none of them contradicts its own scope, and could
only be met by renaming a hundred metrics across a hundred merged tasks. So the literal
count is measured and **reported** — `category_named_gate_metrics`, with every name — and
the gate is the enforceable property beside it. That is exactly what T116 did when
`robots_adjudications_without_a_competent_second_reader` turned out to be honest at 19 and
not at 0: keep the honest number, gate on the structural property the module can enforce,
and say so. The rename is a two-file change — `status/plan.md` and
`arsenal/tasks/t-21d5216a.md` — because `tests/test_plan_v2.py` fails a change to one and
not the other.

**This module does not exempt itself, and it is category-named.**
`category_named_metrics_recorded_without_a_denominator` is headed by *metrics*, which is a
thing this repository holds, so C1 catches it like any other. That is the right answer
rather than an embarrassment: the rule does not say a category-named metric is wrong, it
says it is one that **requires a floor** — and this one commits two, so its own zero is
read together with proof that the scan happened. A name engineered to score `outcome` on
its own classifier would be the fail-open reading of the rule, written by the module whose
job is to refuse it.

**What is committed and what is only reported.** The finding and its names are committed
exactly. The censuses — `metrics_classified`, `category_named_gate_metrics`, the per-metric
readings — are *not*: every one of them moves when any other task PR lands a gate block,
which is the drift T104 exists to stop. They are printed by a run and asserted against
floors (`MINIMUM_METRICS_CLASSIFIED`, `MINIMUM_CATEGORY_NAMED_RECORDED`) that the record
commits in their place, the shape `task_gate.record` and `plan_v2.record` already use.

**The floor is this module's own subject turned on itself.** A classifier that reports zero
findings because it parsed no metrics is precisely the vacuity it exists to report, so a
run that classifies fewer than `MINIMUM_METRICS_CLASSIFIED` metrics writes nothing and
**exits 1** — not the 3 that `make evidence` prints as "unmeasured (recorded)" and carries
past, which is T115's finding about every other floor in this repository.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = _REPO_ROOT / "status" / "plan.md"
DEFAULT_TASKS = _REPO_ROOT / "arsenal" / "tasks"
DEFAULT_HISTORY = DEFAULT_TASKS / "_history"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T123.json"

#: The denominator floors. Committed in place of the counts themselves, which move
#: whenever any other task PR lands a gate block. Both sit well under what the board
#: declares today — 144 metrics classified, 116 of them category-named — because a floor
#: is a claim that the scan happened, not a census of the day (T100).
MINIMUM_METRICS_CLASSIFIED = 100
#: The finding's own denominator: category-named metrics whose payload was actually read.
#: Zero findings over no payload read is the same vacuity one level up, so this floor is
#: the one that makes `category_named_metrics_recorded_without_a_denominator == 0` mean
#: something. 96 payloads are read today.
MINIMUM_CATEGORY_NAMED_RECORDED = 60

#: A gate expression: the metric name, the comparison, the threshold.
_GATE_EXPRESSION = re.compile(r"^([a-z][a-z0-9_]*)\s*(==|!=|<=|>=|<|>)\s*(-?\d+(?:\.\d+)?)\s*$")

#: The `## Acceptance gate` section of a task file, and the fenced ```gate block in it.
#: Same two expressions `task_gate` reads with, kept here rather than imported so a task
#: file this module cannot parse is a violation of this module's own reading.
_SECTION_RE = re.compile(r"##\s+Acceptance gate\s*\n(.*?)(?=\n##\s|\Z)", re.DOTALL | re.IGNORECASE)
_BLOCK_RE = re.compile(r"```gate\s*\n(.*?)```", re.DOTALL)

#: Function words that open a qualifier. The head noun is on their left.
_QUALIFIER_OPENERS = frozenset(
    {
        "that",
        "which",
        "whose",
        "who",
        "where",
        "when",
        "while",
        "because",
        "without",
        "with",
        "within",
        "outside",
        "inside",
        "in",
        "into",
        "on",
        "onto",
        "at",
        "by",
        "for",
        "from",
        "to",
        "of",
        "off",
        "over",
        "under",
        "after",
        "before",
        "against",
        "despite",
        "beyond",
        "past",
        "across",
        "and",
        "or",
        "but",
        "than",
        "per",
        "not",
        "no",
        "never",
        "still",
        "only",
        "as",
        "a",
        "an",
        "the",
        "their",
        "its",
        "it",
        "this",
        "these",
    }
)

#: Adjective and participle endings. A qualifier can sit to the *left* of the head too
#: (`growth_sensitive_evidence_keys`), so only the trailing ones are stripped — the head
#: is the last surviving noun of the leading noun group.
_MODIFIER_SUFFIXES = (
    "ed",
    "ing",
    "ive",
    "able",
    "ible",
    "ical",
    "al",
    "ic",
    "ent",
    "ant",
    "ous",
    "ary",
    "less",
    "ful",
    "ory",
    "sensitive",
    "driven",
    "based",
)

#: Irregular past participles: `posts_sent` is `posts`, modified, not a thing called a
#: `sent`. Suffix matching cannot see these, and one of them sits in the task's own
#: worked example, so the list is not an optimisation.
_IRREGULAR_PARTICIPLES = frozenset(
    {
        "sent",
        "read",
        "written",
        "made",
        "kept",
        "held",
        "lost",
        "found",
        "given",
        "taken",
        "seen",
        "shown",
        "left",
        "built",
        "drawn",
        "known",
        "put",
        "set",
        "cut",
        "run",
        "met",
        "told",
        "said",
        "gone",
        "done",
    }
)

#: Heads that name a **reading of one quantity** rather than a set with members. Step 2
#: of the rule: "there being none of them" is not a way to satisfy a fraction, a score,
#: an exit code or an error magnitude.
_MEASUREMENT_HEADS = frozenset(
    {
        "f1",
        "recall",
        "precision",
        "accuracy",
        "fraction",
        "rate",
        "ratio",
        "score",
        "size",
        "count",
        "coverage",
        "overage",
        "chars",
        "spearman",
        "error",
        "loss",
        "overlap",
        "code",
        "correlation",
        "percentage",
        "linkage",
        "traceability",
        "provenance",
        "resolution",
        "sufficiency",
    }
)

#: Heads that name an **occurrence** — clause E1. Every entry is a noun for an act:
#: something that exists only by having been performed. Nothing is added here because a
#: metric would otherwise be reported; a head that is not obviously an act belongs on the
#: default side, where the verdict is `category` and the cost is one floor.
_OCCURRENCE_HEADS = frozenset(
    {
        "post",
        "posts",
        "get",
        "gets",
        "request",
        "requests",
        "call",
        "calls",
        "fetch",
        "fetches",
        "send",
        "sends",
        "write",
        "writes",
        "read",
        "reads",
        "run",
        "runs",
        "merge",
        "merges",
        "drop",
        "drops",
        "push",
        "pushes",
        "dispatch",
        "dispatches",
        "ask",
        "asks",
        "disclosure",
        "disclosures",
        "adjudication",
        "adjudications",
        "search",
        "searches",
        "scan",
        "scans",
        "fire",
        "fires",
        "firing",
        "firings",
        "attempt",
        "attempts",
        "presentation",
        "presentations",
        "application",
        "applications",
        "rebinding",
        "rebindings",
        "narrowing",
        "narrowings",
        "reentry",
        "reentries",
        "leak",
        "leaks",
        "breach",
        "breaches",
        "egress",
    }
)

#: Tokens that pull a name toward `outcome` — a fault predicated of what is counted, or a
#: participle predicating an act performed on it. They never decide a verdict — see the
#: module docstring — and are recorded so a reader can argue about a specific call.
#: `status_presence_fields_named_as_identity` is the borderline case #334 named: the
#: participle `named` is an act, the head `fields` is a thing this repository holds, and
#: the conservative verdict is what stands.
_FAULT_MARKERS = frozenset(
    {
        "without",
        "missing",
        "absent",
        "not",
        "no",
        "never",
        "despite",
        "outside",
        "unbacked",
        "unticked",
        "false",
        "wrong",
        "stale",
        "silent",
        "illegal",
        "unapproved",
        "unreported",
        "broken",
    }
)
_FAULT_PREFIXES = ("un", "mis", "non", "in", "il", "ir")


class MetricNamingError(Exception):
    """The board could not be read — never silently a clean zero."""


@dataclass(frozen=True)
class Metric:
    """One gate metric the board declares, and where it was declared."""

    name: str
    comparison: str
    threshold: float
    sources: tuple[str, ...] = ()
    evidence: str | None = None
    key: str | None = None

    @property
    def satisfied_by_an_empty_scan(self) -> bool:
        """Whether a scan that found nothing passes this gate.

        The whole vacuity question is downstream of this: a `>=` gate is refused by an
        empty scan, so no name under one can promise more than it counts in the way this
        module is about.
        """
        if self.comparison == "==":
            return self.threshold == 0
        if self.comparison == "<=":
            return self.threshold >= 0
        if self.comparison == "<":
            return self.threshold > 0
        return False


@dataclass(frozen=True)
class Reading:
    """One metric's verdict, with the head noun and the clause it was decided by."""

    metric: str
    verdict: str
    clause: str
    head: str
    borderline: str | None = None
    sources: tuple[str, ...] = ()
    evidence: str | None = None
    recorded: bool = False
    denominators: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "verdict": self.verdict,
            "clause": self.clause,
            "head": self.head,
            "borderline": self.borderline,
            "sources": list(self.sources),
            "evidence": self.evidence,
            "recorded": self.recorded,
            "denominators": list(self.denominators),
        }


def _singular(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("es") and len(token) > 3:
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss") and len(token) > 2:
        return token[:-1]
    return token


def _is_modifier(token: str) -> bool:
    if token in _IRREGULAR_PARTICIPLES:
        return True
    return any(
        token.endswith(suffix) and len(token) > len(suffix) + 1 for suffix in _MODIFIER_SUFFIXES
    )


def head_noun(name: str) -> str:
    """The head of the noun phrase the metric name spells out.

    The leading noun group is everything before the first function word that opens a
    qualifier; the head is its last token once trailing modifiers are stripped. So
    `bodyless_posts_sent_without_a_content_type` is headed by `posts` (the `sent` is a
    participle and the `without…` a qualifier), `probes_identical_to_their_fixture` by
    `probes`, and `growth_sensitive_evidence_keys` by `keys`.

    Deliberately shallow. It is a reading of English, not a parser, and it is allowed to
    be wrong: an unrecognised head lands on C1, the conservative verdict.
    """
    tokens = [token for token in name.split("_") if token]
    if not tokens:
        raise MetricNamingError(f"{name!r}: not a metric name")
    prefix: list[str] = []
    for token in tokens:
        if token in _QUALIFIER_OPENERS:
            break
        prefix.append(token)
    while prefix and _is_modifier(prefix[-1]) and len(prefix) > 1:
        prefix.pop()
    if prefix and _is_modifier(prefix[-1]) and len(prefix) == 1:
        # A whole leading group of modifiers — fall back to the last token of the name,
        # which is the only other candidate for a head.
        return tokens[-1]
    return prefix[-1] if prefix else tokens[-1]


def pull_toward_outcome(name: str) -> str | None:
    """The token that argues the name is outcome-named, if the name carries one.

    A fault marker, or a past participle sitting after the head — `posts_sent`,
    `fields_named_as_identity`. It is reported and never acted on: a rule that let it
    decide would call `floors_that_do_not_fail_the_gate` and
    `status_presence_fields_named_as_identity` outcome-named, which is the fail-open
    direction and names two of the four cases this task exists to catch.
    """
    head = head_noun(name)
    seen_head = False
    for token in name.split("_"):
        if token == head:
            seen_head = True
            continue
        if token in _FAULT_MARKERS:
            return token
        if _is_modifier(token) and any(token.startswith(prefix) for prefix in _FAULT_PREFIXES):
            return token
        if seen_head and (token in _IRREGULAR_PARTICIPLES or token.endswith("ed")):
            return token
    return None


def classify(metric: Metric) -> Reading:
    """The verdict for one metric, from its name and its comparison alone."""
    name = metric.name
    head = head_noun(name)
    borderline = pull_toward_outcome(name)
    if not metric.satisfied_by_an_empty_scan:
        return Reading(
            name, "out_of_scope", "S1", head, borderline, metric.sources, metric.evidence
        )
    if _singular(head) in {_singular(h) for h in _MEASUREMENT_HEADS}:
        return Reading(name, "not_a_count", "M1", head, borderline, metric.sources, metric.evidence)
    if head in _OCCURRENCE_HEADS or _singular(head) in _OCCURRENCE_HEADS:
        return Reading(name, "outcome", "E1", head, borderline, metric.sources, metric.evidence)
    return Reading(name, "category", "C1", head, borderline, metric.sources, metric.evidence)


def _gate_block_fields(text: str) -> tuple[str | None, dict[str, str]]:
    """The gate expression and the block's `evidence:` / `key:` fields, if any."""
    section = _SECTION_RE.search(text)
    if section is None:
        return None, {}
    block = _BLOCK_RE.search(section.group(1))
    if block is None:
        return None, {}
    expression: str | None = None
    fields: dict[str, str] = {}
    for raw in block.group(1).splitlines():
        line = raw.strip().strip("`")
        if not line:
            continue
        if _GATE_EXPRESSION.match(line):
            expression = expression or line
        elif ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip().lower()] = value.strip().strip("'\"")
    return expression, fields


def _add(board: dict[str, Metric], metric: Metric) -> None:
    """Merge one declaration into the board, keeping whichever carries the evidence path.

    A metric is declared twice by construction — once in the plan row, once in the task
    file's gate block — and only the task file names the payload.
    """
    existing = board.get(metric.name)
    if existing is None:
        board[metric.name] = metric
        return
    board[metric.name] = Metric(
        name=metric.name,
        comparison=existing.comparison,
        threshold=existing.threshold,
        sources=tuple(sorted(set(existing.sources) | set(metric.sources))),
        evidence=existing.evidence or metric.evidence,
        key=existing.key or metric.key,
    )


def board_metrics(
    plan: Path | None = None,
    tasks: Path | None = None,
    history: Path | None = None,
) -> dict[str, Metric]:
    """Every gate metric the board declares, from the plan and from every task file.

    Live task files **and** the archive, read as one board, for the reason
    `task_gate.measure` reads both: archiving a task file is what a task PR does, and a
    census that moved across that move would be wrong on one side of every merge.
    """
    plan = DEFAULT_PLAN if plan is None else plan
    tasks = DEFAULT_TASKS if tasks is None else tasks
    history = DEFAULT_HISTORY if history is None else history
    board: dict[str, Metric] = {}
    if plan.exists():
        # Imported here rather than at module scope: `plan_v2` imports nothing from this
        # module, and keeping the dependency one-way means a broken plan parser cannot
        # take this module's own tests down with it.
        from integral.plan_v2 import plan_rows

        for row in plan_rows(plan):
            match = _GATE_EXPRESSION.match(row.gate.replace("`", "").strip())
            if match is None:
                continue
            _add(
                board,
                Metric(
                    name=match.group(1),
                    comparison=match.group(2),
                    threshold=float(match.group(3)),
                    sources=(f"plan:{row.label}",),
                ),
            )
    for directory in (tasks, history):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            expression, fields = _gate_block_fields(path.read_text(encoding="utf-8"))
            if expression is None:
                continue
            match = _GATE_EXPRESSION.match(expression)
            if match is None:  # pragma: no cover - `_gate_block_fields` matched already
                continue
            _add(
                board,
                Metric(
                    name=match.group(1),
                    comparison=match.group(2),
                    threshold=float(match.group(3)),
                    sources=(f"task:{path.name}",),
                    evidence=fields.get("evidence"),
                    key=fields.get("key"),
                ),
            )
    return board


def _dig(data: object, dotted: str) -> tuple[bool, object]:
    current = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def denominators(payload: dict[str, Any], gate_key: str) -> list[str]:
    """Which keys of a payload evidence a scan that was not empty.

    A positive number, or a list or object with something in it. A zero, a `false`, an
    empty list and a string all say nothing about how much was looked at — and a string
    saying `"measured"` least of all, since that is the word a vacuous run also writes.
    """
    found: list[str] = []
    for key, value in payload.items():
        if key == gate_key:
            continue
        if isinstance(value, bool):
            continue
        a_positive_count = isinstance(value, int | float) and value > 0
        something_in_a_collection = isinstance(value, list | dict) and len(value) > 0
        if a_positive_count or something_in_a_collection:
            found.append(key)
    return sorted(found)


def _unmeasured(reason: str) -> dict[str, Any]:
    return {
        "category_named_metrics_recorded_without_a_denominator": -1,
        "recorded_without_a_denominator": [],
        "metric_naming_status": "unmeasured",
        "metrics_classified": 0,
        "category_named_gate_metrics": 0,
        "category_named_metrics_recorded": 0,
        "category_named": [],
        "outcome_named": [],
        "not_a_count": [],
        "out_of_scope": [],
        "readings": [],
        "violations": [reason],
    }


def measure(
    plan: Path | None = None,
    tasks: Path | None = None,
    history: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Classify the board's gate metrics and find the zeros resting on nothing.

    The paths default to `None` and are resolved here rather than in the signature: a
    default bound at definition time cannot be redirected, and a check whose own tests
    can only ever run against the live repository is one nobody can write a failing case
    for.
    """
    plan = DEFAULT_PLAN if plan is None else plan
    root = _REPO_ROOT if root is None else root
    board = board_metrics(plan, tasks, history)
    if not board:
        return _unmeasured(f"{plan}: no gate metric could be read from the board")

    readings: list[Reading] = []
    findings: list[str] = []
    for name in sorted(board):
        metric = board[name]
        reading = classify(metric)
        recorded = False
        found: tuple[str, ...] = ()
        if reading.verdict != "out_of_scope" and metric.evidence:
            try:
                payload = json.loads((root / metric.evidence).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError):
                payload = None
            if isinstance(payload, dict):
                gate_key = metric.key or name
                present, value = _dig(payload, gate_key)
                if present and not isinstance(value, bool) and isinstance(value, int | float):
                    recorded = True
                    found = tuple(denominators(payload, gate_key.split(".")[0]))
        reading = Reading(
            reading.metric,
            reading.verdict,
            reading.clause,
            reading.head,
            reading.borderline,
            reading.sources,
            reading.evidence,
            recorded,
            found,
        )
        readings.append(reading)
        if reading.verdict == "category" and reading.recorded and not reading.denominators:
            findings.append(name)

    by_verdict: dict[str, list[str]] = {
        "category": [],
        "outcome": [],
        "not_a_count": [],
        "out_of_scope": [],
    }
    for reading in readings:
        by_verdict[reading.verdict].append(reading.metric)
    classified = sum(len(by_verdict[v]) for v in ("category", "outcome", "not_a_count"))
    category_recorded = [r.metric for r in readings if r.verdict == "category" and r.recorded]
    return {
        "category_named_metrics_recorded_without_a_denominator": len(findings),
        "recorded_without_a_denominator": findings,
        "metric_naming_status": "measured",
        "metrics_classified": classified,
        "category_named_gate_metrics": len(by_verdict["category"]),
        "category_named_metrics_recorded": len(category_recorded),
        "category_named": by_verdict["category"],
        "outcome_named": by_verdict["outcome"],
        "not_a_count": by_verdict["not_a_count"],
        "out_of_scope": by_verdict["out_of_scope"],
        "readings": [reading.as_dict() for reading in readings],
        "violations": [],
    }


def floor_breaches(measured: dict[str, Any]) -> list[str]:
    """Which denominators came in under their floor. Empty is the pass.

    Read **before** the record is written: `record` writes both `_at_least` keys
    unconditionally, so a run that wrote first would leave an artefact claiming a floor it
    never met — and that artefact is what the next healthy run's `make evidence` diffs
    against (`plan_v2.floor_breaches`, same repair).
    """
    breaches = []
    classified = measured["metrics_classified"]
    if classified < MINIMUM_METRICS_CLASSIFIED:
        breaches.append(
            f"only {classified} metrics classified (floor {MINIMUM_METRICS_CLASSIFIED}) — "
            "a metric-naming check that read no metrics is this module's own subject"
        )
    recorded = measured["category_named_metrics_recorded"]
    if recorded < MINIMUM_CATEGORY_NAMED_RECORDED:
        breaches.append(
            f"only {recorded} category-named metrics had a payload to read (floor "
            f"{MINIMUM_CATEGORY_NAMED_RECORDED}) — no zero resting on nothing, over no "
            "payload read, is the same vacuity one level up"
        )
    return breaches


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed, out of what was measured.

    The finding and the names behind it, exactly. The censuses go: every one of them
    moves when any other task PR lands a gate block, and a committed value that another
    task's merge invalidates reddens `make evidence` on work that changed nothing here —
    T104's finding, and `task_gate.record`'s shape.
    """
    dropped = (
        "metrics_classified",
        "category_named_gate_metrics",
        "category_named_metrics_recorded",
        "category_named",
        "outcome_named",
        "not_a_count",
        "out_of_scope",
        "readings",
    )
    committed = {key: value for key, value in measured.items() if key not in dropped}
    committed["metrics_classified_at_least"] = MINIMUM_METRICS_CLASSIFIED
    committed["category_named_metrics_recorded_at_least"] = MINIMUM_CATEGORY_NAMED_RECORDED
    return committed


def write_evidence(
    evidence: Path | None = None,
    plan: Path | None = None,
    tasks: Path | None = None,
    history: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T123.json`; return what was measured.

    A run that breaches either floor writes nothing at all: the only record it could
    write is one asserting a floor it did not meet.
    """
    evidence = DEFAULT_EVIDENCE_PATH if evidence is None else evidence
    measured = measure(plan, tasks, history, root)
    if floor_breaches(measured) or measured["violations"]:
        return measured
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str] | None = None) -> int:
    """Write T123's evidence. Exit 1 on a finding, on a violation, or under a floor."""
    args = list(sys.argv[1:] if argv is None else argv)
    evidence = Path(args[0]) if args else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(evidence)

    for violation in measured["violations"]:
        print(f"✗ {violation}", file=sys.stderr)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["violations"]:
        return 1
    for name in measured["recorded_without_a_denominator"]:
        print(
            f"✗ {name}: category-named, and its payload records the zero with nothing "
            "saying how much was scanned",
            file=sys.stderr,
        )
    if measured["recorded_without_a_denominator"]:
        return 1

    # **Exit 1, not 3.** `make evidence` prints 3 as "unmeasured (recorded)" and carries
    # on, so a floor that exits 3 is decoration — T115's finding, applied here on the day
    # the floor was written rather than after it had been decoration for a while.
    breaches = floor_breaches(measured)
    for breach in breaches:
        print(breach, file=sys.stderr)
    return 1 if breaches else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
