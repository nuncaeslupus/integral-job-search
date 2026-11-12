---
id: t-ea7e2acd
title: "review: CV/letter renderer passes every text field through as raw HTML"
priority: 5
requires: [human:gate]
---

Imported from issue #926

**Severity:** medium · **Confidence:** high · **Category:** correctness

**Where:** `src/integral/document_render.py:261-321, src/integral/document_render.py:17-22`

### Finding
By design `_render_block` interpolates block text unescaped. A contact entry `Ana Pérez <ana@example.org>` is emitted as a tag and the address disappears from the rendered CV, a bare `&` yields invalid markup, and any `<script>`/`<img onerror>` copied from an advert (employer name, quoted requirement) into a letter runs when the local HTML is opened.

### Evidence
Repro: document_render.render({'title':'CV','blocks':[{'type':'header','name':'Ana Pérez','contact':['Ana Pérez <ana@example.org>','R&D lead']},{'type':'summary','text':'error rate<script>alert(1)</script>'}]}) outputs `<p class="contact">Ana Pérez <ana@example.org> · R&D lead</p>` and the script tag verbatim. `validate()` (325-352) checks types only.

### Suggested direction
Escape by default and allow a small explicit inline vocabulary (b/strong/em/a) via a sanitiser; the '&' bug the docstring cites is a double-escape problem, not a reason to pass markup through.

_From the full repo review of 2026-11-11 (finding #7). Not fixed yet; verify before acting._

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
