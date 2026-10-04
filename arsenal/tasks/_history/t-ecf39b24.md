---
id: t-ecf39b24
title: "T228: A candidate cannot rule out an employer: an exclusion is text-matched, and most of an employer's adverts do not name its sector"
label: "T228: A candidate cannot rule"
priority: 10
status: merged
---

Filed from a candidate session (test-mode 658fcce2).

The candidate ruled out restaurant-sector employers. One such employer has 41 stored adverts and the sector exclusion holds 9, because the other 32 never say what the company sells. Add an `employer:<name>` facet matched against the offer's company (normalised: JobFluent appends ` logo`, and titles carry ` en <Empresa>`), applied by `source()` and `partition` like any other exclusion.


## Acceptance gate

```bash
uv run pytest tests/test_employer_exclusion.py -q
```
