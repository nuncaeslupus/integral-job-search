---
id: t-ad6bc8ad
title: "T261: A selector cannot take part of a text node, so arbeitsagentur.de titles arrive with a rendering artefact"
priority: 5
requires: [human:gate]
---

Imported from issue #356

Found by the 2026-09-06 connector survey (`connectors/ruled-out.yaml`, `engine_gap_selector`).

`arbeitsagentur.de` — the German federal employment agency, rank 1 on the wanted list, and **DE has zero connectors** — passes every test. robots allows `/jobsuche/suche?was=python` and `/jobsuche/`. It is Angular but server-side rendered: the GET returns 376 KB carrying 25 real results with stable class names.

Everything maps except the title:

| field | selector | value |
|---|---|---|
| item | `li.listeneintrag` | ✓ |
| detail_url | `a[role="button"]` + `href` | ✓ |
| company | `.firma-lane` | ✓ `R+V Allgemeine Versicherung AG` |
| location | `.ba-icon-location-full` | ✓ `Wiesbaden` |
| **title** | — | **every candidate carries a prefix** |

There are exactly three elements holding the title, and all three are polluted:

```
.titel-lane                     ->  "1. Python Entwickler (m/w/d)"
h2.sr-only                      ->  "1: Python Entwickler (m/w/d) bei R+V Allgemeine Versicherung AG"
button.vormerken-button[title]  ->  "Stelle vormerken: Python Entwickler (m/w/d)"
```

A connector can select any of them and can take an attribute. It cannot take a **substring**, so every offer would reach a candidate titled `1. Python Entwickler (m/w/d)`.

## Same shape as the gap already recorded one grammar over

`engine_gap_json` in the same file holds nine boards blocked because a JSON path cannot name an array element. This is the HTML twin: a selector cannot name a substring. Both are deliberate — `SimpleSelector` and `JSON_PATH` are documented as *"intentionally too small a language to smuggle anything through"*, and that is a property worth keeping.

**So the fix is not "add regex to the selector".** That reintroduces exactly what the grammar exists to exclude, and a connector-supplied regex is a denial-of-service surface before it is anything else. Something narrow and non-executable is wanted — a fixed prefix to drop, an nth-child index, or picking the *last* text node rather than the concatenation. The last of those would solve this board without adding any expression syntax at all, since in all three elements the title is the final span.

Whichever is chosen, the negative control matters: a connector that declares a prefix which is **not** present must not silently return the whole string.

## Payoff

DE gains its first connector, and it is the federal employment agency — national coverage, all sectors, public-sector terms. `stepstone.de` is the other DE candidate and is unmapped; it may or may not have the same problem.

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
