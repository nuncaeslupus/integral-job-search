---
id: t-0925aafd
title: "T333: Fixture tools do not understand an after_text selector"
priority: 5
requires: [human:gate]
---

Imported from issue #772

Raised by the second reader on #767 (T254), outside that diff.

- `tools/excerpt_fixture.py` exits 1 on `connectors/talent_es` (`'div' names no class`) now that its detail body is selected by `css: div` + `after_text`. It also appends its "body truncated" marker to a body it did not cut (single `<p>`, 1,176 characters kept whole).
- `tools/annotate_connector_fixture.py` reads only `spec.css` and ignores `after_text`, so it annotates the wrong node for such a field.

Both tools should resolve a field through the engine's own selector path rather than re-reading `css`, and the marker should be written only when something was cut.

Suggested gate: `connector_packages_the_fixture_tools_cannot_process == 0`.

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
