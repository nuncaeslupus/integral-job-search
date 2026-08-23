"""Whether a URL may be fetched, according to the site's own robots.txt.

Stdlib only, for the same reason `corpus.py` is: the decision belongs to
`tools/collect_ads.py`, which needs the scraping stack, but the *rule* must be
testable without it. `urllib.robotparser` implements the matching; this adds
the two things it leaves to the caller — where the file comes from, and what to
do when it cannot be read.

**The user agent is the whole point.** robots.txt is addressed to whoever the
client says it is, so a client that lies about its identity is not complying
with the file, it is evading it. Both boards this repository has collected from
say so explicitly: `tecnoempleo.com` allows `User-agent: *` on its listings and
`Disallow: /` for nine named AI crawlers, and `remoteok.com` does the same in a
Cloudflare-managed block. An honest name is what makes the `*` rules the ones
that apply.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

# Who we say we are. A contact URL, because a board that wants this to stop
# needs somewhere to say so — that is the half of politeness a delay cannot do.
USER_AGENT = "integral-job-search/0.1 (+https://github.com/nuncaeslupus/integral-job-search)"

Fetch = Callable[[str], str]


class RobotsError(RuntimeError):
    """The site's rules could not be established, so nothing may be fetched."""


def _read(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        return str(response.read().decode("utf-8", errors="replace"))


class Robots:
    """One robots.txt per host, fetched once and remembered."""

    def __init__(self, user_agent: str = USER_AGENT, fetch: Fetch = _read) -> None:
        self.user_agent = user_agent
        self._fetch = fetch
        self._parsers: dict[str, RobotFileParser] = {}

    def _parser(self, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._parsers:
            parser = RobotFileParser()
            try:
                parser.parse(
                    self._fetch(
                        urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
                    ).splitlines()
                )
            except urllib.error.HTTPError as exc:
                # 404 is the site saying "no rules", which permits everything.
                # Anything else — 403, 500, a redirect loop — is an unanswered
                # question, and an unanswered question is not a yes.
                if exc.code != 404:
                    raise RobotsError(f"{origin}/robots.txt returned {exc.code}") from exc
                parser.parse([])
            except OSError as exc:
                raise RobotsError(f"{origin}/robots.txt could not be read: {exc}") from exc
            self._parsers[origin] = parser
        return self._parsers[origin]

    def allows(self, url: str) -> bool:
        return bool(self._parser(url).can_fetch(self.user_agent, url))

    def delay(self, url: str, floor: float) -> float:
        """The site's crawl-delay, or `floor` — whichever asks us to wait longer."""
        stated = self._parser(url).crawl_delay(self.user_agent)
        return max(floor, float(stated)) if stated is not None else floor
