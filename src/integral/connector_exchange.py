"""The connector exchange — discover, install, and offer to contribute (T54).

`docs/distribution.md` §6. Connectors flow both ways, and the tool does the work
so the candidate never has to know what a pull request is.

**Coming in.** The sources repository publishes a manifest over plain HTTPS — no
account, no authentication, and therefore **no authority**. Every name in it is
untrusted input: `_package_dir` accepts a single safe path component and refuses
anything that resolves outside the root it was given, so a manifest naming
`../../victim` writes nothing. `install` fetches the package into
`$INTEGRAL_HOME/connectors/` — the user's directory, resolved by T51's
`candidate_root`, which already refuses any path inside a git work tree — and
then runs the package's fixture test **before first use**.
`Installation.connector` is `None` whenever that check found violations, and
`usable_connectors` re-runs it over the whole installed library, so a stale
connector is not something either the single-package path or the bulk loader
hands back. It stays on disk, because repairing it is the same work as writing
one.

**Going out — and the reason this module is shaped the way it is.**

The gate is `unconsented_contributions == 0`, and a blocklist or an "are you
sure?" prompt read after the fact cannot deliver that: it detects a contribution
that already happened. So consent is **structural**.

- `contribute` is the only function that assembles anything, and its second
  parameter is an `Approval`.
- An `Approval` cannot exist saying anything but yes: `__post_init__` refuses
  every other answer, so there is no hand-built object that says "no" and no
  docstring standing in for an invariant.
- The approval carries the digest of the exact `Disclosure` it answered, and
  that digest covers the package's **resolved path** and a hash of its **file
  contents** — not just their names. A yes for one connector cannot be replayed
  against a look-alike disclosure rooted somewhere else, and files edited after
  the yes are refused rather than sent under it.
- One yes buys one contribution: `contribute` refuses a digest that already
  appears in the ledger.
- A connector already declined is refused even with an approval in hand —
  process spec §5.4's non-insistence rule, enforced rather than remembered.

Every refusal is recorded before it is raised, so the gate's denominator is the
number of contributions *attempted*, not the number that succeeded — otherwise
the only way to make the score look good would be to attempt less.

**How the measurement avoids grading its own homework.** `measure` reads the
ledgers **from disk** (T45, S6) and anchors every check on a root derived from
`home`, never on a value the record supplied — a check anchored on the writer's
own constraint is a tautology, not a measurement. And because a self-reported
list of paths is only as honest as the code that wrote it, the leak check does
not consult it at all: it reads the candidate's own files out of
`$INTEGRAL_HOME/profiles/` and searches every bundle and every ledger for their
text. `contribute` cannot author that away.

**What is deliberately not here.** No anonymous submission endpoint — it is the
only option that needs a service to run and defend, and the volume does not
justify one. The fork/branch/pull-request itself is a `gh` invocation, written
into the outbox next to the bundle and recorded in the audit record, never
executed: process spec §6.2's default is to stop one step short of sending.
Everything below is offline, so no test and no measurement needs a network or a
live sources repository.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import HTTPMessage
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import IO, Any

import yaml

from integral.connector_contract import check_package
from integral.connectors import (
    CONNECTOR_FILENAME,
    META_FILENAME,
    SITE_NAME,
    Connector,
    ConnectorError,
    load_connector,
)
from integral.state_home import candidate_root

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T54.json"

# The sources repository, and the two URLs read from it. Plain HTTPS against raw
# file paths: a manifest and the package files it names. Nothing here needs an
# account, which is the whole reason the incoming half can be automatic while
# the outgoing half cannot — and also why nothing it says may be trusted.
SOURCES_REPO = "nuncaeslupus/integral-connectors"
_RAW = f"https://raw.githubusercontent.com/{SOURCES_REPO}/main"
MANIFEST_URL = f"{_RAW}/manifest.json"
PACKAGE_BASE_URL = f"{_RAW}/connectors/"

# The fixture manifest this module's own gate is measured against. The sources
# repository now exists, and the probe still does not read it: pointing the gate
# at a committed manifest is what makes the measurement about *this code* rather
# than about whether somebody's server answered today — and the gate has to run
# where there is no egress at all. `tools/publish_connectors.py` builds the
# published tree from `connectors/`, and `tests/test_publish_connectors.py`
# installs from it offline, so what is published is checked without the network
# becoming a dependency of the gate.
DEFAULT_MANIFEST_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "exchange" / "manifest.json"
DEFAULT_PACKAGES_DIR = _REPO_ROOT / "connectors"

CONNECTORS_DIRNAME = "connectors"
OUTBOX_DIRNAME = "outbox"
PROFILES_DIRNAME = "profiles"
EXCHANGE_DIRNAME = "exchange"
CONTRIBUTIONS_FILENAME = "contributions.jsonl"
REFUSALS_FILENAME = "refusals.jsonl"
DECLINES_FILENAME = "declines.jsonl"
INSTALLS_FILENAME = "installs.jsonl"

# What counts as an explicit yes. Deliberately short: anything ambiguous — a
# silence, a "maybe", a "sure, whatever" — is not consent to publish somebody's
# work under their name, and no `Approval` can be built from any of it.
EXPLICIT_YES = frozenset({"yes", "y"})

SUBMISSION_NOTE = "SUBMISSION.txt"

# The shortest run of candidate text the leak check will hunt for. Below this a
# match is noise — "ES", "true", a date — and every bundle would be a defect.
LEAK_NEEDLE_MINIMUM = 12
_QUOTED = re.compile(rf'"([^"]{{{LEAK_NEEDLE_MINIMUM},}})"')


class ExchangeError(Exception):
    """A refusal by the exchange — never a network or a parse failure alone."""


Fetch = Callable[[str], str]
"""A URL in, its text out. Injected everywhere, so nothing below needs a network."""


# ---------------------------------------------------------------------------
# untrusted names


def _package_dir(root: Path, name: str) -> Path:
    """`root/name`, for a `name` that is one safe path component and nothing else.

    Both roots this module writes under — the installed library and the outbox —
    are joined with a name that came from somewhere else: the first from an
    unauthenticated manifest, the second from a `Disclosure` a caller built. A
    containment check anchored on the *joined* path is self-consistent and buys
    nothing, because an escaped join is its own happy root. So the name is
    validated as a component first, and the containment check is anchored on
    `root`.
    """
    if not isinstance(name, str) or not SITE_NAME.fullmatch(name):
        raise ExchangeError(f"{name!r} is not a connector package name")
    target = root / name
    if target.resolve().parent != root.resolve():
        raise ExchangeError(f"{name!r} would not stay inside {root}")
    return target


# ---------------------------------------------------------------------------
# coming in


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse a redirect that leaves https — on every hop, not just the first.

    `urlopen` follows redirects, and the stock handler is happy to send an
    `https` request onward to `http` or `ftp`. Checking only the URL the caller
    passed makes "no redirect off https" a comment rather than a guarantee, and
    the party choosing the redirect is the same unauthenticated server that
    supplies the package names `_package_dir` refuses to trust.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise ExchangeError(f"the exchange refuses a redirect off https: {newurl!r}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def https_fetcher(timeout: float = 20.0) -> Fetch:
    """The real reader: plain HTTPS, no credentials, and https on every hop."""
    opener = urllib.request.build_opener(_HttpsOnlyRedirects())

    def fetch(url: str) -> str:
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ExchangeError(f"the exchange reads https only, not {url!r}")
        with opener.open(url, timeout=timeout) as response:
            return str(response.read().decode("utf-8"))

    return fetch


def directory_fetcher(manifest: Path, packages: Path) -> Fetch:
    """Serve the manifest and packages from local directories.

    The offline stand-in for the sources repository, used by the tests and by
    this module's own probe. Same call signature as `https_fetcher`, so the code
    under measurement is the code that would run against the real thing.
    """

    def fetch(url: str) -> str:
        if url == MANIFEST_URL:
            return manifest.read_text(encoding="utf-8")
        if url.startswith(PACKAGE_BASE_URL):
            return (packages / url[len(PACKAGE_BASE_URL) :]).read_text(encoding="utf-8")
        raise ExchangeError(f"nothing is published at {url!r}")

    return fetch


@dataclass(frozen=True)
class ManifestEntry:
    """One connector on offer, with the provenance the candidate is shown."""

    package: str
    site: str
    country: str
    language: str
    contributor: str
    last_verified: str
    files: tuple[str, ...]

    @property
    def provenance(self) -> str:
        """The sentence `docs/distribution.md` §6 puts in front of the candidate."""
        return (
            f"There is already a connector for `{self.site}`, contributed by "
            f"{self.contributor} and last verified on {self.last_verified}."
        )


def read_manifest(fetch: Fetch) -> list[ManifestEntry]:
    """Read the sources repository's manifest. Offline when `fetch` is."""
    try:
        raw = json.loads(fetch(MANIFEST_URL))
    except (OSError, ValueError) as exc:
        raise ExchangeError(f"the manifest could not be read: {exc}") from exc
    try:
        return [
            ManifestEntry(
                package=str(item["package"]),
                site=str(item["site"]),
                country=str(item["country"]),
                language=str(item["language"]),
                contributor=str(item["contributor"]),
                last_verified=str(item["last_verified"]),
                files=tuple(str(name) for name in item["files"]),
            )
            for item in raw["connectors"]
        ]
    except (KeyError, TypeError) as exc:
        raise ExchangeError(f"the manifest is malformed: {exc}") from exc


def find(entries: list[ManifestEntry], site: str) -> ManifestEntry | None:
    """The entry covering `site`, or `None` — the sourcing step's question."""
    return next((entry for entry in entries if entry.site == site), None)


def home_dir(env: Mapping[str, str] | None = None) -> Path:
    """`$INTEGRAL_HOME` — the user's directory, never the clone (T51)."""
    return candidate_root(env=env)


def connectors_dir(home: Path | None = None) -> Path:
    """`$INTEGRAL_HOME/connectors/`, where a borrowed connector is installed."""
    return (home if home is not None else home_dir()) / CONNECTORS_DIRNAME


def outbox_dir(home: Path | None = None) -> Path:
    """`$INTEGRAL_HOME/outbox/`, where a prepared bundle waits to be sent."""
    return (home if home is not None else home_dir()) / OUTBOX_DIRNAME


@dataclass(frozen=True)
class Installation:
    """An installed package, and the verdict of its fixture test.

    `connector` is `None` exactly when `violations` is non-empty. That is the
    "before first use" rule made structural for a single install;
    `usable_connectors` is the same rule for the library as a whole.
    """

    package: Path
    entry: ManifestEntry
    violations: tuple[str, ...]
    connector: Connector | None

    @property
    def verified(self) -> bool:
        return self.connector is not None


def install(entry: ManifestEntry, fetch: Fetch, *, home: Path | None = None) -> Installation:
    """Fetch `entry` into `$INTEGRAL_HOME/connectors/`, then run its fixture test.

    The check is not optional and cannot be deferred: a stale connector fails
    here rather than in the middle of a search, and the tool offers to repair
    it. The files stay on disk either way — repairing is the same work as
    writing one, and deleting them would throw that head start away.
    """
    root = connectors_dir(home)
    target = _package_dir(root, entry.package)
    target.mkdir(parents=True, exist_ok=True)
    for name in entry.files:
        destination = (target / name).resolve()
        if not destination.is_relative_to(target.resolve()):
            raise ExchangeError(f"the manifest names a file outside the package: {name!r}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            fetch(PACKAGE_BASE_URL + f"{entry.package}/{name}"), encoding="utf-8"
        )

    violations = tuple(check_package(target).violations)
    connector: Connector | None = None
    if not violations:
        try:
            connector = load_connector(target)
        except ConnectorError as exc:  # pragma: no cover - check_package covers this
            violations = (f"the package would not load: {exc}",)

    _append(
        _ledger(home, INSTALLS_FILENAME),
        {
            "package": entry.package,
            "site": entry.site,
            "installed_at": str(target),
            "violations": list(violations),
            "at": _now(),
        },
    )
    return Installation(package=target, entry=entry, violations=violations, connector=connector)


def usable_connectors(home: Path | None = None) -> tuple[dict[str, Connector], list[str]]:
    """The installed library, loaded **through** the fixture check.

    `connectors.load_connectors` is the format-level loader and knows nothing
    about packaging; using it on the installed library would hand back a stale
    connector as readily as a sound one. This is the loader the exchange's
    invariant lives in, so "checked before first use" is a property of getting a
    connector at all rather than of one function's return type.

    ponytail: the check is re-run on every load rather than cached. The library
    is a handful of directories; add a `last_verified`-keyed cache if it ever
    grows enough to notice.
    """
    usable: dict[str, Connector] = {}
    rejected: list[str] = []
    root = connectors_dir(home)
    if not root.is_dir():
        return usable, rejected
    for package in sorted(p for p in root.iterdir() if p.is_dir()):
        if check_package(package).violations:
            rejected.append(package.name)
            continue
        try:
            usable[package.name] = load_connector(package)
        except ConnectorError:  # pragma: no cover - check_package covers this
            rejected.append(package.name)
    return usable, rejected


# ---------------------------------------------------------------------------
# going out — disclosure, approval, contribution


def bundle_files(package: Path) -> tuple[str, ...]:
    """Every file that would be sent, relative to the package — no exceptions.

    Derived by walking the package rather than listed from a constant, because
    the disclosure has to name what would *actually* go: a hard-coded list stays
    true until somebody adds a file to a package, and then it is a lie in the
    one place the candidate was promised the truth.
    """
    return tuple(sorted(str(p.relative_to(package)) for p in package.rglob("*") if p.is_file()))


@dataclass(frozen=True)
class Disclosure:
    """Everything stated before anything is sent (`docs/distribution.md` §6).

    `content_digest` is part of the identity, not decoration: without it a yes
    covers a list of file *names*, and the bytes behind them are free to change
    between the question and the answer.
    """

    package: Path
    package_name: str
    site: str
    github_username: str
    files: tuple[str, ...]
    content_digest: str

    def __post_init__(self) -> None:
        if not SITE_NAME.fullmatch(self.package_name):
            raise ExchangeError(f"{self.package_name!r} is not a connector package name")

    @property
    def digest(self) -> str:
        """Identifies *this* contribution, so approving one never approves another.

        Covers where the files are and what is in them, not only what they are
        called. Two directories with matching filenames — a connector package
        and a profile directory dressed up as one — are different contributions,
        and a yes for one is not a yes for the other.
        """
        return _digest(
            str(self.package.resolve()),
            self.package_name,
            self.site,
            self.github_username,
            self.files,
            self.content_digest,
        )

    @property
    def text(self) -> str:
        listed = "\n".join(f"  - {name}" for name in self.files)
        return (
            f"Contributing the `{self.site}` connector would send exactly these "
            f"files, and nothing else:\n{listed}\n"
            f"The contribution is public and carries your GitHub username "
            f"{self.github_username}.\n"
            "Nothing about you, your profile or your search is included — none of "
            "it is read to build this.\n"
            "Declining costs you nothing: the connector stays installed and "
            "working, and I will not ask about it again."
        )


def disclose(package: Path, *, github_username: str) -> Disclosure:
    """State the full disclosure for one connector. Reads only the package."""
    package = package.resolve()
    meta = yaml.safe_load((package / META_FILENAME).read_text(encoding="utf-8"))
    files = bundle_files(package)
    contents, _ = _read_bundle(package, files)
    return Disclosure(
        package=package,
        package_name=package.name,
        site=str(meta["site"]),
        github_username=github_username,
        files=files,
        content_digest=_hash_contents(contents),
    )


@dataclass(frozen=True)
class Approval:
    """One explicit yes to one disclosure — and nothing else can be built.

    The refusal is in `__post_init__` rather than only in `approve`, so
    `Approval(digest, "no", when)` raises wherever it is written. "One
    constructor" was a docstring before; now there is no object that says no.
    """

    disclosure_digest: str
    answer: str
    at: str

    def __post_init__(self) -> None:
        if self.answer.strip().lower() not in EXPLICIT_YES:
            raise ExchangeError(f"{self.answer!r} is not an explicit yes")


def approve(disclosure: Disclosure, answer: str, *, at: str | None = None) -> Approval | None:
    """An `Approval` for an explicit yes, `None` for anything else."""
    if answer.strip().lower() not in EXPLICIT_YES:
        return None
    return Approval(disclosure_digest=disclosure.digest, answer=answer, at=at or _now())


def _submission_command(disclosure: Disclosure) -> list[str]:
    """The `gh` invocation that would open the pull request.

    Private, and reachable only from `contribute`. It was public, which made it
    a way to assemble the whole outward action past every consent check and
    without entering any denominator — a pure function is still a bypass when it
    is the last step before a shell.

    ponytail: the agent runs the returned argv in the user's shell after
    `gh auth login`; nothing here shells out, so no test and no gate ever
    touches the network or somebody's credentials.
    """
    return [
        "gh",
        "pr",
        "create",
        "--repo",
        SOURCES_REPO,
        "--head",
        f"connector/{disclosure.package_name}",
        "--title",
        f"Add a connector for {disclosure.site}",
        "--body",
        f"Contributed by {disclosure.github_username}. Files: " + ", ".join(disclosure.files),
    ]


def contribute(
    disclosure: Disclosure,
    approval: Approval,
    *,
    home: Path | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    """Assemble the bundle and record the contribution. Requires an `Approval`.

    Five refusals, every one of them recorded before it is raised so that an
    attempt cannot be made to disappear by failing:

    1. an approval that is not one;
    2. an approval that says anything but yes — re-checked here rather than
       trusted, because the ledger's copy of it is what the gate reads;
    3. an approval that answered a *different* disclosure, where "different"
       includes a different directory and different file contents;
    4. an approval already spent — one yes buys one contribution;
    5. a connector the candidate has already declined.

    Past those, the only files read are the ones the disclosure named, from the
    one directory it named, and the bytes are re-hashed and compared with what
    was disclosed: a file edited between the question and the answer is refused,
    not sent under the old yes.
    """
    if not isinstance(approval, Approval):
        raise _refuse(disclosure, "a contribution needs an explicit per-item approval", home)
    if approval.answer.strip().lower() not in EXPLICIT_YES:
        raise _refuse(disclosure, "the approval records no explicit yes", home)
    if approval.disclosure_digest != disclosure.digest:
        raise _refuse(
            disclosure,
            "the approval answers a different disclosure — approving one "
            "contribution never approves another",
            home,
        )
    if _already_spent(approval.disclosure_digest, home):
        raise _refuse(disclosure, "that approval has already been used once", home)
    if not may_offer(disclosure.package_name, home=home):
        raise _refuse(disclosure, f"{disclosure.package_name} was declined", home)

    contents, paths_read = _read_bundle(disclosure.package, disclosure.files)
    if _hash_contents(contents) != disclosure.content_digest:
        raise _refuse(disclosure, "the files changed after the disclosure was approved", home)

    outbox = _package_dir(outbox_dir(home), disclosure.package_name)
    for name, text in contents.items():
        destination = outbox / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    command = _submission_command(disclosure)
    (outbox / SUBMISSION_NOTE).write_text(
        "This bundle has not been sent. To open the pull request:\n\n"
        + " ".join(command)
        + f"\n\nOr open an issue at https://github.com/{SOURCES_REPO}/issues with "
        "these files attached.\n",
        encoding="utf-8",
    )

    record = {
        "package": disclosure.package_name,
        "site": disclosure.site,
        "github_username": disclosure.github_username,
        "files": list(disclosure.files),
        "source_package": str(disclosure.package.resolve()),
        "content_digest": disclosure.content_digest,
        "paths_read": paths_read,
        "bundle": str(outbox),
        "submission": command,
        "approval": {
            "disclosure_digest": approval.disclosure_digest,
            "answer": approval.answer,
            "at": approval.at,
        },
        "at": at or _now(),
    }
    _append(_ledger(home, CONTRIBUTIONS_FILENAME), record)
    return record


def decline(disclosure: Disclosure, *, home: Path | None = None, at: str | None = None) -> None:
    """Record a decline. A complete outcome: nothing is sent, nothing is removed."""
    _append(
        _ledger(home, DECLINES_FILENAME),
        {"package": disclosure.package_name, "site": disclosure.site, "at": at or _now()},
    )


def may_offer(package_name: str, *, home: Path | None = None) -> bool:
    """`False` once this connector has been declined — §5.4's non-insistence rule."""
    return not any(
        record.get("package") == package_name
        for record in records(_ledger(home, DECLINES_FILENAME))
    )


# ---------------------------------------------------------------------------
# the measurement — read back from disk, anchored on nothing the writer supplied


def records(path: Path) -> list[dict[str, Any]]:
    """Every JSON object in a ledger file; an absent file is an empty ledger."""
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def audit(home: Path) -> list[str]:
    """Every recorded contribution no matching approval backs, named.

    Reads `contributions.jsonl` off disk and recomputes each record's disclosure
    digest from the record's own fields — including where the package was and
    what was in it. A record whose approval is missing, answers a different
    disclosure, carries something other than an explicit yes, or reuses a digest
    an earlier record already spent is named here.
    """
    defects: list[str] = []
    seen: set[str] = set()
    for index, record in enumerate(records(_ledger(home, CONTRIBUTIONS_FILENAME))):
        label = f"{record.get('package', f'record {index}')}"
        approval = record.get("approval")
        if not isinstance(approval, dict):
            defects.append(f"{label}: recorded with no approval")
            continue
        expected = _digest(
            str(record.get("source_package", "")),
            str(record.get("package", "")),
            str(record.get("site", "")),
            str(record.get("github_username", "")),
            tuple(str(name) for name in record.get("files", [])),
            str(record.get("content_digest", "")),
        )
        digest = str(approval.get("disclosure_digest", ""))
        # Answer first, digest second: an approval that says "no" is named for
        # what it says, not for the digest mismatch that also follows from it.
        if str(approval.get("answer", "")).strip().lower() not in EXPLICIT_YES:
            defects.append(f"{label}: the approval records no explicit yes")
        elif digest != expected:
            defects.append(f"{label}: the approval answers a different disclosure")
        elif digest in seen:
            defects.append(f"{label}: the approval was already spent on an earlier contribution")
        seen.add(digest)
    return defects


def foreign_reads(home: Path) -> list[str]:
    """Every path a recorded contribution read from outside the installed library.

    Anchored on `$INTEGRAL_HOME/connectors/`, **not** on the record's own
    `source_package`. Checking `paths_read` against the very value that
    constrained what went into `paths_read` compares a set against the rule that
    produced it: always empty, whatever the code does.
    """
    library = connectors_dir(home).resolve()
    defects: list[str] = []
    for record in records(_ledger(home, CONTRIBUTIONS_FILENAME)):
        for raw in record.get("paths_read", []):
            if not Path(str(raw)).is_relative_to(library):
                defects.append(f"{record.get('package')}: read {raw} outside the installed library")
    return defects


def candidate_strings(home: Path) -> list[str]:
    """Distinctive text belonging to the candidate, read from their own files.

    The needles for the leak check, taken from `$INTEGRAL_HOME/profiles/` rather
    than from anything the contribution path reported about itself.
    """
    found: set[str] = set()
    profiles = home / PROFILES_DIRNAME
    if not profiles.is_dir():
        return []
    for path in profiles.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover - binary profile artefact
            continue
        found.add(text.strip())
        found.update(_QUOTED.findall(text))
    return sorted(s for s in found if len(s) >= LEAK_NEEDLE_MINIMUM)


def candidate_data_in_output(home: Path) -> list[str]:
    """Every bundle or ledger file carrying text from the candidate's own files.

    This is the check the writer of `contribute` cannot author away. `audit` and
    `foreign_reads` both read a record the contribution path wrote; a mutant
    that reads `master.json` and persists it can simply not mention it. This
    reads *both* trees off disk and looks for one in the other, so the leak
    shows up in the output whether or not anything admitted to it.

    ponytail: substring matching, so a leak that transforms the text — encodes,
    summarises, re-words it — escapes. The structural guarantee is
    `_read_bundle`'s single root; this is the independent witness to it. Hash
    every field against a model of the profile if that ever stops being enough.
    """
    needles = candidate_strings(home)
    if not needles:
        return []
    defects: list[str] = []
    for root in (outbox_dir(home), home / EXCHANGE_DIRNAME):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):  # pragma: no cover - binary bundle artefact
                continue
            if any(needle in text for needle in needles):
                # Names where, never what: the finding must not itself become a
                # copy of the candidate's data, here or in committed evidence.
                defects.append(f"candidate text appears in {path.relative_to(home)}")
    return defects


def unverified_connectors_offered(home: Path) -> list[str]:
    """Every connector the loader hands back that fails its fixture check today.

    Re-runs `check_package` from disk over what `usable_connectors` returned, so
    a loader that stopped checking moves this number instead of leaving a
    docstring behind.
    """
    usable, _rejected = usable_connectors(home)
    return [name for name in usable if check_package(connectors_dir(home) / name).violations]


def measure(home: Path) -> dict[str, Any]:
    """T54's gate, read back from the ledgers under `home`.

    The denominator is contributions **attempted** — recorded plus refused —
    rather than contributions that succeeded. Scoring only what got through
    would reward refusing everything, and would let a probe that never tries
    anything hard report a clean sheet.

    D-2: `unconsented_contributions` is `None` when nothing was attempted. A
    passing zero over zero attempts is not a measurement, and reporting it as
    one is how a gate goes green while measuring nothing.
    """
    contributions = records(_ledger(home, CONTRIBUTIONS_FILENAME))
    refusals = records(_ledger(home, REFUSALS_FILENAME))
    installs = records(_ledger(home, INSTALLS_FILENAME))
    attempts = len(contributions) + len(refusals)
    unconsented = audit(home)
    foreign = foreign_reads(home)
    leaks = candidate_data_in_output(home)
    unverified = unverified_connectors_offered(home)
    _usable, rejected = usable_connectors(home)
    return {
        "unconsented_contributions": len(unconsented) if attempts else None,
        "contribution_attempts": attempts,
        "contributions_recorded": len(contributions),
        "contributions_refused": len(refusals),
        "contributions_declined": len(records(_ledger(home, DECLINES_FILENAME))),
        "installs_recorded": len(installs),
        "connectors_rejected_unverified": len(rejected),
        "foreign_path_reads": len(foreign),
        "candidate_data_in_output": len(leaks),
        "unverified_connectors_offered": len(unverified),
        "unconsented": unconsented,
        "foreign_reads": foreign,
        "leaks": leaks,
        "unverified_offered": unverified,
        # One list, so what the run prints and what it exits on cannot drift.
        # They did: `_main` printed a fourth defect list and computed the exit
        # code from three, so the gate could report a finding and still pass.
        "defects": [*unconsented, *foreign, *leaks, *unverified],
        "unmeasured_reason": None
        if attempts
        else "no contribution was attempted, so consent was not exercised",
    }


def probe(
    home: Path,
    manifest: Path = DEFAULT_MANIFEST_FIXTURE,
    packages: Path = DEFAULT_PACKAGES_DIR,
) -> None:
    """Drive the whole exchange under `home`, adversarially, against a fixture candidate.

    A fixture candidate — invented, in a temporary directory, never anyone's
    real profile — is planted first, precisely so the leak check has something
    to find if the contribution path ever grows a read it should not have.

    The sequence deliberately includes the paths that must fail, because they
    are what gives the gate a denominator worth dividing by: a stale connector
    that must be rejected, a refusal that must produce no approval, a decline
    that must survive a later yes, an approval replayed a second time, and files
    edited after the yes that covered them.
    """
    profile = home / PROFILES_DIRNAME / "fixture-candidate"
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "master.json").write_text(
        json.dumps(
            {
                "name": "Fixture Candidate",
                "note": "invented for the T54 probe; not a real person",
                "looking_for": "backend work in an invented city",
            }
        ),
        encoding="utf-8",
    )

    fetch = directory_fetcher(manifest, packages)
    entries = read_manifest(fetch)
    if not entries:
        raise ExchangeError("the fixture manifest publishes no connector")

    borrowed = install(entries[0], fetch, home=home)
    if not borrowed.verified:
        raise ExchangeError(f"the fixture package failed its own check: {borrowed.violations}")

    # A connector whose recorded markup no longer yields an offer. It installs,
    # it fails its fixture test, and no loader hands it back.
    stale_entry, stale_fetch = _stale_source(home / ".probe-sources", packages, entries[0])
    stale = install(stale_entry, stale_fetch, home=home)
    if stale.verified:
        raise ExchangeError("a stale connector passed its fixture test")
    usable, rejected = usable_connectors(home)
    if stale_entry.package in usable or stale_entry.package not in rejected:
        raise ExchangeError("the loader handed back a connector that failed its check")

    offer = disclose(borrowed.package, github_username="@fixture-user")
    if approve(offer, "no thanks") is not None:
        raise ExchangeError("a refusal produced an approval")
    decline(offer, home=home)
    if may_offer(offer.package_name, home=home) or not borrowed.package.is_dir():
        raise ExchangeError("declining did not leave the connector installed and unasked")
    _must_refuse(offer, _yes(offer), home, "a declined connector was contributed")

    written = _copy_package(borrowed.package, "handwritten_es")
    second = disclose(written, github_username="@fixture-user")
    consent = _yes(second)
    contribute(second, consent, home=home)
    _must_refuse(second, consent, home, "one approval bought two contributions")

    tampered = _copy_package(borrowed.package, "tampered_es")
    third = disclose(tampered, github_username="@fixture-user")
    stale_consent = _yes(third)
    (tampered / META_FILENAME).write_text(
        (tampered / META_FILENAME).read_text(encoding="utf-8") + "\n# edited after the yes\n",
        encoding="utf-8",
    )
    _must_refuse(third, stale_consent, home, "files edited after the yes were sent under it")


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Run the probe in a throwaway home, measure from its ledgers, record."""
    with TemporaryDirectory() as tmp:
        home = Path(tmp)
        probe(home)
        measured = measure(home)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def verdict(measured: dict[str, Any]) -> int:
    """0 clean, 1 a defect was found, 3 nothing was measured (D-2).

    Split out of `_main` so the rule can be exercised against a measurement the
    probe did not produce. A verdict reachable only by running the happy path is
    a verdict nobody has seen fail.
    """
    if measured["unconsented_contributions"] is None:
        return 3
    return 1 if measured["unconsented_contributions"] or measured["defects"] else 0


def _main(argv: list[str] | None = None) -> int:
    """`python -m integral.connector_exchange [evidence-path]` — T54's gate."""
    args = (argv or sys.argv)[1:]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))
    for defect in measured["defects"]:
        print(defect, file=sys.stderr)
    if measured["unmeasured_reason"]:
        print(measured["unmeasured_reason"], file=sys.stderr)
    return verdict(measured)


# ---------------------------------------------------------------------------
# internals


def _digest(*parts: str | tuple[str, ...]) -> str:
    payload = json.dumps([list(p) if isinstance(p, tuple) else p for p in parts], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_contents(contents: dict[str, str]) -> str:
    """A digest of what is in the files, not merely what they are called."""
    digest = hashlib.sha256()
    for name in sorted(contents):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(contents[name].encode("utf-8")).digest())
    return digest.hexdigest()


def _read_bundle(package: Path, files: tuple[str, ...]) -> tuple[dict[str, str], list[str]]:
    """The only reader on the contribution path, rooted at one package directory."""
    contents: dict[str, str] = {}
    paths: list[str] = []
    root = package.resolve()
    for name in files:
        path = (package / name).resolve()
        if not path.is_relative_to(root):
            raise ExchangeError(f"the disclosure names a file outside the package: {name!r}")
        contents[name] = path.read_text(encoding="utf-8")
        paths.append(str(path))
    return contents, paths


def _already_spent(digest: str, home: Path | None) -> bool:
    return any(
        (record.get("approval") or {}).get("disclosure_digest") == digest
        for record in records(_ledger(home, CONTRIBUTIONS_FILENAME))
    )


def _refuse(disclosure: object, reason: str, home: Path | None) -> ExchangeError:
    """Record the attempt, then hand back the error for the caller to raise.

    Every refusal enters the denominator. A refusal that left no trace would
    make "nothing was contributed without consent" true of a run that tried
    twenty times and was stopped twenty times, and of a run that never tried.
    """
    _append(
        _ledger(home, REFUSALS_FILENAME),
        {
            "package": getattr(disclosure, "package_name", None),
            "reason": reason,
            "at": _now(),
        },
    )
    return ExchangeError(reason)


def _ledger(home: Path | None, filename: str) -> Path:
    return (home if home is not None else home_dir()) / EXCHANGE_DIRNAME / filename


def _append(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _yes(disclosure: Disclosure) -> Approval:
    approval = approve(disclosure, "yes")
    if approval is None:  # pragma: no cover - "yes" is an explicit yes by construction
        raise ExchangeError("an explicit yes produced no approval")
    return approval


def _rebadge(package: Path, name: str) -> Path:
    """Rewrite a copied package so it belongs to the site its directory claims.

    A package's directory name must be `<site>_<locale>` (`connectors.load_connector`),
    so a copy under a new name is not a connector for a new site until its
    `site:` says so. Without this, every package the probe builds fails for the
    same uninteresting reason and the stale one never gets to fail for the
    interesting one.
    """
    site = name.rsplit("_", 1)[0]
    for filename, replacement in (
        (CONNECTOR_FILENAME, f"site: {site}"),
        (META_FILENAME, f"site: {site}.test"),
    ):
        path = package / filename
        path.write_text(
            re.sub(
                r"^site:.*$",
                replacement,
                path.read_text(encoding="utf-8"),
                count=1,
                flags=re.MULTILINE,
            ),
            encoding="utf-8",
        )
    return package


def _copy_package(source: Path, name: str) -> Path:
    target = _package_dir(source.parent, name)
    shutil.copytree(source, target, dirs_exist_ok=True)
    return _rebadge(target, name).resolve()


def _stale_source(root: Path, packages: Path, entry: ManifestEntry) -> tuple[ManifestEntry, Fetch]:
    """A copy of a real package whose recorded listing no longer yields an offer.

    Markup drift, which is what actually goes stale: the selectors are intact
    and the recorded response no longer contains anything they match.
    """
    stale = dataclasses.replace(entry, package="stalejobs_es", site="stalejobs.test")
    target = _package_dir(root, stale.package)
    shutil.copytree(packages / entry.package, target, dirs_exist_ok=True)
    _rebadge(target, stale.package)
    (target / "fixture" / "list.html").write_text("<html><body></body></html>\n", encoding="utf-8")
    return stale, directory_fetcher(root / "manifest.json", root)


def _must_refuse(disclosure: Disclosure, approval: Approval, home: Path, complaint: str) -> None:
    """Assert a contribution path refuses, and let the refusal reach the ledger."""
    try:
        contribute(disclosure, approval, home=home)
    except ExchangeError:
        return
    raise ExchangeError(complaint)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
