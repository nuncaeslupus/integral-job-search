---
id: t-8f11fdb7
title: "T110: method: POST with no body_json produces a POST with no Content-Type"
priority: 5
requires: [human:gate]
---

Imported from issue #299

Found by the second-reader audit of #295 (T89). Latent, not live — nothing in the library declares this shape today.

`_only_a_post_carries_a_body` refuses a body without a POST, but not a POST without a body. `build_list_requests` then takes the `body_json is None` branch and returns `ListRequest(method="POST", headers={}, body=None)` — a bodyless POST with **no `Content-Type`**, which several back ends answer 400 or 415 to.

## Scope

Either refuse it at load — a POST with no body is almost certainly a mistake in a connector file — or state in the schema that it is legal and what it means. It is currently neither, which is the actual defect: the schema has an opinion about one direction and none about the other.

## Acceptance gate

<!-- This task came from an issue, so its "gate" is prose. Write a real check
     below, then DELETE the `requires: [human:gate]` line in the front matter.
     Until that line is gone the selector will not offer this task, which is
     deliberate: a prose gate runs nothing, and a gate that runs nothing passes
     everything. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
false
```
