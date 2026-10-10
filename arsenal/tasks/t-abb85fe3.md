---
id: t-abb85fe3
title: "T288: T183 follow-up: full-page background raster passes the photo floors; veto flow not wired"
priority: 5
requires: [human:gate]
---

Imported from issue #664

Found by the second reader on #663 (F2, optional there).

- A full-page A4 background image (e.g. 1240×1754, aspect 0.707, Canva-style CV with a text layer) passes `photo_extract`'s floors and is returned as "the photo".
- The spec's remedy — show the candidate what was found and let them veto — is not wired: `ImportResult.photo` is never surfaced, step 11 doesn't read `cv/source/<doc>.photo.png`.
- `.claude/skills/step-01-intake/SKILL.md:115` still says the photograph is "collected by step 11", contradicting "never ask for one".

No impact yet: nothing consumes the photo. Must be fixed before the photo is rendered into an application (T181's `render_document(photo=...)`).

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
