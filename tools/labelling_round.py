#!/usr/bin/env python3
"""Which adverts a labelling round has to cover, and in what order.

T56's subset is closed at five dimensions, each needing ten evaluation labels.
Labels are placed per *advert*, so the round's real size is not 45 reads but
however many adverts carry marks for the five — a greedy cover over
`corpus/labelled/suggestions.json` answers that, and today it is eleven.

Prints the ids. `make labelling-round` feeds them to `labelling_page.py --only`,
which is the surface the labelling actually happens on.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

FIVE = [
    "remote_arrangement",
    "compensation_transparency",
    "contract_stability",
    "schedule_flexibility",
    "seniority_expectation",
]
FLOOR = 10
STORE = Path("corpus/labelled/ads.jsonl")
SUGGESTIONS = Path("corpus/labelled/suggestions.json")


def cover(dimensions: list[str], floor: int) -> tuple[list[str], dict[str, int]]:
    """Adverts to label, most-covering first, until every dimension reaches `floor`.

    Greedy, and greedy is enough: the shortfall it leaves is reported rather
    than assumed away, so a subset the corpus cannot floor says so instead of
    silently returning a short list.
    """
    lines = STORE.read_text(encoding="utf-8").splitlines()
    ads = {json.loads(line)["id"]: json.loads(line) for line in lines if line.strip()}
    marks = json.loads(SUGGESTIONS.read_text(encoding="utf-8"))["by_ad"]

    need = dict.fromkeys(dimensions, floor)
    for ad in ads.values():
        if ad["split"] == "evaluation":
            for label in ad["labels"]:
                if label["dimension"] in need:
                    need[label["dimension"]] = max(0, need[label["dimension"]] - 1)

    available = {
        ad_id: {m["dimension"] for m in ms if m["dimension"] in need}
        for ad_id, ms in marks.items()
        if ads.get(ad_id, {}).get("split") == "evaluation"
    }
    available = {a: d for a, d in available.items() if d}

    order: list[str] = []
    while any(v > 0 for v in need.values()):
        gain = lambda a: sum(1 for d in available[a] if need[d] > 0)  # noqa: E731
        best = max(available, key=gain, default=None)
        if best is None or not gain(best):
            break
        for d in available[best]:
            need[d] = max(0, need[d] - 1)
        order.append(best)
        del available[best]
    return order, {d: n for d, n in need.items() if n}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The adverts a labelling round must cover.")
    parser.add_argument("--ids", action="store_true", help="print only the ids, comma-separated")
    parser.add_argument("--floor", type=int, default=FLOOR)
    args = parser.parse_args(argv)

    order, shortfall = cover(FIVE, args.floor)
    if args.ids:
        print(",".join(order))
        return 0
    print(f"{len(order)} advert(s) cover {len(FIVE)} dimension(s) to {args.floor} labels each")
    for i, ad_id in enumerate(order, 1):
        print(f"  {i:2}. {ad_id}")
    print(f"  shortfall: {shortfall or 'none'}")
    return 0 if not shortfall else 1


if __name__ == "__main__":
    raise SystemExit(main())
