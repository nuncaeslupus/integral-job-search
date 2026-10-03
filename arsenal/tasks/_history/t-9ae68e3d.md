---
id: t-9ae68e3d
title: "T246: Pay enters the ranking unconverted, and a stated band can be stored as none"
label: "T246: normalise pay for ranking"
priority: 10
status: merged
---

Filed from a candidate session (test-mode 658fcce2). The owner's instruction for this round: the
project does a hard job to be able to sort offers, and anything that keeps it from sorting
correctly at this point is a design flaw.

## What happened

Among the eleven offers, one band was in USD while the candidate's weights are in EUR; it reached
`rank()` as a bare per-month number: `Candidate.salary_per_month` carries no currency, and
`require_pay_coherence` checks only a band's point against the band, skipping a band in another
currency. Nothing converts it and nothing refuses it. Another advert stated a USD band in its text and was stored with
`salary: null`, so it counted as unpaid. Six of eleven had no published pay and therefore no
basis for comparison at all.

## What is missing

- One conversion step into the weights' currency, dated, before any pay reaches the sort; refuse,
  rather than compare, when no rate is available.
- Extraction re-reads the advert text for a band when the source left `salary` empty.
- For an offer with no published pay, an estimate with its source and range (role, level, country),
  marked as an estimate — or the offer is ordered among the unpaid ones and said to be.


## Acceptance gate

```gate
unconverted_pay_reaching_rank == 0
evidence: status/evidence/T246.json
key: unconverted_pay_reaching_rank
```

```bash
uv run --extra dev pytest tests/test_pay_normalise.py tests/test_pay_dominance.py tests/test_rank.py -q
uv run --extra dev python -m integral.pay_normalise
python3 -c "import json,sys; m=json.load(open('status/evidence/T246.json')); sys.exit(0 if m['unconverted_pay_reaching_rank']==0 and m['offers_checked']>=10 and m['unconverted_detected_when_planted']==1 else 1)"
```

The `bash` block regenerates `status/evidence/T246.json` and checks its denominator and that
the audit can rise; the `gate` block asserts the metric. The no-published-pay choice is the
second option the task allows: the offer is ordered among the unpaid ones and the ranking
says so (`unpaid_offers`), with no estimate.
