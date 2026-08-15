"""T4b acceptance tests for the raw ad corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobsearch.corpus import load_ads

TARGET_MIX = {"es": 60, "en": 25, "ca": 15}
TOLERANCE = 0.10


def test_raw_corpus_meets_size_and_language_mix() -> None:
    ads = load_ads()
    assert len(ads) >= 100, f"raw corpus has {len(ads)} ads, need >= 100"
    for lang, target in TARGET_MIX.items():
        count = sum(1 for ad in ads if ad["language"] == lang)
        assert abs(count - target) <= TOLERANCE * target, (
            f"{lang}: {count} ads, target {target} ±{TOLERANCE:.0%}"
        )


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
