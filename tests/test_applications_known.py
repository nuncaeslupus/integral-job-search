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


def test_applied_advert_is_named_and_an_unknown_one_is_new(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "profiles"
    create_profile(root, "Fixture", handle="fixture", language="en", fiction=True)
    store = ProfileStore(root, "fixture")
    offer = Offer(
        id=compute_offer_id("ad"),
        source="b",
        url="https://B.example/jobs/1/",
        title="AI Engineer",
        company="C",
        text="ad",
    )
    record = track_new_offer(offer, at=T0)
    for step in ("shortlisted", "applied"):
        offer, record = transition(offer, record, step, at=T0)
    save_lifecycle_offer(store, offer, record)
    record_application_status(store, offer.id, status="applied", at=T0)

    # Same advert under a different spelling (host case, trailing slash, tracking param).
    seen = "https://b.example/jobs/1?utm_source=mail"
    code = _cli(
        ["known", seen, "https://b.example/jobs/2", "--id", "fixture", "--input-dir", str(root)]
    )
    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        f"applied applied | AI Engineer | C | {seen}",
        "NEW https://b.example/jobs/2",
    ]
