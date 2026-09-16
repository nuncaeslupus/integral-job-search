---
id: t-1b6d84af
title: "T182: Take the document's accent colour from the employer's own site, with a contrast-safe text variant"
priority: 10
deps: [t-9c2e05d7]
workspace: CANDIDATE
tags: [step-11-application]
---

## Acceptance gate

```bash
uv run --extra dev pytest tests/test_brand_palette.py -q
```

## Where this comes from

The DOMMA documents shipped with an accent colour I invented (`#7a5c8e`), and
the candidate asked the obvious question — *"los colores, son los corporativos
de DOMMA?"* — which had the honest answer "no". Measuring the real ones took one
browser call over `getComputedStyle`, counting how many elements carry each
colour:

| | |
|---|---|
| `#101637` | navy, dominant ink — 2440 elements |
| `#1c296a` | secondary blue |
| `#ec504e` | coral, the only accent |
| `#f8f7f5` | cream |
| `#bbbcca` | lilac-grey |

A document in the employer's own palette reads as addressed to them. One in a
palette the assistant liked reads as a template.

**The catch, and it is why this is a task rather than a habit**: a brand accent
is chosen for large type and buttons, and is usually illegible as body text.
`#ec504e` on white is **3.7:1** — below WCAG AA for small text. Darkened to
`#c93b39` it is ≈4.9:1. Decorative rules keep the exact brand colour, since
contrast does not apply to them.

## What to build

A step in the application flow that, given the employer's site:

- extracts the palette by element frequency (the dominant ink, the accent, the
  paper tint) rather than by scraping a style guide that usually does not exist;
- emits both the exact accent and a **darkened text variant** meeting 4.5:1 on
  the document's paper colour, and says which is which;
- **records the measurement in `trazabilidad.md`**, so a later session does not
  have to re-derive it — and so the candidate can see the colours are theirs.

When the site cannot be read, fall back to the neutral palette and say so. A
guessed brand colour is worse than no brand colour.

## Tests

`test_text_variant_meets_aa` — the emitted text colour is ≥ 4.5:1 against paper
for every fixture palette, including ones already dark enough to pass unchanged.

`test_decorative_variant_is_the_unmodified_brand_colour`.

`test_unreadable_site_falls_back_and_says_so`.

## Location

Service: **CANDIDATE** · Size: S

Code: `src/integral/brand_palette.py`
