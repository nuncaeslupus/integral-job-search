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

from integral.connector_coverage import installed_packages
from integral.connectors import (
    DEFAULT_CONNECTORS_DIR,
    FIXTURE_DIRNAME,
    PROBE_DIRNAME,
    Connector,
    ConnectorError,
    load_connector,
    parse_list_page,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T72.json"

Health = Literal["healthy", "broken"]

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


def undecoded_entities(values: Iterable[str]) -> list[str]:
    """Which of these strings still carry a raw `&name;`/`&#N;` reference."""
    return [v for v in values if _ENTITY_RE.search(v)]


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


def free_signals(items: list[dict[str, str]], site: str) -> list[str]:
    """The signals T72 names, computed over rows already in hand — no
    request spent to compute any of them."""
    reasons: list[str] = []
    if items and all(not item.get("company") for item in items):
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
    connector: Connector, site: str, *, baseline_html: str, probe_html: str | None
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
    """
    baseline_items = parse_list_page(connector, baseline_html)
    probed = probe_html is not None
    probe_items = parse_list_page(connector, probe_html) if probe_html is not None else []

    reasons = free_signals(probe_items if probed else baseline_items, site)
    if probed and baseline_items and not probe_items:
        reasons.append(
            f"{len(baseline_items)} row(s) recorded previously, 0 now — the parser no "
            "longer matches this connector's own markup"
        )

    health: Health = "broken" if reasons else "healthy"
    return Reading(
        connector=connector.site,
        site=site,
        health=health,
        baseline_items=len(baseline_items),
        probe_items=len(probe_items),
        reasons=tuple(reasons),
        probed=probed,
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


def probe_captured_at(package: Path) -> str | None:
    """When this package's probe was taken, per `probe/captured.json`.

    `None` whenever that cannot be answered — the file is absent, unreadable,
    not JSON, carries no `captured_at`, or carries one that is not a `YYYY-MM-DD`
    date. Every one of those is "this capture
    does not say how current it is", which is what the caller records; none of
    them is a reason to fail the health check, because the date annotates the
    verdict rather than producing it."""
    try:
        raw = (package / PROBE_DIRNAME / PROBE_CAPTURE_FILE).read_text(encoding="utf-8")
        recorded = json.loads(raw).get("captured_at")
    except (OSError, UnicodeError, ValueError, AttributeError):
        return None
    if not isinstance(recorded, str):
        return None
    try:
        # `strptime` and not `date.fromisoformat`: the latter also accepts
        # `20260828` and other ISO spellings, and this value is read by a human
        # deciding whether a probe is stale. One spelling or none.
        datetime.strptime(recorded, "%Y-%m-%d")
    except ValueError:
        # Covers the empty string, `unknown`, and `2026-13-45` alike. Every one
        # of them is a capture that does not say when it was taken, and emitting
        # it beside `gate_status: measured` would dress it up as one that does.
        return None
    return recorded


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
    reading = assess(connector, site, baseline_html=baseline_html, probe_html=probe_html)
    # Only a reading that actually read a probe can carry its date; stamping an
    # unprobed one would date a rot stage that never ran.
    if not reading.probed:
        return reading
    return replace(reading, probe_captured_at=probe_captured_at(package))


def measure(
    directory: Path = DEFAULT_CONNECTORS_DIR,
    *,
    fetch: Callable[[Path], str] = default_fetch,
) -> dict[str, Any]:
    """T72's gate reading: `silent_connector_failures`.

    Only `usable` packages are evaluated — `installed_packages` already
    marks a reserved-example-domain package (`examplejobs_es`) unusable, and
    a worked example has no portal to have silently rotted.
    """
    packages = [p for p in installed_packages(directory) if p.usable]
    readings: list[Reading] = []
    for package in packages:
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

    evaluated = len(readings)
    probed = sum(1 for r in readings if r.probed)
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
            }
            for r in readings
        ],
    }


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
    print(json.dumps(measured, ensure_ascii=False))
    for reading in measured["readings"]:
        for reason in reading["reasons"]:
            print(f"{reading['connector']}: {reason}", file=sys.stderr)

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
            unprobed = [r["connector"] for r in measured["readings"] if not r["probed"]]
            why = (
                f"{evaluated} connector(s) evaluated but only {probed} probed — no current "
                f"read captured at {PROBE_DIRNAME}/list.html for: {', '.join(unprobed)}. "
                "The rot stage did not run"
            )
        print(
            f"silent_connector_failures: UNMEASURED — {why}. Not a pass and not a fail.",
            file=sys.stderr,
        )
        return 3
    return 1 if measured["silent_connector_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
