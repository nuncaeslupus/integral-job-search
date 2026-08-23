"""T54 — the connector exchange: discovery, installation, and consent.

Everything here is offline. The sources repository is served by
`directory_fetcher` out of `tests/fixtures/exchange/manifest.json` and the
committed `connectors/examplejobs_es/` package, so no test needs a network, an
account, or a sources repository that exists yet.

The candidate is invented and lives in a `tmp_path` home: T54's central claim is
that the contribution path never reads anything of theirs, and a claim like that
is only worth testing when there is something there to read.

The block marked *adversarial review* is the one that matters. Each test there
fails against the code as it stood before the review — a manifest escaping the
home, a yes replayed against a look-alike disclosure, a hand-built refusal, and
one approval spent twice.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from integral.connector_exchange import (
    DEFAULT_EVIDENCE_PATH,
    DEFAULT_MANIFEST_FIXTURE,
    DEFAULT_PACKAGES_DIR,
    EXCHANGE_DIRNAME,
    MANIFEST_URL,
    SUBMISSION_NOTE,
    Approval,
    Disclosure,
    ExchangeError,
    Fetch,
    ManifestEntry,
    _main,
    approve,
    audit,
    bundle_files,
    candidate_data_in_output,
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
    unverified_connectors_offered,
    usable_connectors,
    verdict,
    write_evidence,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REFERENCE = _REPO_ROOT / "connectors" / "examplejobs_es"
_USER = "@fixture-user"

# Invented, and obviously so. Nothing about a real person goes anywhere near a
# test that exists to prove nothing about a person goes anywhere.
_CANDIDATE_SECRET = "Fixture Candidate, looking for work in an invented city"


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


def _yes(offer: Disclosure) -> Approval:
    approval = approve(offer, "yes")
    assert approval is not None
    return approval


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


def test_the_bulk_loader_rejects_what_failed_its_fixture(tmp_path: Path) -> None:
    """F7: the invariant lives in the loader, not in one function's return type."""
    home = tmp_path / "home"
    stale = _sources(tmp_path, lambda text: text.replace('item: ".job-card"', 'item: ".gone"'))
    install(read_manifest(stale)[0], stale, home=home)
    usable, rejected = usable_connectors(home)
    assert usable == {}
    assert rejected == ["examplejobs_es"]
    # And nothing the loader did return fails a check run fresh from disk.
    assert unverified_connectors_offered(home) == []


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

    library = (home / "connectors").resolve()
    assert record["paths_read"]
    for raw in record["paths_read"]:
        assert Path(raw).is_relative_to(library)
        assert not Path(raw).is_relative_to(home / "profiles")

    bundle = home / "outbox" / installed.name
    for path in bundle.rglob("*"):
        if path.is_file():
            assert _CANDIDATE_SECRET not in path.read_text(encoding="utf-8")

    # And the same conclusion reached the way the gate reaches it: from disk,
    # and — for the leak check — without consulting anything the writer said.
    assert foreign_reads(home) == []
    assert candidate_data_in_output(home) == []
    measured = measure(home)
    assert measured["foreign_path_reads"] == 0
    assert measured["candidate_data_in_output"] == 0


def test_the_submission_is_prepared_and_not_sent(home: Path, installed: Path) -> None:
    offer = disclose(installed, github_username=_USER)
    record = contribute(offer, _yes(offer), home=home)
    assert record["submission"][:3] == ["gh", "pr", "create"]
    note = (home / "outbox" / installed.name / SUBMISSION_NOTE).read_text(encoding="utf-8")
    assert "has not been sent" in note


# ---------------------------------------------------------------------------
# adversarial review — each of these fails against the code before the review


def test_f5_a_manifest_cannot_name_a_package_outside_the_home(
    home: Path, tmp_path: Path, fetch: Fetch
) -> None:
    """The manifest is unauthenticated, so every name in it is untrusted input."""
    entry = read_manifest(fetch)[0]
    victim = tmp_path / "victim"
    victim.mkdir()

    for hostile in ("../../victim/pwned", "..", "/etc/pwned", "a/b", "Escaped"):
        with pytest.raises(ExchangeError):
            install(
                ManifestEntry(
                    package=hostile,
                    site=entry.site,
                    country=entry.country,
                    language=entry.language,
                    contributor=entry.contributor,
                    last_verified=entry.last_verified,
                    files=entry.files,
                ),
                fetch,
                home=home,
            )
    assert list(victim.iterdir()) == []
    assert not (home / "connectors").exists() or list((home / "connectors").iterdir()) == []


def test_f5_a_bundle_cannot_be_written_outside_the_outbox(home: Path, installed: Path) -> None:
    """The same escape by the other door: a `Disclosure` naming its own package."""
    offer = disclose(installed, github_username=_USER)
    with pytest.raises(ExchangeError):
        Disclosure(
            package=offer.package,
            package_name="../../escaped",
            site=offer.site,
            github_username=offer.github_username,
            files=offer.files,
            content_digest=offer.content_digest,
        )


def test_f1_a_yes_cannot_be_replayed_against_a_look_alike_directory(
    home: Path, installed: Path, tmp_path: Path
) -> None:
    """A digest over file *names* makes any directory with those names the same offer."""
    impostor = tmp_path / "impostor"
    shutil.copytree(installed, impostor)
    # Same package name, same site, same file names — different bytes, and above
    # all a different directory. It must not be the same contribution.
    (impostor / "meta.yaml").write_text(
        (impostor / "meta.yaml").read_text(encoding="utf-8") + f"\n# {_CANDIDATE_SECRET}\n",
        encoding="utf-8",
    )

    real = disclose(installed, github_username=_USER)
    fake = Disclosure(
        package=impostor,
        package_name=real.package_name,
        site=real.site,
        github_username=real.github_username,
        files=real.files,
        content_digest=real.content_digest,
    )
    assert fake.digest != real.digest

    with pytest.raises(ExchangeError):
        contribute(fake, _yes(real), home=home)
    assert records(home / EXCHANGE_DIRNAME / "contributions.jsonl") == []
    assert candidate_data_in_output(home) == []


def test_f1_files_edited_after_the_yes_are_refused(home: Path, installed: Path) -> None:
    offer = disclose(installed, github_username=_USER)
    consent = _yes(offer)
    (installed / "meta.yaml").write_text(
        (installed / "meta.yaml").read_text(encoding="utf-8") + "\n# edited after the yes\n",
        encoding="utf-8",
    )
    with pytest.raises(ExchangeError, match="changed after"):
        contribute(offer, consent, home=home)
    assert records(home / EXCHANGE_DIRNAME / "contributions.jsonl") == []


def test_f3_no_approval_object_can_say_anything_but_yes(home: Path, installed: Path) -> None:
    """`approve` being the only constructor was a docstring; now it is enforced."""
    offer = disclose(installed, github_username=_USER)
    for answer in ("no", "", "maybe", "NOPE"):
        with pytest.raises(ExchangeError):
            Approval(disclosure_digest=offer.digest, answer=answer, at="2026-01-01T00:00:00+00:00")
    assert records(home / EXCHANGE_DIRNAME / "contributions.jsonl") == []
    assert not (home / "outbox").exists()


def test_f4_one_yes_buys_exactly_one_contribution(home: Path, installed: Path) -> None:
    offer = disclose(installed, github_username=_USER)
    consent = _yes(offer)
    contribute(offer, consent, home=home)
    for _ in range(4):
        with pytest.raises(ExchangeError, match="already been used"):
            contribute(offer, consent, home=home)
    assert len(records(home / EXCHANGE_DIRNAME / "contributions.jsonl")) == 1
    # And a ledger carrying the replay anyway is named by the audit.
    assert measure(home)["unconsented_contributions"] == 0


def test_f1b_the_leak_check_does_not_consult_what_the_writer_reported(
    home: Path, installed: Path
) -> None:
    """F1b/F2: the checks are anchored on the home, not on the record's own fields.

    A record that lies about where it read — the shape a mutant would write —
    is caught because `foreign_reads` measures against
    `$INTEGRAL_HOME/connectors/`, and a bundle carrying the candidate's text is
    caught without reading `paths_read` at all.
    """
    offer = disclose(installed, github_username=_USER)
    contribute(offer, _yes(offer), home=home)
    ledger = home / EXCHANGE_DIRNAME / "contributions.jsonl"
    record = records(ledger)[0]

    smuggled = str(home / "profiles" / "fixture-candidate" / "master.json")
    record["paths_read"] = [*record["paths_read"], smuggled]
    # A record that also rewrites `source_package` to cover its tracks: the old
    # check compared the paths against exactly this field and saw nothing.
    record["source_package"] = str(home)
    ledger.write_text(json.dumps(record) + "\n", encoding="utf-8")

    assert foreign_reads(home) == [
        f"{installed.name}: read {smuggled} outside the installed library"
    ]
    assert measure(home)["foreign_path_reads"] == 1

    # And the independent witness: profile text in a bundle, with nothing in the
    # record admitting to it.
    (home / "outbox" / installed.name / "meta.yaml").write_text(
        f"site: examplejobs.test\n# {_CANDIDATE_SECRET}\n", encoding="utf-8"
    )
    leaks = candidate_data_in_output(home)
    assert leaks == [f"candidate text appears in outbox/{installed.name}/meta.yaml"]
    # The finding names where, never what.
    assert _CANDIDATE_SECRET not in " ".join(leaks)
    assert measure(home)["candidate_data_in_output"] == 1


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
        # A byte-identical duplicate: the shape a replayed yes actually leaves.
        dict(honest),
    ]
    with ledger.open("a", encoding="utf-8") as handle:
        for record in planted:
            handle.write(json.dumps(record) + "\n")

    named = audit(home)
    assert len(named) == 4
    assert "smuggled_es: recorded with no approval" in named
    assert "stale_approval_es: the approval answers a different disclosure" in named
    assert "answered_no_es: the approval records no explicit yes" in named
    assert f"{installed.name}: the approval was already spent on an earlier contribution" in named

    measured = measure(home)
    assert measured["unconsented_contributions"] == 4
    assert measured["unconsented"] == named


def test_every_refusal_enters_the_denominator(home: Path, installed: Path) -> None:
    """A refusal that left no trace would make a run that never tried look clean."""
    offer = disclose(installed, github_username=_USER)
    decline(offer, home=home)
    with pytest.raises(ExchangeError):
        contribute(offer, _yes(offer), home=home)

    measured = measure(home)
    assert measured["contributions_recorded"] == 0
    assert measured["contributions_refused"] == 1
    assert measured["contribution_attempts"] == 1
    # Attempted and stopped is a measurement; it is not "nothing happened".
    assert measured["unconsented_contributions"] == 0
    assert measured["unmeasured_reason"] is None


def test_nothing_attempted_is_unmeasured_not_a_passing_zero(home: Path) -> None:
    """D-2: a score is a number, a failure, or `None` — never 0 over 0 attempts."""
    measured = measure(home)
    assert measured["contribution_attempts"] == 0
    assert measured["unconsented_contributions"] is None
    assert measured["unmeasured_reason"]


def test_the_evidence_the_gate_reads_is_what_the_probe_wrote(tmp_path: Path) -> None:
    evidence = tmp_path / "T54.json"
    measured = write_evidence(evidence)
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured
    assert measured["unconsented_contributions"] == 0
    # The probe drives the paths that must fail as well as the one that must
    # work, so the denominator is a measurement rather than a constant.
    assert measured["contributions_recorded"] == 1
    assert measured["contributions_refused"] == 3
    assert measured["contribution_attempts"] == 4
    assert measured["contributions_declined"] == 1
    assert measured["installs_recorded"] == 2
    assert measured["connectors_rejected_unverified"] == 1
    assert measured["foreign_path_reads"] == 0
    assert measured["candidate_data_in_output"] == 0
    assert measured["unverified_connectors_offered"] == 0
    assert _main(["connector_exchange", str(evidence)]) == 0


def test_every_defect_the_run_prints_is_one_it_fails_on(home: Path, installed: Path) -> None:
    """F6: a gate that prints a finding and exits 0 is not a gate.

    `_main` prints `defects` and `verdict` reads `defects`, so there is one
    list and no room for a fourth category to be reported and ignored.
    """
    offer = disclose(installed, github_username=_USER)
    contribute(offer, _yes(offer), home=home)
    clean = measure(home)
    assert clean["defects"] == []
    assert verdict(clean) == 0

    for key in ("unconsented", "foreign_reads", "leaks", "unverified_offered"):
        poisoned = {**clean, key: ["a planted finding"]}
        poisoned["defects"] = [
            *poisoned["unconsented"],
            *poisoned["foreign_reads"],
            *poisoned["leaks"],
            *poisoned["unverified_offered"],
        ]
        assert verdict(poisoned) == 1, key

    # And the concatenation itself is what `measure` publishes, not a rule the
    # test restates: plant a real leak and read it back off the same key.
    (home / "outbox" / installed.name / "meta.yaml").write_text(
        f"site: examplejobs.test\n# {_CANDIDATE_SECRET}\n", encoding="utf-8"
    )
    live = measure(home)
    assert live["defects"] == live["leaks"] != []
    assert verdict(live) == 1

    assert verdict({**clean, "unconsented_contributions": None}) == 3


def test_the_committed_evidence_is_current() -> None:
    committed = json.loads(DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert committed["unconsented_contributions"] == 0
    assert committed["contribution_attempts"] > 1
