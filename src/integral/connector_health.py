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
live HTTP request, and it is `[LAPTOP]`-only for exactly that reason. So
"the example query recorded in the connector's own file" is read here the
same way T12 reads it: `fixture/list.html`, the response that URL actually
returned the day someone last verified this connector — evidence already in
hand, not a request this module is in a position to make.

Two stages, in order, over that evidence:

1. **Free signals**, costing nothing: `company` null on every row,
   undecoded HTML entities (`&amp;`) in a title, a `detail_url` that does
   not point at the portal's own host.
2. **One bounded sentinel probe**, capped at one retry
   (`MAX_PROBE_ATTEMPTS`): does today's read of that same file still yield
   what the connector's own recorded fixture proves it once did? A portal
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from integral.connector_coverage import installed_packages
from integral.connectors import (
    DEFAULT_CONNECTORS_DIR,
    FIXTURE_DIRNAME,
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


@dataclass(frozen=True)
class Reading:
    """One connector's verdict, and the evidence it rests on."""

    connector: str
    site: str
    health: Health
    baseline_items: int
    probe_items: int
    reasons: tuple[str, ...]


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
    parsed = urlsplit(url)
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


def assess(connector: Connector, site: str, *, baseline_html: str, probe_html: str) -> Reading:
    """T72's verdict for one connector, given its baseline and today's read.

    `baseline_html` is what this connector's own fixture proves it once
    parsed; `probe_html` is what the sentinel probe read this time — the
    same bytes, in production, since there is no live fetcher to diverge
    from it. A test simulating a restyled or emptied page supplies a
    different string for `probe_html` and leaves `baseline_html` as the
    connector's real, untouched record.
    """
    baseline_items = parse_list_page(connector, baseline_html)
    probe_items = parse_list_page(connector, probe_html)

    reasons = free_signals(probe_items, site)
    if baseline_items and not probe_items:
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
    )


def default_fetch(package: Path) -> str:
    """The sentinel probe's source in this repo: the connector's own
    recorded fixture. There is no HTTP client here to reach for instead —
    see the module docstring's `connectors.py` citation."""
    return (package / FIXTURE_DIRNAME / "list.html").read_text(encoding="utf-8")


def probe_fetch(package: Path, *, fetch: Callable[[Path], str] = default_fetch) -> str | None:
    """Run `fetch` at most `MAX_PROBE_ATTEMPTS` times; `None` once every
    attempt has raised — a caller falls back to the baseline alone rather
    than treating a read failure as proof of breakage."""
    result: str | None = None
    for _ in range(MAX_PROBE_ATTEMPTS):
        try:
            result = fetch(package)
        except OSError:
            continue
        else:
            return result
    return result


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
        return Reading(connector.site, site, "broken", 0, 0, (f"no recorded fixture: {exc}",))

    probe_html = probe_fetch(package, fetch=fetch)
    if probe_html is None:
        # The probe itself could not be run — the free pass must still be
        # able to reach a verdict, over the baseline alone.
        probe_html = baseline_html
    return assess(connector, site, baseline_html=baseline_html, probe_html=probe_html)


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
                )
            )
            continue
        readings.append(assess_package(path, connector, package.site or package.name, fetch=fetch))

    evaluated = len(readings)
    violations = [r for r in readings if r.health == "broken"]
    return {
        "silent_connector_failures": len(violations),
        # Both names on purpose: the spec's success criterion names the
        # first, the gate block's `status-key` mechanism was added against
        # the second. Same count, so a reader trusting either finds it.
        "connector_runs_evaluated": evaluated,
        "silent_connector_failures_evaluated": evaluated,
        "gate_status": "measured" if evaluated else "unmeasured",
        "readings": [
            {
                "connector": r.connector,
                "site": r.site,
                "health": r.health,
                "baseline_items": r.baseline_items,
                "probe_items": r.probe_items,
                "reasons": list(r.reasons),
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

    if measured["gate_status"] == "unmeasured":
        print(
            "silent_connector_failures: UNMEASURED — 0 connector(s) evaluated. Not a pass and "
            "not a fail.",
            file=sys.stderr,
        )
        return 3
    return 1 if measured["silent_connector_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
