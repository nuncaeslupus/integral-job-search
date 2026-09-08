# Adversarial review — T120 (`t-9d41c7f5`), v3

## Findings

```
BLOCKER | tests/test_connector_policy.py:34 — the diff in this case file is incomplete, and what it does contain fails `make lint` and 4 tests
  Trigger: apply the packet's diff to f2633eac and run the acceptance gate's own
           command block: `uv run --extra dev pytest tests/test_second_reader.py
           tests/test_connector_policy.py -q`.
  Why: The packet's own `--stat` says `tests/test_connector_policy.py | 124`
       changed lines. The diff body carries 27 (+17 -10). Every other file in the
       packet matches its stat exactly, so ~97 lines of that file's change were
       not given to me. The consequence is visible: the diff adds
       `from integral import robots, second_reader` at :34 and never uses the
       import, so `make lint` stops on `F401 integral.second_reader imported but
       unused`; and `_classify`'s default reader is changed from the stdlib to
       `integral.second_reader` while three call sites (:642, :704, :729) are
       left without a reader argument. Measured on the applied tree:
         4 failed, 43 passed
         test_a_file_that_refuses_a_path_is_never_told_no_control_is_possible
           assert 'competent' == 'incompetent'
         test_a_second_reader_that_allows_one_refused_path_cannot_carry_an_agreement
           assert 'competent' == 'partially_competent'
         test_the_honest_count_of_incompetent_second_readers_is_reported_under_its_own_name
           assert 19 == 20
         test_single_parser_names_which_of_its_two_findings_each_row_is
           assert 3 == 4
       Those last two are the hard-coded literals that must move because
       foorilla.com is re-adjudicated. I cannot tell whether the real change
       updates them correctly, because those lines are the ones missing. Per the
       brief, a diff I could not fully read is a BLOCK on its own; and the diff
       as presented does not pass its own gate.
```

```
BLOCKER | src/integral/second_reader.py:679-705 — the two exit codes the acceptance gate names are asserted nowhere; gutting both keeps the suite green
  Trigger: in `_main`, replace `return 1` (misread) with `return 0` and `return 3`
           (under floor) with `return 0`. Then
           `uv run --extra dev pytest tests/test_second_reader.py -q`.
  Why: 23 passed. The task's gate block states the contract explicitly — "The run
       must **return 1** on any misread case and **return 3** — `unmeasured`, not
       a pass — when the fixture table is under its floor, so a zero over an empty
       table is never a pass." `_main` is called exactly once in the tests
       (`assert sr._main([str(target)]) == 0`, the healthy path).
       `test_a_misread_case_returns_one_rather_than_the_three_evidence_records` is
       named for the exit code and asserts
       `sr.measure(mutated)["second_reader_verdicts_misread"] == 1` — the misread
       *count*, not the exit status — and `_main` takes no case table, so it is
       never run over a misreading one.
       `test_a_scan_under_its_floor_reports_unmeasured_rather_than_a_clean_zero`
       likewise checks `measure()["gate_status"]` and never `_main`. The exit
       status is what `make evidence` reads: a 3 is recorded and the run
       continues, a 1 stops it. So the one mechanism that makes a misread stop the
       evidence run, and the one that stops an under-floor table reading as a
       pass, are both untested and both silently removable. That is the shape
       CLAUDE.md's "a green gate is necessary and is not sufficient" names, on
       this task's own stated acceptance condition.
```

```
BLOCKER | src/integral/second_reader.py:400-428 (`spellings`) — the multi-spelling match is fail-open when the widened rule is an `Allow`, and the docstring asserts the opposite
  Trigger:
      User-agent: *
      Disallow: /jobs
      Allow: /*/apply
    target `/jobs?next=%2Fapply` →  `sr.allows(...)` returns **True**.
    (Second witness, same shape: `Disallow: /x` + `Allow: /*http://` against
    `/x?u=http%3A%2F%2Fy` → True. Removing the `Allow` line returns False in
    both cases, so the widening is what flips it.)
  Why: `spellings()` offers the target encoded, as written, and query-decoded, and
       `allows()` matches a rule against *any* of the three. Under this module's
       own canonicalisation (§2.2.2's example table: reserved octets used as data
       in a query are percent-encoded), the path to match is
       `/jobs?next=%2Fapply`, `Allow: /*/apply` does not match it, and the only
       matching rule is `Disallow: /jobs` — DISALLOW. The reader answers ALLOW,
       because the decoded spelling lets the 8-octet `Allow` outrank the 5-octet
       `Disallow`. The docstring's justification for the widening is
       "Comparing against more spellings can only make more rules apply — it never
       makes a `Disallow` stop matching — which is the direction to be wrong in":
       making an `Allow` apply is exactly how a `Disallow` stops deciding, so the
       safety argument in the comment is false, not merely incomplete. This was
       added in response to an earlier review round to close a fail-open, and it
       reopens one on the other side. No case in the table has a wildcard spanning
       a `?` on the allow side, so the gate is green over it — the same blind spot
       the docstring credits the previous review with finding.
       The narrow fix that keeps the stated invariant true is to widen only
       `disallow` patterns to the extra spellings.
```

```
RISK | src/integral/second_reader.py:199-248 (`parse`) — a UTF-8 BOM makes the reader allow every path on a file that disallows everything
  Trigger: sr.allows("﻿User-agent: *\nDisallow: /\n", "integral-job-search/0.1", "/anything") → True
  Why: `_strip_comment(...).strip()` does not remove U+FEFF, so the first field
       reads as `﻿user-agent`, falls through to the "unknown field" branch,
       and every rule under it is dropped for having no group above it — the
       whole document parses to zero groups and §2.2.2's fallback allows. Real
       robots.txt files are served with BOMs. This is not a regression (measured:
       `integral.robots` and `urllib.robotparser` are both True here too), so it
       will never show as a reader disagreement, and the competence check cannot
       see it. But this module is the one being certified as the RFC-competent
       reader, its 49-case table has no BOM row, and the failure is fail-open on
       the most restrictive file there is. I could not check RFC 9309's exact
       wording on BOM handling — egress is 403 here — so I am flagging the
       behaviour rather than asserting the citation.
```

```
RISK | connectors/robots-adjudications.yaml:17-44 — the header added by this diff states the opposite of what the same diff does
  Trigger: read the new header paragraph against the foorilla.com row 200 lines below.
  Why: "So the standings below are unchanged, and the honest count stays what
       T116 committed." In the same diff, foorilla.com moves `single_parser` →
       `two_parsers_agreed` and `status/evidence/T116.json` moves
       `robots_adjudications_without_a_competent_second_reader` 20 → 19. This is
       a ledger whose entire purpose is that its prose and its rows say the same
       thing; a reader who trusts the header will mis-report the board's state.
```

```
NOTE | status/plan.md:390 — the tree as presented fails `make evidence`
  `plan_v2` reports "T120 has a ticked plan row and is still `open` on the
  board": the row is ticked ☑ while `arsenal/tasks/t-9d41c7f5.md` is still in
  the queue. That resolves the moment `open_task_pr.sh` archives the task file in
  the same commit (I simulated the archive and the whole evidence run then went
  green with no drift outside S8, which returns to 0). Recording it because the
  gate is red on the tree that was handed to me, so no green `make host-gate` can
  have been taken over exactly this state.
```

```
NOTE | intent document — one stale premise, which does not change the verdict
  "Only usajobs.gov carries a `robots_txt:` snapshot today" — three rows do
  (usajobs.gov, landing.jobs, foorilla.com). The diff's own work depends on
  foorilla's snapshot existing, so the diff is right and the intent is stale.
```

## What I actually checked

I reconstructed the change outside the repository (nothing was written into the
working tree): `git archive f2633eac` into a scratch directory, then
`git apply --recount` of the packet's diff — plain `git apply` refuses it, which
is the first symptom of the truncation above. In that tree I ran the acceptance
gate's own command block, `make lint`, `make evidence` (full, ~100 gate modules,
before and after simulating the task-file archive), and `python -m
integral.connector_policy --second-readers`.

Beyond the diff I opened `src/integral/robots.py`'s entry point (via
`_repo_matcher_allows`), `connectors/robots-adjudications.yaml` in full for the
three rows carrying a `robots_txt:` snapshot, `status/evidence/S8.json` and
`T116.json` at the base commit, and grepped `_classify(` across the patched test
file to find the three call sites the diff leaves without a reader argument.

Things I verified as sound, so they are not findings:

- The foorilla.com re-adjudication is real. `_classify` with
  `integral.second_reader` tries 22 controls, the RFC matcher refuses all 22, the
  new reader refuses all 22 → `competent`; both paths named in
  `second_reader_refused` are refused by both readers, and both `allowed` paths
  are allowed by both. The standing is earned, not asserted.
- `measure()` over the committed table: `second_reader_verdicts_misread: 0` on 49
  cases, 31 fail-open, 12 paths refused that `urllib.robotparser` allows (floors
  30/15/8), `gate_status: measured`. `record()` does drop the three counts of the
  day, and `test_the_committed_evidence_matches_what_the_reader_measures_now`
  binds the committed file to a live measurement.
- The matcher itself is a linear segment walk with no backtracking; I could not
  make it hang. The `*`-as-empty, `$`-as-trailing-anchor, tie-to-allow,
  longest-*matching*-rule, group-combining and no-fallback-to-`*`-when-named
  behaviours all answer as the case table's derivations require, including the
  two cases (`Disallow:` bare, equivalent allow/disallow) where the new reader
  must *not* manufacture a refusal.
- `T85.json` 100 → 101 and `T125.json` 467 → 471 are consistent with exactly the
  four new files; `second_reader` does appear in the evidence run as its own gate
  module, so the new gate is not orphaned.
- Neither the intent document nor the diff contains anything addressed to a
  reviewer — no "approved", no instruction to skip a check. I grepped for it.

Things I could not determine: whether the case table was genuinely derived by a
session that had not read `src/` (an unverifiable provenance claim, though the
`_segments` docstring recording that the table *caught* this module's first
reading of a mid-pattern `$` is real evidence for it); the exact RFC 9309 text,
since egress is 403 here and every citation in the change is RECOLLECTED; and,
most importantly, the ~97 lines of `tests/test_connector_policy.py` that the
case file does not contain.

VERDICT: BLOCK — the case file's diff is incomplete for `tests/test_connector_policy.py` (27 lines shown against its own stat's 124) and what was given fails `make lint` and four tests; separately, the exit codes 1 and 3 that the acceptance gate names are asserted by no test, and `spellings()` introduces a demonstrable fail-open in which a wildcard `Allow` reaching an encoded query outranks a matching `Disallow`.
