"""Reference salary bands from the Manfred Tech Career Report 2026, fetched at runtime.

The report is CC BY-NC and this repository is MIT, so none of its values live
here: the payload is fetched when asked for (after a robots check) and cached
only under the candidate's own profile tree. Anything unknown, refused or
failed returns None; a band is never guessed.

Payload shape this module reads: `{"bands": [{"role", "seniority",
"company_type", "min", "max"}, ...]}`, gross yearly euros. Measured on
2026-11-19, the published tcr-2026.json carries only key figures, prose facts
and FAQs: the role/seniority/company-type charts are not in it, so against the
live file the lookup finds nothing until the report publishes such a table.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from integral.identity import ProfileStore
from integral.robots import USER_AGENT, Robots

URL = "https://www.getmanfred.com/tech-career-report/tcr-2026.json"
SOURCE = "Manfred Tech Career Report 2026"
CACHE_PARTS = ("cache", "manfred-tcr-2026.json")


@dataclass(frozen=True)
class Band:
    low: int
    high: int
    source: str = SOURCE


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data: bytes = resp.read()
    return data


def _payload(
    store: ProfileStore, fetch: Callable[[str], bytes], robots: Robots
) -> dict[str, Any] | None:
    cache = store.path(*CACHE_PARTS)
    if cache.exists():
        raw = cache.read_bytes()
    else:
        if not robots.allows(URL):
            return None
        try:
            raw = fetch(URL)
            json.loads(raw)
        except Exception:  # any failed fetch or bad body shows nothing
            return None
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(raw)
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def reference_band(
    store: ProfileStore,
    role: str,
    seniority: str,
    company_type: str,
    *,
    fetch: Callable[[str], bytes] = _fetch,
    robots: Robots | None = None,
) -> Band | None:
    """The reported band for this cell, or None when it cannot be shown."""
    data = _payload(store, fetch, robots or Robots())
    if data is None:
        return None
    want = (role.casefold(), seniority.casefold(), company_type.casefold())
    for row in data.get("bands", []):
        try:
            got = tuple(str(row[k]).casefold() for k in ("role", "seniority", "company_type"))
            if got == want:
                return Band(int(row["min"]), int(row["max"]))
        except (KeyError, TypeError, ValueError):
            continue
    return None
