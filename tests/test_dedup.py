"""T13 — cross-source dedup by similarity over normalised text, and expiry.

The gate is `dedup_precision >= 0.95`: of the pairs the algorithm flags as
duplicates, the fraction that really are. Precision rather than recall
because a false merge silently drops a role from the candidate's list with
nothing to tell them it happened, while a missed duplicate is only noise —
see `integral.dedup`'s module docstring for the full argument.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from integral import liveness
from integral.connectors import SEARCH_SOURCE
from integral.dedup import (
    MINIMUM_CLUSTER_PAIRS,
    MINIMUM_PAIRS,
    SIMILARITY_THRESHOLD,
    DedupError,
    ExpiryFinding,
    Tombstone,
    _fixture_batch,
    _majority_cluster_fixture,
    detect_expired,
    find_duplicates,
    jaccard,
    load_tombstones,
    normalise_for_comparison,
    probe_dedup,
    shingles,
    similarity,
    tombstone_match,
    write_evidence,
)
from integral.offers import Offer


def _offer_hex(n: int, text: str, **fields: object) -> Offer:
    return Offer(id=f"sha256:{n:064x}", source="portal", text=text, **fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# the two named tests


def test_crossposted_duplicates_are_collapsed() -> None:
    """A repost of the same ad through a different portal — reworded opening
    and closing lines, unchanged middle — must be found as a duplicate.
    Missing this is the failure `dedup_precision` does not penalise but the
    product still cares about, so it is asserted directly here rather than
    only inferred from the gate's precision number."""
    offers, duplicate_pairs = _fixture_batch()
    matches = find_duplicates(offers)
    predicted = {frozenset((m.offer_a, m.offer_b)) for m in matches}
    assert duplicate_pairs.issubset(predicted), (
        "at least one seeded crosspost pair was not collapsed: "
        f"missed {duplicate_pairs - predicted}"
    )


def test_distinct_roles_at_same_company_are_not_merged() -> None:
    """Backend Engineer and Frontend Engineer at the same company (`Acme`)
    share an employer, a boilerplate footer, and near-identical titles up to
    the role name — and must still not be reported as the same ad. Collapsing
    this pair is exactly the invisible failure `dedup_precision` exists to
    catch: the candidate would silently lose one of the two roles."""
    offers, duplicate_pairs = _fixture_batch()
    backend_acme = next(o for o in offers if o.title == "Backend Engineer - Acme")
    frontend_acme = next(o for o in offers if o.title == "Frontend Engineer")
    assert frozenset((backend_acme.id, frontend_acme.id)) not in duplicate_pairs  # fixture sanity

    matches = find_duplicates(offers)
    predicted = {frozenset((m.offer_a, m.offer_b)) for m in matches}
    assert frozenset((backend_acme.id, frontend_acme.id)) not in predicted


# ---------------------------------------------------------------------------
# additional seeded cases


def test_different_title_same_body_is_a_duplicate() -> None:
    """Only the title differs; the body is byte-identical. The near-duplicate
    path must catch this even though T11's `compute_offer_id` (verbatim-text
    hashing) does not, because the ids differ."""
    body = (
        "Senior Platform Engineer role. Own our deployment pipeline, mentor "
        "two junior engineers, and drive incident response process. We run "
        "on AWS with Terraform and everything is containerised. Strong "
        "communication skills required for cross-team collaboration."
    )
    a = _offer_hex(101, body, title="Senior Platform Engineer")
    b = _offer_hex(102, body, title="Platform Engineer (Senior)")
    assert similarity(a, b) >= SIMILARITY_THRESHOLD


def test_same_ad_with_boilerplate_footer_added_is_a_duplicate() -> None:
    """One source renders a legal/cookie footer after the ad body; another
    does not. The footer must not dilute the match below threshold."""
    body = (
        "Customer Support Specialist needed for a fast-growing SaaS team. "
        "You will triage inbound tickets, escalate bugs to engineering, and "
        "maintain our public help centre articles. Experience with "
        "Zendesk or a similar tool is expected, along with clear written "
        "communication in English."
    )
    footer = (
        "Equal opportunity employer. We celebrate diversity and are committed "
        "to creating an inclusive environment for all employees. By applying "
        "you consent to our processing of your data for recruitment purposes "
        "in accordance with our privacy policy."
    )
    a = _offer_hex(111, body)
    b = _offer_hex(112, body + " " + footer)
    assert similarity(a, b) >= SIMILARITY_THRESHOLD


def test_shared_boilerplate_does_not_merge_distinct_ads() -> None:
    """The hard negative: several ads for genuinely different roles all carry
    the same source-template footer verbatim. A naive Jaccard score over raw
    text merges them on the footer alone; `find_duplicates`'s batch-level
    boilerplate filter must not let that happen. Uses `_fixture_batch`
    directly (its cluster around `t13-1c`/`t13-2a`/`t13-2b` is built for
    exactly this) rather than a two-offer pair, because the filter needs a
    batch to define "common" against (see `_boilerplate_shingles`)."""
    offers, duplicate_pairs = _fixture_batch()
    backend_with_footer = next(o for o in offers if o.title == "Backend Engineer - Acme")
    data_offers_with_footer = [
        o for o in offers if o.title is not None and o.title.startswith("Data Engineer")
    ]
    assert data_offers_with_footer, "fixture must seed at least one Data Engineer ad"

    matches = find_duplicates(offers)
    predicted = {frozenset((m.offer_a, m.offer_b)) for m in matches}
    for data_offer in data_offers_with_footer:
        pair = frozenset((backend_with_footer.id, data_offer.id))
        assert pair not in duplicate_pairs  # fixture sanity: these are not seeded as duplicates
        assert pair not in predicted, (
            f"{backend_with_footer.title!r} and {data_offer.title!r} were merged on "
            "shared boilerplate alone"
        )


def test_majority_duplicate_cluster_is_not_erased_as_boilerplate() -> None:
    """Regression for the finding-1 review note: a single-pass frequency
    filter that counts boilerplate over raw offers cannot tell a shared
    template fragment from a popular role's own crossposts. Three
    independently reworded copies of one DevOps Engineer ad are 3 of 5
    offers in `_majority_cluster_fixture` (60%, over the 50% boilerplate
    line) — a popular role is *more* likely to dominate a small batch, not
    less, so this is the case the boilerplate filter exists to survive, not
    an edge case. Under the single-pass version this replaced, every one of
    the three true-duplicate pairs below scored exactly 0.0: the ads' own
    shared body was reclassified as template text and their similarity
    signal erased along with it. The two-pass fix
    (`_cluster_representatives` + `_boilerplate_shingles` over cluster
    representatives, see the module docstring) must find all three."""
    offers, duplicate_pairs = _majority_cluster_fixture()
    assert len(duplicate_pairs) >= MINIMUM_CLUSTER_PAIRS, "fixture sanity: needs 3+ seeded pairs"

    matches = find_duplicates(offers)
    predicted = {frozenset((m.offer_a, m.offer_b)) for m in matches}
    assert duplicate_pairs.issubset(predicted), (
        "a majority-of-the-batch duplicate cluster was erased as boilerplate: "
        f"missed {duplicate_pairs - predicted}"
    )


def test_probe_dedup_reports_majority_cluster_recall_without_changing_the_declared_gate() -> None:
    """The recall-side probe finding 1's review note asked for: recorded
    alongside `dedup_precision` in the same evidence dict, not in place of
    it — `dedup_precision` stays the declared gate."""
    measured = probe_dedup()
    assert measured["majority_cluster_pairs_seeded"] >= MINIMUM_CLUSTER_PAIRS
    assert measured["majority_cluster_recall"] == 1.0
    assert measured["majority_cluster_missed"] == 0
    assert "dedup_precision" in measured  # the gate itself is still reported


def test_normalisation_does_not_mutate_the_stored_offer() -> None:
    """T11 keeps `Offer.text` verbatim because T15's evidence spans are
    offsets into it. `normalise_for_comparison` must return a new string and
    leave the offer's own text untouched — and `Offer` being frozen means an
    attempt to write back would raise, not silently succeed."""
    original_text = "Backend Engineer, Remote.\n\nSalary: DOE.  Apply now!!"
    offer = _offer_hex(121, original_text)
    normalised = normalise_for_comparison(offer.text)

    assert offer.text == original_text  # untouched
    assert normalised != original_text  # actually normalised (lowercased, punctuation folded)
    with pytest.raises(Exception):  # noqa: B017 - pydantic's frozen-model error type is internal
        offer.text = "mutated"


def test_expired_offer_is_detected_by_expires_at() -> None:
    """An offer past its `expires_at` is flagged — but not deleted, purged,
    or transitioned. §7.1's `-> expired` transition is S5's."""
    offer = _offer_hex(131, "Contract role, three months.", expires_at="2026-01-01T00:00:00Z")
    now = datetime(2026, 8, 18, tzinfo=UTC)
    findings = detect_expired([offer], now=now)
    assert findings == [
        ExpiryFinding(offer.id, "expires_at_passed", "expired at 2026-01-01T00:00:00Z")
    ]
    assert offer.status == "new"  # detection never writes back to the offer


def test_offer_dropped_from_source_listing_is_detected_as_delisted() -> None:
    """An offer with no `expires_at` that a source no longer lists is also
    expired, by §7.1's other route ("no longer live at source")."""
    offer = _offer_hex(132, "Contract role.", source_ref="abc-123")
    now = datetime(2026, 8, 18, tzinfo=UTC)
    findings = detect_expired([offer], now=now, still_listed={"portal": frozenset({"xyz-999"})})
    assert len(findings) == 1
    assert findings[0].reason == "delisted"


def test_source_with_no_completed_pass_is_not_treated_as_delisting_everything() -> None:
    """A source absent from `still_listed` has not been re-collected this
    round; treating that silence as delisting would expire every offer the
    first time a collection run is skipped or fails."""
    offer = _offer_hex(133, "Contract role.", source_ref="abc-123")
    now = datetime(2026, 8, 18, tzinfo=UTC)
    findings = detect_expired([offer], now=now, still_listed={"other-portal": frozenset()})
    assert findings == []


def test_naive_now_raises_instead_of_silently_assuming_utc() -> None:
    """Regression for finding 2: an ISO `expires_at` ending in 'Z' parses to
    a timezone-aware datetime, so comparing it against a naive `now` used to
    raise a bare `TypeError` from deep inside the loop — and the only tests
    that existed passed an explicitly aware `now`, so the public function's
    naive path was untested. This repo's habit is to refuse an ambiguous
    input rather than guess (§7.4's own posture on tombstone rules), so a
    naive `now` must raise a clear, actionable error up front instead of
    either crashing confusingly or silently treating naive as UTC."""
    offer = _offer_hex(134, "Contract role.", expires_at="2026-01-01T00:00:00Z")
    naive_now = datetime(2026, 8, 18)  # no tzinfo
    with pytest.raises(ValueError, match="timezone-aware"):
        detect_expired([offer], now=naive_now)


def test_offset_bearing_non_utc_expiry_is_compared_correctly() -> None:
    """An `expires_at` carrying an explicit non-UTC offset must compare
    correctly against an aware `now`, not just the 'Z'-suffixed UTC case the
    other tests exercise. 2026-08-18T23:30:00+05:00 is 2026-08-18T18:30:00Z —
    already past an aware `now` of 2026-08-18T19:00:00Z, even though the
    naive wall-clock hour (23:30) reads *after* the naive wall-clock hour of
    `now` (19:00). A fix that merely stripped tzinfo instead of comparing the
    aware instants correctly would get this backwards."""
    offer = _offer_hex(135, "Contract role.", expires_at="2026-08-18T23:30:00+05:00")
    now = datetime(2026, 8, 18, 19, 0, tzinfo=UTC)
    findings = detect_expired([offer], now=now)
    assert findings == [
        ExpiryFinding(offer.id, "expires_at_passed", "expired at 2026-08-18T23:30:00+05:00")
    ]


def test_naive_expires_at_is_treated_as_ambiguous_and_skipped() -> None:
    """An `expires_at` with no 'Z' and no offset parses fine but names no
    zone — genuinely ambiguous, not malformed. Guessing "the same zone as
    `now`" is the silent assumption finding 2 exists to remove, so this is
    skipped for the offer rather than guessed at, the same treatment as an
    unparseable value (and unlike the previous behaviour, which replaced the
    missing tzinfo with `now`'s)."""
    offer = _offer_hex(136, "Contract role.", expires_at="2020-01-01T00:00:00")
    now = datetime(2026, 8, 18, tzinfo=UTC)
    findings = detect_expired([offer], now=now)
    assert findings == []


# ---------------------------------------------------------------------------
# tombstones — the seam T13 leaves for S5


def test_tombstone_match_by_text_sha256() -> None:
    tombstone = Tombstone(
        offer_id="of-1",
        url_canonical="https://example.com/jobs/1",
        text_sha256="deadbeef",
        first_seen="2026-04-02",
        purged_at="2026-06-03",
        last_status="screened_out",
        resightings=0,
    )
    found = tombstone_match([tombstone], text_sha256="deadbeef")
    assert found is tombstone
    assert tombstone_match([tombstone], text_sha256="somethingelse") is None
    assert tombstone_match([tombstone]) is None  # no keys given, no match


def test_load_tombstones_raises_on_malformed_row(tmp_path: Path) -> None:
    """A loader raises when what it's given cannot become the thing it
    promises — same rule as `offers.load_offer`."""
    path = tmp_path / "tombstones.jsonl"
    path.write_text('{"offer_id": "of-1"}\n', encoding="utf-8")  # missing required fields
    with pytest.raises(DedupError):
        load_tombstones(path)


def test_load_tombstones_round_trips_a_well_formed_file(tmp_path: Path) -> None:
    path = tmp_path / "tombstones.jsonl"
    row = (
        '{"offer_id": "of-1", "url_canonical": "https://x/1", "text_sha256": "abc", '
        '"first_seen": "2026-04-02", "purged_at": "2026-06-03", '
        '"last_status": "expired", "resightings": 2}'
    )
    path.write_text(row + "\n", encoding="utf-8")
    loaded = load_tombstones(path)
    assert len(loaded) == 1
    assert loaded[0].offer_id == "of-1"
    assert loaded[0].resightings == 2


# ---------------------------------------------------------------------------
# shingling / Jaccard building blocks


def test_shingles_of_short_text_is_the_whole_text() -> None:
    assert shingles("one two three") == frozenset({"one two three"})


def test_jaccard_of_two_empty_sets_is_zero_not_one() -> None:
    assert jaccard(frozenset(), frozenset()) == 0.0


# ---------------------------------------------------------------------------
# the gate


def test_probe_dedup_judges_enough_pairs() -> None:
    """`MINIMUM_PAIRS` exists so a trivially small fixture cannot report a
    hollow 1.0. The seeded fixture must clear it."""
    measured = probe_dedup()
    assert measured["pairs_judged"] >= MINIMUM_PAIRS


def test_probe_dedup_meets_the_precision_floor() -> None:
    measured = probe_dedup()
    assert measured["dedup_precision"] >= 0.95
    assert measured["failures"] == []


def test_write_evidence_persists_the_measurement(tmp_path: Path) -> None:
    target = tmp_path / "T13.json"
    measured = write_evidence(target)
    assert target.exists()
    assert measured["dedup_precision"] >= 0.95


# ---------------------------------------------------------------------------
# D-18 — an advert is verified at its source before it is offered


def _advert(offer_id_seed: str, *, source: str = "examplejobs", text: str = "Se busca.") -> Offer:
    return Offer(
        id="sha256:" + hashlib.sha256(offer_id_seed.encode("utf-8")).hexdigest(),
        source=source,
        text=text,
    )


def test_a_dead_advert_is_marked_expired_not_offered() -> None:
    """The tablondeanuncios case, end to end.

    Every listing from that board read "Puesto ocupado" and every one was
    presented as a vacancy. A closure notice in the advert's own body is the
    advert saying it is over, so the offer is expired and withheld — both, not
    either.
    """
    offer = _advert("ocupado", text="<h1>Albañil</h1><p>PUESTO OCUPADO</p>")
    check = liveness.read_response(offer.id, 200, offer.text)

    assert check.liveness == "dead"
    assert "puesto ocupado" in check.reason
    assert liveness.expire(offer, check).status == "expired"

    shown, withheld = liveness.presentable([offer], {offer.id: check})
    assert shown == []
    assert [w.liveness for w in withheld] == ["dead"]

    # A server that retires the listing outright says the same thing.
    gone = _advert("gone")
    gone_check = liveness.read_response(gone.id, 404, None)
    assert gone_check.liveness == "dead"
    assert liveness.expire(gone, gone_check).status == "expired"


def test_a_search_index_hit_is_verified_at_source_before_it_becomes_an_offer() -> None:
    """D-18's gate. `offers_presented_without_a_liveness_check == 0`.

    A search index is a memory of a page, and the page moves on. An offer that
    a general web search produced and nobody fetched is withheld — the default
    is not "alive", because that default is exactly how seven dead adverts
    reached a candidate.
    """
    hit = _advert("indexed", source=SEARCH_SOURCE, text="Albañil en Bilbao.")
    assert liveness.index_sourced(hit)

    # Never fetched: withheld, and not claimed dead either.
    unchecked = liveness.read_response(hit.id, None, None)
    assert unchecked.liveness == "unverified"
    assert liveness.presentable([hit], {hit.id: unchecked})[0] == []
    assert liveness.expire(hit, unchecked).status == "new"

    # An offer with no check at all must not slip through on the absence.
    assert liveness.presentable([hit], {})[0] == []

    # Fetched and open: this is the one the candidate may see.
    fetched = liveness.read_response(hit.id, 200, "Se busca albañil. Jornada completa.")
    assert fetched.liveness == "live"
    assert liveness.presentable([hit], {hit.id: fetched})[0] == [hit]

    measured = liveness.measure()
    assert measured["violations"] == []
    assert measured["offers_presented_without_a_liveness_check"] == 0
    assert any(r["expected"] == "live" and r["presented"] for r in measured["readings"])


def test_a_403_is_not_evidence_the_advert_is_gone() -> None:
    """The jobtoday case, and the reason there are three verdicts.

    A 403 is an anti-bot rule or a filled vacancy, indistinguishable from
    here. Both keep the offer away from the candidate; only one deserves a
    tombstone, and tombstoning a live vacancy would stop it ever being offered
    again (§7.4).
    """
    offer = _advert("jobtoday", source=SEARCH_SOURCE)
    check = liveness.read_response(offer.id, 403, None)

    assert check.liveness == "unverified"
    assert "not evidence the advert is gone" in check.reason
    assert liveness.presentable([offer], {offer.id: check})[0] == []
    assert liveness.expire(offer, check).status == "new"


def test_every_offer_needs_a_source_check_including_a_connector_s() -> None:
    """A connector reads a listing page, and a listing page is an index too —
    just a smaller one. The web-search case is the loudest, not the only one."""
    assert liveness.needs_source_check(_advert("from-connector"))
    assert liveness.needs_source_check(_advert("from-search", source=SEARCH_SOURCE))


def test_a_closure_notice_survives_casing_and_whitespace() -> None:
    """Boards do not agree on markup. "Puesto  Ocupado" across a line break is
    the same sentence, and a check that missed it would pass the advert."""
    assert liveness.dead_phrase_in("PUESTO\n  OCUPADO") == "puesto ocupado"
    assert liveness.dead_phrase_in("Esta Oferta   Ya No Está Disponible") is not None
    assert liveness.dead_phrase_in("Se busca albañil, jornada completa") is None


def test_a_redirect_is_not_evidence_the_advert_is_live() -> None:
    """A board retiring an advert commonly 301s it to a generic listings page,
    which renders perfectly and says nothing about the vacancy. `304` is a
    statement about a cache, not about today. Reading either as live is how a
    dead advert looks alive with a 200 attached to the wrong page."""
    offer = _advert("redirected", source=SEARCH_SOURCE)
    for status in (301, 302, 303, 304, 307, 308):
        check = liveness.read_response(offer.id, status, "<h1>Ofertas de empleo</h1>")
        assert check.liveness == "unverified", f"{status} read as {check.liveness}"
        assert "follow it" in check.reason
        assert liveness.presentable([offer], {offer.id: check})[0] == []


@pytest.mark.parametrize("status", ["expired", "archived"])
def test_liveness_does_not_un_retire_a_record(status: str) -> None:
    """Liveness answers "is the advert still there", never "should this
    candidate see it". A `live` verdict on an expired record would put it back
    in the list while the record itself still reads `expired` — two answers to
    one question, and the candidate sees the wrong one."""
    retired = _advert("retired").model_copy(update={"status": status})
    live_again = liveness.read_response(retired.id, 200, "Se busca albañil.")

    assert live_again.liveness == "live"
    shown, withheld = liveness.presentable([retired], {retired.id: live_again})
    assert shown == []
    assert "does not un-retire" in withheld[0].reason

    # An ordinary record with the same verdict is shown — the withholding is
    # about the record's retirement, not about the check.
    ordinary = _advert("ordinary")
    ordinary_check = liveness.read_response(ordinary.id, 200, "Se busca albañil.")
    assert liveness.presentable([ordinary], {ordinary.id: ordinary_check})[0] == [ordinary]


def test_a_redirect_that_lands_on_another_page_is_not_this_advert() -> None:
    """Following the redirect fixes the status code, not the problem.

    A board retiring an advert commonly sends it to a generic listings page,
    which answers 200 and carries no closure phrase. Judged on the response
    alone that reads `live` — and the candidate is shown a vacancy that is
    really a search page. What settles it is *where the fetch landed*.
    """
    offer = _advert("moved", source=SEARCH_SOURCE)
    listings = "<h1>Ofertas de empleo</h1><p>Encuentra tu próximo trabajo</p>"

    strayed = liveness.read_response(
        offer.id,
        200,
        listings,
        advert_url="https://board.example.com/oferta/12345",
        final_url="https://board.example.com/ofertas",
    )
    assert strayed.liveness == "unverified"
    assert "not this vacancy" in strayed.reason
    assert liveness.presentable([offer], {offer.id: strayed})[0] == []

    # Landing where it was sent is the ordinary case, and stays live.
    arrived = liveness.read_response(
        offer.id,
        200,
        "Se busca albañil. Jornada completa.",
        advert_url="https://board.example.com/oferta/12345",
        final_url="https://board.example.com/oferta/12345/",
    )
    assert arrived.liveness == "live", "a trailing slash is not a different page"
