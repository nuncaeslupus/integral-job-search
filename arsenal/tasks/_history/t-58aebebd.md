---
id: t-58aebebd
title: "T238: one failed read of robots.txt drops the whole board for the round, with no retry"
label: "T238: robots read retried once"
priority: 10
status: merged
---

Filed from a candidate session (test-mode 658fcce2).

Measured 2026-10-02: `Robots().allows('https://www.trabajos.com/ofertas-empleo/python')` raised `RobotsError: … <urlopen error [Errno 113] No route to host>` in the afternoon; the same board was read and returned 13 live offers four hours earlier. `sourcing._one_board` turns that into `skipped: robots.txt could not be read, so the path is not permitted` — the right direction (fail-closed), and the wrong granularity: a transient network error costs the board's whole round, and `_allowed` (line 986) answers `False` for every advert URL of that host, so the liveness of its stored offers cannot be checked either.

Retry a network-level failure (not an HTTP answer) a bounded number of times before concluding, and keep the skip message distinguishing 'unreachable' from 'refused' so the candidate is told which it was. Never read as permission.


## Acceptance gate

```bash
uv run pytest tests/test_robots_retry.py -q
```
