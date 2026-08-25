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
    silently returning a short list. That report is the useful half — it is what
    distinguishes "label more" from "collect more", and only one of those is
    work a person can do this evening.

    An (advert, dimension) pair that already carries a label contributes nothing:
    the mark has been decided. An advert can therefore be picked again for the
    dimensions it still has marks for, and the page shows its banked labels as
    already-confirmed rather than asking twice.
    """
    lines = STORE.read_text(encoding="utf-8").splitlines()
    ads = {json.loads(line)["id"]: json.loads(line) for line in lines if line.strip()}
    marks = json.loads(SUGGESTIONS.read_text(encoding="utf-8"))["by_ad"]

    need = dict.fromkeys(dimensions, floor)
    placed: dict[str, set[str]] = {}
    for ad in ads.values():
        placed[ad["id"]] = {label["dimension"] for label in ad["labels"]}
        if ad["split"] == "evaluation":
            for label in ad["labels"]:
                if label["dimension"] in need:
                    need[label["dimension"]] = max(0, need[label["dimension"]] - 1)

    available = {
        ad_id: {m["dimension"] for m in ms if m["dimension"] in need}
        - placed.get(ad_id, set())
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


def below_floor(floor: int) -> list[str]:
    """Every ad-side dimension the evaluation split cannot yet score."""
    from integral.dimensions import load_dimensions
    from integral.extraction import ad_side, evaluation_labels
    from integral.harness import load_store

    counts: dict[str, int] = {}
    for _, label in evaluation_labels(load_store()):
        counts[label.dimension] = counts.get(label.dimension, 0) + 1
    return sorted(d.id for d in ad_side(load_dimensions()) if counts.get(d.id, 0) < floor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The adverts a labelling round must cover.")
    parser.add_argument("--ids", action="store_true", help="print only the ids, comma-separated")
    parser.add_argument("--floor", type=int, default=FLOOR)
    parser.add_argument(
        "--dimensions",
        default="",
        help="comma-separated ids; 'below-floor' takes every dimension that cannot yet "
        "be scored. Default: the declared subset.",
    )
    args = parser.parse_args(argv)

    if args.dimensions == "below-floor":
        wanted = below_floor(args.floor)
    elif args.dimensions:
        wanted = [d.strip() for d in args.dimensions.split(",") if d.strip()]
    else:
        wanted = FIVE
    order, shortfall = cover(wanted, args.floor)
    if args.ids:
        print(",".join(order))
        return 0
    reached = len(wanted) - len(shortfall)
    print(
        f"{len(order)} advert(s) cover {reached} of {len(wanted)} "
        f"dimension(s) to {args.floor} labels each"
    )
    for i, ad_id in enumerate(order, 1):
        print(f"  {i:2}. {ad_id}")
    if shortfall:
        print("  the corpus cannot floor these — they need collecting, not labelling:")
        for d, n in sorted(shortfall.items(), key=lambda x: -x[1]):
            print(f"    {d:28} still short {n}")
    else:
        print("  shortfall: none")
    return 0 if not shortfall else 1


if __name__ == "__main__":
    raise SystemExit(main())
