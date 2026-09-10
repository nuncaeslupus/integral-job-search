"""T72 — a connector whose selectors no longer match its own markup is
reported broken, never a quiet zero.

`connector_coverage.py` asks whether a connector *exists* for a market;
`liveness.py` asks whether one *offer* is alive. Nothing asks whether the
connector itself still works — and `trabajos_es` is the only real board this
library has, so one restyle takes sourcing to zero with no signal at all
(`status/spec-v3-silent-success.md`).

`connectors.py`'s own module docstring settles where a request may come
from: "Fetching is not this module's job… a cloud session cannot reach one —
403 at the egress proxy." T12 is the module that turns a connector into a
live HTTP request, and it is `[LAPTOP]`-only for exactly that reason.

**The baseline and the probe must be two different reads, or this module
measures nothing.** `fixture/list.html` is the baseline: the response that
URL actually returned the day someone last verified this connector. The
probe is a *separately captured* read of the same query, taken on a later
day by the permitted `[LAPTOP]` process and committed to `probe/list.html`
beside `probe/captured.json`, which records when. An earlier revision
pointed the probe at `fixture/list.html` as well — so the production path
compared a string with itself, `silent_connector_failures` could only ever
be 0, and the evidence recorded `"gate_status": "measured"` on a module
whose entire purpose is detecting parser rot. Reading a file twice is not a
measurement; reading two captures taken on two different days is.

**The capture date is committed, never taken from the filesystem.** A
checkout does not preserve mtimes, so deriving it there would give every
clone a different answer and `make evidence` would report drift on a file
nobody edited. `probe/captured.json` travels with the bytes it describes,
and refreshing the probe is therefore a deliberate act that shows up in a
diff — the same rule `tools/annotate_connector_fixture.py` follows.

What this does not buy: nothing forces a refresh. A probe left alone long
enough certifies a board that may since have rotted, and `probe_captured_at`
in the evidence is what makes that visible rather than a mechanism that
prevents it.

When no probe is present, the honest report is that the rot stage
did not run: the free signals below still audit the recorded evidence, but
the gate reads `unmeasured` — not a healthy verdict.

Two stages, in order, over that evidence:

1. **Free signals**, costing nothing: `company` null on every row,
   undecoded HTML entities (`&amp;`) in a title, a `detail_url` that does
   not point at the portal's own host.
2. **One bounded sentinel probe**, capped at one retry
   (`MAX_PROBE_ATTEMPTS`): does the separately captured current read still
   yield what the connector's own recorded fixture proves it once did? A portal
   that has yielded before and now yields nothing is the silent failure
   this module exists to catch; a portal whose recorded fixture was never
   non-empty has nothing to regress from, and reporting that as breakage
   would be the false alarm that gets a real health check switched off.

The free pass must be able to reach a verdict alone — a check that always
needs the probe's own request to succeed is a check that runs rarely, which
`status/spec-v3-silent-success.md` treats as equivalent to not existing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml

from integral.connector_coverage import installed_packages
from integral.connectors import (
    DEFAULT_CONNECTORS_DIR,
    FIXTURE_DIRNAME,
    META_FILENAME,
    PROBE_DIRNAME,
    Connector,
    ConnectorError,
    connector_packages,
    load_connector,
    parse_list_page,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T72.json"
#: T73's record. Same module, separate file: the two gates ask different
#: questions of the same readings and a reader must be able to fail one
#: without the other going quiet.
DEFAULT_RATE_LIMIT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T73.json"
#: T127. A third question of the same packages: whether the probe the rot
#: check reads is a second read of the board or a restatement of the first.
DEFAULT_DIVERGENCE_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T127.json"

#: T73. `inconclusive` is the third verdict, and it is not a soft `broken`:
#: it says the question was not answered, the same distinction `liveness`
#: draws with `unverified` and the gate layer with `unmeasured`.
Health = Literal["healthy", "broken", "inconclusive"]


class ConnectorHealthError(Exception):
    """A health-check action was asked for in a way this module refuses."""


#: Statuses that mean "we were not allowed to look", never "the parser
#: rotted". 429 is the canonical refusal; 403 is the same refusal spelled by
#: a WAF; 503 is the board being unavailable, which says nothing about our
#: selectors either. None of the three is evidence about the markup, because
#: none of them delivered any.
BLOCKED_STATUSES: frozenset[int] = frozenset({403, 429, 503})

#: What a challenge page says when it is served with a 200. Lowercased
#: substring match, and — see `rate_limited` — consulted **only** when
#: nothing parsed, because every one of these phrases can legitimately occur
#: inside an advert on a page that was served to us in full.
BLOCK_PAGE_MARKERS: tuple[str, ...] = (
    "just a moment",
    "attention required",
    "checking your browser",
    "enable javascript and cookies to continue",
    "ddos protection by cloudflare",
    "access denied",
    "you have been blocked",
    "request blocked",
    "unusual traffic",
    "too many requests",
    "rate limit",
    "captcha",
    "_incapsula_resource",
    # T166, infojobs.net's edge page, 2026-09-10 — its heading and the vendor's
    # own sentence. Until these, that page was caught only because `captcha`
    # sits in its canonical link and an element id: markup, not text, one
    # rename from reading as an empty board.
    "no podemos identificar tu navegador",
    "to regain access",
)

#: What "undecoded" means: an entity reference that survived HTML parsing
#: unescaped — the tell-tale of a title pulled from the wrong element, or
#: from markup a restyle now double-encodes.
_ENTITY_RE = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]*|#\d+|#x[0-9a-fA-F]+);")

#: The sentinel probe is a health check, not a crawler: one read, one retry,
#: never more.
MAX_PROBE_ATTEMPTS = 2


#: Records when the probe beside it was taken. Committed with the capture,
#: because a checkout does not preserve mtimes and a date derived from one
#: would differ per clone — drift on a file nobody edited.
PROBE_CAPTURE_FILE = "captured.json"


@dataclass(frozen=True)
class Reading:
    """One connector's verdict, and the evidence it rests on."""

    connector: str
    site: str
    health: Health
    baseline_items: int
    probe_items: int
    reasons: tuple[str, ...]
    #: Whether a separately captured current read was available. False means
    #: the rot stage did not run for this connector, so `health` rests on the
    #: free signals alone and cannot be read as "not rotted".
    probed: bool = True
    #: When the probe was taken, from `probe/captured.json`. `None` when no
    #: probe was read, and also when one was read but records no date — an
    #: undated capture cannot say how current the verdict is.
    probe_captured_at: str | None = None
    #: T73. Why the capture was a refusal rather than a listing — the status
    #: it carried, or the challenge page it turned out to be. `None` means we
    #: were shown the page. This is not a reason: it is the *absence* of
    #: evidence, and folding it in with the reasons is what let a 429 read as
    #: breakage.
    rate_limited: str | None = None

    @property
    def rot_stage_ran(self) -> bool:
        """Did the comparison this module exists to make actually happen?

        A refused capture is a file that was read, so `probed` is true for it
        — but nothing was compared. Only this answers whether a zero here is
        a finding about parser rot or a lower bound over the free signals.
        """
        return self.probed and self.rate_limited is None


def undecoded_entities(values: Iterable[str]) -> list[str]:
    """Which of these strings still carry a raw `&name;`/`&#N;` reference."""
    return [v for v in values if _ENTITY_RE.search(v)]


def rate_limited(html: str | None, status: int | None, *, parsed_items: int = 0) -> str | None:
    """Why this capture was a refusal rather than a listing — or `None`.

    T73's whole content. A capture that yielded nothing is the input to T72's
    regression branch, and there are two entirely different reasons for it:
    the board restyled and our selectors stopped matching, or the board
    refused us. Only the first is breakage.

    Two signals, and they are deliberately asymmetric:

    * **The recorded status** decides on its own. `probe/captured.json`
      already carries it, written by the `[LAPTOP]` process that made the
      capture, and a 429 is not open to interpretation.
    * **The body markers** are consulted only once `parsed_items` is 0.
      Every phrase in `BLOCK_PAGE_MARKERS` can occur inside a real advert —
      "captcha" and "access denied" both appear in job descriptions — and a
      page that yielded rows was plainly served to us whatever words it
      contains. Reading the markers first would let one advert turn a whole
      healthy board `inconclusive`, which is the same silencing this module
      exists to prevent, arriving from the other side.
    """
    if status is not None and status in BLOCKED_STATUSES:
        return f"the capture records HTTP {status} — the board refused the read"
    if html is None or parsed_items:
        return None
    lowered = html.lower()
    for marker in BLOCK_PAGE_MARKERS:
        if marker in lowered:
            return f"the capture is a challenge page, not a listing ({marker!r})"
    return None


def on_portal_host(url: str, site: str) -> bool:
    """Does `url` point at the portal `site` names, e.g. `trabajos.com`?

    A relative URL (no scheme and no `netloc` — `.oferta`'s own listing
    rows never carry a scheme) is implicitly on the portal's own host;
    that is what "relative" means, and flagging it as off-host would fail
    every connector that links this way, `trabajos_es` included.

    An *opaque* scheme is not a relative URL and is never on the portal's
    host: `mailto:` and `javascript:` also parse to an empty `netloc`, so
    testing emptiness alone silently waves them through. Host comparison
    uses `hostname` rather than `netloc` because `netloc` carries the
    port, and `trabajos.com:443` is the same host as `trabajos.com`.
    """
    try:
        parsed = urlsplit(url)
        # `urlsplit` defers port validation to attribute access, so a non-numeric
        # or out-of-range port parses fine and leaves `hostname` intact — reading
        # as on-host and raising no signal. Touching `.port` here is what makes it
        # follow the malformed path instead.
        _ = parsed.port
    except ValueError:
        # `urlsplit` raises on a malformed authority — `https://[::1` is an
        # "Invalid IPv6 URL". A connector emitting one is exactly the rot this
        # module exists to catch, so it must become a signal, never an
        # exception that aborts `measure()` before any verdict is reached.
        return False
    if not parsed.netloc:
        return not parsed.scheme
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    bare = site.lower()
    return host == bare or host.endswith("." + bare)


def free_signals(
    items: list[dict[str, str]], site: str, declared: frozenset[str] | None = None
) -> list[str]:
    """The signals T72 names, computed over rows already in hand — no
    request spent to compute any of them.

    `declared` is the set of field names the connector's *list page* claims to
    produce. The null-company signal asks whether a claim came out empty, and
    a connector that never claimed a company on its listing has not failed to
    deliver one: justjoin.it's listing document is an index of URLs and
    nothing else, with title, employer and salary all on each advert's own
    page. Before this argument existed, such a connector read `broken` on the
    day it was written and every day after — a permanent red that says nothing
    about rot, which is the failure mode that makes people stop reading a
    signal.

    Passing `None` keeps the old behaviour of asking regardless, so a caller
    that does not know what was declared still gets the blunt version.

    The trade-off, stated rather than discovered later: an author *could*
    silence this by dropping `company` from the list declaration. They would
    then have no company on any row, which the ranking shows as unknown — a
    visible hole, not a quiet one. A connector that keeps the claim and
    returns nulls is still flagged, which is the case this signal was built
    for.
    """
    reasons: list[str] = []
    claims_company = declared is None or "company" in declared
    if claims_company and items and all(not item.get("company") for item in items):
        reasons.append("company is null on every row")
    bad_titles = undecoded_entities(item["title"] for item in items if item.get("title"))
    if bad_titles:
        reasons.append(f"{len(bad_titles)} title(s) carry an undecoded HTML entity")
    urls = [item["detail_url"] for item in items if item.get("detail_url")]
    off_host = [url for url in urls if not on_portal_host(url, site)]
    if off_host:
        reasons.append(f"{len(off_host)} detail_url(s) do not point at {site}")
    return reasons


def assess(
    connector: Connector,
    site: str,
    *,
    baseline_html: str,
    probe_html: str | None,
    probe_status: int | None = None,
) -> Reading:
    """T72's verdict for one connector, given its baseline and today's read.

    `baseline_html` is what this connector's own fixture proves it once
    parsed; `probe_html` is what the sentinel probe read this time. They must
    come from two different reads — passing the same string for both makes
    the regression branch below unreachable and the verdict worthless.

    `probe_html` is `None` when no current read has been captured. The free
    signals then run over the baseline, because an undecoded entity or an
    off-host `detail_url` in the recorded evidence is a real defect that
    costs no request to see; but the regression branch is skipped and the
    reading is marked unprobed, which is what stops `measure` calling the
    result a measurement.

    `probe_status` is what `probe/captured.json` recorded for that read. T73:
    a capture the board refused yields nothing, exactly like a capture whose
    selectors stopped matching, and only the status and the body can tell the
    two apart. When it was a refusal the regression branch is skipped and the
    verdict is `inconclusive` — *unless* a free signal fired, because those
    cost no request and a finding we actually made outranks a question we
    could not ask. That precedence is the same one `_main` already applies
    between a real violation and a missing probe.
    """
    baseline_items = parse_list_page(connector, baseline_html)
    probed = probe_html is not None
    probe_items = parse_list_page(connector, probe_html) if probe_html is not None else []

    declared = frozenset(
        connector.list.fields
        if connector.list.from_json is None
        else connector.list.from_json.fields
    )
    # Gated on `probed`, and classified exactly once. `rate_limited` answers
    # from the recorded status alone when there is no body, so a package whose
    # `captured.json` says 429 with no `list.html` beside it used to come back
    # `inconclusive` with `rate_limited=None` — and both readers key off the
    # second field, so `_main` filed it under "no current read captured" while
    # `measure_rate_limiting` skipped it entirely. No probe file is "the rot
    # stage did not run", which `probed=False` already says; it is not a
    # refusal we watched happen.
    refused = (
        rate_limited(probe_html, probe_status, parsed_items=len(probe_items)) if probed else None
    )
    read_through = probed and refused is None

    reasons = free_signals(probe_items if read_through else baseline_items, site, declared)
    if read_through and baseline_items and not probe_items:
        reasons.append(
            f"{len(baseline_items)} row(s) recorded previously, 0 now — the parser no "
            "longer matches this connector's own markup"
        )

    health: Health = "broken" if reasons else ("inconclusive" if refused else "healthy")
    return Reading(
        connector=connector.site,
        site=site,
        health=health,
        baseline_items=len(baseline_items),
        probe_items=len(probe_items),
        reasons=tuple(reasons),
        probed=probed,
        rate_limited=refused,
    )


def default_fetch(package: Path) -> str:
    """The sentinel probe's source: a separately captured current read at
    `probe/list.html`, written by the permitted `[LAPTOP]` process.

    It must never be `FIXTURE_DIRNAME` — that file is `assess`'s baseline,
    and returning it here compared a string with itself. `OSError` when no
    capture exists is the correct answer, and `probe_fetch` turns it into
    the `None` that makes the gate report `unmeasured`."""
    return (package / PROBE_DIRNAME / "list.html").read_text(encoding="utf-8")


def probe_fetch(package: Path, *, fetch: Callable[[Path], str] = default_fetch) -> str | None:
    """Run `fetch` at most `MAX_PROBE_ATTEMPTS` times; `None` once every
    attempt has raised — a caller falls back to the baseline alone rather
    than treating a read failure as proof of breakage."""
    result: str | None = None
    for _ in range(MAX_PROBE_ATTEMPTS):
        try:
            result = fetch(package)
        except (OSError, UnicodeError):
            # `read_text` raises UnicodeDecodeError — a ValueError, NOT an OSError —
            # on a capture that is not valid UTF-8. Catching OSError alone let it
            # escape past `write_evidence`, so a corrupt probe produced no evidence
            # at all rather than an unmeasured gate.
            continue
        else:
            return result
    return result


def _read_capture(package: Path) -> dict[str, Any]:
    """`probe/captured.json` as a mapping, `{}` whenever it cannot be read.

    Absent, unreadable, not UTF-8, not JSON, or JSON that is not an object —
    all of them mean the same thing to every caller here: this capture does
    not describe itself. None of them is a reason to fail the health check,
    because the record annotates the verdict rather than producing it.
    """
    try:
        raw = (package / PROBE_DIRNAME / PROBE_CAPTURE_FILE).read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def probe_status(package: Path) -> int | None:
    """The HTTP status this package's capture records, or `None`.

    `bool` is excluded deliberately: it is an `int` in Python, and a
    `"status": true` would otherwise compare as 1. A capture that does not
    record a status is not a refusal — it is a capture predating the field,
    and the body markers are what answers for it.
    """
    status = _read_capture(package).get("status")
    return status if isinstance(status, int) and not isinstance(status, bool) else None


def probe_captured_at(package: Path) -> str | None:
    """When this package's probe was taken, per `probe/captured.json`.

    `None` whenever that cannot be answered — the file is absent, unreadable,
    not JSON, carries no `captured_at`, or carries one that is not a `YYYY-MM-DD`
    date. Every one of those is "this capture
    does not say how current it is", which is what the caller records; none of
    them is a reason to fail the health check, because the date annotates the
    verdict rather than producing it."""
    recorded = _read_capture(package).get("captured_at")
    if not isinstance(recorded, str):
        return None
    try:
        # `strptime` and not `date.fromisoformat`: the latter also accepts
        # `20260828` and other ISO spellings, and this value is read by a human
        # deciding whether a probe is stale. One spelling or none.
        parsed = datetime.strptime(recorded, "%Y-%m-%d")
    except ValueError:
        # Covers the empty string, `unknown`, and `2026-13-45` alike. Every one
        # of them is a capture that does not say when it was taken, and emitting
        # it beside `gate_status: measured` would dress it up as one that does.
        return None
    # Round-trip, because `strptime` is not the exact check the format string
    # looks like: `%m` and `%d` accept an unpadded `2026-8-28` just as happily
    # as `2026-08-28`. Re-rendering and comparing is what makes "one spelling"
    # true — asserted by review on #256 after the first attempt claimed it and
    # did not deliver it.
    return recorded if parsed.strftime("%Y-%m-%d") == recorded else None


def assess_package(
    package: Path,
    connector: Connector,
    site: str,
    *,
    fetch: Callable[[Path], str] = default_fetch,
) -> Reading:
    """`assess`, wired to one installed package's own recorded fixture."""
    baseline_path = package / FIXTURE_DIRNAME / "list.html"
    try:
        baseline_html = baseline_path.read_text(encoding="utf-8")
    except OSError as exc:
        return Reading(
            connector.site, site, "broken", 0, 0, (f"no recorded fixture: {exc}",), probed=False
        )

    # `None` when no current read was captured. It is NOT replaced by the
    # baseline: that substitution is what made the regression branch dead
    # code in the production path while the evidence still said "measured".
    probe_html = probe_fetch(package, fetch=fetch)
    reading = assess(
        connector,
        site,
        baseline_html=baseline_html,
        probe_html=probe_html,
        probe_status=probe_status(package),
    )
    # Only a reading that actually read a probe can carry its date; stamping an
    # unprobed one would date a rot stage that never ran.
    if not reading.probed:
        return reading
    return replace(reading, probe_captured_at=probe_captured_at(package))


#: The one key `set_enabled` writes. Its absence means enabled: fifteen
#: packages predate this flag and none of them is retired.
_ENABLED_RE = re.compile(r"^enabled:.*$", re.MULTILINE)


def is_enabled(package: Path) -> bool:
    """Is this connector still in service? Absent or malformed means yes.

    Defaulting open is the deliberate direction. A typo in one package's
    `meta.yaml` should not quietly retire a working board — the failure this
    task exists to prevent, arriving through the flag built to prevent it.
    """
    try:
        meta = yaml.safe_load((package / META_FILENAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return True
    if not isinstance(meta, dict):
        return True
    return meta.get("enabled") is not False


def offer_to_disable(reading: Reading) -> str | None:
    """What to put to a human about this connector, or `None` for nothing.

    Offered, never automatic — and never for `inconclusive`. Retiring a board
    on the strength of our own rate limiting is precisely the outcome T73
    exists to make impossible, so the third verdict is not a quieter `broken`
    that still reaches for the switch: it reaches for nothing.
    """
    if reading.health != "broken":
        return None
    return (
        f"{reading.connector} reads broken: {'; '.join(reading.reasons)}. "
        f"Disable it? `set_enabled(<package>, False, confirmed=True)` writes "
        f"`enabled: false` into its {META_FILENAME} and touches nothing else."
    )


def set_enabled(package: Path, enabled: bool, *, confirmed: bool) -> Path:
    """Flip one connector's `enabled` flag. Refuses without `confirmed`.

    The keyword is the whole mechanism: nothing in this module calls it, so
    the only way a board is retired is a caller that said so in as many
    words. A health check that switches boards off by itself is a health
    check that gets switched off after its first false alarm, and then the
    silent rot it existed to catch comes back unwatched.

    One key, edited in the text. `meta.yaml` carries the reasoning a
    maintainer wrote about a board — trabajos_es's runs to thirty lines of
    robots.txt findings — and re-serialising it through `yaml.safe_dump` to
    change one boolean would delete all of it.
    """
    if not confirmed:
        raise ConnectorHealthError(
            f"refusing to set enabled={enabled} on {package.name} without confirmation — "
            "disabling a connector is offered to a human, never taken automatically"
        )
    meta = package / META_FILENAME
    text = meta.read_text(encoding="utf-8")
    line = f"enabled: {'true' if enabled else 'false'}"
    updated, replaced = _ENABLED_RE.subn(line, text, count=1)
    if not replaced:
        note = "# Set by hand or by an accepted health-check offer."
        updated = text.rstrip("\n") + f"\n\n{note}\n{line}\n"
    meta.write_text(updated, encoding="utf-8")
    return meta


def _live_readings(
    directory: Path, *, fetch: Callable[[Path], str] = default_fetch
) -> tuple[list[Reading], list[str]]:
    """Every enabled, usable package read once, plus the names of the retired.

    Only `usable` packages are evaluated — `installed_packages` already marks
    a reserved-example-domain package (`examplejobs_es`) unusable, and a
    worked example has no portal to have silently rotted.

    A retired board is not health-checked, but it is *named* rather than
    dropped: a library that shrank to nothing must read `unmeasured`, never
    as a clean run over an empty set.
    """
    usable = [p for p in installed_packages(directory) if p.usable]
    disabled = [p.name for p in usable if not is_enabled(directory / p.name)]
    retired = set(disabled)
    readings: list[Reading] = []
    for package in usable:
        if package.name in retired:
            continue
        path = directory / package.name
        try:
            connector = load_connector(path)
        except ConnectorError as exc:
            readings.append(
                Reading(
                    package.name,
                    package.site or "",
                    "broken",
                    0,
                    0,
                    (f"connector could not be loaded: {exc}",),
                    probed=False,
                )
            )
            continue
        readings.append(assess_package(path, connector, package.site or package.name, fetch=fetch))
    return readings, disabled


def measure(
    directory: Path = DEFAULT_CONNECTORS_DIR,
    *,
    fetch: Callable[[Path], str] = default_fetch,
) -> dict[str, Any]:
    """T72's gate reading: `silent_connector_failures`."""
    readings, disabled = _live_readings(directory, fetch=fetch)
    evaluated = len(readings)
    # `rot_stage_ran`, not `probed`: T73 added a third way for the comparison
    # not to have happened. A refused capture is a file that was read and
    # nothing that was compared, and counting it as probed would stamp
    # `measured` on a run that looked at a challenge page.
    probed = sum(1 for r in readings if r.rot_stage_ran)
    violations = [r for r in readings if r.health == "broken"]
    # Two ways to be unmeasured, and both are real. Nothing evaluated is the
    # empty-input-set failure the task payload names. Something evaluated but
    # not probed is the subtler one: the rot stage never ran, so a violation
    # count of zero is a lower bound over the free signals, not a finding
    # about parser rot. Only a run where every evaluated connector had a
    # separately captured current read can call itself a measurement.
    status = "measured" if evaluated and probed == evaluated else "unmeasured"
    return {
        "silent_connector_failures": len(violations),
        # Both names on purpose: the spec's success criterion names the
        # first, the gate block's `status-key` mechanism was added against
        # the second. Same count, so a reader trusting either finds it.
        "connector_runs_evaluated": evaluated,
        "silent_connector_failures_evaluated": evaluated,
        "connector_runs_probed": probed,
        "disabled": disabled,
        "gate_status": status,
        "readings": [
            {
                "connector": r.connector,
                "site": r.site,
                "health": r.health,
                "baseline_items": r.baseline_items,
                "probe_items": r.probe_items,
                "reasons": list(r.reasons),
                "probed": r.probed,
                "probe_captured_at": r.probe_captured_at,
                "rate_limited": r.rate_limited,
            }
            for r in readings
        ],
    }


#: Known refusals, each carrying its own ground truth. Every entry here *is*
#: a refusal — that is not the classifier's opinion, it is why the row exists
#: — so a run that reports one of them `broken` has failed T73's gate outright.
#:
#: They are constructed rather than drawn from the library because the
#: library is fifteen 200s: a denominator taken only from live captures would
#: be 0, `gate_status` would read `unmeasured` for as long as every board
#: kept answering, and a gate that never runs is exactly the silent success
#: this increment exists to catch. A live refusal, when one happens, is
#: counted beside them.
_INFOJOBS_EDGE_HEAD = (
    "<html><head><title>InfoJobs</title>"
    '<link rel="canonical" href="https://www.infojobs.net/distil/distil/captcha.xhtml" />'
    "</head>"
)
_INFOJOBS_EDGE_BODY = (
    '<body class="es"><div class="heading-addons inner-expanded">'
    '<h1 class="contrast xlarge">No podemos identificar tu navegador</h1>'
    "<p>¿Cómo lo solucionamos? ¡Elemental, querido Watson!</p>"
    "<p>Comprueba que JavaScript esté habilitado en tu navegador y que no tengas ningún "
    "plugin que pueda impedir su carga o redirija tu tráfico a través de un proxy.</p>"
    "</div>"
    '<p style="display: none;">To regain access, please make sure that cookies and '
    "JavaScript are enabled before reloading the page.</p></body></html>"
)

RATE_LIMIT_SAMPLES: tuple[tuple[str, int | None, str], ...] = (
    ("bare 429", 429, "<html><body>Too Many Requests</body></html>"),
    ("429 with a retry hint", 429, "<html><body>Slow down. Retry after 60s.</body></html>"),
    ("403 from a WAF", 403, "<html><body>Forbidden</body></html>"),
    ("503 while the board is down", 503, "<html><body>Service Unavailable</body></html>"),
    (
        "cloudflare interstitial, served 200",
        200,
        "<html><head><title>Just a moment...</title></head>"
        "<body>Checking your browser before accessing.</body></html>",
    ),
    (
        "cloudflare block, served 200",
        200,
        "<html><head><title>Attention Required! | Cloudflare</title></head>"
        "<body>You have been blocked.</body></html>",
    ),
    (
        "captcha challenge, served 200",
        200,
        "<html><body><div id='captcha'>Please complete the captcha</div></body></html>",
    ),
    (
        "incapsula challenge, served 200",
        200,
        "<html><body><iframe src='/_Incapsula_Resource?SWCGHOEL'></iframe></body></html>",
    ),
    # T166. The page infojobs.net's CDN edge serves this tool, excerpted from a
    # live 29,762-byte response on 2026-09-10 (canonical link, heading, the
    # hidden vendor sentence — byte-identical, the rest cut). A 200 with no
    # listing in it, and never "no jobs": a real browser is served the board.
    (
        "infojobs edge check, served 200",
        200,
        _INFOJOBS_EDGE_HEAD + _INFOJOBS_EDGE_BODY,
    ),
    # The same page with its one `captcha`-bearing line gone, which is all a
    # restyle would take. Caught by its text or not at all.
    ("infojobs edge check, markup renamed, served 200", 200, _INFOJOBS_EDGE_BODY),
    (
        "rate-limit notice with no status recorded",
        None,
        "<html><body>You have hit our rate limit. Try later.</body></html>",
    ),
    (
        "unusual-traffic interstitial with no status recorded",
        None,
        "<html><body>Our systems have detected unusual traffic.</body></html>",
    ),
)


def _ground_package(directory: Path) -> tuple[str, Connector, str, str] | None:
    """A connector to put the constructed refusals through, and its baseline.

    Three requirements, and the third was found by review rather than by
    design. The baseline must **parse**, and must yield rows, so a sample has
    something to regress *from* — a baseline that never yielded is excused by
    T72 before T73's branch is ever reached, and every sample would pass for
    the wrong reason.

    And it must produce **no free signals of its own**. On the refusal path
    `assess` runs the free signals over the baseline, so a ground fixture
    carrying one undecoded entity or one off-host `detail_url` makes `reasons`
    non-empty for all ten samples at once: `health` reads `broken`,
    `rate_limited_runs_reported_as_broken` reads 10, and T73 fails for a
    T72-class defect in an unrelated connector while naming rate limiting as
    the cause. A gate whose red says the wrong thing is worse than one that
    stays amber, so a library with no clean ground reports `unmeasured`.

    The name comes back with it and is written into the evidence, so a reader
    can always tell which fixture the samples were judged against.
    """
    for package in installed_packages(directory):
        if not package.usable or not is_enabled(directory / package.name):
            continue
        path = directory / package.name
        try:
            connector = load_connector(path)
            baseline = (path / FIXTURE_DIRNAME / "list.html").read_text(encoding="utf-8")
        except (ConnectorError, OSError, UnicodeError):
            continue
        site = package.site or package.name
        items = parse_list_page(connector, baseline)
        if not items:
            continue
        declared = frozenset(
            connector.list.fields
            if connector.list.from_json is None
            else connector.list.from_json.fields
        )
        if free_signals(items, site, declared):
            continue
        return package.name, connector, site, baseline
    return None


def measure_rate_limiting(
    directory: Path = DEFAULT_CONNECTORS_DIR,
    *,
    samples: tuple[tuple[str, int | None, str], ...] = RATE_LIMIT_SAMPLES,
    fetch: Callable[[Path], str] = default_fetch,
) -> dict[str, Any]:
    """T73's gate reading: `rate_limited_runs_reported_as_broken`.

    The denominator is what makes this a measurement. It counts refusals
    *classified*, and every constructed sample is a refusal by construction —
    so deleting the block check does not quietly zero this gate, it fires it:
    the samples fall through to the regression branch, report `broken`, and
    the numerator rises. An empty sample set with no live refusal leaves
    nothing classified, and `gate_status` says `unmeasured` rather than
    dressing an unrun check up as a pass.
    """
    readings: list[tuple[str, Reading]] = []
    ground = _ground_package(directory)
    if ground is not None:
        _, connector, site, baseline = ground
        readings.extend(
            (
                name,
                assess(
                    connector,
                    site,
                    baseline_html=baseline,
                    probe_html=body,
                    probe_status=status,
                ),
            )
            for name, status, body in samples
        )
    # Live refusals count too — they are the case the samples stand in for,
    # and on the day a board starts answering 429 this is where it shows up.
    readings.extend(
        (f"live: {r.connector}", r)
        for r in _live_readings(directory, fetch=fetch)[0]
        if r.rate_limited is not None
    )

    violations = [name for name, r in readings if r.health == "broken"]
    evaluated = len(readings)
    return {
        "rate_limited_runs_reported_as_broken": len(violations),
        # Both names on purpose, as T72 does: the payload names the first,
        # the `status-key` mechanism was written against the second.
        "rate_limited_runs_reported_as_broken_evaluated": evaluated,
        "runs_evaluated": evaluated,
        "gate_status": "measured" if evaluated else "unmeasured",
        # Which fixture the constructed refusals were judged against. A defect
        # in it would surface as ten broken samples at once, so a reader who
        # sees that number needs to know where to look first.
        "ground_package": ground[0] if ground is not None else None,
        "reported_as_broken": violations,
        "readings": [
            {
                "case": name,
                "health": r.health,
                "rate_limited": r.rate_limited,
                "baseline_items": r.baseline_items,
                "probe_items": r.probe_items,
                "reasons": list(r.reasons),
            }
            for name, r in readings
        ],
    }


def write_rate_limit_evidence(
    evidence: Path = DEFAULT_RATE_LIMIT_EVIDENCE_PATH,
    directory: Path = DEFAULT_CONNECTORS_DIR,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T73.json`."""
    measured = measure_rate_limiting(directory)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH, directory: Path = DEFAULT_CONNECTORS_DIR
) -> dict[str, Any]:
    """Measure and record `status/evidence/T72.json`."""
    measured = measure(directory)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.connector_health [path]`.

    Without arguments it writes the evidence file, so `make evidence` —
    whose module list is derived from `^def _main` — regenerates T72's
    number with no flag to remember.
    """
    parser = argparse.ArgumentParser(
        description="T72's gate: a rotted connector parser is reported broken, never a quiet zero"
    )
    parser.add_argument("path", nargs="?", default=str(DEFAULT_EVIDENCE_PATH))
    args = parser.parse_args(argv[1:])

    measured = write_evidence(Path(args.path))
    # Two gates, one module, two files — the same shape `cv_store` uses for
    # S4 and T97. They ask different questions of the same readings, and a
    # reader must be able to fail one without the other going quiet.
    # Beside T72's file, wherever that was asked for: a caller redirecting
    # one record to a scratch directory is not asking to have the other
    # written into the repository.
    rate_limits = write_rate_limit_evidence(Path(args.path).parent / "T73.json")
    divergence = write_divergence_evidence(Path(args.path).parent / "T127.json")
    print(json.dumps(measured, ensure_ascii=False))
    for reading in measured["readings"]:
        for reason in reading["reasons"]:
            print(f"{reading['connector']}: {reason}", file=sys.stderr)
        if reading.get("rate_limited"):
            print(
                f"{reading['connector']}: inconclusive — {reading['rate_limited']}. "
                "Not evidence of breakage, and not grounds to disable anything.",
                file=sys.stderr,
            )
    # T73 fails loudly and on its own: a refusal reported as breakage is how
    # a working board gets retired, and it must not be readable as T72 noise.
    if rate_limits["rate_limited_runs_reported_as_broken"]:
        for case in rate_limits["reported_as_broken"]:
            print(f"rate-limited run reported as broken: {case}", file=sys.stderr)
        return 1

    # T127, before T72's own reading. A tautological probe makes T72's answer
    # meaningless for that package — it compared a page with itself — so
    # reporting `silent_connector_failures: 0` first would be answering with a
    # number this finding says not to trust.
    if divergence["connectors_whose_probe_repeats_its_fixture"]:
        for package in divergence["tautological_probes"]:
            print(
                f"{package}: the probe names no offer the fixture does not — "
                "the rot check compares the same markup twice and cannot fail",
                file=sys.stderr,
            )
        return 1
    if divergence["gate_status"] == "unmeasured":
        print(
            f"probe divergence unmeasured: {divergence['probes_compared']} probe(s) "
            f"compared, the floor is {divergence['probes_compared_floor']}",
            file=sys.stderr,
        )
        return 3

    # A violation the free signals actually FOUND is a measured failure, and it
    # outranks any missing probe. Testing `unmeasured` first meant one unprobed
    # connector turned every real finding on every other connector into exit 3 —
    # which `make evidence` records as "unmeasured (recorded)" and walks past. The
    # module built to catch a connector failing silently would have failed silently.
    # `unmeasured` is only honest when there is nothing to report.
    if measured["silent_connector_failures"]:
        return 1
    if measured["gate_status"] == "unmeasured":
        evaluated = measured["connector_runs_evaluated"]
        probed = measured["connector_runs_probed"]
        if not evaluated:
            why = "0 connector(s) evaluated"
        else:
            # Two different ways the rot stage does not run, and telling a
            # reader which happened is the difference between "capture one"
            # and "we are being refused". `probed` alone conflated them.
            uncaptured = [
                r["connector"]
                for r in measured["readings"]
                if not r["probed"] and not r.get("rate_limited")
            ]
            refused = [r["connector"] for r in measured["readings"] if r.get("rate_limited")]
            parts = []
            if uncaptured:
                parts.append(
                    f"no current read captured at {PROBE_DIRNAME}/list.html for: "
                    f"{', '.join(uncaptured)}"
                )
            if refused:
                parts.append(f"the board refused the read for: {', '.join(refused)}")
            why = (
                f"{evaluated} connector(s) evaluated but only {probed} compared — "
                f"{'; '.join(parts)}. The rot stage did not run"
            )
        print(
            f"silent_connector_failures: UNMEASURED — {why}. Not a pass and not a fail.",
            file=sys.stderr,
        )
        return 3
    return 1 if measured["silent_connector_failures"] else 0


#: A package whose probe repeats its fixture is compared against nothing, so a
#: library that lost every real probe must fail rather than pass over an empty
#: set. Seventeen packages carry a probe today; the floor sits below that with
#: room for one to be withdrawn without the gate going quiet.
MINIMUM_PROBES_COMPARED = 12


def list_references(connector: Connector, html: str) -> set[str]:
    """The offers a list page names, keyed the way a reader would tell them apart.

    `detail_url` first because it is the board's own identifier; `title` only
    where a connector publishes no detail link. Anything else — company, date,
    the teaser — repeats across offers and would understate divergence.
    """
    references: set[str] = set()
    for item in parse_list_page(connector, html):
        reference = item.get("detail_url") or item.get("title")
        if reference:
            references.add(reference)
    return references


def probe_divergence(package: Path, connector: Connector) -> dict[str, Any]:
    """Whether this package's probe is a second read or a restatement of the first.

    `assess_package` compares the probe against the fixture and calls a parser
    healthy when both yield offers. That comparison is only worth something if
    the two pages carry **different offers**: a probe holding the same adverts
    exercises the same markup, so a parser that broke on anything new would
    still be called healthy.

    This module's own header records fixing that once — an earlier revision
    pointed the probe at `fixture/list.html`, so the production path compared a
    string with itself. The fix was made in the *code*, and the **data** was
    never checked. Measured 2026-09-05, two packages were still tautological:
    `ticjob_es`, whose probe is byte-identical to its fixture, and
    `getmanfred_es`, whose probe is byte-*different* and names the same three
    offers — which no byte comparison would ever have caught.

    `repeats_the_fixture` is true when **every** offer the probe names also
    appears in the fixture. Not a threshold on the overlap: a probe that adds
    one new advert does compare something, and one is the honest boundary.
    """
    fixture, probe = package / "fixture" / "list.html", package / "probe" / "list.html"
    reading: dict[str, Any] = {"package": package.name, "compared": False, "reason": None}
    if not fixture.exists() or not probe.exists():
        reading["reason"] = "no probe" if fixture.exists() else "no fixture"
        return reading
    fixture_refs = list_references(connector, fixture.read_text(encoding="utf-8"))
    probe_refs = list_references(connector, probe.read_text(encoding="utf-8"))
    # A side that parses to nothing is not a divergence of zero, it is a
    # question that was not asked — the `unmeasured` distinction, per package.
    # Scoring it as 100% overlap would report the parser's own failure as a
    # tautology and send a reader to re-capture a probe that was fine.
    if not fixture_refs or not probe_refs:
        reading["reason"] = (
            f"parsed no offers (fixture={len(fixture_refs)}, probe={len(probe_refs)})"
        )
        return reading
    shared = fixture_refs & probe_refs
    return {
        "package": package.name,
        "compared": True,
        "reason": None,
        "fixture_offers": len(fixture_refs),
        "probe_offers": len(probe_refs),
        "shared_offers": len(shared),
        "overlap": round(len(shared) / len(probe_refs), 4),
        "repeats_the_fixture": shared == probe_refs,
        "byte_identical": fixture.read_bytes() == probe.read_bytes(),
    }


def measure_probe_divergence(directory: Path = DEFAULT_CONNECTORS_DIR) -> dict[str, Any]:
    """T127's gate reading: `connectors_whose_probe_repeats_its_fixture`."""
    readings = []
    for package in connector_packages(directory):
        try:
            connector = load_connector(package / "connector.yaml")
        except Exception as error:
            readings.append(
                {"package": package.name, "compared": False, "reason": f"unloadable: {error}"}
            )
            continue
        readings.append(probe_divergence(package, connector))
    compared = [r for r in readings if r["compared"]]
    tautological = [r["package"] for r in compared if r["repeats_the_fixture"]]
    return {
        "connectors_whose_probe_repeats_its_fixture": len(tautological),
        "probes_compared": len(compared),
        # The floor is what stops a clean zero resting on an empty scan: a
        # library that lost every probe would otherwise report 0 tautologies
        # and pass, which is the exact reading it must not be able to give.
        "probes_compared_floor": MINIMUM_PROBES_COMPARED,
        "gate_status": "measured" if len(compared) >= MINIMUM_PROBES_COMPARED else "unmeasured",
        "tautological_probes": sorted(tautological),
        "readings": sorted(readings, key=lambda r: str(r["package"])),
    }


def write_divergence_evidence(
    evidence: Path = DEFAULT_DIVERGENCE_EVIDENCE_PATH,
    directory: Path = DEFAULT_CONNECTORS_DIR,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T127.json`."""
    measured = measure_probe_divergence(directory)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
