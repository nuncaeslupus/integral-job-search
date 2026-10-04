---
id: t-afd63f27
title: "T234: talent_es reads the advert page with a build-hash selector that now matches nothing, and a selector matching nothing on a 200 page is reported nowhere"
label: "T234: talent_es detail selector"
priority: 5
status: merged
---

Filed from a candidate session (test-mode 658fcce2).

`connectors/talent_es/connector.yaml` reads the advert body with `div.sc-f4dbceab-10`, a styled-components build hash. Measured 2026-10-02 on `https://es.talent.com/view?id=635737020307146631`: HTTP 200, 310,755 bytes, **0** elements with that class (the page's classes are now `sc-126c3eb4-*`); the committed `fixture/detail.html` has 2. The connector's own list section refuses hashed classes for exactly this reason and the detail section uses one. `last_verified` reads 2026-09-21.

Two fixes, and the second is the general one: a durable selector for the talent advert body, and a detail parse that yields no text from a 200 page being counted and printed per board, the way `off_aim` and `dropped` are — today it is indistinguishable from an advert with no body.


## Acceptance gate

```bash
uv run --extra dev pytest tests/test_detail_selectors.py tests/test_connectors.py tests/test_sourcing.py -q
```
