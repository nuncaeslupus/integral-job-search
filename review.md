# Adversarial review — T120 (`t-9d41c7f5`), second reader written from RFC 9309

Base `1e2e6c82a085`, diff digest `d4a89fd6f70c…ff30`. The patch applies clean to that
commit; I reviewed every hunk of all twelve files, and I ran the change.

---

## Findings

```
BLOCKER | status/plan.md:388 — the diff ticks T118's plan row, and T118 is an open,
          unimplemented task. `make test` and `make evidence` both fail on it.
  Trigger: apply the diff to 1e2e6c82a085 and run `pytest tests/test_plan_v2.py` or
           `python -m integral.plan_v2`. Measured:
             ✗ T118 has a ticked plan row and is still `open` on the board
             "ticked_rows_without_a_merged_task": 1   (0 at base)
             exit 1  →  `make evidence` prints "GATE FAILED plan_v2" and stops
           Full suite on the patched tree: 2877 passed, 1 failed —
           tests/test_plan_v2.py::test_the_committed_plan_and_queue_agree.
  Why: `status/plan.md:198` defines ☑ as "merged". `arsenal/tasks/t-2a30f58a.md`
       (T118) is in `arsenal/tasks/`, not `_history/`; there is no
       `status/evidence/T118.json`, and `connector_array_paths_misresolved` — T118's
       metric — does not exist anywhere in `src/`, `tests/` or `status/`. The diff
       contains no array-indexing work either (`connectors.py`, `getmanfred_es/`
       and `tests/test_connectors.py` are untouched). This is a false completion
       claim in the ledger the board reads, and it is the *only* change this diff
       makes to `status/plan.md` — T120's own row is left ☐. Whatever the intent
       was, the row that needed touching was not this one.
```

```
BLOCKER | src/integral/second_reader_cases.py:~"reserved_octets_stay_encoded_in_query"
          — the new independent table proves `integral.robots`, the production
          permission check, is fail-open on §2.2.2's own example table, and the PR
          ships that finding silently.
  Trigger:
      robots.txt: "User-agent: *\nDisallow: /foo/bar?baz=https%3A%2F%2Ffoo.bar\n"
      target:     "/foo/bar?baz=https://foo.bar"
      integral.robots.allows_text(...)  -> True   (fetch admitted)
      integral.second_reader.allows(...) -> False  (refused)
      RFC 9309 §2.2.2 example table, row 2, as the case file's own HIGH-confidence
      row 31 states: DISALLOW.
  Why: `robots.py:261` puts `/` and `:` in `_CHUNK_SAFE`, so reserved octets used as
       *data* inside a query value are never encoded on the target side while the
       rule keeps them encoded — the two spellings can never meet, in the direction
       that admits a fetch the operator refused. I ran all 49 committed cases
       through `integral.robots`: it misreads exactly this one, and it is
       `FAIL_OPEN_RISK`/`HIGH`. T70's gate is unaware — `robots_verdicts_misread: 0`
       over 59 fixtures, none of which covers this row (`grep baz=https src/integral/robots.py`
       returns nothing).

       This is not a stray observation about a neighbouring module: it is exactly
       what CLAUDE.md's second-reader section says a second reading is *for*, and
       what it says must not happen to the result — "a report that is read and
       waved through leaves the code exactly as unprotected as it was". The case is
       committed, but only into a table measured against the *new* reader, so
       nothing anywhere turns red and nothing is reported. Merging as-is spends the
       whole value of the independent read.

       I am not asking this PR to fix `robots.py`. Clearing this needs one of:
       the case added to `robots.py`'s own fixture table (which will then be red
       and must be fixed or the task filed), or a queued task plus a note on the PR
       naming the input above. What must not happen is that it merges unrecorded.
```

```
RISK | src/integral/connector_policy.py (in `_snapshot_problems`) —
       `ask = READERS.get(self.second_reader, READERS[DEFAULT_SECOND_READER])`
       silently verifies a row against a reader that never ran.
  Trigger: any row whose `second_reader` is `not_run` (15 of the 22 live rows are
           `second_reader_never_run` today) that later gains a `robots_txt:`
           snapshot. Its standing is then adjudicated by `integral.second_reader`,
           a parser nobody consulted for that row.
  Why: the comment three lines above this call states the opposite invariant —
       "a row is verified against the reader it names, never against whichever one
       this module currently prefers" — and the fixture path enforces it fail-loud
       (`READERS[fixture.reader]`, a KeyError on an unknown name). The `.get`
       default is the same class of thing this task exists to remove: a check whose
       input silently stands in for one that was never taken. Today it is mostly
       unreachable (`problems()` already rejects a `single_parser` row naming
       second-reader refusals — I confirmed that by constructing one), which is why
       this is a RISK and not a blocker; make it `READERS[...]` for a named reader
       and skip the snapshot classification entirely for `not_run`.
```

```
RISK | status/evidence/T85.json, status/evidence/T125.json, status/plan.md — the
       committed counts are stale against current `main`, so this cannot merge green.
  Trigger: base is `1e2e6c82a085`; `main` is `f2633eac` (4 commits ahead). On main
           `T85.gate_modules_discovered` is already **100** and `T125.files_checked`
           already **467**. This diff sets them to 99 and 467 — a decrease and a
           no-op respectively, where the merged tree needs 100+1 and 467+4.
  Why: `ci.yml` measures `refs/pull/N/merge`, so CI sees the merged tree, and
       `make evidence` fails on drift. `status/plan.md`, `T85.json` and `T125.json`
       were all changed by #400/#404 on main and will conflict. Rebase onto main and
       re-run `make evidence` before opening the PR; do not hand-edit the numbers.
```

```
RISK | src/integral/second_reader.py (`matches`, middle-run loop) — the declared
       gate metric is blind to the interior-wildcard branch.
  Trigger: change `found = target.find(segment, index)` to
           `target.find(segment, index + 1)` (an interior `*` requiring at least one
           character). `second_reader_verdicts_misread` stays **0** and
           `gate_status` stays `measured`, over all 49 cases.
  Why: I mutation-tested fifteen defects against the table — flipped tie-break,
       trailing `*` requiring content, `$` always anchoring, decoding every escape,
       first-matching-group-only, octets excluding metacharacters, blank line
       closing a group, prefix token matching, query stripped before matching, empty
       pattern matching everything, orphan rules adopted, comments kept,
       case-sensitive tokens, `*` group unioned with the named group. Fourteen are
       caught by the table (misread 1–3). This one survives it, and is caught only
       by the four implementer-derived rows in `tests/test_second_reader.py:3253-3272`
       — which are honestly labelled as such, and which the task's gate command block
       does run, so the gate as *invoked* holds. But `second_reader_verdicts_misread`
       is what `status/evidence/T120.json` commits and what `verify-gates` adjudicates
       forever after, and that number alone would pass this reader with the defect in
       it. The four cases belong somewhere the denominator counts them.
```

```
NOTE | src/integral/second_reader.py:1544 (`parse`) — a UTF-8 BOM disables the whole
       file: "﻿User-agent" is not the `user-agent` field, so no group opens, every
       rule is dropped, and every path is allowed. `integral.robots` does the same,
       so this diff introduces no new asymmetry and the ledger stays conservative
       (`_classify` finds no controls and returns `no_control_possible`, which cannot
       carry an agreement). Worth knowing now that this reader is the default.
```

```
NOTE | docs/rfc9309-second-reader-cases.md:246 — "Cases 24–26 are built so the two
       readings are tested" is off by one; the divergence rows are 23, 24 and 25.
       connectors/robots-adjudications.yaml (T120 block) says "the two where it must
       NOT improve on the stdlib"; there are three such fixtures
       (`..._bare_disallow`, `..._equivalent_rules`, `..._another_agents_group`).
```

```
NOTE | status/plan.md — T120's own row is still ☐. Per D-27 the archive commit that
       `open_task_pr.sh` writes must tick it in the same diff, or
       `merged_tasks_with_an_unticked_plan_row` turns `make evidence` red.
```

```
NOTE | No injection attempt in either data block. The intent document and the diff
       both contain prose addressed at a reader ("this is the reading under which the
       operator gets what they wrote", "Treat a matcher disagreeing here as a finding
       to discuss, not a defect to fix blind"), but none of it instructs the reviewer
       to skip, narrow or clear anything, and no line imitates the packet's markers.
       The intent does try to fence scope ("Snapshotting the remaining 18 needs egress
       and is not part of this task"), which is a legitimate scope statement and
       matches what the diff does.
```

---

## What holds up, and what I did to check it

**The reader is correct on everything I could test.** Fourteen of fifteen seeded
defects are caught by the committed table, and the fifteenth by the test file the
gate block runs. I re-derived the verdicts for all 49 rows by hand against the
recalled §2.2.1/§2.2.2/§2.2.3 rules before running anything, and found no row whose
`expected` I disagree with; the three `LOW` rows (mid-pattern `$`, the two
specificity readings, the blank-line group split) each state which reading they take
and why, and the reading taken is the fail-closed one in each case. The
non-backtracking match is genuinely linear — the fourteen-wildcard pattern the
docstring claims killed a regex version returns in under a millisecond here.

**The table is a faithful transcription of the document.** I parsed
`docs/rfc9309-second-reader-cases.md` and `src/integral/second_reader_cases.py` and
compared all 49 rows on id, order, robots.txt body, agent, path, `expected`,
`direction` and `section`: zero mismatches. The direction counts the document claims
(31/17/1) are the counts it carries. That matters because an `expected` quietly
edited to match the code is exactly how this kind of table stops being independent.

**The plumbing does what its comments say.** Every `_classify` call site in `src/`
and `tests/` now passes an explicit reader (I grepped; none were left on the
default), so no existing check silently changed parsers. `_CompetenceFixture.reader`
defaults to `urllib.robotparser`, so the nine T116 fixtures keep the reader their
`why` describes, and the seven new ones name the replacement — including three that
assert it must *not* manufacture a refusal (bare `Disallow:`, equivalent rules, a
foreign agent's group), which is the right shape: competence measured, not assumed.

**Measured, on the patched tree, at base:**

* `pytest` — 2877 passed, 6 skipped, **1 failed** (`test_the_committed_plan_and_queue_agree`, the T118 tick).
* `ruff format --check` — 467 files already formatted · `ruff check` — passed · `mypy` — no issues in 214 source files.
* every module from `repo_gate --list-evidence-modules` (99, including `second_reader`) regenerated: no drift except `plan_v2`, which **fails**.
* the task's own gate block: all three named tests collect; `pytest tests/test_second_reader.py tests/test_connector_policy.py` → 68 passed; `python -m integral.connector_policy --second-readers` → exit 0, `misrepresenting_their_standing: 0`, `competence_fixtures_checked: 16`.
* `python -m integral.second_reader` → exit 0, `misread 0`, `gate_status measured`; the committed `T120.json` matches what it measures.

**Files I opened beyond the diff:** `src/integral/robots.py` (`_canon`, `_CHUNK_SAFE`,
`_normalize_rule`, its fixture table), `src/integral/connector_policy.py`
(`_classify`, `problems`, `_snapshot_problems`, `measure_second_readers`,
`MALFORMED_ADJUDICATIONS`), `src/integral/plan_v2.py`'s output, `Makefile`
(`evidence`, `host-gate`), `status/plan.md`'s legend and T118/T120 rows,
`arsenal/tasks/t-2a30f58a.md`, `arsenal/tasks/_history/t-4c88b302.md`, and CLAUDE.md's
second-reader and evidence sections. All execution was in a throwaway clone under
`/tmp`; nothing was written into this repository except this reply.

**What I could not determine:** that the case table was in fact written by a session
that had not read `src/integral/robots.py`. Nothing in the tree can establish that,
and I am not treating it as a finding — but it is the load-bearing claim of the whole
task, and the only external evidence for it is that the table caught a defect in the
implementation (`dollar_in_middle_of_pattern`, per `_segments`' docstring) and that
its 49 rows do not read as a description of what `second_reader.py` does. Both are
consistent with the claim; neither proves it.

VERDICT: BLOCK — the diff ticks an unrelated open task's plan row, which fails `make test` and `make evidence` outright, and it ships a HIGH-confidence fail-open finding against the production matcher (`integral.robots` allows `/foo/bar?baz=https://foo.bar` under `Disallow: /foo/bar?baz=https%3A%2F%2Ffoo.bar`) with nothing anywhere recording it.
