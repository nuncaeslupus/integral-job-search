---
id: t-ead7ae56
title: "T274: No reach filter over stored offers, and the obvious one rejects an offer for an absent location field"
priority: 5
requires: [human:gate]
---

Imported from issue #547

## What happens

A candidate whose constraints forbid relocation needs the offer set split into what they can actually take and what they cannot. Nothing in `src/integral/` does that over stored offers — `eligibility.py` reads requirements the *advert* states (citizenship, work permit, clearance), which is the other direction.

Done ad hoc over a live run, the obvious implementation is wrong in the one direction that costs the candidate the most: **it reads the location field, and an offer whose location field is empty is indistinguishable from an offer abroad.**

## Measured

Nineteen Barcelona adverts landed in the "out of reach" bucket because their board states the location only on the advert page (see #546) and the list row carries none. They were the strongest on-target material in the run — the candidate's own city, their exact role — and the filter put every one of them in the pile it was going to discard.

```
                before   after
Spain              86      105
out of reach      129      110
```

## The evidence the absent field ignores

The board's own config states its market. `jobfluent_es` declares `locale: es` and its `url_pattern` is `empleos-barcelona` — the board lists nothing else. An empty location field on a row from that board is a missing *field*, not a statement that the job is abroad.

## Suggested shape

Buckets: `in_country`, `remote`, `region`, `out_of_reach`, plus an explicit **`unplaced`** for a row whose location cannot be established at all. Fall back to the connector's declared locale before concluding a row is out of reach, and never let an absent field resolve to the bucket that discards it — an unknown belongs in `unplaced`, reported, not silently filed as a rejection.

This mirrors the rule `liveness.presentable` already enforces: an offer with no check is withheld **on the absence** rather than presented as live. Reach should withhold on the absence rather than reject on it.

## Acceptance gate

```bash
uv run python -m integral.reach_filter --evidence
```

`offers_rejected_on_an_absent_field == 0`, over the stored offer set, with `unplaced` reported separately and a floor under the number of offers compared so a clean zero cannot rest on an empty scan.

## Acceptance gate

<!-- This task came from an issue, so its "gate" is prose. Write a real check
     below, then DELETE the `requires: [human:gate]` line in the front matter.
     Until that line is gone the selector will not offer this task, which is
     deliberate: a prose gate runs nothing, and a gate that runs nothing passes
     everything. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
false
```
