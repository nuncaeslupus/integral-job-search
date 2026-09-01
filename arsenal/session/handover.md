# Session handover — 2026-09-01 ~18:25 UTC, interactive, laptop

Board: **119 merged of 144** on `main` (`355b1b7`), 17 open, 5 claimed with a
PR open. `make host-gate` exit 0 on every branch below.

Nothing identifying the candidate is recorded here, and nothing should be. That
is the rule rather than discretion: identity, history and stated constraints
live in the local profile store, and a document in a public repository keeps
whatever it says forever.

## What landed

| Task | PR | What it fixed |
|---|---|---|
| T97 | #282 | Step 1 could not read the CV and carried on. An import log, a partial-read field, and coverage held open until the failure is said out loud |
| T73 | #283 | A 429 or a block page read as parser rot, so our own rate limiting retired working boards. Third verdict `inconclusive` |
| T90 | #285 | A stated exclusion reached only the ranking, so a demoted advert still arrived. It reaches the query now, and accumulates |
| T100 | #284 | `T55.files_scanned` committed as an exact value; the archive moved it, so `open_task_pr.sh` could not open a PR without hand surgery. It is a floor now |

## Open, green, waiting on review

`merge-policy = after-review`, and **CodeRabbit has produced nothing since
16:16 UTC** — no review and no rate-limit comment, on four PRs, including after
an explicit `@coderabbitai review`. `references/pr-review-loop.md` says treat
that as the vendor's clock, check back slowly, and never merge past the policy.
None of these has had a first review, so none has cleared the bar.

| PR | Task | Note |
|---|---|---|
| #286 | T83 — attribution register | `docs/METHODS.md` §2.9, fourteen rows, README Acknowledgements |
| #287 | T96 — monotone dimensions | proved T100: opened with **no workaround at all** |
| #289 | T99 — policy refusals | **needs the owner's decision, not a review** — see below |
| #290 | T95 — chunking and register | changes two `test_presentation.py` tests deliberately |

## #289 is not waiting on a bot

T99's whole diagnosis is that a policy removing boards from a candidate's reach
was written by the implementing session on its own judgement and never put to
the owner. Merging it on `after-review` would repeat that exactly.

The owner's position is on record, quoted in the task file, and
`ruled-out.yaml`'s **own header** already said the same thing two hundred lines
above the entry contradicting it — *"those bans target bulk training crawls; a
connector is one candidate's search."* Nothing could see the contradiction
because the header also said "Nothing reads this file", which was true until
this PR.

Applied as: the remoteok entry narrowed from **access** to **volume**, recording
`decided_by: owner`, `decided_on: 2026-08-31`, and the owner's words. It builds
no connector and is not a finding that remoteok should be read. **If the owner
reads it the other way, one commit inverts it** — the gate measures the record,
not the verdict.

## Two findings filed rather than worked around

- **#274 (closed by #284)** carries the workaround and its retirement, with
  three data points: #282, #283 and #286 needed the `git mv` dance; #287 did
  not.
- **#288 is open and unclaimed.** Every open task PR goes stale on `D12.json`
  the moment any other task PR merges — CI checks the *merge* ref and D12 counts
  gate blocks. It is quadratic in open PRs, restarts the review bot each time,
  and cost more session time today than any single review finding. Four possible
  shapes are listed; none is picked, because the choice is about what D12's
  drift check is for.

## Review findings this session — seven, six accepted

Every accepted case was committed as a fixture, never answered only in a
comment. Denominators rose: 57→60 tests on T73, 13→16 on T90, 23→24 on T100.

Two are worth carrying forward because both are the reviewed task's own subject
turned on itself:

- **T100's `_main` accepted zero sensitive keys without asking whether anything
  had been compared** — a denominator nobody read, inside the fix for a
  denominator nobody asserted.
- **T90's probe counted one presentation twice**, clearing its own floor with
  the duplicate, three lines below the comment forbidding exactly that.

The one rejected finding claimed `D12.gates_declaring_status_key` disagreed with
its own array; it was counted from the diff hunk rather than the file. 23 and 23.

## Known holes, named on the record

- **T73's block-page markers are English-only** and this library is ES/CA-facing.
  A Spanish challenge page is a live fail-open. Recorded in `METHODS.md` §2.9's
  limits column, not just in a PR comment.
- **#264** (getmanfred connector) and **#260** (four JSON packages) are still
  draft and still blocked on an adversarial audit by a session other than the
  implementer. This session implemented neither, but has now implemented enough
  of the surrounding library that a fresh session is the cleaner reader.

## Still undelivered to the candidate, in Spanish

The round-4 report (US vs EUR salary comparison; the Deel Analytics Engineer
role), and the Manfred finding: *Senior Python Engineer*, Law Business Research
(Centellic), €50,000–60,000, 100% remote, Spain, AI-first architecture.

## Environment notes that cost time to rediscover

- `open_task_pr.sh` needs **no workaround** since T100. If a task PR fails on
  evidence drift, the finding is that something *new* is archive-sensitive, and
  `status/evidence/T100.json` names it.
- A task file with no ```gate``` block needs one before its PR, and the key must
  already exist in the evidence file.
- An acceptance ` ```bash ` block that does not name the module writing the
  metric regenerates nothing. Three of this session's five tasks shipped with
  that line missing from the task file; each was corrected in its own PR.
