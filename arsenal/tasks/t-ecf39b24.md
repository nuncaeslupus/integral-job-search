---
id: t-ecf39b24
title: "T228: A candidate cannot rule out an employer: an exclusion is text-matched, and most of an employer's adverts do not name its sector"
label: "T228: A candidate cannot rule"
priority: 10
---

Filed from a candidate session (test-mode 658fcce2).

The candidate ruled out restaurant-sector employers. One such employer has 41 stored adverts and the sector exclusion holds 9, because the other 32 never say what the company sells. Add an `employer:<name>` facet matched against the offer's company (normalised: JobFluent appends ` logo`, and titles carry ` en <Empresa>`), applied by `source()` and `partition` like any other exclusion.


## Acceptance gate

<!-- Replace this with a fenced bash block. A gate that is only prose runs
     nothing, and a gate that runs nothing passes everything — `task_select.py`
     reports gate: false for a task with no block, so an unenforced gate is
     visible rather than quietly inert. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
# e.g. bash tests/surface_probe_test.sh
false
```
