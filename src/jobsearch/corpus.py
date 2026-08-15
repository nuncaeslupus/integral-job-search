"""Raw ad corpus: read, write, and measure it.

Stdlib only, on purpose. The collector (`tools/collect_ads.py`) needs a scraping
stack; reading and validating the committed corpus must not, or the acceptance
gate stops running anywhere the boards are unreachable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# ponytail: src-layout repo root. Valid for an editable install, which is the only
# way this project is installed; a wheel would need the path passed in explicitly.
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "corpus" / "raw" / "ads.jsonl"
LANGUAGES = ("es", "en", "ca")


def load_ads(path: Path = DEFAULT_PATH) -> list[dict[str, Any]]:
    """Read the raw corpus. An entry without a source URL is refused at load."""
    ads: list[dict[str, Any]] = []
    if not path.exists():
        return ads
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        ad = json.loads(line)
        url = str(ad.get("source_url") or "")
        # https only: every board the collector reads serves https, and the acceptance
        # test asserts it — accepting http here would let a corpus load but fail the gate.
        if not url.startswith("https://"):
            raise ValueError(f"{path}:{lineno} ad {ad.get('id')!r} has no resolvable source_url")
        if not str(ad.get("text") or "").strip():
            raise ValueError(f"{path}:{lineno} ad {ad.get('id')!r} has no text")
        ads.append(ad)
    return ads


def save_ads(ads: list[dict[str, Any]], path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(ad, ensure_ascii=False, sort_keys=True) for ad in sorted(ads, key=_by_id)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _by_id(ad: dict[str, Any]) -> str:
    return str(ad["id"])


def language_counts(ads: list[dict[str, Any]]) -> dict[str, int]:
    return {lang: sum(1 for ad in ads if ad["language"] == lang) for lang in LANGUAGES}


def write_evidence(evidence: Path, ads: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Recompute T4b's measured numbers from the committed corpus."""
    if ads is None:
        ads = load_ads()
    measured = {"raw_ad_count": len(ads), "language_counts": language_counts(ads)}
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2) + "\n", encoding="utf-8")
    return measured


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("status/evidence/T4b.json")
    print(json.dumps(write_evidence(target)))
