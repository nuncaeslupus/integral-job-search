---
id: t-41dfc5c1
title: "Close the publisher-kind leftovers from #982"
label: "publisher kind leftovers 2"
priority: 5
---

Review leftovers from #982, batched per policy G after its second review round (report on #982, round 2).

In `integral.publisher_kind`:

1. The one-word guard (`len(words) > 1`) in the negation-across-comma rule is unpinned. Add "No English, you will work at the end client or remotely" as a consultancy fixture, with ES and CA twins.
2. A negation still crosses a comma when the cue's segment is one word followed by o/or/ni and a verb clause: "Sin experiencia previa, ETT líder busca mozos o carretilleros" reads unknown but is an agency. Extend the negation only when the cue sits inside the list.
3. `_PART` accepts adjective-like -ed words: "our client focused approach" reads as a placement.
4. From #965/#982 round 1: "for our client's success" and "work with the client to gather requirements" read consultancy; "don't"/"doesn't" are not negators.

## Wanted

Each case becomes a test in ES, EN and CA; prefer closed rules to lists.

## Acceptance gate

```bash
uv run --extra dev pytest tests/test_publisher_kind.py tests/test_sourcing_exclusions.py -q
```
