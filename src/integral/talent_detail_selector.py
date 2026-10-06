"""T254 — talent_es reads the advert body by a durable selector, not a build hash.

`connectors/talent_es` read the body with `div.sc-f4dbceab-10`, a styled-components
hash that rotated and left a 200 page yielding nothing. This counts the detail
selectors of that package that still sit on a build-generated class, using
`connectors.generated_classes` — T234's predicate, not a second one — and counts
`build_hash_accepted` as no excuse: the point is that the body selector needs none.

No `EVIDENCE_SOURCES` declaration, for the reason `connector_salary_audit` states:
the record is derived from `connectors/`, which neither of T150's tree mutations
touches, so a registered source would read `unmeasured` there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from integral.connectors import generated_classes, load_connector

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE = _REPO_ROOT / "connectors" / "talent_es"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T254.json"


def measure(package: Path = DEFAULT_PACKAGE) -> dict[str, Any]:
    connector = load_connector(package)
    selectors = connector.detail.fields if connector.detail is not None else {}
    on_a_hash = sorted(n for n, s in selectors.items() if generated_classes(s.css))
    return {
        "talent_es_detail_selectors_on_a_generated_class": len(on_a_hash),
        "talent_es_detail_selectors_read": len(selectors),
        "gate_status": "measured" if selectors else "unmeasured",
    }


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """The denominator is committed as a floor, never the count of the day."""
    return {
        "talent_es_detail_selectors_on_a_generated_class": measured[
            "talent_es_detail_selectors_on_a_generated_class"
        ],
        "talent_es_detail_selectors_read_at_least": 1,
        "gate_status": measured["gate_status"],
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(record(measured), indent=2) + "\n", encoding="utf-8")
    return measured


def _main() -> int:
    measured = write_evidence()
    print(json.dumps(record(measured)))
    bad = measured["talent_es_detail_selectors_on_a_generated_class"]
    return 1 if bad or measured["gate_status"] != "measured" else 0


if __name__ == "__main__":
    raise SystemExit(_main())
