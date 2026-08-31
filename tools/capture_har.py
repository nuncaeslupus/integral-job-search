#!/usr/bin/env python3
"""Record a HAR for one URL with a real browser engine, so the `har` skill has
something to read.

The skill says capturing is the browser's job, and it is right — but nobody is
sitting at this browser. Playwright drives the Chrome already installed on this
machine (`channel="chrome"`, no download) with a **fresh** profile: no cookies,
no logins, nothing of the owner's session. That matters more than the eight
lines it saves.

    uv run --with playwright python3 tools/capture_har.py <url> <out.har> [wait_ms]

ponytail: fresh context every run, no cookie reuse. If a board ever needs a
logged-in capture, that is the owner's own export, not this.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

# Chrome's own string plus our token — the site serves the real app, and still
# gets told who is asking. Same honesty T71 already accepts for a 403 retry.
UA_SUFFIX = " integral-job-search/0.1 (+https://github.com/nuncaeslupus/integral-job-search)"


def capture(url: str, out: Path, wait_ms: int = 6000) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        probe = browser.new_context()
        ua = probe.new_page().evaluate("navigator.userAgent")
        probe.close()

        context = browser.new_context(
            user_agent=ua + UA_SUFFIX,
            record_har_path=str(out),
            record_har_content="embed",
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(wait_ms)
        except PlaywrightError as exc:
            # `context.close()` is what writes the HAR, and nothing else does.
            # Let a navigation failure escape and the capture is never written
            # at all -- so the sites worth investigating hardest, the slow and
            # the hostile ones, are exactly the ones that leave no evidence.
            # feinaactiva.gencat.cat timed out here and produced no file.
            print(f"{url}: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            context.close()
        browser.close()
    print(f"{out} — {out.stat().st_size / 1_000_000:.1f} MB")


if __name__ == "__main__":
    capture(sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 6000)
