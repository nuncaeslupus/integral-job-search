"""T45 — per-advert generation: every claim traces to a store entry.

The gate this suite carries is the one the spec calls the single worst thing
this project could ship if it fails. So the tests are built so that the metric
can be *wrong*: `test_the_traceability_check_would_notice_an_invented_claim`
plants a line no store entry backs and requires the fraction to drop. A gate
that cannot fail is not a gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.cv_store import CVMaster, Experience, Skill, SourcedText, write_master
from integral.generate import (
    GENERATION_CAP,
    GenerationError,
    generate,
    read_manifest,
    traceability,
)
from integral.identity import ProfileStore, create_profile


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


@pytest.fixture
def master(store: ProfileStore) -> CVMaster:
    built = CVMaster(
        experience=(
            Experience(
                title="Data migration lead",
                organisation="Cintra Logistics",
                start="2021",
                end="2025",
                description="Moved the billing system off the mainframe.",
            ),
        ),
        skills=(Skill(name="PostgreSQL", level="strong"), Skill(name="Catalan payroll law")),
    )
    write_master(store, built)
    return built


ADVERT = (
    "We are hiring a data engineer in Girona. You will own a PostgreSQL estate "
    "and lead a migration off legacy systems. Kubernetes experience required."
)


def test_every_claim_traces_to_a_store_entry(store: ProfileStore, master: CVMaster) -> None:
    """The gate itself: measured over the manifest, against the store."""
    generate(store, master, offer_id="girona-1", advert=ADVERT, asks=("PostgreSQL", "Kubernetes"))
    measured = traceability(store, master, "girona-1", version=1)
    assert measured["cv_generation_traceability"] == 1.0
    assert measured["claims_total"] > 0
    assert measured["claims_untraced"] == []


def test_the_traceability_check_would_notice_an_invented_claim(
    store: ProfileStore, master: CVMaster
) -> None:
    """The metric must be able to fail, or it is decoration.

    A line is appended to the finished CV that no manifest row backs — exactly
    what a model that free-wrote one extra sentence would produce.
    """
    generate(store, master, offer_id="girona-1", advert=ADVERT, asks=("PostgreSQL",))
    cv = store.path("cv", "generated", "girona-1", "v1", "cv.md")
    cv.write_text(cv.read_text() + "Ten years of Kubernetes in production.\n", encoding="utf-8")

    measured = traceability(store, master, "girona-1", version=1)
    assert measured["cv_generation_traceability"] < 1.0
    assert measured["claims_untraced"] == ["cv.md: Ten years of Kubernetes in production."]


def test_regeneration_writes_a_new_version(store: ProfileStore, master: CVMaster) -> None:
    """`v1` survives byte-identical after `v2` is written."""
    generate(store, master, offer_id="girona-1", advert=ADVERT, asks=("PostgreSQL",))
    v1 = store.path("cv", "generated", "girona-1", "v1")
    before = {p.name: p.read_bytes() for p in sorted(v1.iterdir())}

    generate(store, master, offer_id="girona-1", advert=ADVERT, asks=("PostgreSQL", "migration"))
    assert store.path("cv", "generated", "girona-1", "v2").is_dir()
    after = {p.name: p.read_bytes() for p in sorted(v1.iterdir())}
    assert after == before, "an earlier version may already be with an employer"


def test_a_fourth_version_is_refused(store: ProfileStore, master: CVMaster) -> None:
    """Hard cap: three rounds, then the useful move is to talk about what is wrong."""
    for _ in range(GENERATION_CAP):
        generate(store, master, offer_id="girona-1", advert=ADVERT, asks=("PostgreSQL",))
    with pytest.raises(GenerationError, match="three"):
        generate(store, master, offer_id="girona-1", advert=ADVERT, asks=("PostgreSQL",))


def test_advert_wording_is_mirrored_only_over_held_ground(
    store: ProfileStore, master: CVMaster
) -> None:
    """A required skill the store does not hold never appears in the draft."""
    generate(store, master, offer_id="girona-1", advert=ADVERT, asks=("PostgreSQL", "Kubernetes"))
    written = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(store.path("cv", "generated", "girona-1", "v1").iterdir())
        if p.suffix == ".md"
    )
    assert "PostgreSQL" in written, "held ground is mirrored in the advert's own word"
    assert "Kubernetes" not in written, "borrowing a phrase you cannot hold is a lie"

    manifest = read_manifest(store, "girona-1", version=1)
    assert "Kubernetes" in manifest.gaps, "the gap is named, not hidden"


def test_an_unheld_ask_is_never_smuggled_into_the_manifest(
    store: ProfileStore, master: CVMaster
) -> None:
    """The gap list is a report to the candidate, not a claim in the document."""
    generate(store, master, offer_id="girona-1", advert=ADVERT, asks=("Kubernetes",))
    manifest = read_manifest(store, "girona-1", version=1)
    assert all("Kubernetes" not in claim.text for claim in manifest.claims)


def test_a_duplicated_claim_line_is_not_free(store: ProfileStore, master: CVMaster) -> None:
    """One manifest row backs one line — CodeRabbit on #126.

    A set-membership check passed a second copy of a true sentence: the total
    rose and membership still succeeded, so an extra line was invisible. An
    extra line is exactly what an over-eager draft produces.
    """
    generate(store, master, offer_id="girona-1", advert=ADVERT, asks=("PostgreSQL",))
    cv = store.path("cv", "generated", "girona-1", "v1", "cv.md")
    duplicated = next(
        line for line in cv.read_text(encoding="utf-8").splitlines() if "Cintra" in line
    )
    cv.write_text(cv.read_text(encoding="utf-8") + duplicated + "\n", encoding="utf-8")

    measured = traceability(store, master, "girona-1", version=1)
    assert measured["cv_generation_traceability"] < 1.0
    assert measured["claims_untraced"] == [f"cv.md: {duplicated}"]


def test_a_headline_is_a_claim_and_not_a_heading(store: ProfileStore) -> None:
    """Candidate-written prose is a claim whatever it is typeset as.

    Excluding every `#` line exempted the headline from measurement, so anything
    typed after a `#` inherited that invisibility.
    """
    built = CVMaster(
        headline=SourcedText(text="Backend engineer — data platforms"),
        skills=(Skill(name="PostgreSQL", level="strong"),),
    )
    write_master(store, built)
    generate(store, built, offer_id="girona-1", advert=ADVERT, asks=("PostgreSQL",))
    assert traceability(store, built, "girona-1", version=1)["cv_generation_traceability"] == 1.0

    cv = store.path("cv", "generated", "girona-1", "v1", "cv.md")
    cv.write_text(
        cv.read_text(encoding="utf-8") + "# Ten years of Kubernetes in production.\n",
        encoding="utf-8",
    )
    measured = traceability(store, built, "girona-1", version=1)
    assert measured["claims_untraced"] == ["cv.md: # Ten years of Kubernetes in production."]


def test_an_ask_is_held_only_as_a_whole_term(store: ProfileStore) -> None:
    """`"Java" in "JavaScript"` is true and means the opposite of what it is for.

    A substring test let a store holding JavaScript answer an advert asking for
    Java, so the gap went unnamed and the candidate was never told.
    """
    built = CVMaster(skills=(Skill(name="JavaScript", level="strong"),))
    write_master(store, built)
    generate(store, built, offer_id="girona-1", advert="We need Java.", asks=("Java",))

    manifest = read_manifest(store, "girona-1", version=1)
    assert "Java" in manifest.gaps, "a gap the store cannot hold must be named"
    assert all("JavaScript" not in claim.text for claim in manifest.claims)


def test_a_version_directory_is_reserved_before_anything_is_written(
    store: ProfileStore, master: CVMaster, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Allocation is a compare-and-swap, so a second writer is refused, not merged."""
    generate(store, master, offer_id="girona-1", advert=ADVERT, asks=("PostgreSQL",))
    first = store.path("cv", "generated", "girona-1", "v1", "cv.md").read_bytes()

    # The real race: a second caller that read the directory before the first
    # wrote, so it still believes v1 is free. Pinning `next_version` is how that
    # window is reproduced without two processes.
    monkeypatch.setattr("integral.generate.next_version", lambda store, offer_id: 1)
    with pytest.raises(GenerationError, match="already exists"):
        generate(store, master, offer_id="girona-1", advert=ADVERT, asks=("Python",))
    assert store.path("cv", "generated", "girona-1", "v1", "cv.md").read_bytes() == first


def test_a_document_with_no_claims_does_not_score_one(store: ProfileStore) -> None:
    """An empty store generates nothing, and nothing is not a gate that passed."""
    built = CVMaster()
    write_master(store, built)
    generate(store, built, offer_id="girona-1", advert=ADVERT, asks=("PostgreSQL",))
    measured = traceability(store, built, "girona-1", version=1)
    assert measured["claims_total"] == 0
    assert measured["cv_generation_traceability"] is None, "null, never a passing 1.0"
