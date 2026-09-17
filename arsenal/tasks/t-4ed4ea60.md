---
id: t-4ed4ea60
title: "T192: step-11-application should check a candidate's other generated CVs/letters before drafting from zero"
priority: 5
tags: [step-11-application]
---

Candidate note (2026-09-17, step `application`): "Todo lo que hayas aprendido
y que pueda servir para cualquier candidato, anótalo como una tarea para hacerlo
siempre. Por ejemplo, revisar otros currículums generados para aprender de lo que
ya funcionó (o por lo menos se usó) habría que hacerlo, para no generar los CV de
cero cada vez si ya se ha estado trabajando en uno. Lo mismo para las cartas.
Siempre adaptándolas al puesto y a la empresa, pero si se ha dedicado tiempo a
pulirlas, por lo menos valorar si sus ideas son buenas." — before drafting a new
CV or letter, review what has already been generated for this candidate (for
other offers, not just prior versions of the same offer) and weigh whether its
ideas are worth reusing or adapting, rather than starting from zero every time —
always still tailored to the specific posting and company.

`step-11-application`'s protocol today (`.claude/skills/step-11-application/SKILL.md`
§Preconditions) reads `cv/master.json`, the offer, `profile/stories.jsonl`, and
"previous versions in `cv/generated/<offer_id>/`" — that last one is scoped to
the *same* offer only. It never looks at a candidate's other offers' generated
documents. What happened this session only happened because the operator
manually pointed the assistant at one candidate's already-sent letter (Grafana)
and asked for its framing to be reused in three other drafts (Cohere, LiveKit,
Bolt.new) — the skill itself has no step that does this on its own, so the same
reuse would not happen unprompted next time.

Per a separate 2026-09-17 candidate note on the same principle ("Lo de usar scripts
para todo lo que se pueda automatizar en vez de usar tokens, también es
importante"), this should be backed by a script, not by the model re-reading N
full prior documents from memory each time: something that walks a candidate's
`cv/generated/*/v*/manifest.json` (plus the doc text) and prints a compact
per-offer digest — company/title, version count, distinguishing sections (e.g.
a "How I work" block), which `profile/stories.jsonl` episodes were cited — cheap
enough to run before every draft.

Ask: (a) a digest script doing the above; (b) a `step-11-application/SKILL.md`
protocol update instructing that the digest runs before drafting, and that good
ideas it surfaces are proposed for reuse (adapted to the new posting/company),
while keeping the existing "never include a story-bank episode without per-use
approval" rule intact for anything carried over from another offer's letter.

## Acceptance gate

<!-- Replace this with a fenced bash block. A gate that is only prose runs
     nothing, and a gate that runs nothing passes everything — `task_select.py`
     reports gate: false for a task with no block, so an unenforced gate is
     visible rather than quietly inert. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
# e.g. bash tests/prior_cv_digest_test.sh
false
```
