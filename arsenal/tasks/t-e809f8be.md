---
id: t-e809f8be
title: "T332: python.org answers gzip to a request that sent no Accept-Encoding"
priority: 5
requires: [human:gate]
---

Imported from issue #769

Raised by the second reader on #764 (T152), outside that diff; present on main.

python.org served `Content-Encoding: gzip` to a request carrying no `Accept-Encoding`, twice, for `/jobs/?page=1` and the bare `/jobs/` (not for `?page=2`). A reader that does not decode it parses zero adverts from page 1 and reports an empty board rather than an error.

Establish whether the repo's fetch path decodes an unrequested `Content-Encoding`, with a test over a recorded gzip body, and make an undecodable body a loud failure rather than zero adverts.

Suggested gate: `encoded_bodies_parsed_as_zero_adverts == 0`.

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
