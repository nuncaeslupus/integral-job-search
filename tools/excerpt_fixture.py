#!/usr/bin/env python3
"""Reduce a recorded connector fixture to an excerpt that is safe to commit.

A fixture's job is to prove the connector finds the right *fields* in real
markup. It does not need to carry whole job adverts to do that, and it should
not: `connectors/` is a public library of crawlers, and an advert body is the
board's content, not ours. Only the crawler belongs in the repository.

**The edit is made in the raw bytes, never through a parse-and-reserialise.**
Round-tripping the page through `lxml` would silently repair whatever the
server got wrong — unclosed tags, stray end tags, quoting the spec does not
allow — and repaired markup is exactly what a fixture must not be. The repo's
own parser implements no HTML5 tree-repair rules, so a fixture that arrived
pre-repaired would stop testing the thing it exists to test. Everything
outside the truncated spans is therefore byte-identical to what the server
sent.

Two structures are preserved even where truncated:

* the body's nested `<p>`/`<ul>` children, so nesting is still exercised;
* the listing teaser's trailing ellipsis, which is how the connector's own
  test tells a preview from a full body.

Run it after recording, before committing, then re-run
`tools/annotate_connector_fixture.py` — the expectation is derived from the
bytes actually kept.

Usage:
    python tools/excerpt_fixture.py connectors/trabajos_es
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from integral.connectors import load_connector

TEASER_CHARS = 120
BODY_CHARS = 300
BODY_LIST_ITEMS = 2
MARKER = "<p>[fixture excerpt — body truncated, see meta.yaml]</p>"

_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
# The containers this touches hold no nested <div>, checked before use, so a
# non-greedy match to the next close tag is exact.
_CHILD = re.compile(r"<(p|ul)\b[^>]*>.*?</\1>", re.S | re.I)
_ITEM = re.compile(r"<li\b[^>]*>.*?</li>", re.S | re.I)
_CLASS = re.compile(r"\.([\w-]+)")


def visible(html: str) -> str:
    return _WS.sub(" ", _TAGS.sub(" ", html)).strip()


def _spans(raw: str, css_class: str) -> list[tuple[int, int, str]]:
    """(start, end, inner) for every `<div class="…">…</div>` with that class."""
    found = []
    for match in re.finditer(rf'<div class="{re.escape(css_class)}"[^>]*>', raw):
        close = raw.find("</div>", match.end())
        if close != -1:
            found.append((match.end(), close, raw[match.end() : close]))
    return found


def excerpt_teaser(inner: str) -> str | None:
    text = visible(inner)
    if len(text) <= TEASER_CHARS:
        return None
    return "\n" + text[:TEASER_CHARS].rsplit(" ", 1)[0] + " ...\n"


def excerpt_body(inner: str) -> str | None:
    kept: list[str] = []
    running = 0
    took_list = False
    for child in _CHILD.finditer(inner):
        html = child.group(0)
        if running < BODY_CHARS:
            kept.append(html)
            running += len(visible(html))
        elif child.group(1).lower() == "ul" and not took_list:
            items = _ITEM.findall(html)[:BODY_LIST_ITEMS]
            kept.append("<ul>" + "".join(items) + "</ul>")
            took_list = True
    if not kept or (running <= BODY_CHARS and not took_list):
        return None
    return "\n" + "\n".join([*kept, MARKER]) + "\n"


def excerpt_package(package: Path) -> dict[str, int]:
    connector = load_connector(package)
    fixture = package / "fixture"
    changed: dict[str, int] = {}

    plan = [("list.html", connector.list.fields.get("text"), excerpt_teaser, "list_teasers")]
    if connector.detail is not None:
        plan.append(
            ("detail.html", connector.detail.fields.get("text"), excerpt_body, "detail_bodies")
        )

    for filename, field, rewrite, label in plan:
        path = fixture / filename
        if not path.exists() or field is None:
            continue
        classes = _CLASS.findall(field.css)
        if not classes:
            raise SystemExit(f"{filename}: {field.css!r} names no class to locate in the raw bytes")
        css_class = classes[0]
        # newline="" — not read_text(). Universal-newline translation turns a
        # server's CRLF into LF on the way in, so a round-trip through
        # read_text/write_text silently rewrites every line ending in the file.
        # This tool's whole claim is that everything outside an excerpted span
        # is the bytes the server sent; a normalised line ending is exactly the
        # kind of quiet repair the raw-bytes approach exists to avoid.
        with path.open(encoding="utf-8", newline="") as handle:
            raw = handle.read()
        count = 0
        # Right to left, so each replacement leaves earlier offsets valid.
        for start, end, inner in reversed(_spans(raw, css_class)):
            replacement = rewrite(inner)
            if replacement is None:
                continue
            raw = raw[:start] + replacement + raw[end:]
            count += 1
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(raw)
        changed[f"{label}_excerpted"] = count

    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("package", type=Path)
    args = ap.parse_args()
    before = {p.name: p.stat().st_size for p in (args.package / "fixture").iterdir()}
    changed = excerpt_package(args.package)
    after = {p.name: p.stat().st_size for p in (args.package / "fixture").iterdir()}
    print(changed)
    for name in sorted(before):
        print(f"  {name}: {before[name]} -> {after[name]} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
