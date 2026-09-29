---
id: t-a89c7d6e
title: "T206: Relocation and reach read 'satisfied' over a move the commute radius cannot decide"
priority: 10
status: merged
---

Filed from #574's round-1 second reader, F3.

A candidate with a commute radius `("Barcelona",)` and relocation `no`, and an on-site
offer in PL with no region or with a region named like a radius entry (a homonym).
`filter_hard_constraints` passes `home_country=None` there, because the radius cannot say
whether the job means moving. `relocation` and `reach` then fall back to the advert's
`requires_relocation` flag, find nothing to refuse, and `annotate` reports them as
`satisfied` ("nothing in this advert conflicts"). The offer is still withheld by
`location`, but the sentence the candidate reads reports a guess as a cleared check.
That breaks `outcome_for`'s rule: a decided answer is never reported as undecided, and
the reverse holds too.

The rule: in that case each field is asked both ways, moving and not moving. Its verdict
is reported only if the two answers agree. If they disagree, the field is `Uncomparable`
(`unplaced`). A candidate who would move to PL is satisfied either way and is not
withheld for it.

Related, and decided as **no change**: a candidate willing to relocate to PL still has an
unflagged Kraków vacancy withheld by `location`. A stated radius governs every on-site
offer the advert does not flag as a move, at home as abroad. An unflagged Madrid vacancy
is refused on `location` for a candidate who would move anywhere (#550). Presenting
Kraków there would also present it to a candidate whose relocation is unstated. The
`Location` docstring now says so.

## Acceptance gate

```bash
uv run python -m integral.candidate
```
