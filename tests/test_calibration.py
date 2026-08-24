"""T20a — the blind presentation, the recorded ordering, and `rank_spearman`."""

from __future__ import annotations

from pathlib import Path

import pytest

from integral import calibration
from integral.harness import load_store
from integral.identity import ProfileStore, create_profile
from integral.rank import write_ranking


def _drawn_ids() -> list[str]:
    return [calibration.offer_id(ad) for ad in calibration.draw()]


def test_the_twenty_are_drawn_from_the_evaluation_split_only() -> None:
    ads = calibration.draw()
    assert len(ads) == calibration.TWENTY
    assert {ad.split for ad in ads} == {"evaluation"}
    # Deterministic from the ad id, so two machines draw the same twenty.
    assert [ad.id for ad in ads] == [ad.id for ad in calibration.draw()]
    # Eligibility is split membership and nothing else — not "has labels". Only
    # four ads in the whole store carry a label today, so a draw of twenty that
    # filtered on labels could not have existed at all.
    assert sum(1 for ad in ads if ad.labels) < calibration.TWENTY


def test_the_presentation_order_is_independent_of_the_system_ranking() -> None:
    ads = calibration.draw()
    ids = [calibration.offer_id(ad) for ad in ads]

    order = calibration.presentation_order(ids)
    # A pure function of the ids: feeding them in the opposite order — which is
    # what a caller holding the system's ranking would do — changes nothing.
    assert calibration.presentation_order(list(reversed(ids))) == order
    assert sorted(order) == sorted(ids)
    assert order != ids

    payload = calibration.presentation(ads)
    page_order = [page["offer_id"] for page in payload["pages"]]
    assert page_order == order

    # And the detector earns its zero: a presentation that *is* the system's
    # ordering is caught, in either direction.
    assert calibration.leaks(payload, system_order=page_order) == [
        "presentation_follows_the_system_ranking"
    ]
    assert calibration.leaks(payload, system_order=list(reversed(page_order))) == [
        "presentation_follows_the_system_ranking"
    ]
    assert calibration.leaks(payload, system_order=ids) == []


def test_no_score_or_explanation_reaches_the_blind_page() -> None:
    ads = calibration.draw()
    payload = calibration.presentation(ads)

    assert set(payload) == {"pages"}
    for page in payload["pages"]:
        assert set(page) == calibration.PAGE_KEYS
    # The advert itself is there — a blind page with no advert on it is not a
    # page anybody can rank.
    assert payload["pages"][0]["text"]

    for planted in (
        {"salary_equivalent_total": 3200.0},
        {"contribution_eur_month": {"remote": 120.0}},
        {"explanation": "ranked first because it is remote"},
        {"rank": 1},
    ):
        leaky = calibration.presentation(ads)
        leaky["pages"][0].update(planted)
        assert "a_score_or_explanation_reaches_the_page" in calibration.leaks(
            leaky, system_order=[]
        )

    shown = calibration.presentation(ads)
    shown["recorded_ordering"] = [calibration.offer_id(ad) for ad in ads]
    assert "the_recorded_ordering_is_visible" in calibration.leaks(shown, system_order=[])


def test_spearman_matches_a_known_order() -> None:
    a = calibration.ranks(["x", "y", "z", "w"])
    assert calibration.spearman(a, a) == pytest.approx(1.0)
    assert calibration.spearman(a, calibration.ranks(["w", "z", "y", "x"])) == pytest.approx(-1.0)
    # One adjacent swap out of four: rho = 1 - 6*2/(4*15) = 0.8.
    assert calibration.spearman(a, calibration.ranks(["y", "x", "z", "w"])) == pytest.approx(0.8)

    # Ties: a group inside the order shares the average of the ranks it spans.
    tied = calibration.ranks(["x", ["y", "z"], "w"])
    assert tied == {"x": 1.0, "y": 2.5, "z": 2.5, "w": 4.0}
    assert calibration.spearman(tied, tied) == pytest.approx(1.0)
    assert calibration.spearman(a, tied) == pytest.approx(0.9486832980505138)

    with pytest.raises(calibration.CalibrationError):
        calibration.spearman(a, calibration.ranks(["x", "y", "z"]))


def test_a_malformed_ordering_is_refused() -> None:
    drawn = _drawn_ids()
    outsider = next(
        calibration.offer_id(ad) for ad in load_store() if ad.split == "elicitation"
    )

    duplicate = [drawn[0], *drawn[1:-1], drawn[0]]
    short_and_missing_one = drawn[:-1]
    unknown = [*drawn[:-1], "sha256:" + "f" * 64]
    from_the_other_split = [*drawn[:-1], outsider]

    for bad in (duplicate, short_and_missing_one, unknown, from_the_other_split):
        with pytest.raises(calibration.CalibrationError):
            calibration.require_permutation(bad, drawn)

    # A genuine reordering is not malformed — that is the whole point of it.
    calibration.require_permutation(list(reversed(drawn)), drawn)


def test_rank_spearman_is_unmeasured_until_an_ordering_is_recorded(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, create_profile(tmp_path, "Perico", language="en").handle)
    unmeasured = {"rank_spearman": None, "rank_status": "unmeasured"}

    # No store at all — a fresh clone — and a store with no ordering both say
    # the same thing: the measurement has not been taken here.
    assert calibration.measure_spearman(None) == unmeasured
    assert calibration.measure_spearman(store) == unmeasured

    drawn = _drawn_ids()
    calibration.record(store, list(reversed(drawn)))
    # Recorded, but the system has not ranked these twenty here, so there is
    # still nothing to correlate against.
    assert calibration.measure_spearman(store) == unmeasured

    write_ranking(store, {"run_id": "r-0001", "pareto": drawn})
    measured = calibration.measure_spearman(store)
    assert set(measured) == {"rank_spearman", "rank_status"}
    assert measured["rank_status"] == "measured"
    assert measured["rank_spearman"] == pytest.approx(-1.0)


def test_the_blocks_and_notes_are_recorded_beside_the_ordering(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, "perico")
    drawn = _drawn_ids()

    calibration.record(
        store,
        drawn,
        blocks={"Would apply": drawn[:5], "Maybe": drawn[5:12], "Not for me": drawn[12:]},
        # An empty box is not a judgement and is not stored as one.
        notes={
            drawn[0]: {"liked": "  ", "disliked": ""},
            drawn[1]: {"disliked": "Scala \u2014 never written a line of it"},
            drawn[2]: {"liked": "fully remote", "disliked": "no salary stated"},
        },
    )
    saved = calibration.recorded(store)
    assert saved is not None
    # The sign survives: an attractor and a knockout on the same advert stay
    # two facts, which is what a search strategy reads them as.
    assert saved["notes"] == {
        drawn[1]: {"disliked": "Scala \u2014 never written a line of it"},
        drawn[2]: {"liked": "fully remote", "disliked": "no salary stated"},
    }
    assert saved["blocks"]["Would apply"] == drawn[:5]
    # The ordering stays the thing that gets correlated; the blocks sit beside
    # it, not instead of it.
    assert saved["ordering"] == drawn

    outsider = "sha256:" + "f" * 64
    with pytest.raises(calibration.CalibrationError):
        calibration.record(store, drawn, notes={outsider: {"liked": "about nothing"}})
    with pytest.raises(calibration.CalibrationError):
        calibration.record(store, drawn, blocks={"Would apply": [outsider]})


def test_an_invented_candidate_never_certifies_the_gate(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    invented = create_profile(root, "Persona", language="en", fiction=True)
    store = ProfileStore(root, invented.handle)
    drawn = _drawn_ids()

    calibration.record(store, list(reversed(drawn)))
    write_ranking(store, {"run_id": "r-0001", "pareto": drawn})
    # Everything a measured run needs is present, and rho over it would be a
    # real number — which is why the refusal has to be explicit.
    assert calibration.measure_spearman(store) == {
        "rank_spearman": None,
        "rank_status": "unmeasured",
    }

    real = create_profile(root, "Perico", language="en")
    real_store = ProfileStore(root, real.handle)
    calibration.record(real_store, list(reversed(drawn)))
    write_ranking(real_store, {"run_id": "r-0001", "pareto": drawn})
    assert calibration.measure_spearman(real_store)["rank_status"] == "measured"

    # A tree with no readable identity is not a candidate either.
    assert calibration.is_fiction(ProfileStore(root, "nobody"))


def test_an_unusable_recorded_file_is_refused_not_crashed(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, create_profile(tmp_path, "Perico", language="en").handle)
    drawn = _drawn_ids()

    # `measure_spearman` reads `drawn`; a file carrying only `ordering` would
    # raise KeyError out of `make evidence` rather than reporting `unmeasured`.
    store.write_json({"ordering": drawn}, *calibration.ORDERING_PARTS)
    with pytest.raises(calibration.CalibrationError):
        calibration.recorded(store)

    calibration.record(store, drawn)
    # A stray file in the rankings directory is passed over, not fatal.
    store.write_text("not json at all", calibration.RANKINGS_DIR, "zzz.json")
    store.write_json(["a list, not a ranking"], calibration.RANKINGS_DIR, "yyy.json")
    assert calibration.measure_spearman(store)["rank_status"] == "unmeasured"
    write_ranking(store, {"run_id": "r-0001", "pareto": drawn})
    assert calibration.measure_spearman(store)["rank_status"] == "measured"


def test_blocks_must_partition_the_drawn_set(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, create_profile(tmp_path, "Perico", language="en").handle)
    drawn = _drawn_ids()

    # Two blocks sharing a name collapse into one in any object keyed by name,
    # and the ids in the overwritten block vanish while `ordering` still
    # validates. The count of placed ids is what catches it.
    with pytest.raises(calibration.CalibrationError, match="omit"):
        calibration.record(store, drawn, blocks={"Would apply": drawn[:5]})
    with pytest.raises(calibration.CalibrationError, match="more than one block"):
        calibration.record(
            store, drawn, blocks={"a": drawn, "b": drawn[:1]}
        )
    calibration.record(store, drawn, blocks={"a": drawn[:7], "b": drawn[7:]})


def test_the_leak_gate_counts_zero_and_every_plant_is_detected() -> None:
    measured = calibration.measure_leaks()
    assert measured["blind_ranking_leaks"] == 0
    assert measured["plants_undetected"] == []
