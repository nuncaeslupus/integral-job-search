"""The connector exchange — discover, install, and offer to contribute (T54).

`docs/distribution.md` §6. Connectors flow both ways, and the tool does the work
so the candidate never has to know what a pull request is.

**Coming in.** The sources repository publishes a manifest over plain HTTPS — no
account, no authentication. `read_manifest` parses it, each entry carrying its
provenance (who contributed it, when it was last verified) so the offer to the
candidate can say *why* they should trust it. `install` writes the package into
`$INTEGRAL_HOME/connectors/` — the user's directory, resolved by T51's
`candidate_root`, which already refuses any path inside a git work tree — and
then runs the package's fixture test **before first use**. That is not a
convention here: `Installation.connector` is `None` whenever the check found
violations, so a stale connector is not something a caller can obtain and use.
It stays on disk, because repairing it is the same work as writing one.

**Going out — and the reason this module is shaped the way it is.**

The gate is `unconsented_contributions == 0`, and a blocklist or an "are you
sure?" prompt read after the fact cannot deliver that: it detects a contribution
that already happened. So consent is **structural**. There is exactly one
function that sends anything, `contribute`, and its second parameter is an
`Approval`. An `Approval` has one constructor, `approve`, which returns `None`
for every answer that is not an explicit yes — so a declined offer produces
nothing to pass. And an `Approval` carries the digest of the exact `Disclosure`
it answered; `contribute` refuses one whose digest does not match the bundle in
front of it, so approving *some* contribution never authorises *this* one. A
contribution without a per-item yes is not a thing this code can produce.

The same reasoning covers the candidate's data. The bundle cannot carry anything
about them because the contribution path never reads anything of theirs: files
come from `_read_bundle`, whose only root is the connector package directory,
and every absolute path it opened is recorded in the audit record. The
measurement then reads those records **from disk** and confirms it — the numbers
come from what was written, not from the objects that wrote it (T45, S6).

**Declining is a complete outcome, not a fallback** (process spec §5.4). The
connector stays installed and working, and `may_offer` returns `False` for that
connector forever after, so a second offer is not something the code can make
either. `contribute` consults it too: a declined connector cannot be contributed
even with an approval in hand.

**What is deliberately not here.** No anonymous submission endpoint — it is the
only option that needs a service to run and defend, and the volume does not
justify one. The fork/branch/pull-request itself is a `gh` invocation
(`submission_command`), written into the outbox next to the bundle and recorded
in the audit record, never executed from here: process spec §6.2's default is to
stop one step short of sending. Everything below is offline, so no test and no
measurement needs a network or a live sources repository.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml

from integral.connector_contract import check_package
from integral.connectors import META_FILENAME, Connector, ConnectorError, load_connector
from integral.state_home import candidate_root

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T54.json"

# The sources repository, and the two URLs read from it. Plain HTTPS against raw
# file paths: a manifest and the package files it names. Nothing here needs an
# account, which is the whole reason the incoming half can be automatic while
# the outgoing half cannot.
SOURCES_REPO = "nuncaeslupus/integral-connectors"
_RAW = f"https://raw.githubusercontent.com/{SOURCES_REPO}/main"
MANIFEST_URL = f"{_RAW}/manifest.json"
PACKAGE_BASE_URL = f"{_RAW}/connectors/"

# The fixture manifest this module's own gate is measured against. There is no
# published sources repository yet; pointing the probe at a committed manifest
# is what makes the measurement about *this code* rather than about whether
# somebody's server answered today.
DEFAULT_MANIFEST_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "exchange" / "manifest.json"
DEFAULT_PACKAGES_DIR = _REPO_ROOT / "connectors"

CONNECTORS_DIRNAME = "connectors"
OUTBOX_DIRNAME = "outbox"
EXCHANGE_DIRNAME = "exchange"
CONTRIBUTIONS_FILENAME = "contributions.jsonl"
DECLINES_FILENAME = "declines.jsonl"
INSTALLS_FILENAME = "installs.jsonl"

# What counts as an explicit yes. Deliberately short: anything ambiguous — a
# silence, a "maybe", a "sure, whatever" — is not consent to publish somebody's
# work under their name, and `approve` returns `None` for all of it.
EXPLICIT_YES = frozenset({"yes", "y"})

SUBMISSION_NOTE = "SUBMISSION.txt"


class ExchangeError(Exception):
    """A refusal by the exchange — never a network or a parse failure alone."""


Fetch = Callable[[str], str]
"""A URL in, its text out. Injected everywhere, so nothing below needs a network."""


# ---------------------------------------------------------------------------
# coming in


def https_fetcher(timeout: float = 20.0) -> Fetch:
    """The real reader: plain HTTPS, no credentials, no redirect off https."""

    def fetch(url: str) -> str:
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ExchangeError(f"the exchange reads https only, not {url!r}")
        with urllib.request.urlopen(url, timeout=timeout) as response:
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


@dataclass(frozen=True)
class Installation:
    """An installed package, and the verdict of its fixture test.

    `connector` is `None` exactly when `violations` is non-empty. That is the
    "before first use" rule made structural: the only way to get a usable
    `Connector` out of an install is for the fixture check to have passed first.
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
    target = connectors_dir(home) / entry.package
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
    """Everything stated before anything is sent (`docs/distribution.md` §6)."""

    package: Path
    package_name: str
    site: str
    github_username: str
    files: tuple[str, ...]

    @property
    def digest(self) -> str:
        """Identifies *this* contribution, so approving one never approves another."""
        return _digest(self.package_name, self.site, self.github_username, self.files)

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
    meta = yaml.safe_load((package / META_FILENAME).read_text(encoding="utf-8"))
    return Disclosure(
        package=package,
        package_name=package.name,
        site=str(meta["site"]),
        github_username=github_username,
        files=bundle_files(package),
    )


@dataclass(frozen=True)
class Approval:
    """One explicit yes to one disclosure. `approve` is its only constructor."""

    disclosure_digest: str
    answer: str
    at: str


def approve(disclosure: Disclosure, answer: str, *, at: str | None = None) -> Approval | None:
    """An `Approval` for an explicit yes, `None` for anything else.

    `None` is the whole mechanism: a declined or ambiguous answer produces no
    object, and `contribute` cannot be called without one.
    """
    if answer.strip().lower() not in EXPLICIT_YES:
        return None
    return Approval(disclosure_digest=disclosure.digest, answer=answer, at=at or _now())


def submission_command(disclosure: Disclosure) -> list[str]:
    """The `gh` invocation that would open the pull request.

    Built and recorded, never run from here. ponytail: the agent runs this in
    the user's shell after `gh auth login`; nothing in this module shells out,
    so no test and no gate ever touches the network or somebody's credentials.
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

    Three refusals, in the order they matter: an approval that is not one, an
    approval that answered a *different* disclosure, and a connector the
    candidate has already declined. Past those, the only files read are the ones
    the disclosure named, and every path opened goes into the record so the
    measurement can check it from disk.
    """
    if not isinstance(approval, Approval):
        raise ExchangeError("a contribution needs an explicit per-item approval")
    if approval.disclosure_digest != disclosure.digest:
        raise ExchangeError(
            "the approval answers a different disclosure — approving one "
            "contribution never approves another"
        )
    if not may_offer(disclosure.package_name, home=home):
        raise ExchangeError(f"{disclosure.package_name} was declined; it is not offered again")

    contents, paths_read = _read_bundle(disclosure.package, disclosure.files)
    outbox = (home if home is not None else home_dir()) / OUTBOX_DIRNAME / disclosure.package_name
    for name, text in contents.items():
        destination = outbox / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    command = submission_command(disclosure)
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
# the measurement — read back from disk, never from the objects that wrote it


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
    digest from the record's own fields. A record whose approval is missing,
    answers a different disclosure, or carries something other than an explicit
    yes is named here — which is what lets a planted record make the gate fail.
    """
    defects: list[str] = []
    for index, record in enumerate(records(_ledger(home, CONTRIBUTIONS_FILENAME))):
        label = f"{record.get('package', f'record {index}')}"
        approval = record.get("approval")
        if not isinstance(approval, dict):
            defects.append(f"{label}: recorded with no approval")
            continue
        expected = _digest(
            str(record.get("package", "")),
            str(record.get("site", "")),
            str(record.get("github_username", "")),
            tuple(str(name) for name in record.get("files", [])),
        )
        # Answer first, digest second: an approval that says "no" is named for
        # what it says, not for the digest mismatch that also follows from it.
        if str(approval.get("answer", "")).strip().lower() not in EXPLICIT_YES:
            defects.append(f"{label}: the approval records no explicit yes")
        elif approval.get("disclosure_digest") != expected:
            defects.append(f"{label}: the approval answers a different disclosure")
    return defects


def foreign_reads(home: Path) -> list[str]:
    """Every path a recorded contribution read from outside its own package.

    The disk-side half of "the bundle cannot carry candidate data": the
    contribution path records what it opened, and anything not under the
    connector package — a profile tree above all — is named here.
    """
    defects: list[str] = []
    for record in records(_ledger(home, CONTRIBUTIONS_FILENAME)):
        package = Path(str(record.get("source_package", "")))
        for raw in record.get("paths_read", []):
            if not Path(str(raw)).is_relative_to(package):
                defects.append(f"{record.get('package')}: read {raw} outside its connector package")
    return defects


def unchecked_installs(home: Path) -> list[str]:
    """Every install recorded without a fixture verdict — "before first use", audited."""
    return [
        str(record.get("package"))
        for record in records(_ledger(home, INSTALLS_FILENAME))
        if "violations" not in record
    ]


def measure(home: Path) -> dict[str, Any]:
    """T54's gate, read back from the ledgers under `home`.

    D-2: `unconsented_contributions` is `None` when nothing was contributed. A
    passing zero over zero attempts is not a measurement, and reporting it as
    one is how a gate goes green while measuring nothing.
    """
    contributions = records(_ledger(home, CONTRIBUTIONS_FILENAME))
    unconsented = audit(home)
    foreign = foreign_reads(home)
    unchecked = unchecked_installs(home)
    return {
        "unconsented_contributions": len(unconsented) if contributions else None,
        "contributions_recorded": len(contributions),
        "contributions_declined": len(records(_ledger(home, DECLINES_FILENAME))),
        "installs_checked_before_use": len(records(_ledger(home, INSTALLS_FILENAME)))
        - len(unchecked),
        "foreign_path_reads": len(foreign),
        "unconsented": unconsented,
        "foreign_reads": foreign,
        "unchecked_installs": unchecked,
        "unmeasured_reason": None
        if contributions
        else "no contribution was attempted, so consent was not exercised",
    }


def probe(
    home: Path,
    manifest: Path = DEFAULT_MANIFEST_FIXTURE,
    packages: Path = DEFAULT_PACKAGES_DIR,
) -> None:
    """Drive the whole exchange once, against a fixture candidate, under `home`.

    A fixture candidate — invented, in a temporary directory, never anyone's
    real profile — is planted first, precisely so `foreign_reads` has something
    to catch if the contribution path ever grows a read it should not have.

    The sequence is `docs/distribution.md` §6 end to end: read the manifest,
    install with its fixture test, decline the borrowed one (and confirm it
    stays installed and is not offered again), then contribute the one written
    locally, on an explicit yes and not otherwise.
    """
    profile = home / "profiles" / "fixture-candidate"
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "master.json").write_text(
        json.dumps({"name": "Fixture Candidate", "note": "invented; not a real person"}),
        encoding="utf-8",
    )

    fetch = directory_fetcher(manifest, packages)
    entries = read_manifest(fetch)
    if not entries:
        raise ExchangeError("the fixture manifest publishes no connector")

    borrowed = install(entries[0], fetch, home=home)
    if not borrowed.verified:
        raise ExchangeError(f"the fixture package failed its own check: {borrowed.violations}")

    offer = disclose(borrowed.package, github_username="@fixture-user")
    if approve(offer, "no thanks") is not None:
        raise ExchangeError("a refusal produced an approval")
    decline(offer, home=home)
    if may_offer(offer.package_name, home=home) or not borrowed.package.is_dir():
        raise ExchangeError("declining did not leave the connector installed and unasked")

    written = borrowed.package.parent / "handwritten_es"
    shutil.copytree(borrowed.package, written, dirs_exist_ok=True)
    second = disclose(written, github_username="@fixture-user")
    consent = approve(second, "yes")
    if consent is None:  # pragma: no cover - "yes" is an explicit yes by construction
        raise ExchangeError("an explicit yes produced no approval")
    contribute(second, consent, home=home)


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Run the probe in a throwaway home, measure from its ledgers, record."""
    with TemporaryDirectory() as tmp:
        home = Path(tmp)
        probe(home)
        measured = measure(home)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str] | None = None) -> int:
    """`python -m integral.connector_exchange [evidence-path]` — T54's gate."""
    args = (argv or sys.argv)[1:]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))
    for defect in (
        *measured["unconsented"],
        *measured["foreign_reads"],
        *measured["unchecked_installs"],
    ):
        print(defect, file=sys.stderr)
    if measured["unconsented_contributions"] is None:
        print(measured["unmeasured_reason"], file=sys.stderr)
        return 3
    return 1 if measured["unconsented_contributions"] or measured["foreign_path_reads"] else 0


# ---------------------------------------------------------------------------
# internals


def _digest(package: str, site: str, github_username: str, files: tuple[str, ...]) -> str:
    payload = json.dumps(
        {
            "package": package,
            "site": site,
            "github_username": github_username,
            "files": list(files),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


def _ledger(home: Path | None, filename: str) -> Path:
    return (home if home is not None else home_dir()) / EXCHANGE_DIRNAME / filename


def _append(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
