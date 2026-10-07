---
id: t-7c9e2ea9
title: "T258: build_list_urls ignores pagination.start with no test noticing — a 0-indexed board's URLs silently start at page 1"
priority: 5
requires: [human:gate]
---

Imported from issue #340

Found by the fourth independent read of #338 (T109), finding F-D. Pre-existing, out of that PR's scope, filed so it does not live only in a PR comment.

## The defect

`build_list_urls` (`src/integral/connectors.py:1578`) computes its page numbers as `start + offset`. **Mutating that to `1 + offset` is green across the entire suite — 2636 passed, 5 skipped.** Nothing asserts that a connector's URLs honour `pagination.start`.

`Pagination.start` is `Field(default=1, ge=0)`, so **0 is a legal value** and a board that indexes its first page as 0 is expressible. Today such a connector would silently request pages 1, 2, 3… instead of 0, 1, 2… — the first page never fetched, and every offer on it invisible, with no error anywhere.

#338 closed the **body** half of exactly this (`build_list_requests`' `start + offset` is now a fail-open row of `page_placeholders_resolved_inconsistently`, via a probe drawing pages 5 and 6). The **URL** half is the louder one, because it affects every GET connector rather than only the POST ones.

## Why T109's gate structurally cannot reach it

`integral.page_placeholder`'s probe document uses a fixed `url_pattern` with no `{page}` in it, and `Probe` carries no `url_pattern` field — so no probe can observe the page number reaching the URL at all. The same inertness makes the `path_segment` probes bind the mode allowlist rather than exercise path substitution. Closing this means giving `Probe` a `url_pattern` and comparing built URLs, or a separate check.

`Pagination.start` also carries no docstring (`connectors.py:916` is a bare `Field`), and nothing in T109's `RULE` stated what it means until R6b was added there — which is why a probe's expected page numbers had to be read off `build_list_requests` rather than off a rule.

## Suggested gate

`page_numbers_not_counted_from_the_declared_start == 0`, over a probe table covering `query_param`, `path_segment` and `body_field` with `start` values of 0, 1 and something larger — named after the wrong outcome rather than a category, per T123. The denominator is a floor.

The task is done when mutating **either** `start + offset` — the URL one and the body one — is a red row of that metric, rather than one being caught by a neighbouring gate and the other by nothing.

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
