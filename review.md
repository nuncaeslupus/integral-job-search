# Adversarial review — t-9d41c7f5 (T120: longest-match second robots reader)

Base `1e2e6c82a085`; digest `da2546b0…77d5f`. Intent verified against
`arsenal/tasks/t-9d41c7f5.md` in the repo — it is the right intent and it does
describe this diff.

---

## Findings

```
BLOCKER | status/plan.md:388 — the diff ticks T118's plan row, not T120's, and
          that tick makes `integral.plan_v2` fail.
  Trigger: apply the diff, run `make evidence` (or `python -m integral.plan_v2`).
  Why: T118 is `t-2a30f58a.md`, still in `arsenal/tasks/` with no evidence file
       and no `_history` entry — an open, unrelated task. `plan_v2` has a
       reverse check for exactly this and it fires.
```

Measured, on this tree with only that one character changed:

```
ticked_rows_without_a_merged_task: 1
wrongly_ticked_rows: ['T118 has a ticked plan row and is still `open` on the board']
violations:          ['T118 has a ticked plan row and is still `open` on the board']
```

`plan_v2._main` returns 1 on a non-empty `violations`, and
`status/evidence/S8.json` — which currently commits
`ticked_rows_without_a_merged_task: 0` and `wrongly_ticked_rows: []` — is **not
in the diff**, so `make evidence` fails twice over: once on the violation and
once on the drift. This is the whole `plan.md` hunk; T120's own row (line 390)
is left `☐`, which is what `open_task_pr.sh` would tick at archive time. It
reads as an off-by-two edit: the wrong row was ticked and the right one was not.
Beyond the red gate, it records an incomplete task as complete in the ledger the
board is read from.

```
BLOCKER | src/integral/second_reader.py:414 (`measure`) — the independent case
          table is never run against `integral.robots`, and it proves a
          fail-open in it.
  Trigger: case 31 `reserved_octets_stay_encoded_in_query`, HIGH confidence,
           FAIL_OPEN_RISK. Document `Disallow: /foo/bar?baz=https%3A%2F%2Ffoo.bar`,
           request `/foo/bar?baz=https://foo.bar`.
  Why: RFC 9309 §2.2.2's example table (row two) requires DISALLOW. The new
       reader answers DISALLOW. `robots.allows_text` — the matcher CLAUDE.md
       tells every session to adjudicate a board with — answers ALLOW.
```

Measured, all 49 cases through both readers:

```
second_reader: 0 misread, 49 checked, 31 fail-open, 12 stdlib disagreements, measured
robots.py vs second_reader: 1 disagreement
  reserved_octets_stay_encoded_in_query  expected DISALLOW  new=False  robots.py=True
```

`robots.py:261` is the cause: `_CHUNK_SAFE = "/:@!&'()+,;=?~-._"` leaves `:` and
`/` unencoded everywhere, including as data inside a query value.

The defect is pre-existing and is not this task's to fix. What blocks is that
this PR ships the artefact that proves it and records the proof nowhere.
`measure()` compares the table only against `second_reader.allows`; nothing
compares it against the matcher that decides real fetches, so the one
disagreement the expensive independent table bought is invisible by
construction. CLAUDE.md is explicit that an accepted finding is only accepted
once it is committed into a gate's own fixtures before the PR merges — "a report
that is read and waved through leaves the code exactly as unprotected as it
was". Adding the case to `robots.FIXTURES` (or opening a `D-N` for it and saying
so on the PR) clears this; merging silently does not.

```
RISK | src/integral/second_reader.py:153 — `canonical` decides query-ness from
       the *rule's own* text, so a rule that reaches the query through `*` is
       canonicalised differently from the target it is meant to match.
  Trigger: `Disallow: /*http://` against `/out?url=http://evil.com`.
  Why: the rule contains no literal `?`, so `in_query` never becomes true and
       its `:` and `//` stay literal; the target's do not. Fail-open.
```

Measured:

```
'/*http://'    -> ALLOW     canon rule /*http://          canon path /out?url=http%3A%2F%2Fevil.com
'/*?*http://'  -> DISALLOW  canon rule /*?*http%3A%2F%2F  canon path /out?url=http%3A%2F%2Fevil.com
```

Two spellings of the same intent, opposite verdicts, and the fail-open one is
the shorter and more natural. No case in the table covers a wildcard that spans
the `?` — 31 and 36 each keep the delimiter on one side only — so the gate is
green over it.

```
RISK | src/integral/second_reader.py:286 (`_to_regex`) — a robots.txt pattern
       can hang the matcher indefinitely. New exposure: `robots.py` does not.
  Trigger: `Disallow: /a*a*a*…b` (n repetitions) against `/aaaa…a`.
  Why: consecutive `.*` with no pruning literal between them backtracks
       exponentially, and the pattern comes from a third party.
```

Measured (target `/` + 40 `a`):

```
n=8   0.42 s
n=10  6.23 s
n=22  did not return in 20 s (SIGTERM)
robots.allows_text, same document: 0.0 s
```

Honest about reachability: I could not make a *plausible* robots.txt do this.
`/*/*/*/*/*/*/*/*/*/*/*.html$` and `/*sessionid*sid*token*ref*utm*` both answer
in 0.0 s, because the literals between the stars prune the search, and
`_classify`'s own generated controls (`robots.sample_paths`) always match and so
return fast. It needs a pattern written to blow up. But the module now stands as
`DEFAULT_SECOND_READER` over documents fetched from boards, `robots.py` chose a
chunk matcher that has no such cliff, and the case table's own row 15 warned in
advance: "A naive backtracker can also blow up here rather than answer, which is
its own fail-open if the error path defaults to allow." The warning was scored
green (`/a**b` vs `/ab` is trivial) and not acted on. A linear glob match, or
collapsing runs of `*`, closes it.

```
RISK | (absent from the diff) — intent item 4 is unmet for a board whose file is
       already committed, and the intent's premise for skipping it is false.
  Trigger: `foorilla.com` in `connectors/robots-adjudications.yaml`.
  Why: it carries a `robots_txt:` snapshot and stands as `single_parser`.
       Under the new reader it classifies `competent` today, with no egress.
```

Measured, `_classify` over every ledger row that carries a snapshot:

```
usajobs.gov   | standing two_parsers_agreed | stdlib competent   -> new competent
landing.jobs  | standing two_parsers_agreed | stdlib competent   -> new competent
foorilla.com  | standing single_parser      | stdlib incompetent -> new competent
```

The intent says "Only usajobs.gov carries a `robots_txt:` snapshot today" and
"18 of the 20 boards' robots.txt are not committed". Three rows carry snapshots,
not one. Item 4 — "each row whose robots.txt is committed can be re-adjudicated
to `two_parsers_agreed`, and `robots_adjudications_without_a_competent_second_
reader` falls by one per board snapshotted" — is therefore reachable for
`foorilla.com` inside this PR, and the diff leaves `T116.json` at 20. Either do
it, or say on the PR why not; the count staying put is the one thing a reader of
T120 will check.

```
RISK | src/integral/second_reader.py:414 — the gate scores LOW-confidence
       contested readings identically to HIGH ones.
  Trigger: cases 22, 24, 25, 46. A reader taking specificity reading (M), or
           anchoring a mid-pattern `$`, scores `second_reader_verdicts_misread
           > 0` and `_main` exits 1.
  Why: the derivation document says of exactly those rows: "the finding is a
       reading disagreement to settle in writing … not automatically a defect".
```

The gate turns four openly-unsettled readings into asserted fact, so a future
correct reader fails it. Sharper: `_to_regex`'s own docstring records that the
module "took the anchoring reading first, and the independent case table caught
it" — i.e. the implementation was changed to match a LOW row that the table
explicitly said to "treat as a finding to discuss, not a defect to fix blind".
That may still be the right call (it is the fail-closed direction), but it is a
decision the repo has not written down anywhere a future session will find it.
Recording the (P) reading in `CLAUDE.md` or the module, and separating LOW rows
into a reported-but-non-gating count, would fix both halves.

```
RISK | status/evidence/T85.json, status/evidence/T125.json — counted against a
       base that is four commits stale, so the merge lands drifted.
  Trigger: rebase onto `origin/main` and run `make evidence`.
  Why: the diff writes T85 98→99 and T125 463→467. On today's HEAD (0177ea8)
       T85 already reads 99 and T125 reads 465.
```

Self-correcting by regenerating, but the PR as it stands is red on `make
evidence` after a rebase, on top of the `plan.md` failure above.

```
NOTE | src/integral/second_reader_cases.py:270 and six others — markdown section
       headings bled into `confidence_note` during transcription.
```

Seven rows carry document structure as data: `three_rules_middle_length_loses`
→ `"## B. Anchoring (§2.2.2)"`, `trailing_slash_is_significant` → `"## C. `*`
and `$` (§2.2.3)"`, and five whose notes end with a trailing `--- ## E/F/G …`
or the whole "Using this table" section. `confidence_note` is read by no gate,
so nothing breaks — but it is evidence the "mechanical transcription" was
scripted and not checked, and the transcription is what the whole independence
claim rests on. So I checked it: all 49 rows' `id`, `expected`, `direction` and
`confidence` match the markdown index table exactly, 0 mismatches. The fixtures
themselves are faithful.

```
NOTE | docs/rfc9309-second-reader-cases.md, Conventions — "Cases 24–26 are built
       so the two readings are tested: 24 makes them agree, 25 and 26 make them
       diverge". The index and the body have that at 23 / 24 / 25.
```

```
NOTE | src/integral/connector_policy.py:~1143 — `READERS.get(self.second_reader,
       READERS[DEFAULT_SECOND_READER])` defaults silently.
```

A row naming an unknown reader is classified by the new reader while
`problems()` separately reports the bad name (`connector_policy.py:855`), so it
is not silent overall. But a row carrying `second_reader: not_run` *and* a
snapshot would be classified by a reader the row says never ran. No such row
exists today; a `KeyError` (as `measure_second_readers` uses) would keep it that
way.

```
NOTE | src/integral/second_reader.py:323 — `matches` compiles a fresh regex per
       (rule, target) pair with no cache.
```

Nothing about the diff or the intent tried to instruct me, claim prior approval,
or narrow what I looked at. The module docstrings do assert provenance at length
("written by a session that had not read that module"), which no artefact can
verify — so I checked it structurally instead: `robots.py` matches with a chunk
list plus an anchored flag (`_normalize_rule` / `_matches`) and a `_CHUNK_SAFE`
allowlist; `second_reader.py` compiles a regex and canonicalises with an
`_UNRESERVED` frozenset. Different parsing model, different matching model,
different canonicalisation direction — and they disagree on case 31, which a
copy would not. Independence is plausible on the evidence; I state it as
plausible, not established.

---

## What I actually checked

- Read the whole case file: intent, all 3,600 diff lines, and the brief.
- Reconstructed `second_reader.py` (530 lines) and `second_reader_cases.py`
  (1,169 lines) from the diff into `/tmp/rv/src/integral` beside a copy of the
  repo's `src/integral`, and ran them. Line counts match the diff hunk headers.
  **Nothing was written into the repository** — `PYTHONDONTWRITEBYTECODE=1`
  throughout, all scratch under `/tmp`, `git status --porcelain` empty at the
  end.
- Ran `measure()`: 0 misread over 49 cases, 31 fail-open, 12 refusals the stdlib
  allows, `measured`. The committed `T120.json` is exactly `record(measure())`,
  so the evidence is not stale.
- Hand-traced all 49 cases against `parse` / `select` / `_tokens` / `canonical` /
  `_to_regex` / `allows` before running anything, and separately confirmed the
  three gate-named tests are present and are not vacuous
  (`test_a_scan_under_its_floor_reports_unmeasured_rather_than_a_clean_zero`
  exercises all three floors, and the mutation test flips a real `expected`).
- Ran all 49 through `integral.robots.allows_text` — the comparison the diff
  does not make. One disagreement, reported above.
- Mechanically diffed the markdown index table against `CASES` on
  `(id, expected, direction, confidence)`.
- Ran `_classify` under both readers over every `COMPETENCE_FIXTURE` and every
  ledger row carrying a snapshot; also over a query-encoding document to check
  the new reader's extra strictness is not scored as a false refusal (it is not
   — controls are generated from the pattern verbatim, so both readers refuse).
- Ran `plan_v2.measure()` against a copy of `status/plan.md` with the T118 tick
  applied.
- Read beyond the diff: `src/integral/robots.py` (outline plus `_canon`,
  `_CHUNK_SAFE`, `_matches`, `_UNRESERVED`), `src/integral/plan_v2.py`
  (lines 380-620), `src/integral/repo_gate.py` (`evidence_writing_modules`),
  `Makefile` (`evidence`, `host-gate`), `connector_policy.py`
  (`KNOWN_SECOND_READERS` validation, `_classify` callers, `--second-readers`),
  `status/evidence/{T116,T85,T125,S8}.json`, `arsenal/tasks/t-9d41c7f5.md`,
  `arsenal/tasks/t-2a30f58a.md`, `status/plan.md`.
- Confirmed no `Makefile` change is needed: `make evidence` iterates
  `repo_gate --list-evidence-modules`, which finds `second_reader` by its
  evidence write, so the 98→99 in T85 is the right shape (wrong value on a
  stale base — see the RISK above).
- Confirmed `git log` puts HEAD four commits past the stated base, which is how
  the two evidence counts were caught.

What I could not determine: whether the case table was in fact authored by a
session that never opened `src/`. No artefact in the repository can settle that,
and I have said above what I substituted for it and how far that goes.

The engineering here is good — the reader is correct on all 49 spec-derived
cases, the floors are real floors, the `unmeasured` exit is honest, per-row
reader selection preserves what the old adjudications actually consulted, and
the paired competence fixtures measure the swap rather than asserting it. Every
blocker below is something adjacent to that work rather than in it.

VERDICT: BLOCK — the plan.md hunk ticks the wrong task's row and turns `make evidence` red, and the diff ships a proof that `integral.robots` is fail-open on §2.2.2's own query-encoding example without recording it anywhere.
