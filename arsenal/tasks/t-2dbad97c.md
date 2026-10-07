---
id: t-2dbad97c
title: "T331: A paginated list fetch that 404s past the last page: end of pages or failed fetch?"
priority: 5
requires: [human:gate]
---

Imported from issue #768

Raised by the second reader on #764 (T152), outside that diff.

`https://www.python.org/jobs/?page=3` answers 404 today, and the board holds 26 adverts at 25 per page, so `?page=2` will answer 404 as soon as it drops to 25. `pythonorg_en` now paginates with `max_pages: 2`.

Nothing in the repo establishes whether the list fetcher treats a 404 on a **non-first** page as "no more pages" (page 1's adverts kept) or as a failed fetch (the whole board's result lost or reported as an error). Establish it with a test against the engine's own fetch path, and fix it if page 1 is lost.

Suggested gate: `paginated_fetches_that_lose_page_one_to_a_404_on_a_later_page == 0`.

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
