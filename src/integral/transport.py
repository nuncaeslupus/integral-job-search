"""The one HTTP layer: every request this package sends goes through here (#929).

There used to be four — `robots._read`, `canonical_ad.guarded_fetch`,
`connector_exchange.https_fetcher` and `tools/collect_ads.get` — each with its own
redirect rule, delay, size limit and decoding. They agreed on nothing in particular,
so each guard held only where somebody had remembered to write it. Here every hop of
every request, redirects included, is put through the same checks, in this order:

1. **https only.** A redirect off https is refused like a first URL off it.
2. **A public address.** `is_public_web_url`: never localhost, a private range, or a
   legacy spelling of one (`2130706433`). Links come from scraped adverts.
3. **The caller's own refusal hook**, when it has one (the corpus collector's ledger).
4. **robots.txt**, through `integral.robots`, under this tool's own `USER_AGENT`.
   Unreadable is refused, never permitted.
5. **Spacing** — at least the origin's Crawl-delay, or `REQUEST_FLOOR_SECONDS`,
   between two requests to one origin in this process (`space`).
6. **A size cap.** A body larger than `max_bytes` is refused, not truncated: a cut
   page reads as a complete one downstream.

The robots.txt fetch itself is the one request that cannot ask robots.txt first;
it goes through `fetch_policy`, which keeps 1, 2 and 6 and follows at most
`MAX_REDIRECTS` hops (RFC 9309 §2.3.1.2).

    Transport().request("https://example.com/jobs")   # -> Hop, or FetchRefused
"""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from email.message import Message
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urljoin, urlsplit

if TYPE_CHECKING:
    from integral.robots import Robots

# Who we say we are. A contact URL, because a board that wants this to stop
# needs somewhere to say so — that is the half of politeness a delay cannot do.
USER_AGENT = "integral-job-search/0.1 (+https://github.com/nuncaeslupus/integral-job-search)"

#: The strictest of the old stacks (`tools/collect_ads.py`); urllib's own default was 10.
MAX_REDIRECTS = 5
DEFAULT_TIMEOUT = 20.0
#: A starting value: an advert page is some hundreds of KiB, and an endless answer
#: must not be read whole into memory.
MAX_PAGE_BYTES = 5 * 1024 * 1024
#: RFC 9309 asks a crawler to parse at least 500 KiB of robots.txt.
MAX_POLICY_BYTES = 512 * 1024
#: The least gap kept between two requests to one origin when its robots.txt states
#: no `Crawl-delay`. A starting value rather than a rule of the web: a longer stated
#: Crawl-delay still wins, and a host that asks for less is not given less.
REQUEST_FLOOR_SECONDS = 1.0
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
#: What survives a redirect to another origin: ours, and nothing the caller added.
_CROSS_ORIGIN_HEADERS = frozenset({"user-agent", "accept", "accept-encoding"})


class FetchRefused(Exception):
    """A request this layer will not send, or a body it will not accept.

    Deliberately not an `OSError`: callers treat `OSError` as "the network failed,
    try later", and a refusal is a decision, not a fault.
    """


class BodyTooLarge(FetchRefused):
    """The answer was larger than the cap the caller set."""


class RobotsRefused(FetchRefused):
    """robots.txt disallows the URL for this tool, or could not be read (fail closed)."""


def _embedded_ipv4(address: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """Every IPv4 address an IPv6 literal can carry: mapped, 6to4, Teredo, and the low 32 bits.

    A closed rule rather than a list of prefixes: IPv4-compatible addresses, NAT64
    (RFC 6052) and any translator prefix not yet named all put the IPv4 address in
    the last 32 bits. Taking those bits from *every* IPv6
    literal also refuses a public IPv6 address whose last four bytes happen to read
    as a private IPv4 one — accepted, since no board is reached by IPv6 literal.
    """
    found = [ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)]
    if address.ipv4_mapped is not None:
        found.append(address.ipv4_mapped)
    if address.sixtofour is not None:
        found.append(address.sixtofour)
    if address.teredo is not None:
        found.extend(address.teredo)
    return found


def is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Globally routable, and so is every IPv4 address an IPv6 one carries."""
    if not address.is_global:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        return all(inner.is_global for inner in _embedded_ipv4(address))
    return True


def _unsafe_host_text(host: str) -> bool:
    """`%`, NUL, whitespace or a control character: no hostname needs one (#993 F1).

    urllib unquotes the host before it connects, so `127%2e0%2e0%2e1` classified as
    a name here would reach 127.0.0.1. Refusing the characters closes every
    spelling at once, rather than decoding and classifying again.
    """
    return any(c == "%" or c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in host)


def is_public_web_url(url: str) -> bool:
    """http(s) to a named host or a public IP; never localhost or a private address.

    Links come from scraped adverts, so one pointing at `http://127.0.0.1:8080/` or an
    intranet address must not be requested from the candidate's machine. A named host
    passes here and is checked again where it is resolved (`_checked_connection`).
    A URL carrying userinfo (`https://u@host/`) is refused: no board needs one.
    """
    parts = urlsplit(url)
    raw_host = parts.netloc.rpartition("@")[2]
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme.lower() not in ("http", "https") or not host:
        return False
    if "@" in parts.netloc or _unsafe_host_text(raw_host) or _unsafe_host_text(host):
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        address: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(host)
    except ValueError:
        # The resolver also reads the legacy IPv4 spellings `ipaddress` refuses —
        # `2130706433`, `0x7f000001`, `0177.0.0.1`, `127.1` are all 127.0.0.1.
        try:
            address = ipaddress.IPv4Address(socket.inet_aton(host))
        except OSError:
            return True
    return is_public_address(address)


def origin(url: str) -> str:
    """RFC 6454's (scheme, host, port), with the default port filled in.

    `https://www.usajobs.gov:443/job/…` and `https://www.usajobs.gov/…` are one origin,
    or a refusal on one spelling leaves the other free to be asked (#466 F1).
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    port: int | str | None
    try:
        port = parts.port or {"http": 80, "https": 443}.get(scheme)
    except ValueError:  # a malformed port in a board's own link: keep it as written
        port = parts.netloc.rpartition(":")[2].lower()
    return f"{scheme}://{parts.hostname or ''}:{port}"


@dataclass(frozen=True)
class Hop:
    """One answer: its status, headers, raw bytes and the URL that gave it."""

    status: int
    headers: Mapping[str, str]
    raw: bytes
    url: str

    @property
    def charset(self) -> str | None:
        content_type = self.headers.get("Content-Type") or self.headers.get("content-type")
        if not content_type:
            return None
        message = Message()
        message["Content-Type"] = content_type
        return message.get_content_charset()

    def text(self) -> str:
        """The body by its declared charset, utf-8 by default, never raising."""
        try:
            return self.raw.decode(self.charset or "utf-8", "replace")
        except LookupError:  # a charset name Python does not know
            return self.raw.decode("utf-8", "replace")


#: method, url, headers, body, timeout, max_bytes -> one hop, redirects NOT followed.
Send = Callable[[str, str, Mapping[str, str], bytes | None, float, int], Hop]


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Hand every 3xx back: redirects are followed by `Transport`, one checked hop at a time."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _checked_addresses(host: str, port: int) -> list[tuple[str, int]]:
    """Resolve `host` and refuse unless EVERY address is public (#993 F2).

    One non-public answer refuses the name: a name that resolves anywhere private
    is not a public board, and trying the public addresses first would let a
    rebinding answer through on a retry.
    """
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    checked: list[tuple[str, int]] = []
    for *_, sockaddr in infos:
        ip = str(sockaddr[0]).split("%", 1)[0]
        if not is_public_address(ipaddress.ip_address(ip)):
            raise FetchRefused(f"{host} resolves to {ip}, which is not a public address")
        checked.append((ip, port))
    if not checked:
        raise OSError(f"{host} did not resolve")
    return checked


def _checked_create_connection(conn: http.client.HTTPConnection) -> Callable[..., socket.socket]:
    """`socket.create_connection` that connects only to the addresses it checked.

    The connection is made to the checked IP, so the name is resolved once and
    the answer that was checked is the one used (no rebinding between the two).
    TLS still verifies against the hostname: `HTTPSConnection` wraps this socket
    with `server_hostname=self.host`. Through a proxy (`CONNECT`), the proxy makes
    the connection: the target's own resolution is checked here, but what the
    proxy resolves cannot be — that remainder is recorded as a follow-up task.
    """

    def create(
        address: tuple[str, int], timeout: Any = None, source_address: Any = None
    ) -> socket.socket:
        tunnel = getattr(conn, "_tunnel_host", None)
        if tunnel:
            _checked_addresses(tunnel, getattr(conn, "_tunnel_port", None) or 443)
            return socket.create_connection(address, timeout, source_address)
        last: OSError | None = None
        for checked in _checked_addresses(address[0], address[1]):
            try:
                return socket.create_connection(checked, timeout, source_address)
            except OSError as exc:
                last = exc
        assert last is not None  # `_checked_addresses` returns at least one address
        raise last

    return create


class _CheckedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        setattr(self, "_create_connection", _checked_create_connection(self))  # noqa: B010


class _CheckedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        setattr(self, "_create_connection", _checked_create_connection(self))  # noqa: B010


class _CheckedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_CheckedHTTPConnection, req)


class _CheckedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_CheckedHTTPSConnection, req, context=getattr(self, "_context", None))


_OPENER = urllib.request.build_opener(_NoRedirects(), _CheckedHTTPHandler(), _CheckedHTTPSHandler())


def _read_capped(reply: Any, max_bytes: int, url: str) -> bytes:
    raw = reply.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise BodyTooLarge(f"{url} answered more than {max_bytes} bytes")
    return bytes(raw)


def urllib_send(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
    timeout: float,
    max_bytes: int,
) -> Hop:
    """The real socket. Network failures raise `OSError`; an HTTP status never does."""
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with _OPENER.open(request, timeout=timeout) as reply:
            return Hop(reply.status, dict(reply.headers), _read_capped(reply, max_bytes, url), url)
    except urllib.error.HTTPError as exc:
        with contextlib.closing(exc):
            raw = _read_capped(exc, max_bytes, url) if exc.fp is not None else b""
        return Hop(exc.code, dict(exc.headers or {}), raw, url)


# --------------------------------------------------------------------------- spacing

#: `time.sleep`, named so a test can replace it rather than wait.
_pause: Callable[[float], None] = time.sleep
_clock: Callable[[], float] = time.monotonic
#: When this process last requested each origin. Per origin and not per board:
#: 56 Greenhouse boards are one host, and each used to start its own count.
_last_request_at: dict[str, float] = {}


class Policy(Protocol):
    """What this layer needs from `integral.robots.Robots`."""

    def allows(self, url: str) -> bool: ...

    def delay(self, url: str, floor: float) -> float: ...


@contextlib.contextmanager
def no_waiting() -> Iterator[None]:
    """Skip the spacing sleep: for constructed rounds that touch no real host."""
    global _pause
    kept, _pause = _pause, lambda _seconds: None
    try:
        yield
    finally:
        _pause = kept


def space(robots: Policy, url: str, floor: float = REQUEST_FLOOR_SECONDS) -> None:
    """Wait out the origin's gap since our previous request to it, then record this one.

    The first request to an origin waits only if its robots.txt was just read: that
    read is recorded too (`fetch_policy`), so it counts as the previous request.
    """
    key = origin(url)
    last = _last_request_at.get(key)
    if last is not None:
        wait = robots.delay(url, floor) - (_clock() - last)
        if wait > 0:
            _pause(wait)
    _last_request_at[key] = _clock()


# --------------------------------------------------------------------------- requests


def _hop_target(url: str, hop: Hop) -> str | None:
    location = hop.headers.get("Location") or hop.headers.get("location")
    if hop.status in _REDIRECTS and location:
        return urljoin(url, location)
    return None


def fetch_policy(
    url: str,
    user_agent: str = USER_AGENT,
    send: Send | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Hop:
    """A robots.txt: public addresses only, no https->http downgrade, capped, <= 5 hops."""
    send = send if send is not None else urllib_send
    for _ in range(MAX_REDIRECTS + 1):
        if not is_public_web_url(url):
            raise FetchRefused(f"{url} is not a public web address")
        hop = send(
            "GET",
            url,
            {"User-Agent": user_agent, "Accept-Encoding": "identity"},
            None,
            timeout,
            MAX_POLICY_BYTES,
        )
        _last_request_at[origin(url)] = _clock()
        target = _hop_target(url, hop)
        if target is None:
            return hop
        if urlsplit(url).scheme == "https" and urlsplit(target).scheme != "https":
            raise FetchRefused(f"robots.txt redirect off https refused: {target}")
        url = target
    raise FetchRefused(f"more than {MAX_REDIRECTS} redirects reading {url}")


_SHARED: Robots | None = None


def shared_robots() -> Robots:
    """One `Robots` for every caller that does not bring its own: each robots.txt read once."""
    global _SHARED
    if _SHARED is None:
        from integral.robots import Robots  # robots imports this module

        _SHARED = Robots()
    return _SHARED


class Transport:
    """Requests that obey the six rules in the module docstring, on every hop."""

    def __init__(
        self,
        robots: Policy | None = None,
        *,
        refuse: Callable[[str], str | None] | None = None,
        send: Send | None = None,
        floor: float = REQUEST_FLOOR_SECONDS,
    ) -> None:
        self.robots = robots if robots is not None else shared_robots()
        self._refuse = refuse
        self._send = send if send is not None else urllib_send
        self._floor = floor

    def admit(self, url: str) -> None:
        """Raise `FetchRefused` unless rules 1-4 let `url` be requested."""
        from integral.robots import RobotsError

        if urlsplit(url).scheme != "https":
            raise FetchRefused(f"https only, not {url}")
        if not is_public_web_url(url):
            raise FetchRefused(f"{url} is not a public web address")
        if self._refuse is not None and (why := self._refuse(url)):
            raise FetchRefused(why)
        try:
            allowed = self.robots.allows(url)
        except RobotsError as exc:
            raise RobotsRefused(f"robots.txt could not be read for {url}: {exc}") from exc
        except ValueError as exc:  # a URL the robots fetch itself cannot send
            raise FetchRefused(f"{url} cannot be requested: {exc}") from exc
        if not allowed:
            raise RobotsRefused(f"robots.txt disallows {url} for {USER_AGENT}")

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_bytes: int = MAX_PAGE_BYTES,
        first_hop_spaced: bool = False,
    ) -> Hop:
        """Send one request, following redirects only through `admit` and `space`.

        `first_hop_spaced` is for a caller that already called `space` for `url`
        (sourcing does, because its cache decides whether a request is made at all);
        redirect hops are spaced regardless. A caller's `User-Agent` never wins.
        """
        sent = {**(headers or {}), "User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        for hop_number in range(MAX_REDIRECTS + 1):
            self.admit(url)
            if not (hop_number == 0 and first_hop_spaced):
                space(self.robots, url, self._floor)
            try:
                hop = self._send(method, url, sent, body, timeout, max_bytes)
            except ValueError as exc:  # http.client.InvalidURL: a URL it cannot send
                raise FetchRefused(f"{url} cannot be requested: {exc}") from exc
            target = _hop_target(url, hop)
            if target is None:
                return hop
            if hop.status not in (307, 308):  # RFC 9110 §15.4: these become a GET
                method, body = "GET", None
                sent = {k: v for k, v in sent.items() if k.lower() != "content-type"}
            if origin(target) != origin(url):
                # RFC 9110 §15.4: a caller's headers are for the origin it asked.
                keep = _CROSS_ORIGIN_HEADERS | ({"content-type"} if body is not None else set())
                sent = {k: v for k, v in sent.items() if k.lower() in keep}
            url = target
        raise FetchRefused(f"more than {MAX_REDIRECTS} redirects fetching {url}")
