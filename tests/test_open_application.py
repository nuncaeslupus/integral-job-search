"""T255: an open application is a declared record, and no advert consumer mistakes it for one."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

import integral.presentation_log as pl
from integral.dedup import detect_expired, find_duplicates
from integral.identity import ProfileStore
from integral.lifecycle import (
    LifecycleError,
    collect_offer,
    offer_identity,
    save_lifecycle_offer,
    track_new_offer,
)
from integral.liveness import needs_source_check, presentable
from integral.offers import Offer, OfferError, compute_offer_id, is_advert, open_application

SKILL = Path(__file__).resolve().parent.parent / ".claude/skills/step-11-application/SKILL.md"
AT = "2026-01-01T00:00:00+00:00"
ID = compute_offer_id("fixture advert")
URL = "https://forja.example/trabaja-con-nosotros"


def test_open_application_is_declared_and_has_no_text() -> None:
    offer = open_application("Forja Ejemplo", URL, [" Why us? ", "", "CV"])
    assert offer.kind == "open_application"
    assert offer.text == ""
    assert offer.form_questions == ["Why us?", "CV"]
    assert not is_advert(offer)
    assert open_application("forja  ejemplo", URL).id == open_application("Forja Ejemplo", URL).id


@pytest.mark.parametrize(("company", "url"), [("", URL), ("Forja Ejemplo", " ")])
def test_open_application_needs_employer_and_destination(company: str, url: str) -> None:
    with pytest.raises(OfferError):
        open_application(company, url)


def test_the_hand_written_shapes_are_refused() -> None:
    with pytest.raises(ValueError, match="blank"):
        Offer(id=ID, source="manual", company="Forja Ejemplo", text="")
    with pytest.raises(ValueError, match="form questions"):
        Offer(id=ID, source="manual", company="Forja Ejemplo", text="t", form_questions=["q"])
    with pytest.raises(ValueError, match="no advert text"):
        Offer(id=ID, source="manual", kind="open_application", company="F", text="t", url=URL)


def test_is_advert_reads_raw_json_and_defaults_old_records_to_advert() -> None:
    assert is_advert({"id": "a"})
    assert is_advert({"kind": "advert"})
    assert not is_advert({"kind": "open_application"})
    assert not is_advert({"kind": "something new"})


@pytest.fixture
def store_and_twin(tmp_path: Path) -> tuple[ProfileStore, str]:
    return pl._store_with_twin(tmp_path, "Forja Ejemplo", URL)


def test_record_is_stored_and_idempotent(store_and_twin: tuple[ProfileStore, str]) -> None:
    store, _ = store_and_twin
    first = pl.record_open_application(store, "Forja Ejemplo", URL, ["CV"], at=AT)
    again = pl.record_open_application(store, "Forja Ejemplo", URL, ["CV"], at=AT)
    assert first.id == again.id
    assert first.kind == "open_application"
    assert pl._loaded(store, first.id) is not None


def test_no_consumer_treats_it_as_a_vacancy(store_and_twin: tuple[ProfileStore, str]) -> None:
    store, twin = store_and_twin
    made = pl.record_open_application(store, "Forja Ejemplo", URL, ["CV"], at=AT)
    assert pl.treated_as_advert(store, made.id, twin) == []


def test_liveness_skips_it_and_still_checks_adverts() -> None:
    app = open_application("Forja Ejemplo", URL)
    advert = Offer(id=ID, source="manual", company="Forja Ejemplo", text="Backend")
    assert not needs_source_check(app)
    assert needs_source_check(advert)
    shown, withheld = presentable([app, advert], {})
    assert [o.id for o in shown] == [app.id]
    assert [c.offer_id for c in withheld] == [advert.id]


def test_it_has_no_advert_identity() -> None:
    assert offer_identity(open_application("Forja Ejemplo", URL)) is None


def test_collect_offer_refuses_it(store_and_twin: tuple[ProfileStore, str]) -> None:
    store, _ = store_and_twin
    with pytest.raises(LifecycleError):
        collect_offer(store, open_application("Forja Ejemplo", URL), at=AT)


def test_dedup_and_expiry_ignore_it() -> None:
    app = open_application("Forja Ejemplo", URL)
    twin = Offer(id=ID, source="manual", company="Forja Ejemplo", text="Backend", url=URL)
    other = open_application("Forja Ejemplo", URL + "/2")
    assert find_duplicates([app, twin]) == []
    assert find_duplicates([app, other]) == []
    dated = app.model_copy(update={"expires_at": "2020-01-01T00:00:00+00:00"})
    assert detect_expired([dated], now=datetime(2030, 1, 1, tzinfo=UTC)) == []
    assert detect_expired(
        [twin.model_copy(update={"expires_at": "2020-01-01T00:00:00+00:00"})],
        now=datetime(2030, 1, 1, tzinfo=UTC),
    )


def test_partition_holds_an_unshortlisted_open_application(
    store_and_twin: tuple[ProfileStore, str],
) -> None:
    store, _ = store_and_twin
    app = open_application("Otra Casa", "https://otra.example/apply")
    save_lifecycle_offer(store, app, track_new_offer(app, at=AT))
    _, held = pl.partition(store, [app.id])
    assert [(h.offer_id, h.reason) for h in held] == [(app.id, pl.REASON_OPEN_APPLICATION)]


def test_gate_measures_zero_and_catches_the_synthetic_shapes() -> None:
    result = pl.measure_open_applications()
    assert result["gate_status"] == "measured"
    assert result["open_applications_stored_as_adverts"] == 0
    assert result["open_applications_checked"] >= pl.MINIMUM_OPEN_APPLICATION_CASES
    assert result["synthetic_shapes_not_counted"] == 0
    assert result["adverts_not_treated_as_adverts"] == 0


def test_gate_is_unmeasured_under_its_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pl, "OPEN_APPLICATIONS", pl.OPEN_APPLICATIONS[:1])
    result = pl.measure_open_applications()
    assert result["gate_status"] == "unmeasured"
    assert result["open_applications_stored_as_adverts"] == -1


def test_skill_carries_the_open_application_rule_verbatim() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    fence = re.search(r"## An open application.*?```text\n(.*?)```", skill, re.S)
    assert fence is not None
    text = " ".join(fence.group(1).split())
    assert "There is no advert to tailor against" in text
    assert "employer's own site is the reference" in text
    assert "A form answer takes the place of the letter" in text
    assert "record_open_application" in skill
