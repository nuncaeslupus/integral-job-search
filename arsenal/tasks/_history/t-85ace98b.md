---
id: t-85ace98b
title: "T233: After sourcing, the ranked view is asked for instead of being the default, and a ranking that cannot order for missing data does not say what is missing"
label: "T233: After sourcing, the ranked"
priority: 5
status: merged
---

Filed from a candidate session (test-mode 658fcce2).

The owner: showing the offers ranked "debería ser el comportamiento por defecto. Aquí el problema es saber cómo ordenarlas o si te faltan datos para hacerlo bien." Step 7 closes by asking whether to see them ranked; go straight to the ranking. And when the ranker cannot separate offers because an input is missing (in this session: no weights, and no dimension for the kind of company he prefers), say which input is missing and what one answer would change. Related to T209, which is about recommending and about profile strengths.


## Acceptance gate

```bash
uv run --extra dev pytest tests/test_rank_missing_inputs.py tests/test_rank.py tests/test_rank_order_readings.py -q
uv run python -m integral.rank
python3 -c "import json,sys; m=json.load(open('status/evidence/T233.json')); sys.exit(0 if m['rankings_with_unordered_ties_and_no_named_missing_input']==0 and m['unseparated_rankings_ok']==1 and m['silent_when_reporter_is_empty']>0 else 1)"
```
