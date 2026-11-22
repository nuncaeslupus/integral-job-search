"""The live fetcher step 7 uses: `source()` over the network, through `integral.transport` (#920).

`source()` and `source_every_phrase()` take a `fetch` and never open a socket
themselves. Until this module the only fetchers that shipped were fixtures and
browser captures, so every session wrote its own HTTP code for the live round —
its own User-Agent, timeout, redirect rule, size limit and decoding. This is the
one a session uses instead, and the step-7 skill forbids any other:

    uv run python -m integral.live_fetch run --handle <handle> [--offset N] [--browser PAGE ...]

or, from Python, `source_every_phrase(store, constraints, aim, fetch=live_fetch())`.

Every request goes through `Transport`: https only, a public address, robots.txt
under `USER_AGENT` on every hop, the origin's crawl delay, a size cap. The body is
decoded with the connector's own `charset` by `decode_body`, which refuses rather
than replaces. Nothing here raises into the round: a refusal, a network fault or an
undecodable body comes back as a `Response` with `error` set, which `source()`
already reports per board.
"""

from __future__ import annotations

import argparse
import http.client
import sys
from datetime import UTC, datetime
from pathlib import Path

from integral.candidate import load_constraints
from integral.connectors import ConnectorError, ListRequest, decode_body
from integral.constraints_step import CONSTRAINTS_PARTS
from integral.identity import ProfileStore, default_profiles_root
from integral.robots import Robots
from integral.search_terms import load_aim
from integral.sourcing import Fetch, Response, from_captures, source, source_every_phrase
from integral.transport import FetchRefused, Send, Transport


def live_fetch(robots: Robots | None = None, *, send: Send | None = None) -> Fetch:
    """A `sourcing.Fetch` over the network, every hop guarded by `integral.transport`.

    `source()` spaces each request itself before calling a fetch (its cache decides
    whether a request is made at all), so the first hop is not spaced twice here;
    every redirect hop still is.
    """
    transport = Transport(robots, send=send)

    def fetch(request: ListRequest) -> Response:
        try:
            hop = transport.request(
                request.url,
                method=request.method,
                headers=request.headers,
                body=request.body,
                first_hop_spaced=True,
            )
        except FetchRefused as exc:
            return Response(None, "", error=f"refused: {exc}")
        except (OSError, http.client.HTTPException) as exc:
            return Response(None, "", error=f"unreachable: {exc}")
        try:
            body = decode_body(hop.raw, request.charset)
        except ConnectorError as exc:
            return Response(hop.status, "", error=str(exc))
        return Response(hop.status, body)

    return fetch


def _run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m integral.live_fetch run")
    parser.add_argument("--handle", required=True)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--offset",
        type=int,
        default=None,
        help="resume one window at this offset, as a run's NOT-searched line says",
    )
    parser.add_argument(
        "--browser",
        type=Path,
        nargs="*",
        default=(),
        help="pages the candidate's own browser saved, for `client: browser` boards",
    )
    args = parser.parse_args(argv)
    store = ProfileStore(args.root or default_profiles_root(), args.handle)
    if not store.exists(*CONSTRAINTS_PARTS):
        print(f"no constraints recorded for {args.handle}: run step 2 first", file=sys.stderr)
        return 2
    constraints = load_constraints(store.read_json(*CONSTRAINTS_PARTS))
    aim = load_aim(store)
    fetch = live_fetch()
    browser = from_captures(args.browser) if args.browser else None
    at = datetime.now(UTC).isoformat(timespec="seconds")
    if args.offset is None:
        run = source_every_phrase(store, constraints, aim, fetch=fetch, browser=browser, at=at)
    else:
        run = source(
            store, constraints, aim, fetch=fetch, browser=browser, at=at, offset=args.offset
        )
    print(run.summary())
    return 0


def _main(argv: list[str]) -> int:
    if not argv or argv[0] != "run":
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        print("usage: python -m integral.live_fetch run --handle H [--root DIR]", file=sys.stderr)
        return 2
    return _run(argv[1:])


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
