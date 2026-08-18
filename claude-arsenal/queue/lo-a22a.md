# T44: Ranking presentation — the offer card as a filled template

## Acceptance gate

```gate
provisional_rankings_unlabelled == 0
evidence: status/evidence/T44.json
key: provisional_rankings_unlabelled
```

```bash
echo "no gate command defined for T44 — replace this line with the command that writes status/evidence/T44.json" >&2; exit 1
```

## What this is

Presentation is half of step 9's specification, not a rendering detail. An
ordering nobody can read is not a result.

The card: title and employer; the facts as bullets — pay (gross, and roughly
what it leaves per month, T33), hours, location and arrangement, contract — and
then **one line of what actually matters about this one**, in plain words and
including the bad part: *"full remote, pay is good, but it is a gun factory."*
That sentence is what the candidate reads; the bullets are what they check
afterwards. A handful at a time, not forty. Lead with the offer and the one
thing that most moved it, never with a score.

## The rule that matters

**Unknown is shown as unknown, not as neutral.** An advert silent on hours is
not an advert promising good ones.

**A provisional ranking that is not labelled provisional is a defect, not a
shortcut** — the L1 ranking says so, once, in one line, along with what would
sharpen it.

Where the list is rendered as a page it is a **template filled from the
normalised offer JSON** — built once, filled fast, never assembled a paragraph
at a time by a model.

## Tests

Write these RED before any production code:

`test_l1_ranking_is_labelled_provisional` in `tests/test_presentation.py`;
`test_unknown_field_renders_as_unknown_not_neutral`;
`test_card_is_filled_from_json_not_generated_per_offer` — rendering the same
offer twice is byte-identical.

## Location

Service: **MATCH** · Size: M · Depends: T18, T19, T33

Design: `status/plan.md` (MATCH) · Spec: `status/spec-v2-steps.md` step 9
