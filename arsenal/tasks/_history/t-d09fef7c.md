---
id: t-d09fef7c
title: "T205: A commute radius compares region names byte for byte, so `Krakow` is outside `Kraków`"
priority: 10
status: merged
---

`_violates_location` asked `offer.region not in field_value.commutable_regions`: an
exact string test. A radius of `("Kraków",)` refused an on-site offer whose region the
advert spelled `kraków`, `KRAKÓW` or `Krakow`, and a decomposed `Kraków` too. The
same shape splits the supported languages: a Spanish or Catalan advert writes `Málaga`,
an English board serving the same vacancy writes `Malaga`, and only one of them was
inside the radius. Since #574 the relocation half of the filter reads the same
comparison, so a foreign offer whose region matched only after normalisation was
`removed` there instead of held `unplaced`.

Fail-closed — offers lost, not leaked — and the fix must stay that way: merging two
spellings is the fail-open direction, because a wrong merge presents an offer outside
the radius.

**The rule.** An offer's region is compared with each `commutable_regions` entry under
Unicode's canonical caseless form (§3.13 D145, `NFD(casefold(NFD(x)))`), at every site
that reads the radius:

- equal there → **inside**;
- equal only once every `General_Category=Mn` character is also removed → **maybe**:
  the offer is held `unplaced`, never presented as reachable, because accent-stripping
  merges real, distinct places (`Habo` and `Håbo` are two Swedish municipalities);
- otherwise, or when the name is nothing but marks and whitespace → **outside**.

Out of scope, both fail-closed: letters Unicode does not decompose (`Łódź` ≠ `Lodz`,
`Ø` ≠ `O`) and exonyms (`Gerona`/`Girona`, `Perpignan`/`Perpinyà`) — the repo has no
gazetteer, and `eligibility.py` says in so many words that it is not one.

Adversarial fixtures are written by a second session from the rule above, before it
reads the implementation (CLAUDE.md, "Fixtures for a correctness-critical gate").

## Acceptance gate

```bash
uv run python -m integral.candidate
```
