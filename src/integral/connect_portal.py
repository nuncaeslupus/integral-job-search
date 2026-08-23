"""T12: how faithfully does the live-portal connector parse its recorded pages?

`connector_fixture_parse_f1` is F1 over **field cells** — one cell per
(item index, field name) — between two independent readings of the same
recorded HTML:

* the *predicted* side is `integral.connectors`: the repo's own tree builder
  over stdlib `html.parser`, and a selector subset with no combinators;
* the *expected* side is a frozen JSON file written by
  `tools/annotate_connector_fixture.py`, which read the same bytes with `lxml`
  and BeautifulSoup's full CSS engine.

Two properties this file exists to keep:

**The expectation is data, not a re-derivation.** The gate never re-runs the
annotator. If it did, both sides would be recomputed from the fixture in the
same breath and the comparison would agree with itself no matter what either
parser did — the failure mode where a harness constructs both sides of its own
equality. Re-annotating is a deliberate act, and it shows up in a diff.

**Item count is inside the score.** Items are aligned by document order, and an
item present on one side and absent on the other contributes its whole row of
cells as a miss. A connector that finds 20 of the 40 offers on the page cannot
score well by parsing those 20 perfectly — which is exactly what an F1 computed
only over the rows both sides happened to produce would have let it do.

Stdlib only, on purpose: `tools/annotate_connector_fixture.py` needs a scraping
stack, and measuring the committed fixtures must not, or this gate stops
running anywhere the extra dependencies are absent.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from integral.connectors import load_connector, parse_detail_page, parse_list_page

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE = _REPO_ROOT / "connectors" / "trabajos_es"
DEFAULT_EXPECTED = _REPO_ROOT / "tests" / "fixtures" / "connectors" / "trabajos_es_expected.json"
DEFAULT_EVIDENCE_PATH = Path("status/evidence/T12.json")

# Shared by both sides of the comparison, deliberately. The two parsers collapse
# runs of whitespace differently, and this gate is about which field was found —
# not about either one's whitespace policy. Normalising on only one side would
# measure that difference instead of the extraction.
_WHITESPACE = re.compile(r"\s+")


def normalise(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def _cells(rows: list[dict[str, str]]) -> dict[tuple[int, str], str]:
    """One (index, field) → value cell per extracted field, whitespace-normalised."""
    return {
        (index, field): normalise(value)
        for index, row in enumerate(rows)
        for field, value in row.items()
    }


def _row(index: int, fields: dict[str, str]) -> dict[tuple[int, str], str]:
    """One row of cells at a chosen index, for the detail page."""
    return {(index, field): normalise(value) for field, value in fields.items()}


def score(
    expected: dict[tuple[int, str], str], predicted: dict[tuple[int, str], str]
) -> dict[str, Any]:
    """F1 over field cells, with every disagreement named."""
    hits = 0
    misses: list[dict[str, str]] = []
    for key in sorted(expected.keys() | predicted.keys(), key=lambda k: (k[0], k[1])):
        want, got = expected.get(key), predicted.get(key)
        if want is not None and want == got:
            hits += 1
            continue
        misses.append(
            {
                "item": str(key[0]),
                "field": key[1],
                "expected": (want or "")[:120],
                "parsed": (got or "")[:120],
            }
        )
    # A cell that differs is both a false positive and a false negative: the
    # connector produced something, and what it should have produced is missing.
    false_positive = sum(1 for m in misses if m["parsed"])
    false_negative = sum(1 for m in misses if m["expected"])
    precision = hits / (hits + false_positive) if hits + false_positive else 0.0
    recall = hits / (hits + false_negative) if hits + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "connector_fixture_parse_f1": round(f1, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "cells_expected": len(expected),
        "cells_parsed": len(predicted),
        "cells_agreeing": hits,
        "mismatches": misses,
    }


def measure(
    package: Path = DEFAULT_PACKAGE, expected_path: Path = DEFAULT_EXPECTED
) -> dict[str, Any]:
    connector = load_connector(package)
    expected_doc = json.loads(expected_path.read_text(encoding="utf-8"))

    parsed_items = parse_list_page(
        connector, (package / "fixture" / "list.html").read_text(encoding="utf-8")
    )
    detail_path = package / "fixture" / "detail.html"
    parsed_detail = (
        parse_detail_page(connector, detail_path.read_text(encoding="utf-8"))
        if connector.detail is not None and detail_path.exists()
        else {}
    )

    # The detail page is one more row, indexed past every list item so its fields
    # cannot collide with item 0's.
    detail_row = max(len(expected_doc["list_items"]), len(parsed_items))
    expected = _cells(expected_doc["list_items"]) | _row(detail_row, expected_doc["detail_fields"])
    predicted = _cells(parsed_items) | _row(detail_row, parsed_detail)

    measured = score(expected, predicted)
    measured["package"] = package.name
    measured["items_expected"] = len(expected_doc["list_items"])
    measured["items_parsed"] = len(parsed_items)
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH, **kwargs: Path) -> dict[str, Any]:
    measured = measure(**kwargs)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.connect_portal [path]` → T12's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps({k: v for k, v in measured.items() if k != "mismatches"}, ensure_ascii=False))
    for mismatch in measured["mismatches"][:10]:
        print(
            f"  item {mismatch['item']} {mismatch['field']}: "
            f"expected {mismatch['expected']!r}, parsed {mismatch['parsed']!r}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
