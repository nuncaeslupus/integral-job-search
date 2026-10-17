---
id: t-22aea8d2
title: "T341: Nothing reads the candidate's mailbox for replies to applications they sent"
priority: 5
status: merged
---

Promoted from the candidate sessions of 2026-09-06..2026-10-16: a practice the assistant ran by hand (scratch scripts or profile conventions) that any candidate needs.

T334 covers job-alert emails at sourcing time. The other half recurred in about eight sessions: replies to sent applications (acknowledgement, rejection, interview invitation) and portal messages, read so the applications board stays true.

With a per-read permission (a shared browser may hold someone else's mailbox): find replies matching an application on record, propose the status change (through T340's command, the candidate confirms), and on a rejection ask whether its reason is informative and, if so, record it as a preference. Offers or new terms found in portal mail go to the T334 path, not into this one.

Suggested gate: `mailbox_reads_without_a_per_read_permission == 0`.

## Acceptance gate

```bash
uv run pytest tests/test_mailbox_replies.py -q && uv run python -m integral.mailbox_replies
```
