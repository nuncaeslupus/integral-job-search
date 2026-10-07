---
id: t-f8a66d6c
title: "T266: One half of the seeding vocabulary still compares raw, so a respelt requester key leaks its city"
priority: 5
requires: [human:gate]
---

Imported from issue #530

Round 9's second reader on #520 reproduced this against `d9feaa73`.

## The claim that is false

Round 8's F2 made `_seeds_a_block` normalise both halves of the seeding vocabulary, and
the commit message says both halves normalise now. `src/integral/connector_contract.py:849`
still does the raw membership test:

```python
introduced_by in REQUESTER_OBJECT_KEYS
```

So `Custom`, `custom_ids` and `CUSTOMIDS` get no trailing run, and `"clientCity":"Barcelona"`
survives the scrub where the lowercase `custom` redacts it. **`custom_ids` is a spelling the
round-8 commit message names as fixed.**

## Why the audit cannot see it

`test_every_seeding_respelling_seeds` asserts the **predicate** `_seeds_a_block`. The
predicate is a proxy for the sweep, and line 849 is a second, independent spelling of the
same decision that the predicate never reaches. `tests/test_connector_contract.py:1936`
re-implements that same raw comparison, so the test agrees with the defect.

The fix is one line at 849 plus the test asserting the **sweep's output** over respellings
rather than the predicate's verdict. Two near-free gaps in `_respellings` while in there:
it never generates `key.lower()`, and the separator only ever goes after the first
character, so `customids` and `custom_ids` are not among the representatives it tests.

Found by the round-9 reader on #520; merged anyway by the owner's explicit decision, with
the finding queued here rather than taken as another review round.

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
