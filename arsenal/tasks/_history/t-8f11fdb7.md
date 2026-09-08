---
id: t-8f11fdb7
title: "T110: method: POST with no body_json produces a POST with no Content-Type"
priority: 5
status: merged
---

## Acceptance gate

```gate
bodyless_posts_sent_without_a_content_type == 0
evidence: status/evidence/T110.json
key: bodyless_posts_sent_without_a_content_type
```

```bash
uv run python -m integral.bodyless_post \
  && uv run python -m pytest tests/test_bodyless_post.py \
       tests/test_connectors.py::test_a_post_with_no_body_is_refused_at_load_or_carries_a_content_type \
       tests/test_connectors.py::test_the_schema_states_a_verdict_for_both_directions -q
```

**One heading, both fences.** The import template's placeholder left a second
`## Acceptance gate` further down, and `gate_run.sh` reads the **first** such
section: with the executable block under the second heading it reported
`gate: prose-only — NOTHING WAS EXECUTED` while the evidence half passed, which
is the shape AGENTS.md names ("a gate that runs nothing passes everything") with
a green metric sitting on top of it. Found by this task's second-reader review.

Transcribed from `status/plan.md`'s row for this task, which declared this
metric before the task was imported. The name is the plan's, not a new one:
inventing a second name for a declared metric is a mistake this repository has
made four times, and `test_the_committed_plan_and_queue_agree` fails it.

Imported from issue #299

Found by the second-reader audit of #295 (T89). Latent, not live — nothing in the library declares this shape today.

`_only_a_post_carries_a_body` refuses a body without a POST, but not a POST without a body. `build_list_requests` then takes the `body_json is None` branch and returns `ListRequest(method="POST", headers={}, body=None)` — a bodyless POST with **no `Content-Type`**, which several back ends answer 400 or 415 to.

## Scope

Either refuse it at load — a POST with no body is almost certainly a mistake in a connector file — or state in the schema that it is legal and what it means. It is currently neither, which is the actual defect: the schema has an opinion about one direction and none about the other.

## Chosen: refused, in both places

`_only_a_post_carries_a_body` is now `_a_post_and_a_body_imply_each_other` and
says both halves. The other option — bless the shape and give it a content type
— was not taken, and the reason is the same one that makes `Content-Type`
derived rather than declared: a connector may not name a header, so the header
follows from the body's form and there is no form to follow when there is no
body. Blessing a bodyless POST would mean the schema deriving a header from
nothing, or a connector naming one, and the second is the door `body_json`
exists to keep shut.

The refusal is repeated in `build_list_requests`, for the reason
`build_list_urls` repeats its clamp: an object made with `model_copy(update=…)`
never met the validator, so the property is kept where the request is made and
not only where the file is read.

`{}` stays legal. The schema's test is `body_json is None`, so an empty mapping
is a declared body with a content type to derive; "no body" and "an empty body"
are different documents and only the first is this task's shape.

## The ticked plan row belongs to the archive commit, not to a later one

`status/plan.md`'s T110 row is ticked in this diff while the task file is still
in `arsenal/tasks/`, so a **pre-archive** working tree fails `plan_v2`'s
`wrongly_ticked_rows` — "T110 has a ticked plan row and is still `open` on the
board" — and that is the one thing `make host-gate` reports red here. It is not
a defect and it must not be fixed by unticking the row: `open_task_pr.sh` moves
the task file into `_history/` with `status: merged` and runs the host gate
**over that tree**, in the same commit, and D-27's other half then requires the
tick. Both directions measured on this branch rather than assumed:

```text
archived + ticked    → violations: []
archived + unticked  → ['T110 is archived as merged and its plan row reads `☐`, not `☑`']
```

`status/evidence/S8.json` is byte-identical to `HEAD`'s under the archived tree,
so it is deliberately **not** in this diff. A pre-archive copy of it — which
records the violation above — must never be staged; restore it from `HEAD` if a
local gate run leaves it dirty.

The acceptance gate is at the top of this file — one heading carrying the
metric fence and the executable one, for the reason recorded there.
