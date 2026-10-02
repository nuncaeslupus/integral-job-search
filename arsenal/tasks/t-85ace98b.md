---
id: t-85ace98b
title: "T233: After sourcing, the ranked view is asked for instead of being the default, and a ranking that cannot order for missing data does not say what is missing"
label: "T233: After sourcing, the ranked"
priority: 5
---

Filed from a candidate session (test-mode 658fcce2).

The owner: showing the offers ranked "debería ser el comportamiento por defecto. Aquí el problema es saber cómo ordenarlas o si te faltan datos para hacerlo bien." Step 7 closes by asking whether to see them ranked; go straight to the ranking. And when the ranker cannot separate offers because an input is missing (in this session: no weights, and no dimension for the kind of company he prefers), say which input is missing and what one answer would change. Related to T209, which is about recommending and about profile strengths.


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
