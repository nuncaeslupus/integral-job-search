"""T183 — take the candidate's photo from their own CV, never ask for one.

A Spanish CV without a photo reads as incomplete, and the candidate's photo is
usually already inside the source PDF she handed over at intake. Extraction
therefore happens at **intake** (`cv_store.import_document` calls
`extract_photo`), and step 11 reads the stored asset instead of asking.

The heuristic, and its stated ceiling:

* look only at the raster images on **page 1**, ignoring soft masks and
  stencil masks (they are alpha channels, not pictures);
* take the **largest by pixel area**;
* accept it only if its short side is at least `MIN_SHORT_SIDE` pixels and its
  width/height ratio lies in [`MIN_ASPECT`, `MAX_ASPECT`].

The test is applied to the largest image, *not* used to filter the field
first. Filtering first would let a small square icon (a LinkedIn glyph, a
flag) win once a banner or wide logo had been discarded, which is a fail-open
answer: a picture the candidate never chose, in the header of a document sent
to an employer. Testing the largest means a designed CV whose biggest raster
is a logo yields **no photo** — a normal outcome, not an error. Two images
tied for largest are ambiguous and also yield no photo. The remedy for a
designed CV that still beats the heuristic is to show the candidate what was
found and let them veto, not a fourth rule.

Every failure (no `pdfimages`, unreadable PDF, no image) is `None`. Nothing is
invented and the candidate is never asked for a file.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

MIN_SHORT_SIDE = 200
MIN_ASPECT = 0.6
MAX_ASPECT = 1.4
_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class _Listed:
    index: int  # position among ALL listed rows: pdfimages numbers files by it
    kind: str
    width: int
    height: int


def _run(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        done = subprocess.run(
            args, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done if done.returncode == 0 else None


def _list_page_one(pdf: Path) -> list[_Listed] | None:
    done = _run(["pdfimages", "-list", "-f", "1", "-l", "1", "--", str(pdf)])
    if done is None:
        return None
    rows: list[_Listed] = []
    for line in done.stdout.splitlines()[2:]:  # two header lines
        cells = line.split()
        if len(cells) < 5 or not cells[0].isdigit():
            continue
        try:
            rows.append(_Listed(len(rows), cells[2], int(cells[3]), int(cells[4])))
        except ValueError:
            return None
    return rows


def choose(rows: list[_Listed]) -> _Listed | None:
    """The photo among the listed rows, or `None` (see the module docstring)."""
    pictures = [r for r in rows if r.kind == "image" and r.width > 0 and r.height > 0]
    if not pictures:
        return None
    ranked = sorted(pictures, key=lambda r: r.width * r.height, reverse=True)
    best = ranked[0]
    if len(ranked) > 1 and ranked[1].width * ranked[1].height == best.width * best.height:
        return None
    if min(best.width, best.height) < MIN_SHORT_SIDE:
        return None
    if not MIN_ASPECT <= best.width / best.height <= MAX_ASPECT:
        return None
    return best


def extract_photo(pdf: Path) -> bytes | None:
    """PNG bytes of the candidate's photo from page 1 of `pdf`, else `None`."""
    rows = _list_page_one(pdf)
    if not rows:
        return None
    best = choose(rows)
    if best is None:
        return None
    try:
        with tempfile.TemporaryDirectory() as scratch:
            prefix = Path(scratch) / "img"
            if (
                _run(["pdfimages", "-png", "-f", "1", "-l", "1", "--", str(pdf), str(prefix)])
                is None
            ):
                return None
            produced = Path(f"{prefix}-{best.index:03d}.png")
            if not produced.is_file():
                return None
            data = produced.read_bytes()
    except OSError:
        return None
    return data or None
