"""T224 — one advert is stored once, whatever text the list row carried.

The offer id hashes text and a list row's text changes between searches, so a
rule-out recorded against one id missed every other copy. Every case below that
can be derived from the connector library is derived over **every connector**
(`CONNECTORS`), so a package added later is covered without anyone remembering
to list it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit

import pytest

from integral.advert_identity import identity_query_for, restrict_query
from integral.connectors import Connector, load_connectors, parse_list_page
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import (
    advert_identity,
    build_tombstone,
    canonicalize_url,
    collect_offer,
    current_tombstones,
    load_lifecycle_offer,
    offer_identity,
    purge_offer,
    save_lifecycle_offer,
    stored_identities,
    track_new_offer,
)
from integral.offers import Offer, compute_offer_id
from integral.presentation_log import partition, rule_out

ROOT = Path(__file__).resolve().parents[1]
CONNECTORS = sorted(load_connectors(ROOT / "connectors"), key=lambda c: c.site)
SITES = [c.site for c in CONNECTORS]
DECLARED = [c.site for c in CONNECTORS if c.identity_query is not None]
NOW = "2026-01-01T00:00:00+00:00"
LATER = "2026-06-01T00:00:00+00:00"


def _by_site(site: str) -> Connector:
    return next(c for c in CONNECTORS if c.site == site)


def _base(connector: Connector) -> str:
    pattern = (
        connector.list.url_pattern.replace("{page}", "1")
        .replace("{query}", "python")
        .replace("{employer}", "a0")
    )
    return pattern


def _fixture_urls(connector: Connector) -> list[str]:
    path = ROOT / "connectors" / f"{connector.site}_{connector.locale}" / "fixture" / "list.html"
    if not path.exists():
        return []
    urls = []
    for item in parse_list_page(connector, path.read_text(encoding="utf-8")):
        found = item.get("url") or item.get("detail_url")
        if found:
            urls.append(urljoin(_base(connector), found))
    return urls


def _advert_url(connector: Connector, n: int) -> str:
    """A url of the shape this connector's adverts have: its own committed
    fixture's when it has one, otherwise a path on its list host."""
    urls = sorted(set(_fixture_urls(connector)))
    if urls:
        return urls[n % len(urls)]
    return urljoin(_base(connector), f"/zz-advert/{n}")


def _with_params(url: str, **params: str) -> str:
    sep = "&" if urlsplit(url).query else "?"
    return url + sep + "&".join(f"{k}={v}" for k, v in params.items())


def _offer(connector: Connector, url: str, text: str) -> Offer:
    return Offer(id=compute_offer_id(text), source=connector.site, url=url, text=text)


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    create_profile(root, "Fixture", handle="fixture", language="es", fiction=True)
    return ProfileStore(root, "fixture")


def _stored_ids(store: ProfileStore) -> set[str]:
    return {p.stem for p in Path(store.path("offers")).glob("*.json") if not p.name.startswith("_")}


# --- the declaration, checked against the committed fixtures -----------------


def test_the_library_is_not_empty() -> None:
    # A closed rule over an empty population passes everything.
    assert len(CONNECTORS) >= 25
    assert sum(len(_fixture_urls(c)) for c in CONNECTORS) >= 100


@pytest.mark.parametrize("site", SITES)
def test_a_connector_whose_adverts_carry_a_query_declares_what_is_identity(site: str) -> None:
    connector = _by_site(site)
    with_query = [u for u in _fixture_urls(connector) if urlsplit(u).query]
    if with_query:
        assert connector.identity_query is not None, (
            f"{site}: advert urls carry a query ({with_query[0]}) and the connector does not "
            "say which parameters name the advert — undeclared keeps the whole query, so the "
            "same advert stored under two searches is two adverts"
        )


@pytest.mark.parametrize("site", SITES)
def test_the_declared_identity_never_merges_two_adverts_the_fixture_shows_apart(
    site: str,
) -> None:
    # Fail-closed direction: dropping an identity parameter hides the second advert.
    urls = set(_fixture_urls(_by_site(site)))
    canonical = {canonicalize_url(u) for u in urls}
    identities = {advert_identity(u, site) for u in urls}
    assert len(identities) == len(canonical)


@pytest.mark.parametrize("site", SITES)
def test_a_parameter_outside_the_declaration_is_not_identity(site: str) -> None:
    connector = _by_site(site)
    declared = connector.identity_query
    for url in sorted(set(_fixture_urls(connector)))[:5] or [_advert_url(connector, 0)]:
        probed = advert_identity(_with_params(url, zzsearch="1"), site)
        if declared is None:
            assert probed != advert_identity(url, site)  # kept: nothing was claimed
        else:
            assert probed == advert_identity(url, site)


@pytest.mark.parametrize("site", SITES)
def test_every_declared_identity_parameter_changes_the_identity(site: str) -> None:
    connector = _by_site(site)
    for name in connector.identity_query or ():
        for url in sorted(set(_fixture_urls(connector)))[:5]:
            pairs = dict(parse_qsl(urlsplit(url).query))
            if name not in pairs:
                continue
            other = url.replace(f"{name}={pairs[name]}", f"{name}={pairs[name]}9")
            assert advert_identity(other, site) != advert_identity(url, site)


def test_the_query_that_motivated_this_is_one_advert() -> None:
    # The issue's own example: JobFluent carries the search in the url.
    a = "https://www.jobfluent.com/es/empleos/data-scientist-barcelona-cc3854?q=AI+engineer&result=21"
    b = "https://www.jobfluent.com/es/empleos/data-scientist-barcelona-cc3854?q=python&result=3"
    assert advert_identity(a, "jobfluent") == advert_identity(b, "jobfluent")


def test_talent_keeps_the_id_that_is_its_identity() -> None:
    a = "https://es.talent.com/view?id=600989642228510677&k=python&l=Espa%C3%B1a&p=1"
    b = "https://es.talent.com/view?id=600989642228510678&k=python&l=Espa%C3%B1a&p=1"
    again = "https://es.talent.com/view?id=600989642228510677&k=java&p=2"
    assert advert_identity(a, "talent") != advert_identity(b, "talent")
    assert advert_identity(a, "talent") == advert_identity(again, "talent")


def test_a_source_no_connector_declares_keeps_the_whole_query() -> None:
    url = "https://example.test/job?id=7&x=1"
    assert identity_query_for("manual") is None
    assert advert_identity(url, "manual") == canonicalize_url(url)
    assert advert_identity(None, "manual") is None
    assert advert_identity("  ", "manual") is None


def test_restrict_query_is_a_filter_not_a_rewrite() -> None:
    canonical = "https://h.test/p?a=1&b=2"
    assert restrict_query(canonical, None) == canonical
    assert restrict_query(canonical, ()) == "https://h.test/p"
    assert restrict_query(canonical, ("b",)) == "https://h.test/p?b=2"


@pytest.mark.parametrize("bad", ["ID", "", " id", "id=1", "a&b"])
def test_an_identity_parameter_name_that_could_never_match_is_refused(bad: str) -> None:
    connector = _by_site("talent")
    with pytest.raises(ValueError, match="identity_query"):
        Connector.model_validate({**connector.model_dump(mode="json"), "identity_query": [bad]})


# --- storage: one advert, one stored copy ------------------------------------


@pytest.mark.parametrize("site", SITES)
def test_the_same_advert_under_new_text_is_not_stored_again(site: str, store: ProfileStore) -> None:
    connector = _by_site(site)
    url = _advert_url(connector, 0)
    first = _offer(connector, url, "list row text, search one")
    second = _offer(connector, _with_params(url, utm_source="x"), "list row text, search two")
    assert collect_offer(store, first, at=NOW).added_as_new
    outcome = collect_offer(store, second, at=NOW)
    assert not outcome.added_as_new
    assert outcome.duplicate_of == first.id
    assert _stored_ids(store) == {first.id}


@pytest.mark.parametrize("site", SITES)
def test_a_different_advert_is_stored(site: str, store: ProfileStore) -> None:
    connector = _by_site(site)
    first = _offer(connector, _advert_url(connector, 0), "advert one")
    other = _offer(connector, _advert_url(connector, 1), "advert two")
    if first.url == other.url:  # a one-advert fixture
        other = _offer(connector, urljoin(_base(connector), "/zz-other/9"), "advert two")
    assert collect_offer(store, first, at=NOW).added_as_new
    assert collect_offer(store, other, at=NOW).added_as_new
    assert len(_stored_ids(store)) == 2


@pytest.mark.parametrize("site", DECLARED)
def test_a_search_dependent_query_does_not_split_a_declared_connector(
    site: str, store: ProfileStore
) -> None:
    connector = _by_site(site)
    url = _advert_url(connector, 0)
    a = _offer(connector, _with_params(url, zzsearch="1"), "text a")
    b = _offer(connector, _with_params(url, zzsearch="2"), "text b")
    assert collect_offer(store, a, at=NOW).added_as_new
    assert not collect_offer(store, b, at=NOW).added_as_new


def test_a_url_less_offer_ruled_out_does_not_withhold_another_url_less_offer(
    store: ProfileStore,
) -> None:
    # No url is no identity, and no identity is not "the same identity as every
    # other offer with none".
    one = Offer(id=compute_offer_id("a"), source="manual", text="a")
    two = Offer(id=compute_offer_id("b"), source="manual", text="b")
    collect_offer(store, one, at=NOW)
    collect_offer(store, two, at=NOW)
    rule_out(store, one.id, "no", at=NOW)
    assert partition(store, [two.id]) == ([two.id], [])


def test_a_url_less_offer_is_never_called_a_copy(store: ProfileStore) -> None:
    one = Offer(id=compute_offer_id("a"), source="manual", text="a")
    two = Offer(id=compute_offer_id("b"), source="manual", text="b")
    assert collect_offer(store, one, at=NOW).added_as_new
    assert collect_offer(store, two, at=NOW).added_as_new


# --- rule-outs follow the advert ---------------------------------------------


@pytest.mark.parametrize("site", SITES)
def test_a_ruled_out_advert_does_not_come_back_under_a_new_id(
    site: str, store: ProfileStore
) -> None:
    connector = _by_site(site)
    url = _advert_url(connector, 0)
    first = _offer(connector, url, "text, first search")
    collect_offer(store, first, at=NOW)
    rule_out(store, first.id, "not my profile", at=NOW)
    again = _offer(connector, _with_params(url, utm_medium="y"), "text, second search")
    outcome = collect_offer(store, again, at=LATER)
    assert not outcome.added_as_new
    assert again.id not in _stored_ids(store)
    shown, held = partition(store, [first.id])
    assert shown == []
    assert [h.offer_id for h in held] == [first.id]


@pytest.mark.parametrize("site", SITES)
def test_copies_stored_before_this_change_are_covered_at_read_time(
    site: str, store: ProfileStore
) -> None:
    # The migration question, answered by construction: no stored file is
    # rewritten, and the verdict recorded against one copy still withholds the
    # others. The second copy is written the way every pre-T224 copy was.
    connector = _by_site(site)
    url = _advert_url(connector, 0)
    ruled = _offer(connector, url, "text, search one")
    legacy = _offer(connector, _with_params(url, utm_term="z"), "text, search two")
    collect_offer(store, ruled, at=NOW)
    save_lifecycle_offer(store, legacy, track_new_offer(legacy, at=NOW))
    before = {i: Path(store.path("offers", f"{i}.json")).read_bytes() for i in _stored_ids(store)}
    rule_out(store, ruled.id, "wrong sector", at=NOW)
    shown, held = partition(store, [legacy.id])
    assert shown == []
    assert held[0].reason == "wrong sector"
    after = {i: Path(store.path("offers", f"{i}.json")).read_bytes() for i in _stored_ids(store)}
    assert after[legacy.id] == before[legacy.id]


def test_a_sibling_that_is_not_ruled_out_does_not_withhold_the_new_copy(
    store: ProfileStore,
) -> None:
    connector = _by_site("jobfluent")
    url = _advert_url(connector, 0)
    a = _offer(connector, url, "a")
    b = _offer(connector, _with_params(url, result="9"), "b")
    save_lifecycle_offer(store, a, track_new_offer(a, at=NOW))
    save_lifecycle_offer(store, b, track_new_offer(b, at=NOW))
    shown, held = partition(store, [a.id, b.id])
    # Never both: the same advert twice in one list is one advert shown once.
    assert shown == [a.id]
    assert [h.offer_id for h in held] == [b.id]


def test_two_different_adverts_are_both_shown(store: ProfileStore) -> None:
    connector = _by_site("talent")
    a = _offer(connector, "https://es.talent.com/view?id=1&p=1", "a")
    b = _offer(connector, "https://es.talent.com/view?id=2&p=1", "b")
    save_lifecycle_offer(store, a, track_new_offer(a, at=NOW))
    save_lifecycle_offer(store, b, track_new_offer(b, at=NOW))
    assert partition(store, [a.id, b.id]) == ([a.id, b.id], [])


# --- tombstones key on the identity ------------------------------------------


@pytest.mark.parametrize("site", SITES)
def test_a_tombstone_records_the_identity_not_the_search(site: str, store: ProfileStore) -> None:
    connector = _by_site(site)
    url = _advert_url(connector, 0)
    offer = _offer(connector, url, "to be purged")
    collect_offer(store, offer, at=NOW)
    rule_out(store, offer.id, "no", at=NOW)
    now = datetime(2026, 6, 1, tzinfo=UTC)
    tombstone = purge_offer(store, offer.id, at=LATER, now=now)
    assert tombstone.url_canonical == offer_identity(offer)
    again = _offer(connector, _with_params(url, utm_medium="2"), "different text entirely")
    outcome = collect_offer(store, again, at=LATER)
    assert outcome.matched_tombstone == offer.id
    assert not outcome.added_as_new
    assert again.id not in _stored_ids(store)


@pytest.mark.parametrize("site", DECLARED)
def test_a_declared_connectors_tombstone_matches_a_different_search(
    site: str, store: ProfileStore
) -> None:
    connector = _by_site(site)
    url = _advert_url(connector, 0)
    offer = _offer(connector, _with_params(url, zzsearch="1"), "to be purged")
    collect_offer(store, offer, at=NOW)
    rule_out(store, offer.id, "no", at=NOW)
    purge_offer(store, offer.id, at=LATER, now=datetime(2026, 6, 1, tzinfo=UTC))
    again = _offer(connector, _with_params(url, zzsearch="2"), "different text entirely")
    outcome = collect_offer(store, again, at=LATER)
    assert outcome.matched_tombstone == offer.id
    assert again.id not in _stored_ids(store)


def test_a_tombstone_written_before_this_change_still_matches(store: ProfileStore) -> None:
    # The ledger is append-only: a row holding the whole query is read through
    # the identity rule via its raw `url`, never migrated.
    connector = _by_site("jobfluent")
    old_url = "https://www.jobfluent.com/es/empleos/x-barcelona-cc1?q=AI+engineer&result=21"
    legacy = _offer(connector, old_url, "old text")
    collect_offer(store, legacy, at=NOW)
    rule_out(store, legacy.id, "no", at=NOW)
    tombstone = build_tombstone(
        load_lifecycle_offer(store, legacy.id)[0],
        load_lifecycle_offer(store, legacy.id)[1],
        purged_at=LATER,
    ).model_copy(update={"url_canonical": canonicalize_url(old_url)})
    store.append_jsonl(tombstone.model_dump(mode="json"), "offers", "tombstones.jsonl")
    Path(store.path("offers", f"{legacy.id}.json")).unlink()
    Path(store.path("offers", "lifecycle", f"{legacy.id}.json")).unlink()
    newer = _offer(
        connector, "https://www.jobfluent.com/es/empleos/x-barcelona-cc1?q=python&result=3", "new"
    )
    outcome = collect_offer(store, newer, at=LATER)
    assert outcome.matched_tombstone == legacy.id
    assert legacy.id in current_tombstones(store)
    assert not outcome.added_as_new


def test_the_identity_cache_notices_a_file_that_changed_on_disk(store: ProfileStore) -> None:
    connector = _by_site("jobfluent")
    url = _advert_url(connector, 0)
    a = _offer(connector, url, "a")
    collect_offer(store, a, at=NOW)
    assert stored_identities(store)[a.id] == advert_identity(url, "jobfluent")  # cache primed
    path = Path(store.path("offers", f"{a.id}.json"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["url"] = urljoin(_base(connector), "/es/empleos/elsewhere-barcelona-cc99")
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    other = _offer(connector, url, "b")
    assert collect_offer(store, other, at=NOW).added_as_new
