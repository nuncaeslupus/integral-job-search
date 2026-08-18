"""T4b acceptance tests for the raw ad corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobsearch.corpus import load_ads
from jobsearch.corpus_scope import TARGET_MIX, measure

TOLERANCE = 0.10


def test_raw_corpus_meets_size_and_language_mix() -> None:
    ads = load_ads()
    assert len(ads) >= 100, f"raw corpus has {len(ads)} ads, need >= 100"
    for lang, target in TARGET_MIX.items():
        count = sum(1 for ad in ads if ad["language"] == lang)
        assert abs(count - target) <= TOLERANCE * target, (
            f"{lang}: {count} ads, target {target} ±{TOLERANCE:.0%}"
        )


def test_every_language_slice_matches_its_declared_scope() -> None:
    """D-1: the Catalan slice is not a like-for-like remote-programming sample
    like ES/EN — it is Catalan IT ads at large, remote dimension mixed in
    rather than filtered for — and three documents say so independently:
    `status/plan.md`'s T4b row, `corpus/raw/README.md`'s "Known divergence"
    section, and this test's own `TARGET_MIX` (imported from
    `jobsearch.corpus_scope`, not restated here). Before this test existed, a
    plan-row edit or a README rewrite could silently re-narrow the Catalan
    slice back to "remote programming" while the other two documents kept
    saying otherwise — the exact silent-drift failure D-1 was filed over. This
    fails the moment any one of the three stops carrying the agreed scope,
    rather than trusting three hand-edited documents to stay in sync."""
    measured = measure()
    assert measured["corpus_language_slice_mismatch"] == 0, measured["mismatches"]


def test_every_raw_ad_carries_a_source_url() -> None:
    for ad in load_ads():
        assert ad["source_url"].startswith("https://"), ad["id"]


def test_ad_without_source_url_is_refused_at_load(tmp_path: Path) -> None:
    broken = tmp_path / "ads.jsonl"
    broken.write_text(
        json.dumps({"id": "x", "language": "es", "text": "hola", "source_url": ""}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no resolvable source_url"):
        load_ads(broken)
