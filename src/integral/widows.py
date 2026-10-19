"""T143: measure widow lines in a rendered CV or letter, and fail the render on them.

A paragraph that ends in one or two words wastes a line and, on a two-page CV, can
be the difference between fitting and not. Line breaking is the renderer's decision
and no reading of the JSON predicts it, so this reads the **laid-out pages** (the
text boxes WeasyPrint places, which are exactly what it writes into the PDF), never
the source text.

**What a widow is.** Fragments are grouped into lines by vertical position; a line
is a widow when the line above it runs the full column, nothing follows it inside
the block, and it is narrower than :data:`MAX_RATIO` of the column.

**Two contracts the first version got wrong**

1. A grid row is not a line. Columns of a flex grid share a vertical position, so a
   row is split where the horizontal gap says a new column began
   (:data:`COLUMN_GAP`), and each run is measured alone.
2. A heading is not a paragraph. A line set entirely in capitals is not reported.

**The report carries the word count**, because shortening a paragraph by fewer
words than its last line holds only makes the widow shorter, not gone.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T143.json"

# A last line narrower than this share of its column is a widow.
MAX_RATIO = 0.25
# The line above must reach at least this share of the column to count as "full".
FULL_RATIO = 0.9
# A horizontal gap wider than this many line-heights starts a new column.
COLUMN_GAP = 0.6
# Lines closer than this many line-heights are one block; a list item's margin or a
# paragraph gap is wider, so a short one-line item is not a paragraph's last line.
BLOCK_PITCH = 1.05
# Left edges within this many layout units are the same column.
COLUMN_TOLERANCE = 2.0
# The fixture documents must hold at least this many full-width lines, so a
# fixture that never wraps cannot report zero.
MINIMUM_FULL_LINES = 6


@dataclass(frozen=True)
class Fragment:
    """One run of text the renderer placed: its page, extent and line."""

    page: int
    x0: float
    x1: float
    top: float
    line_height: float
    text: str


@dataclass(frozen=True)
class Run:
    """One column's share of one line."""

    page: int
    x0: float
    x1: float
    top: float
    line_height: float
    text: str

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass(frozen=True)
class Widow:
    page: int
    ratio: float
    words: int
    text: str

    def __str__(self) -> str:
        return (
            f"page {self.page}: {self.words} word(s), {self.ratio:.0%} of the column: {self.text!r}"
        )


def _is_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def runs_of(fragments: Iterable[Fragment]) -> list[Run]:
    """Lines by vertical position, then columns by horizontal gap; each run alone."""
    ordered = sorted((f for f in fragments if f.text.strip()), key=lambda f: (f.page, f.top))
    rows: list[list[Fragment]] = []
    for frag in ordered:
        row = rows[-1] if rows else None
        if row and row[0].page == frag.page and abs(row[0].top - frag.top) < row[0].line_height / 2:
            row.append(frag)
        else:
            rows.append([frag])
    runs: list[Run] = []
    for row in rows:
        row.sort(key=lambda f: f.x0)
        group = [row[0]]
        for frag in row[1:]:
            if frag.x0 - group[-1].x1 > COLUMN_GAP * frag.line_height:
                runs.append(_join(group))
                group = []
            group.append(frag)
        runs.append(_join(group))
    return runs


def _is_marker(frag: Fragment) -> bool:
    return not any(c.isalnum() for c in frag.text)


def _join(group: Sequence[Fragment]) -> Run:
    # A list marker sits left of its item's text, so the item's first line would start
    # at another left edge than its next lines; the text's edge is the column's.
    lead = 0
    while lead < len(group) - 1 and _is_marker(group[lead]):
        lead += 1
    text = group[lead:]
    first = text[0]
    return Run(
        first.page,
        first.x0,
        max(f.x1 for f in text),
        min(f.top for f in text),
        max(f.line_height for f in text),
        "".join(f.text for f in text).strip(),
    )


def _columns(fragments: Iterable[Fragment]) -> list[tuple[float, list[Run]]]:
    """``(column width, runs top to bottom)`` for each left edge on each page."""
    columns: list[list[Run]] = []
    for run in sorted(runs_of(fragments), key=lambda r: (r.page, r.x0, r.top)):
        last = columns[-1] if columns else None
        if last and last[0].page == run.page and abs(last[0].x0 - run.x0) <= COLUMN_TOLERANCE:
            last.append(run)
        else:
            columns.append([run])
    return [
        (max(r.x1 for r in col) - col[0].x0, sorted(col, key=lambda r: r.top)) for col in columns
    ]


def _adjacent(upper: Run, lower: Run) -> bool:
    return 0 < lower.top - upper.top <= BLOCK_PITCH * upper.line_height


def find_widows(fragments: Iterable[Fragment]) -> list[Widow]:
    """Every widow among ``fragments`` (see the module docstring for the definition)."""
    found: list[Widow] = []
    for width, column in _columns(fragments):
        for i in range(1, len(column)):
            prev, run = column[i - 1], column[i]
            if not _adjacent(prev, run) or _is_caps(run.text):
                continue
            if i + 1 < len(column) and _adjacent(run, column[i + 1]):
                continue
            ratio = run.width / width if width else 1.0
            if prev.width >= FULL_RATIO * width and ratio < MAX_RATIO:
                found.append(Widow(run.page, ratio, run.words, run.text))
    return sorted(found, key=lambda w: w.page)


def full_lines(fragments: Iterable[Fragment]) -> int:
    """How many wrapped lines were measured: runs that reach their column's full width
    and are followed by another line of the same block."""
    count = 0
    for width, column in _columns(fragments):
        for i in range(len(column) - 1):
            if column[i].width >= FULL_RATIO * width and _adjacent(column[i], column[i + 1]):
                count += 1
    return count


def fragments_of_pages(pages: Sequence[Any]) -> list[Fragment]:
    """The text fragments of laid-out WeasyPrint pages, each with its line's extent."""
    out: list[Fragment] = []

    def walk(box: Any, number: int, line: Any) -> None:
        kind = type(box).__name__
        if kind == "LineBox":
            line = box
        if kind == "TextBox" and line is not None:
            out.append(
                Fragment(
                    number,
                    float(box.position_x),
                    float(box.position_x + box.width),
                    float(line.position_y),
                    float(line.height),
                    str(box.text),
                )
            )
        for child in getattr(box, "children", ()):
            walk(child, number, line)

    for number, page in enumerate(pages, start=1):
        walk(page._page_box, number, None)
    return out


# --------------------------------------------------------------------------
# Fixtures and the gate


def fixture_cv() -> dict[str, Any]:
    """A CV whose paragraphs wrap, so the measurement has real lines to read."""
    return {
        "title": "Ana Perez - CV",
        "blocks": [
            {
                "type": "header",
                "name": "Ana Perez",
                "title": "Data engineer",
                "contact": ["ana@example.org", "Girona"],
            },
            {
                "type": "summary",
                "text": (
                    "Builds data platforms and the teams that run them, with a decade of work on "
                    "batch and streaming pipelines, warehouse design, cost control and the "
                    "unglamorous reliability work that keeps analysts trusting the numbers they "
                    "report every single morning to the rest of the company."
                ),
            },
            {"type": "section", "title": "Experience"},
            {
                "type": "job",
                "role": "Engineer",
                "org": "Acme",
                "dates": "2020 - 2024",
                "place": "Remote",
                "bullets": [
                    "Moved the nightly load to streaming and cut the time to fresh data from "
                    "six hours to under ten minutes for every dashboard the finance team uses",
                    "Cut p95 latency of the serving layer by half after profiling the slowest "
                    "queries and replacing a join that scanned the whole fact table each time",
                ],
            },
            {"type": "section", "title": "Projects"},
            {
                "type": "project",
                "name": "pipeline-kit",
                "text": (
                    "A small orchestration library for scheduling dependent jobs, retrying "
                    "failed steps and recording what ran, kept deliberately free of any "
                    "service to operate."
                ),
                "href": "https://example.org/repo",
                "live": "https://example.org/demo",
                "tags": ["python", "sql"],
            },
            {"type": "section", "title": "Skills"},
            {
                "type": "grid",
                "cells": [
                    {"title": "Python", "text": "daily"},
                    {"title": "SQL", "text": "daily"},
                    {"title": "Cloud", "text": "weekly"},
                ],
            },
        ],
    }


def fixture_letter() -> dict[str, Any]:
    return {
        "title": "Letter",
        "blocks": [
            {"type": "letter", "place": "Girona", "date": "7 September 2026"},
            {"type": "to", "lines": ["Hiring team", "Acme"]},
            {
                "type": "text",
                "text": (
                    "I am writing about the data engineering role you advertised, because the "
                    "work you describe, moving a warehouse from nightly batches to streaming "
                    "without losing the trust of the analysts who depend on it, is the work I "
                    "have spent the last four years doing and want to keep doing well."
                ),
            },
            {
                "type": "text",
                "text": (
                    "At my current employer I led that migration end to end, from the first "
                    "design note to the last dashboard moved across, and I would be glad to "
                    "talk through what went right and what I would do differently the next time "
                    "around, given what I know now."
                ),
            },
            {"type": "sign", "closing": "Regards,", "name": "Ana Perez"},
        ],
    }


def measure() -> dict[str, Any]:
    """T143's gate reading: widows in the CV and the letter rendered for a fixture offer."""
    from integral import document_render as dr

    try:
        import weasyprint  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: F401
    except (ImportError, OSError):
        return {
            "widow_defects": -1,
            "gate_status": "unmeasured",
            "reasons": ["the PDF engine (WeasyPrint, the 'pdf' extra) is not installed"],
        }
    widows: list[str] = []
    wrapped = 0
    for label, document in (("cv", fixture_cv()), ("letter", fixture_letter())):
        fragments = dr.layout_fragments(dr.render(document))
        wrapped += full_lines(fragments)
        widows.extend(f"{label} {w}" for w in find_widows(fragments))
    if wrapped < MINIMUM_FULL_LINES:
        return {
            "widow_defects": -1,
            "gate_status": "unmeasured",
            "reasons": [f"only {wrapped} full line(s) measured (floor {MINIMUM_FULL_LINES})"],
        }
    return {
        "widow_defects": len(widows),
        "max_ratio": MAX_RATIO,
        "documents": ["cv", "letter"],
        "full_lines_measured_at_least": MINIMUM_FULL_LINES,
        "gate_status": "measured",
        "widows": widows,
    }


def _main() -> int:
    measured = measure()
    if measured["gate_status"] == "unmeasured" and DEFAULT_EVIDENCE_PATH.exists():
        # Without the engine nothing was measured; keep the last measurement.
        for reason in measured["reasons"]:
            print(reason, file=sys.stderr)
        return 3
    DEFAULT_EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_EVIDENCE_PATH.write_text(
        json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in measured.items() if k != "widows"}, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        for reason in measured["reasons"]:
            print(reason, file=sys.stderr)
        return 3
    for widow in measured["widows"]:
        print(widow, file=sys.stderr)
    return 1 if measured["widows"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
