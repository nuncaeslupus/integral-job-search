"""T54 — the connector exchange: discovery, installation, and consent.

Everything here is offline. The sources repository is served by
`directory_fetcher` out of `tests/fixtures/exchange/manifest.json` and the
committed `connectors/examplejobs_es/` package, so no test needs a network, an
account, or a sources repository that exists yet.

The candidate is invented and lives in a `tmp_path` home: T54's central claim is
that the contribution path never reads anything of theirs, and a claim like that
is only worth testing when there is something there to read.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from integral.connector_exchange import (
    DEFAULT_MANIFEST_FIXTURE,
    DEFAULT_PACKAGES_DIR,
    EXCHANGE_DIRNAME,
    MANIFEST_URL,
    SUBMISSION_NOTE,
    Approval,
    Disclosure,
    ExchangeError,
    Fetch,
    _main,
    approve,
    audit,
    bundle_files,
    contribute,
    decline,
    directory_fetcher,
    disclose,
    find,
    foreign_reads,
    install,
    may_offer,
    measure,
    read_manifest,
    records,
    write_evidence,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REFERENCE = _REPO_ROOT / "connectors" / "examplejobs_es"
_USER = "@fixture-user"

# Invented, and obviously so. Nothing about a real person goes anywhere near a
# test that exists to prove nothing about a person goes anywhere.
_CANDIDATE_SECRET = "Fixture Candidate, looking for work in Madrid"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """An `$INTEGRAL_HOME` with a fixture candidate already in it."""
    root = tmp_path / "home"
    profile = root / "profiles" / "fixture-candidate"
    profile.mkdir(parents=True)
    (profile / "master.json").write_text(json.dumps({"name": _CANDIDATE_SECRET}), encoding="utf-8")
    (profile / "stories.jsonl").write_text(
        json.dumps({"episode": _CANDIDATE_SECRET}) + "\n", encoding="utf-8"
    )
    return root


@pytest.fixture
def fetch() -> Fetch:
    """The published sources repository, served from what this repo committed."""
    return directory_fetcher(DEFAULT_MANIFEST_FIXTURE, DEFAULT_PACKAGES_DIR)


@pytest.fixture
def installed(home: Path, fetch: Fetch) -> Path:
    entry = read_manifest(fetch)[0]
    return install(entry, fetch, home=home).package


def _sources(tmp_path: Path, mutate: Callable[[str], str] | None = None) -> Fetch:
    """A private copy of the sources repository a test may break.

    `mutate` is applied to the copied `connector.yaml` text — the shape
    `test_connector_contract.py` uses: break the real package, so the failure is
    the one the test asked for and not an artefact of a hand-built look-alike.
    """
    root = tmp_path / "sources"
    package = root / "examplejobs_es"
    shutil.copytree(_REFERENCE, package)
    manifest = json.loads(DEFAULT_MANIFEST_FIXTURE.read_text(encoding="utf-8"))
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if mutate is not None:
        path = package / "connector.yaml"
        path.write_text(mutate(path.read_text(encoding="utf-8")), encoding="utf-8")
    return directory_fetcher(root / "manifest.json", root)


# ---------------------------------------------------------------------------
# coming in


def test_the_manifest_is_read_with_its_provenance(fetch: Fetch) -> None:
    entries = read_manifest(fetch)
    entry = find(entries, "examplejobs.test")
    assert entry is not None
    assert find(entries, "nowhere.test") is None
    # Who contributed it and when it was last verified — §6's whole offer.
    assert entry.contributor in entry.provenance
    assert entry.last_verified in entry.provenance


def test_the_exchange_reads_only_what_the_sources_repository_publishes(fetch: Fetch) -> None:
    assert json.loads(fetch(MANIFEST_URL))["manifest_version"] == 1
    with pytest.raises(ExchangeError):
        fetch("https://elsewhere.test/manifest.json")


def test_an_installed_connector_runs_its_fixture_before_first_use(
    home: Path, tmp_path: Path, fetch: Fetch
) -> None:
    """The fixture test is part of installing, not a step a caller may skip."""
    entry = read_manifest(fetch)[0]

    good = install(entry, fetch, home=home)
    assert good.violations == ()
    assert good.connector is not None
    assert good.verified
    assert good.package == home / "connectors" / "examplejobs_es"

    # A stale connector — one whose selectors no longer match the markup — fails
    # here, and there is no usable `Connector` to be had from it.
    stale = tmp_path / "stale-home"
    broken = install(
        entry,
        _sources(tmp_path, lambda text: text.replace('item: ".job-card"', 'item: ".gone"')),
        home=stale,
    )
    assert broken.connector is None
    assert not broken.verified
    assert any("rule 2" in violation for violation in broken.violations)

    # Installed anyway: repairing it is the same work as writing one, and the
    # verdict is on disk for the measurement to read back.
    assert (broken.package / "connector.yaml").is_file()
    recorded = records(stale / EXCHANGE_DIRNAME / "installs.jsonl")
    assert [r["package"] for r in recorded] == ["examplejobs_es"]
    assert recorded[0]["violations"] == list(broken.violations)


def test_installing_never_writes_into_the_clone(home: Path, installed: Path) -> None:
    assert installed.is_relative_to(home)
    assert not installed.is_relative_to(_REPO_ROOT)


# ---------------------------------------------------------------------------
# going out


def test_the_disclosure_lists_every_file_that_would_be_sent(home: Path, installed: Path) -> None:
    offer = disclose(installed, github_username=_USER)

    on_disk = {str(p.relative_to(installed)) for p in installed.rglob("*") if p.is_file()}
    assert set(offer.files) == on_disk
    assert on_disk >= {"connector.yaml", "meta.yaml", "fixture/list.html"}

    for name in offer.files:
        assert name in offer.text
    assert _USER in offer.text
    assert "public" in offer.text
    assert "Nothing about you, your profile or your search is included" in offer.text
    assert "Declining costs you nothing" in offer.text

    # And what is actually assembled is exactly what was named — no more.
    contribute(offer, _yes(offer), home=home)
    bundle = home / "outbox" / installed.name
    sent = {str(p.relative_to(bundle)) for p in bundle.rglob("*") if p.is_file()}
    assert sent - {SUBMISSION_NOTE} == set(offer.files)


def test_nothing_leaves_the_machine_without_an_explicit_yes(home: Path, installed: Path) -> None:
    offer = disclose(installed, github_username=_USER)

    # Every answer that is not a yes produces no approval at all — so there is
    # nothing a caller could pass to `contribute`.
    for answer in ("no", "", "  ", "maybe", "not now", "sure, whatever", "yes please"):
        assert approve(offer, answer) is None
    assert approve(offer, "yes") is not None
    assert approve(offer, " Y ") is not None

    with pytest.raises(ExchangeError):
        contribute(offer, None, home=home)  # type: ignore[arg-type]

    # An approval for a *different* disclosure is not an approval for this one.
    other = disclose(installed, github_username="@somebody-else")
    with pytest.raises(ExchangeError):
        contribute(offer, _yes(other), home=home)

    assert records(home / EXCHANGE_DIRNAME / "contributions.jsonl") == []
    assert not (home / "outbox").exists()

    record = contribute(offer, _yes(offer), home=home)
    assert record["approval"]["answer"] == "yes"
    assert (home / "outbox" / installed.name / SUBMISSION_NOTE).is_file()


def test_declining_leaves_the_connector_installed_and_is_not_asked_again(
    home: Path, installed: Path
) -> None:
    offer = disclose(installed, github_username=_USER)
    assert may_offer(offer.package_name, home=home)

    decline(offer, home=home)

    assert not may_offer(offer.package_name, home=home)
    # Installed and working, exactly as before.
    assert bundle_files(installed) == offer.files
    assert (installed / "connector.yaml").read_text(encoding="utf-8")
    # Not a fallback: even a later yes cannot reopen it.
    with pytest.raises(ExchangeError):
        contribute(offer, _yes(offer), home=home)
    assert records(home / EXCHANGE_DIRNAME / "contributions.jsonl") == []
    assert not (home / "outbox").exists()


def test_no_profile_path_is_read_by_the_contribution_path(home: Path, installed: Path) -> None:
    """The bundle cannot carry candidate data because it never reads any."""
    offer = disclose(installed, github_username=_USER)
    record = contribute(offer, _yes(offer), home=home)

    package = Path(record["source_package"])
    assert record["paths_read"]
    for raw in record["paths_read"]:
        assert Path(raw).is_relative_to(package)
        assert not Path(raw).is_relative_to(home / "profiles")

    bundle = home / "outbox" / installed.name
    for path in bundle.rglob("*"):
        if path.is_file():
            assert _CANDIDATE_SECRET not in path.read_text(encoding="utf-8")

    # And the same conclusion reached the way the gate reaches it: from disk.
    assert foreign_reads(home) == []
    assert measure(home)["foreign_path_reads"] == 0


def test_the_submission_is_prepared_and_not_sent(home: Path, installed: Path) -> None:
    offer = disclose(installed, github_username=_USER)
    record = contribute(offer, _yes(offer), home=home)
    assert record["submission"][:3] == ["gh", "pr", "create"]
    note = (home / "outbox" / installed.name / SUBMISSION_NOTE).read_text(encoding="utf-8")
    assert "has not been sent" in note


# ---------------------------------------------------------------------------
# the gate, and its teeth


def test_a_contribution_no_approval_backs_is_counted_and_named(home: Path, installed: Path) -> None:
    """The gate can fail. Plant records nothing consented to and watch it."""
    offer = disclose(installed, github_username=_USER)
    contribute(offer, _yes(offer), home=home)
    assert measure(home)["unconsented_contributions"] == 0

    ledger = home / EXCHANGE_DIRNAME / "contributions.jsonl"
    honest = records(ledger)[0]
    planted = [
        {**honest, "package": "smuggled_es", "approval": None},
        {**honest, "package": "stale_approval_es", "files": [*honest["files"], "extra.txt"]},
        {
            **honest,
            "package": "answered_no_es",
            "approval": {**honest["approval"], "answer": "no"},
        },
    ]
    with ledger.open("a", encoding="utf-8") as handle:
        for record in planted:
            handle.write(json.dumps(record) + "\n")

    named = audit(home)
    assert len(named) == 3
    assert "smuggled_es: recorded with no approval" in named
    assert "stale_approval_es: the approval answers a different disclosure" in named
    assert "answered_no_es: the approval records no explicit yes" in named

    measured = measure(home)
    assert measured["unconsented_contributions"] == 3
    assert measured["unconsented"] == named


def test_a_read_outside_the_package_is_counted_and_named(home: Path, installed: Path) -> None:
    offer = disclose(installed, github_username=_USER)
    contribute(offer, _yes(offer), home=home)
    ledger = home / EXCHANGE_DIRNAME / "contributions.jsonl"
    record = records(ledger)[0]
    smuggled = str(home / "profiles" / "fixture-candidate" / "master.json")
    record["paths_read"] = [*record["paths_read"], smuggled]
    ledger.write_text(json.dumps(record) + "\n", encoding="utf-8")

    assert foreign_reads(home) == [
        f"{installed.name}: read {smuggled} outside its connector package"
    ]
    assert measure(home)["foreign_path_reads"] == 1


def test_nothing_contributed_is_unmeasured_not_a_passing_zero(home: Path) -> None:
    """D-2: a score is a number, a failure, or `None` — never 0 over 0 attempts."""
    measured = measure(home)
    assert measured["contributions_recorded"] == 0
    assert measured["unconsented_contributions"] is None
    assert measured["unmeasured_reason"]


def test_the_evidence_the_gate_reads_is_what_the_probe_wrote(tmp_path: Path) -> None:
    evidence = tmp_path / "T54.json"
    measured = write_evidence(evidence)
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured
    assert measured["unconsented_contributions"] == 0
    assert measured["contributions_recorded"] == 1
    assert measured["contributions_declined"] == 1
    assert measured["installs_checked_before_use"] == 1
    assert measured["foreign_path_reads"] == 0
    assert _main(["connector_exchange", str(evidence)]) == 0


def test_the_committed_evidence_is_current() -> None:
    from integral.connector_exchange import DEFAULT_EVIDENCE_PATH

    committed = json.loads(DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert committed["unconsented_contributions"] == 0


def _yes(offer: Disclosure) -> Approval:
    approval = approve(offer, "yes")
    assert approval is not None
    return approval
