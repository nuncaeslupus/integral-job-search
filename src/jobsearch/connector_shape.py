"""The advertised connector shape, measured against what actually runs (D-10).

`docs/distribution.md` §5 is a promise to a contributor: these are the files a
shared connector may contain, and this is what each one does. A file named
there that no runtime executes is a promise the tool cannot keep — and the
contributor finds out only after writing one, when their connector passes every
conformance rule and still does nothing.

That is not hypothetical. §5 advertised an optional `parse.py` as the escape
hatch "for sites the declarative form cannot express", and nothing in
`src/jobsearch` ever executed one: `connectors.py` interprets `connector.yaml`
and matches selectors, and there is no import machinery anywhere in the package.
Review on PR #77 found it; it was seeded as D-10 (#78) rather than resolved
there, because dropping the hatch and building a sandbox for it are both design
decisions.

The hatch was dropped. This module is what stops it coming back by accident: it
reads the shape §5 advertises, subtracts the mechanisms this repository can
actually execute, and records the difference. Re-advertising a `parse.py`
without also building the runtime for it fails the gate here, in the same
commit, rather than failing a contributor some months later.

**Why the executable set is a declared constant rather than something detected.**
Detecting "does a runtime exist for this file?" means asking whether some code
path somewhere would import it, which is precisely the question a static walk
cannot answer — the same limit that makes the AST allowlist in
`connector_contract` admission lint rather than a sandbox. So the set is
declared, and empty, and the day someone builds the isolated runner for
`parse.py` (D-10's resolution B) they add the name here in that commit. Keeping
it a constant means the gate measures a claim somebody had to write down, not an
inference that can quietly go wrong.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from jobsearch.connector_contract import OPTIONAL_ENTRIES, REQUIRED_ENTRIES

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D10.json"
DEFAULT_DOC_PATH = _REPO_ROOT / "docs" / "distribution.md"

# The heading whose fenced block is the shape. Matched on the number and not on
# the wording, so rephrasing the title does not silently stop the measurement.
_SECTION = re.compile(r"^## 5\.", re.MULTILINE)
_FENCE = re.compile(r"^```", re.MULTILINE)

# A file this repository can execute from inside a connector package. Empty, and
# `parse.py` is the name that would go here — see the module docstring.
EXECUTED_ENTRIES: frozenset[str] = frozenset()

# What makes an advertised entry a *mechanism* rather than data: it is code, so
# something has to run it for the promise to mean anything. `.yaml` and `.html`
# entries are read, and the rules that read them are checked elsewhere.
_CODE_SUFFIX = ".py"


class ShapeError(Exception):
    """The shape could not be read — never silently a measurement of zero."""


def advertised_entries(doc: Path = DEFAULT_DOC_PATH) -> tuple[str, ...]:
    """The filenames §5's fenced shape block names, in the order it names them."""
    try:
        text = doc.read_text(encoding="utf-8")
    except OSError as exc:
        raise ShapeError(f"{doc}: could not be read: {exc}") from exc

    section = _SECTION.search(text)
    if section is None:
        raise ShapeError(f"{doc}: no '## 5.' section — the shape is not where this expects it")

    fences = list(_FENCE.finditer(text, section.end()))
    if len(fences) < 2:
        raise ShapeError(f"{doc}: §5 has no fenced shape block")
    block = text[fences[0].end() : fences[1].start()]

    entries: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or not line.startswith(" "):
            # The unindented first line is the `connectors/<site-id>/` root.
            continue
        name = stripped.split()[0]
        if name.endswith("/"):
            continue
        entries.append(name)
    if not entries:
        raise ShapeError(f"{doc}: §5's shape block names no files")
    return tuple(entries)


def measure(doc: Path = DEFAULT_DOC_PATH) -> dict[str, Any]:
    """D-10's gate: advertised executable mechanisms that nothing executes."""
    advertised = advertised_entries(doc)
    mechanisms = [name for name in advertised if name.endswith(_CODE_SUFFIX)]
    without_runtime = sorted(set(mechanisms) - EXECUTED_ENTRIES)

    # The other half of "the two shapes agree". A doc that advertises a file the
    # checker refuses is the same defect pointing the other way: a contributor
    # following §5 gets refused by a rule §5 did not mention.
    enforced = REQUIRED_ENTRIES | OPTIONAL_ENTRIES
    top_level = {name for name in advertised if "." in name and not name.endswith((".html",))}
    unenforced = sorted(top_level - enforced)

    return {
        "advertised_connector_mechanisms_without_a_runtime": len(without_runtime),
        "advertised_entries": list(advertised),
        "mechanisms_without_a_runtime": without_runtime,
        "advertised_but_not_admitted_by_rule_1": unenforced,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    doc: Path = DEFAULT_DOC_PATH,
) -> dict[str, Any]:
    """Measure and record `status/evidence/D10.json`."""
    measured = measure(doc)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write D-10's gate evidence. Exit 1 when the shape promises what nothing runs.

        python -m jobsearch.connector_shape [evidence-path] [--doc PATH]

    `--doc` measures a document other than the committed one. As in
    `connector_contract` (D-11), evidence is then written only if the caller
    also named where it goes: a measurement of some other file is not evidence
    about this repository, and recording it unconditionally is how the committed
    number gets replaced by an answer to a different question.
    """
    args = list(argv[1:])
    doc = DEFAULT_DOC_PATH
    own_doc = True
    if "--doc" in args:
        index = args.index("--doc")
        if index + 1 >= len(args):
            print("connector-shape: --doc needs a path", file=sys.stderr)
            return 2
        doc = Path(args[index + 1])
        own_doc = False
        args = args[:index] + args[index + 2 :]
    positional = [arg for arg in args if not arg.startswith("--")]
    # None means "measured, recorded nowhere" — see the docstring.
    default_target = DEFAULT_EVIDENCE_PATH if own_doc else None
    target: Path | None = Path(positional[0]) if positional else default_target
    try:
        measured = measure(doc) if target is None else write_evidence(target, doc)
    except ShapeError as exc:
        # Exit 3, not 1: the shape could not be read, so nothing was measured.
        # A gate that could not run has not failed — and must not read as passed.
        print(f"connector-shape: {exc}", file=sys.stderr)
        return 3

    for name in measured["mechanisms_without_a_runtime"]:
        print(
            f"✗ docs/distribution.md §5 advertises {name}, and nothing executes it — "
            "a connector needing it would pass every rule and still not work (D-10)",
            file=sys.stderr,
        )
    for name in measured["advertised_but_not_admitted_by_rule_1"]:
        print(
            f"✗ docs/distribution.md §5 advertises {name}, which rule 1 refuses — "
            "a contributor following §5 would be refused by a rule §5 does not mention",
            file=sys.stderr,
        )
    print(json.dumps(measured, ensure_ascii=False))
    failures = measured["advertised_connector_mechanisms_without_a_runtime"] + len(
        measured["advertised_but_not_admitted_by_rule_1"]
    )
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
