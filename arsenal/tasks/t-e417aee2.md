---
id: t-e417aee2
title: "T142: Parametrised CV and letter rendering \u2014 page size, brand accent, margins"
priority: 5
tags: [docs]
workspace: CANDIDATE
issue: 387
---

## Acceptance gate

```gate
document_render_defects == 0
evidence: status/evidence/T142.json
key: document_render_defects
```

```bash
uv run --extra dev pytest tests/test_document_render.py -q
uv run --extra dev python -m integral.document_render
```

Step 11 writes a CV and a letter; today it writes Markdown and whatever a PDF
engine's defaults make of it. This replaces that with one HTML template plus a
render step whose few real decisions are parameters.

Built by hand for a live application on 2026-09-07 and carried through thirteen
revisions with the candidate (`docgen.py` + `build_docs.sh` + `style.css`, in that
candidate's `cv/generated/<offer>/v13/`); this task is to make it part of the tool.
**Take `docgen.py` as the reference implementation, not a starting sketch** — it is
about 150 lines and its shape held across every one of those revisions.

**A document is JSON; the HTML is an artefact nobody edits.** The block vocabulary is
deliberately small and none of it is candidate-specific: `header`, `summary`,
`section`, `job`, `project`, `bullets`, `grid`, `board`, and for a letter `letter`,
`to`, `text`, `sign`. Writing a CV for anyone is filling in one JSON file.

A `project` carries **two links, and they are not the same claim**: `href` goes to the
repository, `live` to a running deployment and renders as a `LIVE` badge. A reader who
can open the thing in ten seconds is worth more than one who can read its source, and a
project with only source must not look like one with both.

**One rule about text, learned by breaking it:** every text field carries inline HTML
and passes through as written; only `href` values are escaped. Escaping some fields
and not others shipped `EDUCATION &AMP; CERTIFICATIONS`, and it was caught by diffing
the text layer of the generated PDF against the hand-written one it was meant to
reproduce. **That diff is the acceptance evidence for the port** — the letter came out
identical character for character, which is a stronger claim than any test asserting
the template still renders.

**The parameters, and nothing else**

- `page_size` — **derived from the recipient's country, not asked**: Letter for
  US/CA/MX/PH/CL, A4 for everywhere else. An A4 CV printed on Letter is the kind of
  detail a European reader never notices and an American one does.
- `accent` — one hex colour. **Default: the employer's own brand colour**, which for
  this application was Grafana's `#ff671d`, read off their site.
- `margins` — line length is what a reader feels first.
- `body_size` — **one number sets the whole type scale.** Every other size is an `em`
  fraction of it. Nine absolute sizes drifted apart the first time the body grew: the
  small grid cells stayed at 8.6 pt and ended up smaller than the body text.
- `language` — the document's own, independent of the reader's UI language (T141).

**What it must hold, and why**

- The **PDF keeps a text layer `integral.ats` accepts** — no missing fields, no
  corruption markers. A CV an ATS cannot parse is a CV nobody reads.
- **The CV fits its page budget.** Two pages was reached by hand by tuning font size
  and leading against a fixed content set; the contract asserts the rendered page
  count, so a later content edit fails loudly instead of silently becoming three.
- A colour is applied **everywhere the template names an accent** — heading rules,
  section titles, link underlines — so a brand colour cannot be half-applied. This
  includes anything drawn rather than styled: **WeasyPrint renders inline SVG
  standalone and the document's CSS never reaches inside it**, so an SVG whose fills
  come from a stylesheet renders in its fallback colour and nothing warns you. The
  fills have to be attributes, which is why the accent is an argument to the
  generator and not only a CSS variable.
- **Page count is a cliff, not a slope.** A flex or table grid does not fragment: the
  last section either fits or moves whole, so freeing 20 mm changes nothing and
  freeing 36 mm removes a page. Any contract that tunes size against page count has to
  know this, or it reads a null result as "no effect".

Content stays where it is: this task renders, it does not write. The manifest
tracing every claim to its store entry (T45) is untouched.

