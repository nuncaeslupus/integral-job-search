---
id: t-a3f7ad2a
title: "Close the pay-statement leftovers from #981"
label: "pay statement leftovers 4"
priority: 5
---

Review leftovers from #981, batched per policy G after its second review round (report on #981, round 2).

In `integral.pay_transparency.states_own_pay`, these send but should be refused:

1. "Vam guanyar 2000." (first-person plural past, CA).
2. "Vaig  guanyar 2000." (two spaces): write `vaig\s+guanyar`.
3. "Cobro, el 2000." / "Gané, el 2000.": a comma between the earning word and the year word.

Fail-closed (sendable text refused):

4. "Quiero ganar 45k." reads as an expectation and should send (with EN/CA twins: "I want to earn 45k.", "Vull guanyar 45k." already sends).

Still open from #977: expectations refused since #971/#974 (item 7 of t-bd07e01a), and no free-text pay sweep for letters, CVs and interview scripts.

## Wanted

Each case above becomes a test in ES, EN and CA; close with closed rules rather than more words.

## Acceptance gate

```bash
uv run --extra dev pytest tests/test_pay_transparency.py tests/test_form_answers.py -q
```
