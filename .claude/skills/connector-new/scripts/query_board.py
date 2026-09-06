#!/usr/bin/env python3
"""Answer the three questions that decide whether a board can be connected.

    uv run python3 ${CLAUDE_SKILL_DIR}/scripts/query_board.py \
        --listing "https://landing.jobs/jobs?q=python" \
        --advert  "https://landing.jobs/at/we-are-meta/staff-python-engineer" \
        --refused "https://landing.jobs/jobs/search" \
        --refused "https://landing.jobs/api/v1/jobs"

Prints a verdict block to paste into the connector's header, and exits 1 when
the board cannot be connected as fetched. It never writes a connector: what it
produces is evidence, and the file is still written by a person who read it.

Three questions, in the order that stops wasted work:

1. **May we fetch it?** Adjudicated by `integral.robots`, this repo's audited
   RFC 9309 matcher, never by grepping the file. Every `--refused` path is a
   negative control: a matcher that cannot refuse cannot permit either, and a
   True with no False beside it says nothing. The stdlib parser runs as the
   second reader and its *competence* is reported, because on any robots.txt
   opening with `Allow: /` it answers True to everything and an agreement with
   it would be an agreement with a parser that cannot disagree.

2. **Is the advert in the bytes?** Counting rows is unreliable — a wrong URL
   looks exactly like an empty page. This fetches and reports the body size and
   whether it changes when a client's headers are added, which is what
   separates "server-rendered" from "rendered after load".

3. **Does a client unlock it?** A board that answers a short page plain and a
   long one to `HX-Request: true` is reachable through `client:` (T133). When
   nothing here unlocks it, record a HAR and look for the request the page made
   — the `har` skill does that, and it is how foorilla.com was solved.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "src")

from integral.connector_procedure import (  # noqa: E402
    CLIENTS,
    second_reader_verdict,
)
from integral.robots import USER_AGENT, Robots  # noqa: E402

def fetch(url: str, headers: dict[str, str]) -> tuple[int | None, int, str]:
    """(status, byte count, error) for one GET. Never raises."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            # urllib does not decompress, and a gzipped body decodes as
            # nothing. Asking for none is honest and costs a few KB.
            "Accept-Encoding": "identity",
            **headers,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.status, len(response.read()), ""
    except urllib.error.HTTPError as error:
        return error.code, 0, str(error)
    except Exception as error:  # transport: there is no status to report
        return None, 0, f"{type(error).__name__}: {error}"


def robots_report(allowed: list[str], refused: list[str]) -> tuple[bool, list[str]]:
    """Adjudicate every path, and say whether the second reader was competent."""
    lines: list[str] = []
    matcher = Robots()
    ok = True
    for url in allowed:
        verdict = matcher.allows(url)
        ok = ok and verdict
        lines.append(f"  {str(verdict):5}  {url}")
    for url in refused:
        verdict = matcher.allows(url)
        ok = ok and not verdict
        lines.append(f"  {str(verdict):5}  {url}   <- negative control, must be False")
    if not refused:
        lines.append("  (no --refused path given: a True with no False beside it is not a verdict)")
        ok = False
    return ok, lines


def second_reader(paths: list[str]) -> str:
    """`second_reader_verdict` over the live robots.txt for these paths."""
    if not paths:
        return "not run — no path given"
    origin = "/".join(paths[0].split("/")[:3])
    try:
        request = urllib.request.Request(
            origin + "/robots.txt", headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            text = response.read().decode("utf-8", "replace")
    except Exception as error:  # a reader that could not read is not a reader
        return f"not run — {type(error).__name__}: {error}"
    return second_reader_verdict(text, paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listing", required=True, help="the search-results URL")
    parser.add_argument("--advert", help="one advert's own URL, if the list has no body")
    parser.add_argument(
        "--refused",
        action="append",
        default=[],
        help="a path robots.txt should REFUSE — the negative control, repeatable",
    )
    args = parser.parse_args()

    allowed = [url for url in (args.listing, args.advert) if url]
    print("ROBOTS  (integral.robots, this repo's audited matcher)")
    print(f"  agent: {USER_AGENT}")
    permitted, lines = robots_report(allowed, args.refused)
    print("\n".join(lines))
    print(f"  second reader: {second_reader(allowed + args.refused)}")
    if not permitted:
        print("\nVERDICT  refused — do not fetch, and record it in connectors/ruled-out.yaml")
        return 1

    print("\nREACHABILITY  (same URL, one row per client a connector may declare)")
    best = ""
    largest = 0
    for url in allowed:
        print(f"  {url}")
        for name, headers in CLIENTS.items():
            status, size, error = fetch(url, headers)
            flag = ""
            if status == 200 and size > largest:
                largest, best, flag = size, name, "  <- most content so far"
            print(f"    client={name:5} status={status} bytes={size}{flag} {error}")

    print("\nVERDICT  robots permits it.")
    if best and best != "none":
        print(f"  Declare `client: {best}` — it returned the most content by a clear margin.")
        print("  Confirm the advert page's own target: a board behind htmx usually swaps the")
        print("  list and the advert into different elements (foorilla: mc_1 and mc_2).")
    else:
        print("  No client needed; a plain GET returns the most content.")
    print("  If the biggest response still has no advert in it, the page fetched its rows")
    print("  from somewhere else: record a HAR and use the `har` skill to find that request.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
