"""What a connector must satisfy to be *shared* — the conformance check (T53).

T32 settled the connector **format**: declarative, data not code, no stored
credential. This settles the **package**, which is a different question. A
selector file is enough to run a connector on the machine that wrote it; it is
not enough to borrow one. Borrowing needs to know who maintains it, when it
last worked, and — above all — whether it does what it claims *without asking
the network*, because the only honest way to review a scraper somebody else
wrote is to run it against a response they recorded.

So a shared connector is a directory (`docs/distribution.md` §5):

    connectors/<site-id>/
      connector.yaml     what to fetch, and the mapping to the offer schema
      parse.py           optional, only where the declarative form cannot express it
      fixture/           one recorded response, saved verbatim
        list.html          required — the listing page rule 2 is checked against
        detail.html        optional — recorded when the connector has a `detail`
      meta.yaml          site, country, language, maintainer handle, last_verified

The two fixture filenames are fixed rather than discovered. Rule 2 has to know
which recorded file is the listing in order to check anything against it, and
"whichever file sorts first" is the kind of rule that works until somebody adds
`README.html`. A contributor is told the name by the violation message rather
than having to find it here.

and six rules, in **one command** that a contributor's agent and CI both run,
so a green local check and a green CI are the same judgement rather than two
that drift:

1. one connector, one directory, exactly those files;
2. a fixture is present, and the connector's output over it satisfies the
   offer schema **offline** — no fixture, no merge;
3. no network of its own: only the runner's HTTP client, which owns rate
   limiting, robots.txt, timeouts and the user agent (checked statically);
4. no filesystem writes, no subprocess, no environment or credential reads;
5. `meta.yaml` complete, including `last_verified`;
6. policy: public listings only, robots.txt respected, no authentication,
   paywall or captcha bypass.

## Why rules 3 and 4 are static, and what that buys

They are checked by reading `parse.py` as an **AST**, never by running it.
Running it to see what it does is the thing the rules exist to prevent: by the
time an import has executed, a module-level `socket.connect` has already
happened. So the check parses, walks, and refuses — and it refuses against an
**allowlist** of imports rather than a blocklist of bad ones. A blocklist is a
list of the attacks somebody thought of; `importlib`, `ctypes`, `os.system`
via a re-export, and `builtins.__import__` are all things a blocklist misses on
the day it is written. The allowlist is short because the job is small: a
`parse.py` turns text into text.

This is the same argument `connectors.py` makes for its selector grammar, and
it is deliberately the same shape: match against a closed vocabulary, never
evaluate.

## Why the fixture's provenance is a rule and not a convention

Job adverts are public. The **set** of adverts a person reads is not — it
carries their field, their level, their city, and the fact that they are
looking at all. A fixture committed to a public repository carries whatever it
was made from, permanently, and no later deletion reaches a clone. So the
recorded response must declare itself a *sampled* fetch made for this purpose,
and a package whose fixture declares anything else — or declares nothing — is
refused rather than reviewed by hand.

## What this does not do

It does not create the sources repository or move connectors into it; that is
a follow-up, once there is more than one connector to move. It defines and
enforces the contract those connectors will have to satisfy, here, where there
is already one to check it against.

Exit: 0 every package conforms; 1 at least one violation; 3 nothing was
checked (no package at all is not a pass — see `MINIMUM_PACKAGES`).
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from jobsearch.connectors import (
    CONNECTOR_FILENAME,
    DEFAULT_CONNECTORS_DIR,
    FIXTURE_DIRNAME,
    META_FILENAME,
    ConnectorError,
    build_offer,
    connector_packages,
    load_connector,
    parse_detail_page,
    parse_list_page,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T53.json"

PARSE_FILENAME = "parse.py"

# Rule 1. Exactly these, and nothing else. An unexpected file is a violation
# rather than a warning: "one connector, one directory" is what lets a reviewer
# know that everything in the directory is the connector, and a stray
# `notes.txt` today is a stray `credentials.env` tomorrow.
REQUIRED_ENTRIES = frozenset({CONNECTOR_FILENAME, META_FILENAME, FIXTURE_DIRNAME})
OPTIONAL_ENTRIES = frozenset({PARSE_FILENAME})

# Rules 3 and 4, as an allowlist. A `parse.py` turns text into text; nothing
# here reaches a socket, a file, the environment or another process. See the
# module docstring for why this is not a blocklist.
ALLOWED_IMPORTS = frozenset({"re", "json", "datetime", "typing", "collections", "unicodedata"})

# Names that reach outside the process no matter how they are imported, so
# they are refused as calls even if some allowed module were to re-export one.
FORBIDDEN_CALLS = frozenset(
    {
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "input",
        "breakpoint",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "memoryview",
    }
)

# Rule 5. `last_verified` is the one that decays, and the one a borrower most
# needs: a connector is a claim about markup somebody else controls.
REQUIRED_META = ("site", "country", "language", "maintainer", "last_verified")

# Rule 6, as the only accepted answers. There is deliberately no vocabulary for
# "authenticated" or "paywalled" — a connector needing either could not be
# shared, so the schema cannot express it rather than the policy forbidding it.
REQUIRED_POLICY = {
    "listings": "public",
    "robots_txt": "respected",
    "authentication": "none",
}

# The fixture must say it was sampled for this purpose. See the docstring.
ACCEPTED_FIXTURE_PROVENANCE = "sampled"

# A clean result over no packages is not a clean result. `verify_gates` and CI
# both read the number this module writes, and "0 violations" from an empty
# directory reads identically to "0 violations" from a directory that was
# checked — which is the failure mode every gate in this repository is built to
# refuse.
MINIMUM_PACKAGES = 1


@dataclass(frozen=True)
class PackageReport:
    """One package's verdict. `violations` is empty exactly when it conforms."""

    name: str
    violations: tuple[str, ...] = ()


@dataclass
class ContractReport:
    """Every package's verdict, and the total the gate reads."""

    packages: list[PackageReport] = field(default_factory=list)

    @property
    def violations(self) -> list[str]:
        return [f"{p.name}: {v}" for p in self.packages for v in p.violations]


def _load_yaml(path: Path) -> Any:
    """`safe_load`, and only ever `safe_load`.

    The same reason `connectors.py` gives: a `!!python/object/apply:` tag in a
    contributed file constructs whatever it names, at load time, before any
    rule below has had a chance to look at it.
    """
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConnectorError(f"{path.name} could not be read: {exc}") from exc


def check_layout(package: Path) -> list[str]:
    """Rule 1 — one connector, one directory, exactly those files."""
    violations: list[str] = []
    present = {p.name for p in package.iterdir() if not p.name.startswith(".")}
    for required in sorted(REQUIRED_ENTRIES):
        if required not in present:
            violations.append(f"rule 1: {required} is missing")
    unexpected = sorted(present - REQUIRED_ENTRIES - OPTIONAL_ENTRIES)
    for name in unexpected:
        violations.append(f"rule 1: {name} is not part of a connector package")
    if (package / FIXTURE_DIRNAME).exists() and not (package / FIXTURE_DIRNAME).is_dir():
        violations.append(f"rule 1: {FIXTURE_DIRNAME} must be a directory")
    return violations


def check_meta(package: Path) -> list[str]:
    """Rules 5 and 6, plus the fixture's provenance."""
    meta_path = package / META_FILENAME
    if not meta_path.is_file():
        return [f"rule 5: {META_FILENAME} is missing"]
    try:
        meta = _load_yaml(meta_path)
    except ConnectorError as exc:
        return [f"rule 5: {exc}"]
    if not isinstance(meta, dict):
        return [f"rule 5: {META_FILENAME} is not a mapping"]

    violations: list[str] = []
    for key in REQUIRED_META:
        value = meta.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            violations.append(f"rule 5: {META_FILENAME} has no {key}")
    if "last_verified" in meta and meta["last_verified"] is not None:
        raw = meta["last_verified"]
        parsed = raw if isinstance(raw, date) else None
        if parsed is None:
            try:
                date.fromisoformat(str(raw))
            except ValueError:
                violations.append(
                    f"rule 5: last_verified {raw!r} is not an ISO date — a date nobody "
                    "can parse is the same as no date"
                )

    policy = meta.get("policy")
    if not isinstance(policy, dict):
        violations.append("rule 6: no policy block — public listings must be declared, not assumed")
    else:
        for key, expected in REQUIRED_POLICY.items():
            actual = policy.get(key)
            if actual != expected:
                violations.append(f"rule 6: policy.{key} is {actual!r}, must be {expected!r}")

    fixture_meta = meta.get("fixture")
    if not isinstance(fixture_meta, dict):
        violations.append(
            "rule 2: no fixture block — a recorded response must declare where it came from"
        )
    else:
        provenance = fixture_meta.get("provenance")
        if provenance != ACCEPTED_FIXTURE_PROVENANCE:
            violations.append(
                f"rule 2: fixture.provenance is {provenance!r}, must be "
                f"{ACCEPTED_FIXTURE_PROVENANCE!r} — a fixture is a listing sampled for this "
                "purpose, never an advert the candidate was reading"
            )
    return violations


def check_code(package: Path) -> list[str]:
    """Rules 3 and 4 — statically, by reading `parse.py`, never running it.

    No `parse.py` is the normal case and passes: the declarative form covers
    most sites, and this file exists for the ones it cannot express.
    """
    source_path = package / PARSE_FILENAME
    if not source_path.is_file():
        return []
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    except (OSError, SyntaxError) as exc:
        return [f"rule 3/4: {PARSE_FILENAME} could not be parsed: {exc}"]

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    violations.append(
                        f"rule 3/4: {PARSE_FILENAME} imports {alias.name!r}, which is not in "
                        f"the allowlist ({', '.join(sorted(ALLOWED_IMPORTS))})"
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            # `from . import x` has no module; a relative import inside a
            # connector package can only reach the package itself, which has no
            # other python in it, so it is refused rather than reasoned about.
            if node.level or root not in ALLOWED_IMPORTS:
                name = node.module or "." * node.level
                violations.append(
                    f"rule 3/4: {PARSE_FILENAME} imports from {name!r}, which is not in "
                    f"the allowlist ({', '.join(sorted(ALLOWED_IMPORTS))})"
                )
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else None
            if called in FORBIDDEN_CALLS:
                violations.append(f"rule 3/4: {PARSE_FILENAME} calls {called}()")
    return violations


def check_fixture(package: Path) -> list[str]:
    """Rule 2 — the connector's output over its own fixture is a valid offer.

    Offline by construction: this reads files and calls the interpreter. There
    is no HTTP client in this module to reach for, which is the point — CI
    running this over a contributed package must never become a scraping proxy
    for whatever URL that package names.
    """
    fixture_dir = package / FIXTURE_DIRNAME
    if not fixture_dir.is_dir():
        return ["rule 2: no fixture/ — no fixture, no merge"]
    recorded = sorted(
        p for p in fixture_dir.iterdir() if p.is_file() and not p.name.startswith(".")
    )
    if not recorded:
        return ["rule 2: fixture/ is empty — no fixture, no merge"]

    try:
        connector = load_connector(package)
    except ConnectorError as exc:
        return [f"rule 2: {exc}"]

    listing = fixture_dir / "list.html"
    if not listing.is_file():
        return [f"rule 2: fixture/list.html is missing — {[p.name for p in recorded]} recorded"]

    try:
        items = parse_list_page(connector, listing.read_text(encoding="utf-8"))
    except ConnectorError as exc:
        return [f"rule 2: the connector could not read its own fixture: {exc}"]
    if not items:
        return [
            "rule 2: the connector selects nothing from its own fixture — a recorded response "
            "it cannot read proves the opposite of what it is for"
        ]

    detail_fields: dict[str, str] | None = None
    detail = fixture_dir / "detail.html"
    if connector.detail is not None and detail.is_file():
        try:
            detail_fields = parse_detail_page(connector, detail.read_text(encoding="utf-8"))
        except ConnectorError as exc:
            return [f"rule 2: the connector could not read fixture/detail.html: {exc}"]

    try:
        build_offer(
            connector,
            list_fields=items[0],
            detail_fields=detail_fields,
            url=items[0].get("detail_url") or "https://example.invalid/offer",
            source_ref=f"{connector.site}:{connector.locale}",
        )
    except (ConnectorError, ValidationError) as exc:
        return [f"rule 2: the fixture does not yield a valid offer: {exc}"]
    return []


def check_package(package: Path) -> PackageReport:
    """Every rule, over one package."""
    violations = [
        *check_layout(package),
        *check_meta(package),
        *check_code(package),
        *check_fixture(package),
    ]
    return PackageReport(name=package.name, violations=tuple(violations))


def check_library(directory: Path = DEFAULT_CONNECTORS_DIR) -> ContractReport:
    """Every package under `directory`."""
    return ContractReport(packages=[check_package(p) for p in connector_packages(directory)])


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    directory: Path = DEFAULT_CONNECTORS_DIR,
) -> dict[str, Any]:
    """Measure T53's gate from the committed connector library and record it."""
    report = check_library(directory)
    measured: dict[str, Any] = {
        "connector_contract_violations": len(report.violations),
        "packages_checked": len(report.packages),
        "violations": report.violations,
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """The conformance command.

        python -m jobsearch.connector_contract [evidence-path] [--connectors DIR]

    `--connectors` is what makes this the *contributor's* command and not just
    ours: someone writing a connector on their own machine runs it over their
    own directory and gets the identical verdict CI will reach, which is the
    whole point of there being one command rather than a checklist.
    """
    args = argv[1:]
    directory = DEFAULT_CONNECTORS_DIR
    if "--connectors" in args:
        index = args.index("--connectors")
        if index + 1 >= len(args):
            print("connector-contract: --connectors needs a directory", file=sys.stderr)
            return 2
        directory = Path(args[index + 1])
        args = args[:index] + args[index + 2 :]
    positional = [arg for arg in args if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    try:
        measured = write_evidence(target, directory)
    except ConnectorError as exc:
        print(f"connector-contract: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(measured, ensure_ascii=False))
    if measured["packages_checked"] < MINIMUM_PACKAGES:
        print(
            f"only {measured['packages_checked']} package(s) checked "
            f"(floor {MINIMUM_PACKAGES}) — a clean result over nothing is not a result",
            file=sys.stderr,
        )
        return 3
    for violation in measured["violations"]:
        print(f"connector contract: {violation}", file=sys.stderr)
    return 1 if measured["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
