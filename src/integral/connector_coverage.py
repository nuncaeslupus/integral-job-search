"""D-16 — sourcing that has no connector for the candidate's market must say so.

`connectors/` holds one package, `examplejobs_es`, whose own header says
`examplejobs.test` is not a real job board. During the test session of
2026-08-20 `integral.connectors` was never called at all: step 7 ran a general
`WebSearch`, fetched two of the hits, and presented seven adverts. Nothing in
that exchange told the candidate that no board had been searched — and the
question they asked afterwards ("don't we yet have that part implemented?")
is the whole defect, asked by the person it happened to.

Two things are wrong there and this module measures both.

**Coverage is not disclosed.** A run against a market nothing covers looks,
from the candidate's chair, exactly like a run against a market something
covers: seven jobs either way. So the disclosure has to be a rule the skill
carries, and a rule with a remedy attached — a disclosure that names no way
out is a dead end, and the two ways out already exist (build a connector for a
portal the candidate names; drive their own browser session on a source they
are logged into).

**An example is not coverage.** `examplejobs_es` is a worked instance of T32's
format, and counting it would let `connectors/` claim the Spanish market on the
strength of a site that does not exist. The rule here is the reserved-TLD one
(RFC 2606 and RFC 6761): a site under `.test`, `.example`, `.invalid` or
`.localhost` is guaranteed never to resolve, which is precisely what "this is
an example, not a board" means, and unlike a hand-kept blocklist it stays true
for the next example somebody commits.

`undisclosed_connectorless_sourcing` counts the sourcing situations in which
this tool would fetch without a connector and say nothing about it. The
situations probed are every market the installed library declares, plus the
one that is always available — a market no installed package declares at all —
so the disclosure requirement is exercised even on a day when every declared
market happens to be covered. A situation counts when it is connectorless
*and* undisclosed; a library that cannot be read at all records `-1`, never a
clean `0`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from integral.connectors import (
    DEFAULT_CONNECTORS_DIR,
    META_FILENAME,
    SEARCH_SOURCE,
    ConnectorError,
    build_search_offer,
)
from integral.offers import Offer
from integral.process_spec import Step, StepList, load_steps
from integral.step_skills import DEFAULT_SKILLS_DIR, skill_dir_name

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-16.json"
DEFAULT_STEPS_DOC = _REPO_ROOT / "status" / "spec-v2-steps.md"

#: The step whose prose carries the rule. Sourcing, by id — the number is
#: derived from the step list rather than written here, so a renumbered
#: process moves this with it.
SOURCING_STEP_ID = "sourcing"

#: Top-level domains reserved by RFC 2606 and RFC 6761 for documentation,
#: examples and testing. A connector pointing at one of these is a worked
#: example of the format; it is never a board anybody can be sourced from.
EXAMPLE_TLDS = frozenset({"test", "example", "invalid", "localhost"})

#: How a market is named in a reading when no installed package declares it.
#: Not a country code: it stands for "wherever this candidate is, if the
#: library does not reach there", which is the situation D-16 was filed from.
UNDECLARED_MARKET = "(no installed connector declares this market)"

Provenance = Literal["connector", "search", "unattributed"]


# ---------------------------------------------------------------------------
# what the library covers


@dataclass(frozen=True)
class Package:
    """One installed connector package, read for what market it serves.

    `usable` is the question this module exists to ask, and it is deliberately
    separate from "does this package pass the contract check" (T53's job): a
    package can be perfectly well-formed and still be an example.
    """

    name: str
    site: str | None
    country: str | None
    language: str | None
    usable: bool
    reason: str | None


def is_example_site(site: str | None) -> bool:
    """Is this a reserved example domain rather than a real board?"""
    if not site:
        return False
    tld = site.strip().rstrip(".").rsplit(".", 1)[-1]
    return tld.lower() in EXAMPLE_TLDS


def read_package(path: Path) -> Package:
    """Read one package's `meta.yaml` for its market, never raising.

    An unreadable package is reported as unusable with the reason attached,
    rather than skipped: a package nobody can read is not coverage either, and
    a probe that quietly dropped it would turn a broken library into a clean
    number.
    """
    meta_path = path / META_FILENAME
    if not meta_path.is_file():
        return Package(path.name, None, None, None, False, f"no {META_FILENAME}")
    try:
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return Package(path.name, None, None, None, False, f"{META_FILENAME}: {exc}")
    if not isinstance(meta, dict):
        return Package(path.name, None, None, None, False, f"{META_FILENAME} is not a mapping")

    site = meta.get("site")
    country = meta.get("country")
    language = meta.get("language")
    site = site.strip() if isinstance(site, str) else None
    country = country.strip().upper() if isinstance(country, str) else None
    language = language.strip() if isinstance(language, str) else None

    if site is None:
        return Package(path.name, None, country, language, False, f"{META_FILENAME} has no site")
    if is_example_site(site):
        return Package(
            path.name,
            site,
            country,
            language,
            False,
            f"{site} is a reserved example domain — a worked example of the format, not a board",
        )
    if country is None:
        return Package(
            path.name, site, None, language, False, f"{META_FILENAME} declares no country"
        )
    return Package(path.name, site, country, language, True, None)


def installed_packages(directory: Path = DEFAULT_CONNECTORS_DIR) -> list[Package]:
    """Every installed package, read. Raises only when the directory is gone."""
    if not directory.is_dir():
        raise ConnectorError(f"connector directory not found: {directory}")
    return [
        read_package(p)
        for p in sorted(directory.iterdir())
        if p.is_dir() and not p.name.startswith(".")
    ]


@dataclass(frozen=True)
class Coverage:
    """What the installed library offers for one market."""

    market: str
    usable: tuple[str, ...]
    example_only: tuple[str, ...]
    unreadable: tuple[str, ...]

    @property
    def covered(self) -> bool:
        """Only a usable package for this market counts. An example never does."""
        return bool(self.usable)


def assess_coverage(
    country: str | None, packages: list[Package] | None = None, *, directory: Path | None = None
) -> Coverage:
    """What covers `country` — `None` meaning a market the library never names.

    Passing `packages` reuses a library already read; `directory` reads one.
    """
    if packages is None:
        packages = installed_packages(directory or DEFAULT_CONNECTORS_DIR)
    wanted = country.strip().upper() if country else None
    market = wanted or UNDECLARED_MARKET

    def declares(package: Package) -> bool:
        # A market nobody declared is declared by nobody, by construction —
        # including by an example. `examplejobs_es` says `country: ES`, so it
        # is the reason Spain is uncovered and has nothing to do with any
        # other market; listing it under `UNDECLARED_MARKET` as well would
        # have the evidence assert a connection that does not exist.
        return wanted is not None and package.country == wanted

    return Coverage(
        market=market,
        usable=tuple(p.name for p in packages if p.usable and declares(p)),
        example_only=tuple(
            p.name for p in packages if not p.usable and is_example_site(p.site) and declares(p)
        ),
        # Not market-scoped, and deliberately: a package nobody can read
        # declares no market anyone can check, so it is a hole in *every*
        # reading rather than an absence from all of them.
        unreadable=tuple(p.name for p in packages if not p.usable and not is_example_site(p.site)),
    )


def offer_provenance(offer: Offer, sites: Iterable[str] = ()) -> Provenance:
    """Where an offer actually came from, read off the record alone.

    `sites` is the installed connectors' `site` values. Three answers, and the
    third matters as much as the first two: an offer whose source is neither
    the reserved search name nor a connector this library holds is
    `unattributed` — it may not be presented as a connector result, because
    nothing here can say a connector produced it.
    """
    if offer.source == SEARCH_SOURCE:
        return "search"
    return "connector" if offer.source in set(sites) else "unattributed"


# ---------------------------------------------------------------------------
# what the tool says about it


def disclosure(coverage: Coverage) -> str | None:
    """The sentence a connectorless run owes the candidate, or `None`.

    Returned as text rather than a boolean because the disclosure has content:
    which market, and that what follows came from a general web search. A
    caller that only needed "should I say something" can test it for `None`.
    """
    if coverage.covered:
        return None
    where = "" if coverage.market == UNDECLARED_MARKET else f" for {coverage.market}"
    return (
        f"No connector in this tool covers your market{where}, so what follows came from a "
        "general web search rather than a search of the boards you would use. I can build a "
        "connector for a board you name, or work through your own browser session on a site "
        "you are logged into."
    )


# The rule as the step spec states it. Measured, like D-15's, so that the gate
# reports `-1` rather than a clean `0` if the requirement itself is deleted:
# a check that outlives its requirement enforces a policy the project no
# longer holds, while looking like a pass.
_SPEC_RULE_RE = re.compile(r"where\s+no\s+connector\s+covers\s+the\s+candidate'?s\s+market", re.I)

# The four things the skill must carry. Each is a distinct way the fix can rot:
# the disclosure can go, either remedy can go (leaving a dead end), or the
# labelling that keeps a search result legible downstream can go.
_SKILL_ELEMENTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "states the absence rule",
        re.compile(r"no\s+connector\s+covers\s+the\s+candidate'?s\s+market,?\s+say\s+so", re.I),
    ),
    (
        "offers building a connector",
        re.compile(r"build\s+a\s+connector\s+for\s+a\s+named\s+portal", re.I),
    ),
    (
        "offers the candidate's own browser session",
        re.compile(r"the\s+candidate'?s\s+own\s+browser\s+session", re.I),
    ),
    (
        "labels a search result as one",
        re.compile(r"search\s+result\s+is\s+never\s+presented\s+as\s+a\s+connector\s+result", re.I),
    ),
)


def rule_is_declared(steps_doc: Path = DEFAULT_STEPS_DOC) -> bool:
    """Does the step spec still require the disclosure?"""
    try:
        return bool(_SPEC_RULE_RE.search(steps_doc.read_text(encoding="utf-8")))
    except OSError:
        return False


def sourcing_step(steps: StepList | None = None) -> Step | None:
    """The `sourcing` step, by id."""
    steps = steps or load_steps()
    return next((s for s in steps.steps if s.id == SOURCING_STEP_ID), None)


def skill_shortfalls(step: Step, skills_dir: Path = DEFAULT_SKILLS_DIR) -> list[str]:
    """Which of the four required elements the sourcing skill is missing."""
    skill = skills_dir / skill_dir_name(step) / "SKILL.md"
    try:
        text = skill.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{skill.name} could not be read: {exc}"]
    return [name for name, pattern in _SKILL_ELEMENTS if not pattern.search(text)]


def search_offer_shortfalls() -> list[str]:
    """Does a search-built offer still come back legible as one?

    A round trip, not a reading: `build_search_offer` is the only path a
    search hit has into the store, and the property that matters is what
    `offer_provenance` says about what it produced. Stamping the source and
    reading it back are the two halves of one guarantee, and checking only
    the first would pass a version where the reader had drifted.
    """
    try:
        offer = build_search_offer(
            text="A probe advert, built through the search path.",
            url="https://example.invalid/probe",
            source_ref="coverage-probe",
        )
    except ConnectorError as exc:
        return [f"build_search_offer refused a well-formed search result: {exc}"]
    shortfalls = []
    if offer.source != SEARCH_SOURCE:
        shortfalls.append(f"a search-built offer carries source {offer.source!r}")
    if offer_provenance(offer, (offer.source,)) != "search":
        shortfalls.append("a search-built offer reads back as a connector result")
    return shortfalls


# ---------------------------------------------------------------------------
# the measurement


def probe(
    packages: list[Package],
    *,
    undisclosed_reasons: list[str],
) -> list[dict[str, Any]]:
    """One reading per sourcing situation, in market order.

    The situations are every market the library declares plus
    `UNDECLARED_MARKET`, which is always connectorless and therefore always
    exercises the disclosure — without it, a library that happened to cover
    every market it names would let the rule rot behind a true zero.
    """
    declared = sorted({p.country for p in packages if p.country})
    readings = []
    for market in [*declared, None]:
        coverage = assess_coverage(market, packages)
        connectorless = not coverage.covered
        readings.append(
            {
                "market": coverage.market,
                "connectorless": connectorless,
                "usable": list(coverage.usable),
                "example_only": list(coverage.example_only),
                "unreadable": list(coverage.unreadable),
                "disclosed": not undisclosed_reasons,
                "discloses": disclosure(coverage),
                "counts": connectorless and bool(undisclosed_reasons),
                "reasons": list(undisclosed_reasons) if connectorless else [],
            }
        )
    return readings


def _unmeasured(reason: str, readings: list[dict[str, Any]]) -> dict[str, Any]:
    """The shape a reading that could not happen takes: `-1`, never `0`."""
    return {
        "undisclosed_connectorless_sourcing": -1,
        "situations_probed": len(readings),
        "connectors_installed": 0,
        "connectors_usable": 0,
        "rule_declared_in_step_spec": False,
        "shortfalls": [reason],
        "readings": readings,
    }


def measure(
    directory: Path = DEFAULT_CONNECTORS_DIR,
    skills_dir: Path = DEFAULT_SKILLS_DIR,
    steps_doc: Path = DEFAULT_STEPS_DOC,
    steps_path: Path | None = None,
) -> dict[str, Any]:
    """D-16's gate reading: `undisclosed_connectorless_sourcing`."""
    try:
        packages = installed_packages(directory)
    except ConnectorError as exc:
        return _unmeasured(str(exc), [])
    if not packages:
        # Not zero: with no library at all there is no market to probe, and a
        # `0` here would say "every connectorless run discloses" on the
        # strength of having looked at nothing.
        return _unmeasured(f"no connector packages under {directory} — nothing was probed", [])

    if not rule_is_declared(steps_doc):
        return _unmeasured(
            f"{steps_doc.name} no longer requires a disclosure where no connector covers the "
            "candidate's market, so this gate is not measuring what D-16 names",
            [],
        )

    try:
        steps = load_steps() if steps_path is None else load_steps(steps_path)
    except Exception as exc:  # a load failure is evidence to report, not a crash
        return _unmeasured(f"step list could not be loaded: {exc}", [])
    step = sourcing_step(steps)
    if step is None:
        return _unmeasured(f"the step list names no {SOURCING_STEP_ID!r} step", [])

    reasons = [*skill_shortfalls(step, skills_dir), *search_offer_shortfalls()]
    readings = probe(packages, undisclosed_reasons=reasons)
    return {
        "undisclosed_connectorless_sourcing": sum(1 for r in readings if r["counts"]),
        "situations_probed": len(readings),
        "connectors_installed": len(packages),
        "connectors_usable": sum(1 for p in packages if p.usable),
        "rule_declared_in_step_spec": True,
        "shortfalls": reasons,
        "readings": readings,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    directory: Path = DEFAULT_CONNECTORS_DIR,
    skills_dir: Path = DEFAULT_SKILLS_DIR,
    steps_doc: Path = DEFAULT_STEPS_DOC,
) -> dict[str, Any]:
    """Measure and record `status/evidence/D-16.json`."""
    measured = measure(directory, skills_dir, steps_doc)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.connector_coverage [--country ES] [--check]`.

    Without arguments it writes the evidence file, so `make evidence` — whose
    module list is derived from `^def _main` — regenerates D-16's number with
    no flag to remember. `--country` answers the question the skill asks at
    the top of a run: is there a connector for this candidate's market, and if
    not, what should be said.
    """
    parser = argparse.ArgumentParser(description="D-16's gate over connector coverage disclosure")
    parser.add_argument(
        "--country",
        metavar="CC",
        help="report coverage for one market (ISO country code) and the disclosure it owes",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence file",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/D-16.json)",
    )
    parser.add_argument(
        "--connectors-dir",
        default=str(DEFAULT_CONNECTORS_DIR),
        metavar="DIR",
        help="connector library to read (default: connectors)",
    )
    args = parser.parse_args(argv[1:])
    directory = Path(args.connectors_dir)

    if args.country is not None:
        try:
            coverage = assess_coverage(args.country, directory=directory)
        except ConnectorError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        say = disclosure(coverage)
        print(
            json.dumps(
                {
                    "market": coverage.market,
                    "covered": coverage.covered,
                    "usable": list(coverage.usable),
                    "example_only": list(coverage.example_only),
                    "disclosure": say,
                },
                ensure_ascii=False,
            )
        )
        # 1, not 0: a connectorless market is a finding the caller must act on
        # — it is what the skill has to say out loud before showing anything.
        return 0 if say is None else 1

    if args.check:
        measured = measure(directory)
    else:
        measured = write_evidence(Path(args.write_evidence), directory)

    print(json.dumps(measured, ensure_ascii=False))
    for shortfall in measured["shortfalls"]:
        print(shortfall, file=sys.stderr)
    if measured["undisclosed_connectorless_sourcing"] == -1:
        return 3
    return 1 if measured["undisclosed_connectorless_sourcing"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
