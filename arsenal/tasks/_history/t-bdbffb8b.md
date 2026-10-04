---
id: t-bdbffb8b
title: "T241: Reports and dashboards have no shared visual style"
label: "T241: one shared report style"
priority: 10
status: merged
---

Filed from a candidate session (test-mode 658fcce2).

## What happened

The owner's remark, on being handed an applications board: the project has not talked about UI,
and if it is going to produce reports or dashboards they should follow similar patterns or one
style.

Today there is none to follow. `src/integral` holds no stylesheet and no HTML template. The only
HTML generator in the repository is the vendored reader for specs and plans
(`.claude/skills/init/assets/scripts/create_reader.py`), which is the bundle's and not ours to
restyle. The ranking skill already requires that a rendered list be "a template filled from the
normalised offer JSON", and nothing provides that template.

## What is missing

- One stylesheet, with light and dark from `prefers-color-scheme`, the colour tokens named once
  (surface, ink, muted, line, accent, positive, negative), and the handful of components a report
  needs: summary tiles, a card, a status chip, a three-column fact grid that collapses on a phone.
- One function that wraps a body in the page shell, so a second report cannot drift from the first.
- Every page self-contained: no external font, script or stylesheet. A candidate's report is
  personal data and must render offline, from a file.
- A check that every HTML page the package writes goes through that function.


## Acceptance gate

```bash
uv run --extra dev pytest tests/test_report_style.py -q
```
