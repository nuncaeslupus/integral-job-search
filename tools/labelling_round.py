#!/usr/bin/env python3
"""Build the T56 round-1 labelling document: 11 adverts, five dimensions, one note box each.

The eleven are a greedy cover — read them in order and all five dimensions reach
the floor of ten with no shortfall. Marks come from `corpus/labelled/suggestions.json`,
never from `Dimension.extraction.cues`: a labeller confirming cue output would make
`extraction_macro_f1` score the extractor against itself (D-2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from integral.dimensions import Dimension, load_dimensions

FIVE = [
    "remote_arrangement",
    "compensation_transparency",
    "contract_stability",
    "schedule_flexibility",
    "seniority_expectation",
]
FLOOR = 10
OUT = Path("status/specs/labelling-round-01.md")


def main() -> int:
    lines = Path("corpus/labelled/ads.jsonl").read_text(encoding="utf-8").splitlines()
    ads = {json.loads(line)["id"]: json.loads(line) for line in lines if line.strip()}
    suggestions = Path("corpus/labelled/suggestions.json").read_text(encoding="utf-8")
    marks = json.loads(suggestions)["by_ad"]
    dims = {d.id: d for d in load_dimensions() if d.id in FIVE}

    held = {d: 0 for d in FIVE}
    for ad in ads.values():
        if ad["split"] == "evaluation":
            for label in ad["labels"]:
                if label["dimension"] in held:
                    held[label["dimension"]] += 1

    cover = {
        a: {m["dimension"] for m in ms if m["dimension"] in FIVE}
        for a, ms in marks.items()
        if ads.get(a, {}).get("split") == "evaluation"
    }
    cover = {a: v for a, v in cover.items() if v}

    need = {d: FLOOR - held[d] for d in FIVE}
    order: list[str] = []
    while any(v > 0 for v in need.values()):
        best = max(cover, key=lambda a: sum(1 for d in cover[a] if need[d] > 0), default=None)
        if best is None or not sum(1 for d in cover[best] if need[d] > 0):
            break
        for d in cover[best]:
            need[d] = max(0, need[d] - 1)
        order.append(best)
        del cover[best]

    out = [_preamble(dims, held, order)]
    for i, ad_id in enumerate(order, 1):
        out.append(_advert(i, ads[ad_id], marks[ad_id], dims))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")

    unfindable = [
        f"{a}/{m['dimension']}"
        for a in order
        for m in marks[a]
        if m["dimension"] in FIVE and m["quote"] not in ads[a]["text"]
    ]
    short = {k: v for k, v in need.items() if v} or "none"
    print(f"{OUT}  ({len(order)} adverts, shortfall {short})")
    detail = " — " + ", ".join(unfindable) if unfindable else ""
    print(f"  quotes not locatable in their advert: {len(unfindable)}{detail}")
    return 0


def _rungs(dim: Dimension) -> str:
    return " · ".join(f"**{lv.value:g}** {lv.label.en}" for lv in dim.levels)


def _preamble(dims: dict[str, Dimension], held: dict[str, int], order: list[str]) -> str:
    rows = "\n".join(
        f"| `{d}` | {dims[d].label.en} | {held[d]} | {FLOOR - held[d]} | {_rungs(dims[d])} |"
        for d in FIVE
    )
    return f"""# T56 labelling round 1 — eleven adverts

The subset was decided cold on 2026-08-25 and is **closed**: these five dimensions and no
others. `extraction_macro_f1` will be the mean over exactly these, with the other twenty
named in `dimensions_below_floor`.

These eleven adverts are a greedy cover of the five. Worked in order they take every one
of them to ten labels with no shortfall — that is the whole round, not a first instalment.

| dimension | | held | needed | rungs |
|---|---|---|---|---|
{rows}

### How to answer

Each advert below has one note box. Write one line per dimension, using this shorthand —
it transcribes into `Label` rows without anyone guessing what you meant:

```
remote      confirm
pay         change 0.0        the figure is a maximum tarifa, not a salary
contract    delete            that quote is about the client's contract, not the role's
hours       new 0.7  "horari flexible de matí"
seniority   absent            the advert genuinely does not say
```

* **confirm** — the proposed value is right. Recorded as `source: confirmed`.
* **change `<value>`** — right dimension, wrong rung. Recorded as `source: edited`.
* **delete** — the quote does not evidence this dimension at all. No label is written.
* **new `<value>` "quote"** — the marks missed it. Quote **verbatim** from the advert so
  the span can be located. Recorded as `source: human`.
* **absent** — the advert says nothing about it. No label; this is not the same as
  `delete`, and neither is the same as a `0` rung, which is a positive statement that the
  advert says *on-site* or *fixed hours*.

Add `negated` to any line where the advert **denies** the dimension ("sense guàrdies",
"no es requereix experiència") rather than being silent. That distinction is a separate
measurement (T59) and it cannot be recovered later from the value alone.

### What is deliberately not here

* **No cue data.** No patterns, no cue values, no highlighting derived from them. Marks
  come from the read pass in `suggestions.json`, whose provenance is recorded. A labeller
  confirming cue output would make the gate score the extractor against itself (D-2).
* **Marks for the other twenty dimensions are omitted**, though several of these adverts
  carry them. The round is the five.
* **The 32 `blind_control` adverts are not here.** They are unmarked on purpose so blind
  agreement can be read against confirmed agreement — a different measurement, not cheap
  labels.

---
"""


def _advert(
    i: int, ad: dict[str, Any], ms: list[dict[str, Any]], dims: dict[str, Dimension]
) -> str:
    rows = "\n".join(
        f"| {dims[m['dimension']].label.en} | `{m['dimension']}` | **{m['value']:g}** "
        f"{_rung_name(dims[m['dimension']], m['value'])} | “{m['quote']}” |"
        for m in ms
        if m["dimension"] in FIVE
    )
    missing = [d for d in FIVE if d not in {m["dimension"] for m in ms if m["dimension"] in FIVE}]
    absent = (
        "\n\nNo mark was proposed for: "
        + ", ".join(f"`{d}`" for d in missing)
        + ". Say `new …` if the advert in fact states one.\n"
        if missing
        else "\n"
    )
    return f"""## {i}. {ad.get("title") or ad["id"]}

`{ad["id"]}` · {ad["language"]} · [source]({ad["source_url"]})

| dimension | id | proposed | quote |
|---|---|---|---|
{rows}
{absent}
**The advert, verbatim**

{_quote_block(ad["text"])}

---
"""


def _rung_name(dim: Dimension, value: float) -> str:
    exact = [lv for lv in dim.levels if abs(lv.value - value) < 1e-9]
    return exact[0].label.en if exact else "_(between rungs)_"


def _quote_block(text: str) -> str:
    return "\n".join("> " + line if line.strip() else ">" for line in text.splitlines())


if __name__ == "__main__":
    raise SystemExit(main())
