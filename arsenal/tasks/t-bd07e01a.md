---
id: t-bd07e01a
title: "Close the pay-statement leftovers from #977"
label: "pay statement leftovers 3"
priority: 5
---

Review leftovers from #977, batched per policy G after its second review round (report on #977).

Fail-open in `integral.pay_transparency.states_own_pay`. Each returns sendable and must be refused:

1. A year word right after the earning verb makes a bare 19xx/20xx read as a year (regression from #977's first commit; refused on main before it): "Gano el 2000.", "Cobro el 1990.", "Me pagan el 1950.", "Em paguen el 1950.", "Cobro durante 2000", "I get paid until 2000".
2. Past earning forms missing from `_EARNS` (ES/CA parity; "I earned 2000." is refused): "Gané 2000.", "Vaig guanyar 2000.", "En 2024 gané 2000.", "El 2024 vaig guanyar 2000."

Fail-closed (sendable text refused):

3. `_UNIT` lacks ES/CA "releases": "Hago 3 lanzamientos a la semana.", "Faig 3 llançaments a la setmana."
4. Still open since #971/#974: ranges and expectations, e.g. "de 45 a 50k", "from 45k to 50k", "45k is my minimum.", "Entre 45 y 50k.", "I'd like to earn 45k", "Me gustaría ganar 45k", "M'agradaria guanyar 45k", "Mi suelo salarial es 50k".

Also still open: letters, CVs and interview scripts get no free-text pay sweep.

## Wanted

1: a number is not a year when the year word directly follows the earning word. 2: add the past forms. 3: add `lanzamient\w*` and `llançament\w*` to `_UNIT`. Every case becomes a test in ES, EN and CA.

## Acceptance gate

```bash
uv run --extra dev pytest tests/test_pay_transparency.py tests/test_form_answers.py -q
```
