"""T225 — a copy of an advert already shown, or already ruled out, is held back.

`partition` used to look at an offer's own record only. A `present()` row on one
copy, or a rule-out on one copy stored under a different URL, left every other
copy to be shown again. A sibling is the same `advert_identity` (same URL) or the
same `posting_key` (same employer and title, different URL).

Every verdict below is derived from that definition and from the task's two
costs: re-showing a ruled-out advert is the costly direction, hiding an advert
the candidate never saw is the other. So each hold-back case has a control that
must stay shown.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from integral.feedback import record_decision
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import posting_key, save_lifecycle_offer, track_new_offer
from integral.offers import Offer, compute_offer_id
from integral.presentation_log import Withheld, partition, present, rule_out, withheld_line

_AT = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    create_profile(root, "Fixture", handle="fixture", language="es", fiction=True)
    return ProfileStore(root, "fixture")


def _save(
    store: ProfileStore,
    text: str,
    *,
    url: str | None,
    title: str | None = "Backend engineer",
    company: str | None = "ACME",
    source: str = "fixture",
) -> str:
    offer = Offer(
        id=compute_offer_id(text), source=source, url=url, title=title, company=company, text=text
    )
    save_lifecycle_offer(store, offer, track_new_offer(offer, at=_AT))
    return offer.id


def _pair(store: ProfileStore, **second: Any) -> tuple[str, str]:
    """Two stored copies of one posting under different URLs, unless overridden."""
    first = _save(store, "copy one", url="https://a.example/jobs/1")
    kwargs: dict[str, Any] = {"url": "https://b.example/ofertas/99"}
    kwargs.update(second)
    return first, _save(store, "copy two", **kwargs)


# --- already shown ------------------------------------------------------------


def test_a_copy_of_a_shown_advert_is_held_back_by_url(store: ProfileStore) -> None:
    shown = _save(store, "one", url="https://a.example/jobs/1?utm_source=x", title="X", company="Y")
    other = _save(store, "two", url="https://a.example/jobs/1?utm_source=z", title="Q", company="R")
    present(store, [shown], at=_AT)
    kept, held = partition(store, [other])
    assert kept == []
    assert held == [Withheld(other, "el mismo anuncio ya se te mostró", shown)]


def test_a_copy_of_a_shown_advert_is_held_back_by_employer_and_title(store: ProfileStore) -> None:
    shown, other = _pair(store)
    present(store, [shown], at=_AT)
    kept, held = partition(store, [other])
    assert kept == []
    assert [(h.offer_id, h.sibling) for h in held] == [(other, shown)]


def test_the_shown_copy_itself_is_not_held_back(store: ProfileStore) -> None:
    # Repeating an offer is `passed_over`'s business. Only the *other* copy is held.
    shown, _other = _pair(store)
    present(store, [shown], at=_AT)
    assert partition(store, [shown]) == ([shown], [])


def test_a_copy_shown_itself_is_not_held_by_a_shown_sibling(store: ProfileStore) -> None:
    one, two = _pair(store)
    present(store, [one], at=_AT)
    present(store, [two], at=_AT)
    assert partition(store, [two]) == ([two], [])


def test_an_unshown_sibling_does_not_hold_a_copy_back(store: ProfileStore) -> None:
    # Stored is not shown: a copy that was merely collected has told the candidate nothing.
    _one, two = _pair(store)
    assert partition(store, [two]) == ([two], [])


def test_a_different_title_from_the_same_employer_is_still_shown(store: ProfileStore) -> None:
    shown = _save(store, "one", url="https://a.example/jobs/1")
    other = _save(store, "two", url="https://b.example/jobs/2", title="Data engineer")
    present(store, [shown], at=_AT)
    assert partition(store, [other]) == ([other], [])


def test_the_same_title_at_another_employer_is_still_shown(store: ProfileStore) -> None:
    shown = _save(store, "one", url="https://a.example/jobs/1")
    other = _save(store, "two", url="https://b.example/jobs/2", company="Initech")
    present(store, [shown], at=_AT)
    assert partition(store, [other]) == ([other], [])


# --- ruled out ----------------------------------------------------------------


def test_a_rule_out_holds_back_a_copy_with_another_url(store: ProfileStore) -> None:
    ruled, other = _pair(store)
    rule_out(store, ruled, "no es mi perfil", at=_AT)
    kept, held = partition(store, [other])
    assert kept == []
    assert held == [Withheld(other, "no es mi perfil", ruled)]


def test_a_rule_out_on_the_later_copy_holds_back_the_earlier_one(store: ProfileStore) -> None:
    one, two = _pair(store)
    rule_out(store, two, "lejos", at=_AT)
    assert partition(store, [one])[1] == [Withheld(one, "lejos", two)]


def test_a_rule_out_does_not_hold_back_a_different_title(store: ProfileStore) -> None:
    ruled, other = _pair(store, title="Data engineer")
    rule_out(store, ruled, "no", at=_AT)
    assert partition(store, [other]) == ([other], [])


@pytest.mark.parametrize("blank", [None, "", "   ", "\u00a0\t "])
def test_a_blank_employer_is_never_merged(store: ProfileStore, blank: str | None) -> None:
    ruled = _save(store, "one", url="https://a.example/jobs/1", company=blank)
    other = _save(store, "two", url="https://b.example/jobs/2", company=blank)
    rule_out(store, ruled, "no", at=_AT)
    present(store, [ruled], at=_AT)
    assert partition(store, [other]) == ([other], [])


@pytest.mark.parametrize("blank", [None, "", "   ", "\u00a0\t "])
def test_a_blank_title_is_never_merged(store: ProfileStore, blank: str | None) -> None:
    ruled = _save(store, "one", url="https://a.example/jobs/1", title=blank)
    other = _save(store, "two", url="https://b.example/jobs/2", title=blank)
    rule_out(store, ruled, "no", at=_AT)
    present(store, [ruled], at=_AT)
    assert partition(store, [other]) == ([other], [])


def test_a_url_less_copy_is_matched_by_employer_and_title(store: ProfileStore) -> None:
    ruled = _save(store, "one", url=None)
    other = _save(store, "two", url="https://b.example/jobs/2")
    rule_out(store, ruled, "no", at=_AT)
    assert [h.sibling for h in partition(store, [other])[1]] == [ruled]


@pytest.mark.parametrize(
    ("title", "company"),
    [
        ("BACKEND ENGINEER", "acme"),
        ("  Backend   engineer ", "ACME  "),
        ("Backend\tengineer\n", "ACME"),
        ("Backend engineer", "\uff21\uff23\uff2d\uff25"),  # fullwidth: NFKC
    ],
)
def test_case_and_whitespace_do_not_make_a_different_advert(
    store: ProfileStore, title: str, company: str
) -> None:
    ruled, other = _pair(store, title=title, company=company)
    rule_out(store, ruled, "no", at=_AT)
    assert [h.sibling for h in partition(store, [other])[1]] == [ruled]


@pytest.mark.parametrize(
    ("title", "company"),
    [
        ("Backend engineer (senior)", "ACME"),
        ("Backend", "ACME"),
        ("Backend engineers", "ACME"),
        ("Backend engineer", "ACME Labs"),
        ("Backend-engineer", "ACME"),
    ],
)
def test_near_misses_are_not_merged(store: ProfileStore, title: str, company: str) -> None:
    ruled, other = _pair(store, title=title, company=company)
    rule_out(store, ruled, "no", at=_AT)
    present(store, [ruled], at=_AT)
    assert partition(store, [other]) == ([other], [])


# --- which sibling statuses hold back ----------------------------------------


@pytest.mark.parametrize("status", ["shortlisted", "applied"])
def test_a_sibling_the_candidate_is_pursuing_does_not_hold_back_by_status(
    store: ProfileStore, status: str
) -> None:
    # Not ruled out and not presented: nothing here says the candidate has seen the copy.
    chosen, other = _pair(store)
    record_decision(store, chosen, "shortlisted", at=_AT, reason=None)
    if status == "applied":
        record_decision(store, chosen, "applied", at=_AT, reason=None)
    assert partition(store, [other]) == ([other], [])


# --- the same advert in one batch ---------------------------------------------


def test_two_copies_in_one_batch_are_one_advert_shown_once(store: ProfileStore) -> None:
    one, two = _pair(store)
    kept, held = partition(store, [one, two])
    assert kept == [one]
    assert held == [Withheld(two, "el mismo anuncio ya está en esta lista", one)]


# --- the key itself -----------------------------------------------------------


def test_the_key_is_employer_and_title_only() -> None:
    assert posting_key("Backend engineer", "ACME") == posting_key(" BACKEND  engineer", "acme")
    assert posting_key("Backend engineer", "ACME") != posting_key("ACME", "Backend engineer")
    assert posting_key(None, "ACME") is None
    assert posting_key("Backend engineer", None) is None
    assert posting_key(" ", "ACME") is None


def test_the_report_names_the_reason_and_the_count(store: ProfileStore) -> None:
    ruled, other = _pair(store)
    rule_out(store, ruled, "no es mi perfil", at=_AT)
    assert (
        withheld_line(partition(store, [other])[1]) == "1 descartada(s): 1 porque «no es mi perfil»"
    )
