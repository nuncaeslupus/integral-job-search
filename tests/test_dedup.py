"""T13 — cross-source dedup by similarity over normalised text, and expiry.

The gate is `dedup_precision >= 0.95`: of the pairs the algorithm flags as
duplicates, the fraction that really are. Precision rather than recall
because a false merge silently drops a role from the candidate's list with
nothing to tell them it happened, while a missed duplicate is only noise —
see `jobsearch.dedup`'s module docstring for the full argument.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobsearch.dedup import (
    MINIMUM_PAIRS,
    SIMILARITY_THRESHOLD,
    DedupError,
    ExpiryFinding,
    Tombstone,
    _fixture_batch,
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
from jobsearch.offers import Offer


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
