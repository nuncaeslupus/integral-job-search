"""T153: a `provenance` nobody checks is a label wearing evidence's clothes.

T113 gave `probe/captured.json` a `provenance` field so that "transcribed from
a committed curl" and "recorded live" would be distinguishable **in the
artefact** rather than argued in a pull-request comment. It shipped advisory:
nineteen of twenty captures declared nothing, nothing failed on any value, and
**a fabricated capture claiming `live` passed**.

That is the field's own subject turned on itself. A marker nobody checks
records an intention, not a fact, and the thing T113 exists to refuse — an
artefact certifying a request nobody made — is exactly what an unchecked `live`
waves through. This module is the check.

**What "enforced" means here, and what it deliberately does not.** No test can
tell a request that was issued from one forged with enough patience; the claim
"these bytes came off the wire" is not decidable from the bytes. What *is*
decidable is whether the artefact **substantiates its own claim** — whether the
package carries the things the claim entails, and whether they agree with each
other. So a capture is *unenforced* when its declaration is one this module
cannot hold it to, and the count of those is the gate.

**The vocabulary, and why `unrecorded` must be written down.** T113 read an
absent field as `unrecorded` and never wrote it back, so that "nobody has
established this" would not be retro-stamped onto twenty files. The cost is
that an absence and a statement are the same byte string — nothing — and the
absence read as a pass. So the three values are all **declarable** and one of
them must be present:

* `live` — recorded off the wire.
* `transcribed` — written down from a request committed elsewhere in this repo.
* `unrecorded` — nobody has established how this record came to exist.

`unrecorded` claims nothing, so there is nothing to substantiate and it is
trivially enforced. That is the point, not a loophole: it is the truthful value
for the nineteen, the gate is satisfiable with them saying so, and **stamping
`live` or `transcribed` on them to make a number fall is the invention this
module exists to refuse.** What changed is only that the absence now has to be
stated rather than inferred — `read_provenance`'s silent default was the last
place a missing field could read as a pass.

**What `live` must carry.** A live capture leaves the response behind; a
hand-written one has nothing to leave. So the claim is held to the bytes in
`probe/`:

* `captured_at` — a well-formed `YYYY-MM-DD`, and not in the future. A record
  of a fetch that has not happened yet is not a record of a fetch.
* `status` — an integer HTTP status in 100…599.
* `response` — `{file, bytes, sha256}`, where `file` names a plain filename
  inside the package's own `probe/`, and `bytes` and `sha256` **agree with the
  committed file**.

The digest is what makes the claim more than a form filled in. It binds `live`
to the exact bytes it certifies: hand-edit `probe/list.html` afterwards and the
claim breaks, which is the property a reader actually wants from a word meaning
"this is what the board sent". A capture claiming `live` over a package with no
response committed cannot substantiate it and is counted.

**What `transcribed` must name.** A transcribed record's whole content is
"somebody else's committed command produced this", so it must say **which**,
and that command must be resolvable here:

* `transcribed_from` — a repo-relative path (no absolute path, no `..`) that
  exists.
* that file's text must contain the captured **URL**.
* and, for a POST, each top-level `key:value` of the captured body, rendered as
  compact JSON.

The text is read with backslashes stripped before matching, because the
committed command is usually a shell line inside a YAML scalar and
`-d '{\\"Keyword\\":\\"python\\"…}'` is the same request as the body it is being
compared to. Pairs are matched individually rather than as one serialised
object so that a source spelling the body in a different key order still
resolves — the claim is "this request is committed", not "these bytes are
committed in this order".

`usajobs_en` is the one capture that declares anything today, and it now names
`connectors/ruled-out.yaml`, whose `retest` line for usajobs.gov carries that
URL and that body.

**A package with no readable capture is counted too.** Otherwise the cheapest
way to satisfy a gate about capture provenance would be to delete the capture,
which is the fail-open direction this whole family of tasks keeps meeting.

**The denominator is a floor, not the count of the day** (T100, T111): twenty
captures ship, `MINIMUM_CAPTURES_SCANNED` is committed in their place, and a
scan finding fewer reports `unmeasured` rather than the clean zero an empty
`connectors/` would otherwise produce. A breach exits **1**, not the 3 that
`make evidence` records and walks past — that is T115's finding, and a module
written after it has no reason to reproduce the hole it names.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from integral.connector_coverage import is_example_site, read_package
from integral.connector_health import PROBE_CAPTURE_FILE
from integral.connectors import DEFAULT_CONNECTORS_DIR, PROBE_DIRNAME
from integral.pagination_capture import LIVE, TRANSCRIBED, UNRECORDED

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T153.json"

#: The three a capture may declare. Unlike `pagination_capture.PROVENANCE`,
#: which is the set of *claims*, this includes `UNRECORDED` — because after
#: this task a capture must say which of the three it is, and "nobody has
#: established this" is a statement a file can carry.
DECLARABLE = frozenset({LIVE, TRANSCRIBED, UNRECORDED})

#: The floor the denominator is checked against, committed in place of the
#: count of the day. Twenty non-example packages ship one capture each today;
#: fifteen leaves room for several to be retired without a false alarm while
#: staying far above what an empty, unreadable or example-only `connectors/`
#: would produce. Raise it when the library grows — it is a floor, not a target.
MINIMUM_CAPTURES_SCANNED = 15

#: `YYYY-MM-DD`, the spelling `connector_health.probe_captured_at` already
#: requires of the same field in the same file.
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: A plain filename inside `probe/`: no separators, no `.`/`..`, so a
#: `response.file` cannot address anything outside the package it belongs to.
_PLAIN_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Finding:
    """One capture whose provenance this module cannot hold it to.

    `claim` is what the artefact declared — including the sentinel `absent`,
    which is the finding T113's silent default hid.
    """

    package: str
    claim: str
    reason: str
    #: Every finding here is fail-open by construction: each one is a place the
    #: gate previously said yes to something it was built to refuse. The field
    #: is carried anyway so the evidence rows read the same as T113's.
    direction: str = "fail-open"

    def as_row(self) -> dict[str, str]:
        return {
            "package": self.package,
            "claim": self.claim,
            "reason": self.reason,
            "direction": self.direction,
        }


def read_record(package: Path) -> dict[str, Any] | None:
    """`probe/captured.json` as the raw mapping it holds, or `None`.

    Deliberately *not* `pagination_capture.read_capture`: that returns a
    `Capture` whose `provenance` has already been defaulted, so by the time it
    is in hand "declared nothing" and "declared `unrecorded`" are the same
    value — the very distinction this module exists to make. Absent,
    unreadable, not JSON, or JSON that is not an object all read as `None`,
    which is a finding rather than an error, the posture `connector_health` and
    `pagination_capture` already take toward this file.
    """
    path = package / PROBE_DIRNAME / PROBE_CAPTURE_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _valid_date(declared: Any, today: date) -> str | None:
    """`None` when `declared` is a usable capture date, else why it is not."""
    if not isinstance(declared, str) or not _ISO_DATE.match(declared):
        return f"captured_at {declared!r} is not a YYYY-MM-DD date"
    try:
        when = date.fromisoformat(declared)
    except ValueError:
        return f"captured_at {declared!r} is not a real date"
    if when > today:
        return f"captured_at {declared} is in the future — no fetch has happened yet"
    return None


def check_live(package: Path, record: dict[str, Any], today: date) -> list[str]:
    """Why this `live` claim is not substantiated by the package. Empty = it is.

    Every reason is read off the artefact: the recorded date, the recorded
    status, and the response bytes committed beside the record. Nothing here
    consults a commit message, a pull-request comment or the ledger — those are
    where the claim used to live, and moving it into the file was T113's whole
    point.
    """
    reasons: list[str] = []

    date_problem = _valid_date(record.get("captured_at"), today)
    if date_problem is not None:
        reasons.append(date_problem)

    status = record.get("status")
    if not isinstance(status, int) or isinstance(status, bool) or not 100 <= status <= 599:
        reasons.append(f"status {status!r} is not an HTTP status a response carried")

    response = record.get("response")
    if not isinstance(response, dict):
        reasons.append("no `response` block — a live capture leaves the bytes it recorded")
        return reasons

    name = response.get("file")
    if not isinstance(name, str) or not _PLAIN_FILENAME.match(name):
        reasons.append(f"response.file {name!r} is not a plain filename inside probe/")
        return reasons

    path = package / PROBE_DIRNAME / name
    try:
        body = path.read_bytes()
    except OSError:
        reasons.append(f"response.file {name!r} is not committed beside the capture")
        return reasons

    declared_bytes = response.get("bytes")
    if not isinstance(declared_bytes, int) or isinstance(declared_bytes, bool):
        reasons.append(f"response.bytes {declared_bytes!r} is not a byte count")
    elif declared_bytes != len(body):
        reasons.append(f"response.bytes {declared_bytes} but {name} is {len(body)} bytes on disk")

    declared_digest = response.get("sha256")
    if not isinstance(declared_digest, str) or not _SHA256.match(declared_digest):
        reasons.append(f"response.sha256 {declared_digest!r} is not a sha256 digest")
    else:
        actual = hashlib.sha256(body).hexdigest()
        if actual != declared_digest:
            reasons.append(f"response.sha256 does not match {name} ({actual} on disk)")

    return reasons


def _body_needles(body: Any) -> list[str]:
    """What a committed command must contain to have produced `body`.

    A mapping becomes one needle per top-level pair, rendered as compact JSON,
    so a source that spells the same request with its keys in another order
    still resolves. Anything else becomes one needle for the whole value.
    """
    if isinstance(body, dict):
        return [
            json.dumps({key: value}, separators=(",", ":"), ensure_ascii=False)[1:-1]
            for key, value in body.items()
        ]
    return [json.dumps(body, separators=(",", ":"), ensure_ascii=False)]


def check_transcribed(record: dict[str, Any], repo_root: Path = _REPO_ROOT) -> list[str]:
    """Why this `transcribed` claim names no resolvable committed request.

    `transcribed` means "somebody else's committed command produced this
    record", so the check is that the command is here and that it is a command
    for *this* request — the URL, and every field of the body if one was
    recorded.
    """
    reasons: list[str] = []

    source = record.get("transcribed_from")
    if not isinstance(source, str) or not source:
        reasons.append(
            "no `transcribed_from` — a transcribed record must name the committed "
            "request it came from"
        )
        return reasons

    candidate = Path(source)
    if candidate.is_absolute() or ".." in candidate.parts:
        reasons.append(f"transcribed_from {source!r} is not a repo-relative path")
        return reasons

    path = repo_root / candidate
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        reasons.append(f"transcribed_from {source!r} does not resolve in this repo")
        return reasons

    # The committed command is usually a shell line inside a YAML scalar, where
    # the body's quotes arrive backslash-escaped. Stripping backslashes is what
    # makes `-d '{\"Keyword\":\"python\"}'` and `{"Keyword": "python"}` the same
    # request rather than two strings that merely look alike.
    haystack = text.replace("\\", "")

    url = record.get("url")
    if not isinstance(url, str) or not url:
        reasons.append("no `url` to look for in the transcribed source")
    elif url not in haystack:
        reasons.append(f"{source} does not carry the captured URL {url}")

    body = record.get("body")
    if body is not None:
        missing = [needle for needle in _body_needles(body) if needle not in haystack]
        if missing:
            reasons.append(
                f"{source} does not carry the captured body: " + ", ".join(sorted(missing))
            )

    return reasons


def check_capture(
    package: Path, repo_root: Path = _REPO_ROOT, today: date | None = None
) -> Finding | None:
    """The finding this package's capture raises, or `None` if it has none."""
    today = date.today() if today is None else today

    record = read_record(package)
    if record is None:
        return Finding(package.name, "absent", "no readable probe/captured.json to enforce")

    if "provenance" not in record:
        return Finding(
            package.name,
            "absent",
            "no `provenance` key — an unstated provenance is a finding, not a default",
        )

    declared = record["provenance"]
    if not isinstance(declared, str) or declared not in DECLARABLE:
        return Finding(
            package.name,
            repr(declared),
            f"provenance is outside the vocabulary {sorted(DECLARABLE)}",
        )

    if declared == UNRECORDED:
        # It claims nothing, so there is nothing to substantiate. The honest
        # value for a record whose origin nobody established, and the one the
        # nineteen carry.
        return None

    reasons = (
        check_live(package, record, today)
        if declared == LIVE
        else check_transcribed(record, repo_root)
    )
    return None if not reasons else Finding(package.name, declared, "; ".join(reasons))


def measure(
    directory: Path | None = None,
    repo_root: Path | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Every shipped capture whose provenance this module cannot hold it to.

    The library, the repo root and the day are all substitutable, for
    `pagination_capture.measure`'s reason: a check that can only ever be run
    against the committed library can only ever be run against a library that
    is already passing, and a fabricated capture is exactly the input this
    needs to be handed.
    """
    directory = DEFAULT_CONNECTORS_DIR if directory is None else directory
    repo_root = _REPO_ROOT if repo_root is None else repo_root
    packages = sorted(p for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []

    examples: list[str] = []
    findings: list[Finding] = []
    claims: dict[str, int] = {LIVE: 0, TRANSCRIBED: 0, UNRECORDED: 0}
    scanned = 0
    for package in packages:
        if is_example_site(read_package(package).site):
            examples.append(package.name)
            continue
        scanned += 1
        record = read_record(package)
        declared = record.get("provenance") if record is not None else None
        if isinstance(declared, str) and declared in claims:
            claims[declared] += 1
        finding = check_capture(package, repo_root, today)
        if finding is not None:
            findings.append(finding)

    measured: dict[str, Any] = {
        "captures_with_an_unenforced_provenance": len(findings),
        "captures_scanned": scanned,
        "claims": claims,
        "example_packages_excluded": examples,
        "findings": [finding.as_row() for finding in findings],
        "fail_open": sum(1 for finding in findings if finding.direction == "fail-open"),
        "gate_status": "measured",
    }
    if scanned < MINIMUM_CAPTURES_SCANNED:
        measured["gate_status"] = "unmeasured"
        measured["unmeasured_reason"] = (
            f"only {scanned} capture(s) scanned (floor {MINIMUM_CAPTURES_SCANNED}) — "
            "zero unenforced provenances over a library nobody read is not a pass"
        )
    return measured


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed, out of what was measured.

    `captures_scanned` and `claims` are dropped and the floor committed in
    their place: both move the moment anybody adds, retires or re-records a
    connector, so committing them as exact values reddens `make evidence` on a
    change that is not a finding (T100). What must not move is the numerator,
    and it does not.
    """
    dropped = ("captures_scanned", "claims")
    committed = {key: value for key, value in measured.items() if key not in dropped}
    committed["captures_scanned_at_least"] = MINIMUM_CAPTURES_SCANNED
    return committed


def write_evidence(evidence: Path | None = None, directory: Path | None = None) -> dict[str, Any]:
    """Measure and record `status/evidence/T153.json`.

    A run that breaches the floor writes nothing: the only record it could
    write is one asserting a floor the run never met, and that artefact is what
    the next healthy run's `make evidence` would diff against.
    """
    evidence = DEFAULT_EVIDENCE_PATH if evidence is None else evidence
    measured = measure(directory)
    if measured["gate_status"] == "unmeasured":
        return measured
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.capture_provenance [evidence-path]` → T153's evidence.

    A floor breach returns **1**, not the 3 `make evidence` prints as
    "unmeasured (recorded)" and continues past. T115 is the finding: an
    anti-vacuity floor that does not fail the gate is decoration, and the
    evidence still records `gate_status: unmeasured` so the two statements —
    "this did not measure" and "this failed" — are both available.
    """
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(positional[0]) if positional else None)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        print(measured["unmeasured_reason"], file=sys.stderr)
        return 1
    for row in measured["findings"]:
        print(
            f"{row['direction']}: {row['package']} declares {row['claim']} — {row['reason']}",
            file=sys.stderr,
        )
    return 1 if measured["captures_with_an_unenforced_provenance"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
