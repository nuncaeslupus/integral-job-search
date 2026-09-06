"""The supported language set is declared in seven places; this asserts they agree.

`Language = Literal["en", "es", "ca"]` reads like the definition of what
languages this product supports. It is not. It is one restatement among seven,
and before this module exactly **one pair** of them was checked —
`test_dimension_model.py` asserts `set(get_args(Language)) == set(LANGUAGES)`,
which covers two sites and reads as though it covers the concept. The other five
agreed by coincidence.

That is this repository's recurring failure shape (T122, T123, T127): a check
that passes for a mechanism other than the one it names.

**Measured, not inferred.** #360's finding came from adding `pt` to the three
obvious declarations in a throwaway worktree on 2026-09-06 and reading what
broke. Thirteen tests failed loudly, which is the system working. Then
`make evidence` died on::

    AttributeError: 'LocalisedText' object has no attribute 'pt'

because `LocalisedText.get()` checks membership in `LANGUAGES` and then reaches
the value with `getattr(self, language)` — the guard reads one declaration and
the lookup reads another. Nothing had compared them.

The quieter one never raised at all. `identity.Language` validates
`Identity.language`, the field in every candidate's `identity.json`, while
`identity.py` separately checks membership in `corpus.LANGUAGES` a few hundred
lines below. Two rules for one question, in one file, with nothing comparing
them.

**Every declaration here is read from the thing itself, never copied.** A table
of expected values in this module would be an eighth restatement, and it would
agree with itself forever. `corpus.LANGUAGES` is the reference not because it is
privileged but because it is the one the other modules' comments point at.

**Duplication is not automatically a defect, so this does not delete it.**
`salary_recovery.LANGUAGES` says in its own comment why it repeats the tuple: its
per-language census is that module's parity evidence and "must not silently
shrink to whatever the corpus holds". That is a deliberate independent assertion
and it should stay independent — it should merely be *checked*, which is what
this does. Only `interview.leaks_quota_language` lost its inline `("en", "es",
"ca")`, because its own docstring already called them "corpus languages" and
nothing was being asserted by writing them out again.

Widening the set is **not** this module's job — that is #358, and it needs an
owner's decision on which language and how to bootstrap a corpus for a language
that has no connectors. What this makes true is that widening it produces a
checklist instead of a search.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args

from integral import corpus, corpus_scope, identity, salary_recovery
from integral.dimensions import Language as DimensionLanguage
from integral.dimensions import LocalisedText

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T129.json"
DEFAULT_CATALOGUE = _REPO_ROOT / "strings" / "catalogue.json"

#: The site every other one is compared against. Not privileged — it is simply
#: the one `salary_recovery` and `LocalisedText.get` already name in their own
#: comments, so disagreement is reported in the direction a reader expects.
REFERENCE = "corpus.LANGUAGES"

#: A floor, never the count of the day (T100). Seven sites are known to exist;
#: a run that resolves fewer has lost one to a rename or a deletion, and a clean
#: zero over five sites is precisely the empty-scan pass this repo keeps finding.
MINIMUM_LANGUAGE_DECLARATIONS = 7


def _catalogue_languages(path: Path = DEFAULT_CATALOGUE) -> frozenset[str]:
    return frozenset(json.loads(path.read_text(encoding="utf-8"))["languages"])


#: Each entry reads its declaration **from the live object**, so a site that is
#: renamed or emptied raises here rather than quietly reporting agreement.
DECLARATIONS: tuple[tuple[str, Callable[[], frozenset[str]]], ...] = (
    (REFERENCE, lambda: frozenset(corpus.LANGUAGES)),
    ("salary_recovery.LANGUAGES", lambda: frozenset(salary_recovery.LANGUAGES)),
    ("dimensions.Language", lambda: frozenset(get_args(DimensionLanguage))),
    ("identity.Language", lambda: frozenset(get_args(identity.Language))),
    ("dimensions.LocalisedText fields", lambda: frozenset(LocalisedText.model_fields)),
    ("corpus_scope.TARGET_MIX keys", lambda: frozenset(corpus_scope.TARGET_MIX)),
    ("strings/catalogue.json languages", _catalogue_languages),
)


def read_declarations() -> dict[str, frozenset[str] | str]:
    """Every declaration, or the reason it could not be read.

    A site that raises is recorded as a string, not dropped. Dropping it would
    turn a deleted declaration into one fewer disagreement — a check that gets
    *greener* as the thing it checks disappears.
    """
    out: dict[str, frozenset[str] | str] = {}
    for name, read in DECLARATIONS:
        try:
            out[name] = read()
        except Exception as exc:  # the reason is the evidence, so nothing is narrowed
            out[name] = f"{type(exc).__name__}: {exc}"
    return out


def measure() -> dict[str, Any]:
    declarations = read_declarations()
    reference = declarations.get(REFERENCE)

    unreadable = sorted(name for name, value in declarations.items() if isinstance(value, str))
    resolved = len(declarations) - len(unreadable)

    if not isinstance(reference, frozenset):
        # Nothing to compare against. Every site is a disagreement, because the
        # alternative is reporting zero over a comparison that never happened.
        disagreeing = sorted(declarations)
    else:
        disagreeing = sorted(
            name
            for name, value in declarations.items()
            if not isinstance(value, frozenset) or value != reference
        )

    measured = resolved >= MINIMUM_LANGUAGE_DECLARATIONS
    return {
        "language_set_declarations_disagreeing": len(disagreeing),
        "language_set_declarations_compared_at_least": MINIMUM_LANGUAGE_DECLARATIONS,
        "language_set_declarations_resolved": resolved,
        "reference": REFERENCE,
        "reference_value": sorted(reference) if isinstance(reference, frozenset) else None,
        "disagreeing": disagreeing,
        "unreadable": unreadable,
        "declarations": {
            name: sorted(value) if isinstance(value, frozenset) else value
            for name, value in sorted(declarations.items())
        },
        "gate_status": "measured" if measured else "unmeasured",
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    record = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit non-zero on any disagreement")
    args = parser.parse_args(argv)

    record = write_evidence()
    for name, value in record["declarations"].items():
        mark = "✗" if name in record["disagreeing"] else " "
        print(f"  {mark} {name:36} {value}")
    print(
        f"\n{record['language_set_declarations_resolved']} declaration(s) read, "
        f"{record['language_set_declarations_disagreeing']} disagreeing "
        f"({record['gate_status']})"
    )

    if not args.check:
        return 0
    if record["gate_status"] != "measured":
        print(
            f"fewer than {MINIMUM_LANGUAGE_DECLARATIONS} declarations resolved — "
            "a site was renamed or removed, so this run measured nothing",
            file=sys.stderr,
        )
        return 3
    return 1 if record["disagreeing"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
