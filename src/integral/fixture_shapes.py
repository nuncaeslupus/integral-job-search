"""T177 — a fixture shape that relocates nothing pins nothing.

`tests/test_liveness.py` runs every refusal sample in `RATE_LIMIT_SAMPLES`
through shapes that restyle it (an innocuous title, a long ordinary page ahead
of the marker). A shape exists to move one particular thing; a cell where it
leaves that thing where it already was runs, passes, and asserts nothing the
unshaped cell did not. #455's round-5 reader found two such cells: `buried`
anchored on `<body>`, and the two Cloudflare samples carry their markers in
`<head>`, so their first marker stayed at offset 19.

The rule is the property, not an anchor tuple: **every (sample, shape) cell
either moves what its shape is declared to move, or is counted here.** Each
`Shape` carries its own `moved` predicate, so a shape added for a page form
nobody has met yet is measured the moment it is listed in `SHAPES`.

`measure()` writes `fixture_shape_cells_that_relocate_nothing`; the cells
compared are the denominator and `MINIMUM_SHAPE_CELLS` is a literal floor, so
a product that shrank to nothing cannot score a clean zero.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from integral.connector_health import BLOCK_PAGE_MARKERS, RATE_LIMIT_SAMPLES

#: Inert page text, long enough that a scan cut short at any plausible length
#: never reaches what follows it (#455 round 4, N5). No block marker in it.
PADDING = "<p>Ofertas de empleo en Barcelona, actualizadas cada día.</p>" * 400

INNOCUOUS_TITLE = "Acme Empleo"

Sample = tuple[str, int | None, str]


def first_marker_offset(page: str) -> int | None:
    """Where the earliest block-page marker starts in `page`, case-folded the
    way the scan reads it; `None` when the page carries no marker."""
    folded = page.casefold()
    hits = [at for marker in BLOCK_PAGE_MARKERS if (at := folded.find(marker)) >= 0]
    return min(hits) if hits else None


def named_innocuously(body: str) -> str:
    """A block page given a site-name `<title>` and no `<h1>` — what a restyle
    of any challenge page can look like (#455 round 3, N3)."""
    demoted = body.replace("<h1", "<h2").replace("</h1>", "</h2>")
    if "<head>" in demoted:
        return demoted.replace("<head>", f"<head><title>{INNOCUOUS_TITLE}</title>", 1)
    if "<html>" in demoted:
        return demoted.replace("<html>", f"<html><head><title>{INNOCUOUS_TITLE}</title></head>", 1)
    # A fragment with neither element (the renamed infojobs edge page): the
    # title is prepended, or the cell restyles nothing.
    return f"<title>{INNOCUOUS_TITLE}</title>" + demoted


def buried(body: str) -> str:
    """The same refusal with its words after ~24 KB of an ordinary page.

    `<html>` first: the Cloudflare samples carry their markers in `<head>`,
    which precedes `<body>`, so anchoring there left them at offset 19."""
    for anchor in ("<html>", "<body>"):
        if anchor in body:
            return body.replace(anchor, anchor + PADDING, 1)
    return PADDING + body


def _marker_moved_later(before: str, after: str) -> bool:
    """The first marker moved past the padding: a shorter shift would not clear
    the 2,000-character window the shape exists to defeat."""
    a, b = first_marker_offset(before), first_marker_offset(after)
    return a is not None and b is not None and b - a >= len(PADDING)


def _title_restyled(before: str, after: str) -> bool:
    title = f"<title>{INNOCUOUS_TITLE.casefold()}</title>"
    folded = after.casefold()
    return title not in before.casefold() and title in folded and ("<h1" not in folded)


@dataclass(frozen=True)
class Shape:
    """A restyle of a refusal page, and the test of what it is shaped to move."""

    name: str
    apply: Callable[[str], str]
    moved: Callable[[str, str], bool]
    #: Whether the shape moves a block marker, and so has nothing to move in a
    #: sample that carries none. A shape that does not (a retitle) is measured
    #: over every sample.
    moves_marker: bool = False


#: Shapes whose effect is checked. "as recorded" is the unshaped control and is
#: deliberately not a member: it moves nothing by construction.
SHAPES: tuple[Shape, ...] = (
    Shape("named innocuously", named_innocuously, _title_restyled),
    Shape("buried", buried, _marker_moved_later, moves_marker=True),
)

AS_RECORDED = "as recorded"


def shaped_pages() -> dict[str, Callable[[str], str]]:
    """Every shape the liveness test applies, control included."""
    return {AS_RECORDED: lambda body: body, **{s.name: s.apply for s in SHAPES}}


def marker_bearing(samples: tuple[Sample, ...]) -> list[Sample]:
    """The samples with a block-page marker — the only ones a marker-relocating
    shape has anything to move in."""
    return [s for s in samples if first_marker_offset(s[2]) is not None]


#: A product that shrank must not read as a clean zero: ten marker-bearing
#: samples for `buried` plus all thirteen samples for `named innocuously`.
#: arsenal-floor-margin: MINIMUM_SHAPE_CELLS value=23
MINIMUM_SHAPE_CELLS = 23


def measure(
    samples: tuple[Sample, ...] = RATE_LIMIT_SAMPLES,
    shapes: tuple[Shape, ...] = SHAPES,
) -> dict[str, Any]:
    """The (sample, shape) cells whose shaping left the
    thing the shape exists to move where it was."""
    stuck: list[str] = []
    compared = 0
    bearing = marker_bearing(samples)
    for shape in shapes:
        for case, _status, body in bearing if shape.moves_marker else samples:
            compared += 1
            if not shape.moved(body, shape.apply(body)):
                stuck.append(f"{case} / {shape.name}")
    measured: dict[str, Any] = {
        "fixture_shape_cells_that_relocate_nothing": len(stuck),
        "cells_compared": compared,
        "cells_compared_at_least": MINIMUM_SHAPE_CELLS,
        "gate_status": "measured" if compared >= MINIMUM_SHAPE_CELLS else "unmeasured",
    }
    if stuck:
        measured["cells"] = stuck
    return measured
