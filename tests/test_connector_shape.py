"""D-10 — the shape §5 advertises, measured against what this repo can execute.

Written against the committed `docs/distribution.md` rather than an inline
fixture, for the reason the rest of these suites give: a look-alike drifts away
from the real document, unnoticed, the first time somebody edits the real one.
Where a test needs a *different* shape it derives it from the real file, so it
is still the real document with one thing changed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral.connector_shape import (
    DEFAULT_DOC_PATH,
    DEFAULT_EVIDENCE_PATH,
    ShapeError,
    _main,
    advertised_entries,
    measure,
    write_evidence,
)

_PARSE_LINE = "  parse.py           optional, only for sites the declarative form cannot express\n"


def _doc_readvertising_parse_py(tmp_path: Path) -> Path:
    """The committed document with `parse.py` put back into §5's shape block."""
    text = DEFAULT_DOC_PATH.read_text(encoding="utf-8")
    anchor = "  connector.yaml     what to fetch and how to map it to the offer schema\n"
    assert text.count(anchor) == 1, "§5's shape block moved — this fixture needs updating"
    doc = tmp_path / "distribution.md"
    doc.write_text(text.replace(anchor, anchor + _PARSE_LINE), encoding="utf-8")
    return doc


def test_the_gate_holds_over_the_committed_document() -> None:
    """Nothing §5 advertises is a mechanism without a runtime."""
    measured = measure()
    assert measured["advertised_connector_mechanisms_without_a_runtime"] == 0
    assert measured["mechanisms_without_a_runtime"] == []
    assert measured["advertised_but_not_admitted_by_rule_1"] == []


def test_the_shape_block_is_actually_being_read() -> None:
    """A parser that silently matched nothing would pass every other test here.

    The gate is a count of things not found, so "found nothing at all" and
    "found nothing wrong" produce the same zero. Only asserting the entries it
    *did* read separates them — the same reason the conformance command exits 3
    over an empty library rather than 0.
    """
    assert advertised_entries() == ("connector.yaml", "list.html", "detail.html", "meta.yaml")


def test_readvertising_parse_py_fails_the_gate(tmp_path: Path) -> None:
    """The regression D-10 exists to prevent, in the form it would come back.

    Someone restores the escape hatch to §5 because a site needs it, without
    building the isolated runner that would make it real. That is the exact
    state the check found on #77, and it must not be reachable again by editing
    prose alone.
    """
    doc = _doc_readvertising_parse_py(tmp_path)
    measured = measure(doc)
    assert measured["advertised_connector_mechanisms_without_a_runtime"] == 1
    assert measured["mechanisms_without_a_runtime"] == ["parse.py"]
    # ...and it is *also* flagged as advertised-but-refused, because rule 1 no
    # longer admits it. Both halves of the disagreement, from one edit.
    assert measured["advertised_but_not_admitted_by_rule_1"] == ["parse.py"]


def test_the_command_exits_non_zero_when_the_shape_promises_what_nothing_runs(
    tmp_path: Path,
) -> None:
    """A violation must reach the shell, or `make evidence` reports a pass."""
    doc = _doc_readvertising_parse_py(tmp_path)
    evidence = tmp_path / "D10.json"
    assert _main(["x", str(evidence), "--doc", str(doc)]) == 1
    recorded = json.loads(evidence.read_text(encoding="utf-8"))
    assert recorded["mechanisms_without_a_runtime"] == ["parse.py"]
    assert write_evidence(evidence, doc)["advertised_connector_mechanisms_without_a_runtime"] == 1


def test_measuring_another_document_leaves_our_committed_evidence_alone(tmp_path: Path) -> None:
    """The D-11 rule, applied to this command before it can be broken by it.

    `--doc` without a destination measures and reports; it does not replace this
    repository's `status/evidence/D10.json` with an answer about another file.
    """
    before = json.loads(DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert _main(["x", "--doc", str(_doc_readvertising_parse_py(tmp_path))]) == 1
    assert json.loads(DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8")) == before


@pytest.mark.parametrize(
    ("content", "why"),
    [
        ("# no section five here\n", "no '## 5.'"),
        ("## 5. Every connector has the same shape\n\nprose, no fence.\n", "no fenced block"),
        ("## 5. Shape\n\n```\nconnectors/<site-id>/\n```\n", "names no files"),
    ],
)
def test_an_unreadable_shape_is_never_a_measurement_of_zero(
    tmp_path: Path, content: str, why: str
) -> None:
    """The failure mode this whole module exists to avoid, applied to itself.

    A shape that could not be read has measured nothing. Reporting 0 would mean
    "nothing is advertised without a runtime", which is indistinguishable from a
    clean bill of health and is how a gate layer goes inert.
    """
    doc = tmp_path / "distribution.md"
    doc.write_text(content, encoding="utf-8")
    with pytest.raises(ShapeError):
        measure(doc)


def test_the_command_reports_an_unreadable_shape_as_could_not_run(tmp_path: Path) -> None:
    """Exit 3 — not 1 (failed) and emphatically not 0 (passed).

    A gate that could not run has not reached a verdict. Exiting 0 here would
    make a deleted or restructured §5 look like a clean measurement, which is
    the inert-gate failure this module was written to catch elsewhere.
    """
    assert _main(["x", str(tmp_path / "D10.json"), "--doc", str(tmp_path / "absent.md")]) == 3


def test_the_doc_flag_needs_a_path(tmp_path: Path) -> None:
    assert _main(["x", "--doc"]) == 2
