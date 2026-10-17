"""T342: record the employer's measured colours with a version, and render from that record.

Step 11 colours a document in the employer's own palette. The *counting* is done in the
employer's page by `tools/measure_colours.js` (one function, run in the browser console,
printing `{colour: element count}`); this module takes that JSON from there.

* `python -m integral.brand_measure --site URL [--counts FILE]` reads the JSON (stdin when
  no file), prints the `trazabilidad_section` (`--json`: the palette), and with
  `--root R --handle H --offer O --version N` records the measurement in that version's
  `palette.json`; `--trazabilidad FILE` appends the section to that file.
* The accent a document is rendered with is **re-derived from the recorded counts**
  (`palette_for`), never read from a stored colour, so the document cannot carry an
  accent nobody measured. `approval.stage_send` and `verify_send` render with it.
* `versions_without_measurement` lists the generated versions with no record: those are
  the ones the T342 gate counts.

`palette.json` is not Markdown, so it never joins a payload's documents or the `send/`
folder.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from integral.brand_palette import BrandPalette, extract_palette, trazabilidad_section
from integral.identity import ProfileStore

MEASUREMENT_FILE = "palette.json"
SCHEMA_VERSION = 1


class MeasureError(ValueError):
    """The measurement cannot be read, or is not the shape the snippet returns."""


def parse_counts(text: str) -> dict[str, int]:
    """`{colour: count}` from the snippet's JSON; anything else is refused, not repaired."""
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise MeasureError(f"the colour counts are not JSON: {exc}") from exc
    return checked_counts(raw)


def checked_counts(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise MeasureError("the colour counts must be a JSON object {colour: count}")
    counts: dict[str, int] = {}
    for colour, n in raw.items():
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
            raise MeasureError(f"the count for {colour!r} is {n!r}, not a positive whole number")
        counts[str(colour)] = n
    return counts


def record(store: ProfileStore, where: Sequence[str], site: str, counts: Mapping[str, int]) -> Path:
    """Write the measurement into the version directory `where`; returns the file."""
    return store.write_json(
        {"schema_version": SCHEMA_VERSION, "site": site, "counts": dict(counts)},
        *where,
        MEASUREMENT_FILE,
    )


def read_measurement(
    store: ProfileStore, where: Sequence[str]
) -> tuple[str, dict[str, int]] | None:
    """`(site, counts)` recorded for the version, or None when nothing was recorded."""
    if not store.exists(*where, MEASUREMENT_FILE):
        return None
    try:
        data = store.read_json(*where, MEASUREMENT_FILE)
        if data["schema_version"] != SCHEMA_VERSION:
            raise MeasureError(f"schema_version {data['schema_version']!r} is not {SCHEMA_VERSION}")
        return str(data["site"]), checked_counts(data["counts"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MeasureError(f"{MEASUREMENT_FILE} cannot be read: {exc}") from exc


def palette_for(store: ProfileStore, where: Sequence[str]) -> BrandPalette | None:
    """The palette the recorded counts give; None when the version has no record."""
    measured = read_measurement(store, where)
    return None if measured is None else extract_palette(measured[1])


def generated_versions(store: ProfileStore) -> list[tuple[str, ...]]:
    """Every `cv/generated/<offer>/v<N>` directory of the profile, sorted."""
    base = store.path("cv", "generated")
    if not base.is_dir():
        return []
    return sorted(
        ("cv", "generated", offer.name, version.name)
        for offer in base.iterdir()
        if offer.is_dir()
        for version in offer.iterdir()
        if version.is_dir() and version.name.startswith("v")
    )


def versions_without_measurement(store: ProfileStore) -> list[tuple[str, ...]]:
    """The generated versions with no recorded colour measurement."""
    return [
        where for where in generated_versions(store) if not store.exists(*where, MEASUREMENT_FILE)
    ]


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m integral.brand_measure",
        description="Turn tools/measure_colours.js output into a palette and its trazabilidad.",
    )
    parser.add_argument("--site", required=True, help="the page the colours were measured on")
    parser.add_argument("--counts", help="the snippet's JSON file (default: standard input)")
    parser.add_argument("--json", action="store_true", help="print the palette as JSON")
    parser.add_argument("--trazabilidad", help="append the section to this file")
    parser.add_argument("--root", help="profiles root, to record in a version directory")
    parser.add_argument("--handle")
    parser.add_argument("--offer")
    parser.add_argument("--version", type=int)
    args = parser.parse_args(argv)
    recording = [args.root, args.handle, args.offer, args.version]
    if any(v is not None for v in recording) and any(v is None for v in recording):
        parser.error("--root, --handle, --offer and --version go together")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        text = Path(args.counts).read_text(encoding="utf-8") if args.counts else sys.stdin.read()
        counts = parse_counts(text)
    except (OSError, MeasureError) as exc:
        print(f"brand_measure: {exc}", file=sys.stderr)
        return 2
    palette = extract_palette(counts)
    if args.root is not None:
        from integral.identity import IdentityError

        try:
            store = ProfileStore(Path(args.root), args.handle)
            where = ("cv", "generated", args.offer, f"v{args.version}")
            if not store.path(*where).is_dir():
                raise MeasureError(f"{'/'.join(where)} is not a generated version")
            record(store, where, args.site, counts)
        except (OSError, MeasureError, IdentityError, ValueError) as exc:
            print(f"brand_measure: {exc}", file=sys.stderr)
            return 2
    section = trazabilidad_section(palette, args.site)
    if args.trazabilidad:
        with Path(args.trazabilidad).open("a", encoding="utf-8") as stream:
            stream.write("\n" + section)
    if args.json:
        print(
            json.dumps(
                {
                    "source": palette.source,
                    "reason": palette.reason,
                    "ink": palette.ink,
                    "paper": palette.paper,
                    "accent": palette.decorative_hex,
                    "accent_text": palette.text_hex,
                    "measured": palette.measured,
                }
            )
        )
    else:
        print(section, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
