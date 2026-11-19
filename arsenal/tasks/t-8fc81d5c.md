---
id: t-8fc81d5c
title: "Close the current-pay leak class left over from #956"
label: "current pay leak class"
priority: 5
---

Review leftovers from #956 (pay transparency), batched per policy G after its second review round. Full cases in the two second-reader reports on #956.

Fail-open in `integral.pay_transparency.current_pay_defects`, today a list of own-pay patterns:

1. A label and its figure split across clauses: "Current salary: 38k", "Salario actual: 38.000 €", "Sou actual: 38.000 €", "My current salary, 38000 euros.", "My current salary and bonus total 45000 euros."
2. First-person phrasings missing, unevenly by language: "I'm paid 38k.", "I currently earn 38k.", "I was earning 38000 euros.", "My base is 38k.", "Me pagan 38000 euros.", "Suelo cobrar 38000 euros.", "Em paguen 38.000 €.", "Cobrava 38.000 euros.", "Percebo 38.000 euros."
3. An expectation word anywhere in the clause cancels the refusal: "Mi salario actual es 38000 euros con variable por objetivos.", "I earn 38000 plus a target bonus."
4. A figure in words: "Treinta y ocho mil euros es mi salario actual."
5. Letters, CVs and step-12 interview scripts are protected by skill prose only.

Fail-closed: "Mi salario deseado es 45000 euros.", "My ideal salary is 45k.", "El meu sou ideal és 45.000 €." are refused.

## Wanted

Close the class with one rule, not more patterns (an enumeration has no last element). Invert the default: a pay figure in a cited row or answer is sendable only when the row is clearly an expectation or a floor in ES/EN/CA, judged on the row as a whole; otherwise it is refused. Apply the same check to the letter, CV and interview-script lines where they already pass a document sweep. Every case above becomes a test, in all three languages.

## Acceptance gate

```bash
uv run --extra dev pytest tests/test_pay_transparency.py -q
```
