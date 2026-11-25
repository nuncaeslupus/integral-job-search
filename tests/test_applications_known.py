"""`integral.applications known`: an advert found outside `source()` is matched
against the store before it is presented as new."""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.applications import _cli
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import (
    record_application_status,
    save_lifecycle_offer,
    track_new_offer,
    transition,
)
from integral.offers import Offer, compute_offer_id

T0 = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "profiles"
    create_profile(r, "Fixture", handle="fixture", language="en", fiction=True)
    return r


def _store(root: Path, url: str, text: str, *, applied: bool, source: str = "b") -> None:
    store = ProfileStore(root, "fixture")
    offer = Offer(
        id=compute_offer_id(text),
        source=source,
        url=url,
        title="AI Engineer",
        company="C",
        text=text,
    )
    record = track_new_offer(offer, at=T0)
    for step in ("shortlisted", "applied") if applied else ():
        offer, record = transition(offer, record, step, at=T0)
    save_lifecycle_offer(store, offer, record)
    if applied:
        record_application_status(store, offer.id, status="applied", at=T0)


def _known(root: Path, *urls: str) -> int:
    return _cli(["known", *urls, "--id", "fixture", "--input-dir", str(root)])


def test_applied_advert_is_named_and_an_unknown_one_is_new(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _store(root, "https://B.example/jobs/1/", "ad", applied=True)
    # Same advert under a different spelling (host case, trailing slash, tracking param).
    seen = "https://b.example/jobs/1?utm_source=mail"
    assert _known(root, seen, "https://b.example/jobs/2") == 0
    assert capsys.readouterr().out.splitlines() == [
        f"applied applied | AI Engineer | C | {seen}",
        "NEW https://b.example/jobs/2",
    ]


def test_a_query_the_board_does_not_use_for_identity_is_ignored(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # jobfluent_es declares identity_query: [] — `?result=` is a listing position.
    base = "https://www.jobfluent.com/es/empleo/barcelona/123-ai-engineer"
    _store(root, base, "jf", applied=True, source="jobfluent_es")
    assert _known(root, base + "?result=21") == 0
    assert capsys.readouterr().out.startswith("applied applied |")


def test_every_stored_copy_is_listed_so_none_hides_another(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _store(root, "https://b.example/jobs/1", "copy one", applied=False)
    _store(root, "https://b.example/jobs/1", "copy two", applied=True)
    assert _known(root, "https://b.example/jobs/1") == 0
    assert sorted(line.split(" |")[0] for line in capsys.readouterr().out.splitlines()) == [
        "applied applied",
        "new -",
    ]


def test_an_unreadable_offer_file_is_named_and_exits_1(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = ProfileStore(root, "fixture")
    _store(root, "https://b.example/jobs/1", "ad", applied=False)
    (store.home / "offers" / "broken.json").write_text("{not json")
    assert _known(root, "https://b.example/jobs/9") == 1
    out = capsys.readouterr()
    assert out.out.splitlines() == ["NEW https://b.example/jobs/9"]
    assert "UNREADABLE broken" in out.err
