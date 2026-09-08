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
  the package **commits at that path** — a symlink is refused, because
  `read_bytes` follows one and a link is how a capture would certify itself
  against another package's response — and `bytes` and `sha256` **agree with
  the committed file**.

The last of those is one rule (`_committed_at`) rather than a check written per
call site, and that is not tidiness. Written twice it was wrong once: the leaf
was checked and the **directory holding it** was not, so a package whose
`probe/` was itself a symlink to a donor read as enforced over bytes it never
held — and a `probe/` linked at a sibling's made a package with no capture of
its own read as enforced. Every path this module reads out of a package or a
repository now goes through the same question, `probe/captured.json` included.

The digest is what makes the claim more than a form filled in. It binds `live`
to the exact bytes it certifies: hand-edit `probe/list.html` afterwards and the
claim breaks, which is the property a reader actually wants from a word meaning
"this is what the board sent". A capture claiming `live` over a package with no
response committed cannot substantiate it and is counted.

**What `transcribed` must name, and what that establishes.** A transcribed
record's whole content is "somebody else's committed command produced this".
Both halves of that sentence are checked, because both are about **what a
source has to be**:

* **another artefact.** `transcribed_from` is a repo-relative path — no
  absolute path, no `..`, no symlink out of the tree — that resolves, and that
  does **not** resolve inside the citing capture's own `probe/`. A record is
  not a source for itself: `captured.json` holds its own `url` and `body` by
  construction, so a capture citing its own file would satisfy every question a
  containment check can ask, at the cost of one line and no new file. That is
  the cheapest forgery this module could leave open, and it would sit behind
  its strongest-sounding word.
* **a command for this request.** One line of that file must carry a
  request-issuing command (`curl`, `wget`, `xh`, `Invoke-WebRequest`), the
  captured URL, and every top-level body field — the three together, on that
  line — and the command must be found in what is **left of the line once the
  URL and the body are struck out**. Naming a URL is not issuing one, and the
  string under test may not supply the evidence about itself: a URL whose path
  reads `/curl/`, or an ordinary job-board body of `{"q": "curl"}`, certified
  its own capture until a second reader asked. So the refused class is exactly
  **a mention that names no client command of its own** — a prose sentence
  carrying the URL, a dated comment about it, a note saying the fetch was
  refused. T113 decided that class when it refused to write `pythonorg_en`'s
  capture from exactly such a comment, because **"a dated sentence in a comment
  is not a capture"**. A module enforcing T113's field cannot accept what T113
  refused.

  A denial that **quotes** a command — *"we never ran: `curl -s '<url>'`"* — is
  not in that class and passes. Textual negation is not decidable and this does
  not try: what is established is that the repo commits the text of a command,
  never what the prose around it says was done with it. That limit is disclosed
  here and pinned by a control fixture rather than left as a sentence.

Lines are joined across a trailing `\\` before matching, since a `curl` wrapped
over several lines is one command, and the text is then read with backslashes
stripped, because the committed command is usually a shell line inside a YAML
scalar and `-d '{\\"Keyword\\":\\"python\\"…}'` is the same request as the body it
is being compared to. Body pairs are matched individually rather than as one
serialised object so that a source spelling them in a different key order still
resolves — but they must land on **one line**, so two keys mentioned in
unrelated places are not a body anybody sent.

So the honest reading of an enforced `transcribed` is **"this repo commits a
command for this request, somewhere other than in this record"** — not "these
bytes came back from that command". The method is not matched against the line;
nothing establishes the command was ever run; "resolves in this repo" is not
"is tracked by git"; and a client the vocabulary does not name reads as no
command at all, which is fail-closed. `check_transcribed`'s docstring states
each of those in full. Naming the ceiling is the point of the task: a marker
whose strength is overstated in prose is the same defect as one nobody checks,
one level up.

`usajobs_en` is the one capture that declares anything today, and it names
`connectors/ruled-out.yaml`, whose one-line `retest` command for usajobs.gov
carries the `curl`, that URL and that body together.

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

#: A plain filename: no separators, no `.`/`..`. This constrains the **name**
#: and nothing else — `\Z` rather than `$` so a trailing newline is not a
#: filename either. What keeps a `response.file` from addressing bytes outside
#: the package is the containment check in `check_live`, not this pattern: a
#: name matching here can still be a committed *symlink*, and `read_bytes`
#: follows it.
_PLAIN_FILENAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")

#: The clients a committed request is written with. A line carrying none of them
#: is prose *about* a request rather than a request, which is the distinction
#: T113 drew when it refused `pythonorg_en`'s dated comment. The list is narrow
#: on purpose: a request issued by a client it does not name reads as no command
#: at all — fail-closed, and the fix is to add the name. `http` is deliberately
#: absent, because every URL carries it and it would make the test trivially
#: true.
_REQUEST_COMMAND = re.compile(r"(?<![\w-])(?:curl|wget|xh|Invoke-WebRequest)(?![\w-])")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _committed_at(root: Path, relative: Path) -> bool:
    """Does `root` commit a file at `relative`, or does that path lead elsewhere?

    **One rule, three callers** — `read_record` asks it about
    `probe/captured.json`, `check_live` about `probe/<response.file>`, and
    `check_transcribed` about `transcribed_from`. All three are the same
    question: *does this tree carry those bytes at that path, or is some part of
    the path a link to somebody else's?* Written per call site it was written
    two different ways, and only one of them was right — `check_live` resolved
    **both** sides of its own comparison, which normalises a symlinked
    directory away on the left and the right alike, so the leaf was checked and
    the `probe/` holding it was not. That is T122's defect, two readers of one
    rule, and the repair is the shared rule rather than a second implementation
    that happens to agree today.

    The rule: resolve the **base**, never the relative part. `base / relative`
    is where the tree says the file is; `(base / relative).resolve()` is where
    the filesystem actually goes. They differ exactly when some component of
    `relative` is a symlink — the leaf, or any directory above it. Resolving the
    base first is what keeps a checkout or a library reached *through* a
    symlinked path from being refused for it, which would be fail-closed for
    every package at once.

    It says nothing about existence: a path with no file at it is "committed
    here" and fails later, on the read, with a reason about the file rather than
    about a link.
    """
    base = root.resolve()
    return (base / relative).resolve() == base / relative


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

    **A capture the package does not commit is not the package's capture.** The
    same containment rule the two checks use applies to this file first: a
    `probe/` that is a symlink to a sibling's makes every package downstream of
    it read as holding a record it does not have — `test_deleting_the_capture_is
    _not_the_cheapest_way_to_pass` with the deletion replaced by a link. Reading
    it here rather than in each check is what keeps `measure`'s claim tally and
    `check_capture`'s verdict from disagreeing about which file was read.
    """
    if not _committed_at(package, Path(PROBE_DIRNAME) / PROBE_CAPTURE_FILE):
        return None
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

    # The name is inside `probe/`; the bytes must be too. `read_bytes` follows a
    # symlink, and git commits symlinks, so a `list.html` pointing at another
    # package's probe — or at anything else on the machine — would otherwise let
    # a capture certify itself against bytes it never received. `_committed_at`
    # is asked about the whole relative path rather than the leaf, so `probe/`
    # being a link is the same refusal as `list.html` being one: this check used
    # to resolve both sides and could not see the directory at all.
    probe = package / PROBE_DIRNAME
    path = probe / name
    if not _committed_at(package, Path(PROBE_DIRNAME) / name):
        reasons.append(
            f"response.file {name!r} does not resolve inside the package's own "
            "probe/ — a symlink is not a committed response"
        )
        return reasons

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


def _command_lines(text: str) -> list[str]:
    """The source's lines, as a shell would see them. Two normalisations, no more.

    Physical lines ending in `\\` are **joined**, because a `curl` wrapped over
    five lines is one command and splitting it would refuse a perfectly good
    source. Backslashes are then dropped, because the committed command is
    usually a shell line inside a YAML scalar and `-d '{\\"Keyword\\":\\"python\\"}'`
    is the same request as the body it is being compared against.
    """
    joined = re.sub(r"\\[ \t]*\r?\n", " ", text)
    return [line.replace("\\", "") for line in joined.splitlines()]


def _issues_the_request(line: str, needles: list[str]) -> bool:
    """Is this one line a committed command for exactly this request?

    Two conditions, and the second is the one a second reader found missing.

    *All of the needles, on this line.* The captured URL and every top-level
    body field together, so that pieces scattered through a file do not add up
    to a request nobody sent.

    *A client word that is not one of the needles.* `_REQUEST_COMMAND` used to
    be applied to the whole line, needles included, so the very strings under
    test could supply the independent evidence that a request was issued: a file
    whose entire content was `https://example.com/curl/jobs` certified its own
    capture, and so did a body of `{"q": "curl"}` — an ordinary search for a job
    board about developer tools. That is the same shape as a record citing
    itself, one level in: the thing being checked must not be able to satisfy
    the check. So the command is looked for in what is **left of the line once
    the needles are struck out**.

    They are replaced by a space rather than deleted, because deleting them
    could splice a client word out of the two halves that surrounded one — a
    fix that manufactured the evidence it removed would be the same defect
    again, in the other direction.
    """
    if not all(needle in line for needle in needles):
        return False
    remainder = line
    for needle in needles:
        remainder = remainder.replace(needle, " ")
    return _REQUEST_COMMAND.search(remainder) is not None


def check_transcribed(
    package: Path, record: dict[str, Any], repo_root: Path = _REPO_ROOT
) -> list[str]:
    """Why this `transcribed` claim names no committed command for this request.

    `transcribed` means "somebody else's committed command produced this
    record", and that sentence has two halves the check has to ask about
    separately — because both are about **what a source has to be**, and a
    source failing either one substantiates nothing.

    *Somebody else's* — `transcribed_from` is a repo-relative path (no absolute
    path, no `..`, and no symlink anywhere along it) that resolves, and that does not
    resolve inside the citing capture's own `probe/`. A record is not a source
    for itself: `captured.json` contains its own `url` and its own `body` by
    construction, so a capture citing its own file would answer every question
    the check can ask, at a cost of one line and no new file — the cheapest
    forgery the module could possibly leave open, sitting behind its
    strongest-sounding word.

    *Command* — one line of that file must carry a request-issuing command
    together with the URL and every top-level body field, and the command must
    still be there once the URL and the body are **struck out of the line**.
    Naming a URL is not issuing one, and the strings under test may not be the
    evidence about themselves: a URL whose path reads `/curl/`, or a body of
    `{"q": "curl"}` — an ordinary thing for this tool to have searched — used to
    certify their own capture out of a file containing nothing else.

    So the refused class is precisely **a mention that names no client command
    of its own**: a prose sentence carrying the URL, a dated comment about it, a
    note saying the fetch was refused. T113 already decided that class — it
    refused to write `pythonorg_en`'s capture from exactly such a comment,
    because "a dated sentence in a comment is not a capture" — and a module
    enforcing T113's own field must not accept what T113 refused.

    **The disclosed limit, stated where it can be checked rather than implied.**
    A denial that *quotes* a command — "we never ran: `curl -s '<url>'`" —
    passes, and that is the honest ceiling rather than a gap: textual negation
    is not decidable, and a check that guessed at one would be a worse thing
    than a narrow one. Nothing here reads what the prose says was *done* with
    the command; only that its text is committed. An earlier draft of this
    docstring claimed the refused class included "a note recording that the
    fetch was refused and never made", which is true only of the spellings that
    omit a client word — a docstring certifying a property its test does not
    check, which is this task's own subject one level up.

    Body pairs are matched individually rather than as one serialised object, so
    a source spelling the same request with its keys in another order still
    resolves — but they must be found on **one line**, so two keys mentioned in
    unrelated places do not add up to a body that was never sent.

    **What this establishes, and what it does not.** The honest reading of an
    enforced `transcribed` is *"this repo commits a command for this request,
    somewhere other than in this record"* — not "these bytes came back from
    that command". Specifically:

    * the **method** is not matched against the line, so a committed `curl` of
      the same URL carrying the same fields satisfies a `POST` claim and a
      `GET` one alike;
    * nothing establishes the command was ever **run**, or that its output is
      what `captured.json` records — only that it is committed here;
    * "resolves in this repo" is not "is tracked by git": an untracked working
      -tree file satisfies it. `tools/verified_gate.sh` measures a clean
      checkout, which makes that gap hard to reach rather than closed;
    * the client vocabulary is a fixed list. A request issued by a client
      `_REQUEST_COMMAND` does not name reads as no command at all — fail-closed,
      and the fix is to add the name.
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

    root = repo_root.resolve()
    path = root / candidate
    if not _committed_at(repo_root, candidate):
        reasons.append(
            f"transcribed_from {source!r} is not the file this repo commits at that "
            "path — a symlink is not a committed source"
        )
        return reasons

    probe = (package / PROBE_DIRNAME).resolve()
    resolved = path.resolve()
    if resolved == probe or probe in resolved.parents:
        reasons.append(
            f"transcribed_from {source!r} is inside the capture's own probe/ — "
            "a record is not a source for itself"
        )
        return reasons

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        reasons.append(f"transcribed_from {source!r} does not resolve in this repo")
        return reasons

    lines = _command_lines(text)
    haystack = "\n".join(lines)

    url = record.get("url")
    if not isinstance(url, str) or not url:
        reasons.append("no `url` to look for in the transcribed source")
        return reasons
    if url not in haystack:
        reasons.append(f"{source} does not carry the captured URL {url}")

    needles = [url]
    body = record.get("body")
    if body is not None:
        body_needles = _body_needles(body)
        missing = [needle for needle in body_needles if needle not in haystack]
        if missing:
            reasons.append(
                f"{source} does not carry the captured body: " + ", ".join(sorted(missing))
            )
        needles.extend(body_needles)

    if reasons:
        return reasons

    # Every piece is somewhere in the file. The claim is that a *command* for
    # this request is committed, so they must be one command: a single line
    # issuing a request, carrying the URL and the whole body, and naming a
    # client somewhere other than inside the URL and body themselves.
    if not any(_issues_the_request(line, needles) for line in lines):
        reasons.append(
            f"{source} mentions this request but commits no command for it — no single "
            "line carries a request command together with the captured URL and every "
            "body field, and a sentence about a fetch is not a fetch"
        )
    return reasons


def check_capture(
    package: Path, repo_root: Path = _REPO_ROOT, today: date | None = None
) -> Finding | None:
    """The finding this package's capture raises, or `None` if it has none."""
    today = date.today() if today is None else today

    record = read_record(package)
    if record is None:
        if not _committed_at(package, Path(PROBE_DIRNAME) / PROBE_CAPTURE_FILE):
            return Finding(
                package.name,
                "absent",
                "probe/captured.json is not the file this package commits at that path "
                "— a symlinked probe/ borrows another package's capture instead of "
                "holding one of its own",
            )
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
        else check_transcribed(package, record, repo_root)
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
    # Built from `DECLARABLE` rather than re-spelled: a second literal list of
    # the same three values is a second reader of one rule, and the one that
    # would silently stop counting if the vocabulary ever grew.
    claims: dict[str, int] = dict.fromkeys(sorted(DECLARABLE), 0)
    scanned = 0
    for package in packages:
        if is_example_site(read_package(package).site):
            examples.append(package.name)
            continue
        scanned += 1
        record = read_record(package)
        declared = record.get("provenance") if record is not None else None
        if isinstance(declared, str) and declared in DECLARABLE:
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

    `captures_scanned`, `claims` and `example_packages_excluded` are dropped and
    the floor committed in their place: all three move the moment anybody adds,
    retires or re-records a connector, so committing them as exact values
    reddens `make evidence` on a change that is not a finding (T100/T150).
    The list of excluded examples is the one a second reader caught still being
    committed exactly — it is a note about the scan, not a measurement, and
    adding a second example package would have reddened the gate for a reason
    unrelated to any provenance. What must not move is the numerator, and it
    does not.

    **`fail_open` is dropped too, and that one is this task's own subject caught
    in this task's own evidence.** `Finding.direction` defaults to `fail-open`
    and nothing in this module ever sets it to anything else, so the committed
    `fail_open` was `len(findings)` written twice — two numbers in one record
    that cannot disagree, the second reading as a corroborating measurement and
    corroborating nothing. `cue_audit` and `second_reader` compute a direction
    per case, which is what makes their `fail_open` a measurement; here it was a
    constant wearing one's clothes. The per-row `direction` stays, because as a
    *label on a row* it is a true and useful statement — it is the aggregate
    that pretended to be measured. Anyone wanting the count can add up the rows,
    which is the only place the fact actually lives.
    """
    dropped = ("captures_scanned", "claims", "example_packages_excluded", "fail_open")
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
