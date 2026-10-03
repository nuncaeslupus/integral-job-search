---
id: t-9ae82a8e
title: "T225: partition holds back only an offer's own status, so a copy of a ruled-out or already-shown advert is presented again"
label: "T225: partition holds back only"
priority: 10
status: merged
---

Filed from a candidate session (test-mode 658fcce2).

`presentation_log.partition` withholds an offer whose **own** record is `screened_out`/`rejected` or that matches an exclusion. It does not look for another stored record of the same advert (same canonical URL, or same employer and title), so a rule-out or a `present()` row on one copy does not hold the others. Independent of T224: copies already in a store stay there. In session 658fcce2 the filter had to be done by hand (15 held as already seen, 14 as repeats).


## Acceptance gate

```bash
uv run pytest tests/test_sibling_hold_back.py tests/test_advert_identity.py tests/test_presentation_register.py -q
```
